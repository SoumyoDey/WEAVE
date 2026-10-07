# Next steps

State as of 2026-09-28. **PR #2 is merged** (`49ead8f`); `main` is the live
branch and carries everything below.

**The active workstream is the password-protected reviewer deployment** (§10),
which is not what the rest of this document is about — everything below §8
predates it. Both of its prerequisites are **fixed**; what it now waits on is a
**host**, since the AWS plan was dropped on 2026-09-18 and nothing replaced it.
Read `REVIEW_DEPLOY_PREREQS.md` before deploying anything.

**Read this first.** Items 1, 3, 3b, 4, 7 and 8 below are done, all seven
defects the fixture layer found are fixed, and **the consistency audit is closed —
all six phases** (`CONSISTENCY_AUDIT.md`). **Nothing is blocked on another person
any more**; what is left is work, a decision that is yours, or data that is not
in this repository.

**Changes the rest of this document assumes**, newest first:

- **2026-10-02 — a tropical cyclone tab is requested** (§37), and it is the
  first *new* workstream since the consistency audit closed. Two features —
  every member's storm track on the map at once, and every member's field as a
  translucent layer — in a new tab, from data on the HPC. **Not started, and
  the first task is not code**: the request came with the warnings that the
  structure and the dates may differ from ours, which names this project's two
  most expensive defects (§13/§22 and §12). Read §37 before opening an editor.
- **2026-09-29 — the 09-08 run is a MIXTURE of two forecasts** (§20). §18's AIFS
  wind was not isolated: **four of six model/variable combinations were the
  09-16 run**, including all three models' wind and GEFS precipitation. Only
  AIFS and UKMO precipitation are genuinely 09-08. GEFS is now loaded as its own
  `2025-09-16` run via the new `Data/convert_gefs.py`, which reads the
  initialisation time out of the files and prints it.
- **2026-09-28 — the AIFS wind was the WRONG FORECAST RUN, and is fixed** (§18).
  The field stored at `2025-09-08 00Z` was the `2025-09-16` run, so every AIFS
  wind score paired a forecast with truth from eight days before it was
  initialised. Replaced from the HPC and now reproducible: MAE fell 70.5%.
  **Every AIFS wind figure written before this date is on the wrong forecast.**
  Verifying it exposed **two further defects, both now fixed** (§19): the map
  never respected the run selector, and GEFS wind was duplicated in the raw
  tables (now deduplicated, with the unique keys those tables always lacked). A
  third — `/api/spatial-metric` ignoring a documented `hour` — **was my error and
  is withdrawn**; only its docstring was wrong.
- **2026-09-28 — AIFS 06Z is loaded and the run is multi-model** (§17), using
  the converter in §16. Two defects fell out, both needing two runs whose
  *model lists differ*: `_run_pairs_sql` was discarding the `init_time` callers
  sent, and the Comparison tab offered a model the run does not hold. Both
  fixed. `2025-09-08 06Z` now holds AIFS and UKMO.
- **2026-09-28 — the AIFS converter exists** (§16), `Data/convert_aifs.py`. It
  reproduces the loaded 00Z run exactly — all 17,915,148 member rows. **GEFS
  still has none**, and AIFS *wind* is structurally supported but numerically
  unconfirmed.
- **2026-09-25 — the selector is date + cycle and scales past a dropdown**
  (§15), the basemap no longer demands an API key, and the run guard's last two
  leaks are closed. §14's "hidden below 760px" open item is fixed here. The
  method note worth carrying: a control that is right at two runs is not
  automatically right at sixty-eight, and there are **17 UKMO dates already on
  the cluster**.
- **2026-09-24 — a SECOND RUN is loaded** (§14): `2025-09-08 06Z`, UKMO only,
  0–36 h. The selector became a live control (two of them, after §15). It
  surfaced three defects that
  needed two runs to exist, and confirmed the AIFS/GEFS conversion stage does
  not exist anywhere.
- **2026-09-24 — the export convention is per-run, and scoring reads it**
  (§13). Finding a regrid re-run duplicated rows came out of the same work;
  that is fixed too, so **`DATA_EXPANSION_DESIGN.md` phase 4 is closed** and
  only phase 5 remains.
- **2026-09-24 — the run selector is built** (`DATA_EXPANSION_DESIGN.md`
  phase 3): run state in React with a stale-response guard, a header selector,
  and switch behaviour. Lead-time clamping turns out to matter on the single
  loaded run, since the models' ranges differ.
- **2026-09-22 — CI is clean** (§6): the actions are bumped off the deprecated
  Node 20 runtime, and the runners are pinned to `ubuntu-24.04` ahead of the
  19 October migration to Ubuntu 26, which would otherwise have moved Cartopy's
  GEOS and PROJ underneath the render tests unannounced. No annotations remain.
- **2026-09-21 — the Vite migration is dropped** (§6). That empties the
  lower-priority list; the cost of staying on CRA is stated there.
- **2026-09-21 — `observation_data` was VACUUM FULLed**, 1065 MB back down to
  499 MB (§12). Housekeeping rather than a fix, but it is a direct consequence
  of the UTC correction and the reason is worth knowing before the next bulk
  `UPDATE` on this database.
- **2026-09-18 — the AWS deployment is off** and no platform has replaced it
  (§10). Both `Estimate Costs/*.docx` are superseded. **No code changed**: the
  pool check reads the live server's limits rather than a table of instance
  sizes, so only the *justification* in `REVIEW_DEPLOY_PREREQS.md` §2 needed
  re-anchoring.
- **2026-09-17 — both reviewer-deployment prerequisites are fixed** (§10). One
  origin behind one `basic_auth` (`deploy/Caddyfile`, validated), same-origin
  API base, gunicorn on `127.0.0.1`, and a `DB_POOL_MAX` default that is safe at
  every worker count and checked at startup.
- **2026-09-16 — `observation_data` has a loader, it found a 4-hour defect in
  the truth field, and that defect is now FIXED** (§12).
  `Data/load_observations.py` reproduces **all 2,480,664 rows** of the loaded
  run bit-for-bit, which closes the last hole in the install path. Getting it to
  reproduce them is what exposed the defect: IMERG's timestamps were 4 hours
  behind UTC while ERA5's were not, so every precipitation score compared a
  forecast at lead H against truth from H+4.

  **The correction is live.** Both `observation_data` and
  `regridded_observation` are on UTC, the old field is kept as
  `regridded_observation_shifted`, and `METRICS_AUDIT.md` §0 is regenerated.
  **Every precipitation figure written before 2026-09-16 is on the old time
  base** — including anything quoted elsewhere in this document. Wind figures
  are unchanged throughout.
- **2026-09-16 — both observation sources have been found on Explorer** (§11).
  This is the big one, because item 3 below said for three weeks that the
  ingest was blocked on data that is "not on the development machine" — it is
  not on the development machine and it is on the cluster. **ERA5 wind is a
  complete match** for the loaded run. **IMERG precipitation is a partial
  one**: the only file covering 2025-09-08 is 6-hourly, where the truth field
  in the database today is half-hourly, so precipitation carries a decision
  rather than just work. Read §11 before starting the ingest.
- **2026-09-10 — the reviewer deployment's two prerequisites are recorded**
  (§10), in `REVIEW_DEPLOY_PREREQS.md`. Both are unimplemented; the note is a
  write-up, not a fix.
- **2026-09-02 — the `init_time` migration is done** (§8). The regridded tables
  carry a run identity, every query filters on it, the frontend names the run on
  every request, and an ambiguous request gets a 400 instead of a guess.
  `DATA_EXPANSION_DESIGN.md` phases 1–2 are closed and its "do not load a second
  run" rule is retired.
- **2026-09-02 — wind has its own metric colour bands** (see the ownerless-items
  list). The precipitation edges are unchanged.
- **2026-09-04 — the truth field was replaced** (§7). The banker's-rounding
  checkerboard is gone; every interior cell now averages the same number of
  observations. Scores moved — wind bias by up to 29% at a point — so
  `METRICS_AUDIT.md`'s figures no longer match the app and need re-deriving.
- **2026-09-04 — the deterministic metric endpoints are cached** (§6), 382x on a
  warm request. Note the cache key includes a fingerprint of the truth field, so
  the switch above invalidated it automatically.
- **2026-08-27 — the target grid is a constant**, so `regrid_members.py` can run
  on a fresh database for the first time (§2).
- **2026-09-02 — `regridded_forecast` is DROPPED** from `weave_weather` (§2),
  after six days renamed. A gzipped dump is the only remaining copy and it lives
  outside the repo. **`WEAVE_v2` and `WEAVE_presentation` can no longer serve
  from this database, permanently** — they query the old name and no version of
  them does not. If one of those errors about a missing relation, that is this,
  not a bug. And restart any long-running server after a schema change — see the
  trap in §1, which cost an hour.

## Where things stand

PR #2 merged on 2026-09-02 as `49ead8f`, all 90 commits preserved — +19,279/−1,802
across 78 files, over half of it tests and documentation. `main` is now 125
commits. See §1 for how and why it went in without review.

- **The backend and frontend suites pass with no xfails.** `python -m pytest -q`
  in `Data/` runs anywhere: without PostgreSQL a little over a fifth of it skips
  itself and the rest still runs.

  **Coverage, measured 2026-10-01** — `metrics.py` **100%** (282 statements, 0
  missing), `flask_api.py` **97%** (2083 statements, **54 missing**):

  ```bash
  cd Data && python -m pytest -q --cov=flask_api --cov=metrics --cov-report=term-missing
  ```

  > **This line claimed both were at 100% until 2026-10-01, and for `flask_api.py`
  > that was false.** The gap is not the two `pragma: no cover` branches below —
  > it is 54 statements, and the largest blocks are nameable: `available_runs`
  > (6) and the whole `/api/runs` body (21), with ~27 singles across other
  > endpoints. Long-standing code, not recent drift. **Exactly one test in the
  > suite calls `/api/runs`.**
  >
  > The paragraph below already said to re-check rather than trust it. Nothing
  > did, because **the CI workflow never runs `--cov` at all** — so the claim was
  > unfalsifiable in the one place that would have caught it. A number nothing
  > measures is a number that decays silently; this one decayed under a sentence
  > predicting it would.
  >
  > **Scope the measurement.** `.coveragerc` sets `source = .`, so an unscoped
  > `--cov` or a bare `coverage run` tries to measure site-packages and dies on
  > whichever compiled extension your import order reaches first — Cartopy's
  > Cython shim under `sysmon`, or numpy's `_pocketfft_umath`. Two machines got
  > two different crashes from the same mistake on 2026-10-01. Use the command
  > above; making the broken invocation impossible is a pending `.coveragerc`
  > change.

  **Exact counts are deliberately not written here** — they went stale three
  times on 2026-08-27 alone, and a number that is wrong more often than right is
  worse than no number. Measure instead:

  ```bash
  cd Data && python -m pytest -q | tail -1              # with PostgreSQL
  cd Data && WEAVE_SKIP_DB_TESTS=1 python -m pytest -q | tail -1
  ```

  If a figure ever matters, re-measure it rather than doing arithmetic on a
  previous one — that is the same rule this document applies to the PR size.
  Two branches are excluded with `# pragma: no cover`, each carrying the reason
  it cannot execute — they are dead code, not untested code, and a test asserts
  the invariant that makes each one dead (`test_last_guards.py`). They are
  **`compare/skill`'s "no observations" warning** and **the region composite's
  re-weighting when FSS is absent**; the point endpoint's version of that second
  branch IS reachable and is tested, and only the region one cannot be. Removing
  both pragmas leaves exactly those two lines uncovered and nothing else, which is
  worth re-checking rather than trusting if the number ever matters.
- **CI exists and is green.** `.github/workflows/tests.yml`, added 2026-08-24,
  runs four jobs on every PR and on pushes to `main`: jest, playwright against
  real Chromium, the production bundle with warnings-as-errors, and pytest
  against a PostgreSQL service container. Two details there are load-bearing —
  the backend job asserts the database answers *before* running pytest, because
  `test_db_endpoints.py` skips itself when PostgreSQL is unreachable and would
  otherwise return a green tick over untested SQL; and the build job's
  warnings-as-errors is what stops a clean build from quietly decaying.
- **It was never reviewed.** The request sat 6 days; before that it sat 3 weeks
  with nobody having been *asked* at all. Worth knowing which of those two
  applies before concluding anything about how carefully this was read.
- The three records, in the order to read them:
  - `METRICS_AUDIT.md` — the metric audit. Read before re-deriving anything.
  - `CONSISTENCY_AUDIT.md` — all six phases, findings classified.
  - `Data/fixture_db.py` docstring — every expected test number, derived.

### Done on 2026-08-19/20

1. **Fixture-database test layer** (item 3): `flask_api.py` 41% -> 83%. Found
   seven defects, all fixed.
2. **Member-grid migration finished** (3b): `_member_cases_by_cell` is the one
   implementation behind `/api/spread-skill`, `/api/compare/skill` and both
   spread-dependent maps. The point panels and the maps now agree exactly.
3. **Observation coverage in the UI** (item 4): `/api/observation-coverage`, a
   timeline marker, and empty states that name the record's extent.
4. **Per-model native grids in the fixture**, so a cell-collapse bug can be seen.
5. **Consistency audit phases 1-4**, then its safe-mechanical, documentation and
   page-flow groups.
6. **Consistency audit phase 6, text correctness.** Seven wrong user-visible
   strings, all fixed; two open questions recorded rather than guessed at. The
   headline one: four spatial metrics labelled wind maps in `mm/h`, including on
   the Cartopy PNG itself. Every finding was a string that a later fix had
   falsified — see the pattern note at the end of `CONSISTENCY_AUDIT.md`.
7. **Consistency audit phase 5, typography.** Every font size and weight in
   `src/` now comes from `theme.js` — 72 size sites and 95 weight sites. Two
   rendered changes in total, both in `AboutModal`, both roundings onto the
   scale. **This closes the consistency audit: all six phases are run.**

---

## If you are picking this up cold

In priority order. Nothing here is half-done.

**Every model/variable in the database is now the run it claims to be**, as of
2026-09-30 (§24). That was not true for five of the nine combinations at
`2025-09-08 00Z` before then, and §20 had recorded two of them as already fixed.

**The written records now agree with it too**, as of 2026-10-01: `METRICS_AUDIT.md`
§0 is re-derived against `2025-09-16 00Z` — the only initialisation holding all
three models at both variables — and the planning documents are reconciled
against the code (§29). The re-derivation retracted the audit's own headline:
*"AIFS 3.4× better than either"* at wind compared one correctly-paired model
against two mislabelled ones, and the honest figure is **~21–27%**.

**That reconciliation claimed "nothing in the records is knowingly stale", and it
was wrong within the hour.** The "Where things stand" section above asserted
`flask_api.py` at 100% statement coverage; measured the same day it is **97%**,
54 statements short. §29 compared the planning documents against the *code* and
never ran the *measurement*, so a claim that only a measurement could falsify
walked straight through an audit designed to catch exactly that.

Worth keeping as the shape rather than the instance: **an audit only catches the
kinds of error it looks for.** Reading code against prose finds prose that
describes the wrong code; it does not find prose asserting a number nobody
computed. The second kind needs the number.

So: the records are reconciled against the code, and any claim resting on a
*measurement* deserves re-measuring before it is trusted.

0. **The reviewer deployment is the live task** (§10). **Both prerequisites are
   fixed as of 2026-09-17** — one origin behind one `basic_auth`, and pool
   defaults that are safe at every tier and checked at startup. What is left is
   not code: generate the password hash and point the hostname at the box. The
   Caddyfile is validated (Caddy v2.11.4, "Valid configuration"). **The host
   decision is also the data decision** — a fresh box starts with an empty
   PostgreSQL and the database is **58 GB** (re-measured 2026-09-28 after the
   raw-table unique keys, §19) — see §10.
1. **Nothing is blocked on a person any more.** PR #2 is merged (§1). What is
   left is either work, a decision that is yours, or blocked on data that is not
   in this repository — and each says which below.
2. ~~**Item 2, drop `regridded_forecast`**~~ **done 2026-09-02** (§2). 245 MB
   reclaimed; a 19 MB dump outside the repo is the only copy left.
   `observation_data` is *also* unread by the API. **The reason given here for
   leaving it alone — "raw ingested data no script here can regenerate" — stopped
   being true on 2026-09-16**, when `load_observations.py` began reproducing it
   bit-for-bit from the Explorer sources (§12). It is **13.54 GB**, 11% of the
   database, measured 2026-10-01. Still kept, and that is now a decision rather
   than a constraint: `regrid_observations.py` reads it to build the truth field,
   so dropping it would mean reloading before any future re-regrid. Revisit it if
   the retention threshold starts to bite.
3. ~~**The `observation_data` ingest — the largest real piece of work left.**~~
   **DONE 2026-09-16 (§12).** `Data/load_observations.py` reproduces all
   2,480,664 rows of the loaded run bit-for-bit from the sources on Explorer
   (§11), so a fresh clone can now build the truth field and `DEPLOY.md` §2b's
   promise of "forecasts and no truth" no longer holds. This also unblocks
   `DATA_EXPANSION_DESIGN.md` phase 4 and therefore a second run.

   **What it created was larger than what it closed.** The run's precipitation
   truth was stored **4 hours behind UTC** while its wind truth was not (§12),
   so every precipitation number the app and
   `METRICS_AUDIT.md` reported was misaligned in time. **Measured and then
   fixed, 2026-09-16** (§12): continuous errors fell 4–11% domain-wide and up
   to 67% at a point, UKMO's precipitation bias flipped sign, and FSS/CSI moved
   in *opposite directions by model* — so the shift had been changing which
   model looked better, not just inflating everyone's error. Wind was
   byte-identical, the control that confirmed it was IMERG's alone. The
   corrected field is live and the loader now reproduces both sources at its
   UTC default with no shift flag.
4. ~~**Re-derive `METRICS_AUDIT.md`.**~~ **done 2026-09-04.** Its §0 carries the
   current figures, generated by `Data/rederive_audit.py` with each number's
   parameters printed beside it; stale values in the body are marked in place.
   The root problem was that the original figures recorded no query, so several
   are not recomputable at all — that is now fixed for next time by the script
   rather than by another round of archaeology.
5. ~~**Item 6, the lower-priority list.**~~ **Empty as of 2026-09-22**, this
   time with nothing pending behind it: endpoint caching and row caps done, the
   Vite migration dropped, the CI actions bumped and the runners pinned. CI
   emits no annotations. The runner pin §6 asked a future reader to revisit was
   moved to `ubuntu-26.04` on 2026-10-02, ahead of the `ubuntu-latest`
   migration (§34) — which also found the reason the pin gave for itself was
   wrong.
6. ~~**`DATA_EXPANSION_DESIGN.md`: phase 5 only.**~~ **ALL FIVE PHASES ARE NOW
   CLOSED** — phase 5 decided 2026-10-01 (§27). History below.
   ~~Phase 3, the run-selector UI~~ **done 2026-09-24** — `RunProvider`, a header selector, and switch
   behaviour (invalidate, clamp lead time, grey out models a run lacks). Read
   that document's phase 3 for what shipped and the two departures from its
   sketch, then **§15 for what using it changed on 2026-09-25**: date and cycle
   instead of combined tuples, a date control that changes shape above 12 dates,
   and the two run-guard leaks that only appeared once a second run existed.

   **One part of it was not inert on the single run, contrary to the
   expectation recorded here for weeks.** Lead-time clamping is live now,
   because the three models have different ranges in the same run: +360h on
   AIFS clamps to +198h on UKMO instead of scrubbing to a lead time that
   returns nothing.

   **Phase 4 is done (2026-09-24).** The export convention is
   now recorded per run at load time and scoring reads it, so old and new runs
   can disagree about their divisors — which retires the standing warning that
   re-exporting GEFS needs `SCALED_EXPORT_DIVISOR_HOURS` edited in the same
   commit. Its item 1 — a
   regrid re-run duplicating rows — **is fixed too** (`5d45a29`); §13 has it.

   ~~**Then phase 5**~~ **DECIDED 2026-10-01 (§27).** Re-measured first and the
   arithmetic was low *again*, by about 50%: the database is **123.52 GB** over
   three initialisations and a three-model run is **55.30 GB**, so ten runs is
   **553 GB** and the 200 GB line that document warns about is crossed at
   **four** runs, not ten.

   **Retention: no limit yet, revisit at 250 GB** — two more full runs. The
   threshold is *enforced* rather than recorded: `_check_storage_headroom`
   reports it on `/api/health` and at startup, because "revisit at 250 GB" in a
   design document is read by whoever is already looking for it, never by the
   person about to start a 55 GB ingest. No archive tier is implemented, since
   nothing is evicted yet; the options are costed in that document.

   **Observations were the third decision and they are no longer a constraint**:
   89% of stored forecast-hours are scorable (4,220 of 4,752), and observations
   scale with the period covered rather than the run count.

### Open items with no owner

Three still open; the fourth is struck through, fixed 2026-09-02. The first two
are old, the last two came out of phase 6.

- ~~**`fbi` and `composite_confidence` are Analysis-only and nobody decided
  that.**~~ **DECIDED 2026-10-06 (§43):** FBI is in both surfaces; the composite
  stays Analysis-only on purpose, with a test pinning the absence.
- **UKMO coordinates are stored at two precisions** in `ensemble_statistics`
  (`35.1562` vs `35.15625`). **Re-characterised 2026-10-07 (§48)** — this used
  to read "wind and precipitation coordinates differ", which is a side effect
  rather than the thing. The split is **per load, not per variable**: the two
  09-08 precipitation loads wrote 5-decimal coordinates and everything loaded
  since wrote 4. Every run is internally consistent at 107 latitudes, and
  wind's runs all agree with each other.
- **The two tabs pool the point categorical metrics differently.** Analysis scores
  CSI/POD/FAR on the clicked cell alone; Comparison pools them over the whole
  `box_cells` box (default 9×9). Each says what it does and neither is wrong, but
  the same point at the same threshold gives two different CSIs. Phase 1 missed it
  because its matrix asked what is *available*, not which estimator produced it —
  the same blind spot as `METRICS_AUDIT.md` finding 8. A cross-reference now makes
  it visible; deciding which one is right is the actual work.
- ~~**The metric colour bands are precipitation-calibrated and wind uses them.**~~
  **Fixed 2026-09-02.** Measured first, per cell over the full domain and all
  three models (4,883 cells per metric): the mm/h edges put **79% of MAE cells,
  78% of RMSE and 86% of CRPS in "Poor"**, and the backend's `Normalize(0, 2)`
  clipped **45.5%** of cells at the top colour, so the PNG showed no structure
  where the variation was. Wind now has its own edges — MAE `1.0/2.0/3.5`, RMSE
  `1.2/2.5/4.0`, CRPS `0.7/1.5/2.8`, bias `±0.75/±2.5`, and plot norms out to
  5.0/5.5/4.0/±5.0 — giving no band under 19% and 6.8% clipping.

  Two things to know before touching them. **They are absolute, not quantiles**:
  exact quartiles were computed and deliberately rejected, because a quantile
  band reads "worse than three quarters of this run" while the label says
  "Poor", so every run would report 25% Poor cells however good it was. And the
  numbers are anchored on the meteorology (~1 m/s good, 3.5+ poor), not on this
  run — whose errors are on the high side, whose verification reaches only +23 h,
  and whose domain is mostly ocean. Re-deriving the edges from another run would
  be re-calibrating to its difficulty. `WIND_BAND_BASIS` in `src/constants.js`
  carries the measurement; `WIND_PLOT_STYLE_OVERRIDES` in `flask_api.py` is the
  server-rendered half. Dimensionless metrics (CSI, POD, FAR, SSR, correlation)
  deliberately have no override and a test pins that they fall back.

### Traps

- **Never trust a summary of the numbers — re-measure.** Writing
  the (since deleted) reviewer's guide found a live defect (`fss` alone returned
  nothing) purely by re-running the figures. Two of my own conclusions in these documents were wrong
  and are marked as retracted; do not quietly "clean up" a retraction.
- **`regridded_forecast_ens.std_dev` is a true ensemble spread** (nanstd over
  regridded members, ddof=1). The "pooled member x native-cell, ~23% high" story
  belongs to the superseded `regridded_forecast`. See §3b.
- **A refactor can hollow out a test instead of failing it.** Two tests filtering
  on `lat == 35.0` passed vacuously once UKMO moved to a grid with no cell there.
  Assert non-emptiness first.
- ~~**Cartopy drops coverage's tracer** partway through both render functions, so
  ~120 executed lines read as uncovered. Do not chase it.~~ **Retracted
  2026-08-21 — it was chaseable.** True of coverage's default C tracer, which
  Cartopy's extension modules disturb; false of the `sys.monitoring` backend
  added in Python 3.12. `Data/.coveragerc` now sets `core = sysmon`, which
  reclaimed 58 lines with no code change and no pragma, and both render bodies
  are traced for real rather than inferred from the PNG assertions. The original
  caveat returns on Python < 3.12, where coverage falls back to the C tracer.

  Worth keeping as a lesson rather than deleting: "do not chase it" was written
  after a real investigation and was accurate about the tool available at the
  time. A trap can go stale the same way a comment can.
- **A comment or label that was right when written is the most likely thing to be
  wrong now.** Every one of phase 6's seven findings was accurate at the time and
  falsified later by a fix elsewhere — the code moved, the sentence did not. When
  you change behaviour, grep for the strings that described the old behaviour, and
  prefer a test on the *invariant* over a test on the wording: a test that asserts
  a sentence gets rewritten by the same change that breaks it.
- **Grep the rendered result, not the source, to ask "is any of this left?"**
  Phase 5's exit grep (`fontSize: '`) came back clean while a 17px literal was on
  screen, because it was inside a ternary; four more hid in SVG attributes. A
  computed-style sweep of the running app found all of them in one call. The
  source grep answers a narrower question than it looks like it does.
- **`t` is the design token, imported in 16 files.** Do not shadow it. Two legends
  and `App.js` used it as a local (`const t = setTimeout(…)`, map callbacks); those
  are renamed. A shadowed `t` compiles, passes the suite, and fails at render.

---

## 1. Merge PR #2 — MERGED 2026-09-02

Merge commit `49ead8f`, with **all 90 commits preserved** (`--merge`, not
`--squash`): the individual messages carry most of the reasoning, and several
record why an approach was abandoned. `main` went from 35 to 125 commits.

**Merged without review**, after the request sat 6 days unacted-on. The merge
commit body says so, and records the pre-merge SHAs — `main` was `41e9dfa`, head
`d7c03f0` — so a revert has something to aim at. CI was green on all four checks.

`REVIEW_GUIDE.md` is **deleted**, as it always said it should be after merge. It
was written to make one review tractable and its header figures were stale within
days. Nothing durable was lost: everything in it was either already recorded
elsewhere or is now, and the one genuinely unique item — which two branches carry
`# pragma: no cover` — is in the list under "Where things stand" above.

Two side effects of merging worth knowing:

- **It unbroke `main`.** `main` had been failing against `weave_weather` since the
  2026-08-27 rename, because it read `regridded_forecast`. It no longer does.
- **`WEAVE_v2` and `WEAVE_presentation` are still broken** the same way, and
  merging did nothing for them. They read the renamed table and no version of
  them does not. Retire them, repoint them, or rename the table back.

**And the trap this cost an hour to find.** A long-running Flask process started
2026-08-26 was still holding port 5000 with pre-rename code *loaded in memory*,
returning 500 from `/api/spatial-metric` and 404 from `/api/runs` while the code
on disk was correct. Checking a running server's `cwd` or its files tells you
nothing about what it imported at startup: **restart every server after a schema
change.** A stale webpack cache did the same thing to the dev server after a
branch checkout swapped 78 files under it — `rm -rf node_modules/.cache`. In both
cases the code was fine and only a process disagreed.

**The same trap from the other end, 2026-09-28: a server can outlive the tool
that started it, and then "nothing is running" is wrong.** The editor's preview
manager listed no live servers while `flask_api.py` still held port 5000 with
**`PPID 1`** — orphaned when its manager went away, so asking that manager to
stop it was a no-op. It had been holding its connection pool open
(`DB_POOL_MIN=2`) the whole time, and would have made the next start fail as a
port conflict rather than an obvious "already running". **Ask the port, not the
process manager:**

```bash
lsof -nP -iTCP:5000 -sTCP:LISTEN
```

Then kill the reloader parent and its child.

## 2. Drop the superseded table — DROPPED 2026-09-02

245 MB and 1,499,977 rows, superseded by `regridded_forecast_ens`, which carries
a true ensemble spread derived from `regridded_forecast_member`. It was kept only
so the old and new numbers could be compared, and that comparison is done and
written up.

