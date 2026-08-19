# Next steps

State as of 2026-08-19. Branch `p0-reliability`, PR #2 on `SoumyoDey/WEAVE`.

**Item 3 below is done**, and so are all six defects it found — see "What it
found" and the member-grid migration in 3b.

## Where things stand

PR #2 is **open, MERGEABLE, CLEAN, and deliberately not merged** — 51 commits,
30 files, +9219/−1332. `main` has not moved, so it is a clean fast-forward.

- 174 backend + 22 frontend tests pass. `metrics.py` at 100% statement coverage.
- No reviews, and no CI on the repo (`checks: 0`) — nothing runs on merge.
- `METRICS_AUDIT.md` is the record for everything below. Read it before
  re-deriving anything; several conclusions in it were reached, withdrawn and
  re-established, and the reasoning for each is kept.

---

## 1. Merge PR #2

Blocked only on review. It changes every precipitation number in the app, so it
is worth a second pair of eyes — particularly `Data/metrics.py`, where the unit
and window conventions live.

```bash
gh pr merge 2 --repo SoumyoDey/WEAVE --squash --delete-branch
```

`--squash` given 51 commits, many iterating on one finding. Use `--merge` instead
if the individual messages are worth keeping — they carry most of the reasoning.

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
render functions (the PNG assertions prove those bodies run). 256 backend tests
pass in ~9 s, with no xfails left.

- `Data/fixture_db.py` builds `weave_fixture_test` from the real schema
  (`schema.sql` + the DDL in `regrid_members.py`, read from source so a new
  column cannot be forgotten) and seeds one 5×5 patch of the 0.5° grid.
- `Data/test_db_endpoints.py` drives every endpoint against it, including the
  three Cartopy renders and the connection pool.
- Both skip themselves without PostgreSQL (`WEAVE_SKIP_DB_TESTS=1` to force it),
  so `python -m pytest -q` still runs anywhere: 174 pass, 67 skip.

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

Six defects, none of which the 174-test suite could see. **All six are now fixed.**
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

Finding 11 established that the stored aggregate `std_dev` is the spread of the
pooled (member × native-cell) population, so it carries within-cell spatial
variance that is not ensemble spread at all — about 23% high on the loaded run.
`/api/spread-skill` was moved onto `regridded_forecast_member` for that reason.
**The spatial maps never were**, so the Analysis map and the Analysis point panel
answered the same question from two different tables. This finishes it.

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

- **It is on one clean grid.** Every table shares the same 0.5° cells, so the
  0.25°-snap collapse in defect 6 is invisible — the fixture has nothing for two
  cells to collapse *onto*. Seeding one model on an offset or finer native grid
  would catch that whole class, which is also where audit finding 3 and the
  cross-model join bug lived. **Do this before batching the ensemble queries.**
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

## 4. Surface observation coverage in the UI

Truth exists only to fh ≈ 19.5 for the loaded run. Beyond that, verification
correctly returns nothing with a warning — but a user scrubbing to +48 h sees an
empty panel and cannot tell that from a bug. Show the observation record's extent
somewhere in the interface.

The backend half is now pinned by `TestObservationCoverage`: past the record the
endpoints return zero matched cells plus the "past the end of the observation
record" warning, and a partly observed window is rejected rather than averaged.
What is missing is the UI reading that warning.

## 5. Two planned pieces of work, with their own documents

- **`CONSISTENCY_AUDIT_PLAN.md`** — whether Analysis and Comparison behave like
  one product: metric parity (a real `fss` gap is already identified), wind vs
  precipitation parity in every context, page flow, chart grammar, typography,
  and a sweep for wrong text. Six phases, survey before fixing.
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
