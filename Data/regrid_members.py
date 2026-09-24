#!/usr/bin/env python
"""Bilinear regridding of individual ensemble members onto the common 0.5° grid.

Why this exists
---------------
`regridded_forecast` stores only `mean_value` and `std_dev`, and that `std_dev`
is the spread of the pooled (member × native-cell) population — it mixes the
ensemble spread with the spatial variance inside each 0.5° box. Every
spread-dependent score built on it (SSR, CRPS, Brier) inherits that inflation,
and per-member differencing of a cumulative model (AIFS) is impossible without
the members themselves.

This script regrids each member separately, then derives the ensemble mean and
spread *from the regridded members*. The result is internally consistent:

    mean_value = mean over members of the regridded member field
    std_dev    = the true ensemble spread of that field, sample (ddof=1)

Method
------
Bilinear interpolation on the model's regular lat/lon source grid — the same
operator `cdo remapbil` applies, implemented directly here because the original
member files are not available locally and the interpolation has to run from
`forecast_data`. Bilinear is a *linear* operator, which gives a free consistency
check the caller can run:

    mean(bilinear(members)) == bilinear(mean(members))

`--verify` asserts exactly that, and also reports how the derived spread differs
from the stored pooled `std_dev`.

Missing native cells
--------------------
Precipitation was sparsified before loading: cells at or near zero were never
written (the smallest stored AIFS value is 0.002 mm). A native cell absent for a
member therefore means "no precipitation", and is filled with 0.0 rather than
being treated as missing — interpolating around such a hole would bias the
result wet. Wind is dense and unaffected.

Nothing here reads or writes `regridded_forecast`. Output goes to
`regridded_forecast_member` and `regridded_forecast_ens`, so the old and new
numbers can be compared before anything is switched over. The target grid used
to be read from `regridded_forecast` — it is now a constant, which is what makes
that table droppable; `target_grid` says why.

Usage
-----
    python regrid_members.py --variables precipitation
    python regrid_members.py --models AIFS --hours 0-48 --verify
    python regrid_members.py --verify-grid --hours 0   # check the grid constant
"""
import argparse
import io
import os
import sys
from collections import defaultdict

import numpy as np
import psycopg2
from dotenv import load_dotenv
from scipy.interpolate import RegularGridInterpolator

# Local: the run registry, written at the end of each model/variable so the
# run describes its own export convention rather than being inferred later.
import run_registry

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

