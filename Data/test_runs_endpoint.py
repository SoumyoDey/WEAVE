"""`/api/runs` and `available_runs` — the endpoint the run selector waits on.

Written 2026-10-01 because these had **no test at all**. `flask_api.py` was
documented at 100% statement coverage and measured at 97%; of the 54 uncovered
statements, 21 are the `/api/runs` body and 6 are `available_runs`. Three places
in the suite mentioned the path — a comment, a docstring, and an assertion that
a *different* endpoint's 400 hint contains the string `/api/runs` — and none of
them ever issued a request to it (NEXT_STEPS.md §33).

That matters more than 27 statements suggests. `src/App.js` fetches nothing
model-scoped until this endpoint answers, so every model-dependent view in the
app is behind it, and `RunContext.jsx` reads four separate shapes out of the
response (`runs`, `latest`, `detail`, and `detail[].models[].variables[]`).

**The contract test is the important one here.** `RunContext.jsx` carries a
comment recording a defect found by hand: the UI calls the variable `wind` while
the database stores `wind_u_10m` and `wind_v_10m`, and a mocked payload written
in the UI's spelling agreed with itself while the live endpoint did not — "a
mock agrees with whatever you wrote it to say". `STORED_VARIABLES` exists to
bridge that. `TestTheContractRunContextReads` pins the backend half against real
SQL, so the next such disagreement fails here instead of being found by someone
checking the live endpoint.

These use conftest's `db_client`, not a hand-rolled test client. That is not
incidental: `conftest.py` replaces the psycopg2 pool with a MagicMock before
`flask_api` is imported, so a client built any other way talks to a mock whose
cursor iterates empty and every assertion below would pass on `[]`. That is
exactly how `test_point_list_caps.py` managed nine tests that verified nothing
(§28).
"""
import datetime

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

import flask_api as api
import fixture_db as fx


# What `fixture_db.seed()` registers: three models x three variables at one init.
EXPECTED_MODELS    = set(fx.MODELS)
EXPECTED_VARIABLES = {'precipitation', 'wind_u_10m', 'wind_v_10m'}
EXPECTED_ENTRIES   = len(EXPECTED_MODELS) * len(EXPECTED_VARIABLES)
RUN_ISO            = fx.INIT_TIME.isoformat()


@pytest.fixture
def runs(db_client):
    """The parsed `/api/runs` body, asserted non-empty before anything reads it.

    Every assertion in this file is satisfied by an empty response — `runs` is
    a list, `latest` is None, no model disagrees with anything — so the guard
    belongs where nothing can route around it rather than in a test of its own
    that a later edit could reorder.
    """
    r = db_client.get('/api/runs')
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    body = r.get_json()
    assert body['entries'], 'no entries — every assertion below would be vacuous'
    return body


class TestTheShapeTheSelectorNeeds:
    def test_it_answers_with_the_four_documented_keys(self, runs):
        assert set(runs) == {'runs', 'latest', 'detail', 'entries'}

    def test_every_registered_combination_is_reported(self, runs):
        got = {(e['model_name'], e['variable_name']) for e in runs['entries']}
        assert got == {(m, v) for m in EXPECTED_MODELS for v in EXPECTED_VARIABLES}
        assert len(runs['entries']) == EXPECTED_ENTRIES

    def test_runs_is_the_distinct_init_times_and_latest_is_the_first(self, runs):
        assert runs['runs'] == [RUN_ISO]
        assert runs['latest'] == runs['runs'][0]

    def test_init_time_is_serialised_as_a_string_not_a_datetime(self, runs):
        """`jsonify` would render a datetime in RFC 822, which
        `RunContext.jsx` compares against ISO strings from the URL. The endpoint
        calls `.isoformat()` explicitly for that reason."""
        assert all(isinstance(e['init_time'], str) for e in runs['entries'])
        assert all(isinstance(t, str) for t in runs['runs'])
        datetime.datetime.fromisoformat(runs['latest'])      # parses, or raises

    def test_detail_lines_up_with_runs(self, runs):
        assert [d['init_time'] for d in runs['detail']] == runs['runs']

    def test_each_run_lists_its_models_and_variables(self, runs):
        d = runs['detail'][0]
        assert set(d['models']) == EXPECTED_MODELS
        assert set(d['variables']) == EXPECTED_VARIABLES
        for model, m in d['models'].items():
            assert m['n_members'] == len(fx.MEMBER_OFFSETS), model
            assert {v['variable'] for v in m['variables']} == EXPECTED_VARIABLES

    def test_the_variable_list_per_run_is_deduplicated(self, runs):
        """Three models each carry the same three variables, so the per-run
        `variables` list is built with a membership check. Without it this would
        be nine entries and the selector would show each variable three times."""
        d = runs['detail'][0]
        assert len(d['variables']) == len(set(d['variables'])) == 3


