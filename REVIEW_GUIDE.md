# Reviewing PR #2 (`p0-reliability`)

Written for whoever reviews this before merge. Delete it after.

**It is big — 57 commits, +12,111/−1,479 — but 52% of that is tests and docs.**
More importantly it **changes numbers the app already published**, which is the
part worth your time. This guide lists every such change with the before/after
value on the loaded run, the line to look at, and the test that pins it.

You should not have to re-derive any of the science. `METRICS_AUDIT.md` is the
record, and each constant in the unit layer was established **from the stored
data**, three independent ways where it mattered — not inferred from the code.

---

## What the diff is actually made of

| area | files | added | removed |
|---|---|---|---|
| tests + fixture | 5 | 3,109 | 0 |
| docs (`.md`) | 8 | 3,180 | 9 |
| backend (`Data/`) | 7 | 3,437 | 1,028 |
| frontend (`src/`) | 18 | 2,385 | 442 |

Of the backend, `Data/metrics.py` (+729, new) is the science extracted out of
`flask_api.py` so it can be tested and reasoned about on its own. **That file is
the highest-value thing to read.** `flask_api.py` is +2,283/−1,016; the rest is
the member regrid script, schema and config.

---

## If you have twenty minutes

```bash
cd Data && pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q                 # 604 pass; 483 without PostgreSQL
```

Then, against the loaded database:

```bash
curl -s localhost:5000/api/health | python -m json.tool
```

`precip_export_convention.status` must read `ok`. That check exists because the
divisor below is a property of the **data**, not the code, so it goes stale the
moment anyone re-exports — and a stale value corrects twice with no visible
symptom. It infers the convention back out of the stored rows and compares
(`_check_export_convention`, `flask_api.py:2035`).

Then read these four constants and their comments — they are the whole unit and
window layer, and everything downstream is arithmetic on top of them:

| | `metrics.py` |
|---|---|
| `MODEL_ACCUM_HOURS` | 260 |
| `CUMULATIVE_PRECIP_MODELS` / `RATE_STORED_PRECIP_MODELS` | 268, 305 |
| `SCALED_EXPORT_DIVISOR_HOURS` | 324 |
| `COMMON_VERIFICATION_WINDOW_HOURS` | 386 |

---

## The changes that move published numbers

Highest risk first. "Loaded run" is 2025-09-08 00Z.

### 1. Every precipitation value in the app

Both AIFS and GEFS precipitation were **double-converted**. The `_scaled` JSON
export had already divided to mm/h — AIFS by 6, GEFS by a flat 3 — and the metric
layer divided again, understating both by about 7×.

`SCALED_EXPORT_DIVISOR_HOURS` (`metrics.py:324`) encodes what the export did.
Established three ways on this run, none of them circular: a cell-level fit
against observed rate (obs/increment 1.33, an ordinary dry bias, versus 7.98 if
read as an amount); a domain-mean comparison with no observations involved (AIFS
0.431 vs GEFS 0.381 vs UKMO 0.559 mm/h — dividing again puts AIFS an order of
magnitude outside the family); and a 48 h water budget (17.95 mm against 17.64 mm
observed, 1.8%).

**This constant is permanent and is not debt** — it describes how the loaded data
was produced. If GEFS is ever re-exported, it must move to `{'GEFS': 6.0}` *in the
same change*, or the correction applies twice. `/api/health` is the guard.

Tests: `test_metrics.py` golden vectors; `TestUnitConventionParity` in
`test_db_endpoints.py`.

### 2. Every score, via a common verification window

Each model emits on a different cadence, and a threshold only means one thing if
the window means one thing — UKMO's hourly records exceeded 25 mm/6h **1.64×**
more often than the identical data averaged to 6 h, so comparing its CSI against
AIFS's was comparing two different questions. Everything is now scored over a
common 6 h window (`_rebin_to_common_window`, `metrics.py:389`). This also removed
a GEFS double-count, where overlapping records pooled 12 of every 24 hours twice.

