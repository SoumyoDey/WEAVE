"""Tests for the run registry.

The validation rules need no database and run anywhere. The read and write
paths are exercised against a real PostgreSQL registry — the throwaway one
`fixture_db.py` builds, not the development database. See below.

What is being pinned is mostly *refusals*. The registry's value is that it
declines to guess a convention, and a guess is not a crash — it is a plausible
number that is wrong by a factor. Every assertion below that expects an
exception is standing in for a precipitation field nobody would have
questioned.

── Which database these run against, and why ─────────────────────────────────

Until 2026-10-01 the database-backed tests connected to whatever
`run_registry.DB_CONFIG` named, which is `weave_weather` unless `DB_NAME` says
otherwise. `.github/workflows/tests.yml` sets `DB_USER`, `DB_PASSWORD`,
`DB_HOST` and `DB_PORT` for the backend job but not `DB_NAME`, and the service
container creates no database by that name — so every one of them skipped on
every run the repository has ever had. `778 passed, 41 skipped`, identically, on
ba3fa88, 7002a2d and 57a221c; the same suite on a machine with a database was
`819 passed` at ba3fa88, with no skips at all.

That gap was not cosmetic. On 2026-09-30 four of these tests failed locally
because they named `2025-09-08 00:00:00` and expected GEFS to resolve there,
which stopped being true when the mislabelled GEFS rows were deleted (§24).
CI was green through the broken state, green through the fix, and would have
been green had the fix been wrong.

So they run against the fixture database instead, which exists wherever
PostgreSQL does. `fixture_db.seed()` populates `forecast_run_registry` through
`run_registry.record()` itself — three models x three variables at one init —
so the read path has real rows to resolve against.

The trap in that move is the one NEXT_STEPS.md's Traps list names: *a refactor
can hollow out a test instead of failing it.* `_a_loaded_run` **skips** when a
combination is absent, so repointing these at a database that happened not to
hold GEFS precipitation would turn them green by emptying them — the same
non-result, reached through the data instead of the code.
`TestTheRegistryHoldsWhatTheseTestsResolve` is the guard: it asserts the
combinations are there and *fails* rather than skipping. The two resolution
tests that loop compare a whole dict for the same reason, so a combination that
went missing is a failure naming it rather than one fewer assertion.

`TestTheDevelopmentDatabaseIsCoherent` is the one part that stays local-only:
it audits rows that exist only on a development machine, so there is nothing in
CI for it to read. It says that when it skips, and the workflow says it too.
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

    def test_wind_is_declared_unscaled_rather_than_left_out(self):
        """u and v are instantaneous, so nothing was divided out — and saying
        so beats staying silent.

        Leaving wind undeclared was the first attempt and it drifted: the real
        database's backfill named it `unscaled` while a freshly built fixture
        left it NULL, so the same lookup returned None against one and raised
        against the other.
        """
        assert reg.declared_for('AIFS', 'wind_u_10m') == (reg.UNSCALED, None)
        assert reg.declared_for('UKMO', 'wind_v_10m') == (reg.UNSCALED, None)

    def test_an_unheard_of_model_is_undeclared(self):
        assert reg.declared_for('ECMWF_IFS', 'precipitation') is None


class TestEnsureSchemaIsTheColumnTheFixtureBuildsWith:
    """`ensure_schema` is the loader's additive migration; the fixture applies
    the same SQL at build time instead of per test (see the `writable` fixture
    for why). Both facts are pinned here so neither can move alone: a column
    added to `SCHEMA_ADDITIONS` reaches the fixture database without anyone
    remembering to, and `ensure_schema` cannot start doing something else.
    """

    class RecordingCursor:
        def __init__(self):
            self.executed = []

        def execute(self, sql, params=None):
            self.executed.append(sql)

    def test_it_executes_exactly_the_additions(self):
        c = self.RecordingCursor()
        reg.ensure_schema(c)
        assert c.executed == [reg.SCHEMA_ADDITIONS]

    def test_the_additions_are_what_the_fixture_database_is_built_from(self):
        import fixture_db as fx
        assert reg.SCHEMA_ADDITIONS in fx._schema_sql()

    def test_the_additions_are_idempotent_as_written(self):
        """A loader runs this against a database that may or may not predate the
        column, so it has to be re-runnable. `IF NOT EXISTS` is what makes that
        true, and it is the only reason the fixture can apply it at build time
        and a loader apply it again afterwards."""
        assert 'IF NOT EXISTS' in reg.SCHEMA_ADDITIONS


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


# ── Against the fixture database ──────────────────────────────────────────────
# Not the development one: see the module docstring for why that choice is the
# whole point of this file's 2026-10-01 revision.

def _registry_cursor(fixture_db, autocommit=False):
    """A RealDictCursor on the fixture database, and its connection."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    conn = psycopg2.connect(**fixture_db.db_config())
    conn.autocommit = autocommit
    return conn, conn.cursor(cursor_factory=RealDictCursor)


