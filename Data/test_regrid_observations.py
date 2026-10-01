"""The observation regrid: the binning rule, and the artifact it exists to avoid.

`regridded_observation` is the truth field behind every scored endpoint, so the
rule that builds it decides what "observed" means everywhere at once. These tests
pin the rule, pin that it partitions rather than double-counts, and pin the
specific defect in the pre-existing table that motivated writing a new
implementation instead of reproducing the old one:

    round-half-to-even assigns both of a cell's boundary neighbours to the
    whole-degree cell, so adjacent cells get systematically different stencils.

The pure tests need no database. The ones that check the SQL run `ro.aggregate`
against the **fixture** database, over a native scene defined in this file.

**They used to assert against the live `regridded_observation`** — written
against a staging copy while the rebuild was being compared to the old field,
then pointed at the live table when that became the truth field on 2026-09-04.
That is why they skipped on every CI run this repository had: `ro.DB_CONFIG`
names `weave_weather`, which CI does not have (§26).

Moving them changed what they are, for the better. They check a *rule*, and they
had been using whatever was loaded as their supply of coordinates — so the
parity test's coverage of the offsets that matter was luck, and the stencil test
read a stored table rather than exercising the GROUP BY that builds it. They now
run the real SQL over coordinates chosen to put native points exactly on the
cell boundaries, which is the only place the artifact can appear.

Whether the *loaded* table is a correct partition of the *loaded* native data is
a separate question — about data rather than code — and it is still asked, by
`TestTheLoadedTruthFieldIsCoherent` at the end of this file. That class is
**local-only by design**: it reads `weave_weather`, which CI does not have, and
says so when it skips. `regrid_observations.py --compare` measures the same
thing in more detail, but only when someone runs it; the audit runs unprompted.
See §31.
"""
import math
import os

import pytest

import regrid_observations as ro
from regrid_members import TARGET_RESOLUTION


class TestTheBinningRule:
    """[c - res/2, c + res/2): a boundary coordinate goes to the upper cell."""

    def test_a_coordinate_at_a_cell_centre_maps_to_itself(self):
        for c in (24.0, 25.5, 35.0, 45.0, -85.0, -75.5, -65.0):
            assert ro.cell_centre(c) == c

    def test_a_boundary_coordinate_goes_up_not_to_the_even_cell(self):
        # The whole point. Under round-half-to-even, 24.25 -> 24.0 and
        # 25.25 -> 25.0, both landing on the whole degree; the half-degree cell
        # is starved. Half-open-upward sends each to the cell above it.
        assert ro.cell_centre(24.25) == 24.5
        assert ro.cell_centre(24.75) == 25.0
        assert ro.cell_centre(25.25) == 25.5
        assert ro.cell_centre(25.75) == 26.0

    def test_the_rule_is_not_round_half_to_even(self):
        # A regression guard with teeth: if anyone reaches for round() or
        # np.round() here, these are the coordinates that expose it.
        starved = [x for x in (24.25, 25.25, 26.25, 35.25)
                   if ro.cell_centre(x) == round(x / TARGET_RESOLUTION) * TARGET_RESOLUTION]
        assert starved == [], f"binning agrees with banker's rounding at {starved}"

    def test_negative_longitudes_use_the_same_upward_rule(self):
        # Longitudes are all negative here, and floor() on negatives is where a
        # hand-rolled rule usually breaks.
        assert ro.cell_centre(-85.0) == -85.0
        assert ro.cell_centre(-84.75) == -84.5
        assert ro.cell_centre(-84.25) == -84.0
        assert ro.cell_centre(-84.5) == -84.5

    def test_every_point_in_a_box_maps_to_that_box(self):
        half = TARGET_RESOLUTION / 2
        for c in (24.0, 25.5, 35.0, -75.5):
            for frac in (-0.5, -0.25, 0.0, 0.25, 0.49):
                x = c + frac * TARGET_RESOLUTION
                if x < c - half:          # below the box, belongs to the one under
                    continue
                assert ro.cell_centre(x) == c, (c, x)

    def test_the_boxes_tile_without_gap_or_overlap(self):
        # Walk a fine sweep and assert the cell index only ever steps by one.
        centres = [ro.cell_centre(24.0 + i * 0.01) for i in range(2200)]
        steps = {round(b - a, 10) for a, b in zip(centres, centres[1:])}
        assert steps <= {0.0, TARGET_RESOLUTION}, steps


