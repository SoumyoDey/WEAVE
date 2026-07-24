"""Pytest setup for the backend metric tests.

flask_api opens a real PostgreSQL connection pool at import time, so we replace
psycopg2's pool with a stub *before* any test module imports flask_api. The
metric tests drive the pure computation paths with hand-built inputs (a fake
cursor or a monkeypatched fetch helper), so no real database is ever touched and
the suite runs anywhere.
"""
from unittest.mock import MagicMock

import psycopg2.pool

# Applied at conftest import — pytest loads conftest.py before collecting test
# modules, so this is in place by the time `import flask_api` runs.
psycopg2.pool.ThreadedConnectionPool = MagicMock()
