# Design plan — more data, and selecting it

Written 2026-08-14. Today WEAVE serves **one forecast run**: 2025-09-08 00Z, three
models, two variables. Nothing in the UI lets you choose otherwise, because there
is nothing to choose. This is the plan for making run selection real.

It is deliberately a design document rather than a task list: the schema decision
in Phase 1 constrains everything after it, and getting it wrong is expensive.

---

## The core problem

**`regridded_forecast_ens` and `regridded_forecast_member` have no initialisation
time column.** They carry `model_name, variable_name, forecast_hour, lat, lon` and
nothing else. Today that is unambiguous because only one run exists. Add a second
and every row becomes undecidable.

Worse, the API already papers over it: `_fetch_fcst_obs_pairs_spatial` resolves
valid time by looking up **the latest run in `forecast_runs`** and adding
`forecast_hour`. With one run that is correct. With two it silently attributes
every regridded row to the newest initialisation, and every score becomes wrong
without any error.

**This is the single blocking issue.** Nothing else in this document matters until
it is fixed, and it must be fixed *before* a second run is loaded, not after.

## Phase 1 — Schema

Add `init_time TIMESTAMP NOT NULL` to both regridded tables, and to the
observation tables if they do not already key on absolute time (they do —
`obs_time` is absolute, which is why observations were never affected).

```sql
ALTER TABLE regridded_forecast_ens    ADD COLUMN init_time TIMESTAMP;
ALTER TABLE regridded_forecast_member ADD COLUMN init_time TIMESTAMP;
UPDATE regridded_forecast_ens    SET init_time = '2025-09-08 00:00:00';
UPDATE regridded_forecast_member SET init_time = '2025-09-08 00:00:00';
ALTER TABLE regridded_forecast_ens    ALTER COLUMN init_time SET NOT NULL;
ALTER TABLE regridded_forecast_member ALTER COLUMN init_time SET NOT NULL;
```

Then the indexes, which matter at this size — `regridded_forecast_member` is
already 6.5 GB for one run:

```sql
CREATE INDEX idx_rfe_run ON regridded_forecast_ens
  (model_name, variable_name, init_time, forecast_hour, latitude, longitude);
CREATE INDEX idx_rfm_run ON regridded_forecast_member
  (model_name, variable_name, init_time, forecast_hour, latitude, longitude);
```

**Partition by `init_time`** if more than a handful of runs is the goal. Range
partitioning on init_time keeps queries touching one partition and makes dropping
an old run instant rather than a 6 GB delete.

Also add a **run registry** — one row per (model, init_time) with the load
timestamp, the member count, the forecast-hour range, and the export convention
that produced it. That last field retires the standing hazard in
`METRICS_AUDIT.md` finding 16: `SCALED_EXPORT_DIVISOR_HOURS` becomes a per-run
fact read from the database rather than a constant in code that goes stale
silently. `/api/health`'s convention check becomes a per-run assertion.

## Phase 2 — Backend

Every query that touches a regridded table gains an `init_time` filter. The
places to change are the ones already inventoried in `METRICS_AUDIT.md` finding
17 — the same list, since they are the paths that read forecasts:

- `_fetch_fcst_obs_pairs_spatial`
- `/api/compare/skill`, `/api/compare/timeseries`, `/api/compare/categorical`
- `/api/categorical-metrics`, the region categorical path
- `/api/spread-skill`, `_compute_correlation_points`, `_compute_ssr_points`
- `/api/forecast-data`, `/api/wind-data`, `/api/point-timeseries`

**Delete `get_model_run_id`'s "latest run" behaviour** rather than defaulting it.
A default is how this becomes wrong quietly. Make `init_time` a required
parameter, and return `400` when it is absent — an explicit failure the first time
someone forgets is far cheaper than a plausible wrong number.

New endpoint:

```
GET /api/runs  ->  [{model, init_time, hours: [...], members, variables: [...]}]
```

The UI needs this to populate its selectors, and it is also the honest answer to
"what data do you have?", which nothing currently answers.

## Phase 3 — Frontend

A **run selector** in the header, beside the existing model/variable/lead-time
controls: initialisation date, then time (00Z / 06Z / 12Z / 18Z). Populated from
`/api/runs`, not hard-coded.

Decisions to make deliberately:

- **Does the run apply globally or per tab?** Global is simpler and matches how
  the model selector already behaves. But the Comparison tab may eventually want
  *the same model from two different runs* — comparing 00Z against 12Z is a real
  and useful question. Design the state so that is possible later even if the
  first version is global.
- **What happens on switch?** Lead time should persist where valid and clamp where
  not. Drawn regions and points should survive. Computed results must be
  invalidated — a stale map from another run is exactly the kind of quiet error
  this project has spent a lot of effort removing.
- **What if a model is missing from a run?** Grey it out with the reason, rather
  than silently returning nothing.

## Phase 4 — Ingest

The current pipeline is manual and partly off-machine, which is why the export
conventions were so hard to reconstruct. Any expansion should make ingest
**scripted, idempotent, and self-describing**:

1. Download → subset → regrid → load, each step re-runnable without duplicating
   rows (`ON CONFLICT` on the natural key, which now includes `init_time`).
2. Record the export convention in the run registry **at load time**. Never infer
   it later — that inference cost days.
3. Fail loudly on an unknown convention rather than assuming the previous one.
4. Keep `Data_convert_weave/"aifs react.py"`'s fixed per-record-window behaviour,
   and set the registry's convention field accordingly so old and new runs can
   coexist with different divisors.

## Phase 5 — Scale

Rough arithmetic before committing: one run is ~6.5 GB of members plus ~250 MB of
ensemble statistics, for **two variables and three models**. Ten runs is ~65 GB,
which is fine on disk and slow without partitioning.

Decide up front:

- **Retention** — how many runs stay hot? A rolling window with older runs dropped
  or archived is easier than discovering the limit at 200 GB.
- **Do members need to be kept for every run?** They exist to give a true ensemble
  spread and exact per-member differencing. A cheaper option is to keep members
  for recent runs and only `regridded_forecast_ens` for older ones, accepting
  approximate spread on the archive — but that must be visible in the UI, not
  silent.
- **Verification needs observations to cover the forecast range.** The current run
  has truth for ~19.5 h of a 240 h forecast. More runs are only worth loading if
  the observation record grows with them.

---

## Order, and the one rule

1. Schema + run registry (Phase 1)
2. Backend `init_time` threading, with **no default** (Phase 2)
3. `/api/runs` and the selector (Phase 3)
4. Scripted ingest (Phase 4)
5. Load a second run — **only now**

**Do not load a second run before Phase 2 is done.** With the current
"latest run wins" resolution, a second initialisation makes every existing score
wrong in a way that looks entirely plausible and would take another audit to find.
