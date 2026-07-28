# WEAVE — System-Design Plan & Session Handoff

> Self-contained handoff. A fresh session (or teammate) should be able to pick up
> the system-design work from this document alone. Written 2026-07-28.

---

## 0. How to use this doc
- **§1–§4** = context you need before touching anything (architecture, current
  state, how to run/verify, non-obvious gotchas).
- **§5** = the gap analysis (what's wrong at the system level).
- **§6** = the phased plan (S1–S6) — the actual work.
- **§7** = two decisions that change the plan; answer these first.
- **§9** = a copy-paste prompt to kick off a fresh session.

---

## 1. What WEAVE is (architecture snapshot)

Interactive weather-ensemble verification app.

```
[ browser: React SPA (CRA/Leaflet/Recharts) ]
        │  HTTP JSON  (REACT_APP_API_URL, baked at build)
        ▼
[ Flask JSON API  (Data/flask_api.py, gunicorn in prod) ]
        │  psycopg2 ThreadedConnectionPool (read-only)
        ▼
[ PostgreSQL: weave_weather ]     + server-side Cartopy/Matplotlib PNG rendering
```

- **Three tabs:** Visualization (Leaflet map + IDW field + uncertainty overlays +
  wind), Analysis (point + region verification), Comparison (multi-model).
- **Models:** AIFS (50 members, 6h precip accum), GEFS (30, 3h), UKMO (18, 1h).
- **Variables with data:** precipitation + wind. (temperature_2m / pressure_msl
  exist in schema, no data.)
- **Spatial metrics** (bias/MAE/RMSE/CRPS/CSI/POD/FAR/Brier/SSR/correlation/FSS)
  are computed server-side and rendered as Cartopy PNGs.

### Two table families (important, non-obvious)
| Purpose | Tables | Notes |
|---|---|---|
| Point analysis, cone, point SSR, member data | `forecast_data` (127M rows, per-member), `ensemble_statistics` (per-point mean/std) | normalized, FK to `forecast_runs`/`models`/`variables` |
| Region + comparison spatial metrics | `regridded_forecast`, `regridded_observation` | **denormalized**, keyed by string `model_name`/`variable_name`, **no `run_id`/FK** |
| SSR / correlation obs (sparse) | `observation_data` | single-timestamp match |
| Spatial-metric obs (dense) | `regridded_observation` | window-averaged |

The app always uses the **latest** `forecast_runs` row (`ORDER BY
initialization_time DESC LIMIT 1`). Wind forecast "speed" on the aggregate tables
is `√(mean_u²+mean_v²)` (a `|mean vector|` **approximation** — the point SSR path
via `forecast_data` is exact). FSS is a **domain-aggregate** fractions score, not
true neighborhood FSS.

---

## 2. Current state — what's already done

All line-level correctness/reliability/perf work is **done and on PR #2**. This
document is about the **system-design** work that remains (§5–§6).

**Git:** repo `/Users/k.aggarwal/Documents/AFW/WEAVE_v3`, remote
`github.com/SoumyoDey/WEAVE.git`. Branch **`p0-reliability`**, **11 commits on top
of `41e9dfa`**, **PR #2 open** (`main ← p0-reliability`), pushed, **not merged**.
`.claude/` is intentionally untracked.

Commits (oldest→newest):
1. `80f4d43` P0+P1 — DB txn/pool autocommit, pyplot→OO, windLayer leak, fetch
   sequencing, schema.sql completed; input validation 400s, SSR clamp, FSS fix,
   join logging; **built the Comparison "Advanced metrics" feature**.
2. `c60ecc0` P2 — removed correlated latest-run subqueries, batched spread-skill
   N+1, spatial-indexed the IDW canvas loop, memoized quadratic chart builders.
3. `eefb2d7` P3 — mapReady state, accessibility (dialog/focus/labels), error
   surfacing, config drift.
4. `7bbd001` backend metric tests (29, DB-free).
5. `9c9833a` fixed remaining `Math.max(...array)` spreads.
6. `a6d2886` **wind verification** — compare forecast SPEED √(u²+v²), not raw
   u-component, across all aggregate paths; compare/skill wind accum=1.
7. `08a8e99` precip SSR/correlation accumulation normalization.
8. `1338f00` backend robustness — release DB conn before Cartopy render, pool
   retry, Compute-All-Maps throttle-to-4.
9. `28707ea` UI clarity — SSR "Undefined", NaN guards, hour-max 0, °W/°S labels.

> The 2026-07-28 "demo-readiness" fixes that had been made to the (now-gone)
> `WEAVE_presentation` folder and never committed are **all re-implemented** in
> these commits.

**Tests:** backend `Data/test_metrics.py` (29 golden-vector, DB-free);
`Data/requirements-dev.txt` pins pytest. Frontend `src/App.test.js` (2 smoke).

**Presentation copy:** `/Users/k.aggarwal/Documents/AFW/WEAVE_presentation` =
clean snapshot of **pristine `main`** (no dev changes), runnable, has
`HOW_TO_RUN.md`. Separate from the dev repo — don't confuse the two.

---

## 3. Environment & run / verify cheat-sheet

- **Python:** the `afw` conda env → `~/miniconda3/envs/afw/bin/python`
  (has Flask, psycopg2, cartopy, numpy, scipy, matplotlib, pytest).
- **DB:** PostgreSQL `weave_weather`, creds in `Data/.env` (gitignored). ~127M
  forecast points. Data covers **US East Coast** (~lon −85..−65, lat 34..45),
  single init time **2025-09-08 00:00 UTC** — pick coastal points/regions or
  metrics read "no data" (not a bug).

**Run backend** (port 5000):
```bash
cd Data && ~/miniconda3/envs/afw/bin/python flask_api.py
```
**Run frontend** (port 3000):
```bash
npm start
```
**Backend tests / frontend tests / build:**
```bash
cd Data && ~/miniconda3/envs/afw/bin/python -m pytest -q      # 29 pass
CI=true npx react-scripts test --watchAll=false               # 2 pass
CI=false npx react-scripts build                              # must compile clean
```
**Browser preview** (in-session): `preview_start` with name `weave-frontend`
(from `.claude/launch.json`).

### Gotchas (learned this session — save yourself the time)
- **Backend startup races `curl`** — it takes ~4–14s to bind. Poll `/api/health`
  in a loop before hitting endpoints; don't trust a fixed `sleep`.
- **`gh` CLI is not installed.** PR #2 was created via the GitHub REST API using
  the token from `git credential fill` (git push already uses it).
- **`git push` occasionally times out at ~2 min** — just retry; it succeeds.
- **Analysis tab can briefly render blank** — a `chartsReady` rAF gate; wait a
  beat / re-click, it's not a crash. There is **no error boundary** yet (a real
  crash would blank the app).
