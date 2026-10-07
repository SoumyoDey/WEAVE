"""Tests for `/api/config` — `SYSTEM_DESIGN_PLAN.md` S4.

S4 asks for one backend source of truth exposed to the frontend, with the exit
criterion that adding a model, variable or metric is a **single-place change**.
The endpoint is only half of that. These tests are the other half, and they
guard two different joins:

1. **Declaration against behaviour.** `METRIC_REQUIREMENTS` says what each
   metric needs; the dispatchers are what actually read it. A table that drifts
   from the code it describes is worse than no table, because it reads as
   authoritative.
2. **Frontend against declaration.** `src/constants.js` restates these facts as
   `requiresHour`, `requiresThreshold` and `VALUE_UNITS`. Nothing has ever
   checked the two agree.

The second is the one that earns its keep. Every single-sided test in this repo
passed throughout the defects that motivated S4: four spatial metrics labelling
wind maps in `mm/h` (`CONSISTENCY_AUDIT.md` 6.1), and the UI's `wind` not being
a stored variable at all, which silently disabled lead-time clamping. Neither
side was internally inconsistent. They disagreed with each other.

Reading JavaScript from a Python test is unusual, so: the alternative is a jest
test that imports the backend, which is worse. The parse is deliberately narrow
— it reads literal `key:`, `requiresHour:` and `requiresThreshold:` fields out
of `METRIC_CONFIG`, and fails loudly if it finds nothing rather than passing
vacuously on a file it could not understand.
"""
import json
import pathlib
import re

import pytest

import flask_api as api


REPO = pathlib.Path(__file__).resolve().parent.parent
CONSTANTS = REPO / 'src' / 'constants.js'


@pytest.fixture(scope='module')
def config():
    api.app.config['TESTING'] = True
    response = api.app.test_client().get('/api/config')
    assert response.status_code == 200, response.data
    return response.get_json()


@pytest.fixture(scope='module')
def js():
    """The facts `src/constants.js` restates, parsed out of METRIC_CONFIG.

    Returns {key: {'hour': bool, 'threshold': bool}} plus the VALUE_UNITS map.
    """
    assert CONSTANTS.exists(), f'{CONSTANTS} is missing'
    src = CONSTANTS.read_text()

    start = src.index('export const METRIC_CONFIG')
    block = src[start:]
    entries = {}
    # Each entry opens with `key: 'name',` and carries the two flags before the
    # next entry's key. Splitting on the key keeps this independent of field
    # order and of whatever sits between them.
    chunks = re.split(r"\n\s*key:\s*'([a-z_]+)'", block)
    for name, body in zip(chunks[1::2], chunks[2::2]):
        hour = re.search(r'requiresHour:\s*(true|false)', body)
        thr = re.search(r'requiresThreshold:\s*(true|false)', body)
        assert hour and thr, f'{name}: could not read both flags from constants.js'
        entries[name] = {'hour': hour.group(1) == 'true',
                         'threshold': thr.group(1) == 'true'}

    units = dict(re.findall(r"^\s*(precipitation|wind):\s*'([^']+)',",
                            src[src.index('export const VALUE_UNITS'):],
                            re.M))

    # Guard the parse itself. A regex that silently matches nothing would make
    # every assertion below vacuously true — the exact failure mode
    # `NEXT_STEPS.md` records under "a refactor can hollow out a test".
    assert len(entries) >= 8, f'parsed only {len(entries)} metrics from constants.js'
    assert len(units) == 2, f'parsed {units} from VALUE_UNITS'
    return {'metrics': entries, 'units': units}


