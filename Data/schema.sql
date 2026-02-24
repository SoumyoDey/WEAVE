-- Weather Forecast Database Schema (No PostGIS Required)
-- Optimized for ensemble precipitation data storage

-- 1. Models table
CREATE TABLE models (
    model_id SERIAL PRIMARY KEY,
    model_name VARCHAR(50) NOT NULL UNIQUE,
    ensemble_count INTEGER NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Variables table
CREATE TABLE variables (
    variable_id SERIAL PRIMARY KEY,
    variable_name VARCHAR(50) NOT NULL UNIQUE,
    units VARCHAR(20) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Forecast runs table
CREATE TABLE forecast_runs (
    run_id SERIAL PRIMARY KEY,
    model_id INTEGER REFERENCES models(model_id),
    initialization_time TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(model_id, initialization_time)
);

-- 4. Main forecast data table
CREATE TABLE forecast_data (
    data_id BIGSERIAL PRIMARY KEY,
    run_id INTEGER REFERENCES forecast_runs(run_id),
    variable_id INTEGER REFERENCES variables(variable_id),
    forecast_hour INTEGER NOT NULL,
    ensemble_member INTEGER,
    latitude FLOAT NOT NULL,
    longitude FLOAT NOT NULL,
    value FLOAT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for fast queries
CREATE INDEX idx_forecast_data_lat_lon ON forecast_data(latitude, longitude);
CREATE INDEX idx_forecast_data_run_var_hour ON forecast_data(run_id, variable_id, forecast_hour);
CREATE INDEX idx_forecast_data_run_var_hour_member ON forecast_data(run_id, variable_id, forecast_hour, ensemble_member);

-- 5. Precomputed ensemble statistics table
CREATE TABLE ensemble_statistics (
    stat_id BIGSERIAL PRIMARY KEY,
    run_id INTEGER REFERENCES forecast_runs(run_id),
    variable_id INTEGER REFERENCES variables(variable_id),
    forecast_hour INTEGER NOT NULL,
    latitude FLOAT NOT NULL,
    longitude FLOAT NOT NULL,
    mean_value FLOAT,
    std_dev FLOAT,
    min_value FLOAT,
    max_value FLOAT,
    percentile_25 FLOAT,
    percentile_50 FLOAT,
    percentile_75 FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX idx_ensemble_stats_lat_lon ON ensemble_statistics(latitude, longitude);
CREATE INDEX idx_ensemble_stats_run_var_hour ON ensemble_statistics(run_id, variable_id, forecast_hour);

-- 6. Insert initial model metadata
INSERT INTO models (model_name, ensemble_count, description) VALUES
    ('AIFS', 50, 'AI Forecasting System - ECMWF'),
    ('GEFS', 30, 'Global Ensemble Forecast System - NOAA'),
    ('UKMO', 18, 'UK Met Office Global Ensemble');

-- 7. Insert initial variable metadata
INSERT INTO variables (variable_name, units, description) VALUES
    ('precipitation', 'mm/hr', 'Total precipitation rate'),
    ('temperature_2m', 'K', '2-meter temperature'),
    ('wind_u_10m', 'm/s', '10-meter u-component of wind'),
    ('wind_v_10m', 'm/s', '10-meter v-component of wind'),
    ('pressure_msl', 'Pa', 'Mean sea level pressure');

-- Verify tables created
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'public' 
ORDER BY table_name;
