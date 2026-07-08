from flask import Flask, jsonify, request, Response, g
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import math
import io
import base64
import os
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
import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cfeature

app = Flask(__name__)
# Cap request bodies so a malformed/oversized POST can't exhaust memory.
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))
CORS(app, origins=os.environ.get('CORS_ORIGIN', 'http://localhost:3000'))


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
    int(os.environ.get('DB_POOL_MAX', 30)),
    **DB_CONFIG
)


def get_db_connection():
    return connection_pool.getconn()


def return_db_connection(conn):
    connection_pool.putconn(conn)


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


def _compute_ssr_points(cursor, run_id, variable_id, init_time, hour,
                        min_lat, max_lat, min_lon, max_lon, obs_col):
    """SSR at a single forecast hour from ensemble_statistics + observation_data."""
    cursor.execute("""
        SELECT latitude, longitude, mean_value, std_dev
        FROM ensemble_statistics
        WHERE run_id = %s AND variable_id = %s AND forecast_hour = %s
          AND latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s
          AND std_dev IS NOT NULL
    """, (run_id, variable_id, hour, min_lat, max_lat, min_lon, max_lon))
    ens_rows = cursor.fetchall()

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
    for row in ens_rows:
        lat  = float(row['latitude'])
        lon  = float(row['longitude'])
        mean = row['mean_value']
        std  = float(row['std_dev'])
        if mean is None:
            continue
        mean = float(mean)
        obs  = obs_lookup.get((round(lat * 4) / 4, round(lon * 4) / 4))
        if obs is None:
            continue
        err_sq = (mean - obs) ** 2
        ssr    = round(std ** 2 / err_sq, 4) if err_sq > 1e-10 else None
        if ssr is not None:
            points.append({'lat': lat, 'lon': lon, 'value': ssr})
    return points


def _compute_correlation_points(cursor, run_id, variable_id, init_time,
                                 min_lat, max_lat, min_lon, max_lon, obs_col):
    """Spread-skill correlation across verified hours from ensemble_statistics + observation_data."""
    candidate_hours = [0, 6, 12, 18, 24, 48, 72, 96, 120, 144, 168]
    hour_data = {}
    for hour in candidate_hours:
        valid_time = init_time + timedelta(hours=hour)
        cursor.execute("""
            SELECT latitude, longitude, mean_value, std_dev
            FROM ensemble_statistics
            WHERE run_id = %s AND variable_id = %s AND forecast_hour = %s
              AND latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s
              AND std_dev IS NOT NULL
        """, (run_id, variable_id, hour, min_lat, max_lat, min_lon, max_lon))
        ens_rows = cursor.fetchall()
        if not ens_rows:
            continue
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
        for row in ens_rows:
            lat  = float(row['latitude'])
            lon  = float(row['longitude'])
            mean = row['mean_value']
            std  = float(row['std_dev'])
            if mean is None:
                continue
            mean = float(mean)
            key  = (round(lat * 4) / 4, round(lon * 4) / 4)
            obs  = obs_lookup.get(key)
            if obs is None:
                continue
            point_pairs[key] = {'lat': lat, 'lon': lon,
                                 'spread': std, 'abs_error': abs(mean - obs)}
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


def _fetch_ens_obs_pairs_spatial(cursor, run_id, variable_id, init_time,
                                  model_name, obs_col,
                                  min_lat, max_lat, min_lon, max_lon,
                                  hour_min=0, hour_max=168):
    """Fetch (hour, mean_rate, std_rate, obs_rate) tuples from ensemble_statistics
    + observation_data — same original-resolution tables used by SSR and correlation.
    Returns {(lat_k, lon_k): [(hour, mean_rate, std_rate, obs_rate), ...]}."""
    from collections import defaultdict
    is_wind = (obs_col == 'wind_speed')
    accum_h = 1 if is_wind else MODEL_ACCUM_HOURS.get(model_name, 1)

    cursor.execute("""
        SELECT forecast_hour, latitude, longitude, mean_value, std_dev
        FROM ensemble_statistics
        WHERE run_id = %s AND variable_id = %s
          AND forecast_hour BETWEEN %s AND %s
          AND latitude  BETWEEN %s AND %s
          AND longitude BETWEEN %s AND %s
          AND mean_value IS NOT NULL AND std_dev IS NOT NULL
        ORDER BY latitude, longitude, forecast_hour
    """, (run_id, variable_id, hour_min, hour_max,
          min_lat, max_lat, min_lon, max_lon))
    ens_rows = cursor.fetchall()
    if not ens_rows:
        return {}

    valid_times = [init_time + timedelta(hours=r['forecast_hour']) for r in ens_rows]
    min_obs_t = min(valid_times) - timedelta(hours=accum_h - 1)
    max_obs_t = max(valid_times)

    cursor.execute(
        "SELECT obs_time, latitude, longitude, " + obs_col + " AS obs_val"
        " FROM observation_data"
        " WHERE obs_time BETWEEN %s AND %s"
        "   AND latitude  BETWEEN %s AND %s"
        "   AND longitude BETWEEN %s AND %s"
        "   AND " + obs_col + " IS NOT NULL",
        (min_obs_t, max_obs_t, min_lat, max_lat, min_lon, max_lon)
    )
    obs_dict = {}
    for r in cursor.fetchall():
        lat_k = round(float(r['latitude'])  * 4) / 4
        lon_k = round(float(r['longitude']) * 4) / 4
        obs_dict[(lat_k, lon_k, r['obs_time'])] = float(r['obs_val'])

    if not obs_dict:
        return {}

    result = defaultdict(list)
    for row in ens_rows:
        lat  = float(row['latitude'])
        lon  = float(row['longitude'])
        hour = row['forecast_hour']
        mean = float(row['mean_value'])
        std  = float(row['std_dev'])
        vt   = init_time + timedelta(hours=hour)
        lat_k = round(lat * 4) / 4
        lon_k = round(lon * 4) / 4
        obs_window = [
            obs_dict[(lat_k, lon_k, vt - timedelta(hours=dh))]
            for dh in range(accum_h - 1, -1, -1)
            if (lat_k, lon_k, vt - timedelta(hours=dh)) in obs_dict
        ]
        if not obs_window:
            continue
        result[(lat_k, lon_k)].append((
            hour,
            mean / accum_h,
            std  / accum_h,
            sum(obs_window) / len(obs_window),
        ))
    return dict(result)


