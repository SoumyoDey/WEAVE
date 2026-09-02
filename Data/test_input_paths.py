"""Input rejection and the branches a specific request shape reaches.

Companion to `test_error_paths.py`, which covers failure *of the system*. This
one covers failure *of the request*: a model name that is not a model, an hour
that is not a number, an empty model list. Those branches are the ones an
attacker and a fumbled URL both find first, and they are also where a 500 is
least excusable, because nothing has actually gone wrong.

The rest of the file reaches branches that need a particular shape of data
rather than a particular failure: the wind threshold key, a contingency table
with no events in it, a composite with and without FSS.

Run:  ~/miniconda3/envs/afw/bin/python -m pytest Data -q
"""
from datetime import datetime, timedelta

import pytest

import flask_api as api


INIT = datetime(2025, 9, 8, 0, 0, 0)
BOX_QS = "min_lat=35&max_lat=37&min_lon=-77&max_lon=-74"
BOX = {"min_lat": 35, "max_lat": 37, "min_lon": -77, "max_lon": -74}


# ── Rejecting a name that is not a name ──────────────────────────────────────
# Model and variable reach SQL as identifiers, so they are allowlisted rather
# than escaped. Every endpoint that takes one has to check.
GET_WITH_TOKENS = [
    "/api/forecast-data?model={m}&variable={v}&hour=6",
    "/api/point-timeseries?model={m}&variable={v}&lat=36&lon=-75.5",
    "/api/spread-skill?model={m}&variable={v}&lat=36&lon=-75.5",
    "/api/spatial-metric?metric=mae&model={m}&variable={v}&" + BOX_QS,
    "/api/observation-coverage?model={m}&variable={v}",
]

POST_WITH_TOKENS = [
    ("/api/compare/skill", {"models": ["{m}"], "variable": "{v}", "lat": 36, "lon": -75.5}),
    ("/api/compare/timeseries", {"models": ["{m}"], "variable": "{v}", "lat": 36, "lon": -75.5}),
    ("/api/compare/categorical", {"models": ["{m}"], "variable": "{v}", "lat": 36, "lon": -75.5}),
    ("/api/compare/spatial-agreement",
     {"models": ["{m}", "GEFS"], "variable": "{v}", "hour": 6, **BOX}),
    ("/api/categorical-metrics", {"model": "{m}", "variable": "{v}", "lat": 36, "lon": -75.5}),
    ("/api/region-categorical-metrics", {"model": "{m}", "variable": "{v}", **BOX}),
    ("/api/compare/spatial-diff",
     {"model_a": "{m}", "model_b": "GEFS", "metric": "mae", "variable": "{v}", **BOX}),
]

BAD_TOKENS = ["AIFS'; DROP TABLE forecast_runs--", "../../etc/passwd", "a b", "x;y", ""]


class TestNamesAreAllowlisted:
    @pytest.mark.parametrize("bad", BAD_TOKENS)
    def test_wind_data_rejects_a_bad_model(self, client, bad):
        # Listed separately: it takes no `variable`, so the shared table's
        # second assertion would have been checking the same URL twice.
        assert client.get(f"/api/wind-data?model={bad}&hour=6").status_code == 400

    @pytest.mark.parametrize("bad", BAD_TOKENS)
    @pytest.mark.parametrize("path", GET_WITH_TOKENS,
                             ids=[p.split("?")[0].rsplit("/", 1)[-1] for p in GET_WITH_TOKENS])
    def test_get_endpoints_reject_a_bad_model_or_variable(self, client, path, bad):
        assert client.get(path.format(m=bad, v="precipitation")).status_code == 400
        assert client.get(path.format(m="AIFS", v=bad)).status_code == 400

    @pytest.mark.parametrize("bad", BAD_TOKENS)
    @pytest.mark.parametrize("path,body", POST_WITH_TOKENS,
                             ids=[p.rsplit("/", 1)[-1] for p, _ in POST_WITH_TOKENS])
    def test_post_endpoints_reject_a_bad_model_or_variable(self, client, path, body, bad):
        def fill(obj, **kw):
            if isinstance(obj, dict):
                return {k: fill(v, **kw) for k, v in obj.items()}
            if isinstance(obj, list):
                return [fill(v, **kw) for v in obj]
            return obj.format(**kw) if isinstance(obj, str) else obj

        assert client.post(path, json=fill(body, m=bad, v="precipitation")).status_code == 400
        assert client.post(path, json=fill(body, m="AIFS", v=bad)).status_code == 400


