from flask import Flask, jsonify, request, Response, g, has_request_context
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
from collections import defaultdict
import math
import io
import base64
import os
import json
import hashlib
import logging
import time
from datetime import datetime, timedelta
import scipy.stats

# ── Load .env (if present) before anything else ───────────────────────────────
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# ── Matplotlib / Cartopy (Agg backend — no display required) ──────────────────
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
# Object-oriented figure API. pyplot (plt.figure / plt.tight_layout / plt.close)
# keeps a *global* figure registry that is NOT thread-safe; under gunicorn's
# threaded workers two concurrent plot requests can interleave that global
# state and corrupt/crash a render. Building figures via Figure()+FigureCanvasAgg
# keeps each request's figure fully local. (plt.cm.* colormap lookups are
# read-only constants and remain safe to use.)
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cfeature

app = Flask(__name__)
# Cap request bodies so a malformed/oversized POST can't exhaust memory.
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))
CORS(app, origins=os.environ.get('CORS_ORIGIN', 'http://localhost:3000'))

# ── Observability ─────────────────────────────────────────────────────────────
# S2 asks for an observable service; what was here was 86 `print()` calls and no
# `logging` import, which meant no timestamps, no levels, nothing correlating
# two concurrent requests, and — worst of the three — every endpoint's
# `except Exception` discarding the traceback and printing only `str(e)`.
#
# Installed before any route is registered, so a request cannot be served
# without an id. See `observability.py` for why an inbound X-Request-ID is
# validated rather than cleaned, and for what deliberately stays a `print`.
import observability
import cyclone_metrics

observability.configure_logging()
REQUEST_STATS = observability.install(app)
log = logging.getLogger('weave.api')


# ── Metric computations ───────────────────────────────────────────────────────
# The science lives in metrics.py as pure functions (no Flask, no DB), so it can
# be tested without a database and reasoned about on its own. Imported by name
# rather than with a star so the dependency is explicit and greppable.
import run_registry
from metrics import (                                    # noqa: E402
    MODEL_ACCUM_HOURS, CUMULATIVE_PRECIP_MODELS,
    RATE_CUMULATED_PRECIP_MODELS, SSR_CAP,
    _grid_step,
    _clamp_ssr, _ssr_from_variances, _spread_inflation,
    _censor_correction, _gaussian_crps, _exceedance_probability,
    _neighbourhood_fractions, _fss_components, _fss_from_components,
    _fractions_skill_score, _fss_from_pairs,
    _precip_period_hours, _precip_lookback_hours, _increment_divisor,
    _obs_window_mean, _rebin_to_common_window, COMMON_VERIFICATION_WINDOW_HOURS,
    _infer_scaled_export_divisor, SCALED_EXPORT_DIVISOR_HOURS,
    _rebin_member_to_common_window,
    _precip_rate_series, _precip_member_rate_series,
    _categorical_summary, _region_mean, _region_pooled_metrics,
    _spatial_diff_points,
)

# ── JSON error responses ──────────────────────────────────────────────────────
# API clients always expect JSON. These ensure a malformed request or an
# uncaught exception returns a clean JSON body (not Werkzeug's HTML page /
# stack trace) in production. In debug mode the interactive debugger still
# takes precedence for uncaught 500s, which is what local dev wants.
@app.errorhandler(400)
def _err_bad_request(e):
    return jsonify({'error': 'Bad request'}), 400

@app.errorhandler(413)
def _err_too_large(e):
    return jsonify({'error': 'Payload too large'}), 413

@app.errorhandler(429)
def _err_rate(e):
    return jsonify({'error': 'Too many requests — slow down.'}), 429

@app.errorhandler(500)
def _err_internal(e):
    return jsonify({'error': 'Internal server error'}), 500


# ── Rate limiting ─────────────────────────────────────────────────────────────
# Best-effort DoS protection; no-op if flask-limiter isn't installed. With multiple
# gunicorn workers the in-memory limit is per-worker — use a shared store
# (RATE_LIMIT_STORAGE=redis://…) for a global limit in production.
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    Limiter(
        key_func=get_remote_address, app=app,
        default_limits=[os.environ.get('RATE_LIMIT', '300 per minute')],
        storage_uri=os.environ.get('RATE_LIMIT_STORAGE', 'memory://'),
    )
except Exception as _e:  # pragma: no cover
    log.warning(f"⚠️  Rate limiting disabled: {_e}")


# ── Plot caching ───────────────────────────────────────────────────────────────
# Cartopy renders are CPU-bound and re-requested often (same region/metric,
# repeat viewers). Best-effort, no-op if flask-caching isn't installed. Backend
# is env-var-selectable — swap to CACHE_TYPE=RedisCache + CACHE_REDIS_URL for a
# shared cache across multiple workers/instances; FileSystemCache (default)
# survives a Flask restart, unlike an in-memory cache. The directory lives
# outside Data/ so cache writes don't sit in the same tree as the source files.
cache = None
try:
    from flask_caching import Cache
    _cache_dir = os.path.join(os.path.dirname(__file__), '..', '.cache', 'plots')
    os.makedirs(_cache_dir, exist_ok=True)
    cache = Cache(app, config={
        'CACHE_TYPE':       os.environ.get('CACHE_TYPE', 'FileSystemCache'),
        'CACHE_DIR':        _cache_dir,
        'CACHE_THRESHOLD':  int(os.environ.get('CACHE_THRESHOLD', 500)),
        'CACHE_REDIS_URL':  os.environ.get('CACHE_REDIS_URL', ''),
    })
except Exception as _e:  # pragma: no cover
    log.warning(f"⚠️  Plot caching disabled: {_e}")

def _cache_get(key):
    if cache is None:
        return None
    try:
        return cache.get(key)
    except Exception as _e:
        log.warning(f"⚠️  Cache read failed: {_e}")
        return None

def _data_version(cursor):
    """A short token that changes whenever the loaded forecast data changes.

    The metric endpoints are deterministic — a pure function of the request and
    the database — so they are safe to cache. The hard part is invalidation, and
    a TTL alone gets it wrong in both directions: too long and a re-run of
    `regrid_members.py` serves numbers from the old data, too short and the
    expensive queries this exists to avoid run anyway.

    So the cache key carries a version derived from `forecast_run_registry`,
    which records one row per (model, variable, init_time) with the load time,
    member count and hour range. Reload or regrid anything and `loaded_at` moves,
    the version changes, and every affected key is orphaned in the same instant —
    no expiry to wait for and no flush to remember. Stale entries age out under
    the TTL that is still applied as a backstop.

    Returns 'noreg' when the registry is absent, which is honest rather than
    silent: on a part-migrated database the version cannot see data changes, so
    the TTL is doing all the work. Cached per request in `g` — this is read once
    per endpoint and the query is over nine rows, but not free.
    """
    if not has_request_context():
        return _data_version_uncached(cursor)
    cached = g.get('data_version')
    if cached is None:
        cached = _data_version_uncached(cursor)
        g.data_version = cached
    return cached


def _data_version_uncached(cursor):
    try:
        cursor.execute("SELECT to_regclass('forecast_run_registry') IS NOT NULL AS ok")
        if not cursor.fetchone()['ok']:
            return 'noreg'
        cursor.execute("""
            SELECT model_name, variable_name, init_time, loaded_at,
                   n_members, hour_min, hour_max
            FROM forecast_run_registry
            ORDER BY model_name, variable_name, init_time
        """)
        rows = [tuple(str(v) for v in r.values()) for r in cursor.fetchall()]

        # The truth field, too. The registry describes the FORECASTS, and a score
        # depends on both sides — so a registry-only version misses a change to
        # the observations entirely. That is not hypothetical: on 2026-09-04 the
        # truth field was replaced (`regridded_observation` swapped for the
        # rebuilt one, §7) with the registry untouched, and every cached score
        # would have kept serving pre-switch numbers indefinitely.
        #
        # The sum is the discriminating part — the swap preserved the row count
        # and every timestamp and changed only the values, so a count-and-time
        # fingerprint would have missed it. It caught the real swap:
        # 193378.266 -> 192735.753 for wind. About 50 ms, once per request.
        #
        # `value::numeric`, NOT `SUM(value)` on the float. A float SUM is not
        # deterministic here: PostgreSQL aggregates in parallel, so the addition
        # order varies between identical queries and the last digits move
        # (…83437, …83435, …83437 on three consecutive runs). That made the
        # version — and therefore every cache key — different on every request,
        # so the cache never hit once and the app paid this query for nothing.
        # Measured, not assumed: three consecutive calls returned three different
        # versions. Numeric addition is exact and order-independent.
        cursor.execute("""
            SELECT source, COUNT(*) AS n, MAX(obs_time) AS t,
                   SUM(value::numeric) AS s
            FROM regridded_observation
            GROUP BY source ORDER BY source
        """)
        rows += [('obs',) + tuple(str(v) for v in r.values())
                 for r in cursor.fetchall()]
        return hashlib.sha256(repr(rows).encode()).hexdigest()[:12]
    except Exception as _e:                                   # pragma: no cover
        # A cache key is not worth failing a request over. An unstable version
        # only costs cache misses.
        log.warning(f"⚠️  data version unavailable, caching by TTL alone: {_e}")
        return 'nover'