class TestConfiguration:
    def test_every_source_names_a_variable_and_a_column(self):
        for source, (variable, column) in ro.SOURCES.items():
            assert variable and column, source

    def test_the_default_target_is_not_the_live_table(self):
        # A first run must not be able to destroy the field every published
        # number was computed against.
        assert ro.DEFAULT_TABLE != ro.LIVE_TABLE

    def test_the_resolution_is_the_one_the_forecast_grid_uses(self):
        # Truth cells and forecast cells are joined on latitude/longitude, so a
        # divergence here would silently match zero rows.
        assert ro.TARGET_RESOLUTION == TARGET_RESOLUTION


class TestGuards:
    def test_an_unknown_source_fails_rather_than_rebuilding_nothing(self, monkeypatch):
        monkeypatch.setattr('sys.argv', ['regrid_observations.py', '--sources', 'NOPE'])
        with pytest.raises(SystemExit) as e:
            ro.main()
        assert 'NOPE' in str(e.value)

    def test_appending_to_the_live_table_is_refused(self, monkeypatch):
        # Without --truncate this would double every cell and leave the
        # endpoints averaging the truth field with itself.
        monkeypatch.setattr('sys.argv',
                            ['regrid_observations.py', '--table', ro.LIVE_TABLE])
        with pytest.raises(SystemExit) as e:
            ro.main()
        assert ro.LIVE_TABLE in str(e.value)

    @pytest.mark.parametrize('argv', [
        ['regrid_observations.py', '--sources', 'NOPE'],
        ['regrid_observations.py', '--table', ro.LIVE_TABLE],
    ])
    def test_the_guards_reject_before_touching_the_database(self, monkeypatch, argv):
        # The regression this pins: the live-table guard used to sit *below*
        # psycopg2.connect, so on a host where the database is unreachable a bad
        # argument surfaced as an OperationalError instead of the refusal. CI
        # found it, because the CI database is deliberately not weave_weather.
        # Point the config at a port nothing listens on: a guard that still
        # rejects cleanly here cannot be doing I/O first.
        monkeypatch.setattr(ro, 'DB_CONFIG',
                            {**ro.DB_CONFIG, 'host': '127.0.0.1', 'port': 1,
                             'dbname': 'definitely_not_a_database'})
        monkeypatch.setattr('sys.argv', argv)
        with pytest.raises(SystemExit):
            ro.main()


# ── Against real SQL, on a scene designed to show the artifact ────────────────
#
# These four used to resolve through `ro.DB_CONFIG`, which names `weave_weather`
# unless `DB_NAME` says otherwise, so they skipped in CI on every run this
# repository had — the same gap as `test_run_registry.py` (§26).
#
# **The fix was not to set DB_NAME.** The guard tests above
# (`test_the_guards_reject_before_touching_the_database`) depend on `DB_CONFIG`
# naming nothing reachable: that is how the live-table guard sitting *below*
# `psycopg2.connect` was caught in the first place. Pointing DB_NAME at a real
# database would hollow those out — still passing, no longer testing that the
# refusal precedes any I/O.
#
# Nor was it enough to point these at the fixture database as it stands. What
# they check is a *rule*, and they were using whatever happened to be loaded as
# their supply of coordinates:
#
#   - the SQL/Python parity test read `observation_data`'s distinct coordinates,
#     so its coverage of the dangerous offsets was luck rather than design;
#   - the partition and stencil tests read the stored `regridded_observation`,
#     which the fixture seeds synthetically rather than deriving, so against the
#     fixture the first would have failed and the second would have passed on a
#     single-point-per-cell field that cannot show a checkerboard at all.
#
# So they now run `ro.aggregate()` — the real GROUP BY, in real SQL — over a
# native scene built here for the purpose: a 20x20 IMERG-like 0.1 degree grid
# laid out to fill exactly 16 target cells, 25 native points each, spanning both
# whole-degree and half-degree centres in both axes. The scene is inserted into
# the fixture database inside a transaction that is rolled back, so nothing is
# left behind for the endpoint tests that share it.
#
# `test_the_scene_can_actually_show_the_artifact` is the guard on all of this:
# it checks in pure Python that round-half-to-even produces non-uniform stencils
# on these very coordinates. Without it, "every cell has 25" might be true of
# any rule, and the checkerboard test would be decoration.
#
# What this section does NOT cover is whether the *loaded*
# `regridded_observation` is a correct partition of the *loaded*
# `observation_data` — a question about data rather than code. That is audited
# separately by `TestTheLoadedTruthFieldIsCoherent` at the end of this file,
# which is local-only because only a development machine has the data to read.