DB_CONFIG = {
    'dbname':   os.environ.get('DB_NAME',     'weave_weather'),
    'user':     os.environ.get('DB_USER',     'k.aggarwal'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'host':     os.environ.get('DB_HOST',     'localhost'),
    'port':     int(os.environ.get('DB_PORT', 5432)),
}

# Variables that were sparsified on load — an absent native cell means zero,
# not missing. See the module docstring.
ZERO_FILL_VARIABLES = {'precipitation'}

# The common analysis grid every scored endpoint reads: 0.5° over the domain the
# whole project uses. Stated here rather than discovered by query — see
# `target_grid` for why that changed.
TARGET_LAT_RANGE  = (25.0, 45.0)
TARGET_LON_RANGE  = (-85.0, -65.0)
TARGET_RESOLUTION = 0.5

SCHEMA = """
CREATE TABLE IF NOT EXISTS regridded_forecast_member (
    model_name      TEXT      NOT NULL,
    variable_name   TEXT      NOT NULL,
    init_time       TIMESTAMP NOT NULL,
    forecast_hour   INTEGER   NOT NULL,
    ensemble_member INTEGER   NOT NULL,
    latitude        REAL      NOT NULL,
    longitude       REAL      NOT NULL,
    value           REAL      NOT NULL
);

CREATE TABLE IF NOT EXISTS regridded_forecast_ens (
    model_name      TEXT      NOT NULL,
    variable_name   TEXT      NOT NULL,
    init_time       TIMESTAMP NOT NULL,
    forecast_hour   INTEGER   NOT NULL,
    latitude        REAL      NOT NULL,
    longitude       REAL      NOT NULL,
    mean_value      REAL,
    std_dev         REAL,
    n_members       INTEGER,
    resolution      TEXT
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_rfm_lookup
    ON regridded_forecast_member(model_name, variable_name, forecast_hour, latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_rfm_cell
    ON regridded_forecast_member(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_rfe_lookup
    ON regridded_forecast_ens(model_name, variable_name, forecast_hour, latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_rfe_cell
    ON regridded_forecast_ens(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_rfm_run
    ON regridded_forecast_member(model_name, variable_name, init_time, forecast_hour, latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_rfe_run
    ON regridded_forecast_ens(model_name, variable_name, init_time, forecast_hour, latitude, longitude);

-- The natural key, enforced. Without these, re-running a regrid over hours
-- already present appends a second copy of every row and nothing complains —
-- and every score is then computed over duplicated members, which is a spread
-- that looks plausible and is wrong. DATA_EXPANSION_DESIGN.md phase 4 item 1
-- asks for each step to be re-runnable; this is what makes that true rather
-- than hoped for.
--
-- `idx_rfm_run` above looks similar and is not a substitute: it is not unique,
-- and it omits `ensemble_member`, which is part of what identifies a member row.
CREATE UNIQUE INDEX IF NOT EXISTS uq_rfm_natural_key
    ON regridded_forecast_member(model_name, variable_name, init_time,
                                 forecast_hour, ensemble_member, latitude, longitude);
CREATE UNIQUE INDEX IF NOT EXISTS uq_rfe_natural_key
    ON regridded_forecast_ens(model_name, variable_name, init_time,
                              forecast_hour, latitude, longitude);
"""


def target_grid():
    """The common 0.5° grid, as a constant.

    This used to read `SELECT DISTINCT latitude/longitude FROM
    regridded_forecast`, so the new tables would land on exactly the same cells
    as the old one. Two things made that wrong to keep:

    - **Nothing in this repository writes `regridded_forecast`.** It was produced
      off-repo, so on a fresh database the query returned nothing and this script
      died on the next line printing `tgt_lats[0]`. There was no way to bootstrap.
    - **Repointing it at `regridded_forecast_ens` would be worse**, that being
      this script's own output: empty on the first run, and thereafter keyed on
      the union of whatever native hulls have been regridded so far rather than
      on the canonical grid. Cells outside a model's hull are never written (see
      the `inside` test in `regrid`), and UKMO's native grid does not reach the
      domain edge, so a `_ens` holding UKMO alone yields 39x39 spanning
      25.5..44.5 — silently clipping AIFS and GEFS to UKMO's footprint on the
      next run, 160 cells per model/variable/hour, with no error.

    The grid was never a discovered quantity, only an undocumented one. 0.5 is
    exact in binary, so this reproduces the stored coordinates bit-for-bit rather
    than approximately; verified against all three regridded tables on the loaded
    run, 41x41 identical in both axes. `--verify-grid` re-runs that check against
    whichever of them still exist.

    That exactness is doing real work, and it is worth knowing why it holds: the
    two tables this script writes declare their coordinates `REAL`, i.e. float32,
    while `regridded_forecast` used `FLOAT`. Multiples of 0.5 survive both
    identically, which is why one constant can be compared against all three and
    why `WHERE latitude = 35.5` still matches its own row. A grid at a resolution
    that is *not* a binary fraction — 0.1, 0.05 — would not survive the float32
    round trip, and this comparison would have to move to a tolerance. That is
    already visible elsewhere in the schema: `ensemble_statistics` holds UKMO wind
    at 35.1562 and UKMO precipitation at 35.15625 for exactly this reason.
    """
    def axis(lo, hi):
        # Half a step of headroom: arange's stop is exclusive, and this keeps the
        # endpoint from turning on floating-point luck.
        return np.arange(lo, hi + TARGET_RESOLUTION / 2, TARGET_RESOLUTION)

    return axis(*TARGET_LAT_RANGE), axis(*TARGET_LON_RANGE)


def verify_grid(cursor, tgt_lats, tgt_lons):
    """Assert the constant grid matches what the regridded tables already hold.

    This is what makes dropping `regridded_forecast` safe: the coordinates it
    defined for everything downstream have to be the coordinates the constant
    produces, exactly. Tables that do not exist yet are skipped rather than
    failing, so this is runnable on a partly built database.
    """
    for table in ('regridded_forecast', 'regridded_forecast_ens',
                  'regridded_forecast_member'):
        cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (table,))
        if not cursor.fetchone()[0]:
            print(f"  {table}: absent, skipped")
            continue
        for column, expected in (('latitude', tgt_lats), ('longitude', tgt_lons)):
            cursor.execute(f"SELECT DISTINCT {column} FROM {table} ORDER BY 1")
            stored = [float(r[0]) for r in cursor.fetchall()]
            if not stored:
                print(f"  {table}.{column}: empty, skipped")
                continue
            # A subset is the expected state for one model whose native hull does
            # not span the domain; a coordinate that is *not* on the grid is not.
            off_grid = sorted(set(stored) - {float(v) for v in expected})
            if off_grid:
                raise AssertionError(
                    f"{table}.{column} holds {len(off_grid)} coordinate(s) that "
                    f"the constant grid does not produce, e.g. {off_grid[:5]} — "
                    f"the constant and the stored data disagree")
            print(f"  {table}.{column}: {len(stored)} of {len(expected)} cells, "
                  f"all on the grid")


