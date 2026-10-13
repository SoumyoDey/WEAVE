"""One definition of what each variable is verified against.

The triple — forecast column, observation column, observation source — was
written out as an `if is_wind: ... else: ...` branch at **eight** sites in
`flask_api.py`, and the two reader-facing strings naming the sources were
written a ninth and tenth time in `AnalysisTab.jsx`. Adding a variable meant
finding every branch; worse, the UI could name a source the scoring code was
not using and nothing would notice, which is §19's defect exactly — four
spatial metrics confidently labelled `mm/h` for wind (`NEXT_STEPS.md` §75).

Three kinds of check here, and the third is the one that keeps mattering:

* the mapping is right, including the asymmetry that catches people — the UI's
  `wind` is not a stored variable;
* `/api/config` serves it, so the client can stop guessing;
* **no endpoint keeps its own copy.** A source scan, because the defect was
  never one wrong string; it was ten places that could disagree.
"""
import ast
import pathlib
import re

import pytest

import flask_api as api


HERE = pathlib.Path(__file__).resolve().parent
ANALYSIS_TAB = HERE.parent / 'src' / 'components' / 'AnalysisTab.jsx'
METRIC_PANEL = HERE.parent / 'src' / 'components' / 'MetricPanel.jsx'


@pytest.fixture(scope='module')
def config():
    api.app.config['TESTING'] = True
    r = api.app.test_client().get('/api/config')
    assert r.status_code == 200, r.data
    return r.get_json()


class TestTheMapping:
    def test_precipitation_verifies_against_imerg(self):
        assert api._sources_for('precipitation') == (
            'precipitation', 'precipitation', 'GPM_IMERG_V07B')

    def test_wind_verifies_against_era5_and_is_not_a_stored_variable(self):
        """The asymmetry worth a test of its own.

        The UI's `wind` is not a column: the grid holds `wind_u_10m` and
        `wind_v_10m`. Looking `wind` up directly returns nothing, reads as
        "this run has no wind", and silently disabled lead-time clamping once
        already.
        """
        fcst, obs, src = api._sources_for('wind')
        assert fcst == 'wind_u_10m'
        assert obs == 'wind_speed'
        assert src == 'ERA5_WIND'

    def test_an_unknown_variable_falls_back_rather_than_raising(self):
        # An endpoint reaching this has already failed `_bad_token`; answering
        # with the precipitation shape keeps the failure a 404 about missing
        # data rather than a 500.
        assert api._sources_for('nonsense') == (
            'nonsense', 'precipitation', 'GPM_IMERG_V07B')


class TestTheEndpointServesIt:
    def test_both_sources_are_named_with_labels(self, config):
        srcs = config['observation_sources']
        assert srcs['precipitation']['source'] == 'GPM_IMERG_V07B'
        assert srcs['wind']['source'] == 'ERA5_WIND'
        assert 'IMERG' in srcs['precipitation']['label']
        assert 'ERA5' in srcs['wind']['label']

    def test_the_served_sources_match_the_constant(self, config):
        for name, spec in api.OBSERVATION_SOURCES.items():
            assert config['observation_sources'][name]['source'] == spec['source']
            assert config['observation_sources'][name]['label'] == spec['label']

    def test_candidate_hours_are_served_per_variable(self, config):
        assert config['candidate_hours'] == api.CANDIDATE_LEAD_HOURS

    def test_precipitation_candidates_start_after_its_first_window(self, config):
        """+0h is not offered for an accumulation, and that is the reason the
        two lists differ at all."""
        assert 0 not in config['candidate_hours']['precipitation']
        assert 0 in config['candidate_hours']['wind']


class TestNoCopiesRemain:
    """The scan. Ten places could disagree; one should."""

    def test_the_backend_names_each_source_exactly_once(self):
        src = (HERE / 'flask_api.py').read_text()
        for literal in ('GPM_IMERG_V07B', 'ERA5_WIND'):
            hits = src.count(f"'{literal}'")
            assert hits == 1, (
                f'{literal} appears {hits} times; it belongs only in '
                f'OBSERVATION_SOURCES — use _sources_for(variable)')

    def test_the_scan_would_notice_a_new_branch(self):
        # Vacuity guard: the constant itself must be findable, or the test
        # above would pass on a file that had been renamed out from under it.
        src = (HERE / 'flask_api.py').read_text()
        assert 'OBSERVATION_SOURCES = {' in src
        assert 'def _sources_for(' in src

    def test_the_analysis_tab_does_not_name_a_source_itself(self):
        """It may keep the strings as a *fallback*; what it must not do is
        decide. The giveaway was a ternary on the variable choosing between two
        literals with no server value involved."""
        src = ANALYSIS_TAB.read_text()
        assert 'observationLabelFrom' in src, 'the tab should ask the server'
        # The literals survive only inside the fallback argument of that call.
        for literal in ('IMERG', 'ERA5'):
            for match in re.finditer(literal, src):
                window = src[max(0, match.start() - 400):match.start()]
                assert 'observationLabelFrom' in window, (
                    f'{literal} is named outside the fallback to '
                    f'observationLabelFrom')

    def test_the_metric_panel_asks_for_its_candidate_hours(self):
        src = METRIC_PANEL.read_text()
        assert 'candidateHoursFrom' in src
        assert 'useConfig' in src


def test_the_config_endpoint_still_needs_no_database(monkeypatch):
    """Adding these must not have given `/api/config` a query.

    It is the one endpoint that answers without the database, which is what
    makes it safe for the client to call on every page load.
    """
    def boom(*a, **k):
        raise AssertionError('/api/config touched the database')

    monkeypatch.setattr(api, 'get_db_connection', boom)
    api.app.config['TESTING'] = True
    r = api.app.test_client().get('/api/config')
    assert r.status_code == 200
    assert 'observation_sources' in r.get_json()


def test_the_module_still_parses():
    # Eight edits to one file; this is the cheap gate that the earlier scripted
    # passes over `flask_api.py` lacked when they corrupted it.
    assert ast.parse((HERE / 'flask_api.py').read_text())
