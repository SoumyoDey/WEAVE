# WEAVE — Deployment Guide (beta)

Architecture: a **React single-page app** (static build) talking to a **Flask JSON API**, which reads from a **PostgreSQL** database of forecast/observation data.

```
[ browser ] → static build (CDN / static host) ─HTTP→ Flask API (gunicorn) → PostgreSQL
```

**Deploying the password-protected reviewer beta?** Both prerequisites are now
handled in this guide and in the repo: §4a serves the frontend and the API from
one origin behind a single `basic_auth` (`deploy/Caddyfile`), and §3's pool
defaults are safe at every worker count and checked at startup. The reasoning,
and the arithmetic, are in
[`REVIEW_DEPLOY_PREREQS.md`](REVIEW_DEPLOY_PREREQS.md). **Two steps are still
yours**: choose a host, generate the password hash with `caddy hash-password`,
and point the hostname at the box. (The `Estimate Costs/` .docx files outside
this repo are superseded — they price an AWS deployment that is no longer the
plan.)

---

## 1. Prerequisites
- Python 3.11+ and a virtualenv/conda env for the API
- Node 18+ / npm for building the frontend
- PostgreSQL 14+ reachable from the API host
- System libs for cartopy: **usually nothing to do.** This line used to say GEOS and PROJ were required; they generally are not. cartopy, shapely and pyproj publish wheels for Linux (x86_64 and aarch64), macOS and Windows, and those wheels carry their own copies — shapely bundles `libgeos`, pyproj bundles `libproj`, and cartopy links neither. Verified on CI, which installs from `Data/requirements.txt` and loads only the vendored copies out of `site-packages` (NEXT_STEPS.md §34).

  You need them only where pip has no wheel for your platform and builds from the sdist — an unusual architecture, a very new Python, or `--no-binary`. In that case `apt-get install libgeos-dev libproj-dev proj-data proj-bin`, or avoid the build with `conda install -c conda-forge cartopy`.

---

## 2. Database

**Two stages, and the second is not optional.** The loaders populate the *native*
tables; every scored endpoint reads the *regridded* ones. Until 2026-08-27 this
section stopped after the loaders, which produced a deployment whose maps and
metric panels were all empty — the app looked installed and verified nothing.

### 2a. Schema and native data
```bash
createdb weave_weather
psql -d weave_weather -f Data/schema.sql
psql -d weave_weather -f Data/add_indexes.sql        # indexes — do not skip, queries rely on them
# Load data with the loaders (adjust paths/args inside as needed):
python Data/load_to_postgres.py
python Data/load_wind.py
python Data/load_gefs_ukmo_wind.py
```
Verify: `psql -d weave_weather -c "SELECT count(*) FROM forecast_data;"` should be non-zero.

### 2b. Regrid onto the common 0.5° grid
```bash
cd Data
python regrid_members.py --variables precipitation          # forecasts
python regrid_members.py --variables wind_u_10m,wind_v_10m
python regrid_observations.py --table regridded_observation --truncate   # truth
```

Both scripts create their own tables, so nothing needs adding to `schema.sql`.
`regrid_members.py` writes `regridded_forecast_member` and
`regridded_forecast_ens`; `regrid_observations.py` box-averages
`observation_data` into `regridded_observation`.

**A fresh install needs no migration for the column itself.**
`regrid_members.py`'s DDL already includes `init_time` and the run-scoped
indexes, so the tables come out right the first time — verified on a throwaway
database. `Data/migrate_init_time.py` exists for the other case: a database
loaded *before* 2026-09-02, whose regridded tables predate that column.

**A fresh install should still run it once**, after 2b, to populate
`forecast_run_registry` — the per-run record of member counts, hour ranges and
export convention that `/api/runs` reads:

```bash
python Data/migrate_init_time.py --dry-run   # says what it would change
python Data/migrate_init_time.py
```

It is idempotent, so this is safe whichever case you are in; on an
already-migrated database it reports the column as present and refreshes the
registry. Run it *after* the loaders, not before — with `forecast_runs` still
empty it exits saying there is no run to attribute rows to, which is correct but
unhelpful. Without the registry, `/api/runs` falls back to a `DISTINCT` over the
ens table and still answers, just without the member counts and conventions.

Two things to know:

- **`regrid_observations.py` defaults to a `_rebuilt` table, not the live one**, so
  the `--table regridded_observation` above is deliberate and required on a fresh
  install. On an *existing* database, run `--compare` first: the rule here is not
  the one that produced the pre-2026-08-27 data, and the difference is material
  (see `NEXT_STEPS.md` §7).
- **`observation_data` still has no loader in this repo.** It is the one remaining
  hole: the native point observations were ingested off-repo, and 2b can only
  coarsen what 2a loaded. A fresh deployment therefore gets forecasts and no
  truth until that table is populated by other means.

Verify:
```bash
psql -d weave_weather -c "SELECT count(*) FROM regridded_forecast_ens;"
psql -d weave_weather -c "SELECT count(*) FROM regridded_observation;"
python Data/regrid_members.py --verify-grid --hours 0   # coordinates land on the grid
```
Both counts must be non-zero. If `regridded_observation` is empty, every metric
panel will be correctly-but-confusingly blank.

### 2c. Cyclone tracks — optional, and independent of everything above

**Skip this and the app still works**; the Cyclones tab is simply empty. The
cyclone tables share nothing with the forecast/observation tables — different
source, different grid (none), different loader — so 2c can be run before, after
or never, and a failure here cannot affect the other three tabs.

The source is **not** the forecast archive. It is a separate set of CXML tracker
outputs on Explorer — **1,181 files** named `<centre>_<label>h_<STORM>.csv`,
several per storm and centre, one per initialisation cadence:

```bash
cd Data
python load_cyclone_tracks.py --source /projects/k.aggarwal/Shuochen/output --dry-run
python load_cyclone_tracks.py --source /projects/k.aggarwal/Shuochen/output --skip-bad
```

Run `--dry-run` first: it reads, validates and reports without writing, and the
refusals below are worth seeing before a commit rather than after one. The
loader creates its own three tables, so nothing needs adding to `schema.sql`.

**`--skip-bad` is required for this archive and is not a shrug.** Without it a
single self-contradicting file stops the whole load, which is the right default.
One file of 1,181 genuinely is contradictory — `egrr_72h_GITA.csv` carries two
initialisations in one file — and `--skip-bad` names and counts every file it
skips at the end. Read that list; it is the only record that the load is
incomplete.

**Do not point `--source` at `storm_2016_2024_*`.** That is an older generation
of the same product, scored against a **different IBTrACS vintage** — the two
disagree for 24 of 138 storms, because IBTrACS revises past storms
retrospectively. Mixing them gives a table where some storms are scored against
one best track and some against another, and every track error is then wrong by
whatever the revision moved. The loader refuses to load a second generation into
a non-empty registry; if you genuinely want to switch generations, clear the
three cyclone tables first. `TC_DATA_ACCESS.md` §9 has the evidence.

Verify:
```bash
psql -d weave_weather -c "SELECT count(*) FROM cyclone_track_member;"
psql -d weave_weather -c "SELECT DISTINCT source_generation FROM cyclone_run_registry;"
```

Measured on the current load: **992,730 track rows, 5,379 best-track rows and
1,180 runs** over 138 storms and three centres (ECMWF-ENS 339 runs, GEFS 410,
MOGREPS 431), initialisations from 2016-01-01 to 2024-12-11. **201 MB** in all —
negligible beside the 123 GB of forecast data, so §9's storage arithmetic does
not change. `source_generation` must come back as exactly one value, `output`.

**Two counts that do not match, and the smaller one is the table.** The loader
reports 993,255 rows read; the table holds **992,730**. The 525-row difference
is one source file, `kwbc_0h_MATTHEW.csv`, which holds 1,050 rows that are 525
records each written twice — identical in every field. They carry no
information and are not stored.

**The loader now says so**, which it did not when this was first written:

```
  525 byte-identical duplicate row(s) ignored, in 1 run(s):
    kwbc MATTHEW: 525
```

Expect that line on this archive. A *different* count, or a different run named,
means the source changed. A file whose rows repeat with **different** positions
is refused outright rather than counted, because that is a contradiction rather
than a duplicate and choosing between the two would be inventing a track.

> An earlier version of this section guessed these might be distinct candidate
> cyclones that the uniqueness constraint was discarding. They are not — checked
> against the source, all 525 are exact repeats in a single file. The guess was
> plausible enough to act on, which is the argument for checking before acting.

---

## 3. Backend (Flask API)
```bash
cd Data
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then edit .env — see the env table below
```