@pytest.fixture(scope='module')
def cur(fixture_db):
    """A read-only cursor on the fixture registry.

    `fixture_db` is conftest's session-scoped build. Depending on it rather than
    connecting to the database by name is deliberate: it guarantees the database
    has been created and seeded before this connection opens, and keeps it alive
    until the session tears it down, whatever order the modules are collected in.

    **autocommit, and that is load-bearing.** This fixture is module-scoped, so
    its connection outlives every test in the file. Inside a transaction, its
    first `SELECT` would take an ACCESS SHARE lock on `forecast_run_registry`
    and hold it, idle, until module teardown — and any later test wanting an
    ACCESS EXCLUSIVE lock on the same table would wait for a transaction that
    only this same (now blocked) process can end. Self-deadlock, no timeout.
    Nothing here writes, so there is no transaction worth keeping open.
    """
    conn, c = _registry_cursor(fixture_db, autocommit=True)
    with c:
        yield c
    conn.close()


@pytest.fixture
def writable(fixture_db):
    """A cursor for the write-path tests, rolled back afterwards.

    Never committed, so these exercise the real upsert against the real table
    without leaving a fabricated run behind for the read-path tests above — or
    for the endpoint tests that share this database — to find.

    It deliberately does **not** call `reg.ensure_schema()`. Against the
    development database that was a no-op; against the fixture it is real DDL
    on a table another connection in this same process is reading, which is the
    ACCESS EXCLUSIVE half of the deadlock described on `cur`. The column is
    already there: `fixture_db._schema_sql()` appends
    `run_registry.SCHEMA_ADDITIONS` to the DDL it builds the database from, for
    exactly this reason. `TestEnsureSchemaIsTheColumnTheFixtureBuildsWith`
    above pins that those two are the same statement, so the fixture cannot
    drift away from what a loader would add.
    """
    conn, c = _registry_cursor(fixture_db)
    with c:
        yield c
    conn.rollback()
    conn.close()


FUTURE_RUN = '2099-01-01 06:00:00'


def _loaded_run(cur, model_name, variable_name):
    """An `init_time` the registry holds for this combination, or None.

    These tests used to name `2025-09-08 00:00:00` for every model. That broke
    on 2026-09-30 when GEFS was removed from that run: the GEFS rows stored
    there were the 09-16 forecast under the wrong label, and GEFS does not
    exist on the cluster for 09-08 at all, so the *correct* database has no GEFS
    at that init (`NEXT_STEPS.md` §24). Four tests then failed against a
    database that had just been fixed.

    What they mean to pin is the read path — that a declared run resolves to its
    own divisor and that two runs can disagree — not which dates happen to be
    loaded. So they ask the registry which init holds a combination rather than
    asserting an inventory.
    """
    cur.execute(f"""
        SELECT init_time FROM {reg.TABLE}
         WHERE model_name = %s AND variable_name = %s
         ORDER BY init_time LIMIT 1
    """, (model_name, variable_name))
    row = cur.fetchone()
    return None if row is None else row['init_time']


def _a_loaded_run(cur, model_name, variable_name):
    """`_loaded_run`, skipping when the combination is absent.

    Safe *only* because `TestTheRegistryHoldsWhatTheseTestsResolve` asserts the
    combinations are present. On its own a skip here is indistinguishable from a
    pass, which is how a test gets hollowed out rather than broken.
    """
    run = _loaded_run(cur, model_name, variable_name)
    if run is None:
        pytest.skip(f'{model_name}/{variable_name} is not loaded in any run')
    return run


# Every (model, variable) the read-path tests below resolve against. Asserted
# present rather than discovered: `_a_loaded_run` skips, so a fixture that
# stopped seeding one of these would empty the tests instead of failing them.
RESOLVED_COMBINATIONS = (
    ('AIFS', 'precipitation'),
    ('GEFS', 'precipitation'),
    ('UKMO', 'precipitation'),
    ('AIFS', 'wind_u_10m'),
)


