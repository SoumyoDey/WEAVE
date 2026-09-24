"""Tests for the run registry.

The validation rules need no database and run anywhere. The read path is
exercised against the real registry, and skips itself without PostgreSQL like
`test_db_endpoints.py` and `test_regrid_observations.py`.

What is being pinned is mostly *refusals*. The registry's value is that it
declines to guess a convention, and a guess is not a crash — it is a plausible
number that is wrong by a factor. Every assertion below that expects an
exception is standing in for a precipitation field nobody would have
questioned.
"""
import os

import pytest

import run_registry as reg


class TestTheDeclaredConventions:
    def test_the_two_scaled_models_carry_their_divisors(self):
        """These are the numbers `SCALED_EXPORT_DIVISOR_HOURS` encodes, and the
        reason the constant cannot serve two runs: they describe this export,
        not the model."""
        assert reg.declared_for('AIFS', 'precipitation') == (reg.SCALED, 6.0)
        assert reg.declared_for('GEFS', 'precipitation') == (reg.SCALED, 3.0)

    def test_ukmo_is_unscaled_rather_than_missing(self):
        """The distinction the whole module exists for. UKMO was never scaled —
        its native rate is converted straight to mm/h — so `unscaled` is a fact
        about it, not an absence of information."""
        assert reg.declared_for('UKMO', 'precipitation') == (reg.UNSCALED, None)

    def test_wind_declares_nothing_because_there_is_no_window(self):
        """u and v are instantaneous. There is no accumulation period to divide
        by, so there is no convention to record."""
        assert reg.declared_for('AIFS', 'wind_u_10m') is None

    def test_an_unheard_of_model_is_undeclared(self):
        assert reg.declared_for('ECMWF_IFS', 'precipitation') is None


class TestRecordRefusesIncoherentRows:
    """`record` validates before it writes, so a bad row never reaches the
    table. These use a cursor that would raise if touched, proving the refusal
    happens before any SQL."""

    class ExplodingCursor:
        def execute(self, *a, **k):
            raise AssertionError('should have been rejected before any SQL')

    def test_scaled_without_a_divisor(self):
        """Says something was divided out without saying by what — the exact
        state that made the original convention take days to reconstruct."""
        with pytest.raises(ValueError, match='no export_divisor_h'):
            reg.record(self.ExplodingCursor(), 'NEW', 'precipitation',
                       '2025-09-09T00:00:00', convention=reg.SCALED)

    def test_unscaled_with_a_divisor(self):
        """Contradictory: an unscaled export has nothing to undo, so a divisor
        would be applied to data that was never divided."""
        with pytest.raises(ValueError, match='nothing to undo'):
            reg.record(self.ExplodingCursor(), 'NEW', 'precipitation',
                       '2025-09-09T00:00:00',
                       convention=reg.UNSCALED, export_divisor_h=6.0)

    def test_a_convention_that_is_not_one(self):
        with pytest.raises(ValueError, match='unknown convention'):
            reg.record(self.ExplodingCursor(), 'NEW', 'precipitation',
                       '2025-09-09T00:00:00', convention='per-window')


# ── Against the real database ─────────────────────────────────────────────────

def _skip_reason():
    if os.environ.get('WEAVE_SKIP_DB_TESTS'):
        return 'WEAVE_SKIP_DB_TESTS is set'
    try:
        import psycopg2
        psycopg2.connect(**reg.DB_CONFIG).close()
    except Exception as exc:                                  # pragma: no cover
        return f'no database: {type(exc).__name__}'
    return None


@pytest.fixture(scope='module')
def cur():
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)
    import psycopg2
    from psycopg2.extras import RealDictCursor
    conn = psycopg2.connect(**reg.DB_CONFIG)
    with conn.cursor(cursor_factory=RealDictCursor) as c:
        yield c
    conn.rollback()      # read-only: never leave anything behind
    conn.close()


