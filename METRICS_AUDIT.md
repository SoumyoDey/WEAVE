# WEAVE_v3 — system, workflow & metric-correctness audit

> 2026-08-12. Evidence-based review of the verification-metric pipeline:
> physical/unit correctness, workflow logic, and system design.
> Every "confirmed" claim below is backed by a query against the live
> `weave_weather` DB or a live API call, quoted inline.
>
> **Status:** findings **1, 2, 3 and 4 are fixed** (see "Fix status" at the
> bottom). Findings 5–11 remain open. Three Analysis-tab endpoints still carry
> the old divisor and are listed there too.

---

## Severity summary

| # | Finding | Severity | Confidence |
|---|---|---|---|
| 1 | AIFS precipitation is **cumulative from init**, treated as a 6-hour bucket | Critical | Confirmed |
| 2 | GEFS precipitation uses **interleaved 3 h / 6 h buckets**, divided by a fixed 3 | Critical | Confirmed |
| 3 | Point mode returns **each lead time up to 4×** at off-grid points | High | Confirmed |
| 4 | `mean_ssr` averages per-case **ratios**, inflated by the clamp | High | Confirmed |
| 5 | FSS uses a single domain-wide fraction — measures frequency, not placement | High | Confirmed |
| 6 | Maps drawn with `step = 0.25` on a **0.5° grid** → 0.125° offset | Medium | Confirmed |
| 7 | SSR is a **variance** ratio but labelled with spread/error bands | Medium | Confirmed |
| 8 | Region metrics average per-cell ratios; point metrics pool counts | Medium | Confirmed |
| 9 | Gaussian CRPS/Brier applied to zero-inflated precipitation | Medium | By inspection |
| 10 | No ensemble-size correction `(M+1)/M` (AIFS 50, GEFS 30, UKMO 18) | Low | Confirmed |
| 11 | Two parallel truth paths (native vs regridded) for the same metric names | Design | Confirmed |

---

## 1. AIFS precipitation is cumulative from init — Critical

`MODEL_ACCUM_HOURS = {AIFS: 6, GEFS: 3, UKMO: 1}` and every consumer computes
`rate = mean_value / accum_h`. For AIFS that assumes each record is *that
period's* total. It is not — it is the running total since initialisation.

Domain-mean by lead time is monotone, which only happens for a cumulative field:

```
AIFS  [0.335, 0.787, 1.198, 1.583, 1.941, 2.369]  monotone=True
GEFS  [0.286, 0.458, 0.265, 0.468, 0.255, 0.428]  monotone=False
UKMO  [0.300, 0.298, 0.358, 0.417, 0.460, 0.463]  monotone=False
```

A single grid point (36.0 N, 75.5 W) shows the same, and the size of the error:

| lead | raw | `raw/6` (reported today) | `(raw−prev)/6` (true rate) |
|---|---|---|---|
| +6h | 0.1620 | 0.0270 | 0.0270 |
| +12h | 0.2723 | 0.0454 | 0.0184 |
| +24h | 0.3547 | 0.0591 | 0.0053 |
| +48h | 1.8083 | 0.3014 | 0.0842 |

The reported "rate" is right only at the first lead time and then drifts
without bound — at +48 h it is 3.6× the true rate, and the gap keeps growing
because the numerator is a running total. Everything scale-dependent is
affected for AIFS: **bias, MAE, RMSE, CRPS, and every threshold-based score**
(CSI/POD/FAR/Brier compare a growing cumulative value against a fixed
mm/6h threshold, so exceedance becomes near-certain at long leads).

SSR survives numerically (`σ²/ε²` is scale-invariant) but changes meaning: it
describes the calibration of *cumulative* precipitation, which is not
comparable to UKMO's hourly SSR sitting next to it in the same chart.

**Fix:** de-accumulate before rating — `(v(h) − v(h−6)) / 6`. Needs a
lead-time-aware fetch, since the current query returns each row independently.

## 2. GEFS interleaves 3-hour and 6-hour buckets — Critical

Grouping every GEFS record by `forecast_hour mod 6`:

```
h mod 6 = 0 : mean 0.3767  (n=54300)
h mod 6 = 3 : mean 0.2030  (n=50381)
```

A ratio of 1.86 ≈ 2 over ~100 k records is the standard NCEP bucketing
pattern: records at h ≡ 3 (mod 6) are 0–3 h / 6–9 h totals, records at
h ≡ 0 (mod 6) are 0–6 h / 6–12 h totals. Dividing everything by 3 is correct
for the odd buckets and **2× wrong for the even ones**, so GEFS metrics carry a
sawtooth artefact that alternates with lead time.

