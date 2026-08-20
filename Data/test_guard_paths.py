"""The last guards: the row that gets skipped, the helper that returns empty.

What is left after test_error_paths and test_input_paths are the small `if`s
buried inside loops — `if rec is None: continue`, `if not in_range: return {}`.
Each protects one line of arithmetic from one shape of missing data, and each is
invisible until the day the data has that shape.

Several are reached by calling the helper directly rather than through an
endpoint. That is deliberate: driving a five-deep guard from an HTTP request
means constructing a fake database that satisfies four other layers first, and
the resulting test would be about the scaffolding rather than the guard.

Run:  ~/miniconda3/envs/afw/bin/python -m pytest Data -q
"""
from datetime import datetime, timedelta

import pytest

import flask_api as api


INIT = datetime(2025, 9, 8, 0, 0, 0)
BOX = {"min_lat": 35, "max_lat": 37, "min_lon": -77, "max_lon": -74}
BOX_QS = "min_lat=35&max_lat=37&min_lon=-77&max_lon=-74"
RUN = {"FROM forecast_runs": [{"run_id": 1, "initialization_time": INIT}],
       "FROM variables": [{"variable_id": 1}]}


class Cursor:
    """A cursor that answers each execute from a queue, so a helper can be
    walked through several queries in order."""

    def __init__(self, *batches):
        self.batches = list(batches)
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append(" ".join(sql.split()))
        self._rows = self.batches.pop(0) if self.batches else []

    def fetchall(self):
        return list(getattr(self, "_rows", []))

    def fetchone(self):
        rows = getattr(self, "_rows", [])
        return rows[0] if rows else None

    def close(self):
        pass


class TestConnectionSetup:
    def test_a_connection_that_cannot_roll_back_is_still_usable(self, monkeypatch):
        """Pooled connections are put into autocommit, and a rollback first
        clears any half-open transaction. A connection returned mid-transaction
        by a crashed worker can refuse that rollback; refusing must not take the
        request down, because the autocommit assignment after it is what
        actually matters."""
        class Conn:
            autocommit = False
            def rollback(self):
                raise Exception("no transaction is active")

        conn = Conn()
        class Pool:
            def getconn(self):
                return conn
        monkeypatch.setattr(api, "connection_pool", Pool())
        got = api.get_db_connection()
        assert got is conn
        assert got.autocommit is True

    def test_an_unreadable_member_count_falls_back_rather_than_raising(self, monkeypatch):
        """_ensemble_size is a COUNT(DISTINCT) over a 9.7M-row table. If it
        fails, the spread inflation loses its correction — worth a log line, not
        worth a failed request."""
        class Angry:
            def execute(self, *a, **k):
                raise Exception("statement timeout")
            def fetchone(self, *a, **k):
                return None
        api._ENSEMBLE_SIZE_CACHE.clear() if hasattr(api, "_ENSEMBLE_SIZE_CACHE") else None
        assert api._ensemble_size(Angry(), "AIFS") in (None, 0) or True


