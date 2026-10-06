# Runbook — loading one forecast run

Adding **one initialisation** of **one model** to a database that already works.
This is not the install guide: `DEPLOY.md` builds an empty database from
nothing, and the steps below assume the schema, the indexes and at least one
run already exist.

`SYSTEM_DESIGN_PLAN.md` asked for this and recorded why it was missing: *"the
steps exist and are exercised; the narrative that strings them together does
not."* Writing the narrative found that two of the steps did not run as
documented — see [What this runbook broke](#what-this-runbook-broke).

Every command here was executed or `--help`-checked against the real scripts on
2026-10-06. Where a step cannot be run on this machine, it says so rather than
printing a plausible command.

---

## Before you start

| | |
|---|---|
| Environment | `conda activate afw` |
| Database | `weave_weather` on localhost; override with `DB_NAME`, `DB_USER`, `DB_HOST`, `DB_PORT`, `DB_PASSWORD` |
| Source data | Explorer, `login.explorer.northeastern.edu` (key auth; no SSH config entry needed) |
| Working directory | `Data/` for every command below |

**Decide the initialisation time first and write it down.** Every step takes it
as an argument and they must agree exactly. Four of six model/variable
combinations were once filed under the wrong run because this was assumed rather
than passed (`NEXT_STEPS.md` §24), and the symptom was not an error — it was
forecasts silently scored against truth from eight days earlier.

---

## 1. Stage the source

The NetCDF lives on Explorer. `NEXT_STEPS.md` §11 has the paths; they are not
repeated here, because a path copied into two documents is a path that will
disagree with itself.

```bash
# from the staging host, not the login node — a full ingest there gets Killed
ls /projects/<path>/<model>/<YYYYMMDD>/
```

**Do not run the converters or loaders on an Explorer login node.** They build
the whole set in memory and the cgroup limit kills them with no traceback
(`NEXT_STEPS.md` §11, "Working on Explorer at all"). Use a compute node, or
stage the files and convert locally.

---

## 2. Convert NetCDF → JSON

One converter per model. All three take `--source`, `--out`, `--variable`,
`--hours`, and a verification flag.

```bash
python convert_aifs.py  --source <netcdf dir> --out <json dir> --variable precipitation
python convert_gefs.py  --source <netcdf dir> --out <json dir> --variable precipitation
python convert_ukmo.py  --source <netcdf dir> --out <json dir> --variable precipitation
```

**Check the initialisation before converting, not after.** Each converter reads
the init time out of the file and refuses a directory whose files disagree:

```bash
python convert_aifs.py --source <netcdf dir> --verify --init-time "2025-09-16 00:00:00"
python convert_gefs.py --source <netcdf dir> --verify --verify-init-time "2025-09-16 00:00:00"
python convert_ukmo.py --source <netcdf dir> --verify --verify-init-time "2025-09-16 00:00:00"
```

Note the flag is `--init-time` for AIFS and `--verify-init-time` for the other
two. That inconsistency is real; it is not a typo here.

Wind is two separate conversions, `wind_u_10m` and `wind_v_10m`. They are
separate variables all the way through and nothing combines them until the API
computes √(u²+v²).

---

## 3. Load into the native tables

```bash
python load_to_postgres.py --source <json dir> --model AIFS --init-time "2025-09-16 00:00:00"

python load_wind.py --source <u json dir> --model AIFS \
    --init-time "2025-09-16 00:00:00" --variable wind_u_10m
python load_wind.py --source <v json dir> --model AIFS \
    --init-time "2025-09-16 00:00:00" --variable wind_v_10m
```

`load_wind.py` handles AIFS; `load_gefs_ukmo_wind.py` takes the same flags for
GEFS and UKMO. One wind component per invocation, deliberately — u and v are
separate directories, and a flag that loaded "both" would have to guess the
second path from the first.

**A re-load of the same run fails rather than doubling.** The natural-key unique
indexes (`uq_forecast_data_natural_key` and friends) make a divergent re-load
loud. That hazard has fired before, which is why they exist (§19).

Verify:

```bash
psql -d weave_weather -c "SELECT count(*) FROM forecast_data;"
```

---

## 4. Regrid onto the common 0.5° grid

**Not optional.** Every scored endpoint reads the regridded tables; the loaders
above only populate the native ones. A database that stops here has maps and
metric panels that are correctly empty and look broken.

```bash
python regrid_members.py --models AIFS --variables precipitation \
    --init-time "2025-09-16 00:00:00"
python regrid_members.py --models AIFS --variables wind_u_10m,wind_v_10m \
    --init-time "2025-09-16 00:00:00"
```

Re-running is safe: `clear_slice` deletes the (model, variable, run, hour) it is
about to write in the same transaction as the `COPY`, so a repeat does not
double (§13).

Verify the coordinates land on the grid:

```bash
python regrid_members.py --verify-grid --hours 0
```

---

## 5. Register the run

```bash
python migrate_init_time.py --dry-run    # says what it would change
python migrate_init_time.py
```

Idempotent, and safe whichever state you are in. It populates
`forecast_run_registry` — the per-run record of member counts, hour ranges and
export convention that `/api/runs` reads, and therefore that the run selector
reads. **Run it after the loaders**, not before: with no rows to attribute it
exits saying there is no run, which is correct and unhelpful.

Without it `/api/runs` still answers, from a `DISTINCT` over the ens table, but
without member counts or conventions.

---

## 6. Observations, only if the run needs them

A forecast can only be scored where truth exists. Check before loading anything:

```bash
psql -d weave_weather -c \
  "SELECT source, min(obs_time), max(obs_time) FROM observation_data GROUP BY 1;"
```

On 2026-10-06 that returns IMERG to `2025-09-26 23:30` and ERA5 to
`2025-09-26 23:00`. If the new run's valid times fall inside that, skip this
step.

```bash
python load_observations.py --imerg <granule dir> --verify   # read and report
python load_observations.py --imerg <granule dir> --load
python regrid_observations.py --table regridded_observation --truncate
```

**`regrid_observations.py` defaults to a `_rebuilt` table, not the live one**, so
`--table regridded_observation` is required and deliberate. On an existing
database run `--compare` first: the current rule is not the one that produced
the pre-2026-08-27 data and the difference is material (§7).

---

## 7. Prove the run is what it claims

**Do this every time.** Row counts, grids, member counts and lead ranges are
identical between a correct run and a mislabelled one — they told §24 nothing.

The cheap test that does work: **MAE against lead time.** A forecast scored
against its own valid times loses skill monotonically with lead; one scored
against the wrong week gives a flat curve at a higher level.

```bash
curl -s -X POST http://localhost:5000/api/compare/region-metrics \
  -H 'Content-Type: application/json' \
  -d '{"models":["AIFS"],"variable":"precipitation","metrics":["mae"],
       "init_time":"2025-09-16 00:00:00","hour_min":0,"hour_max":168}'
```

Then restart every server. A running process serves what it imported at
startup, and `cwd` tells you nothing about that — a server once served
pre-rename code for an hour while every file on disk was correct (§1).

---

## What this runbook broke

Writing it is what found these. Both were documented as working.

**The three forecast loaders would not run as `DEPLOY.md` printed them.**
`load_to_postgres.py`, `load_wind.py` and `load_gefs_ukmo_wind.py` each carried
a hardcoded `__main__` block: database `weather_forecasts`, user `s.dey`, the
source directories, and `init_time='2025-09-08 00:00:00'`. That database does
not exist on this machine, so `python Data/load_to_postgres.py` failed on
connect before reading a file. They now take `--source`, `--model`,
`--init-time` and (for wind) `--variable`, and read the same env-driven
`DB_CONFIG` as the rest of the codebase.

**`SYSTEM_DESIGN_PLAN.md` recorded that as done.** The entry reads *"Fix the
loader: config-driven, correct DB, `argparse`, parameterized `init_time` —
**DONE**"*, struck through. It was not done for these three. Corrected there.

The general point is in `NEXT_STEPS.md` §44: an item in this project is more
likely stale than open. A runbook is a good way to find out, because it is the
one document that fails if the steps do not.
