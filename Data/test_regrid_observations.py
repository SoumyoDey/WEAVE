"""The observation regrid: the binning rule, and the artifact it exists to avoid.

`regridded_observation` is the truth field behind every scored endpoint, so the
rule that builds it decides what "observed" means everywhere at once. These tests
pin the rule, pin that it partitions rather than double-counts, and pin the
specific defect in the pre-existing table that motivated writing a new
implementation instead of reproducing the old one:

    round-half-to-even assigns both of a cell's boundary neighbours to the
    whole-degree cell, so adjacent cells get systematically different stencils.

The pure tests need no database. The ones that check the SQL against real
coordinates skip themselves without PostgreSQL, like `test_db_endpoints.py`.
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


# ── Against the real database ─────────────────────────────────────────────────

def _skip_reason():
    if os.environ.get('WEAVE_SKIP_DB_TESTS'):
        return 'WEAVE_SKIP_DB_TESTS is set'
    try:
        import psycopg2
        psycopg2.connect(**ro.DB_CONFIG).close()
    except Exception as exc:                                  # pragma: no cover
        return f'no database: {type(exc).__name__}'
    return None


@pytest.fixture(scope='module')
def cur():
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)
    import psycopg2
    conn = psycopg2.connect(**ro.DB_CONFIG)
    with conn.cursor() as c:
        yield c
    conn.close()


class TestTheSqlMatchesThePythonRule:
    def test_they_agree_on_every_native_coordinate(self, cur):
        for column in ('latitude', 'longitude'):
            cur.execute(f"SELECT DISTINCT {column} FROM observation_data ORDER BY 1")
            values = [float(r[0]) for r in cur.fetchall()]
            assert values, f'no {column} values to check'
            cur.execute(
                f"SELECT {column}, {ro._cell_sql(column)} "
                f"FROM (SELECT DISTINCT {column} FROM observation_data) s ORDER BY 1")
            for raw, sql_cell in cur.fetchall():
                assert float(sql_cell) == ro.cell_centre(float(raw)), (column, raw)


class TestThePartition:
    def test_no_observation_is_counted_twice_or_dropped(self, cur):
        # The defining property of a partition, stated as arithmetic: the
        # stencil counts must sum to the number of native observations.
        for source, (variable, column) in ro.SOURCES.items():
            cur.execute(f"""SELECT count({column}) FROM observation_data
                            WHERE source=%s AND {column} IS NOT NULL""", (source,))
            native = cur.fetchone()[0]
            cur.execute("""SELECT coalesce(sum(source_points), 0)
                           FROM regridded_observation_rebuilt
                           WHERE source=%s AND variable_name=%s""", (source, variable))
            pooled = cur.fetchone()[0]
            if pooled == 0:
                pytest.skip('regridded_observation_rebuilt is not populated')
            assert pooled == native, source

    def test_interior_stencils_are_uniform_regardless_of_parity(self, cur):
        # The checkerboard test. In the stored table this returns several
        # distinct counts per source; a correct partition returns exactly one.
        cur.execute("""
            SELECT source, count(DISTINCT source_points)
            FROM regridded_observation_rebuilt
            WHERE latitude BETWEEN 26 AND 44 AND longitude BETWEEN -84 AND -66
            GROUP BY 1""")
        rows = cur.fetchall()
        if not rows:
            pytest.skip('regridded_observation_rebuilt is not populated')
        for source, n_distinct in rows:
            assert n_distinct == 1, (
                f'{source} interior has {n_distinct} different stencil sizes — '
                f'the parity artifact is back')


class TestCoverage:
    def test_truth_covers_every_forecast_cell(self, cur):
        # A forecast cell with no truth cell scores nothing, silently. The
        # observation grid must be a superset of the forecast grid.
        cur.execute("""SELECT DISTINCT latitude, longitude
                       FROM regridded_forecast_ens""")
        forecast = {(round(float(a), 4), round(float(b), 4)) for a, b in cur.fetchall()}
        cur.execute("""SELECT DISTINCT latitude, longitude
                       FROM regridded_observation_rebuilt""")
        truth = {(round(float(a), 4), round(float(b), 4)) for a, b in cur.fetchall()}
        if not truth or not forecast:
            pytest.skip('tables are not populated')
        assert not (forecast - truth), sorted(forecast - truth)[:10]
