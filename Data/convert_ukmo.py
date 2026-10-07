#!/usr/bin/env python
"""Convert UKMO ensemble NetCDF into the JSON the WEAVE loaders read.

The third and last converter, completing the set with `convert_aifs.py` (§16)
and `convert_gefs.py` (§20). `Data_convert_weave/React.py` already handled UKMO
*precipitation* and lives outside the repository; this covers **wind**, which
had no converter at all, and reimplements precipitation so the whole model can
be rebuilt from inside the tree.

Like `convert_gefs.py`, it reads the initialisation time out of the file and
prints it, and refuses a directory whose files disagree. That is the check that
`NEXT_STEPS.md` §20 exists because nobody had: UKMO wind stored at
`2025-09-08` is the `2025-09-16` run, and `forecast_reference_time` said so all
along.

UKMO differs from the other two in almost every convention
----------------------------------------------------------
Worth reading before assuming anything carries over:

* **The ensemble dimension is `realization`** — not AIFS's `number`, not GEFS's
  `member`. Its values are **already 0-based** and match the database directly,
  where AIFS's `number` is 1-based and needs the array index instead.

* **Longitude is already signed** (-84.796875), so there is **no 0-360
  conversion**. GEFS needs one and getting it wrong there silently empties the
  domain; doing it here would be equally silent and equally wrong. The guard
  below is a no-op on this data by design, not by accident.

* **The lead time is `forecast_period`, in SECONDS.** AIFS and GEFS carry a
  `step` in hours. 86400 here means +24 h, not +86400 h.

* **The grid is 107 x 71 = 7,597 cells**, unaligned at 0.1875 x 0.28125 deg. Not
  square, so a transposed read fails loudly rather than silently — the one
  convention where UKMO is *safer* than the other two.

* **One file per valid time, and the filename carries the VALID time, not the
  initialisation.** `conus_east_20250909T0000Z-PT0024H00M-...` is the +24 h lead
  of the 09-08 00Z run. Reading the date in that name as the run is exactly the
  mistake §20 documents.

* **Precipitation is `total_rainfall_rate` in m/s**, needing x3.6e6 to reach
  mm/h, and is recorded `unscaled` in the registry because that conversion
  leaves a rate rather than an amount. Nothing downstream should divide it
  again. Wind is m/s already.

* **18 members**, against AIFS's 50 and GEFS's 30.

Usage
-----
    python convert_ukmo.py \
        --source .../u_wind_at_10m/2025-09-08/T0000Z --out ./json_ukmo_u

    python convert_ukmo.py --source <that dir> --verify \
        --variable wind_u_10m --verify-init-time '2025-09-08 00:00:00'
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np


VALUE_DECIMALS = 3

# Precipitation keeps 4, matching what `React.py` wrote and what the stored rows
# carry. Wind keeps 3. Neither is a free choice: they are what is loaded.
PRECIP_DECIMALS = 4

# m/s -> mm/h for `total_rainfall_rate`. The AIFS/GEFS `tp` is already mm and
# needs nothing; applying this to those would inflate rainfall a millionfold,
# and omitting it here leaves rates around 1e-7.
MS_TO_MM_H = 3_600_000.0

COORD_DP = 4
SENTINEL = 1e30

# `-PT0024H00M-`. Cross-checked against `forecast_period`.
LEAD_IN_NAME = re.compile(r'-PT(\d{2,4})H(\d{2})M-')

# Source variable -> (database variable, units factor, decimals, std decimals,
# drop zeros).
#
# **Precipitation rounds its mean to 4 and its std to 6.** That asymmetry is not
# a choice, it is what `React.py` wrote and what the stored rows carry: its mean
# block rounds to 4 and its std block to 6. Using one figure for both reproduces
# the members and the mean exactly and misses 4,724 std cells, which is how this
# was found. Wind uses 3 for both.
VARIABLES = {
    'total_rainfall_rate': ('precipitation', MS_TO_MM_H, PRECIP_DECIMALS, 6, True),
    'u_wind':              ('wind_u_10m',    1.0,  VALUE_DECIMALS, VALUE_DECIMALS, False),
    'v_wind':              ('wind_v_10m',    1.0,  VALUE_DECIMALS, VALUE_DECIMALS, False),
}

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class ConversionError(RuntimeError):
    """Raised when a file does not look the way this script requires."""


def lead_hours(filename):
    """Lead from the filename's `PT<H>H<M>M`, or None. Verified against the file."""
    match = LEAD_IN_NAME.search(Path(filename).name)
    if not match:
        return None
    hours, minutes = int(match.group(1)), int(match.group(2))
    if minutes:
        # Nothing loaded has a sub-hourly lead and `forecast_hour` is an integer
        # column, so a non-zero minute would be silently truncated.
        raise ConversionError(
            f'{Path(filename).name}: lead is {hours}h{minutes:02d}m, and the '
            f'database stores whole hours only')
    return hours


