"""Every regridded read is scoped to one forecast run.

`regridded_forecast_ens` and `regridded_forecast_member` gained `init_time` in
`migrate_init_time.py`. Adding the column is the easy half; the half that
actually protects anything is that **every** query filters on it. A query that
forgets returns rows from every loaded run blended together, with no error and
no empty result to notice — the same failure the migration exists to prevent,
just relocated from the schema to one SELECT.

There is only one run loaded, so a behavioural test cannot tell a filtered query
from an unfiltered one: both return the same rows. These tests therefore read the
source, which is unusual and deliberate. The alternative — seeding a second run
into the fixture — is the better test and a much larger change; this is the guard
that can exist today, and it fails loudly if a new query is added without the
predicate.
"""
import inspect
import re
from datetime import datetime

import pytest

import flask_api as api


REGRIDDED = ('regridded_forecast_ens', 'regridded_forecast_member')


# The one query that must NOT be scoped to a run: the one that lists the runs.
# `available_runs`' fallback groups by init_time to enumerate what is loaded, so
# filtering it to a single run would make /api/runs report only that run and the
# selector would never offer a second. Recognised by its GROUP BY rather than by
# name, so a rewrite of the same query stays exempt and an unrelated query
# cannot borrow the exemption.
def _enumerates_runs(stmt):
    return 'GROUP BY' in stmt and 'init_time' in stmt.split('GROUP BY', 1)[1]


def _sql_statements(source):
    """Every triple-quoted block that reads a regridded forecast table."""
    blocks = re.findall(r'"""(.*?)"""', source, re.DOTALL)
    return [b for b in blocks
            if any(t in b for t in REGRIDDED)
            and re.search(r'\bSELECT\b', b)
            and not _enumerates_runs(b)]


class TestEveryRegriddedQueryIsRunScoped:
    def test_the_source_has_such_queries_to_check(self):
        # Guard against the regex silently matching nothing, which would make
        # every test below vacuously true.
        stmts = _sql_statements(inspect.getsource(api))
        assert len(stmts) >= 5, f'only found {len(stmts)} regridded SELECTs'

    def test_every_one_filters_on_init_time(self):
        offenders = []
        for stmt in _sql_statements(inspect.getsource(api)):
            # Either an equality against a bound run, or the multi-model tuple
            # membership test that `_run_pairs_sql` produces.
            scoped = ('init_time = %s' in stmt
                      or 'init_time)' in stmt          # (model_name, init_time) IN ...
                      or '{_runw}' in stmt)
            if not scoped:
                first = next((l.strip() for l in stmt.splitlines() if l.strip()), '')
                offenders.append(first[:90])
        assert offenders == [], (
            'regridded SELECT(s) with no init_time filter — they would blend '
            f'runs once a second one is loaded: {offenders}')

    def test_the_wind_self_join_matches_on_the_run(self):
        # `_fcst_speed_sql` joins the ens table to itself to pair u with v. The
        # caller's filter constrains `u` only, so without this the pairing would
        # cross initialisations and compose a speed from two forecasts.
        _sel, from_clause, _varw, _vnn = api._fcst_speed_sql(True, 'u.latitude')
        assert 'v.init_time = u.init_time' in from_clause

    def test_the_precipitation_branch_needs_no_join(self):
        _sel, from_clause, _varw, _vnn = api._fcst_speed_sql(False, 'u.latitude')
        assert 'JOIN' not in from_clause


class TestRunPairsSql:
    """The multi-model predicate: one run per model, not one run for all."""

    class FakeCursor:
        def __init__(self, times):
            self._times = times
            self._row = None

        def execute(self, sql, params=None):
            self._row = None

        def fetchone(self):
            return self._row

    def test_it_pairs_each_model_with_its_own_run(self, monkeypatch):
        times = {'AIFS': 'T1', 'GEFS': 'T2'}
        monkeypatch.setattr(api, '_resolve_init_time',
                            lambda cur, model, requested: times.get(model))
        pred, params, resolved = api._run_pairs_sql(None, ['AIFS', 'GEFS'])
        assert resolved == times
        # Models and times travel as parallel arrays, so the pairing is
        # positional — a single init_time would be wrong for all but one model.
        assert params == [['AIFS', 'GEFS'], ['T1', 'T2']]
        assert 'unnest' in pred and 'model_name, u.init_time) IN' in pred

    def test_a_model_with_no_run_is_dropped_not_matched_to_another(self, monkeypatch):
        monkeypatch.setattr(api, '_resolve_init_time',
                            lambda cur, model, requested:
                                None if model == 'GEFS' else 'T1')
        pred, params, resolved = api._run_pairs_sql(None, ['AIFS', 'GEFS'])
        assert resolved == {'AIFS': 'T1'}
        assert params == [['AIFS'], ['T1']]

    def test_the_model_list_is_never_interpolated_into_sql(self, monkeypatch):
        # Models reach here as allowlisted identifiers, but the predicate should
        # not have to rely on that a second time. A name that would be hostile if
        # interpolated must come back as a bound parameter, not as SQL.
        monkeypatch.setattr(api, '_resolve_init_time',
                            lambda cur, model, requested: 'T1')
        hostile = "AIFS'; DROP TABLE regridded_forecast_ens; --"
        pred, params, _r = api._run_pairs_sql(None, [hostile])
        assert hostile not in pred
        assert params[0] == [hostile]
        assert 'unnest(%s::text[], %s::timestamp[])' in pred


