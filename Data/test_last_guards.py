"""The last guards, reached by calling the helper that owns them.

Everything here is one `continue` or one `return []` three or four layers inside
a helper. Driving them through HTTP would mean building a fake database that
satisfies every layer above first, and the test would then be about the
scaffolding. So these call the function directly and hand it exactly the awkward
shape the guard exists for.

Two branches turned out to be unreachable, and that is written up at the bottom
rather than papered over — an unreachable branch is a finding, not a coverage
problem.

Run:  ~/miniconda3/envs/afw/bin/python -m pytest Data -q
"""
from datetime import datetime, timedelta

import pytest

import flask_api as api


INIT = datetime(2025, 9, 8, 0, 0, 0)
BOX = {"min_lat": 35, "max_lat": 37, "min_lon": -77, "max_lon": -74}
BOX_QS = "min_lat=35&max_lat=37&min_lon=-77&max_lon=-74"
RUN_ROW = {"run_id": 1, "initialization_time": INIT}


class Queue:
    """A cursor that answers each execute from a queue, in order."""

    def __init__(self, *batches):
        self.batches = list(batches)
        self.executed = []
        self._rows = []

    def execute(self, sql, params=None):
        self.executed.append(" ".join(sql.split()))
        self._rows = self.batches.pop(0) if self.batches else []

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


def fcst_row(hour, lat=36.0, lon=-75.5, mean=1.0, std=0.5):
    return {"forecast_hour": hour, "latitude": lat, "longitude": lon,
            "mean_value": mean, "std_dev": std}


def obs_row(hour, lat=36.0, lon=-75.5, value=1.0):
    return {"obs_time": INIT + timedelta(hours=hour), "latitude": lat,
            "longitude": lon, "obs_val": value}


class TestSsrMapSkipsACellWithoutTheRequestedHour:
    def test_a_cell_scored_at_other_lead_times_is_skipped(self, monkeypatch):
        """The map asks for one lead time. A cell can have cases at others and
        not at that one — the observation record ends mid-run, so the later
        hours simply are not there — and the cell has to drop out rather than
        contribute a None."""
        monkeypatch.setattr(api, "_member_cases_by_cell", lambda *a, **k: {
            (36.0, -75.5): {12: {"spread_sq": 0.25, "spread": 0.5,
                                 "error": 0.5, "n_members": 3}},
            (36.5, -75.0): {6:  {"spread_sq": 0.25, "spread": 0.5,
                                 "error": 0.5, "n_members": 3}},
        })
        pts = api._compute_ssr_points(None, "AIFS", "precipitation", INIT, 6,
                                      35, 37, -77, -74)
        assert [p["lat"] for p in pts] == [36.5], "the +12h-only cell was not skipped"


class TestThePairsFetchGivesUpEarly:
    ARGS = ("AIFS", "precipitation", 35, 37, -77, -74)

    def test_no_forecast_hour_falls_inside_the_requested_range(self):
        """Rows exist, but all at lead times outside the window. Returning {}
        here is what stops every metric downstream from iterating nothing and
        reporting a confident zero."""
        cur = Queue([RUN_ROW], [fcst_row(240)])
        with api.app.test_request_context("/"):
            assert api._fetch_fcst_obs_pairs_spatial(
                cur, *self.ARGS, hour_min=0, hour_max=18) == {}

    def test_no_observation_covers_any_of_them(self):
        cur = Queue([RUN_ROW], [fcst_row(6), fcst_row(12)], [])
        with api.app.test_request_context("/"):
            assert api._fetch_fcst_obs_pairs_spatial(
                cur, *self.ARGS, hour_min=0, hour_max=18) == {}


class TestPerCellMetricsSkipAnEmptyCell:
    """`pairs` can carry a cell with an empty list — the join matched the cell
    but no lead time survived the window check. Both of these iterate `entries`
    immediately, so the guard is what keeps a statistics call off an empty
    sequence."""

    @pytest.mark.parametrize("fn", ["_compute_crps_points_rf",
                                    "_compute_brier_points_rf"])
    def test_a_cell_with_no_entries_is_skipped(self, monkeypatch, fn):
        monkeypatch.setattr(api, "_fetch_fcst_obs_pairs_spatial",
                            lambda *a, **k: {(36.0, -75.5): [],
                                             (36.5, -75.0): [(6, 1.0, 0.5, 1.0)]})
        pts = getattr(api, fn)(None, "AIFS", "precipitation", 35, 37, -77, -74,
                               0, 18, threshold_rate=0.5)
        assert all(p["lat"] != 36.0 for p in pts), "the empty cell produced a point"