# IMERG's native lattice is 0.1 degrees with centres at odd multiples of 0.05,
# so the .25 and .75 boundaries ARE native coordinates — which is exactly why
# the rounding rule matters. Laid out to fill whole target cells so that every
# cell is interior and a correct rule gives a uniform stencil.
NATIVE_STEP   = 0.1
SCENE_LATS    = [round(34.75 + i * NATIVE_STEP, 2) for i in range(20)]
SCENE_LONS    = [round(-76.25 + i * NATIVE_STEP, 2) for i in range(20)]
SCENE_SOURCE  = 'WEAVE_TEST_IMERG'     # never a real source; see ro.SOURCES
SCENE_TIMES   = 2
EXPECTED_CELLS   = 16                  # 4 target cells per axis
EXPECTED_STENCIL = 25                  # 5 native points per axis, per cell
SCENE_POINTS  = len(SCENE_LATS) * len(SCENE_LONS)


@pytest.fixture(scope='module')
def scene_cur(fixture_db):
    """A cursor on the fixture database holding the native scene, uncommitted.

    Inserted and rolled back rather than seeded into `fixture_db.py`: the scene
    exists to exercise a binning rule at a resolution the rest of the fixture
    has no use for, and `fixture_db`'s own `observation_data` is documented as
    the shape the endpoints once read. Keeping it local means neither has to
    bend around the other.

    Read-only afterwards from the suite's point of view, and never committed, so
    the modules that share this database cannot see it.
    """
    import psycopg2
    from psycopg2.extras import execute_values
    from datetime import datetime, timedelta

    conn = psycopg2.connect(**fixture_db.db_config())
    rows = []
    for t in range(SCENE_TIMES):
        obs_time = datetime(2025, 9, 8, 0, 0, 0) + timedelta(hours=t)
        for lat in SCENE_LATS:
            for lon in SCENE_LONS:
                # A value that varies by cell, so an averaging mistake is not
                # hidden by a constant field.
                rows.append((obs_time, lat, lon, abs(lat) + abs(lon),
                             SCENE_SOURCE))
    with conn.cursor() as c:
        execute_values(c, """
            INSERT INTO observation_data
                (obs_time, latitude, longitude, precipitation, source) VALUES %s
        """, rows)
        yield c
    conn.rollback()
    conn.close()


class TestTheSceneIsFitForPurpose:
    """Asserted before anything reads through it.

    Two separate ways these tests could pass while checking nothing: the scene
    could be empty, or it could be uniform under *every* rounding rule. Both are
    ruled out here rather than assumed.
    """

    def test_the_scene_is_in_the_database(self, scene_cur):
        scene_cur.execute("SELECT count(*) FROM observation_data WHERE source = %s",
                          (SCENE_SOURCE,))
        assert scene_cur.fetchone()[0] == SCENE_POINTS * SCENE_TIMES

    def test_the_scene_can_actually_show_the_artifact(self):
        """Guard the guard, in pure Python: round-half-to-even must produce a
        *non*-uniform stencil on these coordinates.

        If it did not, `test_interior_stencils_are_uniform_regardless_of_parity`
        would be satisfied by any rule at all and would be pinning nothing.
        Measured: the banker's rule gives 16, 24 and 36 where the correct one
        gives a uniform 25.
        """
        import collections
        banker = lambda v: 0.5 * round(v / 0.5)
        counts = collections.Counter(
            (banker(la), banker(lo)) for la in SCENE_LATS for lo in SCENE_LONS)
        assert len(set(counts.values())) > 1, (
            'the scene is uniform under round-half-to-even too, so it cannot '
            'detect the checkerboard the correct rule exists to avoid')

    def test_the_boundary_coordinates_really_are_in_the_scene(self):
        # The artifact only appears where a native point sits exactly on a cell
        # boundary. If the lattice ever moves off the .25/.75 offsets, the
        # checkerboard test stops exercising the case it is named for.
        half = TARGET_RESOLUTION / 2
        on_boundary = [v for v in SCENE_LATS
                       if math.isclose((v + half) % TARGET_RESOLUTION, 0.0,
                                       abs_tol=1e-9)]
        assert on_boundary, 'no latitude sits on a cell boundary'


