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
