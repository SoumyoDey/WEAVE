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

> **Everything in this section is a 2026-07-28 snapshot and three of its facts
> are now false.** Corrected 2026-10-01; the original is kept below because the
> commit list is still an accurate record of what P0–P3 contained.
>
> - **PR #2 is MERGED** (2026-09-02, `49ead8f`), not open. The branch
>   `p0-reliability` is gone and **work happens on `main`**, which is well past
>   the 11 commits named below. There is nothing to "push" or "get reviewed".
> - **The test suite is not 29 backend tests and 2 frontend smoke tests.** It is
>   far larger now. **This bullet used to carry the figures, including
>   "`metrics.py` and `flask_api.py` at 100% statement coverage" — and
>   `flask_api.py` was 97%.** Measured the same day the bullet was written.
>
>   Keep the correction visible, because of *where* it happened: a correction
>   banner, headed "corrected 2026-10-01", asserting a number in the same breath
>   as telling the reader to measure rather than quote it. The §29 reconciliation
>   checked whether prose matched the *code* and so could not catch a claim that
>   only a *measurement* falsifies — and then restated one.
>
>   So this bullet no longer names a figure at all. **`NEXT_STEPS.md`'s "Where
>   things stand" holds the coverage numbers and the command that produces
>   them**, in one place, because two copies of a measured number is how the
>   second one rots.
> - **`WEAVE_presentation` is gone**, so the warning about confusing it with the
>   dev repo no longer applies. Its demo-readiness fixes were re-implemented
>   here, which the note below already says.
>
> For where things actually stand, read `NEXT_STEPS.md` — it has an "If you are
> picking this up cold" section written for exactly that, and is current through
> §27.

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

> ## Status, reconciled 2026-10-01
>
> **This roadmap was written 2026-07-28 and had never been checked against what
> shipped.** Only the Vite item in S5 carried a marker. Two months of work landed
> through `NEXT_STEPS.md` without anyone asking which S-phase it belonged to, so
> **S1 and the science track were substantially complete and unmarked**, while
> four phases are genuinely untouched. Each item below was verified against the
> code, not against another document.
>
> | phase | state |
> |---|---|
> | **S1** Data lifecycle | **mostly DONE** — 2 items left |
> | **S2** Ops & delivery | **CI + observability** — containerisation and an exercised restore left |
> | **S3** Scale | **partly** — caps and caching done, Redis/async/load-test not |
> | **S4** Extensibility | **DONE 2026-10-02** — exit criterion met; see the section below |
> | **S5** Frontend | **1 decision, 2 items untouched** |
> | **S6** Security | **beta-adequate**, gated on "only if public" |
> | Science track | **DONE** |
>
> **The reconciliation itself is the lesson.** A roadmap that is never marked
> stops being a plan and becomes a list of things that might already be true —
> which is worse than no list, because it invites re-doing finished work and
> hides what is actually missing. The same failure as `CONSISTENCY_AUDIT.md`'s
> header and `METRICS_AUDIT.md`'s figures, found in the same sweep.

### S1 — Data lifecycle & integrity *(foundation, do first)* — **MOSTLY DONE**
- ~~Commit & document the full ingestion pipeline incl. the regrid + observation
  steps~~ **DONE.** `convert_aifs.py`, `convert_gefs.py` and `convert_ukmo.py`
  (§16, §20) plus `load_observations.py` (§12), `regrid_members.py` and
  `regrid_observations.py`. **Every table can now be rebuilt from source**, which
  this phase called its highest-leverage gap. Each converter reads the
  initialisation time *out of the file* and refuses a directory whose files
  disagree — the check that would have caught §20 at the moment it was
  introduced.
  - ~~*Still open:* an end-to-end **"load one run" runbook**~~ — **written
    2026-10-06**, `RUNBOOK_LOAD_ONE_RUN.md`. Writing it broke two steps that
    were documented as working, which is the argument for having it.
- ~~Fix the loader: config-driven, correct DB, `argparse`, parameterized
  `init_time`~~ ~~**DONE.**~~ **This was not true for the three forecast
  loaders** and said so for some time. `load_to_postgres.py`, `load_wind.py`
  and `load_gefs_ukmo_wind.py` each carried a hardcoded `__main__` — database
  `weather_forecasts` (which does not exist here), user `s.dey`, fixed source
  paths and `init_time='2025-09-08 00:00:00'`. **Actually done 2026-10-06**:
  all three take `--source`, `--model`, `--init-time` and, for wind,
  `--variable`, and read the env-driven `DB_CONFIG` the rest of the codebase
  uses. Found by writing the runbook above.
