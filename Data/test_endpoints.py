"""Endpoint-level tests for the WEAVE API — request validation and the response
contract the frontend depends on.

`test_metrics.py` covers the science as pure functions. This file covers the
layer above it: that bad input yields a clean 400 rather than a 500, and that
each endpoint keeps emitting the keys the React components read. Those are the
regressions that are cheap to introduce and expensive to notice, because a
renamed key produces an empty chart rather than an error.

Still no database: `RoutedCursor` answers each query by matching a distinctive
fragment of its SQL, so a test declares only the tables it cares about.

Run:  ~/miniconda3/envs/afw/bin/python -m pytest Data -q
"""
from datetime import datetime, timedelta

import pytest

import flask_api as api


INIT = datetime(2025, 9, 8, 0, 0, 0)


# ── Fake database ─────────────────────────────────────────────────────────────
class RoutedCursor:
    """Stands in for a psycopg2 RealDictCursor.

    `routes` maps a substring of the SQL to either a list of row dicts or a
    callable taking the bound params and returning one. The first matching
    route wins; an unmatched query yields no rows, which is what an endpoint
    would see for a region with no data.
    """

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.executed = []
        self._rows = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))
        for fragment, rows in self.routes.items():
            if fragment in " ".join(sql.split()):
                self._rows = rows(params) if callable(rows) else list(rows)
                return
        self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, *a, **kw):
        return self._cursor

    def close(self):
        pass


@pytest.fixture
def client():
    api.app.config.update(TESTING=True)
    return api.app.test_client()


@pytest.fixture
def fake_db(monkeypatch):
    """Point the endpoints at a RoutedCursor instead of the connection pool."""
    def _install(routes=None):
        cur = RoutedCursor(routes)
        monkeypatch.setattr(api, "get_db_connection", lambda: _FakeConn(cur))
        monkeypatch.setattr(api, "return_db_connection", lambda conn: None)
        # Member counts hit a very large table; keep them out of these tests.
        monkeypatch.setattr(api, "_ensemble_size", lambda cursor, model: 50)
        return cur
    return _install


def _fcst_row(hour, lat=36.0, lon=-75.5, mean=1.0, std=0.5):
    return {"forecast_hour": hour, "latitude": lat, "longitude": lon,
            "mean_value": mean, "std_dev": std}


def _obs_rows(hours, lat=36.0, lon=-75.5, value=1.0, per_cell=False):
    out = []
    for h in hours:
        row = {"obs_time": INIT + timedelta(hours=h), "obs_val": value}
        if per_cell:
            row.update({"latitude": lat, "longitude": lon})
        out.append(row)
    return out