def _metric_cache_key(prefix, cursor, **parts):
    """A cache key for a deterministic metric endpoint.

    Everything that changes the answer has to be in here. Two are easy to
    forget and both were, historically:

    - **`init_time`.** Before the run identity existed there was one run and the
      question did not arise; with two, a key without it serves one run's numbers
      for another — the exact silent cross-run error `migrate_init_time.py` was
      written to remove. Pass it in `parts`.
    - **the data version**, above, so a reload invalidates rather than waiting.

    Floats are rounded on the way in by the callers rather than here, because how
    coarse is safe depends on the parameter: a bounding box tolerates 2 dp, a
    threshold does not.
    """
    payload = json.dumps(parts, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"{prefix}:{_data_version(cursor)}:{digest}"


# How long a cached metric result may outlive its data version. The version does
# the real invalidation; this only bounds how long an orphaned entry occupies
# space, so it can be generous.
METRIC_CACHE_TTL = int(os.environ.get('METRIC_CACHE_TTL', 6 * 3600))

# ── Row caps on point-list responses ─────────────────────────────────────────
# `/api/forecast-data` and `/api/wind-data` return one record per native grid
# cell, and the native grid is a property of whatever data was loaded, not of
# anything this code controls. Today the worst case is UKMO wind at 7,597 cells
# and 946 KB; a finer model or a wider domain would grow that without limit, and
# nothing in the request can bound it.
#
# The cap is on CELLS, not rows. These queries return one row per (cell, hour)
# and group into cells afterwards, so a plain `LIMIT` on rows would cut the last
# cell in half and hand back a cell with hours missing — a subtly wrong value
# rather than a visibly short list, which is the worse failure. The SQL limit is
# therefore generous enough to bound the database's work, and the trim to whole
# cells happens after grouping.
#
# Set well above anything the current data produces, so this changes no
# behaviour today and exists to stop the unbounded case.
POINT_LIST_MAX_CELLS = int(os.environ.get('POINT_LIST_MAX_CELLS', 20000))


def _cap_cells(by_cell, limit=None):
    """(kept, truncated) — whole cells only, deterministically ordered.

    Sorting before trimming matters: without it, which cells survive depends on
    dict insertion order, so two identical requests could return different halves
    of the domain and the cache would key them the same.
    """
    limit = POINT_LIST_MAX_CELLS if limit is None else limit
    if len(by_cell) <= limit:
        return by_cell, False
    kept = dict(sorted(by_cell.items())[:limit])
    return kept, True


def _point_list_response(result, truncated, what=''):
    """A bare-array response, with truncation reported in headers.

    Headers rather than a wrapper object because these endpoints return a JSON
    array and the frontend reads it as one; changing the shape to report an edge
    case would break every caller for the common case. A client that ignores the
    header gets the capped list, which is the same thing it would have got from
    a server that simply could not return more.

    **No total is reported, deliberately.** The obvious header — "showing N of
    M" — cannot be filled honestly here: the query fetches `limit + 1` rows
    precisely so that overflow is detectable without reading the whole table, so
    the only total available is `limit + 1`. An earlier version reported that,
    which said "100 of 101" for a request whose real total was 7,597 — worse than
    silence, because it made the loss look negligible. Getting the true figure
    needs a second COUNT query, which is not worth paying to decorate an error
    path; the caller is told it is incomplete and what the limit was, which is
    what they need to act.
    """
    resp = jsonify(result)
    resp.headers['X-Row-Count'] = str(len(result))
    resp.headers['X-Row-Limit'] = str(POINT_LIST_MAX_CELLS)
    if truncated:
        resp.headers['X-Truncated'] = 'true'
        # Loud on the server too: a truncated map that nobody noticed is exactly
        # the outcome the cell-wise trim above is meant to avoid.
        #
        # This used to be a `print(..., flush=True)`, and the flush was load
        # bearing: stdout is block-buffered when the server's output is
        # redirected to a file, which hid this line the first time it fired.
        # `logging` flushes on emit and writes to stderr, so the reason is gone
        # with the print — recorded here so nobody re-adds it as a kwarg
        # `Logger.warning` does not take, which is exactly how this line broke
        # seven tests during the conversion.
        log.warning("point list truncated%s: returned %d cells, the limit "
                    "(POINT_LIST_MAX_CELLS=%d); there are more",
                    what, len(result), POINT_LIST_MAX_CELLS)
    return resp


# The query parameters a spatial metric's answer can depend on. Keying on the
# whole of `request.args` would let an unrelated parameter — a cache-buster, an
# analytics tag — fragment the cache into single-use entries; keying on too few
# would serve one threshold's answer for another. This is the list the dispatch
# functions actually read, minus the ones already named explicitly in the key.
SPATIAL_METRIC_CACHE_ARGS = frozenset({
    'hour', 'hour_min', 'hour_max', 'threshold_mm_6h', 'threshold_ms',
    'radius', 'member',
})


def _body_cache_key(prefix, cursor, body, fields):
    """Key a POST metric endpoint on the fields of its body that matter.

    Named fields rather than the whole body, for the same reason the GET version
    filters `request.args`: an extra key the endpoint ignores would fragment the
    cache into single-use entries. `models` is sorted, since asking for
    [AIFS, GEFS] and [GEFS, AIFS] is the same question — the endpoints already
    sort it internally.

    `init_time` is included whenever the caller sent one. When they did not, the
    resolution depends on what is loaded, which the data version already covers.
    """
    parts = {k: body.get(k) for k in fields if k in body}
    if isinstance(parts.get('models'), list):
        parts['models'] = sorted(str(m) for m in parts['models'])
    if isinstance(parts.get('metrics'), list):
        parts['metrics'] = sorted(str(m) for m in parts['metrics'])
    return _metric_cache_key(prefix, cursor, **parts)


def _cache_set(key, value, timeout):
    if cache is None:
        return
    try:
        cache.set(key, value, timeout=timeout)
    except Exception as _e:
        log.warning(f"⚠️  Cache write failed: {_e}")


# ── Lightweight input allowlist ───────────────────────────────────────────────
# Queries are parameterised (injection-safe); this is defence-in-depth + a clean
# 400 for obviously-malformed model/variable tokens instead of an empty result.
import re
_TOKEN_RE = re.compile(r'^[A-Za-z0-9_]{1,40}$')
def _bad_token(*vals):
    return any(v is not None and not _TOKEN_RE.match(str(v)) for v in vals)

DB_CONFIG = {
    'dbname':   os.environ.get('DB_NAME',     'weave_weather'),
    'user':     os.environ.get('DB_USER',     'k.aggarwal'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'host':     os.environ.get('DB_HOST',     'localhost'),
    'port':     int(os.environ.get('DB_PORT', 5432)),
}

import psycopg2.pool

# ThreadedConnectionPool is safe for multi-threaded Flask serving.
#
# The pool is PER WORKER, so the number that has to stay under PostgreSQL's
# `max_connections` is `workers × DB_POOL_MAX`, not DB_POOL_MAX. The old
# defaults (5/20) were chosen for the 4-worker case in DEPLOY.md §3 and hold
# there: 4 × 20 = 80 < 100. They do NOT hold at the worker counts the review
# deployment's larger tiers assume — 6 × 20 = 120 and 8 × 20 = 160 — where
# workers fail to acquire a connection under exactly the load the bigger
# instance was bought to carry.
#
# So the defaults are now 2/8, which is safe across every documented tier
# (8 × 8 = 64 < 100) and still covers the region "Compute All Maps" burst of
# ~10 concurrent requests, since those queue on the pool rather than failing
# (`_pool_getconn` retries). Raising `max_connections` instead is the other
# valid fix, and costs memory on a box that is also running the database.
#
# `_check_pool_headroom` verifies the arithmetic against the live server at
# startup rather than trusting this comment to be read.
# Named rather than inlined into the `os.environ.get` calls so a test can pin
# the shipped default. Reading the *effective* value instead would pass against
# whatever a local .env happens to set, which is not the thing worth asserting.
DB_POOL_MIN_DEFAULT = 2
DB_POOL_MAX_DEFAULT = 8

DB_POOL_MIN = int(os.environ.get('DB_POOL_MIN', DB_POOL_MIN_DEFAULT))
DB_POOL_MAX = int(os.environ.get('DB_POOL_MAX', DB_POOL_MAX_DEFAULT))

connection_pool = psycopg2.pool.ThreadedConnectionPool(
    DB_POOL_MIN, DB_POOL_MAX, **DB_CONFIG
)


def _worker_count():
    """How many API processes will share this database.

    `WEB_CONCURRENCY` is the variable gunicorn itself reads, so a deployment
    that sets workers the documented way is understood without extra
    configuration. Falls back to 1, which is the dev case and cannot be wrong
    in the dangerous direction: it under-reports the risk only when the
    variable is unset, and then there is nothing to report.
    """
    for name in ('WEB_CONCURRENCY', 'GUNICORN_WORKERS'):
        raw = os.environ.get(name)
        if raw:
            try:
                return max(1, int(raw))
            except ValueError:
                pass
    return 1


def _check_pool_headroom(cursor):
    """Compare `workers × DB_POOL_MAX` against the server's `max_connections`.

    Returns a dict for `/api/health`, so the condition is checkable on a
    deployed instance rather than only in a startup log nobody reads. The
    failure this catches is quiet and load-dependent: everything works until
    enough users arrive at once, and then requests error out with a pool
    exhaustion that looks like a database problem.

    `superuser_reserved_connections` is subtracted because those slots are not
    available to this role, so the usable ceiling is lower than
    `max_connections` suggests.
    """
    cursor.execute("SHOW max_connections")
    max_conn = int(cursor.fetchone()[0])
    try:
        cursor.execute("SHOW superuser_reserved_connections")
        reserved = int(cursor.fetchone()[0])
    except Exception:
        reserved = 0

    workers = _worker_count()
    demand  = workers * DB_POOL_MAX
    usable  = max_conn - reserved
    return {
        'workers':             workers,
        'pool_max_per_worker': DB_POOL_MAX,
        'peak_connections':    demand,
        'max_connections':     max_conn,
        'usable_connections':  usable,
        'headroom':            usable - demand,
        'safe':                demand <= usable,
    }


# Phase 5's retention decision, 2026-10-01: **no retention limit yet, revisit at
# 250 GB.** That is a real decision rather than a deferral, but only if something
# announces the threshold — "revisit at 250 GB" is otherwise a note nobody reads
# at the moment it matters, which is mid-load.
#
# The number is the user's, chosen against a measured 123.52 GB holding three
# initialisations and a then-measured 55.30 GB for a three-model run. So the
# threshold is a little over two runs away, and crossing it is a *loading*
# decision. (The database is 128.88 GB as of 2026-10-08 and a full run 58.00 GB;
# the headroom check reads both live, so only the per-run figure below is a
# constant that can rot.)
#
# `DATA_EXPANSION_DESIGN.md` phase 5 carries the archive options this is meant to
# prompt; none is implemented, because none was chosen.
DB_SIZE_REVISIT_GB = float(os.environ.get('WEAVE_DB_SIZE_REVISIT_GB', 250))

# What a THREE-MODEL run costs, measured 2026-10-01 on the 2025-09-16 00Z run
# (AIFS + GEFS + UKMO, precipitation and wind): 116,423,050 native rows and
# 42,546,970 regridded member rows, weighted by each table's measured
# bytes-per-row — 55.30 GB.
#
# **Re-measured 2026-10-08 after §52 added `idx_rfm_cell_member_hour`.** That
# index is 5.09 GB across the 17 model-run-variable combinations loaded, so a
# full run now carries about 2.70 GB of it: **58.00 GB**. A new index changes
# what a future run costs, and this constant is the only place that says so —
# it was still quoting the pre-index figure the day after, which would have
# under-reported the last run before the threshold.
#
# The planning figure is this rather than the mean of what is loaded, and the
# difference is not pedantic. The mean today is well under it because one of the
# three initialisations is a partial 06Z run costing 8.49 GB, so dividing
# headroom by the mean answers "how many runs like the ones I have" when the
# question is "does another real run fit" — and reports 3 where the answer is 2.
# `DATA_EXPANSION_DESIGN.md` phase 5 states the same warning about the cheap
# UKMO-only run: do not read the cheapest thing in the database as headroom.
#
# Re-measure after any index change:
#   SELECT round(pg_relation_size('idx_rfm_cell_member_hour')/1024.0^3
#                / (SELECT count(*) FROM forecast_run_registry) * 9, 2);
DB_GB_PER_FULL_RUN = float(os.environ.get('WEAVE_DB_GB_PER_RUN', 58.00))


def _check_storage_headroom(cursor):
    """Report database size against the retention threshold, for `/api/health`.

    The same shape of check as `_check_pool_headroom` above and for the same
    reason: a condition that is only written down is a condition that is
    discovered too late. The pool one predicts a failure under concurrent load;
    this one predicts a failure under the next ingest, where running out of disk
    partway through a 55 GB load is both slow to notice and tedious to unwind.

    Reports two per-run figures, because they answer different questions and
    confusing them is how a threshold gets crossed mid-load:

        `mean_gb_per_run`  descriptive — the footprint over the initialisations
                           actually loaded, partial ones included.
        `gb_per_full_run`  the planning figure, a measured three-model run.

    `runs_until_revisit` divides by the second. Using the mean would report 3
    where the answer is 2, because a partial 06Z run drags the mean down by a
    third. See `DB_GB_PER_FULL_RUN`.

    `runs` counts initialisations rather than (model, run) pairs; `forecast_runs`
    holds one row per model per init, so counting it directly would divide the
    footprint by the wrong number.

    Deliberately not a failure: `safe` goes False and the whole endpoint stays
    `healthy`, because being past the threshold means a decision is due, not that
    anything is broken.
    """
    cursor.execute("SELECT pg_database_size(current_database())")
    size_gb = cursor.fetchone()[0] / 1024 ** 3
    cursor.execute("SELECT COUNT(*) FROM forecast_runs")
    pairs = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT initialization_time) FROM forecast_runs")
    runs = cursor.fetchone()[0]
    headroom = DB_SIZE_REVISIT_GB - size_gb
    return {
        'database_gb':      round(size_gb, 2),
        'revisit_at_gb':    DB_SIZE_REVISIT_GB,
        'headroom_gb':      round(headroom, 2),
        'runs':             runs,
        'model_runs':       pairs,
        'mean_gb_per_run':  round(size_gb / runs, 2) if runs else 0.0,
        'gb_per_full_run':  DB_GB_PER_FULL_RUN,
        'runs_until_revisit': (max(0, int(headroom // DB_GB_PER_FULL_RUN))
                               if DB_GB_PER_FULL_RUN > 0 else None),
        'safe':             size_gb < DB_SIZE_REVISIT_GB,
    }


def _pool_getconn():
    """getconn with a short bounded retry. ThreadedConnectionPool.getconn raises
    PoolError immediately when every connection is checked out; a brief wait lets
    an in-flight request return one instead of surfacing an instant 500. Tuned
    for the region 'Compute All Maps' burst (several concurrent requests)."""
    retries = int(os.environ.get('DB_POOL_RETRIES', 5))
    delay   = float(os.environ.get('DB_POOL_RETRY_DELAY', 0.25))
    last_err = None
    for attempt in range(retries):
        try:
            return connection_pool.getconn()
        except psycopg2.pool.PoolError as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(delay)
    raise last_err


def get_db_connection():
    # This API is read-only, so we run every pooled connection in autocommit
    # mode. Without it, psycopg2 opens an implicit transaction on the first
    # statement; if any query then raises, the connection is returned to the
    # pool stuck in an aborted-transaction state and the NEXT request that
    # reuses it fails with "current transaction is aborted" — one bad request
    # poisons the pool. Autocommit means a failed statement rolls itself back
    # and the connection stays usable.
    conn = _pool_getconn()
    try:
        if not conn.autocommit:
            conn.rollback()          # clear any half-open txn before switching
            conn.autocommit = True
    except Exception:
        # Connection is unusable — discard it and hand back a fresh one.
        try:
            connection_pool.putconn(conn, close=True)
        except Exception:
            pass
        conn = _pool_getconn()
        conn.autocommit = True
    return conn


def return_db_connection(conn):
    if conn is None:
        return
    try:
        # Dispose of a broken connection instead of poisoning the pool with it.
        broken = getattr(conn, 'closed', 0)
        connection_pool.putconn(conn, close=bool(broken))
    except Exception:
        pass


# ── Request-parameter validation helpers ──────────────────────────────────────
# These parse+validate BEFORE the DB try-block so a bad value yields a clean 400
# rather than an uncaught cast error surfacing as a generic 500.
def _valid_member(member):
    """A member selector is 'mean', 'std', or an integer index."""
    if member in ('mean', 'std'):
        return True
    try:
        int(member)
        return True
    except (TypeError, ValueError):
        return False


def _parse_bbox(args):
    """Parse + sanity-check min/max lat/lon from request args.

    Returns (bbox_dict, None) on success or (None, (json, status)) on error, so
    callers can `bbox, err = _parse_bbox(...); if err: return err`.
    """
    try:
        min_lat = float(args.get('min_lat',  25))
        max_lat = float(args.get('max_lat',  45))
        min_lon = float(args.get('min_lon', -85))
        max_lon = float(args.get('max_lon', -65))
    except (TypeError, ValueError):
        return None, (jsonify({'error': 'lat/lon bounds must be numeric'}), 400)
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        return None, (jsonify({'error': 'latitude must be in [-90, 90]'}), 400)
    if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
        return None, (jsonify({'error': 'longitude must be in [-180, 180]'}), 400)
    if min_lat >= max_lat or min_lon >= max_lon:
        return None, (jsonify({'error': 'min bound must be strictly less than max bound'}), 400)
    return {'min_lat': min_lat, 'max_lat': max_lat,
            'min_lon': min_lon, 'max_lon': max_lon}, None


def _parse_latlon(src, lat_default=None, lon_default=None):
    """Parse + range-check a single lat/lon pair, the point-endpoint counterpart
    of _parse_bbox.

    The bbox path has range-checked since the P1 input-validation work; the point
    path never did, so `lat=999` returned 200 with `cell: [999.0, -75.0]` — a
    coordinate that is not a place, echoed back as though it were a grid cell.
    Same contract as _parse_bbox: `(lat, lon), err = _parse_latlon(...)`.
    """
    lat_raw = src.get('lat', lat_default)
    lon_raw = src.get('lon', lon_default)
    if lat_raw is None or lon_raw is None:
        return None, (jsonify({'error': 'lat and lon are required'}), 400)
    try:
        lat, lon = float(lat_raw), float(lon_raw)
    except (TypeError, ValueError):
        return None, (jsonify({'error': 'lat and lon must be numeric'}), 400)
    if not math.isfinite(lat) or not math.isfinite(lon):
        return None, (jsonify({'error': 'lat and lon must be finite'}), 400)
    if not -90 <= lat <= 90:
        return None, (jsonify({'error': 'latitude must be in [-90, 90]'}), 400)
    if not -180 <= lon <= 180:
        return None, (jsonify({'error': 'longitude must be in [-180, 180]'}), 400)
    return (lat, lon), None

























# A member count is fixed for a run, so it is cached per process. The key is the
# run, not the model: a later run can be loaded with a different ensemble size,
# and keying on the model alone would serve the first one forever.
_ENSEMBLE_SIZE_CACHE = {}

# The UI's `wind` is not a stored variable — the registry records the two
# components. Either answers "how many members", so the first is enough.
_REGISTRY_VARIABLE = {'wind': 'wind_u_10m'}


def _ensemble_size(cursor, model_name, variable=None, init_time=None):
    """Number of ensemble members in a run, or None if unknown.

    Reads `forecast_run_registry`, which records the count at load time. With no
    `init_time` it answers for the newest run of that model, which is what the
    two callers that cannot name one want.

    **This was 74 seconds and is now 11 milliseconds** (NEXT_STEPS.md §50). It
    used to COUNT(DISTINCT ensemble_member) over `forecast_data` — 240M rows,
    73 GB — at each run's first lead time, and the comment above it claimed
    "2-6 s". The planner could not use an index for the correlated
    `(SELECT MIN(forecast_hour) ... WHERE run_id = fr.run_id)`, so every call
    **sequentially scanned the whole table once per run of that model**: three
    scans, 9.15M buffers each, 25 s each. It was the single largest cost in the
    app — 172 of the 179 s a three-model region request spent — and it was
    invisible in development because the process cache made it a once-per-model
    charge that the first request paid and nobody timed.

    Values verified equal to the old query's on 2026-10-07, per run rather than
    per model: AIFS 50 at all three runs, GEFS 30, UKMO 18.
    """
    reg_var = _REGISTRY_VARIABLE.get(variable, variable)
    key = (model_name, reg_var, init_time)
    if key in _ENSEMBLE_SIZE_CACHE:
        return _ENSEMBLE_SIZE_CACHE[key]
    n = None
    try:
        where  = ['model_name = %s', 'n_members IS NOT NULL']
        params = [model_name]
        if reg_var is not None:
            where.append('variable_name = %s')
            params.append(reg_var)
        if init_time is not None:
            where.append('init_time = %s')
            params.append(init_time)
        cursor.execute(f"""
            SELECT n_members FROM forecast_run_registry
            WHERE {' AND '.join(where)}
            ORDER BY init_time DESC
            LIMIT 1
        """, tuple(params))
        row = cursor.fetchone()
        if row:
            n = int(row['n_members'] if isinstance(row, dict) else row[0])
        elif reg_var is not None or init_time is not None:
            # A run the registry does not describe for this variable. The count
            # is a property of the run, so fall back to the model's newest
            # registered run rather than to the table scan below.
            return _ensemble_size(cursor, model_name)
    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        log.warning(f"⚠️  ensemble size lookup failed for {model_name}: {e}")
    n = n if (n and n > 1) else None
    _ENSEMBLE_SIZE_CACHE[key] = n
    return n


def available_runs(cursor):
    """[(model, variable, init_time, ...)] from the run registry, newest first.

    Reads `forecast_run_registry`, which `migrate_init_time.py` populates at load
    time. Falls back to a DISTINCT over the ens table when the registry is absent
    so a database migrated only part-way still answers, rather than making
    `/api/runs` the one endpoint that needs the newest schema.
    """
    cursor.execute("SELECT to_regclass('forecast_run_registry') IS NOT NULL AS ok")
    if cursor.fetchone()['ok']:
        cursor.execute("""
            SELECT model_name, variable_name, init_time,
                   n_members, hour_min, hour_max, export_divisor_h
            FROM forecast_run_registry
            ORDER BY init_time DESC, model_name, variable_name
        """)
        return [dict(r) for r in cursor.fetchall()]
    cursor.execute("""
        SELECT model_name, variable_name, init_time,
               MAX(n_members) AS n_members,
               MIN(forecast_hour) AS hour_min, MAX(forecast_hour) AS hour_max,
               NULL::real AS export_divisor_h
        FROM regridded_forecast_ens
        GROUP BY model_name, variable_name, init_time
        ORDER BY init_time DESC, model_name, variable_name
    """)
    return [dict(r) for r in cursor.fetchall()]


class RunSelectionError(Exception):
    """The request does not identify a single forecast run. Answered with 400."""


@app.errorhandler(RunSelectionError)
def _handle_run_selection_error(err):
    # One handler rather than a try/except in every endpoint: the resolver is
    # reached from eight of them through three different helpers, and a 500 here
    # would read as a server fault when it is a request that needs a parameter.
    return jsonify({'error': str(err), 'hint': 'GET /api/runs lists what is loaded'}), 400


_UNSET = object()


def _requested_init_time():
    """The `init_time` the current request asked for, or None.

    Read here rather than threaded through eight endpoint signatures. GET
    endpoints carry it in the query string, POST endpoints in the JSON body,
    which is where every other parameter of theirs already lives.

    Returns None outside a request context: the metric helpers are also called
    directly by the unit tests, and a resolver that only works inside Flask
    would make those tests fail for a reason unrelated to what they check.
    """
    if not has_request_context():
        return None
    if request.method == 'POST':
        body = request.get_json(silent=True)
        return (body or {}).get('init_time') if isinstance(body, dict) else None
    return request.args.get('init_time')


def _resolve_init_time(cursor, model_name, requested=_UNSET):
    """The initialisation time a request is about, as a datetime.

    A supplied `init_time` is honoured exactly and validated against what is
    loaded, so a typo raises rather than returning an empty map that reads as
    "no data here".

    When it is absent, this defaults to the model's only run **when there is
    exactly one**, and raises when there are several.

    That last rule is a deliberate departure from DATA_EXPANSION_DESIGN.md phase
    2, which says to require the parameter unconditionally and 400 whenever it is
    missing. The reason a default is dangerous is ambiguity — "the latest run"
    silently picks one of several. With exactly one run loaded there is nothing
    to pick between, so defaulting is a statement of fact rather than a guess,
    and refusing would break every existing caller (and 600-odd tests) to prevent
    an error that cannot occur. Gating on ambiguity instead means the API becomes
    strict automatically at the moment strictness starts to matter: load a second
    run and every caller that has not been updated fails loudly, with a message
    naming /api/runs, instead of receiving a plausible wrong number.

    The frontend sends the parameter regardless, so it is already correct for the
    two-run case rather than relying on this fallback.
    """
    if requested is _UNSET:
        requested = _requested_init_time()

    # Per-request cache in Flask g, keyed by the requested value as well as the
    # model: this is reached several times per request (once per model per query,
    # and _member_cases_by_cell is called repeatedly), and the resolver now runs
    # a two-row query rather than a LIMIT 1, so re-deriving it is not free.
    if not has_request_context():
        return _resolve_init_time_uncached(cursor, model_name, requested)
    cache = g.get('init_time_cache')
    if cache is None:
        g.init_time_cache = {}
        cache = g.init_time_cache
    key = (model_name, requested)
    if key in cache:
        return cache[key]

    resolved = _resolve_init_time_uncached(cursor, model_name, requested)
    cache[key] = resolved
    return resolved


def _resolve_init_time_uncached(cursor, model_name, requested):
    if requested:
        try:
            wanted = (datetime.fromisoformat(str(requested).replace('Z', '+00:00'))
                      .replace(tzinfo=None))
        except (ValueError, TypeError):
            raise RunSelectionError(
                f"init_time is not an ISO timestamp: {requested!r}")
        cursor.execute("""
            SELECT 1 FROM forecast_runs fr
            JOIN models m ON m.model_id = fr.model_id
            WHERE m.model_name = %s AND fr.initialization_time = %s
        """, (model_name, wanted))
        if not cursor.fetchone():
            raise RunSelectionError(
                f"no {model_name} run at init_time {wanted.isoformat()}")
        return wanted

    cursor.execute("""
        SELECT fr.initialization_time
        FROM forecast_runs fr
        JOIN models m ON m.model_id = fr.model_id
        WHERE m.model_name = %s
        ORDER BY fr.initialization_time DESC
    """, (model_name,))
    rows = cursor.fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise RunSelectionError(
            f"{model_name} has {len(rows)} loaded runs, so init_time is required. "
            f"Newest is {rows[0]['initialization_time'].isoformat()}.")
    return rows[0]['initialization_time']


def get_model_run_id(cursor, model_name, requested=_UNSET):
    """The `forecast_runs.run_id` for the run **this request is about**.

    Resolution is delegated to `_resolve_init_time`, so this shares one
    implementation with every other run-scoped read: a supplied `init_time` is
    honoured and validated, a single loaded run is defaulted to as a statement
    of fact, and ambiguity raises rather than picking.

    **This used to be `ORDER BY initialization_time DESC LIMIT 1`** — a third
    inline copy of the silent "latest run" lookup that the `init_time` migration
    exists to remove, and one that survived both earlier passes at removing it
    (see `NEXT_STEPS.md` §8, which notes it took two). It was invisible while one
    run was loaded and became a wrong answer the moment a second arrived: a
    request naming 00Z was served 06Z data, all 4,426 cells of it, with no error
    anywhere. Five endpoints read it, including `/api/forecast-data`, so **the
    map ignored the run selector entirely** while the scored endpoints honoured
    it — which is why this survived being "verified in the app".

    Returning a run_id for a run that holds no rows for the requested variable
    is correct, not a gap: `/api/wind-data` at a precipitation-only run should
    answer empty rather than quietly serve another run's wind.
    """
    init_time = _resolve_init_time(cursor, model_name, requested)
    if init_time is None:
        return None

    # Cache per-request in Flask g so repeated calls within the same HTTP
    # request (e.g. multiple dispatch functions) hit the DB only once. Keyed on
    # the run as well as the model, because one request can now legitimately ask
    # about more than one.
    key = (model_name, init_time)
    cache = None
    if has_request_context():
        cache = g.get('run_id_cache')
        if cache is None:
            g.run_id_cache = {}
            cache = g.run_id_cache
        if key in cache:
            return cache[key]

    cursor.execute("""
        SELECT fr.run_id
        FROM forecast_runs fr
        JOIN models m ON fr.model_id = m.model_id
        WHERE m.model_name = %s AND fr.initialization_time = %s
    """, (model_name, init_time))
    result = cursor.fetchone()
    run_id = result['run_id'] if result else None
    if cache is not None:
        cache[key] = run_id
    return run_id


def _run_pairs_sql(cursor, models, alias='u', requested=_UNSET):
    """(predicate, params, resolved) restricting a multi-model query to one run each.

    `requested` defaults to `_UNSET`, not `None`, and the difference is not
    cosmetic. `_resolve_init_time` only consults the request body when it is
    handed `_UNSET`; an explicit `None` means "no init_time was asked for" and
    sends it to the single-run fallback instead. Defaulting to `None` here
    therefore *discarded the `init_time` the caller had already sent*, and was
    invisible for as long as every model had exactly one run — the fallback
    returned the right answer for the wrong reason. It surfaced the moment a
    second AIFS run was loaded (2026-09-28), as a 400 on
    `/api/compare/timeseries` and `/api/compare/spatial-agreement` saying
    init_time was required by a caller that had supplied it.

    The comparison endpoints select `model_name = ANY(...)`, and models are not
    required to share an initialisation time — so a single `init_time = %s` would
    be wrong for all but one of them, and omitting the filter entirely lets a
    model's rows be compared against another model's run. Both are the silent
    mis-attribution this migration exists to remove.

    Expressed as a tuple-membership test over two unnested arrays so it stays one
    parameterised statement: no SQL is interpolated from the model list, which
    reaches this as an allowlisted identifier but should not have to be trusted
    twice.
    """
    resolved = {}
    for m in models:
        t = _resolve_init_time(cursor, m, requested)
        if t is not None:
            resolved[m] = t
    predicate = (f" AND ({alias}.model_name, {alias}.init_time) IN "
                 f"(SELECT * FROM unnest(%s::text[], %s::timestamp[]))")
    params = [list(resolved.keys()), list(resolved.values())]
    return predicate, params, resolved


def _fcst_speed_sql(is_wind, base_cols):
    """SQL fragments to select forecast mean/std from regridded_forecast_ens (aliased
    `u`), deriving wind SPEED from the u/v component rows for wind.

    Verification/comparison compares against the observed scalar wind_speed, so
    the forecast side must also be a speed — not the raw u-component (the old
    bug). On the aggregate tables there are no per-member speeds, so speed is
    approximated from the component means/spreads:
        mean ≈ |mean vector| = √(mean_u² + mean_v²)
        std  ≈ √(σu² + σv²)
    (The point SSR path via forecast_data computes the exact per-member speed.)

    Returns (select_cols, from_clause, var_predicate, v_notnull). Callers keep
    their own WHERE using `u.*` columns; for precipitation the variable name is a
    bound param, for wind it is hard-coded so no extra param is needed. Every
    returned fragment is a controlled literal — no user input is interpolated.
    """
    if is_wind:
        select_cols = (f"{base_cols}, "
                       "SQRT(POWER(u.mean_value, 2) + POWER(v.mean_value, 2)) AS mean_value, "
                       "SQRT(POWER(u.std_dev, 2)    + POWER(v.std_dev, 2))    AS std_dev")
        from_clause = ("regridded_forecast_ens u "
                       "JOIN regridded_forecast_ens v "
                       "ON v.model_name = u.model_name AND v.forecast_hour = u.forecast_hour "
                       # Same run on both sides. Without this the u/v pairing
                       # would cross initialisations once a second run is loaded,
                       # composing a wind speed from two different forecasts —
                       # and the caller's own init_time filter on `u` would not
                       # catch it, because it says nothing about `v`.
                       "AND v.init_time = u.init_time "
                       "AND v.latitude = u.latitude AND v.longitude = u.longitude "
                       "AND v.variable_name = 'wind_v_10m'")
        return (select_cols, from_clause, "u.variable_name = 'wind_u_10m'",
                "AND v.mean_value IS NOT NULL AND v.std_dev IS NOT NULL")
    return (f"{base_cols}, u.mean_value, u.std_dev",
            "regridded_forecast_ens u", "u.variable_name = %s", "")


def _pearson(xs, ys):
    """Pearson r over two equal-length sequences, rounded, or None.

    None when there are fewer than two pairs or either series has no variance —
    a zero denominator is "there is nothing to correlate", which must not be
    reported as 0.0 ("no relationship").
    """
    n = len(xs)
    if n < 2 or len(ys) != n:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) *
                    sum((y - my) ** 2 for y in ys))
    return round(num / den, 4) if den > 1e-10 else None


# Lead times the spatial correlation map scores at. A fixed set, so the models
# stay comparable — an hourly model would otherwise correlate over 24 samples
# against a 6-hourly model's 4, and the region view puts those side by side.
CORRELATION_LEAD_HOURS = (0, 6, 12, 18, 24, 48, 72, 96, 120, 144, 168)


def _window_source_hours(model_name, targets, is_wind,
                         window=COMMON_VERIFICATION_WINDOW_HOURS):
    """Native forecast hours needed to build a score at each hour in `targets`.

    Purely a query-pruning helper: the member grid is members x cells x hours, so
    fetching every lead time to score one is the difference between a 5 s map and
    a 55 s map. Verification runs on a common `window`, so a target needs every
    native record whose own span lies inside (target - window, target] — six
    hourly UKMO records, or the single 6 h record AIFS and GEFS emit — plus, for a
    cumulative model, the record one period earlier to difference against. Wind is
    instantaneous: no window, so just the target.
    """
    if is_wind:
        return sorted({h for h in targets if h >= 0})

    cadence  = max(1, MODEL_ACCUM_HOURS.get(model_name, 1))
    lookback = _precip_lookback_hours(model_name)
    needed   = set()
    for target in targets:
        hour = target
        while hour > target - window:
            needed.add(hour)
            hour -= cadence
    if lookback:
        needed |= {h - lookback for h in set(needed)}
    return sorted(h for h in needed if h >= 0)


def _observation_record_end(cursor, obs_var, obs_src):
    """Latest observation time for a variable/source, or None.

    Deliberately not restricted to the bounding box: the record's extent is a
    property of the ingest, and leaving the box out lets this use
    idx_rgo_source_var_time instead of scanning. Used to drop lead times that run
    past the end of the truth before querying forecasts that can never be scored.
    """
    cursor.execute("""
        SELECT MAX(obs_time) AS t FROM regridded_observation
        WHERE variable_name = %s AND source = %s
    """, (obs_var, obs_src))
    row = cursor.fetchone()
    return row['t'] if row else None


def _point_case_record(case):
    """One scored lead time at one cell, as both point endpoints report it.

    `/api/spread-skill` (the Analysis point panel) and `/api/compare/skill` (the
    Comparison one) describe the same thing, so they emit the same record. They
    used to differ in more than shape: compare/skill read the aggregate spread
    while spread-skill read the members, and the two panels reported SSRs up to
    31% apart for the same cell and lead time.
    """
    err = case['ens_mean'] - case['obs']
    return {
        'hour':      case['hour'],
        'ssr':       _ssr_from_variances(case['spread_sq'], err ** 2,
                                         case['n_members']),
        'crps':      round(_gaussian_crps(case['ens_mean'], case['spread'],
                                          case['obs']), 6),
        'bias':      round(err, 4),
        'mae':       round(abs(err), 4),
        'rmse':      round(abs(err), 4),   # one case: |error|; pooled below
        'spread':    round(case['spread'], 4),
        'error':     round(case['error'],  4),
        'ens_mean':  round(case['ens_mean'], 4),
        'mean_val':  round(case['ens_mean'], 4),   # compare/skill's name for it
        'obs':       round(case['obs'],      4),
        'n_members': case['n_members'],
        'period_h':  case['period_h'],
        'n_obs_in_window': case['n_obs_in_window'],
    }


def _point_summary(hours_list):
    """Aggregate a list of `_point_case_record`s over lead times.

    Shared so the two point panels cannot drift in estimator, which matters most
    for SSR: it is pooled as mean(sigma^2)/mean(err^2), NOT the mean of the
    per-case ratios, because E[X/Y] != E[X]/E[Y] and one near-zero error drags the
    mean to the clamp. Hence `ssr_agg` rather than the `mean_ssr` it was once
    called — the name claimed the one thing this deliberately is not.
    """
    if not hours_list:
        return {'ssr_agg': None, 'correlation': None, 'crps': None,
                'bias': None, 'mae': None, 'rmse': None}
    n      = len(hours_list)
    crpss  = [h['crps'] for h in hours_list if h['crps'] is not None]
    paired = [(h['spread'], h['mae']) for h in hours_list if h['spread'] is not None]

    ssr_agg = None
    if paired:
        mean_var    = sum(s ** 2 for s, _ in paired) / len(paired)
        mean_sq_err = sum(e ** 2 for _, e in paired) / len(paired)
        if mean_sq_err > 1e-10:
            n_members = max((h.get('n_members') or 0) for h in hours_list)
            ssr_agg = _ssr_from_variances(mean_var, mean_sq_err, n_members or None)

    return {
        'ssr_agg':     ssr_agg,
        'correlation': _pearson([s for s, _ in paired], [e for _, e in paired]),
        'crps':        round(sum(crpss) / len(crpss), 4) if crpss else None,
        'bias':        round(sum(h['bias'] for h in hours_list) / n, 4),
        'mae':         round(sum(h['mae']  for h in hours_list) / n, 4),
        'rmse':        round(math.sqrt(sum(h['rmse'] ** 2 for h in hours_list) / n), 4),
    }


def _member_rate_sql(model_name, is_wind, exported):
    """SQL that turns stored member values into mm/h (or m/s) on the common window.

    One query doing in the database what `_member_moments_python` does in
    Python, because the volume is the cost: the full domain is **2.35M member
    rows** for one model, and shipping them was ~20 s of psycopg2 building row
    dicts before any arithmetic ran (`NEXT_STEPS.md` §52).

    The arithmetic is `metrics.py`'s, restated in SQL rather than reimplemented:

    - `period` is `_precip_period_hours` — GEFS's bucket resets every 6 h, so
      its `h%6==3` records cover 3 h and the rest 6 h.
    - the divisor is `_increment_divisor`, resolved **in Python** and inlined as
      a literal per period, because it depends on the run's export convention
      and not on anything in the row.
    - a cumulative model is differenced against the record one period earlier,
      and `prev_hour = hour - period` is the guard that makes `lag()` mean what
      `prev_hour in series` means. Without it a gap in the series would be
      differenced against whatever record came before it, silently.
    - re-binning is `_rebin_member_to_common_window`: a record already spanning
      6 h passes through, otherwise records tiling `(target-6, target]` exactly
      are combined weighted by their own periods, and a partial cover is
      dropped. `exact` and `tiled` reproduce that precedence — GEFS at a 6 h
      target has both a 6 h and a 3 h record, which sum to 9 and must not be
      combined.

    Wind is instantaneous: no differencing, no re-binning, and the speed is
    per-member `sqrt(u^2 + v^2)`, joined on the natural key the unique index
    already covers.
    """
    if is_wind:
        # The two components are a join in the server rather than two result
        # sets paired in Python. `uq_rfm_natural_key` leads with
        # (model, variable, init_time, forecast_hour, ensemble_member), so both
        # sides are index scans.
        return """
            WITH u AS (
                SELECT latitude AS lat, longitude AS lon,
                       ensemble_member AS member, forecast_hour AS hour,
                       value::float8 AS value
                FROM regridded_forecast_member
                WHERE model_name = %(model)s AND variable_name = 'wind_u_10m'
                  AND init_time = %(init)s
                  AND latitude  BETWEEN %(min_lat)s AND %(max_lat)s
                  AND longitude BETWEEN %(min_lon)s AND %(max_lon)s
                  AND value IS NOT NULL {hour_pred}
            ), v AS (
                SELECT latitude AS lat, longitude AS lon,
                       ensemble_member AS member, forecast_hour AS hour,
                       value::float8 AS value
                FROM regridded_forecast_member
                WHERE model_name = %(model)s AND variable_name = 'wind_v_10m'
                  AND init_time = %(init)s
                  AND latitude  BETWEEN %(min_lat)s AND %(max_lat)s
                  AND longitude BETWEEN %(min_lon)s AND %(max_lon)s
                  AND value IS NOT NULL {hour_pred}
            ), member_rate AS (
                SELECT u.lat, u.lon, u.member, u.hour AS target,
                       sqrt(u.value * u.value + v.value * v.value) AS rate
                FROM u JOIN v ON v.lat = u.lat AND v.lon = u.lon
                             AND v.member = u.member AND v.hour = u.hour
            )
            SELECT round(lat::numeric, 2) AS lat, round(lon::numeric, 2) AS lon,
                   target AS hour, avg(rate) AS ens_mean,
                   var_pop(rate) AS spread_sq, count(*) AS n_members
            FROM member_rate
            WHERE rate IS NOT NULL {target_pred}
            GROUP BY lat, lon, target
            ORDER BY lat, lon, target
        """

    if model_name == 'GEFS':
        period = 'CASE WHEN r.hour %% 6 = 3 THEN 3 ELSE 6 END'
        divisor = ('CASE WHEN r.hour %% 6 = 3 THEN %(div3)s ELSE %(div6)s END')
    else:
        period  = '%(period)s'
        divisor = '%(div)s'

    if model_name in CUMULATIVE_PRECIP_MODELS:
        amount = """GREATEST(0.0, CASE WHEN r.hour - r.period <= 0 THEN r.value
                                       ELSE r.value - r.prev_value END)"""
        guard  = 'WHERE r.hour - r.period <= 0 OR r.prev_hour = r.hour - r.period'
    else:
        amount, guard = 'r.value', ''

    return f"""
        WITH raw AS (
            -- **Not** `round(latitude::numeric, 2) AS lat` here, though that is
            -- the key the result is reported under. Rounding inside the query
            -- makes the window's partition key a function of the column, and a
            -- function of a column cannot be served by an index however
            -- monotonic it is — which cost a sort of 5M rows to disk (§52).
            -- Rounding moved to the outermost projection; it is safe because
            -- the regridded grid has 41 distinct latitudes and 41 distinct
            -- rounded latitudes, so the two group the same way.
            SELECT latitude AS lat, longitude AS lon,
                   ensemble_member AS member, forecast_hour AS hour,
                   value::float8 AS value
            FROM regridded_forecast_member
            WHERE model_name = %(model)s AND variable_name = %(variable)s
              AND init_time = %(init)s
              AND latitude  BETWEEN %(min_lat)s AND %(max_lat)s
              AND longitude BETWEEN %(min_lon)s AND %(max_lon)s
              AND value IS NOT NULL {{hour_pred}}
        ), seq AS (
            SELECT r.*, {period} AS period,
                   lag(value) OVER w AS prev_value,
                   lag(hour)  OVER w AS prev_hour
            FROM raw r
            WINDOW w AS (PARTITION BY lat, lon, member ORDER BY hour)
        ), rates AS (
            SELECT r.lat, r.lon, r.member, r.hour, r.period,
                   ({amount}) / ({divisor}) AS rate
            FROM seq r
            {guard}
        ), tgt AS (
            -- Integer ceiling to the next 6 h boundary: the one target a record
            -- can contribute to.
            SELECT lat, lon, member, hour, period, rate,
                   ((hour + 5) / 6) * 6 AS target
            FROM rates WHERE hour > 0
        ), binned AS (
            -- Pass-through and tiling decided in ONE aggregation. Writing them
            -- as two CTEs and an anti-join cost 2m42s instead of seconds: a CTE
            -- is inlined unless it says otherwise, so each reference re-ran the
            -- whole pipeline beneath it, and the NOT EXISTS ran it again (§52).
            SELECT lat, lon, member, target,
                   max(rate) FILTER (WHERE hour = target AND period = 6)
                       AS exact_rate,
                   sum(rate * period) / 6.0 AS tiled_rate,
                   sum(period)              AS covered
            FROM tgt
            WHERE hour - period >= target - 6
            GROUP BY lat, lon, member, target
        ), member_rate AS (
            -- A record already spanning the window wins, which is what
            -- `_rebin_to_common_window` does before it considers tiling: GEFS
            -- has both a 6 h and a 3 h record at a 6 h target, and they must
            -- not be added together.
            SELECT lat, lon, member, target,
                   coalesce(exact_rate,
                            CASE WHEN covered = 6 THEN tiled_rate END) AS rate
            FROM binned
        )
        SELECT round(lat::numeric, 2) AS lat, round(lon::numeric, 2) AS lon,
               target AS hour, avg(rate) AS ens_mean,
               var_pop(rate) AS spread_sq, count(*) AS n_members
        FROM member_rate
        WHERE rate IS NOT NULL {{target_pred}}
        GROUP BY lat, lon, target
        -- Deterministic output. The old path's order came from Python dict
        -- insertion and this one's from the index, so without this the same
        -- request returns the same cells in a different sequence — which is
        -- invisible until a point list is truncated and the cap keeps a
        -- different subset.
        ORDER BY lat, lon, target
    """


def _member_moments_sql(cursor, model_name, variable, init_time,
                        min_lat, max_lat, min_lon, max_lon,
                        source_hours=None, targets=None):
    """{(lat, lon): {hour: (ens_mean, spread_sq, n_members)}} from the database.

    The pooled moments are all the callers need — no metric here reads the
    individual members — so the 2.35M rows collapse to one row per scored
    (cell, lead time) in the server. `_member_moments_python` is the reference
    this is pinned against, value for value.
    """
    is_wind = (variable == 'wind')
    params = {'model': model_name, 'variable': variable, 'init': init_time,
              'min_lat': min_lat, 'max_lat': max_lat,
              'min_lon': min_lon, 'max_lon': max_lon}
    if not is_wind:
        exported = _export_divisor(model_name, init_time)
        if model_name == 'GEFS':
            params['div3'] = _increment_divisor(model_name, 3, exported)
            params['div6'] = _increment_divisor(model_name, 6, exported)
        else:
            period = _precip_period_hours(model_name, 6)
            params['period'] = period
            params['div'] = _increment_divisor(model_name, period, exported)

    hour_pred = target_pred = ''
    if source_hours is not None:
        hour_pred = ' AND forecast_hour = ANY(%(source_hours)s)'
        params['source_hours'] = list(source_hours)
    if targets is not None:
        target_pred = ' AND target = ANY(%(targets)s)'
        params['targets'] = list(targets)

    sql = _member_rate_sql(model_name, is_wind, None).format(
        hour_pred=hour_pred, target_pred=target_pred)
    cursor.execute(sql, params)
    out = defaultdict(dict)
    for row in cursor.fetchall():
        out[(float(row['lat']), float(row['lon']))][row['hour']] = (
            float(row['ens_mean']), float(row['spread_sq']), int(row['n_members']))
    return dict(out)


def _member_moments_python(cursor, model_name, variable, init_time,
                           min_lat, max_lat, min_lon, max_lon,
                           source_hours=None, targets=None):
    """**The reference implementation of `_member_moments_sql`.**

    Same signature, same return — {(lat, lon): {hour: (ens_mean, spread_sq,
    n_members)}} — computed by fetching every member row and doing the
    arithmetic in Python with `metrics.py`'s own helpers.

    It is not on any request path. It is kept because the SQL version restates
    `_precip_member_rate_series`, `_increment_divisor` and
    `_rebin_member_to_common_window` in another language, and a restatement
    needs something to be checked against:
    `test_member_moments.py` runs both over the fixture and fails on any cell,
    lead time or member count that differs. Change one of them and that test
    tells you the other has drifted — which is the whole point of keeping it
    (`NEXT_STEPS.md` §52).
    """
    is_wind = (variable == 'wind')

    def _member_rows(var_name):
        hour_pred, hour_param = '', ()
        if source_hours is not None:
            hour_pred = ' AND u.forecast_hour = ANY(%s)'
            hour_param = (list(source_hours),)
        cursor.execute(f"""
            SELECT u.latitude, u.longitude, u.forecast_hour, u.ensemble_member,
                   u.value
            FROM regridded_forecast_member u
            WHERE u.model_name = %s AND u.variable_name = %s
              AND u.init_time = %s
              AND u.latitude BETWEEN %s AND %s AND u.longitude BETWEEN %s AND %s
              {hour_pred}
        """, (model_name, var_name, init_time,
              min_lat, max_lat, min_lon, max_lon, *hour_param))
        return cursor.fetchall()

    # Cells are keyed at 2 dp, the same key the regridded pairs path uses — NOT a
    # 0.25° snap, which silently collapsed several of UKMO's 0.1875° native cells
    # onto one key and then kept one cell's coordinates with another's values.
    def _key(row):
        return (round(float(row['latitude']), 2), round(float(row['longitude']), 2),
                row['forecast_hour'], row['ensemble_member'])

    if is_wind:
        v_value = {_key(r): float(r['value'])
                   for r in _member_rows('wind_v_10m') if r['value'] is not None}
        rows = [(r, v_value.get(_key(r))) for r in _member_rows('wind_u_10m')]
        values = [(r, math.sqrt(float(r['value']) ** 2 + v ** 2))
                  for r, v in rows if r['value'] is not None and v is not None]
    else:
        values = [(r, float(r['value']))
                  for r in _member_rows(variable) if r['value'] is not None]

    raw = defaultdict(lambda: defaultdict(dict))
    for r, val in values:
        cell = (round(float(r['latitude']), 2), round(float(r['longitude']), 2))
        raw[cell][r['ensemble_member']][r['forecast_hour']] = val
    if not raw:
        return {}

    out = {}
    for cell, members in raw.items():
        by_hour = defaultdict(list)
        for series in members.values():
            rates = _precip_member_rate_series(
                model_name, series, is_wind=is_wind,
                exported=_export_divisor(model_name, init_time))
            if not is_wind:
                # Members are re-binned individually and only then pooled, so the
                # spread is of 6 h means rather than of a mixture of windows.
                rates = _rebin_member_to_common_window(rates)
            for hour, (rate, _period) in rates.items():
                if targets is not None and hour not in targets:
                    continue
                by_hour[hour].append(rate)
        moments = {}
        for hour, pooled in by_hour.items():
            n = len(pooled)
            ens_mean = sum(pooled) / n
            moments[hour] = (ens_mean,
                             sum((x - ens_mean) ** 2 for x in pooled) / n,
                             n)
        if moments:
            out[cell] = moments
    return out


def _member_cases_by_cell(cursor, model_name, variable, init_time,
                          min_lat, max_lat, min_lon, max_lon, hours=None,
                          _moments=None):
    """Per-cell, per-lead-time ensemble spread and error, from the MEMBER grid.

    Returns {(lat, lon): {hour: case}}, where each case carries `ens_mean`,
    `spread`, `spread_sq`, `error`, `obs`, `n_members`, `period_h` and
    `n_obs_in_window`. Restrict to particular lead times with `hours`.

    This is the one implementation behind /api/spread-skill and the spatial
    ssr/correlation maps, so the point panel and the map cannot answer the same
    question two different ways — which they did until this replaced a second
    implementation reading `ensemble_statistics` + `observation_data`.

    **The forecast moments are computed in the database** (`_member_moments_sql`)
    and the observation half here, which is the split that matters for cost: the
    member grid is members x cells x hours and the moments are one row per
    scored cell and lead time, so the full domain ships ~47k rows instead of
    2.35M (`NEXT_STEPS.md` §52). `_moments` injects a different implementation —
    `_member_moments_python` — and exists so the equivalence test can drive this
    function both ways.

    Why the member grid, precisely — the earlier version of this note said the
    aggregate `std_dev` carries within-cell spatial variance and runs ~23% high.
    That is true of `regridded_forecast` (METRICS_AUDIT.md finding 11) and NOT of
    `regridded_forecast_ens`, whose `std_dev` is `nanstd(members, ddof=1)` over the
    regridded members and equals their sample spread exactly. Two real reasons
    remain, and they are bigger than the retracted one:

    1. **A cumulative model's increment spread is not recoverable from the stored
       totals.** The aggregate path has to approximate it as
       sqrt(sigma(h)^2 - sigma(h-p)^2), which assumes independent increments and
       comes out negative for ~13% of AIFS records. At 36.0/-75.5, +12 h it gives
       sqrt(0.2128^2 - 0.1511^2) = 0.1499 against an exact 0.1144 from
       differencing each member — 31% high. Differencing per member is EXACT.
    2. **Re-binning destroys the spread outright.** Combining records onto the
       common window cannot carry it (the spread of a mean is not the mean of
       spreads), so an hourly model had no spread there at all and every spread
       metric came back empty. Re-binning each MEMBER first and pooling afterwards
       gives the exact spread of the 6 h means.

    A third, minor: the stored value is a sample spread (ddof=1) and this computes
    the population one, a factor sqrt(n/(n-1)) — 1.010 for AIFS's 50 members,
    1.017 for GEFS's 30.

    Truth comes from `regridded_observation` over the window each record spans,
    the same rule every other scored endpoint uses — not the instantaneous match
    against the sparse `observation_data` the old path used.
    """
    is_wind = (variable == 'wind')
    obs_var = 'wind_speed' if is_wind else 'precipitation'
    obs_src = 'ERA5_WIND'  if is_wind else 'GPM_IMERG_V07B'
    # Every re-binned precipitation record spans the common window; wind is
    # instantaneous. The per-record period the old pooling carried could only
    # ever have been one of these two.
    period = 1 if is_wind else COMMON_VERIFICATION_WINDOW_HOURS

    # Prune the query to the lead times that can actually produce a score: the
    # records each target is built from, and nothing past the end of the
    # observation record. The member grid is members x cells x hours, so fetching
    # every hour to score one is the difference between a 5 s map and a 55 s one.
    source_hours = targets = None
    if hours is not None:
        obs_end = _observation_record_end(cursor, obs_var, obs_src)
        targets = sorted(h for h in hours
                         if obs_end is None
                         or init_time + timedelta(hours=h) <= obs_end)
        if not targets:
            return {}
        source_hours = _window_source_hours(model_name, targets, is_wind)

    moments_of = _moments or _member_moments_sql
    pooled = moments_of(cursor, model_name, variable, init_time,
                        min_lat, max_lat, min_lon, max_lon,
                        source_hours=source_hours, targets=targets)
    if not pooled:
        return {}

    scored      = {h for by_hour in pooled.values() for h in by_hour}
    valid_times = [init_time + timedelta(hours=h) for h in scored]
    cursor.execute("""
        SELECT obs_time, latitude, longitude, AVG(value) AS obs_val
        FROM regridded_observation
        WHERE variable_name = %s AND source = %s
          AND obs_time BETWEEN %s AND %s
          AND latitude  BETWEEN %s AND %s
          AND longitude BETWEEN %s AND %s
        GROUP BY obs_time, latitude, longitude
    """, (obs_var, obs_src,
          min(valid_times) - timedelta(hours=period), max(valid_times),
          min_lat, max_lat, min_lon, max_lon))
    obs_by_cell = defaultdict(dict)
    for r in cursor.fetchall():
        if r['obs_val'] is None:
            continue
        key = (round(float(r['latitude']), 2), round(float(r['longitude']), 2))
        obs_by_cell[key][r['obs_time']] = float(r['obs_val'])

    out = {}
    candidates = matched = 0
    for cell, by_hour in pooled.items():
        cell_obs = obs_by_cell.get(cell)
        cases = {}
        for hour in sorted(by_hour):
            ens_mean, spread_sq, n = by_hour[hour]
            candidates += 1
            # A partially observed window is rejected, not averaged.
            obs, covered, n_obs = _obs_window_mean(
                cell_obs, init_time + timedelta(hours=hour), period)
            if not n or obs is None or covered < period:
                continue
            matched += 1
            cases[hour] = {
                'hour':      hour,
                'ens_mean':  ens_mean,
                'spread':    math.sqrt(spread_sq),
                'spread_sq': spread_sq,
                'error':     abs(ens_mean - obs),
                'obs':       obs,
                'n_members': n,
                'period_h':  period,
                'n_obs_in_window': n_obs,
            }
        if cases:
            out[cell] = cases

    if candidates and not matched:
        log.warning(f"⚠️  member↔obs join matched 0 of {candidates} records for "
              f"{model_name}/{variable} — grid misalignment, or no fully observed "
              f"window ({len(obs_by_cell)} obs cells, keys at 2 dp).")
    return out


def _member_pairs_by_cell(cursor, model_name, variable, init_time,
                          min_lat, max_lat, min_lon, max_lon,
                          hour_min=0, hour_max=168):
    """`_fetch_fcst_obs_pairs_spatial`'s shape, but with spread from the MEMBERS.

    Returns {(lat, lon): [(hour, mean_rate, std_rate, obs_rate), ...]}, which is
    exactly what the pairs-based metric functions already consume — so the
    metric arithmetic is untouched and only the source of `std_rate` changes.

    **Why this exists.** The aggregate path re-bins records onto the common
    6-hour window, and `_rebin_to_common_window` returns `std = None` for any
    record it has to combine, because the spread of a mean is not the mean of
    spreads. UKMO is hourly, so *every* record gets combined, so every
    spread-dependent metric skipped every record and the CRPS, aggregate-SSR and
    Brier maps came back **empty for UKMO at every lead time and every run** —
    an empty field rather than a stated reason.

    `_member_cases_by_cell` was built to fix precisely this (see its docstring)
    and was wired into the `ssr` and `correlation` maps and the two point
    endpoints. These three were left behind. Measured 2026-09-29: `ssr` and
    `correlation` returned 1,461 and 1,520 cells for UKMO while `crps`,
    `ssr_agg` and `brier` returned 0, with AIFS and GEFS populated throughout.

    It also makes AIFS's spread **exact** rather than approximated. The
    aggregate path reconstructs a cumulative model's increment spread as
    sqrt(sigma(h)^2 - sigma(h-p)^2), which assumes independent increments, comes
    out negative for ~13% of AIFS records and 31% high where it does resolve.
    So AIFS and GEFS numbers move here too, in the direction the member-grid
    migration already established for `ssr`.
    """
    hours = None
    if hour_min is not None and hour_max is not None:
        hours = set(range(int(hour_min), int(hour_max) + 1))
    cases = _member_cases_by_cell(cursor, model_name, variable, init_time,
                                  min_lat, max_lat, min_lon, max_lon, hours=hours)
    pairs = {}
    for cell, by_hour in cases.items():
        entries = []
        for hour, case in sorted(by_hour.items()):
            # `error` is the signed forecast-minus-observation the aggregate
            # path's consumers reconstruct as (mean_rate - obs_rate); carrying
            # `obs` keeps that identity true.
            entries.append((hour, case['ens_mean'], case['spread'], case['obs']))
        if entries:
            pairs[cell] = entries
    return pairs


def _compute_ssr_points(cursor, model_name, variable, init_time, hour,
                        min_lat, max_lat, min_lon, max_lon):
    """SSR per cell at one lead time, from the member grid.

    Spread comes from the members themselves and the lead time is the common
    verification window, so this map now reports the same number /api/spread-skill
    reports for the same cell. See _member_cases_by_cell.
    """
    cases  = _member_cases_by_cell(cursor, model_name, variable, init_time,
                                   min_lat, max_lat, min_lon, max_lon, hours={hour})
    points = []
    for (lat, lon), by_hour in cases.items():
        case = by_hour.get(hour)
        if case is None:
            continue
        ssr = _ssr_from_variances(case['spread_sq'], case['error'] ** 2,
                                  case['n_members'])
        if ssr is not None:
            points.append({'lat': lat, 'lon': lon, 'value': ssr})
    return points


def _compute_correlation_points(cursor, model_name, variable, init_time,
                                min_lat, max_lat, min_lon, max_lon):
    """Spread-skill correlation per cell, across lead times, from the member grid.

    corr(spread, |error|) over the lead times a cell was scored at. A cell needs
    at least two, and variance in both series — a flat spread or a flat error has
    nothing to correlate and yields None rather than 0.

    Returns (points, n_hours) where n_hours counts the distinct lead times that
    contributed anywhere in the box.

    Scored at CORRELATION_LEAD_HOURS rather than at every lead time the model
    emits, so a 24-sample UKMO correlation is not put beside a 4-sample AIFS one
    in the region view. /api/spread-skill, which describes a single cell rather
    than comparing models, still uses every native lead time — so the two agree on
    spread, error and SSR at any shared hour, but their correlations are over
    different lead-time sets. See NEXT_STEPS.md.
    """
    cases = _member_cases_by_cell(cursor, model_name, variable, init_time,
                                  min_lat, max_lat, min_lon, max_lon,
                                  hours=set(CORRELATION_LEAD_HOURS))
    points, scored_hours = [], set()
    for (lat, lon), by_hour in cases.items():
        scored_hours.update(by_hour)
        series = [by_hour[h] for h in sorted(by_hour)]
        corr   = _pearson([c['spread'] for c in series],
                          [c['error']  for c in series])
        if corr is not None:
            points.append({'lat': lat, 'lon': lon, 'value': corr})
    return points, len(scored_hours)


def _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                   min_lat, max_lat, min_lon, max_lon,
                                   hour_min=0, hour_max=168):
    """
    Fetches per-(lat,lon) lists of (hour, mean_rate, std_rate, obs_rate) tuples
    from regridded_forecast_ens + regridded_observation tables.

    Rates are mm/h via _precip_rate_series(), which applies each model's own
    record semantics (cumulative differencing for AIFS, per-record bucket length
    for GEFS) rather than a single divisor — see the notes on that function.
    `std_rate` is None when the spread isn't recoverable for that record;
    spread-dependent metrics must skip those.
    Returns dict: {(lat_rounded, lon_rounded): [(hour, mean_rate, std_rate, obs_rate), ...]}
    """
    from collections import defaultdict
    is_wind = (variable == 'wind')
    # Cumulative models need one record below hour_min to difference against.
    lookback = 0 if is_wind else _precip_lookback_hours(model_name)
    if is_wind:
        fcst_var, obs_var, obs_src = 'wind_u_10m', 'wind_speed', 'ERA5_WIND'
    else:
        fcst_var, obs_var, obs_src = variable, 'precipitation', 'GPM_IMERG_V07B'

    # The run this request is about, resolved once. This used to be an inline
    # "latest run" query, which is how /api/spatial-metric came to ignore a
    # requested init_time entirely and answer from whichever run was newest —
    # returning a full, plausible map for a run the caller had not asked for.
    # Everything run-related goes through the one resolver now.
    init_time_val = _resolve_init_time(cursor, model_name)
    if init_time_val is None:
        return {}

    # Forecast mean/std (wind → speed via u/v self-join; see _fcst_speed_sql).
    _sel, _frm, _varw, _vnn = _fcst_speed_sql(is_wind, "u.latitude, u.longitude, u.forecast_hour")
    cursor.execute(f"""
        SELECT {_sel}
        FROM {_frm}
        WHERE u.model_name = %s AND {_varw}
          AND u.init_time = %s
          AND u.forecast_hour BETWEEN %s AND %s
          AND u.latitude  BETWEEN %s AND %s
          AND u.longitude BETWEEN %s AND %s
          AND u.mean_value IS NOT NULL AND u.std_dev IS NOT NULL {_vnn}
        ORDER BY u.latitude, u.longitude, u.forecast_hour
    """, (model_name, *(() if is_wind else (fcst_var,)), init_time_val,
          max(0, hour_min - lookback), hour_max, min_lat, max_lat, min_lon, max_lon))
    fcst_rows = cursor.fetchall()
    if not fcst_rows:
        return {}

    # Per-cell hour series, converted to rates with this model's own semantics.
    raw_by_cell = defaultdict(dict)
    for row in fcst_rows:
        key = (round(float(row['latitude']), 2), round(float(row['longitude']), 2))
        raw_by_cell[key][row['forecast_hour']] = (float(row['mean_value']),
                                                  float(row['std_dev']))
    rates_by_cell = {
        cell: _precip_rate_series(model_name, series, is_wind,
                                  exported=_export_divisor(model_name, init_time_val))
        for cell, series in raw_by_cell.items()
    }
    # Wind is instantaneous and already on one footing; precipitation is not, so
    # every model is re-expressed on the common window before anything is scored.
    if not is_wind:
        rates_by_cell = {cell: _rebin_to_common_window(r)
                         for cell, r in rates_by_cell.items()}

    max_period = max((p for rates in rates_by_cell.values()
                      for _, _, p in rates.values()), default=1)
    in_range_hours = [h for rates in rates_by_cell.values() for h in rates
                      if hour_min <= h <= hour_max]
    if not in_range_hours:
        return {}
    valid_times = [init_time_val + timedelta(hours=h) for h in in_range_hours]
    # A record covering `period` hours verifies against (vt - period, vt], so the
    # earliest observation any record can need sits one full period back.
    min_obs_t = min(valid_times) - timedelta(hours=max_period)
    max_obs_t = max(valid_times)

    cursor.execute("""
        SELECT obs_time, latitude, longitude, AVG(value) AS obs_val
        FROM regridded_observation
        WHERE variable_name = %s AND source = %s
          AND obs_time BETWEEN %s AND %s
          AND latitude  BETWEEN %s AND %s
          AND longitude BETWEEN %s AND %s
        GROUP BY obs_time, latitude, longitude
    """, (obs_var, obs_src, min_obs_t, max_obs_t,
          min_lat, max_lat, min_lon, max_lon))
    obs_by_cell = defaultdict(dict)
    for r in cursor.fetchall():
        lat_k = round(float(r['latitude']),  2)
        lon_k = round(float(r['longitude']), 2)
        obs_by_cell[(lat_k, lon_k)][r['obs_time']] = float(r['obs_val'])

    if not obs_by_cell:
        return {}

    result = defaultdict(list)
    matched_rows = candidate_rows = 0
    for (lat, lon), rates in rates_by_cell.items():
        for hour, (mean_rate, std_rate, period) in sorted(rates.items()):
            if not (hour_min <= hour <= hour_max):
                continue                     # a lookback record, fetched only to difference
            candidate_rows += 1
            vt = init_time_val + timedelta(hours=hour)
            # Observations averaged over the SAME period the record covers, so a
            # 6-hourly AIFS record verifies against a 6 h mean rate and an hourly
            # UKMO record against a 1 h rate. Every observation in the window is
            # used, including sub-hourly ones (IMERG is half-hourly), so the
            # window mean is the best estimate of the observed mean rate.
            obs_window, covered, _n_obs = _obs_window_mean(obs_by_cell.get((lat, lon)), vt, period)
            # A partially covered window must be rejected, not averaged: at the
            # edge of the observation record a 6 h forecast would otherwise be
            # scored against a single observation up to 5 h from its valid time.
            if obs_window is None or covered < period:
                continue
            matched_rows += 1
            result[(lat, lon)].append((hour, mean_rate, std_rate, obs_window))

    # Diagnose a silent join failure: the fcst↔obs join is pure rounded-key
    # (2 dp) equality on the cell and needs a fully observed window, so an offset
    # grid or a lead time past the end of the observation record yields zero
    # pairs — indistinguishable from "no data" downstream.
    if matched_rows == 0:
        log.warning(f"⚠️  fcst↔obs join matched 0 of {candidate_rows} forecast records "
              f"for {model_name}/{variable} — grid misalignment, or no fully "
              f"observed window ({len(obs_by_cell)} obs cells, keys at 2 dp).")
    return dict(result)


