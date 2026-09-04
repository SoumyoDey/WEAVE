"""The metric cache: what goes in the key, and what invalidates it.

The metric endpoints are deterministic, so caching them is safe. Everything that
decides whether it is *correct* lives in the key, and a key that omits something
does not fail — it serves a confidently wrong answer for a request nobody made.
Two omissions are the ones to guard:

- **`init_time`.** Before the run identity existed there was one run and the
  question could not arise. With two, a key without it serves one run's numbers
  under another run's label — the same silent cross-run error
  `migrate_init_time.py` exists to prevent, reintroduced at a different layer.
  `/api/compare/spatial-agreement` had exactly this gap.
- **the data version**, derived from `forecast_run_registry`, so a reload or a
  re-run of `regrid_members.py` orphans every affected entry immediately rather
  than after a TTL.

`conftest.py` disables the cache for the rest of the suite, because a
FileSystemCache that survives a restart cannot tell one test's fake database from
another's. So this file tests the cache directly rather than through endpoints.
"""
import inspect
import re

import pytest

import flask_api as api


class FakeCursor:
    """Answers the two queries `_data_version` issues."""

    def __init__(self, registry=None, has_registry=True, obs=None):
        self._registry = registry if registry is not None else []
        self._obs = obs if obs is not None else [dict(OBS)]
        self._has = has_registry
        self._rows = []

    def execute(self, sql, params=None):
        if 'to_regclass' in sql:
            self._rows = [{'ok': self._has}]
        elif 'regridded_observation' in sql:
            self._rows = list(self._obs)
        else:
            self._rows = list(self._registry)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


# One row of the observation fingerprint: the truth field's side of the version.
OBS = {'source': 'ERA5_WIND', 'n': 40344,
       't': '2025-09-08 23:00:00', 's': 192735.753}

ROW = {'model_name': 'AIFS', 'variable_name': 'precipitation',
       'init_time': '2025-09-08 00:00:00', 'loaded_at': '2026-09-02 12:00:00',
       'n_members': 50, 'hour_min': 6, 'hour_max': 360}


class TestDataVersion:
    def test_it_is_stable_for_unchanged_data(self):
        a = api._data_version_uncached(FakeCursor([ROW]))
        b = api._data_version_uncached(FakeCursor([ROW]))
        assert a == b

    def test_a_reload_changes_it(self):
        # `loaded_at` moving is what a re-run of the regrid looks like. This is
        # the whole invalidation mechanism: if it does not move, stale numbers
        # are served until the TTL expires.
        before = api._data_version_uncached(FakeCursor([ROW]))
        after = api._data_version_uncached(
            FakeCursor([{**ROW, 'loaded_at': '2026-09-02 13:00:00'}]))
        assert before != after

    @pytest.mark.parametrize('field,value', [
        ('init_time', '2025-09-09 00:00:00'),
        ('n_members', 30),
        ('hour_max', 240),
        ('model_name', 'GEFS'),
    ])
    def test_any_registry_field_changing_changes_it(self, field, value):
        before = api._data_version_uncached(FakeCursor([ROW]))
        after = api._data_version_uncached(FakeCursor([{**ROW, field: value}]))
        assert before != after, f'{field} does not affect the data version'

    def test_a_new_run_appearing_changes_it(self):
        one = api._data_version_uncached(FakeCursor([ROW]))
        two = api._data_version_uncached(
            FakeCursor([ROW, {**ROW, 'init_time': '2025-09-09 00:00:00'}]))
        assert one != two

    def test_no_registry_says_so_rather_than_pretending(self):
        # On a part-migrated database the version cannot see data changes, so the
        # TTL is doing all the work. A constant is the honest answer; raising
        # would fail requests over a cache key.
        assert api._data_version_uncached(FakeCursor(has_registry=False)) == 'noreg'


