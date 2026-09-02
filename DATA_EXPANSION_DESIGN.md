# Design plan — more data, and selecting it

Written 2026-08-14. **Status updated 2026-09-02: phases 1 and 2 are done, and the
blocking issue below is closed.** WEAVE still serves one forecast run
(2025-09-08 00Z, three models, two variables), but it no longer *assumes* it.

| phase | state |
|---|---|
| 1. Schema + run registry | **done** — `Data/migrate_init_time.py`, applied |
| 2. Backend `init_time`, no silent default | **done** — with one deliberate change, below |
| 3. `/api/runs` and the selector | **endpoint done**, selector not built |
| 4. Scripted ingest | **blocked** — `observation_data` has no loader in this repo |
| 5. Scale / retention | undecided |

It is deliberately a design document rather than a task list: the schema decision
in Phase 1 constrains everything after it, and getting it wrong is expensive.
Phases 1–2 below are kept as written, with what actually happened recorded
against them — the plan and the outcome differ in three places worth knowing.

---

## The core problem — CLOSED 2026-09-02

> **This section describes the state before the migration.** It is kept because
> the reasoning still explains why the schema looks the way it does, and because
> the failure it describes is the one every later safeguard is aimed at.
>
> What closed it: `init_time NOT NULL` on both regridded tables (phase 1), and
> every query filtering on it (phase 2). `_fetch_fcst_obs_pairs_spatial`'s
> "latest run" lookup is gone — and note it took **two** passes to remove,
> because it had a second inline copy that the first pass missed and that
> silently answered from the newest run for a caller who had asked for another.

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

## Phase 1 — Schema — DONE 2026-09-02

Run `Data/migrate_init_time.py` (idempotent; `--dry-run` and `--rollback` both
work). Applied to `weave_weather`: 42,550,480 member rows and 1,497,294 ens rows
all carry `2025-09-08 00:00:00`, NOT NULL, no default; `forecast_run_registry`
holds 9 rows with the right member counts (50/30/18) and hour ranges.

**Two departures from the recipe below, both deliberate.**

*The ALTER.* This document's sequence — add nullable, `UPDATE`, `SET NOT NULL` —
rewrites every row. On the 6.5 GB member table that is minutes of work and
roughly doubles the on-disk size until a `VACUUM FULL`. Since PostgreSQL 11,
`ADD COLUMN NOT NULL DEFAULT <constant>` is **catalogue-only**: the value is
stored once in `pg_attribute.attmissingval` and materialised on read. So the
script does that and then drops the default, which is instant at any size. The
2m17s it took was building the two 42M-row indexes, not touching the column.

Dropping the default is not cosmetic — it leaves the backfilled rows alone while
making the column mandatory for new inserts, so `regrid_members.py` has to state
which run it is writing. A default left in place would move the silent
mis-attribution out of the query layer and into the schema.

*Models with different init times.* Not handled. A single `ADD COLUMN DEFAULT`
cannot give them different values, and the per-model backfill that needs is a
path the loaded data cannot exercise, so the script exits with the manual recipe
rather than shipping untested logic. It also refuses outright if `forecast_runs`
already holds more than one run, since the backfill's assumption would then be
false and unrecoverable — which is the entire reason this had to come first.

The original recipe follows.

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

## Phase 2 — Backend — DONE 2026-09-02

Ten query sites filter on the run, and the frontend names it on every request.
`test_run_scoping.py` reads the SQL to assert none is missed — deliberately, since
with one run loaded a filtered and an unfiltered query return identical rows, so
no behavioural test can tell them apart. It found two sites that had been missed.

**Three places needed more than a `WHERE` clause**, none of them in the list
below:

- **The wind self-join.** `_fcst_speed_sql` joins the ens table to itself to pair
  u with v. A caller's filter constrains `u` only, so the join needs
  `v.init_time = u.init_time` or a second run composes a speed from two
  different forecasts — and the caller's own filter would not catch it.