def _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                   min_lat, max_lat, min_lon, max_lon,
                                   hour_min=0, hour_max=168):
    """
    Fetches per-(lat,lon) lists of (hour, mean_rate, std_rate, obs_rate) tuples
    from regridded_forecast + regridded_observation tables.
    All rates are normalised to mm/h by dividing by MODEL_ACCUM_HOURS.
    Returns dict: {(lat_rounded, lon_rounded): [(hour, mean_rate, std_rate, obs_rate), ...]}
    """
    from collections import defaultdict
    is_wind = (variable == 'wind')
    # Wind speed is instantaneous (m/s) — no accumulation period normalization.
    accum_h = 1 if is_wind else MODEL_ACCUM_HOURS.get(model_name, 1)
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

    cursor.execute("""
        SELECT latitude, longitude, forecast_hour, mean_value, std_dev
        FROM regridded_forecast
        WHERE model_name    = %s
          AND variable_name = %s
          AND forecast_hour BETWEEN %s AND %s
          AND latitude  BETWEEN %s AND %s
          AND longitude BETWEEN %s AND %s
          AND mean_value IS NOT NULL AND std_dev IS NOT NULL
        ORDER BY latitude, longitude, forecast_hour
    """, (model_name, fcst_var, hour_min, hour_max,
          min_lat, max_lat, min_lon, max_lon))
    fcst_rows = cursor.fetchall()
    if not fcst_rows:
        return {}

    valid_times = [init_time_val + timedelta(hours=r['forecast_hour'])
                   for r in fcst_rows]
    min_obs_t = min(valid_times) - timedelta(hours=accum_h - 1)
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
    obs_dict = {}
    for r in cursor.fetchall():
        lat_k = round(float(r['latitude']),  2)
        lon_k = round(float(r['longitude']), 2)
        obs_dict[(lat_k, lon_k, r['obs_time'])] = float(r['obs_val'])

    if not obs_dict:
        return {}

    result = defaultdict(list)
    for row in fcst_rows:
        lat  = round(float(row['latitude']),  2)
        lon  = round(float(row['longitude']), 2)
        hour = row['forecast_hour']
        mean = float(row['mean_value'])
        std  = float(row['std_dev'])
        vt   = init_time_val + timedelta(hours=hour)

        obs_window = [
            obs_dict[(lat, lon, vt - timedelta(hours=dh))]
            for dh in range(accum_h - 1, -1, -1)
            if (lat, lon, vt - timedelta(hours=dh)) in obs_dict
        ]
        if not obs_window:
            continue
        obs_rate  = sum(obs_window) / len(obs_window)
        mean_rate = mean / accum_h
        std_rate  = std  / accum_h
        result[(lat, lon)].append((hour, mean_rate, std_rate, obs_rate))

    return dict(result)


# ── Accuracy metric compute functions (use regridded tables) ──────────────────

def _compute_bias_points_rf(cursor, model_name, variable,
                             min_lat, max_lat, min_lon, max_lon,
                             hour_min=0, hour_max=168, **_kw):
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
                            hour_min=0, hour_max=168, **_kw):
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
                             hour_min=0, hour_max=168, **_kw):
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
                             hour_min=0, hour_max=168, **_kw):
    pairs = _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                           min_lat, max_lat, min_lon, max_lon,
                                           hour_min, hour_max)
    points = []
    for (lat, lon), entries in pairs.items():
        if not entries:
            continue
        crps_vals = []
        for _, mr, sr, orr in entries:
            if sr > 1e-10:
                z    = (orr - mr) / sr
                crps = sr * (z * (2 * scipy.stats.norm.cdf(z) - 1)
                             + 2 * scipy.stats.norm.pdf(z)
                             - 1.0 / np.sqrt(np.pi))
            else:
                crps = abs(mr - orr)
            crps_vals.append(max(0.0, crps))
        points.append({'lat': lat, 'lon': lon, 'value': round(float(np.mean(crps_vals)), 4)})
    return points


# ── Categorical metric compute functions ─────────────────────────────────────

def _compute_csi_points_rf(cursor, model_name, variable,
                            min_lat, max_lat, min_lon, max_lon,
                            hour_min=0, hour_max=168,
                            threshold_rate=25.0 / 6.0, **_kw):
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
                            threshold_rate=25.0 / 6.0, **_kw):
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
                            threshold_rate=25.0 / 6.0, **_kw):
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
                              threshold_rate=25.0 / 6.0, **_kw):
    pairs = _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                           min_lat, max_lat, min_lon, max_lon,
                                           hour_min, hour_max)
    points = []
    for (lat, lon), entries in pairs.items():
        if not entries:
            continue
        bs_vals = []
        for _, mr, sr, orr in entries:
            is_obs = float(orr > threshold_rate)
            if sr > 1e-10:
                p_event = float(1.0 - scipy.stats.norm.cdf(threshold_rate,
                                                             loc=mr, scale=sr))
            else:
                p_event = 1.0 if mr > threshold_rate else 0.0
            bs_vals.append((p_event - is_obs) ** 2)
        points.append({'lat': lat, 'lon': lon,
                       'value': round(float(np.mean(bs_vals)), 6)})
    return points


def _dispatch_ssr(cursor, run_id, variable_id, init_time, args,
                  min_lat, max_lat, min_lon, max_lon, obs_col):
    hour   = int(args.get('hour', 6))
    points = _compute_ssr_points(cursor, run_id, variable_id, init_time, hour,
                                  min_lat, max_lat, min_lon, max_lon, obs_col)
    return points, {'hour': hour}


