"""The analysis domain is configurable, and something checks it against the data.

The 0.5-degree box was written out twice — `TARGET_LAT_RANGE`/`TARGET_LON_RANGE`
in `regrid_members.py`, deciding what gets *loaded*, and `DEFAULT_REGION` in
`flask_api.py`, deciding what gets *served* to a request that names no box. One
fact on both sides of the ingest boundary, and the only thing keeping them equal
was a test that parsed one file's source text (`NEXT_STEPS.md` §76).

**The configurability is the easy half and the dangerous one.** A hard-coded
constant can only be wrong if somebody edits a file. An environment variable can
be wrong because of a shell — and a running API pointed at a box the database
does not hold answers every default-bbox request against the wrong region,
silently. So the tests that matter here are not "the override works"; they are
the ones about what happens when the override disagrees with the rows.
"""
import importlib
import os

import pytest

import domain
import flask_api as api


@pytest.fixture
def reload_domain(monkeypatch):
    """Re-import `domain` under a modified environment, then put it back.

    The values are read at import, which is deliberate — the domain describes
    data already on disk — so a test that wants a different one has to reload.
    """
    def configure(**env):
        for key, value in env.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        return importlib.reload(domain)

    yield configure
    # Other modules hold references to the module object, so the reload must be
    # undone with the real environment or every later test sees the override.
    for key in ('WEAVE_DOMAIN_LAT', 'WEAVE_DOMAIN_LON', 'WEAVE_DOMAIN_RESOLUTION'):
        os.environ.pop(key, None)
    importlib.reload(domain)


class TestTheDefault:
    def test_it_is_the_box_this_project_uses(self):
        assert domain.LAT_RANGE == (25.0, 45.0)
        assert domain.LON_RANGE == (-85.0, -65.0)
        assert domain.RESOLUTION == 0.5

    def test_it_reports_itself_as_the_default(self):
        assert domain.is_default() is True

    def test_the_bbox_shape_is_what_the_api_uses(self):
        assert domain.as_bbox() == {'min_lat': 25.0, 'max_lat': 45.0,
                                    'min_lon': -85.0, 'max_lon': -65.0}


class TestTheOverride:
    def test_an_environment_pair_replaces_the_default(self, reload_domain):
        d = reload_domain(WEAVE_DOMAIN_LAT='30,40', WEAVE_DOMAIN_LON='-80,-70')
        assert d.LAT_RANGE == (30.0, 40.0)
        assert d.LON_RANGE == (-80.0, -70.0)
        assert d.is_default() is False

    def test_an_empty_value_is_not_an_override(self, reload_domain):
        # A variable exported as "" is the usual way a shell says "unset".
        d = reload_domain(WEAVE_DOMAIN_LAT='')
        assert d.LAT_RANGE == d.DEFAULT_LAT_RANGE

    @pytest.mark.parametrize('bad', ['25', '25,45,65', 'north,south', '', ' '])
    def test_a_malformed_pair_either_raises_or_falls_back(self, reload_domain, bad):
        if bad.strip() == '':
            assert reload_domain(WEAVE_DOMAIN_LAT=bad).LAT_RANGE == (25.0, 45.0)
            return
        with pytest.raises(ValueError):
            reload_domain(WEAVE_DOMAIN_LAT=bad)

    def test_a_reversed_range_raises_rather_than_loading(self, reload_domain):
        """Starting with a *different* domain than was asked for is the one
        outcome worse than refusing to start."""
        with pytest.raises(ValueError):
            reload_domain(WEAVE_DOMAIN_LAT='45,25')

    def test_a_non_positive_resolution_raises(self, reload_domain):
        with pytest.raises(ValueError):
            reload_domain(WEAVE_DOMAIN_RESOLUTION='0')


class TestTheCheckAgainstTheData:
    """What makes the override safe. Routed cursors, both outcomes."""

    @staticmethod
    def _cursor(stored):
        from conftest import RoutedCursor
        return RoutedCursor({'FROM regridded_forecast_ens': [stored]})

    def test_it_is_safe_when_the_grid_matches_exactly(self):
        out = api._check_domain(self._cursor(
            {'min_lat': 25.0, 'max_lat': 45.0, 'min_lon': -85.0, 'max_lon': -65.0}))
        assert out['safe'] is True
        assert out['rows_loaded'] is True

    def test_a_partial_load_inside_the_box_is_safe(self):
        """A database still being filled is the normal state, not a fault.

        The fixture is exactly this — a 5x5 lattice at 35-37 N inside the real
        domain — and an equality test called it a mismatch. Flagging it would
        make the check noise on every development machine.
        """
        out = api._check_domain(self._cursor(
            {'min_lat': 35.0, 'max_lat': 37.0, 'min_lon': -76.0, 'max_lon': -74.0}))
        assert out['safe'] is True

    def test_data_outside_the_configured_box_is_not_safe(self):
        # The case the check exists for: rows that exist and are silently
        # clipped out of every default-bbox answer.
        out = api._check_domain(self._cursor(
            {'min_lat': 20.0, 'max_lat': 40.0, 'min_lon': -100.0, 'max_lon': -60.0}))
        assert out['safe'] is False
        assert out['stored']['min_lat'] == 20.0
        assert out['configured']['min_lat'] == 25.0

    def test_it_catches_a_box_clipped_on_one_side_only(self):
        # Latitudes fine, longitudes reaching past the western edge.
        out = api._check_domain(self._cursor(
            {'min_lat': 30.0, 'max_lat': 40.0, 'min_lon': -90.0, 'max_lon': -70.0}))
        assert out['safe'] is False

    def test_an_empty_database_is_not_a_mismatch(self):
        """A fresh database has nothing to disagree with.

        Reporting `safe: false` before anything is loaded would make the check
        noise on exactly the deployment that has not made a mistake yet.
        """
        out = api._check_domain(self._cursor(
            {'min_lat': None, 'max_lat': None, 'min_lon': None, 'max_lon': None}))
        assert out['safe'] is True
        assert out['rows_loaded'] is False

    def test_a_small_float_difference_is_not_a_mismatch(self):
        # Coordinates are float4 in places; an exact comparison would flag
        # rounding noise as a clipped domain.
        out = api._check_domain(self._cursor(
            {'min_lat': 24.9999999, 'max_lat': 45.0000001,
             'min_lon': -85.0000001, 'max_lon': -64.9999999}))
        assert out['safe'] is True


class TestItIsServed:
    def test_health_carries_the_domain(self, db_client):
        body = db_client.get('/api/health').get_json()
        assert 'domain' in body, sorted(body)
        assert set(body['domain']) >= {'configured', 'stored', 'safe',
                                       'from_default', 'rows_loaded'}

    def test_the_fixture_grid_agrees_with_the_configured_domain(self, db_client):
        """The fixture is regridded onto the same lattice, so this is `True`
        here — and it is the assertion that would fail first if someone changed
        the domain without reloading."""
        assert db_client.get('/api/health').get_json()['domain']['safe'] is True

    def test_a_mismatch_does_not_make_the_endpoint_unhealthy(self, db_client, monkeypatch):
        monkeypatch.setattr(api, '_check_domain', lambda cur: {
            'safe': False, 'from_default': False, 'rows_loaded': True,
            'resolution': 0.5, 'configured': {}, 'stored': {}})
        body = db_client.get('/api/health').get_json()
        assert body['status'] == 'healthy'
        assert body['domain']['safe'] is False