class TestTheRegistryHoldsWhatTheseTestsResolve:
    """The non-emptiness guard, asserted before anything reads through it.

    NEXT_STEPS.md's Traps list: *a refactor can hollow out a test instead of
    failing it* — two tests filtering on `lat == 35.0` passed vacuously once
    UKMO moved to a grid with no cell there. Repointing the registry tests at a
    different database is the same move, so it gets the same guard: assert
    non-emptiness first, and fail rather than skip when it is gone.
    """

    def test_the_registry_is_not_empty(self, cur):
        cur.execute(f'SELECT count(*) AS n FROM {reg.TABLE}')
        assert cur.fetchone()['n'] > 0, (
            f'{reg.TABLE} has no rows, so every resolution test below would '
            f'skip rather than verify anything')

    def test_every_combination_the_read_tests_need_is_loaded(self, cur):
        missing = [c for c in RESOLVED_COMBINATIONS
                   if _loaded_run(cur, *c) is None]
        assert missing == [], (
            f'{missing} are not in {reg.TABLE}, so the tests that resolve them '
            f'would skip instead of running — check what fixture_db.seed() '
            f'registers')


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
        loaded = _a_loaded_run(writable, 'GEFS', 'precipitation')
        reg.record(writable, 'GEFS', 'precipitation', FUTURE_RUN,
                   n_members=30, hour_min=0, hour_max=240,
                   convention=reg.SCALED, export_divisor_h=6.0)

        # The new run says 6h...
        assert reg.resolve_divisor(writable, 'GEFS', 'precipitation', FUTURE_RUN) == 6.0
        # ...while the loaded run still says 3h, untouched.
        assert reg.resolve_divisor(writable, 'GEFS', 'precipitation', loaded) == 3.0

    def test_a_model_can_become_unscaled_in_a_later_run(self, writable):
        loaded = _a_loaded_run(writable, 'GEFS', 'precipitation')
        reg.record(writable, 'GEFS', 'precipitation', FUTURE_RUN,
                   n_members=30, hour_min=0, hour_max=240,
                   convention=reg.UNSCALED)
        assert reg.resolve_divisor(writable, 'GEFS', 'precipitation', FUTURE_RUN) is None
        assert reg.resolve_divisor(writable, 'GEFS', 'precipitation', loaded) == 3.0


class TestAnUndeclaredModelIsRecordedHonestly:
    def test_it_is_written_but_refuses_to_resolve(self, writable):
        """A new model can be loaded before anyone declares its convention —
        the registry should hold the row so the run appears in /api/runs, and
        still refuse to invent a divisor for it."""
        reg.record(writable, 'ECMWF_IFS', 'precipitation', FUTURE_RUN,
                   n_members=51, hour_min=0, hour_max=240)
        with pytest.raises(reg.UnknownConventionError, match='no declared'):
            reg.resolve_divisor(writable, 'ECMWF_IFS', 'precipitation', FUTURE_RUN)


# No run is named here any more. The constant that used to live at this point
# was `RUN = '2025-09-08 00:00:00'`, and naming a date is precisely what broke on
# 2026-09-30 (§24) — so every test below asks the registry which init holds the
# combination it needs. `TestTheRegistryHoldsWhatTheseTestsResolve` above is what
# keeps "ask the registry" from degrading into "ask, get nothing, skip".

def _resolve_each(cur, combinations):
    """`{model: divisor}` for the combinations the registry holds.

    A combination it does not hold is simply absent from the result, so the
    caller compares whole dicts and a missing one fails the comparison by name
    instead of quietly costing an assertion inside a loop.
    """
    resolved = {}
    for model, variable in combinations:
        run = _loaded_run(cur, model, variable)
        if run is not None:
            resolved[model] = reg.resolve_divisor(cur, model, variable, run)
    return resolved