**Fix:** `h % 6 == 3 → v/3`; `h % 6 == 0 → (v − v(h−3))/3`.

## 3. Point mode multiplies every lead time at off-grid points — High

`compare_skill` selects forecasts with `latitude BETWEEN lat±0.26` on a **0.5°**
grid, then iterates rows. A grid-aligned point catches one cell; a point near a
cell corner catches four:

```
(36.00, -75.50) grid-aligned    -> 1 forecast row at a single hour
(35.75, -75.75) on the cell edge -> 4 forecast rows at a single hour
```

Live API at the edge point (`hour_min 0, hour_max 12`):

```
hours returned : [0,0,0,0, 1,1,1,1, 2,2,2,2, ... 12,12,12]
duplicated     : {0:4, 1:4, 2:4, ... 11:3, 12:3}
summary n      : 50   (should be 13 distinct lead times)
```

Consequences: the per-lead-time charts plot up to four points per hour; the
summary means divide by 50 instead of 13 and silently weight cells that happen
to have more rows; and each of the four distinct forecast cells is verified
against the *same* box-averaged observation (`AVG(value)` over the box), so
three of the four comparisons are against the wrong cell's obs.

**Fix:** select the nearest single cell (or aggregate cells explicitly and
match obs per cell rather than box-averaging).

## 4. `mean_ssr` averages ratios and inherits the clamp — High

`compare_skill` computes a per-lead-time `ssr = σ²/ε²`, then reports the plain
mean. Since `E[X/Y] ≠ E[X]/E[Y]`, and a single case can have `ε² ≈ 0`, the
per-case ratio explodes; `_clamp_ssr` caps it at 10, which then drags the mean
upward rather than being neutral.

Live: AIFS at (36, −75.5) returns `+6h ssr = 10.0` — a clamped value — and the
reported `mean_ssr = 3.8135`. One saturated case dominates the headline number.

The spatial metric already does this correctly: `_compute_ssr_agg_points_rf`
uses `mean(σ²) / mean(ε²)`. Point mode should use the same estimator — that is
also the standard definition of the spread–skill ratio over a sample.

## 5. FSS is a domain frequency comparison, not a fractions skill score — High

`_categorical_hours_for_box` reduces the whole box to two scalars
(`f` = forecast event fraction, `o` = observed event fraction) and returns
`1 − (f−o)² / (f² + o²)`.

Roberts–Lean FSS computes fractions in a *sliding neighbourhood around each
grid point*, then averages the squared differences over all points. With one
box-wide fraction there is no neighbourhood and no spatial information: two
fields with identical event counts but completely disjoint placement score
**FSS = 1.0**. The metric as implemented answers "do the two fields rain over
the same *amount* of area", not "do they rain in the same *place*" — which is
the entire purpose of FSS.

The `fss_window` control reinforces the misreading: it changes the size of the
box, but the score is still a single fraction over that box, so it is a domain
selector, not a neighbourhood width. The UI labels it "Fractions Skill Score ·
higher is better".

**Fix:** either implement true neighbourhood fractions (convolve the binary
fields with an n×n kernel, then `1 − Σ(f−o)² / Σ(f²+o²)` over points), or
rename it — "event-frequency agreement" — and drop the window control.

## 6. Maps are drawn at the wrong cell size — Medium

`_render_metric_map_png` hard-codes `step = 0.25` for pcolormesh cell edges,
but `regridded_forecast` is on a **0.5°** grid:

```
distinct lats: [25.0, 25.5, 26.0, 26.5, 27.0, 27.5]  spacing 0.5
```

`lat_edges = [lat − 0.125 …, last + 0.125]` makes every cell span
`lat−0.125 … lat+0.375`, i.e. **shifted 0.125° (~14 km) north and east** of its
true centre, and the final row/column is drawn at half width. Every metric map
in both tabs is georeferenced slightly wrong.

**Fix:** derive `step` from the median spacing of `lats_set`/`lons_set` instead
of assuming 0.25.

## 7. SSR convention vs its legend — Medium

