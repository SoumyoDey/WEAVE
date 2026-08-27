#!/usr/bin/env python
"""Box-average native point observations onto the common 0.5 degree grid.

Why this exists
---------------
`regridded_observation` is the truth field behind every scored endpoint, and
until now **no script in this repository could produce it**. It was built
off-repo, which meant a fresh deployment following DEPLOY.md got forecasts and no
verification: `flask_api.py` reads the table, `fixture_db.py` seeds a synthetic
version for tests, and nothing else touched it. That is the gap this closes.

The input is `observation_data`, the sparse-but-actually-dense native point
observations that the same off-repo ingest loaded. That table is raw ingested
data no script here can regenerate either — but it *is* in the database, and the
regridded field is a pure function of it, so this script needs no original
IMERG or ERA5 files.

The binning rule, and why this one
----------------------------------
Every native observation is assigned to exactly one target cell:

    centre = 0.5 * floor((coordinate + 0.25) / 0.5)

which is the half-open box **[centre - 0.25, centre + 0.25)**. A point exactly on
a boundary goes to the upper cell. That makes the target cells a true partition
of the plane: no observation is counted twice, no observation is dropped, and
`sum(source_points)` over a time slice equals the number of native observations
in it. `value` is the unweighted mean of the members of the box, and
`source_points` records how many there were, so an edge cell built from three
observations is distinguishable from an interior one built from twenty-five.

**This is not a bit-for-bit reproduction of the existing table**, and that is
deliberate. The stored `source_points` shows whole-degree cells built from a
6x6 native stencil and half-degree cells from 4x4, on a grid where the
coordinates are exact and both should give the same count — an asymmetry with no
defensible reason that I could find, and reproducing it would have meant encoding
an artifact rather than a rule. `--compare` measures the difference against the
stored table so the size of that decision is visible rather than assumed.

Consequences of the partition that are worth knowing:

- **Interior counts are what the resolution ratio predicts**: 5x5 = 25 for IMERG
  at 0.1 degrees, 2x2 = 4 for ERA5 at 0.25. Edge cells get fewer, because the
  native record stops.
- **The target extent falls out of the rule** rather than being declared. IMERG's
  native hull (24.05..45.95, -85.95..-64.05) yields 45x45 spanning 24..46, and
  ERA5's (25..45, -85..-65) yields 41x41 spanning 25..45 — which is exactly the
  cell set the existing table holds, so joins against
  `regridded_forecast_ens` are unaffected either way.
- **Observation coverage is a superset of the forecast grid** for IMERG and
  identical for ERA5. `test_regrid_observations.py` asserts the superset property,
  since a scored cell with no truth cell silently returns nothing.

Wind
----
`observation_data.wind_speed` is exactly sqrt(u^2 + v^2) at every point (verified:
max absolute difference 0.0), so this averages the stored scalar speed directly.
That is the mean speed over the box, which is **not** the speed of the mean
vector — the two differ whenever direction varies within the box, and the mean of
speeds is the right one to verify a forecast speed against. The forecast side
reaches the same quantity from the other direction: `regrid_members.py` computes
sqrt(u^2 + v^2) per member and then averages.

Usage
-----
    python regrid_observations.py --compare              # measure, write nothing
    python regrid_observations.py                        # -> _rebuilt table
    python regrid_observations.py --table regridded_observation --truncate

The default target is `regridded_observation_rebuilt`, not the live table, so a
first run cannot destroy the truth field that every published number was computed
against. Writing to the real table takes an explicit `--table`.
"""
import argparse
import io
import math
import os
import sys

import psycopg2
from dotenv import load_dotenv

# One definition of the lattice spacing, shared with the forecast regrid so the
# two cannot drift apart. Only the spacing is shared: the forecast grid's extent
# is a stated constant, while the observation extent is whatever the native
# record covers.
from regrid_members import TARGET_RESOLUTION

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

