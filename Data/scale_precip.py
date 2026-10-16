#!/usr/bin/env python
"""Scale converted AIFS/GEFS precipitation JSON from mm per record to mm/h.

Where this sits in the pipeline
-------------------------------
    convert_aifs.py / convert_gefs.py  ->  [THIS SCRIPT]  ->  load_to_postgres.py

UKMO precipitation and every wind component skip it: `convert_ukmo.py` already
emits mm/h, and wind is instantaneous, so there is no window to divide by.

This is the stage that used to live outside the repository, as
`Data_convert_weave/"aifs react.py"`. Every converter told the reader to run it
next and nothing here contained it, so the pipeline could not be rebuilt from a
clone. The two rules it has carried over its life are both reproduced here, by
name, because both are in the database.

The two rules
-------------
`flat` (the default) divides every record by one number per model: AIFS 6 h,
GEFS 3 h. This is what `run_registry.DECLARED` assumes, so a run scaled this
way needs no registry step beyond the usual `--backfill`.

`per-window` divides each record by the hours it actually covers. For AIFS
that is still 6 h. AIFS is a running total since initialisation, emitted
6-hourly, and the reader differences consecutive records, so
`C(h)/6 - C(h-6)/6 == (C(h) - C(h-6))/6` is exactly the mean rate over that
6 h. For GEFS it is 3 h at `h%6==3` and 6 h at `h%6==0`, because NCEP resets
the bucket every 6 h and the 6-hour record contains the 3-hour one.

**Both rules give identical scores**, provided the registry is told which one
was used (`NEXT_STEPS.md` §22). Scoring undoes `flat` for GEFS with
`period / divisor`, and treats `per-window` data, labelled `rate`, as already
a rate. **A mislabelled run is wrong by up to 2x**: GEFS per-window data
recorded as `scaled, 3` reads as a 24% better MAE than it has, which once made
GEFS look like the best model. So `per-window` GEFS must be registered `rate`.
The script prints the exact command for that.

How the loaded runs were produced (measured from the stored values)
-------------------------------------------------------------------
    AIFS 2025-09-08 00Z    flat, ÷6, 3 decimals
    AIFS 2025-09-08 06Z    ÷6, 4 decimals   (rule irrelevant for AIFS)
    AIFS 2025-09-16 00Z    ÷6, 4 decimals
    GEFS 2025-09-16 00Z    flat, ÷3, 3 decimals   (re-scaled to the legacy rule, §22)

Decimals change stored values in the last digit and nothing measurable in the
scores. The default is 4. Pass `--decimals 3` to reproduce the 3-decimal runs
bit for bit.

Guards
------
* A file whose forecast hour cannot be parsed from its name (`-<h>h-`, the
  pattern `load_to_postgres.py` reads) is skipped and listed, never divided by
  a guess.
* The output directory gets a `SCALED.json` marker. A source directory holding
  one is refused, because scaling twice divides by the window twice and nothing
  downstream could tell.
* `--source` and `--out` must differ.

Usage
-----
    python scale_precip.py --model AIFS --source json_aifs --out json_aifs_scaled
    python scale_precip.py --model GEFS --source json_gefs --out json_gefs_scaled
    python scale_precip.py --model GEFS --rule per-window --source ... --out ...
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import run_registry

MODELS = ('AIFS', 'GEFS')
FLAT, PER_WINDOW = 'flat', 'per-window'
RULES = (FLAT, PER_WINDOW)

# The one divisor per model the `flat` rule applies, and which
# `run_registry.DECLARED` records as `scaled, <divisor>`.
FLAT_DIVISOR_HOURS = {'AIFS': 6.0, 'GEFS': 3.0}

DEFAULT_DECIMALS = 4
MARKER = 'SCALED.json'


class ScalingError(Exception):
    """Raised instead of writing output that would be scaled wrongly."""


def record_window_hours(model, forecast_hour, rule=FLAT):
    """Hours to divide the record ending at `forecast_hour` by."""
    model = model.upper()
    if model not in MODELS:
        raise ScalingError(f'{model} has no precipitation scaling rule; only '
                           f'{", ".join(MODELS)} pass through this stage')
    if rule not in RULES:
        raise ScalingError(f'unknown rule {rule!r}; expected one of {RULES}')
    if rule == FLAT or model == 'AIFS':
        return FLAT_DIVISOR_HOURS[model]
    # GEFS per-window: the bucket resets every 6 h, so 0-3, 0-6, 6-9, 6-12, ...
    return 3.0 if forecast_hour % 6 == 3 else 6.0


def registry_convention(model, rule=FLAT):
    """The (export_convention, export_divisor_h) the registry must hold."""
    model = model.upper()
    if model == 'GEFS' and rule == PER_WINDOW:
        return run_registry.RATE, None
    return run_registry.SCALED, FLAT_DIVISOR_HOURS[model]


def forecast_hour_from_filename(filename):
    """Same pattern `load_to_postgres.py` parses, so the two cannot disagree."""
    match = re.search(r'-(\d+)h-', filename)
    return int(match.group(1)) if match else None


def scale_records(records, divisor, decimals=DEFAULT_DECIMALS):
    """One file's `[{lat, lon, value}]`, with each value divided and rounded."""
    return [{'lat': r['lat'], 'lon': r['lon'],
             'value': round(r['value'] / divisor, decimals)}
            for r in records]


