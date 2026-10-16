"""The startup checks reach a deployment, not only the dev server.

The pool and storage checks existed, were careful, and **production never saw
them**: they ran inside `if __name__ == '__main__'`, which is the Flask dev
server's entry point. gunicorn imports `flask_api:app`, so that block never
executes — the one deployment where "your pool will not fit under
`max_connections`" actually matters was the one deployment nobody warned
(`NEXT_STEPS.md` §74).

The figures were on `/api/health` throughout, which is not the same thing. A
number available to whoever thinks to look is not a warning.

These tests drive `report_startup_checks` directly with a routed cursor,
because what needs proving is *what it says when something is wrong* — and
neither the fixture nor the real database is over capacity, so a test that only
ran against them could never see the warning path at all.
"""
from datetime import datetime

import pytest

import flask_api as api


def _emit_to(collected):
    return lambda line: collected.append(line)


@pytest.fixture
def checks(monkeypatch):
    """`report_startup_checks` with its three probes stubbed.

    The probes have their own tests; this file is about whether the reporter
    says the right thing, to the right place, in each state.
    """
    def configure(pool_safe=True, storage_safe=True, domain_safe=True):
        monkeypatch.setattr(api, 'get_db_connection', lambda: _FakeConn())
        monkeypatch.setattr(api, 'return_db_connection', lambda conn: None)
        monkeypatch.setattr(api, '_check_pool_headroom', lambda cur: {
            'safe': pool_safe, 'workers': 4, 'pool_max_per_worker': 8,
            'peak_connections': 32, 'usable_connections': 97, 'max_connections': 100})
        monkeypatch.setattr(api, '_check_storage_headroom', lambda cur: {
            'safe': storage_safe, 'database_gb': 260.0, 'runs': 5,
            'revisit_at_gb': 250.0, 'headroom_gb': -10.0,
            'runs_until_revisit': 0, 'mean_gb_per_run': 52.0})
        monkeypatch.setattr(api, '_check_data_freshness', lambda cur: {
            'runs': 3, 'latest_init': '2025-09-16T00:00:00',
            'last_loaded_at': '2026-09-30T11:26:00'})
        monkeypatch.setattr(api, '_check_domain', lambda cur: {
            'safe': domain_safe, 'from_default': True, 'rows_loaded': True,
            'resolution': 0.5,
            'configured': {'min_lat': 25.0, 'max_lat': 45.0,
                           'min_lon': -85.0, 'max_lon': -65.0},
            'stored':     {'min_lat': 20.0, 'max_lat': 40.0,
                           'min_lon': -100.0, 'max_lon': -60.0}})
    return configure


class _FakeCur:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _FakeConn:
    def cursor(self, *a, **kw): return _FakeCur()


class TestWhatItSays:
    def test_it_says_nothing_alarming_when_everything_fits(self, checks):
        checks()
        out = []
        api.report_startup_checks(emit=_emit_to(out))
        assert out == [], out

    def test_it_warns_when_the_pool_is_over_capacity(self, checks):
        checks(pool_safe=False)
        out = []
        api.report_startup_checks(emit=_emit_to(out))
        assert len(out) == 1
        assert 'CONNECTION POOL OVER CAPACITY' in out[0]
        # The numbers an operator needs to act, not just the verdict.
        assert '32' in out[0] and '97' in out[0]
        assert 'DB_POOL_MAX' in out[0]

    def test_it_warns_when_storage_is_past_the_threshold(self, checks):
        checks(storage_safe=False)
        out = []
        api.report_startup_checks(emit=_emit_to(out))
        assert len(out) == 1
        assert 'STORAGE PAST THE RETENTION THRESHOLD' in out[0]
        # Says plainly that nothing is broken — the stance /api/health takes.
        assert 'Nothing is broken' in out[0]

    def test_it_warns_when_the_domain_does_not_match_the_data(self, checks):
        """The warning that makes the domain safe to configure at all.

        A constant can only be wrong if someone edits a file; an environment
        variable can be wrong because of a shell, and every default-bbox answer
        would then be scoped to a box the database does not hold (§76).
        """
        checks(domain_safe=False)
        out = []
        api.report_startup_checks(emit=_emit_to(out))
        assert len(out) == 1
        assert 'ANALYSIS DOMAIN DOES NOT MATCH THE DATA' in out[0]
        # Both boxes, so the reader can see which way it drifted.
        assert '25.0' in out[0] and '20.0' in out[0]
        assert 'WEAVE_DOMAIN_LAT' in out[0]

    def test_both_warnings_appear_together(self, checks):
        checks(pool_safe=False, storage_safe=False)
        out = []
        api.report_startup_checks(emit=_emit_to(out))
        assert len(out) == 2

    def test_it_defaults_to_the_logger_rather_than_stdout(self, checks, caplog):
        """The default emitter is what a deployment actually gets."""
        checks(pool_safe=False)
        with caplog.at_level('WARNING', logger='weave.api'):
            api.report_startup_checks()
        assert any('CONNECTION POOL OVER CAPACITY' in r.message for r in caplog.records)

    def test_it_logs_what_is_loaded_even_when_all_is_well(self, checks, caplog):
        # "Nothing was warned" and "the check never ran" look identical
        # without a line saying it ran.
        checks()
        with caplog.at_level('INFO', logger='weave.api'):
            api.report_startup_checks(emit=_emit_to([]))
        assert any("latest init" in r.getMessage() or "WEAVE data" in r.getMessage()
                   for r in caplog.records)


