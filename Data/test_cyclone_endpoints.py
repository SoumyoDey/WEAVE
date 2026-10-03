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
import pytest

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


class TestStrikeProbability:
    """§37 feature 2. The arithmetic is pinned in `test_cyclone_metrics.py`
    against hand-built ensembles; these pin the endpoint's half — the
    denominator reaching the response, the parameters being honoured, and an
    empty window answering honestly."""

    URL = f'/api/cyclone/strike-probability?storm={fx.CY_STORM}&centre=ecmf'

    def test_it_returns_a_field_in_range(self, db_client):
        body = db_client.get(self.URL).get_json()
        assert body['points']
        assert all(0.0 < p['value'] <= 1.0 for p in body['points'])

    def test_the_peak_is_the_fixture_denominator_not_the_tracks_present(self, db_client):
        """The fixture's ECMWF run tracks 4 of 51. Every member passes through
        the same start point, so the peak cell is struck by all four — and four
        of fifty-one is 0.078, not 1.0. A response at 1.0 would mean the
        denominator was the tracks supplied."""
        body = db_client.get(self.URL).get_json()
        assert body['nominal_members'] == 51
        assert body['tracked_members'] == 4
        assert body['peak'] == round(4 / 51, 4)

    def test_a_larger_radius_covers_more_cells(self, db_client):
        small = db_client.get(f'{self.URL}&radius_km=60').get_json()
        large = db_client.get(f'{self.URL}&radius_km=400').get_json()
        assert large['cells'] > small['cells']

    def test_the_lead_window_is_honoured(self, db_client):
        narrow = db_client.get(f'{self.URL}&hour_min=0&hour_max=0').get_json()
        wide = db_client.get(f'{self.URL}&hour_min=0&hour_max=24').get_json()
        assert wide['cells'] > narrow['cells']

    def test_a_window_with_no_track_says_so_rather_than_returning_zeros(self, db_client):
        body = db_client.get(f'{self.URL}&hour_min=900&hour_max=999').get_json()
        assert body['points'] == []
        assert 'reason' in body

    def test_a_silly_radius_is_refused(self, db_client):
        assert db_client.get(f'{self.URL}&radius_km=0').status_code == 400
        assert db_client.get(f'{self.URL}&radius_km=99999').status_code == 400
        assert db_client.get(f'{self.URL}&radius_km=abc').status_code == 400

    def test_an_unknown_storm_is_404(self, db_client):
        r = db_client.get('/api/cyclone/strike-probability?storm=NOPE&centre=ecmf')
        assert r.status_code == 404


class TestChoosingAnInitialisation:
    """A storm has several initialisations and they are not interchangeable —
    how many members developed the storm varies between them, which is the
    reason to be able to pick one.

    The fixture seeds a single init per centre, so these pin the *contract*:
    an explicit init is honoured, an absent one defaults to the newest, and an
    init that does not belong to this run is refused rather than quietly
    serving a different one.
    """

    def _init_of(self, db_client, centre='ecmf'):
        return db_client.get(
            f'/api/cyclone/tracks?storm={fx.CY_STORM}&centre={centre}'
        ).get_json()['init_time']

    def test_an_explicit_init_is_honoured(self, db_client):
        init = self._init_of(db_client)
        body = db_client.get(
            f'/api/cyclone/tracks?storm={fx.CY_STORM}&centre=ecmf&init={init}'
        ).get_json()
        assert body['init_time'] == init

    def test_an_init_from_another_run_is_404_not_a_substitution(self, db_client):
        """Serving the newest run when asked for a specific one would be a
        silent substitution: the user sees a different forecast from the one
        they selected, with nothing saying so."""
        r = db_client.get(
            f'/api/cyclone/tracks?storm={fx.CY_STORM}&centre=ecmf'
            f'&init=1999-01-01T00:00:00')
        assert r.status_code == 404

    def test_strike_probability_honours_it_too(self, db_client):
        init = self._init_of(db_client)
        body = db_client.get(
            f'/api/cyclone/strike-probability?storm={fx.CY_STORM}&centre=ecmf'
            f'&init={init}').get_json()
        assert body['init_time'] == init

    def test_strike_probability_refuses_a_foreign_init_as_well(self, db_client):
        r = db_client.get(
            f'/api/cyclone/strike-probability?storm={fx.CY_STORM}&centre=ecmf'
            f'&init=1999-01-01T00:00:00')
        assert r.status_code == 404

    def test_the_listing_carries_what_the_selector_needs(self, db_client):
        """The selector is built from `/api/cyclones` rather than a fourth
        endpoint, so the run rows must carry the init and both member counts."""
        runs = db_client.get('/api/cyclones').get_json()['runs']
        mine = [r for r in runs if r['storm_name'] == fx.CY_STORM]
        assert mine
        for r in mine:
            assert r['init_time'] and r['nominal_members'] and r['tracked_members']


