"""The cyclone track endpoints, against real SQL.

`NEXT_STEPS.md` §37, `TC_TAB_DESIGN.md`. These run on the fixture database, so
they run in CI — which is the §26 lesson applied before the fact rather than
after: `test_run_registry.py`'s database tests resolved through a development
database and never ran in CI at all.

The fixture's cyclone scene is deliberately asymmetric. Its ECMWF run tracks
**4 of 51** members, because the denominator is the quantity most likely to be
got wrong (`TC_TAB_DESIGN.md` §5) and a fixture where every member tracked the
storm cannot catch it.
"""
import fixture_db as fx


class TestListingWhatIsLoaded:
    def test_it_lists_the_seeded_runs(self, db_client):
        body = db_client.get('/api/cyclones').get_json()
        assert fx.CY_STORM in body['storms']
        assert {r['centre'] for r in body['runs']} == {c for c, *_ in fx.CY_RUNS}

    def test_a_basin_filter_selects(self, db_client):
        assert db_client.get('/api/cyclones?basin=NA').get_json()['runs']

    def test_a_basin_the_data_does_not_have_returns_nothing_rather_than_everything(self, db_client):
        # An unmatched filter that silently returns the whole set is how a user
        # reads a Pacific storm as Atlantic.
        assert db_client.get('/api/cyclones?basin=WP').get_json()['runs'] == []


class TestTheTracks:
    def test_every_tracked_member_comes_back_as_its_own_polyline(self, db_client):
        body = db_client.get(
            f'/api/cyclone/tracks?storm={fx.CY_STORM}&centre=ecmf').get_json()
        tracked = dict((c, t) for c, _s, _n, t in fx.CY_RUNS)['ecmf']
        assert len(body['members']) == tracked
        assert all(len(m['points']) == len(fx.CY_LEADS) for m in body['members'])

    def test_it_reports_the_denominator_and_they_differ(self, db_client):
        """The point of the whole endpoint. 4 tracks out of 51 members means 47
        forecast no cyclone, and a response that only said "4" would let a
        reader take four lines for the ensemble."""
        body = db_client.get(
            f'/api/cyclone/tracks?storm={fx.CY_STORM}&centre=ecmf').get_json()
        assert body['nominal_members'] == 51
        assert body['tracked_members'] == 4
        assert body['tracked_members'] < body['nominal_members']

    def test_the_system_is_named_not_the_centre(self, db_client):
        # kwbc is a distribution node carrying NCEP and Canadian products, so
        # the system is what identifies the forecast (TC_DATA_ACCESS.md).
        body = db_client.get(
            f'/api/cyclone/tracks?storm={fx.CY_STORM}&centre=kwbc').get_json()
        assert body['system'] == 'GEFS'
        assert body['centre'] == 'kwbc'

    def test_the_best_track_comes_back_too(self, db_client):
        body = db_client.get(
            f'/api/cyclone/tracks?storm={fx.CY_STORM}&centre=ecmf').get_json()
        assert len(body['best_track']) == len(fx.CY_LEADS)

    def test_the_spread_grows_with_lead_as_the_fixture_builds_it(self, db_client):
        """The fixture fans members by index, so the spread at a lead is a
        number this test can state rather than measure with the code under
        test."""
        body = db_client.get(
            f'/api/cyclone/tracks?storm={fx.CY_STORM}&centre=ecmf').get_json()
        at = lambda lead: [p['lat'] for m in body['members']
                           for p in m['points'] if p['lead'] == lead]
        first, last = fx.CY_LEADS[1], fx.CY_LEADS[-1]
        assert (max(at(last)) - min(at(last))) > (max(at(first)) - min(at(first)))

    def test_an_unknown_storm_is_404_not_an_empty_success(self, db_client):
        r = db_client.get('/api/cyclone/tracks?storm=NOPE&centre=ecmf')
        assert r.status_code == 404

    def test_the_required_parameters_are_required(self, db_client):
        assert db_client.get('/api/cyclone/tracks?storm=X').status_code == 400
        assert db_client.get('/api/cyclone/tracks?centre=ecmf').status_code == 400
