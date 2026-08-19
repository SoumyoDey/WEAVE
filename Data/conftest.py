"""Pytest setup for the backend tests.

flask_api opens a real PostgreSQL connection pool at import time, so we replace
psycopg2's pool with a stub *before* any test module imports flask_api. The
metric tests drive the pure computation paths with hand-built inputs (a fake
cursor or a monkeypatched fetch helper), so no real database is ever touched and
the suite runs anywhere.

`test_db_endpoints.py` is the exception: it runs the endpoints against a real
throwaway database built by `fixture_db.py`, because a fake cursor cannot
exercise SQL. Those tests skip themselves when PostgreSQL is not reachable, so
the promise above still holds — the suite runs anywhere, it just verifies more
where a server exists. Set WEAVE_SKIP_DB_TESTS=1 to skip them explicitly.
"""
from unittest.mock import MagicMock

import psycopg2.pool
import pytest

# The real class, kept before the stub goes in: the fixture-database tests need
# a working pool, and by the time they run the name below is a MagicMock.
REAL_THREADED_POOL = psycopg2.pool.ThreadedConnectionPool

# Applied at conftest import — pytest loads conftest.py before collecting test
# modules, so this is in place by the time `import flask_api` runs.
psycopg2.pool.ThreadedConnectionPool = MagicMock()


# ── Fixture database (real PostgreSQL) ────────────────────────────────────────

@pytest.fixture(scope='session')
def fixture_db():
    """A freshly built, seeded throwaway database. Skips if there is no server."""
    import fixture_db as fx

    reason = fx.unavailable_reason()
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
def db_client(fixture_pool, _clear_plot_cache, monkeypatch):
    """A Flask test client whose queries reach the fixture database."""
    import flask_api as api

    monkeypatch.setattr(api, 'connection_pool', fixture_pool)
    # Resolved once per process in the real app; a test must not inherit the
    # count another test's data implied.
    api._ENSEMBLE_SIZE_CACHE.clear()
    api.app.config.update(TESTING=True)
    return api.app.test_client()
