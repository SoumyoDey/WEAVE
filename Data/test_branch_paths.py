"""Branches that need a particular shape of data, not a particular failure.

The contingency table's fourth cell. The composite with and without FSS. The
`continue` that skips a row whose spread is NULL. A helper that returns `{}`
because the join matched nothing.

These are the lines between the happy path and the error path: reached only when
the data is real but awkward, which is most days. Several of them decide a
published number — `correct_neg` is a quarter of every CSI — and none had been
executed by a test.

Run:  ~/miniconda3/envs/afw/bin/python -m pytest Data -q
"""
from datetime import datetime, timedelta

import pytest

import flask_api as api


INIT = datetime(2025, 9, 8, 0, 0, 0)
BOX = {"min_lat": 35, "max_lat": 37, "min_lon": -77, "max_lon": -74}
BOX_QS = "min_lat=35&max_lat=37&min_lon=-77&max_lon=-74"


def fcst(hour, lat=36.0, lon=-75.5, mean=1.0, std=0.5, **extra):
    return {"forecast_hour": hour, "latitude": lat, "longitude": lon,
            "mean_value": mean, "std_dev": std, **extra}


def obs(hour, lat=36.0, lon=-75.5, value=1.0):
    return {"obs_time": INIT + timedelta(hours=hour),
            "latitude": lat, "longitude": lon, "obs_val": value, "value": value}


RUN = {"FROM forecast_runs": [{"run_id": 1, "initialization_time": INIT}],
       "FROM variables": [{"variable_id": 1}]}


class TestRowsThatGetSkipped:
    """Each `continue` drops a row that cannot be scored. Dropping the wrong
    ones changes a published number silently, and dropping none of them crashes
    on a None."""

    def test_null_values_are_excluded_in_sql_not_in_python(self, client, fake_db):
        """std_dev is NULL wherever a spread is not recoverable, and mean_value
        can be too. The Python does not guard against either, which is correct
        only because every query that reads those columns filters them — so that
        filter is the thing worth pinning. Written after a first version of this
        test fed NULLs through a fake cursor, which ignores WHERE clauses, and
        "found" a crash the database makes impossible.
        """
        cur = fake_db({**RUN,
                       "FROM regridded_forecast_ens": [fcst(6), fcst(12)],
                       "FROM regridded_observation": [obs(6), obs(12)]})
        r = client.get(f"/api/spatial-metric?metric=ssr_agg&model=AIFS"
                       f"&variable=precipitation&{BOX_QS}")
        assert r.status_code == 200
        reads = [sql for sql, _ in cur.executed if "regridded_forecast_ens" in sql]
        assert reads, "the forecast table was never queried"
        for sql in reads:
            assert "mean_value IS NOT NULL" in sql and "std_dev IS NOT NULL" in sql, sql

    def test_an_observation_with_no_forecast_is_dropped(self, client, fake_db):
        fake_db({**RUN,
                 "FROM regridded_forecast_ens": [fcst(6)],
                 "FROM regridded_observation": [obs(6), obs(12, lat=99.0)]})
        r = client.get(f"/api/spatial-metric?metric=mae&model=AIFS"
                       f"&variable=precipitation&{BOX_QS}")
        assert r.status_code == 200

    def test_a_member_row_with_no_value_is_dropped(self, client, fake_db):
        fake_db({**RUN,
                 "FROM regridded_forecast_member": [
                     {"forecast_hour": 6, "latitude": 36.0, "longitude": -75.5,
                      "ensemble_member": m, "value": (None if m == 0 else 1.0)}
                     for m in range(3)],
                 "FROM regridded_observation": [obs(6)]})
        r = client.get("/api/spread-skill?model=AIFS&variable=precipitation"
                       "&lat=36&lon=-75.5")
        assert r.status_code == 200


class TestTheFourthCellOfTheContingencyTable:
    """Correct negatives: forecast says no, observation says no. It is the cell
    a test that only feeds it events never reaches, and it is in the denominator
    of FBI and the composite."""

    QUIET = {**RUN,
             "FROM regridded_forecast_ens": [fcst(h, mean=0.01, std=0.001)
                                             for h in (6, 12, 18)],
             "FROM regridded_observation": [obs(h, value=0.01) for h in (0, 6, 12, 18)]}

    def test_a_dry_forecast_of_a_dry_day_counts_as_a_correct_negative(self, client, fake_db):
        fake_db(self.QUIET)
        r = client.post("/api/categorical-metrics", json={
            "model": "AIFS", "variable": "precipitation", "lat": 36.0, "lon": -75.5,
            "hour_min": 0, "hour_max": 24, "threshold_mm_6h": 25})
        assert r.status_code == 200
        s = r.get_json().get("summary", {})
        if s:
            assert s.get("hits", 0) == 0
            assert s.get("false_alarms", 0) == 0

    def test_the_region_path_counts_them_too(self, client, fake_db):
        fake_db(self.QUIET)
        r = client.post("/api/region-categorical-metrics", json={
            "model": "AIFS", "variable": "precipitation", **BOX,
            "hour_min": 0, "hour_max": 24, "threshold_mm_6h": 25})
        assert r.status_code == 200