class TestTheDisplayPathDropsWhatItCannotDraw:
    """/api/forecast-data serves the map, so it reads a table whose query does
    not filter NULLs — a display wants every cell it can draw. The three guards
    below are what keep an undrawable cell out of the response."""

    def test_a_cell_with_no_record_at_the_requested_hour_is_dropped(self, client, fake_db):
        # Rows at +6h only; ask for +12h. The rate series has no entry, so `rec`
        # is None and the cell is skipped rather than sent as null.
        fake_db({"FROM ensemble_statistics": [
                     {"lat": 36.0, "lon": -75.5, "mean_value": 1.0,
                      "std_dev": 0.5, "forecast_hour": 6}],
                 "FROM forecast_runs": [RUN_ROW]})
        r = client.get("/api/forecast-data?model=AIFS&variable=precipitation"
                       "&hour=12&member=mean")
        assert r.status_code == 200
        assert r.get_json() == []

    def test_a_member_row_with_a_null_value_is_dropped(self, client, fake_db):
        fake_db({"FROM forecast_data": [
                     {"lat": 36.0, "lon": -75.5, "value": None, "forecast_hour": 6},
                     {"lat": 36.5, "lon": -75.0, "value": 2.0, "forecast_hour": 6}],
                 "FROM forecast_runs": [RUN_ROW]})
        r = client.get("/api/forecast-data?model=AIFS&variable=precipitation"
                       "&hour=6&member=0")
        assert r.status_code == 200
        assert all(p["lat"] != 36.0 for p in r.get_json())

    def test_a_member_cell_with_no_record_at_the_hour_is_dropped(self, client, fake_db):
        fake_db({"FROM forecast_data": [
                     {"lat": 36.0, "lon": -75.5, "value": 2.0, "forecast_hour": 6}],
                 "FROM forecast_runs": [RUN_ROW]})
        r = client.get("/api/forecast-data?model=AIFS&variable=precipitation"
                       "&hour=12&member=0")
        assert r.status_code == 200
        assert r.get_json() == []


class TestUnknownVariableIsA404:
    def test_a_variable_missing_from_the_table_names_itself(self, client, fake_db):
        # The run resolves; the variable lookup finds nothing. Unguarded this
        # indexed None; the contract is a 404 that says which variable.
        fake_db({"FROM forecast_runs": [RUN_ROW]})
        r = client.get(f"/api/spatial-metric?metric=mae&model=AIFS"
                       f"&variable=precipitation&{BOX_QS}")
        assert r.status_code == 404
        assert "not found" in r.get_json()["error"]


class TestSpatialAgreementServesFromTheCache:
    def test_a_cached_render_short_circuits_before_any_query(self, client, monkeypatch):
        """The cache key is the request shape, and a hit returns before the
        connection is even taken. Asserting that no query ran is the point —
        Cartopy plus the pool is the expensive half of this endpoint."""
        stored = {"image": "cached-png", "n_models": 2}
        monkeypatch.setattr(api, "_cache_get", lambda key: stored)
        def must_not_run():
            raise AssertionError("a cache hit still opened a connection")
        monkeypatch.setattr(api, "get_db_connection", must_not_run)

        r = client.post("/api/compare/spatial-agreement", json={
            "models": ["AIFS", "GEFS"], "variable": "precipitation",
            "hour": 6, **BOX})
        assert r.status_code == 200
        assert r.get_json() == stored


class TestTheCategoricalPointPathBailsOut:
    CENTRE = "ORDER BY POWER"

    def test_no_forecast_rows_at_all(self, client, fake_db):
        fake_db({self.CENTRE: [{"latitude": 36.0, "longitude": -75.5}],
                 "FROM regridded_forecast_ens": [],
                 "FROM forecast_runs": [RUN_ROW]})
        r = client.post("/api/categorical-metrics", json={
            "model": "AIFS", "variable": "precipitation", "lat": 36.0, "lon": -75.5})
        assert r.status_code == 404
        assert "No forecast data" in r.get_json()["error"]

    def test_rows_exist_but_none_at_the_centre_cell(self, client, fake_db):
        """The box can catch neighbours while the clicked cell itself has
        nothing. The point metrics describe the centre cell, so there is no
        answer to give — and quietly scoring a neighbour instead would be the
        worst outcome."""
        fake_db({self.CENTRE: [{"latitude": 36.0, "longitude": -75.5}],
                 "FROM regridded_forecast_ens": [fcst_row(6, lat=35.0, lon=-76.0)],
                 "FROM forecast_runs": [RUN_ROW]})
        r = client.post("/api/categorical-metrics", json={
            "model": "AIFS", "variable": "precipitation",
            "lat": 36.0, "lon": -75.5, "box_cells": 5})
        assert r.status_code == 404