@pytest.fixture
def writable():
    """A cursor for the write-path tests, rolled back afterwards.

    Never committed, so these exercise the real upsert against the real table
    without leaving a fabricated run behind for the app — or for the read-path
    tests above — to find.
    """
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)
    import psycopg2
    from psycopg2.extras import RealDictCursor
    conn = psycopg2.connect(**reg.DB_CONFIG)
    with conn.cursor(cursor_factory=RealDictCursor) as c:
        reg.ensure_schema(c)
        yield c
    conn.rollback()
    conn.close()


FUTURE_RUN = '2099-01-01 06:00:00'


class TestTheUpsertIsIdempotent:
    """Phase 4, item 1: every step re-runnable without duplicating rows.

    A loader that fails halfway and is re-run is the normal case, not the
    exceptional one, so this has to be boring rather than careful.
    """

    def _rows(self, cur):
        cur.execute(f"""SELECT n_members, hour_min, hour_max, export_convention,
                              export_divisor_h
                       FROM {reg.TABLE}
                      WHERE model_name='AIFS' AND variable_name='precipitation'
                        AND init_time=%s""", (FUTURE_RUN,))
        return cur.fetchall()

    def test_recording_twice_leaves_one_row(self, writable):
        for _ in range(2):
            reg.record(writable, 'AIFS', 'precipitation', FUTURE_RUN,
                       n_members=50, hour_min=6, hour_max=360)
        assert len(self._rows(writable)) == 1

    def test_a_re_run_updates_rather_than_conflicting(self, writable):
        reg.record(writable, 'AIFS', 'precipitation', FUTURE_RUN,
                   n_members=50, hour_min=6, hour_max=120)
        reg.record(writable, 'AIFS', 'precipitation', FUTURE_RUN,
                   n_members=50, hour_min=6, hour_max=360)
        assert self._rows(writable)[0]['hour_max'] == 360

    def test_the_declared_convention_is_applied_without_being_asked_for(self, writable):
        reg.record(writable, 'AIFS', 'precipitation', FUTURE_RUN,
                   n_members=50, hour_min=6, hour_max=360)
        row = self._rows(writable)[0]
        assert row['export_convention'] == reg.SCALED
        assert row['export_divisor_h'] == 6.0


class TestTwoRunsCanDisagree:
    """The reason the convention moved out of a constant at all.

    `SCALED_EXPORT_DIVISOR_HOURS` says GEFS was divided by 3. NEXT_STEPS.md's
    standing decision is that GEFS will not be re-exported, so that is
    permanent *for the loaded run* — and the failure mode it warns about is
    that a re-export would need the constant changed in the same commit, or
    the correction applies twice. Per-run storage removes that coupling
    entirely, which is what this proves.
    """

    def test_a_re_export_records_its_own_divisor_and_leaves_the_old_run_alone(self, writable):
        reg.record(writable, 'GEFS', 'precipitation', FUTURE_RUN,
                   n_members=30, hour_min=0, hour_max=240,
                   convention=reg.SCALED, export_divisor_h=6.0)

        # The new run says 6h...
        assert reg.resolve_divisor(writable, 'GEFS', 'precipitation', FUTURE_RUN) == 6.0
        # ...while the loaded run still says 3h, untouched.
        assert reg.resolve_divisor(writable, 'GEFS', 'precipitation', RUN) == 3.0

    def test_a_model_can_become_unscaled_in_a_later_run(self, writable):
        reg.record(writable, 'GEFS', 'precipitation', FUTURE_RUN,
                   n_members=30, hour_min=0, hour_max=240,
                   convention=reg.UNSCALED)
        assert reg.resolve_divisor(writable, 'GEFS', 'precipitation', FUTURE_RUN) is None
        assert reg.resolve_divisor(writable, 'GEFS', 'precipitation', RUN) == 3.0


