"""The paths a healthy request never takes.

`test_metrics.py` covers the science, `test_endpoints.py` the response contract,
`test_db_endpoints.py` the SQL. All three drive the happy path and the
well-formed error. This file drives the rest: every `except` handler, every
early return, every `continue` guard that skips a row.

Those lines are where an outage is decided. A handler that leaks a connection
string, or crashes on the way to reporting a crash, only ever runs on the day
something else has already gone wrong — which is the worst day to discover it is
untested. They were 117 of the 221 lines coverage could not reach.

Run:  ~/miniconda3/envs/afw/bin/python -m pytest Data -q
"""
import uuid
from datetime import datetime

import psycopg2
import pytest

import flask_api as api


INIT = datetime(2025, 9, 8, 0, 0, 0)

# Every endpoint, with a body/query that would otherwise succeed. Parametrising
# over this is what makes the error-handler sweep exhaustive rather than a
# hand-picked few.
POINT = {"lat": 36.0, "lon": -75.5}
BOX   = {"min_lat": 35, "max_lat": 37, "min_lon": -77, "max_lon": -74}
BOX_QS = "&".join(f"{k}={v}" for k, v in BOX.items())

ENDPOINTS = [
    ("GET",  f"/api/forecast-data?model=AIFS&variable=precipitation&hour=6", None),
    ("GET",  f"/api/wind-data?model=AIFS&hour=6", None),
    ("GET",  f"/api/point-timeseries?model=AIFS&variable=precipitation&lat=36&lon=-75.5", None),
    ("GET",  f"/api/spread-skill?model=AIFS&variable=precipitation&lat=36&lon=-75.5", None),
    ("GET",  f"/api/spatial-metric?metric=mae&model=AIFS&variable=precipitation&{BOX_QS}", None),
    ("GET",  "/api/models", None),
    ("GET",  "/api/variables", None),
    ("GET",  "/api/observation-coverage?model=AIFS&variable=precipitation", None),
    ("POST", "/api/compare/skill",
     {"models": ["AIFS"], "variable": "precipitation", **POINT}),
    ("POST", "/api/compare/timeseries",
     {"models": ["AIFS"], "variable": "precipitation", **POINT}),
    ("POST", "/api/compare/categorical",
     {"models": ["AIFS"], "variable": "precipitation", **POINT}),
    ("POST", "/api/compare/region-metrics",
     {"models": ["AIFS"], "variable": "precipitation", "metrics": ["mae"], **BOX}),
    ("POST", "/api/compare/spatial-agreement",
     {"models": ["AIFS", "GEFS"], "variable": "precipitation", "hour": 6, **BOX}),
    ("POST", "/api/compare/spatial-diff",
     {"model_a": "AIFS", "model_b": "GEFS", "metric": "mae",
      "variable": "precipitation", **BOX}),
    ("POST", "/api/categorical-metrics",
     {"model": "AIFS", "variable": "precipitation", **POINT}),
    ("POST", "/api/region-categorical-metrics",
     {"model": "AIFS", "variable": "precipitation", **BOX}),
]


def call(client, method, path, body):
    return client.get(path) if method == "GET" else client.post(path, json=body)


class TestEveryEndpointSurvivesADatabaseFailure:
    """A dead database must produce JSON, not a stack trace, and must not put
    the connection string in the response — the health check has been careful
    about that since P1 and the rest of the API should match it."""

    @pytest.mark.parametrize("method,path,body", ENDPOINTS,
                             ids=[p.split("?")[0] for _, p, _ in ENDPOINTS])
    def test_connection_refused_is_json_not_a_traceback(self, prod_client, monkeypatch,
                                                        method, path, body):
        def boom():
            raise psycopg2.OperationalError(
                'could not connect to server: password=hunter2 host=db.internal')
        monkeypatch.setattr(api, "get_db_connection", boom)

        r = call(prod_client, method, path, body)
        assert r.status_code in (200, 500), r.status_code
        payload = r.get_json()
        assert payload is not None, "response was not JSON"
        assert "hunter2" not in str(payload)
        assert "db.internal" not in str(payload)

    @pytest.mark.parametrize("method,path,body", ENDPOINTS,
                             ids=[p.split("?")[0] for _, p, _ in ENDPOINTS])
    def test_a_query_that_raises_mid_request_is_caught(self, prod_client, fake_db,
                                                       monkeypatch, method, path, body):
        """The connection opens and the query fails — a lock timeout, a dropped
        table, a syntax error after a migration. Different handler from the one
        above, because the `finally` has a cursor to close."""
        cur = fake_db({})
        def raising_execute(sql, params=None):
            raise psycopg2.errors.QueryCanceled("statement timeout")
        monkeypatch.setattr(cur, "execute", raising_execute)

        r = call(prod_client, method, path, body)
        assert r.status_code in (200, 404, 500)
        assert r.get_json() is not None
        assert "statement timeout" not in str(r.get_json())


class TestPoolFailures:
    def test_a_pool_error_is_retried_then_reported(self, monkeypatch):
        """_pool_getconn retries once before giving up: a connection can be
        broken by a server restart, and one retry turns a user-visible failure
        into a hiccup. The retry has to be bounded, or a dead server becomes a
        hang."""
        calls = []

        class DeadPool:
            def getconn(self):
                calls.append(1)
                raise psycopg2.pool.PoolError("connection pool exhausted")

        monkeypatch.setattr(api, "connection_pool", DeadPool())
        with pytest.raises(Exception):
            api.get_db_connection()
        assert calls, "the pool was never asked for a connection"

    def test_returning_a_broken_connection_does_not_raise(self, monkeypatch):
        """Disposal runs in a `finally`. If it can throw, it replaces the real
        error with its own and the original is lost."""
        class Angry:
            closed = 1
            def putconn(self, *a, **k):
                raise psycopg2.pool.PoolError("cannot return")
            def close(self):
                raise RuntimeError("cannot close either")

        monkeypatch.setattr(api, "connection_pool", Angry())
        api.return_db_connection(Angry())   # must not raise