def read_field(path):
    """(values, lats, lons, db_variable, init_time, lead, factor, decimals, drop_zero)."""
    try:
        import netCDF4 as nc
    except ImportError:                                # pragma: no cover
        sys.exit('netCDF4 is required to read source files: '
                 'conda install -c conda-forge netcdf4')

    with nc.Dataset(path, 'r') as ds:
        found = [n for n in ds.variables if n in VARIABLES]
        if len(found) != 1:
            raise ConversionError(
                f'{Path(path).name}: expected exactly one of '
                f'{sorted(VARIABLES)}, found {found or "none"}')
        name = found[0]
        db_variable, factor, decimals, std_decimals, drop_zero = VARIABLES[name]

        var = ds.variables[name]
        if set(var.dimensions) != {'realization', 'latitude', 'longitude'}:
            raise ConversionError(
                f'{Path(path).name}: {name} has dimensions {var.dimensions}, '
                f'expected realization/latitude/longitude')
        order = [var.dimensions.index(d)
                 for d in ('realization', 'latitude', 'longitude')]
        values = np.transpose(np.asarray(var[:]), order)

        lats = np.asarray(ds.variables['latitude'][:], dtype=np.float64)
        lons = np.asarray(ds.variables['longitude'][:], dtype=np.float64)
        # A no-op on this data: UKMO longitudes are already signed. Kept so the
        # three converters read the same way, and harmless because a signed
        # value is never > 180.
        lons = np.where(lons > 180.0, lons - 360.0, lons)

        init_time = lead = None
        if 'forecast_reference_time' in ds.variables:
            init_time = EPOCH + timedelta(
                seconds=float(np.asarray(ds.variables['forecast_reference_time'][:])))
        if 'forecast_period' in ds.variables:
            # SECONDS, unlike the `step` in hours the other two carry.
            lead = float(np.asarray(ds.variables['forecast_period'][:])) / 3600.0

    if values.shape[1:] != (lats.size, lons.size):
        raise ConversionError(
            f'{Path(path).name}: field is {values.shape} but the grid is '
            f'{lats.size}x{lons.size}')
    values = np.where(np.abs(values) >= SENTINEL, np.nan, values)
    return (values, lats, lons, db_variable, init_time, lead, factor, decimals,
            std_decimals, drop_zero)


def output_stem(init_time, hour, db_variable):
    """The JSON basename, from the verified initialisation and lead.

    Built rather than copied, for the reason `convert_gefs.output_stem` spells
    out: the loaders parse `-(\\d+)h-` and `load_to_postgres.py` defaults a
    missed match to **hour 0**. A UKMO source name carries the *valid* time, so
    reusing it would also bake the wrong date into the filename.
    """
    if init_time is None:
        raise ConversionError(
            'cannot name the output without an initialisation time: the file '
            'has no `forecast_reference_time`')
    return f'conus_east_{init_time:%Y%m%d%H%M%S}-{hour}h-ukmo_{db_variable}'


def _points(field, lats, lons, factor, decimals, drop_zero):
    out = []
    for i in range(lats.size):
        lat = round(float(lats[i]), COORD_DP)
        row = field[i]
        for j in range(lons.size):
            value = float(row[j])
            if np.isnan(value):
                continue
            if drop_zero and value == 0:
                continue
            out.append({'lat': lat,
                        'lon': round(float(lons[j]), COORD_DP),
                        'value': round(value * factor, decimals)})
    return out


def ensemble_stats(values, lats, lons, factor, decimals, std_decimals, drop_zero):
    """Mean and std, std restricted to the cells the mean kept.

    Same coupling as the other two converters: the loader applies `std` with an
    `UPDATE` keyed on the statistics row, so a std without a mean is discarded
    in silence. float32 preserved.
    """
    mean_records = _points(np.nanmean(values, axis=0), lats, lons,
                           factor, decimals, drop_zero)
    keep = {(r['lat'], r['lon']) for r in mean_records}
    std_records = [r for r in _points(np.nanstd(values, axis=0), lats, lons,
                                      factor, std_decimals, False)
                   if (r['lat'], r['lon']) in keep]
    return mean_records, std_records


