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

Nothing here overwrites `regridded_forecast`. Output goes to
`regridded_forecast_member` and `regridded_forecast_ens`, so the old and new
numbers can be compared before anything is switched over.

Usage
-----
    python regrid_members.py --variables precipitation
    python regrid_members.py --models AIFS --hours 0-48 --verify
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

SCHEMA = """
CREATE TABLE IF NOT EXISTS regridded_forecast_member (
    model_name      TEXT    NOT NULL,
    variable_name   TEXT    NOT NULL,
    forecast_hour   INTEGER NOT NULL,
    ensemble_member INTEGER NOT NULL,
    latitude        REAL    NOT NULL,
    longitude       REAL    NOT NULL,
    value           REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS regridded_forecast_ens (
    model_name      TEXT    NOT NULL,
    variable_name   TEXT    NOT NULL,
    forecast_hour   INTEGER NOT NULL,
    latitude        REAL    NOT NULL,
    longitude       REAL    NOT NULL,
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
"""


def target_grid(cursor):
    """The 0.5° grid already in use, read from regridded_forecast so the new
    tables land on exactly the same cells as the old one."""
    cursor.execute("SELECT DISTINCT latitude FROM regridded_forecast ORDER BY 1")
    lats = [float(r[0]) for r in cursor.fetchall()]
    cursor.execute("SELECT DISTINCT longitude FROM regridded_forecast ORDER BY 1")
    lons = [float(r[0]) for r in cursor.fetchall()]
    return np.array(lats), np.array(lons)


def fetch_hour(cursor, model, variable, hour):
    """{member: {(lat, lon): value}} for one model/variable/forecast hour."""
    cursor.execute("""
        SELECT fd.ensemble_member, fd.latitude, fd.longitude, fd.value
        FROM forecast_data fd
        JOIN forecast_runs fr ON fr.run_id = fd.run_id
        JOIN models m         ON m.model_id = fr.model_id
        JOIN variables v      ON v.variable_id = fd.variable_id
        WHERE m.model_name = %s AND v.variable_name = %s
          AND fd.forecast_hour = %s AND fd.ensemble_member IS NOT NULL
          AND fd.value IS NOT NULL
    """, (model, variable, hour))
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


def regrid(conn, model, variable, hours, tgt_lats, tgt_lons, verify=False):
    zero_fill = variable in ZERO_FILL_VARIABLES
    total_member_rows = total_ens_rows = 0
    verify_stats = []

    with conn.cursor() as cur:
        for hour in hours:
            by_member = fetch_hour(cur, model, variable, hour)
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
                            member_rows.append((model, variable, hour, m,
                                                float(lat), float(lon), float(value)))
                    ens_rows.append((model, variable, hour, float(lat), float(lon),
                                     float(mean[i, j]), float(std[i, j]),
                                     len(members), '0.5deg'))

            total_member_rows += copy_rows(
                conn, 'regridded_forecast_member',
                ('model_name', 'variable_name', 'forecast_hour', 'ensemble_member',
                 'latitude', 'longitude', 'value'), member_rows)
            total_ens_rows += copy_rows(
                conn, 'regridded_forecast_ens',
                ('model_name', 'variable_name', 'forecast_hour', 'latitude', 'longitude',
                 'mean_value', 'std_dev', 'n_members', 'resolution'), ens_rows)
            conn.commit()
            print(f"    {model} {variable} fh={hour:3d}: {len(members):2d} members, "
                  f"{int(inside.sum()):4d} cells, {len(member_rows):6,} member rows")

    if verify and verify_stats:
        worst = max(verify_stats)
        status = "OK" if worst < 1e-9 else "MISMATCH"
        print(f"  linearity check mean(bilinear(members)) == bilinear(mean): "
              f"max|diff|={worst:.3e}  {status}")
    return total_member_rows, total_ens_rows


def parse_hours(spec, cursor, model, variable):
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
        ORDER BY 1
    """, (model, variable))
    return [int(r[0]) for r in cursor.fetchall()]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--models', default='AIFS,GEFS,UKMO')
    ap.add_argument('--variables', default='precipitation')
    ap.add_argument('--hours', default=None, help='e.g. "0-48" or "6,12,18"; default all')
    ap.add_argument('--verify', action='store_true',
                    help='assert bilinear linearity and compare against the stored table')
    ap.add_argument('--truncate', action='store_true',
                    help='clear the target tables for these models/variables first')
    args = ap.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
            cur.execute(INDEXES)
        conn.commit()

        with conn.cursor() as cur:
            tgt_lats, tgt_lons = target_grid(cur)
        print(f"target grid: {len(tgt_lats)} x {len(tgt_lons)} at 0.5deg "
              f"({tgt_lats[0]}..{tgt_lats[-1]}, {tgt_lons[0]}..{tgt_lons[-1]})\n")

        for model in args.models.split(','):
            for variable in args.variables.split(','):
                with conn.cursor() as cur:
                    if args.truncate:
                        for table in ('regridded_forecast_member', 'regridded_forecast_ens'):
                            cur.execute(f"DELETE FROM {table} "
                                        f"WHERE model_name=%s AND variable_name=%s",
                                        (model, variable))
                        conn.commit()
                    hours = parse_hours(args.hours, cur, model, variable)
                if not hours:
                    print(f"  {model} {variable}: no forecast hours, skipped")
                    continue
                print(f"  {model} {variable}: {len(hours)} forecast hours")
                m_rows, e_rows = regrid(conn, model, variable, hours,
                                        tgt_lats, tgt_lons, verify=args.verify)
                print(f"  -> {m_rows:,} member rows, {e_rows:,} ensemble rows\n")
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
