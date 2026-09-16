#!/usr/bin/env python
"""Load native IMERG and ERA5 observations into `observation_data`.

Why this exists
---------------
`observation_data` is the one table in this database that **no script in this
repository could produce**. `regrid_observations.py` closed the gap above it —
it box-averages this table onto the 0.5 degree grid to build
`regridded_observation` — but its own docstring says plainly that its input "is
raw ingested data no script here can regenerate either". That is the last hole
in the install path: `DEPLOY.md` section 2b tells a fresh deployment it gets
forecasts and no truth, and this is why. This script closes it.

The loaded run's observations were ingested off-repo, so the conventions below
were not chosen — they were **recovered from the loaded table and then
verified against it**. `--verify` is the mode that does the recovering: it
reads a source file, builds the rows it would insert, and compares them
against what is already in `observation_data` without writing anything. On the
2025-09-08 00Z run that comparison is exact, which is what makes this a
reproduction of the original ingest rather than a second opinion about it.

Run `--verify` before trusting `--load` on a new date. The rows are a pure
function of the source files, so a convention that drifts is silent: every
score in the app would move and nothing would error.

The conventions, and where each came from
-----------------------------------------
Recovered from the loaded run, not invented here:

- **ERA5 wind** is `source = 'ERA5_WIND'`, hourly, on ERA5's native 0.25 degree
  grid. `wind_u` and `wind_v` are stored as they arrive and `wind_speed` is
  `sqrt(u^2 + v^2)` per point. That identity is not decoration:
  `regrid_observations.py` averages the stored scalar speed directly, having
  verified it equals the recomputed value everywhere, and the forecast side
  reaches the same quantity per member in `regrid_members.py`. A loader that
  stored the speed of the mean vector instead would be wrong in a way only a
  varying-direction box reveals.
- **IMERG precipitation** is `source = 'GPM_IMERG_V07B'`, half-hourly, on
  IMERG's native 0.1 degree grid, in **mm/hr** — an instantaneous rate, not an
  accumulation. `random_error` and `quality_index` come from the granule's
  `randomError` and `precipitationQualityIndex`.
- **Longitudes are stored negative** (-85 to -65), while ERA5 arrives on a
  0-360 grid (275 to 295). The conversion happens here. Getting this wrong
  produces a table that loads cleanly and joins to nothing.
- **`obs_time` is the granule's start**, not its midpoint or end.

The defect this found: IMERG is stored 4 hours behind UTC
-----------------------------------------------------------
**The legacy IMERG timestamps are 4 hours earlier than the observations they
hold, and ERA5's are not.** This was not suspected; it fell out of `--verify`
refusing to match and is now proven by exact field comparison:

- The stored rows run 2025-09-07 20:00 to 2025-09-08 19:30. The granules whose
  220x220 precipitation fields match them **exactly**, cell for cell, are UTC
  2025-09-08 00:00 to 23:30 -- the 48 granules of one UTC day.
- With `--imerg-shift-hours -4` all 2,323,200 rows reproduce with zero
  differences in any column. Without it, none of the timestamps line up.
- **ERA5 needs no shift**: its 157,464 rows reproduce exactly at face-value
  UTC. So the two truth sources in one table are on different time bases.

4 hours is UTC-4, which is Eastern Daylight Time in September over a domain
that is the US East Coast, so the likely cause is a timezone conversion
applied to IMERG and not to ERA5.

**What it costs, and what has not been measured.** Forecast valid times are
UTC -- wind verifies against unshifted ERA5 and returns plausible scores --
so every precipitation score pairs a forecast at lead H against truth from
H+4. Two consequences follow structurally: the precipitation record really
extends to +23.5 h rather than the +19.5 h `/api/observation-coverage`
reports, and every precipitation metric in `METRICS_AUDIT.md` is misaligned in
time. **How much each score moves has not been computed** -- that needs the
truth field rebuilt at correct UTC and the endpoints re-run, which is a
decision about the live table rather than something to slip into a loader.

`--imerg-shift-hours` exists to keep that decision open: it can reproduce the
legacy table exactly, which is what proves the rest of this script correct.
Default is 0, because UTC is right.

Extent
------
ERA5 arrives already cut to a region (`era5_subset.py` on the cluster does
that), but **IMERG granules are global**: 3600x1800 cells, 6.5M per granule
and 311M rows across the 48 that cover one run. The loaded table holds
220x220, so an extent has to be chosen somewhere, and `--bbox` is where. It is
an explicit argument rather than a constant because the observation record's
extent is a *measured* property in `regrid_observations.py` and inventing a
canonical one here would quietly make it a declared one.

The loaded run's hull, for reference when reproducing it:

    --bbox 24.05,45.95,-85.95,-64.05

Usage
-----
    python load_observations.py --verify --era5 era5_wind_20250908.nc
    python load_observations.py --verify --imerg 'granules/*.HDF5' \
                                --bbox 24.05,45.95,-85.95,-64.05
    python load_observations.py --load   --era5 era5_wind_20250908.nc

`--load` writes to `observation_data_rebuilt` unless given an explicit
`--table`, for the same reason `regrid_observations.py` defaults away from the
live table: a first run must not be able to destroy the field every published
number was computed against.
"""
import argparse
import glob
import io
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