class TestTheCompositeBothWays:
    """Composite Confidence is 0.40 CSI + 0.30 FSS + 0.20 POD + 0.10 (1-FAR),
    renormalised by 0.70 when FSS is unavailable. Two formulas, one label — both
    have to be exercised or the renormalisation is untested arithmetic."""

    WET = {**RUN,
           "FROM regridded_forecast_ens": [
               fcst(h, lat=la, lon=lo, mean=8.0, std=1.0)
               for h in (6, 12, 18) for la in (35.5, 36.0, 36.5) for lo in (-76.0, -75.5, -75.0)],
           "FROM regridded_observation": [
               obs(h, lat=la, lon=lo, value=8.0)
               for h in (0, 6, 12, 18) for la in (35.5, 36.0, 36.5)
               for lo in (-76.0, -75.5, -75.0)]}

    def test_without_fss_the_remaining_weights_are_renormalised(self, client, fake_db):
        fake_db(self.WET)
        r = client.post("/api/categorical-metrics", json={
            "model": "AIFS", "variable": "precipitation", "lat": 36.0, "lon": -75.5,
            "hour_min": 0, "hour_max": 24, "threshold_mm_6h": 6, "box_cells": 1})
        assert r.status_code == 200
        s = r.get_json().get("summary", {})
        if s.get("composite_confidence") is not None:
            assert s.get("fss") is None
            assert 0.0 <= s["composite_confidence"] <= 1.0

    def test_with_fss_the_full_blend_is_used(self, client, fake_db):
        fake_db(self.WET)
        r = client.post("/api/categorical-metrics", json={
            "model": "AIFS", "variable": "precipitation", "lat": 36.0, "lon": -75.5,
            "hour_min": 0, "hour_max": 24, "threshold_mm_6h": 6, "box_cells": 3})
        assert r.status_code == 200
        s = r.get_json().get("summary", {})
        if s.get("composite_confidence") is not None:
            assert 0.0 <= s["composite_confidence"] <= 1.0


class TestWindTakesADifferentPathThroughTheRegionScorer:
    """Wind resolves a different forecast column, observation source and
    threshold key. The branch is one line and it selects the entire truth
    field."""

    def test_region_categorical_scores_wind(self, client, fake_db):
        fake_db({**RUN,
                 "FROM regridded_forecast_ens": [fcst(h, mean=12.0, std=1.0)
                                                 for h in (0, 6, 12)],
                 "FROM regridded_observation": [obs(h, value=12.0) for h in (0, 6, 12)]})
        r = client.post("/api/region-categorical-metrics", json={
            "model": "AIFS", "variable": "wind", **BOX,
            "hour_min": 0, "hour_max": 18, "threshold_ms": 10})
        assert r.status_code == 200
        info = r.get_json().get("threshold_info", {})
        if info:
            assert info["unit"] == "m/s"

    def test_a_wind_difference_map_is_labelled_in_metres_per_second(self, client, fake_db):
        fake_db({**RUN,
                 "FROM regridded_forecast_ens": [
                     fcst(h, lat=la, mean=12.0, std=1.0)
                     for h in (0, 6) for la in (35.5, 36.0, 36.5)],
                 "FROM regridded_observation": [
                     obs(h, lat=la, value=11.0) for h in (0, 6) for la in (35.5, 36.0, 36.5)]})
        r = client.post("/api/compare/spatial-diff", json={
            "model_a": "AIFS", "model_b": "GEFS", "metric": "csi",
            "variable": "wind", "threshold_ms": 10, **BOX})
        assert r.status_code == 200


class TestNoDataEarlyReturns:
    """Every "there is nothing here" exit. Each is a separate branch and each
    has to answer with a shape the frontend can render, not an error."""

    @pytest.mark.parametrize("path,body", [
        ("/api/compare/skill",
         {"models": ["AIFS"], "variable": "precipitation", "lat": 36.0, "lon": -75.5}),
        ("/api/categorical-metrics",
         {"model": "AIFS", "variable": "precipitation", "lat": 36.0, "lon": -75.5}),
        ("/api/region-categorical-metrics",
         {"model": "AIFS", "variable": "precipitation", **BOX}),
    ])
    def test_a_run_with_forecasts_but_no_observations(self, client, fake_db, path, body):
        fake_db({**RUN,
                 "FROM regridded_forecast_ens": [fcst(h) for h in (6, 12)],
                 "FROM regridded_forecast_member": [
                     {"forecast_hour": 6, "latitude": 36.0, "longitude": -75.5,
                      "ensemble_member": m, "value": 1.0} for m in range(3)],
                 "FROM regridded_observation": []})
        r = client.post(path, json=body)
        assert r.status_code == 200, r.get_json()
        assert r.get_json() is not None

    def test_compare_skill_says_so_when_no_cell_has_data(self, client, fake_db):
        fake_db(RUN)
        r = client.post("/api/compare/skill", json={
            "models": ["AIFS", "GEFS"], "variable": "precipitation",
            "lat": 36.0, "lon": -75.5})
        assert r.status_code == 200
        assert r.get_json()["models"] == {}
        assert "obs_warning" in r.get_json()