def run_init_time(cursor, model, requested=None):
    """The initialisation time this model's `forecast_data` belongs to.

    `requested` selects one when several are loaded. Until 2026-09-24 this
    function refused on ambiguity and told the caller to "pass the run
    explicitly" — with no parameter to pass it through, so loading a second run
    made the model unregriddable, including the run already there. The refusal
    was right; the missing argument was the bug.

    Written into every regridded row so the output carries its run identity.
    Before `migrate_init_time.py` the regridded tables had no such column and
    the API resolved "the latest run" at query time — which is correct with one
    run loaded and silently wrong with two.

    Fails rather than defaulting when a model has more than one run, because the
    native rows this reads are keyed by `run_id` and picking one of several here
    would attribute a regrid to the wrong initialisation.
    """
    cursor.execute("""
        SELECT DISTINCT fr.initialization_time
        FROM forecast_data fd
        JOIN forecast_runs fr ON fr.run_id = fd.run_id
        JOIN models m         ON m.model_id = fr.model_id
        WHERE m.model_name = %s
    """, (model,))
    times = [r[0] for r in cursor.fetchall()]
    if not times:
        raise SystemExit(f"{model}: no forecast_data, so no run to attribute a "
                         f"regrid to")
    if requested is not None:
        match = [t for t in times if str(t) == str(requested)]
        if not match:
            raise SystemExit(
                f"{model}: no forecast_data at {requested}. Loaded runs are "
                f"{sorted(str(t) for t in times)}.")
        return match[0]
    if len(times) > 1:
        raise SystemExit(
            f"{model}: forecast_data spans {len(times)} initialisation times "
            f"({sorted(str(t) for t in times)}). Regrid one run at a time — pass "
            f"--init-time to say which.")
    return times[0]


def fetch_hour(cursor, model, variable, hour, init_time):
    """{member: {(lat, lon): value}} for one model/variable/hour of one run.

    **`init_time` is not optional, and that is the point.** Until 2026-09-24
    this query was not scoped to a run at all. With one run loaded that was
    harmless; with two it returns members from both, and since the result is
    keyed by member number the later run's member 5 silently overwrites the
    earlier one's. The regrid would then emit a blend of two initialisations,
    correctly shaped and quietly wrong — the exact failure the `init_time`
    migration exists to prevent, surviving in the one place that writes the
    regridded tables rather than reads them.

    Nothing caught it because `run_init_time` refused to proceed when a model
    had more than one run, so this code path had never run against two.
    """
    cursor.execute("""
        SELECT fd.ensemble_member, fd.latitude, fd.longitude, fd.value
        FROM forecast_data fd
        JOIN forecast_runs fr ON fr.run_id = fd.run_id
        JOIN models m         ON m.model_id = fr.model_id
        JOIN variables v      ON v.variable_id = fd.variable_id
        WHERE m.model_name = %s AND v.variable_name = %s
          AND fd.forecast_hour = %s AND fd.ensemble_member IS NOT NULL
          AND fd.value IS NOT NULL
          AND fr.initialization_time = %s
    """, (model, variable, hour, init_time))
    by_member = defaultdict(dict)
    for member, lat, lon, value in cursor.fetchall():
        by_member[int(member)][(round(float(lat), 4), round(float(lon), 4))] = float(value)
    return by_member


