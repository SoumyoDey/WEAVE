#!/usr/bin/env python
"""Convert AIFS ensemble NetCDF into the JSON the WEAVE loaders read.

This is the stage that did not exist. `Data_convert_weave/React.py` handles UKMO
only, and `Data_convert_weave/"aifs react.py"` — despite its name — is JSON to
JSON rescaling that sits *downstream* of this step. The AIFS run already in the
database was converted off-machine by something that was never kept, which is
why a second AIFS run could not be loaded at all. See `NEXT_STEPS.md` §14.

It lives in the repository, unlike the converters it joins, for the reason
`load_observations.py` does: a stage kept outside the tree is a stage that gets
lost.

Where this sits in the pipeline
-------------------------------
    AIFS NetCDF  ->  [THIS SCRIPT]  ->  json_data_aifs_ensemble/
                                            |
                                            v
                            Data_convert_weave/"aifs react.py"   (divides by 6)
                                            |
                                            v
                                     json_data_aifs_ensemble_scaled/
                                            |
                                            v
                                     load_to_postgres.py

**This script does not divide by anything.** AIFS `tp` is a running total since
initialisation, and turning that into a rate is the next stage's job. Dividing
here would double-correct, silently, and the only sign would be precipitation
scores that are uniformly a sixth of what they should be.

Conventions, every one of them measured against the loaded run
--------------------------------------------------------------
Each cost a wrong answer if guessed, so each is asserted rather than assumed:

* `tp(number, latitude, longitude)`, shape (50, 81, 81). **The grid is square,
  so a transposed read is completely silent** — the same trap IMERG set in
  `load_observations.py`. Axes are therefore resolved by dimension *name*, never
  by position, and `test_convert_aifs.py` uses a deliberately non-square grid.

* **The ensemble member is the array index, not the `number` variable.** `number`
  runs 1..50; the database holds 0..49. Member 0 is `number` 1. Writing the
  `number` value into the filename would shift every member by one and could not
  be seen in any aggregate.

* **Units are already mm.** `tp` is `kg m**-2`, which over water is millimetres.
  UKMO's `total_rainfall_rate` is m/s and needs x3.6e6; applying that here would
  inflate precipitation by six orders of magnitude.

* **Precipitation below 0.01 mm is dropped** (`MIN_PRECIP_MM`). This is not a
  tidy-up, it is the loaded run's convention: of 4,212 non-zero cells in the
  first hour of member 0, the database holds 4,001, and the boundary is exact —
  everything dropped is <= 0.00977 mm, everything kept is >= 0.01074 mm, with no
  overlap. It is also why no stored value is 0.001: 0.01 mm over 6 h rounds to
  0.002 mm/h, and that is the observed minimum.

* **Values round to 3 decimals in mm, with Python's `round`.** Not numpy's:
  `np.round` disagrees on ~6% of cells. The scaling stage then rounds again, and
  `round(round(tp, 3) / 6, 3)` reproduces the loaded table exactly where
  `round(tp / 6, 3)` misses 343 of 4,001 cells in a single slice.

* **`mean` and `std` stay in float32.** `np.mean`/`np.std` preserve the input
  dtype, and widening to float64 first moves the last digit. This is the mirror
  image of `load_observations.py`, where float64 was *required* for `hypot`; the
  rule is not "use float64", it is "use what produced the stored numbers".

* **`std` is the population standard deviation** (`ddof=0`, numpy's default).
  `ddof=1` mismatches 362,979 of 378,737 rows, so the two are easy to tell
  apart once compared — and impossible to tell apart by reading either script.

* **The `std` file is written only where `mean` survives the threshold.**
  `load_to_postgres.py` loads `std` with an `UPDATE` keyed on the statistics
  row, so a `std` value at a cell with no `mean` is silently discarded. Writing
  them anyway, as `React.py` does, cannot change the database and only makes the
  file bigger.

* **Latitude is stored ascending (25 -> 45)** even though the variable carries
  `stored_direction = "decreasing"`. The attribute describes the GRIB it came
  from, not this array. Rows are emitted in file order and the attribute is
  ignored; reordering on the strength of it would flip the domain.

* **Hour 0 legitimately produces an empty precipitation file.** A cumulative
  total is zero at initialisation, so no cell reaches 0.01 mm — measured, not
  assumed: 0 of 6,561. The database has no hour 0 for AIFS precipitation and
  that is correct, not a gap.

Verified how
------------
Reproducing the loaded AIFS 2025-09-08 00Z run, through the legacy `/6` and
3-decimal scaling, gives **all 17,915,148 member rows** and **all 378,737
mean/std rows** exactly: 3,000 of 3,000 (hour, member) slices agree cell-for-
cell and value-for-value, with no cell in the database absent from the source
and none in the source absent from the database. `--verify` re-runs that
comparison.

Byte-identical output is weak evidence on its own — a silent fallback produces
it too — so the conventions above were each established by *perturbing* them and
confirming the reproduction breaks. That is what makes the 0.01 mm threshold and
the double rounding findings rather than guesses.

Wind, and the wrong-run defect it uncovered
-------------------------------------------
Wind now reproduces exactly too — all 61 hours of both components, members and
statistics — but only after the field in the database was **replaced**, because
what was there had been loaded from the wrong forecast run.

The symptom was that `wind_u10`/`wind_v10` had the identical file layout and the
stored table had exactly the shape this script produces (61 hours x 50 members x
6,561 cells = 20,011,050 rows, every cell kept, zeros and negatives included, 3
decimals) while every *value* differed: at `2025-09-08 00Z` +120h cell
(25.0, -85.0) the database held -5.567 where the source has -4.050. No member
index, spatial shift, ensemble mean or ensemble std accounted for it — each was
tried, and the closest was ~1.8 mean absolute error where a real match is
~0.0005.

**It was the `2025-09-16` run filed as `2025-09-08`.** Found by matching the
stored field's mean and standard deviation against every date, cycle and member
in the tree, then confirmed cell-for-cell against the preserved rows. Since
observations only cover 2025-09-08, every AIFS wind score had been pairing a
forecast with truth from eight days *before* it was initialised. Replacing it
moved domain-aggregate MAE 2.2386 -> 0.6595, RMSE 2.4754 -> 0.7838 and CRPS
1.7322 -> 0.5093. The superseded rows are kept outside the repo as
`weave_aifs_wind_prev_20260928.sql.gz`.

**The lesson for this script**: the cell set matching perfectly proved only that
the *grid* was right. Shape agreement is not provenance, and a field can be a
real forecast, correctly converted, and still be the wrong forecast. Only
matching values against a named source settles it, which is what `--verify`
does.

**`--verify` applies the divisor only to accumulations.** Wind is stored as
exported — the registry records it `unscaled` — so dividing it by 6 made every
value differ while the cell set matched exactly, which looks exactly like bad
data and is not.

Usage
-----
    # one cycle of precipitation
    python convert_aifs.py \
        --source /projects/k.aggarwal/WEAVE/AIFS/regional_data/conus_east/precipitation/20250908/init_06/pf \
        --out ./json_data_aifs_ensemble

    # check this script against the run already loaded
    python convert_aifs.py --source <2025-09-08 init_00 pf dir> --verify
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np


# Cells below this are not written. The loaded run's boundary, measured: every
# dropped cell is <= 0.00977 mm and every kept one >= 0.01074 mm.
MIN_PRECIP_MM = 0.01

# Decimals kept in the JSON, in the source's own units. The scaling stage rounds
# again; raising this here changes the stored numbers in the last digit and so
# makes a new run inconsistent with the loaded one rather than more accurate.
VALUE_DECIMALS = 3

# The legacy scaling stage, reproduced for --verify only. Real conversions go
# through `aifs react.py`, which owns this divisor.
LEGACY_DIVISOR_HOURS = 6.0
LEGACY_DECIMALS = 3

# Coordinates are matched against the database at this precision, which is what
# the stored grid carries. `load_observations.py` lost 2.19M rows to getting the
# equivalent number wrong, so it is named rather than inlined.
COORD_DP = 4

# What the loaders and the scaling stage both parse. Defined once here so this
# script cannot drift away from `load_to_postgres.extract_metadata_from_filename`.
HOUR_IN_NAME = re.compile(r'-(\d+)h-')

# Anything at or above this is a GRIB missing-value sentinel (tp carries
# 3.40282346638529e+38) rather than a reading.
SENTINEL = 1e30

# Variables that are accumulations, and so get the threshold. Wind is
# instantaneous: a 0 m/s component is a real measurement and a negative one is
# half the domain, so thresholding it would delete data.
ACCUMULATED = ('tp',)


class ConversionError(RuntimeError):
    """Raised when a file does not look the way this script requires."""


def forecast_hour(filename):
    """Lead time from the filename, or None if it does not carry one."""
    match = HOUR_IN_NAME.search(filename)
    return int(match.group(1)) if match else None


def read_field(path):
    """Return (values, lats, lons, variable_name) with axes ordered (member, lat, lon).

    Axes are located by dimension name. The domain is square, so an index slip
    here produces a plausible field that is wrong everywhere and flagged by
    nothing.
    """
    # Imported here, not at module scope, so the conventions in this file can be
    # unit-tested where netCDF4 is not installed — `load_observations.py` defers
    # xarray for the same reason.
    try:
        import netCDF4 as nc
    except ImportError:                                # pragma: no cover
        sys.exit('netCDF4 is required to read source files: '
                 'conda install -c conda-forge netcdf4')

    with nc.Dataset(path, 'r') as ds:
        names = [n for n, v in ds.variables.items()
                 if v.dimensions and set(v.dimensions) >= {'number', 'latitude', 'longitude'}]
        if len(names) != 1:
            raise ConversionError(
                f'{Path(path).name}: expected exactly one (number, latitude, longitude) '
                f'variable, found {names or "none"}')
        name = names[0]
        var = ds.variables[name]

        order = [var.dimensions.index(d) for d in ('number', 'latitude', 'longitude')]
        values = np.transpose(np.asarray(var[:]), order)

        lats = np.asarray(ds.variables['latitude'][:], dtype=np.float64)
        lons = np.asarray(ds.variables['longitude'][:], dtype=np.float64)

    if values.shape[1:] != (lats.size, lons.size):
        raise ConversionError(
            f'{Path(path).name}: field is {values.shape} but the grid is '
            f'{lats.size}x{lons.size}')

    # A GRIB sentinel left in place would be written out as rainfall of 3.4e38.
    values = np.where(np.abs(values) >= SENTINEL, np.nan, values)
    return values, lats, lons, name


def _points(field, lats, lons, threshold, decimals):
    """Grid to records, dropping NaN and anything under `threshold`.

    `field` stays in its source dtype: `round(float(x), n)` on a float32 and on
    its float64 widening are not always the same number in the last digit, and
    the stored run was produced from float32.
    """
    out = []
    for i in range(lats.size):
        lat = round(float(lats[i]), COORD_DP)
        row = field[i]
        for j in range(lons.size):
            value = float(row[j])
            if np.isnan(value):
                continue
            if threshold is not None and value < threshold:
                continue
            out.append({'lat': lat,
                        'lon': round(float(lons[j]), COORD_DP),
                        'value': round(value, decimals)})
    return out


def convert_file(path, out_dir, threshold=None, decimals=VALUE_DECIMALS,
                 write_stats=True, indent=None):
    """Convert one NetCDF file into member, mean and std JSON files.

    Returns a dict of output filename -> record count.
    """
    values, lats, lons, variable = read_field(path)
    stem = Path(path).stem

    if threshold is None and variable in ACCUMULATED:
        threshold = MIN_PRECIP_MM

    written = {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def dump(suffix, records):
        target = out_dir / f'{stem}_{suffix}.json'
        with open(target, 'w') as handle:
            json.dump(records, handle, indent=indent)
        written[target.name] = len(records)

    # Member index, not the `number` variable: `number` is 1-based and the
    # database is 0-based.
    for member in range(values.shape[0]):
        dump(f'member_{member:02d}',
             _points(values[member], lats, lons, threshold, decimals))

    if write_stats:
        mean_records, std_records = ensemble_stats(values, lats, lons, threshold, decimals)
        dump('mean', mean_records)
        dump('std', std_records)

    return written


def ensemble_stats(values, lats, lons, threshold, decimals):
    """Mean and std records, the std restricted to the cells the mean kept.

    `std` is filtered by the mean's surviving *keys* rather than by re-applying
    the threshold to a numpy mask. Two reasons, and the second is why this is
    not merely tidier:

    1. `load_to_postgres.py` loads `std` with an `UPDATE` keyed on the
       statistics row, so a `std` at a cell with no `mean` is discarded in
       silence. One filter cannot disagree with itself.

    2. **`mask = mean < threshold` and `float(mean) < threshold` disagree at
       exactly the threshold.** numpy casts the Python float down to the array's
       float32, where `0.01` is exactly representable as the same bit pattern;
       in float64 that same float32 is 0.00999999977, which is *below* 0.01. One
       cell of the loaded run — (44.75, -83.0) at +6h — sits precisely there, so
       the numpy mask kept a cell the stored run drops. Still true under numpy
       2.4's NEP 50 promotion, which was checked rather than assumed.

    `np.nanmean`/`np.nanstd` preserve float32 and are bit-identical to
    `np.mean`/`np.std` on this data; the nan- forms are used so a fill value
    cannot poison a whole cell. `std` is the population deviation (`ddof=0`).
    """
    mean_records = _points(np.nanmean(values, axis=0), lats, lons, threshold, decimals)
    keep = {(r['lat'], r['lon']) for r in mean_records}
    std_records = [r for r in _points(np.nanstd(values, axis=0), lats, lons, None, decimals)
                   if (r['lat'], r['lon']) in keep]
    return mean_records, std_records


def convert_folder(source, out_dir, threshold=None, decimals=VALUE_DECIMALS,
                   write_stats=True):
    """Convert every NetCDF file in `source`, ordered by lead time."""
    files = sorted(Path(source).glob('*.nc'),
                   key=lambda p: (forecast_hour(p.name) is None, forecast_hour(p.name) or 0))
    if not files:
        raise ConversionError(f'no .nc files in {source}')

    unnamed = [p.name for p in files if forecast_hour(p.name) is None]
    if unnamed:
        # The loader defaults a missing hour to 0, which would pile every such
        # file onto the analysis time instead of failing.
        raise ConversionError(
            f'{len(unnamed)} file(s) carry no `-<N>h-` lead time, which the loader '
            f'would silently read as hour 0: {unnamed[:3]}')

    print(f'{len(files)} file(s) in {source}')
    totals = {'files': 0, 'records': 0, 'empty': []}
    for path in files:
        written = convert_file(path, out_dir, threshold, decimals, write_stats)
        totals['files'] += 1
        totals['records'] += sum(written.values())
        members = {k: v for k, v in written.items() if '_member_' in k}
        if members and not any(members.values()):
            totals['empty'].append(forecast_hour(path.name))
        print(f'  +{forecast_hour(path.name):>4}h  {len(written):3d} files, '
              f'{sum(written.values()):>8,} records', flush=True)

    print(f'\nwrote {totals["records"]:,} records from {totals["files"]} file(s) '
          f'to {out_dir}')
    if totals['empty']:
        print(f'hours with no member records: {totals["empty"]} — expected at hour 0 '
              f'for a cumulative field, since nothing has accumulated yet')
    print('\nNext: `aifs react.py` to divide by the 6 h emit interval, then '
          'load_to_postgres.py.')
    return totals


def verify(source, model='AIFS', variable='precipitation', init_time=None,
           divisor=LEGACY_DIVISOR_HOURS, limit_hours=None):
    """Compare this script's output against a run already in the database.

    Applies the legacy scaling (`/divisor` then round to 3) so the comparison is
    against what is stored, and reports cells present on one side only as well
    as values that differ — a count-only check would pass while every value was
    wrong.
    """
    import os

    import psycopg2
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', 5432),
        dbname=os.getenv('DB_NAME', 'weave_weather'),
        user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'))
    cur = conn.cursor()

    files = sorted(Path(source).glob('*.nc'), key=lambda p: forecast_hour(p.name) or 0)
    if limit_hours:
        files = [p for p in files if forecast_hour(p.name) in limit_hours]

    where_run = 'and r.initialization_time = %s' if init_time else ''
    member_rows = stat_rows = 0
    bad_slices, bad_stats = [], []

    for path in files:
        hour = forecast_hour(path.name)
        values, lats, lons, name = read_field(path)
        threshold = MIN_PRECIP_MM if name in ACCUMULATED else None
        # **Only accumulations were scaled on the way in.** Wind is stored as
        # exported — the registry records it `unscaled` — so dividing it here
        # made every value differ while the cell set matched exactly, which is
        # what a scaling error looks like and is easy to misread as bad data.
        effective_divisor = divisor if name in ACCUMULATED else 1.0

        def scaled(records, _d=effective_divisor):
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
            expected = scaled(_points(values[member], lats, lons, threshold, VALUE_DECIMALS))
            got = db.get(member, {})
            member_rows += len(expected)
            missing = set(expected) - set(got)
            extra = set(got) - set(expected)
            differs = sum(1 for k in set(expected) & set(got)
                          if abs(expected[k] - got[k]) > 1e-12)
            if missing or extra or differs:
                bad_slices.append((hour, member, len(missing), len(extra), differs))

        mean_records, std_records = ensemble_stats(values, lats, lons, threshold,
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

    cur.execute(f"""
        select count(*) from forecast_data fd
        join forecast_runs r on r.run_id = fd.run_id
        join models m on m.model_id = r.model_id
        join variables v on v.variable_id = fd.variable_id
        where m.model_name = %s and v.variable_name = %s
          and fd.ensemble_member is not null {where_run}""",
                [model, variable] + ([init_time] if init_time else []))
    db_members = cur.fetchone()[0]
    conn.close()

    print(f'member rows: reproduced {member_rows:,}, database holds {db_members:,}'
          f'{"" if limit_hours else "  equal: %s" % (member_rows == db_members)}')
    print(f'slices differing: {len(bad_slices)}')
    for row in bad_slices[:5]:
        print(f'   hour {row[0]} member {row[1]}: {row[2]} missing, {row[3]} extra, '
              f'{row[4]} values differ')
    print(f'stat hours differing: {len(bad_stats)}')
    for row in bad_stats[:5]:
        print(f'   hour {row[0]}: {row[1]} cells one-sided, {row[2]} mean, {row[3]} std')

    ok = not bad_slices and not bad_stats and (limit_hours or member_rows == db_members)
    print('\nVERIFIED — reproduces the loaded run exactly' if ok
          else '\nDID NOT reproduce the loaded run')
    return ok


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Convert AIFS ensemble NetCDF to the JSON the WEAVE loaders read.',
        epilog='This script does not divide by the emit interval; `aifs react.py` does.')
    parser.add_argument('--source', required=True,
                        help='directory of *.nc files for one variable and cycle')
    parser.add_argument('--out', help='output directory (required unless --verify)')
    parser.add_argument('--threshold', type=float, default=None,
                        help=f'drop values below this (default {MIN_PRECIP_MM} for '
                             f'accumulations, none for wind)')
    parser.add_argument('--decimals', type=int, default=VALUE_DECIMALS,
                        help=f'decimals kept in the JSON (default {VALUE_DECIMALS}, '
                             f'which is what the loaded run carries)')
    parser.add_argument('--no-stats', action='store_true',
                        help='skip the mean and std files')
    parser.add_argument('--verify', action='store_true',
                        help='compare against a run already in the database instead '
                             'of writing files')
    parser.add_argument('--init-time', help='restrict --verify to one initialisation')
    parser.add_argument('--variable', default='precipitation',
                        help='database variable name for --verify (default precipitation)')
    parser.add_argument('--hours', type=int, nargs='*',
                        help='restrict --verify to these lead times')
    args = parser.parse_args(argv)

    if args.verify:
        return 0 if verify(args.source, variable=args.variable,
                           init_time=args.init_time,
                           limit_hours=set(args.hours) if args.hours else None) else 1

    if not args.out:
        parser.error('--out is required unless --verify is given')

    probe = sorted(Path(args.source).glob('*.nc'))
    if probe:
        _, _, _, name = read_field(probe[0])
        if name not in ACCUMULATED:
            print(f'NOTE: {name} is not an accumulation, so no threshold is applied and '
                  f'no divisor belongs downstream — the registry records wind '
                  f'`unscaled`. Do not run this output through `aifs react.py`.\n')

    convert_folder(args.source, args.out, args.threshold, args.decimals,
                   write_stats=not args.no_stats)
    return 0


if __name__ == '__main__':
    sys.exit(main())
