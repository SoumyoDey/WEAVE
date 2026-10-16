"""The slowest endpoint in the app was the one with no result cache.

`/api/spread-skill` sits immediately below `point_timeseries` in
`flask_api.py` and has cached since the caching existed. `point_timeseries`
never adopted it, so **every repeat of an identical request re-ran a 4.4 s
query** — and it is the endpoint the S3 load test showed capping throughput
at about 3 req/s (`NEXT_STEPS.md` §82).

That is §64's pattern in a new place: a mechanism gets applied where someone
noticed the problem, and the other half of the file keeps paying.

Measured after wiring it up: 10.1 s cold, then 0.64 s, 0.62 s, 0.68 s —
about **15× on repeats** — while a different point still costs 3.5 s, which
is the check that matters. A cache that returned the same answer for a
different point would be faster and wrong.
"""
import inspect

import flask_api as api


def _source():
    return inspect.getsource(api.point_timeseries)


def test_point_timeseries_consults_the_cache():
    """The defect itself: no read, so every request paid full price."""
    src = _source()
    assert '_cache_get' in src, (
        'point_timeseries does not read the cache — every repeat re-runs the '
        'query (§84)')


def test_point_timeseries_writes_to_the_cache():
    """A read without a write is a cache that never hits."""
    src = _source()
    assert '_cache_set' in src, 'point_timeseries never populates the cache'


def test_the_key_includes_everything_that_changes_the_answer():
    """A key missing a parameter serves one question's answer to another.

    `init_time` is the one with history — `_metric_cache_key`'s own docstring
    records that a key without it served one run's numbers for another, the
    exact cross-run error `migrate_init_time.py` exists to remove. `lat`/`lon`
    matter because this endpoint is per-point, and `radius` because it selects
    the search box.
    """
    src = _source()
    for part in ('model=', 'variable=', 'init_time=', 'lat=', 'lon=', 'radius='):
        assert part in src.split('_cache_get')[0].split('_metric_cache_key')[-1], (
            f'{part!r} is not in the cache key — two different requests would '
            f'share an entry')


def test_it_uses_its_own_namespace():
    """`spread-skill` keys on 'spread'; sharing that prefix would collide.

    Both endpoints key on the same model/variable/init/lat/lon/radius, so with
    a shared prefix one would serve the other's payload — a different shape
    entirely, and a bug that would look like data corruption rather than a
    caching mistake.
    """
    src = _source()
    assert "'point_timeseries'" in src or '"point_timeseries"' in src, (
        'point_timeseries shares a cache namespace with another endpoint')


def test_the_source_guard_can_fail():
    """A source scan that cannot fail is not a check (§28, §78, §79, §82).

    `inspect.getsource` returning something unexpected — a decorator wrapper
    rather than the function body — would make every assertion above pass
    vacuously. This pins that the source really is this endpoint's.
    """
    src = _source()
    assert 'point-timeseries' in src or 'Timeseries' in src, src[:200]
    assert 'nonexistent_marker_f81a' not in src
