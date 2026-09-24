#!/usr/bin/env python
"""The run registry: what is loaded, and how each run's export was produced.

Why this exists
---------------
`DATA_EXPANSION_DESIGN.md` phase 4 asks for an ingest that is scripted,
idempotent and **self-describing**, and gives the reason: the current pipeline
is manual and partly off-machine, "which is why the export conventions were so
hard to reconstruct". Reconstructing one cost days and produced
`SCALED_EXPORT_DIVISOR_HOURS`, a module constant that describes *the run that
happens to be loaded*.

A constant cannot describe two runs. The moment a second run is exported
differently, one of them is corrected with the other's divisor and every
precipitation score in it is wrong by a factor — silently, because nothing
downstream can tell. `forecast_run_registry` already carries `export_divisor_h`
per (model, variable, init_time); `migrate_init_time.py` created it and
backfilled it from that constant, with a comment saying moving it into data was
the point. What was missing is this module: something that **writes it at load
time** and **refuses to guess**.

Two things phase 4 asks for that the column alone could not give
------------------------------------------------------------------
**1. Telling "unscaled" apart from "unrecorded".** `export_divisor_h` is NULL
for UKMO precipitation because UKMO was never scaled — React.py converts its
native rate straight to mm/h — and NULL for a model nobody has declared yet.
Those are opposite situations that must not be treated alike, and a nullable
float cannot distinguish them. So the convention is named explicitly in
`export_convention`, and NULL there means nobody said, which is an error rather
than a default.

**2. Failing loudly** (phase 4, item 3). `metrics._increment_divisor` currently
returns `period` for any model it does not know, which reads as "unscaled" and
is indistinguishable from "we have never heard of this model". A new model
loaded without a declared convention would be scored as though it stored plain
amounts. `resolve_divisor` raises instead.

What this module does NOT do yet
--------------------------------
**Scoring still reads the constant**, not the registry. Moving it is a change
to every precipitation number in the app and belongs in its own step, measured
the way the UTC correction was. This module is the half that makes that
possible: the data is recorded correctly at load time first, so the switch is
a read-path change with nothing to backfill.

Usage
-----
    import run_registry as reg

    reg.ensure_schema(cur)
    reg.record(cur, 'AIFS', 'precipitation', init_time,
               n_members=50, hour_min=6, hour_max=360)
    reg.refresh_from_members(cur, init_time)     # counts and ranges from data
"""
import argparse
import os
import sys

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