The code computes a **variance** ratio (`σ² / ε²`), while
`PLOT_STYLE_REGISTRY['ssr']` labels the bands `<0.5 severely underdispersive`,
`0.8–1.2 calibrated`, `>2.0 severely overdispersive`. Those are the
conventional bands for the **spread/error** ratio `σ / RMSE`. Both are 1 when
perfectly calibrated, so the centre is fine, but the wings are mislabelled: a
variance ratio of 0.5 is a spread/error ratio of 0.71, which is not "severe".
Either take the square root before plotting or relabel the bands (0.64–1.44 for
the same tolerance).

## 8. Region and point categorical metrics use different estimators — Medium

- Point mode (`_categorical_summary`, added in Inc 2) pools hits/misses/false
  alarms across lead times and then forms the ratio — event-weighted, correct.
- Region mode (`_region_mean`) averages **per-cell CSI/POD/FAR values** — an
  unweighted mean of ratios, where a cell with two cases counts as much as a
  cell with fifty.

The same metric name in the same tab is computed two different ways. The region
figure also cannot be reproduced from the region's contingency table. The
per-cell mean is the right choice for the *map* (it is what each pixel shows),
but the headline bar should pool. Same issue for region RMSE: the mean of
per-cell RMSE is not the domain RMSE, because the square root is not linear.

Related UI inconsistency: the diff map's mean is over *shared* cells while the
region bars are over each model's own cells. Equal when both are 54; for CSI
they were 27 vs 54, so `bar(A) − bar(B) ≠ mean diff`.

## 9. Gaussian assumption for precipitation — Medium

CRPS uses the closed-form Gaussian CRPS, and Brier gets its event probability
from `1 − Φ(threshold; μ, σ)`. Both formulas are **correctly implemented** (I
checked the CRPS identity against the standard-normal value at the mean,
`(1/√π)(√2 − 1) ≈ 0.2337`, which the test suite pins). The issue is the
distribution: precipitation is non-negative, zero-inflated and right-skewed, so
a Gaussian assigns real probability mass below zero and understates the upper
tail. For wind speed it is defensible; for precipitation, CRPS and Brier carry a
systematic bias, largest for light-precip cells where μ ≈ 0.

Worth at minimum a documented caveat; a censored/gamma distribution would be the
proper fix.

## 10. No ensemble-size correction — Low

A finite ensemble under-estimates variance; the standard correction is
`σ²·(M+1)/M`. Member counts differ substantially:

```
AIFS 50, GEFS 30, UKMO 18
```

so the correction is 2.0 %, 3.3 % and 5.6 % respectively — a ~3.5 % *relative*
bias between AIFS and UKMO in every SSR comparison. Small next to findings 1–5,
but it is a free fix and it specifically distorts cross-model ranking, which is
this tab's whole purpose.

## 11. Two parallel truth paths — Design

| | Analysis point mode | Comparison point mode |
|---|---|---|
| Forecast | `forecast_data` / `ensemble_statistics` (native, per-member) | `regridded_forecast` (mean/std) |
| Obs | `observation_data` | `regridded_observation` |
| Match | 0.5° radius, exact per-member speed | ±0.26° box, `|mean vector|` for wind |

Same metric names, two pipelines, different numbers — this is the root cause of
the "Analysis and Comparison SSR disagree" observation, not a bug in either.
It also means a fix to the accumulation handling has to be made in both places.

Recommend one metric layer (`Data/metrics.py`) parameterised by data source,
with the endpoints as thin adapters. `flask_api.py` is ~3 700 lines mixing
routing, SQL, numerics and Cartopy rendering.

Also worth noting: metric computations are deterministic in
(model, bbox, hours, threshold) but only the *plot* endpoint is cached, so
recomputing the same region metrics re-runs the full query each time; and the
point-list queries have no row cap, so a large bbox pulls an unbounded result
set into Python.

---

## What I checked and found correct

- CRPS closed form (both copies) — matches the standard Gaussian CRPS identity.
- CSI / POD / FAR definitions and their contingency-table denominators.
- `_categorical_summary` pooling (Inc 2) — event-weighted, verified by test.
- `_spatial_diff_points` — subtraction, shared-cell intersection, 0.25° snap.
- Region means match `/api/spatial-metric` exactly (MAE 0.5720 / 54 cells;
  CSI 0.2901 / 27 cells).
- Wind: forecast speed uses `√(u²+v²)` rather than the u component, and
  `accum_h = 1` is correctly applied so no precip factor leaks into wind.
- The obs half-hourly cadence is handled correctly — `_fetch_fcst_obs_pairs_spatial`
  keys on exact hourly timestamps and averages to a rate.
- SSR clamp, FSS `None`-when-no-events, and the threshold unit split
  (mm/6h vs m/s) all behave as documented.

