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

    def test_the_model_list_is_never_interpolated_into_sql(self):
        # Models reach here as allowlisted identifiers, but the predicate should
        # not have to rely on that a second time.
        pred, _params, _r = api._run_pairs_sql.__wrapped__(None, []) \
            if hasattr(api._run_pairs_sql, '__wrapped__') else (None, None, None)
        # The predicate is a constant string with placeholders only.
        src = inspect.getsource(api._run_pairs_sql)
        assert 'unnest(%s::text[], %s::timestamp[])' in src


class TestResolveInitTime:
    def test_a_malformed_timestamp_is_rejected(self):
        with pytest.raises(ValueError, match='not an ISO timestamp'):
            api._resolve_init_time(None, 'AIFS', 'not-a-date')

    def test_it_still_falls_back_to_the_latest_run_for_now(self, monkeypatch):
        # Documented, temporary, and the reason the frontend keeps working while
        # the schema moves ahead of it. DATA_EXPANSION_DESIGN phase 2 says this
        # becomes a 400; this test is what will have to change when it does.
        monkeypatch.setattr(api, '_latest_init_time', lambda cur, model: 'LATEST')
        assert api._resolve_init_time(None, 'AIFS', None) == 'LATEST'
        assert api._resolve_init_time(None, 'AIFS', '') == 'LATEST'
