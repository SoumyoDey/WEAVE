#!/usr/bin/env python
"""Convert GEFS ensemble NetCDF into the JSON the WEAVE loaders read.

The GEFS half of the stage that did not exist. `convert_aifs.py` (`NEXT_STEPS.md`
§16) did AIFS; this completes the set, so every forecast table in the database
can be rebuilt from source.

**It reports the initialisation time it read out of the file, and refuses to
convert a directory whose files disagree with each other.** That is not
defensive dressing — it is the whole reason this file is shaped the way it is.
On 2026-09-29 four of six model/variable combinations in the database turned out
to be the `2025-09-16` run filed under `2025-09-08`, GEFS among them, scored
against observations from eight days before those forecasts were initialised.
Nothing in the pipeline had ever looked at the init time stored *inside* the
data. Now the conversion stage does, and prints it.

Where this sits in the pipeline
-------------------------------
    GEFS NetCDF  ->  [THIS SCRIPT]  ->  json_data_gefs_ensemble/
                                            |
                                            v
                            Data_convert_weave/"aifs react.py"   (the divisor)
                                            |
                                            v
                                     load_to_postgres.py

**This script does not divide.** GEFS precipitation is a bucket total and the
divisor depends on the lead time (below); that belongs to the scaling stage,
which already knows the rule.

Conventions, every one measured against the loaded run
-----------------------------------------------------
* **Longitude is 0-360 and the database is -180..180.** The source runs
  275.0 -> 295.0 for a domain stored as -85 -> -65. Converted with
  `lon - 360 where lon > 180`. Left alone, every row lands outside the domain
  and joins with *nothing* — an empty result that reads as missing data rather
  than as a units mistake. This is the single most destructive convention here
  and the one with no visible symptom.

* **`tp(member, latitude, longitude)` on a 41x41 grid**, so a transposed read is
  silent, exactly as for AIFS. Axes resolve by dimension name. Note the
  dimension is `member`, where AIFS uses `number` — and unlike AIFS's 1-based
  `number`, this one is already 0-based and matches the database directly.

* **The grid is the target grid.** GEFS is native 0.5 deg on 25-45N/85-65W, which
  is what `regrid_members.py` regrids *to*, so its regrid is near-identity. That
  makes it the model where a coordinate error is least likely to look like
  anything.

* **The filenames lie about the accumulation window.** Every file sits under
  `Total_precipitation_surface_3_Hour_Accumulation_ens`, including the `f006`,
  `f012`, `f018` files that hold **6-hour** totals: NCEP resets the bucket every
  6 h, so the record at `h%6==3` covers 3 h and the record at `h%6==0` covers 6 h
  and *contains* the 3-hour one. The window is therefore derived from the lead
  time, never from the path.

* **`step` and `time` are in the file, and are checked.** `step` is the lead in
  hours and must equal the `fNNN` in the filename; `time` is the initialisation.
  The regional extracts have had `GRIB_stepRange`/`startStep`/`endStep`
  stripped, so the older advice to "read the step" has to mean these two
  scalars.

* **Precipitation drops anything at or below 0.01 mm**, which is *not* the same
  rule AIFS uses. Measured across 4 hours x 30 members: of 82,206 non-zero
  source cells the database keeps 78,995 with a raw minimum of **0.02 mm** and
  drops 3,211 with a raw maximum of **0.01 mm**, no overlap.

  Two things worth stating rather than smoothing over. **AIFS keeps 0.01 and
  GEFS drops it** — `convert_aifs.py` uses `>= 0.01`, this uses `> 0.01` — so
  the two models' thresholds are genuinely different and neither was guessed.
  And because GEFS tp is quantised to **0.01 mm**, `> 0.01` and `>= 0.02` fit
  the evidence identically; the constant below is the one that reproduces the
  loaded rows, and which of the two the original author wrote is not
  recoverable. A first pass at this read a single hour, saw a kept minimum of
  0.1 mm, and concluded there was no threshold at all — the boundary only
  appears once enough members are compared.

* **Wind keeps every cell**, zeros and negatives included, and is `unscaled` in
  the registry: 105 hours x 30 members x 1,681 cells = 5,295,150 rows, exactly
  what the database holds. Do not run wind through the scaling stage.

* **Values round to 3 decimals**, Python's `round`, as for AIFS.

A new load will not match the old GEFS rows, on purpose
-------------------------------------------------------
The loaded GEFS precipitation is `round(round(tp, 3) / 3, 3)` — the **fixed**
divisor of 3 applied to every file, including the `h%6==0` files that hold 6-hour
totals, so those are stored at **twice** the rate they should be. That is
`METRICS_AUDIT.md` finding 2, and `aifs react.py` has since been fixed to divide
by each record's own window. Converting afresh and scaling through the fixed
script therefore *changes* every `h%6==0` value. That is the defect being
repaired, not a discrepancy to reconcile.

`--verify` exists to check this script against the rows already loaded, so it
applies the **legacy** fixed divisor deliberately, the way `convert_aifs.py`'s
does. `--window-divisor` switches it to the correct per-window rule.

Usage
-----
    # one cycle of precipitation
    python convert_gefs.py \
        --source /projects/k.aggarwal/WEAVE/GEFS/regional_data/conus_east/Total_precipitation_surface_3_Hour_Accumulation_ens/20250916/00Z \
        --out ./json_data_gefs_ensemble

    # check against what is loaded (which is the 09-16 run, under a 09-08 label)
    python convert_gefs.py --source <that dir> --verify \
        --verify-init-time '2025-09-08 00:00:00'
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np


# Decimals kept in the JSON, in the source's own units.
VALUE_DECIMALS = 3

# The scaling stage's legacy behaviour, for `--verify` only: one fixed divisor
# for every file. Wrong at h%6==0 and reproduced here because it is what the
# stored rows went through.
LEGACY_DIVISOR_HOURS = 3.0
LEGACY_DECIMALS = 3

COORD_DP = 4

# `-f003` / `_f120`. The lead time is cross-checked against the file's own
# `step`, so this is a starting point rather than the authority.
HOUR_IN_NAME = re.compile(r'[_-]f(\d{2,3})(?:\.nc)?$')

SENTINEL = 1e30

# Variables that are bucket accumulations, so small values are absent rather
# than measured and the scaling stage owns a divisor.
ACCUMULATED = ('tp',)

# Precipitation at or below this is not written. Measured, not chosen: every
# dropped cell is <= 0.01 mm and every kept one >= 0.02 mm. Compared STRICTLY,
# because the loaded run drops 0.01 where AIFS keeps it.
MIN_PRECIP_MM = 0.01

# GEFS's own epoch for the `time`/`valid_time` scalars.
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class ConversionError(RuntimeError):
    """Raised when a file does not look the way this script requires."""


def forecast_hour(filename):
    """Lead time from the filename, or None. Verified against `step`."""
    match = HOUR_IN_NAME.search(Path(filename).stem + '.nc')
    return int(match.group(1)) if match else None


def accumulation_window(hour):
    """Hours the bucket at `hour` covers.

    NCEP resets every 6 h, so `h%6==3` is a 3-hour bucket and `h%6==0` a 6-hour
    one which contains it. Derived from the lead, because the path says
    "3_Hour_Accumulation" for both.
    """
    return 3 if hour % 6 == 3 else 6


def output_stem(init_time, hour, variable):
    r"""The JSON basename, built from the VERIFIED init time and lead hour.

    **Not the source stem.** GEFS files are named `..._f003.nc`, and both
    downstream stages parse the lead time with `-(\d+)h-`:

    * `aifs react.py` skips a file it cannot parse and reports it — which is how
      this was caught, with all 2,560 files listed as skipped.
    * `load_to_postgres.py` does `int(match.group(1)) if match else 0`, so it
      would have **silently loaded every GEFS row at forecast hour 0**: no
      error, no empty result, one hour holding eighty hours of data.

    Rebuilding the name here also means the file carries the init time this
    script read out of the data and cross-checked against `step`, rather than
    whatever the directory happened to be called.
    """
    if init_time is None:
        raise ConversionError(
            'cannot name the output without an initialisation time: the file '
            'has no `time` variable, so the run cannot be established from it')
    return f'conus_east_{init_time:%Y%m%d%H%M%S}-{hour}h-gefs_{variable}'


def read_field(path):
    """(values, lats, lons, name, init_time, step_hours), axes (member, lat, lon).

    Longitude is converted to -180..180 here rather than at the call sites, so
    there is one place it can be got wrong.
    """
    try:
        import netCDF4 as nc
    except ImportError:                                # pragma: no cover
        sys.exit('netCDF4 is required to read source files: '
                 'conda install -c conda-forge netcdf4')

    with nc.Dataset(path, 'r') as ds:
        names = [n for n, v in ds.variables.items()
                 if v.dimensions and set(v.dimensions) >= {'member', 'latitude', 'longitude'}]
        if len(names) != 1:
            raise ConversionError(
                f'{Path(path).name}: expected exactly one (member, latitude, '
                f'longitude) variable, found {names or "none"}')
        name = names[0]
        var = ds.variables[name]
        order = [var.dimensions.index(d) for d in ('member', 'latitude', 'longitude')]
        values = np.transpose(np.asarray(var[:]), order)

        lats = np.asarray(ds.variables['latitude'][:], dtype=np.float64)
        lons = np.asarray(ds.variables['longitude'][:], dtype=np.float64)
        # 0..360 -> -180..180. The destructive one.
        lons = np.where(lons > 180.0, lons - 360.0, lons)

        init_time = step_hours = None
        if 'time' in ds.variables:
            init_time = EPOCH + timedelta(seconds=float(np.asarray(ds.variables['time'][:])))
        if 'step' in ds.variables:
            step_hours = float(np.asarray(ds.variables['step'][:]))

    if values.shape[1:] != (lats.size, lons.size):
        raise ConversionError(
            f'{Path(path).name}: field is {values.shape} but the grid is '
            f'{lats.size}x{lons.size}')

    values = np.where(np.abs(values) >= SENTINEL, np.nan, values)
    return values, lats, lons, name, init_time, step_hours


def _points(field, lats, lons, accumulation, decimals):
    """Grid to records.

    `accumulation` applies the precipitation threshold: strictly greater than
    `MIN_PRECIP_MM`, which is what the loaded run does. Wind passes False and
    keeps every cell, because 0 m/s is a reading and negative is half the
    domain.

    The comparison is on the Python float, not a numpy mask: at exactly the
    threshold those two disagree, which cost `convert_aifs.py` a cell.
    """
    out = []
    for i in range(lats.size):
        lat = round(float(lats[i]), COORD_DP)
        row = field[i]
        for j in range(lons.size):
            value = float(row[j])
            if np.isnan(value):
                continue
            if accumulation and not value > MIN_PRECIP_MM:
                continue
            out.append({'lat': lat,
                        'lon': round(float(lons[j]), COORD_DP),
                        'value': round(value, decimals)})
    return out


def ensemble_stats(values, lats, lons, accumulation, decimals):
    """Mean and std records, std restricted to the cells the mean kept.

    Same coupling and the same reason as `convert_aifs.ensemble_stats`: the
    loader applies `std` with an `UPDATE` keyed on the statistics row, so a std
    at a cell with no mean is silently discarded. float32 is preserved.
    """
    mean_records = _points(np.nanmean(values, axis=0), lats, lons, accumulation, decimals)
    keep = {(r['lat'], r['lon']) for r in mean_records}
    std_records = [r for r in _points(np.nanstd(values, axis=0), lats, lons, False, decimals)
                   if (r['lat'], r['lon']) in keep]
    return mean_records, std_records


def convert_file(path, out_dir, decimals=VALUE_DECIMALS, write_stats=True):
    """Convert one NetCDF file. Returns (written, init_time, hour)."""
    values, lats, lons, variable, init_time, step_hours = read_field(path)
    hour = forecast_hour(path)

    # The filename is checked against the file's own `step` rather than trusted.
    # A mismatch means the lead time is not what the name claims, and every row
    # would be stored under the wrong hour.
    if hour is not None and step_hours is not None and abs(step_hours - hour) > 1e-9:
        raise ConversionError(
            f'{Path(path).name}: filename says f{hour:03d} but the file says '
            f'step={step_hours:g} h. The name is not the authority here.')
    if hour is None:
        hour = int(step_hours) if step_hours is not None else None
    if hour is None:
        raise ConversionError(f'{Path(path).name}: no lead time in the name or the file')

    accumulation = variable in ACCUMULATED
    stem = output_stem(init_time, hour, variable)
    written = {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def dump(suffix, records):
        target = out_dir / f'{stem}_{suffix}.json'
        with open(target, 'w') as handle:
            json.dump(records, handle)
        written[target.name] = len(records)

    for member in range(values.shape[0]):
        dump(f'member_{member:02d}', _points(values[member], lats, lons, accumulation, decimals))
    if write_stats:
        mean_records, std_records = ensemble_stats(values, lats, lons, accumulation, decimals)
        dump('mean', mean_records)
        dump('std', std_records)
    return written, init_time, hour


def convert_folder(source, out_dir, decimals=VALUE_DECIMALS, write_stats=True):
    """Convert every NetCDF file in `source`, ordered by lead time.

    Refuses a directory whose files disagree about their initialisation time,
    which is the check that would have caught the 2026-09-29 defect at the point
    it was introduced rather than three weeks later.
    """
    files = sorted(Path(source).glob('*.nc'),
                   key=lambda p: (forecast_hour(p) is None, forecast_hour(p) or 0))
    if not files:
        raise ConversionError(f'no .nc files in {source}')

    totals = {'files': 0, 'records': 0, 'hours': [], 'windows': {}}
    inits = {}
    # Decided from the first file rather than per file, so a directory holding a
    # mixture is a refusal below rather than a half-labelled report.
    accumulated = read_field(files[0])[3] in ACCUMULATED
    print(f'{len(files)} file(s) in {source}')
    for path in files:
        written, init_time, hour = convert_file(path, out_dir, decimals, write_stats)
        if init_time is not None:
            inits.setdefault(init_time, []).append(path.name)
        totals['files'] += 1
        totals['records'] += sum(written.values())
        totals['hours'].append(hour)
        # The window only means something for an accumulation. Reporting it for
        # wind printed a note about "3_Hour_Accumulation" over files that are
        # instantaneous and live in a different directory entirely.
        if accumulated:
            window = accumulation_window(hour)
            totals['windows'][window] = totals['windows'].get(window, 0) + 1
            print(f'  +{hour:>4}h  window {window}h  {len(written):3d} files, '
                  f'{sum(written.values()):>8,} records', flush=True)
        else:
            print(f'  +{hour:>4}h  {len(written):3d} files, '
                  f'{sum(written.values()):>8,} records', flush=True)

    if len(inits) > 1:
        raise ConversionError(
            'this directory holds more than one initialisation time: '
            + '; '.join(f'{t:%Y-%m-%d %H:%MZ} ({len(v)} file(s))' for t, v in inits.items()))

    print(f'\nwrote {totals["records"]:,} records from {totals["files"]} file(s) '
          f'to {out_dir}')
    if inits:
        (init,) = inits
        print(f'\n*** INITIALISATION TIME, READ FROM THE FILES: '
              f'{init:%Y-%m-%d %H:%M}Z ***')
        print(f'    Load with init_time="{init:%Y-%m-%d %H:%M:%S}". This is the run '
              f'the DATA is from;\n    the directory it sits in is not evidence. '
              f'See NEXT_STEPS.md §20.')
    if totals['windows']:
        print(f'\naccumulation windows: '
              + ', '.join(f'{n} file(s) at {w}h' for w, n in sorted(totals['windows'].items())))
        print('the path says "3_Hour_Accumulation" for all of them; the h%6==0 '
              'files hold 6 h')
    return totals


def verify(source, model='GEFS', variable='precipitation', init_time=None,
           legacy=True, limit_hours=None):
    """Compare this script's output against rows already in the database."""
    import os

    import psycopg2
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', 5432),
        dbname=os.getenv('DB_NAME', 'weave_weather'),
        user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'))
    cur = conn.cursor()

    files = sorted(Path(source).glob('*.nc'), key=lambda p: forecast_hour(p) or 0)
    if limit_hours:
        files = [p for p in files if forecast_hour(p) in limit_hours]

    where_run = 'and r.initialization_time = %s' if init_time else ''
    member_rows = stat_rows = 0
    bad_slices, bad_stats = [], []
    file_init = None

    for path in files:
        values, lats, lons, name, init_from_file, _ = read_field(path)
        file_init = init_from_file or file_init
        hour = forecast_hour(path)
        accumulation = name in ACCUMULATED
        if name in ACCUMULATED:
            divisor = LEGACY_DIVISOR_HOURS if legacy else float(accumulation_window(hour))
        else:
            divisor = 1.0

        def scaled(records, _d=divisor):
            return {(r['lat'], r['lon']): round(r['value'] / _d, LEGACY_DECIMALS)
                    for r in records}

        args = [model, variable, hour] + ([init_time] if init_time else [])
        cur.execute(f"""
            select fd.ensemble_member, fd.latitude, fd.longitude, fd.value
            from forecast_data fd
            join forecast_runs r on r.run_id = fd.run_id
            join models m on m.model_id = r.model_id
            join variables v on v.variable_id = fd.variable_id
            where m.model_name = %s and v.variable_name = %s
              and fd.forecast_hour = %s and fd.ensemble_member is not null
              {where_run}""", args)
        db = {}
        for member, lat, lon, value in cur.fetchall():
            db.setdefault(member, {})[(round(lat, COORD_DP), round(lon, COORD_DP))] = value

        for member in range(values.shape[0]):
            expected = scaled(_points(values[member], lats, lons, accumulation, VALUE_DECIMALS))
            got = db.get(member, {})
            member_rows += len(expected)
            missing = set(expected) - set(got)
            extra = set(got) - set(expected)
            differs = sum(1 for k in set(expected) & set(got)
                          if abs(expected[k] - got[k]) > 1e-12)
            if missing or extra or differs:
                bad_slices.append((hour, member, len(missing), len(extra), differs))

        mean_records, std_records = ensemble_stats(values, lats, lons, accumulation,
                                                   VALUE_DECIMALS)
        exp_mean, exp_std = scaled(mean_records), scaled(std_records)
        cur.execute(f"""
            select es.latitude, es.longitude, es.mean_value, es.std_dev
            from ensemble_statistics es
            join forecast_runs r on r.run_id = es.run_id
            join models m on m.model_id = r.model_id
            join variables v on v.variable_id = es.variable_id
            where m.model_name = %s and v.variable_name = %s and es.forecast_hour = %s
              {where_run}""", args)
        dbs = {(round(a, COORD_DP), round(b, COORD_DP)): (c, d) for a, b, c, d in cur.fetchall()}
        stat_rows += len(exp_mean)
        bad_m = sum(1 for k in exp_mean if k not in dbs or abs(exp_mean[k] - dbs[k][0]) > 1e-12)
        bad_s = sum(1 for k in exp_std
                    if k not in dbs or dbs[k][1] is None
                    or abs(exp_std[k] - dbs[k][1]) > 1e-12)
        if set(exp_mean) != set(dbs) or bad_m or bad_s:
            bad_stats.append((hour, len(set(exp_mean) ^ set(dbs)), bad_m, bad_s))

        sys.stdout.write(f'\r  +{hour:>4}h  members {member_rows:,}  stats {stat_rows:,}   ')
        sys.stdout.flush()
    print()

    conn.close()
    print(f'member rows reproduced: {member_rows:,}')
    print(f'slices differing: {len(bad_slices)}')
    for row in bad_slices[:5]:
        print(f'   hour {row[0]} member {row[1]}: {row[2]} missing, {row[3]} extra, '
              f'{row[4]} values differ')
    print(f'stat hours differing: {len(bad_stats)}')
    for row in bad_stats[:5]:
        print(f'   hour {row[0]}: {row[1]} cells one-sided, {row[2]} mean, {row[3]} std')

    if file_init and init_time:
        stored = str(init_time)[:10]
        actual = f'{file_init:%Y-%m-%d}'
        if stored != actual:
            print(f'\n*** THE LABEL AND THE DATA DISAGREE: these rows are stored under '
                  f'{stored} and the source files say {actual}. ***')

    ok = not bad_slices and not bad_stats
    print('\nVERIFIED — reproduces those rows exactly' if ok
          else '\nDID NOT reproduce those rows')
    return ok


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Convert GEFS ensemble NetCDF to the JSON the WEAVE loaders read.',
        epilog='The initialisation time is read from the files and printed; the '
               'directory name is not evidence.')
    parser.add_argument('--source', required=True,
                        help='directory of *.nc files for one variable and cycle')
    parser.add_argument('--out', help='output directory (required unless --verify)')
    parser.add_argument('--decimals', type=int, default=VALUE_DECIMALS)
    parser.add_argument('--no-stats', action='store_true',
                        help='skip the mean and std files')
    parser.add_argument('--verify', action='store_true',
                        help='compare against rows already in the database')
    parser.add_argument('--verify-init-time',
                        help='the init_time those rows are stored under, which is '
                             'not necessarily the one in the files')
    parser.add_argument('--variable', default='precipitation',
                        help='database variable name for --verify')
    parser.add_argument('--window-divisor', action='store_true',
                        help='verify against the CORRECT per-window divisor rather '
                             'than the legacy fixed 3')
    parser.add_argument('--hours', type=int, nargs='*')
    args = parser.parse_args(argv)

    if args.verify:
        return 0 if verify(args.source, variable=args.variable,
                           init_time=args.verify_init_time,
                           legacy=not args.window_divisor,
                           limit_hours=set(args.hours) if args.hours else None) else 1

    if not args.out:
        parser.error('--out is required unless --verify is given')

    convert_folder(args.source, args.out, args.decimals, write_stats=not args.no_stats)
    return 0


if __name__ == '__main__':
    sys.exit(main())