def convert_file(path, out_dir, write_stats=True):
    (values, lats, lons, db_variable, init_time, lead,
     factor, decimals, std_decimals, drop_zero) = read_field(path)
    hour = lead_hours(path)

    if hour is not None and lead is not None and abs(lead - hour) > 1e-6:
        raise ConversionError(
            f'{Path(path).name}: filename says PT{hour:04d}H but '
            f'forecast_period says {lead:g} h. The name is not the authority.')
    if hour is None:
        hour = int(round(lead)) if lead is not None else None
    if hour is None:
        raise ConversionError(f'{Path(path).name}: no lead time in the name or the file')

    stem = output_stem(init_time, hour, db_variable)
    written = {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def dump(suffix, records):
        target = out_dir / f'{stem}_{suffix}.json'
        with open(target, 'w') as handle:
            json.dump(records, handle)
        written[target.name] = len(records)

    # `realization` is already 0-based and matches the database, so the array
    # index is the member number without adjustment — unlike AIFS.
    for member in range(values.shape[0]):
        dump(f'member_{member:02d}',
             _points(values[member], lats, lons, factor, decimals, drop_zero))
    if write_stats:
        mean_records, std_records = ensemble_stats(values, lats, lons, factor,
                                                   decimals, std_decimals, drop_zero)
        dump('mean', mean_records)
        dump('std', std_records)
    return written, init_time, hour, db_variable


def convert_folder(source, out_dir, write_stats=True):
    files = sorted(Path(source).glob('*.nc'),
                   key=lambda p: (lead_hours(p) is None, lead_hours(p) or 0))
    if not files:
        raise ConversionError(f'no .nc files in {source}')

    totals = {'files': 0, 'records': 0}
    inits, variables, hours = {}, set(), []
    print(f'{len(files)} file(s) in {source}')
    for path in files:
        written, init_time, hour, db_variable = convert_file(path, out_dir, write_stats)
        if init_time is not None:
            inits.setdefault(init_time, []).append(path.name)
        variables.add(db_variable)
        hours.append(hour)
        totals['files'] += 1
        totals['records'] += sum(written.values())
        if totals['files'] % 25 == 0 or totals['files'] == len(files):
            print(f'  +{hour:>4}h  {totals["files"]}/{len(files)} files, '
                  f'{totals["records"]:>9,} records', flush=True)

    if len(inits) > 1:
        raise ConversionError(
            'this directory holds more than one initialisation time: '
            + '; '.join(f'{t:%Y-%m-%d %H:%MZ} ({len(v)} file(s))'
                        for t, v in inits.items()))
    if len(variables) > 1:
        raise ConversionError(f'mixed variables in one directory: {sorted(variables)}')

    print(f'\nwrote {totals["records"]:,} records from {totals["files"]} file(s) '
          f'to {out_dir}')
    print(f'variable: {variables.pop()}   lead times: {min(hours)}-{max(hours)}h '
          f'({len(set(hours))} distinct)')
    if inits:
        (init,) = inits
        print(f'\n*** INITIALISATION TIME, READ FROM THE FILES: '
              f'{init:%Y-%m-%d %H:%M}Z ***')
        print(f'    Load with init_time="{init:%Y-%m-%d %H:%M:%S}".')
        print(f'    NOTE: UKMO filenames carry the VALID time, not this. '
              f'See NEXT_STEPS.md §20.')
    return totals


def verify(source, variable, init_time=None, limit_hours=None):
    """Compare against rows already in the database. No divisor: UKMO is unscaled."""
    import os

    import psycopg2
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', 5432),
        dbname=os.getenv('DB_NAME', 'weave_weather'),
        user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'))
    cur = conn.cursor()

    files = sorted(Path(source).glob('*.nc'), key=lambda p: lead_hours(p) or 0)
    if limit_hours:
        files = [p for p in files if lead_hours(p) in limit_hours]

    where_run = 'and r.initialization_time = %s' if init_time else ''
    rows = 0
    bad_slices, bad_stats = [], []
    file_init = None

    for path in files:
        (values, lats, lons, db_variable, init_from_file, _,
         factor, decimals, std_decimals, drop_zero) = read_field(path)
        file_init = init_from_file or file_init
        hour = lead_hours(path)
        args = [variable, hour] + ([init_time] if init_time else [])
        cur.execute(f"""
            select fd.ensemble_member, fd.latitude, fd.longitude, fd.value
            from forecast_data fd
            join forecast_runs r on r.run_id = fd.run_id
            join models m on m.model_id = r.model_id
            join variables v on v.variable_id = fd.variable_id
            where m.model_name = 'UKMO' and v.variable_name = %s
              and fd.forecast_hour = %s and fd.ensemble_member is not null
              {where_run}""", args)
        db = {}
        for member, lat, lon, value in cur.fetchall():
            db.setdefault(member, {})[(round(lat, COORD_DP), round(lon, COORD_DP))] = value

        for member in range(values.shape[0]):
            expected = {(r['lat'], r['lon']): r['value']
                        for r in _points(values[member], lats, lons,
                                         factor, decimals, drop_zero)}
            got = db.get(member, {})
            rows += len(expected)
            missing = set(expected) - set(got)
            extra = set(got) - set(expected)
            differs = sum(1 for k in set(expected) & set(got)
                          if abs(expected[k] - got[k]) > 1e-9)
            if missing or extra or differs:
                bad_slices.append((hour, member, len(missing), len(extra), differs))

        mean_records, std_records = ensemble_stats(values, lats, lons, factor,
                                                   decimals, std_decimals, drop_zero)
        exp_mean = {(r['lat'], r['lon']): r['value'] for r in mean_records}
        exp_std = {(r['lat'], r['lon']): r['value'] for r in std_records}
        cur.execute(f"""
            select es.latitude, es.longitude, es.mean_value, es.std_dev
            from ensemble_statistics es
            join forecast_runs r on r.run_id = es.run_id
            join models m on m.model_id = r.model_id
            join variables v on v.variable_id = es.variable_id
            where m.model_name = 'UKMO' and v.variable_name = %s
              and es.forecast_hour = %s {where_run}""", args)
        dbs = {(round(a, COORD_DP), round(b, COORD_DP)): (c, d)
               for a, b, c, d in cur.fetchall()}
        bad_m = sum(1 for k in exp_mean
                    if k not in dbs or abs(exp_mean[k] - dbs[k][0]) > 1e-9)
        bad_s = sum(1 for k in exp_std
                    if k not in dbs or dbs[k][1] is None
                    or abs(exp_std[k] - dbs[k][1]) > 1e-9)
        if set(exp_mean) != set(dbs) or bad_m or bad_s:
            bad_stats.append((hour, len(set(exp_mean) ^ set(dbs)), bad_m, bad_s))

        sys.stdout.write(f'\r  +{hour:>4}h  rows {rows:,}   ')
        sys.stdout.flush()
    print()
    conn.close()

    print(f'rows reproduced: {rows:,}')
    print(f'slices differing: {len(bad_slices)}')
    for row in bad_slices[:5]:
        print(f'   hour {row[0]} member {row[1]}: {row[2]} missing, {row[3]} extra, '
              f'{row[4]} differ')
    print(f'stat hours differing: {len(bad_stats)}')
    for row in bad_stats[:5]:
        print(f'   hour {row[0]}: {row[1]} one-sided, {row[2]} mean, {row[3]} std')

    if file_init and init_time and str(init_time)[:10] != f'{file_init:%Y-%m-%d}':
        print(f'\n*** THE LABEL AND THE DATA DISAGREE: these rows are stored under '
              f'{str(init_time)[:10]} and the files say {file_init:%Y-%m-%d}. ***')

    ok = not bad_slices and not bad_stats
    print('\nVERIFIED — reproduces those rows exactly' if ok
          else '\nDID NOT reproduce those rows')
    return ok


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Convert UKMO ensemble NetCDF to the JSON the WEAVE loaders read.',
        epilog='UKMO filenames carry the VALID time; the initialisation comes from '
               'forecast_reference_time and is printed.')
    parser.add_argument('--source', required=True)
    parser.add_argument('--out')
    parser.add_argument('--no-stats', action='store_true')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--verify-init-time',
                        help='the init_time those rows are stored under, which is '
                             'not necessarily the one in the files')
    parser.add_argument('--variable', default='wind_u_10m',
                        help='database variable name for --verify')
    parser.add_argument('--hours', type=int, nargs='*')
    args = parser.parse_args(argv)

    if args.verify:
        return 0 if verify(args.source, args.variable,
                           init_time=args.verify_init_time,
                           limit_hours=set(args.hours) if args.hours else None) else 1
    if not args.out:
        parser.error('--out is required unless --verify is given')
    convert_folder(args.source, args.out, write_stats=not args.no_stats)
    return 0


if __name__ == '__main__':
    sys.exit(main())