class TestAgainstARealCursor:
    """Unstubbed, because stubbing all three probes hid a real defect.

    Every test in `TestWhatItSays` replaces `_check_pool_headroom`,
    `_check_storage_headroom` and `_check_data_freshness`, so none of them ever
    exercised the **cursor** this function hands them. The first version passed
    a `RealDictCursor`; the two older checks read their rows positionally
    (`fetchone()[0]`), so it raised `KeyError: 0`, the `except` swallowed it as
    "Could not verify startup headroom: 0", and the checks silently did not run
    — inside the function written to stop checks silently not running.

    Caught by reading the dev server's own banner, not by the suite. This test
    is the suite catching up.
    """

    def test_it_runs_end_to_end_against_the_fixture_database(self, fixture_pool, monkeypatch):
        monkeypatch.setattr(api, 'connection_pool', fixture_pool)
        out = []
        result = api.report_startup_checks(emit=_emit_to(out))

        # The shapes the caller destructures in `__main__`. `rate_limit`
        # joined them in §83 — it needs no database, so it is computed
        # outside the cursor block, but it is reported the same way.
        assert set(result) == {'pool', 'storage', 'freshness', 'domain',
                               'rate_limit'}
        assert isinstance(result['storage']['database_gb'], float)
        assert isinstance(result['pool']['usable_connections'], int)
        assert 'latest_init' in result['freshness']
        assert isinstance(result['rate_limit']['safe'], bool)

    def test_the_dev_banner_fields_all_resolve(self, fixture_pool, monkeypatch):
        """`__main__` formats these by key; a missing one is an AttributeError
        at startup, which is the other way this could fail unnoticed."""
        monkeypatch.setattr(api, 'connection_pool', fixture_pool)
        r = api.report_startup_checks(emit=_emit_to([]))
        for key in ('database_gb', 'runs', 'headroom_gb', 'revisit_at_gb',
                    'runs_until_revisit', 'safe'):
            assert key in r['storage'], key
        for key in ('workers', 'pool_max_per_worker', 'peak_connections',
                    'usable_connections', 'safe'):
            assert key in r['pool'], key
        for key in ('runs', 'latest_init', 'last_loaded_at'):
            assert key in r['freshness'], key
        for key in ('configured', 'stored', 'from_default', 'rows_loaded', 'safe'):
            assert key in r['domain'], key


class TestItIsWiredToRequests:
    """The half that `__main__` could not provide."""

    def test_a_before_request_hook_is_registered(self):
        hooks = [f.__name__ for f in api.app.before_request_funcs.get(None, [])]
        assert '_run_startup_checks_once' in hooks, hooks

    def test_the_hook_runs_the_checks_once_and_not_again(self, monkeypatch):
        calls = []
        monkeypatch.setattr(api, 'report_startup_checks',
                            lambda *a, **k: calls.append(1))
        monkeypatch.setattr(api, '_STARTUP_CHECKS_DONE', False)
        monkeypatch.setitem(api.app.config, 'TESTING', False)

        client = api.app.test_client()
        client.get('/api/ready')
        client.get('/api/ready')
        assert calls == [1], 'expected exactly one run per worker process'

    def test_a_failing_check_does_not_break_the_request(self, monkeypatch, caplog):
        def boom(*a, **k):
            raise RuntimeError('database went away')
        monkeypatch.setattr(api, 'report_startup_checks', boom)
        monkeypatch.setattr(api, '_STARTUP_CHECKS_DONE', False)
        monkeypatch.setitem(api.app.config, 'TESTING', False)

        client = api.app.test_client()
        with caplog.at_level('WARNING', logger='weave.api'):
            resp = client.get('/api/ready')
        assert resp.status_code in (200, 503), resp.status_code
        # `getMessage()` renders the %-args; `r.message` is the raw template.
        assert any('database went away' in r.getMessage() for r in caplog.records)

    def test_it_is_skipped_under_testing(self, monkeypatch):
        """So the suite does not pay for it on whichever test goes first."""
        calls = []
        monkeypatch.setattr(api, 'report_startup_checks',
                            lambda *a, **k: calls.append(1))
        monkeypatch.setattr(api, '_STARTUP_CHECKS_DONE', False)
        monkeypatch.setitem(api.app.config, 'TESTING', True)

        api.app.test_client().get('/api/ready')
        assert calls == []


def test_main_no_longer_carries_its_own_copy():
    """`__main__` must call the shared reporter, not re-implement it.

    Two copies is how the dev server and the deployment came to disagree about
    what gets said in the first place.
    """
    import pathlib
    src = pathlib.Path(__file__).resolve().parent.joinpath('flask_api.py').read_text()
    main_block = src[src.index("if __name__ == '__main__':"):]
    assert 'report_startup_checks(' in main_block
    assert '_check_pool_headroom(' not in main_block
    assert '_check_storage_headroom(' not in main_block
