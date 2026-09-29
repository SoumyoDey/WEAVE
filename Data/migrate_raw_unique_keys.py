#!/usr/bin/env python
"""Give `forecast_data` and `ensemble_statistics` the unique keys they lack.

`5d45a29` gave the *regridded* tables `uq_rfm_natural_key` and
`uq_rfe_natural_key`, because a re-run was appending a second copy of every row
and every score was then computed over duplicated members. The raw tables were
left as they were, with only a surrogate `data_id`/`stat_id` primary key — so
loading the same run twice still doubles every row, silently.

**That has already happened.** GEFS wind was loaded twice: 10,590,300 rows where
5,295,150 belong, in both components, and 353,010 statistics rows where 176,505
belong. Found 2026-09-28 while investigating something else, because
`/api/wind-data` self-joins `ensemble_statistics` u against v and turned 2x into
**4.00x** — 6,724 points for 1,681 cells.

The regridded tables absorbed it harmlessly (the regrid keys by member and cell
and overwrote with an identical value), so no score was wrong. That is luck, not
design: two rows with the same key and *different* values would have been
resolved by whichever the regrid happened to read last.

What this does
--------------
1. Reports duplication per (run, variable) — and **only touches groups that
   have some**, so an already-clean database is a no-op rather than a full
   rewrite of 146M rows.
2. Refuses to delete anything from a group whose copies disagree. Identical
   copies are information-free and safe to collapse; disagreeing ones are a
   different defect and picking a winner would hide it.
3. Deletes all but the lowest surrogate id in each group.
4. Creates the unique indexes, which is the part that stops this recurring.

Idempotent, and `--dry-run` reports without writing.

Why not make the existing index unique
--------------------------------------
`idx_forecast_data_member_lookup` covers the natural key **plus `value`**. A
unique constraint there would reject exact duplicates and still permit two rows
with the same key and contradictory values, which is the worse case. The
constraint has to be on the key alone.

Cost
----
The `forecast_data` index is the expensive part — six columns over 146M rows,
several GB and several minutes. `CREATE UNIQUE INDEX` takes a write lock for the
duration; `--concurrently` avoids that at the price of not running inside a
transaction, which is the right choice against anything serving traffic.
"""
import argparse
import os
import sys
import time

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))

DB_CONFIG = dict(
    host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', 5432),
    dbname=os.getenv('DB_NAME', 'weave_weather'),
    user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'),
)

# (table, surrogate key, natural key, index name). The natural key is what
# identifies one reading; anything beyond it is payload.
TARGETS = [
    ('forecast_data', 'data_id',
     ('run_id', 'variable_id', 'forecast_hour', 'ensemble_member',
      'latitude', 'longitude'),
     'uq_forecast_data_natural_key'),
    ('ensemble_statistics', 'stat_id',
     ('run_id', 'variable_id', 'forecast_hour', 'latitude', 'longitude'),
     'uq_ensemble_statistics_natural_key'),
    # The observation tables, added 2026-09-29 before extending the record.
    # One reading per (source, time, cell): `observation_data` carries
    # precipitation and the wind components in the SAME row per source, so the
    # variable is not part of its key, whereas the regridded table is one row
    # per variable.
    ('observation_data', 'obs_id',
     ('source', 'obs_time', 'latitude', 'longitude'),
     'uq_observation_data_natural_key'),
    ('regridded_observation', 'id',
     ('source', 'variable_name', 'obs_time', 'latitude', 'longitude'),
     'uq_regridded_observation_natural_key'),
]

# Columns that must agree before duplicates are collapsed.
PAYLOAD = {'forecast_data': ('value',),
           'ensemble_statistics': ('mean_value', 'std_dev'),
           'observation_data': ('precipitation', 'wind_u', 'wind_v', 'wind_speed'),
           'regridded_observation': ('value', 'source_points')}

# Tables keyed on a run, which the per-(run, variable) scoping below assumes.
# The observation tables have neither column, so they are scanned whole — which
# is affordable because they are small next to `forecast_data`.
RUN_SCOPED = {'forecast_data', 'ensemble_statistics'}


def duplicate_groups(cur, table, natural_key):
    """[(run_id, variable_id, groups, rows)] for pairs that hold duplicates.

    Scoped per (run_id, variable_id) so each aggregation stays index-covered
    rather than sorting the whole table. The observation tables have no such
    columns, so they are checked in one pass with `(None, None)` standing in.
    """
    keys = ', '.join(natural_key)
    if table not in RUN_SCOPED:
        cur.execute(f'SELECT count(*), count(DISTINCT ({keys})) FROM {table}')
        rows, distinct = cur.fetchone()
        return [(None, None, rows - distinct, rows)] if rows != distinct else []
    cur.execute(f'SELECT DISTINCT run_id, variable_id FROM {table} ORDER BY 1, 2')
    found = []
    for run_id, variable_id in cur.fetchall():
        cur.execute(f"""
            SELECT count(*), count(DISTINCT ({keys}))
            FROM {table} WHERE run_id = %s AND variable_id = %s
        """, (run_id, variable_id))
        rows, distinct = cur.fetchone()
        if rows != distinct:
            found.append((run_id, variable_id, rows - distinct, rows))
    return found