DB_CONFIG = {
    'dbname':   os.environ.get('DB_NAME',     'weave_weather'),
    'user':     os.environ.get('DB_USER',     'k.aggarwal'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'host':     os.environ.get('DB_HOST',     'localhost'),
    'port':     int(os.environ.get('DB_PORT', 5432)),
}

TABLE = 'forecast_run_registry'

# The conventions, named. `SCALED` means the export already divided by a fixed
# number of hours and the divisor is needed to undo it; `UNSCALED` means the
# stored value is an amount or a native rate that needs no undoing.
SCALED   = 'scaled'
UNSCALED = 'unscaled'
CONVENTIONS = (SCALED, UNSCALED)


class UnknownConventionError(Exception):
    """Raised rather than assuming a convention for a run that declared none.

    Phase 4, item 3. The failure this prevents is quiet: an undeclared model
    scored as unscaled looks plausible and is wrong by whatever factor its
    export applied.
    """


# What is known about how each model's precipitation was exported, and why.
# This is the *default* used when a loader does not state the convention
# itself; the registry row is what scoring will eventually read, so a run that
# was made differently overrides this by recording its own.
#
# Wind is included and declared UNSCALED rather than left out. An earlier
# version omitted it, reasoning that instantaneous data has no window to divide
# by and therefore no convention — true, but it produced drift: the real
# database's backfill named wind `unscaled` while a freshly built fixture left
# it NULL, so `resolve_divisor` returned None against one and raised against
# the other. "Nothing was divided out" is a fact about wind, and saying it
# explicitly is what keeps the two databases answering the same question the
# same way.
DECLARED = {
    # React.py divided by a flat 6 h, which matches AIFS's 6-hourly records.
    ('AIFS', 'precipitation'): (SCALED, 6.0),
    # Divided by a flat 3 h. Correct for GEFS's h%6==3 buckets and wrong for its
    # h%6==0 buckets, which cover 6 h — hence the 2x correction at scoring time.
    # NEXT_STEPS.md's standing decision: GEFS will not be re-exported, so this
    # is permanent for *this* run. A re-export would record 6.0 for its own run
    # and leave this one alone, which is the entire point of per-run storage.
    ('GEFS', 'precipitation'): (SCALED, 3.0),
    # Never scaled: React.py converts the native rate (m/s) straight to mm/h.
    ('UKMO', 'precipitation'): (UNSCALED, None),
}
# Wind components, for every model: instantaneous, so nothing was divided out.
for _model in ('AIFS', 'GEFS', 'UKMO'):
    for _component in ('wind_u_10m', 'wind_v_10m'):
        DECLARED[(_model, _component)] = (UNSCALED, None)
del _model, _component


SCHEMA_ADDITIONS = f"""
ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS export_convention TEXT;
"""


def ensure_schema(cur):
    """Add what this module needs, idempotently.

    Additive only: `migrate_init_time.py` owns the table, and a loader should
    be able to run against a database that predates this column without a
    migration step of its own.
    """
    cur.execute(SCHEMA_ADDITIONS)


def declared_for(model_name, variable_name):
    """The declared convention for a model and variable, or None if undeclared."""
    return DECLARED.get((model_name, variable_name))


def record(cur, model_name, variable_name, init_time,
           n_members=None, hour_min=None, hour_max=None,
           convention=None, export_divisor_h=None):
    """Upsert one (model, variable, run) row.

    Idempotent on the natural key, which includes `init_time` — phase 4, item 1.
    Re-running a load updates the row rather than duplicating or failing, so the
    whole pipeline can be re-run without a cleanup step.

    The convention defaults to `DECLARED` and can be overridden per call, which
    is what lets a re-exported run record a different divisor from the one
    already loaded. Passing a `SCALED` convention with no divisor is refused:
    that combination says "something was divided out" without saying by what,
    which is exactly the state this module exists to prevent.
    """
    if convention is None and export_divisor_h is None:
        found = declared_for(model_name, variable_name)
        if found is not None:
            convention, export_divisor_h = found

    if convention is not None and convention not in CONVENTIONS:
        raise ValueError(f'unknown convention {convention!r}; '
                         f'expected one of {CONVENTIONS}')
    if convention == SCALED and export_divisor_h is None:
        raise ValueError(f'{model_name}/{variable_name}: convention is '
                         f'{SCALED!r} but no export_divisor_h was given')
    if convention == UNSCALED and export_divisor_h is not None:
        raise ValueError(f'{model_name}/{variable_name}: convention is '
                         f'{UNSCALED!r} but a divisor was given; an unscaled '
                         f'export has nothing to undo')

    cur.execute(f"""
        INSERT INTO {TABLE}
            (model_name, variable_name, init_time, n_members, hour_min,
             hour_max, export_divisor_h, export_convention)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (model_name, variable_name, init_time) DO UPDATE SET
            loaded_at         = now(),
            n_members         = COALESCE(EXCLUDED.n_members, {TABLE}.n_members),
            hour_min          = COALESCE(EXCLUDED.hour_min,  {TABLE}.hour_min),
            hour_max          = COALESCE(EXCLUDED.hour_max,  {TABLE}.hour_max),
            export_divisor_h  = EXCLUDED.export_divisor_h,
            export_convention = COALESCE(EXCLUDED.export_convention,
                                         {TABLE}.export_convention)
    """, (model_name, variable_name, init_time, n_members, hour_min,
          hour_max, export_divisor_h, convention))


def refresh_from_members(cur, init_time=None):
    """Fill counts and lead-time ranges from `regridded_forecast_member`.

    The measured half of the row: how many members and which lead times are
    actually present, rather than what the loader believed it wrote. Same
    derivation `migrate_init_time.py` used, kept here so a loader can call it
    instead of a migration being the only thing that has ever populated this.

    Scoped to one run when given one, so re-running a single load does not
    rewrite every other run's row.
    """
    where, params = '', ()
    if init_time is not None:
        where, params = 'WHERE init_time = %s', (init_time,)
    cur.execute(f"""
        INSERT INTO {TABLE}
            (model_name, variable_name, init_time, n_members, hour_min, hour_max)
        SELECT model_name, variable_name, init_time,
               COUNT(DISTINCT ensemble_member), MIN(forecast_hour), MAX(forecast_hour)
        FROM regridded_forecast_member
        {where}
        GROUP BY model_name, variable_name, init_time
        ON CONFLICT (model_name, variable_name, init_time) DO UPDATE SET
            n_members = EXCLUDED.n_members,
            hour_min  = EXCLUDED.hour_min,
            hour_max  = EXCLUDED.hour_max
    """, params)
    return cur.rowcount


def resolve_divisor(cur, model_name, variable_name, init_time):
    """The export divisor for one run, from the registry. Raises if undeclared.

    Returns None for an unscaled export, which is a real answer meaning "there
    is nothing to undo" — not the same as the absence of one. Anything the
    registry cannot speak for raises `UnknownConventionError`, because the
    alternative is scoring a model by whatever the previous run happened to do.

    This is the read path scoring will move onto. Nothing calls it yet; see the
    module docstring for why that is a separate step.
    """
    cur.execute(f"""
        SELECT export_convention, export_divisor_h
        FROM {TABLE}
        WHERE model_name = %s AND variable_name = %s AND init_time = %s
    """, (model_name, variable_name, init_time))
    row = cur.fetchone()
    if row is None:
        raise UnknownConventionError(
            f'{model_name}/{variable_name} at {init_time} is not in {TABLE}; '
            f'load it through run_registry.record() so its export convention '
            f'is stated rather than assumed')

    convention, divisor = (row['export_convention'], row['export_divisor_h']) \
        if isinstance(row, dict) else (row[0], row[1])

    if convention is None:
        raise UnknownConventionError(
            f'{model_name}/{variable_name} at {init_time} has no declared '
            f'export convention. NULL here means nobody said, which is not the '
            f'same as unscaled — record {UNSCALED!r} explicitly if that is what '
            f'it is.')
    if convention == UNSCALED:
        return None
    if divisor is None:
        raise UnknownConventionError(
            f'{model_name}/{variable_name} at {init_time} is marked {SCALED!r} '
            f'with no divisor, which says something was divided out without '
            f'saying by what')
    return float(divisor)


def backfill_conventions(cur):
    """Name the convention for rows that predate `export_convention`.

    The existing run's divisors were backfilled by `migrate_init_time.py` from
    the constant, so the numbers are right and only the naming is missing.
    Inferred from the divisor rather than from `DECLARED`, so a row someone
    edited by hand keeps saying what it actually holds.

    Deliberately does not touch a row that already names its convention.
    """
    cur.execute(f"""
        UPDATE {TABLE}
           SET export_convention = CASE
                   WHEN export_divisor_h IS NOT NULL THEN %s
                   ELSE %s
               END
         WHERE export_convention IS NULL
           AND variable_name = 'precipitation'
    """, (SCALED, UNSCALED))
    scored = cur.rowcount
    # Wind has no window to divide by, so "unscaled" is the honest answer
    # rather than leaving it undeclared and tripping resolve_divisor later.
    cur.execute(f"""
        UPDATE {TABLE} SET export_convention = %s
         WHERE export_convention IS NULL AND variable_name <> 'precipitation'
    """, (UNSCALED,))
    return scored + cur.rowcount


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--backfill', action='store_true',
                        help='name the convention on rows that predate the column')
    parser.add_argument('--refresh', action='store_true',
                        help='recompute counts and ranges from the member table')
    parser.add_argument('--show', action='store_true', help='print the registry')
    args = parser.parse_args()
    if not (args.backfill or args.refresh or args.show):
        parser.error('give --backfill, --refresh and/or --show')

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            ensure_schema(cur)
            if args.refresh:
                print(f'refreshed {refresh_from_members(cur)} rows from members')
            if args.backfill:
                print(f'named the convention on {backfill_conventions(cur)} rows')
            conn.commit()
            if args.show:
                cur.execute(f"""
                    SELECT model_name, variable_name, init_time, n_members,
                           hour_min, hour_max, export_convention, export_divisor_h
                    FROM {TABLE} ORDER BY init_time DESC, model_name, variable_name
                """)
                for r in cur.fetchall():
                    div = '—' if r['export_divisor_h'] is None else f"{r['export_divisor_h']:g}h"
                    print(f"  {r['init_time']}  {r['model_name']:5s} "
                          f"{r['variable_name']:14s} members={r['n_members'] or '—':>4} "
                          f"hours={r['hour_min']}–{r['hour_max']:<4} "
                          f"{str(r['export_convention'] or 'UNDECLARED'):10s} {div}")
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
