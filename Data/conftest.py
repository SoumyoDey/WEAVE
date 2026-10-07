"""Pytest setup for the backend tests.

flask_api opens a real PostgreSQL connection pool at import time, so we replace
psycopg2's pool with a stub *before* any test module imports flask_api. The
metric tests drive the pure computation paths with hand-built inputs (a fake
cursor or a monkeypatched fetch helper), so no real database is ever touched and
the suite runs anywhere.

`test_db_endpoints.py`, `test_regrid_idempotency.py` and `test_run_registry.py`
are the exception: they run against a real throwaway database built by
`fixture_db.py`, because a fake cursor cannot exercise SQL. Those tests skip
themselves when PostgreSQL is not reachable, so the promise above still holds —
the suite runs anywhere, it just verifies more where a server exists. Set
WEAVE_SKIP_DB_TESTS=1 to skip them explicitly, or WEAVE_REQUIRE_DB_TESTS=1
(as CI does) to turn that skip into a failure.
"""
import os
from unittest.mock import MagicMock

import psycopg2.pool
import pytest

# The real class, kept before the stub goes in: the fixture-database tests need
# a working pool, and by the time they run the name below is a MagicMock.
REAL_THREADED_POOL = psycopg2.pool.ThreadedConnectionPool

# Applied at conftest import — pytest loads conftest.py before collecting test
# modules, so this is in place by the time `import flask_api` runs.
psycopg2.pool.ThreadedConnectionPool = MagicMock()


# ── Caching off by default ─────────────────────────────────────────────────────
# The metric endpoints cache deterministic results in a FileSystemCache that
# survives a restart, and the key cannot distinguish one test's fake database
# from another's: two tests that issue the same request shape against different
# seeded data would otherwise get the first one's answer. That is not a flaw in
# the cache — in production there is one database — but it makes tests share
# state through the filesystem, which is exactly the kind of coupling that makes
# a suite pass in one order and fail in another.
#
# So the cache is disabled for the whole suite. `_cache_get`/`_cache_set` are
# already no-ops when `cache is None`, so every endpoint runs its real query.
# The cache's own behaviour is tested explicitly in test_metric_cache.py rather
# than incidentally here, and the one test that needs a hit monkeypatches
# `_cache_get` directly.
@pytest.fixture(autouse=True)
def _no_metric_cache(monkeypatch):
    import flask_api
    monkeypatch.setattr(flask_api, 'cache', None)


# ── Fixture database (real PostgreSQL) ────────────────────────────────────────

@pytest.fixture(scope='session')
def fixture_db():
    """A freshly built, seeded throwaway database. Skips if there is no server.

    Unless `WEAVE_REQUIRE_DB_TESTS` is set, in which case it **fails** instead.
    Where a database is expected to exist, a skip is the wrong answer: it
    shrinks the run rather than failing it, and the difference is invisible in a
    green tick. The CI workflow sets it for exactly that reason, and already
    asserts separately that the service container answers.

    That guard existed in the workflow and not in the suite, which is how the
    `test_run_registry.py` database tests skipped on every run the repository
    has ever had — the workflow proved PostgreSQL was up, and nothing proved the
    tests had reached it. Setting the variable here covers every module that
    builds on this fixture at once.
    """
    import fixture_db as fx

    reason = fx.unavailable_reason()
    if reason and os.environ.get('WEAVE_REQUIRE_DB_TESTS'):
        pytest.fail(f'WEAVE_REQUIRE_DB_TESTS is set but the fixture database '
                    f'is unavailable: {reason}')
    if reason:
        pytest.skip(f'fixture database unavailable: {reason}')
    fx.build()
    yield fx
    fx.drop_database()


@pytest.fixture(scope='session')
def fixture_pool(fixture_db):
    """A real connection pool onto the fixture database."""
    pool = REAL_THREADED_POOL(1, 4, **fixture_db.db_config())
    yield pool
    pool.closeall()


@pytest.fixture(scope='session')
def _clear_plot_cache():
    """Plot responses are cached by a hash of the request body, which does not
    change when the renderer does — so a stale entry from an earlier session
    could hide a rendering regression. Clear once, not per test, so the
    cache-hit path stays testable."""
    import flask_api as api
    if api.cache is not None:
        with api.app.app_context():
            api.cache.clear()


@pytest.fixture
def db_cursor(db_client):
    """A real `RealDictCursor` on the fixture database.

    For the helpers below the endpoints — `_ensemble_size` and friends — which
    take a cursor rather than a request, and whose defects are therefore
    invisible to a test that goes through the client. Depends on `db_client` so
    the pool is already pointed at the fixture.
    """
    import flask_api as api
    from psycopg2.extras import RealDictCursor

    conn = api.get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        yield cursor
    finally:
        cursor.close()
        api.return_db_connection(conn)


@pytest.fixture
def db_client(fixture_pool, _clear_plot_cache, monkeypatch):
    """A Flask test client whose queries reach the fixture database."""
    import flask_api as api

    monkeypatch.setattr(api, 'connection_pool', fixture_pool)
    # Resolved once per process in the real app; a test must not inherit the
    # count another test's data implied.
    api._ENSEMBLE_SIZE_CACHE.clear()
    api.app.config.update(TESTING=True)
    return api.app.test_client()


# ── Fake database ─────────────────────────────────────────────────────────────
class RoutedCursor:
    """Stands in for a psycopg2 RealDictCursor.

    `routes` maps a substring of the SQL to either a list of row dicts or a
    callable taking the bound params and returning one. The first matching
    route wins; an unmatched query yields no rows, which is what an endpoint
    would see for a region with no data.
    """

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.executed = []
        self._rows = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))
        for fragment, rows in self.routes.items():
            if fragment in " ".join(sql.split()):
                self._rows = rows(params) if callable(rows) else list(rows)
                return
        self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, *a, **kw):
        return self._cursor

    def close(self):
        pass


@pytest.fixture
def client():
    # Imported here, not at module scope: flask_api opens a pool the moment it is
    # imported, and the stub above has to be in place first.
    import flask_api as api
    api.app.config.update(TESTING=True)
    return api.app.test_client()


@pytest.fixture
def prod_client():
    """A client configured the way production is.

    `TESTING=True` sets PROPAGATE_EXCEPTIONS, so an exception escaping a view is
    re-raised into the test instead of reaching Flask's 500 handler. That is
    useful for most tests and wrong for the ones that are *about* the handler:
    every endpoint calls get_db_connection() before its own try block, so a dead
    pool is caught by Flask, not by the view. Testing that under TESTING=True
    would assert a behaviour production does not have.
    """
    import flask_api as api
    api.app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
    try:
        yield api.app.test_client()
    finally:
        api.app.config.update(PROPAGATE_EXCEPTIONS=None)


@pytest.fixture
def fake_db(monkeypatch):
    """Point the endpoints at a RoutedCursor instead of the connection pool."""
    import flask_api as api
    def _install(routes=None):
        cur = RoutedCursor(routes)
        monkeypatch.setattr(api, "get_db_connection", lambda: _FakeConn(cur))
        monkeypatch.setattr(api, "return_db_connection", lambda conn: None)
        # A member count is a registry lookup these routes do not describe, so
        # it is stubbed rather than routed. `*a` because callers that know the
        # variable and the run pass them (§50) and a stub that pins today's
        # arity fails the next caller for a reason that has nothing to do with
        # what it is testing.
        monkeypatch.setattr(api, "_ensemble_size", lambda cursor, model, *a, **k: 50)
        return cur
    return _install