- **The comparison endpoints** select `model_name = ANY(...)`, and models need
  not share an init time, so one `init_time = %s` is wrong for all but one of
  them. `_run_pairs_sql` emits a tuple-membership test over two unnested arrays.
  Model agreement is only meaningful between the same forecast; pairing one
  model's rows with another's initialisation reports disagreement that is really
  a difference in start time.
- **`_check_export_convention`** pooled ratios across runs. The convention is a
  property of a *run* — which is why the registry records `export_divisor_h` per
  (model, variable, init_time) — so two runs exported differently would average
  into a number matching neither.

**The one deliberate change to this phase's rule.** This document says to make
`init_time` required and return 400 whenever it is absent. What shipped refuses
only when the request is **ambiguous**: it resolves the sole run when there is
one, and raises when there are several.

The reason a default is dangerous is ambiguity — "the latest run" silently picks
one of many. With one run there is nothing to pick between, so defaulting states
a fact rather than guessing, and refusing would break every existing caller (and
600-odd tests) to prevent an error that cannot occur. Gating on ambiguity makes
the API strict at exactly the moment strictness starts to matter: load a second
run and every un-updated caller fails loudly, with a message naming `/api/runs`,
instead of receiving a plausible wrong number. The frontend sends the parameter
regardless, so it is already correct for the two-run case rather than relying on
the fallback.

If you want the blanket rule instead, it is the `len(rows) > 1` test in
`_resolve_init_time`.

**One trap this turned up**, worth more than the fix: the endpoints all wrap
their bodies in `except Exception -> 500`, which swallowed the 400 and reported a
request error as a server fault. All 19 now re-raise `RunSelectionError`
explicitly. A helper that raises for the caller's benefit has to survive the
caller's error handling.

The original list of places to change follows; it was accurate but not complete.

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

1. ~~Schema + run registry (Phase 1)~~ **done 2026-09-02**
2. ~~Backend `init_time` threading, with no silent default (Phase 2)~~ **done
   2026-09-02** — plus the frontend naming the run on every request
3. `/api/runs` **done**; the selector is not built, and has no user-visible value
   until a second run exists
4. Scripted ingest (Phase 4) — **the remaining blocker**
5. Load a second run

~~**Do not load a second run before Phase 2 is done.**~~ **Phase 2 is done, so
this rule has been retired.** The hazard it named is gone: a second
initialisation now returns one run's rows per query rather than a blend, and any
caller that does not say which run it means gets a 400 naming `/api/runs` instead
of a plausible wrong number.

**What now blocks a second run is Phase 4, not correctness.** Two things, in
order of how hard they are:

- **`observation_data` has no loader in this repository.** The native point
  observations were ingested off-repo, and nothing in the tree writes that table
  (`fixture_db.py` seeds a synthetic copy for tests, and that is all). A second
  run's forecasts can be loaded and regridded today; without observations over
  its valid times, nothing about it can be *verified*. `regrid_observations.py`
  coarsens `observation_data` onto the analysis grid, so the missing piece is
  specifically the ingest above it — the IMERG and ERA5 downloads and whatever
  converted them. Those source files are not on the development machine either.
- **Everything else in Phase 4** — idempotent re-runnable steps, the convention
  recorded at load time. `forecast_run_registry.export_divisor_h` already exists
  for that last part; it is populated from `SCALED_EXPORT_DIVISOR_HOURS` today
  and should be written by the loader instead.

Two smaller things to do when a second run actually arrives, both already
flagged where they live:

- **`migrate_init_time.py` refuses to backfill** once more than one run is in
  `forecast_runs`. That is correct for a first migration and useless afterwards;
  a second run must arrive with its `init_time` written by the loader, not
  backfilled.
- **`src/api/run.js` resolves the run once and caches it in module state.** A
  real selector must move that into React state — mutable module state would let
  a request issued before a switch resolve after it and paint one run's numbers
  under another run's label. The file says so at the point of definition.