# ── Request validation ────────────────────────────────────────────────────────
# These run before any DB access, so they need no fake database at all.
class TestValidationReturns400:
    @pytest.mark.parametrize("path", [
        "/api/compare/skill", "/api/compare/timeseries", "/api/compare/categorical",
        "/api/compare/region-metrics", "/api/compare/spatial-diff",
        "/api/categorical-metrics", "/api/region-categorical-metrics",
    ])
    def test_non_object_body(self, client, path):
        r = client.post(path, data="not json", content_type="application/json")
        assert r.status_code == 400
        assert "error" in r.get_json()

    @pytest.mark.parametrize("path,body", [
        ("/api/compare/skill", {"models": ["AIFS'; DROP TABLE--"]}),
        ("/api/compare/categorical", {"models": ["../etc"]}),
        ("/api/compare/region-metrics", {"models": ["AIFS"], "variable": "x;y"}),
    ])
    def test_rejects_bad_tokens(self, client, path, body):
        """Model and variable names are allowlisted before reaching SQL."""
        assert client.post(path, json=body).status_code == 400

    def test_region_metrics_rejects_unknown_metric(self, client):
        r = client.post("/api/compare/region-metrics", json={
            "models": ["AIFS"], "metrics": ["not_a_metric"],
            "min_lat": 34, "max_lat": 37, "min_lon": -77, "max_lon": -72})
        assert r.status_code == 400
        assert "not_a_metric" in r.get_json()["error"]

    def test_region_metrics_rejects_inverted_bbox(self, client):
        r = client.post("/api/compare/region-metrics", json={
            "models": ["AIFS"], "min_lat": 40, "max_lat": 37,
            "min_lon": -77, "max_lon": -72})
        assert r.status_code == 400

    def test_region_metrics_rejects_inverted_hours(self, client):
        r = client.post("/api/compare/region-metrics", json={
            "models": ["AIFS"], "min_lat": 34, "max_lat": 37,
            "min_lon": -77, "max_lon": -72, "hour_min": 100, "hour_max": 10})
        assert r.status_code == 400

    def test_region_metrics_rejects_empty_models(self, client):
        r = client.post("/api/compare/region-metrics", json={
            "models": [], "min_lat": 34, "max_lat": 37,
            "min_lon": -77, "max_lon": -72})
        assert r.status_code == 400

    def test_spatial_diff_rejects_identical_models(self, client):
        r = client.post("/api/compare/spatial-diff", json={
            "model_a": "AIFS", "model_b": "AIFS", "metric": "mae",
            "min_lat": 34, "max_lat": 37, "min_lon": -77, "max_lon": -72})
        assert r.status_code == 400
        assert "differ" in r.get_json()["error"]

    def test_spatial_diff_requires_both_models(self, client):
        r = client.post("/api/compare/spatial-diff", json={
            "metric": "mae", "min_lat": 34, "max_lat": 37,
            "min_lon": -77, "max_lon": -72})
        assert r.status_code == 400

    def test_spatial_metric_rejects_unknown_metric(self, client):
        r = client.get("/api/spatial-metric?metric=nope&model=AIFS&variable=precipitation")
        assert r.status_code == 400

    def test_spread_skill_requires_numeric_latlon(self, client):
        assert client.get("/api/spread-skill?model=AIFS&lat=abc&lon=-75").status_code == 400

    def test_plot_rejects_empty_points(self, client):
        r = client.post("/api/spatial-metric-plot", json={"metric": "mae", "points": []})
        assert r.status_code == 400

    def test_plot_rejects_metric_without_a_style(self, client):
        r = client.post("/api/spatial-metric-plot", json={
            "metric": "no_such_style", "points": [{"lat": 36.0, "lon": -75.5, "value": 1.0}]})
        assert r.status_code == 400

    def test_errors_never_leak_internals(self, client):
        """Error bodies stay generic — no driver text, SQL or connection strings."""
        r = client.post("/api/compare/skill", data="{", content_type="application/json")
        body = str(r.get_json()).lower()
        for leak in ("psycopg2", "traceback", "select ", "password", "dbname"):
            assert leak not in body


# ── Response contract ─────────────────────────────────────────────────────────
class TestCompareSkillContract:
    ROUTES = {
        "FROM forecast_runs fr": [{"initialization_time": INIT}],
        "ORDER BY POWER": [{"latitude": 36.0, "longitude": -75.5}],
        # Verification runs on a common 6 h window, so an hourly model needs a
        # full window present before anything is scored — hours 1-12, not 0-2.
        "FROM regridded_forecast_ens u": [_fcst_row(h) for h in range(1, 13)],
        "FROM regridded_observation": _obs_rows(list(range(1, 13))),
    }

    def test_emits_the_keys_the_frontend_reads(self, client, fake_db):
        fake_db(self.ROUTES)
        d = client.post("/api/compare/skill", json={
            "models": ["UKMO"], "lat": 36.0, "lon": -75.5,
            "hour_min": 0, "hour_max": 12, "variable": "precipitation"}).get_json()

        assert set(d) >= {"models", "obs_hours", "obs_warning", "units", "model_cells"}
        m = d["models"]["UKMO"]
        assert set(m) == {"hours", "summary"}
        assert set(m["summary"]) == {"mean_ssr", "correlation", "mean_crps",
                                     "bias", "mae", "rmse"}
        assert set(m["hours"][0]) >= {"hour", "ssr", "crps", "bias", "mae", "rmse",
                                      "spread", "mean_val", "obs", "period_h"}

    def test_one_row_per_lead_time(self, client, fake_db):
        """Audit finding 3: an off-grid point used to return each lead time up
        to four times, once per cell caught by the +/-0.26 box."""
        fake_db(self.ROUTES)
        d = client.post("/api/compare/skill", json={
            "models": ["UKMO"], "lat": 35.75, "lon": -75.75,
            "hour_min": 0, "hour_max": 12, "variable": "precipitation"}).get_json()
        hours = [h["hour"] for h in d["models"]["UKMO"]["hours"]]
        assert hours == sorted(set(hours))

    def test_reports_the_cell_it_verified_against(self, client, fake_db):
        fake_db(self.ROUTES)
        d = client.post("/api/compare/skill", json={
            "models": ["UKMO"], "lat": 35.75, "lon": -75.75,
            "hour_min": 0, "hour_max": 12, "variable": "precipitation"}).get_json()
        assert d["model_cells"]["UKMO"] == [36.0, -75.5]

    def test_no_forecast_data_is_not_an_error(self, client, fake_db):
        """An empty region returns 200 with a warning, so the UI can say so."""
        fake_db({"FROM forecast_runs fr": [{"initialization_time": INIT}]})
        r = client.post("/api/compare/skill", json={
            "models": ["UKMO"], "lat": 36.0, "lon": -75.5, "variable": "precipitation"})
        assert r.status_code == 200
        assert r.get_json()["models"] == {}
        assert r.get_json()["obs_warning"]


