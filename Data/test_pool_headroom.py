"""Tests for the connection-pool headroom check.

The failure this guards against is quiet and load-dependent: each gunicorn
worker holds its own pool, so the number that must fit under PostgreSQL's
`max_connections` is `workers x DB_POOL_MAX`. Everything works until enough
users arrive together, and then requests fail to acquire a connection and it
reads as a database fault rather than a configuration one. See
REVIEW_DEPLOY_PREREQS.md section 2.

`_check_pool_headroom` takes a cursor, so these drive it with a fake one rather
than a database: the arithmetic and the reserved-connection subtraction are the
parts worth pinning, and neither needs PostgreSQL to be running.
"""
import pytest

import flask_api as api


class FakeCursor:
    """Answers the two SHOW statements `_check_pool_headroom` issues.

    Raising on an unexpected query rather than returning a default, so a change
    to the check's queries fails here instead of silently reporting figures
    derived from something else.
    """

    def __init__(self, max_connections=100, reserved=3, reserved_fails=False):
        self.max_connections = max_connections
        self.reserved = reserved
        self.reserved_fails = reserved_fails
        self._answer = None

    def execute(self, sql, params=None):
        if 'superuser_reserved_connections' in sql:
            if self.reserved_fails:
                raise RuntimeError('SHOW not permitted')
            self._answer = (str(self.reserved),)
        elif 'max_connections' in sql:
            self._answer = (str(self.max_connections),)
        else:
            raise AssertionError(f'unexpected query: {sql}')

    def fetchone(self):
        return self._answer


@pytest.fixture
def clean_worker_env(monkeypatch):
    for name in ('WEB_CONCURRENCY', 'GUNICORN_WORKERS'):
        monkeypatch.delenv(name, raising=False)


class TestWorkerCount:
    def test_web_concurrency_is_read_first(self, monkeypatch, clean_worker_env):
        """The variable gunicorn itself reads, so a deployment that sets workers
        the documented way needs no extra configuration."""
        monkeypatch.setenv('WEB_CONCURRENCY', '6')
        assert api._worker_count() == 6

    def test_gunicorn_workers_is_a_fallback(self, monkeypatch, clean_worker_env):
        monkeypatch.setenv('GUNICORN_WORKERS', '8')
        assert api._worker_count() == 8

    def test_defaults_to_one_when_unset(self, clean_worker_env):
        """The dev case. Under-reports the risk only when there is nothing to
        report, since a single process cannot exceed the ceiling on its own."""
        assert api._worker_count() == 1

    def test_a_junk_value_does_not_crash_startup(self, monkeypatch, clean_worker_env):
        """This runs during boot, so it must degrade rather than raise."""
        monkeypatch.setenv('WEB_CONCURRENCY', 'four')
        assert api._worker_count() == 1

    def test_zero_or_negative_is_floored_at_one(self, monkeypatch, clean_worker_env):
        monkeypatch.setenv('WEB_CONCURRENCY', '0')
        assert api._worker_count() == 1


class TestHeadroom:
    def test_the_documented_safe_tier_is_safe(self, monkeypatch, clean_worker_env):
        """8 workers x 8 = 64, under 97 usable. This is the tier the old default
        of 20 broke: 8 x 20 = 160."""
        monkeypatch.setenv('WEB_CONCURRENCY', '8')
        monkeypatch.setattr(api, 'DB_POOL_MAX', 8)
        result = api._check_pool_headroom(FakeCursor())
        assert result['peak_connections'] == 64
        assert result['usable_connections'] == 97
        assert result['headroom'] == 33
        assert result['safe'] is True

    def test_the_old_default_is_reported_unsafe(self, monkeypatch, clean_worker_env):
        """The exact condition REVIEW_DEPLOY_PREREQS.md section 2 describes."""
        monkeypatch.setenv('WEB_CONCURRENCY', '6')
        monkeypatch.setattr(api, 'DB_POOL_MAX', 20)
        result = api._check_pool_headroom(FakeCursor())
        assert result['peak_connections'] == 120
        assert result['safe'] is False
        assert result['headroom'] < 0

    def test_reserved_connections_are_subtracted(self, monkeypatch, clean_worker_env):
        """Superuser-reserved slots are not available to this role, so the
        usable ceiling is below max_connections. Ignoring them would call a
        configuration safe when it is three connections short."""
        monkeypatch.setenv('WEB_CONCURRENCY', '1')
        monkeypatch.setattr(api, 'DB_POOL_MAX', 98)
        result = api._check_pool_headroom(FakeCursor(max_connections=100, reserved=3))
        assert result['usable_connections'] == 97
        assert result['safe'] is False, 'must not count the reserved slots as usable'

    def test_exactly_at_the_ceiling_counts_as_safe(self, monkeypatch, clean_worker_env):
        monkeypatch.setenv('WEB_CONCURRENCY', '1')
        monkeypatch.setattr(api, 'DB_POOL_MAX', 97)
        result = api._check_pool_headroom(FakeCursor(max_connections=100, reserved=3))
        assert result['headroom'] == 0
        assert result['safe'] is True

    def test_an_unreadable_reserved_setting_degrades(self, monkeypatch, clean_worker_env):
        """A role that cannot SHOW that setting should still get the check,
        rather than losing it to an exception during startup."""
        monkeypatch.setenv('WEB_CONCURRENCY', '4')
        monkeypatch.setattr(api, 'DB_POOL_MAX', 8)
        result = api._check_pool_headroom(FakeCursor(reserved_fails=True))
        assert result['usable_connections'] == 100
        assert result['safe'] is True


class TestTheShippedDefault:
    def test_the_default_pool_max_is_safe_at_every_documented_tier(self):
        """Pins the shipped default itself, not just the arithmetic over it.

        Reads `DB_POOL_MAX_DEFAULT` rather than the effective `DB_POOL_MAX`,
        because the effective value comes from whatever `.env` this machine has
        and would pass on a dev box while the committed default was unsafe.

        The tiers are the ones in the cost estimate; the assertion is that the
        default clears all of them against a stock PostgreSQL (100 connections,
        3 superuser-reserved).
        """
        default = api.DB_POOL_MAX_DEFAULT
        for workers in (2, 4, 6, 8):
            assert workers * default <= 97, (
                f'{workers} workers x {default} exceeds the usable ceiling')

    def test_the_old_default_would_fail_that_test(self):
        """Guards the guard: 20 was the previous default and 6 workers was
        enough to break it, so the tier list above has to be able to catch it."""
        assert any(workers * 20 > 97 for workers in (2, 4, 6, 8))