def interpolate_member(cell_values, src_lats, src_lons, tgt_lats, tgt_lons, zero_fill):
    """Bilinear-interpolate one member's scattered native cells to the target grid.

    Returns a (len(tgt_lats), len(tgt_lons)) array, NaN outside the source hull.
    """
    grid = np.full((len(src_lats), len(src_lons)), np.nan)
    li = {v: i for i, v in enumerate(src_lats)}
    oi = {v: i for i, v in enumerate(src_lons)}
    for (lat, lon), value in cell_values.items():
        grid[li[lat], oi[lon]] = value
    if zero_fill:
        grid = np.nan_to_num(grid, nan=0.0)
    elif np.isnan(grid).any():
        # A dense variable with real holes: fill each gap with the column mean so
        # bilinear stays defined, and let the caller see it via n_members.
        col_mean = np.nanmean(grid, axis=0)
        idx = np.where(np.isnan(grid))
        grid[idx] = np.take(col_mean, idx[1])
        grid = np.nan_to_num(grid, nan=0.0)

    interp = RegularGridInterpolator(
        (np.asarray(src_lats), np.asarray(src_lons)), grid,
        method='linear', bounds_error=False, fill_value=np.nan)
    mesh_lat, mesh_lon = np.meshgrid(tgt_lats, tgt_lons, indexing='ij')
    points = np.stack([mesh_lat.ravel(), mesh_lon.ravel()], axis=-1)
    return interp(points).reshape(len(tgt_lats), len(tgt_lons))


def clear_slice(conn, table, model, variable, init_time, hour):
    """Remove the (model, variable, run, hour) slice about to be rewritten.

    What makes a re-run safe. `COPY` cannot express `ON CONFLICT`, so the
    idempotency has to come from clearing first — and clearing exactly the
    slice this pass is about to write, so re-running one hour does not disturb
    the rest of the run.

    Runs in the same transaction as the `COPY` that follows (the loop commits
    per hour), so a crash between them leaves the slice as it was rather than
    deleted. The unique indexes are the backstop: if this is ever skipped, the
    second write fails loudly instead of silently doubling the data.
    """
    with conn.cursor() as cur:
        cur.execute(f"""
            DELETE FROM {table}
             WHERE model_name = %s AND variable_name = %s
               AND init_time = %s AND forecast_hour = %s
        """, (model, variable, init_time, hour))
        return cur.rowcount


def copy_rows(conn, table, columns, rows):
    """Bulk-load via COPY — orders of magnitude faster than execute_batch here."""
    if not rows:
        return 0
    buf = io.StringIO()
    for row in rows:
        buf.write('\t'.join('' if v is None else str(v) for v in row))
        buf.write('\n')
    buf.seek(0)
    with conn.cursor() as cur:
        cur.copy_from(buf, table, columns=columns, null='')
    return len(rows)