class TestTheFssFieldSkipsCellsItCannotUse:
    """FSS is accumulated over every cell in the box, so it meets cells the
    centre-cell metrics never see: one with no record at this hour, one with no
    observation covering its window."""

    def test_a_box_with_ragged_coverage_still_produces_a_score(self, db_client):
        # Real data: the fixture's observations stop at +12h while forecasts run
        # to +36h, so a wide box at a late hour has exactly this raggedness.
        r = db_client.post('/api/categorical-metrics', json={
            'model': 'AIFS', 'variable': 'precipitation',
            'lat': 36.0, 'lon': -75.0, 'hour_min': 0, 'hour_max': 36,
            'threshold_mm_6h': 9.0, 'box_cells': 5, 'fss_window': 3})
        assert r.status_code == 200
        assert r.get_json()['summary']['fss'] is not None

    def test_a_neighbour_missing_the_hour_or_the_observation_is_skipped(self, client, fake_db):
        """Wind, because it is instantaneous: a single observation at the valid
        time covers the record, so a fake cursor can produce a scorable centre
        cell without also satisfying a 6 h precipitation window.

        The box holds three cells. One neighbour has no record at +6h, the other
        has a record but no observation. Both drop out of the FSS field while the
        centre cell still scores — which is the whole point of accumulating FSS
        separately from the contingency table.
        """
        centre, no_record, no_obs = (36.0, -75.5), (36.5, -75.5), (35.5, -75.5)
        fake_db({
            "ORDER BY POWER": [{"latitude": centre[0], "longitude": centre[1]}],
            "FROM regridded_forecast_ens": [
                fcst_row(0, *centre, mean=12.0), fcst_row(6, *centre, mean=12.0),
                fcst_row(0, *no_record, mean=12.0),          # nothing at +6h
                fcst_row(0, *no_obs, mean=12.0), fcst_row(6, *no_obs, mean=12.0),
            ],
            "FROM regridded_observation": [
                obs_row(0, *centre, value=12.0), obs_row(6, *centre, value=12.0),
                obs_row(0, *no_record, value=12.0),
                # `no_obs` deliberately absent from the observation table.
            ],
            "FROM forecast_runs": [RUN_ROW],
        })
        r = client.post("/api/categorical-metrics", json={
            "model": "AIFS", "variable": "wind", "lat": centre[0], "lon": centre[1],
            "hour_min": 0, "hour_max": 18, "threshold_ms": 5, "box_cells": 3})
        assert r.status_code == 200, r.get_json()
        # The centre cell scored, so the endpoint got past its own guards.
        assert r.get_json()["hours"], "the centre cell never scored"

    def test_the_region_box_helper_skips_the_same_two_shapes(self):
        """Directly, because the guards are per-cell inside a per-hour loop and
        an endpoint cannot address one cell of it."""
        cur = Queue(
            [RUN_ROW],
            # Two cells at +6h, one at +12h.
            [fcst_row(6, lat=36.0), fcst_row(6, lat=36.5), fcst_row(12, lat=36.0)],
            # Observations for one cell only, so the other is skipped, and
            # nothing at all for +12h, so that whole hour drops out.
            [obs_row(h, lat=36.0) for h in (0, 1, 2, 3, 4, 5, 6)],
        )
        with api.app.test_request_context("/"):
            out = api._categorical_hours_for_box(
                cur, "AIFS", "precipitation", "precipitation", "GPM_IMERG_V07B",
                35, 37, -77, -74, 0, 18, 0.5)
        # Whatever survives, no hour may claim more points than it had cells.
        for hour in out:
            assert hour["n_pts"] <= 2