DB_CONFIG = {
    'dbname':   os.environ.get('DB_NAME',     'weave_weather'),
    'user':     os.environ.get('DB_USER',     'k.aggarwal'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'host':     os.environ.get('DB_HOST',     'localhost'),
    'port':     int(os.environ.get('DB_PORT', 5432)),
}

# source -> (variable_name written, column read from observation_data).
# Adding a source is a one-line change here; the column is named explicitly
# because `observation_data` is one wide table rather than one per variable.
SOURCES = {
    'GPM_IMERG_V07B': ('precipitation', 'precipitation'),
    'ERA5_WIND':      ('wind_speed',    'wind_speed'),
}

DEFAULT_TABLE = 'regridded_observation_rebuilt'
LIVE_TABLE    = 'regridded_observation'

SCHEMA_TEMPLATE = """
CREATE TABLE IF NOT EXISTS {table} (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    variable_name TEXT NOT NULL,
    obs_time TIMESTAMP NOT NULL,
    latitude FLOAT NOT NULL,
    longitude FLOAT NOT NULL,
    value FLOAT,
    source_points INTEGER,
    resolution TEXT
);
CREATE INDEX IF NOT EXISTS {table}_lat_lon ON {table}(latitude, longitude);
CREATE INDEX IF NOT EXISTS {table}_src_var_time
    ON {table}(source, variable_name, obs_time, latitude, longitude);
"""

def cell_centre(coordinate):
    """The centre of the half-open box [c - res/2, c + res/2) holding `coordinate`.

    The canonical statement of the binning rule; `_cell_sql` is its translation
    into SQL and `test_regrid_observations.py` asserts the two agree on every
    native coordinate in the database.

    **Never use `round()` or `np.round()` here.** That is precisely the bug in the
    existing `regridded_observation`: both round half to *even*, and on this
    lattice a coordinate at a .25 or .75 offset divides by 0.5 to an exact .5,
    so banker's rounding sends both of a cell's boundary neighbours to the
    whole-degree (even) cell. The result is a checkerboard — interior ERA5 cells
    at whole degrees averaged 9 native points while their half-degree neighbours
    got exactly 1. `floor(x + half)` rounds half *up*, consistently, so every
    cell gets the same stencil.
    """
    half = TARGET_RESOLUTION / 2
    return TARGET_RESOLUTION * math.floor((coordinate + half) / TARGET_RESOLUTION)


# The SQL translation of `cell_centre`, applied to a column. Done in SQL because
# the aggregation is a GROUP BY over 2.5M rows and the database is far better at
# that than a round trip.
#
# Float safety: res and res/2 are binary-exact (0.5, 0.25), and every boundary
# this can land on is at a .25 or .75 offset, which is also exact. Native
# coordinates at other offsets (IMERG's .05 steps are not exact) sit strictly
# inside a box, where a last-bit error cannot change the answer.
def _cell_sql(col):
    half = TARGET_RESOLUTION / 2
    return f"{TARGET_RESOLUTION} * floor(({col} + {half}) / {TARGET_RESOLUTION})"


def aggregate(cursor, source, column):
    """[(obs_time, lat, lon, mean, n)] for one source, box-averaged."""
    cursor.execute(f"""
        SELECT obs_time,
               {_cell_sql('latitude')}  AS lat,
               {_cell_sql('longitude')} AS lon,
               AVG({column})            AS value,
               COUNT({column})          AS source_points
        FROM observation_data
        WHERE source = %s AND {column} IS NOT NULL
        GROUP BY obs_time, lat, lon
        ORDER BY obs_time, lat, lon
    """, (source,))
    return cursor.fetchall()


def copy_rows(conn, table, columns, rows):
    """Bulk-load via COPY, matching regrid_members.py's loader."""
    if not rows:
        return 0
    buf = io.StringIO()
    for row in rows:
        buf.write('\t'.join('' if v is None else str(v) for v in row) + '\n')
    buf.seek(0)
    with conn.cursor() as cur:
        cur.copy_from(buf, table, columns=columns, null='')
    return len(rows)


def rebuild(conn, source, table, truncate):
    variable, column = SOURCES[source]
    with conn.cursor() as cur:
        if truncate:
            cur.execute(f"DELETE FROM {table} WHERE source = %s AND variable_name = %s",
                        (source, variable))
            conn.commit()
        agg = aggregate(cur, source, column)

    resolution = f'{TARGET_RESOLUTION:g}deg'
    rows = [(source, variable, t, lat, lon, value, n, resolution)
            for t, lat, lon, value, n in agg]
    written = copy_rows(conn, table,
                        ('source', 'variable_name', 'obs_time', 'latitude',
                         'longitude', 'value', 'source_points', 'resolution'),
                        rows)
    conn.commit()

    times = len({r[2] for r in rows})
    cells = len({(r[3], r[4]) for r in rows})
    stencils = sorted({r[6] for r in rows})
    print(f"  {source} -> {variable}: {written:,} rows, {times} times, "
          f"{cells} cells, source_points {stencils[0]}..{stencils[-1]}")
    return written


def compare(cursor, source):
    """Measure the rebuilt field against the stored one, without writing."""
    variable, column = SOURCES[source]
    print(f"\n  {source} / {variable}")

    rebuilt = {(t, round(float(lat), 4), round(float(lon), 4)): (float(v), int(n))
               for t, lat, lon, v, n in aggregate(cursor, source, column)}

    cursor.execute("""
        SELECT obs_time, latitude, longitude, value, source_points
        FROM regridded_observation WHERE source = %s AND variable_name = %s
    """, (source, variable))
    stored = {(t, round(float(lat), 4), round(float(lon), 4)): (float(v), int(n))
              for t, lat, lon, v, n in cursor.fetchall()}

    only_rebuilt = set(rebuilt) - set(stored)
    only_stored  = set(stored) - set(rebuilt)
    shared       = set(rebuilt) & set(stored)
    print(f"    cells: {len(rebuilt):,} rebuilt, {len(stored):,} stored, "
          f"{len(shared):,} shared")
    if only_rebuilt or only_stored:
        print(f"    ONLY rebuilt: {len(only_rebuilt):,}   ONLY stored: {len(only_stored):,}")
    if not shared:
        return

    diffs = sorted(abs(rebuilt[k][0] - stored[k][0]) for k in shared)
    rel = [abs(rebuilt[k][0] - stored[k][0]) / abs(stored[k][0])
           for k in shared if stored[k][0] != 0]
    n_pts_differ = sum(1 for k in shared if rebuilt[k][1] != stored[k][1])
    exact = sum(1 for d in diffs if d == 0.0)

    def pct(p):
        return diffs[min(int(len(diffs) * p), len(diffs) - 1)]

    print(f"    value: {exact:,} identical ({100*exact/len(shared):.1f}%), "
          f"median |diff| {pct(0.5):.6g}, p95 {pct(0.95):.6g}, max {diffs[-1]:.6g}")
    if rel:
        rel.sort()
        print(f"    relative: median {100*rel[len(rel)//2]:.3f}%, "
              f"max {100*rel[-1]:.3f}%")
    print(f"    source_points differ on {n_pts_differ:,} of {len(shared):,} cells "
          f"({100*n_pts_differ/len(shared):.1f}%)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sources', default=','.join(SOURCES),
                    help=f'comma-separated; known: {", ".join(SOURCES)}')
    ap.add_argument('--table', default=DEFAULT_TABLE,
                    help=f'target table (default {DEFAULT_TABLE}, NOT the live one)')
    ap.add_argument('--truncate', action='store_true',
                    help='clear the target table for these sources first')
    ap.add_argument('--compare', action='store_true',
                    help='measure against the stored table and write nothing')
    args = ap.parse_args()

    sources = [s.strip() for s in args.sources.split(',') if s.strip()]
    unknown = [s for s in sources if s not in SOURCES]
    if unknown:
        # Fail rather than skip: a typo that silently rebuilds nothing looks
        # exactly like a successful run.
        sys.exit(f"unknown source(s): {', '.join(unknown)}. "
                 f"Known: {', '.join(SOURCES)}")

    # Every argument check happens before the connection is opened. Validation
    # that needs I/O to reject a typo is validation that fails obscurely: with
    # this guard below the connect, `--table regridded_observation` on a host
    # with no database reported a psycopg2 OperationalError instead of saying
    # what was wrong with the argument. CI caught that, because the CI database
    # is deliberately not this one.
    if args.table == LIVE_TABLE and not args.truncate:
        # Appending to the live table would double every cell and leave the
        # endpoints averaging a field with itself.
        sys.exit(f"refusing to append to {LIVE_TABLE} — pass --truncate to "
                 f"replace the rows for these sources, or use the default "
                 f"{DEFAULT_TABLE} table")

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        if args.compare:
            print("comparing a rebuild against the stored table; writing nothing")
            with conn.cursor() as cur:
                for source in sources:
                    compare(cur, source)
            return

        with conn.cursor() as cur:
            cur.execute(SCHEMA_TEMPLATE.format(table=args.table))
        conn.commit()
        print(f"target table: {args.table}\n")

        total = sum(rebuild(conn, s, args.table, args.truncate) for s in sources)
        print(f"\n{total:,} rows written to {args.table}")
        if args.table != LIVE_TABLE:
            print(f"The live {LIVE_TABLE} was not touched. Compare first:\n"
                  f"  python regrid_observations.py --compare")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