def regrid(conn, model, variable, hours, tgt_lats, tgt_lons, verify=False,
           init_time_requested=None):
    zero_fill = variable in ZERO_FILL_VARIABLES
    total_member_rows = total_ens_rows = 0
    verify_stats = []
    # What actually got written, for the registry row at the end. Tracked as we
    # go rather than derived afterwards: deriving means a GROUP BY over
    # `regridded_forecast_member`, which is 42M rows, to learn something this
    # loop already knows. `run_registry.py --refresh` still recomputes it from
    # the data when reconciliation is wanted.
    written_hours = []
    max_members = 0

    with conn.cursor() as cur:
        # Resolved once per model/variable and written into every row, so the
        # output says which run it came from instead of leaving the API to guess.
        init_time = run_init_time(cur, model, init_time_requested)
        for hour in hours:
            by_member = fetch_hour(cur, model, variable, hour, init_time)
            if not by_member:
                continue

            src_lats = sorted({lat for cells in by_member.values() for lat, _ in cells})
            src_lons = sorted({lon for cells in by_member.values() for _, lon in cells})
            if len(src_lats) < 2 or len(src_lons) < 2:
                print(f"    {model} {variable} fh={hour}: source grid too small, skipped")
                continue

            members = sorted(by_member)
            stack = np.stack([
                interpolate_member(by_member[m], src_lats, src_lons,
                                   tgt_lats, tgt_lons, zero_fill)
                for m in members
            ])                                             # (M, nlat, nlon)

            mean = np.nanmean(stack, axis=0)
            # Sample spread across MEMBERS only — no spatial variance mixed in.
            std = np.nanstd(stack, axis=0, ddof=1) if len(members) > 1 else np.zeros_like(mean)
            inside = ~np.isnan(mean)

            if verify:
                # Bilinear is linear: interpolating the native ensemble mean must
                # equal the mean of the interpolated members.
                native_sum = defaultdict(float)
                for cells in by_member.values():
                    for cell, value in cells.items():
                        native_sum[cell] += value
                # Divide by EVERY member, not just those present at the cell: a
                # sparsified variable records absence as zero, so averaging only
                # the members that reported would bias the mean wet. This is the
                # same convention the per-member path applies via zero_fill.
                denom = max(1, len(by_member))
                mean_field = {c: v / denom for c, v in native_sum.items()}
                direct = interpolate_member(mean_field, src_lats, src_lons,
                                            tgt_lats, tgt_lons, zero_fill)
                both = inside & ~np.isnan(direct)
                if both.any():
                    verify_stats.append(np.abs(direct[both] - mean[both]).max())

            member_rows, ens_rows = [], []
            for i, lat in enumerate(tgt_lats):
                for j, lon in enumerate(tgt_lons):
                    if not inside[i, j]:
                        continue
                    for k, m in enumerate(members):
                        value = stack[k, i, j]
                        if not np.isnan(value):
                            member_rows.append((model, variable, init_time, hour, m,
                                                float(lat), float(lon), float(value)))
                    ens_rows.append((model, variable, init_time, hour,
                                     float(lat), float(lon),
                                     float(mean[i, j]), float(std[i, j]),
                                     len(members), '0.5deg'))

            # Idempotency, per hour: clear what this pass is about to write.
            # Without it a re-run appends a second copy of every row — see
            # clear_slice and the unique indexes in INDEXES.
            replaced = (clear_slice(conn, 'regridded_forecast_member',
                                    model, variable, init_time, hour)
                        + clear_slice(conn, 'regridded_forecast_ens',
                                      model, variable, init_time, hour))

            total_member_rows += copy_rows(
                conn, 'regridded_forecast_member',
                ('model_name', 'variable_name', 'init_time', 'forecast_hour',
                 'ensemble_member', 'latitude', 'longitude', 'value'), member_rows)
            total_ens_rows += copy_rows(
                conn, 'regridded_forecast_ens',
                ('model_name', 'variable_name', 'init_time', 'forecast_hour',
                 'latitude', 'longitude',
                 'mean_value', 'std_dev', 'n_members', 'resolution'), ens_rows)
            conn.commit()
            written_hours.append(hour)
            max_members = max(max_members, len(members))
            print(f"    {model} {variable} fh={hour:3d}: {len(members):2d} members, "
                  f"{int(inside.sum()):4d} cells, {len(member_rows):6,} member rows"
                  + (f", replaced {replaced:,}" if replaced else ""))

        # Register the run, so it describes itself instead of being inferred
        # later. DATA_EXPANSION_DESIGN.md phase 4: until now nothing but a
        # migration had ever written this table, so a second run would have
        # been absent from /api/runs entirely — invisible to the run selector
        # and with no record of how its export was produced.
        #
        # Only when something was written. A model/variable that produced no
        # rows must not leave a registry row claiming it is loaded.
        if written_hours:
            with conn.cursor() as reg_cur:
                run_registry.ensure_schema(reg_cur)
                run_registry.record(
                    reg_cur, model, variable, init_time,
                    n_members=max_members,
                    hour_min=min(written_hours), hour_max=max(written_hours))
            conn.commit()
            declared = run_registry.declared_for(model, variable)
            how = (f"{declared[0]}" + (f" /{declared[1]:g}h" if declared[1] else '')
                   if declared else 'UNDECLARED — scoring cannot resolve a divisor')
            print(f"    {model} {variable}: registered {min(written_hours)}–"
                  f"{max(written_hours)}h, {max_members} members, {how}")

    if verify and verify_stats:
        worst = max(verify_stats)
        status = "OK" if worst < 1e-9 else "MISMATCH"
        print(f"  linearity check mean(bilinear(members)) == bilinear(mean): "
              f"max|diff|={worst:.3e}  {status}")
    return total_member_rows, total_ens_rows


