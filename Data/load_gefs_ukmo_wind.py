import argparse
import json
import os
import sys
import psycopg2
from psycopg2.extras import execute_batch
from pathlib import Path
import re


# ── Database ──────────────────────────────────────────────────────────────────
# Env-driven, defaulting to the live database, exactly as `flask_api.py` and
# `load_cyclone_tracks.py` do. This block used to be a literal
# `{'dbname': 'weather_forecasts', 'user': 's.dey', ...}` inside `__main__` —
# a database that does not exist on this machine and a user who is not the
# current one, so `python load_gefs_ukmo_wind.py` as `DEPLOY.md` printed it failed on connect
# before reading a file (`NEXT_STEPS.md` §45).
DB_CONFIG = {
    'dbname':   os.environ.get('DB_NAME',     'weave_weather'),
    'user':     os.environ.get('DB_USER',     'k.aggarwal'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'host':     os.environ.get('DB_HOST',     'localhost'),
    'port':     int(os.environ.get('DB_PORT', 5432)),
}


class WeatherDataLoader:
    """Load weather forecast JSON data into PostgreSQL"""

    def __init__(self, db_config):
        self.conn = psycopg2.connect(**db_config)
        self.cursor = self.conn.cursor()
        print("✅ Connected to PostgreSQL database")

    def get_model_id(self, model_name):
        self.cursor.execute(
            "SELECT model_id FROM models WHERE model_name = %s",
            (model_name,)
        )
        result = self.cursor.fetchone()
        return result[0] if result else None

    def get_variable_id(self, variable_name):
        self.cursor.execute(
            "SELECT variable_id FROM variables WHERE variable_name = %s",
            (variable_name,)
        )
        result = self.cursor.fetchone()
        return result[0] if result else None

    def create_forecast_run(self, model_name, init_time):
        model_id = self.get_model_id(model_name)

        self.cursor.execute("""
            INSERT INTO forecast_runs (model_id, initialization_time)
            VALUES (%s, %s)
            ON CONFLICT (model_id, initialization_time) 
            DO UPDATE SET model_id = EXCLUDED.model_id
            RETURNING run_id
        """, (model_id, init_time))

        self.conn.commit()
        return self.cursor.fetchone()[0]

    def extract_metadata_from_filename(self, filename):
        hour_match = re.search(r'-(\d+)h-', filename)
        forecast_hour = int(hour_match.group(1)) if hour_match else 0

        member_match = re.search(r'_member_(\d+)\.json', filename)
        if member_match:
            member_num = int(member_match.group(1))
            file_type = 'member'
        elif '_mean.json' in filename:
            member_num = None
            file_type = 'mean'
        elif '_std.json' in filename:
            member_num = None
            file_type = 'std'
        else:
            member_num = None
            file_type = 'deterministic'

        return forecast_hour, member_num, file_type

    def load_json_file(self, json_path, model_name, init_time, variable_name='precipitation'):
        filename = Path(json_path).name
        forecast_hour, member_num, file_type = self.extract_metadata_from_filename(filename)

        run_id = self.create_forecast_run(model_name, init_time)
        variable_id = self.get_variable_id(variable_name)

        with open(json_path, 'r') as f:
            data = json.load(f)

        if len(data) == 0:
            return 0

        if file_type in ['member', 'deterministic']:
            insert_data = [
                (run_id, variable_id, forecast_hour, member_num,
                 point['lat'], point['lon'], point['value'])
                for point in data
            ]

            execute_batch(self.cursor, """
                INSERT INTO forecast_data 
                (run_id, variable_id, forecast_hour, ensemble_member, latitude, longitude, value)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, insert_data, page_size=1000)

        elif file_type == 'mean':
            insert_data = [
                (run_id, variable_id, forecast_hour,
                 point['lat'], point['lon'], point['value'])
                for point in data
            ]

            execute_batch(self.cursor, """
                INSERT INTO ensemble_statistics 
                (run_id, variable_id, forecast_hour, latitude, longitude, mean_value)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, insert_data, page_size=1000)

        elif file_type == 'std':
            update_data = [
                (point['value'], run_id, variable_id, forecast_hour,
                 point['lat'], point['lon'])
                for point in data
            ]

            execute_batch(self.cursor, """
                UPDATE ensemble_statistics
                SET std_dev = %s
                WHERE run_id = %s AND variable_id = %s AND forecast_hour = %s
                  AND latitude = %s AND longitude = %s
            """, update_data, page_size=1000)

        self.conn.commit()
        return len(data)

    def load_all_files_for_model(self, folder_path, model_name, init_time, variable_name='precipitation'):
        folder = Path(folder_path)
        print(f"🔍 Looking in: {folder.absolute()}")
        print(f"   Folder exists: {folder.exists()}")

        json_files = sorted(list(folder.glob('*.json')))
        print(f"   Files found: {len(json_files)}")

        if not json_files:
            print(f"⚠️ No JSON files found in {folder_path}")
            return 0

        print(f"\n{'=' * 70}")
        print(f"Loading {model_name} {variable_name} - {len(json_files)} files")
        print(f"{'=' * 70}\n")

        total_points = 0
        files_loaded = 0

        for json_file in json_files:
            try:
                points = self.load_json_file(str(json_file), model_name, init_time, variable_name)
                total_points += points
                files_loaded += 1

                if files_loaded % 200 == 0:
                    print(f"  {files_loaded}/{len(json_files)} files, {total_points:,} points...")
            except Exception as e:
                print(f"  ❌ {json_file.name}: {str(e)}")

        print(f"\n✅ {model_name} {variable_name}: {files_loaded} files, {total_points:,} points")
        return total_points

    def get_database_stats(self):
        print(f"\n{'=' * 70}")
        print("DATABASE STATISTICS")
        print(f"{'=' * 70}\n")

        self.cursor.execute("SELECT COUNT(*) FROM forecast_data")
        print(f"Total forecast_data rows: {self.cursor.fetchone()[0]:,}")

        self.cursor.execute("SELECT COUNT(*) FROM ensemble_statistics")
        print(f"Total ensemble_statistics rows: {self.cursor.fetchone()[0]:,}")

    def close(self):
        self.cursor.close()
        self.conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description='Load converted wind JSON for ONE model, ONE run, ONE component.')
    ap.add_argument('--source', required=True,
                    help='directory of converted JSON for one wind component')
    ap.add_argument('--model', required=True, choices=['AIFS', 'GEFS', 'UKMO'])
    ap.add_argument('--init-time', required=True,
                    help='initialisation time, "YYYY-MM-DD HH:MM:SS"')
    # One component per invocation, deliberately. u and v live in separate
    # directories and are separate rows; a flag that loaded "both" would have to
    # guess the second path from the first.
    ap.add_argument('--variable', required=True,
                    choices=['wind_u_10m', 'wind_v_10m'])
    args = ap.parse_args()

    if not os.path.isdir(args.source):
        sys.exit(f'not a directory: {args.source}')

    loader = WeatherDataLoader(DB_CONFIG)
    try:
        loader.load_all_files_for_model(
            folder_path=args.source, model_name=args.model,
            init_time=args.init_time, variable_name=args.variable)
        loader.get_database_stats()
        print('\n\u2705 loaded')
    finally:
        loader.close() if hasattr(loader, 'close') else None