class TestTheSqlMatchesThePythonRule:
    def test_they_agree_on_every_scene_coordinate(self, scene_cur):
        """`_cell_sql` is the translation of `cell_centre` into SQL, and the two
        drifting apart would move the truth field without moving the rule that
        documents it."""
        for column in ('latitude', 'longitude'):
            scene_cur.execute(
                f"SELECT {column}, {ro._cell_sql(column)} "
                f"FROM (SELECT DISTINCT {column} FROM observation_data "
                f"       WHERE source = %s) s ORDER BY 1", (SCENE_SOURCE,))
            checked = scene_cur.fetchall()
            assert len(checked) == len(SCENE_LATS), (column, len(checked))
            for raw, sql_cell in checked:
                assert float(sql_cell) == ro.cell_centre(float(raw)), (column, raw)

    def test_they_agree_on_the_offsets_the_rule_turns_on(self, scene_cur):
        """The boundaries specifically, including negative longitudes, where
        `floor` and `round` disagree about which way to go."""
        probes = [24.25, 24.75, 25.25, 35.25, 35.75, 36.25,
                  -85.25, -75.75, -75.25, -74.75, -65.25]
        scene_cur.execute(
            f"SELECT v, {ro._cell_sql('v')} FROM unnest(%s::float8[]) AS v",
            (probes,))
        rows = scene_cur.fetchall()
        assert len(rows) == len(probes)
        for raw, sql_cell in rows:
            assert float(sql_cell) == ro.cell_centre(float(raw)), raw


class TestThePartition:
    def test_no_observation_is_counted_twice_or_dropped(self, scene_cur):
        # The defining property of a partition, stated as arithmetic: the
        # stencil counts must sum to the number of native observations.
        #
        # Note what this does NOT catch on its own: the banker's rule preserves
        # the total too (400 points either way). It moves points between cells
        # rather than losing them, which is why the uniformity test below is a
        # separate assertion and not a corollary of this one.
        agg = ro.aggregate(scene_cur, SCENE_SOURCE, 'precipitation')
        assert agg, 'the aggregate returned nothing'
        pooled = sum(n for _, _, _, _, n in agg)
        scene_cur.execute("""SELECT count(precipitation) FROM observation_data
                             WHERE source = %s AND precipitation IS NOT NULL""",
                          (SCENE_SOURCE,))
        native = scene_cur.fetchone()[0]
        assert pooled == native == SCENE_POINTS * SCENE_TIMES

    def test_interior_stencils_are_uniform_regardless_of_parity(self, scene_cur):
        # The checkerboard test. Under round-half-to-even this returns several
        # distinct counts; a correct partition returns exactly one.
        agg = ro.aggregate(scene_cur, SCENE_SOURCE, 'precipitation')
        stencils = {int(n) for _, _, _, _, n in agg}
        assert stencils == {EXPECTED_STENCIL}, (
            f'interior has stencil sizes {sorted(stencils)} rather than a '
            f'uniform {EXPECTED_STENCIL} — the parity artifact is back')

    def test_both_parities_are_present_and_treated_alike(self, scene_cur):
        # Uniformity only means anything if whole-degree and half-degree cells
        # are both in the result. This is what the artifact discriminated on.
        agg = ro.aggregate(scene_cur, SCENE_SOURCE, 'precipitation')
        cells = {(round(float(la), 4), round(float(lo), 4))
                 for _, la, lo, _, _ in agg}
        assert len(cells) == EXPECTED_CELLS, sorted(cells)
        whole = {c for c in cells if float(c[0]).is_integer()}
        half  = cells - whole
        assert whole and half, f'only one parity present: {sorted(cells)}'

    def test_the_value_is_the_unweighted_mean_of_the_box(self, scene_cur):
        # `source_points` records the count; `value` must be the plain mean of
        # those points, not a weighted or nearest-point value.
        agg = ro.aggregate(scene_cur, SCENE_SOURCE, 'precipitation')
        by_cell = {}
        for la in SCENE_LATS:
            for lo in SCENE_LONS:
                key = (ro.cell_centre(la), ro.cell_centre(lo))
                by_cell.setdefault(key, []).append(abs(la) + abs(lo))
        for _, la, lo, value, _ in agg:
            expected = by_cell[(round(float(la), 4), round(float(lo), 4))]
            assert float(value) == pytest.approx(sum(expected) / len(expected))