- **Two DBs referenced:** the app reads `weave_weather`; the committed loader
  (`Data/load_to_postgres.py`) hardcodes `weather_forecasts` + user `s.dey` +
  init `2025-09-08` → it's a broken one-shot demo loader (see S1).

---

## 4. Key files
- `Data/flask_api.py` — the entire API (~3k lines). Helpers to know:
  `get_db_connection`/`_pool_getconn` (autocommit + retry),
  `_fcst_speed_sql`/`_ensemble_speed_rows` (wind speed via u/v self-join),
  `_fetch_fcst_obs_pairs_spatial`, `SPATIAL_METRIC_REGISTRY`, `MODEL_ACCUM_HOURS`,
  `PLOT_STYLE_REGISTRY`, `_categorical_hours_for_box`.
- `Data/schema.sql` — all 8 tables (now complete). `Data/add_indexes.sql`.
- `Data/load_*.py` — the (hardcoded/one-shot) loaders. **No loader populates
  `regridded_*` / `observation_data`** — that pipeline is external/undocumented.
- `src/App.js`, `src/components/{AnalysisTab,ComparisonTab}.jsx` (large),
  `src/layers/*`, `src/api/*`, `src/constants.js`, `src/theme.js`.
- Agent memory: `~/.claude/projects/-Users-k-aggarwal-Documents-AFW/memory/`
  (`weave_v3_audit_2026-07-24.md` has the full running log of the code work).

---

## 5. System-design gap analysis

**Headline:** WEAVE is built as a **single-snapshot demo**, not an operational
system. The biggest gaps are in the parts *around* the (now-solid) code.

- **A. Data lifecycle & ingestion 🔴** — regrid + observation ingestion is
  uncommitted/undocumented; loader is hardcoded (wrong DB, one date); single
  snapshot; raw vs regridded families can silently diverge (no `run_id`/FK on
  regridded); no retention/partitioning; no scheduling.
- **B. Data model** — normalized vs denormalized families; two obs sources matched
  by rounded-lat/lon convention (fragile); big tables unpartitioned.
- **C. Scale/perf** — server-side Cartopy render is CPU-bound, synchronous per
  request (the ceiling); FileSystemCache is per-instance; single Postgres; large
  point lists unpaginated.
- **D. Ops/observability 🔴** — no containers/IaC/CI; logging is `print()` only
  (no structured logs/metrics/tracing/error-tracking); shallow health check; no
  backup/secrets story.
- **E. Security** — no authN/Z (open API, rate-limited only); fine internal, gap
  if public. (SQL parameterized, DB read-only — that part is sound.)
- **F. Reliability** — no stale-data signal; no app-level timeout on renders;
  single points of failure; no alerting.
- **G. Extensibility** — adding a model/variable/metric touches ~6 scattered
  places; hardcoded extent/candidate_hours/obs-sources/base-date; complex dual
  path under-documented.
- **H. Frontend** — CRA/react-scripts EOL; single bundle; API URL baked at build;
  no error boundary.
- **I. Testing/CI** — good metric tests, but no endpoint/integration/loader tests,
  2 frontend smoke tests, no CI, no load testing.
- **J. Scientific validity (documented limits)** — `|mean vector|` wind-speed
  approximation on aggregate tables; domain-aggregate (not neighborhood) FSS.

---

## 6. Phased implementation plan

> Phases labeled **S1–S6** to stay distinct from the completed code phases P0–P3.
> Order follows dependency/leverage.

