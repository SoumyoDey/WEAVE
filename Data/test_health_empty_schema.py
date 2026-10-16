"""A reachable database with no schema is not an unreachable one.

`/api/health` probes `'forecast_data'::regclass`, which raises
`UndefinedTable` when the table is absent. That fell into the broad `except`
and was reported as **`"database": "unavailable"`** — the same word used for a
database the API cannot reach at all.

**This became reachable the day `compose.yaml` did.** A fresh PostgreSQL volume
is the normal first state of a container stand-up: `docker compose up` gives
you an empty database, the API starts and reports itself healthy on
`/api/ready`, and the first thing anyone does is curl `/api/health`. Telling
them the database is unavailable sends them to look at networking, DNS and
credentials — all of which are fine. The answer is DEPLOY.md §9: restore a
dump. Found by standing the stack up and reading the log, not by reading code.

It is still **503 and still not "healthy"** — an empty database cannot serve
anything, so an orchestrator should keep taking the instance out. The change is
only in what it says, which is the whole value of a health endpoint.
"""
import psycopg2
import pytest

import flask_api as api


class _RaisingCursor:
    """A cursor whose first `execute` raises, as an empty schema does."""

    def __init__(self, exc):
        self._exc = exc

    def execute(self, *_a, **_k):
        raise self._exc

    def fetchone(self):                       # pragma: no cover - never reached
        raise AssertionError('execute should have raised first')

    def close(self):
        pass


@pytest.fixture
def _client(monkeypatch):
    def _install(exc):
        class _Conn:
            def cursor(self, *a, **k):
                return _RaisingCursor(exc)
        monkeypatch.setattr(api, 'get_db_connection', lambda: _Conn())
        monkeypatch.setattr(api, 'return_db_connection', lambda _c: None)
        api.app.config['TESTING'] = True
        return api.app.test_client()
    return _install


def test_absent_schema_is_not_reported_as_unavailable(_client):
    """The defect itself: an empty database read as an unreachable one."""
    client = _client(psycopg2.errors.UndefinedTable(
        'relation "forecast_data" does not exist'))
    r = client.get('/api/health')
    body = r.get_json()

    # The database IS reachable. Saying otherwise is the bug.
    assert body['database'] == 'connected', body
    assert body.get('schema') == 'absent', body
    assert body['status'] == 'unhealthy', body


def test_absent_schema_answers_503_not_500(_client):
    """503 — the service cannot serve yet, but nothing has faulted."""
    client = _client(psycopg2.errors.UndefinedTable('relation ... does not exist'))
    assert client.get('/api/health').status_code == 503


def test_absent_schema_says_what_to_do_about_it(_client):
    """A health endpoint read during a first stand-up should name the fix."""
    client = _client(psycopg2.errors.UndefinedTable('relation ... does not exist'))
    hint = _client and client.get('/api/health').get_json().get('hint', '')
    assert 'restore' in hint.lower(), hint
    # Pointing at the section that actually has the procedure.
    assert 'section 9' in hint.lower() or '§9' in hint, hint


def test_a_genuinely_unreachable_database_still_says_unavailable(_client):
    """The other half, so the fix cannot swallow a real connection failure.

    Without this the change could report every fault as an absent schema and
    the test above would still pass.
    """
    client = _client(psycopg2.OperationalError('could not connect to server'))
    r = client.get('/api/health')
    body = r.get_json()

    assert r.status_code == 500, body
    assert body['database'] == 'unavailable', body
    assert 'schema' not in body, body