class TestCoverage:
    def test_truth_covers_every_forecast_cell(self, fixture_db):
        """A forecast cell with no truth cell scores nothing, silently, so the
        observation grid must be a superset of the forecast grid.

        Checked against the fixture's own two grids rather than the loaded
        database's. That makes it a test of the invariant the fixture is built
        to satisfy — which is worth having, because `fixture_db.py` sets the
        forecast and observation grids in different functions and nothing else
        would notice them drifting apart.
        """
        import psycopg2
        conn = psycopg2.connect(**fixture_db.db_config())
        conn.autocommit = True
        try:
            with conn.cursor() as c:
                c.execute("SELECT DISTINCT latitude, longitude "
                          "FROM regridded_forecast_ens")
                forecast = {(round(float(a), 4), round(float(b), 4))
                            for a, b in c.fetchall()}
                c.execute("SELECT DISTINCT latitude, longitude "
                          "FROM regridded_observation")
                truth = {(round(float(a), 4), round(float(b), 4))
                         for a, b in c.fetchall()}
        finally:
            conn.close()
        assert forecast, 'no forecast cells — the comparison would be vacuous'
        assert truth, 'no truth cells — the comparison would be vacuous'
        assert not (forecast - truth), sorted(forecast - truth)[:10]


# ── Against the live database — LOCAL ONLY, by design ─────────────────────────
#
# Everything above runs anywhere PostgreSQL does, CI included, and checks the
# *rule*. These check the *data*: that the `regridded_observation` the app
# actually scores against really is a correct partition of the
# `observation_data` it was built from, and that the checkerboard is not in it.
#
# The fixture cannot stand in for that, and the distinction is the same one
# `test_run_registry.py` draws. The fixture's truth field is seeded by
# `fixture_db.py` to a known answer; the live one was produced by a rebuild of a
# table originally built off-repo, and a rebuild can be half-finished, run for
# one source and not the other, or appended to rather than replaced. None of
# those are reachable from the code under test, which is exactly why they are
# worth looking at.
#
# `regrid_observations.py --compare` measures a rebuild against the stored table
# in far more detail than this, and remains the tool for investigating a
# difference. What it does not do is run unprompted. These do, every time the
# suite runs where the database exists, which is the point: the question "is the
# truth field still coherent" should not depend on someone thinking to ask it.
#
# They skip where there is no `weave_weather` — CI, and any fresh checkout — and
# say so. That is a deliberate exception to "no skips in CI", not an oversight:
# see NEXT_STEPS.md §31.

def _live_database_reason():
    """Why the live truth field cannot be audited here, or None."""
    if os.environ.get('WEAVE_SKIP_DB_TESTS'):
        return 'WEAVE_SKIP_DB_TESTS is set'
    try:
        import psycopg2
        psycopg2.connect(connect_timeout=3, **ro.DB_CONFIG).close()
    except Exception as exc:                                  # pragma: no cover
        return (f'{ro.DB_CONFIG["dbname"]!r} is not reachable '
                f'({type(exc).__name__}); this audits the loaded truth field '
                f'and is local-only by design — the binning rule itself is '
                f'tested against the fixture database above')
    return None


@pytest.fixture(scope='module')
def live_cur():
    """A read-only cursor on the live database.

    **autocommit**, for the reason §26 records: a module-scoped connection that
    holds a transaction open keeps an ACCESS SHARE lock on everything it has
    read until teardown, and anything in the same process wanting an ACCESS
    EXCLUSIVE lock then waits on a transaction only it can end. Nothing here
    writes, so there is no transaction worth keeping.
    """
    reason = _live_database_reason()
    if reason:
        pytest.skip(reason)
    import psycopg2
    conn = psycopg2.connect(**ro.DB_CONFIG)
    conn.autocommit = True
    with conn.cursor() as c:
        yield c
    conn.close()