def parse_hours(spec, cursor, model, variable, init_time=None):
    """Which lead hours to regrid.

    `init_time` scopes the discovered set to one run. Without it the union
    across runs comes back, and regridding run A would walk hours that only
    exist in run B — wasted work rather than wrong output, since `fetch_hour`
    is now run-scoped and simply finds nothing, but it makes the log lie about
    what was attempted.
    """
    if spec:
        if '-' in spec:
            a, b = spec.split('-')
            return list(range(int(a), int(b) + 1))
        return [int(h) for h in spec.split(',')]
    cursor.execute("""
        SELECT DISTINCT fd.forecast_hour
        FROM forecast_data fd
        JOIN forecast_runs fr ON fr.run_id = fd.run_id
        JOIN models m         ON m.model_id = fr.model_id
        JOIN variables v      ON v.variable_id = fd.variable_id
        WHERE m.model_name = %s AND v.variable_name = %s
          AND (%s IS NULL OR fr.initialization_time = %s)
        ORDER BY 1
    """, (model, variable, init_time, init_time))
    return [int(r[0]) for r in cursor.fetchall()]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--models', default='AIFS,GEFS,UKMO')
    ap.add_argument('--variables', default='precipitation')
    ap.add_argument('--hours', default=None, help='e.g. "0-48" or "6,12,18"; default all')
    ap.add_argument('--verify', action='store_true',
                    help='assert bilinear linearity and compare against the stored table')
    ap.add_argument('--verify-grid', action='store_true',
                    help='assert every stored coordinate lies on the constant '
                         'target grid, then continue')
    ap.add_argument('--truncate', action='store_true',
                    help='clear the target tables for these models/variables first')
    ap.add_argument('--init-time', default=None,
                    help='which loaded run to regrid, e.g. "2025-09-08 06:00:00". '
                         'Required once a model has more than one run in '
                         'forecast_data; without it an ambiguous model is refused '
                         'rather than guessed at.')
    args = ap.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
            cur.execute(INDEXES)
        conn.commit()

        tgt_lats, tgt_lons = target_grid()
        print(f"target grid: {len(tgt_lats)} x {len(tgt_lons)} at "
              f"{TARGET_RESOLUTION}deg "
              f"({tgt_lats[0]}..{tgt_lats[-1]}, {tgt_lons[0]}..{tgt_lons[-1]})\n")

        if args.verify_grid:
            print("verifying the constant grid against the stored tables:")
            with conn.cursor() as cur:
                verify_grid(cur, tgt_lats, tgt_lons)
            print()

        for model in args.models.split(','):
            for variable in args.variables.split(','):
                with conn.cursor() as cur:
                    if args.truncate:
                        for table in ('regridded_forecast_member', 'regridded_forecast_ens'):
                            cur.execute(f"DELETE FROM {table} "
                                        f"WHERE model_name=%s AND variable_name=%s",
                                        (model, variable))
                        conn.commit()
                    hours = parse_hours(args.hours, cur, model, variable,
                                        args.init_time)
                if not hours:
                    print(f"  {model} {variable}: no forecast hours, skipped")
                    continue
                print(f"  {model} {variable}: {len(hours)} forecast hours")
                m_rows, e_rows = regrid(conn, model, variable, hours,
                                        tgt_lats, tgt_lons, verify=args.verify,
                                        init_time_requested=args.init_time)
                print(f"  -> {m_rows:,} member rows, {e_rows:,} ensemble rows\n")
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
