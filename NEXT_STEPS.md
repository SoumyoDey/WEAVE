# Next steps

State as of 2026-09-02. **PR #2 is merged** (`49ead8f`); `main` is the live
branch and carries everything below.

**Read this first.** Items 1, 3, 3b, 4, 7 and 8 below are done, all seven
defects the fixture layer found are fixed, and **the consistency audit is closed —
all six phases** (`CONSISTENCY_AUDIT.md`). **Nothing is blocked on another person
any more**; what is left is work, a decision that is yours, or data that is not
in this repository.

**Changes the rest of this document assumes**, newest first:

- **2026-09-02 — the `init_time` migration is done** (§8). The regridded tables
  carry a run identity, every query filters on it, the frontend names the run on
  every request, and an ambiguous request gets a 400 instead of a guess.
  `DATA_EXPANSION_DESIGN.md` phases 1–2 are closed and its "do not load a second
  run" rule is retired.
- **2026-09-02 — wind has its own metric colour bands** (see the ownerless-items
  list). The precipitation edges are unchanged.
- **2026-09-02 — the observation regrid exists** (§7), and it found a
  checkerboard artifact in the *current* truth field. The live
  `regridded_observation` is untouched pending a decision.
- **2026-08-27 — the target grid is a constant**, so `regrid_members.py` can run
  on a fresh database for the first time (§2).
- **2026-08-27 — `regridded_forecast` was renamed to
  `regridded_forecast_deprecated`** on `weave_weather`. `main` was broken by this
  and the merge fixed it; **`WEAVE_v2` and `WEAVE_presentation` are still broken**
  and no version of them is not. If one of those errors about a missing relation,
  that is this, not a bug. And restart any long-running server after a schema
  change — see the trap in §1, which cost an hour.

## Where things stand

PR #2 merged on 2026-09-02 as `49ead8f`, all 90 commits preserved — +19,279/−1,802
across 78 files, over half of it tests and documentation. `main` is now 125
commits. See §1 for how and why it went in without review.

- **The backend and frontend suites pass with no xfails**, and `metrics.py` and
  `flask_api.py` are both at **100%** statement coverage. `python -m pytest -q` in
  `Data/` runs anywhere: without PostgreSQL a little over a fifth of it skips
  itself and the rest still runs.

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

1. **Nothing is blocked on a person any more.** PR #2 is merged (§1). What is
   left is either work, a decision that is yours, or blocked on data that is not
   in this repository — and each says which below.
2. **Item 2, drop `regridded_forecast_deprecated`** (245 MB). `main` no longer
   reads it, as of the merge, so the remaining consumers are the `WEAVE_v2` and
   `WEAVE_presentation` app copies — both pointed at this same `weave_weather`
   database, and both already failing against it since the rename. Dropping is
   safe for this repo and final for those two, so it is a decision about whether
   they are still wanted rather than a cleanup. See §2, which twice claimed
   "nothing reads it" and was twice wrong. `observation_data` is *also* unread by
   the API, but it is raw ingested data no script here can regenerate — leave it.
3. **The `observation_data` ingest — the largest real piece of work left**, and
   the only thing now standing between a fresh clone and a working *verified*
   deployment. Nothing in this repository writes that table; the native point
   observations were ingested off-repo and the IMERG/ERA5 source files are not on
   the development machine. `regrid_observations.py` handles everything above it
   (§7), and `DEPLOY.md` §2b says plainly that a fresh install gets forecasts and
   no truth until this exists. It is also what blocks
   `DATA_EXPANSION_DESIGN.md` phase 4 and therefore a second run.
4. **Item 6, the lower-priority list.** Vite (CRA is EOL), caching the
   deterministic metric endpoints, row caps on point-list queries.
5. **`DATA_EXPANSION_DESIGN.md` phases 3–5.** No longer blocked on the schema —
   phases 1–2 are done (§8). What remains is the run-selector UI, which has no
   user-visible value while one run is loaded, and the ingest above. Read that
   document's status table first; three of its instructions were superseded by
   what actually shipped and are marked as such.

### Open items with no owner

Three still open; the fourth is struck through, fixed 2026-09-02. The first two
are old, the last two came out of phase 6.

- **`fbi` and `composite_confidence` are Analysis-only and nobody decided that.**
  Recorded as undecided in `categorical_metrics_endpoint`'s docstring rather than
  justified. Adding FBI to Comparison is cheap; the composite is a judgement call
  because its weights are.
