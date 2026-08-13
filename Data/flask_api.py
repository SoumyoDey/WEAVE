from flask import Flask, jsonify, request, Response, g
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import math
import io
import base64
import os
import json
import hashlib
import time
from datetime import timedelta
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


# ── Metric computations ───────────────────────────────────────────────────────
# The science lives in metrics.py as pure functions (no Flask, no DB), so it can
# be tested without a database and reasoned about on its own. Imported by name
# rather than with a star so the dependency is explicit and greppable.
from metrics import (                                    # noqa: E402
    MODEL_ACCUM_HOURS, CUMULATIVE_PRECIP_MODELS,
    RATE_CUMULATED_PRECIP_MODELS, SSR_CAP,
    _grid_step,
    _clamp_ssr, _ssr_from_variances, _spread_inflation,
    _censor_correction, _gaussian_crps, _exceedance_probability,
    _neighbourhood_fractions, _fss_components, _fss_from_components,
    _fractions_skill_score, _fss_from_pairs,
    _precip_period_hours, _precip_lookback_hours, _increment_divisor,
    _obs_window_mean,
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
    print(f"⚠️  Rate limiting disabled: {_e}")


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
    print(f"⚠️  Plot caching disabled: {_e}")

def _cache_get(key):
    if cache is None:
        return None
    try:
        return cache.get(key)
    except Exception as _e:  # pragma: no cover
        print(f"⚠️  Cache read failed: {_e}")
        return None

def _cache_set(key, value, timeout):
    if cache is None:
        return
    try:
        cache.set(key, value, timeout=timeout)
    except Exception as _e:  # pragma: no cover
        print(f"⚠️  Cache write failed: {_e}")


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
# Min=5 pre-warms connections at startup so the first requests don't pay
# connection setup cost. Max=20 handles bursts (region analysis fires ~10
# concurrent requests).
connection_pool = psycopg2.pool.ThreadedConnectionPool(
    int(os.environ.get('DB_POOL_MIN', 5)),
    # Default 20 so the DEPLOY.md worker math holds (workers × DB_POOL_MAX must
    # stay under PostgreSQL max_connections; 4 × 20 = 80 < 100).
    int(os.environ.get('DB_POOL_MAX', 20)),
    **DB_CONFIG
)


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

























# Member counts are a COUNT(DISTINCT) over a very large table (2-6 s), but they
# are fixed for a run, so resolve once per process.
_ENSEMBLE_SIZE_CACHE = {}


def _ensemble_size(cursor, model_name):
    """Number of ensemble members in a model's latest run, or None if unknown."""
    if model_name in _ENSEMBLE_SIZE_CACHE:
        return _ENSEMBLE_SIZE_CACHE[model_name]
    n = None
    try:
        cursor.execute("""
            SELECT COUNT(DISTINCT fd.ensemble_member) AS n
            FROM forecast_data fd
            JOIN forecast_runs fr ON fr.run_id = fd.run_id
            JOIN models mo ON mo.model_id = fr.model_id AND mo.model_name = %s
            WHERE fd.ensemble_member IS NOT NULL
              AND fd.forecast_hour = (SELECT MIN(forecast_hour)
                                      FROM forecast_data WHERE run_id = fr.run_id)
        """, (model_name,))
        row = cursor.fetchone()
        if row:
            n = int(row['n'] if isinstance(row, dict) else row[0])
    except Exception as e:
        print(f"⚠️  ensemble size lookup failed for {model_name}: {e}")
    n = n if (n and n > 1) else None
    _ENSEMBLE_SIZE_CACHE[model_name] = n
    return n


def get_model_run_id(cursor, model_name):
    # Cache per-request in Flask g so repeated calls within the same HTTP
    # request (e.g. multiple dispatch functions) hit the DB only once.
    cache = g.get('run_id_cache')
    if cache is None:
        g.run_id_cache = {}
        cache = g.run_id_cache
    if model_name in cache:
        return cache[model_name]
    cursor.execute("""
        SELECT fr.run_id
        FROM forecast_runs fr
        JOIN models m ON fr.model_id = m.model_id
        WHERE m.model_name = %s
        ORDER BY fr.initialization_time DESC
        LIMIT 1
    """, (model_name,))
    result = cursor.fetchone()
    run_id = result['run_id'] if result else None
    cache[model_name] = run_id
    return run_id


def _latest_init_time(cursor, model_name):
    """Initialization time of the most recent run for a model (or None).

    Resolving this once per model lets forecast queries drop the per-row
    correlated subquery that re-derived the latest run for every returned row.
    Cached per-request in Flask g.
    """
    cache = g.get('init_time_cache')
    if cache is None:
        g.init_time_cache = {}
        cache = g.init_time_cache
    if model_name in cache:
        return cache[model_name]
    cursor.execute("""
        SELECT fr.initialization_time
        FROM forecast_runs fr
        JOIN models m ON fr.model_id = m.model_id
        WHERE m.model_name = %s
        ORDER BY fr.initialization_time DESC
        LIMIT 1
    """, (model_name,))
    row = cursor.fetchone()
    init_time = row['initialization_time'] if row else None
    cache[model_name] = init_time
    return init_time


def _fcst_speed_sql(is_wind, base_cols):
    """SQL fragments to select forecast mean/std from regridded_forecast (aliased
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
        from_clause = ("regridded_forecast u "
                       "JOIN regridded_forecast v "
                       "ON v.model_name = u.model_name AND v.forecast_hour = u.forecast_hour "
                       "AND v.latitude = u.latitude AND v.longitude = u.longitude "
                       "AND v.variable_name = 'wind_v_10m'")
        return (select_cols, from_clause, "u.variable_name = 'wind_u_10m'",
                "AND v.mean_value IS NOT NULL AND v.std_dev IS NOT NULL")
    return (f"{base_cols}, u.mean_value, u.std_dev",
            "regridded_forecast u", "u.variable_name = %s", "")


def _ensemble_speed_rows(cursor, run_id, variable_id, hour,
                         min_lat, max_lat, min_lon, max_lon, is_wind):
    """ensemble_statistics forecast rows (latitude, longitude, mean_value,
    std_dev) at one hour. For wind, forecast SPEED is derived from the u/v
    component rows (variable_id is the u-component id; v = wind_v_10m) — the same
    |mean vector| approximation used on the regridded tables — so it can be
    compared against the observed scalar wind_speed rather than the raw
    u-component (the old bug)."""
    if is_wind:
        cursor.execute("""
            SELECT u.latitude, u.longitude,
                   SQRT(POWER(u.mean_value, 2) + POWER(v.mean_value, 2)) AS mean_value,
                   SQRT(POWER(u.std_dev, 2)    + POWER(v.std_dev, 2))    AS std_dev
            FROM ensemble_statistics u
            JOIN ensemble_statistics v
              ON v.run_id = u.run_id AND v.forecast_hour = u.forecast_hour
             AND v.latitude = u.latitude AND v.longitude = u.longitude
             AND v.variable_id = (SELECT variable_id FROM variables WHERE variable_name = 'wind_v_10m')
            WHERE u.run_id = %s AND u.variable_id = %s AND u.forecast_hour = %s
              AND u.latitude BETWEEN %s AND %s AND u.longitude BETWEEN %s AND %s
              AND u.std_dev IS NOT NULL AND v.std_dev IS NOT NULL
        """, (run_id, variable_id, hour, min_lat, max_lat, min_lon, max_lon))
    else:
        cursor.execute("""
            SELECT latitude, longitude, mean_value, std_dev
            FROM ensemble_statistics
            WHERE run_id = %s AND variable_id = %s AND forecast_hour = %s
              AND latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s
              AND std_dev IS NOT NULL
        """, (run_id, variable_id, hour, min_lat, max_lat, min_lon, max_lon))
    return cursor.fetchall()


def _compute_ssr_points(cursor, run_id, variable_id, init_time, hour,
                        min_lat, max_lat, min_lon, max_lon, obs_col,
                        model_name=None):
    """SSR at a single forecast hour from ensemble_statistics + observation_data.

    Forecast values are converted to mm/h with the model's own record semantics
    (_precip_rate_series) rather than a single divisor — AIFS stores a running
    total since init, GEFS alternates 3 h and 6 h buckets. Wind is already a
    speed via _ensemble_speed_rows and passes through unchanged.
    """
    is_wind   = (obs_col == 'wind_speed')
    lookback  = 0 if is_wind else _precip_lookback_hours(model_name)
    n_members = _ensemble_size(cursor, model_name) if model_name else None

    raw_by_cell = {}
    for h in ({hour, hour - lookback} if lookback else {hour}):
        if h < 0:
            continue
        for row in _ensemble_speed_rows(cursor, run_id, variable_id, h,
                                        min_lat, max_lat, min_lon, max_lon, is_wind):
            if row['mean_value'] is None or row['std_dev'] is None:
                continue
            key = (float(row['latitude']), float(row['longitude']))
            raw_by_cell.setdefault(key, {})[h] = (float(row['mean_value']),
                                                  float(row['std_dev']))
    ens_rows = [
        {'latitude': lat, 'longitude': lon, 'rate': rates[hour]}
        for (lat, lon), series in raw_by_cell.items()
        for rates in [_precip_rate_series(model_name, series, is_wind)]
        if hour in rates
    ]

    valid_time = init_time + timedelta(hours=hour)
    cursor.execute(
        "SELECT latitude, longitude, " + obs_col + " AS obs_val"
        " FROM observation_data"
        " WHERE obs_time = %s AND latitude BETWEEN %s AND %s"
        "   AND longitude BETWEEN %s AND %s AND " + obs_col + " IS NOT NULL",
        (valid_time, min_lat, max_lat, min_lon, max_lon)
    )
    obs_lookup = {
        (round(float(r['latitude'])  * 4) / 4,
         round(float(r['longitude']) * 4) / 4): float(r['obs_val'])
        for r in cursor.fetchall()
    }
    points = []
    matched = 0
    for row in ens_rows:
        lat  = float(row['latitude'])
        lon  = float(row['longitude'])
        mean, std, _period = row['rate']
        if std is None:
            continue                        # spread not recoverable for this record
        obs = obs_lookup.get((round(lat * 4) / 4, round(lon * 4) / 4))
        if obs is None:
            continue
        matched += 1
        err_sq = (mean - obs) ** 2
        ssr    = _ssr_from_variances(std ** 2, err_sq, n_members)
        if ssr is not None:
            points.append({'lat': lat, 'lon': lon, 'value': ssr})
    # Diagnose silent grid misalignment (quarter-degree key match to sparse obs).
    if ens_rows and matched == 0:
        print(f"⚠️  SSR ens↔obs join matched 0 of {len(ens_rows)} grid points "
              f"at +{hour}h — likely grid misalignment or no obs "
              f"({len(obs_lookup)} obs keys, snapped to 0.25°).")
    return points


def _compute_correlation_points(cursor, run_id, variable_id, init_time,
                                 min_lat, max_lat, min_lon, max_lon, obs_col,
                                 model_name=None):
    """Spread-skill correlation across verified hours from ensemble_statistics +
    observation_data.

    Forecast values are converted to mm/h with the model's own record semantics
    (_precip_rate_series): AIFS is differenced against the previous record,
    GEFS divided by its own bucket length. Records whose spread isn't
    recoverable are skipped, since this metric is entirely about spread.
    """
    candidate_hours = [0, 6, 12, 18, 24, 48, 72, 96, 120, 144, 168]
    is_wind = (obs_col == 'wind_speed')

    # Cumulative models need the record one period earlier to difference against.
    lookback = 0 if is_wind else _precip_lookback_hours(model_name)
    fetch_hours = sorted({h for hour in candidate_hours
                          for h in (hour, hour - lookback) if h >= 0})

    # Raw per-cell series across every hour we need (candidates + lookback).
    raw_by_cell = {}
    for hour in fetch_hours:
        for row in _ensemble_speed_rows(cursor, run_id, variable_id, hour,
                                        min_lat, max_lat, min_lon, max_lon, is_wind):
            if row['mean_value'] is None or row['std_dev'] is None:
                continue
            key = (round(float(row['latitude']) * 4) / 4,
                   round(float(row['longitude']) * 4) / 4)
            entry = raw_by_cell.setdefault(key, {'lat': float(row['latitude']),
                                                 'lon': float(row['longitude']),
                                                 'series': {}})
            entry['series'][hour] = (float(row['mean_value']), float(row['std_dev']))

    if not raw_by_cell:
        return [], 0

    rates_by_cell = {
        key: _precip_rate_series(model_name, entry['series'], is_wind)
        for key, entry in raw_by_cell.items()
    }

    hour_data = {}
    for hour in candidate_hours:
        valid_time = init_time + timedelta(hours=hour)
        cursor.execute(
            "SELECT latitude, longitude, " + obs_col + " AS obs_val"
            " FROM observation_data"
            " WHERE obs_time = %s AND latitude BETWEEN %s AND %s"
            "   AND longitude BETWEEN %s AND %s AND " + obs_col + " IS NOT NULL",
            (valid_time, min_lat, max_lat, min_lon, max_lon)
        )
        obs_rows = cursor.fetchall()
        if not obs_rows:
            continue
        obs_lookup = {
            (round(float(r['latitude'])  * 4) / 4,
             round(float(r['longitude']) * 4) / 4): float(r['obs_val'])
            for r in obs_rows
        }
        point_pairs = {}
        for key, rates in rates_by_cell.items():
            rec = rates.get(hour)
            obs = obs_lookup.get(key)
            if rec is None or obs is None:
                continue
            mean_rate, std_rate, _period = rec
            if std_rate is None:
                continue                  # no spread → nothing to correlate
            point_pairs[key] = {'lat': raw_by_cell[key]['lat'],
                                'lon': raw_by_cell[key]['lon'],
                                'spread': std_rate,
                                'abs_error': abs(mean_rate - obs)}
        if point_pairs:
            hour_data[hour] = point_pairs

    all_keys = {}
    for _hour, pairs in hour_data.items():
        for key, vals in pairs.items():
            if key not in all_keys:
                all_keys[key] = {'lat': vals['lat'], 'lon': vals['lon'], 'hours': []}
            all_keys[key]['hours'].append((vals['spread'], vals['abs_error']))

    points = []
    for _key, info in all_keys.items():
        pairs = info['hours']
        if len(pairs) < 2:
            continue
        spreads = [p[0] for p in pairs]
        errors  = [p[1] for p in pairs]
        n   = len(spreads)
        ms  = sum(spreads) / n
        me  = sum(errors)  / n
        num = sum((spreads[i] - ms) * (errors[i] - me) for i in range(n))
        den = math.sqrt(
            sum((s - ms) ** 2 for s in spreads) *
            sum((e - me) ** 2 for e in errors)
        )
        corr = round(num / den, 4) if den > 1e-10 else None
        if corr is not None:
            points.append({'lat': info['lat'], 'lon': info['lon'], 'value': corr})
    return points, len(hour_data)


def _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                   min_lat, max_lat, min_lon, max_lon,
                                   hour_min=0, hour_max=168):
    """
    Fetches per-(lat,lon) lists of (hour, mean_rate, std_rate, obs_rate) tuples
    from regridded_forecast + regridded_observation tables.

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

    # Pre-fetch initialization_time for the latest run once — avoids the
    # correlated subquery that was re-evaluated for every row in regridded_forecast.
    cursor.execute("""
        SELECT fr.initialization_time
        FROM forecast_runs fr
        JOIN models m ON fr.model_id = m.model_id
        WHERE m.model_name = %s
        ORDER BY fr.initialization_time DESC LIMIT 1
    """, (model_name,))
    run_row = cursor.fetchone()
    if not run_row:
        return {}
    init_time_val = run_row['initialization_time']

    # Forecast mean/std (wind → speed via u/v self-join; see _fcst_speed_sql).
    _sel, _frm, _varw, _vnn = _fcst_speed_sql(is_wind, "u.latitude, u.longitude, u.forecast_hour")
    cursor.execute(f"""
        SELECT {_sel}
        FROM {_frm}
        WHERE u.model_name = %s AND {_varw}
          AND u.forecast_hour BETWEEN %s AND %s
          AND u.latitude  BETWEEN %s AND %s
          AND u.longitude BETWEEN %s AND %s
          AND u.mean_value IS NOT NULL AND u.std_dev IS NOT NULL {_vnn}
        ORDER BY u.latitude, u.longitude, u.forecast_hour
    """, (model_name, *(() if is_wind else (fcst_var,)),
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
        cell: _precip_rate_series(model_name, series, is_wind)
        for cell, series in raw_by_cell.items()
    }

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
        print(f"⚠️  fcst↔obs join matched 0 of {candidate_rows} forecast records "
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
    points = _compute_ssr_points(cursor, run_id, variable_id, init_time, hour,
                                  min_lat, max_lat, min_lon, max_lon, obs_col,
                                  model_name=args.get('model', 'AIFS'))
    return points, {'hour': hour}


def _dispatch_correlation(cursor, run_id, variable_id, init_time, args,
                           min_lat, max_lat, min_lon, max_lon, obs_col):
    points, n_hours = _compute_correlation_points(
        cursor, run_id, variable_id, init_time,
        min_lat, max_lat, min_lon, max_lon, obs_col,
        model_name=args.get('model', 'AIFS'),
    )
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
    return _compute_crps_points_rf(
        cursor, args.get('model', 'AIFS'), args.get('variable', 'precipitation'),
        min_lat, max_lat, min_lon, max_lon,
        int(args.get('hour_min', 0)), int(args.get('hour_max', 168)),
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
    return _compute_brier_points_rf(
        cursor, args.get('model', 'AIFS'), args.get('variable', 'precipitation'),
        min_lat, max_lat, min_lon, max_lon,
        int(args.get('hour_min', 0)), int(args.get('hour_max', 168)),
        threshold_rate=thr,
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
    SSR = mean(σ²) / mean(ε²) across all matched lead times per grid point.
    Requires ≥2 matched pairs to be meaningful.
    """
    if pairs is None:
        pairs = _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                              min_lat, max_lat, min_lon, max_lon,
                                              hour_min, hour_max)
    n_members = _ensemble_size(cursor, model_name) if cursor is not None else None
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
    return _compute_ssr_agg_points_rf(
        cursor, args.get('model', 'AIFS'), args.get('variable', 'precipitation'),
        min_lat, max_lat, min_lon, max_lon,
        int(args.get('hour_min', 0)), int(args.get('hour_max', 168)),
    ), {}


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

        if member == 'mean':
            cursor.execute("""
                SELECT latitude as lat, longitude as lon, mean_value as value
                FROM ensemble_statistics es
                WHERE es.run_id = %s
                  AND es.variable_id = (SELECT variable_id FROM variables WHERE variable_name = %s)
                  AND es.forecast_hour = %s
            """, (run_id, variable_name, forecast_hour))

        elif member == 'std':
            cursor.execute("""
                SELECT latitude as lat, longitude as lon, std_dev as value
                FROM ensemble_statistics es
                WHERE es.run_id = %s
                  AND es.variable_id = (SELECT variable_id FROM variables WHERE variable_name = %s)
                  AND es.forecast_hour = %s
                  AND std_dev IS NOT NULL
            """, (run_id, variable_name, forecast_hour))

        else:
            member_num = int(member)
            cursor.execute("""
                SELECT latitude as lat, longitude as lon, value
                FROM forecast_data
                WHERE run_id = %s
                  AND variable_id = (SELECT variable_id FROM variables WHERE variable_name = %s)
                  AND forecast_hour = %s
                  AND ensemble_member = %s
            """, (run_id, variable_name, forecast_hour, member_num))

        data   = cursor.fetchall()
        result = [
            {
                'lat':   float(row['lat']),
                'lon':   float(row['lon']),
                'value': float(row['value']) if row['value'] else 0
            }
            for row in data
        ]

        print(f"✅ Returned {len(result)} precipitation points for {model_name} +{forecast_hour}h")
        return jsonify(result)

    except Exception as e:
        print(f"❌ Error in forecast-data: {str(e)}")
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
            """, (run_id, forecast_hour))

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
            """, (run_id, forecast_hour))

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
            """, (run_id, forecast_hour, member_num))

        data   = cursor.fetchall()
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

        print(f"✅ Returned {len(result)} wind points for {model_name} +{forecast_hour}h ({member})")
        return jsonify(result)

    except Exception as e:
        print(f"❌ Error in wind-data: {str(e)}")
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
    try:
        lat    = float(request.args.get('lat'))
        lon    = float(request.args.get('lon'))
        radius = float(request.args.get('radius', 0.5))  # degrees search radius
    except (TypeError, ValueError):
        return jsonify({'error': 'lat and lon are required and must be numeric'}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        run_id = get_model_run_id(cursor, model_name)
        if not run_id:
            return jsonify({'error': f'No data found for model {model_name}'}), 404

        if variable == 'wind':
            # Wind speed = sqrt(u² + v²) computed per member then aggregated
            cursor.execute("""
                SELECT
                    u.forecast_hour,
                    AVG(SQRT(POWER(u.value, 2) + POWER(v.value, 2)))            AS mean_val,
                    STDDEV(SQRT(POWER(u.value, 2) + POWER(v.value, 2)))         AS std_val,
                    MIN(SQRT(POWER(u.value, 2) + POWER(v.value, 2)))            AS min_val,
                    MAX(SQRT(POWER(u.value, 2) + POWER(v.value, 2)))            AS max_val,
                    PERCENTILE_CONT(0.10) WITHIN GROUP (
                        ORDER BY SQRT(POWER(u.value, 2) + POWER(v.value, 2))
                    ) AS p10,
                    PERCENTILE_CONT(0.25) WITHIN GROUP (
                        ORDER BY SQRT(POWER(u.value, 2) + POWER(v.value, 2))
                    ) AS p25,
                    PERCENTILE_CONT(0.75) WITHIN GROUP (
                        ORDER BY SQRT(POWER(u.value, 2) + POWER(v.value, 2))
                    ) AS p75,
                    PERCENTILE_CONT(0.90) WITHIN GROUP (
                        ORDER BY SQRT(POWER(u.value, 2) + POWER(v.value, 2))
                    ) AS p90
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
                  AND ABS(u.latitude  - %s) <= %s
                  AND ABS(u.longitude - %s) <= %s
                GROUP BY u.forecast_hour
                ORDER BY u.forecast_hour
            """, (run_id, lat, radius, lon, radius))

        else:
            # Precipitation — pull raw members so the distribution can be built
            # AFTER de-accumulation. Aggregating in SQL first would describe the
            # running total, not the amount falling in each period, and the
            # spread of a cumulative field is not the spread of its increments.
            cursor.execute("""
                SELECT fd.forecast_hour, fd.ensemble_member,
                       fd.latitude, fd.longitude, fd.value
                FROM forecast_data fd
                WHERE fd.run_id = %s
                  AND fd.variable_id = (SELECT variable_id FROM variables WHERE variable_name = %s)
                  AND ABS(fd.latitude  - %s) <= %s
                  AND ABS(fd.longitude - %s) <= %s
                  AND fd.ensemble_member IS NOT NULL
                ORDER BY fd.forecast_hour, fd.ensemble_member
            """, (run_id, variable, lat, radius, lon, radius))

        rows = cursor.fetchall()
        result = []

        if variable != 'precipitation':
            # Instantaneous — the SQL aggregate is already the answer.
            for row in rows:
                result.append({
                    'hour': row['forecast_hour'],
                    'mean': round(float(row['mean_val'] or 0), 4),
                    'std':  round(float(row['std_val']  or 0), 4),
                    'min':  round(float(row['min_val']  or 0), 4),
                    'max':  round(float(row['max_val']  or 0), 4),
                    'p10':  round(float(row['p10'] or 0), 4),
                    'p25':  round(float(row['p25'] or 0), 4),
                    'p75':  round(float(row['p75'] or 0), 4),
                    'p90':  round(float(row['p90'] or 0), 4),
                })
        else:
            # Build the distribution from members de-accumulated individually,
            # which is exact: the spread of the differenced members IS the
            # spread of the increment. Use the cell nearest the clicked point so
            # spatial variance doesn't leak into the ensemble spread.
            from collections import defaultdict
            cells = {(float(r['latitude']), float(r['longitude'])) for r in rows}
            if cells:
                cell = min(cells, key=lambda c: (c[0] - lat) ** 2 + (c[1] - lon) ** 2)
                by_member = defaultdict(dict)
                for r in rows:
                    if (float(r['latitude']), float(r['longitude'])) == cell:
                        by_member[r['ensemble_member']][r['forecast_hour']] = float(r['value'])

                rates_by_hour = defaultdict(list)
                for series in by_member.values():
                    for hour, (rate, _p) in _precip_member_rate_series(model_name, series).items():
                        rates_by_hour[hour].append(rate)

                for hour in sorted(rates_by_hour):
                    vals = sorted(rates_by_hour[hour])
                    n    = len(vals)
                    mean = sum(vals) / n
                    std  = math.sqrt(sum((v - mean) ** 2 for v in vals) / n)
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
                    })

        print(f"✅ Timeseries: {len(result)} hours for {model_name} at ({lat}, {lon}) "
              f"[{variable}]")
        return jsonify(result)

    except Exception as e:
        print(f"❌ Error in point-timeseries: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        cursor.close()
        return_db_connection(conn)
# ─────────────────────────────────────────────────────────────────────────────


@app.route('/api/spread-skill', methods=['GET'])
def get_spread_skill():
    """
    Computes Spread-Skill Ratio and Spread-Skill Correlation for a clicked grid point.
    Matches ensemble forecast members against IMERG observations at each forecast hour
    where observations exist (init_time + hour falls within observation_data range).
    SSR = spread² / error²  (1 = well-calibrated, <1 = overconfident, >1 = underconfident)
    Correlation = corr(spread_per_hour, |error|_per_hour) across available lead times.
    """
    model_name = request.args.get('model', 'AIFS')
    variable   = request.args.get('variable', 'precipitation')
    if _bad_token(model_name, variable):
        return jsonify({'error': 'Invalid model or variable'}), 400
    try:
        lat    = float(request.args.get('lat'))
        lon    = float(request.args.get('lon'))
        radius = float(request.args.get('radius', 0.5))
    except (TypeError, ValueError):
        return jsonify({'error': 'lat and lon are required and must be numeric'}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        run_id = get_model_run_id(cursor, model_name)
        if not run_id:
            return jsonify({'error': f'No data found for model {model_name}'}), 404

        cursor.execute("SELECT initialization_time FROM forecast_runs WHERE run_id = %s", (run_id,))
        init_time = cursor.fetchone()['initialization_time']

        obs_col = 'wind_speed' if variable == 'wind' else 'precipitation'

        # Find forecast hours that have a matching observation within the radius
        cursor.execute("""
            SELECT DISTINCT fd.forecast_hour
            FROM forecast_data fd
            WHERE fd.run_id = %s
              AND fd.variable_id = (SELECT variable_id FROM variables WHERE variable_name = %s)
              AND ABS(fd.latitude  - %s) <= %s
              AND ABS(fd.longitude - %s) <= %s
              AND EXISTS (
                  SELECT 1 FROM observation_data o
                  WHERE o.obs_time = %s::timestamp + (fd.forecast_hour || ' hours')::interval
                    AND ABS(o.latitude  - %s) <= %s
                    AND ABS(o.longitude - %s) <= %s
                    AND o.""" + obs_col + """ IS NOT NULL
              )
            ORDER BY fd.forecast_hour
        """, (run_id, 'wind_u_10m' if variable == 'wind' else variable,
              lat, radius, lon, radius,
              str(init_time), lat, radius, lon, radius))

        available_hours = [r['forecast_hour'] for r in cursor.fetchall()]

        if not available_hours:
            return jsonify({'hours': [], 'correlation': None, 'n_cases': 0})

        is_precip = (variable != 'wind')
        # Cumulative models need the record one period earlier to difference
        # against, and that hour need not have an observation of its own.
        lookback = _precip_lookback_hours(model_name) if is_precip else 0
        fetch_hours = sorted({h for hour in available_hours
                              for h in (hour, hour - lookback) if h >= 0})

        # Batch-fetch members for ALL hours in one query (was a per-hour query →
        # N+1). Member identity and cell are selected too: the ensemble spread is
        # the spread ACROSS MEMBERS AT ONE CELL. Pooling every cell inside the
        # radius into one list mixed spatial variance into "spread" (a 50-member
        # AIFS ensemble was reporting ~1200 "members"), which inflated SSR.
        from collections import defaultdict
        if variable == 'wind':
            cursor.execute("""
                SELECT u.forecast_hour, u.ensemble_member, u.latitude, u.longitude,
                       SQRT(POWER(u.value, 2) + POWER(v.value, 2)) AS member_val
                FROM forecast_data u
                JOIN forecast_data v
                    ON u.run_id = v.run_id AND u.forecast_hour = v.forecast_hour
                   AND u.ensemble_member = v.ensemble_member
                   AND u.latitude = v.latitude AND u.longitude = v.longitude
                WHERE u.run_id = %s AND u.forecast_hour = ANY(%s)
                  AND u.variable_id = (SELECT variable_id FROM variables WHERE variable_name = 'wind_u_10m')
                  AND v.variable_id = (SELECT variable_id FROM variables WHERE variable_name = 'wind_v_10m')
                  AND ABS(u.latitude  - %s) <= %s
                  AND ABS(u.longitude - %s) <= %s
                  AND u.ensemble_member IS NOT NULL
            """, (run_id, fetch_hours, lat, radius, lon, radius))
        else:
            cursor.execute("""
                SELECT forecast_hour, ensemble_member, latitude, longitude,
                       value AS member_val
                FROM forecast_data
                WHERE run_id = %s AND forecast_hour = ANY(%s)
                  AND variable_id = (SELECT variable_id FROM variables WHERE variable_name = %s)
                  AND ABS(latitude  - %s) <= %s
                  AND ABS(longitude - %s) <= %s
                  AND ensemble_member IS NOT NULL
                ORDER BY forecast_hour, ensemble_member
            """, (run_id, fetch_hours, variable, lat, radius, lon, radius))
        raw_rows = cursor.fetchall()

        # Pick the cell nearest the clicked point and keep only its members.
        cells = {(float(r['latitude']), float(r['longitude'])) for r in raw_rows}
        if not cells:
            return jsonify({'hours': [], 'correlation': None, 'n_cases': 0})
        cell = min(cells, key=lambda c: (c[0] - lat) ** 2 + (c[1] - lon) ** 2)

        by_member = defaultdict(dict)
        for r in raw_rows:
            if (float(r['latitude']), float(r['longitude'])) != cell:
                continue
            by_member[r['ensemble_member']][r['forecast_hour']] = float(r['member_val'])

        # De-accumulate PER MEMBER — exact for a cumulative model, so the spread
        # of the resulting members is the true spread of the increment.
        members_by_hour = defaultdict(list)
        for _member, series in by_member.items():
            for hour, (rate, _period) in _precip_member_rate_series(
                    model_name, series, is_wind=(variable == 'wind')).items():
                if hour in available_hours:
                    members_by_hour[hour].append(rate)

        # Batch-fetch matched observations for every valid time at once, then map
        # each back to its forecast hour. Centred on the chosen forecast cell, so
        # the forecast and the observation describe the same place.
        valid_time_to_hour = {init_time + timedelta(hours=h): h for h in available_hours}
        cursor.execute(
            "SELECT obs_time, AVG(" + obs_col + ") AS obs_val"
            " FROM observation_data"
            " WHERE obs_time = ANY(%s)"
            "   AND ABS(latitude  - %s) <= %s AND ABS(longitude - %s) <= %s"
            "   AND " + obs_col + " IS NOT NULL"
            " GROUP BY obs_time",
            (list(valid_time_to_hour.keys()), cell[0], radius, cell[1], radius)
        )
        obs_by_hour = {}
        for r in cursor.fetchall():
            h = valid_time_to_hour.get(r['obs_time'])
            if h is not None and r['obs_val'] is not None:
                obs_by_hour[h] = float(r['obs_val'])

        results = []
        for hour in available_hours:
            members = members_by_hour.get(hour, [])
            if not members or hour not in obs_by_hour:
                continue
            obs       = obs_by_hour[hour]
            n         = len(members)
            ens_mean  = sum(members) / n
            spread_sq = sum((x - ens_mean) ** 2 for x in members) / n   # population variance
            spread    = math.sqrt(spread_sq)
            error     = abs(ens_mean - obs)
            error_sq  = error ** 2
            ssr       = _ssr_from_variances(spread_sq, error_sq, n)

            results.append({
                'hour':      hour,
                'spread':    round(spread, 4),
                'error':     round(error, 4),
                'ssr':       ssr,
                'ens_mean':  round(ens_mean, 4),
                'obs':       round(obs, 4),
                'n_members': n,
            })

        # Spread-Skill Correlation across available lead times
        valid = [(r['spread'], r['error']) for r in results
                 if r['spread'] is not None and r['error'] is not None]
        correlation = None
        if len(valid) >= 2:
            spreads = [v[0] for v in valid]
            errors  = [v[1] for v in valid]
            n       = len(spreads)
            ms = sum(spreads) / n
            me = sum(errors)  / n
            num = sum((spreads[i] - ms) * (errors[i] - me) for i in range(n))
            den = math.sqrt(
                sum((spreads[i] - ms) ** 2 for i in range(n)) *
                sum((errors[i]  - me) ** 2 for i in range(n))
            )
            correlation = round(num / den, 4) if den > 1e-10 else None

        print(f"✅ Spread-skill: {len(results)} hours matched, corr={correlation} "
              f"for ({lat},{lon}) at cell {cell}")
        return jsonify({'hours': results, 'correlation': correlation,
                        'n_cases': len(results),
                        # The grid cell the ensemble was actually read from.
                        'cell': list(cell)})

    except Exception as e:
        print(f"❌ Error in spread-skill: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        cursor.close()
        return_db_connection(conn)


@app.route('/api/spatial-metric', methods=['GET'])
def get_spatial_metric():
    """
    Computes spatial SSR or Spread-Skill Correlation maps for a bounding box.
    Params: metric (ssr|correlation), model, variable, hour (ssr only),
            min_lat, max_lat, min_lon, max_lon
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

        cursor.execute(
            "SELECT initialization_time FROM forecast_runs WHERE run_id = %s", (run_id,)
        )
        init_time = cursor.fetchone()['initialization_time']

        cursor.execute(
            "SELECT variable_id FROM variables WHERE variable_name = %s", (var_lookup,)
        )
        var_row = cursor.fetchone()
        if not var_row:
            return jsonify({'error': f'Variable {var_lookup} not found'}), 404
        variable_id = var_row['variable_id']

        dispatch = SPATIAL_METRIC_REGISTRY[metric]
        points, extra = dispatch(
            cursor, run_id, variable_id, init_time, request.args,
            min_lat, max_lat, min_lon, max_lon, obs_col,
        )
        print(f"✅ Spatial {metric}: {len(points)} pts — {model_name} "
              f"bbox [{min_lat},{max_lat}]×[{min_lon},{max_lon}]")
        return jsonify({'metric': metric, 'points': points, **extra})

    except Exception as e:
        print(f"❌ Error in spatial-metric: {e}")
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
        'cbar_label':      'Bias (mm/h)  [+ = over-forecast]',
        'cbar_ticks':      [-2, -1, 0, 1, 2],
        'cbar_ticklabels': ['-2', '-1', '0', '+1', '+2'],
        'cbar_fontsize':   9,
    },
    'mae': {
        'cmap': plt.cm.YlOrRd,
        'norm': mcolors.Normalize(vmin=0, vmax=2),
        'cbar_label':      'MAE (mm/h)',
        'cbar_ticks':      [0, 0.5, 1.0, 1.5, 2.0],
        'cbar_ticklabels': ['0', '0.5', '1', '1.5', '2'],
        'cbar_fontsize':   9,
    },
    'rmse': {
        'cmap': plt.cm.YlOrRd,
        'norm': mcolors.Normalize(vmin=0, vmax=2),
        'cbar_label':      'RMSE (mm/h)',
        'cbar_ticks':      [0, 0.5, 1.0, 1.5, 2.0],
        'cbar_ticklabels': ['0', '0.5', '1', '1.5', '2'],
        'cbar_fontsize':   9,
    },
    'crps': {
        'cmap': plt.cm.YlOrRd,
        'norm': mcolors.Normalize(vmin=0, vmax=1),
        'cbar_label':      'CRPS (mm/h, lower=better)',
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




def _render_metric_map_png(points, cmap, norm, cbar_label, title,
                           cbar_ticks=None, cbar_ticklabels=None,
                           cbar_fontsize=9):
    """Render scattered 0.25° metric points as a Cartopy PNG, base64-encoded.

    Shared by /api/spatial-metric-plot and /api/compare/spatial-diff so both
    draw identical map furniture — only the colour mapping and title differ.
    Callers must release their DB connection first: rendering is CPU-bound and
    holding a pooled connection across it starves concurrent requests.
    """
    # ── Build 2-D grid from scattered 0.25° points ────────────────────
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
        style = PLOT_STYLE_REGISTRY[metric]

        # ── Title ─────────────────────────────────────────────────────────
        var_label    = VAR_LABELS.get(variable, variable)
        metric_label = style['cbar_label']
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
            points, style['cmap'], style['norm'], style['cbar_label'],
            f"{title_line1}\n{title_line2}",
            cbar_ticks=style['cbar_ticks'],
            cbar_ticklabels=style['cbar_ticklabels'],
            cbar_fontsize=style['cbar_fontsize'],
        )

        print(f"✅ Plot: {metric} · {model} · {var_label} · {len(points)} pts")
        result = {'image': img_b64}
        _cache_set(_cache_key, result, timeout=int(os.environ.get('PLOT_CACHE_TTL', 24 * 3600)))
        return jsonify(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Internal server error'}), 500


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


@app.route('/api/health', methods=['GET'])
def health_check():
    # Acquiring the connection is inside the try: an exhausted or unreachable
    # pool is exactly the condition a health check exists to report, so it must
    # answer "unhealthy" rather than fall through to the generic 500 handler.
    conn = cursor = None
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM forecast_data")
        count = cursor.fetchone()[0]
        return jsonify({
            "status": "healthy",
            "database": "connected",
            "total_forecast_points": count
        })
    except Exception as e:
        # Log the detail server-side but don't leak the raw exception string
        # (DB internals / connection strings) to the client.
        print(f"❌ Health check failed: {e}")
        return jsonify({"status": "unhealthy", "database": "unavailable"}), 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            return_db_connection(conn)












# ── Comparison endpoints (multi-model, regridded_forecast / regridded_observation) ──


@app.route('/api/compare/timeseries', methods=['POST'])
def compare_timeseries():
    """
    Returns ensemble mean and std per forecast hour for multiple models at a
    single lat/lon point, queried from regridded_forecast.

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
    try:
        lat      = float(body.get('lat', 35.0))
        lon      = float(body.get('lon', -75.0))
        hour_min = int(body.get('hour_min', 0))
        hour_max = int(body.get('hour_max', 168))
    except (TypeError, ValueError):
        return jsonify({'error': 'lat, lon, hour_min, hour_max must be numeric'}), 400

    # Wind → forecast SPEED via u/v self-join (see _fcst_speed_sql); precip → the
    # variable itself. (Was: raw u-component, which isn't a speed.)
    is_wind = (variable == 'wind')
    var_name = variable

    if not models:
        return jsonify({'error': 'No models specified'}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        _sel, _frm, _varw, _vnn = _fcst_speed_sql(is_wind, "u.model_name, u.forecast_hour")
        cursor.execute(f"""
            SELECT {_sel}
            FROM {_frm}
            WHERE u.model_name = ANY(%s) AND {_varw}
              AND u.forecast_hour BETWEEN %s AND %s
              AND u.latitude  BETWEEN %s AND %s
              AND u.longitude BETWEEN %s AND %s
            ORDER BY u.model_name, u.forecast_hour
        """, (
            models, *(() if is_wind else (var_name,)),
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
            rates = _precip_rate_series(m, series, is_wind)
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

        print(f"✅ compare/timeseries: {sum(len(v) for v in result.values())} pts "
              f"for models {models} at ({lat},{lon})")
        return jsonify(result)

    except Exception as e:
        print(f"❌ Error in compare/timeseries: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        cursor.close()
        return_db_connection(conn)


@app.route('/api/compare/skill', methods=['POST'])
def compare_skill():
    """
    Computes per-hour and summary skill metrics (SSR, CRPS, Bias, MAE, RMSE)
    by matching regridded_forecast values against regridded_observation at the
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
    try:
        lat      = float(body.get('lat', 35.0))
        lon      = float(body.get('lon', -75.0))
        hour_min = int(body.get('hour_min', 0))
        hour_max = int(body.get('hour_max', 168))
    except (TypeError, ValueError):
        return jsonify({'error': 'lat, lon, hour_min, hour_max must be numeric'}), 400

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
        # ------------------------------------------------------------------
        # 1. Resolve each model's nearest grid cell to the requested point
        # ------------------------------------------------------------------
        # A +/-0.26 degree box on a 0.5 degree grid catches one cell only when
        # the point is grid-aligned; near a cell corner it catches four, which
        # previously returned each lead time up to 4x and averaged the summary
        # over rows rather than lead times. Pin one cell per model instead.
        init_times = {m: _latest_init_time(cursor, m) for m in models}
        init_times = {m: t for m, t in init_times.items() if t is not None}
        if not init_times:
            return jsonify({'models': {}, 'obs_hours': [],
                            'obs_warning': 'No forecast data found for selected parameters.'})

        is_wind = (variable == 'wind')
        cell_of = {}
        for m in list(init_times):
            cursor.execute("""
                SELECT latitude, longitude
                FROM regridded_forecast
                WHERE model_name = %s AND variable_name = %s
                  AND latitude  BETWEEN %s AND %s
                  AND longitude BETWEEN %s AND %s
                ORDER BY POWER(latitude - %s, 2) + POWER(longitude - %s, 2)
                LIMIT 1
            """, (m, fcst_var, lat - 1.0, lat + 1.0, lon - 1.0, lon + 1.0, lat, lon))
            row = cursor.fetchone()
            if row:
                cell_of[m] = (float(row['latitude']), float(row['longitude']))
        if not cell_of:
            return jsonify({'models': {}, 'obs_hours': [],
                            'obs_warning': 'No forecast data found for selected parameters.'})

        # ------------------------------------------------------------------
        # 2. Per-model hour series at that cell, converted to mm/h rates
        # ------------------------------------------------------------------
        # Cumulative models need one record below hour_min to difference against.
        _sel, _frm, _varw, _vnn = _fcst_speed_sql(is_wind, "u.forecast_hour")
        rates_of, periods_used = {}, set()
        for m, (m_lat, m_lon) in cell_of.items():
            lookback = 0 if is_wind else _precip_lookback_hours(m)
            cursor.execute(f"""
                SELECT {_sel}
                FROM {_frm}
                WHERE u.model_name = %s AND {_varw}
                  AND u.forecast_hour BETWEEN %s AND %s
                  AND u.latitude = %s AND u.longitude = %s
                  AND u.mean_value IS NOT NULL
                  AND u.std_dev    IS NOT NULL {_vnn}
                ORDER BY u.forecast_hour
            """, (m, *(() if is_wind else (fcst_var,)),
                  max(0, hour_min - lookback), hour_max, m_lat, m_lon))
            series = {r['forecast_hour']: (float(r['mean_value']), float(r['std_dev']))
                      for r in cursor.fetchall()}
            if not series:
                continue
            rates = {h: v for h, v in _precip_rate_series(m, series, is_wind).items()
                     if hour_min <= h <= hour_max}
            if rates:
                rates_of[m] = rates
                periods_used.update(p for _, _, p in rates.values())

        if not rates_of:
            return jsonify({'models': {}, 'obs_hours': [],
                            'obs_warning': 'No forecast data found for selected parameters.'})

        # Member counts for the finite-ensemble spread correction (cached).
        n_members_of = {m: _ensemble_size(cursor, m) for m in rates_of}

        # ------------------------------------------------------------------
        # 3. Observations at the same cell, averaged over each record's period
        # ------------------------------------------------------------------
        valid_times = [init_times[m] + timedelta(hours=h)
                       for m, rates in rates_of.items() for h in rates]
        max_period  = max(periods_used, default=1)
        min_obs_t   = min(valid_times) - timedelta(hours=max_period - 1)
        max_obs_t   = max(valid_times)

        obs_of = {}
        for m, (m_lat, m_lon) in cell_of.items():
            if m not in rates_of:
                continue
            cursor.execute("""
                SELECT obs_time, AVG(value) AS obs_val
                FROM regridded_observation
                WHERE variable_name = %s AND source = %s
                  AND obs_time BETWEEN %s AND %s
                  AND latitude = %s AND longitude = %s
                GROUP BY obs_time
            """, (obs_var, obs_src, min_obs_t, max_obs_t, m_lat, m_lon))
            obs_of[m] = {r['obs_time']: float(r['obs_val']) for r in cursor.fetchall()}

        if not any(obs_of.values()):
            return jsonify({'models': {}, 'obs_hours': [],
                            'obs_warning': 'No observations found for this location/variable.'})

        # ------------------------------------------------------------------
        # 3b. Match and compute per-lead-time metrics
        # ------------------------------------------------------------------
        # All metrics are in mm/h so cross-model comparisons are fair. SSR is
        # scale-invariant; CRPS/bias/MAE/RMSE scale with the unit, so the shared
        # rate normalisation is what makes them comparable.
        model_data = {}

        for m_name, rates in rates_of.items():
            obs_by_time = obs_of.get(m_name) or {}
            for hour in sorted(rates):
                mean_rate, std_rate, period = rates[hour]
                vt = init_times[m_name] + timedelta(hours=hour)

                # Obs over the same period the forecast record covers; a
                # partially observed window is rejected (see _obs_window_mean).
                obs_rate, covered, n_obs_window = _obs_window_mean(obs_by_time, vt, period)
                if obs_rate is None or covered < period:
                    continue

                err      = mean_rate - obs_rate
                abs_err  = abs(err)
                err_sq   = err ** 2

                # SSR and CRPS need the spread, which isn't recoverable for
                # every record of a cumulative model (see _precip_rate_series).
                if std_rate is None:
                    ssr = crps = None
                else:
                    ssr  = _ssr_from_variances(std_rate ** 2, err_sq,
                                               n_members_of.get(m_name))
                    crps = _gaussian_crps(mean_rate, std_rate, obs_rate)

                model_data.setdefault(m_name, []).append({
                    'hour':      hour,
                    'ssr':       round(ssr,  4) if ssr  is not None else None,
                    'crps':      round(crps, 6) if crps is not None else None,
                    'bias':      round(err,  4),
                    'mae':       round(abs_err, 4),
                    'rmse':      round(math.sqrt(err_sq), 4),
                    # spread and obs in mm/h for display
                    'spread':    round(std_rate, 4) if std_rate is not None else None,
                    'mean_val':  round(mean_rate, 4),
                    'obs':       round(obs_rate,  4),
                    'period_h':  period,
                    'n_obs_in_window': n_obs_window,
                })

        # ------------------------------------------------------------------
        # 4. Compute per-model summaries
        # ------------------------------------------------------------------
        result_models = {}
        obs_hours_all = set()

        for m_name, hours_list in model_data.items():
            n        = len(hours_list)
            crpss    = [h['crps'] for h in hours_list if h['crps'] is not None]
            biases   = [h['bias'] for h in hours_list]
            maes     = [h['mae']  for h in hours_list]
            rmses    = [h['rmse'] for h in hours_list]
            # Spread and |error| paired, keeping only records that have a spread.
            paired   = [(h['spread'], h['mae']) for h in hours_list
                        if h['spread'] is not None]

            mean_crps = round(sum(crpss) / len(crpss), 4) if crpss else None
            bias_val  = round(sum(biases) / n,         4) if biases else None
            mae_val   = round(sum(maes)  / n,          4) if maes  else None
            rmse_val  = round(math.sqrt(sum(r ** 2 for r in rmses) / n), 4) if rmses else None

            # Aggregate SSR as mean(sigma^2)/mean(err^2), NOT the mean of the
            # per-case ratios: E[X/Y] != E[X]/E[Y], and a single near-zero error
            # sends its ratio to the clamp, which then drags the mean up. This
            # matches the estimator the spatial ssr_agg metric already uses.
            mean_ssr = None
            if paired:
                mean_var    = sum(s ** 2 for s, _ in paired) / len(paired)
                mean_sq_err = sum(e ** 2 for _, e in paired) / len(paired)
                if mean_sq_err > 1e-10:
                    mean_ssr = _ssr_from_variances(mean_var, mean_sq_err,
                                                  n_members_of.get(m_name))

            # Spread-skill correlation (spread vs |error|)
            corr_val = None
            if len(paired) >= 2:
                spreads  = [s for s, _ in paired]
                abs_errs = [e for _, e in paired]
                ns = len(paired)
                ms = sum(spreads) / ns
                me = sum(abs_errs) / ns
                num = sum((spreads[i] - ms) * (abs_errs[i] - me) for i in range(ns))
                den = math.sqrt(
                    sum((s - ms) ** 2 for s in spreads) *
                    sum((e - me) ** 2 for e in abs_errs)
                )
                corr_val = round(num / den, 4) if den > 1e-10 else None

            result_models[m_name] = {
                'hours':   hours_list,
                'summary': {
                    'mean_ssr':     mean_ssr,
                    'correlation':  corr_val,
                    'mean_crps':    mean_crps,
                    'bias':         bias_val,
                    'mae':          mae_val,
                    'rmse':         rmse_val,
                },
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
        else:
            obs_warning = 'No observations found for this location/variable.'

        print(f"✅ compare/skill: {len(result_models)} models, "
              f"{len(obs_hours_sorted)} obs hours at ({lat},{lon}), "
              f"cells={ {m: cell_of.get(m) for m in result_models} }")
        return jsonify({
            'models':             result_models,
            'obs_hours':          obs_hours_sorted,
            'obs_warning':        obs_warning,
            # Metadata so the frontend can display the conversion notes
            'model_accum_hours':  {m: MODEL_ACCUM_HOURS.get(m, 1) for m in models},
            # The grid cell each model was actually verified at (finding 3).
            'model_cells':        {m: list(cell_of[m]) for m in result_models if m in cell_of},
            'units':              'mm/h',  # all metrics are in mm/h after normalisation
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ Error in compare/skill: {e}")
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
    _cache_key = 'agree:' + json.dumps({
        'models':   sorted(models),
        'variable': variable,
        'hour':     hour,
        'bbox':     [round(min_lat, 2), round(max_lat, 2), round(min_lon, 2), round(max_lon, 2)],
    }, sort_keys=True)
    _cached = _cache_get(_cache_key)
    if _cached is not None:
        return jsonify(_cached)

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        if is_wind:
            # Inter-model disagreement of forecast wind SPEED. Derive per-model
            # speed √(mean_u²+mean_v²) in a subquery, then aggregate across models.
            cursor.execute("""
                SELECT latitude, longitude,
                       STDDEV(speed)              AS disagreement,
                       AVG(speed)                 AS avg_mean,
                       COUNT(DISTINCT model_name) AS n_models
                FROM (
                    SELECT u.model_name, u.latitude, u.longitude,
                           SQRT(POWER(u.mean_value, 2) + POWER(v.mean_value, 2)) AS speed
                    FROM regridded_forecast u
                    JOIN regridded_forecast v
                      ON v.model_name = u.model_name AND v.forecast_hour = u.forecast_hour
                     AND v.latitude = u.latitude AND v.longitude = u.longitude
                     AND v.variable_name = 'wind_v_10m'
                    WHERE u.model_name = ANY(%s) AND u.variable_name = 'wind_u_10m'
                      AND u.forecast_hour = %s
                      AND u.latitude  BETWEEN %s AND %s
                      AND u.longitude BETWEEN %s AND %s
                      AND u.mean_value IS NOT NULL AND v.mean_value IS NOT NULL
                ) s
                GROUP BY latitude, longitude
                HAVING COUNT(DISTINCT model_name) >= 2
                ORDER BY latitude, longitude
            """, (models, hour, min_lat, max_lat, min_lon, max_lon))
        else:
            cursor.execute("""
                SELECT
                    latitude,
                    longitude,
                    STDDEV(mean_value)          AS disagreement,
                    AVG(mean_value)             AS avg_mean,
                    COUNT(DISTINCT model_name)  AS n_models
                FROM regridded_forecast
                WHERE model_name    = ANY(%s)
                  AND variable_name = %s
                  AND forecast_hour = %s
                  AND latitude  BETWEEN %s AND %s
                  AND longitude BETWEEN %s AND %s
                GROUP BY latitude, longitude
                HAVING COUNT(DISTINCT model_name) >= 2
                ORDER BY latitude, longitude
            """, (models, var_name, hour, min_lat, max_lat, min_lon, max_lon))

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

        print(f"✅ compare/spatial-agreement: {n_points} pts, "
              f"{n_models} models, +{hour}h, {variable}")
        result = {
            'image':    img_b64,
            'hour':     hour,
            'n_models': n_models,
            'n_points': n_points,
        }
        _cache_set(_cache_key, result, timeout=int(os.environ.get('SPATIAL_AGREEMENT_CACHE_TTL', 20 * 60)))
        return jsonify(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ Error in compare/spatial-agreement: {e}")
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
    try:
        lat               = float(body.get('lat',         35.0))
        lon               = float(body.get('lon',        -75.0))
        hour_min          = int(body.get('hour_min',     0))
        hour_max          = int(body.get('hour_max',     168))
        # FSS needs a neighbourhood. `box_cells` = 1 keeps this a true point —
        # CSI/POD/FAR describe the clicked cell and FSS is undefined. Raising it
        # gives FSS a field to work with WITHOUT moving the point metrics, which
        # stay on the centre cell so their meaning never silently changes.
        box_cells         = max(1, min(int(body.get('box_cells',  1)), 41))
        fss_window        = max(1, min(int(body.get('fss_window', 3)), 21))
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
        init_time_val = _latest_init_time(cursor, model_name)
        if init_time_val is None:
            return jsonify({'error': 'No forecast data found for the selected parameters.'}), 404
        # Wind → forecast SPEED via u/v self-join (see _fcst_speed_sql).
        # Cumulative models need one record below hour_min to difference against.
        lookback = 0 if is_wind else _precip_lookback_hours(model_name)

        # Centre the box on the nearest grid cell rather than the raw click, so
        # box_cells maps to exactly that many cells per axis instead of 1-or-4
        # depending on where in a cell the user happened to click.
        cursor.execute("""
            SELECT latitude, longitude FROM regridded_forecast
            WHERE model_name = %s AND variable_name = %s
              AND latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s
            ORDER BY POWER(latitude - %s, 2) + POWER(longitude - %s, 2)
            LIMIT 1
        """, (model_name, fcst_var, lat - 1.0, lat + 1.0, lon - 1.0, lon + 1.0, lat, lon))
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
              AND u.forecast_hour BETWEEN %s AND %s
              AND u.latitude  BETWEEN %s AND %s
              AND u.longitude BETWEEN %s AND %s
              AND u.mean_value IS NOT NULL AND u.std_dev IS NOT NULL {_vnn}
            ORDER BY u.forecast_hour
        """, (model_name, *(() if is_wind else (fcst_var,)),
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
        rates_by_cell = {
            cell: {h: v for h, v in
                   _precip_rate_series(model_name, series, is_wind).items()
                   if hour_min <= h <= hour_max}
            for cell, series in raw_by_cell.items()
        }
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
        brier_sq_sum = 0.0
        n_brier      = 0
        # FSS is the one metric here that needs a field rather than a cell, so
        # it is accumulated separately over every cell in the box.
        fss_num = fss_den = 0.0

        def _fss_for_hour(hour):
            f_bin, o_bin = {}, {}
            for cell, cell_rates in rates_by_cell.items():
                rec = cell_rates.get(hour)
                if rec is None:
                    continue
                c_mean, _c_std, c_period = rec
                c_vt = init_time_val + timedelta(hours=hour)
                c_obs, c_covered, _n = _obs_window_mean(obs_by_cell.get(cell), c_vt, c_period)
                if c_obs is None or c_covered < c_period:
                    continue
                f_bin[cell] = float(c_mean > threshold_rate)
                o_bin[cell] = float(c_obs > threshold_rate)
            return _fss_components(f_bin, o_bin, fss_window)

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

            # Contingency table
            if box_cells > 1:
                h_num, h_den, _n = _fss_for_hour(hour)
                fss_num += h_num
                fss_den += h_den

            if   is_fcst and     is_obs:  hits         += 1
            elif is_fcst and not is_obs:  false_alarms += 1
            elif not is_fcst and is_obs:  misses       += 1
            else:                         correct_neg  += 1

            # Probabilistic event probability (Gaussian). Needs the spread, which
            # isn't recoverable for every record of a cumulative model, so those
            # records sit out of the Brier score but still count in the
            # contingency table (which only needs the mean).
            p_event = (None if std_rate is None
                       else _exceedance_probability(mean_rate, std_rate, threshold_rate))

            if p_event is not None:
                brier_sq_sum += (p_event - float(is_obs)) ** 2
                n_brier      += 1

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
        print(f"✅ categorical-metrics: {model_name} {variable} ({lat},{lon}) "
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
                'hits':                  hits,
                'misses':                misses,
                'false_alarms':          false_alarms,
                'correct_neg':           correct_neg,
                'pod':                   pod,
                'far':                   far,
                'fbi':                   fbi,
                'csi':                   csi,
                'brier_score':           bs,
                'fss':                   fss,
                'composite_confidence':  composite,
            },
            'obs_hours':    obs_hours_list,
            'obs_warning':  obs_warning,
            'threshold_info': threshold_info,
            'scored_area':    scored_area,
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"❌ Error in categorical-metrics: {e}")
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
        init_time_val = _latest_init_time(cursor, model_name)
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
              AND u.forecast_hour BETWEEN %s AND %s
              AND u.latitude  BETWEEN %s AND %s
              AND u.longitude BETWEEN %s AND %s
              AND u.mean_value IS NOT NULL AND u.std_dev IS NOT NULL {_vnn}
            ORDER BY u.forecast_hour, u.latitude, u.longitude
        """, (model_name, *(() if is_wind else (fcst_var,)),
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
        rates_by_cell = {cell: _precip_rate_series(model_name, series, is_wind)
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
                'brier_score': h_bs, 'fss': fss_hour,
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
            else:
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

        print(f"✅ region-categorical-metrics: {model_name} {variable} "
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
                'brier_score': bs, 'fss': mean_fss,
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

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"❌ Error in region-categorical-metrics: {e}")
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
    init_time_val = _latest_init_time(cursor, model_name)
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
          AND u.forecast_hour BETWEEN %s AND %s
          AND u.latitude  BETWEEN %s AND %s
          AND u.longitude BETWEEN %s AND %s
          AND u.mean_value IS NOT NULL AND u.std_dev IS NOT NULL {_vnn}
        ORDER BY u.forecast_hour, u.latitude, u.longitude
    """, (model_name, *(() if is_wind else (fcst_var,)),
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
    rates_by_cell = {cell: _precip_rate_series(model_name, series, is_wind)
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
        out.append({'hour': hour, 'n_pts': h_n_pts,
                    'csi': csi, 'pod': pod, 'far': far, 'fss': fss,
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
    try:
        lat        = float(body.get('lat',       35.0))
        lon        = float(body.get('lon',      -75.0))
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
        print(f"✅ compare/categorical: {len(models)} models, "
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
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"❌ Error in compare/categorical: {e}")
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
                          'crps', 'csi', 'pod', 'far', 'brier', 'fss']

# FSS is a property of a whole field at a lead time, so unlike the others it has
# no per-cell value: no map, and no entry in `cell_means`.
COMPARE_REGION_NO_CELL_VALUE = {'fss'}


def _single_metric_points(cursor, model_name, variable, metric,
                          min_lat, max_lat, min_lon, max_lon,
                          hour_min, hour_max, threshold_rate):
    """Per-cell points for one metric and one model.

    Handles both families: the pairs-based metrics off the regridded tables and
    `correlation`, which needs the ensemble path's run/variable/init lookups.
    """
    if metric in COMPARE_REGION_METRIC_FNS:
        return COMPARE_REGION_METRIC_FNS[metric](
            cursor, model_name, variable,
            min_lat, max_lat, min_lon, max_lon,
            hour_min, hour_max, threshold_rate=threshold_rate)

    if metric != 'correlation':
        return []

    run_id = get_model_run_id(cursor, model_name)
    if not run_id:
        return []
    cursor.execute(
        "SELECT initialization_time FROM forecast_runs WHERE run_id = %s", (run_id,))
    init_row = cursor.fetchone()
    if not init_row:
        return []
    is_wind    = (variable == 'wind')
    var_lookup = 'wind_u_10m' if is_wind else variable
    cursor.execute(
        "SELECT variable_id FROM variables WHERE variable_name = %s", (var_lookup,))
    var_row = cursor.fetchone()
    if not var_row:
        return []
    points, _n_hours = _compute_correlation_points(
        cursor, run_id, var_row['variable_id'], init_row['initialization_time'],
        min_lat, max_lat, min_lon, max_lon,
        'wind_speed' if is_wind else 'precipitation',
        model_name=model_name)
    return points


def _region_metric_points(cursor, model_name, variable, metrics,
                          min_lat, max_lat, min_lon, max_lon,
                          hour_min, hour_max, threshold_rate):
    """Per-cell points for each pairs-based metric, for one model.

    Every metric here derives from the same fcst↔obs match, so the two queries
    behind it run once per model instead of once per (model, metric) — nine
    metrics × three models would otherwise be 27 round trips per request.
    Returns (points_by_metric, pairs, n_matched_cells) — the raw pairs come back
    too so the caller can pool over samples rather than average per-cell scores.
    """
    wanted = [m for m in metrics if m in COMPARE_REGION_METRIC_FNS]
    if not wanted:
        return {}, {}, 0
    pairs = _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                          min_lat, max_lat, min_lon, max_lon,
                                          hour_min, hour_max)
    out = {}
    for m in wanted:
        out[m] = COMPARE_REGION_METRIC_FNS[m](
            cursor, model_name, variable,
            min_lat, max_lat, min_lon, max_lon,
            hour_min, hour_max, threshold_rate=threshold_rate, pairs=pairs)
    return out, pairs, len(pairs)






@app.route('/api/compare/region-metrics', methods=['POST'])
def compare_region_metrics():
    """Region-mean verification metrics for several models over one bbox.

    Request JSON:
        { models, variable, min_lat, max_lat, min_lon, max_lon,
          hour_min, hour_max, metrics?, threshold_mm_6h | threshold_ms }
    Response JSON:
        { models:   { AIFS: {mae: 2.1, bias: -0.3, ...}, .. },
          n_points: { AIFS: {mae: 812, ...}, .. },   # grid cells behind each mean
          n_cells:  { AIFS: 812, .. },               # matched fcst↔obs cells
          metrics, threshold_info, bbox, hour_min, hour_max, warnings }

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
        per_model     = {}
        per_counts    = {}
        per_cell_mean = {}
        n_cells       = {}
        warnings      = {}

        for m in models:
            points_by_metric, pairs, matched = _region_metric_points(
                cursor, m, variable, metrics,
                min_lat, max_lat, min_lon, max_lon,
                hour_min, hour_max, threshold_rate)

            # Headline values are pooled over every (cell, lead time) sample —
            # the same estimator point mode uses. The per-cell mean is what the
            # MAP of this metric averages to, so it is reported alongside.
            values = _region_pooled_metrics(pairs, metrics, threshold_rate,
                                            _ensemble_size(cursor, m),
                                            fss_window=fss_window)
            cell_means = {k: _region_mean(v) for k, v in points_by_metric.items()}
            counts     = {k: len(v) for k, v in points_by_metric.items()}
            # Metrics with no pooled form (correlation) fall back to the cell mean.
            for k, v in cell_means.items():
                values.setdefault(k, v)

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
            if matched == 0:
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

        print(f"✅ compare/region-metrics: {len(models)} models × {len(metrics)} metrics, "
              f"bbox [{min_lat},{max_lat}]×[{min_lon},{max_lon}] "
              f"{hour_min}-{hour_max}h, cells={n_cells}")

        return jsonify({
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
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"❌ Error in compare/region-metrics: {e}")
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
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"❌ Error in compare/spatial-diff: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        # Release before rendering: Cartopy work is CPU-bound and would
        # otherwise hold a pooled connection for the whole render.
        cursor.close()
        return_db_connection(conn)

    diff_points, n_a, n_b = _spatial_diff_points(pts_a, pts_b)

    if not diff_points:
        print(f"⚠️  compare/spatial-diff: no shared cells for {model_a} vs {model_b} "
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

        metric_label = PLOT_STYLE_REGISTRY.get(metric, {}).get('cbar_label', metric)
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
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"❌ Error rendering compare/spatial-diff: {e}")
        return jsonify({'error': 'Internal server error'}), 500

    print(f"✅ compare/spatial-diff: {metric} {model_a}−{model_b}, "
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
    print("🌬️  Wind: speed = √(u² + v²), direction = atan2(u,v)")
    print("📊 Cone of Uncertainty: mean, std, min, max, p10/p25/p75/p90 per hour")
    print("📊 Multi-model comparison: timeseries, skill scores, spatial agreement")
    print("=" * 60)

    flask_port  = int(os.environ.get('FLASK_PORT',  5000))
    # Default OFF: the Werkzeug debugger allows remote code execution and must never
    # be on for a deployed/beta instance. Local dev opts in via FLASK_DEBUG=true in .env.
    flask_debug = os.environ.get('FLASK_DEBUG', 'false').lower() in ('1', 'true', 'yes')
    app.run(debug=flask_debug, host='0.0.0.0', port=flask_port)