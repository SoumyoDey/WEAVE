#!/usr/bin/env python
"""Regenerate the quantitative claims in METRICS_AUDIT.md, with their parameters.

Why this exists
---------------
Re-deriving that audit by hand was painful for one reason: **most of its numbers
did not record the query that produced them.** "observed 0.387 mm/h" does not say
over which box, which hours, or which observation source, so when the truth field
changed on 2026-09-04 there was no way to recompute the same quantity — only a
similar one, which is worse than useless because it looks like a comparison.

So this script computes a fixed set of figures and prints the parameters beside
each. Run it, paste the output into the audit, and the next time the data changes
the update is one command instead of an archaeology exercise.

    python rederive_audit.py            # human-readable
    python rederive_audit.py --markdown # tables to paste into the audit

Scopes are deliberately few and reused, so figures are comparable across
findings: the coastal point the audit uses throughout, the small box, and the
full analysis domain. Adding a scope is cheaper than reusing one loosely.

What it does NOT do
-------------------
It does not reproduce the *original* numbers. Several cannot be reproduced at all
— their scope was never written down — and this makes no attempt to guess. Where
the audit's figure and this script's figure disagree, the audit's provenance is
unknown and this one's is printed above it.
"""
import argparse
import os
import statistics as st
import sys

# Importing flask_api opens a connection pool, which is what we want here: these
# figures should come through the same code path the app serves, not a
# reimplementation of it. A reimplementation is how an audit ends up confirming
# its own arithmetic rather than the app's.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flask_api as api  # noqa: E402

# ── Scopes, stated once and reused ───────────────────────────────────────────
POINT = {'lat': 36.0, 'lon': -75.5}
POINT_LABEL = '36.0 N, 75.5 W (the coastal point used throughout the audit)'
BOX = {'min_lat': 35, 'max_lat': 37, 'min_lon': -77, 'max_lon': -74}
BOX_LABEL = '35-37 N, 77-74 W'
FULL = {'min_lat': 25, 'max_lat': 45, 'min_lon': -85, 'max_lon': -65}
FULL_LABEL = '25-45 N, 85-65 W (the whole analysis grid)'
HOURS = {'hour_min': 0, 'hour_max': 168}
# Resolved from the run at startup, not hardcoded — see `_models_in_run`.
MODELS = ['AIFS', 'GEFS', 'UKMO']

# Which forecast run every figure below describes.
#
# **This became load-bearing on 2026-09-28**, when AIFS and UKMO each gained a
# second run. Until then the API defaulted to the only run and this script could
# omit the parameter; now an unqualified request is refused as ambiguous, which
# is the `init_time` migration working as designed.
#
# **The default moved to `2025-09-16 00Z` on 2026-10-01.** This used to read
# "the audit has always described 2025-09-08 00Z — the full three-model run".
# That stopped being true in `NEXT_STEPS.md` §24: GEFS at 09-08 was the 09-16
# forecast under the wrong label and was deleted, because no GEFS 09-08 exists
# on the cluster. **09-16 is now the only initialisation holding all three
# models at both variables**, which is what this audit needs.
INIT_TIME = '2025-09-16 00:00:00'


def _client():
    # The cache would answer from a previous run's data version and is exactly
    # what an audit must not read through.
    api.cache = None
    return api.app.test_client()