- ~~Link the table families; consistency check that fails ingestion on
  divergence~~ **DONE.** `regridded_*` carry `init_time` (`migrate_init_time.py`),
  and `uq_forecast_data_natural_key` / `uq_ensemble_statistics_natural_key` /
  `uq_rfm_natural_key` / `uq_rfe_natural_key` make a divergent re-load **fail**
  rather than silently double (§19). The hazard had already fired once: GEFS wind
  was loaded twice and `/api/wind-data` squared it to 4.00×.
- **NOT DONE — freshness signal.** `/api/health` returns `status`, `database`,
  `total_forecast_points_estimate`, `precip_export_convention`,
  `connection_pool` and `storage`. **None of them is "data as of `<init_time>`".**
  The UI names the run in its selector, so a reader is not misled, but the
  readiness signal this phase asked for does not exist.
- **PARTLY — retention decided 2026-10-01** (`DATA_EXPANSION_DESIGN.md` phase 5):
  no limit yet, revisit at 250 GB, enforced by `_check_storage_headroom`.
  **Partitioning is NOT done** — nothing in `schema.sql` is partitioned, and at
  55.30 GB per three-model run it is what would make eviction cheap.
- **Exit:** reached except for the runbook and the freshness signal.

### S2 — Ops & delivery baseline *(de-risks the rest)* — **CI + OBSERVABILITY**
- **NOT DONE — containerize.** No `Dockerfile`, no `docker-compose.yml`.
- ~~CI: backend pytest + frontend build/test on push; block on red~~ **DONE
  2026-08-24.** `.github/workflows/tests.yml`, four jobs on every PR and push to
  `main`: jest, playwright against real Chromium, the production bundle with
  warnings-as-errors, and pytest against a PostgreSQL service container. Two
  details are load-bearing and are documented in `NEXT_STEPS.md`: the backend job
  asserts the database answers *before* running pytest, and `WEAVE_REQUIRE_DB_TESTS`
  (2026-10-01) turns an unreachable fixture from a skip into a failure — added
  after a class of test was found to have never run in CI at all.
- ~~**NOT DONE — observability.**~~ **DONE 2026-10-02** (`NEXT_STEPS.md` §36).
  `Data/observability.py`: structured logging to stderr (`LOG_LEVEL`,
  `LOG_FORMAT=text|json`), a validated and propagated `X-Request-ID` on every
  request and response, one access line per request with status and duration,
  in-process counts and latency percentiles on `/api/health`, and
  `GET /api/ready` as the readiness probe this bullet said was missing.

  **The 43 endpoint `print()` calls are gone**; the 43 in the `__main__` startup
  banner stay, because a banner the dev server prints is not service output and
  `gunicorn` never runs it. The bullet's real finding was not the missing
  timestamps: every endpoint ended `except Exception as e: print(str(e))`, so
  **the traceback was discarded**. Those are `log.exception` now, and a test
  asserts `exc_info` is present rather than trusting the call.

  *Still open, and worth stating because the boundary above hides it:* the
  pool-headroom and storage-headroom warnings also live in the `__main__`
  block, so in production nobody is told. Moving them to application start is a
  behaviour change to someone else's work and belongs in its own commit.
- **PARTLY — backup/restore runbook.** This bullet used to read "`DEPLOY.md` has
  eight sections and **none of them mentions `pg_dump`, backup or restore**".
  That stopped being true on 2026-10-01: `DEPLOY.md` now has nine sections and
  §9 is *Backup and recovery*, written during the planning-document
  reconciliation (`NEXT_STEPS.md` §29).

  What remains is not the writing. §9 states the real position rather than
  inventing a procedure — there is no automated backup, rebuild-from-source is
  the supported path at a measured ~42 minutes for one model's wind at one
  initialisation, and **`pg_dump` has never been run at this size** (128.88 GB on 2026-10-08). An untested
  restore is a plan, not a backup, so the open item is *exercising* it and
  recording what it cost. **No secrets manager** either: `Data/.env` is the
  whole of it.
- **Exit:** not reached, but the gap is narrower and named. The CI gate is
  green and the service is observable; what is absent is the local stack (no
  `Dockerfile`, no `docker-compose.yml`) and a restore anyone has actually run.

