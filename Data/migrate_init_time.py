#!/usr/bin/env python
"""Give the regridded tables a run identity, and register the runs.

The problem
-----------
`regridded_forecast_ens` and `regridded_forecast_member` carry
`model_name, variable_name, forecast_hour, latitude, longitude` and nothing that
says *which forecast run* a row came from. With one run loaded that is
unambiguous. With two, every row becomes undecidable — and the API does not
error, it guesses: `_latest_init_time` resolves the newest run in
`forecast_runs` and adds `forecast_hour` to get a valid time. So a second
initialisation would silently attribute every regridded row to it and make every
score wrong in a way that looks entirely plausible.

`DATA_EXPANSION_DESIGN.md` calls this the single blocking issue, and says it must
be fixed *before* a second run is loaded rather than after. This is that fix.

What it does
------------
1. `init_time TIMESTAMP NOT NULL` on both regridded tables, backfilled from
   `forecast_runs` and then stripped of its default.
2. `forecast_run_registry` — one row per (model, variable, init_time) recording
   what was loaded, when, over what hours, from how many members, and under
   which export convention.
3. Indexes leading with the run, so a query for one run touches one range.

Idempotent: every step checks first, so re-running is a no-op and a half-applied
migration can be finished by running it again.

Why `ADD COLUMN ... DEFAULT` and not the design document's plan
--------------------------------------------------------------
The design document says to add the column nullable, `UPDATE` it, then set NOT
NULL. That rewrites every row: `regridded_forecast_member` is 42.2M rows and
6.5 GB, so the UPDATE would take minutes and roughly double the table's on-disk
size until a VACUUM FULL. Since PostgreSQL 11, `ADD COLUMN ... NOT NULL DEFAULT
<constant>` is a **catalogue-only** change — the value is stored once in
`pg_attribute.attmissingval` and materialised on read — so it is instant at any
size. This script does that, then `DROP DEFAULT`.

Dropping the default matters and is not cosmetic. It leaves the backfilled rows
alone but makes the column mandatory for new inserts, so `regrid_members.py` has
to state which run it is writing. A default left in place is exactly the silent
mis-attribution this migration exists to remove — it would just move from the
query layer to the schema.

Usage
-----
    python migrate_init_time.py --dry-run     # report, change nothing
    python migrate_init_time.py
    python migrate_init_time.py --rollback    # drop the column and the registry
"""
import argparse
import os
import sys

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

DB_CONFIG = {
    'dbname':   os.environ.get('DB_NAME',     'weave_weather'),
    'user':     os.environ.get('DB_USER',     'k.aggarwal'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'host':     os.environ.get('DB_HOST',     'localhost'),
    'port':     int(os.environ.get('DB_PORT', 5432)),
}

REGRIDDED_TABLES = ('regridded_forecast_ens', 'regridded_forecast_member')

REGISTRY_DDL = """
CREATE TABLE IF NOT EXISTS forecast_run_registry (
    model_name       TEXT      NOT NULL,
    variable_name    TEXT      NOT NULL,
    init_time        TIMESTAMP NOT NULL,
    loaded_at        TIMESTAMP NOT NULL DEFAULT now(),
    n_members        INTEGER,
    hour_min         INTEGER,
    hour_max         INTEGER,
    -- The divisor the source export had already applied, per METRICS_AUDIT
    -- finding 16. Recorded per run at load time so it can never again be a
    -- constant in code that goes stale when someone re-exports: a run loaded
    -- under a different convention coexists with this one instead of silently
    -- correcting twice.
    export_divisor_h REAL,
    PRIMARY KEY (model_name, variable_name, init_time)
);
"""

# Leading with the run so a single-run query touches one index range. The old
# idx_rf{e,m}_lookup indexes stay: they still serve queries that do not filter
# on init_time, and dropping them is a separate decision.
RUN_INDEXES = {
    'regridded_forecast_ens': """
        CREATE INDEX IF NOT EXISTS idx_rfe_run ON regridded_forecast_ens
            (model_name, variable_name, init_time, forecast_hour, latitude, longitude)
    """,
    'regridded_forecast_member': """
        CREATE INDEX IF NOT EXISTS idx_rfm_run ON regridded_forecast_member
            (model_name, variable_name, init_time, forecast_hour, latitude, longitude)
    """,
}


def _table_exists(cur, table):
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (table,))
    return cur.fetchone()[0]


def _column_exists(cur, table, column):
    cur.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table, column))
    return cur.fetchone() is not None