**Run with gunicorn (never `app.run()` / the Flask dev server in beta):**
```bash
cd Data
WEB_CONCURRENCY=4 gunicorn -w 4 -b 127.0.0.1:5000 flask_api:app
```
- **Bind `127.0.0.1`, not `0.0.0.0`.** The API authenticates nothing itself — the password lives on the Caddy vhost (§4a) — so a port reachable from outside is a way straight past it. Localhost-only means the proxy is the only route in.
- `WEB_CONCURRENCY` must match `-w`. It is what the startup pool check reads to verify `workers × DB_POOL_MAX` fits under `max_connections`; gunicorn reads the same variable, so setting it once serves both.
- `flask_api:app` imports the module-level `app`; the `.env` is loaded relative to `flask_api.py`, so it's found regardless of cwd.
- **Worker/DB math:** each worker holds its own connection pool (`DB_POOL_MAX`, default **8**). Keep `workers × DB_POOL_MAX` under PostgreSQL's `max_connections` (default 100, of which 3 are superuser-reserved). 8 × 8 = 64 is safe at every tier; the old default of 20 held only for 4 workers and failed at 5+ concurrent users.
  **This is now checked, not just documented:** the API prints the arithmetic at startup and refuses to be quiet about it, and `/api/health` reports it under `connection_pool` with a `safe` flag. Check that after deploying rather than trusting the table.
- The `spatial-metric-plot` and `compare/spatial-agreement` endpoints render matplotlib/cartopy images (CPU-heavy, ~seconds). Don't set worker count too low; the Caddyfile sets a 120s proxy timeout for this reason.

---

## 4. Frontend (static build)
**For the single-origin deployment below, set nothing.** `src/api/base.js`
defaults to same-origin `/api` in a production build, so:

```bash
npm ci
GENERATE_SOURCEMAP=false npm run build
```

- **Do not set `REACT_APP_API_URL`** unless the API genuinely lives on another
  host. It is baked into the bundle at build time, so whatever it holds ships to
  every browser in readable JavaScript — and if it names a second origin, a
  password on the static site protects nothing, because that origin can be
  called directly. Verified: a build with it unset contains **zero** occurrences
  of a separate API origin in the shipped JavaScript.
- **`GENERATE_SOURCEMAP=false`** because the default build emits a 4.5 MB
  `main.*.js.map` containing the complete original source. Behind a password
  that is a smaller problem than it looks, but it is still the whole codebase
  handed to anyone who gets in, and reviewers do not need it.

Serve `build/` from the same vhost as the API — see §4a. For a quick local check
(this serves the static half only, so API calls will 404 until something is
proxying `/api`):
```bash
npx serve -s build
```

---

## 4a. One origin, one password (the reviewer beta)

`deploy/Caddyfile` in this repo is the whole configuration: it serves `build/`,
proxies `/api/*` to gunicorn on localhost, and puts `basic_auth` over **both**.
Two edits before it works — the hostname, and the password hash:

```bash
caddy hash-password        # paste the bcrypt output into deploy/Caddyfile
caddy run --config deploy/Caddyfile
```

Never put a plaintext password in that file. Caddy also fetches and renews the
TLS certificate itself once the hostname resolves to the box, which covers §7's
TLS item.

Full reasoning, and the arithmetic behind the pool limits, are in
[`REVIEW_DEPLOY_PREREQS.md`](REVIEW_DEPLOY_PREREQS.md).

---

## 5. CORS — not needed for the single-origin deployment
With the frontend and API on one vhost there is **no cross-origin request to
allow**, so `CORS_ORIGIN` does not matter and can be left at its default. It is
still required if you deliberately split the two hosts, in which case set it to
the exact frontend origin (scheme + host + port); a mismatch means the browser
blocks every API call. That split is also the configuration a single password
cannot protect — see §4.

---

## 6. Environment variables (`Data/.env`)

