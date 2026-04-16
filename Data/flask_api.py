from flask import Flask, jsonify, request
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import math

app = Flask(__name__)
CORS(app)

DB_CONFIG = {
    'dbname': 'weather_forecasts',
    'user': 's.dey',
    'password': '',
    'host': 'localhost',
    'port': 5432
}

import psycopg2.pool

connection_pool = psycopg2.pool.SimpleConnectionPool(
    1, 10,
    **DB_CONFIG
)


def get_db_connection():
    return connection_pool.getconn()


def return_db_connection(conn):
    connection_pool.putconn(conn)


def get_model_run_id(cursor, model_name):
    cursor.execute("""
        SELECT fr.run_id 
        FROM forecast_runs fr
        JOIN models m ON fr.model_id = m.model_id
        WHERE m.model_name = %s
        ORDER BY fr.initialization_time DESC
        LIMIT 1
    """, (model_name,))
    result = cursor.fetchone()
    return result['run_id'] if result else None


@app.route('/api/forecast-data', methods=['GET'])
def get_forecast_data():
    model_name    = request.args.get('model', 'AIFS')
    variable_name = request.args.get('variable', 'precipitation')
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
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        return_db_connection(conn)


@app.route('/api/wind-data', methods=['GET'])
def get_wind_data():
    model_name    = request.args.get('model', 'AIFS')
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
        return jsonify({'error': str(e)}), 500
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
    lat        = float(request.args.get('lat'))
    lon        = float(request.args.get('lon'))
    radius     = float(request.args.get('radius', 0.5))  # degrees search radius

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

        rows   = cursor.fetchall()
        result = []
        for row in rows:
            result.append({
                'hour': row['forecast_hour'],
                'mean': round(float(row['mean_val'] or 0), 4),
                'std':  round(float(row['std_val']  or 0), 4),
                'min':  round(float(row['min_val']  or 0), 4),
                'max':  round(float(row['max_val']  or 0), 4),
                'p10':  round(float(row['p10']       or 0), 4),
                'p25':  round(float(row['p25']       or 0), 4),
                'p75':  round(float(row['p75']       or 0), 4),
                'p90':  round(float(row['p90']       or 0), 4),
            })

        print(f"✅ Timeseries: {len(result)} hours for {model_name} at ({lat}, {lon})")
        return jsonify(result)

    except Exception as e:
        print(f"❌ Error in point-timeseries: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        return_db_connection(conn)
# ─────────────────────────────────────────────────────────────────────────────


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


if __name__ == '__main__':
    print("🚀 Flask API Starting...")
    print("=" * 60)
    print("📍 http://localhost:5000")
    print("=" * 60)
    print("Available endpoints:")
    print("  • GET /api/forecast-data?model=AIFS&variable=precipitation&hour=6&member=mean")
    print("  • GET /api/wind-data?model=GEFS&hour=12&member=0")
    print("  • GET /api/point-timeseries?model=AIFS&variable=precipitation&lat=35.0&lon=-75.0")
    print("  • GET /api/models")
    print("  • GET /api/variables")
    print("  • GET /api/health")
    print("=" * 60)
    print("✅ Optimized with connection pooling")
    print("🌬️  Wind: speed = √(u² + v²), direction = atan2(u,v)")
    print("📊 Cone of Uncertainty: mean, std, min, max, p10/p25/p75/p90 per hour")
    print("=" * 60)

    app.run(debug=True, host='0.0.0.0', port=5000)