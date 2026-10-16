"""The advertised rate limit should be the one a client actually meets.

`flask-limiter` defaults to `memory://`, which **each gunicorn worker keeps
privately**. So `300 per minute` under `-w 4` admits up to 1,200, and which
counter a client meets depends on which worker the proxy hands it to — the
same client can be throttled on one request and not the next.

This was written in a comment beside the limiter and reported nowhere, while
`deploy/Dockerfile.api` ships `WEB_CONCURRENCY=4`. **The shipped configuration
had the gap** (`NEXT_STEPS.md` §83).

It is a correctness gap, not a security hole: the limit still bounds a single
client, at N× the configured rate. Two halves to the fix — `compose.yaml`
wires Redis so the containerised deployment is right by default, and
`_check_rate_limit_storage` puts the *effective* number on `/api/health` so a
deployment that is not using a shared store says so instead of being believed.

`safe` is false only when the storage is per-process **and** there is more
than one process. A single worker with `memory://` is correct, and warning
about it would be noise nobody can act on — one test below pins exactly that,
because a check that fires in a correct configuration gets ignored in every
configuration.
"""
import importlib

import pytest

import flask_api as api


def _check(monkeypatch, storage, workers, limit='300 per minute'):
    """Evaluate the check under a given storage/worker/limit combination."""
    monkeypatch.setattr(api, 'RATE_LIMIT_STORAGE', storage)
    monkeypatch.setattr(api, 'RATE_LIMIT', limit)
    monkeypatch.setenv('WEB_CONCURRENCY', str(workers))
    return api._check_rate_limit_storage()


def test_memory_storage_with_several_workers_is_not_safe(monkeypatch):
    """The defect: four private counters presented as one limit."""
    r = _check(monkeypatch, 'memory://', 4)
    assert r['safe'] is False, r
    assert r['shared_across_workers'] is False, r


def test_it_reports_the_effective_limit_not_the_configured_one(monkeypatch):
    """The number that matters is the one a client can actually reach."""
    r = _check(monkeypatch, 'memory://', 4, '300 per minute')
    assert r['stated_per_minute'] == 300, r
    assert r['effective_per_minute'] == 1200, r


def test_redis_storage_is_safe_and_the_limit_is_what_it_says(monkeypatch):
    r = _check(monkeypatch, 'redis://redis:6379/0', 4, '300 per minute')
    assert r['safe'] is True, r
    assert r['shared_across_workers'] is True, r
    assert r['effective_per_minute'] == 300, r


def test_one_worker_with_memory_storage_is_correct(monkeypatch):
    """The guard against a check that cries wolf.

    A single process holding its own counters is exactly right. If this
    reported `safe: false` the warning would fire for every developer running
    the dev server, and a warning that is always on is one nobody reads.
    """
    r = _check(monkeypatch, 'memory://', 1, '300 per minute')
    assert r['safe'] is True, r
    assert r['effective_per_minute'] == 300, r


@pytest.mark.parametrize('limit,expected', [
    ('300 per minute', 300),
    ('10 per second', 600),
    ('600 per hour', 10),
    ('5/minute', 5),
])
def test_limit_strings_convert_to_per_minute(limit, expected):
    assert api._rate_limit_per_minute(limit) == expected


def test_an_unparseable_limit_reports_nothing_rather_than_guessing():
    """A wrong number stated confidently is worse than an absent one."""
    assert api._rate_limit_per_minute('300 per fortnight') is None
    assert api._rate_limit_per_minute('') is None


def test_unparseable_limit_does_not_break_the_check(monkeypatch):
    """`safe` is about the storage, and stays answerable without a number."""
    r = _check(monkeypatch, 'memory://', 4, 'nonsense')
    assert r['safe'] is False, r
    assert r['stated_per_minute'] is None, r
    assert r['effective_per_minute'] is None, r


def test_health_reports_it(monkeypatch):
    """On `/api/health` beside `connection_pool`, for the same reason (§27).

    A figure that only exists in a startup log is gone by the time anyone
    wants it.
    """
    import inspect
    src = inspect.getsource(api.health_check)
    assert '_check_rate_limit_storage' in src, (
        'the health endpoint does not report the rate-limit check')