def _scope(table, run_id, variable_id):
    """(WHERE clause, params) narrowing to one (run, variable), or the whole table.

    The forecast tables are narrowed so each aggregation stays index-covered
    instead of sorting 146M rows; the observation tables have no run columns and
    are small enough to scan whole.
    """
    if table in RUN_SCOPED:
        return 'WHERE run_id = %s AND variable_id = %s', (run_id, variable_id)
    return '', ()


def copies_disagree(cur, table, natural_key, run_id, variable_id):
    """How many duplicate groups hold more than one distinct payload.

    Two levels, because the per-group aggregate cannot itself be summed —
    PostgreSQL rejects nested aggregates. NULL is folded to a sentinel so a
    NULL/non-NULL pair counts as disagreement rather than being ignored, which
    matters for `std_dev`. The sentinel is a literal, not `chr(0)`: PostgreSQL
    refuses a null character in text, and every payload column here is numeric
    so its `::text` cannot collide with it.
    """
    keys = ', '.join(natural_key)
    checks = ' + '.join(
        f"(count(DISTINCT coalesce({c}::text, '<null>')) - 1)" for c in PAYLOAD[table])
    scope, params = _scope(table, run_id, variable_id)
    cur.execute(f"""
        SELECT coalesce(sum(extra), 0) FROM (
            SELECT GREATEST({checks}, 0) AS extra
            FROM {table}
            {scope}
            GROUP BY {keys}
            HAVING count(*) > 1
        ) per_group
    """, params)
    return int(cur.fetchone()[0])


def dedupe(cur, table, surrogate, natural_key, run_id, variable_id):
    """Delete all but the lowest surrogate id in each group. Returns the count."""
    keys = ', '.join(natural_key)
    scope, params = _scope(table, run_id, variable_id)
    cur.execute(f"""
        DELETE FROM {table}
        WHERE {surrogate} IN (
            SELECT {surrogate} FROM (
                SELECT {surrogate},
                       row_number() OVER (PARTITION BY {keys} ORDER BY {surrogate}) AS rn
                FROM {table} {scope}
            ) ranked WHERE rn > 1
        )
    """, params)
    return cur.rowcount


def index_exists(cur, name):
    cur.execute('SELECT indisunique FROM pg_index i '
                'JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = %s', (name,))
    row = cur.fetchone()
    return row[0] if row else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true',
                    help='report what would change and write nothing')
    ap.add_argument('--concurrently', action='store_true',
                    help='build the indexes without a write lock (cannot run in a '
                         'transaction; use this against a live server)')
    args = ap.parse_args(argv)

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = bool(args.concurrently)
    failed = False
    try:
        for table, surrogate, natural_key, index_name in TARGETS:
            print(f'\n=== {table} ===')
            with conn.cursor() as cur:
                state = index_exists(cur, index_name)
                if state is True:
                    print(f'  {index_name} already exists and is unique')
                    continue

                groups = duplicate_groups(cur, table, natural_key)
                if not groups:
                    print('  no duplicates')
                else:
                    total = sum(g[2] for g in groups)
                    print(f'  {len(groups)} (run, variable) pair(s) hold {total:,} '
                          f'duplicate row(s)')
                    for run_id, variable_id, dupes, rows in groups:
                        bad = copies_disagree(cur, table, natural_key, run_id, variable_id)
                        note = '' if not bad else f'  !! {bad} group(s) DISAGREE'
                        print(f'    run {run_id} variable {variable_id}: '
                              f'{dupes:,} of {rows:,}{note}')
                        if bad:
                            # Collapsing these would pick a value arbitrarily and
                            # hide a different defect.
                            print('       refusing to collapse disagreeing copies')
                            failed = True
                            continue
                        if args.dry_run:
                            continue
                        started = time.time()
                        removed = dedupe(cur, table, surrogate, natural_key,
                                         run_id, variable_id)
                        conn.commit() if not conn.autocommit else None
                        print(f'       deleted {removed:,} in {time.time()-started:.1f}s')

                if failed:
                    print('  skipping the index while duplicates remain')
                    continue
                if args.dry_run:
                    print(f'  would create {index_name} on ({", ".join(natural_key)})')
                    continue

                started = time.time()
                concurrently = 'CONCURRENTLY ' if args.concurrently else ''
                print(f'  creating {index_name} ...', flush=True)
                # NULLS NOT DISTINCT so the deterministic path's NULL
                # `ensemble_member` cannot duplicate — PostgreSQL treats NULLs
                # as distinct by default, which would leave exactly the hole
                # this closes. Matches `schema.sql`; needs PostgreSQL 15+.
                cur.execute(f'CREATE UNIQUE INDEX {concurrently}IF NOT EXISTS '
                            f'{index_name} ON {table} ({", ".join(natural_key)}) '
                            f'NULLS NOT DISTINCT')
                if not conn.autocommit:
                    conn.commit()
                cur.execute('SELECT pg_size_pretty(pg_relation_size(%s::regclass))',
                            (index_name,))
                print(f'       built in {time.time()-started:.1f}s, '
                      f'{cur.fetchone()[0]}')
    finally:
        conn.close()

    if failed:
        print('\nINCOMPLETE — duplicates whose copies disagree were left alone')
        return 1
    print('\nDONE' if not args.dry_run else '\nDRY RUN — nothing written')
    return 0


if __name__ == '__main__':
    sys.exit(main())