def _column_default(cur, table, column):
    cur.execute("""
        SELECT column_default FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table, column))
    row = cur.fetchone()
    return row[0] if row else None


def latest_init_times(cur):
    """{model_name: initialization_time} for the newest run of each model.

    The backfill value. This is the one moment where "the latest run" is the
    right answer: there is exactly one run loaded, so attributing existing rows
    to it is a statement of fact rather than a guess. Every later read gets an
    explicit `init_time` instead.
    """
    cur.execute("""
        SELECT m.model_name, MAX(fr.initialization_time) AS init_time
        FROM forecast_runs fr
        JOIN models m ON m.model_id = fr.model_id
        GROUP BY m.model_name
    """)
    return {r[0]: r[1] for r in cur.fetchall()}


def distinct_run_count(cur):
    cur.execute("SELECT COUNT(DISTINCT initialization_time) FROM forecast_runs")
    return cur.fetchone()[0]


def add_init_time(cur, table, backfill, dry_run):
    if not _table_exists(cur, table):
        print(f"  {table}: absent, skipped")
        return
    if _column_exists(cur, table, 'init_time'):
        default = _column_default(cur, table, 'init_time')
        state = f"default {default}" if default else "no default"
        print(f"  {table}.init_time: already present ({state})")
        if default and not dry_run:
            cur.execute(f"ALTER TABLE {table} ALTER COLUMN init_time DROP DEFAULT")
            print(f"    -> dropped the default, so inserts must state the run")
        return
    if dry_run:
        print(f"  {table}: WOULD add init_time NOT NULL DEFAULT '{backfill}', "
              f"then drop the default")
        return
    # Catalogue-only on PG 11+: instant regardless of row count.
    cur.execute(f"ALTER TABLE {table} "
                f"ADD COLUMN init_time TIMESTAMP NOT NULL DEFAULT %s", (backfill,))
    cur.execute(f"ALTER TABLE {table} ALTER COLUMN init_time DROP DEFAULT")
    print(f"  {table}: added init_time, backfilled {backfill}, default dropped")


def populate_registry(cur, dry_run):
    """One row per (model, variable, init_time) actually present in the members."""
    if dry_run:
        print("  registry: WOULD create and populate from regridded_forecast_member")
        return
    cur.execute(REGISTRY_DDL)
    cur.execute("""
        INSERT INTO forecast_run_registry
            (model_name, variable_name, init_time, n_members, hour_min, hour_max)
        SELECT model_name, variable_name, init_time,
               COUNT(DISTINCT ensemble_member), MIN(forecast_hour), MAX(forecast_hour)
        FROM regridded_forecast_member
        GROUP BY model_name, variable_name, init_time
        ON CONFLICT (model_name, variable_name, init_time) DO UPDATE SET
            n_members = EXCLUDED.n_members,
            hour_min  = EXCLUDED.hour_min,
            hour_max  = EXCLUDED.hour_max
    """)
    print(f"  registry: {cur.rowcount} (model, variable, run) rows")

    # The export convention, from the constant that currently encodes it. Moving
    # it into data is the point: `SCALED_EXPORT_DIVISOR_HOURS` describes how the
    # *loaded* export was produced, and a second run made differently would
    # otherwise be corrected with the first run's divisor.
    from metrics import SCALED_EXPORT_DIVISOR_HOURS
    for model, divisor in SCALED_EXPORT_DIVISOR_HOURS.items():
        cur.execute("""
            UPDATE forecast_run_registry SET export_divisor_h = %s
            WHERE model_name = %s AND variable_name = 'precipitation'
              AND export_divisor_h IS NULL
        """, (divisor, model))
    print(f"  registry: export divisors recorded from SCALED_EXPORT_DIVISOR_HOURS")


def rollback(cur):
    for table in REGRIDDED_TABLES:
        if _table_exists(cur, table) and _column_exists(cur, table, 'init_time'):
            cur.execute(f"ALTER TABLE {table} DROP COLUMN init_time")
            print(f"  {table}: dropped init_time")
    cur.execute("DROP TABLE IF EXISTS forecast_run_registry")
    print("  dropped forecast_run_registry")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true', help='report, change nothing')
    ap.add_argument('--rollback', action='store_true',
                    help='drop init_time and the registry')
    args = ap.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            if args.rollback:
                print("rolling back:")
                rollback(cur)
                conn.commit()
                return

            runs = distinct_run_count(cur)
            latest = latest_init_times(cur)
            print(f"forecast_runs holds {runs} distinct initialisation time(s)")
            for model, t in sorted(latest.items()):
                print(f"  {model}: {t}")

            if runs > 1:
                # The backfill assumes every regridded row belongs to the single
                # loaded run. With more than one already present that assumption
                # is false and there is no way to recover which is which — which
                # is precisely why this migration had to come first.
                sys.exit(
                    f"REFUSING TO BACKFILL: {runs} distinct initialisation times are "
                    f"already in forecast_runs. The regridded tables carry no run "
                    f"identity, so there is no way to tell which rows belong to "
                    f"which run. Reload the regridded tables per run instead.")
            if not latest:
                sys.exit("no runs in forecast_runs — nothing to attribute rows to")
            if len(set(latest.values())) != 1:
                # A single ADD COLUMN DEFAULT cannot give different models
                # different values, and the per-model backfill that would need
                # (add nullable, UPDATE per model, SET NOT NULL) is a path this
                # data cannot exercise, so it is not written rather than written
                # untested. Say so plainly instead of picking one and hoping.
                sys.exit(
                    f"REFUSING TO BACKFILL: models have different initialisation "
                    f"times ({sorted(set(str(t) for t in latest.values()))}). This "
                    f"script only handles the single-run case it can verify. Add "
                    f"the column nullable, UPDATE per model, then SET NOT NULL.")

            backfill = next(iter(latest.values()))
            print("\nschema:")
            for table in REGRIDDED_TABLES:
                add_init_time(cur, table, backfill, args.dry_run)

            if not args.dry_run:
                print("\nindexes:")
                for table, ddl in RUN_INDEXES.items():
                    if _table_exists(cur, table):
                        cur.execute(ddl)
                        print(f"  {table}: idx leading with (model, variable, init_time)")

            print("\nregistry:")
            populate_registry(cur, args.dry_run)

            if args.dry_run:
                conn.rollback()
                print("\ndry run: rolled back")
            else:
                conn.commit()
                print("\ndone")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