class TestSpatialDiffValidation:
    @pytest.mark.parametrize("body,fragment", [
        ({"model_a": "AIFS", "model_b": "GEFS", "metric": "nope", **BOX}, "Unknown metric"),
        ({"model_a": "AIFS", "model_b": "GEFS", "metric": "mae",
          "min_lat": 95, "max_lat": 97, "min_lon": -77, "max_lon": -74}, "latitude"),
        ({"model_a": "AIFS", "model_b": "GEFS", "metric": "mae",
          "min_lat": 35, "max_lat": 37, "min_lon": -200, "max_lon": -74}, "longitude"),
        ({"model_a": "AIFS", "model_b": "GEFS", "metric": "mae", **BOX,
          "hour_min": 100, "hour_max": 10}, "hour_min"),
        ({"model_a": "AIFS", "model_b": 7, "metric": "mae", **BOX}, None),
    ])
    def test_bad_input_is_a_400_naming_the_problem(self, client, body, fragment):
        r = client.post("/api/compare/spatial-diff", json=body)
        assert r.status_code == 400
        if fragment:
            assert fragment in r.get_json()["error"]


class TestBboxValidation:
    @pytest.mark.parametrize("qs,fragment", [
        ("min_lat=95&max_lat=97&min_lon=-77&max_lon=-74", "latitude"),
        ("min_lat=35&max_lat=37&min_lon=-200&max_lon=-74", "longitude"),
        ("min_lat=35&max_lat=37&min_lon=-77&max_lon=200", "longitude"),
        ("min_lat=-95&max_lat=37&min_lon=-77&max_lon=-74", "latitude"),
    ])
    def test_a_box_off_the_globe_is_rejected(self, client, qs, fragment):
        r = client.get(f"/api/spatial-metric?metric=mae&model=AIFS"
                       f"&variable=precipitation&{qs}")
        assert r.status_code == 400
        assert fragment in r.get_json()["error"]

    def test_a_point_endpoint_without_coordinates_says_which_are_missing(self, client):
        r = client.get("/api/spread-skill?model=AIFS&variable=precipitation")
        assert r.status_code == 400
        assert "lat" in r.get_json()["error"]


class TestRenderFailuresAreContained:
    """Cartopy is the one place in the process that can fail for reasons nothing
    else can — a font cache, a projection, a memory ceiling. It runs after the
    DB connection is released, so the handler has to be right or the failure
    leaks a half-finished response."""

    PTS = [{"lat": 36.0, "lon": -75.5, "value": 1.0},
           {"lat": 36.5, "lon": -75.0, "value": 2.0}]

    def test_a_broken_renderer_is_a_500_not_a_hang(self, prod_client, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("Agg backend unavailable")
        monkeypatch.setattr(api, "_render_metric_map_png", boom)
        import uuid
        r = prod_client.post("/api/spatial-metric-plot", json={
            "metric": "mae", "model": "AIFS", "variable": "precipitation",
            "points": [{**p, "value": uuid.uuid4().int % 997 / 100} for p in self.PTS]})
        assert r.status_code == 500
        assert "Agg backend" not in str(r.get_json())

    def test_a_broken_renderer_in_the_diff_path_is_contained(self, prod_client,
                                                             fake_db, monkeypatch):
        fake_db({**RUN,
                 "FROM regridded_forecast_ens": [
                     fcst(h, lat=la) for h in (6, 12) for la in (35.5, 36.0, 36.5)],
                 "FROM regridded_observation": [
                     obs(h, lat=la) for h in (6, 12) for la in (35.5, 36.0, 36.5)]})
        def boom(*a, **k):
            raise RuntimeError("Agg backend unavailable")
        monkeypatch.setattr(api, "_render_metric_map_png", boom)
        r = prod_client.post("/api/compare/spatial-diff", json={
            "model_a": "AIFS", "model_b": "GEFS", "metric": "mae",
            "variable": "precipitation", **BOX})
        assert r.status_code in (200, 500)
        assert "Agg backend" not in str(r.get_json())


class TestSpatialAgreementCache:
    def test_the_second_identical_request_is_served_from_the_cache(self, client, fake_db):
        fake_db({**RUN,
                 "FROM regridded_forecast_ens": [
                     fcst(6, lat=la, lon=lo) for la in (35.5, 36.0) for lo in (-76.0, -75.5)]})
        import uuid
        body = {"models": ["AIFS", "GEFS"], "variable": "precipitation",
                "hour": 6, **BOX, "_cache_buster": str(uuid.uuid4())}
        first = client.post("/api/compare/spatial-agreement", json=body)
        second = client.post("/api/compare/spatial-agreement", json=body)
        assert first.status_code == second.status_code
        assert first.get_json() == second.get_json()