Wind is exempt — instantaneous, so there is no window to reconcile. Display paths
keep native cadence on purpose.

### 3. Spread now comes from the members, not the aggregate table

`/api/spread-skill` read the member grid; the spatial maps and
`/api/compare/skill` read aggregate tables, so **the same cell was scored from a
different source depending on which panel you opened**. `_member_cases_by_cell`
is now the single implementation behind all three.

Two reasons make the member grid the right source — and note a third, given in an
earlier draft of this guide, is **retracted**:
`regridded_forecast_ens.std_dev` is *not* an inflated pooled spread (that is the
superseded `regridded_forecast`, audit finding 11); it equals the members' sample
spread exactly, verified cell by cell. What remains:

- a cumulative model's increment spread must be approximated from stored totals as
  √(σ(h)² − σ(h−p)²), which was **31% high** at 36.0/−75.5 +12 h (0.1499 against
  an exact 0.1144) and goes negative for ~13% of AIFS records;
- re-binning onto the common window discards the spread entirely, so an hourly
  model had no spread-dependent scores at all.

At 36.0/−75.5, +6 h, map and panel now agree exactly:

| | AIFS | GEFS | UKMO |
|---|---|---|---|
| SSR | 1.0232 | 0.4486 | 1.9973 |

Side effects worth knowing: UKMO precipitation correlation **exists at all** now
(35 cells, mean +0.48, previously always empty); every model returns the same cell
count; and `+0 h` precipitation is now empty for all three rather than blank for
two and a full map for UKMO, whose 1-hour record at +0 h covers (−1, 0] — before
initialisation — and was being scored against a single instantaneous observation.

Performance was part of this: the member grid is members × cells × hours, and the
naive version was 9–65× slower. Full-domain `ssr` is now **1.06 s against 5.80 s
before**, wind `correlation` 2.03 s against 0.98 s.

Test: `test_the_map_and_the_point_panel_report_the_same_ssr`, which only works
because the fixture seeds the aggregate spread deliberately inflated.

### 4. The wind cone of uncertainty was 28% too wide

`/api/point-timeseries` took the nearest cell for precipitation but let the wind
branch aggregate in SQL over every cell within `radius` — the same defect as (3),
on the display side. At 36.0/−75.5, +0 h, `radius=0.5`: **std 2.9243 → 2.1009**,
and it no longer changes with `radius` at all (0.5 and 0.1 used to disagree for
the same point). It also reported a sample spread where precipitation reported the
population one, and omitted `n_members`. Both variables are one code path now, and
precipitation's numbers are byte-identical.

### 5. The earliest verification window was short by an hour of observations

`compare/skill` fetched observations from `min(valid_time) − (max_period − 1)`,
which is enough for observations on the hour and **not** for half-hourly IMERG.
The +6 h window averaged 11 of its 12 samples, weighted toward the end. One
character (`flask_api.py:2352`); on this run the +6 h observed rate moves
**0.025947 → 0.025035 mm/h**, understating the model's wet bias there. Later lead
times unchanged; wind never affected.

### 6. Three reporting fixes

- `compare/skill` hard-coded `units: 'mm/h'` for every variable, so the Comparison
  point chart labelled wind in mm/h (`flask_api.py:2496`).
- `n_points['fss']` was 0 beside a real score, because FSS has no per-cell map to
  count. It now reports the matched cells. This matters because AIFS's `fss` on
  this run is a real **0.0**, previously indistinguishable from no data.
