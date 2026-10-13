"""`/api/health` says how current the data is, not only that the server is up.

Before this, health reported a connected database, a pool that fits and a disk
with room — and **nothing about whether the numbers it serves are from last
week or last year** (`NEXT_STEPS.md` §73). "Is this stale?" was unanswerable
without a SQL client, which is the question an operator actually has.

Three clocks, kept separate on purpose because they answer different questions:
how old the *weather* is (`latest_init`), how long the archive has been *quiet*
(`last_loaded_at`), and how far the *truth record* reaches (`observations`),
which is what actually bounds verification.

**There is deliberately no `safe` flag**, unlike the pool and storage checks
beside it, and one test below pins that. Those compare against a threshold that
means something. This is a research archive: `2025-09-16` is the run under
study and is supposed to be old, so any staleness threshold would be invented —
and an invented threshold that reads `safe: false` forever is worse than no
flag at all.

The boolean that *is* reported, `covers_latest_init`, is exercised both ways
with a routed cursor, because the fixture only ever shows it true and a test
that can only observe one outcome is not testing the logic.
"""
from datetime import datetime, timedelta

import pytest

import flask_api as api


REGISTRY_SQL = 'FROM forecast_run_registry'
OBS_SQL      = 'FROM regridded_observation WHERE source'


def _routed(latest_init, last_loaded, runs, obs_end):
    """A cursor answering the two queries `_check_data_freshness` makes."""
    from conftest import RoutedCursor
    return RoutedCursor({
        REGISTRY_SQL: [{'latest_init': latest_init,
                        'last_loaded_at': last_loaded,
                        'runs': runs}],
        OBS_SQL: [{'end': obs_end}],
    })


class TestAgainstTheRealDatabase:
    def test_health_carries_a_freshness_block(self, db_client):
        body = db_client.get('/api/health').get_json()
        assert 'freshness' in body, sorted(body)
        f = body['freshness']
        assert set(f) >= {'latest_init', 'latest_init_age_hours', 'last_loaded_at',
                          'last_loaded_age_hours', 'runs', 'observations'}

    def test_the_latest_init_is_the_registry_max(self, db_client, fixture_pool):
        f = db_client.get('/api/health').get_json()['freshness']
        conn = fixture_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT max(init_time) FROM forecast_run_registry')
                expected = cur.fetchone()[0]
        finally:
            fixture_pool.putconn(conn)
        assert f['latest_init'] == (expected.isoformat() if expected else None)

    def test_both_observation_sources_are_named(self, db_client):
        obs = db_client.get('/api/health').get_json()['freshness']['observations']
        assert obs['precipitation']['source'] == 'GPM_IMERG_V07B'
        assert obs['wind']['source'] == 'ERA5_WIND'

    def test_the_ages_are_numbers_and_not_negative(self, db_client):
        f = db_client.get('/api/health').get_json()['freshness']
        for key in ('latest_init_age_hours', 'last_loaded_age_hours'):
            assert isinstance(f[key], (int, float)), key
            assert f[key] >= 0, f'{key} is in the future: {f[key]}'

    def test_freshness_does_not_make_the_endpoint_unhealthy(self, db_client):
        """Old data is a fact about the archive, not a fault.

        The same stance `storage` takes with `safe: false` — a decision may be
        due, nothing is broken.
        """
        body = db_client.get('/api/health').get_json()
        assert body['status'] == 'healthy'


class TestTheLogicBothWays:
    """Routed-cursor tests, because the fixture can only show one outcome."""

    def test_covers_latest_init_is_true_when_observations_reach_the_run(self):
        init = datetime(2025, 9, 16)
        out = api._check_data_freshness(
            _routed(init, datetime(2026, 9, 30), 3, init + timedelta(days=10)))
        assert out['observations']['precipitation']['covers_latest_init'] is True

    def test_covers_latest_init_is_false_when_they_stop_short(self):
        # The state that matters: a run is loaded that cannot be scored yet.
        init = datetime(2025, 9, 16)
        out = api._check_data_freshness(
            _routed(init, datetime(2026, 9, 30), 3, init - timedelta(days=1)))
        assert out['observations']['precipitation']['covers_latest_init'] is False

    def test_an_empty_archive_reports_nulls_rather_than_raising(self):
        # `max()` over no rows is NULL, which is what a fresh database returns.
        out = api._check_data_freshness(_routed(None, None, 0, None))
        assert out['latest_init'] is None
        assert out['latest_init_age_hours'] is None
        assert out['runs'] == 0
        assert out['observations']['wind']['covers_latest_init'] is False

    def test_the_age_is_measured_from_the_timestamp(self):
        five_hours_ago = datetime.now() - timedelta(hours=5)
        out = api._check_data_freshness(
            _routed(five_hours_ago, five_hours_ago, 1, None))
        assert out['latest_init_age_hours'] == pytest.approx(5.0, abs=0.2)

    def test_there_is_no_safe_flag(self):
        """Pinned, because adding one is the obvious "improvement" to make.

        It would need a staleness threshold, and for an archive whose subject
        run is a year old any threshold is invented — it would read
        `safe: false` forever and teach the reader to ignore the field.
        """
        out = api._check_data_freshness(_routed(datetime(2025, 9, 16),
                                                datetime(2026, 9, 30), 3, None))
        assert 'safe' not in out