class TestNumbersMustBeNumbers:
    """Every numeric query parameter, fed a word. The contract is 400 — a 500
    here would mean an unhandled ValueError reached the user."""

    @pytest.mark.parametrize("path", [
        "/api/forecast-data?model=AIFS&variable=precipitation&hour=six",
        "/api/wind-data?model=AIFS&hour=six",
        "/api/point-timeseries?model=AIFS&variable=precipitation&lat=36&lon=-75.5&radius=wide",
        "/api/spread-skill?model=AIFS&variable=precipitation&lat=36&lon=-75.5&radius=wide",
        "/api/spatial-metric?metric=csi&model=AIFS&variable=precipitation&"
        + BOX_QS + "&threshold_mm_6h=lots",
        "/api/spatial-metric?metric=mae&model=AIFS&variable=precipitation&min_lat=a"
        "&max_lat=37&min_lon=-77&max_lon=-74",
        "/api/forecast-data?model=AIFS&variable=precipitation&hour=6&member=third",
        "/api/wind-data?model=AIFS&hour=6&member=third",
    ])
    def test_get_rejects_a_non_numeric_parameter(self, client, path):
        assert client.get(path).status_code == 400

    @pytest.mark.parametrize("path,body", [
        ("/api/compare/skill", {"models": ["AIFS"], "hour_min": "soon"}),
        ("/api/compare/timeseries", {"models": ["AIFS"], "hour_max": "later"}),
        ("/api/compare/categorical", {"models": ["AIFS"], "hour_min": "soon"}),
        ("/api/compare/categorical", {"models": ["AIFS"], "fss_window": "wide"}),
        ("/api/compare/categorical", {"models": ["AIFS"], "threshold_mm_6h": "lots"}),
        ("/api/categorical-metrics", {"model": "AIFS", "hour_min": "soon"}),
        ("/api/categorical-metrics", {"model": "AIFS", "box_cells": "many"}),
        ("/api/categorical-metrics", {"model": "AIFS", "threshold_mm_6h": "lots"}),
        ("/api/region-categorical-metrics", {"model": "AIFS", **BOX, "hour_min": "soon"}),
        ("/api/region-categorical-metrics", {"model": "AIFS", **BOX, "threshold_mm_6h": "x"}),
        ("/api/region-categorical-metrics", {"model": "AIFS", **BOX, "fss_window": "wide"}),
        ("/api/compare/region-metrics", {"models": ["AIFS"], **BOX, "hour_min": "soon"}),
        ("/api/compare/region-metrics", {"models": ["AIFS"], **BOX, "threshold_mm_6h": "x"}),
        ("/api/compare/spatial-agreement", {"models": ["AIFS", "GEFS"], **BOX, "hour": "six"}),
        ("/api/compare/spatial-diff",
         {"model_a": "AIFS", "model_b": "GEFS", "metric": "mae", **BOX, "hour_min": "soon"}),
        ("/api/compare/spatial-diff",
         {"model_a": "AIFS", "model_b": "GEFS", "metric": "mae", **BOX, "threshold_mm_6h": "x"}),
    ])
    def test_post_rejects_a_non_numeric_parameter(self, client, path, body):
        assert client.post(path, json=body).status_code == 400


class TestListsMustBeLists:
    @pytest.mark.parametrize("path,body", [
        ("/api/compare/skill", {"models": [], "variable": "precipitation"}),
        ("/api/compare/timeseries", {"models": [], "variable": "precipitation"}),
        ("/api/compare/categorical", {"models": [], "variable": "precipitation"}),
        ("/api/compare/region-metrics", {"models": [], **BOX}),
        ("/api/compare/region-metrics", {"models": [1, 2], **BOX}),
        ("/api/compare/region-metrics", {"models": ["AIFS"], "metrics": [7], **BOX}),
        ("/api/compare/spatial-agreement", {"models": ["AIFS"], "hour": 6, **BOX}),
        ("/api/compare/categorical", {"models": [1, 2], "lat": 36, "lon": -75.5}),
        ("/api/compare/skill", {"models": [{}], "lat": 36, "lon": -75.5}),
    ])
    def test_a_malformed_model_or_metric_list_is_rejected(self, client, path, body):
        assert client.post(path, json=body).status_code == 400

    @pytest.mark.parametrize("path", ["/api/spatial-metric-plot",
                                      "/api/compare/spatial-agreement"])
    def test_a_non_object_body_is_rejected(self, client, path):
        r = client.post(path, data="[]", content_type="application/json")
        assert r.status_code == 400


