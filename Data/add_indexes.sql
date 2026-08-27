-- Run once against the weave_weather database to add missing indexes.
-- Each CREATE INDEX is CONCURRENT-safe (no table lock on Postgres 9.5+).

-- forecast_data: observation time-range + spatial queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_forecast_data_run_var_latlon
    ON forecast_data(run_id, variable_id, latitude, longitude);

-- observation_data: time + spatial lookups. These served the SSR / correlation
-- paths, which now read regridded_observation instead, so the index no longer
-- has a query behind it. Kept because the table is kept (see schema.sql) and a
-- fresh install should not silently differ from the loaded database.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_observation_data_time_latlon
    ON observation_data(obs_time, latitude, longitude);

-- The two idx_rgf_* indexes on `regridded_forecast` were removed from this file
-- along with the table's CREATE (see schema.sql). An existing database still
-- holds both the table and the indexes, and should: `main` and the WEAVE_v2 /
-- WEAVE_presentation copies still query it. This file only stops a NEW install
-- from creating what nothing on this branch reads.
-- The replacement tables are indexed by `regrid_members.py`'s own INDEXES block,
-- which runs every time the script does, so nothing is needed for them here.

-- regridded_observation: time + spatial + source lookups
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_regridded_obs_src_time_latlon
    ON regridded_observation(source, variable_name, obs_time, latitude, longitude);

-- forecast_runs: foreign key + latest-run ORDER BY queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_forecast_runs_model_time
    ON forecast_runs(model_id, initialization_time DESC);