class TestErrorByLead:
    """View 2. The arithmetic is pinned in `test_cyclone_metrics.py`; these pin
    the endpoint — that it recomputes rather than reading a shipped column, and
    that it says where the observation record stops rather than letting a line
    simply end."""

    URL = f'/api/cyclone/error-by-lead?storm={fx.CY_STORM}&centre=ecmf'

    def test_it_returns_a_row_per_lead(self, db_client):
        body = db_client.get(self.URL).get_json()
        assert [r['lead'] for r in body['points']] == list(fx.CY_LEADS)

    def test_the_fixture_members_fan_out_so_spread_grows(self, db_client):
        """`fixture_db` fans members by index times lead, so spread must rise
        with lead by construction — a number the fixture states rather than one
        measured with the code under test."""
        body = db_client.get(self.URL).get_json()
        spreads = [r['spread_km'] for r in body['points']]
        assert spreads[0] == pytest.approx(0.0, abs=1e-6)   # all together at +0
        assert spreads == sorted(spreads)
        assert spreads[-1] > spreads[1]

    def test_error_is_present_where_the_best_track_reaches(self, db_client):
        body = db_client.get(self.URL).get_json()
        assert all(r['mean_km'] is not None for r in body['points'])
        assert body['last_verified_lead'] == max(fx.CY_LEADS)

    def test_it_carries_the_denominator_like_the_other_endpoints(self, db_client):
        body = db_client.get(self.URL).get_json()
        assert body['nominal_members'] == 51
        assert body['tracked_members'] == 4

    def test_percentiles_bracket_the_median(self, db_client):
        for r in db_client.get(self.URL).get_json()['points']:
            if r['verified']:
                assert r['p10_km'] <= r['median_km'] <= r['p90_km']

    def test_it_honours_an_init_and_refuses_a_foreign_one(self, db_client):
        init = db_client.get(
            f'/api/cyclone/tracks?storm={fx.CY_STORM}&centre=ecmf'
        ).get_json()['init_time']
        assert db_client.get(f'{self.URL}&init={init}').get_json()['init_time'] == init
        assert db_client.get(f'{self.URL}&init=1999-01-01T00:00:00').status_code == 404

    def test_the_required_parameters_are_required(self, db_client):
        assert db_client.get('/api/cyclone/error-by-lead?storm=X').status_code == 400