def _dispatch_correlation(cursor, run_id, variable_id, init_time, args,
                           min_lat, max_lat, min_lon, max_lon, obs_col):
    points, n_hours = _compute_correlation_points(
        cursor, run_id, variable_id, init_time,
        min_lat, max_lat, min_lon, max_lon, obs_col,
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


def _ens_pairs(cursor, run_id, variable_id, init_time, args,
               min_lat, max_lat, min_lon, max_lon, obs_col,
               hour_min=None, hour_max=None):
    """Convenience wrapper: build ens pairs for a dispatcher."""
    hmin = int(args.get('hour_min', 0))  if hour_min is None else hour_min
    hmax = int(args.get('hour_max', 168)) if hour_max is None else hour_max
    return _fetch_ens_obs_pairs_spatial(
        cursor, run_id, variable_id, init_time,
        args.get('model', 'AIFS'), obs_col,
        min_lat, max_lat, min_lon, max_lon, hmin, hmax,
    )


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
                                hour_min=0, hour_max=168, **_kw):
    """
    Time-aggregated SSR using regridded tables.
    SSR = mean(σ²) / mean(ε²) across all matched lead times per grid point.
    Requires ≥2 matched pairs to be meaningful.
    """
    pairs = _fetch_fcst_obs_pairs_spatial(cursor, model_name, variable,
                                           min_lat, max_lat, min_lon, max_lon,
                                           hour_min, hour_max)
    points = []
    for (lat, lon), entries in pairs.items():
        if len(entries) < 2:
            continue
        mean_var    = float(np.mean([sr ** 2 for _, _, sr, _   in entries]))
        mean_sq_err = float(np.mean([(mr - orr) ** 2 for _, mr, _, orr in entries]))
        if mean_sq_err > 1e-10:
            ssr = round(mean_var / mean_sq_err, 4)
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
    forecast_hour = int(request.args.get('hour', 6))
    member        = request.args.get('member', 'mean')

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
    forecast_hour = int(request.args.get('hour', 6))
    member        = request.args.get('member', 'mean')

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
            # Precipitation — aggregate directly over ensemble members
            cursor.execute("""
                SELECT
                    fd.forecast_hour,
                    AVG(fd.value)                                               AS mean_val,
                    STDDEV(fd.value)                                            AS std_val,
                    MIN(fd.value)                                               AS min_val,
                    MAX(fd.value)                                               AS max_val,
                    PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY fd.value)     AS p10,
                    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY fd.value)     AS p25,
                    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY fd.value)     AS p75,
                    PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY fd.value)     AS p90
                FROM forecast_data fd
                WHERE fd.run_id = %s
                  AND fd.variable_id = (SELECT variable_id FROM variables WHERE variable_name = %s)
                  AND ABS(fd.latitude  - %s) <= %s
                  AND ABS(fd.longitude - %s) <= %s
                GROUP BY fd.forecast_hour
                ORDER BY fd.forecast_hour
            """, (run_id, variable, lat, radius, lon, radius))

        # Precipitation is stored as period-accumulated totals; divide by accum_h
        # to convert to mm/h rate. Wind, temperature, and pressure are
        # instantaneous so no normalization is needed (accum_h = 1).
        accum_h = MODEL_ACCUM_HOURS.get(model_name, 1) if variable == 'precipitation' else 1

        rows   = cursor.fetchall()
        result = []
        for row in rows:
            result.append({
                'hour': row['forecast_hour'],
                'mean': round(float(row['mean_val'] or 0) / accum_h, 4),
                'std':  round(float(row['std_val']  or 0) / accum_h, 4),
                'min':  round(float(row['min_val']  or 0) / accum_h, 4),
                'max':  round(float(row['max_val']  or 0) / accum_h, 4),
                'p10':  round(float(row['p10']       or 0) / accum_h, 4),
                'p25':  round(float(row['p25']       or 0) / accum_h, 4),
                'p75':  round(float(row['p75']       or 0) / accum_h, 4),
                'p90':  round(float(row['p90']       or 0) / accum_h, 4),
            })

        print(f"✅ Timeseries: {len(result)} hours for {model_name} at ({lat}, {lon}) "
              f"[accum_h={accum_h}]")
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

        results = []
        for hour in available_hours:
            # Fetch ensemble members at this hour
            if variable == 'wind':
                cursor.execute("""
                    SELECT SQRT(POWER(u.value, 2) + POWER(v.value, 2)) AS member_val
                    FROM forecast_data u
                    JOIN forecast_data v
                        ON u.run_id = v.run_id AND u.forecast_hour = v.forecast_hour
                       AND u.ensemble_member = v.ensemble_member
                       AND u.latitude = v.latitude AND u.longitude = v.longitude
                    WHERE u.run_id = %s AND u.forecast_hour = %s
                      AND u.variable_id = (SELECT variable_id FROM variables WHERE variable_name = 'wind_u_10m')
                      AND v.variable_id = (SELECT variable_id FROM variables WHERE variable_name = 'wind_v_10m')
                      AND ABS(u.latitude  - %s) <= %s
                      AND ABS(u.longitude - %s) <= %s
                      AND u.ensemble_member IS NOT NULL
                """, (run_id, hour, lat, radius, lon, radius))
            else:
                cursor.execute("""
                    SELECT value AS member_val FROM forecast_data
                    WHERE run_id = %s AND forecast_hour = %s
                      AND variable_id = (SELECT variable_id FROM variables WHERE variable_name = %s)
                      AND ABS(latitude  - %s) <= %s
                      AND ABS(longitude - %s) <= %s
                      AND ensemble_member IS NOT NULL
                    ORDER BY ensemble_member
                """, (run_id, hour, variable, lat, radius, lon, radius))

            # Precipitation members are period-accumulated totals (mm/6h for AIFS,
            # mm/3h for GEFS, mm/h for UKMO). IMERG observations are in mm/h.
            # Divide by accum_h so all values are in mm/h before computing
            # spread/error. Wind and other instantaneous variables use accum_h=1.
            accum_h = MODEL_ACCUM_HOURS.get(model_name, 1) if variable == 'precipitation' else 1
            members = [float(r['member_val']) / accum_h for r in cursor.fetchall()]

            # Fetch matched observation (average within radius at the valid time)
            cursor.execute("""
                SELECT AVG(""" + obs_col + """) AS obs_val
                FROM observation_data
                WHERE obs_time = %s::timestamp + (%s || ' hours')::interval
                  AND ABS(latitude  - %s) <= %s
                  AND ABS(longitude - %s) <= %s
                  AND """ + obs_col + """ IS NOT NULL
            """, (str(init_time), hour, lat, radius, lon, radius))

            obs_row = cursor.fetchone()
            if not members or not obs_row or obs_row['obs_val'] is None:
                continue

            obs      = float(obs_row['obs_val'])
            n        = len(members)
            ens_mean = sum(members) / n
            spread_sq = sum((x - ens_mean) ** 2 for x in members) / n   # population variance
            spread    = math.sqrt(spread_sq)
            error     = abs(ens_mean - obs)
            error_sq  = error ** 2
            ssr       = round(spread_sq / error_sq, 4) if error_sq > 1e-10 else None

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

        print(f"✅ Spread-skill: {len(results)} hours matched, corr={correlation} for ({lat},{lon})")
        return jsonify({'hours': results, 'correlation': correlation, 'n_cases': len(results)})

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
    min_lat    = float(request.args.get('min_lat',  25))
    max_lat    = float(request.args.get('max_lat',  45))
    min_lon    = float(request.args.get('min_lon', -85))
    max_lon    = float(request.args.get('max_lon', -65))
    threshold_mm_6h = float(request.args.get('threshold_mm_6h', 25.0))

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
    try:
        body     = request.get_json(force=True)
        metric   = body.get('metric',   'ssr')
        model    = body.get('model',    'AIFS')
        variable = body.get('variable', 'precipitation')
        hour     = body.get('hour',     6)
        n_hours  = body.get('n_hours',  None)
        points   = body.get('points',   [])

        if not points:
            return jsonify({'error': 'No points provided'}), 400

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

        # pcolormesh needs cell-edge coordinates (N+1 values per axis)
        step      = 0.25
        lat_edges = np.append(lat_arr - step / 2, lat_arr[-1] + step / 2)
        lon_edges = np.append(lon_arr - step / 2, lon_arr[-1] + step / 2)
        lon_mesh, lat_mesh = np.meshgrid(lon_edges, lat_edges)

        # ── Colourmap & norm ──────────────────────────────────────────────
        if metric not in PLOT_STYLE_REGISTRY:
            return jsonify({'error': f'No plot style for metric: {metric}'}), 400
        style          = PLOT_STYLE_REGISTRY[metric]
        cmap           = style['cmap']
        norm           = style['norm']
        cbar_label     = style['cbar_label']
        cbar_ticks     = style['cbar_ticks']
        cbar_ticklabels = style['cbar_ticklabels']
        cbar_fontsize  = style['cbar_fontsize']

        # ── Map extent ────────────────────────────────────────────────────
        lat_range = lat_arr.max() - lat_arr.min()
        lon_range = lon_arr.max() - lon_arr.min()
        pad = max(2.0, min(lat_range, lon_range) * 0.18)
        extent = [
            lon_arr.min() - pad, lon_arr.max() + pad,
            lat_arr.min() - pad, lat_arr.max() + pad,
        ]

        # ── Figure ───────────────────────────────────────────────────────
        proj = ccrs.PlateCarree()
        fig  = plt.figure(figsize=(13, 7), dpi=130)
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
        cbar.set_ticks(cbar_ticks)
        cbar.set_ticklabels(cbar_ticklabels, fontsize=cbar_fontsize)
        cbar.ax.tick_params(labelcolor='#333333')

        # Title
        var_labels = {
            'precipitation': 'Precipitation',
            'wind':          'Wind Speed',
            'temperature_2m':'Temperature (2 m)',
            'pressure_msl':  'Mean Sea-Level Pressure',
        }
        var_label = var_labels.get(variable, variable)
        METRIC_LABELS = {k: v['cbar_label'] for k, v in PLOT_STYLE_REGISTRY.items()}
        metric_label = METRIC_LABELS.get(metric, metric)
        title_line1 = f"{model}  ·  {var_label}  ·  {metric_label}"
        CATEGORICAL_METRICS = {'csi', 'pod', 'far', 'brier'}
        thr_info = ''
        if metric in CATEGORICAL_METRICS:
            thr_mm6h = body.get('threshold_mm_6h', 25)
            thr_info = f'  ·  thr >{thr_mm6h} mm/6h'
        if metric == 'ssr':
            title_line2 = f"Forecast +{hour}h  |  {len(points)} grid points"
        elif metric == 'correlation':
            title_line2 = f"{n_hours} verified lead times  |  {len(points)} grid points"
        else:
            title_line2 = f"{len(points)} grid points{thr_info}"
        ax.set_title(f"{title_line1}\n{title_line2}",
                     fontsize=10.5, fontweight='bold', pad=10, color='#1a1a1a')

        # Small watermark
        ax.text(0.995, 0.005, 'WEAVE', transform=ax.transAxes,
                fontsize=7, color='gray', alpha=0.55, ha='right', va='bottom')

        plt.tight_layout(pad=0.4)

        # ── Encode PNG → base64 ───────────────────────────────────────────
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=130, bbox_inches='tight',
                    facecolor='white', edgecolor='none')
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode('utf-8')
        plt.close(fig)

        print(f"✅ Plot: {metric} · {model} · {var_label} · {len(points)} pts")
        return jsonify({'image': img_b64})

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
    conn   = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM forecast_data")
        count = cursor.fetchone()[0]
        return jsonify({
            "status": "healthy",
            "database": "connected",
            "total_forecast_points": count
        })
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500
    finally:
        cursor.close()
        return_db_connection(conn)


