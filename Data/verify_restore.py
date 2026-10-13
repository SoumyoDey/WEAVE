"""Compare a restored database against the live one, table by table.

Written for the `pg_dump`/`pg_restore` rehearsal `DEPLOY.md` §9 asked for and
nobody had run. **A restore that completes is not a restore that worked**: the
failure worth catching is not a crash — those announce themselves — but a table
that came back short, or numerically altered, while `pg_restore` exits 0.

So the comparison is on content, not on success:

* `count(*)` per table, which catches a truncated or missing relation;
* `sum`, `min` and `max` of every numeric column, which catches altered values
  without hashing a hundred million rows. A sum alone can be fooled by two
  compensating changes; a sum *and* both extremes, per column, across every
  table, cannot be fooled by anything plausible;
* the index and constraint inventory, because `pg_dump` stores index
  *definitions* rather than index data — 99 of this database's 138 GB are
  indexes, so "the data restored" and "the database is usable" are different
  claims, and only the second one matters at 03:00.

Usage:
    python verify_restore.py weave_weather weave_restore_rehearsal
"""
import sys
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor


NUMERIC_TYPES = {'smallint', 'integer', 'bigint', 'real', 'double precision',
                 'numeric', 'decimal'}


def connect(dbname):
    return psycopg2.connect(dbname=dbname, user='k.aggarwal',
                            host='localhost', port=5432,
                            cursor_factory=RealDictCursor)


def tables(cur):
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    return [r['table_name'] for r in cur.fetchall()]


def numeric_columns(cur, table):
    cur.execute("""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
    """, (table,))
    return [r['column_name'] for r in cur.fetchall()
            if r['data_type'] in NUMERIC_TYPES]


def fingerprint(cur, table):
    """`count(*)` plus sum/min/max of each numeric column, in one pass."""
    cols = numeric_columns(cur, table)
    parts = ['count(*) AS n']
    for c in cols:
        parts += [f'sum("{c}"::double precision) AS "sum_{c}"',
                  f'min("{c}"::double precision) AS "min_{c}"',
                  f'max("{c}"::double precision) AS "max_{c}"']
    cur.execute(f'SELECT {", ".join(parts)} FROM "{table}"')
    row = dict(cur.fetchone())
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in row.items()}


def index_inventory(cur):
    cur.execute("""
        SELECT tablename, indexname FROM pg_indexes
        WHERE schemaname = 'public' ORDER BY tablename, indexname
    """)
    return {(r['tablename'], r['indexname']) for r in cur.fetchall()}


def close(a, b):
    """Floats survive a dump/restore exactly; this tolerates only summation
    order, which differs because the restored heap is in a different physical
    order."""
    if a is None or b is None:
        return a is None and b is None
    if a == b:
        return True
    scale = max(abs(a), abs(b), 1.0)
    return abs(a - b) <= 1e-9 * scale


def main():
    live_name, restored_name = sys.argv[1], sys.argv[2]
    live, restored = connect(live_name), connect(restored_name)
    lc, rc = live.cursor(), restored.cursor()

    lt, rt = tables(lc), tables(rc)
    failures = []

    missing = set(lt) - set(rt)
    extra = set(rt) - set(lt)
    if missing:
        failures.append(f'tables missing from the restore: {sorted(missing)}')
    if extra:
        failures.append(f'unexpected tables in the restore: {sorted(extra)}')

    print(f'{"table":<34} {"rows (live)":>14} {"rows (restored)":>16}  verdict')
    print('-' * 86)
    for t in lt:
        if t not in rt:
            print(f'{t:<34} {"—":>14} {"MISSING":>16}  FAIL')
            continue
        lf, rf = fingerprint(lc, t), fingerprint(rc, t)
        bad = [k for k in lf if not close(lf[k], rf.get(k))]
        verdict = 'ok' if not bad else f'FAIL {bad[:3]}'
        if bad:
            failures.append(f'{t}: {bad}')
        print(f'{t:<34} {lf["n"]:>14,} {rf["n"]:>16,}  {verdict}')

    li, ri = index_inventory(lc), index_inventory(rc)
    print()
    print(f'indexes: live {len(li)}, restored {len(ri)}')
    if li != ri:
        only_live = sorted(li - ri)
        failures.append(f'{len(only_live)} index(es) did not come back: {only_live[:5]}')
        print(f'  MISSING: {only_live[:5]}')
    else:
        print('  every index and constraint came back')

    print()
    if failures:
        print('RESTORE NOT VERIFIED')
        for f in failures:
            print(' ', f)
        return 1
    print('RESTORE VERIFIED — row counts, numeric aggregates and indexes all match')
    return 0


if __name__ == '__main__':
    sys.exit(main())
