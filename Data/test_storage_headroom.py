"""Tests for the storage headroom check — `DATA_EXPANSION_DESIGN.md` phase 5.

Phase 5's retention decision, taken 2026-10-01, was **no limit yet, revisit at
250 GB**. The risk in a decision shaped like that is not that the number is
wrong; it is that nothing says the number has been reached. "Revisit at 250 GB"
written in a design document is read by whoever is already looking for it, which
is never the person about to start a 55 GB ingest.

So the threshold is reported by `/api/health` and printed at startup, the same
treatment `_check_pool_headroom` gets and for the same reason: a condition that
is only documented is discovered too late.

Like the pool tests, these drive a fake cursor. The arithmetic is the part worth
pinning and none of it needs PostgreSQL. The one test that matters most is
`test_it_actually_trips` — a threshold that cannot go unsafe is decoration.
"""
import pytest

import flask_api as api


GB = 1024 ** 3


class FakeCursor:
    """Answers the three statements `_check_storage_headroom` issues.

    Raises on anything else, so a change to the check's queries fails here
    rather than quietly reporting figures derived from something else — the
    same contract as `test_pool_headroom.FakeCursor`.
    """

    def __init__(self, size_gb=123.52, runs=3, model_runs=8):
        self.size_gb = size_gb
        self.runs = runs
        self.model_runs = model_runs
        self._answer = None

    def execute(self, sql, params=None):
        if 'pg_database_size' in sql:
            self._answer = (int(self.size_gb * GB),)
        elif 'COUNT(DISTINCT initialization_time)' in sql:
            self._answer = (self.runs,)
        elif 'COUNT(*) FROM forecast_runs' in sql:
            self._answer = (self.model_runs,)
        else:
            raise AssertionError(f'unexpected query: {sql}')

    def fetchone(self):
        return self._answer


class TestTheMeasuredState:
    """Figures from the 2026-10-01 measurement, which is what the threshold was
    chosen against."""

    def test_today_is_under_the_threshold(self):
        r = api._check_storage_headroom(FakeCursor())
        assert r['safe'] is True
        assert r['database_gb'] == pytest.approx(123.52, abs=0.01)
        assert r['headroom_gb'] == pytest.approx(126.48, abs=0.01)

    def test_it_says_how_many_more_runs_fit(self):
        """The number someone wants before starting a load, not after. Three
        runs in 123.52 GB is ~41.2 GB each, so 126.48 GB of headroom takes
        three more."""
        r = api._check_storage_headroom(FakeCursor())
        assert r['mean_gb_per_run'] == pytest.approx(41.17, abs=0.01)
        assert r['runs_until_revisit'] == 3

    def test_runs_are_initialisations_not_model_run_pairs(self):
        """`forecast_runs` holds one row per (model, init), so counting it
        directly would report 8 runs where 3 initialisations are loaded and
        divide the footprint by the wrong number."""
        r = api._check_storage_headroom(FakeCursor(runs=3, model_runs=8))
        assert r['runs'] == 3
        assert r['model_runs'] == 8


class TestItActuallyTrips:
    """Guards the guard. A threshold that cannot report `safe: False` is
    decoration, and this repo has shipped assertions that could not fail before
    (`test_a_grid_mismatch_is_refused`, the complement-covers-a-set one)."""

    def test_it_actually_trips(self):
        r = api._check_storage_headroom(FakeCursor(size_gb=260.0))
        assert r['safe'] is False
        assert r['headroom_gb'] < 0

    def test_the_boundary_is_not_safe(self):
        """At exactly the threshold the review is due, so `<` not `<=`."""
        assert api._check_storage_headroom(
            FakeCursor(size_gb=api.DB_SIZE_REVISIT_GB))['safe'] is False

    def test_two_more_runs_would_cross_it(self):
        """The decision's whole premise: at the measured 55.30 GB for a
        three-model run, 250 GB is a little over two runs away. If this stops
        being true the threshold wants revisiting, not the test."""
        measured_three_model_run = 55.30
        assert 123.52 + 2 * measured_three_model_run < api.DB_SIZE_REVISIT_GB
        assert 123.52 + 3 * measured_three_model_run > api.DB_SIZE_REVISIT_GB


class TestItDoesNotBreakAnything:
    def test_an_empty_database_does_not_divide_by_zero(self):
        """A fresh box starts with no runs — which is exactly the reviewer
        deployment's starting state (§10), so this path is reached in practice
        rather than hypothetically."""
        r = api._check_storage_headroom(FakeCursor(size_gb=0.01, runs=0,
                                                   model_runs=0))
        assert r['mean_gb_per_run'] == 0.0
        assert r['runs_until_revisit'] is None
        assert r['safe'] is True

    def test_the_threshold_is_overridable_without_an_edit(self, monkeypatch):
        """So a smaller host can carry a smaller number without a code change —
        the reviewer box may well have less disk than this machine."""
        monkeypatch.setattr(api, 'DB_SIZE_REVISIT_GB', 100.0)
        r = api._check_storage_headroom(FakeCursor())
        assert r['revisit_at_gb'] == 100.0
        assert r['safe'] is False

    def test_being_over_is_not_an_error(self):
        """`safe: False` means a decision is due, not that anything is broken,
        so the check returns a dict either way and never raises. /api/health
        stays `healthy` — the endpoint reports the condition rather than
        failing on it."""
        over = api._check_storage_headroom(FakeCursor(size_gb=999.0))
        assert over['safe'] is False
        assert set(over) == set(api._check_storage_headroom(FakeCursor()))