class TestResolvingAgainstTheLoadedRun:
    def test_the_scaled_models_resolve_to_their_divisors(self, cur):
        """Each model against a run that actually holds it. AIFS and GEFS have
        different divisors, which is the per-run storage this module exists for
        seen from the read side — and in the real database, since §24, they no
        longer share an init at all."""
        assert _resolve_each(cur, (('AIFS', 'precipitation'),
                                   ('GEFS', 'precipitation'))) == {
            'AIFS': 6.0, 'GEFS': 3.0}

    def test_unscaled_resolves_to_None_which_is_an_answer(self, cur):
        """None here means "nothing to undo" and is a successful resolution.
        The failure mode being avoided is treating it as "unknown" and either
        raising on a perfectly well-described run, or defaulting."""
        run = _a_loaded_run(cur, 'UKMO', 'precipitation')
        assert reg.resolve_divisor(cur, 'UKMO', 'precipitation', run) is None

    def test_wind_resolves_too_rather_than_staying_undeclared(self, cur):
        """Wind declares `unscaled` rather than staying silent, so the read
        path does not trip over a variable that simply has no window. This is
        the drift `DECLARED`'s wind entries were added to stop: the real
        database's backfill named wind `unscaled` while a freshly built fixture
        left it NULL, so the same lookup answered differently against each."""
        run = _a_loaded_run(cur, 'AIFS', 'wind_u_10m')
        assert reg.resolve_divisor(cur, 'AIFS', 'wind_u_10m', run) is None

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
        run = _a_loaded_run(cur, 'AIFS', 'precipitation')
        with pytest.raises(reg.UnknownConventionError):
            reg.resolve_divisor(cur, 'ECMWF_IFS', 'precipitation', run)


# ── Invariants every registry must satisfy ────────────────────────────────────
# Written as functions so the same two queries can be run against the fixture
# database (below, in CI and locally) and against the development database (at
# the end of this file, locally only). Returning the offending rows rather than
# a boolean is what makes a failure say which row is wrong.

def _rows_with_no_convention(cur):
    cur.execute(f"""
        SELECT model_name, variable_name FROM {reg.TABLE}
        WHERE export_convention IS NULL
    """)
    return cur.fetchall()


def _rows_whose_two_columns_contradict(cur):
    cur.execute(f"""
        SELECT model_name, variable_name, export_convention, export_divisor_h
        FROM {reg.TABLE}
        WHERE (export_convention = %s AND export_divisor_h IS NULL)
           OR (export_convention = %s AND export_divisor_h IS NOT NULL)
    """, (reg.SCALED, reg.UNSCALED))
    return cur.fetchall()


class TestNoRowIsLeftUndeclared:
    def test_every_row_names_its_convention(self, cur):
        """An undeclared row is a landmine for the read path: NULL means nobody
        said, and `resolve_divisor` raises on it rather than defaulting. Nothing
        that writes this table should be able to produce one."""
        assert _rows_with_no_convention(cur) == []

    def test_the_named_convention_agrees_with_the_divisor(self, cur):
        """The two columns must not contradict each other: `scaled` with no
        divisor, or `unscaled` with one, is the incoherent state `record`
        refuses to write — and which a backfill or a hand edit could still
        create, since neither goes through `record`."""
        assert _rows_whose_two_columns_contradict(cur) == []

    def test_it_still_agrees_with_the_constant_scoring_uses(self, cur):
        """Scoring still reads `SCALED_EXPORT_DIVISOR_HOURS`. Until that moves
        onto the registry, the two must not drift — a disagreement here means
        one of them is silently wrong about the run it describes.

        The constant and `run_registry.DECLARED` are separate literals and
        neither is derived from the other, so this has teeth against the fixture
        as well: the fixture's rows come from `DECLARED`, and what is compared
        is `metrics`'s independent copy of the same numbers.
        """
        from metrics import SCALED_EXPORT_DIVISOR_HOURS
        combinations = tuple((m, 'precipitation') for m in SCALED_EXPORT_DIVISOR_HOURS)
        assert _resolve_each(cur, combinations) == dict(SCALED_EXPORT_DIVISOR_HOURS)