### S3 — Scale the compute/render path — **PARTLY**
- **NOT DONE — Redis.** The metric cache is in-process, so it dies with each
  worker and is not shared between them. Redis appears in `flask_api.py` only as
  an optional rate-limit backend (`RATE_LIMIT_STORAGE`). No region warming.
  - *Measured cost of not having it:* a cold wide-window region score takes
    **~78 s**, against 0.5–0.9 s cached. The Analysis region view fires ~10 at
    once, and every worker restart pays it again.
- **NOT DONE — async Cartopy / task queue / app-level timeouts.**
- ~~Paginate/stream large point lists~~ **DONE** — row caps, with
  `test_point_list_caps.py` pinning them (and made to actually query a database
  on 2026-10-01).
- **NOT DONE — load test to a concurrency target.** The pool headroom check
  computes what *would* fit; nothing has driven load at it.
- **Exit:** not reached.

### S4 — Extensibility & maintainability — **DONE 2026-10-02**
- ~~Single registry exposed to the frontend via a config endpoint~~ **DONE.**
  `GET /api/config` (`NEXT_STEPS.md` §32) serves the facts that were duplicated:
  which metrics exist, which need a single lead time rather than a range, which
  need a threshold, which have a unit-sensitive scale, which variables exist and
  in what unit, the region suite, and the common verification window. No
  database access — 2 ms — so it answers while the pool is busy.

  **It serves facts, not presentation, and that boundary is deliberate.**
  Colours, labels, legends and band edges stay in `src/constants.js`. The
  server-rendered PNG uses a continuous `Normalize` for most metrics while the
  browser overlay uses discrete bands: they are different renderings on purpose,
  so pushing one palette through the endpoint would make them agree by breaking
  one of them.

  **The parity tests are what close the gap**, not the endpoint. Three joins are
  now checked: `METRIC_REQUIREMENTS` against what the dispatchers actually read
  (by introspection), `src/constants.js` against the endpoint in both
  directions, and `VALUE_UNITS` against `VARIABLE_UNITS`. Verified to *fail*
  rather than assumed: flipping `csi`'s `requiresThreshold` in the frontend
  produces `requires_threshold disagrees (backend, frontend): {'csi': (True,
  False)}`, and a backend-only metric is named. The JS parser asserts it found
  at least 8 metrics before comparing, so it cannot pass vacuously on a file it
  failed to parse.
- ~~**Still open:** the frontend consumes the endpoint but still renders from
  `METRIC_CONFIG`~~ **DONE 2026-10-02 — the exit criterion is met.** The metric
  selector renders from `/api/config` (`NEXT_STEPS.md` §35): the server decides
  which metrics exist and what each requires, `constants.js` keeps labels,
  colours and order. Adding a metric to `SPATIAL_METRIC_REGISTRY` now puts it in
  the UI with no frontend change.

  The line above also said the frontend *consumed* the endpoint. It did not —
  `src/api/config.js` was imported by nothing but its own test, so the client
  existed, passed its tests, and was never called. That is recorded in §35
  rather than quietly corrected, because a well-tested component wired to
  nothing is a failure mode this project has now hit three times.
- **Still open** — config-driving the hardcoded extent / candidate hours / obs
  sources / base date. Each verified in place 2026-10-08:

  | item | where it is written down |
  |---|---|
  | extent | `TARGET_LAT_RANGE`/`TARGET_LON_RANGE` in `Data/regrid_members.py:84`, and again as bbox defaults at `flask_api.py:700` and `:4474` |
  | candidate hours | `src/components/MetricPanel.jsx:50` — `[0, 6, 12, 18]` for wind, `[6, 12, 18, 24]` otherwise |
  | obs sources | `src/components/AnalysisTab.jsx:192` and `AboutModal.jsx:80` name IMERG and ERA5 in prose |
  | base date | `src/components/Timeline.jsx:67` |

  **The base date is not merely unconfigured, it is wrong, and the line above it
  says so.** The fallback is `new Date('2025-09-08T00:00:00Z')` while the run
  the app opens on is `2025-09-16`; the comment two lines up reads *"comes from
  the run, not a hard-coded date — the latter silently lied the moment a
  different run was loaded."* It is reached whenever `obsCoverage` is null,
  which is every page load until that request returns, and permanently if it
  fails. Valid times are then computed eight days off. Filed here rather than
  fixed in a documentation commit.