def scale_directory(source, out, model, rule=FLAT, decimals=DEFAULT_DECIMALS):
    """Scale every `*.json` in `source` into `out`. Returns a summary dict."""
    source, out = Path(source), Path(out)
    model = model.upper()
    record_window_hours(model, 0, rule)          # validates model and rule
    if source.resolve() == out.resolve():
        raise ScalingError('--source and --out are the same directory; '
                           'scaling in place would leave no unscaled copy')
    if (source / MARKER).exists():
        raise ScalingError(f'{source} holds {MARKER}: it is already scaled, and '
                           f'scaling it again would divide by the window twice')
    files = sorted(p for p in source.glob('*.json') if p.name != MARKER)
    if not files:
        raise ScalingError(f'no JSON files in {source}')

    out.mkdir(parents=True, exist_ok=True)
    divisors, skipped = Counter(), []
    for path in files:
        hour = forecast_hour_from_filename(path.name)
        if hour is None:
            skipped.append((path.name, 'no forecast hour (-<h>h-) in the filename'))
            continue
        divisor = record_window_hours(model, hour, rule)
        with open(path) as handle:
            records = json.load(handle)
        with open(out / path.name, 'w') as handle:
            json.dump(scale_records(records, divisor, decimals), handle)
        divisors[(hour % 6, divisor)] += 1

    convention, export_divisor = registry_convention(model, rule)
    summary = {
        'model': model, 'rule': rule, 'decimals': decimals,
        'source': str(source), 'files_written': sum(divisors.values()),
        'divisors': {f'h%6=={m}': {'divide_by_h': d, 'files': n}
                     for (m, d), n in sorted(divisors.items())},
        'skipped': [{'file': f, 'reason': why} for f, why in skipped],
        'registry': {'export_convention': convention,
                     'export_divisor_h': export_divisor},
    }
    with open(out / MARKER, 'w') as handle:
        json.dump(summary, handle, indent=2)
    return summary


def report(summary):
    print(f"{summary['model']}: {summary['files_written']} files scaled "
          f"({summary['rule']}, {summary['decimals']} decimals)")
    for window, entry in summary['divisors'].items():
        print(f"  {window}: ÷{entry['divide_by_h']:g} h  ({entry['files']} files)")
    if summary['skipped']:
        print(f"\nSKIPPED {len(summary['skipped'])} file(s), NOT written:")
        for entry in summary['skipped'][:10]:
            print(f"  {entry['file']}: {entry['reason']}")
    convention = summary['registry']['export_convention']
    if convention == run_registry.RATE:
        print('\nREGISTRY STEP REQUIRED. This is per-window GEFS, and the registry '
              'would otherwise record it as `scaled, 3`, which halves every 6-hour '
              'bucket a second time at scoring. After loading, regridding and '
              '`migrate_init_time.py`, run:\n'
              f"  python run_registry.py --record --model {summary['model']} "
              f"--variable precipitation --init-time '<init>' --convention rate")
    else:
        print(f"\nRegistry: `{convention}, {summary['registry']['export_divisor_h']:g}`, "
              f"which is what run_registry.DECLARED assumes; `run_registry.py "
              f"--backfill` after `migrate_init_time.py` records it.")
    print('\nNext: load_to_postgres.py on the output directory.')


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--model', required=True, type=str.upper, choices=MODELS)
    parser.add_argument('--source', required=True, help='converted JSON directory')
    parser.add_argument('--out', required=True, help='directory to write scaled JSON to')
    parser.add_argument('--rule', default=FLAT, choices=RULES,
                        help='flat (default; what every loaded run used) or per-window')
    parser.add_argument('--decimals', type=int, default=DEFAULT_DECIMALS,
                        help=f'decimals kept (default {DEFAULT_DECIMALS}; the '
                             f'3-decimal runs were scaled with 3)')
    args = parser.parse_args(argv)
    try:
        summary = scale_directory(args.source, args.out, args.model,
                                  args.rule, args.decimals)
    except ScalingError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    report(summary)
    return 0 if not summary['skipped'] else 2


if __name__ == '__main__':
    sys.exit(main())