class TestTheRateConvention:
    """`rate` means each record was divided by its OWN window already.

    Added 2026-09-30 because the other two cannot describe that. `scaled` holds
    one divisor for the whole run and `_increment_divisor` computes
    `period / divisor` — right for a fixed factor, wrong when the factor *is*
    the period; `unscaled` would divide a rate by its window a second time.

    The case that forced it: GEFS 09-16 had been scaled through the current
    per-window `aifs react.py` while `record()` wrote `scaled, 3` from the
    module constant, so every 6-hour bucket was halved again — MAE read 0.1864
    where the correctly-labelled value is 0.2318.

    The stored data was afterwards re-scaled to the legacy flat /3 so the units
    stay uniform across runs, and the two representations give **identical**
    scores once each is labelled truthfully. So nothing in the database uses
    `rate` today. It stays because the repository's scaler is the per-window
    version: the next GEFS load through it produces per-window data, and without
    this the registry would mislabel it exactly as before.
    """

    class ExplodingCursor:
        def execute(self, *a, **k):
            raise AssertionError('should have been rejected before any SQL')

    def test_rate_is_a_known_convention(self):
        assert reg.RATE in reg.CONVENTIONS

    def test_the_two_modules_agree_on_the_sentinel(self):
        """`metrics` restates it rather than importing — the two modules do not
        depend on each other. This is what makes that safe."""
        import metrics
        assert reg.PER_WINDOW == metrics.PER_WINDOW

    def test_the_hyphenated_spelling_is_still_not_a_convention(self):
        """`per_window` is the sentinel `resolve_divisor` returns; `rate` is the
        convention. Neither is `per-window`, which an older test already uses as
        its example of an unknown one."""
        assert 'per-window' not in reg.CONVENTIONS
        assert reg.PER_WINDOW not in reg.CONVENTIONS

    def test_a_rate_run_needs_no_further_division(self):
        """At BOTH window lengths. The 6-hour case is the one that was wrong."""
        import metrics
        for period in (1, 3, 6):
            assert metrics._increment_divisor('GEFS', period,
                                              metrics.PER_WINDOW) == 1.0

    def test_the_legacy_flat_divisor_still_compensates(self):
        """Guards the guard: the stored data really is flat /3 and its 6-hour
        buckets really do need halving. Breaking this to fix `rate` would move
        every GEFS figure in the database."""
        import metrics
        assert metrics._increment_divisor('GEFS', 3, 3.0) == 1.0
        assert metrics._increment_divisor('GEFS', 6, 3.0) == 2.0

    def test_unscaled_still_divides_by_the_window(self):
        import metrics
        assert metrics._increment_divisor('UKMO', 1, None) == 1
        assert metrics._increment_divisor('UKMO', 6, None) == 6

    def test_rate_with_a_divisor_is_refused(self):
        """A single divisor cannot be true of a per-window export, so accepting
        one would let the contradiction straight back in."""
        with pytest.raises(ValueError, match='divided by its own window'):
            reg.record(self.ExplodingCursor(), 'NEW', 'precipitation',
                       '2025-09-09T00:00:00',
                       convention=reg.RATE, export_divisor_h=3.0)


# ── Against the development database — LOCAL ONLY, by design ──────────────────
#
# Everything above runs anywhere PostgreSQL does, CI included. These two do not,
# and that is the honest answer rather than a gap: they assert a property of
# rows that exist only in `weave_weather` on a development machine. CI has a
# PostgreSQL service container and no such database, so there is nothing for
# them to read — `.github/workflows/tests.yml` deliberately leaves `DB_NAME`
# unset and says so.
#
# They are kept because the invariants they check are about data, and the
# fixture cannot stand in for data: every fixture row is written by
# `run_registry.record()`, which refuses an incoherent one. The development
# database's rows were written by `migrate_init_time.py`'s backfill and by
# `backfill_conventions()`, neither of which goes through `record`, and can
# still be edited by hand. That is the state worth auditing, and the audit runs
# every time the suite is run where the database exists.

def _development_database_reason():
    """Why the development database cannot be audited here, or None."""
    if os.environ.get('WEAVE_SKIP_DB_TESTS'):
        return 'WEAVE_SKIP_DB_TESTS is set'
    try:
        import psycopg2
        psycopg2.connect(connect_timeout=3, **reg.DB_CONFIG).close()
    except Exception as exc:                                  # pragma: no cover
        return (f'{reg.DB_CONFIG["dbname"]!r} is not reachable '
                f'({type(exc).__name__}); this audit reads the development '
                f'database and is local-only by design — the registry itself '
                f'is tested against the fixture database above')
    return None


@pytest.fixture(scope='module')
def development_cur():
    reason = _development_database_reason()
    if reason:
        pytest.skip(reason)
    import psycopg2
    from psycopg2.extras import RealDictCursor
    conn = psycopg2.connect(**reg.DB_CONFIG)
    with conn.cursor(cursor_factory=RealDictCursor) as c:
        yield c
    conn.rollback()      # read-only: never leave anything behind
    conn.close()


class TestTheDevelopmentDatabaseIsCoherent:
    def test_the_backfill_left_no_row_undeclared(self, development_cur):
        assert _rows_with_no_convention(development_cur) == []

    def test_no_row_contradicts_itself(self, development_cur):
        assert _rows_whose_two_columns_contradict(development_cur) == []
