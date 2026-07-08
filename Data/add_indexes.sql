-- Run once against the weave_weather database to add missing indexes.
-- Each CREATE INDEX is CONCURRENT-safe (no table lock on Postgres 9.5+).

-- forecast_data: observation time-range + spatial queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_forecast_data_run_var_latlon
    ON forecast_data(run_id, variable_id, latitude, longitude);

-- observation_data: time + spatial lookups used by SSR / correlation
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_observation_data_time_latlon
    ON observation_data(obs_time, latitude, longitude);

-- regridded_forecast: run_id is now used directly (correlated subquery removed)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_regridded_forecast_run_var_hour
    ON regridded_forecast(run_id, variable_name, forecast_hour);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_regridded_forecast_run_latlon
    ON regridded_forecast(run_id, latitude, longitude);

-- regridded_observation: time + spatial + source lookups
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_regridded_obs_src_time_latlon
    ON regridded_observation(source, variable_name, obs_time, latitude, longitude);

-- forecast_runs: foreign key + latest-run ORDER BY queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_forecast_runs_model_time
    ON forecast_runs(model_id, initialization_time DESC);