class TestMetricCacheKey:
    def test_init_time_is_part_of_the_key(self):
        # The cross-run bug, as a test. Same everything else, different run.
        cur = FakeCursor([ROW])
        a = api._metric_cache_key('m', cur, metric='mae', init_time='2025-09-08')
        b = api._metric_cache_key('m', cur, metric='mae', init_time='2025-09-09')
        assert a != b

    def test_the_data_version_is_part_of_the_key(self):
        a = api._metric_cache_key('m', FakeCursor([ROW]), metric='mae')
        b = api._metric_cache_key(
            'm', FakeCursor([{**ROW, 'loaded_at': '2026-09-03 00:00:00'}]),
            metric='mae')
        assert a != b

    def test_the_prefix_separates_endpoints(self):
        cur = FakeCursor([ROW])
        assert (api._metric_cache_key('metric', cur, x=1)
                != api._metric_cache_key('spread', cur, x=1))

    def test_the_same_request_gives_the_same_key(self):
        cur = FakeCursor([ROW])
        parts = dict(metric='mae', bbox=[25.0, 45.0], init_time='2025-09-08')
        assert (api._metric_cache_key('m', cur, **parts)
                == api._metric_cache_key('m', FakeCursor([ROW]), **parts))

    def test_keyword_order_does_not_matter(self):
        cur = FakeCursor([ROW])
        assert (api._metric_cache_key('m', cur, a=1, b=2)
                == api._metric_cache_key('m', cur, b=2, a=1))


class TestBodyCacheKey:
    def test_model_order_is_not_part_of_the_question(self):
        # Asking for [AIFS, GEFS] and [GEFS, AIFS] is one question; the endpoints
        # sort internally, so two keys would just halve the hit rate.
        cur = FakeCursor([ROW])
        a = api._body_cache_key('c', cur, {'models': ['AIFS', 'GEFS']}, ('models',))
        b = api._body_cache_key('c', cur, {'models': ['GEFS', 'AIFS']}, ('models',))
        assert a == b

    def test_metric_order_likewise(self):
        cur = FakeCursor([ROW])
        a = api._body_cache_key('c', cur, {'metrics': ['mae', 'rmse']}, ('metrics',))
        b = api._body_cache_key('c', cur, {'metrics': ['rmse', 'mae']}, ('metrics',))
        assert a == b

    def test_a_field_that_changes_the_answer_changes_the_key(self):
        cur = FakeCursor([ROW])
        a = api._body_cache_key('c', cur, {'lat': 36.0}, ('lat', 'lon'))
        b = api._body_cache_key('c', cur, {'lat': 37.0}, ('lat', 'lon'))
        assert a != b

    def test_an_unlisted_field_cannot_fragment_the_cache(self):
        # A cache-buster or analytics parameter the endpoint ignores must not
        # turn every request into a miss.
        cur = FakeCursor([ROW])
        a = api._body_cache_key('c', cur, {'lat': 36.0}, ('lat',))
        b = api._body_cache_key('c', cur, {'lat': 36.0, '_t': 12345}, ('lat',))
        assert a == b

    def test_init_time_travels_when_the_caller_sends_one(self):
        cur = FakeCursor([ROW])
        a = api._body_cache_key('c', cur, {'init_time': '2025-09-08'}, ('init_time',))
        b = api._body_cache_key('c', cur, {'init_time': '2025-09-09'}, ('init_time',))
        assert a != b


class TestTheArgsAllowlistIsComplete:
    """A GET metric's key filters `request.args` through an allowlist. A
    parameter the dispatchers read but the allowlist omits would be invisible to
    the key — two different thresholds sharing one cached answer."""

    def test_every_arg_the_dispatchers_read_is_keyed_or_named(self):
        src = inspect.getsource(api)
        read = set(re.findall(r"args\.get\('([a-z_0-9]+)'", src))
        # Named explicitly in the spatial-metric key rather than via the
        # allowlist, so they are covered either way.
        named = {'metric', 'model', 'variable', 'min_lat', 'max_lat',
                 'min_lon', 'max_lon', 'init_time'}
        missed = read - named - set(api.SPATIAL_METRIC_CACHE_ARGS)
        assert missed == set(), (
            f'query parameters read but not in the cache key: {sorted(missed)} — '
            f'two different values would share one cached answer')

    def test_the_allowlist_is_not_vacuous(self):
        assert len(api.SPATIAL_METRIC_CACHE_ARGS) >= 5


