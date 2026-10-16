"""`flask_api` must import in a fresh interpreter, which pytest cannot check.

**This file exists because a commit reached `main` that stopped the server
starting, with all four CI jobs green** (`NEXT_STEPS.md` §82). The change added
`@app.errorhandler(psycopg2.pool.PoolError)` near the top of the module, and
`import psycopg2` does not bind the `pool` submodule — the explicit
`import psycopg2.pool` sat 280 lines further down, beside the pool
construction. Under gunicorn the module raised
`AttributeError: module 'psycopg2' has no attribute 'pool'` at import and the
process exited after seven seconds.

**Every in-process test passed, and had to.** `conftest.py` does
`import psycopg2.pool` at line 20 to stub `ThreadedConnectionPool`, so by the
time any test imports `flask_api` the submodule is already bound and the
attribute resolves. The suite is structurally incapable of seeing this: the
fixture that makes testing possible is what hides it.

So the check has to happen **in a subprocess with a clean interpreter**, which
is the only environment that resembles `gunicorn flask_api:app`. The general
lesson, and the reason this is not only about one import: *a test process that
has already imported something cannot tell you whether the module under test
imports it.*
"""
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))


# `flask_api` builds its `ThreadedConnectionPool` at **import time**
# (`flask_api.py:453`), so importing it reaches for a real database. In-process
# tests never notice because `conftest.py` replaces `ThreadedConnectionPool`
# with a `MagicMock`; a subprocess gets no such help, and the first version of
# this file duly passed locally and failed CI with
# `database "weave_weather" does not exist`.
#
# **The stub cannot be `psycopg2.pool.ThreadedConnectionPool`**, the way
# conftest does it, because reaching that name requires `import psycopg2.pool`
# — which binds the submodule and masks the exact bug these tests exist to
# catch. Stubbing `psycopg2.connect` instead is one level lower: the pool
# constructor calls it, so the pool builds against fakes, and `psycopg2.pool`
# is left for `flask_api` to import or fail to.
_PRELUDE = (
    'import psycopg2, unittest.mock as _m; '
    'psycopg2.connect = _m.MagicMock(); '
)


def _fresh(code, prelude=True):
    """Run `code` in a new interpreter with `Data/` importable and nothing else.

    `-S` is deliberately not used — the real deployment has site-packages. What
    matters is that **this** process's imports are not inherited, so the module
    has to satisfy its own dependencies.
    """
    return subprocess.run(
        [sys.executable, '-c', (_PRELUDE if prelude else '') + code],
        cwd=HERE, capture_output=True, text=True, timeout=180,
        # A clean-ish environment: no pytest, no conftest, no TESTING flag.
        env={**os.environ, 'PYTHONPATH': HERE, 'FLASK_DEBUG': '0'},
    )


def test_flask_api_imports_in_a_fresh_interpreter():
    """What `gunicorn flask_api:app` does, before it serves anything."""
    r = _fresh('import flask_api')
    assert r.returncode == 0, (
        'flask_api failed to import in a clean interpreter — gunicorn would '
        f'exit on startup.\nstderr:\n{r.stderr[-2000:]}')


def test_the_wsgi_entrypoint_resolves():
    """`flask_api:app` is the name DEPLOY.md §3 and the Dockerfile both use.

    Importing the module is necessary and not sufficient: the callable has to
    be there under that exact name.
    """
    r = _fresh('import flask_api; assert callable(flask_api.app), type(flask_api.app)')
    assert r.returncode == 0, r.stderr[-2000:]


def test_psycopg2_pool_is_bound_by_the_module_itself():
    """The specific trap, pinned.

    Asserted from a fresh interpreter rather than this one, because `conftest`
    has already bound `psycopg2.pool` here and the check would pass vacuously.
    Verified to be a real distinction: `import psycopg2` alone leaves
    `hasattr(psycopg2, 'pool')` False.
    """
    r = _fresh('import psycopg2; assert not hasattr(psycopg2, "pool"); '
               'import flask_api; '
               'assert hasattr(psycopg2, "pool"), "flask_api did not import it"')
    assert r.returncode == 0, r.stderr[-2000:]


def test_the_guard_can_fail():
    """A check that cannot fail is not a check (§28, §78, §79, §82).

    Imports a module that genuinely does not exist, through the same helper,
    and requires a non-zero exit. Without this, a `_fresh` that silently
    swallowed errors would make every test above pass forever.
    """
    r = _fresh('import a_module_that_does_not_exist_94e1')
    assert r.returncode != 0, 'the subprocess helper does not surface failures'


def test_these_tests_do_not_need_a_database():
    """The tests above must pass where CI runs, which has no `weave_weather`.

    The first version of this file did not, and went green locally and red on
    CI for a reason that had nothing to do with what it was testing. Pointing
    the config at a database that certainly does not exist reproduces CI's
    environment here, so the dependency cannot creep back in unnoticed.
    """
    r = subprocess.run(
        [sys.executable, '-c', _PRELUDE + 'import flask_api'],
        cwd=HERE, capture_output=True, text=True, timeout=180,
        env={**os.environ, 'PYTHONPATH': HERE, 'FLASK_DEBUG': '0',
             'DB_NAME': 'definitely_not_a_database_8f21a'},
    )
    assert r.returncode == 0, (
        'flask_api cannot be imported without a live database — these tests '
        f'will fail on CI.\nstderr:\n{r.stderr[-2000:]}')