| Variable | Purpose | Beta value |
|---|---|---|
| `DB_NAME` | Postgres database | `weave_weather` |
| `DB_USER` | Postgres user | **real user** (no default) |
| `DB_PASSWORD` | Postgres password | **real password** (don't leave blank) |
| `DB_HOST` / `DB_PORT` | Postgres host/port | your DB host / `5432` |
| `DB_POOL_MIN` / `DB_POOL_MAX` | per-worker pool | `2` / `8` |
| `WEB_CONCURRENCY` | worker count, for the pool check | match gunicorn `-w` |
| `CORS_ORIGIN` | allowed frontend origin | *(unused on one origin — §5)* |
| `FLASK_PORT` | API port | `5000` |
| `FLASK_DEBUG` | **must be false/unset in beta** | *(leave unset)* |
| `MAX_CONTENT_LENGTH` | max request body (bytes) | `16777216` |
| `LOG_LEVEL` | `DEBUG`/`INFO`/`WARNING`… | `INFO` |
| `LOG_FORMAT` | `text` to read, `json` to ship | `text` locally, `json` behind a collector |
| `LOG_QUIET_PATHS` | paths logged at DEBUG, so probes do not drown the log | `/api/health,/api/ready` |

Frontend build vars (not in `.env`): `GENERATE_SOURCEMAP=false`, and
`REACT_APP_API_URL` **only** if the API is deliberately on another host (§4).

---

## 7. Security checklist (before exposing to testers)
- [ ] `FLASK_DEBUG` unset/false (default is now false; the Werkzeug debugger must never be reachable).
- [ ] Real `DB_USER` / `DB_PASSWORD`; the DB not exposed publicly.
- [ ] **`basic_auth` covers `/api/*` as well as the static build** (§4a). The API authenticates nothing on any of its routes, so this is the only thing in front of it.
- [ ] **gunicorn bound to `127.0.0.1`, not `0.0.0.0`** (§3) — otherwise port 5000 is reachable directly and the password is bypassable.
- [ ] **Built without `REACT_APP_API_URL`** so the bundle ships no second origin (§4). Check: `grep -c "http://" build/static/js/*.js` should not turn up an API host.
- [ ] **Built with `GENERATE_SOURCEMAP=false`** so the full source is not served alongside the app (§4).
- [ ] `/api/health` reports `connection_pool.safe: true` (§3).
- [ ] TLS terminated at the proxy — Caddy does this itself once the hostname resolves (§4a).
- [ ] `CORS_ORIGIN` locked to the frontend origin, *if* the two are on separate hosts (§5).
- [ ] **Rotate the GitHub PAT** that was previously embedded in the git remote; remotes are now tokenless + use a credential helper.
- [ ] `.env` never committed (already git-ignored).

---

## 7a. Readiness and logs

`GET /api/ready` is the probe for a load balancer or a container runtime: it
takes a pooled connection and runs `SELECT 1`, nothing more. **200** means this
worker can serve; **503** means it cannot and the balancer should route around
it. Point liveness/readiness checks here, *not* at `/api/health` — health runs
database-size, pool, storage and export-convention checks, which is what you
read once after a deploy, not several times a minute.

Logs go to **stderr**, one line per request:

```
2026-10-02T10:15:01-0400 INFO [trace-abc] weave.access: GET /api/models 200 3.4ms from 127.0.0.1
```

The bracketed value is the request id. It is taken from an inbound
`X-Request-ID` when the caller sends a sane one — so a trace spans your proxy
and the app — and generated otherwise; either way it comes back on the response,
so a tester reporting a problem has something to quote. Set `LOG_FORMAT=json`
to get the same fields as JSON objects for a collector.

`GET /api/health` also reports what this worker has served since it started:
request counts by status class and recent latency percentiles. It is per-worker
and resets on restart — with `-w 4` you are seeing one of four.

---

## 8. Smoke test after deploy

Everything is behind one password now, so `curl` needs `-u`:

```bash
BASE=https://weave-review.example.com
curl -u reviewer -f "$BASE/api/health"    # {"status":"healthy",...}
curl -u reviewer -f "$BASE/api/models"    # [{"name":"AIFS"...}]
```

**Then check the password is actually load-bearing** — these two are the test
that §4a worked, and both must fail:

```bash
curl -o /dev/null -w '%{http_code}\n' "$BASE/api/health"   # expect 401
curl -o /dev/null -w '%{http_code}\n' "$BASE/"             # expect 401
```

A `200` from either means the vhost is serving something in front of the
password, which is the exact failure `REVIEW_DEPLOY_PREREQS.md` §1 describes.
And from another machine, confirm the API is not reachable around the proxy:

```bash
curl -m 5 -o /dev/null -w '%{http_code}\n' http://<host>:5000/api/health
# expect a timeout or refusal, NOT 200 — see the gunicorn bind in §3
```

Check the pool arithmetic on the deployed instance rather than trusting §3:

```bash
curl -su reviewer "$BASE/api/health" | python3 -m json.tool | grep -A8 connection_pool
# "safe": true
```

Then load the frontend, confirm the map renders a field, click a point →
Analysis charts, and run a Comparison. Check the browser console is free of
errors — and free of requests to any origin other than this one, which is the
frontend half of the same check.

**If 2c was run, check the Cyclones tab too** — and check it the way the one
defect found in it was found, which was not by looking at the map:

```bash
curl -su reviewer -f "$BASE/api/cyclones" | python3 -c \
  'import json,sys; r=json.load(sys.stdin)["runs"]; print(len(r), "runs")'
# 1180 runs on the current load; 0 means 2c was skipped, which is allowed
```

Then open the tab, switch storm and centre a few times, and **watch the network
panel, not the map**. There should be exactly one round of requests per change
and no 404s. The tab shipped with a defect where every switch first requested
the new storm against the previous storm's initialisation — a pair that cannot
exist — and the component's own error guards meant the 404 was never displayed.
The map looked perfect throughout. A 404 here means that regression is back.

Three things on the tab are worth reading rather than glancing at, because each
is a number that would be wrong in a plausible-looking way:

- The header says *"N of M members tracked this storm"*. **M is the ensemble
  size, not N** — a member that forecast no cyclone is a result, not a gap, and
  dividing by N would inflate every strike probability. On a MOGREPS storm the
  two numbers usually differ, which is the easiest place to see it is right.
- A storm near the dateline (try YASA) must draw as **one** continuous fan, not
  two clusters on opposite edges of a world-zoomed map.
- The error/spread chart's caption states how far the member count falls by
  +144 h. If it says the count is flat across all leads, something is wrong.

Then check the storage headroom, which says whether another run still fits
before anyone starts a 55 GB ingest (`DATA_EXPANSION_DESIGN.md` phase 5):

```bash
curl -su reviewer "$BASE/api/health" | python3 -m json.tool | grep -A9 '"storage"'
# "safe": true, and "runs_until_revisit" > 0
```

---

## 9. Backup and recovery

> **Added 2026-10-01. There was no backup section here at all**, which was found
> while reconciling the planning documents — `SYSTEM_DESIGN_PLAN.md` S2 asks for
> a "backup/restore runbook" and nothing had been written. This states the real
> position rather than inventing a procedure nobody has run.

**There is no automated backup, and the database is 123.52 GB.** Two recovery
paths exist, and they are very different in cost:

**1. Rebuild from source — the supported path, and slow.** Every table can be
rebuilt: the three converters (`convert_aifs.py`, `convert_gefs.py`,
`convert_ukmo.py`) produce the forecast JSON, `load_to_postgres.py` /
`load_wind.py` load it, `regrid_members.py` regrids, and
`load_observations.py` + `regrid_observations.py` build the truth field from the
sources on Explorer (`NEXT_STEPS.md` §11 has the paths). The cyclone tables are
rebuilt separately and cheaply by `load_cyclone_tracks.py` (§2c) — minutes, not
hours, and from a source that needs no conversion step.

Budget realistically. Measured 2026-10-01: **one model's wind at one
initialisation — two components, 155 lead times, 42M rows — took 42 minutes to
load**, plus conversion and regrid on either side. A full three-model run is
several hours of wall time and needs the NetCDF sources staged first.

**2. `pg_dump` — faster to restore, and nobody has run it at this size.**

```bash
pg_dump -Fc -d weave_weather -f weave_$(date +%F).dump    # custom format, compressed
pg_restore -d weave_weather -j 4 weave_2026-10-01.dump    # parallel restore
```

Two things to know before relying on it. The dump of a 123 GB database is itself
large and has to go somewhere that is not the same disk, and **this has not been
exercised here** — an untested restore is a plan, not a backup. If it matters,
run it once against a scratch database and record how long it took and how big
the file was, in this section.

**The cyclone data is the cheap case.** 201 MB from CSVs that need no
conversion, so it is always faster to re-run §2c than to restore it. The one
thing a restore would preserve and a reload would not is the record of which
files were skipped — `--skip-bad` prints that list and nothing stores it.

**What is cheap to protect and easy to overlook:** the schema, the loaders and
the converters are all in git, so the *code* half needs no backup. What is not in
git is the 123 GB of loaded data and the staged NetCDF sources — and of those,
only the data is reproducible from Explorer.