- **Requesting `fss` alone returned nothing** — no value, `n_cells: 0`, and a
  warning that the grids did not overlap, none of which was true: `mae` over the
  same box returned 35 cells. The fcst↔obs fetch was skipped because FSS has no
  per-cell function of its own. `correlation` alone drew the same false warning,
  since it comes from the member path and needs no pairs. Both fixed
  (`_region_metric_points`, and `pairs_needed` at the warning).

  Found while fact-checking this guide, which is worth knowing about the test
  suite: the existing FSS test co-requested `mae`, so it passed. The replacement
  asks for **each metric on its own** — nine of the ten always worked, and only
  the combination was broken, which a per-metric loop catches and a hand-picked
  pair does not.

---

## What the tests do and do not prove

`flask_api.py` went from 41% to **100%** statement coverage; `metrics.py` is also
at 100%. 604 backend and 128 frontend tests, no xfails.

The load-bearing idea in `fixture_db.py` is that **all three models are given the
same true field in each one's own storage convention**, so they must return
identical scores — a regression in the unit or window layer breaks exactly one
model and the test names it. The conventions are restated in the fixture rather
than imported from `metrics.py`, so a wrong divisor cannot cancel itself out.

Known blind spots, all recorded in `NEXT_STEPS.md`:

- ~~**Cartopy drops coverage's tracer** partway through both render functions, so
  ~120 executed lines read as uncovered.~~ **No longer true.** It was a property
  of coverage's C tracer, not of Cartopy; `Data/.coveragerc` sets
  `core = sysmon` and both render bodies are traced directly. Nothing about the
  code changed — only what the measurement could see.
- **Two branches are excluded rather than covered**, both `else` arms the
  surrounding logic makes unreachable: `compare/skill`'s "no observations"
  warning, and the region composite's re-weighting without FSS. Each pragma
  states why, and a test pins the invariant that makes it dead — so if the
  coupling ever breaks, the test fails rather than the branch silently going
  live. The point endpoint's version of that composite branch IS live and is
  tested; the region one cannot be.
- `regridded_forecast_ens.std_dev` still agrees with the members by construction,
  so the fixture cannot tell which of those two an endpoint read. Only matters if
  the pairs-based metrics are ever migrated.
- Precipitation is flat in lead time, which is what makes bias/MAE/RMSE exactly
  derivable and also makes its spread-skill correlation degenerate. The signed
  proof of the correlation arithmetic is carried on wind instead (spread tracks
  error by construction, so the answer must be exactly +1).

**Three findings in this audit were wrong and were withdrawn.** All three failed
the same way — a real signal, misread as to cause. Never run raw Pearson on a
skewed field; always control against a known-good pair; model-vs-model agreement
is not a truth test. A fourth was misdiagnosed during this work and the corrected
diagnosis is kept beside it in `NEXT_STEPS.md`. If you disagree with a conclusion,
that document is where the reasoning lives.

---

## Decisions not to undo by accident

- `SCALED_EXPORT_DIVISOR_HOURS` is permanent (see 1).
- **GEFS filenames lie.** Every file is named
  `Total_precipitation_surface_3_Hour_Accumulation_ens_*`, including the f006/f012/
  f018/f024 files that hold **6-hour** totals. Read `step` from the file, never the
  name. Verified on two independent runs.
- Precipitation was **sparsified on load** — an absent cell means zero, so ensemble
  means must divide by every member, not by the members present.
- Observations end 2025-09-08 19:30, so truth exists only to fh ≈ 19.5. That is
  now stated in the UI rather than left to look like a bug.
- One deliberate inconsistency remains: the correlation **map** scores over a fixed
  lead-time set so models stay comparable, while the **panel** uses every native
  lead time because it describes one cell. They agree on spread, error and SSR at
  any shared hour. Flagged for `CONSISTENCY_AUDIT_PLAN.md` phase 1.

---

## Merging

`main` has not moved, so this is a clean fast-forward. No CI runs on the repo.

```bash
gh pr merge 2 --repo SoumyoDey/WEAVE --squash --delete-branch
```

`--squash` given 56 commits, many iterating on one finding. Use `--merge` instead
if the individual messages are worth keeping — they carry most of the reasoning,
and several record why an approach was abandoned.