> **State: dropped.** Sequence, over six days: its last reader in this repo
> became a constant (2026-08-27), `schema.sql` stopped creating it (2026-08-27),
> it was renamed to `regridded_forecast_deprecated` rather than dropped
> (2026-08-27), the rename sat for six days to flush out a reader no search could
> reach, PR #2 merged so `main` stopped reading it (2026-09-02), and then
> `DROP TABLE` (2026-09-02).
>
> **A dump was taken first**, because unlike `_ens` and `_member` this table had
> **no writer anywhere in the repository** — it was produced off-repo, so nothing
> here could rebuild it. 19 MB gzipped, all 1,499,977 rows plus the DDL:
>
> ```
> ~/Documents/AFW/regridded_forecast_deprecated_2026-09-02.sql.gz
> ```
>
> That file is the only copy. It is outside the repo deliberately — 19 MB of
> superseded data does not belong in git — which also means nothing backs *it*
> up. If the old numbers ever matter again, restore with
> `gunzip -c <file> | psql -d weave_weather`.
>
> **`WEAVE_v2` and `WEAVE_presentation` can no longer serve from this database,
> permanently.** They query the old name, no version of them does not, and they
> were already failing since the rename. That was the accepted trade, made
> knowingly.
>
> Verified after dropping: `/api/health` healthy with convention `ok`,
> `compare/skill` still returning AIFS 0.0918 / GEFS 1.9413 / UKMO 0.0831,
> `/api/runs` answering, `regrid_members.py --verify-grid` degrading to
> `regridded_forecast: absent, skipped` as designed, and 649 tests passing.
>
> The consumer table below is kept as the record of why this was never a
> one-line cleanup — and of this section having twice claimed "nothing reads it"
> and been wrong twice.
>
> The consumers that made this more than a cleanup, all pointed at the same
> `weave_weather` database (checked in each one's `.env`):
>
> | consumer | reads | note |
> |---|---|---|
> | `origin/main`, this repo | 6 | the merge target for PR #2 |
> | `WEAVE_v2/Data/flask_api.py` | 6 | `DB_NAME=weave_weather` |
> | `WEAVE_presentation/Data/flask_api.py` | 14 | `DB_NAME=weave_weather` |
>
> On `main` the readers are `_fetch_fcst_obs_pairs_spatial` plus
> `/api/compare/timeseries`, `/api/compare/skill`,
> `/api/compare/spatial-agreement`, `/api/categorical-metrics` and
> `/api/region-categorical-metrics` — the core of the app. The single shared
> helper differs by exactly one line between branches:
>
> ```
> origin/main:      FROM regridded_forecast
> p0-reliability:   FROM {_frm}   ->  regridded_forecast_ens
> ```
>
> `origin/comparison-tab` and `origin/phase2-restructure` read it too; only
> `origin/kartik` is clean, being frontend-only. Merging PR #2 clears `main`;
> it does nothing for `WEAVE_v2` and `WEAVE_presentation`, which need retiring
> or repointing on their own.
>
> The class of reader the rename exists to catch is the one no search can reach:
> an ad-hoc `psql` session, a notebook outside this tree, something on the HPC.
> A `DROP` would have hidden those behind a permanent 245 MB loss.

**This section has now claimed "nothing reads the table" twice, and been wrong
both times.** Worth reading as a pattern rather than two mistakes:

1. The first version said it while `regrid_members.py`'s `target_grid` was
   reading `SELECT DISTINCT latitude/longitude FROM regridded_forecast` to decide
   which cells to interpolate onto — so the table was still defining every scored
   cell in the app. Two consequences that a grep for readers would have caught
   and the sentence hid:

   - **Nothing in this repo writes `regridded_forecast`.** On a fresh database
     the query returned nothing and the script died on the next line printing
     `tgt_lats[0]`. `regrid_members.py` could never have run on a new deployment.
   - **The fix this section recommended would have made that permanent.**
     Repointing the lookup at `regridded_forecast_ens` points it at
     `regrid_members.py`'s *own output*: empty on the first run, and thereafter
     keyed on the union of whatever native hulls have been regridded rather than
     on the canonical grid. Cells outside a model's hull are never written, and
     UKMO's native grid stops at 25.0312–44.9062 / −84.7969 to −65.1094, so a
     `_ens` holding UKMO alone gives 39×39 spanning 25.5–44.5 and silently clips
     AIFS and GEFS to UKMO's footprint on the next run — 160 cells per
     model/variable/hour, no error.

2. The second version — written 2026-08-27, after that was fixed — said it again,
   and was wrong for a completely different reason: **it was scoped to this
   branch without saying so.** `p0-reliability` genuinely has no reader; `main`,
   `WEAVE_v2` and `WEAVE_presentation` have twenty-six between them. Nothing in
   the sentence was false about the working tree, and it was still dangerous,
   because the instruction attached to it was a destructive `DROP` against a
   database three other consumers share.

**The lesson, which is the reusable part:** "nothing reads X" is not a property
of a working tree. Before writing it, ask *whose* code and *which* database — the
right check is every branch (`git grep X $(git branch -r)`) and every app copy
pointed at the same `DB_NAME`, not `grep` in the current checkout. A drop is also
not undoable, so the claim has to be true of everything holding a connection, not
just of the thing you happen to be editing.

The grid was never a discovered quantity, only an undocumented one:
`TARGET_LAT_RANGE`, `TARGET_LON_RANGE` and `TARGET_RESOLUTION` in
`regrid_members.py` now state it as 25–45 N, −85 to −65 W at 0.5°, 41×41. 0.5 is
exact in binary, so this reproduces the stored coordinates bit-for-bit rather
than approximately — verified against all three regridded tables on the loaded
run, and `--verify-grid` re-runs that check against whichever still exist.
`test_regrid_grid.py` pins the values, and pins that `target_grid` takes no
cursor, because the source was the bug rather than the numbers.

The code side is **done as of 2026-08-27**: `schema.sql` no longer creates the
table and `add_indexes.sql` no longer indexes it, so a fresh install never gets
one. Verified by applying both files to a throwaway database and then running
`regrid_members.py --verify-grid` against it — the script gets its 41x41 grid,
creates `_ens` and `_member` for itself, and exits 0, where the old lookup gets
`ERROR: relation "regridded_forecast" does not exist`. That is the fresh-install
path working for the first time.

**What is left is not a code change.** It is the rename-then-drop above, and it
waits on PR #2 merging plus a decision about `WEAVE_v2` and `WEAVE_presentation`.
Nothing in this repository needs touching for it either way: `verify_grid` reads
the table when present and prints `absent, skipped` when not, and the fixture
database already builds from `schema.sql` and passes without it (630 tests).

**How the "not used" claim was established for this branch**, so the next person
can re-run it rather than trust it:

- Every table name after `FROM`/`JOIN` in `flask_api.py`, enumerated:
  `ensemble_statistics`, `forecast_data`, `forecast_runs`, `models`,
  `regridded_forecast_ens`, `regridded_forecast_member`, `regridded_observation`,
  `variables`. The bare table is not among them.
- **The dynamic-SQL hole closed**, which a plain grep misses. Five sites build
  `FROM {_frm}`; `_frm` comes only from `_fcst_speed_sql`, which returns two
  hard-coded literals, both `regridded_forecast_ens`. No other constructed table
  name exists in `Data/*.py`.
- **Runtime, not just static:** the fixture database no longer creates the table
  (`to_regclass` → NULL) and 17 of the 18 endpoints run against it. Any reader
  would fail with `relation does not exist`. The 18th,
  `/api/compare/categorical`, issues no direct SQL — it goes through
  `_fetch_fcst_obs_pairs_spatial` and `_region_metric_points`.
- **Database objects:** no views, matviews, functions, triggers or rules mention
  it, and no inbound foreign keys. The only dependents are its own two indexes,
  its toast table and its sequence.
- **Not certifiable this way:** anything leaving no trace in the repo or the
  catalog — an ad-hoc `psql` session, a notebook elsewhere, something on the HPC.
  That is what the rename week is for.

## 3. A fixture-database test layer  ← DONE (2026-08-19)

`flask_api.py` went from **41% to 83%** statement coverage here, and to **99%**
once the error, input and guard paths were covered on 2026-08-21. The caveat this
paragraph used to carry — that the real figure was a little higher because
Cartopy drops coverage's tracer — is gone: switching coverage to the
`sys.monitoring` backend traces those render bodies directly, so the number no
longer needs an asterisk.

- `Data/fixture_db.py` builds `weave_fixture_test` from the real schema
  (`schema.sql` + the DDL in `regrid_members.py`, read from source so a new
  column cannot be forgotten) and seeds one 5×5 patch of the 0.5° grid.
- `Data/test_db_endpoints.py` drives every endpoint against it, including the
  three Cartopy renders and the connection pool.
- Both skip themselves without PostgreSQL (`WEAVE_SKIP_DB_TESTS=1` to force it),
  so `python -m pytest -q` still runs anywhere: 176 pass, 107 skip.

**The load-bearing idea.** All three models get the *same true field*, each
expressed in its own storage convention — AIFS cumulative, GEFS pre-divided by a
flat 3 h, UKMO a native hourly rate. So they must produce identical scores, and a
regression in the unit or window layer breaks exactly one model and the test says
which. The scene is arranged so every number is hand-derivable: bias 0.8, MAE 1.4,
RMSE √2.3, CSI 0.6, POD 0.75, FAR 0.25 for precipitation; the wind spread grows on
exactly the schedule its error grows on, so the spread-skill correlation is
exactly +1 (a *signed* anchor, which a constant field cannot give). Observations
stop at +12 h against records running to +36 h, reproducing the real run's shape.

The storage conventions are restated in `fixture_db.py` rather than imported from
`metrics.py`, on purpose: seeding with the code under test would let a wrong
divisor cancel itself out.

### What it found

Seven defects, none of which the 174-test suite could see. **All seven are now fixed.**
Each was first written as a strict `xfail`, so the suite stayed red until the
marker came off — the fix and its test landed together. They are regression tests
now, in `TestFormerDefects` and alongside the behaviour they cover.

1. ~~**`/api/compare/skill` labels wind in `mm/h`.**~~ **Fixed.** `units` was
   hard-coded for every variable; it now branches on the variable, the same way
   `/api/spread-skill` always did. User-visible, and exactly the class of error
   CONSISTENCY_AUDIT_PLAN phase 6 is for.
   Test: `test_every_endpoint_labels_wind_in_metres_per_second`.
2. ~~**The earliest verification window was short by an hour of observations.**~~
   **Fixed.** The point path fetched from `min(valid_time) - (max_period - 1)`
   where the spatial path uses the full `max_period`. That is sufficient for
   observations on the hour and not for half-hourly IMERG, so the earliest
   window's first sample was never fetched and that lead time's observed rate was
   a mean over 11 of its 12 samples, weighted toward the end of the window. On the
   loaded run at 36.0/−75.5 the +6 h observed rate moves from 0.025947 to
   0.025035 mm/h (a 3.6% overstatement of the truth, which understated the model's
   wet bias); every later lead time is unchanged, and wind was never affected
   because its records span one hour.
   Test: `test_the_earliest_window_uses_every_observation_in_it`, which pins the
   point and spatial paths to the same count.
3. ~~**An hourly model can never produce a precipitation correlation.**~~
   **Fixed by the member-grid migration — see below.** Worth reading the wrong
   first diagnosis, because it is a good example of a real signal misread as to
   cause: `_compute_correlation_points` only queried hours that are multiples of 6,
   and tiling a 6 h window does need six consecutive hourly records — but widening
   the fetch does not help. The re-bin then produces the window and sets
   `std_rate = None`, because the spread of a mean is not the mean of spreads and
   `_rebin_to_common_window` refuses to guess it. Verified directly:
   `_rebin_to_common_window` on an hourly series gives `{6: (3.0, None, 6), …}`
   against AIFS's `{6: (3.0, 0.25, 6), …}`. Re-binning each MEMBER first and
   pooling afterwards is the only sound fix.
4. ~~**`/api/point-timeseries` leaks spatial variance into the wind cone.**~~
   **Fixed.** The precipitation branch took the nearest cell (finding 11); the wind
   branch aggregated in SQL over every cell within `radius`, used `STDDEV`
   (sample) where precipitation used the population spread, and omitted
   `n_members`. Both variables now run one code path — raw members, nearest cell,
   population spread — differing only in how a member's value is derived (raw, or
   √(u²+v²) per member) and whether de-accumulation applies.

   On the loaded run at 36.0/−75.5, +0 h, `radius=0.5`: the wind band was **28%
   too wide** (std 2.9243 → 2.1009), which is spatial variance that was being
   presented as ensemble spread. The cone no longer changes with `radius` at all —
   before, 0.5 and 0.1 gave different answers for the same point. `n_members` (50)
   and `cell` are now reported, and precipitation's numbers are byte-identical.
   Percentiles moved marginally (p10 10.1891 → 10.2285): nearest-rank now, matching
   precipitation, rather than `PERCENTILE_CONT`'s interpolation.
5. ~~**`n_points['fss']` is 0 next to a real FSS value.**~~ **Fixed.** The count
   was of per-cell map points, and FSS has none by design, so a caller using it to
   decide whether a score was populated hid a valid one. FSS is a property of the
   whole field at each lead time, so it now reports the matched cells behind it (35
   on the loaded run, matching `n_cells`). Honest in the other direction too: UKMO's
   absent CRPS still reports 0, so a real `fss` of 0.0 — which AIFS has on that run
   — is now distinguishable from no data.
6. ~~**The correlation map's cell values are order-dependent for UKMO.**~~
   **Fixed by the member-grid migration**, which removed the 0.25° snap entirely.
   Found while attempting 3: the old path keyed its per-cell series on a 0.25°
   snap, but UKMO's native grid is 0.1875° — 35.15625 and 35.34375 are different
   cells and both snap to 35.25, so **110 native cells collapsed onto 77 keys**,
   each keeping the *first* row's coordinates with the *last* row's values, from a
   query with no `ORDER BY`. Batching the per-hour queries (logically identical)
   shifted that row order and moved every UKMO wind value, which is how it
   surfaced. The member grid is already on the shared 0.5° grid, so cells are now
   keyed at 2 dp like every other scored path and there is nothing to collapse.

   Still latent, unrelated to the above: in `ensemble_statistics`, UKMO **wind**
   rows sit at float32-rounded coordinates (`35.1562`) and UKMO **precipitation**
   rows at exact ones (`35.15625`), because two different loaders wrote them.
   Nothing joins across variables today, so nothing is broken — but any such join
   would match zero rows, silently.

7. ~~**Requesting `fss` alone returned nothing.**~~ **Fixed.** No value,
   `n_cells: 0`, and a warning that the grids did not overlap — none of it true,
   since `mae` over the same box returned 35 cells. `_region_metric_points` skipped
   the fcst↔obs fetch unless a metric with a *per-cell function* was requested, and
   FSS has none, being a property of the whole field. `correlation` alone drew the
   same false warning, since it comes from the member path and needs no pairs
   (fixed with `pairs_needed` at the warning).

   Found while fact-checking the reviewer's guide — a good argument for writing the
   numbers down and then re-measuring them. The existing FSS test co-requested
   `mae`, so it passed; the replacement asks for **each metric on its own**. Nine of
   the ten always worked and only the combination was broken, which is the kind of
   gap a per-metric loop catches and a hand-picked pair does not.

Two non-defects worth not re-deriving, now pinned by tests:

- **UKMO precipitation has no CRPS, Brier or SSR at all.** Re-binning an hourly
  model onto the common window combines records, and the spread of a mean is not
  the mean of spreads, so the spread is dropped rather than guessed. AIFS and GEFS
  emit 6 h records natively and keep theirs. Correct, but it means one of three
  models silently has no probabilistic precipitation scores — parity material for
  CONSISTENCY_AUDIT_PLAN phase 1.
- **Pooled RMSE (1.5166) and the mean of per-cell RMSE (1.4) are different
  numbers** and both are reported (finding 8). √ is not linear. Confusing them is
  how a headline stops matching its own map.

---

## 3b. The member-grid migration — DONE (2026-08-19)

`/api/spread-skill` reads `regridded_forecast_member`; **the spatial maps never
did**, so the Analysis map and the Analysis point panel answered the same question
from two different tables. This finishes it.

**Correction, made 2026-08-20.** This section originally justified the migration
with finding 11 — that the aggregate `std_dev` is a pooled (member × native-cell)
spread carrying within-cell spatial variance, ~23% high. That is true of
`regridded_forecast` and **false of `regridded_forecast_ens`**, whose `std_dev` is
`nanstd(members, ddof=1)` over the regridded members and equals their sample
spread exactly (verified: ratio 1.0000 at every cell checked). The migration was
still right, for two reasons that are larger than the retracted one:

- **A cumulative model's increment spread is not recoverable from stored totals.**
  The aggregate path approximates it as √(σ(h)² − σ(h−p)²), which assumes
  independent increments and goes negative for ~13% of AIFS records. At
  36.0/−75.5, +12 h that is √(0.2128² − 0.1511²) = 0.1499 against an exact 0.1144
  — 31% high, and it matches the old endpoint's output to four decimals.
- **Re-binning destroys the spread outright**, so an hourly model had none on the
  common window and every spread metric came back empty.

Plus a minor third: the stored spread is a sample one (ddof=1), the member path
computes the population one — √(n/(n−1)), so 1.010 for AIFS and 1.017 for GEFS.

`_member_cases_by_cell` is now the single implementation behind `/api/spread-skill`
and both spread-dependent maps (`metric=ssr`, `metric=correlation`). `_compute_
ssr_points` and `_compute_correlation_points` are thin wrappers over it, and
`_ensemble_speed_rows` is gone. Nothing reads the sparse `observation_data` table
any more — truth comes from `regridded_observation` over the window each record
spans, like every other scored endpoint.

What changed, measured on the loaded run over 35–37 N, 77–74 W:

- **The map and the panel now agree exactly.** At 36.0/−75.5, +6 h, both report
  SSR 1.0232 (AIFS), 0.4486 (GEFS), 1.9973 (UKMO). They disagreed before.
- **UKMO precipitation correlation exists at all**, 35 cells at a mean of +0.48,
  where it was permanently empty (defect 3).
- **All three models now return the same cell count** — the 0.25° collapse is gone
  (defect 6).
- **+0 h precipitation is now empty for every model**, where AIFS and GEFS returned
  nothing and UKMO returned a full map. UKMO's 1-hour record at +0 h covers
  (−1, 0] — before initialisation — and was being scored against a single
  instantaneous observation. Two models blank and one full at the same lead time
  was the clearer symptom. Wind is instantaneous and keeps +0 h.
- **Wind speed is now exact per member** — √(u²+v²) per member, rather than the
  |mean vector| approximation the aggregate table forces.

Performance had to be dealt with, because the member grid is members × cells ×
hours. The naive migration made the full-domain map 9–65× slower (5.8 s → 54.6 s
for SSR, 1.0 s → 65.7 s for wind correlation). Three fixes, and it now beats the
old code:

| full domain | before migration | naive | now |
|---|---|---|---|
| `ssr` precipitation, AIFS | 5.80 s | 54.65 s | **1.06 s** |
| `ssr` wind, UKMO | 4.53 s | 65.54 s | **0.50 s** |
| `correlation` wind, UKMO | 0.98 s | 65.67 s | **2.03 s** |
| `correlation` precipitation, UKMO | (empty) | 52.06 s | **4.97 s** |

1. `_window_source_hours` prunes the query to the records each target is built
   from, instead of fetching every lead time to score one.
2. `_observation_record_end` drops targets past the end of the truth *before*
   querying forecasts that could never be scored.
3. The wind u/v pairing moved out of SQL into a dict. The join predicate includes
   `ensemble_member`, which `idx_rfm_lookup` does not cover, so the planner
   rescanned every member of a cell per probe — two index range scans and a hash
   are ~20× faster. (An index covering `ensemble_member` would also work; not
   adding one to avoid a migration on a 9.7 M-row table for no further gain.)

One deliberate difference remains, documented in the function: the **map**
correlates over `CORRELATION_LEAD_HOURS`, a fixed set, so models stay comparable —
an hourly model would otherwise be correlated over 24 samples beside a 6-hourly
model's 4, and the region view puts those side by side. The **panel** still uses
every native lead time, because it describes one cell rather than comparing
models. They agree on spread, error and SSR at any shared hour; only the
correlation's lead-time set differs. Worth settling in
CONSISTENCY_AUDIT_PLAN phase 1.

Frontend: `MetricPanel`'s lead-time buttons were `[0, 6, 12, 18]` for both
variables, and `+0h` is now structurally empty for precipitation, so they are
variable-aware (`[6, 12, 18, 24]` for precipitation, unchanged for wind) with a
guard that re-selects a valid lead time when the variable changes. Verified in the
browser: both sets render, the guard snaps `+0h` → `+6h` on switching to
precipitation, and the maps draw (36 precipitation cells at +6 h, 54 wind cells at
+0 h) with a clean console.

### What the fixture cannot see

Worth knowing before trusting a green run, and worth fixing if this layer is
extended:

- ~~**It is on one clean grid.**~~ **Fixed (2026-08-19).** The regridded tables are
  on the shared 0.5° analysis grid, as before; the pre-regrid tables are now on each
  model's own native grid, measured from the loaded run: **AIFS 0.25°, GEFS 0.5°,
  UKMO 0.1875° × 0.28125° and aligned to neither**. UKMO's 10 native latitudes
  collapse onto 7 keys under a 0.25° snap — latitude does because 0.1875 < 0.25,
  longitude does not because 0.28125 > 0.25 — so the fixture can now see the defect
  6 class, and `test_the_fixture_can_actually_see_a_collapse` fails if that
  property is ever seeded away. It also reproduces the coordinate-precision split
  (UKMO wind at `35.1562`, precipitation at `35.15625`).

  Two things this bought beyond insurance. `/api/point-timeseries`' nearest-cell
  choice now has **more than one candidate** — two UKMO cells straddle the band
  boundary at 36.25 carrying 3.0 and 0.5 mm/h, and a 0.02° move flips the answer,
  so `min(cells, key=distance)` is exercised for the first time. And "all three
  models score identically" now means something much stronger: their native grids
  differ by nearly 3× in cell count (81 / 25 / 70) and every score still comes back
  on the same 25 analysis cells.

  The enabling change was making the field a function of latitude
  (`precip_scene`) rather than a dict keyed by exact cell, so it can be evaluated
  on any grid. Being piecewise constant over the analysis bands, it regrids to
  itself, so no second truth was introduced. **Lesson worth keeping:** the refactor
  silently hollowed out two tests that filtered by exact latitude — they became
  vacuous rather than failing, since UKMO has no cell at 35.0. Both now match by
  band and assert non-emptiness first.
- ~~**The aggregate and member tables agree by construction.**~~ **Fixed** while
  doing the migration above: `ensemble_statistics` is now seeded with a spread
  `NATIVE_SPREAD_INFLATION` (2x) the true ensemble spread, with the member values
  left exact — a faithful model of what finding 11 says about the real data, and
  what lets a test tell *which* table an endpoint read. `test_the_map_and_the_
  point_panel_report_the_same_ssr` could not exist without it.
  `regridded_forecast_ens` still agrees with the members, since the pairs-based
  metrics that read it were not migrated.
- **Precipitation is flat in lead time**, which is what makes bias/MAE/RMSE exactly
  derivable — and also makes its spread-skill correlation degenerate (zero
  variance in both series). The correlation arithmetic is proved on wind instead,
  where the fixture makes spread track error for an exact +1. A metric needing
  *both* an exact flat score and a non-degenerate correlation on the same variable
  cannot be tested against this fixture; put the variation on the other variable.

## 4. Surface observation coverage in the UI — DONE (2026-08-19)

Truth exists only to fh ≈ 23.5 for the loaded run. Beyond that, verification
correctly returns nothing — but a user scrubbing to +48 h saw an empty panel and
could not tell that from a bug.

Every scored endpoint could already say that a *particular* query found no
observations, and two panels rendered that message. What none of them could say is
where the truth *ends*: the messages were all reactive, and the extent appeared
nowhere. So `/api/observation-coverage` now reports it up front —
`record_end_lead_hours` (23.5 on the loaded run) and `last_verifiable_hour`, the
last lead time that can actually be scored. Those differ, and the difference is
physical: a precipitation record needs its whole 6 h window observed, so
precipitation stops at **+18 h**, while wind is instantaneous and reaches **+23 h**
on its own ERA5 record. The UI shows both correctly.

Surfaced in three places, in order of how early the user meets them:

1. **The timeline** — the track past `last_verifiable_hour` is hatched, with a
   `verified to +18h` marker on the lead-time axis. This is the one that matters:
   it is on the control the lead time is chosen with, so the limit is visible
   before anything is clicked.
2. **The lead-time readout** — `beyond verification (+18h)` appears beside the
   valid time whenever the selected hour is past the record, and clears when it
   is not.