def _models_in_run(init_time):
    """Which models the named run actually holds, in order.

    `MODELS` was hardcoded to all three until 2026-10-01, which stopped working
    the moment a run held fewer. Two already do: `2025-09-08 06Z` is AIFS and
    UKMO, and `2025-09-08 00Z` became AIFS and UKMO when GEFS was deleted from
    it (`NEXT_STEPS.md` §24 — the rows there were the 09-16 forecast mislabelled,
    and no GEFS 09-08 exists on the cluster).

    Asking for a model a run lacks does not produce a small gap. `_check` turns
    the refusal into a `SystemExit`, so the whole audit stops — which is the
    right behaviour for a bad request and the wrong one for a run that is simply
    smaller. Reading the inventory removes the question.

    This is the same rule the registry work arrived at from the other direction:
    *have the tool describe what is in the table, never what it was told to
    expect.*
    """
    conn = api.get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT m.model_name
                  FROM forecast_runs r
                  JOIN models m ON m.model_id = r.model_id
                 WHERE r.initialization_time = %s
                 ORDER BY m.model_name
            """, (init_time,))
            found = [row[0] for row in cur.fetchall()]
    finally:
        api.return_db_connection(conn)
    if not found:
        raise SystemExit(
            f'no run at init_time={init_time!r}. Loaded runs come from '
            f'/api/runs; pass one of those to --init-time.')
    return found


def _check(payload, what):
    """Fail on an error response instead of rendering it as blank cells.

    The first version of this script read figures out of the payload with
    `.get(...)` chains, so a refused request produced a table of empty cells and
    carried on. That output is worse than a crash: it looks like a result, and
    an audit's whole purpose is that its numbers can be trusted. On 2026-09-28
    it printed six blank rows of point scores before falling over two sections
    later.
    """
    if not isinstance(payload, dict):
        raise SystemExit(f'{what}: expected an object, got {type(payload).__name__}')
    if 'error' in payload:
        raise SystemExit(f'{what}: {payload["error"]}\n'
                         f'  hint: {payload.get("hint", "")}\n'
                         f'  (this script pins init_time={INIT_TIME!r}; '
                         f'pass --init-time to describe a different run)')
    return payload


def point_scores(c, md):
    rows = []
    for variable in ('precipitation', 'wind'):
        d = _check(c.post('/api/compare/skill',
                          json={'models': MODELS, 'variable': variable,
                                'init_time': INIT_TIME,
                                **POINT, **HOURS}).get_json(),
                   f'compare/skill {variable}')
        for m in MODELS:
            s = d.get('models', {}).get(m, {}).get('summary', {})
            rows.append((variable, m, s.get('bias'), s.get('mae'),
                         s.get('rmse'), s.get('crps'), s.get('ssr_agg')))
    _emit('Point scores',
          f'/api/compare/skill at {POINT_LABEL}, hours 0-168, run {INIT_TIME}',
          ['variable', 'model', 'bias', 'mae', 'rmse', 'crps', 'ssr_agg'], rows, md)


def pooled_vs_cell_mean(c, md):
    """Finding 8: the two estimators genuinely differ, and by how much."""
    d = _check(c.post('/api/compare/region-metrics',
                      json={'models': MODELS, 'variable': 'precipitation',
                            'metrics': ['mae', 'rmse'], 'init_time': INIT_TIME,
                            **HOURS, **FULL}).get_json(),
               'compare/region-metrics mae+rmse')
    rows = []
    for m in MODELS:
        p, cm = d['models'][m], d['cell_means'][m]
        rows.append((m, 'rmse', p['rmse'], cm['rmse'],
                     round(p['rmse'] / cm['rmse'], 3), d['n_cells'][m]))
        ratio = round(p['mae'] / cm['mae'], 3) if cm['mae'] else None
        rows.append((m, 'mae', p['mae'], cm['mae'], ratio, d['n_cells'][m]))
    _emit('Pooled vs per-cell estimators (finding 8)',
          f'/api/compare/region-metrics over {FULL_LABEL}, hours 0-168, '
          f'run {INIT_TIME}',
          ['model', 'metric', 'pooled', 'cell mean', 'ratio', 'n cells'], rows, md,
          note='RMSE differs by Jensen (sqrt is concave). MAE is linear, so the '
               'two agree wherever every cell contributes the same number of '
               'samples — GEFS is the exception, because its cells do not.')


def categorical_by_threshold(c, md):
    """The same estimator split, on a metric that needs events to exist."""
    rows = []
    for thr in (25, 6, 3, 1):
        d = _check(c.post('/api/compare/region-metrics',
                          json={'models': MODELS, 'variable': 'precipitation',
                                'metrics': ['csi'], 'threshold_mm_6h': thr,
                                'init_time': INIT_TIME,
                                **HOURS, **FULL}).get_json(),
                   f'compare/region-metrics csi thr={thr}')
        for m in MODELS:
            rows.append((thr, m, d['models'][m].get('csi'),
                         d['cell_means'][m].get('csi')))
    _emit('Pooled vs per-cell CSI, by threshold',
          f'/api/compare/region-metrics over {FULL_LABEL}, hours 0-168, '
          f'run {INIT_TIME}',
          ['thr mm/6h', 'model', 'pooled CSI', 'cell-mean CSI'], rows, md,
          note='At 25 mm/6h GEFS has no events at all, so its CSI is 0 by '
               'definition rather than by performance — a threshold has to '
               'produce events before the two estimators can be compared.')


def per_cell_distribution(c, md):
    rows = []
    for variable in ('precipitation', 'wind'):
        for m in MODELS:
            qs = '&'.join(f'{k}={v}' for k, v in FULL.items())
            r = _check(c.get(f'/api/spatial-metric?metric=mae&model={m}'
                             f'&variable={variable}&{qs}'
                             f'&init_time={INIT_TIME.replace(" ", "%20")}'
                             f'&hour_min={HOURS["hour_min"]}'
                             f'&hour_max={HOURS["hour_max"]}').get_json(),
                       f'spatial-metric mae {m} {variable}')
            v = [p['value'] for p in r.get('points', []) if p.get('value') is not None]
            # An empty result is itself a finding, so it is reported rather than
            # skipped: a row silently absent reads as "not measured".
            rows.append((variable, m, len(v),
                         round(st.mean(v), 4) if v else None,
                         round(st.median(v), 4) if v else None,
                         round(max(v), 4) if v else None))
    _emit('Per-cell MAE distribution',
          f'/api/spatial-metric metric=mae over {FULL_LABEL}, hours 0-168, '
          f'run {INIT_TIME}',
          ['variable', 'model', 'n cells', 'mean', 'median', 'max'], rows, md)


def domain_means(md):
    """Observed and forecast domain means — the 'in family' check."""
    conn = api.get_db_connection()
    cur = conn.cursor()
    try:
        rows = []
        cur.execute("""
            SELECT source, round(avg(value)::numeric, 4), count(*)
            FROM regridded_observation
            WHERE latitude BETWEEN %(min_lat)s AND %(max_lat)s
              AND longitude BETWEEN %(min_lon)s AND %(max_lon)s
            GROUP BY source ORDER BY source
        """, FULL)
        for src, mean, n in cur.fetchall():
            rows.append(('observed', src, float(mean), n))
        # `init_time` is not optional here even though the table would answer
        # without it: with two runs loaded an unfiltered average blends them,
        # and the result is a number that belongs to no forecast. Nothing would
        # have complained — this is the failure the migration exists to prevent,
        # reached through a direct query rather than an endpoint.
        cur.execute("""
            SELECT model_name, round(avg(mean_value)::numeric, 4), count(*)
            FROM regridded_forecast_ens
            WHERE variable_name = 'precipitation'
              AND init_time = %(init_time)s
              AND latitude BETWEEN %(min_lat)s AND %(max_lat)s
              AND longitude BETWEEN %(min_lon)s AND %(max_lon)s
            GROUP BY model_name ORDER BY model_name
        """, dict(FULL, init_time=INIT_TIME))
        for m, mean, n in cur.fetchall():
            rows.append(('forecast (as stored)', m, float(mean), n))
    finally:
        cur.close()
        api.return_db_connection(conn)
    _emit('Domain means', f'{FULL_LABEL}, every stored record of run {INIT_TIME}',
          ['side', 'source/model', 'mean', 'n rows'], rows, md,
          note="AIFS's forecast figure is a CUMULATIVE total, not a rate, so it "
               "is not comparable with the others — the audit's in-family check "
               "uses the AIFS *increment*. Kept here only to make that trap "
               "visible rather than to invite the comparison.")


def truth_field_stencils(md):
    """The property the 2026-09-04 switch established. A parity split here means
    the banker's-rounding checkerboard has come back."""
    conn = api.get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT source,
                   CASE WHEN latitude  = floor(latitude)  THEN 'whole' ELSE 'half' END,
                   CASE WHEN longitude = floor(longitude) THEN 'whole' ELSE 'half' END,
                   min(source_points), max(source_points), count(*)
            FROM regridded_observation
            WHERE latitude BETWEEN 26 AND 44 AND longitude BETWEEN -84 AND -66
            GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
        """)
        rows = cur.fetchall()
    finally:
        cur.close()
        api.return_db_connection(conn)
    _emit('Truth-field stencils (interior cells only)',
          'regridded_observation, 26-44 N 84-66 W',
          ['source', 'lat', 'lon', 'min obs', 'max obs', 'n cells'], rows, md,
          note='Every row must show the SAME min/max within a source. Different '
               'values by parity is the round-half-to-even checkerboard, which '
               'the 2026-09-04 rebuild removed.')


def _emit(title, params, headers, rows, md, note=None):
    if md:
        print(f"\n**{title}**\n")
        print(f"*{params}*\n")
        print('| ' + ' | '.join(headers) + ' |')
        print('|' + '|'.join(['---'] * len(headers)) + '|')
        for r in rows:
            print('| ' + ' | '.join('' if v is None else str(v) for v in r) + ' |')
        if note:
            print(f"\n{note}")
    else:
        print(f"\n### {title}")
        print(f"    {params}")
        w = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
        print('    ' + '  '.join(str(h).ljust(w[i]) for i, h in enumerate(headers)))
        for r in rows:
            print('    ' + '  '.join(('' if v is None else str(v)).ljust(w[i])
                                     for i, v in enumerate(r)))
        if note:
            print(f"    note: {note}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--markdown', action='store_true',
                    help='emit markdown tables for pasting into the audit')
    # `global` has to precede every use of the name in this function, so the
    # default is spelled via the module rather than read directly.
    global INIT_TIME
    ap.add_argument('--init-time', default=INIT_TIME,
                    help='the run to describe (default %(default)s). Every '
                         'figure is per-run, and with more than one loaded an '
                         'unqualified request is refused rather than guessed.')
    args = ap.parse_args()
    INIT_TIME = args.init_time
    global MODELS
    MODELS = _models_in_run(INIT_TIME)
    c = _client()
    if args.markdown:
        print('<!-- generated by Data/rederive_audit.py — do not hand-edit -->')
        print(f'<!-- run {INIT_TIME}, models {", ".join(MODELS)} -->')
        print(f'<!-- regenerate with: '
              f'python rederive_audit.py --markdown --init-time "{INIT_TIME}" -->')
    else:
        print(f'run {INIT_TIME} holds: {", ".join(MODELS)}\n')
    truth_field_stencils(args.markdown)
    point_scores(c, args.markdown)
    pooled_vs_cell_mean(c, args.markdown)
    categorical_by_threshold(c, args.markdown)
    per_cell_distribution(c, args.markdown)
    domain_means(args.markdown)


if __name__ == '__main__':
    main()