class TestCompareCategoricalContract:
    ROUTES = {
        "FROM forecast_runs fr": [{"initialization_time": INIT}],
        "FROM regridded_forecast_ens u": [
            _fcst_row(h, lat=lat, mean=mean)
            for h in range(1, 7)              # a full 6 h verification window
            for lat, mean in ((36.0, 10.0), (36.5, 0.0))
        ],
        "FROM regridded_observation": [
            {"obs_time": INIT + timedelta(hours=h), "latitude": lat,
             "longitude": -75.5, "obs_val": 8.0}
            for h in range(1, 7) for lat in (36.0, 36.5)
        ],
    }

    def test_summaries_are_additive_to_models(self, client, fake_db):
        """`summaries` was added alongside `models`, which keeps its per-hour
        list shape — the frontend still indexes it as a list."""
        fake_db(self.ROUTES)
        d = client.post("/api/compare/categorical", json={
            "models": ["UKMO"], "lat": 36.0, "lon": -75.5,
            "variable": "precipitation", "threshold_mm_6h": 6,
            "hour_min": 0, "hour_max": 12}).get_json()

        assert isinstance(d["models"]["UKMO"], list)
        s = d["summaries"]["UKMO"]
        assert set(s) >= {"csi", "pod", "far", "fss", "hits", "misses",
                          "false_alarms", "n_pts", "n_hours", "brier"}

    def test_threshold_info_reports_the_unit(self, client, fake_db):
        fake_db(self.ROUTES)
        d = client.post("/api/compare/categorical", json={
            "models": ["UKMO"], "lat": 36.0, "lon": -75.5,
            "variable": "wind", "threshold_ms": 8}).get_json()
        assert d["threshold_info"]["unit"] == "m/s"


class TestRegionMetricsContract:
    def _routes(self):
        return {
            "FROM forecast_runs fr": [{"initialization_time": INIT}],
            "FROM regridded_forecast_ens u": [
                _fcst_row(h, lat=lat, mean=2.0, std=1.0)
                for h in range(1, 7) for lat in (36.0, 36.5)   # a full 6 h window
            ],
            "FROM regridded_observation": [
                {"obs_time": INIT + timedelta(hours=h), "latitude": lat,
                 "longitude": -75.5, "obs_val": 1.0}
                for h in range(1, 7) for lat in (36.0, 36.5)
            ],
        }

    def test_returns_pooled_and_per_cell_values(self, client, fake_db):
        """Audit finding 8: the headline is pooled over samples, while
        `cell_means` keeps the per-cell mean the map averages to."""
        fake_db(self._routes())
        d = client.post("/api/compare/region-metrics", json={
            "models": ["UKMO"], "variable": "precipitation",
            "min_lat": 35, "max_lat": 37, "min_lon": -77, "max_lon": -74,
            "hour_min": 0, "hour_max": 12, "metrics": ["mae", "bias"]}).get_json()

        assert set(d) >= {"models", "cell_means", "n_points", "n_cells",
                          "metrics", "threshold_info", "warnings"}
        assert d["models"]["UKMO"]["mae"] == pytest.approx(1.0)
        assert d["cell_means"]["UKMO"]["mae"] == pytest.approx(1.0)

    def test_no_overlap_is_reported_not_silently_empty(self, client, fake_db):
        """A misaligned grid must produce a warning, not a blank chart."""
        fake_db({"FROM forecast_runs fr": [{"initialization_time": INIT}]})
        d = client.post("/api/compare/region-metrics", json={
            "models": ["UKMO"], "variable": "precipitation",
            "min_lat": 35, "max_lat": 37, "min_lon": -77, "max_lon": -74,
            "metrics": ["mae"]}).get_json()
        assert d["warnings"]["UKMO"]
        assert d["models"]["UKMO"]["mae"] is None