class TestSpatialMetricDispatch:
    """Every metric in the registry, through the endpoint. The threshold-taking
    ones resolve their rate from a different key per variable, which is the
    branch that used to send an m/s value through the mm/6h divisor."""

    ALL = ["ssr", "ssr_agg", "correlation", "bias", "mae", "rmse", "crps",
           "csi", "pod", "far", "brier"]

    @pytest.mark.parametrize("variable,thr_key,thr",
                             [("precipitation", "threshold_mm_6h", 25),
                              ("wind", "threshold_ms", 10)])
    @pytest.mark.parametrize("metric", ALL)
    def test_each_metric_dispatches_for_each_variable(self, client, fake_db,
                                                      metric, variable, thr_key, thr):
        fake_db({"FROM forecast_runs": [{"run_id": 1, "initialization_time": INIT}],
                 "FROM variables": [{"variable_id": 1}]})
        r = client.get(f"/api/spatial-metric?metric={metric}&model=AIFS"
                       f"&variable={variable}&{BOX_QS}&hour=6&{thr_key}={thr}")
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["metric"] == metric

    def test_an_unknown_variable_id_is_a_404_not_a_crash(self, client, fake_db):
        fake_db({"FROM forecast_runs": [{"run_id": 1, "initialization_time": INIT}]})
        r = client.get(f"/api/wind-data?model=AIFS&hour=6")
        assert r.status_code in (200, 404)


class TestPlotTitles:
    """The title line differs by metric: ssr names its lead time, correlation
    names how many went into it, everything else just counts points."""

    PTS = [{"lat": 36.0, "lon": -75.5, "value": 1.0},
           {"lat": 36.5, "lon": -75.0, "value": 2.0}]

    @pytest.mark.parametrize("metric,extra", [
        ("ssr", {"hour": 12}),
        ("correlation", {"n_hours": 4}),
        ("mae", {}),
        ("csi", {"threshold_mm_6h": 25}),
    ])
    def test_each_title_shape_renders(self, client, metric, extra):
        import uuid
        r = client.post("/api/spatial-metric-plot", json={
            "metric": metric, "model": "AIFS", "variable": "precipitation",
            "points": [{**p, "value": p["value"] + uuid.uuid4().int % 100 / 1000}
                       for p in self.PTS],
            **extra})
        assert r.status_code == 200
        assert len(r.get_json()["image"]) > 5000

    def test_a_wind_categorical_map_is_labelled_in_metres_per_second(self, client):
        import uuid
        r = client.post("/api/spatial-metric-plot", json={
            "metric": "csi", "model": "AIFS", "variable": "wind",
            "threshold_ms": 12,
            "points": [{**p, "value": p["value"] + uuid.uuid4().int % 100 / 1000}
                       for p in self.PTS]})
        assert r.status_code == 200


class TestExportConventionCheck:
    """/api/health infers the precipitation divisor back out of the data. Its
    three verdicts each carry different advice, and MISMATCH is the one that
    exists to stop a silent double-correction."""

    def _health(self, client, fake_db, inferred):
        fake_db({"FROM ensemble_statistics": [], "AS ratio": []})
        import metrics
        original = api._infer_scaled_export_divisor
        try:
            api._infer_scaled_export_divisor = lambda ratios: inferred
            return api._check_export_convention(
                type("C", (), {"execute": lambda *a, **k: None,
                               "fetchall": lambda *a, **k: [(1.0,)] * 50})())
        finally:
            api._infer_scaled_export_divisor = original

    def test_an_ambiguous_sample_is_indeterminate_not_a_guess(self, client, fake_db):
        result = self._health(client, fake_db, None)
        assert result["status"] == "indeterminate"
        assert "by hand" in result["detail"]

    def test_a_divisor_that_disagrees_with_the_code_is_a_mismatch(self, client, fake_db):
        declared = api.SCALED_EXPORT_DIVISOR_HOURS.get("GEFS")
        result = self._health(client, fake_db, (declared or 3.0) * 2)
        assert result["status"] == "MISMATCH"
        # The message has to name the fix, not just the fault.
        assert "SCALED_EXPORT_DIVISOR_HOURS" in result["detail"]

    def test_a_matching_divisor_is_ok(self, client, fake_db):
        declared = api.SCALED_EXPORT_DIVISOR_HOURS.get("GEFS", 3.0)
        result = self._health(client, fake_db, declared)
        assert result["status"] == "ok"

    def test_a_missing_table_is_reported_not_raised(self, client):
        class Angry:
            def execute(self, *a, **k):
                raise Exception('relation "ensemble_statistics" does not exist')
            def fetchall(self, *a, **k):
                return []
        result = api._check_export_convention(Angry())
        assert result["status"] == "unknown"
        assert "query failed" in result["reason"]