class TestCacheHelpersAreSafeWithoutABackend:
    def test_reads_return_none_when_caching_is_off(self, monkeypatch):
        monkeypatch.setattr(api, 'cache', None)
        assert api._cache_get('anything') is None

    def test_writes_are_a_no_op_when_caching_is_off(self, monkeypatch):
        monkeypatch.setattr(api, 'cache', None)
        api._cache_set('anything', {'a': 1}, timeout=60)   # must not raise

    def test_a_failing_backend_does_not_fail_the_request(self, monkeypatch):
        class Angry:
            def get(self, *a, **k):
                raise RuntimeError('cache down')

            def set(self, *a, **k):
                raise RuntimeError('cache down')
        monkeypatch.setattr(api, 'cache', Angry())
        # A broken cache is a performance problem, not a correctness one: both
        # of these swallow and carry on.
        assert api._cache_get('k') is None
        api._cache_set('k', {'a': 1}, timeout=60)


class TestTheTruthFieldIsInTheVersion:
    """A score depends on the forecast AND the observation. A version derived
    only from the forecast registry misses a change to the truth field — which
    is exactly what happened on 2026-09-04, when `regridded_observation` was
    replaced with the rebuilt field and the registry was untouched."""

    def test_replacing_the_truth_field_changes_the_version(self):
        before = api._data_version_uncached(FakeCursor([ROW], obs=[dict(OBS)]))
        # The real swap: same row count, same timestamps, different values.
        after = api._data_version_uncached(
            FakeCursor([ROW], obs=[{**OBS, 's': 193378.266}]))
        assert before != after, (
            'a change to the observations does not move the data version — '
            'cached scores would keep serving pre-switch numbers')

    def test_the_row_count_alone_would_not_have_caught_it(self):
        # Why the checksum is the load-bearing part and not decoration: the swap
        # preserved every count and every timestamp.
        same_shape = api._data_version_uncached(
            FakeCursor([ROW], obs=[{**OBS, 's': 999.0}]))
        assert same_shape != api._data_version_uncached(
            FakeCursor([ROW], obs=[dict(OBS)]))

    def test_a_new_observation_source_changes_the_version(self):
        one = api._data_version_uncached(FakeCursor([ROW], obs=[dict(OBS)]))
        two = api._data_version_uncached(
            FakeCursor([ROW], obs=[dict(OBS), {**OBS, 'source': 'GPM'}]))
        assert one != two


class TestTheVersionIsStable:
    """A version that changes between identical requests is worse than no cache:
    every key is a miss, and the app pays the fingerprint query for nothing.

    This is not hypothetical. The first version of the observation fingerprint
    used `SUM(value)` on a double-precision column. PostgreSQL aggregates in
    parallel, so the addition order varies between identical queries and the last
    digits move — three consecutive calls produced three different versions, and
    the cache never hit once. `SUM(value::numeric)` is exact and
    order-independent.
    """

    def test_repeated_calls_agree(self):
        cur = FakeCursor([ROW], obs=[dict(OBS)])
        versions = {api._data_version_uncached(FakeCursor([ROW], obs=[dict(OBS)]))
                    for _ in range(5)}
        assert len(versions) == 1, f'version is unstable: {versions}'

    def test_the_fingerprint_query_uses_exact_arithmetic(self):
        # The guard for the real defect. A float SUM reintroduces it silently —
        # nothing fails, the cache just stops working.
        # Comment lines dropped: the comment explaining the defect necessarily
        # mentions the wrong form, which a naive substring check trips on.
        sql = '\n'.join(l for l in inspect.getsource(api._data_version_uncached)
                        .splitlines() if not l.strip().startswith('#'))
        assert 'SUM(value::numeric)' in sql, (
            'the observation fingerprint must sum as numeric; a float SUM is '
            'non-deterministic under parallel aggregation and makes every '
            'cache key a miss')
        assert 'SUM(value)' not in sql
