#!/usr/bin/env python
"""`/api/forecast-hours` — the lead times a run actually holds.

The timeline used to read a constant: `for (let h = 0; h <= 360; h += 6)` in
`constants.js`, shared by all three models. That grid describes no model in this
archive. Measured against the loaded data (`NEXT_STEPS.md` §38): 40 of GEFS
precipitation's 80 steps are off it, **121 of UKMO's 155** are, and GEFS wind
reaches **+384 h** — so 24 hours of loaded data sat past the scrubber's top and
could not be selected at all.

**The point of these tests is that the lists differ per model.** A single
assertion that the endpoint returns *some* hours would pass against the old
constant, which is precisely the defect: a plausible answer that is the same for
everyone. The fixture seeds the real archive's shape in miniature — AIFS
6-hourly from +6, GEFS 3-hourly from +3, UKMO hourly from +0 — so a test can
tell the models apart.

`db_client` from conftest, not a hand-rolled client: conftest replaces the
psycopg2 pool with a MagicMock before `flask_api` is imported, so any other
client talks to a mock whose cursor iterates empty and every assertion here
would pass on `[]` (§28).
"""
import pytest

import fixture_db as fx


def hours_for(db_client, model, variable='precipitation'):
    r = db_client.get(f'/api/forecast-hours?model={model}&variable={variable}')
    assert r.status_code == 200, r.get_json()
    return r.get_json()


class TestTheHoursAreTheModelsOwn:
    """Each model's own cadence, not a shared grid."""

    def test_each_model_returns_its_seeded_cadence(self, db_client):
        for model in ('AIFS', 'GEFS', 'UKMO'):
            body = hours_for(db_client, model)
            assert body['hours'] == fx.PRECIP_HOURS[model], model

    def test_the_three_models_disagree(self, db_client):
        """The assertion the old constant would have failed.

        Under `ALL_HOURS` every model answered identically. If these three ever
        match again, something has gone back to a shared grid.
        """
        got = {m: tuple(hours_for(db_client, m)['hours'])
               for m in ('AIFS', 'GEFS', 'UKMO')}
        assert len(set(got.values())) == 3, got

    def test_a_three_hourly_model_includes_the_odd_steps(self, db_client):
        """GEFS's 3-hourly steps are half of what a 6-hourly grid can reach."""
        hours = hours_for(db_client, 'GEFS')['hours']
        off_grid = [h for h in hours if h % 6 != 0]
        assert off_grid, 'GEFS should carry steps a 6-hourly scrubber misses'
        assert 3 in hours

    def test_an_hourly_model_includes_steps_no_six_hourly_grid_has(self, db_client):
        hours = hours_for(db_client, 'UKMO')['hours']
        assert [1, 2, 3, 4, 5] == hours[1:6]

    def test_the_count_matches_the_list(self, db_client):
        body = hours_for(db_client, 'UKMO')
        assert body['count'] == len(body['hours'])


class TestItIsSortedAndDistinct:
    """The client indexes a slider straight into this array."""

    def test_ascending(self, db_client):
        for model in ('AIFS', 'GEFS', 'UKMO'):
            hours = hours_for(db_client, model)['hours']
            assert hours == sorted(hours), model

    def test_no_duplicates(self, db_client):
        # `regridded_forecast_ens` has one row per cell, so a missing DISTINCT
        # would return the same hour thousands of times and the slider would
        # have thousands of positions that all show the same field.
        for model in ('AIFS', 'GEFS', 'UKMO'):
            hours = hours_for(db_client, model)['hours']
            assert len(hours) == len(set(hours)), model


class TestVariablesAreSeparate:
    """Precipitation and wind do not share a record.

    On the real archive GEFS precipitation stops at +240 h while GEFS wind
    reaches +384 h. A response that ignored `variable` would give the union and
    offer precipitation lead times that hold nothing.
    """

    def test_wind_returns_its_own_cadence(self, db_client):
        body = hours_for(db_client, 'GEFS', 'wind_u_10m')
        assert body['hours'] == fx.WIND_HOURS['GEFS']

    def test_wind_and_precipitation_differ(self, db_client):
        precip = hours_for(db_client, 'GEFS', 'precipitation')['hours']
        wind   = hours_for(db_client, 'GEFS', 'wind_u_10m')['hours']
        assert precip != wind

    def test_the_variable_is_echoed_back(self, db_client):
        body = hours_for(db_client, 'AIFS', 'wind_v_10m')
        assert body['variable'] == 'wind_v_10m'
        assert body['model'] == 'AIFS'


class TestEmptyAndInvalid:
    def test_a_variable_this_run_lacks_returns_an_empty_list_not_an_error(self, db_client):
        """An honest empty, with `count` saying so.

        A 404 here would be wrong: the run exists and the request is
        well-formed, there is simply nothing stored for that pair. The caller
        needs to tell that from a bad request, which is what `count` is for.
        """
        r = db_client.get('/api/forecast-hours?model=AIFS&variable=temperature_2m')
        assert r.status_code == 200
        body = r.get_json()
        assert body['hours'] == [] and body['count'] == 0

    def test_a_bad_token_is_refused(self, db_client):
        r = db_client.get("/api/forecast-hours?model=AIFS'; DROP TABLE x--")
        assert r.status_code == 400

    def test_an_unknown_model_is_404_not_a_500(self, db_client):
        """This test was written first and caught a real crash.

        `_resolve_init_time` returns None when no run is loaded for a model,
        and the endpoint called `.isoformat()` on it — a 500. 404 is the right
        answer and is distinct from the empty-list case above: "no such run" is
        not "this run holds nothing for that variable", and a client that
        cannot tell them apart cannot tell a typo from a gap.
        """
        r = db_client.get('/api/forecast-hours?model=NOPE')
        assert r.status_code == 404, r.get_json()
        assert 'error' in r.get_json()

    def test_the_resolved_init_time_is_reported(self, db_client):
        """So a caller can tell which run the list describes."""
        body = hours_for(db_client, 'AIFS')
        assert body['init_time'].startswith(fx.INIT_TIME.strftime('%Y-%m-%d'))
