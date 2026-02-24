import json
import psycopg2
from psycopg2.extras import execute_batch
from pathlib import Path
import re


class WeatherDataLoader:
    """Load weather forecast JSON data into PostgreSQL"""
    
    def __init__(self, db_config):
        self.conn = psycopg2.connect(**db_config)
        self.cursor = self.conn.cursor()
        print("✅ Connected to PostgreSQL database")
    
    def get_model_id(self, model_name):
        """Get model_id from model name"""
        self.cursor.execute(
            "SELECT model_id FROM models WHERE model_name = %s",
            (model_name,)
        )
        result = self.cursor.fetchone()
        return result[0] if result else None
    
    def get_variable_id(self, variable_name):
        """Get variable_id from variable name"""
        self.cursor.execute(
            "SELECT variable_id FROM variables WHERE variable_name = %s",
            (variable_name,)
        )
        result = self.cursor.fetchone()
        return result[0] if result else None
    
    def create_forecast_run(self, model_name, init_time):
        """Create or get forecast run ID"""
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
        """Extract forecast metadata from filename"""
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
        """Load a single JSON file into database"""
        
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
    
    def load_all_files_for_model(self, folder_path, model_name, init_time):
        """Load all JSON files for a model/run"""
        
        folder = Path(folder_path)
        json_files = sorted(list(folder.glob('*.json')))
        
        if not json_files:
            print(f"⚠️ No JSON files found in {folder_path}")
            return 0
        
        print(f"\n{'='*70}")
        print(f"Loading {model_name} - {len(json_files)} files")
        print(f"{'='*70}\n")
        
        total_points = 0
        files_loaded = 0
        
        for json_file in json_files:
            try:
                points = self.load_json_file(str(json_file), model_name, init_time)
                total_points += points
                files_loaded += 1
                
                if files_loaded % 100 == 0:
                    print(f"  {files_loaded}/{len(json_files)} files, {total_points:,} points...")
            except Exception as e:
                print(f"  ❌ {json_file.name}: {str(e)}")
        
        print(f"\n✅ {model_name}: {files_loaded} files, {total_points:,} points")
        return total_points
    
    def get_database_stats(self):
        """Print database statistics"""
        print(f"\n{'='*70}")
        print("DATABASE STATISTICS")
        print(f"{'='*70}\n")
        
        self.cursor.execute("SELECT COUNT(*) FROM forecast_data")
        print(f"Total forecast_data rows: {self.cursor.fetchone()[0]:,}")
        
        self.cursor.execute("SELECT COUNT(*) FROM ensemble_statistics")
        print(f"Total ensemble_statistics rows: {self.cursor.fetchone()[0]:,}")
    
    def close(self):
        self.cursor.close()
        self.conn.close()


if __name__ == "__main__":
    
    db_config = {
        'dbname': 'weather_forecasts',
        'user': 's.dey',
        'password': '',
        'host': 'localhost',
        'port': 5432
    }
    
    loader = WeatherDataLoader(db_config)
    
    try:
        loader.load_all_files_for_model(
            folder_path='./json_data_aifs_ensemble_scaled',
            model_name='AIFS',
            init_time='2025-09-08 00:00:00'
        )
        
        loader.load_all_files_for_model(
            folder_path='./json_data_gefs_ensemble_scaled',
            model_name='GEFS',
            init_time='2025-09-08 00:00:00'
        )
        
        loader.load_all_files_for_model(
            folder_path='./json_data_ukmo_ensemble',
            model_name='UKMO',
            init_time='2025-09-08 00:00:00'
        )
        
        loader.get_database_stats()
        
        print("\n✅ ALL DATA LOADED!")
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
    finally:
        loader.close()