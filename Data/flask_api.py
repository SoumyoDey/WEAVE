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

# Connection pool
import psycopg2.pool

connection_pool = psycopg2.pool.SimpleConnectionPool(
    1, 10,  # min and max connections
    **DB_CONFIG
)


def get_db_connection():
    return connection_pool.getconn()


def return_db_connection(conn):
    connection_pool.putconn(conn)


def get_model_run_id(cursor, model_name):
    """Get the run_id for a specific model"""
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
    """Optimized forecast data retrieval for precipitation"""

    model_name = request.args.get('model', 'AIFS')
    variable_name = request.args.get('variable', 'precipitation')
    forecast_hour = int(request.args.get('hour', 6))
    member = request.args.get('member', 'mean')

    # Redirect wind requests to wind endpoint
    if variable_name == 'wind':
        return get_wind_data()

    conn = get_db_connection()
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

        data = cursor.fetchall()

        result = [
            {
                'lat': float(row['lat']),
                'lon': float(row['lon']),
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
    """Optimized wind data retrieval with speed and direction calculation"""

    model_name = request.args.get('model', 'AIFS')
    forecast_hour = int(request.args.get('hour', 6))
    member = request.args.get('member', 'mean')

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        run_id = get_model_run_id(cursor, model_name)

        if not run_id:
            return jsonify({'error': f'No data found for model {model_name}'}), 404

        if member == 'mean':
            cursor.execute("""
                SELECT 
                    u.latitude as lat,
                    u.longitude as lon,
                    u.mean_value as u,
                    v.mean_value as v
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
                    u.latitude as lat,
                    u.longitude as lon,
                    u.std_dev as u,
                    v.std_dev as v
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
                    u.latitude as lat,
                    u.longitude as lon,
                    u.value as u,
                    v.value as v
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

        data = cursor.fetchall()

        # Calculate wind speed and direction
        result = []
        for row in data:
            u = float(row['u']) if row['u'] else 0
            v = float(row['v']) if row['v'] else 0

            # Wind speed: sqrt(u² + v²)
            speed = math.sqrt(u * u + v * v)

            # Wind direction: atan2(v, u) converted to meteorological convention
            # Meteorological wind direction is where wind comes FROM, in degrees clockwise from North
            direction_rad = math.atan2(u, v)  # Note: reversed for met convention
            direction_deg = (direction_rad * 180 / math.pi + 180) % 360  # Convert to 0-360

            result.append({
                'lat': float(row['lat']),
                'lon': float(row['lon']),
                'u': round(u, 3),
                'v': round(v, 3),
                'speed': round(speed, 2),
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


@app.route('/api/models', methods=['GET'])
def get_models():
    """Get list of available models"""
    conn = get_db_connection()
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
    """Get list of available variables"""
    conn = get_db_connection()
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
    """Health check endpoint"""
    conn = get_db_connection()
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
    print("  • GET /api/models")
    print("  • GET /api/variables")
    print("  • GET /api/health")
    print("=" * 60)
    print("✅ Optimized with connection pooling")
    print("🌬️  Wind calculation: speed = √(u² + v²), direction = atan2(u,v)")
    print("=" * 60)

    app.run(debug=True, host='0.0.0.0', port=5000)