# ── Accuracy metric compute functions (use regridded tables) ──────────────────

def _compute_bias_points_rf(cursor, model_name, variable,
                             min_lat, max_lat, min_lon, max_lon,
                             hour_min=0, hour_max=168, pairs=None, **_kw):
    if pairs is None:
        pairs = _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                              min_lat, max_lat, min_lon, max_lon,
                                              hour_min, hour_max)
    points = []
    for (lat, lon), entries in pairs.items():
        if entries:
            bias = float(np.mean([mr - orr for _, mr, _, orr in entries]))
            points.append({'lat': lat, 'lon': lon, 'value': round(bias, 4)})
    return points


def _compute_mae_points_rf(cursor, model_name, variable,
                            min_lat, max_lat, min_lon, max_lon,
                            hour_min=0, hour_max=168, pairs=None, **_kw):
    if pairs is None:
        pairs = _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                              min_lat, max_lat, min_lon, max_lon,
                                              hour_min, hour_max)
    points = []
    for (lat, lon), entries in pairs.items():
        if entries:
            mae = float(np.mean([abs(mr - orr) for _, mr, _, orr in entries]))
            points.append({'lat': lat, 'lon': lon, 'value': round(mae, 4)})
    return points


def _compute_rmse_points_rf(cursor, model_name, variable,
                             min_lat, max_lat, min_lon, max_lon,
                             hour_min=0, hour_max=168, pairs=None, **_kw):
    if pairs is None:
        pairs = _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                              min_lat, max_lat, min_lon, max_lon,
                                              hour_min, hour_max)
    points = []
    for (lat, lon), entries in pairs.items():
        if entries:
            rmse = float(np.sqrt(np.mean([(mr - orr) ** 2 for _, mr, _, orr in entries])))
            points.append({'lat': lat, 'lon': lon, 'value': round(rmse, 4)})
    return points


def _compute_crps_points_rf(cursor, model_name, variable,
                             min_lat, max_lat, min_lon, max_lon,
                             hour_min=0, hour_max=168, pairs=None, **_kw):
    if pairs is None:
        pairs = _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                              min_lat, max_lat, min_lon, max_lon,
                                              hour_min, hour_max)
    points = []
    for (lat, lon), entries in pairs.items():
        if not entries:
            continue
        crps_vals = []
        for _, mr, sr, orr in entries:
            if sr is None:
                continue          # spread not recoverable for this record
            crps_vals.append(_gaussian_crps(mr, sr, orr))
        if not crps_vals:
            continue
        points.append({'lat': lat, 'lon': lon, 'value': round(float(np.mean(crps_vals)), 4)})
    return points


# ── Categorical metric compute functions ─────────────────────────────────────

def _compute_csi_points_rf(cursor, model_name, variable,
                            min_lat, max_lat, min_lon, max_lon,
                            hour_min=0, hour_max=168,
                            threshold_rate=25.0 / 6.0, pairs=None, **_kw):
    if pairs is None:
        pairs = _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                              min_lat, max_lat, min_lon, max_lon,
                                              hour_min, hour_max)
    points = []
    for (lat, lon), entries in pairs.items():
        hits = misses = fa = 0
        for _, mr, _, orr in entries:
            if mr > threshold_rate and orr > threshold_rate:      hits   += 1
            elif mr > threshold_rate and orr <= threshold_rate:   fa     += 1
            elif mr <= threshold_rate and orr > threshold_rate:   misses += 1
        denom = hits + misses + fa
        if denom > 0:
            points.append({'lat': lat, 'lon': lon,
                           'value': round(hits / denom, 4)})
    return points


def _compute_pod_points_rf(cursor, model_name, variable,
                            min_lat, max_lat, min_lon, max_lon,
                            hour_min=0, hour_max=168,
                            threshold_rate=25.0 / 6.0, pairs=None, **_kw):
    if pairs is None:
        pairs = _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                              min_lat, max_lat, min_lon, max_lon,
                                              hour_min, hour_max)
    points = []
    for (lat, lon), entries in pairs.items():
        hits = misses = 0
        for _, mr, _, orr in entries:
            if orr > threshold_rate:
                if mr > threshold_rate: hits   += 1
                else:                   misses += 1
        if hits + misses > 0:
            points.append({'lat': lat, 'lon': lon,
                           'value': round(hits / (hits + misses), 4)})
    return points


def _compute_far_points_rf(cursor, model_name, variable,
                            min_lat, max_lat, min_lon, max_lon,
                            hour_min=0, hour_max=168,
                            threshold_rate=25.0 / 6.0, pairs=None, **_kw):
    if pairs is None:
        pairs = _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                              min_lat, max_lat, min_lon, max_lon,
                                              hour_min, hour_max)
    points = []
    for (lat, lon), entries in pairs.items():
        hits = fa = 0
        for _, mr, _, orr in entries:
            if mr > threshold_rate:
                if orr > threshold_rate: hits += 1
                else:                    fa   += 1
        if hits + fa > 0:
            points.append({'lat': lat, 'lon': lon,
                           'value': round(fa / (hits + fa), 4)})
    return points


def _compute_brier_points_rf(cursor, model_name, variable,
                              min_lat, max_lat, min_lon, max_lon,
                              hour_min=0, hour_max=168,
                              threshold_rate=25.0 / 6.0, pairs=None, **_kw):
    if pairs is None:
        pairs = _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                              min_lat, max_lat, min_lon, max_lon,
                                              hour_min, hour_max)
    points = []
    for (lat, lon), entries in pairs.items():
        if not entries:
            continue
        bs_vals = []
        for _, mr, sr, orr in entries:
            if sr is None:
                continue          # spread not recoverable for this record
            is_obs  = float(orr > threshold_rate)
            p_event = _exceedance_probability(mr, sr, threshold_rate)
            bs_vals.append((p_event - is_obs) ** 2)
        if not bs_vals:
            continue
        points.append({'lat': lat, 'lon': lon,
                       'value': round(float(np.mean(bs_vals)), 6)})
    return points


def _dispatch_ssr(cursor, run_id, variable_id, init_time, args,
                  min_lat, max_lat, min_lon, max_lon, obs_col):
    hour   = int(args.get('hour', 6))
    points = _compute_ssr_points(
        cursor, args.get('model', 'AIFS'), args.get('variable', 'precipitation'),
        init_time, hour, min_lat, max_lat, min_lon, max_lon)
    return points, {'hour': hour}


def _dispatch_correlation(cursor, run_id, variable_id, init_time, args,
                           min_lat, max_lat, min_lon, max_lon, obs_col):
    points, n_hours = _compute_correlation_points(
        cursor, args.get('model', 'AIFS'), args.get('variable', 'precipitation'),
        init_time, min_lat, max_lat, min_lon, max_lon)
    return points, {'n_hours': n_hours}


def _resolve_threshold_rate(args):
    """Return threshold_rate in the native comparison unit.
    For wind (m/s): use threshold_ms directly.
    For precipitation (mm/h): convert threshold_mm_6h ÷ 6.
    """
    if args.get('variable', 'precipitation') == 'wind':
        return float(args.get('threshold_ms', 10.0))
    return float(args.get('threshold_mm_6h', 25.0)) / 6.0


def _dispatch_bias(cursor, run_id, variable_id, init_time, args,
                   min_lat, max_lat, min_lon, max_lon, obs_col):
    return _compute_bias_points_rf(
        cursor, args.get('model', 'AIFS'), args.get('variable', 'precipitation'),
        min_lat, max_lat, min_lon, max_lon,
        int(args.get('hour_min', 0)), int(args.get('hour_max', 168)),
    ), {}

def _dispatch_mae(cursor, run_id, variable_id, init_time, args,
                  min_lat, max_lat, min_lon, max_lon, obs_col):
    return _compute_mae_points_rf(
        cursor, args.get('model', 'AIFS'), args.get('variable', 'precipitation'),
        min_lat, max_lat, min_lon, max_lon,
        int(args.get('hour_min', 0)), int(args.get('hour_max', 168)),
    ), {}

def _dispatch_rmse(cursor, run_id, variable_id, init_time, args,
                   min_lat, max_lat, min_lon, max_lon, obs_col):
    return _compute_rmse_points_rf(
        cursor, args.get('model', 'AIFS'), args.get('variable', 'precipitation'),
        min_lat, max_lat, min_lon, max_lon,
        int(args.get('hour_min', 0)), int(args.get('hour_max', 168)),
    ), {}

def _dispatch_crps(cursor, run_id, variable_id, init_time, args,
                   min_lat, max_lat, min_lon, max_lon, obs_col):
    # Member-derived pairs: the aggregate path cannot produce a spread for an
    # hourly model, so this map was empty for UKMO. See _member_pairs_by_cell.
    model = args.get('model', 'AIFS')
    variable = args.get('variable', 'precipitation')
    lo, hi = int(args.get('hour_min', 0)), int(args.get('hour_max', 168))
    return _compute_crps_points_rf(
        cursor, model, variable, min_lat, max_lat, min_lon, max_lon, lo, hi,
        pairs=_member_pairs_by_cell(cursor, model, variable, init_time,
                                    min_lat, max_lat, min_lon, max_lon, lo, hi),
    ), {}

def _dispatch_csi(cursor, run_id, variable_id, init_time, args,
                  min_lat, max_lat, min_lon, max_lon, obs_col):
    thr = _resolve_threshold_rate(args)
    return _compute_csi_points_rf(
        cursor, args.get('model', 'AIFS'), args.get('variable', 'precipitation'),
        min_lat, max_lat, min_lon, max_lon,
        int(args.get('hour_min', 0)), int(args.get('hour_max', 168)),
        threshold_rate=thr,
    ), {}

def _dispatch_pod(cursor, run_id, variable_id, init_time, args,
                  min_lat, max_lat, min_lon, max_lon, obs_col):
    thr = _resolve_threshold_rate(args)
    return _compute_pod_points_rf(
        cursor, args.get('model', 'AIFS'), args.get('variable', 'precipitation'),
        min_lat, max_lat, min_lon, max_lon,
        int(args.get('hour_min', 0)), int(args.get('hour_max', 168)),
        threshold_rate=thr,
    ), {}

def _dispatch_far(cursor, run_id, variable_id, init_time, args,
                  min_lat, max_lat, min_lon, max_lon, obs_col):
    thr = _resolve_threshold_rate(args)
    return _compute_far_points_rf(
        cursor, args.get('model', 'AIFS'), args.get('variable', 'precipitation'),
        min_lat, max_lat, min_lon, max_lon,
        int(args.get('hour_min', 0)), int(args.get('hour_max', 168)),
        threshold_rate=thr,
    ), {}

def _dispatch_brier(cursor, run_id, variable_id, init_time, args,
                    min_lat, max_lat, min_lon, max_lon, obs_col):
    thr = _resolve_threshold_rate(args)
    model = args.get('model', 'AIFS')
    variable = args.get('variable', 'precipitation')
    lo, hi = int(args.get('hour_min', 0)), int(args.get('hour_max', 168))
    return _compute_brier_points_rf(
        cursor, model, variable, min_lat, max_lat, min_lon, max_lon, lo, hi,
        threshold_rate=thr,
        pairs=_member_pairs_by_cell(cursor, model, variable, init_time,
                                    min_lat, max_lat, min_lon, max_lon, lo, hi),
    ), {}


# ── Spatial metric dispatch registry ──────────────────────────────────────────
# To add a new metric:
#   1. Write a _compute_<name>_points() helper above.
#   2. Write a _dispatch_<name>() wrapper with the same signature as above.
#   3. Add an entry here.
#   4. Add a matching entry to PLOT_STYLE_REGISTRY below.
def _compute_ssr_agg_points_rf(cursor, model_name, variable,
                                min_lat, max_lat, min_lon, max_lon,
                                hour_min=0, hour_max=168, pairs=None, **_kw):
    """
    Time-aggregated SSR using regridded tables.
    SSR = √(mean(σ²) / mean(ε²)) across all matched lead times per grid point —
    RMS spread over RMSE, not the variance ratio (METRICS_AUDIT.md finding 7).
    Requires ≥2 matched pairs to be meaningful.
    """
    if pairs is None:
        pairs = _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                              min_lat, max_lat, min_lon, max_lon,
                                              hour_min, hour_max)
    n_members = (_ensemble_size(cursor, model_name, variable, _kw.get('init_time'))
                 if cursor is not None else None)
    points = []
    for (lat, lon), entries in pairs.items():
        # Only records whose spread is available can contribute to a spread ratio.
        entries = [e for e in entries if e[2] is not None]
        if len(entries) < 2:
            continue
        mean_var    = float(np.mean([sr ** 2 for _, _, sr, _   in entries]))
        mean_sq_err = float(np.mean([(mr - orr) ** 2 for _, mr, _, orr in entries]))
        if mean_sq_err > 1e-10:
            ssr = _ssr_from_variances(mean_var, mean_sq_err, n_members)
            if ssr is not None:
                points.append({'lat': lat, 'lon': lon, 'value': ssr})
    return points


def _dispatch_ssr_agg(cursor, run_id, variable_id, init_time, args,
                      min_lat, max_lat, min_lon, max_lon, obs_col):
    model = args.get('model', 'AIFS')
    variable = args.get('variable', 'precipitation')
    lo, hi = int(args.get('hour_min', 0)), int(args.get('hour_max', 168))
    return _compute_ssr_agg_points_rf(
        cursor, model, variable, min_lat, max_lat, min_lon, max_lon, lo, hi,
        pairs=_member_pairs_by_cell(cursor, model, variable, init_time,
                                    min_lat, max_lat, min_lon, max_lon, lo, hi),
        # The SSR bias correction is a function of the ensemble size, so it must
        # be this run's, not whichever run happens to be newest.
        init_time=init_time,
    ), {}


# Metrics /api/spatial-metric can draw as a per-cell field. Every one of these has
# a value at a single grid cell, which is what makes a map of it meaningful.
#
# `fss` is deliberately absent, and this is the reason (CONSISTENCY_AUDIT.md 1b):
# the Fractions Skill Score compares the *fraction* of exceedances in a
# neighbourhood around each point against the observed fraction, so its value
# belongs to a whole field at a lead time, not to a cell. Attributing it to the
# centre cell would draw a map of a number that is not a property of that cell.
# It is therefore reported as a region number in both tabs and mapped in neither —
# see COMPARE_REGION_NO_CELL_VALUE, which encodes the same rule for the region
# metric suite. In Analysis it arrives through the categorical panel rather than
# the metric explorer, which is why it looks absent there at first glance.
SPATIAL_METRIC_REGISTRY = {
    'ssr':         _dispatch_ssr,
    'ssr_agg':     _dispatch_ssr_agg,
    'correlation': _dispatch_correlation,
    'bias':        _dispatch_bias,
    'mae':         _dispatch_mae,
    'rmse':        _dispatch_rmse,
    'crps':        _dispatch_crps,
    'csi':         _dispatch_csi,
    'pod':         _dispatch_pod,
    'far':         _dispatch_far,
    'brier':       _dispatch_brier,
}

# What each metric needs from the caller, declared once and served by
# `/api/config`.
#
# **This is the single source of truth these facts never had.** The same two
# flags were written out again in `src/constants.js` as `requiresHour` and
# `requiresThreshold`, so a metric could be added to the dispatch registry above
# and be invisible in the selector, or be offered without the control it needs.
# `SYSTEM_DESIGN_PLAN.md` S4 asks for exactly this and its exit criterion —
# "adding a metric is a single-place change" — was unmet.
#
# Two tests hold it to that. One checks this table against what the dispatchers
# *actually read* (`test_config_endpoint.py`), so a declaration cannot drift from
# behaviour; the other checks `src/constants.js` against this table, so the
# frontend cannot drift from either. The second is the one that matters: the
# defects this repo keeps finding are backend/frontend disagreements that no
# single-sided test could see — four spatial metrics labelling wind maps in
# `mm/h` (§19), and the UI's `wind` not being a stored variable at all.
#
# `hour` means a single lead time rather than a range: only `ssr` works that way,
# which is why it is absent from the region suite.
METRIC_REQUIREMENTS = {
    'ssr':         {'hour': True,  'threshold': False},
    'ssr_agg':     {'hour': False, 'threshold': False},
    'correlation': {'hour': False, 'threshold': False},
    'bias':        {'hour': False, 'threshold': False},
    'mae':         {'hour': False, 'threshold': False},
    'rmse':        {'hour': False, 'threshold': False},
    'crps':        {'hour': False, 'threshold': False},
    'csi':         {'hour': False, 'threshold': True},
    'pod':         {'hour': False, 'threshold': True},
    'far':         {'hour': False, 'threshold': True},
    'brier':       {'hour': False, 'threshold': True},
}

# The unit each variable carries, which decides whether a metric needs a
# separate wind scale. Duplicated in `src/constants.js` as `VALUE_UNITS` until
# 2026-10-01; the parity test now pins them together. `/api/compare/skill` used
# to hard-code `mm/h` for every variable, which is the defect this removes the
# conditions for.
VARIABLE_UNITS = {
    'precipitation': 'mm/h',
    'wind':          'm/s',
}