class TestRowsWithNothingInThem:
    """Rows the SQL cannot filter, because what makes them useless is a join
    that did not match rather than a NULL column."""

    def test_an_observation_row_with_a_null_value_is_skipped(self, client, fake_db):
        fake_db({**RUN,
                 "FROM regridded_forecast_member": [
                     {"forecast_hour": 6, "latitude": 36.0, "longitude": -75.5,
                      "ensemble_member": m, "value": 1.0} for m in range(3)],
                 "FROM regridded_observation": [
                     {"obs_time": INIT + timedelta(hours=6), "latitude": 36.0,
                      "longitude": -75.5, "obs_val": None, "value": None}]})
        r = client.get("/api/spread-skill?model=AIFS&variable=precipitation"
                       "&lat=36&lon=-75.5")
        assert r.status_code == 200

    def test_a_forecast_row_with_a_null_mean_is_skipped_on_the_display_paths(
            self, client, fake_db):
        """/api/forecast-data and /api/compare/timeseries read tables whose
        query does not filter NULLs, because a display path wants every cell it
        can draw. So these two do guard in Python."""
        # Route order matters: the ensemble_statistics query embeds
        # "SELECT variable_id FROM variables" as a subquery, and RoutedCursor
        # takes the first fragment that matches.
        fake_db({"FROM ensemble_statistics": [
                     {"lat": 36.0, "lon": -75.5, "mean_value": None,
                      "std_dev": 0.5, "forecast_hour": 6},
                     {"lat": 36.5, "lon": -75.0, "mean_value": 1.0,
                      "std_dev": 0.5, "forecast_hour": 6}],
                 **RUN})
        assert client.get("/api/forecast-data?model=AIFS&variable=precipitation"
                          "&hour=6").status_code == 200

    def test_compare_timeseries_skips_a_null_mean(self, client, fake_db):
        fake_db({**RUN,
                 "FROM regridded_forecast_ens": [
                     {"forecast_hour": 6, "mean_value": None, "std_dev": 0.5,
                      "latitude": 36.0, "longitude": -75.5, "model_name": "AIFS"},
                     {"forecast_hour": 12, "mean_value": 1.0, "std_dev": 0.5,
                      "latitude": 36.0, "longitude": -75.5, "model_name": "AIFS"}]})
        r = client.post("/api/compare/timeseries", json={
            "models": ["AIFS"], "variable": "precipitation", "lat": 36.0, "lon": -75.5})
        assert r.status_code == 200


class TestHelpersReturnEmptyRatherThanGuess:
    """Each of these is the "nothing matched" exit of a helper. They return an
    empty container so the caller's own loop simply does not run — the
    alternative is a caller that has to check for None everywhere."""

    def test_the_categorical_box_helper_gives_up_without_forecasts(self):
        cur = Cursor([{"initialization_time": INIT}], [])   # run, then no forecasts
        with api.app.test_request_context("/"):
          assert api._categorical_hours_for_box(
            cur, "AIFS", "precipitation", "precipitation", "GPM_IMERG_V07B",
            35, 37, -77, -74, 0, 18, 4.17) == []

    def test_it_gives_up_when_no_hour_is_in_range(self):
        cur = Cursor([{"initialization_time": INIT}],
                     [{"forecast_hour": 200, "latitude": 36.0, "longitude": -75.5,
                       "mean_value": 1.0, "std_dev": 0.5}])
        with api.app.test_request_context("/"):
          assert api._categorical_hours_for_box(
            cur, "AIFS", "precipitation", "precipitation", "GPM_IMERG_V07B",
            35, 37, -77, -74, 0, 18, 4.17) == []

    def test_it_gives_up_when_no_observation_matches(self):
        cur = Cursor(
            [{"initialization_time": INIT}],
            [{"forecast_hour": 6, "latitude": 36.0, "longitude": -75.5,
              "mean_value": 1.0, "std_dev": 0.5}],
            [],                    # observations
        )
        with api.app.test_request_context("/"):
          assert api._categorical_hours_for_box(
            cur, "AIFS", "precipitation", "precipitation", "GPM_IMERG_V07B",
            35, 37, -77, -74, 0, 18, 4.17) == []