class TestTheContractRunContextReads:
    """The backend half of the UI/database variable-name disagreement.

    `RunContext.jsx` maps `wind -> ['wind_u_10m', 'wind_v_10m']` because looking
    up `wind` directly "finds nothing and returns null — which reads as 'this run
    has no wind' and would have disabled every lead-time clamp on the wind
    variable without erroring anywhere". That was found against the live endpoint
    rather than by a test, because the mocked payload used the UI's spelling.
    """

    def test_wind_is_reported_as_its_two_stored_components(self, runs):
        for model, m in runs['detail'][0]['models'].items():
            names = {v['variable'] for v in m['variables']}
            assert {'wind_u_10m', 'wind_v_10m'} <= names, model

    def test_the_uis_spelling_is_never_what_the_endpoint_returns(self, runs):
        """If `wind` ever appears here, `STORED_VARIABLES` silently stops being
        needed for some models and keeps being needed for others — which is
        worse than either answer on its own."""
        reported = {e['variable_name'] for e in runs['entries']}
        assert 'wind' not in reported
        assert 'wind_speed' not in reported

    def test_every_variable_carries_a_usable_lead_time_range(self, runs):
        """`hourRangeFor` does `Math.max(...entries.map(e => e.hour_min))` and
        rejects a non-finite result. A NULL from the registry arrives as JSON
        `null`, which `Math.max` coerces to 0 rather than rejecting — so the
        scrubber would clamp to {0, 0} instead of greying the model out. The
        endpoint must therefore report numbers, which means the registry must
        hold them."""
        for model, m in runs['detail'][0]['models'].items():
            for v in m['variables']:
                assert isinstance(v['hour_min'], int), (model, v)
                assert isinstance(v['hour_max'], int), (model, v)
                assert v['hour_min'] <= v['hour_max'], (model, v)

    def test_the_wind_components_share_a_range_so_the_intersection_is_non_empty(self, runs):
        """Wind is derived from u and v, so `hourRangeFor` intersects their
        ranges and returns null when `min > max`. Components that disagreed
        would silently remove wind from the selector."""
        for model, m in runs['detail'][0]['models'].items():
            u = next(v for v in m['variables'] if v['variable'] == 'wind_u_10m')
            w = next(v for v in m['variables'] if v['variable'] == 'wind_v_10m')
            assert max(u['hour_min'], w['hour_min']) <= min(u['hour_max'], w['hour_max']), model

    def test_the_export_divisor_is_carried_through_per_model(self, runs):
        """The registry's per-run convention, visible to a caller. AIFS and GEFS
        precipitation were scaled by different fixed divisors and UKMO's was not
        scaled at all — the distinction `run_registry.py` exists for."""
        divisors = {(e['model_name'], e['variable_name']): e['export_divisor_h']
                    for e in runs['entries']}
        assert divisors[('AIFS', 'precipitation')] == 6.0
        assert divisors[('GEFS', 'precipitation')] == 3.0
        assert divisors[('UKMO', 'precipitation')] is None
        assert divisors[('AIFS', 'wind_u_10m')] is None


# ── available_runs, directly ──────────────────────────────────────────────────
# Two behaviours the endpoint cannot reach from the fixture as seeded: ordering
# across more than one run, and the fallback for a database without the
# registry. Both are exercised against the fixture database on a connection of
# this module's own, inside transactions that are rolled back.

@pytest.fixture
def own_cur(fixture_db):
    """A cursor whose writes — including DDL — are rolled back.

    Its own connection, and the only one that touches these rows, so the
    ACCESS EXCLUSIVE lock the DROP below takes cannot wait on a reader in this
    same process. `lock_timeout` turns the self-deadlock §26 recorded into a
    fast, legible error rather than a hang with no timeout.
    """
    conn = psycopg2.connect(**fixture_db.db_config())
    with conn.cursor(cursor_factory=RealDictCursor) as c:
        c.execute("SET lock_timeout = '15s'")
        yield c
    conn.rollback()
    conn.close()