class TestSpatialDiffContract:
    def test_no_shared_cells_reports_both_counts(self, client, fake_db):
        fake_db({"FROM forecast_runs fr": [{"initialization_time": INIT}]})
        d = client.post("/api/compare/spatial-diff", json={
            "model_a": "AIFS", "model_b": "UKMO", "metric": "mae",
            "variable": "precipitation", "min_lat": 35, "max_lat": 37,
            "min_lon": -77, "max_lon": -74}).get_json()
        assert d["n_common"] == 0
        assert "error" in d and "n_a" in d and "n_b" in d
        assert "image" not in d

    def test_releases_the_connection_before_rendering(self, client, fake_db, monkeypatch):
        """Rendering is CPU-bound; holding a pooled connection across it starves
        concurrent requests."""
        released = []
        cur = fake_db({"FROM forecast_runs fr": [{"initialization_time": INIT}]})
        monkeypatch.setattr(api, "return_db_connection", lambda conn: released.append(conn))
        client.post("/api/compare/spatial-diff", json={
            "model_a": "AIFS", "model_b": "UKMO", "metric": "mae",
            "variable": "precipitation", "min_lat": 35, "max_lat": 37,
            "min_lon": -77, "max_lon": -74})
        assert released, "connection was never returned to the pool"
        assert cur is not None


class TestHealth:
    def test_reports_unhealthy_without_leaking(self, client, monkeypatch):
        def boom():
            raise RuntimeError("password=hunter2 host=db.internal")
        monkeypatch.setattr(api, "get_db_connection", boom)
        r = client.get("/api/health")
        assert r.status_code == 500
        assert "hunter2" not in str(r.get_json())
        assert r.get_json()["status"] == "unhealthy"


# ── /api/spread-skill on the shared grid (audit finding 11) ───────────────────
class TestSpreadSkillSharedGrid:
    """spread-skill used to verify natively (0.25 deg forecast against a 0.1 deg
    IMERG point) while every other scored endpoint used the 0.5 deg grid, so the
    same point reported two different SSRs. It now reads the regridded member
    grid and the regridded observations, like everything else."""

    def _member_rows(self, hours, members=4, value=lambda h, m: 1.0 + 0.1 * m):
        return [{"forecast_hour": h, "ensemble_member": m, "member_val": value(h, m)}
                for h in hours for m in range(members)]

    ROUTES_BASE = {
        "FROM forecast_runs": [{"run_id": 1, "initialization_time": INIT}],
        "SELECT initialization_time": [{"initialization_time": INIT}],
    }

    def _routes(self, hours, members=4):
        r = dict(self.ROUTES_BASE)
        r["FROM regridded_forecast_member"] = self._member_rows(hours, members)
        r["FROM regridded_observation"] = _obs_rows(hours)
        return r

    def test_reads_the_member_grid_not_forecast_data(self, client, fake_db):
        """The native tables must not be touched: if they were, the fake DB would
        have no route for them and the query would come back empty."""
        fake_db(self._routes([0, 1, 2]))
        d = client.get("/api/spread-skill?model=UKMO&variable=precipitation"
                       "&lat=36.0&lon=-75.5").get_json()
        assert d["grid"] == "0.5deg"
        assert d["cell"] == [36.0, -75.5]
        assert d["n_cases"] >= 1

    def test_snaps_an_off_grid_click_to_the_shared_cell(self, client, fake_db):
        """A click anywhere inside a cell scores that cell — no radius box."""
        fake_db(self._routes([0, 1, 2]))
        d = client.get("/api/spread-skill?model=UKMO&variable=precipitation"
                       "&lat=36.11&lon=-75.61").get_json()
        assert d["cell"] == [36.0, -75.5]

    def test_spread_is_across_members_only(self, client, fake_db):
        """n_members must equal the ensemble size, not members x cells — the
        defect that had a 50-member AIFS run reporting ~1200 'members'."""
        fake_db(self._routes([0, 1, 2], members=7))
        d = client.get("/api/spread-skill?model=UKMO&variable=precipitation"
                       "&lat=36.0&lon=-75.5").get_json()
        assert d["hours"], "expected at least one scored lead time"
        assert all(h["n_members"] == 7 for h in d["hours"])

    def test_reports_the_window_it_verified_over(self, client, fake_db):
        fake_db(self._routes([0, 1, 2]))
        d = client.get("/api/spread-skill?model=UKMO&variable=precipitation"
                       "&lat=36.0&lon=-75.5").get_json()
        for h in d["hours"]:
            assert h["period_h"] >= 1
            assert h["n_obs_in_window"] >= 1

    def test_no_members_is_empty_not_an_error(self, client, fake_db):
        fake_db(dict(self.ROUTES_BASE, **{"FROM regridded_forecast_member": []}))
        d = client.get("/api/spread-skill?model=UKMO&variable=precipitation"
                       "&lat=36.0&lon=-75.5").get_json()
        assert d["n_cases"] == 0 and d["hours"] == []
        assert "error" not in d
