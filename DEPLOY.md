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