@app.route('/api/forecast-data', methods=['GET'])
def get_forecast_data():
    model_name    = request.args.get('model', 'AIFS')
    variable_name = request.args.get('variable', 'precipitation')
    if _bad_token(model_name, variable_name):
        return jsonify({'error': 'Invalid model or variable'}), 400
    try:
        forecast_hour = int(request.args.get('hour', 6))
    except (TypeError, ValueError):
        return jsonify({'error': 'hour must be numeric'}), 400
    member        = request.args.get('member', 'mean')
    if not _valid_member(member):
        return jsonify({'error': "member must be 'mean', 'std', or an integer"}), 400

    if variable_name == 'wind':
        return get_wind_data()

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        run_id = get_model_run_id(cursor, model_name)
        if not run_id:
            return jsonify({'error': f'No data found for model {model_name}'}), 404
        # Which run this is, for the export divisor below. The same resolver
        # `get_model_run_id` just used, so it cannot name a different run.
        _map_init = _resolve_init_time(cursor, model_name)

        # The map is labelled mm/h, so it has to BE mm/h. The three models do not
        # share a record convention (AIFS cumulates, GEFS buckets, UKMO is already
        # a rate), so the same conversion the metric endpoints use is applied here
        # — otherwise AIFS simply looks wetter the further out you scrub, because
        # its raw value is a running total since initialisation.
        from collections import defaultdict
        lookback = _precip_lookback_hours(model_name)
        hours = sorted({forecast_hour, forecast_hour - lookback} - {h for h in (forecast_hour - lookback,) if h < 0})

        def _fill_predecessor(series):
            """A cumulative model needs the record one period back. Precipitation
            was sparsified on load, so a cell absent at the earlier hour was dry
            there — an implicit zero, not a gap that should void the cell."""
            prev = forecast_hour - lookback
            if lookback and prev >= 0 and prev not in series and forecast_hour in series:
                series[prev] = (0.0, 0.0) if isinstance(series[forecast_hour], tuple) else 0.0
            return series

        if member in ('mean', 'std'):
            cursor.execute("""
                SELECT forecast_hour, latitude AS lat, longitude AS lon, mean_value, std_dev
                FROM ensemble_statistics es
                WHERE es.run_id = %s
                  AND es.variable_id = (SELECT variable_id FROM variables WHERE variable_name = %s)
                  AND es.forecast_hour = ANY(%s)
                ORDER BY latitude, longitude, forecast_hour
                LIMIT %s
            """, (run_id, variable_name, hours,
                  POINT_LIST_MAX_CELLS * max(len(hours), 1) + 1))
            by_cell = defaultdict(dict)
            for row in cursor.fetchall():
                if row['mean_value'] is None:
                    continue
                by_cell[(float(row['lat']), float(row['lon']))][row['forecast_hour']] = (
                    float(row['mean_value']),
                    float(row['std_dev']) if row['std_dev'] is not None else None)
            idx = 0 if member == 'mean' else 1
            by_cell, truncated = _cap_cells(by_cell)
            result = []
            for (lat, lon), series in by_cell.items():
                # Same reason as compare/timeseries: the map must read the
                # registry, or it draws a different rate from the one the
                # scores use. `_resolve_init_time` is the resolver
                # `get_model_run_id` above already went through, so this names
                # the same run rather than re-deciding which one.
                rec = _precip_rate_series(
                    model_name, _fill_predecessor(series),
                    exported=_export_divisor(model_name, _map_init)).get(forecast_hour)
                # A None std is the unrecoverable-increment-spread case; it is
                # dropped rather than shown as zero (see _precip_rate_series).
                if rec is None or rec[idx] is None:
                    continue
                result.append({'lat': lat, 'lon': lon, 'value': rec[idx]})
        else:
            member_num = int(member)
            cursor.execute("""
                SELECT forecast_hour, latitude AS lat, longitude AS lon, value
                FROM forecast_data
                WHERE run_id = %s
                  AND variable_id = (SELECT variable_id FROM variables WHERE variable_name = %s)
                  AND forecast_hour = ANY(%s)
                  AND ensemble_member = %s
                ORDER BY latitude, longitude, forecast_hour
                LIMIT %s
            """, (run_id, variable_name, hours, member_num,
                  POINT_LIST_MAX_CELLS * max(len(hours), 1) + 1))
            by_cell = defaultdict(dict)
            for row in cursor.fetchall():
                if row['value'] is None:
                    continue
                by_cell[(float(row['lat']), float(row['lon']))][row['forecast_hour']] = float(row['value'])
            by_cell, truncated = _cap_cells(by_cell)
            result = []
            for (lat, lon), series in by_cell.items():
                rec = _precip_member_rate_series(model_name, _fill_predecessor(series)).get(forecast_hour)
                if rec is None:
                    continue
                result.append({'lat': lat, 'lon': lon, 'value': rec[0]})

        log.info(f"✅ Returned {len(result)} precipitation points (mm/h) for "
              f"{model_name} +{forecast_hour}h")
        return _point_list_response(
            result, truncated, f" ({model_name} precipitation +{forecast_hour}h)")

    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        log.exception(f"❌ Error in forecast-data: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        cursor.close()
        return_db_connection(conn)


@app.route('/api/wind-data', methods=['GET'])
def get_wind_data():
    model_name    = request.args.get('model', 'AIFS')
    if _bad_token(model_name):
        return jsonify({'error': 'Invalid model'}), 400
    try:
        forecast_hour = int(request.args.get('hour', 6))
    except (TypeError, ValueError):
        return jsonify({'error': 'hour must be numeric'}), 400
    member        = request.args.get('member', 'mean')
    if not _valid_member(member):
        return jsonify({'error': "member must be 'mean', 'std', or an integer"}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        run_id = get_model_run_id(cursor, model_name)
        if not run_id:
            return jsonify({'error': f'No data found for model {model_name}'}), 404

        if member == 'mean':
            cursor.execute("""
                SELECT
                    u.latitude as lat, u.longitude as lon,
                    u.mean_value as u, v.mean_value as v
                FROM ensemble_statistics u
                JOIN ensemble_statistics v 
                    ON u.run_id = v.run_id 
                    AND u.forecast_hour = v.forecast_hour 
                    AND u.latitude = v.latitude 
                    AND u.longitude = v.longitude
                WHERE u.run_id = %s
                  AND u.variable_id = (SELECT variable_id FROM variables WHERE variable_name = 'wind_u_10m')
                  AND v.variable_id = (SELECT variable_id FROM variables WHERE variable_name = 'wind_v_10m')
                  AND u.forecast_hour = %s
                ORDER BY u.latitude, u.longitude
                LIMIT %s
            """, (run_id, forecast_hour, POINT_LIST_MAX_CELLS + 1))

        elif member == 'std':
            cursor.execute("""
                SELECT 
                    u.latitude as lat, u.longitude as lon,
                    u.std_dev as u, v.std_dev as v
                FROM ensemble_statistics u
                JOIN ensemble_statistics v 
                    ON u.run_id = v.run_id 
                    AND u.forecast_hour = v.forecast_hour 
                    AND u.latitude = v.latitude 
                    AND u.longitude = v.longitude
                WHERE u.run_id = %s
                  AND u.variable_id = (SELECT variable_id FROM variables WHERE variable_name = 'wind_u_10m')
                  AND v.variable_id = (SELECT variable_id FROM variables WHERE variable_name = 'wind_v_10m')
                  AND u.forecast_hour = %s
                  AND u.std_dev IS NOT NULL
                ORDER BY u.latitude, u.longitude
                LIMIT %s
            """, (run_id, forecast_hour, POINT_LIST_MAX_CELLS + 1))

        else:
            member_num = int(member)
            cursor.execute("""
                SELECT 
                    u.latitude as lat, u.longitude as lon,
                    u.value as u, v.value as v
                FROM forecast_data u
                JOIN forecast_data v 
                    ON u.run_id = v.run_id 
                    AND u.forecast_hour = v.forecast_hour 
                    AND u.ensemble_member = v.ensemble_member 
                    AND u.latitude = v.latitude 
                    AND u.longitude = v.longitude
                WHERE u.run_id = %s
                  AND u.variable_id = (SELECT variable_id FROM variables WHERE variable_name = 'wind_u_10m')
                  AND v.variable_id = (SELECT variable_id FROM variables WHERE variable_name = 'wind_v_10m')
                  AND u.forecast_hour = %s
                  AND u.ensemble_member = %s
                ORDER BY u.latitude, u.longitude
                LIMIT %s
            """, (run_id, forecast_hour, member_num, POINT_LIST_MAX_CELLS + 1))

        data = cursor.fetchall()
        # One row per cell here, so the SQL limit already bounds cells; fetching
        # one extra is how we know the limit was reached rather than the data
        # simply ending there.
        truncated = len(data) > POINT_LIST_MAX_CELLS
        if truncated:
            data = data[:POINT_LIST_MAX_CELLS]
        result = []
        for row in data:
            u = float(row['u']) if row['u'] else 0
            v = float(row['v']) if row['v'] else 0
            speed         = math.sqrt(u * u + v * v)
            direction_rad = math.atan2(u, v)
            direction_deg = (direction_rad * 180 / math.pi + 180) % 360
            result.append({
                'lat':       float(row['lat']),
                'lon':       float(row['lon']),
                'u':         round(u, 3),
                'v':         round(v, 3),
                'speed':     round(speed, 2),
                'direction': round(direction_deg, 1)
            })

        log.info(f"✅ Returned {len(result)} wind points for {model_name} +{forecast_hour}h ({member})")
        return _point_list_response(
            result, truncated, f" ({model_name} wind +{forecast_hour}h {member})")

    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        log.exception(f"❌ Error in wind-data: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        cursor.close()
        return_db_connection(conn)


# ── NEW: Point time-series for Cone of Uncertainty chart ─────────────────────
@app.route('/api/point-timeseries', methods=['GET'])
def point_timeseries():
    """
    Returns mean, std, min, max, and percentiles across all ensemble members
    for every forecast hour at the nearest grid point to (lat, lon).
    Used by the Analysis tab Cone of Uncertainty chart.
    """
    model_name = request.args.get('model', 'AIFS')
    variable   = request.args.get('variable', 'precipitation')
    if _bad_token(model_name, variable):
        return jsonify({'error': 'Invalid model or variable'}), 400
    point, err = _parse_latlon(request.args)
    if err:
        return err
    lat, lon = point
    try:
        radius = float(request.args.get('radius', 0.5))  # degrees search radius
    except (TypeError, ValueError):
        return jsonify({'error': 'lat and lon are required and must be numeric'}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        run_id = get_model_run_id(cursor, model_name)
        if not run_id:
            return jsonify({'error': f'No data found for model {model_name}'}), 404

        # One code path for both variables: pull raw members and build the
        # distribution here.
        #
        # Aggregating in SQL cannot work for precipitation — the spread of a
        # cumulative field is not the spread of its increments, so the members have
        # to be de-accumulated individually first. And it was wrong for wind for a
        # second reason: it pooled every cell within `radius` into one GROUP BY, so
        # the cone was widened by within-radius spatial variance that is not
        # ensemble spread at all. That is METRICS_AUDIT.md finding 11 again, on the
        # display side. The wind branch also reported a sample standard deviation
        # where precipitation reported the population one, and omitted n_members.
        def _member_rows(var_name):
            # `BETWEEN`, not `ABS(fd.latitude - %s) <= %s`, which is the same
            # set of rows and **63.5 s instead of 3.2 s** (NEXT_STEPS.md §51).
            # Wrapping the column in a function makes the predicate
            # non-sargable: no index can be matched against ABS(latitude), so
            # the planner fell back to a parallel sequential scan of all 240M
            # rows of `forecast_data` — 3.05M buffers, 79.9M rows discarded per
            # worker — to return the 75k rows around one point. The bounds
            # below are an index condition, and `uq_forecast_data_natural_key`
            # serves them.
            cursor.execute("""
                SELECT fd.forecast_hour, fd.ensemble_member,
                       fd.latitude, fd.longitude, fd.value
                FROM forecast_data fd
                WHERE fd.run_id = %s
                  AND fd.variable_id = (SELECT variable_id FROM variables WHERE variable_name = %s)
                  AND fd.latitude  BETWEEN %s AND %s
                  AND fd.longitude BETWEEN %s AND %s
                  AND fd.ensemble_member IS NOT NULL
            """, (run_id, var_name,
                  lat - radius, lat + radius, lon - radius, lon + radius))
            return cursor.fetchall()

        def _member_key(row):
            return (float(row['latitude']), float(row['longitude']),
                    row['forecast_hour'], row['ensemble_member'])

        is_wind = (variable == 'wind')
        if is_wind:
            # Speed per member, paired in Python rather than self-joined: the join
            # predicate includes ensemble_member and latitude/longitude, which no
            # index covers together (see _member_cases_by_cell for the same fix).
            v_value = {_member_key(r): float(r['value'])
                       for r in _member_rows('wind_v_10m') if r['value'] is not None}
            values = [(r, math.sqrt(float(r['value']) ** 2 + v_value[_member_key(r)] ** 2))
                      for r in _member_rows('wind_u_10m')
                      if r['value'] is not None and _member_key(r) in v_value]
        else:
            values = [(r, float(r['value']))
                      for r in _member_rows(variable) if r['value'] is not None]

        from collections import defaultdict
        result = []
        cells  = {(float(r['latitude']), float(r['longitude'])) for r, _v in values}
        if cells:
            # The nearest cell only, for both variables.
            cell = min(cells, key=lambda c: (c[0] - lat) ** 2 + (c[1] - lon) ** 2)
            by_member = defaultdict(dict)
            for r, val in values:
                if (float(r['latitude']), float(r['longitude'])) == cell:
                    by_member[r['ensemble_member']][r['forecast_hour']] = val

            # Wind is instantaneous and passes through; precipitation is
            # de-accumulated per member, which is exact.
            vals_by_hour = defaultdict(list)
            for series in by_member.values():
                rates = _precip_member_rate_series(model_name, series, is_wind=is_wind)
                for hour, (rate, _period) in rates.items():
                    vals_by_hour[hour].append(rate)

            for hour in sorted(vals_by_hour):
                vals = sorted(vals_by_hour[hour])
                n    = len(vals)
                mean = sum(vals) / n
                std  = math.sqrt(sum((v - mean) ** 2 for v in vals) / n)   # population
                def pct(q, _v=vals, _n=n):
                    return _v[min(_n - 1, max(0, int(round(q * (_n - 1)))))]
                result.append({
                    'hour': hour,
                    'mean': round(mean, 4),
                    'std':  round(std, 4),
                    'min':  round(vals[0], 4),
                    'max':  round(vals[-1], 4),
                    'p10':  round(pct(0.10), 4),
                    'p25':  round(pct(0.25), 4),
                    'p75':  round(pct(0.75), 4),
                    'p90':  round(pct(0.90), 4),
                    'n_members': n,
                    'cell': [cell[0], cell[1]],
                })

        log.info(f"✅ Timeseries: {len(result)} hours for {model_name} at ({lat}, {lon}) "
              f"[{variable}]")
        return jsonify(result)

    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        log.exception(f"❌ Error in point-timeseries: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        cursor.close()
        return_db_connection(conn)
# ─────────────────────────────────────────────────────────────────────────────


@app.route('/api/spread-skill', methods=['GET'])
def get_spread_skill():
    """
    Spread-Skill Ratio and Spread-Skill Correlation for one clicked grid cell.

    Reads the regridded MEMBER grid and verifies against `regridded_observation`
    over the window each record spans — the same path the spatial ssr/correlation
    maps use, so the point panel and the map agree (see _member_cases_by_cell).
    A lead time is scored only where an observation covers its whole window, which
    is why the list stops before the forecast does.

    SSR = spread / |error|  (1 = well-calibrated, <1 = overconfident, >1 = underconfident).
    The ratio of the values, not of their squares — see metrics._ssr_from_variances.
    Correlation = corr(spread_per_hour, |error|_per_hour) across scored lead times.
    """
    model_name = request.args.get('model', 'AIFS')
    variable   = request.args.get('variable', 'precipitation')
    if _bad_token(model_name, variable):
        return jsonify({'error': 'Invalid model or variable'}), 400
    point, err = _parse_latlon(request.args)
    if err:
        return err
    lat, lon = point
    try:
        radius = float(request.args.get('radius', 0.5))
    except (TypeError, ValueError):
        return jsonify({'error': 'lat and lon are required and must be numeric'}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        run_id = get_model_run_id(cursor, model_name)
        if not run_id:
            return jsonify({'error': f'No data found for model {model_name}'}), 404

        # Through the one resolver, like every other run-dependent path. This was
        # a fourth copy of "the latest run" — the guard below existed because it
        # read `run_id`'s row in a second query that the ingest could delete
        # between the two. The resolver has no such window.
        init_time = _resolve_init_time(cursor, model_name)
        if init_time is None:
            return jsonify({'error': f'No data found for model {model_name}'}), 404
        is_wind   = (variable == 'wind')

        _key = _metric_cache_key(
            'spread', cursor, model=model_name, variable=variable,
            init_time=init_time, lat=round(lat, 4), lon=round(lon, 4),
            radius=radius,
        )
        _cached = _cache_get(_key)
        if _cached is not None:
            return jsonify(_cached)

        # Verification runs on the shared 0.5 degree grid — the same truth path
        # every other scored endpoint uses, so Analysis and Comparison no longer
        # answer the same question two ways. `radius` is still accepted for URL
        # compatibility but no longer selects a neighbourhood: the score
        # describes one cell, and `cell` in the response says which.
        cell = (round(lat * 2) / 2, round(lon * 2) / 2)

        # One shared implementation with the spatial ssr/correlation maps: a
        # degenerate bbox around the cell. See _member_cases_by_cell.
        eps   = 1e-6
        cases = _member_cases_by_cell(
            cursor, model_name, variable, init_time,
            cell[0] - eps, cell[0] + eps, cell[1] - eps, cell[1] + eps)
        by_hour = cases.get(cell, {})

        results = [_point_case_record(case) for _hour, case in sorted(by_hour.items())]
        summary = _point_summary(results)

        log.info(f"\u2705 Spread-skill: {len(results)} hours matched, "
              f"corr={summary['correlation']} for ({lat},{lon}) at 0.5deg cell {cell}")
        result = {'hours': results,
                        # `correlation` stays at the top level for the callers that
                        # already read it; `summary` is the same shape
                        # /api/compare/skill returns, so the two point panels can
                        # show the same things without a second request.
                        'correlation': summary['correlation'],
                        'summary':     summary,
                        'n_cases': len(results),
                        'units': 'm/s' if is_wind else 'mm/h',
                        'grid': '0.5deg',
                        # The shared-grid cell the ensemble was read from.
                        'cell': list(cell)}
        _cache_set(_key, result, timeout=METRIC_CACHE_TTL)
        return jsonify(result)

    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        log.exception(f"❌ Error in spread-skill: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        cursor.close()
        return_db_connection(conn)


@app.route('/api/spatial-metric', methods=['GET'])
def get_spatial_metric():
    """Per-cell metric maps over a bounding box.

    Eleven metrics, not the two this docstring used to name: the authority is
    `SPATIAL_METRIC_REGISTRY`, and an unknown key is refused with the list.

    **Lead time is not one parameter, and which one applies depends on the
    metric.** Each dispatcher is handed `request.args` and reads its own:

    ==================================  ======================================
    `ssr`                               `hour` — a single lead time, default 6,
                                        echoed back in the response
    `correlation`                       neither; correlated over every hour the
                                        run holds
    the other nine (`bias`, `mae`,      `hour_min` / `hour_max` — a *range*,
    `rmse`, `crps`, `csi`, `pod`,       because these are scored over a window
    `far`, `brier`, `ssr_agg`)          rather than at an instant
    ==================================  ======================================

    So `?hour=` is silently inert on `mae`, and `?hour_min=&hour_max=` is
    silently inert on `ssr`. Both are correct and neither is discoverable from
    the response, which is why the table above is here. **On 2026-09-28 this was
    briefly recorded as a defect** — "documents an hour it never reads" — after
    a grep of this function found no `args.get('hour')`. It is in the
    dispatchers, which receive `request.args`. `NEXT_STEPS.md` keeps that
    retraction, because the mistake was method rather than code: resolve the
    helper before concluding what a parameter does.

    Thresholds are per-variable and also read by the dispatchers:
    `threshold_ms` (default 10.0) for wind, `threshold_mm_6h` (default 25.0,
    divided by 6) for precipitation.

    Params: metric, model, variable, init_time, min_lat, max_lat, min_lon,
            max_lon, plus the lead-time and threshold arguments above.
    """
    metric     = request.args.get('metric', 'ssr')
    model_name = request.args.get('model', 'AIFS')
    variable   = request.args.get('variable', 'precipitation')
    if _bad_token(model_name, variable):
        return jsonify({'error': 'Invalid model or variable'}), 400
    bbox, err = _parse_bbox(request.args)
    if err:
        return err
    min_lat, max_lat = bbox['min_lat'], bbox['max_lat']
    min_lon, max_lon = bbox['min_lon'], bbox['max_lon']
    try:
        threshold_mm_6h = float(request.args.get('threshold_mm_6h', 25.0))
    except (TypeError, ValueError):
        return jsonify({'error': 'threshold_mm_6h must be numeric'}), 400

    if metric not in SPATIAL_METRIC_REGISTRY:
        return jsonify({'error': f'Unknown metric: {metric}. '
                        f'Available: {list(SPATIAL_METRIC_REGISTRY.keys())}'}), 400

    obs_col    = 'wind_speed' if variable == 'wind' else 'precipitation'
    var_lookup = 'wind_u_10m' if variable == 'wind' else variable

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        run_id = get_model_run_id(cursor, model_name)
        if not run_id:
            return jsonify({'error': f'No data found for model {model_name}'}), 404

        # Resolved through the one resolver, like every other run-dependent path.
        # This used to read `initialization_time` for `run_id` directly — a third
        # copy of "the latest run", after the two the init_time migration
        # removed. It agreed with the rest while one run was loaded and would
        # have diverged the moment a second arrived: the queries underneath
        # filter on the *requested* run, so this would have handed them one run's
        # valid times while they read another's rows.
        init_time = _resolve_init_time(cursor, model_name)
        if init_time is None:
            return jsonify({'error': f'No data found for model {model_name}'}), 404

        cursor.execute(
            "SELECT variable_id FROM variables WHERE variable_name = %s", (var_lookup,)
        )
        var_row = cursor.fetchone()
        if not var_row:
            return jsonify({'error': f'Variable {var_lookup} not found'}), 404
        variable_id = var_row['variable_id']

        # Deterministic: the answer is a pure function of these parameters and
        # the loaded data, and the loaded data is in the key via the version. The
        # full-domain requests this serves take 1.0-6.1 s each, and the Analysis
        # region view fires about ten of them at once.
        _key = _metric_cache_key(
            'metric', cursor,
            metric=metric, model=model_name, variable=variable,
            init_time=init_time,
            bbox=[round(min_lat, 4), round(max_lat, 4),
                  round(min_lon, 4), round(max_lon, 4)],
            # Only the arguments this metric actually reads, so an unrelated
            # query parameter cannot fragment the cache.
            args={k: v for k, v in sorted(request.args.items())
                  if k in SPATIAL_METRIC_CACHE_ARGS},
        )
        _cached = _cache_get(_key)
        if _cached is not None:
            return jsonify(_cached)

        dispatch = SPATIAL_METRIC_REGISTRY[metric]
        points, extra = dispatch(
            cursor, run_id, variable_id, init_time, request.args,
            min_lat, max_lat, min_lon, max_lon, obs_col,
        )
        log.info(f"✅ Spatial {metric}: {len(points)} pts — {model_name} "
              f"bbox [{min_lat},{max_lat}]×[{min_lon},{max_lon}]")
        result = {'metric': metric, 'points': points, **extra}
        # Only successes are cached; the error paths above return before this.
        _cache_set(_key, result, timeout=METRIC_CACHE_TTL)
        return jsonify(result)

    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        log.exception(f"❌ Error in spatial-metric: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        cursor.close()
        return_db_connection(conn)


# ── Plot style registry ────────────────────────────────────────────────────────
# To add a new metric's plot style, add an entry here keyed by metric name.
PLOT_STYLE_REGISTRY = {
    'ssr': {
        'cmap': mcolors.ListedColormap(
            ['#c00000', '#e74c3c', '#27ae60', '#e67e22', '#3498db']
        ),
        'norm':           mcolors.BoundaryNorm([0, 0.5, 0.8, 1.2, 2.0, 10.0], 5),
        'cbar_label':     'Spread-Skill Ratio (SSR)',
        'cbar_ticks':     [0.25, 0.65, 1.0, 1.6, 5.0],
        'cbar_ticklabels': ['< 0.5\nSev. underdisp.',
                            '0.5 – 0.8\nOverconfident',
                            '0.8 – 1.2\nCalibrated ✓',
                            '1.2 – 2.0\nUnderconfident',
                            '> 2.0\nSev. overdisp.'],
        'cbar_fontsize':  7.5,
    },
    'ssr_agg': {
        'cmap': mcolors.ListedColormap(
            ['#c00000', '#e74c3c', '#27ae60', '#e67e22', '#3498db']
        ),
        'norm':           mcolors.BoundaryNorm([0, 0.5, 0.8, 1.2, 2.0, 10.0], 5),
        'cbar_label':     'SSR (time-aggregated)',
        'cbar_ticks':     [0.25, 0.65, 1.0, 1.6, 5.0],
        'cbar_ticklabels': ['< 0.5\nSev. underdisp.',
                            '0.5 – 0.8\nOverconfident',
                            '0.8 – 1.2\nCalibrated ✓',
                            '1.2 – 2.0\nUnderconfident',
                            '> 2.0\nSev. overdisp.'],
        'cbar_fontsize':  7.5,
    },
    'correlation': {
        'cmap':           plt.cm.RdBu_r,
        'norm':           mcolors.Normalize(vmin=-1, vmax=1),
        'cbar_label':     'Spread-Skill Correlation',
        'cbar_ticks':     [-1, -0.5, 0, 0.5, 1],
        'cbar_ticklabels': ['-1', '-0.5', '0', '+0.5', '+1'],
        'cbar_fontsize':  9,
    },
    'bias': {
        'cmap': plt.cm.RdBu_r,
        'norm': mcolors.TwoSlopeNorm(vmin=-2.0, vcenter=0.0, vmax=2.0),
        'cbar_label':      'Bias ({unit})  [+ = over-forecast]',
        'cbar_ticks':      [-2, -1, 0, 1, 2],
        'cbar_ticklabels': ['-2', '-1', '0', '+1', '+2'],
        'cbar_fontsize':   9,
    },
    'mae': {
        'cmap': plt.cm.YlOrRd,
        'norm': mcolors.Normalize(vmin=0, vmax=2),
        'cbar_label':      'MAE ({unit})',
        'cbar_ticks':      [0, 0.5, 1.0, 1.5, 2.0],
        'cbar_ticklabels': ['0', '0.5', '1', '1.5', '2'],
        'cbar_fontsize':   9,
    },
    'rmse': {
        'cmap': plt.cm.YlOrRd,
        'norm': mcolors.Normalize(vmin=0, vmax=2),
        'cbar_label':      'RMSE ({unit})',
        'cbar_ticks':      [0, 0.5, 1.0, 1.5, 2.0],
        'cbar_ticklabels': ['0', '0.5', '1', '1.5', '2'],
        'cbar_fontsize':   9,
    },
    'crps': {
        'cmap': plt.cm.YlOrRd,
        'norm': mcolors.Normalize(vmin=0, vmax=1),
        'cbar_label':      'CRPS ({unit}, lower=better)',
        'cbar_ticks':      [0, 0.25, 0.5, 0.75, 1.0],
        'cbar_ticklabels': ['0', '0.25', '0.5', '0.75', '1'],
        'cbar_fontsize':   9,
    },
    'csi': {
        'cmap': plt.cm.RdYlGn,
        'norm': mcolors.Normalize(vmin=0, vmax=1),
        'cbar_label':      'CSI (0→1, higher=better)',
        'cbar_ticks':      [0, 0.25, 0.5, 0.75, 1.0],
        'cbar_ticklabels': ['0', '0.25', '0.5', '0.75', '1'],
        'cbar_fontsize':   9,
    },
    'pod': {
        'cmap': plt.cm.RdYlGn,
        'norm': mcolors.Normalize(vmin=0, vmax=1),
        'cbar_label':      'POD (Probability of Detection)',
        'cbar_ticks':      [0, 0.25, 0.5, 0.75, 1.0],
        'cbar_ticklabels': ['0', '0.25', '0.5', '0.75', '1'],
        'cbar_fontsize':   9,
    },
    'far': {
        'cmap': plt.cm.RdYlGn_r,
        'norm': mcolors.Normalize(vmin=0, vmax=1),
        'cbar_label':      'FAR (False Alarm Ratio, 0=perfect)',
        'cbar_ticks':      [0, 0.25, 0.5, 0.75, 1.0],
        'cbar_ticklabels': ['0', '0.25', '0.5', '0.75', '1'],
        'cbar_fontsize':   9,
    },
    'brier': {
        'cmap': plt.cm.YlOrRd,
        'norm': mcolors.Normalize(vmin=0, vmax=0.5),
        'cbar_label':      'Brier Score (0=perfect)',
        'cbar_ticks':      [0, 0.1, 0.2, 0.3, 0.4, 0.5],
        'cbar_ticklabels': ['0', '0.1', '0.2', '0.3', '0.4', '0.5'],
        'cbar_fontsize':   9,
    },
}


# Wind overrides for the error-magnitude styles. The registry's limits above are
# precipitation ranges in mm/h, and a wind field in m/s runs larger, so
# `Normalize(0, 2)` saturated most of the map at its top colour and the PNG
# carried no gradient where the interesting variation was. The frontend's band
# edges are the discrete version of the same fix — see WIND_BAND_BASIS in
# src/constants.js.
#
# **Re-derived 2026-10-06, because the first pass measured the wrong data.** It
# read "MAE has a median of 1.79 and a p90 of 4.65", taken from the 2025-09-08
# run — where GEFS and UKMO wind were the 09-16 forecast under the wrong label
# (§24), so two thirds of the sample were scored eight days out of register.
# Over every correctly-paired model-run instead (n=6,564 cells): MAE median
# **1.07**, p90 **1.78**; RMSE p90 2.26; CRPS p90 1.33; bias p05/p95 −1.15/+0.90.
# The old limits were roughly twice as wide as real errors warrant, which is the
# original saturation defect in the other direction — every cell crowded into
# the bottom third of the ramp.
#
# Each vmax sits near the observed p90 rather than the maximum, which leaves
# about 10% of cells clipped on purpose: stretching to the maximum would
# compress the range where nearly every cell actually falls.
#
# Only these four appear here. CSI, POD, FAR, Brier, SSR and correlation are
# dimensionless, so their limits mean the same thing in any unit.
WIND_PLOT_STYLE_OVERRIDES = {
    'bias': {
        'norm': mcolors.TwoSlopeNorm(vmin=-1.5, vcenter=0.0, vmax=1.5),
        'cbar_ticks':      [-1.5, -0.75, 0, 0.75, 1.5],
        'cbar_ticklabels': ['-1.5', '-0.75', '0', '+0.75', '+1.5'],
    },
    'mae': {
        'norm': mcolors.Normalize(vmin=0, vmax=2.0),
        'cbar_ticks':      [0, 0.5, 1.0, 1.5, 2.0],
        'cbar_ticklabels': ['0', '0.5', '1', '1.5', '2'],
    },
    'rmse': {
        'norm': mcolors.Normalize(vmin=0, vmax=2.5),
        'cbar_ticks':      [0, 0.625, 1.25, 1.875, 2.5],
        'cbar_ticklabels': ['0', '0.6', '1.25', '1.9', '2.5'],
    },
    'crps': {
        'norm': mcolors.Normalize(vmin=0, vmax=1.5),
        'cbar_ticks':      [0, 0.375, 0.75, 1.125, 1.5],
        'cbar_ticklabels': ['0', '0.4', '0.75', '1.1', '1.5'],
    },
}


def _plot_style(metric, variable):
    """The plot style for a metric, with the wind scale applied when it applies.

    Falls back to the registry entry untouched for precipitation and for every
    dimensionless metric, so a metric with no override renders exactly as before.
    """
    style = PLOT_STYLE_REGISTRY[metric]
    if variable == 'wind' and metric in WIND_PLOT_STYLE_OVERRIDES:
        return {**style, **WIND_PLOT_STYLE_OVERRIDES[metric]}
    return style




def _render_metric_map_png(points, cmap, norm, cbar_label, title,
                           cbar_ticks=None, cbar_ticklabels=None,
                           cbar_fontsize=9):
    """Render scattered metric points as a Cartopy PNG, base64-encoded.

    The points arrive on the shared 0.5° analysis grid; the cell size is measured
    from them rather than assumed, so this does not care what grid they are on
    (see the `_grid_step` call below — hard-coding 0.25 was a bug).

    Shared by /api/spatial-metric-plot and /api/compare/spatial-diff so both
    draw identical map furniture — only the colour mapping and title differ.
    Callers must release their DB connection first: rendering is CPU-bound and
    holding a pooled connection across it starves concurrent requests.
    """
    # ── Build a 2-D grid from the scattered points ─────────────────────
    # Keyed at 0.25°, which is lossless for 0.5° input and is what the
    # difference map keys on too (see metrics._spatial_diff_points).
    lats_set = sorted(set(round(p['lat'] * 4) / 4 for p in points))
    lons_set = sorted(set(round(p['lon'] * 4) / 4 for p in points))

    pt_lookup = {
        (round(p['lat'] * 4) / 4, round(p['lon'] * 4) / 4): float(p['value'])
        for p in points
    }

    lat_arr  = np.array(lats_set)
    lon_arr  = np.array(lons_set)
    val_grid = np.full((len(lat_arr), len(lon_arr)), np.nan)
    for i, lat in enumerate(lats_set):
        for j, lon in enumerate(lons_set):
            v = pt_lookup.get((lat, lon))
            if v is not None:
                val_grid[i, j] = v
    val_masked = np.ma.masked_invalid(val_grid)

    # pcolormesh needs cell-edge coordinates (N+1 values per axis). The step is
    # measured from the data, not assumed: the regridded tables are on a 0.5°
    # grid, and hard-coding 0.25 drew every cell a quarter-degree north-east of
    # its true centre with the final row/column at half width.
    lat_step  = _grid_step(lats_set)
    lon_step  = _grid_step(lons_set)
    lat_edges = np.append(lat_arr - lat_step / 2, lat_arr[-1] + lat_step / 2)
    lon_edges = np.append(lon_arr - lon_step / 2, lon_arr[-1] + lon_step / 2)
    lon_mesh, lat_mesh = np.meshgrid(lon_edges, lat_edges)

    # ── Map extent ────────────────────────────────────────────────────
    lat_range = lat_arr.max() - lat_arr.min()
    lon_range = lon_arr.max() - lon_arr.min()
    pad = max(2.0, min(lat_range, lon_range) * 0.18)
    extent = [
        lon_arr.min() - pad, lon_arr.max() + pad,
        lat_arr.min() - pad, lat_arr.max() + pad,
    ]

    # ── Figure (OO API — no pyplot global state; see import note) ──────
    proj = ccrs.PlateCarree()
    fig  = Figure(figsize=(13, 7), dpi=130)
    FigureCanvasAgg(fig)
    ax   = fig.add_subplot(111, projection=proj)
    ax.set_extent(extent, crs=proj)

    # Geographic features
    ax.add_feature(cfeature.OCEAN.with_scale('50m'),
                   facecolor='#cce4f5', zorder=0)
    ax.add_feature(cfeature.LAND.with_scale('50m'),
                   facecolor='#f2ede4', zorder=0)
    ax.add_feature(cfeature.LAKES.with_scale('50m'),
                   facecolor='#cce4f5', edgecolor='#4a7ea5', linewidth=0.4, zorder=1)
    ax.add_feature(cfeature.RIVERS.with_scale('50m'),
                   edgecolor='#8ab4cc', linewidth=0.3, zorder=1)

    # Metric overlay
    mesh = ax.pcolormesh(
        lon_mesh, lat_mesh, val_masked,
        cmap=cmap, norm=norm,
        transform=proj, alpha=0.85, zorder=2,
    )

    # Borders, coastlines, states drawn on top of overlay
    ax.add_feature(cfeature.STATES.with_scale('50m'),
                   linewidth=0.35, edgecolor='#999999', zorder=3)
    ax.add_feature(cfeature.BORDERS.with_scale('50m'),
                   linewidth=0.65, edgecolor='#444444', zorder=3)
    ax.add_feature(cfeature.COASTLINE.with_scale('50m'),
                   linewidth=0.8,  edgecolor='#1a1a1a', zorder=3)

    # Gridlines with degree labels
    gl = ax.gridlines(
        draw_labels=True, linewidth=0.4, color='gray',
        alpha=0.55, linestyle='--',
        x_inline=False, y_inline=False,
    )
    gl.top_labels   = False
    gl.right_labels = False
    gl.xlabel_style = {'size': 9,  'color': '#333333'}
    gl.ylabel_style = {'size': 9,  'color': '#333333'}

    # Colourbar
    cbar = fig.colorbar(mesh, ax=ax, orientation='vertical',
                        pad=0.025, shrink=0.82, aspect=26)
    cbar.set_label(cbar_label, fontsize=10, labelpad=10, color='#222222')
    if cbar_ticks is not None:
        cbar.set_ticks(cbar_ticks)
    if cbar_ticklabels is not None:
        cbar.set_ticklabels(cbar_ticklabels, fontsize=cbar_fontsize)
    cbar.ax.tick_params(labelcolor='#333333')

    ax.set_title(title, fontsize=10.5, fontweight='bold', pad=10, color='#1a1a1a')

    # Small watermark
    ax.text(0.995, 0.005, 'WEAVE', transform=ax.transAxes,
            fontsize=7, color='gray', alpha=0.55, ha='right', va='bottom')

    fig.tight_layout(pad=0.4)

    # ── Encode PNG → base64 ───────────────────────────────────────────
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=130, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    buf.seek(0)
    # No plt.close(): this Figure was never registered with pyplot, so it
    # carries no global state to release and is freed on scope exit.
    return base64.b64encode(buf.read()).decode('utf-8')


VAR_LABELS = {
    'precipitation':  'Precipitation',
    'wind':           'Wind Speed',
    'temperature_2m': 'Temperature (2 m)',
    'pressure_msl':   'Mean Sea-Level Pressure',
}
CATEGORICAL_METRICS = {'csi', 'pod', 'far', 'brier'}

# The unit a value carries, for the metrics that inherit the variable's unit
# (bias, MAE, RMSE, CRPS). The scores in [0,1] — CSI, POD, FAR, Brier, SSR,
# correlation — are dimensionless and carry no placeholder.
VALUE_UNITS = {
    'precipitation':  'mm/h',
    'wind':           'm/s',
    'temperature_2m': 'K',
    'pressure_msl':   'Pa',
}


def _metric_cbar_label(metric, variable):
    """The colourbar label for a metric, in the unit that variable is scored in.

    These labels are drawn into the PNG and repeated in its title, so a
    hard-coded unit is a wrong statement a user cannot see past — the same
    defect class as the `units: 'mm/h'` that /api/compare/skill used to return
    for wind.
    """
    label = PLOT_STYLE_REGISTRY.get(metric, {}).get('cbar_label', metric)
    return label.replace('{unit}', VALUE_UNITS.get(variable, ''))


@app.route('/api/spatial-metric-plot', methods=['POST'])
def spatial_metric_plot():
    """
    Accepts pre-computed spatial metric points from the React frontend and returns
    a cartopy/matplotlib figure as a base64 PNG.

    Request JSON body:
        {
          "metric":   "ssr" | "correlation",
          "model":    "AIFS" | "GEFS" | "UKMO",
          "variable": "precipitation" | "wind" | ...,
          "hour":     6,           // forecast hour (SSR only)
          "n_hours":  4,           // verified lead times (correlation only)
          "points":   [{"lat": ..., "lon": ..., "value": ...}, ...]
        }
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400

    # Content-addressed cache key: the request body (chiefly `points`) is the
    # entire visual input, so a hash of it self-invalidates on new data — no
    # explicit TTL/invalidation needed, just a long expiry to bound cache size.
    _cache_key = 'plot:' + hashlib.sha256(
        json.dumps(body, sort_keys=True, default=str).encode()
    ).hexdigest()
    _cached = _cache_get(_cache_key)
    if _cached is not None:
        return jsonify(_cached)

    try:
        metric   = body.get('metric',   'ssr')
        model    = body.get('model',    'AIFS')
        variable = body.get('variable', 'precipitation')
        hour     = body.get('hour',     6)
        n_hours  = body.get('n_hours',  None)
        points   = body.get('points',   [])

        if not points:
            return jsonify({'error': 'No points provided'}), 400

        if metric not in PLOT_STYLE_REGISTRY:
            return jsonify({'error': f'No plot style for metric: {metric}'}), 400
        style = _plot_style(metric, variable)

        # ── Title ─────────────────────────────────────────────────────────
        var_label    = VAR_LABELS.get(variable, variable)
        metric_label = _metric_cbar_label(metric, variable)
        title_line1  = f"{model}  ·  {var_label}  ·  {metric_label}"
        thr_info = ''
        if metric in CATEGORICAL_METRICS:
            if variable == 'wind':
                # Wind thresholds are m/s. Callers that only send the
                # threshold_mm_6h key still carry an m/s value for wind, so
                # fall back to it rather than labelling the map "mm/6h".
                thr = body.get('threshold_ms', body.get('threshold_mm_6h', 10))
                thr_info = f'  ·  thr >{thr} m/s'
            else:
                thr_info = f"  ·  thr >{body.get('threshold_mm_6h', 25)} mm/6h"
        if metric == 'ssr':
            title_line2 = f"Forecast +{hour}h  |  {len(points)} grid points"
        elif metric == 'correlation':
            title_line2 = f"{n_hours} verified lead times  |  {len(points)} grid points"
        else:
            title_line2 = f"{len(points)} grid points{thr_info}"

        img_b64 = _render_metric_map_png(
            points, style['cmap'], style['norm'], metric_label,
            f"{title_line1}\n{title_line2}",
            cbar_ticks=style['cbar_ticks'],
            cbar_ticklabels=style['cbar_ticklabels'],
            cbar_fontsize=style['cbar_fontsize'],
        )

        log.info(f"✅ Plot: {metric} · {model} · {var_label} · {len(points)} pts")
        result = {'image': img_b64}
        _cache_set(_cache_key, result, timeout=int(os.environ.get('PLOT_CACHE_TTL', 24 * 3600)))
        return jsonify(result)

    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/config', methods=['GET'])
def get_config():
    """The facts the frontend would otherwise have to restate.

    `SYSTEM_DESIGN_PLAN.md` S4 asks for "one backend source of truth, exposed to
    the frontend via a config endpoint", with the exit criterion that adding a
    model, variable or metric is a single-place change. This is that endpoint.

    **What it serves and what it deliberately does not.** It serves *facts*:
    which metrics exist, what each one needs from the caller, which variables
    exist and in what unit, which metrics have a map, and the common
    verification window. It does not serve *presentation* — colours, labels,
    legend wording and band edges stay in `src/constants.js`, because those are
    genuine frontend concerns and the band edges carry a calibration rationale
    (`WIND_BAND_BASIS`) that belongs with them.

    That split is not a compromise. The server-rendered PNG and the browser
    overlay are intentionally different renderings: `PLOT_STYLE_REGISTRY` uses a
    continuous `Normalize` for most metrics while the overlay uses discrete
    bands, so forcing one set of colours through here would make them agree by
    breaking one of them. The two *do* share SSR's boundaries, and the parity
    test pins those specifically.

    No database access, so it answers while the pool is busy and cannot fail
    over a query. `n_members` therefore comes from `/api/runs`, which already
    reports it per run — the member count is a property of a run, not of a
    model, and `src/constants.js` hardcoding it per model was wrong in principle
    even while the numbers happened to be right.
    """
    return jsonify({
        'variables': {name: {'unit': unit}
                      for name, unit in VARIABLE_UNITS.items()},
        'metrics': {
            key: {
                'requires_hour':      METRIC_REQUIREMENTS[key]['hour'],
                'requires_threshold': METRIC_REQUIREMENTS[key]['threshold'],
                # Every spatial metric has a map; `fss` is the one that cannot
                # and is absent from this registry for that reason.
                'mapped':             True,
                # Whether the metric's scale is unit-sensitive. The dimensionless
                # ones (CSI, POD, FAR, SSR, correlation) mean the same thing in
                # any unit and deliberately have no wind variant.
                'unit_sensitive':     key in WIND_PLOT_STYLE_OVERRIDES,
            }
            for key in SPATIAL_METRIC_REGISTRY
        },
        'region_metrics':       COMPARE_REGION_METRICS,
        # FSS is a property of a field at a lead time, so it has a region value
        # and no per-cell map. Stated here so the UI need not special-case it.
        'region_no_cell_value': sorted(COMPARE_REGION_NO_CELL_VALUE),
        # The three that need a spread and so read the member grid (§21, §25).
        'region_spread_metrics': sorted(COMPARE_REGION_SPREAD_METRICS),
        'verification_window_hours': COMMON_VERIFICATION_WINDOW_HOURS,
    })


@app.route('/api/models', methods=['GET'])
def get_models():
    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("""
            SELECT DISTINCT m.model_name, m.model_id
            FROM models m
            JOIN forecast_runs fr ON m.model_id = fr.model_id
            ORDER BY m.model_name
        """)
        models = cursor.fetchall()
        return jsonify([{'name': m['model_name'], 'id': m['model_id']} for m in models])
    finally:
        cursor.close()
        return_db_connection(conn)


@app.route('/api/variables', methods=['GET'])
def get_variables():
    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT variable_name FROM variables ORDER BY variable_name")
        variables = cursor.fetchall()
        return jsonify([v['variable_name'] for v in variables])
    finally:
        cursor.close()
        return_db_connection(conn)


# ── Tropical cyclone tracks ───────────────────────────────────────────────────
# NEXT_STEPS.md §37, TC_TAB_DESIGN.md. A different shape from everything else
# here: not a field on the 0.5° lattice but an ordered polyline per ensemble
# member, so these get their own tables and their own endpoints rather than a
# variant of the forecast ones.

@app.route('/api/cyclones', methods=['GET'])
def list_cyclones():
    """What storms are loaded — the `/api/runs` of the cyclone tab.

    One row per (storm, centre, initialisation), because that is what a user
    picks. `?basin=NA` filters to the canonical basin; **`basin IS NULL` is not
    a missing value**, it means the source was coarser than the vocabulary —
    MOGREPS writes `SH` where NCEP writes `SI` or `SP` — so a basin filter
    deliberately excludes rather than guessing (TC_DATA_ACCESS.md).
    """
    basin = request.args.get('basin')
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(f"""
            SELECT storm_name, centre, system, init_time, basin, basin_source,
                   nominal_members, tracked_members, genesis_variants,
                   lead_min, lead_max
            FROM cyclone_run_registry
            {'WHERE basin = %s' if basin else ''}
            ORDER BY init_time DESC, storm_name, centre
        """, (basin,) if basin else ())
        rows = [{**r, 'init_time': r['init_time'].isoformat()}
                for r in cursor.fetchall()]
        storms = []
        for r in rows:
            if r['storm_name'] not in storms:
                storms.append(r['storm_name'])
        return jsonify({'storms': storms, 'runs': rows})
    finally:
        cursor.close()
        return_db_connection(conn)


# ── One track per member ──────────────────────────────────────────────────────
# `cyclone_track_member`'s key includes `cyclone_id`, so a member *may* carry
# more than one candidate cyclone. Every view here draws, scores and counts one
# track per member, so where that happens one has to be chosen — and the choice
# is made in one place rather than three, because three copies of a tie-break
# are three chances to disagree (`NEXT_STEPS.md`: grep the query, not the
# function name).
#
# The rule: the candidate with the most points wins, ties broken by the earlier
# start and then by id. "Most points" means the one the member tracked longest,
# which is the member's storm in any reading; the rest of the ordering exists
# only so the answer is deterministic rather than whatever the planner returns.
#
# **No run in the current archive exercises this.** Measured across all 1,181
# source files, no member carries more than one `cyclone_id`. This is here so
# that the widened constraint cannot turn a silent row-drop at load time into a
# silently zigzagging polyline at render time — moving a defect rather than
# fixing it.
_PRIMARY_TRACK_CTE = """
        WITH primary_track AS (
            SELECT member_id, cyclone_id,
                   row_number() OVER (
                       PARTITION BY member_id
                       ORDER BY count(*) DESC, min(lead_hours), cyclone_id) AS rn
            FROM cyclone_track_member
            WHERE storm_name = %s AND centre = %s AND init_time = %s
            GROUP BY member_id, cyclone_id
        )"""
_PRIMARY_TRACK_JOIN = """
            JOIN primary_track p ON p.member_id = t.member_id
                                AND p.cyclone_id = t.cyclone_id AND p.rn = 1"""


@app.route('/api/cyclone/tracks', methods=['GET'])
def cyclone_tracks():
    """Every member's track for one storm, from one centre, at one init.

    The spaghetti map. Returns the members as separate polylines rather than a
    flat point list, because the client draws one line per member and
    regrouping 1,275 points by member in the browser is work the database has
    already done by sorting.

    **`nominal_members` is returned and is not decoration.** A member that
    forecast no cyclone has no track, so `len(members)` is the number that
    *developed* a storm, not the number that ran — ECMWF files carry anywhere
    from 28 to 51. Showing 28 tracks and letting a reader take that for the
    ensemble understates the spread in the direction that matters most, which
    is whether the storm happens at all. The UI is expected to print both.
    """
    storm  = request.args.get('storm')
    centre = request.args.get('centre')
    init   = request.args.get('init')
    if not storm or not centre:
        return jsonify({'error': 'storm and centre are required'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("""
            SELECT storm_name, centre, system, init_time, basin, basin_source,
                   nominal_members, tracked_members, genesis_variants
            FROM cyclone_run_registry
            WHERE storm_name = %s AND centre = %s
              AND (%s::timestamp IS NULL OR init_time = %s::timestamp)
            ORDER BY init_time DESC LIMIT 1
        """, (storm, centre, init, init))
        run = cursor.fetchone()
        if run is None:
            return jsonify({'error': f'no run for {storm} from {centre}'}), 404

        cursor.execute(_PRIMARY_TRACK_CTE + """
            SELECT t.member_id, t.lead_hours, t.valid_time, t.latitude,
                   t.longitude, t.pressure_hpa, t.wind_ms
            FROM cyclone_track_member t""" + _PRIMARY_TRACK_JOIN + """
            WHERE t.storm_name = %s AND t.centre = %s AND t.init_time = %s
            ORDER BY t.member_id, t.lead_hours
        """, (storm, centre, run['init_time'], storm, centre, run['init_time']))
        members = {}
        for r in cursor.fetchall():
            members.setdefault(r['member_id'], []).append({
                'lead': r['lead_hours'],
                'valid_time': r['valid_time'].isoformat(),
                'lat': r['latitude'], 'lon': r['longitude'],
                'pressure_hpa': r['pressure_hpa'], 'wind_ms': r['wind_ms'],
            })

        # How many members had a second candidate cyclone that the selection
        # above discarded. Reported rather than assumed-zero: it is zero for
        # every run in this archive, and a response that quietly stopped saying
        # so would be indistinguishable from one where it had stopped being
        # true. Cheap — it reads the same rows the planner has just scanned.
        cursor.execute("""
            SELECT count(*) AS n FROM (
                SELECT member_id FROM cyclone_track_member
                WHERE storm_name=%s AND centre=%s AND init_time=%s
                GROUP BY member_id HAVING count(DISTINCT cyclone_id) > 1) x
        """, (storm, centre, run['init_time']))
        variant_members = cursor.fetchone()['n']

        # The observed track over the same window, so the map can show what
        # actually happened beside what was forecast.
        cursor.execute("""
            SELECT valid_time, latitude, longitude, wmo_wind, wmo_pressure, nature
            FROM cyclone_best_track
            WHERE storm_name = %s
              AND valid_time BETWEEN
                  (SELECT min(valid_time) FROM cyclone_track_member
                    WHERE storm_name=%s AND centre=%s AND init_time=%s)
              AND (SELECT max(valid_time) FROM cyclone_track_member
                    WHERE storm_name=%s AND centre=%s AND init_time=%s)
            ORDER BY valid_time
        """, (storm, storm, centre, run['init_time'],
              storm, centre, run['init_time']))
        best = [{'valid_time': r['valid_time'].isoformat(),
                 'lat': r['latitude'], 'lon': r['longitude'],
                 'wind_ms': r['wmo_wind'], 'pressure_hpa': r['wmo_pressure'],
                 'nature': r['nature']} for r in cursor.fetchall()]

        return jsonify({
            'storm':   run['storm_name'],
            'centre':  run['centre'],
            'system':  run['system'],
            'init_time': run['init_time'].isoformat(),
            'basin':   run['basin'],
            'basin_source': run['basin_source'],
            # Both counts, always. See the docstring.
            'nominal_members': run['nominal_members'],
            'tracked_members': run['tracked_members'],
            'genesis_variants': run['genesis_variants'],
            # Members for which a second candidate cyclone was dropped so that
            # one member draws one line. 0 everywhere in this archive.
            'variant_members': variant_members,
            'members': [{'member_id': m, 'points': pts}
                        for m, pts in sorted(members.items())],
            'best_track': best,
        })
    finally:
        cursor.close()
        return_db_connection(conn)


@app.route('/api/cyclone/strike-probability', methods=['GET'])
def cyclone_strike_probability():
    """§37 feature 2: the fraction of the ensemble passing within R of each cell.

    A dimensionless field in [0, 1] on the 0.5° lattice — **the same shape as
    every other field this app renders**, which is why this reading of feature 2
    was chosen over fifty translucent member rasters: it goes through the
    existing overlay unchanged.

    `radius_km` is a control rather than a constant because it changes the
    answer, the same bargain the threshold metrics strike. The lead window
    reuses `hour_min`/`hour_max`.

    **Divided by `nominal_members`, not by the tracks returned.** See
    `cyclone_metrics` for why that is a correctness issue rather than a
    bookkeeping one, and the response carries both counts so a reader can check.
    """
    storm  = request.args.get('storm')
    centre = request.args.get('centre')
    init   = request.args.get('init')
    if not storm or not centre:
        return jsonify({'error': 'storm and centre are required'}), 400
    try:
        radius_km = float(request.args.get('radius_km',
                                           cyclone_metrics.DEFAULT_RADIUS_KM))
        hour_min = int(request.args.get('hour_min', 0))
        hour_max = int(request.args.get('hour_max', 10_000))
    except ValueError:
        return jsonify({'error': 'radius_km, hour_min and hour_max must be '
                                 'numbers'}), 400
    if not 1 <= radius_km <= 2000:
        return jsonify({'error': 'radius_km must be between 1 and 2000'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("""
            SELECT init_time, nominal_members, tracked_members, system
            FROM cyclone_run_registry
            WHERE storm_name = %s AND centre = %s
              AND (%s::timestamp IS NULL OR init_time = %s::timestamp)
            ORDER BY init_time DESC LIMIT 1
        """, (storm, centre, init, init))
        run = cursor.fetchone()
        if run is None:
            return jsonify({'error': f'no run for {storm} from {centre}'}), 404

        cursor.execute(_PRIMARY_TRACK_CTE + """
            SELECT t.member_id, t.latitude, t.longitude
            FROM cyclone_track_member t""" + _PRIMARY_TRACK_JOIN + """
            WHERE t.storm_name=%s AND t.centre=%s AND t.init_time=%s
              AND t.lead_hours BETWEEN %s AND %s
            ORDER BY t.member_id, t.lead_hours
        """, (storm, centre, run['init_time'],
              storm, centre, run['init_time'], hour_min, hour_max))
        rows = cursor.fetchall()
        if not rows:
            # An honest empty rather than a field of zeros: no track in the
            # window is a different statement from "nowhere was struck".
            return jsonify({'points': [], 'radius_km': radius_km,
                            'nominal_members': run['nominal_members'],
                            'tracked_members': 0,
                            'reason': 'no track points in this lead window'})

        # Unwrapped against the first point, so a storm across ±180 is one
        # field rather than two with a gap. Wrapped again on the way out.
        reference = rows[0]['longitude']
        tracks = {}
        for r in rows:
            lon = r['longitude']
            previous = tracks.get(r['member_id'], [(None, reference)])[-1][1]
            while lon - previous > 180:
                lon -= 360
            while previous - lon > 180:
                lon += 360
            tracks.setdefault(r['member_id'], []).append((r['latitude'], lon))

        field = cyclone_metrics.strike_probability(
            tracks, run['nominal_members'], radius_km=radius_km)
        peak, cells = cyclone_metrics.summarise(field)
        return jsonify({
            'storm': storm, 'centre': centre, 'system': run['system'],
            'init_time': run['init_time'].isoformat(),
            'radius_km': radius_km,
            'hour_min': hour_min, 'hour_max': hour_max,
            'nominal_members': run['nominal_members'],
            'tracked_members': run['tracked_members'],
            'peak': round(peak, 4), 'cells': cells,
            'points': [{'lat': lat, 'lon': cyclone_metrics.wrap(lon),
                        'value': round(v, 4)} for lat, lon, v in field],
        })
    finally:
        cursor.close()
        return_db_connection(conn)


@app.route('/api/cyclone/error-by-lead', methods=['GET'])
def cyclone_error_by_lead():
    """Track error and ensemble spread against lead time, for one run.

    `TC_TAB_DESIGN.md` §6 view 2, and the data for view 3. This is the existing
    metric-against-lead shape with `distance_km` in place of MAE, and it asks
    the question the whole application asks — does the ensemble's disagreement
    match its error — in track space.

    **Recomputed from the loaded positions, not read from the source's
    `distance_km`.** `compare_cyclone_derived.py` established that their column
    is haversine at R = 6371.0 and reproduces to 2e-13 km, so this returns the
    same numbers; the difference is that these have a derivation a reader can
    check. The column beside it, `mean_lon`, was wrong by up to 213° and the two
    were indistinguishable by inspection.
    """
    storm  = request.args.get('storm')
    centre = request.args.get('centre')
    init   = request.args.get('init')
    if not storm or not centre:
        return jsonify({'error': 'storm and centre are required'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("""
            SELECT init_time, system, nominal_members, tracked_members
            FROM cyclone_run_registry
            WHERE storm_name = %s AND centre = %s
              AND (%s::timestamp IS NULL OR init_time = %s::timestamp)
            ORDER BY init_time DESC LIMIT 1
        """, (storm, centre, init, init))
        run = cursor.fetchone()
        if run is None:
            return jsonify({'error': f'no run for {storm} from {centre}'}), 404

        cursor.execute(_PRIMARY_TRACK_CTE + """
            SELECT t.member_id, t.lead_hours, t.valid_time, t.latitude,
                   t.longitude
            FROM cyclone_track_member t""" + _PRIMARY_TRACK_JOIN + """
            WHERE t.storm_name=%s AND t.centre=%s AND t.init_time=%s
            ORDER BY t.lead_hours, t.member_id
        """, (storm, centre, run['init_time'], storm, centre, run['init_time']))
        points = [(r['member_id'], r['lead_hours'], r['valid_time'],
                   r['latitude'], r['longitude']) for r in cursor.fetchall()]

        cursor.execute("""
            SELECT valid_time, latitude, longitude
            FROM cyclone_best_track WHERE storm_name = %s
        """, (storm,))
        best = {r['valid_time']: (r['latitude'], r['longitude'])
                for r in cursor.fetchall()}

        rows = cyclone_metrics.error_by_lead(points, best)
        return jsonify({
            'storm': storm, 'centre': centre, 'system': run['system'],
            'init_time': run['init_time'].isoformat(),
            'nominal_members': run['nominal_members'],
            'tracked_members': run['tracked_members'],
            # The lead beyond which the observation record stops. Named rather
            # than left for a reader to infer from a line that simply ends:
            # "the forecast outruns the truth" is a live behaviour here, not an
            # error (NEXT_STEPS.md item 4).
            'last_verified_lead': max((r['lead'] for r in rows
                                       if r['verified']), default=None),
            'points': rows,
        })
    finally:
        cursor.close()
        return_db_connection(conn)


@app.route('/api/runs', methods=['GET'])
def get_runs():
    """What forecast data is actually loaded, per model, variable and run.

    DATA_EXPANSION_DESIGN.md phase 2 asks for this so the UI can populate a run
    selector from the data rather than a hard-coded list. It is also the honest
    answer to "what do you have?", which nothing previously answered — a caller
    had to infer the loaded run from a scoring endpoint's valid times.

    `runs` is the distinct initialisation times, newest first, which is what a
    selector needs; `entries` is the per-(model, variable) detail behind them.
    """
    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        entries = available_runs(cursor)
        runs = []
        for e in entries:
            t = e['init_time'].isoformat()
            if t not in runs:
                runs.append(t)
        by_run = {}
        for e in entries:
            t = e['init_time'].isoformat()
            by_run.setdefault(t, {'init_time': t, 'models': {}, 'variables': []})
            by_run[t]['models'].setdefault(e['model_name'], {
                'n_members': e['n_members'],
                'variables': [],
            })
            m = by_run[t]['models'][e['model_name']]
            m['variables'].append({
                'variable': e['variable_name'],
                'hour_min': e['hour_min'],
                'hour_max': e['hour_max'],
                'export_divisor_h': e['export_divisor_h'],
            })
            if e['variable_name'] not in by_run[t]['variables']:
                by_run[t]['variables'].append(e['variable_name'])
        return jsonify({
            'runs':    runs,
            'latest':  runs[0] if runs else None,
            'detail':  [by_run[t] for t in runs],
            'entries': [{**e, 'init_time': e['init_time'].isoformat()}
                        for e in entries],
        })
    finally:
        cursor.close()
        return_db_connection(conn)


@app.route('/api/forecast-hours', methods=['GET'])
def forecast_hours():
    """The lead times a run actually holds, for one model and variable.

    The timeline used a constant: `for (let h = 0; h <= 360; h += 6)` in
    `constants.js`, shared by all three models. That describes no model in this
    archive. Measured against it: 40 of GEFS precipitation's 80 steps are off
    that grid (it is 3-hourly), **121 of UKMO's 155** are, and GEFS wind reaches
    **+384 h**, so 24 hours of loaded data sat past the scrubber's top and could
    not be selected at all (`NEXT_STEPS.md` §38).

    `hour_min`/`hour_max` from `/api/runs` cannot replace this. UKMO's steps run
    1, 2, 3, 4, 5, 7, 8, ... — irregular, so no min/max/stride reproduces them,
    and a client that assumed a stride would invent lead times the run does not
    have. The list is the only honest answer.

    **Derived from the data, not from the registry.** A `hours` column on
    `forecast_run_registry` would be faster and could drift from the rows it
    describes, which is §24's defect exactly — a table confidently stating
    something no longer true. Measured cost of the aggregate for one
    (model, variable, run): 22 ms for AIFS, 52 ms for GEFS wind, 66 ms for
    UKMO's 155 steps. Cheap because it is one group; the same aggregate over
    every group is ~850 ms, which is why this is its own lazy endpoint rather
    than a field on `/api/runs`.

    Query: model, variable, init_time (optional — resolved when unambiguous)
    """
    model_name = request.args.get('model',    'AIFS')
    variable   = request.args.get('variable', 'precipitation')
    if _bad_token(model_name, variable):
        return jsonify({'error': 'Invalid model or variable'}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        requested = request.args.get('init_time', _UNSET)
        init_time = _resolve_init_time(cursor, model_name, requested)
        # `None` means no run is loaded for this model at all — an unknown name,
        # or a model this database does not have. Answered as 404 rather than an
        # empty list, because "no such run" and "this run holds no hours for
        # that variable" are different facts and a client that conflates them
        # cannot tell a typo from a gap. Without this guard the `.isoformat()`
        # below raised and the endpoint 500ed; a test caught it.
        if init_time is None:
            return jsonify({'error': f'no loaded run for {model_name}',
                            'hint': 'GET /api/runs lists what is loaded'}), 404
        cursor.execute("""
            SELECT array_agg(DISTINCT forecast_hour ORDER BY forecast_hour) AS hours
            FROM regridded_forecast_ens
            WHERE model_name = %s AND variable_name = %s AND init_time = %s
        """, (model_name, variable, init_time))
        hours = cursor.fetchone()['hours'] or []
        return jsonify({
            'model':     model_name,
            'variable':  variable,
            'init_time': init_time.isoformat(),
            'hours':     hours,
            # Stated so a caller can tell "this run holds nothing for this
            # variable" from "the request was wrong", which an empty list alone
            # does not distinguish.
            'count':     len(hours),
        })
    finally:
        cursor.close()
        return_db_connection(conn)


@app.route('/api/observation-coverage', methods=['GET'])
def observation_coverage():
    """How far the observation record reaches, in lead-time terms.

    Every scored endpoint already reports when a *particular* query found no
    observations. None of them could say where the truth ends, so a user scrubbing
    past it saw an empty panel and had no way to tell that from a bug. This exists
    to be stated up front, in the interface, before anything is clicked.

    `last_verifiable_hour` is the answer to "how far out can I expect a score":
    a record covering `window_hours` must have that whole window observed, so it
    is the last window boundary at or before the end of the record. Each variable
    has its own record, which is why this is computed per variable rather than
    once: on the loaded run IMERG ends **+23.5 h** after initialisation, giving
    +18 h for precipitation (6 h windows), while ERA5 ends +23 h and wind reaches
    +23 h, being instantaneous.

    Those figures were +19.5 h and +18/+19 h until 2026-09-16, when IMERG's
    timestamps were corrected from 4 hours behind UTC (NEXT_STEPS.md section 12).
    The old comment also read IMERG's end as wind's, which it never was.

    Query: model (default AIFS), variable (precipitation | wind)
    """
    model_name = request.args.get('model',    'AIFS')
    variable   = request.args.get('variable', 'precipitation')
    if _bad_token(model_name, variable):
        return jsonify({'error': 'Invalid model or variable'}), 400

    is_wind = (variable == 'wind')
    obs_var = 'wind_speed' if is_wind else 'precipitation'
    obs_src = 'ERA5_WIND'  if is_wind else 'GPM_IMERG_V07B'
    # Wind is instantaneous, so its window is the hour it is valid for.
    window  = 1 if is_wind else COMMON_VERIFICATION_WINDOW_HOURS

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        init_time = _resolve_init_time(cursor, model_name)
        cursor.execute("""
            SELECT MIN(obs_time) AS first_obs, MAX(obs_time) AS last_obs
            FROM regridded_observation
            WHERE variable_name = %s AND source = %s
        """, (obs_var, obs_src))
        row = cursor.fetchone() or {}
        first_obs, last_obs = row.get('first_obs'), row.get('last_obs')

        record_end_lead = last_verifiable = None
        if init_time is not None and last_obs is not None:
            record_end_lead = (last_obs - init_time).total_seconds() / 3600.0
            if record_end_lead >= window:
                last_verifiable = int(math.floor(record_end_lead / window) * window)

        return jsonify({
            'model':        model_name,
            'variable':     variable,
            'source':       obs_src,
            'init_time':    init_time.isoformat() if init_time else None,
            'obs_start':    first_obs.isoformat() if first_obs else None,
            'obs_end':      last_obs.isoformat()  if last_obs  else None,
            # Hours after initialisation at which the record ends (23.5 for
            # precipitation on the loaded run, 23.0 for wind) — not necessarily a
            # scorable lead time itself.
            'record_end_lead_hours': (round(record_end_lead, 2)
                                      if record_end_lead is not None else None),
            'last_verifiable_hour':  last_verifiable,
            'window_hours':          window,
        })
    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        log.exception(f"❌ Error in observation-coverage: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        cursor.close()
        return_db_connection(conn)


def _check_export_convention(cursor, model_name='GEFS', init_time=None):
    """Does the loaded data still match the export convention we assume?

    SCALED_EXPORT_DIVISOR_HOURS describes how the JSON export converted each
    model to mm/h. It is a property of the DATA, not of this code, so it goes
    stale the moment anyone re-exports — and a stale value corrects twice
    without any visible symptom. This reads the answer back out of the data and
    compares, so the mismatch surfaces on /api/health instead of in the numbers.

    See METRICS_AUDIT.md finding 16.
    """
    declared = SCALED_EXPORT_DIVISOR_HOURS.get(model_name)
    result = {'model': model_name, 'declared_divisor_h': declared}
    try:
        # Scoped to one run, because the export convention is a property of a
        # run rather than of a model — which is why `forecast_run_registry`
        # records `export_divisor_h` per (model, variable, init_time). Pooling
        # ratios across two runs exported under different conventions would
        # average them into a number matching neither, and the check would read
        # `MISMATCH` (or worse, `ok`) for reasons nothing in the output explains.
        #
        # `init_time` arrives from the caller rather than being resolved here:
        # this function takes a cursor and does one query, and giving it a second
        # one would make it need a Flask request context for the resolver's cache.
        cursor.execute("""
            SELECT a.mean_value / b.mean_value
            FROM regridded_forecast_ens a
            JOIN regridded_forecast_ens b
              ON b.model_name = a.model_name AND b.variable_name = a.variable_name
             AND b.init_time = a.init_time
             AND b.forecast_hour = a.forecast_hour - 3
             AND b.latitude = a.latitude AND b.longitude = a.longitude
            WHERE a.model_name = %s AND a.variable_name = 'precipitation'
              AND a.init_time = %s
              AND a.forecast_hour %% 6 = 0 AND a.forecast_hour > 0
              AND a.mean_value > 0.01 AND b.mean_value > 0.01
            LIMIT 20000
        """, (model_name, init_time))
        ratios = [float(r[0]) for r in cursor.fetchall()]
    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:                      # a missing table is not fatal here
        log.warning(f"⚠️  export-convention check could not run: {e}")
        return dict(result, status='unknown', reason='query failed')

    inferred = _infer_scaled_export_divisor(ratios)
    result.update(inferred_divisor_h=inferred, n_samples=len(ratios))
    if inferred is None:
        result['status'] = 'indeterminate'
        result['detail'] = ('too few samples or an ambiguous ratio — check by hand '
                            'before trusting precipitation scores')
    elif declared is None or inferred == declared:
        result['status'] = 'ok'
    else:
        result['status'] = 'MISMATCH'
        result['detail'] = (
            f'the data looks like a divisor of {inferred} h but the code assumes '
            f'{declared} h. If {model_name} was re-exported, set '
            f'SCALED_EXPORT_DIVISOR_HOURS[{model_name!r}] to {inferred}; until then '
            f'its precipitation is off by a factor of {declared / inferred:g}.')
        log.exception(f"❌ export-convention MISMATCH for {model_name}: {result['detail']}")
    return result


# ── The per-run export convention ─────────────────────────────────────────────
#
# `SCALED_EXPORT_DIVISOR_HOURS` describes the export that happens to be loaded.
# `forecast_run_registry` describes each run's own, which is the only thing that
# works once two runs exist — see run_registry.py and DATA_EXPANSION_DESIGN.md
# phase 4.
#
# Cached process-wide and keyed on the run, which is safe where a single
# "current divisor" would not be: the key includes `init_time`, so two runs get
# two entries and concurrent requests for different runs cannot read each
# other's. The registry only changes when data is loaded, and the standing rule
# after a data change is to restart the server (NEXT_STEPS.md section 1).
_DIVISOR_CACHE = {}
_DIVISOR_MISS  = object()


def _export_divisor(model_name, init_time, variable='precipitation'):
    """The divisor this run's export applied, or None if it applied none.

    Falls back to the constant when the registry cannot answer, and says so
    once per key rather than per request. Raising would be the louder choice
    and is wrong here: a database that predates the registry would lose every
    precipitation endpoint at once, and the fallback reproduces exactly the
    behaviour those deployments already have. What must not happen silently is
    a *second* run being scored with the first's divisor — and that cannot
    happen through this path, because a missing row logs and a present row is
    per-run by construction.
    """
    key = (model_name, variable, str(init_time))
    hit = _DIVISOR_CACHE.get(key, _DIVISOR_MISS)
    if hit is not _DIVISOR_MISS:
        return hit

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            value = run_registry.resolve_divisor(cur, model_name, variable, init_time)
    except Exception as exc:
        value = SCALED_EXPORT_DIVISOR_HOURS.get(model_name)
        log.warning(f"⚠️  export convention for {model_name}/{variable} at {init_time} "
              f"unavailable ({type(exc).__name__}: {exc}); falling back to the "
              f"constant ({value}). Run `python run_registry.py --backfill`.")
    finally:
        if conn is not None:
            return_db_connection(conn)

    _DIVISOR_CACHE[key] = value
    return value


@app.route('/api/ready', methods=['GET'])
def readiness():
    """Can this worker serve a request right now? 200 or 503.

    Deliberately *not* `/api/health`, which S2 noted is deep but is not a
    readiness probe: health reports database size, pool headroom, storage
    headroom and the export convention, which is what an operator reads once.
    A load balancer asks a different and much narrower question, several times a
    minute, and must not be the reason those queries run.

    So this takes a connection from the pool and runs `SELECT 1`. That covers
    the two ways this worker can be unable to serve — the pool is exhausted, or
    the database is unreachable — and nothing else. A failure is **503, not
    500**: the process is fine and is telling the truth about itself, and the
    distinction is what lets a balancer take it out of rotation rather than a
    pager treat it as a crash.
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute('SELECT 1')
            cur.fetchone()
        return jsonify({'ready': True}), 200
    except Exception as e:
        # Not `log.exception`: an unready worker during a rolling restart is
        # expected, and a stack trace per probe would bury the one that matters.
        log.warning('readiness probe failed: %s: %s', type(e).__name__, e)
        return jsonify({'ready': False, 'reason': type(e).__name__}), 503
    finally:
        return_db_connection(conn)


@app.route('/api/health', methods=['GET'])
def health_check():
    # Acquiring the connection is inside the try: an exhausted or unreachable
    # pool is exactly the condition a health check exists to report, so it must
    # answer "unhealthy" rather than fall through to the generic 500 handler.
    conn = cursor = None
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        # The planner's estimate, not an exact count.
        #
        # `SELECT COUNT(*) FROM forecast_data` is a sequential scan, and that
        # table is 128M rows: it took **20 seconds**, which is what the whole
        # health check cost. A health endpoint that slow is worse than useless
        # — DEPLOY.md's smoke test curls it, a proxy or load balancer times it
        # out, and it gets slower with every run loaded.
        #
        # `reltuples` answers instantly and is accurate to within a percent
        # after ANALYZE. Nothing needs the exact figure here: this number
        # exists to say "the database is reachable and has data in it", and an
        # estimate says that just as well. The key is named `_estimate` so no
        # caller mistakes it for a count.
        cursor.execute("""
            SELECT GREATEST(reltuples, 0)::bigint
            FROM pg_class WHERE oid = 'forecast_data'::regclass
        """)
        count = cursor.fetchone()[0]
        # This handler uses a plain tuple cursor, so the run is resolved
        # positionally here rather than through `_resolve_init_time`, which
        # indexes its row by name. Getting that wrong is not loud: the broad
        # `except` below would report the whole database as unhealthy over a
        # KeyError in the convention check.
        cursor.execute("""
            SELECT MAX(fr.initialization_time)
            FROM forecast_runs fr
            JOIN models m ON m.model_id = fr.model_id
            WHERE m.model_name = %s
        """, ('GEFS',))
        gefs_init = cursor.fetchone()[0]
        return jsonify({
            "status": "healthy",
            "database": "connected",
            "total_forecast_points_estimate": count,
            # Whether the loaded data still matches what the metric layer assumes
            # about the export. Re-exporting without updating the constant would
            # otherwise correct twice, silently and invisibly.
            "precip_export_convention": _check_export_convention(
                cursor, init_time=gefs_init),
            # Whether workers × DB_POOL_MAX still fits under max_connections.
            # Reported here because the failure it predicts only appears under
            # concurrent load, by which point it reads as a database fault.
            "connection_pool": _check_pool_headroom(cursor),
            # Whether another run still fits under the retention threshold.
            # `safe: false` means a retention decision is due, not that anything
            # is wrong — see DB_SIZE_REVISIT_GB and DATA_EXPANSION_DESIGN.md
            # phase 5.
            "storage": _check_storage_headroom(cursor),
            # What this worker has served since it started: counts by status
            # class and recent latency percentiles. In-process and reset by a
            # restart, which the payload says of itself rather than leaving a
            # reader to assume it is cluster-wide (S2; a real metrics backend is
            # S3's business).
            "requests": REQUEST_STATS.snapshot(),
        })
    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        # Log the detail server-side but don't leak the raw exception string
        # (DB internals / connection strings) to the client.
        log.exception(f"❌ Health check failed: {e}")
        return jsonify({"status": "unhealthy", "database": "unavailable"}), 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            return_db_connection(conn)












# ── Comparison endpoints (multi-model, regridded_forecast_ens / regridded_observation) ──


@app.route('/api/compare/timeseries', methods=['POST'])
def compare_timeseries():
    """
    Returns ensemble mean and std per forecast hour for multiple models at a
    single lat/lon point, queried from regridded_forecast_ens.

    Request JSON:
        { models, lat, lon, hour_min, hour_max, variable }
    Response:
        { "AIFS": [{"hour": 6, "mean": 1.234, "std": 0.456, "raw_mean": 7.4,
                    "period_h": 6}, ...], ... }

    `mean`/`std` are RATES (mm/h for precipitation, m/s for wind) — the backend
    applies each model's record semantics so the client never has to. `raw_mean`
    is the stored value, kept for the tooltip.
    """
    body     = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400
    models   = body.get('models', [])
    variable = body.get('variable', 'precipitation')
    if _bad_token(*models, variable):
        return jsonify({'error': 'Invalid model or variable'}), 400
    point, err = _parse_latlon(body, 35.0, -75.0)
    if err:
        return err
    lat, lon = point
    try:
        hour_min = int(body.get('hour_min', 0))
        hour_max = int(body.get('hour_max', 168))
    except (TypeError, ValueError):
        return jsonify({'error': 'hour_min and hour_max must be numeric'}), 400

    # Wind → forecast SPEED via u/v self-join (see _fcst_speed_sql); precip → the
    # variable itself. (Was: raw u-component, which isn't a speed.)
    is_wind = (variable == 'wind')
    var_name = variable

    if not models:
        return jsonify({'error': 'No models specified'}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        _key = _body_cache_key('cmp-ts', cursor, body, (
            'models', 'variable', 'lat', 'lon', 'hour_min', 'hour_max',
            'init_time',
        ))
        _cached = _cache_get(_key)
        if _cached is not None:
            return jsonify(_cached)

        _sel, _frm, _varw, _vnn = _fcst_speed_sql(is_wind, "u.model_name, u.forecast_hour")
        _runw, _runp, _runs = _run_pairs_sql(cursor, models)
        cursor.execute(f"""
            SELECT {_sel}
            FROM {_frm}
            WHERE u.model_name = ANY(%s) AND {_varw}
              {_runw}
              AND u.forecast_hour BETWEEN %s AND %s
              AND u.latitude  BETWEEN %s AND %s
              AND u.longitude BETWEEN %s AND %s
            ORDER BY u.model_name, u.forecast_hour
        """, (
            models, *(() if is_wind else (var_name,)), *_runp,
            max(0, hour_min - (0 if is_wind else max(
                (_precip_lookback_hours(m) for m in models), default=0))),
            hour_max,
            lat - 0.26, lat + 0.26,
            lon - 0.26, lon + 0.26,
        ))
        rows = cursor.fetchall()

        # Group per model, then convert to rates with that model's semantics.
        # Multiple cells can fall in the box; keep the first per (model, hour)
        # so the series stays one value per lead time.
        raw_by_model = {}
        for row in rows:
            if row['mean_value'] is None:
                continue
            series = raw_by_model.setdefault(row['model_name'], {})
            series.setdefault(row['forecast_hour'],
                              (float(row['mean_value']),
                               float(row['std_dev']) if row['std_dev'] is not None else None))

        result = {}
        for m, series in raw_by_model.items():
            # The run's own divisor, not the module constant. `_runs` already
            # holds each model's resolved init_time, so there is nothing to look
            # up twice. Before this the chart read
            # `SCALED_EXPORT_DIVISOR_HOURS`, which is per *model*, so a run
            # whose export differed from the constant would have been drawn at
            # the wrong rate while every scored number beside it was right.
            rates = _precip_rate_series(m, series, is_wind,
                                        exported=_export_divisor(m, _runs.get(m)))
            result[m] = [
                {
                    'hour':     hour,
                    'mean':     round(mean_rate, 4),
                    'std':      round(std_rate, 4) if std_rate is not None else None,
                    'raw_mean': round(series[hour][0], 4),
                    'period_h': period,
                }
                for hour, (mean_rate, std_rate, period) in sorted(rates.items())
                if hour_min <= hour <= hour_max
            ]

        log.info(f"✅ compare/timeseries: {sum(len(v) for v in result.values())} pts "
              f"for models {models} at ({lat},{lon})")
        _cache_set(_key, result, timeout=METRIC_CACHE_TTL)
        return jsonify(result)

    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        log.exception(f"❌ Error in compare/timeseries: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        cursor.close()
        return_db_connection(conn)


@app.route('/api/compare/skill', methods=['POST'])
def compare_skill():
    """
    Computes per-hour and summary skill metrics (SSR, CRPS, Bias, MAE, RMSE)
    by matching regridded_forecast_ens values against regridded_observation at the
    valid time = initialization_time + forecast_hour hours.

    Request JSON:
        { models, lat, lon, hour_min, hour_max, variable }
    """
    body     = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400
    models   = body.get('models', [])
    variable = body.get('variable', 'precipitation')
    if _bad_token(*models, variable):
        return jsonify({'error': 'Invalid model or variable'}), 400
    point, err = _parse_latlon(body, 35.0, -75.0)
    if err:
        return err
    lat, lon = point
    try:
        hour_min = int(body.get('hour_min', 0))
        hour_max = int(body.get('hour_max', 168))
    except (TypeError, ValueError):
        return jsonify({'error': 'hour_min and hour_max must be numeric'}), 400

    if variable == 'wind':
        fcst_var = 'wind_u_10m'
        obs_var  = 'wind_speed'
        obs_src  = 'ERA5_WIND'
    else:
        fcst_var = variable          # e.g. 'precipitation'
        obs_var  = 'precipitation'
        obs_src  = 'GPM_IMERG_V07B'

    if not models:
        return jsonify({'error': 'No models specified'}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Deterministic, and 2.7 s for three models over the full lead-time
        # range. The Comparison point panel re-requests it on every parameter
        # change.
        _key = _body_cache_key('cmp-skill', cursor, body, (
            'models', 'variable', 'lat', 'lon', 'hour_min', 'hour_max',
            'init_time',
        ))
        _cached = _cache_get(_key)
        if _cached is not None:
            return jsonify(_cached)

        # ------------------------------------------------------------------
        # 1. Resolve each model's nearest grid cell to the requested point
        # ------------------------------------------------------------------
        # A +/-0.26 degree box on a 0.5 degree grid catches one cell only when
        # the point is grid-aligned; near a cell corner it catches four, which
        # previously returned each lead time up to 4x and averaged the summary
        # over rows rather than lead times. Pin one cell per model instead.
        init_times = {m: _resolve_init_time(cursor, m) for m in models}
        init_times = {m: t for m, t in init_times.items() if t is not None}
        if not init_times:
            return jsonify({'models': {}, 'obs_hours': [],
                            'obs_warning': 'No forecast data found for selected parameters.'})

        is_wind = (variable == 'wind')
        cell_of = {}
        for m in list(init_times):
            cursor.execute("""
                SELECT latitude, longitude
                FROM regridded_forecast_ens
                WHERE model_name = %s AND variable_name = %s
                  AND init_time = %s
                  AND latitude  BETWEEN %s AND %s
                  AND longitude BETWEEN %s AND %s
                ORDER BY POWER(latitude - %s, 2) + POWER(longitude - %s, 2)
                LIMIT 1
            """, (m, fcst_var, init_times[m],
                  lat - 1.0, lat + 1.0, lon - 1.0, lon + 1.0, lat, lon))
            row = cursor.fetchone()
            if row:
                cell_of[m] = (float(row['latitude']), float(row['longitude']))
        if not cell_of:
            return jsonify({'models': {}, 'obs_hours': [],
                            'obs_warning': 'No forecast data found for selected parameters.'})

        # ------------------------------------------------------------------
        # 2-3. Per-model, per-lead-time cases at that cell
        # ------------------------------------------------------------------
        # From the MEMBER grid, through the one helper the spatial maps and
        # /api/spread-skill use. This endpoint was the last reader of the
        # aggregate `regridded_forecast_ens` spread on a scored path, which meant
        # the Comparison point panel and the Analysis point panel reported
        # different SSRs for the same cell and lead time — up to 31% apart on the
        # loaded run. Same defect as METRICS_AUDIT.md finding 11, one endpoint
        # behind; see NEXT_STEPS.md.
        eps = 1e-6
        cases_of = {}
        for m, (m_lat, m_lon) in cell_of.items():
            cases = _member_cases_by_cell(
                cursor, m, variable, init_times[m],
                m_lat - eps, m_lat + eps, m_lon - eps, m_lon + eps)
            by_hour = {h: c for h, c in (cases.get((round(m_lat, 2), round(m_lon, 2)))
                                         or {}).items()
                       if hour_min <= h <= hour_max}
            if by_hour:
                cases_of[m] = by_hour

        if not cases_of:
            return jsonify({'models': {}, 'obs_hours': [],
                            'obs_warning': 'No forecast data found for selected parameters.'})

        # ------------------------------------------------------------------
        # 3b. Per-lead-time metrics
        # ------------------------------------------------------------------
        # Every model is put in one unit first — mm/h for precipitation, m/s for
        # wind — so cross-model comparisons are fair. SSR is scale-invariant;
        # CRPS/bias/MAE/RMSE scale with the unit, so that shared normalisation is
        # what makes them comparable.
        model_data = {}

        for m_name, by_hour in cases_of.items():
            model_data[m_name] = [_point_case_record(by_hour[h])
                                  for h in sorted(by_hour)]

        # ------------------------------------------------------------------
        # 4. Compute per-model summaries
        # ------------------------------------------------------------------
        result_models = {}
        obs_hours_all = set()

        for m_name, hours_list in model_data.items():
            result_models[m_name] = {
                'hours':   hours_list,
                'summary': _point_summary(hours_list),
            }
            obs_hours_all.update(h['hour'] for h in hours_list)

        obs_hours_sorted = sorted(obs_hours_all)

        # Build obs_warning
        if obs_hours_sorted:
            n_obs = len(obs_hours_sorted)
            obs_warning = (
                f"Observations cover {n_obs} lead times "
                f"({obs_hours_sorted[0]}h–{obs_hours_sorted[-1]}h). "
                f"Ingest more data for extended coverage."
            )
        else:  # pragma: no cover - unreachable; see note
            # `cases_of` only gains a model whose `by_hour` is non-empty, and the
            # endpoint returns early when `cases_of` is empty, so every entry in
            # `model_data` contributes at least one hour and `obs_hours_all` is
            # never empty here. Kept as a guard rather than deleted, because the
            # invariant lives two screens up; a test asserts the coupling
            # (test_last_guards.py) and will fail if it ever breaks.
            obs_warning = 'No observations found for this location/variable.'

        log.info(f"✅ compare/skill: {len(result_models)} models, "
              f"{len(obs_hours_sorted)} obs hours at ({lat},{lon}), "
              f"cells={ {m: cell_of.get(m) for m in result_models} }")
        result = {
            'models':             result_models,
            'obs_hours':          obs_hours_sorted,
            'obs_warning':        obs_warning,
            # Metadata so the frontend can display the conversion notes
            'model_accum_hours':  {m: MODEL_ACCUM_HOURS.get(m, 1) for m in models},
            # The grid cell each model was actually verified at (finding 3).
            'model_cells':        {m: list(cell_of[m]) for m in result_models if m in cell_of},
            # Precipitation is normalised to a rate; wind is an instantaneous
            # speed and was never in mm/h. Same branch /api/spread-skill uses.
            'units':              'm/s' if is_wind else 'mm/h',
        }
        _cache_set(_key, result, timeout=METRIC_CACHE_TTL)
        return jsonify(result)

    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        log.exception(f"❌ Error in compare/skill: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        cursor.close()
        return_db_connection(conn)


@app.route('/api/compare/spatial-agreement', methods=['POST'])
def compare_spatial_agreement():
    """
    Renders a Cartopy/matplotlib map of model disagreement (STDDEV of ensemble
    mean across models) for a bounding box and a single forecast hour.

    Request JSON:
        { models, min_lat, max_lat, min_lon, max_lon, hour, variable }
    Response:
        { image: base64_png, hour, n_models, n_points }
    """
    body     = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400
    models   = body.get('models', [])
    variable = body.get('variable', 'precipitation')
    if _bad_token(*models, variable):
        return jsonify({'error': 'Invalid model or variable'}), 400
    try:
        min_lat  = float(body.get('min_lat',  25))
        max_lat  = float(body.get('max_lat',  45))
        min_lon  = float(body.get('min_lon', -85))
        max_lon  = float(body.get('max_lon', -65))
        hour     = int(body.get('hour', 24))
    except (TypeError, ValueError):
        return jsonify({'error': 'min_lat, max_lat, min_lon, max_lon, hour must be numeric'}), 400

    is_wind  = (variable == 'wind')
    var_name = variable   # precip path; wind derives speed from u/v (below)

    VAR_UNITS = {
        'precipitation': 'mm/h',
        'wind':          'm/s',
        'wind_u_10m':    'm/s',
        'wind_v_10m':    'm/s',
    }
    unit = VAR_UNITS.get(variable, variable)

    if not models or len(models) < 2:
        return jsonify({'error': 'At least 2 models required for spatial agreement'}), 400

    # This endpoint queries the DB itself (unlike spatial-metric-plot, which
    # renders client-supplied points), so a content hash can't self-invalidate
    # on new data — key on the request shape and bound staleness with a TTL
    # instead, matched to how often a new forecast run actually lands.
    #
    # Deliberately NOT keyed on `_data_version` like the other metric endpoints,
    # even though that would invalidate on a reload instead of waiting out the
    # TTL: the version needs a cursor, and a hit here returns before the
    # connection is taken. Cartopy plus the pool is the expensive half of this
    # endpoint, so paying a query to build the key would give back much of what
    # the cache is for. `test_a_cached_render_short_circuits_before_any_query`
    # pins that, and it is why the TTL stays the invalidation mechanism here.
    #
    # `init_time` IS in the key. Without it, once two runs are loaded, the same
    # models/hour/bbox for a *different* run would be served this run's cached
    # answer — a silent cross-run error of exactly the kind the init_time
    # migration removed, reintroduced by a cache key.
    _cache_key = 'agree:' + json.dumps({
        'models':    sorted(models),
        'variable':  variable,
        'hour':      hour,
        'init_time': str(body.get('init_time')),
        'bbox':      [round(min_lat, 2), round(max_lat, 2), round(min_lon, 2), round(max_lon, 2)],
    }, sort_keys=True)
    _cached = _cache_get(_cache_key)
    if _cached is not None:
        return jsonify(_cached)

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # One run per model on both sides of the comparison. Agreement between
        # models is only meaningful when they are the same forecast: pairing one
        # model's rows with another model's initialisation would report
        # disagreement that is really a difference in start time.
        _runw, _runp, _runs = _run_pairs_sql(cursor, models)
        if is_wind:
            # Inter-model disagreement of forecast wind SPEED. Derive per-model
            # speed √(mean_u²+mean_v²) in a subquery, then aggregate across models.
            cursor.execute(f"""
                SELECT latitude, longitude,
                       STDDEV(speed)              AS disagreement,
                       AVG(speed)                 AS avg_mean,
                       COUNT(DISTINCT model_name) AS n_models
                FROM (
                    SELECT u.model_name, u.latitude, u.longitude,
                           SQRT(POWER(u.mean_value, 2) + POWER(v.mean_value, 2)) AS speed
                    FROM regridded_forecast_ens u
                    JOIN regridded_forecast_ens v
                      ON v.model_name = u.model_name AND v.forecast_hour = u.forecast_hour
                     AND v.init_time = u.init_time
                     AND v.latitude = u.latitude AND v.longitude = u.longitude
                     AND v.variable_name = 'wind_v_10m'
                    WHERE u.model_name = ANY(%s) AND u.variable_name = 'wind_u_10m'
                      {_runw}
                      AND u.forecast_hour = %s
                      AND u.latitude  BETWEEN %s AND %s
                      AND u.longitude BETWEEN %s AND %s
                      AND u.mean_value IS NOT NULL AND v.mean_value IS NOT NULL
                ) s
                GROUP BY latitude, longitude
                HAVING COUNT(DISTINCT model_name) >= 2
                ORDER BY latitude, longitude
            """, (models, *_runp, hour, min_lat, max_lat, min_lon, max_lon))
        else:
            cursor.execute(f"""
                SELECT
                    u.latitude,
                    u.longitude,
                    STDDEV(u.mean_value)          AS disagreement,
                    AVG(u.mean_value)             AS avg_mean,
                    COUNT(DISTINCT u.model_name)  AS n_models
                FROM regridded_forecast_ens u
                WHERE u.model_name    = ANY(%s)
                  AND u.variable_name = %s
                  {_runw}
                  AND u.forecast_hour = %s
                  AND u.latitude  BETWEEN %s AND %s
                  AND u.longitude BETWEEN %s AND %s
                GROUP BY u.latitude, u.longitude
                HAVING COUNT(DISTINCT u.model_name) >= 2
                ORDER BY u.latitude, u.longitude
            """, (models, var_name, *_runp, hour, min_lat, max_lat, min_lon, max_lon))

        rows = cursor.fetchall()
        # All DB access is complete — release the pooled connection BEFORE the
        # multi-second Cartopy render so it isn't held idle during rendering.
        # (Held connections during renders starved the pool under the region
        # "Compute All Maps" burst.) The finally block stays safe: closing an
        # already-closed cursor is a no-op and return_db_connection(None) is guarded.
        cursor.close()
        return_db_connection(conn)
        conn = None

        if not rows:
            return jsonify({'error': 'No overlapping data for selected models/hour/bounds'}), 404

        n_points  = len(rows)
        # Determine the actual number of models represented
        n_models  = max(int(r['n_models']) for r in rows)

        lats  = np.array([float(r['latitude'])      for r in rows])
        lons  = np.array([float(r['longitude'])     for r in rows])
        disag = np.array([float(r['disagreement'])  for r in rows])

        # ── Build 2-D grid ────────────────────────────────────────────────
        lats_set = sorted(set(round(float(r['latitude'])  * 2) / 2 for r in rows))
        lons_set = sorted(set(round(float(r['longitude']) * 2) / 2 for r in rows))

        pt_lookup = {
            (round(float(r['latitude'])  * 2) / 2,
             round(float(r['longitude']) * 2) / 2): float(r['disagreement'])
            for r in rows
        }

        lat_arr  = np.array(lats_set)
        lon_arr  = np.array(lons_set)
        val_grid = np.full((len(lat_arr), len(lon_arr)), np.nan)
        for i, la in enumerate(lats_set):
            for j, lo in enumerate(lons_set):
                v = pt_lookup.get((la, lo))
                if v is not None:
                    val_grid[i, j] = v
        val_masked = np.ma.masked_invalid(val_grid)

        step      = 0.5
        lat_edges = np.append(lat_arr - step / 2, lat_arr[-1] + step / 2)
        lon_edges = np.append(lon_arr - step / 2, lon_arr[-1] + step / 2)
        lon_mesh, lat_mesh = np.meshgrid(lon_edges, lat_edges)

        # ── Colormap & norm ───────────────────────────────────────────────
        max_disag = float(np.nanmax(disag)) if disag.size > 0 else 1.0
        cmap = plt.cm.Reds
        norm = mcolors.Normalize(vmin=0, vmax=max_disag if max_disag > 0 else 1.0)

        # ── Map extent ────────────────────────────────────────────────────
        lat_range = lat_arr.max() - lat_arr.min()
        lon_range = lon_arr.max() - lon_arr.min()
        pad = max(1.5, min(lat_range, lon_range) * 0.12)
        extent = [
            lon_arr.min() - pad, lon_arr.max() + pad,
            lat_arr.min() - pad, lat_arr.max() + pad,
        ]

        # ── Figure (OO API — no pyplot global state; see import note) ──────
        proj = ccrs.PlateCarree()
        fig  = Figure(figsize=(13, 7), dpi=130)
        FigureCanvasAgg(fig)
        ax   = fig.add_subplot(111, projection=proj)
        ax.set_extent(extent, crs=proj)

        # Geographic features (same order as spatial_metric_plot)
        ax.add_feature(cfeature.OCEAN.with_scale('50m'),
                       facecolor='#cce4f5', zorder=0)
        ax.add_feature(cfeature.LAND.with_scale('50m'),
                       facecolor='#f2ede4', zorder=0)
        ax.add_feature(cfeature.LAKES.with_scale('50m'),
                       facecolor='#cce4f5', edgecolor='#4a7ea5', linewidth=0.4, zorder=1)
        ax.add_feature(cfeature.RIVERS.with_scale('50m'),
                       edgecolor='#8ab4cc', linewidth=0.3, zorder=1)

        mesh = ax.pcolormesh(
            lon_mesh, lat_mesh, val_masked,
            cmap=cmap, norm=norm,
            transform=proj, alpha=0.85, zorder=2,
        )

        ax.add_feature(cfeature.STATES.with_scale('50m'),
                       linewidth=0.35, edgecolor='#999999', zorder=3)
        ax.add_feature(cfeature.BORDERS.with_scale('50m'),
                       linewidth=0.65, edgecolor='#444444', zorder=3)
        ax.add_feature(cfeature.COASTLINE.with_scale('50m'),
                       linewidth=0.8,  edgecolor='#1a1a1a', zorder=3)

        gl = ax.gridlines(
            draw_labels=True, linewidth=0.4, color='gray',
            alpha=0.55, linestyle='--',
            x_inline=False, y_inline=False,
        )
        gl.top_labels   = False
        gl.right_labels = False
        gl.xlabel_style = {'size': 9, 'color': '#333333'}
        gl.ylabel_style = {'size': 9, 'color': '#333333'}

        cbar = fig.colorbar(mesh, ax=ax, orientation='vertical',
                            pad=0.025, shrink=0.82, aspect=26)
        cbar.set_label(
            f'Ensemble Mean Std Dev across Models ({unit})',
            fontsize=10, labelpad=10, color='#222222',
        )
        cbar.ax.tick_params(labelcolor='#333333')

        VAR_LABELS = {
            'precipitation': 'Precipitation',
            'wind':          'Wind Speed',
            'wind_u_10m':    'Wind (u-component)',
            'wind_v_10m':    'Wind (v-component)',
        }
        var_label = VAR_LABELS.get(variable, variable)
        ax.set_title(
            f"Model Disagreement — {var_label} — +{hour}h"
            f" | {n_models} models | {n_points} pts",
            fontsize=10.5, fontweight='bold', pad=10, color='#1a1a1a',
        )

        # WEAVE watermark
        ax.text(0.995, 0.005, 'WEAVE', transform=ax.transAxes,
                fontsize=7, color='gray', alpha=0.55, ha='right', va='bottom')

        fig.tight_layout(pad=0.4)

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=130, bbox_inches='tight',
                    facecolor='white', edgecolor='none')
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode('utf-8')
        # No plt.close() — OO Figure, no pyplot global state to release.

        log.info(f"✅ compare/spatial-agreement: {n_points} pts, "
              f"{n_models} models, +{hour}h, {variable}")
        result = {
            'image':    img_b64,
            'hour':     hour,
            'n_models': n_models,
            'n_points': n_points,
        }
        _cache_set(_cache_key, result, timeout=int(os.environ.get('SPATIAL_AGREEMENT_CACHE_TTL', 20 * 60)))
        return jsonify(result)

    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        log.exception(f"❌ Error in compare/spatial-agreement: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        cursor.close()
        return_db_connection(conn)


@app.route('/api/categorical-metrics', methods=['POST'])
def categorical_metrics_endpoint():
    """
    Computes categorical and probabilistic verification metrics at a point.

    Metric definitions (all computed in mm/h after accumulation normalisation):
      POD  = hits / (hits + misses)                  — recall
      FAR  = false_alarms / (hits + false_alarms)    — 0 = perfect
      FBI  = (hits + false_alarms) / (hits + misses) — 1 = perfect
      CSI  = hits / (hits + misses + false_alarms)   — threat score
      BS   = mean((P_event – I_obs)²)               — Brier Score, 0 = perfect
      Composite Confidence (no FSS, weights re-normalised to sum 1):
           = (0.40·CSI + 0.20·POD + 0.10·(1-FAR)) / 0.70

    **FBI is now in both surfaces; Composite Confidence is deliberately not**
    (decided 2026-10-06, CONSISTENCY_AUDIT.md 1d, NEXT_STEPS.md §43). The split
    used to be incidental — no reason for it had ever been recorded — and the two
    halves turned out to deserve opposite answers:

      - **FBI is a measurement**, events forecast over events observed, and its
        counts were already being summed in `_categorical_summary`. It is also
        the one score here that says which *direction* a model is wrong: two
        models with equal CSI can be over- and under-forecasting respectively,
        and nothing else on the Comparison tab would show it. Added.

      - **Composite Confidence is a weighted blend and the weights are a
        judgement nobody has justified.** Within one model it is a summary
        device and the weights cancel out of any comparison a reader makes
        across thresholds or lead times. Ranking *models* by it ranks them by
        the weighting, while looking exactly like a measurement — and the
        Comparison tab exists to rank models. Not added, and that is now a
        decision rather than an oversight.

    Request JSON:
        { model, variable, lat, lon, threshold_mm_6h, hour_min, hour_max }
    """
    body              = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400
    model_name        = body.get('model',            'AIFS')
    variable          = body.get('variable',         'precipitation')
    if _bad_token(model_name, variable):
        return jsonify({'error': 'Invalid model or variable'}), 400
    point, err = _parse_latlon(body, 35.0, -75.0)
    if err:
        return err
    lat, lon = point
    try:
        hour_min          = int(body.get('hour_min',     0))
        hour_max          = int(body.get('hour_max',     168))
        # FSS needs a neighbourhood. `box_cells` = 1 keeps this a true point —
        # CSI/POD/FAR describe the clicked cell and FSS is undefined. Raising it
        # gives FSS a field to work with WITHOUT moving the point metrics, which
        # stay on the centre cell so their meaning never silently changes.
        box_cells         = max(1, min(int(body.get('box_cells',  1)), 41))
        fss_window        = max(1, min(int(body.get('fss_window', 3)), 21))
        # The window slides across the field, so it cannot be wider than it. If
        # it is, every cell's neighbourhood covers the whole field, every
        # fraction equals the field mean, and FSS collapses into a comparison of
        # two domain frequencies — precisely what METRICS_AUDIT.md finding 5
        # rebuilt it to stop being. Widen the field instead, as
        # compare_categorical already does (its `effective_box`).
        #
        # box_cells == 1 is exempt: it is the contract for "a true point", where
        # FSS is undefined by definition, and honouring a window there would
        # quietly turn a point into a neighbourhood.
        if box_cells > 1:
            box_cells = max(box_cells, fss_window)
    except (TypeError, ValueError):
        return jsonify({'error': 'lat, lon, hour_min, hour_max, box_cells, '
                                 'fss_window must be numeric'}), 400

    is_wind = (variable == 'wind')
    try:
        if is_wind:
            fcst_var, obs_var, obs_src = 'wind_u_10m', 'wind_speed', 'ERA5_WIND'
            # Wind speed is in m/s (instantaneous) — use threshold_ms directly.
            threshold_rate = float(body.get('threshold_ms', 10.0))
        else:
            fcst_var, obs_var, obs_src = variable, 'precipitation', 'GPM_IMERG_V07B'
            threshold_rate = float(body.get('threshold_mm_6h', 25.0)) / 6.0
    except (TypeError, ValueError):
        return jsonify({'error': 'threshold must be numeric'}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # ── 1. Forecast rows ─────────────────────────────────────────────────
        init_time_val = _resolve_init_time(cursor, model_name)
        if init_time_val is None:
            return jsonify({'error': 'No forecast data found for the selected parameters.'}), 404
        # Wind → forecast SPEED via u/v self-join (see _fcst_speed_sql).
        # Cumulative models need one record below hour_min to difference against.
        lookback = 0 if is_wind else _precip_lookback_hours(model_name)

        # Centre the box on the nearest grid cell rather than the raw click, so
        # box_cells maps to exactly that many cells per axis instead of 1-or-4
        # depending on where in a cell the user happened to click.
        cursor.execute("""
            SELECT latitude, longitude FROM regridded_forecast_ens
            WHERE model_name = %s AND variable_name = %s
              AND init_time = %s
              AND latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s
            ORDER BY POWER(latitude - %s, 2) + POWER(longitude - %s, 2)
            LIMIT 1
        """, (model_name, fcst_var, init_time_val,
              lat - 1.0, lat + 1.0, lon - 1.0, lon + 1.0, lat, lon))
        centre_row = cursor.fetchone()
        if not centre_row:
            return jsonify({'error': 'No forecast data found for the selected parameters.'}), 404
        c_lat, c_lon = float(centre_row['latitude']), float(centre_row['longitude'])
        hw = max(box_cells * 0.25 - 0.01, 0.05)
        min_lat, max_lat = c_lat - hw, c_lat + hw
        min_lon, max_lon = c_lon - hw, c_lon + hw

        _sel, _frm, _varw, _vnn = _fcst_speed_sql(
            is_wind, "u.forecast_hour, u.latitude, u.longitude")
        cursor.execute(f"""
            SELECT {_sel}
            FROM {_frm}
            WHERE u.model_name = %s AND {_varw}
              AND u.init_time = %s
              AND u.forecast_hour BETWEEN %s AND %s
              AND u.latitude  BETWEEN %s AND %s
              AND u.longitude BETWEEN %s AND %s
              AND u.mean_value IS NOT NULL AND u.std_dev IS NOT NULL {_vnn}
            ORDER BY u.forecast_hour
        """, (model_name, *(() if is_wind else (fcst_var,)), init_time_val,
              max(0, hour_min - lookback), hour_max,
              min_lat, max_lat, min_lon, max_lon))
        fcst_rows = cursor.fetchall()

        if not fcst_rows:
            return jsonify({'error': 'No forecast data found for the selected parameters.'}), 404

        # Convert to mm/h with this model's record semantics (findings 1-2).
        # Several cells can fall in the box; keep the first per hour so the
        # series stays one value per lead time.
        from collections import defaultdict
        raw_by_cell = defaultdict(dict)
        for r in fcst_rows:
            key = (round(float(r['latitude']), 2), round(float(r['longitude']), 2))
            raw_by_cell[key][r['forecast_hour']] = (float(r['mean_value']),
                                                    float(r['std_dev']))
        def _cell_rates(series):
            r = _precip_rate_series(model_name, series, is_wind,
                                    exported=_export_divisor(model_name, init_time_val))
            if not is_wind:
                r = _rebin_to_common_window(r)     # one window for every model
            return {h: v for h, v in r.items() if hour_min <= h <= hour_max}

        rates_by_cell = {cell: _cell_rates(series)
                         for cell, series in raw_by_cell.items()}
        centre_key = (round(c_lat, 2), round(c_lon, 2))
        rates = rates_by_cell.get(centre_key, {})
        if not rates:
            return jsonify({'error': 'No forecast data found for the selected parameters.'}), 404

        # ── 2. Observations (extended window for the longest record period) ───
        valid_times = [init_time_val + timedelta(hours=h) for h in rates]
        max_period  = max(p for _, _, p in rates.values())
        min_obs_t = min(valid_times) - timedelta(hours=max_period)
        max_obs_t = max(valid_times)

        cursor.execute("""
            SELECT obs_time, latitude, longitude, AVG(value) AS obs_val
            FROM regridded_observation
            WHERE variable_name = %s AND source = %s
              AND obs_time BETWEEN %s AND %s
              AND latitude  BETWEEN %s AND %s
              AND longitude BETWEEN %s AND %s
            GROUP BY obs_time, latitude, longitude ORDER BY obs_time
        """, (obs_var, obs_src, min_obs_t, max_obs_t,
              min_lat, max_lat, min_lon, max_lon))
        obs_by_cell = defaultdict(dict)
        for r in cursor.fetchall():
            key = (round(float(r['latitude']), 2), round(float(r['longitude']), 2))
            obs_by_cell[key][r['obs_time']] = float(r['obs_val'])
        # The point metrics read the centre cell only, so their meaning is
        # unchanged by the box: they still describe the clicked location.
        obs_by_time = obs_by_cell.get(centre_key, {})

        if not obs_by_time:
            return jsonify({
                'hours': [], 'summary': {}, 'obs_hours': [],
                'obs_warning': 'No observations found for this location and variable.',
            })

        # ── 3. Per-hour categorical + probabilistic metrics ───────────────────
        hours_data = []
        hits = misses = false_alarms = correct_neg = 0
        # Cases in the contingency table: hours x cells in the box. Reported so
        # a reader can see what a CSI rests on — the centre-cell version this
        # replaced could produce 0.0833 from a single hit in 12 cases.
        n_pts = 0
        brier_sq_sum = 0.0
        n_brier      = 0
        # FSS is the one metric here that needs a field rather than a cell, so
        # it is accumulated separately over every cell in the box.
        fss_num = fss_den = 0.0

        def _box_for_hour(hour):
            """(fss components, [(is_fcst, is_obs, mean, std)]) over the box.

            One scan, two consumers. It used to return only the FSS components
            and the contingency table was built separately from the centre cell
            alone — so `scored_area` reported 81 cells while CSI described 1,
            and the same click gave 0.0833 here against Comparison's 0.2756
            (`NEXT_STEPS.md` §41). The per-cell data was already being computed
            for FSS; only the counting was narrow.
            """
            f_bin, o_bin, cases = {}, {}, []
            for cell, cell_rates in rates_by_cell.items():
                rec = cell_rates.get(hour)
                if rec is None:
                    continue
                c_mean, c_std, c_period = rec
                c_vt = init_time_val + timedelta(hours=hour)
                c_obs, c_covered, _n = _obs_window_mean(obs_by_cell.get(cell), c_vt, c_period)
                if c_obs is None or c_covered < c_period:
                    continue
                f_bin[cell] = float(c_mean > threshold_rate)
                o_bin[cell] = float(c_obs > threshold_rate)
                cases.append((c_mean > threshold_rate, c_obs > threshold_rate,
                              c_mean, c_std))
            return _fss_components(f_bin, o_bin, fss_window), cases

        for hour in sorted(rates):
            mean_rate, std_rate, period = rates[hour]
            vt = init_time_val + timedelta(hours=hour)

            # Obs averaged over the same period the forecast record covers; a
            # partially observed window is rejected (see _obs_window_mean).
            obs_rate, covered, n_obs_window = _obs_window_mean(obs_by_time, vt, period)
            if obs_rate is None or covered < period:
                continue

            is_fcst = mean_rate > threshold_rate
            is_obs  = obs_rate  > threshold_rate

            # Contingency table.
            #
            # **Pooled over the box, not the centre cell** (changed 2026-10-06,
            # `NEXT_STEPS.md` §41). At `box_cells=1` the box *is* the centre
            # cell, so that remains the exact-point case and nothing about it
            # changes. Above 1, every cell in the box contributes a case, which
            # is what `scored_area` has always claimed and what
            # `/api/compare/categorical` has always done.
            if box_cells > 1:
                (h_num, h_den, _n), cases = _box_for_hour(hour)
                fss_num += h_num
                fss_den += h_den
            else:
                cases = [(is_fcst, is_obs, mean_rate, std_rate)]

            for c_fcst, c_obs_hit, c_mean, c_std in cases:
                if   c_fcst and     c_obs_hit: hits         += 1
                elif c_fcst and not c_obs_hit: false_alarms += 1
                elif not c_fcst and c_obs_hit: misses       += 1
                else:                          correct_neg  += 1
                n_pts += 1
                # Brier over the same cases, so the probabilistic and
                # categorical scores describe one sample rather than two.
                c_p = (None if c_std is None
                       else _exceedance_probability(c_mean, c_std, threshold_rate))
                if c_p is not None:
                    brier_sq_sum += (c_p - float(c_obs_hit)) ** 2
                    n_brier      += 1

            # Probabilistic event probability (Gaussian). Needs the spread, which
            # isn't recoverable for every record of a cumulative model, so those
            # records sit out of the Brier score but still count in the
            # contingency table (which only needs the mean).
            p_event = (None if std_rate is None
                       else _exceedance_probability(mean_rate, std_rate, threshold_rate))

            # `p_event` stays for the per-hour series below, which is a
            # centre-cell story by construction; the Brier *score* is
            # accumulated with the cases above.

            hours_data.append({
                'hour':      hour,
                'is_fcst':   int(is_fcst),
                'is_obs':    int(is_obs),
                'p_event':   round(p_event, 4) if p_event is not None else None,
                'mean_rate': round(mean_rate, 4),
                'obs_rate':  round(obs_rate,  4),
                'period_h':  period,
            })

        if not hours_data:
            return jsonify({
                'hours': [], 'summary': {}, 'obs_hours': [],
                'obs_warning': 'No observations matched forecast hours for this location.',
            })

        # ── 4. Summary statistics ─────────────────────────────────────────────
        n            = len(hours_data)
        n_obs_yes    = hits + misses
        n_fcst_yes   = hits + false_alarms
        n_denom_csi  = hits + misses + false_alarms

        pod  = round(hits / n_obs_yes,   4) if n_obs_yes   > 0 else None
        far  = round(false_alarms / n_fcst_yes, 4) if n_fcst_yes > 0 else None
        fbi  = round(n_fcst_yes  / n_obs_yes,   4) if n_obs_yes   > 0 else None
        csi  = round(hits / n_denom_csi, 4) if n_denom_csi > 0 else None
        bs   = round(brier_sq_sum / n_brier, 6) if n_brier else None
        # None at box_cells == 1: a single cell has no neighbourhood to take an
        # event fraction over, so FSS is undefined rather than zero.
        fss  = _fss_from_components(fss_num, fss_den) if box_cells > 1 else None

        # Composite Confidence (FSS excluded — spatial-only metric)
        # Original weights: 0.40 CSI + 0.30 FSS + 0.20 POD + 0.10(1-FAR)
        # Without FSS re-normalise remaining to sum = 1 (÷ 0.70)
        if csi is not None and pod is not None and far is not None:
            if fss is not None:
                composite = round(0.40*csi + 0.30*fss + 0.20*pod + 0.10*(1.0-far), 4)
            else:
                # Re-normalise the remaining weights when FSS is unavailable.
                composite = round(
                    (0.40 * csi + 0.20 * pod + 0.10 * (1.0 - far)) / 0.70, 4
                )
        else:
            composite = None

        obs_hours_list = sorted(h['hour'] for h in hours_data)
        n_obs = len(obs_hours_list)
        obs_warning = (
            f"Observations available for {n_obs} lead times "
            f"({obs_hours_list[0]}h–{obs_hours_list[-1]}h). "
            "Ingest more data to extend verification coverage."
        ) if obs_hours_list else 'No observations found.'

        thr_display = f"{threshold_rate} m/s" if is_wind else f"{round(threshold_rate * 6, 2)} mm/6h"
        log.info(f"✅ categorical-metrics: {model_name} {variable} ({lat},{lon}) "
              f"thr={thr_display}  "
              f"H={hits} M={misses} FA={false_alarms} CN={correct_neg}  "
              f"CSI={csi} POD={pod} FAR={far} FBI={fbi} BS={bs} CC={composite}")

        threshold_info = {'threshold_rate': round(threshold_rate, 4), 'model': model_name}
        # The area actually scored, so the UI never has to guess.
        scored_area = {
            'centre':     [c_lat, c_lon],
            'box_cells':  box_cells,
            'fss_window': fss_window,
            'bbox':       [round(min_lat, 3), round(max_lat, 3),
                           round(min_lon, 3), round(max_lon, 3)],
            'n_cells':    len(rates_by_cell),
        }
        if is_wind:
            threshold_info['threshold_ms'] = threshold_rate
            threshold_info['unit']         = 'm/s'
        else:
            threshold_info['threshold_mm_6h'] = round(threshold_rate * 6, 2)
            threshold_info['unit']             = 'mm/6h'

        return jsonify({
            'hours':        hours_data,
            'summary': {
                # hours x cells behind the counts below. The categorical
                # scores are pooled over `scored_area`, which `n_cells` and
                # `box_cells` describe; before 2026-10-06 they described the
                # FSS area while CSI used the centre cell alone.
                'n_pts':                 n_pts,
                'hits':                  hits,
                'misses':                misses,
                'false_alarms':          false_alarms,
                'correct_neg':           correct_neg,
                'pod':                   pod,
                'far':                   far,
                'fbi':                   fbi,
                'csi':                   csi,
                'brier':                 bs,
                'fss':                   fss,
                'composite_confidence':  composite,
            },
            'obs_hours':    obs_hours_list,
            'obs_warning':  obs_warning,
            'threshold_info': threshold_info,
            'scored_area':    scored_area,
        })

    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        log.exception(f"❌ Error in categorical-metrics: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        cursor.close()
        return_db_connection(conn)


@app.route('/api/region-categorical-metrics', methods=['POST'])
def region_categorical_metrics_endpoint():
    """
    Computes categorical + probabilistic verification metrics aggregated over
    a spatial bounding box, plus FSS (Fractions Skill Score).

    Request JSON:
        { model, variable, min_lat, max_lat, min_lon, max_lon,
          threshold_mm_6h, hour_min, hour_max }
    """
    body            = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400
    model_name      = body.get('model', 'AIFS')
    variable        = body.get('variable', 'precipitation')
    if _bad_token(model_name, variable):
        return jsonify({'error': 'Invalid model or variable'}), 400
    try:
        min_lat         = float(body.get('min_lat', 20.0))
        max_lat         = float(body.get('max_lat', 40.0))
        min_lon         = float(body.get('min_lon', -100.0))
        max_lon         = float(body.get('max_lon', -60.0))
        hour_min        = int(body.get('hour_min', 0))
        hour_max        = int(body.get('hour_max', 168))
        # Neighbourhood width for FSS, in grid cells (odd values centre cleanly).
        fss_window      = max(1, min(int(body.get('fss_window', 3)), 21))
    except (TypeError, ValueError):
        return jsonify({'error': 'min_lat, max_lat, min_lon, max_lon, hour_min, hour_max must be numeric'}), 400

    is_wind = (variable == 'wind')
    try:
        if is_wind:
            fcst_var, obs_var, obs_src = 'wind_u_10m', 'wind_speed', 'ERA5_WIND'
            threshold_rate = float(body.get('threshold_ms', 10.0))
        else:
            fcst_var, obs_var, obs_src = variable, 'precipitation', 'GPM_IMERG_V07B'
            threshold_rate = float(body.get('threshold_mm_6h', 25.0)) / 6.0
    except (TypeError, ValueError):
        return jsonify({'error': 'threshold must be numeric'}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # ── 1. Fetch all forecast grid points in bbox ─────────────────────────
        init_time_val = _resolve_init_time(cursor, model_name)
        if init_time_val is None:
            return jsonify({'error': 'No forecast data found for the selected region.'}), 404
        # Wind → forecast SPEED via u/v self-join (see _fcst_speed_sql).
        # Cumulative models need one record below hour_min to difference against.
        lookback = 0 if is_wind else _precip_lookback_hours(model_name)
        _sel, _frm, _varw, _vnn = _fcst_speed_sql(is_wind, "u.forecast_hour, u.latitude, u.longitude")
        cursor.execute(f"""
            SELECT {_sel}
            FROM {_frm}
            WHERE u.model_name = %s AND {_varw}
              AND u.init_time = %s
              AND u.forecast_hour BETWEEN %s AND %s
              AND u.latitude  BETWEEN %s AND %s
              AND u.longitude BETWEEN %s AND %s
              AND u.mean_value IS NOT NULL AND u.std_dev IS NOT NULL {_vnn}
            ORDER BY u.forecast_hour, u.latitude, u.longitude
        """, (model_name, *(() if is_wind else (fcst_var,)), init_time_val,
              max(0, hour_min - lookback), hour_max,
              min_lat, max_lat, min_lon, max_lon))
        fcst_rows = cursor.fetchall()

        if not fcst_rows:
            return jsonify({'error': 'No forecast data found for the selected region.'}), 404

        # Convert each cell's series to mm/h with this model's record semantics.
        from collections import defaultdict
        raw_by_cell = defaultdict(dict)
        for row in fcst_rows:
            key = (round(float(row['latitude']), 2), round(float(row['longitude']), 2))
            raw_by_cell[key][row['forecast_hour']] = (float(row['mean_value']),
                                                      float(row['std_dev']))
        _exp = _export_divisor(model_name, init_time_val)
        rates_by_cell = {cell: (_precip_rate_series(model_name, series, is_wind, exported=_exp) if is_wind
                                else _rebin_to_common_window(
                                    _precip_rate_series(model_name, series, is_wind, exported=_exp)))
                         for cell, series in raw_by_cell.items()}
        in_range = [(cell, h, v) for cell, rates in rates_by_cell.items()
                    for h, v in rates.items() if hour_min <= h <= hour_max]
        if not in_range:
            return jsonify({'error': 'No forecast data found for the selected region.'}), 404

        # ── 2. Fetch per-(lat,lon) observations for the extended time window ──
        valid_times = [init_time_val + timedelta(hours=h) for _, h, _ in in_range]
        max_period  = max(p for _, _, (_, _, p) in in_range)
        min_obs_t = min(valid_times) - timedelta(hours=max_period)
        max_obs_t = max(valid_times)

        cursor.execute("""
            SELECT obs_time, latitude, longitude, AVG(value) AS obs_val
            FROM regridded_observation
            WHERE variable_name = %s AND source = %s
              AND obs_time BETWEEN %s AND %s
              AND latitude  BETWEEN %s AND %s
              AND longitude BETWEEN %s AND %s
            GROUP BY obs_time, latitude, longitude
            ORDER BY obs_time, latitude, longitude
        """, (obs_var, obs_src, min_obs_t, max_obs_t,
              min_lat, max_lat, min_lon, max_lon))
        obs_by_cell = defaultdict(dict)
        for r in cursor.fetchall():
            obs_by_cell[(round(float(r['latitude']), 2),
                         round(float(r['longitude']), 2))][r['obs_time']] = float(r['obs_val'])

        if not obs_by_cell:
            return jsonify({
                'hours': [], 'summary': {}, 'obs_hours': [],
                'obs_warning': 'No observations found for this region.',
            })

        # ── 3. Group converted records by hour and process ────────────────────
        hours_dict = defaultdict(list)
        for cell, hour, vals in in_range:
            hours_dict[hour].append((cell, vals))

        hours_data = []
        total_hits = total_misses = total_fa = total_cn = 0
        total_brier_sum = 0.0
        total_n = 0
        total_n_brier = 0
        total_fss_num = total_fss_den = 0.0
        obs_hours_set = set()

        for hour in sorted(hours_dict.keys()):
            h_hits = h_misses = h_fa = h_cn = 0
            h_brier_sum = 0.0
            h_n_brier   = 0
            h_fcst_binary = {}
            h_obs_binary  = {}
            h_n_pts = 0

            for (lat_k, lon_k), (mean_rate, std_rate, period) in hours_dict[hour]:
                vt = init_time_val + timedelta(hours=hour)

                # Obs averaged over the same period the forecast record covers.
                # A partially observed window is rejected rather than averaged —
                # see _obs_window_mean.
                obs_rate, covered, _n_obs = _obs_window_mean(obs_by_cell.get((lat_k, lon_k)),
                                                             vt, period)
                if obs_rate is None or covered < period:
                    continue

                is_fcst = mean_rate > threshold_rate
                is_obs  = obs_rate  > threshold_rate

                if   is_fcst and     is_obs:  h_hits    += 1
                elif is_fcst and not is_obs:  h_fa      += 1
                elif not is_fcst and is_obs:  h_misses  += 1
                else:                         h_cn      += 1

                # Needs the spread, which isn't recoverable for every record
                # of a cumulative model; those sit out of the Brier score but
                # still count in the contingency table.
                p_event = (None if std_rate is None
                           else _exceedance_probability(mean_rate, std_rate, threshold_rate))

                if p_event is not None:
                    h_brier_sum += (p_event - float(is_obs)) ** 2
                    h_n_brier   += 1
                h_fcst_binary[(lat_k, lon_k)] = float(is_fcst)
                h_obs_binary[(lat_k, lon_k)]  = float(is_obs)
                h_n_pts += 1

            if h_n_pts == 0:
                continue

            # Per-hour metrics
            h_n_obs_yes   = h_hits + h_misses
            h_n_fcst_yes  = h_hits + h_fa
            h_n_denom_csi = h_hits + h_misses + h_fa

            h_csi = round(h_hits / h_n_denom_csi, 4) if h_n_denom_csi > 0 else None
            h_pod = round(h_hits / h_n_obs_yes,   4) if h_n_obs_yes   > 0 else None
            h_far = round(h_fa   / h_n_fcst_yes,  4) if h_n_fcst_yes  > 0 else None
            h_fbi = round(h_n_fcst_yes / h_n_obs_yes, 4) if h_n_obs_yes > 0 else None
            h_bs  = round(h_brier_sum / h_n_brier, 6) if h_n_brier else None

            # Roberts & Lean FSS over a sliding neighbourhood — a placement
            # score. The domain event fractions are still reported alongside
            # because they are useful context (frequency bias), but they are no
            # longer what FSS is computed from.
            fcst_frac = sum(h_fcst_binary.values()) / h_n_pts
            obs_frac  = sum(h_obs_binary.values())  / h_n_pts
            h_fss_num, h_fss_den, _n = _fss_components(
                h_fcst_binary, h_obs_binary, fss_window)
            fss_hour = _fss_from_components(h_fss_num, h_fss_den)

            hours_data.append({
                'hour': hour, 'n_pts': h_n_pts,
                'hits': h_hits, 'misses': h_misses,
                'false_alarms': h_fa, 'correct_neg': h_cn,
                'csi': h_csi, 'pod': h_pod, 'far': h_far, 'fbi': h_fbi,
                'brier': h_bs, 'fss': fss_hour,
                'fcst_frac': round(fcst_frac, 4), 'obs_frac': round(obs_frac, 4),
            })

            obs_hours_set.add(hour)
            total_hits    += h_hits
            total_misses  += h_misses
            total_fa      += h_fa
            total_cn      += h_cn
            total_brier_sum += h_brier_sum
            total_n         += h_n_pts
            total_n_brier   += h_n_brier
            total_fss_num   += h_fss_num
            total_fss_den   += h_fss_den

        # ── 4. Summary statistics ─────────────────────────────────────────────
        n_obs_yes   = total_hits + total_misses
        n_fcst_yes  = total_hits + total_fa
        n_denom_csi = total_hits + total_misses + total_fa

        pod = round(total_hits / n_obs_yes,    4) if n_obs_yes   > 0 else None
        far = round(total_fa   / n_fcst_yes,   4) if n_fcst_yes  > 0 else None
        fbi = round(n_fcst_yes / n_obs_yes,    4) if n_obs_yes   > 0 else None
        csi = round(total_hits / n_denom_csi,  4) if n_denom_csi > 0 else None
        bs  = round(total_brier_sum / total_n_brier, 6) if total_n_brier > 0 else None

        # Aggregate FSS from summed components across lead times, not as a mean
        # of per-hour scores (which would weight a sparse hour like a dense one).
        mean_fss = _fss_from_components(total_fss_num, total_fss_den)

        if csi is not None and pod is not None and far is not None:
            if mean_fss is not None:
                composite = round(0.40*csi + 0.30*mean_fss + 0.20*pod + 0.10*(1.0-far), 4)
            else:  # pragma: no cover - unreachable in the REGION path; see note
                # Here CSI and FSS are decided by the same per-hour loop: FSS's
                # denominator is the sum of squared event fractions and CSI's is
                # the count of hits, misses and false alarms, so either an event
                # exists somewhere and both are defined, or neither is. The POINT
                # endpoint genuinely needs this arm, because there FSS is gated on
                # `box_cells > 1` regardless of whether any event exists — which
                # is why the same-looking branch is live there and dead here.
                composite = round((0.40*csi + 0.20*pod + 0.10*(1.0-far)) / 0.70, 4)
        else:
            composite = None

        # ── 5. Return ─────────────────────────────────────────────────────────
        n_grid_pts = len(set(
            (round(float(r['latitude']), 2), round(float(r['longitude']), 2))
            for r in fcst_rows
        ))
        obs_hours_list = sorted(h['hour'] for h in hours_data)
        obs_warning = (
            f"Observations available for {len(obs_hours_list)} lead times "
            f"({obs_hours_list[0]}h–{obs_hours_list[-1]}h) across ~{n_grid_pts} grid points."
        ) if obs_hours_list else 'No observations matched.'

        log.info(f"✅ region-categorical-metrics: {model_name} {variable} "
              f"bbox=[{min_lat},{max_lat},{min_lon},{max_lon}] "
              f"thr={threshold_rate} ({body.get('threshold_ms') or body.get('threshold_mm_6h')} raw)  "
              f"H={total_hits} M={total_misses} FA={total_fa} CN={total_cn}  "
              f"CSI={csi} POD={pod} FAR={far} FSS={mean_fss} CC={composite}")

        return jsonify({
            'hours':   hours_data,
            'summary': {
                'hits': total_hits, 'misses': total_misses,
                'false_alarms': total_fa, 'correct_neg': total_cn,
                'pod': pod, 'far': far, 'fbi': fbi, 'csi': csi,
                'brier': bs, 'fss': mean_fss,
                'composite_confidence': composite,
                'n_grid_pts': n_grid_pts,
            },
            'obs_hours': obs_hours_list,
            'obs_warning': obs_warning,
            # The neighbourhood FSS was actually computed over. An FSS value is
            # only interpretable alongside its spatial scale, so echo it back
            # rather than leaving the client to assume the default.
            'fss_window': fss_window,
            'threshold_info': {
                **(({'threshold_ms': threshold_rate, 'unit': 'm/s'})
                   if is_wind else
                   ({'threshold_mm_6h': round(threshold_rate * 6, 2), 'unit': 'mm/6h'})),
                'threshold_rate': round(threshold_rate, 4),
                'model':          model_name,
                'bbox':           [min_lat, max_lat, min_lon, max_lon],
            },
        })

    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        log.exception(f"❌ Error in region-categorical-metrics: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        cursor.close()
        return_db_connection(conn)


def _categorical_hours_for_box(cursor, model_name, fcst_var, obs_var, obs_src,
                               min_lat, max_lat, min_lon, max_lon,
                               hour_min, hour_max, threshold_rate, fss_window=3):
    """Per-hour CSI/POD/FAR/FSS over a bbox for a single model.

    Returns a list of {hour, csi, pod, far, fss, n_pts, hits, misses,
    false_alarms, correct_neg}; [] if no data/obs. The raw contingency counts
    let callers pool across lead times (see _categorical_summary) instead of
    averaging ratios, which would over-weight sparse hours.

    FSS is the Roberts & Lean sliding-neighbourhood score over `fss_window`
    grid cells (see _fractions_skill_score), so it measures spatial placement
    rather than overall event frequency.
    """
    init_time_val = _resolve_init_time(cursor, model_name)
    if init_time_val is None:
        return []
    # Wind → forecast SPEED via u/v self-join (see _fcst_speed_sql).
    is_wind  = (fcst_var == 'wind_u_10m')
    lookback = 0 if is_wind else _precip_lookback_hours(model_name)
    _sel, _frm, _varw, _vnn = _fcst_speed_sql(is_wind, "u.forecast_hour, u.latitude, u.longitude")
    cursor.execute(f"""
        SELECT {_sel}
        FROM {_frm}
        WHERE u.model_name = %s AND {_varw}
          AND u.init_time = %s
          AND u.forecast_hour BETWEEN %s AND %s
          AND u.latitude  BETWEEN %s AND %s
          AND u.longitude BETWEEN %s AND %s
          AND u.mean_value IS NOT NULL AND u.std_dev IS NOT NULL {_vnn}
        ORDER BY u.forecast_hour, u.latitude, u.longitude
    """, (model_name, *(() if is_wind else (fcst_var,)), init_time_val,
          max(0, hour_min - lookback), hour_max, min_lat, max_lat, min_lon, max_lon))
    fcst_rows = cursor.fetchall()
    if not fcst_rows:
        return []

    # Per-cell hour series → mm/h rates using this model's record semantics.
    from collections import defaultdict
    raw_by_cell = defaultdict(dict)
    for row in fcst_rows:
        key = (round(float(row['latitude']), 2), round(float(row['longitude']), 2))
        raw_by_cell[key][row['forecast_hour']] = (float(row['mean_value']),
                                                  float(row['std_dev']))
    _exp = _export_divisor(model_name, init_time_val)
    rates_by_cell = {cell: (_precip_rate_series(model_name, series, is_wind, exported=_exp) if is_wind
                            else _rebin_to_common_window(
                                _precip_rate_series(model_name, series, is_wind, exported=_exp)))
                     for cell, series in raw_by_cell.items()}

    in_range = [(cell, h, v) for cell, rates in rates_by_cell.items()
                for h, v in rates.items() if hour_min <= h <= hour_max]
    if not in_range:
        return []

    max_period  = max(p for _, _, (_, _, p) in in_range)
    valid_times = [init_time_val + timedelta(hours=h) for _, h, _ in in_range]
    min_obs_t = min(valid_times) - timedelta(hours=max_period)
    max_obs_t = max(valid_times)

    cursor.execute("""
        SELECT obs_time, latitude, longitude, AVG(value) AS obs_val
        FROM regridded_observation
        WHERE variable_name = %s AND source = %s
          AND obs_time BETWEEN %s AND %s
          AND latitude  BETWEEN %s AND %s
          AND longitude BETWEEN %s AND %s
        GROUP BY obs_time, latitude, longitude
    """, (obs_var, obs_src, min_obs_t, max_obs_t,
          min_lat, max_lat, min_lon, max_lon))
    obs_by_cell = defaultdict(dict)
    for r in cursor.fetchall():
        obs_by_cell[(round(float(r['latitude']), 2),
                     round(float(r['longitude']), 2))][r['obs_time']] = float(r['obs_val'])
    if not obs_by_cell:
        return []

    hours_dict = defaultdict(list)
    for cell, hour, vals in in_range:
        hours_dict[hour].append((cell, vals))

    out = []
    for hour in sorted(hours_dict.keys()):
        h_hits = h_misses = h_fa = h_cn = 0
        h_fcst_binary, h_obs_binary, h_n_pts = {}, {}, 0
        for (lat_k, lon_k), (mean_rate, _std_rate, period) in hours_dict[hour]:
            vt = init_time_val + timedelta(hours=hour)
            # Obs averaged over the same period the forecast record covers; a
            # partially observed window is rejected (see _obs_window_mean).
            obs_rate, covered, _n_obs = _obs_window_mean(obs_by_cell.get((lat_k, lon_k)),
                                                         vt, period)
            if obs_rate is None or covered < period:
                continue
            is_fcst = mean_rate > threshold_rate
            is_obs  = obs_rate  > threshold_rate
            if   is_fcst and     is_obs:  h_hits   += 1
            elif is_fcst and not is_obs:  h_fa     += 1
            elif not is_fcst and is_obs:  h_misses += 1
            else:                         h_cn     += 1
            h_fcst_binary[(lat_k, lon_k)] = float(is_fcst)
            h_obs_binary[(lat_k, lon_k)]  = float(is_obs)
            h_n_pts += 1

        if h_n_pts == 0:
            continue
        n_obs_yes   = h_hits + h_misses
        n_fcst_yes  = h_hits + h_fa
        n_denom_csi = h_hits + h_misses + h_fa
        csi = round(h_hits / n_denom_csi, 4) if n_denom_csi > 0 else None
        pod = round(h_hits / n_obs_yes,   4) if n_obs_yes   > 0 else None
        far = round(h_fa   / n_fcst_yes,  4) if n_fcst_yes  > 0 else None
        fss_num, fss_den, _n_fss = _fss_components(h_fcst_binary, h_obs_binary, fss_window)
        fss = _fss_from_components(fss_num, fss_den)
        fbi = round(n_fcst_yes / n_obs_yes, 4) if n_obs_yes > 0 else None
        out.append({'hour': hour, 'n_pts': h_n_pts,
                    'csi': csi, 'pod': pod, 'far': far, 'fbi': fbi, 'fss': fss,
                    'hits': h_hits, 'misses': h_misses,
                    'false_alarms': h_fa, 'correct_neg': h_cn,
                    # kept so _categorical_summary can aggregate FSS properly
                    'fss_num': fss_num, 'fss_den': fss_den})
    return out




@app.route('/api/compare/categorical', methods=['POST'])
def compare_categorical():
    """Per-model categorical skill (CSI/POD/FAR/FSS) over lead time, evaluated
    over a small neighbourhood around a point so FSS is meaningful.

    Request JSON:
        { models: [..], lat, lon, hour_min, hour_max, variable,
          threshold_mm_6h | threshold_ms, fss_window, box_cells }
    Response JSON:
        { models:    { AIFS: [{hour, csi, pod, far, fss, n_pts}], .. },
          summaries: { AIFS: {csi, pod, far, fss, brier, n_pts, n_hours}, .. },
          threshold_info, fss_window, bbox }

    `summaries` is additive: `models` keeps its per-hour list shape.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400
    models   = body.get('models', [])
    variable = body.get('variable', 'precipitation')
    if not isinstance(models, list) or not models:
        return jsonify({'error': 'models must be a non-empty list'}), 400
    if not all(isinstance(m, str) for m in models):
        return jsonify({'error': 'models must be a list of strings'}), 400
    if _bad_token(*models, variable):
        return jsonify({'error': 'Invalid model or variable'}), 400
    point, err = _parse_latlon(body, 35.0, -75.0)
    if err:
        return err
    lat, lon = point
    try:
        hour_min   = int(body.get('hour_min',    0))
        hour_max   = int(body.get('hour_max',    168))
        fss_window = int(body.get('fss_window',  3))
        box_cells  = int(body.get('box_cells',   9))
    except (TypeError, ValueError):
        return jsonify({'error': 'lat, lon, hour_min, hour_max, fss_window, '
                                 'box_cells must be numeric'}), 400
    fss_window = max(1, min(fss_window, 21))     # clamp to a sane neighbourhood
    box_cells  = max(1, min(box_cells, 41))

    is_wind = (variable == 'wind')
    try:
        if is_wind:
            fcst_var, obs_var, obs_src = 'wind_u_10m', 'wind_speed', 'ERA5_WIND'
            threshold_rate = float(body.get('threshold_ms', 10.0))
        else:
            fcst_var, obs_var, obs_src = variable, 'precipitation', 'GPM_IMERG_V07B'
            threshold_rate = float(body.get('threshold_mm_6h', 25.0)) / 6.0
    except (TypeError, ValueError):
        return jsonify({'error': 'threshold must be numeric'}), 400

    # The verification box and the FSS neighbourhood are separate things and are
    # now separate parameters. They used to share one: widening the neighbourhood
    # also widened the domain, so CSI/POD/FAR moved when only the FSS scale was
    # meant to. `box_cells` sizes the box; `fss_window` is the sliding
    # neighbourhood inside it. The box is never allowed to be smaller than the
    # window, or the neighbourhood would be clipped to the domain and FSS would
    # silently collapse toward the old domain-fraction behaviour.
    effective_box  = max(box_cells, fss_window)
    hw = max(effective_box * 0.25, 0.26)
    min_lat, max_lat = lat - hw, lat + hw
    min_lon, max_lon = lon - hw, lon + hw

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        per_model  = {}
        summaries  = {}
        for m in models:
            per_model[m] = _categorical_hours_for_box(
                cursor, m, fcst_var, obs_var, obs_src,
                min_lat, max_lat, min_lon, max_lon,
                hour_min, hour_max, threshold_rate, fss_window)
            summary = _categorical_summary(per_model[m])
            if summary is not None:
                # Brier is probabilistic (Gaussian exceedance from mean/spread),
                # so it can't be pooled from the deterministic counts above —
                # take the neighbourhood mean of the per-cell Brier scores.
                brier_pts = _compute_brier_points_rf(
                    cursor, m, variable,
                    min_lat, max_lat, min_lon, max_lon,
                    hour_min, hour_max, threshold_rate=threshold_rate)
                summary['brier'] = (round(float(np.mean([p['value'] for p in brier_pts])), 4)
                                    if brier_pts else None)
            summaries[m] = summary

        threshold_info = ({'threshold_ms': threshold_rate, 'unit': 'm/s'} if is_wind
                          else {'threshold_mm_6h': round(threshold_rate * 6, 2), 'unit': 'mm/6h'})
        threshold_info['threshold_rate'] = round(threshold_rate, 4)

        total = sum(len(v) for v in per_model.values())
        log.info(f"✅ compare/categorical: {len(models)} models, "
              f"{total} model-hours, ({lat},{lon}) window={fss_window} "
              f"thr={threshold_info.get('unit')}")

        return jsonify({
            'models':         per_model,
            'summaries':      summaries,
            'threshold_info': threshold_info,
            'fss_window':     fss_window,
            'box_cells':      effective_box,
            'bbox':           [round(min_lat, 3), round(max_lat, 3),
                               round(min_lon, 3), round(max_lon, 3)],
        })
    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        log.exception(f"❌ Error in compare/categorical: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        cursor.close()
        return_db_connection(conn)


# ── Region-level model comparison ─────────────────────────────────────────────
# The metric suite the Comparison tab's region mode offers. `ssr` (single-hour)
# is deliberately absent: region views aggregate over a lead-time range, which
# is what `ssr_agg` does. `correlation` runs the ensemble path and so is not in
# the pairs-based table below.
COMPARE_REGION_METRIC_FNS = {
    'ssr_agg': _compute_ssr_agg_points_rf,
    'bias':    _compute_bias_points_rf,
    'mae':     _compute_mae_points_rf,
    'rmse':    _compute_rmse_points_rf,
    'crps':    _compute_crps_points_rf,
    'csi':     _compute_csi_points_rf,
    'pod':     _compute_pod_points_rf,
    'far':     _compute_far_points_rf,
    'brier':   _compute_brier_points_rf,
}
COMPARE_REGION_METRICS = ['ssr_agg', 'correlation', 'bias', 'mae', 'rmse',
                          'crps', 'csi', 'pod', 'far', 'fbi', 'brier', 'fss']

# The metrics here that need a SPREAD, and so must come from the member grid
# rather than the regridded mean/spread table.
#
# `_rebin_to_common_window` returns `std = None` for any record it has to
# combine, because the spread of a mean is not the mean of spreads. UKMO is
# hourly, so every record combines and the aggregate path carries no spread for
# it at all. §21 fixed that for the maps and the two point endpoints by routing
# them through `_member_pairs_by_cell`, and **left region mode behind**: region
# mode fetches its pairs once and hands the same dict to all nine metrics, so
# UKMO's CRPS, aggregate SSR and Brier were empty in the Comparison tab's region
# view at every run and every lead range.
#
# `ssr` is not here because it is single-hour and not in the region suite;
# `correlation` is not here because it already runs the member path itself.
COMPARE_REGION_SPREAD_METRICS = frozenset({'crps', 'ssr_agg', 'brier'})

# The region metrics with no per-cell value: no map, and no entry in
# `cell_means`.
#
# FSS is a property of a whole field at a lead time. FBI is a ratio of pooled
# counts, and at one cell both counts are 0 or 1, so a per-cell FBI takes the
# values 0, 1 and undefined and nothing else — a map of it would be a map of
# three colours that looks like a measurement. It is reported as a region
# number, the same treatment the point surface gives it.
COMPARE_REGION_NO_CELL_VALUE = {'fbi', 'fss'}


def _single_metric_points(cursor, model_name, variable, metric,
                          min_lat, max_lat, min_lon, max_lon,
                          hour_min, hour_max, threshold_rate):
    """Per-cell points for one metric and one model.

    Handles both families: the pairs-based metrics off the regridded mean/spread
    table, and `correlation`, which needs the member grid and the run's init time.
    """
    if metric in COMPARE_REGION_METRIC_FNS:
        return COMPARE_REGION_METRIC_FNS[metric](
            cursor, model_name, variable,
            min_lat, max_lat, min_lon, max_lon,
            hour_min, hour_max, threshold_rate=threshold_rate)

    if metric != 'correlation':
        return []

    init_time = _resolve_init_time(cursor, model_name)
    if init_time is None:
        return []
    points, _n_hours = _compute_correlation_points(
        cursor, model_name, variable, init_time,
        min_lat, max_lat, min_lon, max_lon)
    return points


def _region_metric_points(cursor, model_name, variable, metrics,
                          min_lat, max_lat, min_lon, max_lon,
                          hour_min, hour_max, threshold_rate):
    """Per-cell points for each pairs-based metric, for one model.

    **Two pair sources, chosen per metric**, which is the whole point of this
    function's shape:

        `pairs`         the regridded mean/spread table, re-binned onto the
                        common verification window. Scores bias, mae, rmse,
                        csi, pod, far and fss.
        `spread_pairs`  the regridded MEMBER grid, where a spread always
                        exists. Scores the three in
                        `COMPARE_REGION_SPREAD_METRICS` — see that constant for
                        why they cannot use the table above.

    Both are fetched at most once per model rather than once per (model, metric)
    — nine metrics × three models would otherwise be 27 round trips — and the
    member query runs only when one of the three is actually requested, since it
    is the more expensive of the two.

    The raw pairs come back so the caller can pool over samples rather than
    average per-cell scores. Returns
    (points_by_metric, pairs, n_matched_cells, spread_pairs).
    """
    wanted = [m for m in metrics if m in COMPARE_REGION_METRIC_FNS]
    # FSS is derived from the same pairs but has no per-cell function of its own
    # (it is a property of the whole field at a lead time), so asking whether any
    # per-cell metric was requested is the wrong question: requesting `fss` alone
    # skipped the fetch entirely and reported no value, zero cells, and a warning
    # that the grids did not overlap — none of which was true.
    if not wanted and not (COMPARE_REGION_NO_CELL_VALUE & set(metrics)):
        return {}, {}, 0, {}
    pairs = _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                          min_lat, max_lat, min_lon, max_lon,
                                          hour_min, hour_max)

    spread_pairs = {}
    if COMPARE_REGION_SPREAD_METRICS & set(metrics):
        # The member grid is keyed by run, so it needs the init time the rest of
        # this request is already about. `_single_metric_points` resolves it the
        # same way for `correlation`.
        init_time = _resolve_init_time(cursor, model_name)
        if init_time is not None:
            spread_pairs = _member_pairs_by_cell(
                cursor, model_name, variable, init_time,
                min_lat, max_lat, min_lon, max_lon, hour_min, hour_max)

    out = {}
    for m in wanted:
        # An empty dict here is deliberate and is NOT the same as None: None
        # makes each metric fall back to fetching the aggregate pairs itself,
        # which is exactly the defect this routing exists to remove. No run
        # resolved means no spread samples, which is an honest empty.
        src = spread_pairs if m in COMPARE_REGION_SPREAD_METRICS else pairs
        out[m] = COMPARE_REGION_METRIC_FNS[m](
            cursor, model_name, variable,
            min_lat, max_lat, min_lon, max_lon,
            hour_min, hour_max, threshold_rate=threshold_rate, pairs=src)
    return out, pairs, len(pairs), spread_pairs






@app.route('/api/compare/region-metrics', methods=['POST'])
def compare_region_metrics():
    """Region-mean verification metrics for several models over one bbox.

    Request JSON:
        { models, variable, min_lat, max_lat, min_lon, max_lon,
          hour_min, hour_max, metrics?, threshold_mm_6h | threshold_ms }
    Response JSON:
        { models:   { AIFS: {mae: 2.1, bias: -0.3, ...}, .. },
          n_points: { AIFS: {mae: 812, ...}, .. },   # grid cells behind each value
          n_cells:  { AIFS: 812, .. },               # matched fcst↔obs cells
          metrics, threshold_info, bbox, hour_min, hour_max, warnings }

    `n_points` is per metric, because a metric can be None for its own reason (a
    spread the re-bin could not carry, say) while its neighbours are fine. It is 0
    only when nothing contributed — a populated value always has a non-zero count,
    including FSS, which has no per-cell map but is built from the matched cells.

    A model whose forecast and observation grids don't overlap yields all-None
    metrics plus an entry in `warnings`, so the UI can say so rather than draw
    an empty chart.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400

    models   = body.get('models', [])
    variable = body.get('variable', 'precipitation')
    if not isinstance(models, list) or not models:
        return jsonify({'error': 'models must be a non-empty list'}), 400
    if not all(isinstance(m, str) for m in models):
        return jsonify({'error': 'models must be a list of strings'}), 400
    if _bad_token(*models, variable):
        return jsonify({'error': 'Invalid model or variable'}), 400

    metrics = body.get('metrics') or COMPARE_REGION_METRICS
    if not isinstance(metrics, list) or not all(isinstance(m, str) for m in metrics):
        return jsonify({'error': 'metrics must be a list of strings'}), 400
    unknown = [m for m in metrics if m not in COMPARE_REGION_METRICS]
    if unknown:
        return jsonify({'error': f'Unknown metric(s): {unknown}. '
                        f'Available: {COMPARE_REGION_METRICS}'}), 400

    bbox, err = _parse_bbox(body)
    if err:
        return err
    min_lat, max_lat = bbox['min_lat'], bbox['max_lat']
    min_lon, max_lon = bbox['min_lon'], bbox['max_lon']

    try:
        hour_min = int(body.get('hour_min', 0))
        hour_max = int(body.get('hour_max', 168))
        # FSS neighbourhood width in grid cells — independent of the bbox, which
        # the caller draws.
        fss_window = max(1, min(int(body.get('fss_window', 3)), 21))
    except (TypeError, ValueError):
        return jsonify({'error': 'hour_min, hour_max and fss_window must be numeric'}), 400
    if hour_min >= hour_max:
        return jsonify({'error': 'hour_min must be less than hour_max'}), 400

    is_wind = (variable == 'wind')
    try:
        threshold_rate = _resolve_threshold_rate(body)
    except (TypeError, ValueError):
        return jsonify({'error': 'threshold must be numeric'}), 400

    need_corr = 'correlation' in metrics

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # The most expensive endpoint in the app, and the Comparison tab
        # requests it on every parameter change. Deterministic, so cacheable.
        #
        # Measured 2026-10-07, three models and all twelve metrics over a 2.5°
        # box, 0–168 h: **7.3 s cold, ~1 s cached**. It was **217 s** until the
        # member-count lookup stopped scanning `forecast_data` (§50) — so the
        # 12.4 s this comment used to quote, for three models and *two*
        # metrics, was measured before the table grew to 240M rows.
        _key = _body_cache_key('cmp-region', cursor, body, (
            'models', 'variable', 'metrics', 'min_lat', 'max_lat',
            'min_lon', 'max_lon', 'hour_min', 'hour_max', 'fss_window',
            'threshold_mm_6h', 'threshold_ms', 'init_time',
        ))
        _cached = _cache_get(_key)
        if _cached is not None:
            return jsonify(_cached)

        per_model     = {}
        per_counts    = {}
        per_cell_mean = {}
        n_cells       = {}
        warnings      = {}
        # Whether any requested metric comes from the fcst↔obs pairs at all.
        pairs_needed  = bool((set(COMPARE_REGION_METRIC_FNS) |
                             COMPARE_REGION_NO_CELL_VALUE) & set(metrics))

        for m in models:
            points_by_metric, pairs, matched, spread_pairs = _region_metric_points(
                cursor, m, variable, metrics,
                min_lat, max_lat, min_lon, max_lon,
                hour_min, hour_max, threshold_rate)

            # Headline values are pooled over every (cell, lead time) sample —
            # the same estimator point mode uses. The per-cell mean is what the
            # MAP of this metric averages to, so it is reported alongside.
            #
            # `spread_pairs` has to reach here as well as the per-cell functions:
            # the headline and the map are two separate consumers of the pairs,
            # and fixing only the per-cell path would have left the number the
            # user actually reads still empty for an hourly model.
            values = _region_pooled_metrics(pairs, metrics, threshold_rate,
                                            _ensemble_size(cursor, m, variable,
                                                           _resolve_init_time(cursor, m)),
                                            fss_window=fss_window,
                                            spread_pairs=spread_pairs)
            cell_means = {k: _region_mean(v) for k, v in points_by_metric.items()}
            counts     = {k: len(v) for k, v in points_by_metric.items()}
            # Metrics with no pooled form (correlation) fall back to the cell mean.
            for k, v in cell_means.items():
                values.setdefault(k, v)

            # A metric with no per-cell value (FSS) has no points list, so
            # `len(points)` was 0 — reported next to a perfectly good score, which
            # reads as "no data" to any caller using the count to decide whether
            # the value is populated. FSS is a property of the whole field at each
            # lead time, so the cells behind it are the matched cells.
            for k in COMPARE_REGION_NO_CELL_VALUE & set(metrics):
                counts[k] = matched if values.get(k) is not None else 0

            if need_corr:
                corr_points = _single_metric_points(
                    cursor, m, variable, 'correlation',
                    min_lat, max_lat, min_lon, max_lon,
                    hour_min, hour_max, threshold_rate)
                # Correlation is a per-cell correlation across lead times, so
                # the cell mean IS its region value — there's no pooled form.
                values['correlation']     = _region_mean(corr_points)
                cell_means['correlation'] = values['correlation']
                counts['correlation']     = len(corr_points)

            # Distinguish "grids don't line up" from "genuinely no data": the
            # fcst↔obs join is rounded-key equality over a fully observed window,
            # so a misaligned grid — or a lead time running past the end of the
            # observation record — gives zero matches and every metric silently
            # comes back None.
            #
            # Only when the pairs were actually needed, though. `correlation` comes
            # from the member path and needs none, so a request for it alone used to
            # be told the grids did not overlap while returning a perfectly good
            # correlation.
            if matched == 0 and pairs_needed:
                warnings[m] = ('No forecast/observation grid cells matched in this '
                               'region and lead-time range. Either the grids do not '
                               'overlap, or these lead times fall past the end of the '
                               'observation record — verification needs an observation '
                               'covering the whole period each forecast record spans.')

            per_model[m]  = {k: values.get(k) for k in metrics}
            per_counts[m] = {k: counts.get(k, 0) for k in metrics}
            per_cell_mean[m] = {k: cell_means.get(k) for k in metrics}
            n_cells[m]    = matched

        threshold_info = ({'threshold_ms': threshold_rate, 'unit': 'm/s'} if is_wind
                          else {'threshold_mm_6h': round(threshold_rate * 6, 2),
                                'unit': 'mm/6h'})
        threshold_info['threshold_rate'] = round(threshold_rate, 4)

        log.info(f"✅ compare/region-metrics: {len(models)} models × {len(metrics)} metrics, "
              f"bbox [{min_lat},{max_lat}]×[{min_lon},{max_lon}] "
              f"{hour_min}-{hour_max}h, cells={n_cells}")

        result = {
            'models':         per_model,
            # Same metrics averaged per cell — what the corresponding MAP shows.
            'cell_means':     per_cell_mean,
            'n_points':       per_counts,
            'n_cells':        n_cells,
            'metrics':        metrics,
            'fss_window':     fss_window,
            'threshold_info': threshold_info,
            'bbox':           [min_lat, max_lat, min_lon, max_lon],
            'hour_min':       hour_min,
            'hour_max':       hour_max,
            'warnings':       warnings,
        }
        _cache_set(_key, result, timeout=METRIC_CACHE_TTL)
        return jsonify(result)

    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        log.exception(f"❌ Error in compare/region-metrics: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        cursor.close()
        return_db_connection(conn)




@app.route('/api/compare/spatial-diff', methods=['POST'])
def compare_spatial_diff():
    """Per-cell difference (model A − model B) of one metric, rendered as a PNG.

    Request JSON:
        { model_a, model_b, metric, variable, min_lat, max_lat, min_lon, max_lon,
          hour_min, hour_max, threshold_mm_6h | threshold_ms }
    Response JSON:
        { image, n_common, n_a, n_b, max_abs_diff, mean_diff }
        or { error, n_a, n_b, n_common } when the two grids share no cells.

    The colour scale is symmetric about 0 and derived from the largest absolute
    difference, so red/blue always mean "A worse/better" for the metric's own
    sense of direction — read alongside the per-model maps above it.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400

    model_a  = body.get('model_a')
    model_b  = body.get('model_b')
    metric   = body.get('metric', 'mae')
    variable = body.get('variable', 'precipitation')
    if not isinstance(model_a, str) or not isinstance(model_b, str):
        return jsonify({'error': 'model_a and model_b are required'}), 400
    if model_a == model_b:
        return jsonify({'error': 'model_a and model_b must differ'}), 400
    if _bad_token(model_a, model_b, variable):
        return jsonify({'error': 'Invalid model or variable'}), 400
    if metric not in COMPARE_REGION_METRICS:
        return jsonify({'error': f'Unknown metric: {metric}. '
                        f'Available: {COMPARE_REGION_METRICS}'}), 400

    bbox, err = _parse_bbox(body)
    if err:
        return err
    min_lat, max_lat = bbox['min_lat'], bbox['max_lat']
    min_lon, max_lon = bbox['min_lon'], bbox['max_lon']

    try:
        hour_min = int(body.get('hour_min', 0))
        hour_max = int(body.get('hour_max', 168))
    except (TypeError, ValueError):
        return jsonify({'error': 'hour_min and hour_max must be numeric'}), 400
    if hour_min >= hour_max:
        return jsonify({'error': 'hour_min must be less than hour_max'}), 400

    is_wind = (variable == 'wind')
    try:
        threshold_rate = _resolve_threshold_rate(body)
    except (TypeError, ValueError):
        return jsonify({'error': 'threshold must be numeric'}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        pts_a = _single_metric_points(cursor, model_a, variable, metric,
                                      min_lat, max_lat, min_lon, max_lon,
                                      hour_min, hour_max, threshold_rate)
        pts_b = _single_metric_points(cursor, model_b, variable, metric,
                                      min_lat, max_lat, min_lon, max_lon,
                                      hour_min, hour_max, threshold_rate)
    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        log.exception(f"❌ Error in compare/spatial-diff: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        # Release before rendering: Cartopy work is CPU-bound and would
        # otherwise hold a pooled connection for the whole render.
        cursor.close()
        return_db_connection(conn)

    diff_points, n_a, n_b = _spatial_diff_points(pts_a, pts_b)

    if not diff_points:
        log.warning(f"⚠️  compare/spatial-diff: no shared cells for {model_a} vs {model_b} "
              f"({n_a} vs {n_b} cells)")
        return jsonify({
            'error': (f'{model_a} and {model_b} share no grid cells for this metric, '
                      f'region and lead-time range ({n_a} vs {n_b} '
                      f'cells — no overlap or grid misalignment).'),
            'n_a': n_a, 'n_b': n_b, 'n_common': 0,
        })

    diffs        = [p['value'] for p in diff_points]
    max_abs_diff = max(abs(d) for d in diffs)
    mean_diff    = float(np.mean(diffs))

    try:
        # Symmetric norm about 0 so equal-and-opposite differences read equally
        # strongly. A perfectly identical pair would collapse the scale, so
        # keep a small floor.
        vmax = max(max_abs_diff, 1e-6)
        norm = mcolors.Normalize(vmin=-vmax, vmax=vmax)
        ticks = [-vmax, -vmax / 2, 0.0, vmax / 2, vmax]

        metric_label = _metric_cbar_label(metric, variable)
        var_label    = VAR_LABELS.get(variable, variable)
        thr_info = ''
        if metric in CATEGORICAL_METRICS:
            thr_info = (f'  ·  thr >{round(threshold_rate, 3)} m/s' if is_wind
                        else f'  ·  thr >{round(threshold_rate * 6, 2)} mm/6h')
        title = (f"{model_a} − {model_b}  ·  {var_label}  ·  {metric_label}\n"
                 f"{len(diff_points)} shared grid cells  ·  +{hour_min}–{hour_max}h"
                 f"{thr_info}  ·  mean {mean_diff:+.4f}")

        img_b64 = _render_metric_map_png(
            diff_points,
            plt.cm.RdBu_r,
            norm,
            f'{metric} difference  ({model_a} − {model_b})',
            title,
            cbar_ticks=ticks,
            cbar_ticklabels=[f'{v:+.3g}' if v else '0' for v in ticks],
            cbar_fontsize=8.5,
        )
    except RunSelectionError:
        # A 400 about the request, not a server fault: let the
        # errorhandler answer instead of reporting 500.
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        log.exception(f"❌ Error rendering compare/spatial-diff: {e}")
        return jsonify({'error': 'Internal server error'}), 500

    log.info(f"✅ compare/spatial-diff: {metric} {model_a}−{model_b}, "
          f"{len(diff_points)} shared cells (of {n_a}/{n_b}), "
          f"mean {mean_diff:+.4f}")
    return jsonify({
        'image':        img_b64,
        'n_common':     len(diff_points),
        'n_a':          n_a,
        'n_b':          n_b,
        'max_abs_diff': round(max_abs_diff, 6),
        'mean_diff':    round(mean_diff, 6),
    })


if __name__ == '__main__':
    print("🚀 Flask API Starting...")
    print("=" * 60)
    print("📍 http://localhost:5000")
    print("=" * 60)
    print("Available endpoints:")
    print("  • GET  /api/forecast-data?model=AIFS&variable=precipitation&hour=6&member=mean")
    print("  • GET  /api/wind-data?model=GEFS&hour=12&member=0")
    print("  • GET  /api/point-timeseries?model=AIFS&variable=precipitation&lat=35.0&lon=-75.0")
    print("  • GET  /api/spread-skill?model=AIFS&variable=precipitation&lat=35.0&lon=-75.0")
    print("  • POST /api/spatial-metric-plot  {metric, model, variable, hour, n_hours, points}")
    print("  • GET  /api/models")
    print("  • GET  /api/variables")
    print("  • GET  /api/health")
    print("  • POST /api/compare/timeseries  {models, lat, lon, hour_min, hour_max, variable}")
    print("  • POST /api/compare/skill       {models, lat, lon, hour_min, hour_max, variable}")
    print("  • POST /api/compare/spatial-agreement  {models, min_lat, max_lat, min_lon, max_lon, hour, variable}")
    print("  • POST /api/categorical-metrics        {model, variable, lat, lon, threshold_mm_6h, hour_min, hour_max}")
    print("  • POST /api/region-categorical-metrics {model, variable, min_lat, max_lat, min_lon, max_lon, threshold_mm_6h, hour_min, hour_max}")
    print("  • POST /api/compare/region-metrics     {models, variable, min_lat, max_lat, min_lon, max_lon, hour_min, hour_max, metrics}")
    print("  • POST /api/compare/spatial-diff       {model_a, model_b, metric, variable, min_lat, max_lat, min_lon, max_lon, hour_min, hour_max}")
    print("=" * 60)
    print("✅ Optimized with connection pooling")

    # Say it at startup, loudly, when the pool cannot fit under the server's
    # max_connections. This is a warning rather than a refusal on purpose: the
    # worker count is inferred from the environment, so refusing would take an
    # otherwise-working deployment down over a variable that may simply be
    # unset. /api/health carries the same figures for checking afterwards.
    try:
        _hc_conn = get_db_connection()
        try:
            with _hc_conn.cursor() as _hc_cur:
                _pool = _check_pool_headroom(_hc_cur)
                _store = _check_storage_headroom(_hc_cur)
        finally:
            return_db_connection(_hc_conn)

        # Phase 5's threshold, announced where it can be acted on. Printed in
        # both states, because "how many more runs fit" is the number someone
        # wants *before* starting a load, not only once it is too late.
        if _store['safe']:
            print(f"💾 Storage: {_store['database_gb']} GB over "
                  f"{_store['runs']} run(s), {_store['headroom_gb']} GB until the "
                  f"{_store['revisit_at_gb']:.0f} GB retention review"
                  + (f" (~{_store['runs_until_revisit']} more run(s))"
                     if _store['runs_until_revisit'] is not None else ""))
        else:
            print("=" * 60)
            print(f"⚠️  STORAGE PAST THE RETENTION THRESHOLD — a decision is due")
            print(f"    {_store['database_gb']} GB over {_store['runs']} run(s), "
                  f"threshold {_store['revisit_at_gb']:.0f} GB")
            print(f"    mean {_store['mean_gb_per_run']} GB per run")
            print("    Nothing is broken. Choose an archive tier before the next")
            print("    ingest — DATA_EXPANSION_DESIGN.md phase 5 has the options.")
            print("=" * 60)

        if _pool['safe']:
            print(f"✅ Pool headroom: {_pool['workers']} worker(s) × "
                  f"{_pool['pool_max_per_worker']} = {_pool['peak_connections']} "
                  f"of {_pool['usable_connections']} usable connections")
        else:
            print("=" * 60)
            print("⚠️  CONNECTION POOL OVER CAPACITY — requests will fail under load")
            print(f"    {_pool['workers']} worker(s) × {_pool['pool_max_per_worker']} "
                  f"= {_pool['peak_connections']} connections at peak")
            print(f"    server allows {_pool['usable_connections']} usable "
                  f"(max_connections {_pool['max_connections']})")
            print("    Lower DB_POOL_MAX in Data/.env, or raise max_connections.")
            print("    See REVIEW_DEPLOY_PREREQS.md §2.")
            print("=" * 60)
    except Exception as _e:
        # Never let the check itself stop the server starting.
        print(f"⚠️  Could not verify pool headroom: {_e}")
    print("🌬️  Wind: speed = √(u² + v²), direction = atan2(u,v)")
    print("📊 Cone of Uncertainty: mean, std, min, max, p10/p25/p75/p90 per hour")
    print("📊 Multi-model comparison: timeseries, skill scores, spatial agreement")
    print("=" * 60)

    flask_port  = int(os.environ.get('FLASK_PORT',  5000))
    # Default OFF: the Werkzeug debugger allows remote code execution and must never
    # be on for a deployed/beta instance. Local dev opts in via FLASK_DEBUG=true in .env.
    flask_debug = os.environ.get('FLASK_DEBUG', 'false').lower() in ('1', 'true', 'yes')
    app.run(debug=flask_debug, host='0.0.0.0', port=flask_port)