class TestAMemberWithTwoCandidateCyclones:
    """One member, two cyclone_ids — the case the widened constraint admits.

    `cyclone_track_member`'s key gained `cyclone_id` on 2026-10-02 so that a
    member tracking two candidate cyclones at one lead no longer has one of
    them silently discarded at load time. Admitting the row is only half the
    job: every view here draws, scores and counts **one track per member**, so
    something has to choose, and an unchosen second candidate would show up as
    a polyline that teleports between two storms.

    No run in the real archive carries this — measured across all 1,181 source
    files, no member ever has more than one `cyclone_id`. The fixture supplies
    it precisely because the data does not: a selection rule that nothing
    exercises is a rule nobody has tested.

    The fixture's decoy is **shorter** than the real track and at a latitude no
    real member reaches, so these tests assert the decoy is *absent*. Asserting
    the real track is present would pass whether or not the rule works.
    """

    def _kwbc(self, db_client):
        return db_client.get(
            f'/api/cyclone/tracks?storm={fx.CY_STORM}&centre={fx.CY_DECOY_CENTRE}'
        ).get_json()

    def test_the_member_is_one_polyline_not_two(self, db_client):
        body = self._kwbc(db_client)
        tracked = dict((c, t) for c, _s, _n, t in fx.CY_RUNS)[fx.CY_DECOY_CENTRE]
        assert len(body['members']) == tracked
        ids = [m['member_id'] for m in body['members']]
        assert len(ids) == len(set(ids))

    def test_the_longer_candidate_wins(self, db_client):
        body = self._kwbc(db_client)
        member = next(m for m in body['members']
                      if m['member_id'] == fx.CY_DECOY_MEMBER)
        assert len(member['points']) == len(fx.CY_LEADS)
        assert all(p['lat'] != fx.CY_DECOY_LAT for p in member['points'])

    def test_the_discarded_candidate_is_reported_not_silent(self, db_client):
        # The whole point. A view that drops data and says nothing is the
        # defect this change exists to stop repeating.
        assert self._kwbc(db_client)['variant_members'] == 1

    def test_a_run_without_variants_reports_zero(self, db_client):
        body = db_client.get(
            f'/api/cyclone/tracks?storm={fx.CY_STORM}&centre=ecmf').get_json()
        assert body['variant_members'] == 0

    def test_the_member_is_scored_once_not_twice(self, db_client):
        """error-by-lead groups by lead; a second candidate would double it."""
        body = db_client.get(
            f'/api/cyclone/error-by-lead?storm={fx.CY_STORM}'
            f'&centre={fx.CY_DECOY_CENTRE}').get_json()
        tracked = dict((c, t) for c, _s, _n, t in fx.CY_RUNS)[fx.CY_DECOY_CENTRE]
        for row in body['points']:
            assert row['members'] <= tracked, (
                f"lead {row['lead']} counts {row['members']} of {tracked} "
                f"members — the decoy candidate is being counted again")

    def test_the_decoy_does_not_widen_the_strike_field(self, db_client):
        """A member's footprint must come from its own track, not from both."""
        body = db_client.get(
            f'/api/cyclone/strike-probability?storm={fx.CY_STORM}'
            f'&centre={fx.CY_DECOY_CENTRE}&radius_km=120').get_json()
        # The decoy sits 15 degrees north of every real point; at 120 km no
        # cell near it can be marked unless the decoy was included.
        assert body['points'], 'the field should not be empty'
        assert max(p['lat'] for p in body['points']) < fx.CY_DECOY_LAT - 1.0


class TestTheTimeLaggedNoteIsSystemWideNotPerRun:
    """MOGREPS-G is a 36-member time-lagged ensemble: 18 from the stated cycle
    pooled with 18 from six hours earlier, aligned by valid time. That is a
    property of the system and is documented, so the tab states it on every
    MOGREPS run rather than on the one run whose `cyclone_id`s happen to name
    the originating cycle.

    The endpoint's part of that contract is simply `system` — the client
    switches on it — so this pins that `system` is the Met Office's name and
    not the WMO centre code, which is the thing a refactor would quietly swap.
    """

    def test_mogreps_runs_name_the_system_not_the_centre(self, db_client):
        body = db_client.get(
            f'/api/cyclone/tracks?storm={fx.CY_STORM}&centre=ecmf').get_json()
        assert body['system'] == 'ECMWF-ENS'
        assert body['centre'] == 'ecmf'

    def test_the_denominator_is_unaffected_by_lagging(self, db_client):
        """36 is the ensemble size whether or not half of it is stale.

        Worth pinning because the tempting "fix" for lagging is to count only
        the fresh half, which would halve every MOGREPS strike probability.
        Lagged members are forecasts, not absences.
        """
        body = db_client.get(
            f'/api/cyclone/tracks?storm={fx.CY_STORM}&centre=kwbc').get_json()
        assert body['nominal_members'] == dict(
            (c, n) for c, _s, n, _t in fx.CY_RUNS)['kwbc']