DB_CONFIG = {
    'dbname':   os.environ.get('DB_NAME',     'weave_weather'),
    'user':     os.environ.get('DB_USER',     'k.aggarwal'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'host':     os.environ.get('DB_HOST',     'localhost'),
    'port':     int(os.environ.get('DB_PORT', 5432)),
}

ERA5_SOURCE  = 'ERA5_WIND'
IMERG_SOURCE = 'GPM_IMERG_V07B'

DEFAULT_TABLE = 'observation_data_rebuilt'
LIVE_TABLE    = 'observation_data'

# The column order every row tuple in this module uses, and the order `--load`
# COPYs. One list so a reordered tuple cannot silently shift values between
# columns -- `precipitation` and `wind_u` are both plain floats and neither the
# database nor COPY would object.
COLUMNS = ('obs_time', 'latitude', 'longitude', 'precipitation',
           'random_error', 'quality_index', 'source',
           'wind_u', 'wind_v', 'wind_speed')

# Coordinates are compared and grouped as keys, so they need one canonical
# spelling -- and it has to be the *stored* one, or every row looks new.
#
# 2dp, because both native grids land exactly on it: IMERG's 0.1 degree lattice
# sits at .05 offsets and ERA5's is 0.25. That is not a rounding of convenience,
# it is the precision the loaded table already holds. IMERG ships its
# coordinates as **float32**, where 24.05 is really 24.049999237060547, so
# anything finer than 2dp reproduces float32's noise instead of the lattice:
# at 6dp this built 2,190,144 rows that matched nothing, against a table whose
# row count was already exactly right.
#
# A finer observation grid would need this revisited, and would need the stored
# table revisited with it.
COORD_DP = 2

# Slack for bbox edge comparisons only, never for keys. Sized for float32's
# error at these magnitudes, so a bbox quoting a cell centre selects that cell.
COORD_TOL = 1e-4


def _coord(value):
    return round(float(value), COORD_DP)


def _to_negative_lon(lon):
    """ERA5 arrives on 0-360; `observation_data` stores -180..180."""
    return lon - 360.0 if lon > 180.0 else lon


def _clip(lats, lons, bbox):
    """Index arrays selecting the cells inside `bbox`, or everything if None.

    Inclusive on all four edges, so a bbox quoting the loaded run's hull
    (24.05..45.95) selects the cell centred on each end rather than dropping
    them. Returns index arrays rather than boolean masks so the caller can take
    an outer product without materialising the global grid.
    """
    if bbox is None:
        return np.arange(len(lats)), np.arange(len(lons))
    lat0, lat1, lon0, lon1 = bbox
    ai = np.nonzero((lats >= lat0 - COORD_TOL) & (lats <= lat1 + COORD_TOL))[0]
    oi = np.nonzero((lons >= lon0 - COORD_TOL) & (lons <= lon1 + COORD_TOL))[0]
    return ai, oi


def era5_rows(path, bbox=None):
    """Rows for one ERA5 netCDF holding `u10` and `v10`.

    `wind_speed` is computed per point with `np.hypot`, which is the stored
    convention (see the module docstring). Values are read as float32 -- what
    ERA5 ships -- and widened to Python floats, so a float8 column round-trips
    them exactly and `--verify` can demand equality rather than a tolerance.
    """
    import xarray as xr

    with xr.open_dataset(path) as ds:
        if 'u10' not in ds or 'v10' not in ds:
            raise SystemExit(f"{path}: expected u10 and v10, found {list(ds.data_vars)}")

        time_name = 'valid_time' if 'valid_time' in ds.coords else 'time'
        times = ds[time_name].values
        lats  = ds['latitude'].values
        lons  = ds['longitude'].values

        u_all = ds['u10'].values
        v_all = ds['v10'].values

    ai, oi = _clip(lats, np.array([_to_negative_lon(float(x)) for x in lons]), bbox)
    lat_keys = [_coord(x) for x in lats[ai]]
    lon_keys = [_coord(_to_negative_lon(float(x))) for x in lons[oi]]

    grid_lat = np.repeat(lat_keys, len(lon_keys))
    grid_lon = np.tile(lon_keys, len(lat_keys))

    rows = []
    for ti, when in enumerate(times):
        stamp = np.datetime64(when, 's').astype(datetime)
        u_slice = u_all[ti][np.ix_(ai, oi)]
        v_slice = v_all[ti][np.ix_(ai, oi)]
        # In float64, deliberately. ERA5 ships u and v as float32 and those are
        # stored unchanged, but the speed is derived, and the original ingest
        # derived it at double precision -- so a float32 hypot lands 5e-07 away
        # from every stored value. Verified: widening here is what turns the
        # comparison from 157,462 differing rows into an exact reproduction.
        speed = np.hypot(u_slice.astype(np.float64), v_slice.astype(np.float64))
        rows.extend(zip(
            [stamp] * grid_lat.size, grid_lat, grid_lon,
            [None] * grid_lat.size, [None] * grid_lat.size, [None] * grid_lat.size,
            [ERA5_SOURCE] * grid_lat.size,
            u_slice.ravel().astype(np.float64).tolist(),
            v_slice.ravel().astype(np.float64).tolist(),
            speed.ravel().tolist(),
        ))
    return rows


# IMERG's granule layout, kept as data so a version bump is a change here
# rather than a hunt through the reader. V07 stores the grids as
# (time, lon, lat) -- longitude before latitude, which is the opposite of the
# order the array indexing below would suggest if it were not stated.
IMERG_FIELDS = {
    'precipitation': 'precipitation',
    'random_error':  'randomError',
    'quality_index': 'precipitationQualityIndex',
}


def _imerg_stamp(dataset, value):
    """The granule's start time, from its own `time` variable.

    Read from the file rather than parsed out of the filename, which is the
    standing lesson from the GEFS files whose names claim a 3-hour window over
    6-hour totals. Two details that bite: the epoch is **1980-01-06**, not the
    Unix one, and the units string ends in a `UTC` that `np.datetime64` will
    not parse -- so it is stripped rather than passed through.
    """
    units = dataset.attrs.get('units', b'')
    units = units.decode() if isinstance(units, bytes) else str(units)
    epoch = units.split('since')[-1].strip()
    for suffix in ('UTC', 'Z'):
        if epoch.endswith(suffix):
            epoch = epoch[:-len(suffix)].strip()
    stamp = np.datetime64(epoch.replace(' ', 'T')) + np.timedelta64(int(value), 's')
    return np.datetime64(stamp, 's').astype(datetime)


def imerg_rows(paths, bbox=None, shift_hours=0.0):
    """Rows for a set of half-hourly IMERG V07 granules.

    `shift_hours` exists only to reproduce the legacy table, which stores IMERG
    timestamps **4 hours before** the granule's own UTC time -- see the module
    docstring. Leave it at 0 for new data; UTC is what every forecast table and
    the ERA5 rows use.

    V07 stores each field as **(time, lon, lat)** -- longitude before latitude,
    which is the opposite of the (lat, lon) that every other grid in this
    project uses, and transposing it silently would produce a plausible,
    fully-populated, entirely wrong table.

    Fill is -9999.9, not NaN. Those cells are dropped rather than stored as 0,
    because a missing observation and an observed dry half hour are different
    facts and the box mean in `regrid_observations.py` would average them
    together.
    """
    import h5py

    rows = []
    for path in sorted(paths):
        with h5py.File(path, 'r') as handle:
            grid = handle['Grid']
            lats = grid['lat'][:]
            lons = grid['lon'][:]
            ai, oi = _clip(lats, lons, bbox)
            stamp = _imerg_stamp(grid['time'], grid['time'][:][0])
            if shift_hours:
                stamp = stamp + timedelta(hours=shift_hours)

            box = np.ix_(oi, ai)  # (lon, lat), matching the stored layout
            precip  = grid[IMERG_FIELDS['precipitation']][0][box]
            error   = grid[IMERG_FIELDS['random_error']][0][box]
            quality = grid[IMERG_FIELDS['quality_index']][0][box]

            # Transpose to (lat, lon) so the flattened order matches the
            # lat-major grid the rest of this module and the ERA5 reader use.
            precip, error, quality = precip.T, error.T, quality.T

            lat_keys = [_coord(x) for x in lats[ai]]
            lon_keys = [_coord(x) for x in lons[oi]]
            grid_lat = np.repeat(lat_keys, len(lon_keys))
            grid_lon = np.tile(lon_keys, len(lat_keys))

            flat_precip = precip.ravel()
            keep = np.nonzero(~np.isnan(flat_precip) & (flat_precip > -9999.0))[0]

            rows.extend(zip(
                [stamp] * keep.size,
                grid_lat[keep], grid_lon[keep],
                flat_precip[keep].astype(np.float64).tolist(),
                error.ravel()[keep].astype(np.float64).tolist(),
                quality.ravel()[keep].astype(np.float64).tolist(),
                [IMERG_SOURCE] * keep.size,
                [None] * keep.size, [None] * keep.size, [None] * keep.size,
            ))
    return rows


def _key(row):
    return (row[0], row[1], row[2])


def verify(conn, source, rows):
    """Compare built rows against `observation_data`, writing nothing.

    Scoped to the timestamps the source files actually cover, so verifying one
    day of a multi-day table is meaningful rather than reporting every absent
    row as a difference.
    """
    stamps = sorted({r[0] for r in rows})
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT obs_time, latitude, longitude, precipitation,
                   random_error, quality_index, source, wind_u, wind_v, wind_speed
            FROM {LIVE_TABLE}
            WHERE source = %s AND obs_time = ANY(%s)
        """, (source, stamps))
        stored = {_key(r): r for r in cur.fetchall()}

    built = {_key(r): r for r in rows}

    print(f"  built  {len(built):,} rows over {len(stamps)} times")
    print(f"  stored {len(stored):,} rows for the same times")

    missing = sorted(set(built) - set(stored))
    extra   = sorted(set(stored) - set(built))
    if missing:
        print(f"  !! {len(missing):,} built rows are NOT in {LIVE_TABLE}, e.g. {missing[:3]}")
    if extra:
        print(f"  !! {len(extra):,} stored rows were NOT built, e.g. {extra[:3]}")

    shared = set(built) & set(stored)
    worst = {}
    mismatched = 0
    for key in shared:
        b, s = built[key], stored[key]
        differs = False
        for i, column in enumerate(COLUMNS):
            if i < 3 or column == 'source':
                continue
            bv, sv = b[i], s[i]
            if bv is None and sv is None:
                continue
            if (bv is None) != (sv is None):
                worst[column] = float('inf')
                differs = True
                continue
            delta = abs(float(bv) - float(sv))
            if delta > worst.get(column, 0.0):
                worst[column] = delta
            if delta != 0.0:
                differs = True
        if differs:
            mismatched += 1

    print(f"  compared {len(shared):,} shared rows; {mismatched:,} differ in any column")
    for column in COLUMNS:
        if column in worst:
            print(f"    max abs diff  {column:<14} {worst[column]!r}")

    exact = not missing and not extra and mismatched == 0
    print("  EXACT REPRODUCTION" if exact else "  NOT an exact reproduction")
    return exact


def copy_rows(conn, table, rows):
    """Bulk-load via COPY, matching regrid_observations.py's loader."""
    if not rows:
        return 0
    buf = io.StringIO()
    for row in rows:
        buf.write('\t'.join('' if v is None else str(v) for v in row) + '\n')
    buf.seek(0)
    with conn.cursor() as cur:
        cur.copy_from(buf, table, columns=COLUMNS, null='')
    return len(rows)


def ensure_table(conn, table):
    """Create `table` shaped like `observation_data` if it does not exist."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (table,))
        if cur.fetchone()[0] is None:
            cur.execute(f"CREATE TABLE {table} "
                        f"(LIKE {LIVE_TABLE} INCLUDING DEFAULTS INCLUDING IDENTITY)")
            conn.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--era5', help='netCDF holding u10 and v10')
    parser.add_argument('--imerg', help='glob for half-hourly IMERG V07 granules')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--verify', action='store_true',
                      help='compare against observation_data, write nothing')
    mode.add_argument('--load', action='store_true', help='insert the rows')
    parser.add_argument('--table', default=DEFAULT_TABLE,
                        help=f'target for --load (default {DEFAULT_TABLE})')
    parser.add_argument('--bbox', help='lat0,lat1,lon0,lon1 (inclusive); '
                                       'required for global IMERG granules')
    parser.add_argument('--imerg-shift-hours', type=float, default=0.0,
                        help='shift IMERG timestamps; -4 reproduces the legacy '
                             'table, which is 4h behind UTC. Default 0 (UTC).')
    args = parser.parse_args()

    if not args.era5 and not args.imerg:
        parser.error('give --era5 and/or --imerg')

    bbox = None
    if args.bbox:
        try:
            bbox = tuple(float(x) for x in args.bbox.split(','))
        except ValueError:
            parser.error(f'--bbox wants four numbers, got {args.bbox!r}')
        if len(bbox) != 4:
            parser.error(f'--bbox wants four numbers, got {len(bbox)}')

    batches = []
    if args.era5:
        print(f"ERA5  {args.era5}")
        batches.append((ERA5_SOURCE, era5_rows(args.era5, bbox)))
    if args.imerg:
        paths = glob.glob(args.imerg)
        if not paths:
            parser.error(f'--imerg matched no files: {args.imerg}')
        print(f"IMERG {len(paths)} granules")
        batches.append((IMERG_SOURCE, imerg_rows(paths, bbox, args.imerg_shift_hours)))

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        if args.verify:
            ok = all(verify(conn, source, rows) for source, rows in batches)
            return 0 if ok else 1

        ensure_table(conn, args.table)
        for source, rows in batches:
            written = copy_rows(conn, args.table, rows)
            conn.commit()
            print(f"  {source}: {written:,} rows -> {args.table}")
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