class TestTheLoadedTruthFieldIsCoherent:
    """The audits that were removed when these tests moved to the fixture.

    Restored deliberately rather than left to `--compare`: an invariant nobody
    is prompted to check is one that is discovered broken late.
    """

    def test_both_tables_are_populated(self, live_cur):
        """The guard, asserted before the audits read through it.

        The versions of these tests that ran before 2026-10-01 called
        `pytest.skip('regridded_observation is not populated')` here. That is
        the hollowing-out this repository has now hit three times (§26, §28,
        §31): a test that has already decided it can run should not then decide
        it has nothing to say. An empty truth field means every scored endpoint
        returns nothing, so it is a failure, not an absence.
        """
        for table in ('observation_data', 'regridded_observation',
                      'regridded_forecast_ens'):
            live_cur.execute(f'SELECT EXISTS (SELECT 1 FROM {table})')
            assert live_cur.fetchone()[0], f'{table} is empty'

    def test_the_sql_rule_agrees_with_the_python_one_on_real_coordinates(self, live_cur):
        """The designed scene above covers the offsets that matter by
        construction; this covers the ones the data actually has. A native
        coordinate nobody anticipated is the case the scene cannot reach."""
        for column in ('latitude', 'longitude'):
            live_cur.execute(
                f"SELECT {column}, {ro._cell_sql(column)} "
                f"FROM (SELECT DISTINCT {column} FROM observation_data) s")
            rows = live_cur.fetchall()
            assert rows, f'no distinct {column} values to check'
            for raw, sql_cell in rows:
                assert float(sql_cell) == ro.cell_centre(float(raw)), (column, raw)

    def test_no_observation_is_counted_twice_or_dropped(self, live_cur):
        """The partition property of the stored table, as arithmetic: the
        stencil counts must sum to the number of native observations.

        Verified to bite, against the live table inside a rolled-back
        transaction: deleting 1% of the cells takes the pooled count from
        2,991,816 to 2,961,897 and this fails, while the uniformity test below
        still passes. The two are complementary — a partial rebuild is visible
        only here, a wrong stencil rule is visible in both.

        Note what cannot happen, and therefore is not what this guards:
        `uq_regridded_observation_natural_key` makes a straight re-append
        impossible, so the realistic failures are a rebuild that stopped early
        or one that wrote different counts.
        """
        for source, (variable, column) in ro.SOURCES.items():
            live_cur.execute(f"""SELECT count({column}) FROM observation_data
                                 WHERE source=%s AND {column} IS NOT NULL""",
                             (source,))
            native = live_cur.fetchone()[0]
            live_cur.execute("""SELECT coalesce(sum(source_points), 0)
                                FROM regridded_observation
                                WHERE source=%s AND variable_name=%s""",
                             (source, variable))
            pooled = live_cur.fetchone()[0]
            assert native > 0, f'{source} has no native observations'
            assert pooled == native, (
                f'{source}: {pooled:,} pooled against {native:,} native — the '
                f'stored field is not a partition of the data it came from')

    def test_interior_stencils_are_uniform_regardless_of_parity(self, live_cur):
        """The checkerboard, in the field the app actually scores against.

        The pre-existing table failed this: whole-degree cells were built from a
        6x6 native stencil and half-degree cells from 4x4. The rebuild that
        replaced it on 2026-09-04 is what makes this pass, so this is the test
        that notices if that is ever undone.
        """
        live_cur.execute("""
            SELECT source, count(DISTINCT source_points)
            FROM regridded_observation
            WHERE latitude BETWEEN 26 AND 44 AND longitude BETWEEN -84 AND -66
            GROUP BY 1""")
        rows = live_cur.fetchall()
        assert rows, 'no interior cells — the check would be vacuous'
        for source, n_distinct in rows:
            assert n_distinct == 1, (
                f'{source} interior has {n_distinct} different stencil sizes — '
                f'the parity artifact is back')

    def test_truth_covers_every_forecast_cell(self, live_cur):
        """A forecast cell with no truth cell scores nothing, silently, so the
        observation grid must be a superset of the forecast grid.

        The fixture version above pins the same invariant for the fixture's own
        grids. This one is about the loaded run, where the two grids come from
        different ingests entirely and nothing forces them to agree.
        """
        live_cur.execute("SELECT DISTINCT latitude, longitude "
                         "FROM regridded_forecast_ens")
        forecast = {(round(float(a), 4), round(float(b), 4))
                    for a, b in live_cur.fetchall()}
        live_cur.execute("SELECT DISTINCT latitude, longitude "
                         "FROM regridded_observation")
        truth = {(round(float(a), 4), round(float(b), 4))
                 for a, b in live_cur.fetchall()}
        assert forecast and truth, 'a grid is empty — the comparison is vacuous'
        assert not (forecast - truth), sorted(forecast - truth)[:10]