3. **The Analysis spread-skill empty state** — now names the extent
   ("GPM_IMERG_V07B observations for this run end 23.5h after initialisation, so
   verification is available to +18h") instead of the generic "no overlapping
   observations".

`test_the_coverage_endpoint_promises_what_the_scores_deliver` ties the promise to
the behaviour: `last_verifiable_hour` must equal the last lead time
`/api/compare/skill` really does score. A coverage endpoint that drifts from the
scoring endpoints would be worse than none.

Also removed, while wiring this: `Timeline.jsx` had the initialisation time
**hard-coded** as `2025-09-08T00:00:00Z`, so every "Valid …" timestamp would have
silently lied the moment a second run was loaded. It now comes from
`init_time` in the coverage response, with the old constant kept only as a
fallback. That is one less thing for DATA_EXPANSION_DESIGN.md to trip over.

## 5. Two planned pieces of work, with their own documents

- **`CONSISTENCY_AUDIT_PLAN.md`** — **done; all six phases are run and closed**,
  and results and every finding are in `CONSISTENCY_AUDIT.md`. Phase 2 found no
  wind/precipitation gap at all, which the plan did not expect; the real gap was
  in phase 1 (no accuracy metrics at an Analysis point) and is fixed. Phase 6 then
  found the wind gap the plan had been looking for, but in the *text* rather than
  the capability — four metrics labelled wind in `mm/h`. Phase 5 put every font
  size and weight on `theme.js`'s scale. **Treat the plan as history now**: two of
  its instructions were obsolete by the time they were run (it says to add a type
  scale that already existed, and its holdout list predates several components),
  and its phase-5 exit grep passes while a literal is still on screen. The audit
  document is the live record; the plan is what was believed beforehand.
- **`DATA_EXPANSION_DESIGN.md`** — selecting date and initialisation. **Phases
  1–4 are done as of 2026-09-24**, so the two blockers this entry used to name
  are both gone: `init_time` exists and no query resolves valid time from "the
  latest run" (§8), and `observation_data` has a loader (§12). That document's
  "do not load a second run" rule is retired, and a second run is loaded (§14).
  **Only phase 5 (scale and retention) is left, and it is three decisions rather
  than a build.** Like the audit plan above, treat its phase text as what was
  believed beforehand: three of its instructions were superseded by what
  shipped and are marked against each phase.

## 6. Lower priority

- ~~**Bump the GitHub Actions off the deprecated Node 20 runtime.**~~
  **done 2026-09-22.** `checkout` v4→**v7**, `setup-node` v4→**v7**,
  `setup-python` v5→**v7**, `cache` v4→**v6**, `upload-artifact` v4→**v7**. No
  step inputs changed, all four jobs green, and the Node 20 annotations are
  gone — which is the check that matters, since a local YAML parse cannot see a
  broken input.

  **Take the versions from the releases API, not from memory.** The current
  majors were several ahead of what I would have guessed, and guessing would
  have bumped to versions that were themselves already deprecated:

  ```bash
  for r in actions/checkout actions/setup-node actions/setup-python \
           actions/cache actions/upload-artifact; do
    printf '%-26s ' "$r"; gh api "repos/$r/releases/latest" --jq .tag_name
  done
  ```

- ~~**`ubuntu-latest` migrates to Ubuntu 26 from 2026-10-19.**~~ **Pinned to
  `ubuntu-24.04` on 2026-09-22, bumped to `ubuntu-26.04` on 2026-10-02 (§34).**
  The migration would otherwise have happened **on a date nobody chose, attached
  to whatever push happened to be next**. Pinning does not avoid it; it makes it
  a deliberate commit whose diff points at the cause — which is exactly how the
  bump landed.

  **The justification written here was wrong**, and §34 corrects it rather than
  deleting it. It said the backend job `apt-get install`s `libgeos-dev`,
  `libproj-dev`, `proj-data` and `proj-bin` and that "Cartopy links against GEOS
  and PROJ", so an image change would move those versions underneath the render
  tests. Cartopy's compiled extension declares no GEOS or PROJ at all: shapely
  and pyproj bundle their own, as the manylinux policy requires. The pin is a
  general caution about runner images, not that specific guard.

  24.04 is what `ubuntu-latest` resolved to already, so nothing about the run
  changed — confirmed: all four jobs green and **CI now emits no annotations at
  all**, for the first time in a while.

  **The cost, so it is not a surprise later: a pin ages.** 24.04 is supported
  into 2029, but this is now something to revisit rather than something that
  maintains itself. The reason lives in the workflow header too, so whoever
  changes it does not have to find this document first.

- ~~**Vite migration**~~ **dropped 2026-09-21.** A decision, not an oversight,
  so it is struck through rather than deleted — otherwise it reappears the next
  time someone notices the toolchain.

  **What staying on CRA costs**, stated once so it is not rediscovered as a
  surprise: `react-scripts` is unmaintained, so the build toolchain receives no
  upstream fixes and `npm audit` findings in build-time dependencies cannot be
  cleared by upgrading it. Those are build-time, not served to users, which is
  what makes this a defensible call for a short-lived reviewer beta. It becomes
  a real problem only if this app acquires a long production life.

  Two consequences that stay live either way: the **stale `node_modules/.cache`**
  trap in §1 is CRA's, and it has already cost an hour once; and the build job's
  warnings-as-errors is what keeps the CRA build from decaying quietly.
- ~~**Cache the deterministic metric endpoints**~~ **done 2026-09-04.** 382x on
  a warm request. The cache key includes a fingerprint of the truth field, so
  both truth-field swaps since (§7, §12) invalidated it automatically rather
  than serving stale scores. **This is what the references to "§9" elsewhere in
  this document meant** — there has never been a section 9; the work was
  recorded here. Those references now point at §6.
- ~~**Row caps on point-list queries**~~ **done 2026-09-04.**
  `POINT_LIST_MAX_CELLS` (default 20,000) bounds `/api/forecast-data` and
  `/api/wind-data`, whose size is set by the native grid rather than by anything
  in the request — today's worst case is UKMO wind at 7,597 cells and 946 KB, so
  the cap is inert now and exists for a finer model or wider domain. Two details
  are load-bearing: it trims **whole cells** (forecast-data returns one row per
  (cell, hour) and groups afterwards, so a plain row `LIMIT` would return a cell
  computed from a partial series — wrong rather than short), and it reports
  truncation in headers plus a server log line, because a shortened map looks
  complete. No "showing N of M": the query reads `limit + 1` so overflow is
  cheap to detect, which means the only total available is `limit + 1` — an
  earlier version reported that and said "100 of 101" where the real total was
  7,597.

---

## 7. The observation regrid, and a defect in the current truth field

**New 2026-08-27.** `Data/regrid_observations.py` box-averages `observation_data`
onto the 0.5° grid, so `regridded_observation` — the truth field behind every
scored endpoint — can be produced from this repository for the first time.
DEPLOY.md §2b now runs it. **`observation_data` itself still has no loader here**,
so a fresh deployment gets forecasts and no truth until that table arrives by
other means; that is the one remaining hole in the install path. **The source
files for it were located on Explorer on 2026-09-16 — see §11** for the exact
paths and for the one decision the IMERG side carries.

### The defect

Writing it turned up a real problem with the **existing** table. The original
off-repo script assigned each native observation to a target cell with
`np.round(x / 0.5) * 0.5`. `np.round` rounds half to **even**, and on this
lattice a coordinate at a .25 or .75 offset divides by 0.5 to an exact .5 — so
both of a cell's boundary neighbours are pushed onto the whole-degree (even)
cell, starving the half-degree one. Interior stencils, measured:

| | whole/whole | mixed | half/half |
|---|---|---|---|
| ERA5 wind (0.25° native) | 9 | 3 | **1** |
| IMERG precip (0.1° native) | 36 | 24 | 16 |

Predicted from the rounding rule and confirmed against every stored cell. So
**7,776 interior ERA5 wind cells — about 19% of that field — are a single native
observation presented as a 0.5° box mean**, beside neighbours averaging nine. The
artifact is a checkerboard keyed to coordinate parity, which means it does not
average out: it injects parity-correlated structure into every spatial metric
computed against this truth field.

The replacement uses the half-open box `[c-0.25, c+0.25)` via
`floor(x + 0.25)` — rounding half consistently **up** — which partitions the
plane: every observation counted exactly once, every interior cell the same
stencil (25 for IMERG, 4 for ERA5, verified uniform across all four parities).

### What this costs, measured before anything was overwritten

`regrid_observations.py --compare` against the stored table. Same cell set
exactly — 97,200 and 40,344, nothing gained or lost — but different values:

| | identical | median abs diff | p95 | max | median rel |
|---|---|---|---|---|---|
| IMERG precip | 56.5% | 0 | 0.357 mm/h | 6.54 mm/h | 21.8% |
| ERA5 wind | 0.04% | 0.126 m/s | 0.583 m/s | 2.32 m/s | 3.0% |

IMERG's "56.5% identical" is mostly cells that are zero under both rules, and its
large relative figures are near-zero denominators; the absolute column is the one
to read.

### SWITCHED 2026-09-04

**The rebuilt field is now live.** `regridded_observation` is the partition-based
field; the old banker's-rounding one is `regridded_observation_bankers`, kept in
place, plus a 1.8 MB gzipped dump at
`~/Documents/AFW/regridded_observation_prefix_2026-09-04.sql.gz`. The swap ran as
one transaction, so there was no moment with no truth field.

Every interior cell now averages the same stencil — 25 for IMERG, 4 for ERA5 —
regardless of coordinate parity, against 36/24/16 and 9/3/**1** before.

**What moved, at 36.0/−75.5 over 0–36 h:**

| | AIFS | GEFS | UKMO |
|---|---|---|---|
| precipitation MAE | 0.0918 → 0.0862 (−6.1%) | 1.9413 → 1.9404 (−0.0%) | 0.0831 → 0.0775 (−6.7%) |
| wind bias | 1.6617 → 1.8505 (+11.4%) | 1.3845 → 1.6074 (+16.1%) | 0.7962 → 1.0257 (+28.8%) |
| wind MAE | 1.9051 → 1.9099 (+0.3%) | 3.1893 → 3.1583 (−1.0%) | 2.5786 → 2.5396 (−1.5%) |

Precipitation errors got slightly *smaller*, which is what a less noisy truth
field should do. Wind **bias** moved a lot while wind MAE barely did, and the
reason is worth recording because the obvious explanation is wrong: it is **not**
a systematic offset in the old field. Domain-mean observed wind moved only
4.8563 → 4.8409 (0.3%). The large per-cell moves are simply what replacing *one*
sample with the mean of *four* does at an individual cell — at 36.0/−75.5 that is
~0.2 m/s, while the domain average is essentially unchanged.

**`METRICS_AUDIT.md` is now stale in the direction that matters**: every figure in
it was derived against the old field. The new numbers are the better ones, but
nothing in that document says so, and a reader comparing it against the app will
find a discrepancy with no explanation attached. **Re-deriving it is the
follow-up this created**, and it is not small.

To go back: `ALTER TABLE regridded_observation RENAME TO regridded_observation_new;
ALTER TABLE regridded_observation_bankers RENAME TO regridded_observation;` in one
transaction, then restart the API and clear `.cache/plots`.

---

## 8. The `init_time` migration — DONE 2026-09-02

`DATA_EXPANSION_DESIGN.md` called this the single blocking issue for loading more
than one forecast run, and said it had to be fixed *before* a second run arrived
rather than after. It is fixed; that document's phases 1–2 are closed and its
"do not load a second run" rule is retired. Read it for the detail — this is the
short version and the parts a reader of *this* document needs.

**The defect.** The regridded tables carried no run identity, and
`_latest_init_time` resolved the newest run in `forecast_runs` and added
`forecast_hour` to get a valid time. Correct with one run; with two it silently
attributes every regridded row to the newest initialisation and every score
becomes wrong in a way that looks entirely plausible.

**What shipped.** `Data/migrate_init_time.py` (idempotent, `--dry-run`,
`--rollback`) added `init_time NOT NULL` to both regridded tables plus
`forecast_run_registry`; ten query sites filter on it; `/api/runs` reports what
is loaded; `src/api/run.js` makes the frontend name the run on every request.
Applied to `weave_weather`: 42,550,480 member rows and 1,497,294 ens rows all
carry `2025-09-08 00:00:00`.

**Every published number is unchanged** — `compare/skill` still returns AIFS
0.0628/0.0918/0.1013, GEFS 1.9413/1.9413/2.2455, UKMO 0.0276/0.0831/0.0954, and
`/api/health` still reads `ok` with an inferred divisor of 3.0.

### The four things worth knowing before touching this

- **Refusal is gated on ambiguity, not on the parameter being absent.** The
  design document says require `init_time` always and 400 when missing. What
  shipped resolves the sole run when there is one and raises when there are
  several, because the danger in a default is ambiguity and with one run there is
  nothing to pick between. It becomes strict automatically when a second run
  lands. The blanket rule is the `len(rows) > 1` test in `_resolve_init_time`.
- **`ADD COLUMN NOT NULL DEFAULT` is catalogue-only on PG 11+**, so the 6.5 GB
  member table was not rewritten. The design document's add-nullable-then-UPDATE
  recipe would have rewritten 42M rows. The default is dropped afterwards so new
  inserts must state their run — leaving it would move the silent
  mis-attribution from the query layer into the schema.
- **A helper that raises for the caller's benefit must survive the caller's error
  handling.** Every endpoint wraps its body in `except Exception -> 500`, which
  turned the 400 into a server error. All 19 re-raise `RunSelectionError` now.
- **`src/api/run.js` owns both the value and the fetch that finds it**, because
  separating them is a race and was one: requests went out before an App-level
  effect resolved, with no `init_time`. Harmless on one run, but with two every
  first-paint request would 400. Its module state is documented as unsuitable for
  a real selector — switching runs needs React state, or a stale request will
  resolve after the switch and paint one run's numbers under another's label.

### The trap that generalises

**Replacing a resolver means finding every copy of it.** The first pass through
phase 2 left an inline "latest run" query inside
`_fetch_fcst_obs_pairs_spatial`, so `/api/spatial-metric` ignored a requested
`init_time` entirely and answered from whichever run was newest — a full,
plausible map for a run nobody asked for, which is exactly the failure the
migration existed to remove, hiding inside the fix. Neither 649 unit tests nor
the source-reading guard caught it; an end-to-end request with a deliberately
wrong `init_time` did, in one line. When you centralise a lookup, grep for the
*query* as well as the function name.

---

## 10. The reviewer deployment — PREREQUISITES FIXED 2026-09-17

A password-protected deployment for external reviewers.
`REVIEW_DEPLOY_PREREQS.md` is the live record; it lives in the repo so it
survives a clone.

**The AWS plan is off as of 2026-09-18 and no replacement platform is chosen
yet.** Both .docx files in `Estimate Costs/` (outside this repository) are
therefore superseded — the estimate prices a platform that is no longer the
plan, and the prerequisites note does not know either item is fixed. **Neither
fix below was platform-specific**, so nothing shipped needs revisiting: one
origin behind one password is a property of the vhost, and the pool check reads
the live server's own limits. What a new platform changes is the worker count
and `max_connections`, which are inputs to that check rather than assumptions
baked into it.

**Both prerequisites are fixed.** What shipped, and how each was verified:

| | fix | verified by |
|---|---|---|
| §1 auth | `src/api/base.js` defaults to same-origin `/api` in a production build; `deploy/Caddyfile` puts one `basic_auth` over both halves; gunicorn binds `127.0.0.1` | a build with `REACT_APP_API_URL` unset ships **zero** occurrences of a separate API origin in its JavaScript |
| §2 pool | `DB_POOL_MAX` defaults to **8**, safe at every tier (8×8=64 < 97 usable) | startup check and `/api/health` → `connection_pool` report the live arithmetic; the old 20 is reported `safe: false` at −63 headroom |

**What remains is not code.** A host has to be chosen first — that is the open
question as of 2026-09-18. Then two steps that are yours and cannot be done for
you: run `caddy hash-password` and paste the bcrypt hash into the Caddyfile, and
point the hostname at the box. A password should only be written to a file by
the person choosing it.

**Validated 2026-09-17** against Caddy v2.11.4: `caddy validate` returns
**"Valid configuration"**, and the run confirms automatic HTTPS with
HTTP→HTTPS redirects, so §7's TLS item is genuinely covered rather than
assumed. Checked with a real bcrypt hash substituted, since the committed file
carries a placeholder and hash validity is not checked at adaptation time.
`caddy fmt` is clean.

**One deployment prerequisite that looks like a config bug.** Caddy opens the
log writer while *loading* the config, not on first request, so if
`/var/log/caddy` does not exist both `caddy validate` and `caddy run` fail
outright with `mkdir /var/log/caddy: permission denied`. Create it first:

```bash
sudo mkdir -p /var/log/caddy && sudo chown caddy:caddy /var/log/caddy
```

That was the only error the validation found, and it is about the box rather
than the file. The Caddyfile now says so at the `log` block.

Three things found while doing this, none of them in the original note:

- **The API base was duplicated across five files**, each with its own
  `|| 'http://localhost:5000/api'`. That is the root of §1 rather than a tidiness
  problem: there was no same-origin option to choose. Now one module, and the
  standing "replacing a resolver means finding every copy" lesson applies again.
- **The default build ships a 4.5 MB source map** with the complete original
  source. `DEPLOY.md` §4 now builds with `GENERATE_SOURCEMAP=false`.
- **`DEPLOY.md` §3 said to bind `0.0.0.0`**, which would have left port 5000
  reachable and the password bypassable by addressing the host directly. The
  Caddyfile and §3 both say `127.0.0.1` now, and §8's smoke test checks it from
  another machine.

`DEPLOY.md` §8 now also asserts the password is load-bearing — an unauthenticated
request to `/` and to `/api/health` must both return **401**. A 200 from either
is the exact failure §1 describes.

The original write-ups follow, kept as the reasoning.

1. **The API authenticates nothing.** All 19 routes in `flask_api.py` are open;
   the only `token` references in the file are the input-validation regex and
   the data-version tag, so there is no auth layer to switch on. And
   `REACT_APP_API_URL` is baked into the bundle at build time (`DEPLOY.md` §4),
   so **a password on the static site alone protects nothing** — the API's URL
   ships to every browser in readable JavaScript and can be called directly.
   The fix is one Caddy vhost serving both halves with `basic_auth` over the
   whole thing, plus a rebuild with a same-origin API base. That also covers
   `DEPLOY.md` §7's TLS item and retires its §5 `CORS_ORIGIN` step.
2. **The connection pool ceiling.** `DEPLOY.md` §3 works the arithmetic for 4
   workers only. At 6 workers × `DB_POOL_MAX` 20 = 120 against PostgreSQL's
   default `max_connections` of 100, requests start failing under exactly the
   load the larger instance was bought to carry. `DB_POOL_MAX=8` is the safer
   of the two fixes, since each connection costs memory on a box also running
   the database.

### Getting the data to wherever it lands — the thing to settle first

The host decision and the data decision are the same decision, which neither
the estimate nor the prerequisites note said. **A fresh box starts with an empty
PostgreSQL**, so every scored endpoint would return empty — correctly — and
reviewers would see an app with no verification in it.

What is actually in the database, as of 2026-09-21:

| table | size |
|---|---|
| `forecast_data` | 38 GB |
| `regridded_forecast_member` | 18 GB |
| `ensemble_statistics` | 1375 MB |
| `observation_data` | 499 MB |
| `regridded_forecast_ens` | 548 MB |
| `regridded_observation` | 33 MB |
| **whole database** | **58 GB** |

Re-measured 2026-09-28 after the AIFS 06Z load. The progression is the phase 5
argument written out: 36 GB on 2026-09-21 → 38 GB when the unique indexes that
made a regrid re-run safe (§13) cost ~2 GB → 39 GB once UKMO 06Z landed, one
model and 36 hours for ~1 GB (§14) → 45 GB once AIFS 06Z landed, one model and
360 hours for ~6 GB (§17) → **52 GB** after the AIFS wind replacement (§18).
Ten single-model runs is 60 GB on top of what is here.

52 GB → **58 GB** came from the unique keys the raw tables always lacked (§19):
6.4 GB on `forecast_data`, 258 MB on `ensemble_statistics`. That is the price of
making a double load impossible, against 10.9M duplicate rows it has already
cost once.

**Some of this is dead tuples, not data.** The replacement deleted 40M
rows and inserted 40M, and `regridded_forecast_member` still carries **6.2M dead
tuples** with `ensemble_statistics` at 766k. Autovacuum frees that for reuse but
does not shrink the files; only `VACUUM FULL` does, and it takes an exclusive
lock. Expect this after any bulk replacement here — the same note §12 records
for `observation_data`.

> **Re-measured 2026-10-01 (§27): `regridded_forecast_member` now reports 0 dead
> tuples**, `ensemble_statistics` 435,928. Autovacuum caught up on its own, so
> the "~6 GB reclaimable" that followed from this paragraph is no longer true and
> no `VACUUM FULL` is owed. The *expectation* above still holds after the next
> bulk replacement; the specific figure does not. Re-measure rather than quoting
> it.

Three ways, cheapest first:

1. **Serve from this machine's existing `weave_weather`.** Nothing moves. The
   truth field here is the corrected UTC one (§12), verified end to end. The
   beta ships as soon as a host can reach this database.
2. **Dump and restore.** 58 GB, two thirds of it `forecast_data`. Worth asking whether
   the beta needs that table at all before moving it: the scored endpoints read
   the regridded tables and `regridded_observation`, which together are under
   10 GB.
3. **Rebuild from source on the new host.** Now genuinely possible —
   `load_to_postgres.py`, `load_wind.py` and `load_gefs_ukmo_wind.py` write the
   raw forecast tables, `regrid_members.py` the regridded ones, and
   `load_observations.py` + `regrid_observations.py` the truth (§11, §12). But
   the source GRIB/NetCDF lives on Explorer under 14 TB of it, so this means
   pulling data down and re-running the regrids. **This is the path that matters
   for a *second run*, not for standing up this one.**

An earlier version of this section said a fresh host needs the observation
ingest specifically. That was too narrow — it is the whole database, and the
forecast side is the larger part of it.

## 11. Where the observation sources actually are — FOUND 2026-09-16

Item 3 said for three weeks that the IMERG/ERA5 source files were "not on the
development machine". That was true and it was the wrong thing to record,
because it got read as "the data does not exist". **Both are on Explorer**
(`login.explorer.northeastern.edu`, key-based SSH works). Paths, contents and
how each was verified, so the next person can re-check rather than trust this:

### ERA5 wind — a complete match, and a 130 MB shortcut

```
/projects/k.aggarwal/WEAVE/ERA5/era5_wind_jul_dec_2025.nc          18.4 GB, global
/projects/k.aggarwal/WEAVE/ERA5/subsets/conus_east.nc               130 MB, this domain
```

Both carry `u10` and `v10` as `float(valid_time, latitude, longitude)`, 0.25°
regular lat/lon, **4,416 hourly steps from 2025-07-01 00Z to 2025-12-31 23Z**,
`GRIB_stepType = instant`. The loaded run's 2025-09-08 00Z initialisation and
its whole verification span sit well inside that.

**Use the subset, not the global file.** `subsets/conus_east.nc` is 25–45 N,
275–295 °E — which is **−85 to −65 W, exactly `regrid_members.py`'s
`TARGET_LAT_RANGE` and `TARGET_LON_RANGE`** (§2) — at 81×81 points. That is not
a coincidence to rely on blindly, but it was checked: the bounds match to the
degree, and 0.25° over exactly those bounds puts **4 native observations in each
interior 0.5° box**, which is the ERA5 stencil §7 measured and the replacement
rule expects. Verified directly: variables, step, bounds, and that
2025-09-08 is present. `regions_config.json` in the same directory defines the
box; `era5_subset.py` is what cut it.

### IMERG precipitation — half-hourly, and the run date is covered

**This section originally said the cluster had no half-hourly IMERG and that
precipitation therefore carried a choice between 6-hourly data and a GES DISC
download. Both halves of that were wrong**, and the reason is worth more than
the correction: the search had looked in `IMERG_6hourly/`, found 6-hourly
sampling, and generalised from one directory to the filesystem. A deeper search
found `IMERG_complete/` — **4,416 granules, 48 per day, every day of September
2025**, including 2025-09-07 and 09-08.

```
/projects/s.dey/Puja/IMERG/IMERG_complete/    4,416 half-hourly V07B granules, 8 MB each
```

The 48 granules of UTC 2025-09-08 reproduce every stored IMERG row exactly
(§12). **No download and no Earthdata credentials are needed.** The 6-hourly
files below are a different, coarser product from the same project and are not
what the database was built from.

### The 6-hourly IMERG files — not the source, and not to be used

In **someone else's directory** — Puja's data under `s.dey`, written by
`das.puj` and `mansoor.d`. It is group-readable, which is not the same as it
being ours: **copy what you need rather than depending on it in place**, and ask
before treating it as a project input. Its lifetime and permissions are not
under our control.

```
/projects/s.dey/Puja/IMERG/IMERG_6h_accumulated/IMERG_6hourly_202509-202509.nc   648 MB
```

`precipitation(time, lat, lon)` in **mm/6h**, `source = "GPM IMERG V07B"` —
matching the `GPM_IMERG_V07B` label the app already shows (§4) — 0.1° global at
1800×3600, **117 six-hourly steps from 2025-09-01 00Z to 2025-09-30 00Z**, with
2025-09-08 present at 00/06/12/18 Z. Over this domain that is 200×200 native
cells, so **25 native observations per interior 0.5° box**: again exactly the
IMERG stencil §7 measured.

~~**The decision this carries.**~~ **Retired 2026-09-16, same day it was
written.** This said the choice was between accepting 6-hourly data and
re-downloading from GES DISC, because the stored truth is half-hourly and a
6-hourly source reproduces neither `record_end_lead_hours = 19.5` (§4) nor
defect 2's **twelve** samples per window (§3). All of that is true of *this
file* and irrelevant, because `IMERG_complete/` above holds the half-hourly
granules and they reproduce the stored rows exactly. There is no decision and
nothing to download.

**Do not use the pre-regridded files.** `IMERG_6hourly_202507-202509_Regridded_05.nc`
and its `Land_` variant are already on a 0.5° grid by a **conservative** regrid
from another project. Taking them bypasses `regrid_observations.py` entirely and
throws away the whole point of the 2026-09-04 work — the box-mean partition that
replaced banker's rounding (§7) — substituting an unaudited stencil for the one
that was measured. Ingest the 0.1° native field and let this repository regrid it.

### Traps found doing this

- **"Not on the development machine" is not "does not exist."** Three weeks of
  item 3 reading as blocked-on-data came from a sentence that described where
  someone had looked rather than where the data was. When recording a missing
  input, record **where you looked** — otherwise the next reader inherits the
  search's boundary as a fact about the world.
- **And then the same mistake again, in the same session.** Having found
  `IMERG_6hourly/`, this document confidently recorded that the cluster had no
  half-hourly IMERG and set out a choice between two bad options. `IMERG_complete/`
  was one directory away. **One directory is not the filesystem** — and the tell
  was there to read: a table whose row count is exactly 220×220×48 was already
  saying the half-hourly data existed somewhere.
- **`IMERG_6hourly/` does not hold half-hourly data, and does not hold the run
  date.** 248 `3B-HHR` granules, but 2025-07-01 to 2025-08-31 only, and just
  four per day — 00/06/12/18 Z snapshots of a half-hourly product. The directory
  name describes the sampling, not the product, and the `3B-HHR` prefix on each
  file makes it look like a half-hourly archive. Read the granule timestamps.
- **The login node's conda is not the one to use.** `module load anaconda3/2024.06`
  provides no `ncdump` at all, and the `conda` shell hook in `~/.bashrc` was
  OOM-`Killed` on the login node mid-command without failing it. The env at
  `/projects/k.aggarwal/conda_envs/weave/bin/` has a working `ncdump`, `python`
  and `xarray`; call those by absolute path and skip the module system.
### Working on Explorer at all — operational traps, from several tasks

Not specific to the IMERG hunt above. Each of these cost real time on a
*different* task and would have cost it again, because none of them presents as
a limit of the host: every one reads as a bug in whatever you were running.

- **A full ingest on the login node gets `Killed`, and the kill is the only
  message you get.** Found 2026-10-02 running `load_cyclone_tracks.py` over all
  1,181 cyclone CSVs: it builds the whole set of rows in memory before writing,
  which is fine on a workstation and past the login node's cgroup limit. There
  is no traceback and no partial output — the shell reports the job as
  `Killed` and nothing else, which reads like a crash in the script rather than
  a limit on the host.

  **Use `--storms NAME` (or any equivalent subset flag) for a spot check**, and
  a compute node for a real load. The same run restricted to one storm —
  11 files — finished instantly and answered the question that the full run was
  being used to answer. This is the same shape as the `conda` hook above being
  OOM-killed mid-command: on a shared login node, assume memory is the binding
  constraint and reach for a subset first.
- **`/tmp` is per-node, and consecutive `ssh` commands do not land on the same
  node.** `login.explorer.northeastern.edu` resolves to **two** A records
  (129.10.0.145 and .146, hosts `explorer-01` and `explorer-02`) and alternates
  between them — four consecutive `ssh` calls on 2026-10-02 landed 02, 01, 02,
  02. So a `mkdir` in one invocation and a `cd` in the next can genuinely see
  different filesystems, about half the time, which is worse than never. This presents as files vanishing between commands,
  which invites the conclusion that the write failed — it did not, it is simply
  somewhere else.

  **Do multi-step remote work in a single `ssh` invocation**, with `mktemp -d`
  and a trailing `rm -rf`, rather than as a sequence of calls sharing a path by
  assumption. `scp` then `ssh` is the same trap wearing a different hat. Work in
  `/projects` or `/home` instead when something genuinely has to outlive the
  session.
- **The default `python3` has no `psycopg2`.** So a loader that imports it at
  module scope cannot even be `--dry-run` there, despite a dry run needing no
  database at all. Either use the conda env above, or put a stub package on
  `PYTHONPATH` whose `connect` raises — four lines, and it keeps the dry run
  honest by making any real database call fail loudly rather than silently
  succeeding against something unexpected.

## 12. The observation loader, and the 4-hour IMERG defect it found — 2026-09-16

`Data/load_observations.py` loads native IMERG granules and ERA5 netCDFs into
`observation_data`. That was the last table in this database no script here
could produce, and the reason `DEPLOY.md` §2b promises a fresh install
forecasts and no truth. **The hole in the install path is closed.**

**It reproduces the loaded run exactly** — all 2,480,664 rows, every column, no
tolerance:

| source | rows | reproduced |
|---|---|---|
| `ERA5_WIND` | 157,464 | exact, at face-value UTC |
| `GPM_IMERG_V07B` | 2,323,200 | exact, with `--imerg-shift-hours -4` |

That is the point of `--verify`: it builds the rows and compares against the
stored table without writing, so the conventions are **recovered and then
demonstrated** rather than assumed. Run it before trusting `--load` on a new
date — the rows are a pure function of the source files, so a convention that
drifts moves every score and errors nowhere.

### The defect

**IMERG's stored timestamps are 4 hours behind UTC. ERA5's are not.**

Not suspected beforehand; it fell out of `--verify` refusing to match. Proven
by exact 220×220 field comparison rather than inference:

- Stored rows run 2025-09-07 20:00 → 2025-09-08 19:30. The granules whose
  precipitation fields match them cell-for-cell are **UTC 2025-09-08 00:00 →
  23:30** — the 48 granules of one UTC day.
- At `-4` h, all 2,323,200 rows reproduce with zero differences. At 0, no
  timestamp lines up at all.
- ERA5 reproduces exactly at face value, so **the two truth sources in one
  table are on different time bases**.

4 hours is UTC−4, Eastern Daylight Time in September, over a domain that is
the US East Coast. A timezone conversion applied to IMERG and not to ERA5 is
the obvious candidate.

### What it costs — MEASURED 2026-09-16

Forecast valid times are UTC — wind verifies against unshifted ERA5 and
returns plausible scores — so **every precipitation score pairs a forecast at
lead H against truth from H+4.**

**How this was measured, because the method matters more than the numbers.**
Correcting the shift is a *pure relabel*, not a re-regrid: `regrid_observations.py`
groups by `(obs_time, cell)`, so shifting every timestamp by a constant permutes
the groups without changing any group's membership. Verified rather than
asserted — box-averaging `observation_data` at one timestamp reproduces the
stored `regridded_observation` at that timestamp across 2,025 cells with **max
absolute difference 0 and identical `source_points`**. So the corrected field is
the stored one with IMERG's `obs_time + 4h` and ERA5 untouched.

That corrected copy was built in a **separate schema** (`utc.regridded_observation`)
and the API pointed at it with `PGOPTIONS='-c search_path=utc,public'`, which
resolves only the truth table elsewhere and leaves every other table — and the
live table — untouched. The table name is hard-coded at ten sites in
`flask_api.py`, so this is the only way to measure without a rename dance on
production data. The baseline run reproduced every published figure exactly,
which is what makes the comparison trustworthy.

**Controlled at h0–18**, the window scorable under *both* fields. This matters:
correcting the shift also moves the record end from +19.5 h to +23.5 h, so an
uncontrolled comparison mixes realignment with a larger lead-time sample.
Matched cell counts (1681 / 1435 / 1521) confirm the control held.

Region, precipitation, 25–45 N / −85 to −65 W, h0–18:

| | AIFS | GEFS | UKMO |
|---|---|---|---|
| MAE | 0.3719 → 0.3301 (−11%) | 0.5611 → 0.5269 (−6%) | 0.4200 → 0.4043 (−4%) |
| RMSE | 1.0171 → 0.9004 (−11%) | 1.4042 → 1.3296 (−5%) | 1.0489 → 0.9445 (−10%) |
| bias | −0.1075 → −0.0727 | −0.3639 → −0.3162 | **−0.0113 → +0.0272 (sign flip)** |
| FSS | 0.0364 → 0.0122 (**−66%**) | 0.0 → 0.0 | 0.3385 → **0.5105 (+51%)** |
| CSI | 0.0105 → **0.0** | 0.0 → 0.0 | 0.0804 → **0.1771 (+120%)** |

Point, 36.0/−75.5, h0–18:

| | AIFS | GEFS | UKMO |
|---|---|---|---|
| MAE | 0.0862 → 0.0360 (−58%) | 1.9404 → 1.9145 (−1%) | 0.0775 → 0.0256 (−67%) |
| bias | 0.0619 → 0.0360 | 1.9404 → 1.9145 | 0.0267 → 0.0008 |

**Wind is byte-identical across both runs** — every model, every metric. That is
the control, and it confirms the defect is IMERG's alone.

**The conclusion, which is worse than a magnitude error.** The continuous
metrics all improve, modestly domain-wide and by up to 67% at a point, and that
part is unsurprising: a misaligned truth inflates error. But the
**neighbourhood and categorical scores move in opposite directions by model** —
UKMO's FSS gains half again and its CSI more than doubles, while AIFS's FSS
falls by two thirds and its CSI goes to zero. So the shift was not uniform
noise being removed. **It was changing which model looks better at
precipitation**, which is precisely the question the Comparison tab exists to
answer. Two things do survive: the MAE ranking (AIFS < UKMO < GEFS) is unchanged,
and GEFS stays an outlier for the reasons in the standing-decisions note.

`METRICS_AUDIT.md` therefore needs re-deriving *after* the fix, not before —
every precipitation figure in it is on the wrong time base, and §0's script
(`Data/rederive_audit.py`) exists to make that cheap.

### FIXED 2026-09-16 — the corrected field is live

Applied as one transaction, following §7's pattern. Both tables are corrected,
because the raw one is the root: leaving `observation_data` shifted would mean
the next regrid reintroduces the defect.

- `observation_data`: IMERG `obs_time + interval '4 hours'`, 2,323,200 rows.
  Now 2025-09-08 00:00 → 23:30. ERA5 untouched.
- `regridded_observation`: the corrected field, 97,200 IMERG rows now
  00:00 → 23:30. ERA5's 40,344 rows untouched.
- **The old field is kept in place as `regridded_observation_shifted`**, as §7
  did rather than relying on a dump.

**How it was verified, which is the part worth trusting:**

- **The loader now reproduces both sources at its UTC default, with no shift
  flag** — 2,323,200 IMERG rows and 157,464 ERA5 rows, zero differences in any
  column. Before the fix that required `--imerg-shift-hours -4`. The table and
  the granules finally agree about time.
- The regrid chain still holds: box-averaging `observation_data` at 10:00 UTC
  reproduces `regridded_observation` there across 2,025 cells, max absolute
  difference 0, identical `source_points`.
- The API serves exactly the numbers measured through the schema overlay, and
  `/api/observation-coverage` reports `record_end_lead_hours` **23.5**.
- 707 backend tests pass. They run against the fixture database, so they were
  never going to catch this — worth stating plainly rather than reading a green
  suite as confirmation.

**Follow-ups done in the same change:** `METRICS_AUDIT.md` §0 regenerated via
`rederive_audit.py`, with a new header warning; every `19.5` reference across
six files corrected to `23.5`.

**To revert**, in one transaction:

```sql
ALTER TABLE regridded_observation RENAME TO regridded_observation_utc;
ALTER TABLE regridded_observation_shifted RENAME TO regridded_observation;
UPDATE observation_data SET obs_time = obs_time - interval '4 hours'
 WHERE source = 'GPM_IMERG_V07B';
```

then clear `.cache/plots` and restart every server (§1's trap).

### The bloat it left, and the vacuum — 2026-09-21

The `UPDATE` above doubled `observation_data` on disk: **499 MB → 1065 MB**.
Nothing was wrong with it; that is just how PostgreSQL works. An `UPDATE` never
rewrites a row in place — it writes a new version and marks the old one dead, so
that concurrent readers keep seeing a consistent snapshot. Touching 2,323,200
rows therefore left 2,323,200 dead versions behind.

`VACUUM FULL (ANALYZE)` brought it back to **499 MB**, reclaiming 566 MB in 7
seconds. The verbose output is the part worth reading:

```
found 0 removable, 2480664 nonremovable row versions in 64052 pages
```

**Zero removable** — autovacuum had already swept the dead tuples and marked
that space reusable, which is why nothing was ever broken or slow. What it could
not do is give the space back: plain `VACUUM` frees dead space *for reuse by the
same table*, it does not shrink the file. `VACUUM FULL` rewrites the table into
a fresh file, 64,052 pages down to 33,076, and that is the only form that
returns disk to the OS.

**When to bother, and when not to.** Normally not: on a table that keeps being
written, the holes get reused and `VACUUM FULL`'s exclusive lock is not worth
paying. `observation_data` is the exception — it is loaded once and then only
read, so that 566 MB would never have been reclaimed by anything else. Expect
the same after any future bulk `UPDATE` here, including a re-run of the
correction on a second run's rows.

It takes an `ACCESS EXCLUSIVE` lock and needs roughly the table's size in free
space to build the copy, so run it with no server attached. Verified afterwards:
row counts and both sources' UTC ranges unchanged, and the app re-checked end to
end — `/api/health` healthy, `compare/skill` returning the same post-fix figures
to four decimals, a Comparison run driven through the UI with all six metric
panels rendering and a clean console. `VACUUM FULL` cannot alter values, only
their physical layout, so that was confirmation rather than a real risk.

**One loose end, left deliberately.** `regridded_observation_bankers` — the
pre-2026-09-04 banker's-rounding field, kept as §7's rollback — is **still on
the shifted time base**, because correcting it would mean maintaining a field
nothing reads. Anyone rolling back that far gets the 4-hour shift back with it.
Its primary key was also renamed to `regridded_observation_bankers_pkey` here,
since it had been squatting on the canonical name since §7's swap: **renaming a
table does not rename its indexes**, which is what made this swap fail twice
before it went through.

`load_observations.py` defaults to UTC, so a future load is correct
independently of any of this.

`--imerg-shift-hours` keeps that decision open and defaults to **0**, because
UTC is right. It exists so the legacy table can be reproduced exactly, which is
what proves the rest of the script correct — not so the defect can be carried
forward.

### Worth knowing before touching it

- **IMERG V07 stores fields as (time, lon, lat)** — longitude first, the
  opposite of every other grid here. Both dimensions are 220 after clipping, so
  a wrong transpose gives a full, plausible, entirely wrong table and no shape
  error.
- **Coordinates must be canonicalised at 2dp**, the precision the stored table
  holds. IMERG ships float32, where 24.05 is 24.049999237060547; rounding at
  6dp built 2,190,144 rows that matched nothing while the row count was already
  exactly right, which reads as missing data rather than as a rounding choice.
- **Wind speed is derived in float64.** ERA5's `u10`/`v10` are float32 and
  stored unchanged, but the original ingest took `hypot` at double precision —
  a float32 hypot lands 4.8e-07 from every stored value, which is 157,462 rows
  differing by an amount small enough to look like noise and uniform enough not
  to be.
- **IMERG's epoch is 1980-01-06**, not Unix, and its units string ends in
  ` UTC`, which `np.datetime64` rejects rather than ignores. Read the granule's
  own `time` variable, never the filename — the standing GEFS lesson.
- **Fill is −9999.9, not NaN.** Those cells are dropped rather than stored as
  0, because a missing observation and an observed dry half hour would be
  averaged together by the box mean in §7.

`test_load_observations.py` pins the pure functions — coordinate precision, the
bbox clip on cell centres, the longitude convention, the granule epoch. No
source files: granules are 8 MB each and the end-to-end check is `--verify`
against the real table. One lesson from writing those tests, which cost a
failing run: **a synthetic grid noisier than the real one tests the tolerance
rather than the code.** `np.arange(..., 0.1, dtype=np.float32)` drifts ~2e−3 by
index 1800 and failed a clip that is correct on every real granule.

## 13. The export convention is per-run now — 2026-09-24

`SCALED_EXPORT_DIVISOR_HOURS` described the export that happened to be loaded.
`forecast_run_registry` now describes each run's own, `Data/run_registry.py`
writes it at load time, and scoring reads it. `DATA_EXPANSION_DESIGN.md` phase
4 has the detail; this is what a reader of *this* document needs.

**The standing GEFS warning is retired.** It said re-exporting GEFS would
require changing that constant in the same commit or the correction applies
twice. With the divisor stored per run, a re-export records its own and leaves
the loaded run alone. There is a test that two runs disagree without either
being wrong.

**Two distinctions that had to exist first.** `export_divisor_h` was NULL both
for UKMO — never scaled, React.py converts its native rate straight to mm/h —
and for a model nobody had declared. Opposite situations, indistinguishable in
a nullable float, so `export_convention` names them and NULL there is an error
rather than a default. And `metrics._increment_divisor` returned the period for
any unknown model, which reads as unscaled: a model whose export divided by 6
would have scored 6x high with nothing to say so.

**How the switch was verified**, because the obvious check is not sufficient.
Every precipitation number is byte-identical afterwards — which is the right
outcome, and also exactly what a silent fallback to the constant would produce.
So the registry was perturbed instead: GEFS's divisor set to 6 moved its MAE
from 1.4399 to 2.9422, and restoring 3 brought it back. Identical numbers, zero
fallback warnings, and a score that follows the registry when it moves.

**Fallback rather than refusal, deliberately.** `_export_divisor` falls back to
the constant and logs once per key if the registry cannot answer. Raising is
louder and wrong here: a database predating the registry would lose every
precipitation endpoint at once, and the fallback is precisely the behaviour
those deployments already have. The danger the design names — a second run
scored with the first's divisor — cannot reach through this path, because the
cache key is the run.

### One thing this left open

- ~~**Re-running a regrid duplicates rows.**~~ **Fixed 2026-09-24**
  (`5d45a29`). `clear_slice` deletes the (model, variable, run, hour) each pass
  is about to write, in the same transaction as the `COPY`; unique indexes on
  the natural key are the backstop that makes a missed clear loud rather than
  silent. Both tables were clean beforehand, so nothing had to be deduplicated
  — and the indexes building at all re-proves that, since a unique index
  cannot be created over duplicate data. Verified by regridding one slice
  twice: identical counts, identical scores.
- **`point_timeseries` cannot ask which run it is scoring.** It reads native
  `forecast_data` via `get_model_run_id` and never resolves an `init_time`, so
  it is still on the constant. A pre-existing multi-run ambiguity rather than a
  divisor problem, and it needs settling before a second run lands.

### One thing worth knowing about the fixture

**It had no `forecast_run_registry` at all**, and now does. The fixture builds
its schema from source DDL precisely so a table cannot drift out of it — and
one had, because the registry is created by a migration rather than by either
file `_schema_sql` read. Nothing failed, because nothing read it. Adding a
reader is what would have found it, which is a general argument for checking
what the fixture *lacks* rather than trusting that it mirrors production.

## 14. A second run is loaded — 2026-09-24

**`2025-09-08 06Z`, UKMO precipitation only, lead hours 0–36.** The first time
this database has held two initialisations, and the first time the run selector
has had anything to select.

Deliberately partial. AIFS and GEFS could not be loaded at all (see below), and
a one-model run turns out to exercise more of the new machinery than a full one
would: the selector switches, models absent from a run grey out with a reason,
lead time clamps between runs with different ranges, and the per-run export
convention is read rather than assumed.

**Where it came from.** `UKMO/regional_data/conus_east/total_rainfall/2025-09-08/T0600Z`
on Explorer — 37 hourly NetCDF files, 2 MB — converted by
`Data_convert_weave/React.py`, loaded with `load_to_postgres.py` at
`init_time='2025-09-08 06:00:00'`, then `regrid_members.py --init-time`.

### The pipeline is not reproducible for AIFS or GEFS

**There was no NetCDF → JSON converter for them.** `React.py` handles UKMO only
(it reads `total_rainfall_rate` and multiplies by 3.6e6); `aifs react.py`,
despite the name, is JSON → JSON rescaling that sits *downstream* of the
missing stage. Searched both this machine — all five WEAVE folders — and the
cluster: it existed nowhere. That stage was run off-machine and was not kept.

This was the concrete thing behind `DATA_EXPANSION_DESIGN.md`'s "manual and
partly off-machine". Phase 4's work made the *registry* half reproducible; the
conversion half was missing, and writing that converter is what a genuine
multi-model second run needs.

The source data is there: AIFS has 16 runs (4 dates × 4 cycles) already cut to
`conus_east`, at ~32 MB per cycle. It was the converter that was absent, not the
data.

**AIFS precipitation is now closed — see §16.** `Data/convert_aifs.py` (in the
repository, unlike the converters it joins) reproduces the loaded run exactly.
**GEFS is still missing its converter**, and so is anything that would convert
AIFS *wind* with confidence.

### Three defects this surfaced, all of which needed two runs to exist

- **`fetch_hour` was not scoped to a run** (`2bda3ad`). It would have merged
  members from both initialisations into one dict keyed by member number, so
  the later run's member 5 overwrote the earlier one's and the regrid emitted a
  blend of two runs. `run_init_time`'s refusal on ambiguity was the only thing
  keeping that latent.
- **`run_init_time` told callers to "pass the run explicitly" with no parameter
  to pass it through** (`2bda3ad`). Loading a second run made the model
  unregriddable, including the run already there. There is a `--init-time` flag
  now and the refusal names it.
- **A partial regrid narrowed the registry's recorded range.** `--hours 6` set
  UKMO 00Z to `hours 6–6` while the stored data still spanned 0–198, and the
  UI's lead-time clamp reads exactly that field. The load path now *measures*
  from the stored data instead of recording what the pass wrote — ~20 s scoped
  to one run, because the natural-key index covers it.

### Two things left open

- ~~**The run selector is hidden below 760px**~~ **fixed 2026-09-25** (§15).
  It lived inside the header badge that collapses on narrow windows. The run is
  the one piece of context that qualifies everything else on screen, so hiding
  it was the wrong trade.
- **Observations stop at 2025-09-08 23:30 UTC** — re-confirmed against
  `regridded_observation` on 2026-09-28 — so the 06Z run verifies to about
  +17.5 h rather than its full 36. **A short series here is the correct result,
  not a loading failure.** Extending it means loading 09-09 IMERG and ERA5, both
  of which are on Explorer (§11).

## 15. The selector made usable, and made to scale — 2026-09-25

Four changes, all of which came out of *looking at* the app once two runs
existed rather than from the design document. `99f247a`, `3fe8015`, `de6b546`,
`52d36d1`.

### Date and cycle, not combined tuples

The first selector offered one list of whole runs — `8 Sep 00Z`, `8 Sep 06Z`.
That was chosen on a real argument: two coupled dropdowns can express a pair
that does not exist, a date selected and then a cycle that date does not have.

**The argument is right and the conclusion was wrong.** The fix is to derive the
cycle list from the selected date, which makes an impossible pair
*unrepresentable* rather than merely validated. The combined list also does not
scale — four cycles a day is sixteen flat entries for four days, with no
structure to help anyone read them.

Changing date **keeps the cycle where the new date has it** and falls back to
that date's newest otherwise, so comparing 12Z across days does not snap to 00Z
on every move.

### The date control changes shape with the archive

`DATE_LIST_MAX = 12` in `src/components/RunSelector.jsx`:

| dates loaded | control | why |
|---|---|---|
| ≤ 12 | `<select>` | shows exactly which days exist; asking for one that does not is impossible |
| > 12 | `<input type="date">` | constant-size however far the archive grows, and jumps straight to a day |

The dropdown's guarantee is genuinely worth having while the list is short,
which is why it was kept rather than replaced. It stops being worth a list
nobody can scan.

**The cost of the date input is stated and handled, not hidden.** `min` and
`max` bound the range and **say nothing about holes inside it**, so a date input
cannot grey out the days an archive is missing. A date with no runs is therefore
**refused and named** — "no runs on 9 Sep 2025" — with the selection left
unchanged. Snapping to the nearest neighbour would have been smoother and would
show a different day than the one asked for, which is the same class of quiet
wrongness as the 4-hour IMERG shift (§12).

Cycles need none of this: four a day is four options whatever the archive does.

**This is a now-problem, not a hypothetical.** 17 UKMO dates are already on the
cluster, which at four cycles each is 68 runs.

**Where the next limit is, so it is not mistaken for this one:** at some
hundreds of runs `/api/runs` becomes the bottleneck, because it returns a
`detail` entry per run and `RunProvider` holds all of it. That endpoint is what
to paginate. Do not re-attack the selector for it.

### The run guard leaked twice before it held

Switching runs produced 400s, because requests were still going out for a model
the newly-selected run does not have. Three attempts, and the first two are
worth recording as *wrong*:

1. Allow requests while the run list is loading — leaked, because `src/api/run.js`
   resolves independently of the provider.
2. Allow them when no run is selected yet — leaked for the same reason.
3. **Wait for `runStatus === 'ready'`.** This one holds:
   `runHasSelectedModel = runStatus === 'error' || (runStatus === 'ready' && (runModels.length === 0 || runModels.includes(selectedModel)))`.

Separately, **map initialisation bypassed the guard entirely** by calling
`loadDataForHour()` itself instead of going through the gated effects. A guard
that every path but one respects is not a guard.

### The "API KEY REQUIRED" watermark was the basemap

Stamped across the map in the tiles themselves: a provider refusing anonymous
use and writing its refusal into what it served. Not a WEAVE bug and not
recoverable in app code. Swapped to keyless Esri `World_Light_Gray_Base` and
`_Reference` (`src/App.js:292`) — note the `{z}/{y}/{x}` ordering, which is not
the usual `{z}/{x}/{y}`. **If a watermark or blank tiles reappear, read the tile
URL before suspecting app state.**

### `/api/health` no longer counts 128M rows to say hello

It ran `count(*)` on `forecast_data` and took **20 seconds**. Now
`SELECT GREATEST(reltuples, 0)::bigint FROM pg_class WHERE oid = 'forecast_data'::regclass`
→ **0.187 s**, reported as `total_forecast_points_estimate` because an estimate
is what `reltuples` is. A health check that scans a table is a health check that
fails under exactly the load it exists to report on.

## 16. The AIFS converter — WRITTEN 2026-09-28

`Data/convert_aifs.py`, with `Data/test_convert_aifs.py`. This is the stage §14
found missing. **It lives in the repository**, unlike `React.py` and
`aifs react.py`, for the reason `load_observations.py` does: a stage kept
outside the tree is a stage that gets lost, and that is exactly how this one was
lost.

It converts `AIFS/regional_data/conus_east/precipitation/<date>/init_<HH>/pf/*.nc`
into the JSON `load_to_postgres.py` reads. **It does not divide by the emit
interval** — `aifs react.py` owns that. Doing it in both places would make every
precipitation score a sixth of what it should be, with nothing to show for it.

### Verified against the run already loaded

`--verify` reproduces AIFS `2025-09-08 00Z` through the legacy scaling and gets
**all 17,915,148 member rows and all 378,737 mean/std rows exactly** — 3,000 of
3,000 (hour, member) slices agreeing cell-for-cell and value-for-value, nothing
one-sided in either direction. About 100 seconds.

Byte-identical output proves little by itself, since a silent fallback produces
it too, so each convention below was established by *breaking* it and watching
the reproduction fail. That is what makes them findings rather than guesses.

### The conventions, none of which were guessable

| convention | why it matters |
|---|---|
| `tp(number, latitude, longitude)` | the domain is **81×81**, so a transposed read is completely silent — the IMERG trap again. Axes are resolved by dimension *name*; the tests use a non-square grid |
| member = **array index**, not `number` | `number` is 1..50, the database is 0..49. Using `number` shifts every member by one, invisibly |
| units are **already mm** | `kg m**-2`. Applying UKMO's ×3.6e6 would inflate rainfall by six orders of magnitude |
| drop `tp < 0.01 mm` | the loaded run's own boundary, exactly: everything dropped is ≤ 0.00977 mm, everything kept ≥ 0.01074 mm, **no overlap** |
| `round(round(tp, 3)/6, 3)` | double rounding. `round(tp/6, 3)` misses 343 of 4,001 cells in one slice |
| `mean`/`std` in **float32** | numpy preserves the dtype; widening first moves the last digit |
| `std` is **population** (`ddof=0`) | `ddof=1` mismatches 362,979 of 378,737 rows |
| `std` only where `mean` survives | the loader applies `std` with an `UPDATE` keyed on the statistics row, so the rest is discarded in silence |

Two of those explain things that look like bugs and are not. **No stored value
is 0.001**, because 0.01 mm over 6 h rounds to 0.002 mm/h — the observed
minimum. And **hour 0 is legitimately absent**: a cumulative total is zero at
initialisation, so 0 of 6,561 cells clear the threshold and the file is empty.

### The float32 comparison that cost a cell

One cell — (44.75, −83.0) at +6h — has a mean of **exactly** `float32(0.01)`.
`mean_array < 0.01` in numpy is **False** there, because the Python float is
cast down to the array's float32 where it compares equal; `float(mean) < 0.01`
is **True**, because that float32 is 0.00999999977 in float64. The stored run
follows the float64 comparison.

Still true under numpy 2.4's NEP 50 promotion, which was checked rather than
assumed. The fix was not a better comparison but **removing the second one**:
`std` is now filtered by the mean's surviving keys, so the two cannot disagree.

### AIFS wind is NOT closed, and the reason is not this script

`wind_u10`/`wind_v10` have an identical layout, and the loaded wind table has
exactly the shape this converter produces: **61 h × 50 members × 6,561 cells =
20,011,050 rows**, every cell kept (zeros and negatives are real readings, so no
threshold), 3 decimals. The cell sets match perfectly.

~~**The values do not.** At `2025-09-08 00Z` +120h, cell (25.0, −85.0), the
database holds **−5.567** where the source has **−4.050**, and no member index
reproduces it.~~ **WRONG, and resolved 2026-10-07 — see §47.** The values match
exactly. −5.567 is the **2025-09-16** run's value at that cell; −4.050 is the
09-08 run's, and it is what the 09-08 source holds. `verify()` was comparing one
source directory against *every* loaded run, so a second run made the comparison
meaningless. 768 of 768 sampled values reproduce the source.

So wind conversion here is **structurally right and numerically confirmed.**

### A new run will not be bit-identical to the old one, by design

Verified end to end on `2025-09-08 06Z` (not loaded): 61 files → **18,556,766
records** → `aifs react.py` → filenames the loader parses, members 0–49 plus
mean and std, payload keys `lat`/`lon`/`value`.

But the scaled value comes out as **0.0172**, at four decimals, where the loaded
00Z run carries three. That is not drift in the converter: `aifs react.py` was
*fixed* to round to 4 dp, and the loaded run went through the old 3 dp version
(`aifs react.py.orig-backup`). The difference is 0.00005 mm/h — far below any
threshold, colour band or score in the app — but it is real, and the reason a
new run cannot be compared to the old one byte-for-byte. `--verify` applies the
legacy 3 dp deliberately, because it is checking against what is stored.

### What this does and does not unblock

- **Unblocked:** a second AIFS *precipitation* run, reproducibly, from any of
  the 16 cycles on the cluster.
- ~~**Still blocked:** GEFS, which has no converter at all~~ — **`convert_gefs.py`
  exists** (522 lines, "completes the set, so every forecast table can be
  rebuilt from source"). This line outlived it; found in the 2026-10-06 sweep
  (§44). The window conventions it names are still the awkward part: 3 h buckets
  at `h%6==3`, 6 h at `h%6==0`.
- ~~**Unresolved:** where the loaded AIFS wind came from.~~ **RESOLVED
  2026-10-07 (§47): it came from the cluster, exactly.** The mystery was a
  comparison across two runs.

~~`netCDF4` is imported lazily and is not in `Data/requirements.txt`~~ — it was
added in §30 (`netCDF4==1.7.4`), which is what unskipped the file-reading tests
in CI. Another line this paragraph kept after the fact.

## 17. AIFS 06Z is loaded, and it broke two things — 2026-09-28

`2025-09-08 06Z` now holds **AIFS and UKMO**. It is the first initialisation in
this database whose model list *differs from another run's*, and that is what
made both defects below reachable. §14's three defects needed two runs to
exist; these two needed two runs that **disagree about their models**.

### What was loaded

Converted with §16, scaled by `aifs react.py`, loaded, regridded. Every step
checked against a number worked out beforehand rather than eyeballed:

| stage | result |
|---|---|
| convert | 61 files → 3,172 JSON, 18,556,766 records, hour 0 empty as designed |
| scale | 3,172/3,172 at ÷6 h (`h%6==0` throughout, as a 06Z cycle should be) |
| load | **+17,806,364** `forecast_data`, **+375,201** `ensemble_statistics`, both exactly as predicted; 0 stats rows missing a std; 20.9 min |
| regrid | **5,043,000** member + **100,860** ensemble rows on the 41×41 0.5° grid |
| registry | `06Z AIFS precipitation, 6–360 h, scaled`, measured from stored rows |

**`forecast_data` has no natural unique key** — only a surrogate pkey — so a
second load would silently double every row, exactly the hazard `5d45a29` fixed
for the regridded tables. The loader was therefore driven by a wrapper that
refuses to start if AIFS rows already exist at that init, and that checks the
delta afterwards. Worth rebuilding if this is ever done again; better still,
give the table the unique index the regridded ones now have.

Also: **do not pass `--truncate` to `regrid_members.py`** to redo one run. It
deletes by model and variable across *every* init, so it would have taken the
00Z AIFS regrid with it.

### Defect 1 — `_run_pairs_sql` discarded the `init_time` it was given

`/api/compare/timeseries` and `/api/compare/spatial-agreement` began returning
**400 "AIFS has 2 loaded runs, so init_time is required"** to a frontend that
was sending `init_time`.

`_resolve_init_time` distinguishes `_UNSET` ("nobody said") from `None`
("explicitly nothing"), and only consults the request body for the first.
`_run_pairs_sql` declared `requested=None` and passed it straight through, so
the body was never read. **Invisible for as long as every model had one run**,
because the single-run fallback then returned the right answer for the wrong
reason — and the resolver's own docstring asserted the frontend's parameter made
it correct, which was false for these two endpoints.

One-word fix, `None` → `_UNSET`. Pinned by four tests in `test_run_scoping.py`,
two of which fail if the default goes back. The discriminating one asks for a
run that does not exist and requires a raise: the fallback path *cannot* raise,
so a raise proves the body was read — which works against the single-run
fixture and needs no second run seeded.

This is the "strict automatically at the moment strictness starts to matter"
design working exactly as its docstring describes. It failed loudly, named
`/api/runs`, and pointed straight at the bug.

### Defect 2 — the Comparison tab offered a model the run lacks

`ControlsSidebar` has greyed out absent models since phase 3. `ComparisonTab`
did not, and its default selection is all three, so at 06Z it sent GEFS and got
`no GEFS run at init_time 2025-09-08T06:00:00` — a 400 the user could not avoid,
from a control that looked available.

Disabling the chip is **not sufficient on its own**: the selection is state, and
it starts as all three. The narrowing therefore shadows the state under the name
the rest of the component already reads, rather than adding a second list beside
it — sixty-odd sites use it, and a parallel variable would be right only where
someone remembered. It is derived during render, not written back, so switching
to a run that *has* GEFS restores the tick instead of having silently discarded
it.

The minimum-two floor now counts *usable* models rather than ticks; counting
ticks read "three selected" at 06Z and allowed a deselect that left one.

### Verified in the app

`/api/runs` reports 06Z with both models and their own conventions (AIFS divisor
6, UKMO null). **The scored endpoints are genuinely run-scoped** — AIFS
domain-aggregate MAE is **0.332 at 00Z against 0.3583 at 06Z**; identical
numbers would have meant the filter was not applied. The Comparison tab renders
AIFS against UKMO over 0–36 h with each model's accumulation convention
labelled, GEFS dimmed with its reason, and all requests 200.

**Two corrections to what this section first claimed** (§19 has the causes).
That MAE pair was written as "at +6h"; it is a **lead-time aggregate**, because
`/api/spatial-metric` reads no hour parameter at all. And "verified in the app"
was too broad: it rests on the *scored* endpoints, which are correct. The
**map** was never run-scoped, and testing one and generalising to the other is
exactly the step that let it stay hidden.

## 18. The AIFS wind was the wrong forecast run — FIXED 2026-09-28

**The field stored as AIFS wind at `2025-09-08 00Z` was the `2025-09-16` run.**
Observations only cover 2025-09-08, so every AIFS wind score had been pairing a
forecast against truth from **eight days before it was initialised**. Not biased
— meaningless. This is a worse defect than the 4-hour IMERG shift (§12), which
at least compared the right forecast to the wrong hour.

### How it was found, after four wrong guesses

The cell set matched the cluster source *perfectly* — same 0.25° grid, same 61
hours, same 50 members, every key present on both sides — while every value
differed. Each cheap explanation was tried and measured, not reasoned about:

| hypothesis | mean abs difference |
|---|---|
| some other member index | 1.83 (best of 50) |
| a spatial shift or transpose | 2.10 (best of 49 offsets) |
| the ensemble mean | 2.05 |
| the ensemble std | 5.22 |

A real match is ~0.0005, from 3-decimal rounding. What finally found it was
matching the stored field's **mean and standard deviation** against every date,
cycle and member in the tree — which hit `20250916 init_00 +120h member 0` at
−3.4933 / 3.2443 exactly — then confirming cell-for-cell against the preserved
rows: **0 mismatches** across two hours and two members, 6,561 cells each.

**The reusable lesson: shape agreement is not provenance.** A field can be a
real forecast, correctly converted, on the right grid, with the right member
count, and still be the *wrong forecast*. Only matching values against a named
source settles it. Every structural check passed here and all of them were
consistent with data that was unusable.

Also worth keeping: the search that failed looked only inside `20250908`. The
answer was one directory along. That is the third time this project has been
bitten by a search whose scope, not whose method, was wrong.

### What was done

Replaced from `AIFS/regional_data/conus_east/wind_{u,v}10/20250908/init_00/pf`
via `convert_aifs.py` (§16). Deletes for both components ran in **one
transaction**, because a failure between them would compose wind *speed* from
two different forecasts — √(u²+v²) of mismatched fields is a plausible number
with nothing wrong on its face.

| stage | result |
|---|---|
| convert | 20,811,492 records per component (20,011,050 members + 400,221 mean + 400,221 std) |
| replace | exactly those counts landed, both components, 0 statistics rows without a std, 50.8 min |
| regrid | 5,127,050 member + 102,541 ensemble rows per component, registered `0–360h unscaled` |
| verify | **both components reproduce the source exactly** — `--verify` clean on members and statistics |

The superseded rows are preserved outside the repo as
**`weave_aifs_wind_prev_20260928.sql.gz`** (177 MB, all 40,022,100 rows), since
they are the only copy of the field every AIFS wind figure to date was computed
from. `forecast_data` has no unique key, so the replacement was driven through a
wrapper that asserts the delta rather than trusting it.

### The score change

Domain-aggregate, identical call before and after:

| metric | before (the 0916 field) | after (the real 0908 run) | change |
|---|---|---|---|
| bias | −0.7117 | −0.1387 | 80% smaller |
| MAE | 2.2386 | **0.6595** | **−70.5%** |
| RMSE | 2.4754 | **0.7838** | **−68.3%** |
| CRPS | 1.7322 | **0.5093** | **−70.6%** |

**Every AIFS wind figure written before 2026-09-28 is on the wrong forecast**,
including anything in `METRICS_AUDIT.md`. Precipitation is unaffected.

**One thing not to misread:** §12 used wind as the *control* that proved the
4-hour shift was IMERG's alone, and that conclusion still stands — it concerned
the observation side, and wind truth genuinely did not move. The forecast side
was wrong the whole time. Two different facts about the same variable.

### `--verify` divides accumulations only

Wind is stored as exported (`unscaled` in the registry), so applying the 6 h
divisor to it made every value differ while the cell set matched exactly. That
is indistinguishable at a glance from the defect above, and it appeared the
first time wind was verified against a source that was in fact correct. Fixed
and pinned by tests.

## 19. Two defects the wind work exposed, and one I imagined — 2026-09-28

Found while verifying §18. **Two were real and are FIXED. The third was my own
error and is withdrawn** — kept here rather than deleted, because the way I
reached it is the reusable part.

### The map never respected the run selector — FIXED

**`get_model_run_id` is `ORDER BY initialization_time DESC LIMIT 1`** — a third
inline copy of the "silent latest run" pattern the `init_time` migration exists
to remove, and one that survived both earlier removal passes (§8 notes it took
two). Five endpoints call it:

| endpoint | honours the selected run? |
|---|---|
| `/api/spatial-metric` | yes |
| `/api/forecast-data` (the map) | **no** — byte-identical for 00Z and 06Z |
| `/api/point-timeseries` | **no** |
| `/api/wind-data` | **no** |
| `/api/spread-skill` | unconfirmed (400 on the params tried) |

Proven, not inferred: a request naming **00Z** returns **06Z** data — 4,426 of
4,426 cells identical to 06Z, **0** identical to 00Z. So the Visualization map
has been showing the newest run whatever the selector said, which makes the
selector *misleading* rather than merely incomplete.

Worse for wind: `/api/wind-data` resolved to the newest run, and for both AIFS
and UKMO the newest run holds no wind. **UKMO's wind map was blank from
2026-09-24**, when UKMO 06Z was loaded, and AIFS's went blank on 2026-09-28 with
AIFS 06Z. GEFS kept rendering only because it has one run.

**The fix.** `get_model_run_id` now delegates to `_resolve_init_time` and looks
the run up by `(model, init_time)`, so there is **one** resolution path for every
run-scoped read: a supplied `init_time` is honoured and validated, a single
loaded run is still defaulted to, and ambiguity raises. All five callers already
had `except RunSelectionError`, so the refusal surfaces as a 400 naming
`/api/runs` rather than a 500.

Two details worth keeping. The per-request cache was keyed on the **model alone**
and is now keyed on `(model, init_time)` — one request can legitimately ask about
two runs, and the old key answered the second from the first. And the function
had to **move** in the file: its new default is the `_UNSET` sentinel, and
defaults are evaluated at definition time, so it now sits after the resolver it
depends on rather than 100 lines before it.

**Verified end to end, not inferred.** A request naming 00Z now returns the 00Z
rows — 4,895 of 4,895 identical, 0 identical to 06Z — and the two runs return
different payloads. In the app the wind map renders again for **AIFS** (0–11
m/s) and **UKMO** (0–16 m/s) at 00Z, and 06Z correctly answers empty for wind
because it holds none. Seven tests pin it in `test_run_scoping.py`; five fail if
the latest-run lookup is restored, and the two that do not are the single-run
default and the no-runs case, both deliberately unchanged.

Returning a run that holds no rows for the requested variable is **correct, not
a gap**: wind at a precipitation-only run should answer empty rather than
quietly serve another run's wind.

### GEFS wind was duplicated in the raw tables — FIXED

Every GEFS wind row existed **twice** in `forecast_data` and
`ensemble_statistics`, all pairs holding *identical* values. The no-unique-key
hazard, already realised — and it had been there long enough that nobody knew.

`/api/wind-data` self-joins `ensemble_statistics` u against v, which **squared**
it: 6,724 points for 1,681 cells, a ratio of 4.00. That join is what made a
silent 2x visible at all.

**The regridded tables were clean** (ratio 1.000), so no score was ever wrong.
That is luck, not design: the regrid keys by member and cell and overwrote with
an identical value, so two copies that *disagreed* would have been resolved by
whichever it happened to read last.

**The audit came first, and mattered.** Checking every (model, variable, run)
pair rather than the one slice that raised the alarm showed the duplication was
confined to GEFS wind — 5,295,150 duplicate rows per component in
`forecast_data`, 176,505 in `ensemble_statistics`, and **exactly zero
everywhere else**. All 5,295,150 groups were exactly two rows with identical
values (0 differing, 0 with an unexpected count, max within-cell gap 0), so
collapsing them could not lose information.

**`Data/migrate_raw_unique_keys.py`** deduplicates and adds the constraint.
Idempotent, `--dry-run`, and it **refuses to collapse any group whose copies
disagree** — that would be a different defect and picking a winner would hide
it. Scoped per (run, variable) so a clean database is a no-op rather than a
rewrite of 146M rows.

| table | deleted | index |
|---|---|---|
| `forecast_data` | 10,590,300 | `uq_forecast_data_natural_key`, 6,431 MB in 136 s |
| `ensemble_statistics` | 353,010 | `uq_ensemble_statistics_natural_key`, 258 MB in 4 s |

Three decisions inside it worth keeping:

- **`NULLS NOT DISTINCT`.** `ensemble_member` is NULL on the deterministic path
  and PostgreSQL treats NULLs as distinct by default, so a plain unique index
  would have left exactly half the hole open. Needs PostgreSQL 15+; CI runs
  `postgres:15` and the dev box 15.18, checked before relying on it.
- **The existing index could not be reused.** `idx_forecast_data_member_lookup`
  covers this key *plus `value`*, so a unique constraint there would reject
  exact duplicates while still permitting two rows with the same key and
  **contradictory** values — the worse case.
- **It went into `schema.sql`**, so a fresh install and the fixture both get it.
  `idx_forecast_data_member_lookup` exists in production and in no DDL file,
  which is how drift like this starts.

**Verified.** Counts exactly halved; every statistic of the surviving field
unchanged (n 3,362 → 1,681 with identical mean, std, min and max); a duplicate
insert is now refused by name; `/api/wind-data` is ratio **1.00** for all three
models. The index building at all re-proves the dedupe was total, since a unique
index cannot be created over duplicate data. Nine tests sit beside the
regridded-table ones in `test_regrid_idempotency.py`; four fail if the index is
dropped from `schema.sql`.

**Afterwards:** `VACUUM (ANALYZE)` on both tables, which matters beyond space —
`/api/health` reports `reltuples`, and deleting 10.9M rows left that estimate
stale. `forecast_data` is now 135,592,767 rows, down from 146,183,067.

### `/api/spatial-metric` ignores the lead time it documents — WITHDRAWN, this was my error

**There is no defect here.** `ssr` reads `hour` exactly as its docstring said —
1,439 points at `hour=6`, 1,430 at `hour=12`, 0 at `hour=24` — and the other
nine metrics read `hour_min`/`hour_max`, which also work (`mae` over 0–6 h is
0.2567 against 0.3320 over 0–24 h). Thresholds are read per-variable too.

**How I got it wrong**, because the method matters more than the conclusion:

1. I sent `forecast_hour`, which is not the parameter. The frontend sends `hour`.
2. I tested it on `mae`, which legitimately takes a *range* rather than an
   instant, so a single hour is inert there by design.
3. The real error: I grepped `args.get` inside the endpoint body, found no
   `hour`, and concluded nothing read it. **`request.args` is passed into the
   dispatchers**, which read their own arguments.

That third step is this document's own standing trap — *"a grep cannot settle it
alone; resolve the helper before claiming anything"* — applied to
`FROM {_frm}` and not applied here.

**What was really wrong was the docstring**, and that is now fixed: it named two
metrics of eleven and mentioned `hour` without the window that nine of them use.
It now carries a table of which metric reads which, because sending the wrong
one is silently inert and invisible in the response. Six tests pin the contract
rather than describing it.

**Two figures in these records remain corrected**, and for an unchanged reason:
they were requested with `forecast_hour`, so they were never per-hour. The
comparisons themselves stand, because both sides of each used the same call.

## 20. The 09-08 run is a MIXTURE of two forecasts — 2026-09-29

§18 found the AIFS wind was the `2025-09-16` run filed as `2025-09-08`. It was
not an isolated mistake. **Four of six model/variable combinations were the
09-16 run**, each verified cell-for-cell against source, with UKMO
precipitation matching 09-08 exactly as the control that the method can tell the
two dates apart:

| model | variable | actually from | evidence |
|---|---|---|---|
| AIFS | precipitation | **2025-09-08** | 17,915,148 rows exactly (§16) |
| UKMO | precipitation | **2025-09-08** | 1,449/1,449 cells, ×3.6e6 |
| AIFS | wind | 2025-09-16 | fixed in §18 |
| GEFS | precipitation | 2025-09-16 | 455/456/707 cells at two hours |
| GEFS | wind | 2025-09-16 | 1,681 cells × 4 members |
| UKMO | wind | 2025-09-16 | 7,597 cells × 4 members, two hours |

**The likely mechanism:** the cluster holds GEFS only for 09-16 to 09-20. GEFS
and the wind variables were evidently downloaded in a later batch and loaded
onto the existing 09-08 run row. Nothing in the pipeline had ever read the
initialisation time stored *inside* the data.

**What this invalidates:** every wind score for all three models, and every GEFS
precipitation score — including the audit's conclusion that GEFS is much the
worst model. Its MAE of 0.5256 against AIFS's 0.332, its CSI of 0.0109 at 6 mm,
and "GEFS has no events at all at 25 mm/6h" are artefacts of scoring a different
week. Only AIFS and UKMO precipitation survive.

### GEFS is now loaded as its own 2025-09-16 run

`Data/convert_gefs.py` (new) completes the converter set, so every forecast
table can be rebuilt from source. GEFS 09-08 **does not exist on the cluster**,
so relabelling it truthfully was chosen over preserving the fiction.

| stage | result |
|---|---|
| convert | 1,729,714 tp + 5,648,160 u + 5,648,160 v records; init read from the files as 09-16 00Z |
| scale | 2,560 files, **÷6 for the 1,280 `h%6==0` and ÷3 for the rest** — the fixed per-window rule |
| load | precipitation 1,520,352 / stats 104,681; wind 5,295,150 each — all exact, 14.4 min |
| regrid | 3,932,310 + 5,295,150 × 2 member rows |

Verified in the app: `/api/runs` reports three runs, the selector offers **two
dates** for the first time, AIFS and UKMO grey out at 09-16 with a reason, and
the map renders valid `Tue Sep 16 06:00 UTC` at +6h.

**Scores at 09-16 are empty, and that is correct.** Observations cover only
09-08, so `/api/observation-coverage` answers `record_end_lead_hours: -168.5` —
a negative lead, stating that the record ends a week *before* the run begins.
An honest empty, not a failure.

### Conventions `convert_gefs.py` had to establish

- **Longitude is 0-360** (275 → 295 for a domain stored as −85 → −65). Left
  alone, every row lands outside the domain and joins with **nothing** — the
  most destructive convention here and the one with no visible symptom.
- **The threshold is `> 0.01 mm`, and differs from AIFS's `>= 0.01`.** Measured
  over 4 hours × 30 members: 78,995 cells kept with raw minimum 0.02, 3,211
  dropped with raw maximum 0.01, no overlap. A first pass read one hour, saw a
  kept minimum of 0.1 mm and concluded there was no threshold at all. GEFS
  quantises to 0.01, so `> 0.01` and `>= 0.02` fit identically and which was
  originally written is not recoverable.
- **`step` and `time` live in the file** and are both used: `step` is
  cross-checked against the filename's `fNNN`, and `time` gives the
  initialisation, which the converter **prints** and refuses to mix. That check
  is the whole point — it is what would have caught this defect at the moment it
  was introduced.
- **The output filename must be rebuilt.** GEFS sources are `..._f003.nc`, and
  both downstream stages parse `-(\d+)h-`. `aifs react.py` skipped all 2,560
  files and said so; `load_to_postgres.py` does
  `int(match.group(1)) if match else 0` and would have loaded **every GEFS row
  at hour 0** — eighty hours of forecast in one, with no error.

### OPEN: the registry cannot describe a per-window export

The registry holds **one** `export_divisor_h` per run, and
`_increment_divisor` returns `period / exported`. For the legacy flat ÷3 that is
right: 3/3 = 1 for a 3-hour bucket, 6/3 = 2 for a 6-hour one that was halved.

The new GEFS run was scaled **per window**, so it is already mm/h — and
`record()` wrote `scaled, export_divisor_h = 3` from the module constant
anyway. At `h%6==0` scoring would therefore divide by 2 a second time.

**Inert today**, because 09-16 has no observations so nothing reads it. It stops
being inert the moment 09-16 IMERG is loaded. The fix is a third convention
meaning "already a rate, divisor 1 always" — the vocabulary currently offers
only `scaled` and `unscaled`, and neither is true here. That is a decision about
the registry's vocabulary, so it is recorded rather than taken.

## 21. Three spread metrics never worked for an hourly model — FIXED 2026-09-29

`crps`, `ssr_agg` and `brier` returned **0 cells for UKMO at every lead time and
every run**, while `ssr` and `correlation` returned 1,461 and 1,520 for the same
model and AIFS and GEFS were populated throughout. Found while building the
first three-model comparison, because UKMO's CRPS column was empty.

**The cause.** Those three used `_fetch_fcst_obs_pairs_spatial`, the aggregate
path, where `_rebin_to_common_window` returns `std = None` for any record it has
to combine — the spread of a mean is not the mean of spreads. UKMO is hourly, so
*every* record gets combined onto the 6-hour window, so the spread was never
recoverable and every spread metric skipped every record. AIFS passes through
untouched (its records already span 6 h); GEFS survives on its `h%6==0` records.

**`_member_cases_by_cell` was built for exactly this.** Its docstring says so:
"an hourly model had no spread there at all and every spread metric came back
empty. Re-binning each MEMBER first and pooling afterwards gives the exact
spread of the 6 h means." It was wired into the `ssr` map, the `correlation`
map, and the two point endpoints. **These three were missed** — an incomplete
migration rather than a wrong claim, since the record only ever said "both
spread-dependent maps", and `ssr` and `correlation` are those two.

**The fix is an adapter, not three rewrites.** `_member_pairs_by_cell` returns
the aggregate path's exact shape — `{(lat, lon): [(hour, mean, std, obs)]}` —
sourced from the member grid, so the metric arithmetic is untouched and only
where `std` comes from changes.

| metric | AIFS cells | GEFS | UKMO |
|---|---|---|---|
| `crps` | **1681** (was 1559) | 1435 (unchanged) | **1521** (was **0**) |
| `ssr_agg` | **1582** (was 1438) | 1321 (unchanged) | **1519** (was **0**) |
| `brier` | **1681** (was 1559) | 1435 (unchanged) | **1521** (was **0**) |

**AIFS gained cells as well**, and that is the second half of the defect: the
aggregate path reconstructs a cumulative model's increment spread as
sqrt(sigma(h)^2 - sigma(h-p)^2), which **comes out negative for ~13% of AIFS
records** and those were silently dropped. GEFS's coverage is unchanged but its
*values* move, because the spread is now exact rather than approximated (31%
high where the approximation resolved at all).

**Every AIFS, GEFS and UKMO figure for these three metrics changes**, including
`METRICS_AUDIT.md` §0's point CRPS column.

### Still on the aggregate path, deliberately and not

`mae`, `bias`, `rmse` and the categorical metrics stay there on purpose: they
never read `std`, and the member grid is members x cells x hours to compute a
mean the aggregate table already stores.

**But `COMPARE_REGION_METRIC_FNS` has the same hole.** The Comparison tab's
region mode maps `ssr_agg`, `crps` and `brier` to the same three functions and
builds its pairs from `_fetch_fcst_obs_pairs_spatial` once for every metric, so
**UKMO's spread metrics are still empty in region mode**. Fixing it means
sourcing pairs per metric rather than once, since swapping them wholesale would
move `mae`/`bias`/`csi` too. Left as its own change.

## 22. The registry gained a third convention, and the data went back to the legacy one — 2026-09-30

Two related decisions, and the second one reverses the visible effect of the
first while keeping its guard.

### `rate`, because two conventions could not describe a third thing

`_increment_divisor` returns the hours to divide a stored value by:
`period` for `unscaled`, `period / divisor` for `scaled`. Neither can express
**"each record was already divided by its own window"** — there the factor *is*
the period, so a single `export_divisor_h` cannot be true of the run.

GEFS 09-16 was scaled through the current per-window `aifs react.py` while
`record()` wrote `scaled, 3` from the module constant. Every `h%6==0` bucket was
therefore halved a second time at scoring, which read as **MAE 0.1864** where the
truthful value is **0.2318** — a 24% understatement that made GEFS look like the
best model at 09-16. Inert only while 09-16 had no observations; loading them on
2026-09-29 ended that.

`RATE` is now a convention, `resolve_divisor` returns the sentinel
`PER_WINDOW` for it, and `_increment_divisor` answers **1.0** at every window
length. `metrics.PER_WINDOW` **restates** `run_registry.PER_WINDOW` rather than
importing it — the two modules do not depend on each other — and a test pins
that the literals agree, the same bargain `fixture_db.py` strikes. Recording
`rate` *with* a divisor is refused, because that is the contradiction again.

### The stored units then went back to the legacy convention

Keeping two conventions in one database is worse than either. Measured, the two
GEFS runs differed in both respects:

| run | rule | stored decimals |
|---|---|---|
| 09-08 | `round(value / 3, 3)` — flat | 3 |
| 09-16 (as loaded) | `round(value / window, 4)` — per-window | 4 |

So 09-16 was re-scaled from the *unscaled* converted JSON with the legacy rule,
reloaded, re-regridded, and the registry put back to `scaled, 3`. Both runs are
now flat /3 at 3 decimals.

**The change is score-neutral, which is the point.** Per-window data labelled
`rate` and legacy data labelled `scaled, 3` give **identical** scores — MAE
0.2318, RMSE 0.4840, CRPS 0.1769 either way. The 0.1864 was purely the
mislabelling. Uniformity therefore costs nothing and removes a standing trap.

### `rate` stays in the code, and this is why

Nothing in the database uses it now. It is not dead: **the repository's
`aifs react.py` is the per-window version**, so the next GEFS load through the
current pipeline produces per-window data. Without `rate` the registry would
label that `scaled, 3` and reintroduce exactly this defect. Whoever loads GEFS
must either scale with the legacy flat /3, as here, or record `rate`.

## 23. The map and the scores now read one divisor — 2026-09-30

There were **two sources of truth** for the export divisor:

| path | read from |
|---|---|
| every scored metric | `forecast_run_registry` — **per run** |
| `/api/forecast-data` (the map) | `SCALED_EXPORT_DIVISOR_HOURS` — **per model, global** |
| `/api/compare/timeseries` (the forecast chart) | the same module constant |

Five scored call sites already passed `exported=_export_divisor(...)`; these two
did not, so they fell back to the constant. They agreed with the scores only
while every loaded run happened to match it.

**They did not have to.** Labelling GEFS 09-16 `rate` moved the score
0.23182 → 0.34311 while the map stayed at 0.23402 — the two screens showing
different rates for the same forecast, with nothing to indicate which was
right. §22's re-scaling removed the *occasion*; this removes the *possibility*.

Both now read the registry. `compare_timeseries` already had `_runs`, the
resolved model→init_time map, so nothing is looked up twice. The map calls
`_resolve_init_time`, the same resolver `get_model_run_id` goes through
immediately above, so it cannot name a different run than the rows it just
fetched.

**Verified by making the registry lie.** With the fix, flipping GEFS 09-16 to
`rate` moves the map 0.23402 → 0.46804 *and* the score 0.23182 → 0.34311; both
are then wrong, which is the point — a mislabel corrupts consistently instead of
splitting the two screens. Restoring `scaled, 3` returns both.

### What is stored, and what the map draws — for reference

| model | variable | stored | to reach mm/h |
|---|---|---|---|
| AIFS | precipitation | cumulative since init, ÷6 | difference consecutive records |
| GEFS | precipitation | bucket total ÷3 (3 h or 6 h bucket) | ÷2 more at `h%6==0` |
| UKMO | precipitation | already mm/h (m/s × 3.6e6) | nothing |
| all | wind u, v | instantaneous m/s | nothing |

Checked at one cell, +12 h: AIFS stored 0.1730 → 0.2740 differences to 0.1010
and the map returns 0.1010; GEFS stored 5.7530 halves to 2.8765 and the map
returns 2.8765; UKMO stored 8.9265 passes through and the map returns 8.9265.
**The "mm/h" on the legend is honest for all three.**

AIFS's storage is the one that surprises: the raw rows climb with lead
(0.059 → 0.187 across +6 h to +36 h at one cell) because they are a running
total, not a rate. Differencing works because
`C(h)/6 − C(h−6)/6 == (C(h) − C(h−6))/6`, which is the mean rate over that
window.

## 24. The 09-08 mixture is fully unwound — 2026-09-30

§20 found four of six model/variable combinations at `2025-09-08 00Z` were the
09-16 run, and recorded three as fixed. **Two of those three were not.** Loading
GEFS as its own 09-16 run created the correct run but never removed the 09-08
copies, so the count was five, not one:

| model | variable | was | now |
|---|---|---|---|
| GEFS | precipitation | 09-16 data under the 09-08 label | **deleted** |
| GEFS | wind u/v | 09-16 data under the 09-08 label | **deleted** |
| UKMO | wind u/v | 09-16 data under the 09-08 label | **replaced** from 09-08 source |

**It had stopped being harmless.** §20 reasoned these were inert because 09-16
had no truth to score against. Extending the observation record (§21) inverted
that: `regridded_observation` now spans `09-08 00:00`..`09-26 23:30`, so the
09-08 label was being scored against 09-08 truth while holding the 09-16
forecast. A fix recorded as complete had been quietly producing wrong numbers in
every tab for a day.

### Proof before deletion, not after

`scratchpad/prove_duplicates.py` full-joins each suspect against the 09-16 run
on `(hour, lat, lon, member)` over **every** hour, not the two hours §20
sampled. All five came back with 0 unmatched keys and 0 differing values across
54,501,912 rows — so the 09-08 copies carried nothing the 09-16 rows did not,
which is what made deletion safe rather than a judgement call.

**Three controls ran in the same pass**, and they matter more than the suspects:
a check that reports everything identical is broken, not reassuring. AIFS
precipitation differed in 17,154,506 cells, AIFS wind in 20,008,725 of
20,011,050 — independently confirming §18's replacement took — and UKMO
precipitation's 8,027,146 "unmatched" is the *entire* row count of both runs,
because the precipitation and wind loaders round coordinates differently
(`35.1562` vs `35.15625`, the open item below) and the two runs share no keys at
all.

### GEFS is deleted, not relabelled

GEFS does not exist on the cluster for 09-08, so absence is the only truthful
state. 27,575,044 rows across six tables — `forecast_data` 12,110,652,
`ensemble_statistics` 457,691, `regridded_forecast_member` 14,522,610,
`regridded_forecast_ens` 484,087, `forecast_run_registry` 3, and the
`forecast_runs` row itself.

**Dropping the run row is the part that makes the app honest.** With it gone the
selector greys GEFS out at 09-08 with a reason — the same path
`ComparisonTab.run.test.js` already covers for a model a run lacks — instead of
serving the wrong week silently.

### UKMO wind is replaced, and verified against the file

155 NetCDF files per component whose `forecast_reference_time` reads
`2025-09-08 00:00Z` at leads 0..198h. `convert_ukmo.py` wrote 23,550,700 records
each (= 21,195,630 members + 1,177,535 mean + 1,177,535 std), the load
reproduced those counts exactly in 42.2 min, and `--verify` over all 155 hours
reports **0 slices differing and 0 stat hours differing** for both components.
The same check before the replacement reported 7,594 of 7,597 cells differing in
every member.

Regrid: 4,243,590 member + 235,755 ensemble rows per component
(155 × 18 × 1,521).

### Why it survived four weeks and three checks

The 09-08 00Z run's valid times run to `20250916T0600Z`, so its last files are
named for the same date as the 09-16 run's *first*. Both runs have the same
grid, the same 18 members, the same 0..198h leads and the same 21,195,630 rows.
Every structural check passes on the wrong data. This is lesson 5 below
("shape agreement is not provenance") arriving for the third time — and the
registry's `loaded_at` was the one field that hinted at it: all five mislabelled
entries carried the identical `2026-09-02 12:46:20.378681` backfill stamp.

### What confirms the replacement is the right week

Not the row counts — those were identical before and after. The error growth
against ERA5:

| lead | +12h | +24h | +48h | +96h | +198h |
|---|---|---|---|---|---|
| MAE (m/s) | 0.9662 | 0.8812 | 1.0268 | 1.4329 | 2.6591 |

Monotone decay of skill after the first day is what a forecast scored against
its own valid times looks like. The wrong week gives a flat curve at a higher
level, because there is no forecast–truth relationship left to decay. **Add this
to the verification kit: for any run whose provenance is in doubt, plot MAE
against lead before trusting it.**

### ~~Still open after this~~ — closed 2026-10-01

`METRICS_AUDIT.md` §0 was stale in a new way: the stored data had been corrected
while the audit still reported figures derived from the mislabelled rows, so
every wind and GEFS number in it described data that no longer existed.
**Regenerated 2026-10-01 against the 2025-09-16 00Z run** by
`rederive_audit.py`, and §0's header now states which run it describes. Found
still listed as open during the 2026-10-06 sweep (§40).

## 25. Region mode gets the spread metrics too — 2026-10-01

§21 fixed `crps`, `ssr_agg` and `brier` for the maps and both point panels by
taking spread from the member grid, and said in the same breath that
`COMPARE_REGION_METRIC_FNS` still had the hole. It did, for two more days: region
mode fetched its pairs **once** and handed the same dict to all nine metrics, so
UKMO's three were empty in the Comparison tab's region view at every run and
every lead range.

**Two sources now, chosen per metric** — the point of the fix is that it is not a
swap:

| source | metrics |
|---|---|
| `_fetch_fcst_obs_pairs_spatial` — the re-binned mean/spread table | bias, mae, rmse, csi, pod, far, fss |
| `_member_pairs_by_cell` — the member grid | **crps, ssr_agg, brier** (`COMPARE_REGION_SPREAD_METRICS`) |

Swapping wholesale would have moved `mae` and the categorical scores onto a
different sample without anyone asking. The member query is gated on one of the
three actually being requested, because it is much the more expensive of the two
— UKMO at 49 hourly lead times is the slowest call in the endpoint.

**The headline needed it as well as the map.** `/api/compare/region-metrics` has
two consumers of the pairs: the per-cell points behind `cell_means`, and
`_region_pooled_metrics` behind the number the user actually reads. Routing only
the first would have left the headline empty while the map beside it filled in —
the §19 lesson (*check the display path and the scoring path separately*) in a
new place.

### Measured, live, at 09-16 over +0..48h

| model | crps | ssr_agg | brier |
|---|---|---|---|
| AIFS | 0.1076 (651) | 0.6894 (640) | 0.005355 (651) |
| GEFS | 0.1938 (651) | 0.5639 (546) | 0.007877 (651) |
| **UKMO** | **0.1415 (600)** | **0.9151 (586)** | **0.00569 (600)** |

Every UKMO figure was `None` with 0 cells before. They are also *sensible* rather
than merely non-null, which is the better check: UKMO's CRPS sits between the
other two, matching its MAE ranking, and its SSR of 0.9151 is the closest of the
three to 1.0. `mae`/`bias`/`rmse`/`csi` are unchanged for all three.

### A second defect found on the way, in pooled `ssr_agg`

Aggregate SSR is a *ratio* of spread to error. `_region_pooled_metrics` was
taking its numerator over the records that **have** a spread and its denominator
over **all** records — two different samples. For AIFS on the aggregate path
those sets genuinely differ, because the increment spread is reconstructed as
`sqrt(σ(h)² − σ(h−p)²)` and comes out negative for ~13% of records. The per-cell
function has always filtered both together; `_spread_pooled_samples` now makes
the pooled form agree with it. **This moves AIFS and GEFS numbers too** — it is
not only a UKMO fix.

### A test was pinning the hole in place

`test_ukmo_precipitation_has_no_probabilistic_scores` asserted UKMO's three were
`None`, with a docstring reading *"Not a bug, but a parity gap worth pinning"*.
The mechanism it described was correct and still is; the conclusion was wrong,
and §21 had already overturned it for every other surface. **A test can encode a
defect as intended behaviour, and its docstring will sound reasonable** — this
one explained the mechanism accurately and drew the wrong inference from it.
Renamed to `test_every_model_gets_probabilistic_scores_in_region_mode`, with the
old text quoted in place so the reversal is legible rather than silent.

`test_a_metric_with_no_value_still_counts_zero` used UKMO's missing CRPS as its
example of a legitimate `None`; it now uses `correlation` on precipitation, whose
spread the fixture makes flat on purpose, so the example is a real `None` with a
stated reason rather than a missing capability.

## 26. The registry's database tests had never run in CI — FIXED 2026-10-01

`Data/test_run_registry.py` has fourteen tests that need a real
`forecast_run_registry`. **Every one of them skipped on every CI run this
repository has ever had.**

The cause is one unset variable. `.github/workflows/tests.yml` gives the
`backend · pytest` job `DB_USER`, `DB_PASSWORD`, `DB_HOST` and `DB_PORT`, but
not `DB_NAME`, so `run_registry.DB_CONFIG` falls back to `weave_weather` — a
database the PostgreSQL service container does not create. `_skip_reason()`
returned `no database`, the module-scoped `cur` and `writable` fixtures skipped,
and the run was shorter by fourteen tests with nothing to show it.

| run | commit | result |
|---|---|---|
| 36738384700 | ba3fa88 | `778 passed, 41 skipped` |
| 36726212346 | 7002a2d | `778 passed, 41 skipped` |
| 36724828723 | 57a221c | `778 passed, 41 skipped` |

Identical, across three commits that changed the registry. The same suite
against a real database was `819 passed` with no skips at all.

**What it cost.** On 2026-09-30 four of these tests failed locally because they
hardcoded `RUN = '2025-09-08 00:00:00'` and asserted GEFS resolved there, which
stopped being true the moment the mislabelled GEFS rows were deleted (§24).
They were fixed to call `_a_loaded_run()`, which asks the registry which init
holds a combination instead of naming a date. CI was green before that fix,
green after it, and would have been green had the fix been wrong — the only
signal came from a developer running the suite by hand.

### The fix

The database tests now build on `fixture_db.py`'s throwaway database, which
exists wherever PostgreSQL does. `fixture_db.seed()` already registers its runs
through `run_registry.record()` itself — three models x three variables at one
init — so the read path has real rows, including the GEFS precipitation row at
divisor 3 that `TestTwoRunsCanDisagree` needs.

Three things had to be got right, and each is worth stating because each is a
way this could have been "fixed" into a worse state than before:

**1. A skip that moves is still a skip.** `_a_loaded_run()` skips when a
combination is absent, which is correct for a helper that must not assert an
inventory — and it means repointing the module at a database that happened not
to hold GEFS precipitation would have turned fourteen skips into fourteen
*passes* that verified nothing. This is the Traps list entry — *a refactor can
hollow out a test instead of failing it* — reached through the data rather than
the code. `TestTheRegistryHoldsWhatTheseTestsResolve` is the guard: it asserts
the four combinations are present and **fails**, naming them. The two tests that
loop over models now compare a whole dict, so a missing model is a failure that
names it rather than one fewer assertion. Verified by deleting GEFS
precipitation from the fixture seed and confirming three red failures.

**2. The fixture database turned a no-op into real DDL.** `writable` called
`reg.ensure_schema()`, which is `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.
Against `weave_weather` that was a no-op and the column already existed; against
a fresh fixture it is DDL wanting an ACCESS EXCLUSIVE lock on a table the
module-scoped `cur` connection was holding an ACCESS SHARE lock on, idle in
transaction, until module teardown. One process, both ends: self-deadlock, no
timeout, sits forever. (It only appeared now because the new guard test is the
first `cur` test in file order; previously every `writable` test ran first.)
`cur` is now autocommit — it is read-only, so there is no transaction worth
holding — and `writable` no longer issues DDL, because `fixture_db._schema_sql()`
already appends `run_registry.SCHEMA_ADDITIONS` at build time.
`TestEnsureSchemaIsTheColumnTheFixtureBuildsWith` pins that those two are the
same statement, so the fixture cannot drift away from what a loader would add.

**3. The workflow's existing guard was half a guard.** It already asserted the
service container answers before running pytest, precisely so a green tick could
not sit over untested SQL. That proves the *server* is up; nothing proved the
*tests reached it*, and this failure walked straight through the gap.
`conftest.py` now honours `WEAVE_REQUIRE_DB_TESTS`, which turns "the fixture
database is unavailable" from a skip into a failure, and the workflow sets it.
That covers every module built on the fixture at once, not just this one.

Result, for this module in an environment with a PostgreSQL server and no
`weave_weather`: **0 run and 14 skipped, before; 33 run and 2 skipped, after.**
Suite-wide in that environment, skips fall from 41 to 29 — the 12 recovered
here, with the remainder itemised below rather than left as a number.

### Still skipping in CI, and why

Three groups, all now accounted for rather than assumed:

- **2 — `TestTheDevelopmentDatabaseIsCoherent`.** Local-only *by design*: it
  audits `forecast_run_registry` rows that exist only in `weave_weather`. The
  fixture cannot stand in, because every fixture row is written by `record()`,
  which refuses an incoherent one — whereas the development database's rows came
  from `migrate_init_time.py`'s backfill and `backfill_conventions()`, neither of
  which goes through `record`, and can still be edited by hand. That is the
  state worth auditing. The module docstring and the workflow both say so, and
  the skip names its own reason.
- **9 — `test_point_list_caps.py`.** Fixed 2026-10-01, and it turned out not to
  be this section's problem at all. See §28: those nine passed locally while
  asserting nothing.
- **4 — `test_regrid_observations.py`.** Fixed 2026-10-01, see §31. The warning
  about `DB_NAME` held: the fix was to move the data tests onto a designed
  scene in the fixture, not to point `DB_CONFIG` at a real database, because
  this module's argument-guard tests depend on it naming nothing reachable.

**All three groups are now closed.** The only skips left in CI are deliberate
local-only data audits — two here and five in `test_regrid_observations.py`
(§31) — each of which names its reason when it skips.
- **14 — `test_convert_aifs.py`.** `pytest.importorskip('netCDF4')`, and
  `netCDF4` is not in `Data/requirements.txt`. A different problem with the same
  shape: a dependency absent from CI quietly removes a test class. Fixed
  2026-10-01 — see §30, where it turns out to have been a packaging gap rather
  than a test-wiring one.

## 27. Phase 5 is decided, and the arithmetic was low again — 2026-10-01

`DATA_EXPANSION_DESIGN.md` phase 5 was the last open phase: three decisions
rather than a build. All three are now settled. **Re-measured before deciding**,
per this document's own rule about never doing arithmetic on a previous
measurement — and the previous measurement was low by ~50%, having already been
corrected once for being low by ~5x.

| | 2026-09-24 | **2026-10-01** |
|---|---|---|
| whole database | 38 GB (1 run) | **123.52 GB** (3 inits) |
| a three-model run | ~37 GB | **55.30 GB** |
| ten runs | ~370 GB | **553 GB** |

The 200 GB figure that document warns about is crossed at **four** runs.

### Decision 1 — no retention limit yet, revisit at 250 GB

The user's, against those figures. Two more full runs fit.

**Implemented as a check, not a note.** `_check_storage_headroom` reports on
`/api/health` and prints at startup, the same treatment `_check_pool_headroom`
gets: a condition that is only written down is discovered too late, and here
"too late" is partway through a 55 GB ingest. `safe: false` leaves the endpoint
`healthy` — past the threshold means a decision is due, not that anything broke.

**It plans with a measured full run (55.30 GB), not the mean of what is loaded.**
The mean is 41.17 GB because one of the three initialisations is a partial 06Z
run costing 8.49 GB, so dividing headroom by it reports **3 more runs where the
answer is 2**. That is `DATA_EXPANSION_DESIGN.md`'s own warning — *do not read
the cheapest thing in the database as headroom* — arriving inside the check
written to enforce its threshold. I had it wrong in the first draft and caught it
by running the check against the live database rather than only the fake cursor.
Both figures are reported; only the conservative one drives the count.

### Decision 2 — the archive tier is costed, not built

Nothing is evicted, so nothing needs an archive. The analysis is recorded so the
choice is ready:

| tier | kept | per run | scores |
|---|---|---|---|
| hot | everything | 55.30 GB | exact |
| **drop native** | both regridded tables | ~21 GB | **exact, all of them** |
| summary only | `regridded_forecast_ens` | ~1 GB | approximate spread |

**The document frames this as members-or-not and that is a false choice.** The
two member tables serve different readers — `forecast_data` (72.99 GB, 59% of the
database) feeds the map, the point timeseries and the regrid, while
`regridded_forecast_member` (31.66 GB) is what every spread metric scores from.
Dropping only the native pair keeps every score exact. Dropping the member grid
too forces spread back onto `sqrt(σ(h)² − σ(h−p)²)`, which goes negative for ~13%
of AIFS records — the defect §21 and §25 exist to remove.

### Decision 3 — already resolved by the observation extension

The document says "the current run has truth for ~23.5 h of a 240 h forecast".
Obsolete: **89% of stored forecast-hours are scorable**, 4,220 of 4,752. The 11%
that are not is the 09-16 run's far leads running past 09-26, an honest edge.
Observations are 14.52 GB and scale with the *period covered*, not the run count.

### Two stale claims corrected on the way

- **`observation_data` "cannot be regenerated".** False since 2026-09-16;
  `load_observations.py` reproduces it bit-for-bit. It is 13.54 GB the API never
  reads, now kept by decision rather than for want of a rebuild path.
- **"~6 GB reclaimable from `regridded_forecast_member` via `VACUUM FULL`".**
  The table reports **0 dead tuples**; autovacuum has reclaimed it for reuse.
  The item is done and should stop being listed.

## 28. Nine tests that passed everywhere and tested nothing — FIXED 2026-10-01

§26 left `test_point_list_caps.py`'s nine database tests listed as "the same
root cause, not yet fixed". **They were not.** Fixing them meant first finding
that they had never tested anything — not in CI, where they skipped, and not
locally, where they passed.

`TestAgainstTheLoadedData` took a `client` fixture of its own:

```python
@pytest.fixture
def client():
    reason = _skip_reason()          # is api.DB_CONFIG reachable?
    if reason:
        pytest.skip(reason)
    api.app.config['TESTING'] = True
    return api.app.test_client()     # ...and then never uses the connection
```

`conftest.py` replaces `psycopg2.pool.ThreadedConnectionPool` with a `MagicMock`
*before* `flask_api` is imported, so `api.connection_pool` is a mock unless a
fixture replaces it. `db_client` does; this `client` did not. So
`get_db_connection()` handed the endpoints a mock cursor, and **a `MagicMock`
iterates empty**: every request returned `[]` with status 200.

Every assertion in the class is satisfied by an empty list:

| assertion | why it passed on `[]` |
|---|---|
| `'X-Truncated' not in r.headers` | nothing to truncate |
| `len(body) <= 5` | `len([]) == 0` |
| `if r.headers.get('X-Truncated') == 'true': ...` | the branch never ran |
| `[key(p) for p in capped] == [...]` | `[] == []` |

The reachability check was theatre: it proved a server was up and then never
spoke to it. Verified directly rather than inferred — reproducing conftest's
stub in a scratch script and calling `/api/wind-data` returns
`body type: list len: 0`, `X-Row-Count: 0`, `X-Truncated: None`.

**This is a different failure from §26 and a worse one.** There, real tests
skipped where the environment lacked a database; the signal existed and CI
could not see it. Here there was no signal anywhere, and the green tick was
accurate about a test that asserted nothing. §26 was found by reading skip
counts; this was found only by going to fix the skips.

### The fix

- The class now uses conftest's `db_client`, which monkeypatches
  `api.connection_pool` to a real pool on the fixture database. UKMO sits there
  on its own native grid (70 cells), so a limit of 5 genuinely bites.
- `test_every_url_returns_more_cells_than_the_low_limit` is the guard, asserted
  before anything reads through it: *more* than the low limit, not merely
  non-empty, or "a low limit bites" would be vacuous for a second reason.
- Truncation is now asserted outright — `X-Truncated == 'true'`, exactly
  `LOW_LIMIT` cells, `X-Row-Count` and `X-Row-Limit` agreeing — instead of
  sitting behind an `if` that could never fire.
- `test_todays_data_is_not_truncated` was really a claim about a constant: that
  the shipped cap clears the measured worst case (UKMO wind, 7,597 cells,
  946 KB). The fixture's 5x5 patch cannot carry that, so it moved to
  `TestTheDefaultCapClearsTheRealWorstCase`, which needs no database and
  therefore holds everywhere — including CI, where the original never ran.

Falsified rather than assumed: pointing the URLs at a model the fixture does not
hold reproduces the old empty-response state exactly, and gives **10 failures**
where the previous suite was green.

Result: 9 skipped in CI and 9 hollow passes locally become 21 real tests that
run in both. Suite-wide CI skips fall from 29 to 20.

### What this says about the rest

The two checks added in §26 would not have caught this. `WEAVE_REQUIRE_DB_TESTS`
turns a *skip* into a failure; these did not skip. The workflow's reachability
check proves the server answers; so did `_skip_reason`. **The thing neither
covers is a test that reaches a database it never queries** — and the only
general defence is the Traps list's: assert non-emptiness before asserting
anything about contents. Worth applying to any other module that builds its own
client instead of taking conftest's; `test_regrid_observations.py` is next and
its three `pytest.skip('...is not populated')` guards suggest the same question
should be asked of it.

## 29. The planning documents were audited against the code — 2026-10-01

Ten tracked `.md` files, checked against the codebase rather than against each
other. **Three were telling a story the code contradicted**, and all three failed
the same way: a sentence that was true when written and was never revisited —
which is the exact failure `CONSISTENCY_AUDIT.md` phase 6 exists to catch, found
this time in the audit documents themselves.

| document | was | now |
|---|---|---|
| `SYSTEM_DESIGN_PLAN.md` | S1–S6 unmarked since 2026-07-28; §2 said PR #2 was open | every phase reconciled against the code; §2 corrected |
| `CONSISTENCY_AUDIT.md` | titled "results of phases 1–4 — survey only, nothing was fixed" | all six phases, nearly all fixed — which it had contained for weeks |
| `METRICS_AUDIT.md` | §0 dated 2026-09-29 | banner naming the four changes that moved it since |

### What the reconciliation found

**S1 and the science track were substantially DONE and unmarked.** All three
converters, the observation loader, `init_time` on the regridded tables, and
unique natural keys that make a divergent re-load fail — plus exact per-member
wind speed and true neighbourhood FSS. Two months of work landed through this
document without anyone asking which S-phase it belonged to.

**Four phases are genuinely untouched**, and naming them is the point of the
exercise: S2's containerisation and observability (86 `print()` calls, no
`logging`, no request IDs), S3's Redis and load test, **S4 entirely**, and S5's
error boundary and code-splitting.

### Two gaps that were in no document at all

- **`DEPLOY.md` had no backup or restore section** — not a bad one, none — for a
  **123.52 GB** database. Now `DEPLOY.md` §9, written to state the real position
  rather than invent a procedure: rebuilding from source works and is *slow*
  (one model's wind at one init took **42 minutes** for the load alone), and
  `pg_dump` has never been exercised at this size. An untested restore is a plan,
  not a backup.
- **S4's config endpoint does not exist**, so `src/constants.js` keeps its own
  copy of model names, colours, member counts and metric bands while the backend
  keeps the registries. **This is the highest-value item left**, because
  backend/frontend drift is the shape of defects this project keeps finding —
  §19's four spatial metrics labelled wind in `mm/h`, and the `UI 'wind' is not a
  stored variable` trap. Adding a metric is still a two-place change, which is
  precisely S4's unmet exit criterion.

## 30. netCDF4 was never a declared dependency — FIXED 2026-10-01

The last of §26's three groups, and the only one that was not a test problem.

`convert_aifs.py`, `convert_gefs.py` and `convert_ukmo.py` all read source
NetCDF, all import `netCDF4` lazily, and all `sys.exit` with a message when it
is missing. **None of that was declared.** `Data/requirements.txt` never listed
it, so `pip install -r requirements.txt` produced an environment where the three
scripts that let every forecast table be rebuilt from source exit on their first
real use.

The visible symptom was 14 skipped tests. `test_convert_aifs.py` splits into a
numeric tier that runs anywhere and a file-reading tier behind
`pytest.importorskip('netCDF4')`, and its docstring said so plainly — "which is
not in `Data/requirements.txt` ... Same bargain as the PostgreSQL tests". The
bargain was the wrong one: PostgreSQL genuinely is not present on every machine,
whereas netCDF4 is a dependency this project simply had not written down.

Confirmed rather than inferred: blocking the import locally turns exactly 14
tests red, which is the count CI was skipping.

### What was added, and why that version

`netCDF4==1.7.4`, in `requirements.txt` rather than `requirements-dev.txt` —
the converters need it at runtime; the tests needing it too is a consequence,
not the reason.

Checked before committing, because a pin that cannot install is worse than no
pin:

- 1.7.4 ships an **abi3** wheel tagged `manylinux_2_27_x86_64.manylinux_2_28`.
  ubuntu-24.04 has glibc 2.39, so it qualifies. (An early check against
  `manylinux_2_17` alone reported 1.7.2 as the newest available and was simply
  the wrong question — pip on the runner accepts the union of supported tags,
  not one.)
- It needs nothing from apt, unlike cartopy: the wheels bundle HDF5 and
  netcdf-c. It pulls `cftime` and `certifi`.
- The whole of `requirements.txt` + `requirements-dev.txt` resolves to wheels
  for cp313 on that platform with it added, against the existing `numpy==2.4.6`
  pin. netCDF4 requires only `numpy>=1.21.2` there, so nothing is forced.

The local environment has 1.7.4 from **conda-forge**, which is why the version
looked available without checking PyPI. Worth remembering in a conda project:
what is installed says nothing about what `pip install -r` will find.

### The guard

`importorskip` stays, but its meaning has changed: it is now a convenience for
someone running the numeric tier on a partial install, not a statement that the
dependency is optional. So the workflow gained a step that **imports netCDF4 and
cartopy after installing** and prints their versions and linked C library
versions.

That is not redundant with `pip install` failing. The failure it catches is the
one these libraries actually have: a wheel that installs cleanly and then cannot
load its HDF5 or PROJ at import. `pip` would be green, the import would fail,
`importorskip` would swallow it, and 14 tests would vanish again — the same
shape as §26 and §28, through a third route.

## 31. The observation-regrid tests were measuring data, not the rule — FIXED 2026-10-01

The last of §26's three groups. Like §28, fixing the skips meant first noticing
that the tests were not quite what they appeared to be.

`test_regrid_observations.py`'s four database tests resolved through
`ro.DB_CONFIG`, so they skipped in CI. The obvious fix — set `DB_NAME` — is
the one thing that must not be done here, and the file now says so at the point
of definition: `test_the_guards_reject_before_touching_the_database` *depends*
on `DB_CONFIG` naming nothing reachable, because that is how the live-table
guard sitting below `psycopg2.connect` was caught. Setting `DB_NAME` would
leave those passing while no longer testing that the refusal precedes any I/O.

Pointing them at the fixture as it stands does not work either:

- the SQL/Python parity test read `observation_data`'s distinct coordinates, so
  the fixture's 0.5 degree grid would have given it almost nothing to check;
- `test_no_observation_is_counted_twice_or_dropped` compared the stored
  `regridded_observation` against the native table, and the fixture seeds those
  two independently rather than deriving one from the other — it would have
  **failed**;
- `test_interior_stencils_are_uniform_regardless_of_parity` would have passed
  on a field with one native point per cell, which cannot show a checkerboard
  at all.

### What they actually check

A rule. They were using whatever happened to be loaded as a supply of
coordinates, which made their coverage of the offsets that matter a matter of
luck. So they now call `ro.aggregate()` — the real GROUP BY, in real SQL —
over a scene defined in the test file: a 20x20 IMERG-like 0.1 degree lattice,
laid out to fill exactly 16 target cells with 25 native points each, spanning
whole-degree and half-degree centres on both axes. IMERG's lattice has centres
at odd multiples of 0.05, so the .25 and .75 **cell boundaries are themselves
native coordinates** — which is the only place the rounding rule can show a
difference. The scene is inserted into the fixture database in a transaction
that is rolled back, so the modules sharing that database never see it.

### The part worth keeping

Measured while designing the scene, and then written down as a test:

| rule | cells | stencil sizes | total points |
|---|---|---|---|
| `floor(x + half)` (correct) | 16 | **25** uniformly | 400 |
| round-half-to-even (the artifact) | 16 | **16, 24, 36** | 400 |

**Both preserve the total.** The partition test — "no observation is counted
twice or dropped" — passes under the defect, because the defect moves points
between cells rather than losing them. The uniformity test is therefore not a
corollary of the partition test but an independent assertion, and it is the one
that fails. That is now stated in the test rather than left to be rediscovered.

`test_the_scene_can_actually_show_the_artifact` pins the second row of that
table in pure Python. Without it, "every cell has 25" could be true of any rule
and the checkerboard test would be decoration — the same hollowing-out §28 was
about, one level up.

Falsified rather than assumed: reintroducing round-half-to-even in *both* the
Python rule and the SQL translation, so the two still agree with each other,
turns **9 tests red** — and, as the table predicts, the partition test is not
among them.

### The data audit, kept rather than delegated

The first version of this change dropped the live-table assertions entirely, on
the grounds that `regrid_observations.py --compare` already measures a rebuild
against the stored field. That was wrong in one specific way: **`--compare` only
runs when someone runs it.** The question "is the truth field still a partition
of the data it came from" should not depend on anyone thinking to ask.

So `TestTheLoadedTruthFieldIsCoherent` keeps it, **local-only by design**, the
same exception `test_run_registry.py` makes and for the same reason — the
fixture cannot stand in for data. The fixture's truth field is seeded to a known
answer by `fixture_db.py`; the live one came from a rebuild of a table
originally built off-repo, and a rebuild can stop early, run for one source and
not the other, or write different counts. None of those are reachable from the
code under test. (A straight re-append is *not* among them —
`uq_regridded_observation_natural_key` makes it impossible, which I found by
trying it rather than by reading the schema.) Five assertions:

- both tables are populated — a **failure**, not a skip. The versions before
  2026-10-01 called `pytest.skip('regridded_observation is not populated')`
  here, which is the hollowing-out this repository has now hit three times. A
  test that has decided it can run should not then decide it has nothing to say;
  an empty truth field means every scored endpoint returns nothing.
- the SQL and Python rules agree on the coordinates the data actually has —
  the case the designed scene cannot reach, since the scene covers the offsets
  that matter *by construction* and the live table may hold one nobody expected;
- `sum(source_points)` equals the native count, per source;
- interior stencils are uniform — the checkerboard, in the field the app scores
  against. The pre-existing table failed this (6x6 against 4x4); the 2026-09-04
  rebuild is what makes it pass, so this notices if that is undone;
- truth ⊇ forecast, for the loaded run, where the two grids come from different
  ingests and nothing forces them to agree. The fixture keeps its own copy of
  this invariant, which guards `fixture_db.py`'s two grid definitions drifting.

Falsified against the live table, inside rolled-back transactions rather than
reasoned about:

| injected fault | partition test | uniformity test |
|---|---|---|
| 1% of cells deleted (a rebuild that stopped early) | **fails** — 2,961,897 against 2,991,816 | passes |
| stencil counts perturbed by parity (the checkerboard) | **fails** | **fails** — 2 distinct sizes |

The two are complementary, which is the argument for keeping both: a partial
rebuild is visible only to the first.

Cost, measured: about 51 seconds, almost all of it two full scans of
`observation_data`. That is the price of auditing 123 GB and it is paid only
where the data exists.

### Result

4 skips become 23 tests that run everywhere, plus 5 that run wherever the live
database does — 28, up from 17 in this module.

**That closes §26's list.** CI goes from `778 passed, 41 skipped` at ba3fa88 to
**7 skipped**, and every one of those seven is deliberate: five here and two in
`test_run_registry.py`, each naming its own reason when it skips. Every
*accidental* skip this repository had is gone. The difference matters more than
the number — a skip that states why it is a skip is a decision; one that does
not is a hole, and this project had 41 of them.

## 32. The config endpoint, and the join nobody was checking — 2026-10-01

`SYSTEM_DESIGN_PLAN.md` S4 asks for one backend source of truth exposed to the
frontend, with the exit criterion that adding a metric is a single-place change.
§29 found it was the only phase not started, and the highest-value item left —
because backend/frontend drift is the shape of the defects this project keeps
finding, not a hypothetical.

**`GET /api/config`** serves the facts that were restated in `src/constants.js`:
the metric inventory with `requires_hour` / `requires_threshold` /
`unit_sensitive`, the variables and their units, the region suite, which region
metrics have no per-cell map (`fss`), which read the member grid, and the common
verification window. **No database access — 2 ms**, so it answers while the pool
is busy, the same argument that moved `/api/health` off a `COUNT(*)`.

### What it deliberately does not serve

Colours, labels, legends and band edges stay in `src/constants.js`. **This is not
a compromise.** `PLOT_STYLE_REGISTRY` uses a continuous `Normalize` for most
metrics while the browser overlay uses discrete bands — two intentional
renderings of the same number — so pushing one palette through the endpoint
would make them agree by breaking one. The pair that *do* share edges,
`ssr`/`ssr_agg` at `[0, 0.5, 0.8, 1.2, 2.0, 10.0]`, already match exactly.

### The tests are the deliverable, not the endpoint

An endpoint nobody reads changes nothing. Three joins are now checked:

| join | guards |
|---|---|
| `METRIC_REQUIREMENTS` vs the dispatchers | a declaration drifting from behaviour |
| `src/constants.js` vs `/api/config` | the frontend drifting from the backend |
| `VALUE_UNITS` vs `VARIABLE_UNITS` | two copies of the unit table |

**Verified to fail, not assumed to.** Flipping `csi`'s `requiresThreshold` in
the frontend gives `requires_threshold disagrees (backend, frontend): {'csi':
(True, False)}`; adding a metric to the backend alone names it. The JS parser
asserts it found at least 8 metrics before comparing anything, so it cannot pass
vacuously on a file it failed to parse — the hollowed-out-test trap recorded
under Standing traps.

**Why a Python test reads JavaScript.** The alternative is a jest test that
imports Flask, which is worse. Every single-sided test in this repo passed
throughout the defects that motivated S4 — four spatial metrics labelling wind
maps in `mm/h`, and the UI's `wind` not being a stored variable at all. Neither
side was internally inconsistent; they disagreed with each other, and only a
test that spans the boundary can see that.

### What was still two edits — CLOSED 2026-10-02, see §35

This section said the frontend "*consumes* the endpoint (`src/api/config.js`, a
soft dependency that falls back to the local constants and never blocks
rendering) but still *renders* from `METRIC_CONFIG`".

**The first half was not true.** `src/api/config.js` was imported by nothing but
its own test — a client with no caller. The selector did not fall back to the
local constants, it only ever used them. §35 wired it in.

## 33. `/api/runs` had no test — FIXED 2026-10-01

Found by going to measure the coverage claim rather than by reading anything.
`flask_api.py` is documented at 100% and measures 97%; of the 54 uncovered
statements, **21 are the `/api/runs` body and 6 are `available_runs`** — half
the gap in two functions.

Three places in the suite mentioned the path. A comment, a docstring, and an
assertion that a *different* endpoint's 400 hint contains the string
`/api/runs`. **None of them ever issued a request to it.**

That is worth more than 27 statements suggests. `src/App.js` fetches nothing
model-scoped until this endpoint answers, so every model-dependent view is
behind it, and `RunContext.jsx` reads four separate shapes out of the response.

### What the tests pin

`Data/test_runs_endpoint.py`, 19 tests. The one that earns its place is the
contract test. `RunContext.jsx` carries a comment recording a defect found by
hand: the UI calls the variable `wind` while the database stores `wind_u_10m`
and `wind_v_10m`, so looking up `wind` "finds nothing and returns null — which
reads as 'this run has no wind' and would have disabled every lead-time clamp on
the wind variable without erroring anywhere". Its own note on why no test caught
it is the point — *"a mock agrees with whatever you wrote it to say"*. The
backend half is now pinned against real SQL.

Two behaviours the endpoint cannot reach from the fixture as seeded are covered
by calling `available_runs` directly, on this module's own connection inside
rolled-back transactions: **ordering across more than one run** (`ORDER BY
init_time DESC` is the behaviour, since `latest` is literally `runs[0]`), and
**the registry-absent fallback**, reached by dropping `forecast_run_registry`
inside the transaction. That DDL takes an ACCESS EXCLUSIVE lock, so the fixture
sets `lock_timeout` — §26's self-deadlock turned into a fast error rather than a
hang, which is cheaper than rediscovering it.

### A fixture that was lying quietly

`fixture_db.seed()` registered its runs with `n_members` only, leaving
`hour_min` and `hour_max` NULL. **No real database looks like that** —
`run_registry.refresh_from_members()` fills them at load time. The fixture now
seeds the lead-time range it actually holds.

This is not cosmetic. `/api/runs` serves those columns straight through to
`RunContext.hourRangeFor`, which does
`Math.max(...entries.map(e => e.hour_min))` and rejects a non-finite result. A
JSON `null` is not rejected there — `Math.max(null)` is `0` — so a registry row
with NULL hours would clamp the lead-time scrubber to `{0, 0}` instead of
greying the model out. Tests written against the old fixture would have pinned a
response shape the UI cannot use. Verified by reverting the fixture change: two
contract tests fail.

### Result

`flask_api.py` **97% -> 99%**, 54 missing statements down to 27, with `get_runs`
and `available_runs` both at zero. The remaining 27 are singles and pairs
scattered across ~20 endpoints — error branches, not a second hole like this one.

### Now guarded — 2026-10-01

The claim decayed because nothing measured it. Two changes close that.

**CI measures coverage and fails under a floor.** The backend job runs
`--cov=flask_api --cov=metrics --cov-report=term-missing
--cov-fail-under=98.5`. Scoped to the two modules that carry a documented
figure, because a whole-tree percentage would be dominated by loader and
migration scripts the suite does not exercise, and a number nobody can act on is
the kind that rots. 98.5 is a floor, not a target: measured **98.86%**, 2365
statements and 27 missing, identical in a CI-like environment since the seven
local-only audits touch neither module.

Falsified rather than trusted, because a gate that reports without failing is
the same non-result as a skipped test. Appending a twelve-statement untested
helper to `flask_api.py` takes it to 98.40% and **pytest exits 1** — checked as
the process exit code, not as the `FAIL` line in the output, which a pipe will
happily hide.

**An unscoped `--cov` can no longer break.** `.coveragerc` now omits `*.pyx`,
`src/*` and `lib/*`. The mechanism is worth recording because it is not
guessable: **Cython extension modules report relative source filenames.**
`netCDF4`'s code objects carry `src/cftime/_cftime.pyx` and Cartopy's carry
`lib/cartopy/trace.pyx`, with no leading path, and coverage resolves a relative
filename against the working directory — so from `Data/` they resolve *inside*
`source = .` and get instrumented. The result was a crash rather than a wrong
number, and a different crash per machine depending on which compiled extension
the import order reached first: `SystemError: cannot instrument shim code
object 'project_linear'` here, numpy's `cannot load module more than once per
process` elsewhere. `python -m pytest --cov` and `--cov=.` both now pass, 903
tests, where the first failed 15 and the second died during collection.

**The hour it cost is the lesson.** The traceback named `cartopy/trace.pyx` in
its own stack — evidence about *what was being measured*. It was read as
evidence about *which tracer core was in use*, because §6's sysmon/ctrace trap
was already in mind, and that produced a confident report that "coverage cannot
run at all" and a recommendation to pin coverage backwards. Both were wrong; the
scoped invocations the README and `requirements-dev.txt` document had always
worked. Reach for the explanation in front of you before the one you are
carrying.

## 34. The runner pin moved, and its reason turned out to be wrong — 2026-10-02

`ubuntu-24.04` -> **`ubuntu-26.04`**, all four jobs, ahead of `ubuntu-latest`
migrating to Ubuntu 26 from 2026-10-19. **This is the pin working as designed**:
§6 pinned it so the migration would be "a deliberate commit whose diff points at
the cause" instead of arriving attached to whatever push happened to be next,
and that is what this is — its own commit, its own CI result.

Checked before changing the label, since a label that does not exist fails the
job before it starts: `actions/runner-images` carries `Ubuntu2604-Readme.md` and
is shipping image updates for it (20260927).

### The reason the pin gave was wrong

§6 and the workflow header both said: the backend job apt-installs
`libgeos-dev` / `libproj-dev` / `proj-data` / `proj-bin`, and **"Cartopy links
against GEOS and PROJ"**, so a runner image change moves those versions
underneath the render tests. Plausible, and false.

Measured rather than assumed, by parsing the ELF dynamic section of the wheel
that CI actually installs:

| wheel | compiled extension | DT_NEEDED |
|---|---|---|
| `cartopy-0.25.0-cp313-…manylinux_2_28` | `trace.cpython-313-x86_64-linux-gnu.so` | libstdc++, libm, libgcc_s, libpthread, libc — **no GEOS, no PROJ** |
| `shapely-2.1.2` | — | bundles `libgeos`, `libgeos_c` |
| `pyproj-3.8.0` | — | bundles `libproj` (and libsqlite3, libtiff, libcurl) |

Cartopy reaches geometry through shapely and projections through pyproj, and
both ship their own copies. It could not be otherwise: these are manylinux
wheels, and the manylinux policy forbids linking GEOS or PROJ from the system —
auditwheel either bundles a library or the wheel is not manylinux. So the apt
packages are not what the render tests run against.

The pin is still worth having, as a general caution about runner images — a
toolchain, a locale, a system library some *other* dependency does use. It is
just not the specific GEOS/PROJ guard it claimed to be.

§30's wheel arithmetic survives the bump in the direction that matters. It
recorded that `netCDF4`'s abi3 wheel is tagged `manylinux_2_28` and that
ubuntu-24.04's glibc 2.39 clears it. A newer image only raises glibc, and a
manylinux floor is a minimum — so every wheel that resolved on 24.04 still
resolves. The hazard would be a wheel tagged *below* the image, which cannot
happen by moving forward.

### Why the bump was low-risk, stated before it ran

The render tests assert the response is 200, that the body starts with the PNG
magic bytes, and structural figures like `n_common` and `n_models`. **Nothing
compares pixels.** A GEOS or PROJ version change could not have failed them by
shifting a coastline; only a crash would, and the libraries that could crash are
vendored in the wheels and travel with them rather than with the image.

### The apt step is gone too — 2026-10-02

Held back from the runner bump on purpose, so a red run would have had one
possible cause, then done in its own commit. `apt-get install libgeos-dev
libproj-dev proj-data proj-bin` is removed, and nothing in the repository shells
out to `projinfo` or `cs2cs` either.

**A green run would only have shown the suite did not crash**, which is weaker
than it looks and is the same non-result a skipped test gives. So the
verification step measures instead: it forces a real projection and a real
`buffer()` — a lazily-loaded `.so` is not mapped until something needs it, so a
bare import proves less than it appears to — then reads `/proc/self/maps` and
prints every `libgeos`/`libproj` actually mapped, labelled by origin. It asserts
at least one was mapped, so the force-load cannot silently stop working, and
that none came from outside `site-packages`.

What CI reported:

```
GEOS/PROJ libraries actually mapped into this process:
  VENDORED in a wheel  .../site-packages/pyproj.libs/libproj-bde9a34c.so.25.9.8.1
  VENDORED in a wheel  .../site-packages/shapely.libs/libgeos-3ef06f11.so.3.13.1
  VENDORED in a wheel  .../site-packages/shapely.libs/libgeos_c-abcdd5fa.so.1.19.2
```

The hash-mangled filenames are auditwheel's, which is itself the proof these are
vendored copies rather than system ones. The step stays as a canary: if a future
install really does need the system libraries, they are absent now and it fails
there, before pytest.

### The two notes that told a human to install them

`DEPLOY.md` §1 and `Data/requirements.txt` both stated flatly that cartopy needs
system GEOS and PROJ. **Softened rather than deleted, 2026-10-02**, because the
claim is not wrong everywhere — it is wrong by default. cartopy, shapely and
pyproj all publish wheels for Linux (x86_64 and aarch64), macOS and Windows, and
all three also publish an sdist; the system libraries are needed only when pip
has no wheel and falls back to building — an unusual architecture, a very new
Python, or `--no-binary`. Both notes now say that, and point at the measurement
rather than repeating the assertion.

## 35. The metric selector renders from `/api/config` — S4 CLOSED 2026-10-02

`SYSTEM_DESIGN_PLAN.md` S4's exit criterion is that **adding a metric is a
single-place change**. §32 built `/api/config` and the cross-boundary tests, and
left this as "a UI change rather than an architectural one". It was slightly
more than that, because of what the wiring turned out to be.

### The client had no caller

§32 recorded that the frontend *consumes* the endpoint through
`src/api/config.js`, "a soft dependency that falls back to the local constants
and never blocks rendering". **`src/api/config.js` was imported by nothing but
`src/api/config.test.js`.** `fetchConfig` was never called by the application;
`metricKeysFrom` and `unitFrom` had no readers. The selector did not fall back
to the local constants — it only ever used them, and `/api/config` was served,
tested on both sides, and never requested by the running app.

That is the same shape as §28 and §33 from a third direction: a well-tested
component wired to nothing. The tests passed because they tested the client, and
the client worked. Nothing tested that anyone used it.

### What now renders from the server

`useMetricConfig` (`src/state/useMetricConfig.js`) fetches once and merges;
`metricsFrom` in `src/api/config.js` holds the rules. The split is deliberate
and §32 already argued for it: **the server owns the facts, the frontend owns
the presentation.**

| decided by | what |
|---|---|
| `/api/config` | which metrics exist; `requires_hour`; `requires_threshold` |
| `constants.js` | label, description, colour scale, legend, **and order** |

Three rules worth stating:

1. **A metric the server does not serve is dropped**, even if `constants.js`
   still describes it. Offering one the backend will refuse sends the user to an
   error where they expected a map.
2. **The server's `requires_*` win.** They decide which controls appear and which
   parameters the request carries, so a local copy that disagreed would build a
   request the backend rejects. `test_config_endpoint.py` pins that the two agree
   today; this decides which one renders if they ever stop.
3. **Local ordering is kept and unknown metrics go last.** This is not a style
   preference: `jsonify` sorts keys, so the endpoint's order is alphabetical —
   an artifact of serialisation, not a UI decision. Verified in the browser: the
   server returns `bias, brier, correlation, …` and the selector shows
   `ssr, ssr_agg, correlation, …`, the curated order, with the same eleven keys.

A metric the frontend has never heard of is offered, labelled by its key, with
no colour scale. `metricColorFn` was hardened to return `() => null` rather than
`undefined`, because `metricLayer` calls that result per point — an uncoloured
map rather than a TypeError per cell. It looks unfinished until someone gives it
a label and a scale, which is accurate.

### It starts local and upgrades

The first render uses `METRIC_CONFIG`, so the panel is never blank and never
waits on the network; the merged list replaces it when the config arrives. If
the call fails `fetchConfig` resolves to `null`, nothing is replaced, and
behaviour is exactly what it was. That null is the trap in this hook — a
careless `setMetrics(metricsFrom(cfg, local))` without the check would replace a
working list with whatever the merge made of nothing, and `useMetricConfig.test.js`
pins both failure modes (rejected fetch, and a non-ok status).

### Verified in the running app, not only in jest

The jest tests cover the merge. The wiring is what jest cannot see, so it was
checked against a real backend:

- `GET /api/config → 200` now appears in the network log. **It never had before.**
- The selector's eleven options are exactly the eleven keys the server serves.
- `requires_hour` and `requires_threshold` drive the real controls: `ssr` shows
  the Forecast Hour picker, `mae` shows neither, `csi` shows Threshold — each
  agreeing with the endpoint's own answer for that metric.

One wrinkle worth recording because it nearly produced a false bug report: the
first probe said `ssr` did *not* show the hour picker. The labels are uppercased
in CSS, so `innerText` returns `FORECAST HOUR` and a case-sensitive `/Forecast
Hour/` misses it. The screenshot showed the control plainly. **The measurement
was wrong, not the app** — which is method lesson 11 again, one day later.

## 36. The service is observable — S2's observability item, 2026-10-02

S2's bullet read: *"`flask_api.py` still has 86 `print()` calls and imports
neither `logging`, `structlog` nor `sentry`. No request IDs, no latency/count
metrics. `/api/health` is deeper than it was but is not a readiness endpoint."*
All four are addressed. `Data/observability.py` holds it; `flask_api.py` wires
it in before any route is registered.

### The item that mattered was not the timestamps

Every endpoint ended:

```python
except Exception as e:
    print(f"❌ Error in forecast-data: {str(e)}")
    return jsonify({'error': 'Internal server error'}), 500
```

**That prints the message and throws the traceback away.** The one line a reader
most needs — where it failed — was never written down, in a 5,000-line module.
Seventeen of those are now `log.exception`, which keeps the stack, and
`TestErrorsKeepTheirTraceback` asserts `exc_info` is actually present rather
than trusting that the call was changed.

The other two consequences were real but smaller: nothing correlated two
concurrent requests, and there were no timestamps or levels, so a log could not
be filtered and "when did this start" had no answer.

### What is there now

- **Structured logging to stderr**, `LOG_LEVEL` and `LOG_FORMAT=text|json`. JSON
  carries `extra=` fields as fields, so `status` and `duration_ms` are queryable
  rather than substrings to parse back out of a sentence.
- **`X-Request-ID`, validated then propagated.** Accepted from the caller when
  it matches `[A-Za-z0-9._-]{1,64}`, generated otherwise, echoed on the
  response. **Replaced wholesale rather than cleaned**, because a half-sanitised
  id is a bug waiting to be found: an unvalidated header in a log line is how a
  newline in that header forges a log entry. Worth recording that werkzeug's
  test client *refuses to send* a newline header, so that case cannot be driven
  through a client at all — the validator is unit-tested for it directly, since
  a request need not arrive through werkzeug's client in production.
- **One access line per request**, with status, duration and client. Werkzeug's
  dev-server line is quieted to WARNING: it duplicated every request, carried no
  id and no duration, and logged after the context closed so it read `[-]`.
  Quieting it removed the only place the client appeared, so `remote_addr` moved
  onto our line — the peer socket, which behind a proxy is the proxy, stated
  rather than implied.
- **Counts and latency on `/api/health`**, bounded to a 1,000-sample reservoir,
  labelled `"scope": "this worker, since it started"` so nobody reads a
  per-worker number as cluster-wide.
- **`GET /api/ready`**: take a pooled connection, `SELECT 1`, 200 or **503**.
  503 rather than 500 on purpose — the process is fine and is telling the truth
  about itself, which is what lets a balancer route around it instead of paging
  someone. Health stays what it is: database size, pool, storage and export
  convention, read once after a deploy, not several times a minute.

### What deliberately stays a `print`

The 43 calls in the `__main__` startup banner. That is a CLI courtesy from the
dev server, not service output, and `gunicorn` never runs it.

**That boundary hides a real gap, so it is named rather than left implicit:**
the pool-headroom and storage-headroom warnings live in the same block, so in
production *nobody is told*. §27 added the storage warning "announced where it
can be acted on" — and in production it is not announced at all. Fixing that
means moving those checks to application start, a behaviour change to someone
else's work, and it belongs in its own commit.

### One self-inflicted lesson

The conversion was mechanical, and one `print(..., flush=True)` became
`log.warning(..., flush=True)`. `Logger.warning` takes no such kwarg, so it
raised `TypeError` inside an `except` block and **seven tests went red**. The
flush was load-bearing for a print — stdout is block-buffered when redirected to
a file, which had hidden that line once before — and is simply unnecessary now,
since `logging` flushes on emit. The comment explaining the original reason is
kept next to the line, with the reason it no longer applies, because the next
person to read it will otherwise wonder where the flush went.

A mechanical edit across 43 call sites needs the suite run before it is
believed. It was, and that is the only reason this is a footnote.

## 37. Tropical cyclone tab — REQUESTED and BUILT 2026-10-02

Two features asked for, both about showing an ensemble's *disagreement* rather
than its mean:

1. **Hurricane track display** — every ensemble member's predicted storm track
   on the map at once, so track uncertainty is visible across the forecast
   period. The conventional name is a spaghetti plot.
2. **Ensemble scenario overlay** — every member's field rendered as a
   semi-transparent layer simultaneously, so a reader can see whether the
   scenarios cluster tightly or diverge.

In a new tab. **The data is on the HPC**, and the request came with two warnings
attached that are worth more than the feature description: *the data structure
may be different from ours, and the dates may be different too.*

### Status — built, and both provenance questions closed

A fourth tab, five views, **992,730 track rows over 1,180 runs** from three
centres. `TC_DATA_ACCESS.md` is the survey and `TC_TAB_DESIGN.md` the design;
both carry what the build found that the design had not.

Both warnings landed. The structure *was* different — CXML tracker output, one
row per member per lead, not a gridded field — which made feature 2 a derived
strike-probability field rather than a stack of layers. And the dates were
different twice over: a different init cadence, and **two generations of the
same product scored against two different IBTrACS vintages.**

**Both open provenance questions were settled from the files** (2026-10-02,
after the instruction to skip emailing `wang.shuoc`):

- `output/` was scored against the 2026-04-27 best track, the April
  `storm_2016_2024_*` set against the 2025-09-17 one. They disagree for **24 of
  138 storms** — IBTrACS revises retrospectively — so the two generations must
  not be mixed.
- The June re-selection was selecting for a **complete +144 h window**: all
  1,180 loaded runs reach exactly +144 h and none falls short. The storms it
  dropped were dropped for not reaching six days, not for being wrong.

**The one refused file is loaded.** `egrr_72h_GITA.csv` was the only file of
1,181 the loader ever rejected, for carrying two `cyclone_id` cycle stamps. It
turned out to be MOGREPS's **time-lagged ensemble**: the 36-member 12Z ensemble
is 18 members from 12Z plus 18 carried forward from 06Z, and all 36 agree that
`valid - lead` is 12Z. The stamp says where a member came from; it is not a
second initialisation. 431 of the 432 MOGREPS files carry one stamp, so the
check was right to fire and wrong to refuse.

The rule is now **causal rather than constant** — a member may come from an
earlier cycle, never a later one — which keeps the §18/§20 guard (two
independent statements of the init, the defect where AIFS wind stored at
2025-09-08 was the 2025-09-16 run) while admitting the file. The registry
held a `lagged_members` column for a few hours — 18 of 36 here — and it was
removed the same day, then superseded by something better.

**Met Office documentation (supplied 2026-10-02) confirms what GITA implied:**
MOGREPS-G is a 36-member time-lagged ensemble, 18 from the stated cycle plus 18
from six hours earlier, **aligned by valid time**. That is a property of the
system, true of all 432 MOGREPS runs here, not of the one file that happened to
disclose it — so the tab now states it on every MOGREPS run, which is the
"honest version" this file called for and said was blocked on confirmation.

**The magnitude I attached to it was wrong, and is retracted (2026-10-06).**
§37 stated that MOGREPS error curves are pessimistic by roughly 26 km. That
came from GITA's 12Z run alone, split at member 18 on the strength of its
`cyclone_id` stamps: **+25.8 km, 95% CI [+9.1, +42.6]**, n=900. The same split
over every MOGREPS point gives **−2.1 km, CI [−4.1, −0.3]**, n=335,821 — 373x
the sample, opposite sign, indistinguishable from zero.

**And the mechanism is disproved.** The claim assumed members 18–35 are the
previous cycle's forecasts carried forward. Tested against the raw CXML for
2018-02-11, where both cycles exist: a 12Z file's members 18–35 match the 06Z
file's members 0–17 at **1 of 504** shared valid times, against 2 of 504 for the
null. Different forecasts. Member number does not identify the lagged half.

The earlier write-up explained the archive-wide null away — "the ids stop
encoding which half, so both blocks are a 50/50 mix and the penalty cancels".
That is possible, and it was reasoning backwards from a number I wanted to keep.
A one-run result that reverses sign at 373x the sample is a one-run result.

What survives is only the documented fact: MOGREPS-G is a 36-member time-lagged
ensemble. Some pooled penalty must exist in principle; **its size is not
measurable from this archive**, and the provenance needed to correct it is
absent from the derived CSVs *and* from the raw CXML, whose header carries a
single `baseTime` and no per-member cycle marker. Nothing is corrected because
there is no established bias to correct.

**This is the fifth time in this project a claim came from one case.** The
longitude convention three times, the IBTrACS vintage sample, and now this. The
tell was present each time and ignored each time: a number from a single unit of
the data, stated without its sample size.

**The archive is now fully loaded: 1,181 runs, 993,630 track rows.**

Fixing it surfaced a wrong claim of my own. The loader warned that 3,612
longitudes had arrived in 0-360 form and that this meant the upstream
processing had changed. It had not: the *forecast* column is signed ±180 in
every one of the 1,181 files, but the *observed* IBTrACS `LON` is not — it
reaches **253.6**, with 41,159 values above 180 across 85 files, every one a
dateline storm. Both columns pass through the same normaliser, so one counter
conflated them and the message would have fired on all 85, sending someone to
hunt a change that never happened. The claim came from measuring BERYL, in the
Atlantic, which cannot reach the dateline. **That is the third time a longitude
claim here has come from one case** (see `TC_DATA_ACCESS.md`); the counters are
now separate, and only a forecast conversion warns.

**The tab was unusable on a phone, and the map was the part that vanished.**
Found 2026-10-05 by opening it in a narrow pane. The chart panel is a fixed
`340px` with `flexShrink: 0`; the map is `flex: 1`. Below the app's 760px
breakpoint the two were still laid out side by side, so the panel took its 340
and the map got the remainder — measured at a 397px viewport, **28 pixels**,
with its own zoom buttons hanging off the edge.

`App.js` has had an `isNarrow` state at `< 760` since long before this tab; the
tab simply never received it. It does now, and below the breakpoint the map and
panel stack. One listener, one threshold, no second breakpoint invented.

Two things the fix needed that the first attempt did not have. The map takes a
fixed height when stacked, because `flex: 1` in a column whose parent scrolls
collapses to nothing — the same defect one axis over. And `invalidateSize` now
runs on `isNarrow` as well as on `active`: Leaflet does not notice container
resizes, so crossing the breakpoint left the view computed at 28px wide, with
tracks off the edge and unpainted tiles. It re-fits the stored bounds too,
since what framed a storm in a sliver does not frame it in a full-width map.

Worth noting what nearly hid this: at the desktop widths every previous check
used, the layout is correct and the map is 911px. The defect needed a narrow
pane to appear, and `README.md` advertises the app as responsive below 760px.

**Checking that claim found a second one, on every tab.** The tab bar does not
wrap and cannot: its height is `TAB_BAR_H` and each tab is positioned at `top:
TAB_BAR_H`, so a second line slides under the content. At a 375px viewport its
content is **408px**, and the run selector sat from x=218 to x=408 — 33px past
the edge, with `overflowX: visible` and the page not scrolling. The cycle
dropdown was not merely clipped, it was **unreachable**, on all four tabs.
The bar now scrolls horizontally; at desktop widths it does not overflow, so
nothing changes there. The selects inside are native, so their popups are
unaffected — a custom absolutely-positioned dropdown added to that bar later
would be clipped, since `overflow-x: auto` forces `overflow-y` to auto.

The `README.md` claim is rewritten to what was measured: at 375px, all four
tabs have no horizontal page overflow and no control off-screen. It also now
says what is *not* claimed — this is a desktop-first analysis tool, and "nothing
is broken or unreachable" is a weaker promise than "designed for mobile".

**`T` is settled too, 2026-10-06 — the last open question on this tab.** It is
the centre's own forecast cycle numbered from the earliest archived run for that
storm, so **T=0 is the earliest initialisation and T=12 the latest**. The
loader's comment said "cycles back"; it counts forward. Monotonic in `init_time`
across all 401 storm-centre pairs.

Elapsed hours is T x the centre's own cycle interval — **12 h for ECMWF, 6 h for
MOGREPS and GEFS** — but only for 96% / 91% / 83% of pairs respectively, and
every miss is a positive multiple of the interval. A cycle that produced no file
leaves T under-counting the gap, so **T is a cycle number, not a duration**:
derive hours from `init_time`.

That also explains the filename defect this file already records. The label is
always **T x 6**, right for the two 6-hourly centres and wrong by 2x for ECMWF,
because the generating script assumed 6-hourly for everyone. The defect was
known from the lead ranges; the cause was not.

Worth noting the shape of this one: the question sat open for four days as "one
email to `wang.shuoc`", and the answer was a single `GROUP BY` over a column
already in the database. The same was true of both IBTrACS questions and of
GITA. **Four provenance questions, four answers already in the data** — the
pattern is strong enough now to invert the default: assume it is measurable
before assuming it needs asking.

Nothing on this tab is open.

**525 rows dropped by `ON CONFLICT DO NOTHING` — found by a deployment
document, then explained by going and looking.** The loader reported 993,255
rows read; `cyclone_track_member` held 992,730. Six documents quoted the first
number as the table.

The first explanation was a guess, and it was wrong. The uniqueness constraint
excluded `cyclone_id`, so the obvious reading was that members tracking two
candidate cyclones were losing one — plausible, because members disagreeing
about genesis is real in this data and MOGREPS reports up to 23 variants for a
single storm. It was written up with that caveat and acted on.

**Checking the source settled it in one pass.** All 525 collisions are in one
file, `kwbc_0h_MATTHEW.csv`, and all are identical in every field including
`cyclone_id` — 1,050 rows that are 525 records each written twice. And across
all 1,181 files, **no member ever carries more than one `cyclone_id`**, at one
lead or over its whole track: the id is the member's genesis label and is
constant along it. So the genesis-variant explanation was not merely unproven,
it was impossible, and widening the constraint recovers exactly nothing.

Three things were done anyway, and only one of them is about the 525:

1. **The loader counts and names exact duplicates.** It drops them — that was
   always right — but no longer silently. On this archive it prints
   `525 byte-identical duplicate row(s) ignored ... kwbc MATTHEW: 525`. A
   repeat with a *different* position is refused instead of counted, because
   that is a contradiction and picking one would invent a track.
2. **The constraint was widened to include `cyclone_id`** — not as a fix, but
   because the narrow key asserted "a member has one position per lead", which
   is a modelling claim nobody made. Nothing in this archive exercises it; it
   is there so a future one cannot lose a row quietly. `widen_track_constraint`
   migrates an existing database, since `CREATE TABLE IF NOT EXISTS` does
   nothing to a table that already exists — schema source and deployed database
   disagreeing is §24's shape.
3. **The views choose one track per member, in one place.** Admitting the row
   without this would have moved the defect rather than fixed it: a silent drop
   at load time becomes a polyline teleporting between two storms at render
   time. The rule is longest candidate first, ties by earlier start then id,
   and `/api/cyclone/tracks` reports `variant_members` so a discard is visible.
   The fixture seeds a member with two candidates, because a rule nothing
   exercises is a rule nobody has tested.

**The lesson is about the order of operations, not the bug.** The guess was
written into six documents and a recommendation before anyone opened the source
file, and the check that disproved it was a thirty-line script over data already
sitting on Explorer. Worth noting too how it surfaced at all: not from a test,
not from the app, but from running `count(*)` because a deployment document
needed a figure someone might verify. **The counts in a document are a test, if
anyone runs them.**

**One defect found by re-opening the tab, 2026-10-02.** Every storm or centre
change fired a request for the new storm with the *previous* storm's
initialisation — a pair that cannot exist — which 404ed, and was then followed
by the correct request. The init was held in state and reset in an effect,
which is one commit too late: effects run after the render, so the three fetch
effects had already gone out with the stale value. The `alive` guards meant the
404 was never *displayed*, which is why it survived the original build and the
screenshots: the tab looked right and only the network log disagreed.

Two costs, neither visible on screen. Each doomed request was a real database
query, and a tab that reliably emits 404s is a tab whose logs cannot be used to
find the 404s that matter — which undoes some of §36's point. Fixed by deriving
the initialisation during render instead of storing it, so the invalid pair
never exists rather than existing briefly and being cleaned up.

`src/components/CycloneTab.test.js` pins it by asserting a property of **every**
request made rather than of the final state — the final state was always
correct, which was the whole problem. Three of its four cases fail against the
previous version; the fourth passes either way and guards something else.

### Take those two warnings seriously — they name this project's two worst bugs

This repository has paid for both already, and the cost was weeks:

- **"The structure might be different."** The export-convention reconstruction
  (§13, §22) took days and produced `SCALED_EXPORT_DIVISOR_HOURS`, because
  nothing recorded how the stored numbers had been scaled. The GEFS filenames
  still lie — every file is named `..._3_Hour_Accumulation_...` including the
  ones holding 6-hour totals (Standing decisions). A new source with an
  unrecorded convention is the same trap with a new name.
- **"The dates can be different."** The single most expensive defect here was a
  **4-hour UTC shift** in the precipitation truth and not the wind truth (§12),
  which moved every precipitation number in the app and *changed which model
  looked better*. Right behind it, five of nine model/variable combinations
  carried a different run's data under the 09-08 label (§20, §24).

So the first task is not code and not schema design. **It is opening the files
and writing down what is actually in them**, and the test that settles
provenance is already known: §24's method lesson — *plot MAE against lead time;
a forecast scored against its own valid times decays monotonically, the wrong
week gives a flat curve at a higher level.*

### What is genuinely new, and what is not

**The track feature is a new data shape.** Everything in this app is
`(model, variable, init_time, forecast_hour, latitude, longitude, value)` on a
0.5° lattice. A cyclone track is not that: it is an ordered polyline per member
— `(member, forecast_hour) -> (lat, lon)` plus intensity attributes such as
minimum MSLP and maximum 10 m wind — with no grid at all. That wants its own
table and its own endpoint shape, not a variant of
`regridded_forecast_member`. It is also *small*: tens of points per member,
against 1,681 cells per field.

**The scenario overlay is mostly not new data.** `regridded_forecast_member`
already holds per-member fields on the analysis grid, and that is exactly what
feature 2 renders. What is new is the volume on the wire and the rendering.

### The one number to design against

Measured: **1,681 cells** on the analysis grid, and the registry's member counts
are **AIFS 50, GEFS 30, UKMO 18**.

So one lead time of one variable, all AIFS members, is 1,681 × 50 ≈ **84,000
points** — against a `POINT_LIST_MAX_CELLS` of 20,000 that exists because the
*single-field* worst case was 7,597 cells and 946 KB (§6). **The current
endpoints refuse this by design, and they are right to.** Feature 2 therefore
needs a decision before it needs code, and the options are already visible in
this codebase:

- **render server-side**, which the Cartopy path (`_render_metric_map_png`)
  already does for metric maps — one PNG of 50 translucent layers instead of
  50 layers of JSON;
- **send a compact binary** (typed arrays) rather than JSON objects per cell;
- **reduce before sending** — contours or quantile envelopes rather than every
  member's every cell, which may be the better *visualisation* anyway.

Worth noting that 50 translucent canvas layers is a rendering problem as much as
a transfer one, and that the honest version of "do the scenarios cluster" is
often a spread or quantile field rather than 50 overplotted ones.

### Two things that will bite, from this codebase specifically

- **The domain is hardcoded**, and S4 still lists that as open. The analysis
  grid spans roughly 24–46 N, −86 to −64 W. **A hurricane track will leave it.**
  Whatever else happens, the extent has to become data before a track can be
  drawn across a basin.
- **Storage.** §27 set retention at "no limit yet, revisit at 250 GB" against a
  measured 123.52 GB, with a three-model run at 55.30 GB. A cyclone case loaded
  as full member fields is another run-sized ingest, so this feature and that
  threshold meet each other at about the second load.

### What to answer from the HPC files before designing anything

- Format: ATCF a-deck/b-deck, NetCDF, GRIB, CSV, TC-vitals?
- **Is it tracker output or raw fields?** Already-identified cyclone centres per
  member is a loading job. Deriving centres from MSLP or vorticity is a
  different project, and the difference should be settled before anyone
  estimates this.
- Which models, how many members, which initialisations, what track cadence
  (6-hourly is typical for tracks, against our 3- and 6-hourly fields)?
- Does the storm period overlap any loaded run? If not, feature 2 needs its own
  ingest rather than reading what is already here.
- Which intensity attributes exist — minimum MSLP, maximum wind, radius of
  maximum wind?
- Which basin, and how far outside the current extent does it go?

### Sequencing

1. Read the files. **`TC_DATA_ACCESS.md` is the plan for this step** — where to
   look on Explorer, whose directory it is and what that obliges, the survey
   stages, and the gate it has to pass before anything is designed. It leads
   with §11's two failures, because the last search on this cluster produced a
   wrong recorded decision by generalising from one directory, and spent three
   weeks reading "not on the development machine" as "does not exist".

   The data is in **`/projects/k.aggarwal/Shuochen`** — inside our own
   allocation, next to the `WEAVE/` directory §11 used, so §11's
   "someone else's directory" caution does **not** transfer. What does carry
   over is enumerating the whole tree before concluding anything, and asking
   whoever produced it how it was produced: that trail (`era5_subset.py`,
   `regions_config.json`) is how §11 confirmed the ERA5 bounds instead of
   assuming them.
2. Verify provenance with MAE-against-lead before trusting a single number.
3. ~~Then a design note.~~ **`TC_TAB_DESIGN.md`, written 2026-10-02.** Tables,
   normalisation, the verification gates, and the scope boundaries — decided
   from the files where the files decide them, and named as open decisions with
   owners where they do not.

   **It does not decide feature 2, deliberately.** "All individual model runs as
   semi-transparent layers" has three readings — member gridded fields, member
   tracks, or a field *derived* from the tracks — and they differ by two orders
   of magnitude in cost. There are no gridded fields in the folder at all, so
   the first is a fresh ingest against §27's retention threshold; the third
   computes from 197 MB already on disk. That choice belongs to whoever asked
   for the feature, and it is the only thing blocking design.
4. Then the tab. That part is cheap: the tab bar is a literal array in
   `src/App.js` (`[['visualization', …], ['analysis', …], ['comparison', …]]`)
   and adding a fourth entry plus a component is the established pattern.
   One caution — `AnalysisTab.jsx` is 1,264 lines and is on S4's deferred-refactor
   list. A cyclone tab should not become the fifth large component.

**Nothing here is started**, and nothing should be until step 1 is written
down. `TC_DATA_ACCESS.md` says what "written down" has to contain.

## 38. The README's feature claims, audited — 2026-10-06

Prompted by the responsive claim turning out false in two ways: it had sounded
plausible for months and nobody re-read it. So every countable claim in
`README.md` was checked against the code or the database rather than against
memory.

**Eight held.** AIFS 50 / GEFS 30 / UKMO 18 members (confirmed in both
`forecast_run_registry` and `regridded_forecast_member`); 11 verification
metrics (`METRIC_CONFIG` has exactly 11 keys); 9 colormaps; 5 uncertainty
modes (`null | vsup | bivariate | fan | texture`); buckets 0–20
(`Math.max(0, ...)` / `Math.min(20, ...)`); the 3-step onboarding tour, whose
step titles match the README's parenthetical word for word; Viridis as the
default colormap; and the responsive claim, now that it has been fixed.

**Two did not.**

### `temperature_2m` and `pressure_msl` are declared, not held

The README said the database "also holds Temperature 2 m (K) and MSLP (hPa) for
future exposure". The `variables` lookup table does carry rows for both — and
`forecast_data` has **zero rows** for either `variable_id`. A schema row was
being read as data. The units were wrong too: the table says `pressure_msl` is
in **Pa**, not hPa.

Worth noting how this one nearly escaped: an earlier table inventory in this
session reported `variables` and `models` as having **0 rows**, because it read
`n_live_tup`. They have 5 and 3. That is the same estimate-as-count mistake as
method lesson 17, made twice in one session, and the second time it would have
produced the opposite wrong answer — "the variables table is empty, so the claim
is false" happens to reach the right verdict by the wrong route.

### The scrubber addresses a 6-hourly subset, not the archive — OPEN

`constants.js` builds the timeline as `for (let h = 0; h <= 360; h += 6)`. The
stored data does not line up with it:

| model / variable | stored steps | range | not on the grid |
|---|---|---|---|
| AIFS precipitation | 60 | +6..+360 | 0 |
| GEFS precipitation | 80 | +3..+240 | **40** |
| UKMO precipitation | 155 | +0..+198 | **121** |
| GEFS wind | 105 | +0..**+384** | 44, incl. 4 past +360 |

So roughly four fifths of the stored UKMO steps and half the GEFS 3-hourly
steps are not selectable, and 24 hours of loaded GEFS wind sits beyond the
scrubber's top.

**RESOLVED 2026-10-06: the scrubber follows each model's own cadence.** The
standing decision that display paths keep native cadence settled it; the
6-hourly grid was never a decision, just a constant nobody revisited.

`GET /api/forecast-hours?model=&variable=&init_time=` returns the actual list.
**Derived from the rows, not stored on the registry** — a `hours` column would
be faster and could drift from the data it describes, which is §24's defect. One
group costs 22 ms (AIFS), 52 ms (GEFS wind) or 66 ms (UKMO's 155 steps); the
same aggregate over every group is ~850 ms, which is why it is a lazy endpoint
rather than a field on `/api/runs`.

`hour_min`/`hour_max` could not have served: UKMO's steps are 1, 2, 3, 4, 5, 7,
8, … and no min/max/stride reproduces them, so a client assuming a stride would
offer lead times the run does not hold.

Verified in the browser: the slider shows **60** positions for AIFS
precipitation, **155** for UKMO, **105** for GEFS wind, and its last position
renders `GEFS · Wind · +384h` with a populated field — a lead time that could
not be selected at all before. It falls back to the old constant while the
fetch is in flight or if it fails, because a briefly coarser slider beats a
briefly absent one.

**And the build shipped a defect that the next check caught.** The first
version of `fetchForecastHours` built its query by hand and skipped the api
layer's two gating lines. On every page load it fired before the run had
resolved, so `init_time` was absent, so the backend — which refuses a missing
`init_time` once more than one run is loaded, and three are — answered **400**.
The effect then re-ran with the run and succeeded.

Two doomed requests per load, self-correcting, invisible outside the network
panel, and all 250 frontend tests passed straight through it. **That is the
cyclone tab's stale-init 404 defect again** (§37), in a different file, nine
commits later: an effect firing before its dependency resolves, surviving
because the final state is correct. Found the same way too — by reading the
network log rather than the screen.

The fix was not new code but the gate that already existed: `await
whenRunReady()` then `withRunParam()`, the two lines every other fetcher in
`forecastApi.js` uses, which exist precisely so callers do not have to get
effect ordering right. `src/api/forecastHours.test.js` asserts a property of
the *request* rather than of the response; three of its six cases fail against
the pre-fix client.

The lesson is narrower than "check the network log". It is: **when a file has a
gating helper that every sibling function calls, a new function that does not
call it is the bug**, and that is visible without running anything.

**A third look at the same log found the effect firing three times per load**,
all resolving to the same run and returning the same answer. The api-layer gate
made each *request* correct but not the *number* of them: the effect ran once at
mount with `selectedRun` still null and again when it arrived. One guard —
`if (!selectedRun) return;`, which the three sibling effects in `App.js` already
have — took it to one request per load.

So the same file was read three times and gave up a defect each time: the
missing gate, then the missing guard. Neither was visible on screen and all 250
tests passed through both. The network panel is worth a second and third pass
after a change, not just a first.

### `src/App.requests.test.js` — the class of defect, pinned

Three defects in three commits, all the same shape: a request that should not
have gone out, self-correcting, invisible on screen, green suite. Every test in
this repo asserted what a response *contains*; none asserted how many went out.
Each was caught by a person reading a network panel, which is not a repeatable
check. This file is.

Five cases, in two groups:

- **No request leaves without a run.** Every `/api/` call except `/api/runs`
  and `/api/config` must carry `init_time`, and `/api/forecast-hours`
  specifically must never fire before the run resolves.
- **One answer, one request.** `forecast-hours` is fetched exactly once for the
  initial selection and exactly once more per model change, and **no two
  identical `/api/` URLs** appear in one settled load — the general form,
  independent of endpoint.

**Verified to discriminate, by reverting the fixes.** With the effect guard
removed, 2 of 5 fail; with both the guard and the api gate removed — the state
the previous commit shipped — 3 of 5 fail. The two groups catch *different*
defects: without the gate the unqualified and qualified URLs differ, so the
duplicate test passes while the init_time tests fail. Both groups are needed.

Two things learned writing it, both worth more than the tests:

**CRA sets `resetMocks: true`.** That clears every mock's implementation before
each test, *including* ones created inside a `jest.mock` factory, which runs
once. So `jest.fn(() => x)` in a module factory returns `x` in the first test
and `undefined` in every one after — and the symptom is a TypeError deep inside
`App.js` with nothing pointing at the mock. Use plain functions in module
factories.

**Leaflet is stubbed in that file, deliberately.** `App.js` builds its map
inside a `setTimeout`, so in jsdom it lands after a test unmounts and throws
"Map container not found" asynchronously, attributed to whichever test is
running. Anything asserting on the map belongs in a file that does not mock it.

**The counts in that file are production counts, and it matters which.**
`src/index.js` wraps the app in `<React.StrictMode>`, which invokes every effect
twice in development on purpose. RTL's `render` does not wrap, so one effect run
is one request and "exactly one" means it. Wrapping would double every expected
number and make a real duplicate-fetch defect indistinguishable from the
doubling; not wrapping means the numbers deliberately do **not** match a
dev-server network panel.

That is worth knowing because the dev panel looks wrong until you understand it:
`/api/cyclones` fires twice per load while `/api/forecast-hours` fires once.
Neither is a defect. StrictMode doubles both, and `forecast-hours` absorbs its
second run in the `if (!selectedRun) return;` guard — confirmed 2026-10-06 by
disabling StrictMode, where `/api/cyclones` drops to one. The same mechanism
explains why `forecast-hours` measured *three* before that guard: two doubled
mounts plus one when the run arrived.

**The first version of that file was flaky, which is worse than not having
it.** Its `settle()` helper looped eight times at 30 ms and stopped. That was
enough running alone and not enough under `npm test`, where jest runs workers in
parallel and everything is slower, so the model-change case passed five times in
isolation and failed in the full suite — the worst failure mode, because it
teaches people a red run means nothing. It now waits for **two consecutive quiet
windows** (80 ms, 4 s budget) rather than a fixed number of ticks, and the
interaction case waits for its request to *appear* before waiting for quiet.
Requiring two quiet windows is the load-bearing part: one is satisfied by the
gap between a response landing and the effect it triggers firing. Verified with
three consecutive full-suite runs, and re-verified that the tests still
discriminate afterwards — a more generous wait is exactly how a count test goes
quietly toothless.

**When a count test disagrees with the dev server, suspect StrictMode before
suspecting the code.** And a future version of that file which exercises the
Cyclones tab has to account for it: under StrictMode `/api/cyclones` would trip
the duplicate-URL assertion while being entirely correct.

Two things worth keeping from the build. A test written before the code caught a
**500**: `_resolve_init_time` returns `None` for a model with no loaded run and
the endpoint called `.isoformat()` on it. It now answers 404, which is
deliberately distinct from the 200-with-empty-list case — "no such run" is not
"this run holds nothing for that variable", and a client that conflates them
cannot tell a typo from a gap. And the endpoint takes the **stored** variable
name, so `wind_u_10m` rather than the UI's `wind`; passing the UI spelling
returns an empty list silently, which is the same mismatch
`TestTheContractRunContextReads` exists to pin.

---

## 39. Single-case claims, audited — 2026-10-06

Prompted by the MOGREPS 26 km retraction being the fifth claim in this project
built on one unit of data. Rather than wait for a sixth, every empirical claim
in the documents was checked for its sample size.

**Two were resting on too little.**

### The ECMWF `24h` label — five storms stated as "every"

`load_cyclone_tracks.py` and `TC_DATA_ACCESS.md` both said: *"Measured on BERYL,
IDA, ETA, LAN and GONI: **every** ECMWF file labelled `24h` is a 48-hour earlier
initialisation."* Re-measured over the whole archive: **96 of 99** storm pairs,
with 3 at 60 h from a skipped cycle. The factor-of-two is right and the word
"every" was not.

The same paragraph's aside — that `egrr`/LAN's 30 h was a one-off archive gap —
is **6** egrr cases and **15** kwbc ones. `egrr` 24h is 24 h in 111 of 117,
`kwbc` in 96 of 111. Both corrected in place.

### "AIFS is 21–27% better at wind" — one run, now half-replicated

This figure is itself the *correction* to the retracted "3.4x better" headline,
and it inherited the same weakness: one run. AIFS vs UKMO can be tested on a
second run and holds — per-cell wind MAE **0.9298 vs 1.3096** at 09-08 (29%)
against **1.0124 vs 1.2712** at 09-16 (20%). Direction replicates, magnitude
moves.

**The GEFS half cannot be tested**: 2025-09-16 is the only loaded run with GEFS
wind. "AIFS beats GEFS by ~21%" still rests on n=1 and `METRICS_AUDIT.md` now
says so. That is a data limit, not an unfinished check — it closes only when a
second three-model run is loaded.

**Four were checked and are sound**, which is worth recording so they are not
re-audited:

- `mean_lon` out by up to 213° — measured across 63 files and 15 storms.
- The basin vocabularies — "enumerated from every file in `output/`, not
  guessed", and the code refuses unknown codes rather than passing them.
- `METRICS_AUDIT` finding 16 — flagged itself as single-case at the time and was
  later closed against an independent run, exactly the right handling.
- `TC_TAB_DESIGN` § on non-monotone error curves — reasons *correctly* from one
  case: "a single storm's curve has no reason to be monotone … a flag, not a
  gate." The lesson applied rather than violated.

Also not instances, though they name one storm: ALCIDE's genesis-variant counts,
Dorian's member fall-off, YASA's 23-of-36 denominator. Each illustrates a number
the tab computes *per run* and displays, rather than generalising from it.

**The tell, stated once so it is recognisable:** a number quoted without its
sample size, where the sample is one storm, one run, or one file. All five
earlier instances had it — three longitude claims, the IBTrACS vintage sample,
the MOGREPS penalty — and so did both found here. The fix is not more care; it
is writing the n beside the number, because a claim that carries its own sample
size cannot hide this.

---

## 40. What is actually open — swept 2026-10-06

Three items were listed as open and are not. An "open" list that is partly wrong
is worse than none, because the next person either re-does finished work or
stops trusting the list:

- **`METRICS_AUDIT.md` §0 is stale** (§24) — regenerated 2026-10-01 against the
  2025-09-16 run. Closed for five days, still listed.
- **The two IBTrACS questions** (`TC_DATA_ACCESS.md`) — answered in §9 of that
  same file on 2026-10-02. The header was corrected then and the list below it
  was not.
- **"Only the plot endpoint is cached, point lists have no row cap"**
  (`METRICS_AUDIT.md`) — both done. Three endpoints cache through
  `_metric_cache_key`, and `_point_list_response` caps and reports truncation,
  each with its own test file.

**What is genuinely open**, with why it is open rather than merely undone:

*Decisions nobody has made — these need a person, not work:*

1. ~~**Which categorical estimator is right.**~~ **DECIDED 2026-10-06 — §41.**
   Both pool over the box; the two surfaces now agree metric for metric.
2. ~~**Wind metric colour bands.**~~ **DONE 2026-10-06 — §42.** Re-derived from
   correctly-paired data; the 2026-09-02 bands had been measured on the
   mislabelled run.
3. ~~**`fbi` and `composite_confidence` are Analysis-only.**~~ **DECIDED
   2026-10-06 — §43.** FBI added; the composite deliberately not.

*Blocked on data, not effort:*

4. **"AIFS beats GEFS by ~21%" rests on n=1** (§39). 2025-09-16 is still the only
   loaded run with GEFS wind — re-checked 2026-10-06. Closes when a second
   three-model run is loaded.
5. ~~**Where the loaded AIFS wind came from** is unresolved (§16).~~
   **RESOLVED 2026-10-07 — §47.** It came from the cluster, exactly; the
   mystery was a comparison spanning two runs.

*Known and deliberately not acted on:*

6. **UKMO coordinates are stored at two precisions** — still true, and
   **re-characterised 2026-10-07 (§48)**: the split is per load, not per
   variable, every run is internally consistent, and the regridded tables every
   scored endpoint reads are on the 0.5° grid and unaffected. Harmless, but not
   for the reason the old note gave.
7. ~~**No "load one run" runbook.**~~ **WRITTEN 2026-10-06 — §45**,
   `RUNBOOK_LOAD_ONE_RUN.md`. Writing it broke two things documented as working.

**Four more entries were stale, found by checking rather than re-reading**
(2026-10-06, §44). The pattern is now consistent enough to state as a rule: in
this project an item is more likely to be stale than open, so **verify before
listing**.

- **"Observations stop at 2025-09-08 23:30"** — they now reach **2025-09-26
  23:30** (IMERG) and 23:00 (ERA5). Eighteen further days of truth were loaded
  and the note was never updated, so the "+17.5 h verification limit" it warned
  about has not applied for some time.
- **"`regridded_forecast` is kept for comparison"** — **dropped**. `to_regclass`
  returns NULL.
- **"GEFS has no converter at all"** — `convert_gefs.py` is 522 lines and says
  it "completes the set". §9 of this file already listed three converters, so
  the document contradicted itself.
- **"`netCDF4` is not in `Data/requirements.txt`"** — §30 added
  `netCDF4==1.7.4`, which is what unskipped the file-reading tests in CI.

Nothing on the cyclone tab is open.

---

## 41. Analysis and Comparison now answer a click the same way — 2026-10-06

§40 listed this as a decision nobody had made, and `CONSISTENCY_AUDIT.md` had
carried it since phase 6. Measured first, at (35.5, −78.5), threshold 0.1 mm/6h,
hours 0–168, run 2025-09-16, `box_cells=9` on both:

| | `/api/categorical-metrics` | `/api/compare/categorical` |
|---|---|---|
| CSI | **0.0833** | **0.2756** |
| POD / FAR | 0.5 / 0.9091 | 0.8329 / 0.7083 |
| hits / misses / FA | 1 / 1 / 10 | 304 / 61 / 738 |
| sample | centre cell, 12 cases | 81 cells x 28 h = 2,268 pts |
| FSS | 0.4901 | 0.4901 |

**Decided in favour of pooling**, and the sample is why rather than taste. The
Analysis CSI was `1/12` — one hit. One case either way moves it to 0 or 0.167.
That is not a measurement, and `METRICS_AUDIT` finding 8's warning about
ratio-of-means applies hardest exactly where the counts are smallest.

Three things also pointed the same way. Both tabs already defaulted to 9x9.
Both captions already said "9x9 cells". And the Analysis response already
returned `scored_area {box_cells: 9, n_cells: 81}` beside a one-cell CSI — so
it was **mislabelling itself**, independently of the disagreement. Pooling made
the behaviour match what was already claimed; it did not introduce a new claim.

`box_cells=1` remains the exact-point case and is unchanged.

**The implementation was smaller than the decision.** `_fss_for_hour` already
built the per-cell forecast/observation bins for the whole box — the data was
there and only the counting was narrow. It now returns those cases too
(renamed `_box_for_hour`), and the contingency table and Brier score accumulate
over them. One scan, two consumers.

**`n_pts` is new in the summary**, because the defect's real lesson is that a
CSI without its sample size hides this: 0.0833 and 0.2756 look like a
contradiction, while "0.0833 of 12" and "0.2756 of 2,268" read as two different
questions. Same tell as §39's single-case claims, one layer down.

**Two tests pinned the old behaviour and had to change**, which is worth
noticing rather than glossing. One asserted CSI *must not* move with
`box_cells`; the other isolated the composite formula by assuming it. Both were
faithful descriptions of what the code did and neither compared the two
surfaces to each other — which is exactly how the disagreement survived two
audits. `TestTheTwoCategoricalSurfacesAgree` does that comparison now, across
two thresholds and two box sizes.

**`METRICS_AUDIT.md` §0 does not need regenerating**, checked rather than
assumed: its categorical figures come from `/api/compare/region-metrics`, not
the point endpoint. I had said it would when framing the choice.

**Opening the tab found two labels the change had falsified**, which no test
would have caught because both are strings. The control was called **"FSS
area"** — correct until that day, since it moved FSS and nothing else — and the
mode was **"This cell"**. With the box governing every metric, the first named
the wrong metric and the second contradicted the behaviour outright. They now
read **"Scored area"** and **"Around a point"**, which is also what Comparison
calls its equivalent; the comment beside the control used to explain at length
why the two tabs deliberately used *different* words, and that reason is what
§41 removed. "FSS window" is unchanged, being genuinely FSS-only.

The result caption needed nothing — it already said `scored: 81 cells at
37.00°N, 77.00°W`, which was true of FSS before and is true of everything now.
**That caption was accurate and the control label beside it was not**, in the
same panel, for as long as the default was 9.

---

## 42. The wind colour bands were calibrated on corrupted data — 2026-10-06

§40 listed this as a decision nobody had made. It had in fact been made on
2026-09-02 — `METRIC_CONFIG` has carried `windColorFn`/`windLegend` for the four
dimensional metrics since then, wired through `metricColorFn`, with matching
`WIND_PLOT_STYLE_OVERRIDES` on the backend. `CONSISTENCY_AUDIT.md` was never
updated, so it described a month-old state.

**Earlier today I checked that exact pair and called it "not stale".** The
reasoning was that `NEXT_STEPS` said "fixed" while `CONSISTENCY_AUDIT` said
"open" because the *defect* was fixed by labelling the panel and the *judgement*
was still unmade. That was a guess that reconciled two documents without opening
the code, and the code had the bands in it.

**Then the bands turned out to be wrong anyway.** `WIND_BAND_BASIS` named its
source: *"loaded run 2025-09-08 00Z"*. That is the run where **GEFS and UKMO
wind were the 09-16 forecast under the wrong label** (§24), so two thirds of the
calibration sample were forecasts scored against truth eight days out of
register. It shows in the numbers: the basis recorded pooled MAE median **1.79**
and p90 **4.65**, where correctly-paired data reads **1.07** and **1.78**.

| | old basis (09-08, 2/3 mislabelled) | correctly paired |
|---|---|---|
| MAE median | 1.79 | **1.07** |
| MAE p90 | 4.65 | **1.78** |
| MAE max | — | 2.92 |

So the bands came out about twice as wide as real errors warrant, and the
saturation defect simply moved: the precipitation edges put 0/12/35/53 percent
of cells in the four bands, and the first wind edges put **47/53/0/0**. Two
colours over the whole map, with "Poor" unreachable.

**Re-derived from every correctly-paired model-run** — AIFS at 09-08 and 09-16,
GEFS and UKMO at 09-16, n=6,564 cells per metric. Edges near the quartiles:

| metric | edges | spread |
|---|---|---|
| MAE | 0.75 / 1.25 / 1.75 | 30/31/28/11 |
| RMSE | 1.0 / 1.5 / 2.25 | 33/24/33/10 |
| CRPS | 0.5 / 0.8 / 1.2 | 28/26/30/16 |
| bias | ±1.0 / ±0.35 | 8/31/42/15/4 |

Backend norms moved with them — each `vmax` sits near the measured p90, so MAE
2.0 (was 5.0), RMSE 2.5 (5.5), CRPS 1.5 (4.0), bias ±1.5 (±5.0). At the old
limits every cell crowded into the bottom third of the ramp, which is the
original defect inverted.

**Two tests encoded the bad data and both stayed green.**
`constants.test.js` asserted a realistic distribution spreads across four bands
using the deciles `[0.09, 0.70, 1.09, 1.40, 1.79, 2.30, 3.30, 4.65, 7.05]` —
the corrupted ones, named as such in its comment. It passed against the new
bands too, so nothing announced it. **A fixture can be wrong and green**, which
is the same lesson as §39's single-case claims wearing different clothes: the
number was never re-derived when the data it described was corrected.
`MetricPanel.test.js` hardcoded the edge string `'1.0 – 2.0'` while its own
comment explained it was written to survive a recalibration; it now reads the
edge from `METRIC_CONFIG`.

**Verified on the rendered output, not just the numbers.** The wind MAE PNG
now carries **17,107 distinct colours** with no single one dominating the
plotted area — a gradient rather than a flat field. And the ramp utilisation is
arithmetic rather than impression:

| metric | p90 | max | old vmax | ramp used | new vmax | ramp used | clipped |
|---|---|---|---|---|---|---|---|
| MAE | 1.78 | 2.92 | 5.0 | 58% | 2.0 | 100% | 4.3% |
| RMSE | 2.26 | 3.38 | 5.5 | 61% | 2.5 | 100% | 4.6% |
| CRPS | 1.33 | 2.53 | 4.0 | 63% | 1.5 | 100% | 5.8% |

The old limits left roughly 40% of each ramp unreachable, so every cell was
squeezed into the lower half of the colour scale. The new ones clip about 5% on
purpose, which is the stated design — "near the observed p90 rather than the
maximum".

**What is still a judgement.** These bands are distributional — "Excellent"
means better than ~70% of cells in this archive, not that a forecaster would
call it excellent. An absolute standard is a different object. But the map
discriminates now, which is what the entry was actually about.

---

## 43. FBI and Composite Confidence — opposite answers — 2026-10-06

The last of §40's three decisions, and the one where "make the two tabs
consistent" was the wrong frame. The gap was incidental — no reason for it had
ever been recorded — but the two metrics deserved opposite answers.

**FBI added.** Events forecast over events observed, 1 = perfect. It is a
measurement, and the counts it needs were already summed in
`_categorical_summary`, so it was one line in the summary path and one in the
per-hour path. It earns its place on the Comparison tab specifically: **CSI says
how wrong a model is, FBI says which direction.** Two models can post the same
CSI while one over-forecasts the event and the other under-forecasts it, and
nothing else on that tab would show it.

It takes `refLine: 1`, not `bounded: true`. FBI is not in [0, 1] — 2 means twice
too many events — and pinning the axis to [0, 1] would clip every
over-forecasting model to the top and make them look identical, which is the
failure the `bounded` flag exists to prevent for the scores that *are* bounded.

**Composite Confidence deliberately not added.** `0.40 CSI + 0.30 FSS +
0.20 POD + 0.10(1−FAR)`, and nobody has justified those weights. Inside one
model it is a summary device: the weighting is constant, so it cancels out of
any comparison a reader makes across thresholds or lead times. Ranking *models*
by it ranks them by the weighting while looking exactly like a measurement —
and ranking models is what the Comparison tab is for.

So it stays Analysis-only, now by decision rather than by accident, and
`test_the_composite_stays_out_of_the_comparison_surface` pins the absence. A
later change that adds it has to delete that test on purpose and justify the
weights somewhere, which is the point.

**§41 left two stale strings behind, both found by opening the tab.**
`README.md`'s verification-metrics row still described the contingency table as
"reading the centre cell only — so the point metrics do not move", and the
Comparison tab's advanced-metrics caption still said *"Analysis scores these on
the clicked cell alone, so its values differ"*. Both described the behaviour
§41 changed. The caption was wrong twice over, since it also listed
"CSI · POD · FAR · Brier" without FBI; it now reads "… · FBI · Brier … Analysis
pools over the same box, so the two tabs agree."

That is **four** stale strings from one behaviour change — two control labels
caught at the time (§41), these two caught a day later. None of them is reachable
by a test, because a test asserting a sentence has to be rewritten by the same
change that falsifies the sentence. **The only reliable check is reading the
screen after changing behaviour**, which is exactly the step I had proposed
dropping as unproductive two commits earlier.

§40's three decisions are now closed: the categorical estimator (§41), the wind
colour bands (§42), and this.

---

## 44. The open list is wrong more often than it is right — 2026-10-06

Second sweep in one day. The first (§40) found three stale entries of nine; this
one found four more, after the three decisions were closed. So of the original
nine items, **seven turned out to be already done** and two were real.

Stale this round: observations "stop at 2025-09-08 23:30" (they reach
2025-09-26); `regridded_forecast` "is kept" (dropped); "GEFS has no converter at
all" (`convert_gefs.py`, 522 lines — and §9 of this same file already listed
three converters, so the document contradicted itself); and "`netCDF4` is not in
`Data/requirements.txt`" (§30 added it, which is what unskipped the CI tests).

**The failure is structural, not careless.** Every one of these was written true,
and the work that falsified it happened in a different section. A note saying
"X is missing" is invalidated by adding X, and nothing about adding X makes
anyone re-read the note. The documents are organised by *when* work happened,
which is right for a record and wrong for a to-do list — so the to-do list rots
at exactly the rate the project advances.

**Working rule, since this has now happened seven times: in this project an item
is more likely to be stale than open. Verify before listing.** Every entry above
was re-checked against the database or the filesystem before being written down,
which took about five minutes and removed four of six.

It is worth noting what the two survivors have in common: neither can be closed
by work. One needs a second three-model run to exist; the other needs provenance
nobody recorded at the time. **Items that need new data survive; items that need
effort get done and the note stays**, which is exactly backwards from how a
to-do list is supposed to decay.

---

## 45. The runbook, and the two things writing it broke — 2026-10-06

`RUNBOOK_LOAD_ONE_RUN.md`: adding one initialisation of one model to a database
that already works. `DEPLOY.md` builds an empty one from nothing, which is a
different document, and §40 had this listed as open on the grounds that *"the
steps exist and are exercised; the narrative that strings them together does
not."*

**The narrative is what found the breakage.** Writing a command down forces you
to run it, and two of them did not work.

### The three forecast loaders would not run as documented

`load_to_postgres.py`, `load_wind.py` and `load_gefs_ukmo_wind.py` each carried
a hardcoded `__main__`: database **`weather_forecasts`**, user **`s.dey`**, fixed
source directories, and `init_time='2025-09-08 00:00:00'`. `weather_forecasts`
does not exist on this machine — checked — so `python Data/load_to_postgres.py`,
exactly as `DEPLOY.md` §2a printed it, failed on connect before reading a file.

They now take `--source`, `--model`, `--init-time`, and `--variable` for the two
wind loaders, and read the same env-driven `DB_CONFIG` as `flask_api.py` and
`load_cyclone_tracks.py`. One wind component per invocation on purpose: u and v
are separate directories, and a flag that loaded "both" would have to guess the
second path from the first.

### `SYSTEM_DESIGN_PLAN.md` said that was already done

Struck through, as *"Fix the loader: config-driven, correct DB, `argparse`,
parameterized `init_time` — **DONE**"*. It was not done for these three. That is
the §44 pattern inverted and worse: §44 was about notes saying work remained
after it was finished, and this is a note saying work was finished when it was
not. **A struck-through line is read as settled and nobody re-checks it**, which
makes a wrong one more durable than a wrong open item.

### Two conventions the runbook records rather than smooths over

~~The converters disagree: `convert_aifs.py` takes `--init-time` while
`convert_gefs.py` and `convert_ukmo.py` take `--verify-init-time` for the same
job.~~ **Fixed 2026-10-06 (§46)** — all three take `--verify-init-time`, with
`--init-time` kept on AIFS as an alias.

And the whole document turns on one instruction: **decide the initialisation
time first and pass it to every step.** §24's defect — four of six
model/variable combinations filed under the wrong run — came from assuming it
rather than passing it, and produced no error at all, just forecasts scored
against truth from eight days earlier.

Step 7 is therefore the MAE-against-lead provenance check, not a row count. Row
counts, grids, member counts and lead ranges were identical between the right
run and the wrong one and told §24 nothing.

---

## 46. One name for one flag — 2026-10-06

Surfaced by writing §45's runbook and documented there rather than fixed, which
left the runbook carrying a warning instead of a command. Fixed now.

`convert_aifs.py` took `--init-time`; `convert_gefs.py` and `convert_ukmo.py`
took `--verify-init-time`. **Checked before renaming**, because two flags with
different names might have done different things: all three pass the value
straight to `verify(..., init_time=...)` and nothing else. Same job, three-to-one
naming split.

**`--verify-init-time` wins on accuracy, not on the vote.** It restricts
`--verify` and does nothing else. `--init-time` reads like it sets the
initialisation of the conversion output — which it never did, and which is
exactly the misunderstanding that would file a run under the wrong timestamp
(§24). AIFS's own help string already said "restrict --verify to one
initialisation", so the name had been arguing with its own documentation.

`--init-time` survives on AIFS as an alias through argparse's multiple option
strings on one `dest`, so anything already written against it keeps working.
Verified that both spellings land on `verify_init_time`, that the call site
reads that attribute, and that no reference to the old one remains.

`convert_ukmo.py`'s flag had no help text at all; it now has the same sentence
as the other two.

**Small, but it is the shape that costs most.** Nothing was broken — every
script ran, every test passed, and the only symptom was a reader typing the
wrong flag and getting an argparse error. That class does not show up in CI, in
a row count, or in a network log; it shows up when someone follows the
instructions. Which is why §45 found it: writing down a command is the only
check that exercises its spelling.

---

## 47. The AIFS wind provenance mystery was a two-run comparison — 2026-10-07

§16 recorded that the loaded AIFS wind *"has some other provenance that is not
on the cluster under that name"*, on the strength of one cell: at `2025-09-08
00Z` +120 h, (25.0, −85.0), the database held **−5.567** where the source had
**−4.050**, and "no member index reproduces it". It sat on the open list for
weeks as the item that might never close.

**The data was never wrong.** Checked against the cluster:

| | |
|---|---|
| source, 09-08 file, member 0 | **−4.050** |
| database, run `2025-09-08 00Z`, member 0 | **−4.050** |
| database, run `2025-09-16 00Z`, member 0 | **−5.567** |

−5.567 is the **other run**. `verify()` took `init_time` as optional and, when
omitted, compared the source directory — which is exactly one run — against
*every* run in the database. With one run loaded that was harmless; a second run
made it meaningless, and §16 was written in that window.

**Sampled properly before declaring**, because one cell is how this started:
768 of 768 values agree, across both wind components, six lead times (0, 24, 60,
120, 240, 360), sixteen cells and four members. Zero differ, zero missing.

`verify()` now **refuses** an ambiguous comparison rather than producing a
confusing one, naming the loaded runs and telling the caller to pass the one the
files belong to — the same rule `_resolve_init_time` reached independently for
the API.

### Three things worth keeping

**The hypothesis that cracked it was wrong.** The suggestion was that u and v
might be stored separately and combined into speed afterwards, so the stored
number might be √(u²+v²). It is not — speed at that cell is 6.609, not 5.567.
But testing it meant printing the stored values beside each other, and member 0
read −4.050: the value §16 said was absent. **A wrong hypothesis that makes you
look at the data beats a right-sounding note that stops you.**

**"No member index reproduces it" was checkable in one query and nobody ran
it.** Including me — I listed this item three times in a day, described it at
length when asked, and only looked when someone proposed a mechanism. Re-stating
a finding is not re-checking it.

**This is §24's defect wearing a lab coat.** §24 was forecasts scored against the
wrong run's truth; this is a *verification script* comparing against the wrong
run and reporting the discrepancy as a property of the data. The tool built to
catch run mix-ups contained one.

---

## 48. The UKMO coordinate split is per load, not per variable — 2026-10-07

Checked because §47 had just shown that a long-listed item can be a phantom, and
this one carried a load-bearing claim nobody had tested: *"nothing joins across
variables, so nothing is broken."* **Wind speed joins across variables** — it is
√(u²+v²) — so that sentence deserved a query rather than a nod.

The join is safe, and the rest of the description was wrong.

| | |
|---|---|
| `wind_u_10m` latitudes == `wind_v_10m` | **yes** — the speed join is unaffected |
| UKMO precipitation, distinct latitudes | **214** |
| … distinct to 3 decimal places | **107** |
| … positions carrying two spellings | **all 107** |

214 is not a finer grid. It is 107 positions stored twice, once as `25.03125`
and once as `25.0312`. That looked much worse than the note — precipitation
split against itself — until the per-run breakdown:

| variable | run | lowest latitude as stored |
|---|---|---|
| precipitation | 2025-09-08 00Z | `25.03125` |
| precipitation | 2025-09-08 06Z | `25.03125` |
| precipitation | 2025-09-16 00Z | `25.0312` |
| wind u / v | both runs | `25.0312` |

**Every run holds exactly 107 latitudes and is internally consistent.** The two
09-08 precipitation loads wrote five decimals; everything loaded since writes
four. So it is a change in loader behaviour over time, and "wind and
precipitation differ" is the shadow it casts — wind happens to have been loaded
entirely after the change.

**Still harmless, for a better reason than the old note gave.** Queries are
run-scoped throughout, and within a run the coordinates agree. More to the
point, `regridded_forecast_ens` — which every scored endpoint reads — holds **39**
latitudes on the 0.5° analysis grid and never sees the native precision at all.

The residual risk is narrow and worth stating: a query that filters
`latitude = <literal>` **across** runs silently returns only the runs whose load
used that spelling. Nothing does that today.

**The lesson is the one §47 just taught, applied deliberately rather than by
luck.** "Nothing joins across variables" was the kind of claim that sounds like
a conclusion and is actually an assumption; it was one query away from being
checked, and it had been sitting unchecked while the item was listed as
understood.

---

## 49. Five stale markers, and the defect one of them was hiding — 2026-10-07

A sweep of every document's open items, run under §44's rule that an item here
is more likely stale than open. The rule held: **five markers were stale against
two-and-a-bit genuinely open items.** Four were corrections. The fifth was not.

### The one that was hiding something

`CONSISTENCY_AUDIT.md`'s phase-1 availability matrix still showed `fbi` as
absent from both Comparison columns, a day after §43 added it. Correcting a row
means checking what the endpoints return, and they returned this:

```
POST /api/compare/region-metrics  {"metrics": ["csi", "fbi"]}
  -> 400  Unknown metric(s): ['fbi'].
          Available: [... 'csi', 'pod', 'far', 'brier', 'fss']
```

**§43 landed two thirds of its own decision.** FBI went into
`_categorical_summary` (the point surface) and into the Comparison tab's region
metric group in `ComparisonTab.jsx` — and into `_region_pooled_metrics`, which
computes the region surface, not at all. The tab drew an FBI bar for every
selected model with nothing in it.

**Nothing failed, which is why it survived.** The renderer reads
`regionData.models?.[m]?.[key] ?? null`, so a metric the backend never sends is
indistinguishable from a model that has no data for it — the same empty bar. The
400 was never reached from the UI either, because `handleRunRegion` sends no
`metrics` key and the endpoint defaults to its own list. Four tests covered FBI
on the point surface and none on the region one.

**And a sixth stale string, found only by opening the tab.** The region
threshold control read *"CSI · POD · FAR · Brier · FSS only"* — the list of
metrics the threshold governs, which FBI joined on 2026-10-06 and the caption
did not. No test reads it; §43's own caption fix had corrected the *point*
mode's copy two panels away. Checking the fix in the browser is what surfaced
it, which is the argument for doing that rather than trusting a green suite.

Fixed the same day. `_region_pooled_metrics` already had both counts for
CSI/POD/FAR, so the value is one line and is pooled over the same sample as its
neighbours — `fcst_yes / obs_yes`, measured at **1.0537** over 117 cells for
AIFS on the 09-16 run. `COMPARE_REGION_NO_CELL_VALUE` gains `fbi` beside `fss`
and the UI entry gains `noMap`: **at one cell both counts are 0 or 1, so a
per-cell FBI is only ever 0, 1 or undefined**, and a map of it would be three
colours that look like a measurement. Three tests now pin the region surface,
including the identity `FBI == POD / (1 − FAR)`, which breaks if FBI is ever
computed from a different sample than the two metrics beside it.

### The other four

| marker | said | is |
|---|---|---|
| `CONSISTENCY_AUDIT.md` header | "all but two findings are fixed" | both decided 2026-10-06 (§41, §43) |
| …its phase-6 heading | "— **open**" | its own body below says **DECIDED** |
| `METRICS_AUDIT.md` §13 | "`regridded_forecast` is left in place" | dropped; `to_regclass` → NULL |
| `SYSTEM_DESIGN_PLAN.md` S4 | the same bullet twice, "Still open" and "NOT DONE" | merged; both copies also carried `AnalysisTab.jsx` at 1,264 lines, now **1,360** |

The duplicate is the instructive one. Two copies of an item get re-read and
neither gets updated, so a number that was accurate once outlives two rounds of
edits to the file it counts.

### What is actually open, verified against the data

1. **Every GEFS comparison rests on n=1** — and this is broader than §39 and §40
   say. The registry holds GEFS for exactly one initialisation, `2025-09-16 00Z`,
   for **all three variables**, so the precipitation comparison is n=1 too, not
   just wind. AIFS and UKMO have three runs each.
2. **The domain is hardcoded and the cyclone archive is global.** S4's "extent"
   item and `TC_TAB_DESIGN.md` decision 6 are the same item: the grid is
   25–45 N, 85–65 W, while the loaded tracks span −180…180 and **only 1,074 of
   15,185 storms ever enter the box**. It binds only if tracks are ever scored
   against gridded fields; the cyclone tab is track-only and unaffected.
3. Known and deliberately not acted on: the UKMO coordinate spelling (§48),
   S4's deferred refactors, and the four questions for a person at the end of
   `TC_DATA_ACCESS.md`.

**The method point, which is the same one §47 and §48 made and is now three for
three.** Each of these was one query or one request away from being checked, and
each had been sitting unchecked underneath a sentence that read like a
conclusion. The sweep that finds a stale marker is also the sweep that finds the
code the marker was describing wrongly — so correcting documentation is worth
doing against the system rather than against the other documents.

---

## 50. The 217-second region request was one `COUNT(DISTINCT)` — 2026-10-07

Noticed while verifying §49 in the browser: a three-model region comparison
took **217 s**, long enough that a reviewer would assume the tab had hung.

**Profiling first, and the answer was not where anyone would have looked.**
Timing every stage of the request, per model:

| stage | AIFS | GEFS | UKMO |
|---|---|---|---|
| **`_ensemble_size`** | **74.0 s** | **23.8 s** | **74.3 s** |
| member grid (`_member_pairs_by_cell`) | 0.78 s | 0.94 s | 1.48 s |
| aggregate pairs | 0.74 s | 0.95 s | 0.53 s |
| correlation points | 0.37 s | 0.30 s | 0.46 s |
| pooled metrics, incl. FSS | 0.16 s | 0.16 s | 0.14 s |
| every per-cell metric fn | ≤0.11 s each | | |

**172 of 179 s was the member count** — a number this database writes down at
load time. Everything that looks expensive, the 42M-row member grid included,
was under 1.5 s.

### Why one count cost 74 seconds

```sql
SELECT COUNT(DISTINCT fd.ensemble_member) FROM forecast_data fd
JOIN forecast_runs fr ON fr.run_id = fd.run_id
JOIN models mo ON mo.model_id = fr.model_id AND mo.model_name = %s
WHERE fd.ensemble_member IS NOT NULL
  AND fd.forecast_hour = (SELECT MIN(forecast_hour)
                          FROM forecast_data WHERE run_id = fr.run_id)
```

The planner cannot use an index for that correlated subquery, so it
**sequentially scans all 240M rows of `forecast_data` once per run of the
model** — `EXPLAIN (ANALYZE)` shows three scans, 9.15M buffers and 25.3 s each,
195M rows discarded per scan to find one minimum. AIFS has three runs, so AIFS
pays three.

Replaced with one row of `forecast_run_registry`, which records `n_members` at
load time: **74 s → 11 ms**, and per run rather than per model, which is what
the SSR bias correction actually wants. The registry's counts were checked
against the old query's before switching — AIFS 50 at all three runs, GEFS 30,
UKMO 18, computed the slow way one last time (5 m 33 s) to have something to
compare against.

**End to end: 217 s → 7.3 s cold through the UI, ~1 s cached, with every
returned value byte-identical** — verified by running the same request against
the pre-change code in a parallel checkout and diffing all twelve metrics for
all three models, `ssr_agg` included, since it is the only one that reads the
member count.

### Why it hid for months, which is the part worth keeping

**The process cache made it a once-per-model charge that nothing timed.**
`_ENSEMBLE_SIZE_CACHE` meant the first request after a restart paid 172 s and
every later one paid nothing — so an interactive session felt slow once and
fine afterwards, and whoever was testing had already warmed it. In production
each gunicorn worker pays it separately, on whichever unlucky request lands
there first.

**The comment above it said "2-6 s".** That was plausibly true when written,
against a smaller table. Nobody re-measured it, because a comment is not a
measurement and nothing here fails when one rots — the same failure as §48's
"nothing joins across variables" and §40's four stale entries, in a performance
register rather than a correctness one.

**And the guard test asserted nothing.** `test_an_unreadable_member_count_falls_
back_rather_than_raising` ended `assert api._ensemble_size(Angry(), "AIFS") in
(None, 0) or True` — the `or True` makes it pass for any return value at all,
and its docstring described "a 9.7M-row table" that had grown 25-fold. Both
corrected.

**The transferable rule: profile before optimising, including when the slow
thing is obvious.** The member grid is 42M rows, three queries per request, and
is the thing this file's notes keep warning about; it was 3 of 179 s. A count
of fifty members was 172.

Five tests now pin the source rather than the duration — a timing assertion on
a shared database is a flake, and the source is what made it slow. The sharpest
one records every statement and fails if `forecast_data` appears.

---

## Standing decisions — do not undo these by accident

**GEFS precipitation will not be re-exported.** The correction in
`SCALED_EXPORT_DIVISOR_HOURS = {'AIFS': 6.0, 'GEFS': 3.0}` is therefore
permanent. It is not debt: it describes how the loaded data was produced.

If that ever changes and `Data_convert_weave/"aifs react.py"` is re-run (it has
been fixed to divide by each record's own window), the constant must move to
`{'AIFS': 6.0, 'GEFS': 6.0}` **in the same change**, or the correction applies
twice. `/api/health` now infers the convention from the data and reports
`ok` / `MISMATCH` / `indeterminate`, so forgetting is caught rather than silent.

**Every model is verified over a common 6-hour window**
(`COMMON_VERIFICATION_WINDOW_HOURS`). Display paths keep native cadence on
purpose. Wind is exempt — instantaneous, so there is no window to reconcile.

**The GEFS filenames lie.** Every file is named
`Total_precipitation_surface_3_Hour_Accumulation_ens_*`, including the `f006`,
`f012`, `f018`, `f024` files that hold **6-hour** totals. Read `step` from the
file, never the name. Verified on two independent runs.

**`regridded_observation_shifted` and `regridded_observation_bankers` are not
dead tables.** They hold **137,544 rows each** — 97,200 IMERG plus 40,344 ERA5,
complete snapshots rather than fragments — and they are the documented rollback
for two data corrections: the UTC time-base fix (§14) and the banker's-rounding
fix (§7). Both revert procedures in this file rename them back, and **this
database has no backup**, so dropping them removes the only path. They cost
58 MB of 124 GB.

They were nearly dropped on 2026-10-02 after being reported as empty — see the
trap below. If they are ever genuinely unwanted, the revert SQL in §7 and §14
has to be struck out in the same change, or this file will go on promising a
rollback that cannot run.

## Method lessons, earned the hard way

Three findings in this audit were wrong and had to be withdrawn. All three failed
the same way — a real signal, misread as to cause.

1. **Never raw Pearson on a skewed field.** It retracted finding 15 entirely.
   Use Spearman, or Pearson on `log1p`, or a categorical score.
2. **Always control against a known-good pair.** Run the same statistic on
   model-vs-model before concluding anything about data quality.
3. **Model-vs-model agreement is not a truth test.** Ensembles share initial
   conditions and physics lineage, so they agree with each other more than with
   an independent reanalysis. That is expected, not diagnostic.
4. **Do not infer a constant from a filename.** The `_scaled` folder name led to
   a guessed divisor of 6; the actual script said 3, which inverted the fix.
5. **Shape agreement is not provenance.** The AIFS wind matched the source on
   grid, hours, member count and every cell key, and was a different forecast
   run entirely (§18). Structural checks all passed and were all consistent with
   unusable data; only matching *values* against a named source settled it.
6. **A parameter that appears unread may be read by a callee.** Grepping
   `/api/spatial-metric` for `args.get('hour')` found nothing and produced a
   confident, wrong defect report — `request.args` is handed to the dispatchers
   (§19). This is trap 2 in the list above, reached from a different direction:
   **resolve the helper before concluding what anything does.**
7. **Name the parameter you actually sent.** The same report used
   `forecast_hour` against an endpoint that takes `hour`, and an unknown query
   parameter is silently ignored rather than refused — so the evidence looked
   like a bug in the endpoint instead of a typo in the request.
8. **"Fixed" is a claim about the database, not about the commit.** §20 recorded
   GEFS as relabelled and the wind as replaced. Loading the correct run had in
   fact left the wrong rows in place, and nothing re-read the tables to notice
   (§24). Verify a data fix by querying for the *old* state and finding it
   absent, not by confirming the new state is present — both can be true at once.
9. **A test can pin a defect in place, and sound reasonable doing it.**
   `test_ukmo_precipitation_has_no_probabilistic_scores` described its mechanism
   accurately and drew the wrong conclusion from it — "not a bug, but a parity
   gap worth pinning" — months after §21 had established it was a bug
   everywhere else (§25). When a test asserts an **absence**, check whether the
   absence is a property of the data or a limitation of the code path.
10. **MAE against lead time is a provenance test.** Row counts, grids, member
   counts and lead ranges were identical between the two runs and told nothing
   apart. A forecast scored against its own valid times loses skill
   monotonically with lead; the wrong week gives a flat curve at a higher level.
   Cheaper than any of the correlation work in §24 and it answers the actual
   question.
11. **A traceback names what it was doing, not what you were thinking about.**
    `python -m pytest --cov` died with `cannot instrument shim code object
    'project_linear'` and a stack frame in `cartopy/trace.pyx`. That frame said
    coverage was measuring *Cartopy*, which is a scope problem; it was read as a
    *tracer-core* problem, because §6's sysmon/ctrace trap was already in mind.
    The result was a confident report that coverage could not run at all and a
    recommendation to pin coverage backwards, both wrong (§33). A second session
    could not reproduce it, which is what forced the re-read. **When a traceback
    names a file, ask why that file was involved before reaching for the
    explanation you already have.**
12. **What is installed says nothing about what `pip install -r` will find.**
    netCDF4 is a hard dependency of all three converters and was in no
    requirements file for the life of the project, because the conda
    environment had it and nobody ever installed from the file alone (§30).
    The same gap made 14 tests skip in CI. In a conda project, read the
    requirements file, not `pip list` — and check a pin resolves on the target
    platform before committing it, since the version you have locally may have
    come from a different channel entirely.
13. **A passing test can be worse than a skipped one.** Nine cap tests skipped
    in CI and passed locally, and the local passes verified nothing at all: the
    fixture checked a database was reachable and then handed the endpoints
    conftest's MagicMock pool, which iterates empty (§28). A skip at least
    announces itself in the counts. This one was indistinguishable from working
    code on every machine, and was found only because someone went to fix the
    skips. **Before trusting a test that talks to a database, check that it
    asserts a non-empty result** — and check which connection it actually got.
14. **A skipped test and a passing test look identical in a green tick.**
    Fourteen registry tests skipped on every CI run this repository ever had,
    because one environment variable was unset (§26). Nothing was red, nothing
    was wrong, and three commits to the registry went through untested. Read the
    *counts*, not the colour: `778 passed, 41 skipped` identically across three
    different commits is a fact about the environment, not about the code. And
    when moving a test to a database that has different data, assert the data is
    there first — otherwise the skip simply moves with it.

15. **A sample that agrees is not a check that passed.** Asking whether the two
    IBTrACS vintages differed, five storms were compared, all five matched
    exactly, and the conclusion was forming that the vintage did not matter.
    The full 138-storm comparison found **24 revised**. Nothing about the five
    was unrepresentative — they were simply five. The same shape produced both
    longitude retractions in `TC_DATA_ACCESS.md`: one centre read as signed
    ±180, generalised to all three, and two of the three encode it differently.
    **When the question is "do these two sources ever disagree", a sample can
    only answer yes.** A no needs the whole set, and the whole set is usually
    cheap — both of these were one query.
16. **The question that cannot discriminate still returns a number.** Two
    attempts to find what the June re-selection selected for looked sound and
    were worthless: the first compared mean lead depth between dropped and kept
    storms **in a set truncated at +72 h**, so both groups averaged 72 h by
    construction and the test could not have found a difference if one existed.
    A test whose answer is fixed by the data's own shape will not announce
    itself — it reports a clean, symmetric, meaningless result. **Before
    believing a comparison, ask what it would have shown had the hypothesis been
    false.**

17. **`n_live_tup` is an estimate, and on a table nobody writes to it is
    `0` forever.** A table inventory read it as a row count and reported
    `regridded_observation_shifted` and `regridded_observation_bankers` as
    empty leftovers; they hold 137,544 rows each and are §7's and §14's only
    rollback. A drop was requested on the strength of that and would have been
    irreversible, against a database with no backup.

    The mechanism is worth knowing because it is not the usual staleness: both
    tables were created by `ALTER TABLE ... RENAME`, which carries no
    statistics, and **autovacuum only analyses a table in response to writes**,
    so a frozen archive table is never analysed at all — `last_analyze` and
    `last_autoanalyze` were both `NULL`. The estimate was not merely out of
    date, it had never existed. `ANALYZE` on both fixed it.

    This is the same `reltuples` caveat `/api/health` already carries, where
    the field is named `total_forecast_points_estimate` precisely so nobody
    reads it as a count. **Use `count(*)` before acting on a row count**, and
    treat `0` on an untouched table as "unknown", not "empty". More generally:
    the cheap read is fine for a dashboard and not fine as the basis for a
    `DROP`.

The pattern throughout: a fingerprint in the data reliably shows *that* something
is wrong, and reliably cannot say *which* explanation produced it. Three raw
files settled in minutes what a week of correlation tests could not. When a
source of truth exists, go and read it.
