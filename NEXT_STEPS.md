# Next steps

State as of 2026-08-20. Branch `p0-reliability`, PR #2 on `SoumyoDey/WEAVE`.

**Read this, then `REVIEW_GUIDE.md`.** Items 3, 3b and 4 below are done, all seven
defects the fixture layer found are fixed, and consistency-audit phases 1-4 **and
6** are closed (`CONSISTENCY_AUDIT.md`). **The only thing left that needs someone
other than whoever is reading this is the review — item 1.**

## Where things stand

PR #2 is **open and deliberately not merged** — 67 commits, 46 files,
+13207/-1598. `main` has not moved, so it is a clean fast-forward. A count
written down here goes stale on the next push, so re-derive rather than trust
it: `git diff --shortstat main...p0-reliability`.

- **302 backend + 49 frontend tests pass**, no xfails. `metrics.py` 100%,
  `flask_api.py` 83%. `python -m pytest -q` in `Data/` runs anywhere: without
  PostgreSQL most of it skips.
- No reviews, and no CI on the repo (`checks: 0`) — nothing runs on merge.
- The four records, in the order to read them:
  - `REVIEW_GUIDE.md` — what changed and how to check it. Delete after merge.
    **Its header counts are stale** (57 commits, +12,111): the branch has moved
    since. The body is still accurate; only the summary numbers drifted.
  - `METRICS_AUDIT.md` — the metric audit. Read before re-deriving anything.
  - `CONSISTENCY_AUDIT.md` — phases 1-4 and 6, findings classified.
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

---

## If you are picking this up cold

In priority order. Everything here is unstarted; nothing is half-done.

1. **Item 1, the review.** Blocked on a person, not on work. `REVIEW_GUIDE.md`
   exists to make it tractable and lists every change that moves a published
   number, with before/after values and the test that pins each one.
2. **Consistency audit phase 5, typography.** Now the only unrun phase, and the
   mechanical one. `theme.js` already has the scale; the holdouts are listed in
   `CONSISTENCY_AUDIT_PLAN.md`. Two corrections to that list before you start:
   `ui/PanelState.jsx` was written to the scale, and `MetricPanel.jsx` — named
   there as the worst offender at four inline sizes — should be re-checked rather
   than assumed, since phase 6 has been through it since.
3. **Item 2, drop `regridded_forecast`** (245 MB, nothing reads it). Repoint
   `regrid_members.py`'s grid lookup at `regridded_forecast_ens` in the same
   change. `observation_data` is *also* unread now, but it is raw ingested data no
   script in this repo can regenerate — leave it.
4. **Item 6, the lower-priority list.** Vite (CRA is EOL), caching the
   deterministic metric endpoints, row caps on point-list queries.
5. **`DATA_EXPANSION_DESIGN.md`.** Still blocked on the missing `init_time`
   column. One trap was removed: `Timeline.jsx` no longer hard-codes the
   initialisation date.

### Four open items with no owner

The first two are old; the last two came out of phase 6.

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
- **The metric colour bands are precipitation-calibrated and wind uses them.**
  `< 0.2 — Excellent` is an mm/h judgement applied to m/s, and the backend norms
  cap MAE/RMSE at 2, which a real wind MAE exceeds (2.18 m/s over 35–37 N,
  77–74 W), so most of the map saturates to one colour. Setting wind bands needs
  someone who can say what a good wind MAE is; the panel says whose scale it is
  in the meantime.

### Traps

- **Never trust a summary of the numbers — re-measure.** Writing
  `REVIEW_GUIDE.md` found a live defect (`fss` alone returned nothing) purely by
  re-running the figures. Two of my own conclusions in these documents were wrong
  and are marked as retracted; do not quietly "clean up" a retraction.
- **`regridded_forecast_ens.std_dev` is a true ensemble spread** (nanstd over
  regridded members, ddof=1). The "pooled member x native-cell, ~23% high" story
  belongs to the superseded `regridded_forecast`. See §3b.
- **A refactor can hollow out a test instead of failing it.** Two tests filtering
  on `lat == 35.0` passed vacuously once UKMO moved to a grid with no cell there.
  Assert non-emptiness first.
- **Cartopy drops coverage's tracer** partway through both render functions, so
  ~120 executed lines read as uncovered. Do not chase it.
- **A comment or label that was right when written is the most likely thing to be
  wrong now.** Every one of phase 6's seven findings was accurate at the time and
  falsified later by a fix elsewhere — the code moved, the sentence did not. When
  you change behaviour, grep for the strings that described the old behaviour, and
  prefer a test on the *invariant* over a test on the wording: a test that asserts
  a sentence gets rewritten by the same change that breaks it.

---

## 1. Merge PR #2

**Blocked only on review, and this is now the only item on this page that needs
someone other than whoever is reading it.**

`REVIEW_GUIDE.md` exists to make that review tractable: 52% of the diff is tests
and docs, and the guide lists every change that moves a number the app already
published, each with its before/after value on the loaded run, the line to read,
and the test that pins it. Start there, not with the diff.

```bash
gh pr merge 2 --repo SoumyoDey/WEAVE --squash --delete-branch
```

`--squash` given 57 commits, many iterating on one finding. Use `--merge` instead
if the individual messages are worth keeping — they carry most of the reasoning,
and several record why an approach was abandoned.

## 2. Drop the superseded table

Quick and safe. Nothing reads `regridded_forecast` any more (only comments
mention it); it is 245 MB superseded by `regridded_forecast_ens`, which carries a
true ensemble spread derived from `regridded_forecast_member`. It was kept only
so the old and new numbers could be compared, and that comparison is done and
written up.

```sql
DROP TABLE regridded_forecast;
```

Grep for the name first, in case something new started reading it.

## 3. A fixture-database test layer  ← DONE (2026-08-19)

`flask_api.py` went from **41% to 83%** statement coverage; the real figure is a
little higher, because Cartopy drops coverage's tracer partway through both
render functions (the PNG assertions prove those bodies run). 283 backend tests
pass in ~11 s, with no xfails left.

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

   Found while fact-checking `REVIEW_GUIDE.md` — a good argument for writing the
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

- **`CONSISTENCY_AUDIT_PLAN.md`** — **phases 1-4 and 6 are run and closed**;
  results and every finding are in `CONSISTENCY_AUDIT.md`. Phase 2 found no
  wind/precipitation gap at all, which the plan did not expect; the real gap was
  in phase 1 (no accuracy metrics at an Analysis point) and is fixed. Phase 6 then
  found the wind gap the plan had been looking for, but in the *text* rather than
  the capability — four metrics labelled wind in `mm/h`. **Only phase 5
  (typography) is unrun** — see "If you are picking this up cold".
- **`DATA_EXPANSION_DESIGN.md`** — selecting date and initialisation. Blocked on
  one thing: the regridded tables have **no `init_time` column**, and the API
  resolves valid time from "the latest run". Loading a second run before that is
  fixed makes every score wrong in a way that looks plausible.

## 6. Lower priority

- **Vite migration** — CRA is EOL.
- **Cache the deterministic metric endpoints** — only the plot endpoint is cached.
- **Row caps on point-list queries** — currently unbounded.

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