## Known approximation, already documented

`|mean vector|` for ensemble-mean wind speed (`√(mean_u² + mean_v²)`)
under-estimates mean speed by Jensen's inequality, and `√(σu² + σv²)` is not the
speed's standard deviation. Flagged in the code and in the plan; exact per-member
speed is only computed on the native path.

---

## Suggested order of work

1. **Findings 1 + 2** — de-accumulate AIFS and GEFS. Nothing else about
   precipitation verification is trustworthy until this lands.
2. **Finding 3** — nearest-cell selection in `compare_skill`.
3. **Finding 4** — pooled SSR estimator for point mode.
4. **Finding 5** — real neighbourhood FSS, or rename and drop the window.
5. **Findings 6–8** — render step, SSR labelling, estimator consistency.
6. **Findings 9–11** — documented caveats and the metric-layer refactor.

Findings 1–3 should come with regression tests built from the golden vectors
already in `Data/test_metrics.py`.

---

## Fix status (2026-08-12)

**Fixed — 1, 2, 3, and 4.**

A `_precip_rate_series()` layer now applies each model's own record semantics
(`_precip_period_hours`, `_precip_lookback_hours`, `CUMULATIVE_PRECIP_MODELS`)
instead of a single divisor. Finding 4 came along with it because the SSR
aggregation sits in the same rewritten block.

Converted: `_fetch_fcst_obs_pairs_spatial` (region metrics, spatial maps,
spatial diff), `compare_skill` (also nearest-cell, finding 3),
`_categorical_hours_for_box`, `compare_timeseries`, `point_timeseries`,
`_compute_ssr_points`, `_compute_correlation_points`. The frontend no longer
divides — `/api/compare/timeseries` returns rates and owns the unit.

Verified live:

- AIFS rates now equal the hand-computed de-accumulated series exactly
  (`+6h 0.0270, +12h 0.0184, +24h 0.0053, +48h 0.0842`), and AIFS bias no
  longer drifts with lead time (`+0.007, +0.018, -0.020, +0.005` vs the old
  `+0.007, +0.045, +0.025, +0.059`).
- GEFS records now report their own period (`p3`/`p6` alternating).
- The off-grid point returns 12 distinct lead times instead of each one 4×,
  and reports the cell it used (`model_cells`).
- **Regression guard:** UKMO precipitation and all wind numbers are byte-for-byte
  unchanged (UKMO bias 0.106, mae 0.874, csi 0.304, ssr_agg 4.038; AIFS wind
  bias 1.579, mae 3.849, ssr_agg 0.978) — exactly right, since neither
  model's semantics changed.
- 59 backend tests pass (was 46); 13 new ones cover the semantics layer.

### Two things to be aware of

**AIFS now reads much drier.** De-accumulated, its domain-mean rate is ~0.07 mm/h
against ~0.55 mm/h observed, and region bias moved from −0.33 to −0.48 mm/h.
The *structural* handling is now right — the monotone series leaves no doubt the
old per-6h reading was wrong — but a residual factor this large suggests the
AIFS ingest may also carry a unit/scale issue that can't be settled without the
source spec. The old code partly masked this: dividing a growing cumulative by 6
happened to land near the observed rate at short leads. Worth confirming against
the provider's field definition before drawing conclusions about AIFS skill.

**Spread on a cumulative model is approximate.** The stored AIFS std is the
spread of the *total*; the increment's spread is estimated as
`sqrt(Var(C_h) − Var(C_h−6))`, which is negative for ~13% of records. Those
return `None` and are skipped by SSR/CRPS/Brier rather than fabricated — so
those three metrics use a non-random subset for AIFS. Deterministic metrics
(bias/MAE/RMSE/CSI/POD/FAR) are exact. The clean fix is to difference
per-member in `forecast_data` (50 AIFS members are there) and take the spread of
the increments.

### Still on the old divisor

These Analysis-tab endpoints were not converted and still divide by a fixed
`MODEL_ACCUM_HOURS`, so their AIFS/GEFS precipitation numbers remain wrong:

- `GET  /api/spread-skill` — member-level, so it could compute the AIFS
  increment spread *exactly*; the best place to fix the spread problem above.
- `POST /api/categorical-metrics`
- `POST /api/region-categorical-metrics`

`_fetch_ens_obs_pairs_spatial` / `_ens_pairs` also still contain the old logic
but are dead code (no live callers) and are candidates for deletion.