class RunsCursor:
    """A cursor that reports a fixed set of runs for any model."""

    def __init__(self, runs):
        self._runs = runs
        self._rows = []

    def execute(self, sql, params=None):
        if 'SELECT 1 FROM forecast_runs' in sql:          # existence check
            wanted = params[1]
            self._rows = [{'x': 1}] if wanted in self._runs else []
        else:                                             # enumerate runs
            self._rows = [{'initialization_time': t}
                          for t in sorted(self._runs, reverse=True)]

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class TestResolveInitTime:
    def test_a_malformed_timestamp_is_rejected(self):
        with pytest.raises(api.RunSelectionError, match='not an ISO timestamp'):
            api._resolve_init_time(None, 'AIFS', 'not-a-date')

    def test_a_run_that_is_not_loaded_is_rejected(self):
        cur = RunsCursor([datetime(2025, 9, 8)])
        with pytest.raises(api.RunSelectionError, match='no AIFS run at init_time'):
            api._resolve_init_time(cur, 'AIFS', '2025-09-09T00:00:00')

    def test_a_loaded_run_is_honoured_exactly(self):
        cur = RunsCursor([datetime(2025, 9, 8)])
        assert api._resolve_init_time(
            cur, 'AIFS', '2025-09-08T00:00:00') == datetime(2025, 9, 8)

    def test_one_loaded_run_needs_no_parameter(self):
        # Not a guess: with a single run there is nothing to pick between, so
        # defaulting states a fact. This is the deliberate departure from
        # DATA_EXPANSION_DESIGN phase 2's unconditional requirement.
        cur = RunsCursor([datetime(2025, 9, 8)])
        assert api._resolve_init_time(cur, 'AIFS', None) == datetime(2025, 9, 8)

    def test_several_loaded_runs_make_the_parameter_mandatory(self):
        # The point of the whole migration. The moment ambiguity exists the API
        # refuses rather than silently choosing the newest.
        cur = RunsCursor([datetime(2025, 9, 8), datetime(2025, 9, 9)])
        with pytest.raises(api.RunSelectionError, match='2 loaded runs'):
            api._resolve_init_time(cur, 'AIFS', None)

    def test_the_refusal_names_where_to_look(self):
        cur = RunsCursor([datetime(2025, 9, 8), datetime(2025, 9, 9)])
        with pytest.raises(api.RunSelectionError) as e:
            api._resolve_init_time(cur, 'AIFS', None)
        # A caller that gets this has to be able to act on it.
        assert 'init_time is required' in str(e.value)
        assert '2025-09-09' in str(e.value)

    def test_a_model_with_no_runs_resolves_to_none(self):
        # Endpoints already handle "no data for this model"; raising here would
        # turn an empty result into a 400.
        assert api._resolve_init_time(RunsCursor([]), 'AIFS', None) is None


class TestTheHttpContract:
    """What a caller sees. Two of these were 200-with-data and 500 until the
    end-to-end check ran, so they are pinned rather than assumed."""

    BOX = 'min_lat=35&max_lat=37&min_lon=-77&max_lon=-74'
    LOADED = '2025-09-08T00:00:00'

    @pytest.fixture
    def client(self):
        api.app.config['TESTING'] = True
        return api.app.test_client()

    def _spatial(self, client, init_time=None):
        q = f'/api/spatial-metric?metric=mae&model=AIFS&variable=wind&{self.BOX}'
        if init_time is not None:
            q += f'&init_time={init_time}'
        return client.get(q)

    def test_a_malformed_init_time_is_a_400_not_a_500(self, client):
        # The endpoints wrap their bodies in `except Exception -> 500`, which
        # swallowed this into a server error. A bad parameter is the caller's to
        # fix, and a 500 tells them nothing.
        r = self._spatial(client, 'yesterday')
        assert r.status_code == 400
        assert 'not an ISO timestamp' in r.get_json()['error']

    def test_the_error_says_where_to_find_valid_values(self, client):
        r = self._spatial(client, 'yesterday')
        assert '/api/runs' in r.get_json()['hint']

    def test_a_malformed_init_time_on_a_post_is_also_400(self, client):
        r = client.post('/api/compare/skill', json={
            'models': ['AIFS'], 'lat': 36.0, 'lon': -75.5,
            'variable': 'precipitation', 'init_time': 'yesterday'})
        assert r.status_code == 400