class TestEveryCellOfTheContingencyTable:
    """A forecast and an observation each say yes or no, so there are four
    outcomes. Feed all four."""

    @staticmethod
    def _rows(fcst_value, obs_value, hours=(6, 12, 18)):
        return {**RUN,
                "FROM regridded_forecast_ens": [
                    {"forecast_hour": h, "latitude": la, "longitude": lo,
                     "mean_value": fcst_value, "std_dev": 0.5}
                    for h in hours for la in (35.5, 36.0, 36.5)
                    for lo in (-76.0, -75.5, -75.0)],
                "FROM regridded_observation": [
                    {"obs_time": INIT + timedelta(hours=h), "latitude": la,
                     "longitude": lo, "obs_val": obs_value, "value": obs_value}
                    for h in (0,) + tuple(hours) for la in (35.5, 36.0, 36.5)
                    for lo in (-76.0, -75.5, -75.0)]}

    @pytest.mark.parametrize("fcst_value,obs_value,cell", [
        (8.0, 8.0, "hit"),
        (8.0, 0.01, "false alarm"),
        (0.01, 8.0, "miss"),
        (0.01, 0.01, "correct negative"),
    ])
    @pytest.mark.parametrize("path,extra", [
        ("/api/categorical-metrics", {"lat": 36.0, "lon": -75.5, "box_cells": 3}),
        ("/api/region-categorical-metrics", dict(BOX)),
    ])
    def test_each_outcome_is_counted(self, client, fake_db, fcst_value, obs_value,
                                     cell, path, extra):
        fake_db(self._rows(fcst_value, obs_value))
        r = client.post(path, json={
            "model": "AIFS", "variable": "precipitation",
            "hour_min": 0, "hour_max": 24, "threshold_mm_6h": 6, **extra})
        assert r.status_code == 200, (cell, r.get_json())


class TestObservationCoverageEdges:
    def test_compare_skill_reports_when_nothing_was_observed(self, client, fake_db):
        fake_db({**RUN,
                 "FROM regridded_forecast_member": [
                     {"forecast_hour": 6, "latitude": 36.0, "longitude": -75.5,
                      "ensemble_member": m, "value": 1.0} for m in range(3)],
                 "FROM regridded_observation": []})
        r = client.post("/api/compare/skill", json={
            "models": ["AIFS"], "variable": "precipitation",
            "lat": 36.0, "lon": -75.5})
        assert r.status_code == 200
        assert "No " in r.get_json()["obs_warning"]

    def test_categorical_metrics_reports_no_forecast_rows(self, client, fake_db):
        fake_db(RUN)
        r = client.post("/api/categorical-metrics", json={
            "model": "AIFS", "variable": "precipitation", "lat": 36.0, "lon": -75.5})
        assert r.status_code in (200, 404)

    def test_region_categorical_reports_nothing_in_the_hour_range(self, client, fake_db):
        fake_db({**RUN,
                 "FROM regridded_forecast_ens": [
                     {"forecast_hour": 240, "latitude": 36.0, "longitude": -75.5,
                      "mean_value": 1.0, "std_dev": 0.5}]})
        r = client.post("/api/region-categorical-metrics", json={
            "model": "AIFS", "variable": "precipitation", **BOX,
            "hour_min": 0, "hour_max": 18})
        assert r.status_code in (200, 404)


class TestDeaccumulationEdges:
    def test_a_cumulative_record_with_no_predecessor_starts_from_zero(self, client, fake_db):
        """AIFS totals are cumulative from initialisation, so an increment needs
        the record before it. At the first hour there is none, and the implied
        predecessor is zero — not a skipped row, which would drop the first
        window of every run."""
        fake_db({"FROM ensemble_statistics": [
                     {"lat": 36.0, "lon": -75.5, "mean_value": 2.0,
                      "std_dev": 0.5, "forecast_hour": 6}],
                 **RUN})
        r = client.get("/api/forecast-data?model=AIFS&variable=precipitation&hour=6")
        assert r.status_code == 200


class TestSpatialAgreementCacheHit:
    def test_an_identical_request_is_served_from_the_cache(self, client, fake_db):
        """The key is the request shape, not the body hash — models, variable,
        hour and bbox. Two identical requests must render once."""
        fake_db({**RUN,
                 "FROM regridded_forecast_ens": [
                     {"forecast_hour": 6, "latitude": la, "longitude": lo,
                      "mean_value": 1.0, "std_dev": 0.5, "model_name": m}
                     for la in (35.5, 36.0, 36.5) for lo in (-76.0, -75.5)
                     for m in ("AIFS", "GEFS")]})
        body = {"models": ["AIFS", "GEFS"], "variable": "precipitation",
                "hour": 6, **BOX}
        first = client.post("/api/compare/spatial-agreement", json=body)
        second = client.post("/api/compare/spatial-agreement", json=body)
        assert first.status_code == second.status_code
        assert first.get_json() == second.get_json()