- ~~**the deferred refactors** (`@with_db_cursor`, `_render_map()`, shared chart
  primitives, decomposing the two large tab components)~~ — **three of the four
  are DONE, 2026-10-08** (`NEXT_STEPS.md` §57–§60, §63). `@with_db_cursor`
  decorates 22 views; the map furniture is shared as `_map_figure_png` with 5
  callers; both tab components were decomposed. **Shared chart primitives are
  the one that remains**, and §63 parked it deliberately rather than by
  omission: the control row is rendered in two different visual idioms across
  the two tabs, so sharing it would mean picking one and changing how the other
  looks — a design decision, not a refactor.

  The tab components no longer "keep growing" — **measure, do not quote**:

  ```bash
  wc -l src/components/AnalysisTab.jsx src/components/ComparisonTab.jsx
  ```

  > This bullet appeared twice, once as "Still open" and once as "NOT DONE",
  > with the same four items and the same stale line count in both. Merged
  > 2026-10-07. A duplicated open item is worse than it looks: both copies get
  > re-read and neither gets updated, which is how `AnalysisTab.jsx` at 1,264
  > lines survived two rounds of edits to the component it counts.
  >
  > **The replacement count went stale in a day.** 2026-10-07 recorded 1,360;
  > it was 1,376 by 2026-10-08. A figure that moves whenever anyone touches the
  > file cannot be carried in prose, so the command above replaces it — the
  > same treatment §29 reached for the coverage percentages, for the same
  > reason.
  >
  > That paragraph used to end "what the item needs is the *fact* that both
  > components are large and undecomposed, which does not change between
  > measurements." It changed on 2026-10-08: they were decomposed. The dated
  > counts above are left as written, because they record the staleness problem
  > rather than assert today's sizes — but **the standing fact the item rested
  > on is gone, which is the one thing a "does not change" claim never prepares
  > you for.**
- **Exit:** not reached. Adding a *metric* is now a single-place change (§35),
  but a model or variable is still two — `constants.js` `MODELS` carries each
  model's member count and lead hours beside the backend's own registry.

### S5 — Frontend platform & resilience — ~3–4 days, low–med risk
- ~~Vite migration (CRA is EOL)~~ **dropped 2026-09-21** — see `NEXT_STEPS.md`
  §6 for what staying on CRA costs. The rest of S5 stands.
- React error boundary; code-splitting / lazy tabs.
- Runtime API config (stop baking `REACT_APP_API_URL`) — **partly overtaken**:
  `src/api/base.js` now defaults to same-origin `/api` in a production build, so
  the single-origin deployment needs no build-time URL at all. The variable is
  still baked when set, so this item survives only for a genuinely multi-host
  deployment.
- **Exit:** resilient UI, per-env config where it is still needed. "Maintained
  toolchain" is no longer part of the exit, since the migration is dropped.

### S6 — Security & multi-user *(only if exposed beyond internal)* — **BETA-ADEQUATE**
- AuthN (SSO/API keys), authz, per-user quotas, audit logging — **not done, and
  gated on this phase's own condition.** The reviewer beta puts one origin behind
  one `basic_auth` in `deploy/Caddyfile` with gunicorn bound to 127.0.0.1, which
  is adequate for trusted reviewers and is not multi-user security. Revisit only
  if WEAVE is exposed beyond that.

### Parallel track — Scientific validity *(gated on S1)* — **DONE**
- ~~Store per-member wind speeds → exact aggregate wind verification (drops the
  `|mean vector|` approximation)~~ **DONE.** `_member_cases_by_cell` computes
  per-member speed `√(u²+v²)` and says so at `flask_api.py:1181` — "per-member
  SPEED, which is exact — unlike the `|mean vector|`". The approximation is still
  *described* at `flask_api.py:939` for the aggregate path that retains it; that
  docstring is accurate, not stale.
- ~~Implement true neighborhood FSS~~ **DONE.** `_fss_from_pairs` rebuilds the
  binary fields per lead time over an `fss_window` neighbourhood (1–21 cells,
  caller-chosen) and forms the ratio once across hours — the standard
  multi-case aggregation, not a per-cell average. FSS deliberately has no map,
  because its value belongs to a field rather than a cell.

### Quick wins (pull forward, <½ day each)
- React error boundary (S5) · ~~deepen `/api/health` into readiness+freshness~~ **readiness done 2026-10-02 as `/api/ready` (§36); freshness still open** (S1/S2)
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