class TestTheDeclarationMatchesTheCode:
    """`METRIC_REQUIREMENTS` against what the dispatchers actually read."""

    def test_every_dispatched_metric_is_declared(self):
        assert set(api.METRIC_REQUIREMENTS) == set(api.SPATIAL_METRIC_REGISTRY)

    @pytest.mark.parametrize('key', sorted(api.SPATIAL_METRIC_REGISTRY))
    def test_the_threshold_flag_matches_the_dispatcher(self, key):
        """A metric declared to need a threshold must actually resolve one, and
        one declared not to must not — otherwise the UI shows a control that
        does nothing, or hides one the metric silently defaults."""
        import inspect
        source = inspect.getsource(api.SPATIAL_METRIC_REGISTRY[key])
        reads_threshold = '_resolve_threshold_rate' in source
        assert reads_threshold == api.METRIC_REQUIREMENTS[key]['threshold'], (
            f'{key}: declared threshold='
            f'{api.METRIC_REQUIREMENTS[key]["threshold"]} but the dispatcher '
            f'{"does" if reads_threshold else "does not"} resolve one')

    def test_only_ssr_takes_a_single_hour(self):
        """`hour` means one lead time rather than a range. It is why `ssr` is
        absent from the region suite, which aggregates over a range — so if a
        second metric ever becomes single-hour, COMPARE_REGION_METRICS needs
        revisiting at the same time."""
        single = {k for k, v in api.METRIC_REQUIREMENTS.items() if v['hour']}
        assert single == {'ssr'}
        assert 'ssr' not in api.COMPARE_REGION_METRICS


class TestTheFrontendAgrees:
    """`src/constants.js` against the endpoint. The join nothing checked."""

    def test_the_metric_lists_match(self, config, js):
        """A metric in the dispatch registry but not the selector is
        unreachable; one in the selector but not the registry 400s when
        picked."""
        assert set(js['metrics']) == set(config['metrics']), (
            f'only in constants.js: {set(js["metrics"]) - set(config["metrics"])}; '
            f'only in the backend: {set(config["metrics"]) - set(js["metrics"])}')

    @pytest.mark.parametrize('flag,js_key', [('requires_hour', 'hour'),
                                             ('requires_threshold', 'threshold')])
    def test_the_flags_match(self, config, js, flag, js_key):
        mismatched = {k: (config['metrics'][k][flag], js['metrics'][k][js_key])
                      for k in config['metrics']
                      if config['metrics'][k][flag] != js['metrics'][k][js_key]}
        assert not mismatched, f'{flag} disagrees (backend, frontend): {mismatched}'

    def test_the_units_match(self, config, js):
        """`/api/compare/skill` hard-coded `mm/h` for every variable once, which
        labelled an m/s wind speed in a precipitation unit. Two copies of the
        unit table is how that comes back."""
        assert js['units'] == {v: c['unit'] for v, c in config['variables'].items()}


class TestTheEndpointItself:
    def test_it_needs_no_database(self, monkeypatch):
        """It must answer while the pool is busy — a config call that queries is
        a config call that fails under the load it exists to describe, the same
        argument that moved /api/health off a COUNT(*)."""
        def explode(*a, **k):
            raise AssertionError('/api/config must not touch the database')
        monkeypatch.setattr(api, 'get_db_connection', explode)
        api.app.config['TESTING'] = True
        assert api.app.test_client().get('/api/config').status_code == 200

    def test_it_is_json_serialisable_as_served(self, config):
        json.dumps(config)

    def test_region_metrics_are_reported(self, config):
        assert set(config['region_metrics']) == set(api.COMPARE_REGION_METRICS)
        assert set(config['region_spread_metrics']) == \
            set(api.COMPARE_REGION_SPREAD_METRICS)

    @pytest.mark.parametrize('key', ['fbi', 'fss'])
    def test_the_metrics_with_no_map_are_named(self, config, key):
        """FSS is a property of a field at a lead time; FBI is a ratio of
        pooled counts that degenerates to 0/1/undefined at one cell. Both have
        a region value and no per-cell map, and the endpoint says so, so the UI
        need not carry the special case — and so a reader who finds one missing
        from the metric map list has an answer rather than a puzzle."""
        assert config['region_no_cell_value'] == ['fbi', 'fss']
        assert key not in config['metrics']
        assert key in config['region_metrics']

    def test_the_verification_window_is_served(self, config):
        from metrics import COMMON_VERIFICATION_WINDOW_HOURS
        assert config['verification_window_hours'] == COMMON_VERIFICATION_WINDOW_HOURS

    def test_unit_sensitive_matches_the_wind_overrides(self, config):
        """Which metrics have a wind-specific scale. Both sides already agree
        on {bias, mae, rmse, crps} and both say in a comment that the
        dimensionless ones deliberately have none — this stops that agreement
        being a coincidence."""
        flagged = {k for k, v in config['metrics'].items() if v['unit_sensitive']}
        assert flagged == set(api.WIND_PLOT_STYLE_OVERRIDES)
        assert flagged == {'bias', 'mae', 'rmse', 'crps'}