# ── Model accumulation periods (hours) ───────────────────────────────────────
# AIFS outputs 6-hourly accumulated precipitation (mm/6h)
# GEFS outputs 3-hourly accumulated precipitation (mm/3h)
# UKMO outputs hourly instantaneous values (mm/h)
# All skill metrics are computed in mm/h (rate) by dividing mean/std by this
# factor and averaging observations over the same accumulation window.
MODEL_ACCUM_HOURS = {
    'AIFS': 6,
    'GEFS': 3,
    'UKMO': 1,
}

# ── Comparison endpoints (multi-model, regridded_forecast / regridded_observation) ──


@app.route('/api/compare/timeseries', methods=['POST'])
def compare_timeseries():
    """
    Returns ensemble mean and std per forecast hour for multiple models at a
    single lat/lon point, queried from regridded_forecast.

    Request JSON:
        { models, lat, lon, hour_min, hour_max, variable }
    Response:
        { "AIFS": [{"hour": 6, "mean": 1.234, "std": 0.456}, ...], ... }
    """
    body     = request.get_json(force=True)
    models   = body.get('models', [])
    lat      = float(body.get('lat', 35.0))
    lon      = float(body.get('lon', -75.0))
    hour_min = int(body.get('hour_min', 0))
    hour_max = int(body.get('hour_max', 168))
    variable = body.get('variable', 'precipitation')

    # Map 'wind' shorthand to the u-component stored in regridded_forecast
    var_name = 'wind_u_10m' if variable == 'wind' else variable

    if not models:
        return jsonify({'error': 'No models specified'}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("""
            SELECT model_name, forecast_hour, mean_value, std_dev
            FROM regridded_forecast
            WHERE model_name = ANY(%s)
              AND variable_name = %s
              AND forecast_hour BETWEEN %s AND %s
              AND latitude  BETWEEN %s AND %s
              AND longitude BETWEEN %s AND %s
            ORDER BY model_name, forecast_hour
        """, (
            models, var_name, hour_min, hour_max,
            lat - 0.26, lat + 0.26,
            lon - 0.26, lon + 0.26,
        ))
        rows = cursor.fetchall()

        result = {}
        for row in rows:
            m = row['model_name']
            if m not in result:
                result[m] = []
            result[m].append({
                'hour': row['forecast_hour'],
                'mean': round(float(row['mean_value']), 4) if row['mean_value'] is not None else None,
                'std':  round(float(row['std_dev']),    4) if row['std_dev']    is not None else None,
            })

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
    body     = request.get_json(force=True)
    models   = body.get('models', [])
    lat      = float(body.get('lat', 35.0))
    lon      = float(body.get('lon', -75.0))
    hour_min = int(body.get('hour_min', 0))
    hour_max = int(body.get('hour_max', 168))
    variable = body.get('variable', 'precipitation')

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
        # 1. Fetch forecast rows for all requested models
        # ------------------------------------------------------------------
        cursor.execute("""
            SELECT
                rf.model_name,
                rf.forecast_hour,
                rf.mean_value,
                rf.std_dev,
                fr.initialization_time
            FROM regridded_forecast rf
            JOIN models m  ON m.model_name = rf.model_name
            JOIN forecast_runs fr
                ON fr.model_id = m.model_id
                AND fr.run_id = (
                    SELECT run_id FROM forecast_runs fr2
                    JOIN models m2 ON m2.model_id = fr2.model_id
                    WHERE m2.model_name = rf.model_name
                    ORDER BY fr2.initialization_time DESC
                    LIMIT 1
                )
            WHERE rf.model_name = ANY(%s)
              AND rf.variable_name = %s
              AND rf.forecast_hour BETWEEN %s AND %s
              AND rf.latitude  BETWEEN %s AND %s
              AND rf.longitude BETWEEN %s AND %s
              AND rf.mean_value IS NOT NULL
              AND rf.std_dev    IS NOT NULL
            ORDER BY rf.model_name, rf.forecast_hour
        """, (
            models, fcst_var, hour_min, hour_max,
            lat - 0.26, lat + 0.26,
            lon - 0.26, lon + 0.26,
        ))
        fcst_rows = cursor.fetchall()

        if not fcst_rows:
            return jsonify({'models': {}, 'obs_hours': [],
                            'obs_warning': 'No forecast data found for selected parameters.'})

        # ------------------------------------------------------------------
        # 2. Fetch observations covering the full accumulation window
        # ------------------------------------------------------------------
        # For models with accumulation > 1h (AIFS=6h, GEFS=3h) we need obs
        # at multiple hourly timestamps to compute the average rate in that
        # window.  Expand the obs query backward by max(accum_h) - 1 hours.
        valid_times_set = set()
        for row in fcst_rows:
            vt = row['initialization_time'] + timedelta(hours=row['forecast_hour'])
            valid_times_set.add(vt)

        if not valid_times_set:
            return jsonify({'models': {}, 'obs_hours': [],
                            'obs_warning': 'No observations found for this location/variable.'})

        max_accum = max(MODEL_ACCUM_HOURS.get(m, 1) for m in models)
        min_obs_t = min(valid_times_set) - timedelta(hours=max_accum - 1)
        max_obs_t = max(valid_times_set)

        cursor.execute("""
            SELECT obs_time, AVG(value) AS obs_val
            FROM regridded_observation
            WHERE variable_name = %s
              AND source        = %s
              AND obs_time BETWEEN %s AND %s
              AND latitude  BETWEEN %s AND %s
              AND longitude BETWEEN %s AND %s
            GROUP BY obs_time
            ORDER BY obs_time
        """, (
            obs_var, obs_src, min_obs_t, max_obs_t,
            lat - 0.26, lat + 0.26,
            lon - 0.26, lon + 0.26,
        ))
        obs_rows     = cursor.fetchall()
        # keyed by obs_time for O(1) lookup
        obs_by_time  = {row['obs_time']: float(row['obs_val']) for row in obs_rows}

        if not obs_by_time:
            return jsonify({'models': {}, 'obs_hours': [],
                            'obs_warning': 'No observations found for this location/variable.'})

        # ------------------------------------------------------------------
        # 3. Match forecasts to observations and compute rate-normalised metrics
        # ------------------------------------------------------------------
        # All metrics are computed in mm/h so cross-model comparisons are fair:
        #   mean_rate = mean_value / accum_h
        #   std_rate  = std_dev    / accum_h
        #   obs_rate  = average of hourly IMERG values in the accum window (mm/h)
        #
        # SSR is scale-invariant (accum_h cancels), so the value is identical
        # to computing on raw totals.  CRPS, bias, MAE, RMSE all scale with
        # the unit, so normalising to mm/h makes them cross-model comparable.
        model_data = {}  # model_name -> list of per-hour dicts

        for row in fcst_rows:
            m_name  = row['model_name']
            hour    = row['forecast_hour']
            mean    = float(row['mean_value'])
            std     = float(row['std_dev'])
            vt      = row['initialization_time'] + timedelta(hours=hour)
            accum_h = MODEL_ACCUM_HOURS.get(m_name, 1)

            # Collect hourly obs in the half-open window (vt - accum_h, vt]
            # e.g. AIFS +6h  →  obs at vt-5h, vt-4h, vt-3h, vt-2h, vt-1h, vt
            obs_window = []
            for dh in range(accum_h - 1, -1, -1):
                t = vt - timedelta(hours=dh)
                if t in obs_by_time:
                    obs_window.append(obs_by_time[t])

            if not obs_window:
                continue

            obs_rate  = sum(obs_window) / len(obs_window)  # avg mm/h in window
            mean_rate = mean / accum_h                      # mm/h
            std_rate  = std  / accum_h                      # mm/h

            err     = mean_rate - obs_rate
            abs_err = abs(err)
            err_sq  = err ** 2

            # SSR (scale-invariant — same result as with raw totals)
            ssr = round(std_rate ** 2 / err_sq, 6) if err_sq > 1e-10 else None

            # Gaussian CRPS (in mm/h — comparable across models)
            if std_rate > 1e-10:
                z    = (obs_rate - mean_rate) / std_rate
                crps = float(std_rate * (
                    z * (2.0 * scipy.stats.norm.cdf(z) - 1.0)
                    + 2.0 * scipy.stats.norm.pdf(z)
                    - 1.0 / math.sqrt(math.pi)
                ))
            else:
                crps = abs_err

            if m_name not in model_data:
                model_data[m_name] = []

            model_data[m_name].append({
                'hour':      hour,
                'ssr':       round(ssr, 4)        if ssr is not None else None,
                'crps':      round(crps, 6),
                'bias':      round(err,  4),
                'mae':       round(abs_err, 4),
                'rmse':      round(math.sqrt(err_sq), 4),
                # spread and obs in mm/h for display
                'spread':    round(std_rate,  4),
                'mean_val':  round(mean_rate, 4),
                'obs':       round(obs_rate,  4),
                # raw stored values for reference
                'raw_mean':  round(mean, 4),
                'raw_std':   round(std,  4),
                'accum_h':   accum_h,
                'n_obs_in_window': len(obs_window),
            })

        # ------------------------------------------------------------------
        # 4. Compute per-model summaries
        # ------------------------------------------------------------------
        result_models = {}
        obs_hours_all = set()

        for m_name, hours_list in model_data.items():
            n        = len(hours_list)
            ssrs     = [h['ssr']  for h in hours_list if h['ssr']  is not None]
            crpss    = [h['crps'] for h in hours_list]
            biases   = [h['bias'] for h in hours_list]
            maes     = [h['mae']  for h in hours_list]
            rmses    = [h['rmse'] for h in hours_list]
            spreads  = [h['spread'] for h in hours_list]
            abs_errs = [h['mae']  for h in hours_list]

            mean_ssr  = round(sum(ssrs)  / len(ssrs),  4) if ssrs  else None
            mean_crps = round(sum(crpss) / n,          4) if crpss else None
            bias_val  = round(sum(biases) / n,         4) if biases else None
            mae_val   = round(sum(maes)  / n,          4) if maes  else None
            rmse_val  = round(math.sqrt(sum(r ** 2 for r in rmses) / n), 4) if rmses else None

            # Spread-skill correlation (spread vs |error|)
            corr_val = None
            if len(spreads) >= 2:
                ns = len(spreads)
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
              f"accum_hours={MODEL_ACCUM_HOURS}")
        return jsonify({
            'models':             result_models,
            'obs_hours':          obs_hours_sorted,
            'obs_warning':        obs_warning,
            # Metadata so the frontend can display the conversion notes
            'model_accum_hours':  {m: MODEL_ACCUM_HOURS.get(m, 1) for m in models},
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
    body     = request.get_json(force=True)
    models   = body.get('models', [])
    min_lat  = float(body.get('min_lat',  25))
    max_lat  = float(body.get('max_lat',  45))
    min_lon  = float(body.get('min_lon', -85))
    max_lon  = float(body.get('max_lon', -65))
    hour     = int(body.get('hour', 24))
    variable = body.get('variable', 'precipitation')

    var_name = 'wind_u_10m' if variable == 'wind' else variable

    VAR_UNITS = {
        'precipitation': 'mm/h',
        'wind':          'm/s',
        'wind_u_10m':    'm/s',
        'wind_v_10m':    'm/s',
    }
    unit = VAR_UNITS.get(variable, variable)

    if not models or len(models) < 2:
        return jsonify({'error': 'At least 2 models required for spatial agreement'}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
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

        # ── Figure ───────────────────────────────────────────────────────
        proj = ccrs.PlateCarree()
        fig  = plt.figure(figsize=(13, 7), dpi=130)
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

        plt.tight_layout(pad=0.4)

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=130, bbox_inches='tight',
                    facecolor='white', edgecolor='none')
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode('utf-8')
        plt.close(fig)

        print(f"✅ compare/spatial-agreement: {n_points} pts, "
              f"{n_models} models, +{hour}h, {variable}")
        return jsonify({
            'image':    img_b64,
            'hour':     hour,
            'n_models': n_models,
            'n_points': n_points,
        })

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
    body              = request.get_json(force=True)
    model_name        = body.get('model',            'AIFS')
    variable          = body.get('variable',         'precipitation')
    lat               = float(body.get('lat',         35.0))
    lon               = float(body.get('lon',        -75.0))
    hour_min          = int(body.get('hour_min',     0))
    hour_max          = int(body.get('hour_max',     168))

    is_wind = (variable == 'wind')
    if is_wind:
        fcst_var, obs_var, obs_src = 'wind_u_10m', 'wind_speed', 'ERA5_WIND'
        # Wind speed is in m/s (instantaneous) — use threshold_ms directly.
        threshold_rate = float(body.get('threshold_ms', 10.0))
        accum_h        = 1
    else:
        fcst_var, obs_var, obs_src = variable, 'precipitation', 'GPM_IMERG_V07B'
        threshold_rate = float(body.get('threshold_mm_6h', 25.0)) / 6.0
        accum_h        = MODEL_ACCUM_HOURS.get(model_name, 1)

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # ── 1. Forecast rows ─────────────────────────────────────────────────
        cursor.execute("""
            SELECT
                rf.forecast_hour,
                rf.mean_value,
                rf.std_dev,
                fr.initialization_time
            FROM regridded_forecast rf
            JOIN models m  ON m.model_name = rf.model_name
            JOIN forecast_runs fr
                ON fr.model_id = m.model_id
               AND fr.run_id = (
                       SELECT run_id FROM forecast_runs fr2
                       JOIN models m2 ON m2.model_id = fr2.model_id
                       WHERE m2.model_name = rf.model_name
                       ORDER BY fr2.initialization_time DESC LIMIT 1
                   )
            WHERE rf.model_name   = %s
              AND rf.variable_name = %s
              AND rf.forecast_hour BETWEEN %s AND %s
              AND rf.latitude  BETWEEN %s AND %s
              AND rf.longitude BETWEEN %s AND %s
              AND rf.mean_value IS NOT NULL AND rf.std_dev IS NOT NULL
            ORDER BY rf.forecast_hour
        """, (model_name, fcst_var, hour_min, hour_max,
              lat - 0.26, lat + 0.26, lon - 0.26, lon + 0.26))
        fcst_rows = cursor.fetchall()

        if not fcst_rows:
            return jsonify({'error': 'No forecast data found for the selected parameters.'}), 404

        # ── 2. Observations (extended window for accumulation) ────────────────
        valid_times = [
            r['initialization_time'] + timedelta(hours=r['forecast_hour'])
            for r in fcst_rows
        ]
        min_obs_t = min(valid_times) - timedelta(hours=accum_h - 1)
        max_obs_t = max(valid_times)

        cursor.execute("""
            SELECT obs_time, AVG(value) AS obs_val
            FROM regridded_observation
            WHERE variable_name = %s AND source = %s
              AND obs_time BETWEEN %s AND %s
              AND latitude  BETWEEN %s AND %s
              AND longitude BETWEEN %s AND %s
            GROUP BY obs_time ORDER BY obs_time
        """, (obs_var, obs_src, min_obs_t, max_obs_t,
              lat - 0.26, lat + 0.26, lon - 0.26, lon + 0.26))
        obs_by_time = {r['obs_time']: float(r['obs_val']) for r in cursor.fetchall()}

        if not obs_by_time:
            return jsonify({
                'hours': [], 'summary': {}, 'obs_hours': [],
                'obs_warning': 'No observations found for this location and variable.',
            })

        # ── 3. Per-hour categorical + probabilistic metrics ───────────────────
        hours_data = []
        hits = misses = false_alarms = correct_neg = 0
        brier_sq_sum = 0.0

        for row in fcst_rows:
            hour     = row['forecast_hour']
            mean     = float(row['mean_value'])
            std      = float(row['std_dev'])
            vt       = row['initialization_time'] + timedelta(hours=hour)

            obs_window = [
                obs_by_time[vt - timedelta(hours=dh)]
                for dh in range(accum_h - 1, -1, -1)
                if (vt - timedelta(hours=dh)) in obs_by_time
            ]
            if not obs_window:
                continue

            obs_rate  = sum(obs_window) / len(obs_window)
            mean_rate = mean / accum_h
            std_rate  = std  / accum_h

            is_fcst = mean_rate > threshold_rate
            is_obs  = obs_rate  > threshold_rate

            # Contingency table
            if   is_fcst and     is_obs:  hits         += 1
            elif is_fcst and not is_obs:  false_alarms += 1
            elif not is_fcst and is_obs:  misses       += 1
            else:                         correct_neg  += 1

            # Probabilistic event probability (Gaussian)
            if std_rate > 1e-10:
                p_event = float(1.0 - scipy.stats.norm.cdf(
                    threshold_rate, loc=mean_rate, scale=std_rate
                ))
            else:
                p_event = 1.0 if mean_rate > threshold_rate else 0.0

            brier_sq_sum += (p_event - float(is_obs)) ** 2

            hours_data.append({
                'hour':      hour,
                'is_fcst':   int(is_fcst),
                'is_obs':    int(is_obs),
                'p_event':   round(p_event,   4),
                'mean_rate': round(mean_rate, 4),
                'obs_rate':  round(obs_rate,  4),
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
        bs   = round(brier_sq_sum / n,   6)

        # Composite Confidence (FSS excluded — spatial-only metric)
        # Original weights: 0.40 CSI + 0.30 FSS + 0.20 POD + 0.10(1-FAR)
        # Without FSS re-normalise remaining to sum = 1 (÷ 0.70)
        if csi is not None and pod is not None and far is not None:
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

        threshold_info = {'threshold_rate': round(threshold_rate, 4), 'accum_h': accum_h, 'model': model_name}
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
                'composite_confidence':  composite,
            },
            'obs_hours':    obs_hours_list,
            'obs_warning':  obs_warning,
            'threshold_info': threshold_info,
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
    body            = request.get_json(force=True)
    model_name      = body.get('model', 'AIFS')
    variable        = body.get('variable', 'precipitation')
    min_lat         = float(body.get('min_lat', 20.0))
    max_lat         = float(body.get('max_lat', 40.0))
    min_lon         = float(body.get('min_lon', -100.0))
    max_lon         = float(body.get('max_lon', -60.0))
    hour_min        = int(body.get('hour_min', 0))
    hour_max        = int(body.get('hour_max', 168))

    is_wind = (variable == 'wind')
    if is_wind:
        fcst_var, obs_var, obs_src = 'wind_u_10m', 'wind_speed', 'ERA5_WIND'
        threshold_rate = float(body.get('threshold_ms', 10.0))
        accum_h        = 1
    else:
        fcst_var, obs_var, obs_src = variable, 'precipitation', 'GPM_IMERG_V07B'
        threshold_rate = float(body.get('threshold_mm_6h', 25.0)) / 6.0
        accum_h        = MODEL_ACCUM_HOURS.get(model_name, 1)

    conn   = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # ── 1. Fetch all forecast grid points in bbox ─────────────────────────
        cursor.execute("""
            SELECT rf.forecast_hour, rf.latitude, rf.longitude,
                   rf.mean_value, rf.std_dev, fr.initialization_time
            FROM regridded_forecast rf
            JOIN models m  ON m.model_name = rf.model_name
            JOIN forecast_runs fr
                ON fr.model_id = m.model_id
               AND fr.run_id = (
                   SELECT run_id FROM forecast_runs fr2
                   JOIN models m2 ON m2.model_id = fr2.model_id
                   WHERE m2.model_name = rf.model_name
                   ORDER BY fr2.initialization_time DESC LIMIT 1
               )
            WHERE rf.model_name    = %s
              AND rf.variable_name = %s
              AND rf.forecast_hour BETWEEN %s AND %s
              AND rf.latitude  BETWEEN %s AND %s
              AND rf.longitude BETWEEN %s AND %s
              AND rf.mean_value IS NOT NULL AND rf.std_dev IS NOT NULL
            ORDER BY rf.forecast_hour, rf.latitude, rf.longitude
        """, (model_name, fcst_var, hour_min, hour_max,
              min_lat, max_lat, min_lon, max_lon))
        fcst_rows = cursor.fetchall()

        if not fcst_rows:
            return jsonify({'error': 'No forecast data found for the selected region.'}), 404

        # ── 2. Fetch per-(lat,lon) observations for the extended time window ──
        valid_times = [
            r['initialization_time'] + timedelta(hours=r['forecast_hour'])
            for r in fcst_rows
        ]
        min_obs_t = min(valid_times) - timedelta(hours=accum_h - 1)
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
        obs_dict = {
            (round(float(r['latitude']), 2), round(float(r['longitude']), 2), r['obs_time']): float(r['obs_val'])
            for r in cursor.fetchall()
        }

        if not obs_dict:
            return jsonify({
                'hours': [], 'summary': {}, 'obs_hours': [],
                'obs_warning': 'No observations found for this region.',
            })

        # ── 3. Group forecast rows by hour and process ────────────────────────
        from collections import defaultdict
        hours_dict = defaultdict(list)
        for row in fcst_rows:
            hours_dict[row['forecast_hour']].append(row)

        hours_data = []
        total_hits = total_misses = total_fa = total_cn = 0
        total_brier_sum = 0.0
        total_n = 0
        obs_hours_set = set()

        for hour in sorted(hours_dict.keys()):
            h_hits = h_misses = h_fa = h_cn = 0
            h_brier_sum = 0.0
            h_fcst_binary = []
            h_obs_binary  = []
            h_n_pts = 0

            for row in hours_dict[hour]:
                lat_k   = round(float(row['latitude']),  2)
                lon_k   = round(float(row['longitude']), 2)
                mean    = float(row['mean_value'])
                std     = float(row['std_dev'])
                vt      = row['initialization_time'] + timedelta(hours=hour)

                obs_window = [
                    obs_dict[(lat_k, lon_k, vt - timedelta(hours=dh))]
                    for dh in range(accum_h - 1, -1, -1)
                    if (lat_k, lon_k, vt - timedelta(hours=dh)) in obs_dict
                ]
                if not obs_window:
                    continue

                obs_rate  = sum(obs_window) / len(obs_window)
                mean_rate = mean / accum_h
                std_rate  = std  / accum_h

                is_fcst = mean_rate > threshold_rate
                is_obs  = obs_rate  > threshold_rate

                if   is_fcst and     is_obs:  h_hits    += 1
                elif is_fcst and not is_obs:  h_fa      += 1
                elif not is_fcst and is_obs:  h_misses  += 1
                else:                         h_cn      += 1

                if std_rate > 1e-10:
                    p_event = float(1.0 - scipy.stats.norm.cdf(
                        threshold_rate, loc=mean_rate, scale=std_rate
                    ))
                else:
                    p_event = 1.0 if mean_rate > threshold_rate else 0.0

                h_brier_sum += (p_event - float(is_obs)) ** 2
                h_fcst_binary.append(float(is_fcst))
                h_obs_binary.append(float(is_obs))
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
            h_bs  = round(h_brier_sum / h_n_pts, 6)

            # FSS
            fcst_frac = sum(h_fcst_binary) / h_n_pts
            obs_frac  = sum(h_obs_binary)  / h_n_pts
            mse_f   = (fcst_frac - obs_frac) ** 2
            mse_ref = 0.5 * (fcst_frac**2 + obs_frac**2)
            fss_hour = round(1.0 - mse_f / mse_ref, 4) if mse_ref > 1e-10 else 1.0

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

        # ── 4. Summary statistics ─────────────────────────────────────────────
        n_obs_yes   = total_hits + total_misses
        n_fcst_yes  = total_hits + total_fa
        n_denom_csi = total_hits + total_misses + total_fa

        pod = round(total_hits / n_obs_yes,    4) if n_obs_yes   > 0 else None
        far = round(total_fa   / n_fcst_yes,   4) if n_fcst_yes  > 0 else None
        fbi = round(n_fcst_yes / n_obs_yes,    4) if n_obs_yes   > 0 else None
        csi = round(total_hits / n_denom_csi,  4) if n_denom_csi > 0 else None
        bs  = round(total_brier_sum / total_n, 6) if total_n     > 0 else None

        valid_fss_vals = [h['fss'] for h in hours_data if h.get('fss') is not None]
        mean_fss = round(sum(valid_fss_vals) / len(valid_fss_vals), 4) if valid_fss_vals else None

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
            'threshold_info': {
                **(({'threshold_ms': threshold_rate, 'unit': 'm/s'})
                   if is_wind else
                   ({'threshold_mm_6h': round(threshold_rate * 6, 2), 'unit': 'mm/6h'})),
                'threshold_rate': round(threshold_rate, 4),
                'accum_h':        accum_h,
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