class TestSingleMetricPointsDeclinesWhatItCannotMap:
    def test_a_metric_with_no_per_cell_value_returns_no_points(self):
        """`fss` is deliberately absent from the per-cell registry: it is a
        property of a whole field at a lead time, so there is no per-cell value
        to map. Returning [] is what makes the region view draw no map for it
        instead of a wrong one."""
        assert "fss" in api.COMPARE_REGION_NO_CELL_VALUE
        assert "fss" not in api.COMPARE_REGION_METRIC_FNS
        assert api._single_metric_points(
            None, "AIFS", "precipitation", "fss",
            35, 37, -77, -74, 0, 18, threshold_rate=0.5) == []

    def test_correlation_needs_a_run_and_says_nothing_without_one(self):
        cur = Queue([])          # no forecast_runs row
        with api.app.test_request_context("/"):
            assert api._single_metric_points(
                cur, "AIFS", "precipitation", "correlation",
                35, 37, -77, -74, 0, 18, threshold_rate=None) == []


class TestTheDifferenceMapContainsARenderFailure:
    def test_a_failing_render_is_a_500_that_leaks_nothing(self, prod_client,
                                                          fake_db, monkeypatch):
        """The render runs after the connection is released, so its handler is
        the only thing between a Cartopy failure and a half-written response.

        The per-cell metric is stubbed rather than seeded: getting a real join to
        match through a fake cursor means satisfying the 6 h observation window
        as well, and this test is about the render handler, not the join.
        """
        fake_db({"FROM forecast_runs": [RUN_ROW]})
        monkeypatch.setitem(
            api.COMPARE_REGION_METRIC_FNS, "mae",
            lambda *a, **k: [{"lat": la, "lon": lo, "value": 1.5}
                             for la in (35.5, 36.0, 36.5) for lo in (-76.0, -75.5)])

        def boom(*a, **k):
            raise RuntimeError("Agg: could not open display")
        monkeypatch.setattr(api, "_render_metric_map_png", boom)

        r = prod_client.post("/api/compare/spatial-diff", json={
            "model_a": "AIFS", "model_b": "GEFS", "metric": "mae",
            "variable": "precipitation", **BOX})
        assert r.status_code == 500
        assert "Agg" not in str(r.get_json())
        assert "could not open display" not in str(r.get_json())


class TestTwoBranchesThatCannotBeReached:
    """Not coverage gaps — dead code, with a reason.

    Both are `else` arms guarding against a state the surrounding logic makes
    impossible. Left in place because they are cheap and defensible, but
    documented here so the next person measuring coverage does not spend an
    afternoon on them the way this one did.
    """

    def test_compare_skill_always_has_at_least_one_observed_hour(self, db_client):
        """flask_api.py ~2521, the `else` that reports no observations.

        `cases_of` only ever gains a model whose `by_hour` is non-empty, and the
        endpoint returns early when `cases_of` is empty. So by the time the
        warning is built, `obs_hours_all` has at least one hour in it and the
        else arm is unreachable. The empty case is answered earlier, by the
        `No forecast data found` return.
        """
        d = db_client.post('/api/compare/skill', json={
            'models': ['AIFS'], 'variable': 'precipitation',
            'lat': 36.0, 'lon': -75.0, 'hour_min': 0, 'hour_max': 36}).get_json()
        assert d['obs_hours'], "if this is ever empty the else arm becomes live"
        assert 'Observations cover' in d['obs_warning']

    def test_the_region_composite_always_has_an_fss_when_it_has_a_csi(self, db_client):
        """flask_api.py ~3379, the composite renormalised without FSS.

        In the region path both come from the same per-hour loop: FSS's
        denominator is the sum of squared event fractions, and CSI's denominator
        is the count of hits, misses and false alarms. Either there is an event
        somewhere — and then both are defined — or there is not, and then both
        are None. So the region composite never takes the renormalised arm.

        The POINT endpoint genuinely needs both, because there FSS is gated on
        `box_cells > 1` independently of whether any event exists. That is the
        difference, and it is why the same-looking branch is live in one place
        and dead in the other.
        """
        for threshold in (9.0, 10_000.0):
            d = db_client.post('/api/region-categorical-metrics', json={
                'model': 'AIFS', 'variable': 'precipitation', **BOX,
                'hour_min': 0, 'hour_max': 36,
                'threshold_mm_6h': threshold}).get_json()
            s = d['summary']
            assert (s['csi'] is None) == (s['fss'] is None), (
                threshold, "csi and fss became independent — 3379 is now live")
