# WEAVE — Deployment Guide (beta)

Architecture: a **React single-page app** (static build) talking to a **Flask JSON API**, which reads from a **PostgreSQL** database of forecast/observation data.

```
[ browser ] → static build (CDN / static host) ─HTTP→ Flask API (gunicorn) → PostgreSQL
```

---

## 1. Prerequisites
- Python 3.11+ and a virtualenv/conda env for the API
- Node 18+ / npm for building the frontend
- PostgreSQL 14+ reachable from the API host
- System libs for cartopy: **GEOS** and **PROJ** (`apt-get install libgeos-dev libproj-dev proj-data proj-bin`, or install cartopy via `conda -c conda-forge`)

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
gunicorn -w 4 -b 0.0.0.0:5000 flask_api:app
```
- `flask_api:app` imports the module-level `app`; the `.env` is loaded relative to `flask_api.py`, so it's found regardless of cwd.
- **Worker/DB math:** each worker holds its own connection pool (`DB_POOL_MAX`, default 20). Keep `workers × DB_POOL_MAX < PostgreSQL max_connections` (default 100). 4 workers × 20 = 80 is safe.
- The `spatial-metric-plot` and `compare/spatial-agreement` endpoints render matplotlib/cartopy images (CPU-heavy, ~seconds). Don't set worker count too low, and consider a reverse-proxy timeout ≥ 60s.
- Put gunicorn behind nginx/Caddy for TLS and to serve the static frontend.

---

## 4. Frontend (static build)
The API base URL is **baked in at build time** via `REACT_APP_API_URL`. A default build points at `http://localhost:5000/api`, which will NOT work for remote testers — set it explicitly:

```bash
REACT_APP_API_URL="https://your-beta-api.example.com/api" npm ci
REACT_APP_API_URL="https://your-beta-api.example.com/api" npm run build
```
Serve the `build/` folder from any static host / CDN (or nginx). For a quick local check:
```bash
npx serve -s build
```

---

## 5. CORS
The API only allows the origin in `CORS_ORIGIN`. Set it to the exact frontend origin (scheme + host + port), e.g. `https://weave-beta.example.com`. A mismatch → browser blocks all API calls.

---

## 6. Environment variables (`Data/.env`)

| Variable | Purpose | Beta value |
|---|---|---|
| `DB_NAME` | Postgres database | `weave_weather` |
| `DB_USER` | Postgres user | **real user** (no default) |
| `DB_PASSWORD` | Postgres password | **real password** (don't leave blank) |
| `DB_HOST` / `DB_PORT` | Postgres host/port | your DB host / `5432` |
| `DB_POOL_MIN` / `DB_POOL_MAX` | per-worker pool | `5` / `20` |
| `CORS_ORIGIN` | allowed frontend origin | your frontend URL |
| `FLASK_PORT` | API port | `5000` |
| `FLASK_DEBUG` | **must be false/unset in beta** | *(leave unset)* |
| `MAX_CONTENT_LENGTH` | max request body (bytes) | `16777216` |

Frontend build var (not in `.env`): `REACT_APP_API_URL`.

---

## 7. Security checklist (before exposing to testers)
- [ ] `FLASK_DEBUG` unset/false (default is now false; the Werkzeug debugger must never be reachable).
- [ ] Real `DB_USER` / `DB_PASSWORD`; the DB not exposed publicly.
- [ ] `CORS_ORIGIN` locked to the frontend origin.
- [ ] TLS terminated at the proxy (HTTPS for both app and API).
- [ ] **Rotate the GitHub PAT** that was previously embedded in the git remote; remotes are now tokenless + use a credential helper.
- [ ] `.env` never committed (already git-ignored).

---

## 8. Smoke test after deploy
```bash
curl https://your-beta-api.example.com/api/health          # {"status":"healthy",...}
curl https://your-beta-api.example.com/api/models           # [{"name":"AIFS"...}]
```
Then load the frontend, confirm the map renders a field, click a point → Analysis charts, and run a Comparison. Check the browser console is free of errors.