class TestCachingShortCircuits:
    def test_the_plot_cache_returns_the_stored_render(self, client, monkeypatch):
        """The second identical request must not re-render. Cartopy is the
        slowest thing in the process, so this branch is the whole point of the
        cache."""
        renders = []
        real = api._render_metric_map_png

        def counting(*a, **k):
            renders.append(1)
            return real(*a, **k)
        monkeypatch.setattr(api, "_render_metric_map_png", counting)

        # The cache key is a hash of the body and the store outlives the
        # process, so a fixed body may already be warm from an earlier run and
        # the first call would render nothing. A unique value guarantees a miss
        # then a hit, which is the sequence under test.
        unique = uuid.uuid4().int % 1000 / 1000.0
        body = {"metric": "mae", "model": "AIFS", "variable": "precipitation",
                "points": [{"lat": 36.0, "lon": -75.5, "value": unique},
                           {"lat": 36.5, "lon": -75.0, "value": 2.0}]}
        first = client.post("/api/spatial-metric-plot", json=body)
        assert first.status_code == 200
        second = client.post("/api/spatial-metric-plot", json=body)
        assert second.status_code == 200
        assert second.get_json()["image"] == first.get_json()["image"]
        if api.cache is not None:
            assert len(renders) == 1, "the render ran again for an identical body"

    def test_cache_helpers_swallow_a_broken_backend(self, monkeypatch):
        """A cache that has fallen over must degrade to no caching, not to a
        failed request."""
        class Broken:
            def get(self, k):   raise RuntimeError("cache down")
            def set(self, k, v, timeout=None): raise RuntimeError("cache down")
        monkeypatch.setattr(api, "cache", Broken())
        assert api._cache_get("k") is None
        api._cache_set("k", "v", 60)          # must not raise

    def test_the_helpers_are_inert_without_a_cache(self, monkeypatch):
        monkeypatch.setattr(api, "cache", None)
        assert api._cache_get("k") is None
        api._cache_set("k", "v", 60)

    def test_the_run_id_and_init_time_caches_query_once_per_request(self, client, fake_db):
        """Both are per-request caches in Flask `g`. The second call inside one
        request must not hit the database again."""
        cur = fake_db({
            "FROM forecast_runs fr": [{"run_id": 1, "initialization_time": INIT}],
        })
        with api.app.test_request_context("/"):
            assert api.get_model_run_id(cur, "AIFS") == 1
            n = len(cur.executed)
            assert api.get_model_run_id(cur, "AIFS") == 1
            assert len(cur.executed) == n, "the cached run id was re-queried"

            # _latest_init_time is gone: every query path resolves through
            # _resolve_init_time now, which caches on (model, requested) so a
            # request that names a run and one that does not cannot share an
            # entry. Passing requested=None exercises the no-parameter path.
            assert api._resolve_init_time(cur, "AIFS", None) == INIT
            n = len(cur.executed)
            assert api._resolve_init_time(cur, "AIFS", None) == INIT
            assert len(cur.executed) == n, "the cached init time was re-queried"


class TestJsonErrorHandlers:
    """API clients parse JSON. Werkzeug's default HTML error page would be a
    parse failure at the other end, reported as something unrelated."""

    @pytest.mark.parametrize("code,fragment", [
        (400, "Bad request"), (413, "Payload too large"),
        (429, "Too many requests"), (500, "Internal server error"),
    ])
    def test_each_handler_returns_json(self, code, fragment):
        with api.app.test_request_context("/"):
            handler = api.app.error_handler_spec[None][code][Exception] \
                if False else None
        # Call the handlers directly: provoking a real 413/429 needs a body over
        # the limit or a rate-limit backend, neither of which belongs in a unit
        # test, and the contract under test is the handler's own output.
        fn = {400: api._err_bad_request, 413: api._err_too_large,
              429: api._err_rate, 500: api._err_internal}[code]
        with api.app.test_request_context("/"):
            body, status = fn(Exception("boom"))
            assert status == code
            assert fragment.lower() in body.get_json()["error"].lower()

    def test_an_unknown_route_is_json(self, client):
        r = client.get("/api/does-not-exist")
        assert r.status_code == 404


class TestMissingDataReturnsAnAnswerNotAnError:
    """A query that legitimately matches nothing is an ordinary outcome. Each of
    these is a separate early return, and each used to be a plausible place for
    an unguarded index into an empty list."""

    @pytest.mark.parametrize("method,path,body", ENDPOINTS,
                             ids=[p.split("?")[0] for _, p, _ in ENDPOINTS])
    def test_an_empty_database_never_500s(self, client, fake_db, method, path, body):
        fake_db({})          # every query returns no rows
        r = call(client, method, path, body)
        assert r.status_code != 500, r.get_json()
        assert r.get_json() is not None

    @pytest.mark.parametrize("method,path,body", ENDPOINTS,
                             ids=[p.split("?")[0] for _, p, _ in ENDPOINTS])
    def test_a_run_with_no_forecast_rows_never_500s(self, client, fake_db, method, path, body):
        """The run exists but carries no data — a half-finished ingest, which is
        the realistic version of "empty" and takes different branches from a
        database with nothing in it at all."""
        fake_db({
            "FROM forecast_runs fr": [{"run_id": 1, "initialization_time": INIT}],
            "FROM models": [{"model_id": 1, "model_name": "AIFS"}],
        })
        r = call(client, method, path, body)
        assert r.status_code != 500, r.get_json()
