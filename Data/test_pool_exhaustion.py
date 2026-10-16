"""An exhausted connection pool is busy, not broken.

Found by the S3 load test (`NEXT_STEPS.md` §82), which is the first time
anything had measured this app under concurrency. At 16 concurrent requests
against one worker, **8 of 36 returned HTTP 500** carrying
`psycopg2.pool.PoolError: connection pool exhausted` into the generic 500
handler.

Two things were wrong and they compound.

**The status code.** 500 means the server faulted. Nothing had faulted —
eight connections were in use by requests that were all succeeding. A 500
makes every sensible client behaviour look wrong: a browser reports an error,
a load balancer may evict the instance, a health check may restart it. 503
with `Retry-After` is the accurate answer, and it is what the rate limiter
beside it already does for the analogous case with 429.

**The retry budget could not cover the thing it waits for.** It was
5 × 0.25 s = 1.25 s. `/api/point-timeseries` takes 4.4 s cold and holds its
connection for the duration, so the retry gave up about three seconds before
the connection could be returned. Same shape as §78's 10 s `waitFor` inside a
5 s test — patience that cannot be spent. It is now 24 × 0.5 s = 12 s, longer
than the slowest measured cold request.
"""
import psycopg2
import pytest

import flask_api as api


@pytest.fixture
def client():
    api.app.config['TESTING'] = True
    return api.app.test_client()


def test_exhausted_pool_answers_503_not_500(client, monkeypatch):
    """The defect: busy reported as broken."""
    def _always_exhausted():
        raise psycopg2.pool.PoolError('connection pool exhausted')
    monkeypatch.setattr(api, 'get_db_connection', _always_exhausted)

    r = client.get('/api/models')
    assert r.status_code == 503, (r.status_code, r.get_data(as_text=True))


def test_503_carries_retry_after(client, monkeypatch):
    """A client cannot back off sensibly without being told how long."""
    monkeypatch.setattr(api, 'get_db_connection', lambda: (_ for _ in ()).throw(
        psycopg2.pool.PoolError('connection pool exhausted')))

    r = client.get('/api/models')
    assert r.headers.get('Retry-After') == '2', dict(r.headers)
    assert r.get_json().get('retry_after_seconds') == 2, r.get_json()


def test_the_message_does_not_leak_internals(client, monkeypatch):
    """The 500 handler exists to avoid leaking stack detail; so does this."""
    monkeypatch.setattr(api, 'get_db_connection', lambda: (_ for _ in ()).throw(
        psycopg2.pool.PoolError('connection pool exhausted at host=secret')))

    body = client.get('/api/models').get_data(as_text=True)
    assert 'secret' not in body, body
    assert 'Traceback' not in body, body


def test_retry_budget_exceeds_the_slowest_measured_request():
    """The budget is only useful if it outlasts what holds the connection.

    §82 measured `/api/point-timeseries` at **4.4 s cold**. A budget below
    that cannot help in the case that actually exhausts the pool, which is
    precisely what the previous 1.25 s could not do.

    **Reads the module's own constants.** The first version of this test
    restated the defaults as literals — `os.environ.get('DB_POOL_RETRIES', 24)`
    — so it asserted 24 × 0.5 against 4.4 and passed no matter what
    `flask_api` actually used. It passed against `HEAD`, where the budget was
    1.25 s. A test that restates the value it is checking is not checking it;
    the constants exist so there is one copy.
    """
    budget = api.DB_POOL_RETRIES_DEFAULT * api.DB_POOL_RETRY_DELAY_DEFAULT
    assert budget > api.SLOWEST_COLD_REQUEST_SECONDS * 2, (
        f'retry budget {budget}s does not comfortably exceed the slowest '
        f'measured cold request ({api.SLOWEST_COLD_REQUEST_SECONDS}s)')


def test_a_real_fault_is_still_a_500(monkeypatch):
    """The guard: the new handler must not swallow genuine faults.

    Without this, catching PoolError could be widened accidentally and every
    server error would read as "busy, retry" — which is the mirror image of
    the defect being fixed, and the tests above would all still pass.

    **Not the shared `client` fixture.** `TESTING = True` turns on
    `PROPAGATE_EXCEPTIONS`, so an *unhandled* exception is re-raised to the
    caller instead of being converted to a 500 — the first version of this
    test failed with the RuntimeError it had just injected. Registered
    handlers still run under that flag, which is why the `PoolError` cases
    above are unaffected. Turning propagation off here is what makes this
    test observe the production path it is about.
    """
    api.app.config['TESTING'] = True
    api.app.config['PROPAGATE_EXCEPTIONS'] = False
    try:
        monkeypatch.setattr(api, 'get_db_connection',
                            lambda: (_ for _ in ()).throw(
                                RuntimeError('something genuinely broke')))
        r = api.app.test_client().get('/api/models')
        assert r.status_code == 500, (r.status_code, r.get_data(as_text=True))
        assert 'Retry-After' not in r.headers, dict(r.headers)
    finally:
        api.app.config.pop('PROPAGATE_EXCEPTIONS', None)