- **UKMO's wind and precipitation coordinates differ** in `ensemble_statistics`
  (`35.1562` vs `35.15625`, two loaders). Nothing joins across variables, so
  nothing is broken; a test pins the difference so it cannot surprise anyone.
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

## 2. Drop the superseded table — RENAMED 2026-08-27, drop still pending

245 MB, superseded by `regridded_forecast_ens`, which carries a true ensemble
spread derived from `regridded_forecast_member`. It was kept only so the old and
new numbers could be compared, and that comparison is done and written up.

> **State: renamed, not dropped.** On 2026-08-27 the table on `weave_weather`
> became `regridded_forecast_deprecated` — 245 MB and all 1,499,977 rows intact,
> reversible in one statement:
>
> ```sql
> ALTER TABLE regridded_forecast_deprecated RENAME TO regridded_forecast;
> ```
>
> **What this means in practice: `main`, `WEAVE_v2` and `WEAVE_presentation` will
> now fail against this database** until that rename-back is run. That was the
> accepted trade — the point of renaming rather than dropping is that a
> consumer nobody remembered fails loudly and recoverably. If something breaks
> and you want it working again immediately, run the statement above; the data
> never left.
>
> Checked before renaming: two Flask servers were live on `weave_weather`, both
> from `WEAVE_v3` (pids 9244 and 45818), so neither reads this table. Verified
> after: `/api/compare/skill` and `/api/categorical-metrics` returned
> byte-identical responses to the pre-rename baseline, `/api/health` stayed
> healthy, 615 tests passed, and `regrid_members.py --verify-grid` degraded to
> `regridded_forecast: absent, skipped` as designed.
>
> **The `DROP` is still pending**, and still wants PR #2 merged plus a decision
> about the two older app copies. Give the rename time to flush out an unknown
> reader first — that is what it is for.
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

Truth exists only to fh ≈ 19.5 for the loaded run. Beyond that, verification
correctly returns nothing — but a user scrubbing to +48 h saw an empty panel and
could not tell that from a bug.

Every scored endpoint could already say that a *particular* query found no
observations, and two panels rendered that message. What none of them could say is
where the truth *ends*: the messages were all reactive, and the extent appeared
nowhere. So `/api/observation-coverage` now reports it up front —
`record_end_lead_hours` (19.5 on the loaded run) and `last_verifiable_hour`, the
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
   ("GPM_IMERG_V07B observations for this run end 19.5h after initialisation, so
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
  1–2 are done as of 2026-09-02 (§8)**, so the blocker this entry used to name —
  no `init_time` column, valid time resolved from "the latest run" — is gone, and
  that document's "do not load a second run" rule is retired. What remains is the
  ingest (`observation_data` has no loader here) and the selector UI, which has
  no user-visible value while one run is loaded. Like the audit plan above, treat
  its phase text as what was believed beforehand: three of its instructions were
  superseded by what shipped and are marked against each phase.

## 6. Lower priority

- **Vite migration** — CRA is EOL.
- **Cache the deterministic metric endpoints** — only the plot endpoint is cached.
- **Row caps on point-list queries** — currently unbounded.

---

## 7. The observation regrid, and a defect in the current truth field

**New 2026-08-27.** `Data/regrid_observations.py` box-averages `observation_data`
onto the 0.5° grid, so `regridded_observation` — the truth field behind every
scored endpoint — can be produced from this repository for the first time.
DEPLOY.md §2b now runs it. **`observation_data` itself still has no loader here**,
so a fresh deployment gets forecasts and no truth until that table arrives by
other means; that is the one remaining hole in the install path.

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

### The decision nobody has made yet

**The live `regridded_observation` is untouched.** The rebuild is in
`regridded_observation_rebuilt` so the two can be compared without committing.
Switching over is a judgement call, because **every published number in
`METRICS_AUDIT.md` was computed against the current truth
field**, and the table above says they would move — wind especially, where the
current field is barely smoothed on half-degree cells.

Options, in the order I would consider them: rebuild and re-derive the audit
numbers (correct, and invalidates a lot of written-up work); rebuild after PR #2
merges so the review is not aimed at a moving target (my preference); or keep the
current field and treat this as documentation of a known artifact. What should not
happen is a silent switch — the numbers change materially and a reader comparing
against the audit would have no way to know why.

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

The pattern throughout: a fingerprint in the data reliably shows *that* something
is wrong, and reliably cannot say *which* explanation produced it. Three raw
files settled in minutes what a week of correlation tests could not. When a
source of truth exists, go and read it.