### S1 — Data lifecycle & integrity *(foundation, do first)* — ~1–1.5 wk, med risk
- Commit & document the full ingestion pipeline incl. the regrid + observation
  steps; deliver an end-to-end "load one run" runbook.
- Fix the loader: config-driven, correct DB (`weave_weather`), `argparse`,
  parameterized `init_time`; remove hardcoded creds/paths/date.
- Link the table families: add `run_id`/init-time reference to `regridded_*`; add
  a consistency check that fails ingestion on divergence.
- Freshness signal: "data as of `<init_time>`" in `/api/health` + UI; explicit
  "stale/missing" instead of silent "no data".
- Retention + partitioning of `forecast_data`/`ensemble_statistics`.
- **Exit:** a new run ingests end-to-end from docs; raw↔regridded consistency
  enforced; freshness visible.

### S2 — Ops & delivery baseline *(de-risks the rest)* — ~1 wk, low risk
- Containerize (API Dockerfile + static build + `docker-compose` incl. Postgres/Redis).
- CI: run backend pytest + frontend build/test + lint on push; block on red.
- Observability: structured JSON logging + request IDs (replace `print()`), error
  tracking (Sentry), basic metrics (latency/count, DB-pool), deep health/readiness.
- Backup/restore runbook; prod secrets manager.
- **Exit:** one-command local stack; green CI gate; observable prod.

### S3 — Scale the compute/render path — ~1–1.5 wk, med risk
- Redis cache as default; warm common regions.
- Async the heavy Cartopy endpoints (task queue) or pre-render tiles; app-level
  timeouts.
- Optional read replica; paginate/stream large point lists.
- Load test to a concurrency target.
- **Exit:** heavy endpoints don't block workers; concurrency target met.

### S4 — Extensibility & maintainability — ~1 wk, low–med risk
- Single model/variable/metric **registry** (accum hours, obs source, plot style,
  units, thresholds) — one backend source of truth, exposed to the frontend via a
  config endpoint.
- Config-drive hardcoded assumptions (extent, candidate_hours, obs sources, base date).
- Deferred refactors (behind the metric tests): `@with_db_cursor`, `_render_map()`
  helper, shared Recharts chart primitives, decompose the two large tab components.
- **Exit:** adding a model/variable/metric is a single-place change.

### S5 — Frontend platform & resilience — ~3–4 days, low–med risk
- Vite migration (CRA is EOL); React error boundary; runtime API config (stop
  baking `REACT_APP_API_URL`); code-splitting / lazy tabs.
- **Exit:** maintained toolchain, resilient UI, per-env runtime config.

### S6 — Security & multi-user *(only if exposed beyond internal)* — ~1 wk, med risk
- AuthN (SSO/API keys), authz, per-user quotas, audit logging.

### Parallel track — Scientific validity *(gated on S1)* — ~1 wk
- Store per-member wind speeds → exact aggregate wind verification (drops the
  `|mean vector|` approximation). Implement true neighborhood FSS.

### Quick wins (pull forward, <½ day each)
- React error boundary (S5) · deepen `/api/health` into readiness+freshness (S1/S2)
  · Redis cache default (S3) · stale-data banner (S1).

### Testing / reliability
Folded into each phase's exit criteria (integration/endpoint/loader tests in
S1–S2 CI; interaction tests in S5), not a separate phase.

---

## 7. Two decisions to make first
1. **Operational vs demo:** should WEAVE roll forward with new forecast runs, or
   stay a fixed snapshot? → determines whether S1 is a full scheduled pipeline or
   just documenting/fixing the one-shot loader.
2. **Public vs internal:** will it ever be exposed beyond trusted users? →
   determines whether S6 (authN/Z) is in scope at all.

---

## 8. Suggested order
**S1 → S2 → S3 → S4 → S5**; S6 only if public; science track alongside once S1
lands. Start with **S1** — reconstruct/document the ingestion pipeline and fix the
loader; it's the highest-leverage gap and unblocks everything else.

---

## 9. Fresh-session kickoff prompt (copy-paste)

> I'm continuing system-design work on WEAVE_v3 at
> `/Users/k.aggarwal/Documents/AFW/WEAVE_v3` (branch `p0-reliability`, PR #2 open
> against `main`; not merged). Read `SYSTEM_DESIGN_PLAN.md` in the repo root for
> full context — the code-level P0–P3 + demo-fix work is already done and on the
> branch; I now want to execute the **system-design** phases (S1–S6).
>
> Backend runs in the `afw` conda env (`~/miniconda3/envs/afw/bin/python
> Data/flask_api.py`, port 5000) against Postgres `weave_weather`; frontend is
> `npm start` (port 3000). Tests: `cd Data && python -m pytest -q`.
>
> Decisions: WEAVE should be [operational / demo]; it will [be public / stay
> internal]. Start with **S1 (data lifecycle & integrity)** — first
> reconstruct/document the regrid + observation ingestion pipeline and fix the
> hardcoded loader (it currently targets DB `weather_forecasts`/user `s.dey`/init
> `2025-09-08` instead of the app's `weave_weather`). Verify against the running
> backend as you go, and don't trigger any cybersecurity safeguards.