class TestAvailableRuns:
    def test_it_reads_the_registry_when_there_is_one(self, own_cur):
        rows = api.available_runs(own_cur)
        assert len(rows) == EXPECTED_ENTRIES
        assert all(r['init_time'] == fx.INIT_TIME for r in rows)

    def test_runs_come_back_newest_first(self, own_cur):
        """`ORDER BY init_time DESC` — the selector shows the newest run first
        and `latest` is literally `runs[0]`, so the ordering is the behaviour
        rather than a presentational detail. The fixture holds one run, so a
        second is added here and rolled back."""
        older = fx.INIT_TIME - datetime.timedelta(hours=6)
        own_cur.execute("""
            INSERT INTO forecast_run_registry
                (model_name, variable_name, init_time, n_members, export_convention)
            VALUES ('AIFS', 'precipitation', %s, 4, 'unscaled')
        """, (older,))
        times = [r['init_time'] for r in api.available_runs(own_cur)]
        assert times == sorted(times, reverse=True)
        assert times[0] == fx.INIT_TIME and older in times

    def test_it_falls_back_to_the_ens_table_without_a_registry(self, own_cur):
        """The documented reason the fallback exists: a database migrated only
        part-way should still answer rather than making `/api/runs` the one
        endpoint that needs the newest schema.

        Dropped inside this test's own transaction and rolled back, so the table
        is gone only for this connection's view of the database.
        """
        own_cur.execute("DROP TABLE forecast_run_registry")
        rows = api.available_runs(own_cur)
        assert rows, 'the fallback returned nothing'
        got = {(r['model_name'], r['variable_name']) for r in rows}
        assert got == {(m, v) for m in EXPECTED_MODELS for v in EXPECTED_VARIABLES}

    def test_the_fallback_answers_the_same_question_as_the_registry(self, own_cur):
        """Same combinations and same run, derived from the data instead of the
        record of it. The two differ only where they must: the ens table knows
        nothing about export conventions, so `export_divisor_h` is NULL."""
        registry = {(r['model_name'], r['variable_name'], r['init_time'])
                    for r in api.available_runs(own_cur)}
        own_cur.execute("DROP TABLE forecast_run_registry")
        fallback_rows = api.available_runs(own_cur)
        fallback = {(r['model_name'], r['variable_name'], r['init_time'])
                    for r in fallback_rows}
        assert fallback == registry
        assert all(r['export_divisor_h'] is None for r in fallback_rows)

    def test_the_fallback_derives_hours_from_the_data_it_can_see(self, own_cur):
        """`MIN`/`MAX` over `regridded_forecast_ens`, which is what the registry
        would have recorded. Checked against the fixture's own cadence rather
        than against the registry row, so agreeing for the wrong reason is not
        possible."""
        own_cur.execute("DROP TABLE forecast_run_registry")
        rows = {(r['model_name'], r['variable_name']): r
                for r in api.available_runs(own_cur)}
        for model in fx.MODELS:
            r = rows[(model, 'precipitation')]
            assert r['hour_min'] == min(fx.PRECIP_HOURS[model])
            assert r['hour_max'] == max(fx.PRECIP_HOURS[model])
            assert r['n_members'] == len(fx.MEMBER_OFFSETS)


class TestAnEmptyDatabaseAnswersHonestly:
    """No rows is a real answer, not an error — a fresh deployment has none.

    Driven through conftest's routing fake rather than by emptying the fixture:
    what is under test is how `get_runs` assembles a response from zero entries,
    which is Python rather than SQL.
    """

    def test_it_reports_no_runs_and_a_null_latest(self, client, fake_db):
        fake_db({'to_regclass': [{'ok': True}], 'FROM forecast_run_registry': []})
        body = client.get('/api/runs').get_json()
        assert body == {'runs': [], 'latest': None, 'detail': [], 'entries': []}

    def test_latest_is_null_rather_than_absent(self, client, fake_db):
        """The frontend does `data?.latest ?? null` and then selects a run from
        it; a missing key and an explicit null behave alike there, but only one
        of them says so."""
        fake_db({'to_regclass': [{'ok': True}], 'FROM forecast_run_registry': []})
        assert 'latest' in client.get('/api/runs').get_json()