class TestAnUndeclaredModelIsRecordedHonestly:
    def test_it_is_written_but_refuses_to_resolve(self, writable):
        """A new model can be loaded before anyone declares its convention —
        the registry should hold the row so the run appears in /api/runs, and
        still refuse to invent a divisor for it."""
        reg.record(writable, 'ECMWF_IFS', 'precipitation', FUTURE_RUN,
                   n_members=51, hour_min=0, hour_max=240)
        with pytest.raises(reg.UnknownConventionError, match='no declared'):
            reg.resolve_divisor(writable, 'ECMWF_IFS', 'precipitation', FUTURE_RUN)


RUN = '2025-09-08 00:00:00'


class TestResolvingAgainstTheLoadedRun:
    def test_the_scaled_models_resolve_to_their_divisors(self, cur):
        assert reg.resolve_divisor(cur, 'AIFS', 'precipitation', RUN) == 6.0
        assert reg.resolve_divisor(cur, 'GEFS', 'precipitation', RUN) == 3.0

    def test_unscaled_resolves_to_None_which_is_an_answer(self, cur):
        """None here means "nothing to undo" and is a successful resolution.
        The failure mode being avoided is treating it as "unknown" and either
        raising on a perfectly well-described run, or defaulting."""
        assert reg.resolve_divisor(cur, 'UKMO', 'precipitation', RUN) is None

    def test_wind_resolves_too_after_the_backfill(self, cur):
        """Wind declares `unscaled` rather than staying silent, so the read
        path does not trip over a variable that simply has no window."""
        assert reg.resolve_divisor(cur, 'AIFS', 'wind_u_10m', RUN) is None

    def test_an_unloaded_run_raises_rather_than_falling_back(self, cur):
        """The scenario phase 4 item 3 is about: a second run present in the
        data but never recorded would otherwise be scored with whatever the
        first run's export happened to do."""
        with pytest.raises(reg.UnknownConventionError, match='not in'):
            reg.resolve_divisor(cur, 'AIFS', 'precipitation', '2099-01-01 00:00:00')

    def test_an_unknown_model_raises(self, cur):
        """`metrics._increment_divisor` returns `period` for this case, which
        reads as unscaled. A model whose export divided by 6 would then be
        scored 6x high, and nothing would say so."""
        with pytest.raises(reg.UnknownConventionError):
            reg.resolve_divisor(cur, 'ECMWF_IFS', 'precipitation', RUN)


class TestTheBackfillLeftNothingUndeclared:
    def test_every_row_names_its_convention(self, cur):
        """An undeclared row is a landmine for the read path, so there should
        be none once the backfill has run."""
        cur.execute(f"""
            SELECT model_name, variable_name FROM {reg.TABLE}
            WHERE export_convention IS NULL
        """)
        assert cur.fetchall() == []

    def test_the_named_convention_agrees_with_the_divisor(self, cur):
        """The two columns must not contradict each other: `scaled` with no
        divisor, or `unscaled` with one, is the incoherent state `record`
        refuses to write and the backfill must not create."""
        cur.execute(f"""
            SELECT model_name, variable_name, export_convention, export_divisor_h
            FROM {reg.TABLE}
            WHERE (export_convention = %s AND export_divisor_h IS NULL)
               OR (export_convention = %s AND export_divisor_h IS NOT NULL)
        """, (reg.SCALED, reg.UNSCALED))
        assert cur.fetchall() == []

    def test_it_still_agrees_with_the_constant_scoring_uses(self, cur):
        """Scoring still reads `SCALED_EXPORT_DIVISOR_HOURS`. Until that moves
        onto the registry, the two must not drift — a disagreement here means
        one of them is silently wrong about the loaded run."""
        from metrics import SCALED_EXPORT_DIVISOR_HOURS
        for model, divisor in SCALED_EXPORT_DIVISOR_HOURS.items():
            assert reg.resolve_divisor(cur, model, 'precipitation', RUN) == divisor
