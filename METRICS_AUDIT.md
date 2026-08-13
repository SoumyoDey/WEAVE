# WEAVE_v3 — system, workflow & metric-correctness audit

> 2026-08-12. Evidence-based review of the verification-metric pipeline:
> physical/unit correctness, workflow logic, and system design.
> Every "confirmed" claim below is backed by a query against the live
> `weave_weather` DB or a live API call, quoted inline.
>
> **Status:** findings **1–10 are fixed** across every endpoint (see "Fix
> status" at the bottom), plus a spread-pooling bug (3b) found while fixing
> them. Finding 11 is partly addressed — the numerics are extracted; the
> two-truth-paths part is data architecture and remains open.

---

## Severity summary

| # | Finding | Severity | Confidence |
|---|---|---|---|
| 1 | AIFS precipitation is **cumulative from init**, treated as a 6-hour bucket | Critical | Confirmed |
| 2 | GEFS precipitation uses **interleaved 3 h / 6 h buckets**, divided by a fixed 3 | Critical | Confirmed |
| 3 | Point mode returns **each lead time up to 4×** at off-grid points | High | Confirmed |
| 3b | `/api/spread-skill` pooled ~24 cells into the "ensemble" (`n_members` 1199 for a 50-member run), so its spread was largely spatial variance | High | Confirmed |
| 4 | `mean_ssr` averages per-case **ratios**, inflated by the clamp | High | Confirmed |
| 5 | FSS uses a single domain-wide fraction — measures frequency, not placement | High | Confirmed |
| 6 | Maps drawn with `step = 0.25` on a **0.5° grid** → 0.125° offset | Medium | Confirmed |
| 7 | SSR is a **variance** ratio but labelled with spread/error bands | Medium | Confirmed |
| 8 | Region metrics average per-cell ratios; point metrics pool counts | Medium | Confirmed |
| 9 | Gaussian CRPS/Brier applied to zero-inflated precipitation | Medium | By inspection |
| 10 | No ensemble-size correction `(M+1)/M` (AIFS 50, GEFS 30, UKMO 18) | Low | Confirmed |
| 11 | Two parallel truth paths (native vs regridded) for the same metric names | Design | **Resolved 2026-08-13** |
| 12 | AIFS cumulates a **mean rate (mm/h)**, not an amount — differencing then dividing by 6 made every AIFS precip number 6× too dry | Critical | Confirmed |
| 13 | A **partially observed** verification window was accepted, scoring a 6 h forecast against one observation up to 5 h from its valid time | High | Confirmed |
| 14 | ~~ERA5 wind is a different weather field~~ — **interpretation withdrawn 2026-08-13**; data confirmed correct by its owner. The measurement stands as an open verification result | Open question | Reframed |
| 15 | ~~GEFS precipitation correlates with nothing~~ — **RETRACTED 2026-08-13**, the analysis was invalid (raw Pearson on a heavily skewed field) | — | Withdrawn |
| 16 | GEFS precipitation was **double-converted** — its export already produced mm/h and the code divided by the bucket length again | Critical | Confirmed |
| 17 | Each model was verified on its **own cadence**, so the same threshold asked a different question of each and cross-model scores were not comparable | High | Confirmed |

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

### Analysis-tab endpoints — also converted

`GET /api/spread-skill`, `POST /api/categorical-metrics` and
`POST /api/region-categorical-metrics` now use the same semantics layer. No
fixed divisor remains anywhere in the codebase, and the dead
`_fetch_ens_obs_pairs_spatial` / `_ens_pairs` helpers (which still carried the
old convention) were deleted.

**`/api/spread-skill` got an exact spread, and a second bug fixed.** It pooled
every grid cell within the search radius into one member list — a 50-member
AIFS ensemble was reporting `n_members: 1199`, roughly 24 cells x 50 members —
so its "ensemble spread" was mostly *spatial* variance, which inflated SSR. It
now picks the cell nearest the clicked point, reads that cell's members, and
matches observations centred on the same cell.

Because that path has per-member data, AIFS is differenced **per member**, which
is exact: the spread of the differenced members is the true spread of the
increment, with no variance-subtraction approximation and no dropped records.
This is the fix recommended above, now applied.

Effect at (36.0 N, 75.5 W), AIFS precipitation:

| | before | after |
|---|---|---|
| `n_members` | 1199 | 49–50 |
| spread +6h | 0.0290 | 0.0248 |
| SSR +6h | 1.8126 | 0.9740 |
| SSR +12h | 1.5580 | 1.2612 |

**`/api/point-timeseries` (Cone of Uncertainty) got the same treatment.** It
previously aggregated in SQL (`AVG`/`STDDEV`/percentiles) and then scaled the
result, which described the running total rather than the amount falling in
each period — and half-converting it (differenced mean, undifferenced spread)
produced a visibly wrong cone: a near-zero mean under a band inherited from the
cumulative spread, pushing the y-axis to 2.2 mm/h. It now de-accumulates each
member first and builds mean / std / min / max / percentiles from the
differenced members, so the whole distribution is internally consistent (the
axis settles at 0.8 mm/h for the same point).

The remaining approximation is confined to the aggregate mean/std path
(`regridded_forecast`), which has no members to difference.


---

## Fix status — findings 5-10 (2026-08-12)

**5. FSS is now a real neighbourhood score.** `_fss_components` /
`_fractions_skill_score` compute event fractions in a `window`x`window` box
around each grid point (summed-area table, so cost is independent of window
size), then `1 - sum((f-o)^2) / sum(f^2+o^2)` over the shared cells. Cells
absent from the grid are excluded from the neighbourhood rather than counted as
dry. Multi-case aggregation sums numerators and denominators instead of
averaging per-hour scores.

The behaviour that was missing is now present and pinned by tests: two fields
with identical event frequency but disjoint placement score 0.0 (they scored a
perfect 1.0 before), and a one-cell displacement scores better as the window
grows. Live, UKMO over a 48 h window: `fss = 0.0` at window 3 and `0.879` at
window 7.

**6. Map cell size is measured, not assumed.** `_grid_step` takes the median gap
between adjacent coordinates (robust to a missing cell), so the 0.5-degree data
is drawn at 0.5 degrees. Every metric map was previously shifted 0.125 degrees
north-east with a half-width final row/column.

**7. SSR is reported as spread/error.** It was computed as a variance ratio but
labelled with the conventional sigma/RMSE bands, mis-stating the wings — a
variance ratio of 0.5 is a spread/error ratio of 0.71, which is not "severe".
All five SSR sites now go through `_ssr_from_variances`, which returns
`sqrt(mean_var / mean_sq_err)`. The colourbar bands and UI thresholds were
already the sigma/RMSE ones and are unchanged. Verified arithmetically against
the live API: spread `0.0248` / error `0.0252` reports `0.9969`.

**8. Region metrics pool over samples.** `_region_pooled_metrics` computes the
region value from every (cell, lead time) sample: CSI/POD/FAR from summed
contingency counts, RMSE as `sqrt(mean(err^2))`, and so on — the same estimator
point mode uses. The unweighted per-cell mean is still returned as `cell_means`
because that is what the corresponding *map* averages to. The two genuinely
differ: for AIFS, pooled RMSE is `1.329` against a per-cell mean of `0.750`
(Jensen), and pooled CSI `0.208` against `0.157`. `correlation` has no pooled
form and stays a cell mean, which is now stated in the code.

**9. The predictive distribution is centralised and censored at zero.**
`_gaussian_crps` and `_exceedance_probability` are the single home for the
assumption, used by all five CRPS/Brier sites. For a non-negative variable the
Gaussian is now censored at zero (`X = max(0, Y)`), which is the physically
admissible reading. The correction is exact rather than ad hoc: for `y >= 0`,

    CRPS_gauss - CRPS_censored = integral over x<0 of Phi((x-mu)/sigma)^2 dx

because the censored CDF is 0 below zero and the two agree above it. That
integral is evaluated by 24-point Gauss-Legendre quadrature. Exceedance
probabilities for a threshold `>= 0` are unchanged by censoring, so Brier is
identical either way; CRPS picks up the correction, which is negligible when
`mu >> sigma` and material when `mu ~ 0` — exactly the light-precipitation
cells the finding was about.

This does not make the distribution *correct* for precipitation, which is also
zero-inflated and right-skewed. The exact fix is an empirical/ensemble CRPS,
which needs per-member data the aggregate tables do not carry.

**10. Finite-ensemble spread correction applied.** `_spread_inflation` applies
`sqrt((M+1)/M)` to the spread inside every SSR. Member counts are resolved once
per process (`_ensemble_size`, a 2-6 s `COUNT(DISTINCT)`, cached) — AIFS 50,
GEFS 30, UKMO 18, i.e. 1.0%, 1.6% and 2.7% on the spread. Without it the
cross-model SSR ranking carried a ~1.7% relative bias between the largest and
smallest ensemble.

81 backend tests pass (was 64).


## Fix status — finding 11 (partial)

The **numerics are now a separate module.** `Data/metrics.py` holds the pure,
DB-free, Flask-free metric functions — precipitation record semantics, the
spread-skill ratio, the predictive distribution, FSS, region aggregation and
spatial differencing — and `flask_api.py` imports them by name. `metrics.py`
imports standalone (verified: `import metrics` with no Flask and no database),
which is what lets the golden-vector suite cover the science directly.

`flask_api.py` still holds routing, SQL and Cartopy rendering.

**What is NOT fixed:** the two parallel truth paths. Analysis point mode reads
native `forecast_data` / `ensemble_statistics` + `observation_data`; the
Comparison tab reads `regridded_forecast` / `regridded_observation`. Both are
now consistent internally and share `metrics.py`, but they remain two different
samples of the same quantity, so the same metric name can legitimately differ
between tabs. Collapsing that is a data-architecture decision (pick one source
of truth, or label each view with its source), not a refactor.

Also still open from the audit's notes: metric results are deterministic in
(model, bbox, hours, threshold) but only the *plot* endpoint is cached, and the
point-list queries have no row cap.


---

## Follow-ups after the findings (2026-08-12)

Two gaps that only became visible once FSS was a real neighbourhood score.

**FSS is now offered everywhere it applies, with its scale selectable.**
It was missing entirely from the Comparison tab's region view — the most
spatial view in the app was the one place without the spatial skill score.
`fss` joins `COMPARE_REGION_METRICS`, computed by `_fss_from_pairs`, which
rebuilds the binary fields per lead time and sums components across them.
Unlike every other region metric it has no per-cell value, so it is flagged
`noMap`: absent from the map picker (verified — the picker offers the other
ten) and `None` in `cell_means`.

Where FSS appears, its neighbourhood is now selectable:

| View | FSS | Window control |
|---|---|---|
| Comparison · point (advanced metrics) | yes | yes |
| Comparison · region | **yes (new)** | **yes (new)** |
| Analysis · region | yes | yes |
| Analysis · point | n/a — spatial only | n/a |

**The FSS window no longer resizes the verification box.** In
`compare/categorical` the two were one parameter:

    hw = max(fss_window * 0.25, 0.26)

so widening the neighbourhood also widened the domain, and CSI/POD/FAR moved
when only the FSS scale was meant to. `box_cells` (default 9) now sizes the
box and `fss_window` is the neighbourhood inside it; the box is clamped to be
at least the window, or the neighbourhood would be clipped and FSS would slide
back toward the old domain-fraction behaviour.

Verified live — window 1/3/7 at a fixed box of 9:

    fss  0.6766 -> 0.8238 -> 0.8702
    csi  0.5113 -> 0.5113 -> 0.5113      (unchanged, as it must be)
    n    1447   -> 1447   -> 1447

and changing the box alone (3 vs 9) moves the sample: `n_pts` 159 -> 1447.

Note this changes point-mode categorical values, because the box no longer
defaults to the window: at `fss_window` 3 the box was +/-0.75 degrees and is
now +/-2.25.

141 backend tests pass (was 134).


## The scored area is now explicit, and FSS reaches Analysis point mode

"Point" meant two different things and neither tab said so. Analysis point mode
scored a single grid cell; Comparison point mode scored a box around the click
(9x9 after the box/window split above, roughly 4.5 degrees across) under a
heading reading "Compare models at a single location". Worse, within Comparison
point mode the two halves disagreed: SSR/MAE/RMSE described one cell while
CSI/POD/FAR described the box.

That asymmetry is also the whole reason FSS was available in one and not the
other. FSS compares event *fractions* in a neighbourhood; with one cell the
fraction can only be 0 or 1 and the score degenerates into the hit-or-miss CSI
already reports. It was undefined, not missing.

**Both tabs now state the area they scored.** `/api/categorical-metrics`
returns `scored_area` (centre cell, box_cells, fss_window, bbox, n_cells);
`/api/compare/categorical` already returned its bbox and now its box. Each tab
renders a "scored: ..." badge beside the results, and the Comparison mode
subtitle no longer claims a single location.

**Analysis point mode can now produce an FSS,** via a `box_cells` control
(default 1). The design keeps the point metrics honest: the contingency table
and CSI/POD/FAR are always read from the **centre cell only**, so widening the
box gives FSS a field without moving them. Verified at 36.0N 75.5W, threshold
0.2 mm/6h:

    box   1 ( 1 cell ):  H=0 M=0 FA=9  csi=0.0  far=1.0  fss=None
    box   5 (25 cells):  H=0 M=0 FA=9  csi=0.0  far=1.0  fss=0.6773
    box   9 (81 cells):  H=0 M=0 FA=9  csi=0.0  far=1.0  fss=0.7937

The contingency counts are byte-identical across all three; only FSS changes.
At `box_cells` 1 FSS is None and the UI says why rather than showing a zero.

This also closes the residual finding-3 case in that endpoint: it centres on
the nearest grid cell instead of taking whichever row the +/-0.26 degree window
returned first, so the box is exactly `box_cells` per axis regardless of where
in a cell the user clicked.

---

## 12. AIFS cumulates a mean rate, not an amount — Critical (2026-08-13)

Finding 1 established that AIFS precipitation is a running total since init and
must be differenced. That was right. What the fix then assumed — that the
increment is an **amount in mm**, to be divided by the 6 h window to reach mm/h
— is wrong. The increment is *already a mean rate in mm/h*, so dividing by the
period made every AIFS precipitation number **6× too dry**.

This is the residual "AIFS reads much drier than observed" item left open on
2026-08-12. It is **not** an ingest unit error, and it did not need the provider
field spec: the loaded data settles it three independent ways.

**1 — Cell-level fit against observations.** AIFS 6-hourly increment vs the
observed mean rate over the same window, 2025-09-08 00Z run:

```
window  0- 6h  n=1295  obs = 1.123*incr + 0.087  r=0.401  obs/incr = 1.383
window  6-12h  n=1305  obs = 1.485*incr - 0.058  r=0.580  obs/incr = 1.359
window 12-18h  n=1353  obs = 0.804*incr + 0.208  r=0.452  obs/incr = 1.266
POOLED         n=3953  obs = 1.154*incr + 0.073  r=0.497  obs/incr = 1.331
```

Read as a rate, obs/forecast is **1.33** — an ordinary mild dry bias. Read as an
amount (incr/6), obs/forecast is **7.98**, which is exactly 6 × 1.33. The
reported "~8× dry bias" was one real factor of 1.33 and one spurious factor of 6.

**2 — Model-to-model, no observations involved.** Domain-mean rate over 6-18 h:

```
GEFS                        0.3807 mm/h
UKMO                        0.5590 mm/h
AIFS increment as-is        0.4313 mm/h   <- in family
AIFS increment / 6          0.0719 mm/h   <- an order of magnitude out of family
```

**3 — Water budget over 48 h.** Stored AIFS cumulative at 48 h is 2.992.

```
as an amount   ->  2.99 mm over 48 h
as a rate x 6h -> 17.95 mm over 48 h
observed                17.64 mm over 48 h   (0.368 mm/h x 48)
```

The rate reading lands within 1.8% of observed; the amount reading is 6× short.

### Fix

`RATE_CUMULATED_PRECIP_MODELS = {'AIFS'}` in `metrics.py`, applied through
`_increment_divisor(model, period)` in both rate paths (`_precip_rate_series`
and `_precip_member_rate_series`, which are now covered by a test asserting they
agree). The record still *covers* 6 h — `_precip_period_hours` stays 6, so the
increment is still verified against the observed mean rate over the same 6 h.
Only the divisor changed.

Effect on the region suite (32-40N, 80-72W, 6-18 h, threshold 1 mm/6h):

```
              bias      mae      csi      fss
AIFS before  -0.6690   0.6932   0.3993   0.6950
AIFS after   -0.2141   0.6741   0.6595   0.8988
```

AIFS moves from an implausible dry outlier to the best-scoring model in the set,
which is what one would expect of it.

---

## 13. A partially observed verification window was accepted — High (2026-08-13)

Found while checking finding 12. Every fcst↔obs match built its observation
window as "whatever samples exist in the last `period` hours" and accepted it if
**at least one** was present:

```python
obs_window = [obs_dict[(lat, lon, vt - timedelta(hours=dh))]
              for dh in range(period - 1, -1, -1)
              if (lat, lon, vt - timedelta(hours=dh)) in obs_dict]
if not obs_window:
    continue
```

The observation record ends at 2025-09-08 19:30 and the run initialises at
00Z, so truth exists only out to fh ≈ 19.5. Yet a region query over hours 24-48
returned **229 AIFS cells with bias 0.3048**. The AIFS record at fh 24 is valid
2025-09-09 00:00; its window reaches back to Sep 8 19:00, where exactly one
observation still exists. A 6-hour forecast was being scored against a single
observation **5 hours from its valid time**, and the result was presented with
no indication that anything was wrong.

### Fix

`_obs_window_mean(cell_obs, valid_time, period)` in `metrics.py` returns
`(mean, covered_hours, n_samples)`, and all five call sites now reject a window
with `covered < period`. Two further corrections came with it:

- The window is **left-open, right-closed** `(vt - period, vt]`, so the sample
  exactly one period back belongs to the previous record, not this one. The
  observation pre-fetch was widened from `max_period - 1` to `max_period` to
  match.
- **Sub-hourly observations now count.** IMERG is half-hourly and the old code
  only looked at whole hours, discarding half the record. A 6 h AIFS window now
  averages 12 samples instead of 6; `n_obs_in_window` in `/api/compare/skill`
  reports it.

Hours 24-48 now return no score and a warning naming the cause, instead of a
fabricated number. Hours 6-18 keep identical cell counts (227/270/283), so the
coverage requirement costs no legitimate data.

### Call sites converted

| Endpoint | Path |
|---|---|
| `/api/compare/skill` | point, per model |
| `/api/compare/categorical` | point + neighbourhood FSS closure |
| `/api/categorical-metrics` | Analysis point/region |
| `_fetch_fcst_obs_pairs_spatial` | every region + spatial-map metric |

Tests: `TestObsWindowMean` (8 cases) pins the boundary convention, partial
coverage, sub-hourly averaging, and slots-vs-samples. `metrics.py` remains at
100% statement coverage; 151 backend + 22 frontend tests pass.

---

## 11 (resolved). One truth path, and a real ensemble spread — 2026-08-13

Finding 11 sat open as "a data-architecture decision". Measuring it first made
the decision obvious. The split was never Analysis-vs-Comparison — the Analysis
tab straddled it, since `/api/categorical-metrics` already read the regridded
grid. The real line was **display reads native, verification reads regridded**,
with exactly one exception: `/api/spread-skill`.

### What the divergence actually was

AIFS precipitation at 36.0 N 75.5 W, same model, same lead times, before:

```
 fh   native mean  native obs  native SSR |  regrid mean  regrid obs  regrid SSR
  6        0.1762      0.0042       0.875 |       0.1620      0.0259       1.039
 12        0.1025      0.0000       1.134 |       0.1103      0.0167       1.876
 18        0.0400      0.0030       2.792 |       0.0503      0.0836       5.911
```

The *forecasts* agreed within ~8%. The **observations** differed by up to 6× and
the spread-skill correlation came out **+0.97 native against −0.97 regridded** —
the same point, the same run, opposite conclusions. The cause was
representativeness, not a bug in either: the native path scored a 0.25° forecast
cell against a 0.1° IMERG point, the regridded path scored 0.5° area against
0.5° area.

### A second defect this exposed

`regridded_forecast.std_dev` is the spread of the pooled (member × native-cell)
population, so it carries within-cell **spatial** variance that is not ensemble
spread at all. Measured per cell it runs about **1.235×** the true ensemble
spread, and every spread-dependent score — SSR, CRPS, Brier — inherited that
inflation. It also made exact per-member differencing of a cumulative model
impossible, because the members were gone by the time the data was regridded.

### Fix

`Data/regrid_members.py` regrids each ensemble member onto the shared 0.5° grid
by bilinear interpolation — the operator `cdo remapbil` applies — and derives the
ensemble statistics from those members:

```
mean_value = mean over the regridded members
std_dev    = sample spread across members, with no spatial variance mixed in
```

The original member files are not on this machine, so the interpolation runs from
`forecast_data` rather than through CDO itself. Bilinear is a **linear** operator,
which gives a free and exact check that the implementation is right:

```
mean(bilinear(members)) == bilinear(mean(members))     max|diff| = 0.000e+00
```

`--verify` asserts this. It also caught a real subtlety: precipitation was
sparsified on load (dry cells were never written, the smallest stored AIFS value
is 0.002 mm), so an absent cell means zero and the ensemble mean must divide by
**every** member, not only those that reported. Averaging just the reporting
members biases the field wet, and the linearity check fails by 1.0e-1 until the
convention is applied consistently on both sides.

Output goes to new tables — `regridded_forecast_member` (13.2M precipitation rows
+ wind) and `regridded_forecast_ens` — so nothing was overwritten before the two
could be compared. The derived mean lands within **0.4%** of the stored one
(0.33400 vs 0.33532), so bias/MAE/RMSE/CSI/FSS barely move; only the
spread-dependent scores shift, which is the point.

`/api/spread-skill` now reads the member grid and the regridded observations,
snapping the click to its 0.5° cell, and every comparison endpoint reads
`regridded_forecast_ens`.

### Result

The same point, after:

```
 fh | spread-skill mean     obs     SSR | compare mean     obs     SSR
  6 |            0.1726  0.0250  1.0232 |      0.1726  0.0259  1.0400
 12 |            0.1010  0.0167  1.3712 |      0.1010  0.0167  1.7959
 18 |            0.0400  0.0836  2.3707 |      0.0400  0.0836  2.5719
```

Ensemble means are now **identical**, observations agree, and the correlation is
+0.9889 against +0.8149 — the same sign and the same story. The residual SSR gap
is principled and documented: spread-skill differences the members exactly, while
compare/skill still reconstructs the increment spread from aggregate mean/std via
the variance difference. It is no longer the 2.37-vs-5.91 contradiction it was.

Tests: `TestSpreadSkillSharedGrid` (5 cases) pins that the endpoint reads the
member grid rather than the native tables, snaps off-grid clicks, reports
`n_members` as the ensemble size and not members × cells, and returns empty
rather than erroring when a cell has no members. 156 backend + 22 frontend pass;
`metrics.py` stays at 100%.

### Still open

`regridded_forecast` is left in place, untouched, so the old and new numbers can
be compared. Once you are satisfied, it can be dropped. The wind member grid was
regridded the same way (u and v separately, combined as √(u²+v²) per member,
since the combination is not linear and cannot be done before interpolating).

---

## 14. The ERA5 wind truth field is not the same weather — Critical (2026-08-13)

Chasing an apparent wind bias (forecast ~13 m/s against ~8 m/s observed at one
point) turned up something worse than a bias. **There is no wind bias.** The
domain means agree closely — AIFS 4.45 m/s against ERA5 4.25 m/s at fh 0, a
+0.19 m/s difference. What is wrong is that the two fields describe *different
weather*, so every wind verification score in the app is currently meaningless.

### Evidence

**1. The models agree with each other, not with the truth field.** Wind speed on
the shared grid:

```
       AIFS-GEFS   AIFS-ERA5   GEFS-ERA5
fh  0     0.951       0.435       0.424
fh  6     0.956       0.565       0.562
fh 12     0.954       0.631       0.658
fh 18     0.937       0.526       0.538
```

Two independently developed models agree at 0.95. Both agree with ERA5 at half
that. When independent forecasts agree with each other and disagree with the
verification field, the verification field is the outlier.

**2. The lead-time pattern is backwards.** Agreement with ERA5 is *worst* at
fh 0 (0.435) and improves to fh 12 (0.631). At analysis time a forecast should
match the analysis most closely and decay from there. This is the opposite.

**3. Separating the static pattern from the weather.** Decomposing each field
into its time mean and its anomaly:

```
time-mean fields (land/sea contrast, climatology):  corr = 0.616
anomalies (the actual weather), pooled            :  corr = 0.029
```

The agreement that exists is entirely geography — winds are stronger over water
in both fields. The weather itself is uncorrelated.

**4. No alignment error explains it.** Every candidate was tested and rejected:

```
spatial shift scan, dlat/dlon in +/-2 deg  -> best is (0,0), no improvement
N-S flip, E-W flip, both                   -> all worse than direct
transpose (the grid is 81x81, so a         -> -0.075, far worse
  transposed array fails silently)
time shift, dh in -12..+12 h, anomalies    -> flat at ~0.02 everywhere,
  (UKMO hourly, 24 lead times, 1521 cells)    best +1 h at 0.024
```

**5. It is specific to wind.** The same anomaly test on precipitation against
IMERG gives a coherent structure — monotone through zero, peaking at 0.174 —
where wind is flat noise. Precipitation truth was separately confirmed by the
48 h water budget matching observations to 1.8% (finding 12). The IMERG field is
sound; the ERA5 wind field is not.

**6. The component signature.** At 37.0 N 72.25 W, fh 0, all 50 AIFS members
agree on u = -17.9 m/s (spread 1.94) while ERA5 has u = +0.70 m/s. The v
components nearly match (-4.19 against -4.34). Both AIFS and GEFS anticorrelate
with ERA5 on u (-0.31, -0.26) and weakly correlate on v (+0.46, +0.37) — the
same signature in both models, which again points at the shared truth field.

### What this means

Magnitudes are plausible, the field is spatially smooth, and the land/sea
pattern is right, which is exactly why this was invisible: wind verification
*looks* reasonable and is entirely uninformative. Every wind number — bias, MAE,
RMSE, SSR, CSI, POD, FAR — is computed against a field that is not the weather
being forecast. The low wind SSRs (0.14-0.48) are a symptom: the "error" term is
dominated by the mismatch, so the ensemble looks far more overconfident than it is.

Precipitation is unaffected and remains trustworthy.

### Not fixed here

This is a data-acquisition problem, not a code one — most likely the ERA5 pull
fetched a different date (or a different year) from the 2025-09-08 00Z forecast
run, since the labels would still read as requested. It needs the ERA5 download
re-run and checked against the forecast valid times before wind verification
means anything. Flagged rather than patched: no code change can recover the
right field, and silently suppressing the wind panels is the user's call.

### Secondary observation — superseded, see finding 15

An earlier draft of this section reported that the precipitation anomaly test
"peaked at dh = -4 h" and suggested UKMO's hourly records might be labelled with
the start of their valid hour. **That reading was an artefact of the anomaly
convention used** and is withdrawn. That scan removed each cell's *temporal*
mean, which measures timing at a fixed point and is dominated by intermittency.
Under the standard verification view — per-hour spatial anomalies, 6-hourly mean
rates — the picture is:

```
model vs obs        dh=0     best
  AIFS              0.522    0.597 at -3 h
  UKMO              0.527    0.576 at -3 h
```

Both models shift together and the improvement is ~14%, not the five-fold effect
the earlier view implied. UKMO's labelling is not the cause: it tracks AIFS at
0.84 and observations at 0.53, which is a healthy, correctly-labelled model. The
residual ~3 h preference is shared by both models and may be a real sub-window
timing signal or an artefact of the observation record boundary; it is not worth
acting on without a second case.

The IMERG record does begin exactly 4.0 h before the run initialises
(2025-09-07 20:00 against a 00Z init), which would also be explained by the
download deliberately including lookback for the accumulation windows. Given the
weak correlation evidence above, that benign explanation is the more likely one.

---

## 15. GEFS precipitation correlates with nothing — Critical (2026-08-13)

Found while checking whether UKMO's hourly precipitation was mislabelled. It was
not — but GEFS turned out to have the same signature as the ERA5 wind field in
finding 14.

Six-hourly mean precipitation rate on the shared grid, per-hour spatial
anomalies, lead times 6/12/18/24 h:

```
model vs model (no observations involved)
  AIFS - UKMO :  0.8425
  AIFS - GEFS :  0.0563
  GEFS - UKMO :  0.0164

model vs observations, by applied shift
    dh      AIFS      GEFS      UKMO
    -6    0.5702    0.0111    0.5488
    -4    0.5913    0.0315    0.5505
    -3    0.5973    0.0273    0.5757
    -2    0.5730    0.0291    0.5586
    +0    0.5220    0.0327    0.5267
    +2    0.4844    0.0330    0.4921
```

AIFS and UKMO agree strongly with each other (0.84) and verify sensibly against
IMERG (~0.53). GEFS agrees with neither model, and with the observations at no
lag. The bucket convention is not the explanation — the test was repeated
treating the `h % 6 == 0` records as independent 3-hour buckets differenced
against the `h-3` record, and GEFS stayed flat at ~0.03 either way:

```
  current (divide by own window)          peak dh=-1  corr=0.0357
  differenced (independent 3 h buckets)   peak dh=+2  corr=0.0351
```

### What this means

This retrospectively explains GEFS's poor region scores, which had been read as
GEFS simply being the weaker model:

```
             bias      mae      csi      fss
  AIFS    -0.2141   0.6741   0.6595   0.8988
  GEFS    -0.6236   0.8874   0.1396   0.3072
  UKMO     0.0207   0.9405   0.5701   0.8454
```

A CSI of 0.14 and FSS of 0.31 against 0.66/0.90 and 0.57/0.85 is not a model
being worse — it is a model being scored against weather it never forecast.

As with finding 14 the magnitudes are plausible (GEFS domain-mean rate sits
between AIFS and UKMO), the field is spatially smooth, and nothing looks wrong
until it is correlated against anything else.

### Ingest investigation (2026-08-13)

Everything structural was ruled out, and the fault is isolated to the
precipitation *variable* — not the GEFS pipeline, which is otherwise sound.

**GEFS wind is excellent.** On the shared grid, GEFS `wind_u_10m` against AIFS:

```
  fh 6  0.9568      fh 12  0.9539      fh 18  0.9333
```

Same downloader, same run, same grid, same members — so the cycle, the
georeferencing, the member assembly and the regridding are all correct. Whatever
is wrong is specific to precipitation.

**The bucket convention is correct — now positively verified.** GEFS's own field
correlated against itself across lead times shows a distinctive pairing:

```
        3     6     9    12    15    18    21    24
fh3   1.00  0.89  0.29  0.26  0.25  0.29  0.41  0.41
fh6   0.89  1.00  0.62  0.58  0.46  0.45  0.41  0.42
fh9   0.29  0.62  1.00  0.98  0.76  0.67  0.35  0.31
fh12  0.26  0.58  0.98  1.00  0.85  0.77  0.42  0.38
fh15  0.25  0.46  0.76  0.85  1.00  0.98  0.67  0.59
fh18  0.29  0.45  0.67  0.77  0.98  1.00  0.79  0.70
fh21  0.41  0.41  0.35  0.42  0.67  0.79  1.00  0.97
fh24  0.41  0.42  0.31  0.38  0.59  0.70  0.97  1.00
```

Adjacent pairs (3,6), (9,12), (15,18), (21,24) sit at 0.89-0.98 while UKMO's
matrix decays smoothly with no pairing. That is exactly the NCEP signature: the
`h % 6 == 0` record is the 6-hour bucket *containing* the preceding 3-hour one.
`_precip_period_hours` handles this correctly. Finding 2's convention is
confirmed, not merely assumed.

**Also ruled out.** Member scrambling — the 30 members agree with each other at
0.67-0.83, so the ensemble is correctly assembled. Grid truncation — the 34-row
latitude axis seen at fh 12 is sparsification of dry cells, and GEFS precipitation
does reach 45.0 N at other hours. Latitude compression — no affine lat mapping
recovers agreement. A different cycle — GEFS was correlated against AIFS at every
pairing of lead times from 6 to 72 h and no offset produces a diagonal. Corruption
— the field is spatially smooth (lag-1 autocorrelation 0.877) and temporally
coherent.

**What remains.** The GEFS downloader (`~/Documents/AFW/GEFS/gefs_dwnld.py`)
defines two different precipitation products:

```python
'precipitation': {
    'f000_f240': {'var_name': 'Total_precipitation_surface_3_Hour_Accumulation_ens', ...},
    'f246_f384': {'var_name': 'Total_precipitation_surface_6_Hour_Accumulation_ens', ...},
}
```

but the extraction does not select on `var_name`. It substring-matches the
variable attributes:

```python
search_patterns = {'tp': ['precipitation', 'precip'], ...}
```

A GEFS file carries several fields matching "precip" — total, convective, and
rate products among them — and this takes whichever the loop reaches first. Wind
is unaffected because its patterns (`'u-component'`, `'eastward'`) are far more
specific. This is the only precipitation-specific step that differs from the wind
path, and it is the prime suspect.

**A caveat, stated because it does not fit.** Shifting the GEFS field +5.0 deg in
longitude raises agreement with AIFS from about 0 to 0.42-0.50 at fh 12/18/24
(the same shift destroys UKMO's 0.72 agreement, so it is not a generic artefact).
But it makes fh 6 *worse* (0.21 unshifted against 0.10 shifted) and does not
consistently improve agreement with the observations. A true georeferencing error
would apply uniformly at every lead time, so this is recorded as unexplained
rather than claimed as the cause.

### Next step

Re-extract GEFS precipitation selecting on the exact `var_name` instead of the
substring match, and confirm which field the current data actually holds before
trusting any GEFS precipitation score.

### Not fixed here

Same class of problem as finding 14 and the same remedy: a data-acquisition
issue that no code change can repair. The GEFS precipitation ingest needs
re-checking against the 2025-09-08 00Z run — most likely the wrong cycle, date,
or member set. Until then GEFS precipitation scores should not be presented as
model skill.

### Method note

Two anomaly conventions were used across findings 14 and 15 and they answer
different questions:

- **per-cell temporal anomaly** (remove each cell's time mean) — measures whether
  a model gets the timing right at a fixed location. Dominated by intermittency
  for precipitation and easy to over-read.
- **per-hour spatial anomaly** (remove each hour's domain mean) — the standard
  verification view, measures whether the spatial pattern is right at each time.

Conclusions here use the second. Where the two disagree, prefer the second, and
never quote a peak shift from the first without checking it against the second —
that mistake produced the withdrawn "-4 h UKMO labelling" note in finding 14.

---

## 15 — RETRACTED (2026-08-13). GEFS precipitation is a real forecast.

**The finding above is withdrawn. The analysis behind it was invalid.**

Every correlation in finding 15 was a raw Pearson coefficient on a precipitation
field. Precipitation is heavily skewed, and the GEFS field is far peakier than
the others:

```
  fh=12       n     mean   median      p90       max   frac>0.1
  AIFS     1681   0.6131   0.1989   1.9793    5.5931      0.581
  GEFS     1394   0.3090   0.0200   0.6844   22.4422      0.324
  UKMO     1521   0.4739   0.0243   1.4814    8.1143      0.415
  OBS      2025   0.4109   0.0000   1.1329   16.9650      0.277
```

GEFS has a median of 0.02 and a maximum of 22.4. Raw Pearson on such a field is
dominated by a handful of extreme cells, and if those are displaced by even one
gridpoint the coefficient collapses to zero while the field is broadly right.
That is what happened.

Under **rank (Spearman) correlation**, which is the appropriate statistic here,
GEFS has clear and physically sensible skill:

```
          GEFS vs AIFS   GEFS vs UKMO   GEFS vs OBS
  fh  6       0.427          0.436         0.381
  fh 12       0.376          0.371         0.308
  fh 18       0.251          0.145         0.163
  fh 24       0.236          0.140           -
```

Skill decays with lead time, exactly as a real forecast does. The earlier claim
that GEFS "correlates with nothing at any lag" was an artefact of the statistic,
not a property of the data.

**What stands from the investigation.** The structural checks were sound and are
still worth keeping: the NCEP bucket convention is positively confirmed by the
(3,6), (9,12), (15,18), (21,24) pairing at 0.89-0.98; the 30 members are
correctly assembled; the grid is right; there is no cycle offset. The 34-row
latitude axis is sparsification, not truncation.

**What was wrong.** The conclusion that GEFS precipitation is unusable, the
inference that the `gefs_dwnld.py` substring variable match had produced the
wrong field, and the "+5 degree longitude shift" curiosity — that shift is just
what happens when you slide a peaky field across a broad one and re-fit a
Pearson coefficient, which is why it was inconsistent across lead times.

GEFS does verify worse than UKMO here (Spearman against observations 0.38/0.31/0.16
against UKMO's 0.67/0.69/0.75). That is a statement about model performance on
this case, not a data fault.

### Method correction

**Never use raw Pearson correlation on precipitation.** Use Spearman, or Pearson
on log1p, or a categorical score at a threshold. This mistake also produced the
withdrawn "-4 h UKMO labelling" note in finding 14, so it has now caused two
false findings. Before reporting any correlation-based conclusion:

1. Check the skew of both fields (median against max).
2. Run the same statistic on a **known-good pair** as a control — model against
   model is the natural one. If the control also collapses, the statistic is at
   fault, not the data.

## 14 — qualified after the same review

Finding 14 was re-checked against the same failure mode and **holds**, but its
strongest claim is softened.

Wind speed is only mildly skewed (max/median 5.5 for AIFS, 2.7 for ERA5) and
rank correlation tracks Pearson closely, so the finding is not a skew artefact:

```
  fh   pair            pearson   spearman
   0   AIFS vs GEFS      0.951      0.872
   0   AIFS vs ERA5      0.435      0.417
   6   AIFS vs GEFS      0.956      0.948
   6   AIFS vs ERA5      0.565      0.643
  12   AIFS vs GEFS      0.954      0.924
  12   AIFS vs ERA5      0.631      0.667
```

The control finding 15 lacked was then run — the same per-cell temporal anomaly
view applied to a known-good pair:

```
  UKMO vs ERA5 anomalies (24 times, 1521 cells) : pearson 0.017  spearman 0.084
  UKMO vs AIFS anomalies (model against model)  : pearson 0.813  spearman 0.805
```

The anomaly view registers 0.81 between two models, so its near-zero reading
against ERA5 is a real signal rather than a broken statistic.

**Softened claim.** "Every wind verification number is meaningless" was too
strong. Per-hour spatial correlation between UKMO and ERA5 averages 0.54
(Spearman 0.55), so wind verification is not noise — the fields agree on
large-scale structure. What they do not share is temporal evolution. Bias and
MAE against ERA5 are defensible; anything reading hour-to-hour change, and the
low SSRs in particular, should not be trusted until the field is confirmed.

The model-model anomaly control used 4 time samples against 24 for the ERA5
comparison, which favours the control. The gap is large enough that this does not
overturn the conclusion, but a like-for-like sample would make it airtight.

---

## 14 — re-verified with rank anomalies and matched controls (2026-08-13)

The qualification above noted that the model-model control used 4 time samples
against 24 for the ERA5 comparison, which favoured the control. That objection is
now removed. Per-cell **temporal Spearman** — rank-correlate each cell's own time
series, then average over cells — run on identical times, identical cells and the
identical statistic for every pair:

```
  3-hourly, times [0,3,6,9,12,15,18,21], 8 samples/cell
    UKMO vs GEFS  (control)   mean rho=+0.663   cells=1521   frac>0=0.94
    UKMO vs ERA5              mean rho=+0.100   cells=1521   frac>0=0.57
    GEFS vs ERA5              mean rho=+0.113   cells=1681   frac>0=0.58

  6-hourly, times [0,6,12,18], 4 samples/cell
    AIFS vs UKMO  (control)   mean rho=+0.693   cells=1521   frac>0=0.93
    AIFS vs GEFS  (control)   mean rho=+0.605   cells=1681   frac>0=0.89
    AIFS vs ERA5              mean rho=+0.112   cells=1681   frac>0=0.54
    UKMO vs ERA5              mean rho=+0.149   cells=1521   frac>0=0.57

  hourly, times 0..23, 24 samples/cell
    UKMO vs ERA5              mean rho=+0.082   cells=1521   frac>0=0.56
```

Three independent models agree with each other at 0.60-0.69 and every one of them
agrees with ERA5 at 0.08-0.15, at every sampling cadence tested. `frac>0` is the
plainest reading: 89-94% of cells agree in sign between any two models, against
54-58% versus ERA5 — barely distinguishable from a coin flip.

This is rank-based, so the skew that invalidated finding 15 cannot apply; the
controls are matched sample-for-sample; and the result is stable across three
cadences and four model pairs. **Finding 14 stands as re-verified.**

The conclusion remains the qualified one: the ERA5 wind field shares large-scale
spatial structure with the forecasts (per-hour spatial Spearman ~0.55) but not
their temporal evolution. Bias and MAE against it are defensible. Anything that
reads hour-to-hour change is not, and the low wind SSRs (0.14-0.48) in particular
should be treated as an artefact of the mismatch rather than as ensemble
overconfidence, until the field is confirmed against its source.

---

## 14 — interpretation withdrawn (2026-08-13). Data confirmed correct.

**The ERA5 wind data has been confirmed correct by its owner, and the conclusion
that it was "different weather" is withdrawn.** The GEFS precipitation data was
likewise confirmed correct, and finding 15 was already retracted on its own
merits (a bad statistic — see the method correction there).

### The inference that was wrong

The argument was: three independent models agree with each other at 0.60-0.69 on
temporal evolution but with ERA5 at 0.08-0.15, therefore ERA5 is the outlier.

That inference is weaker than it was presented. **Models cluster.** AIFS, GEFS
and UKMO initialise from similar global analyses and share resolution limits and
physics lineages, so their errors are correlated with each other. Agreeing with
one another more closely than with an independent truth field is an expected
property of a model ensemble, not evidence that the truth field is wrong. A known
phenomenon was treated as a smoking gun.

The same applies to the "worst at fh 0" observation. At analysis time the models
are closest to their own shared initial state, which is not ERA5; there is no
requirement that a model's own 10 m wind at fh 0 match an independent reanalysis
closely, particularly for a near-surface field that depends heavily on the
boundary-layer scheme and the land-surface representation, where models differ
most from one another and from a reanalysis.

### What the measurement still says

The numbers themselves are not in dispute and are reproducible:

```
  per-cell temporal Spearman, matched times and cells
    model vs model   +0.60 to +0.69   (frac of cells with rho>0: 0.89-0.94)
    model vs ERA5    +0.08 to +0.15   (frac: 0.54-0.58)
  per-hour spatial Spearman, UKMO vs ERA5:  ~0.55
```

Read against correct data, this is a **verification result about the models, not
a fault in the truth**: on this case the three ensembles reproduce ERA5's
large-scale wind pattern (spatial ~0.55) but have little cell-level skill at the
hour-to-hour evolution of 10 m wind. That is a legitimate and interesting finding
in its own right, and it is what the Comparison and Analysis tabs are for.

It also means the low wind SSRs (0.14-0.48) should be read at face value: spread
is small relative to error because the error is genuinely large, i.e. the
ensembles are overconfident for 10 m wind on this case. The earlier advice to
distrust them was based on the withdrawn interpretation.

### Standing guidance, revised

Wind verification numbers are **usable**. Nothing in the pipeline needs changing
and no code fix follows from this finding.

### What this cost, and the lesson

Two findings in this audit (14's interpretation and 15 entirely) over-read a
statistic into a data-quality accusation. The method correction under finding 15
covers the statistical half (never raw Pearson on skewed fields; always control
against a known-good pair). The second half is inferential:

**Model-vs-model agreement is not a truth test.** When forecasts agree with each
other and disagree with an observation, the observation is only one of the
candidate explanations, and usually not the first one to reach for. Before
concluding that reference data is wrong, the burden is external evidence about
the data itself — provenance, timestamps, source parameters — not a correlation
gap, however large.

---

## 16. GEFS precipitation was double-converted — Critical (2026-08-13)

Confirmed by the data owner: **the "scaled" JSON export converted precipitation
to mm/h before loading.** The loader folders name it —
`json_data_aifs_ensemble_scaled` and `json_data_gefs_ensemble_scaled`, against
`json_data_ukmo_ensemble` for UKMO, which is native mm/h and was never scaled.

`_precip_rate_series` then divided GEFS by its bucket length a second time, so
every GEFS precipitation number was 3-6x too low. Domain mean over 0-24 h:

```
  divided by bucket length (before)  0.053 mm/h
  read as stored                     0.235 mm/h
  observed                           0.387 mm/h
  UKMO, never scaled                 0.418 mm/h
```

This is the same defect as finding 12, which caught AIFS. AIFS is cumulative so
it surfaced as "the increment is already a rate"; GEFS is bucketed so it surfaces
as "the stored value is already a rate". One cause, two shapes. The two are now
expressed as one concept, `RATE_STORED_PRECIP_MODELS = {'AIFS', 'GEFS'}`, and
`_increment_divisor` returns 1 for both.

The record's own window is untouched — `_precip_period_hours` still reports 3 or
6 h for GEFS — because that is the window observations are averaged over. Only
the divisor changed.

Effect on the region suite (32-40N, 80-72W, 6-18 h, threshold 1 mm/6h):

```
              bias      mae      csi      fss
  GEFS before  -0.6236   0.8874   0.1396   0.3072
  GEFS after   -0.0053   1.0620   0.2886   0.5426
```

Bias goes from strongly dry to essentially unbiased. MAE and RMSE rise because
the values are several times larger, so absolute errors scale with them: GEFS now
gets the domain total about right but places it less well than AIFS or UKMO,
which its CSI and FSS already said.

This also removes the last support for the retracted finding 15. GEFS's weak
scores were part statistic (raw Pearson on a skewed field) and part this
double conversion — not a broken data feed.

### The 3-hour records — resolved, and my inference corrected

I first guessed the export divided everything by 6 and proposed doubling the 3 h
records. **That was wrong in both directions.** The export script was later found
at `Data_convert_weave/"aifs react.py"` and states the factors outright:

```python
scale_json_files(..., scale_factor=6, model_name='AIFS')
scale_json_files(..., scale_factor=3, model_name='GEFS')
```

One fixed factor per model, applied to every record whatever window it covers.
UKMO never passes through it — `React.py` converts its native
`total_rainfall_rate` (m/s) straight to mm/h with x3.6e6.

So the factor is right where it happens to match the record, and wrong where it
does not:

| model | export ÷ | record window | stored is | correction |
|---|---|---|---|---|
| AIFS | 6 | 6 h throughout | correct | none (÷1) |
| GEFS | 3 | 3 h buckets | correct | none (÷1) |
| GEFS | 3 | 6 h buckets | **2x too high** | halve (÷2) |

The 6 h buckets needed halving; the 3 h ones needed nothing. `_increment_divisor`
is now `period / SCALED_EXPORT_DIVISOR_HOURS[model]`, which yields 1, 1 and 2 for
those three rows and leaves unscaled models dividing by their own window.

GEFS domain mean by lead time, before and after:

```
  before  0.163  0.287  0.147  0.309  0.163  0.333  0.169  0.313   7 of 7 jumps >1.6x
  after   0.163  0.144  0.147  0.154  0.163  0.167  0.169  0.156   0 of 7
```

Domain mean 0.158 mm/h against 0.387 observed and 0.418 for UKMO. Region suite
(32-40N, 80-72W, 6-18 h, threshold 1 mm/6h):

```
              bias      mae      csi      fss
  AIFS       -0.1684   0.5273   0.6603   0.8994
  GEFS       -0.2292   0.8946   0.2426   0.4799
  UKMO       +0.0216   0.6925   0.5713   0.8541
```

GEFS remains the driest and weakest of the three on this case — bias -0.23, CSI
0.24 — but that is now a model result on a 0.5 degree grid rather than an
arithmetic artefact, and it is a long way from the -0.62 bias and 0.14 CSI it
showed while being double-converted.

**Lesson, third of three.** Findings 14 and 15 were over-read statistics. This one
was an over-read *name*: I inferred a numeric factor from the word "scaled" in a
folder path, and the fingerprint in the data was consistent with two different
factors. Both readings flattened the alternation; only the source could say
which. Do not infer a constant from a filename when the code that produced it can
be found — and if it cannot be found, say the number is unknown rather than
picking the one that fits.

### Confirmed against the raw source files

The 3 h / 6 h interleaving was originally inferred from a containment signature in
the loaded data. It has since been verified directly against the untouched GRIB
derivatives for the same 2025-09-08 00Z run — `test_data/` (f003) and
`PRESENTATIONS/` (f006):

```
  f003: step=3.0   valid_time = init + 3 h
  f006: step=6.0   valid_time = init + 6 h

  WEAVE domain, all 30 members, 50,430 values
    f003 mean 1.0240    f006 mean 1.9645    ratio 1.92
    f006 >= f003 at 95.3% of points
    f006 <  f003 at 2,388 points, largest shortfall 0.07 mm (GRIB packing)
```

An independent 3-6 h bucket would sit below the 0-3 h one at about half of
points, with large negatives. `f006` contains `f003`. The interleaving is real,
and `_increment_divisor` halving the `h%6==0` records is correct.

**The filename is the trap.** Both files are named
`Total_precipitation_surface_3_Hour_Accumulation_ens_...`, because that is the
variable label the download config applies across `f000-f240`. It is accurate for
f003 and wrong for f006, which holds a 6-hour accumulation. `gefs_dwnld.py`
declares both products and `gefs_processing_readme_txt.txt` says plainly
"Total precipitation (3h and 6h accumulations)" — the directory listing is the
only thing that suggests otherwise, and it is what misleads.

Anyone re-checking this should read `step` from the file rather than trusting the
name.

### All three conventions verified against raw source files

Extending the f003/f006 check to every raw file on disk. Nothing below is
inferred from the loaded database — it is read from the untouched files.

**GEFS — the full reset cycle**, 2025-09-08 00Z, steps f003 to f015:

```
  pair          later >= earlier    ratio   reading
  f003 -> f006          95.3%       1.92    contains the earlier (bucket open)
  f006 -> f009          48.6%       0.50    independent (bucket reset)
  f009 -> f012          96.8%       2.04    contains the earlier (bucket open)
  f012 -> f015          58.9%       0.56    independent (bucket reset)
```

Reset every 6 h exactly as `_precip_period_hours` assumes. The implied
non-overlapping 3-hour amounts are smooth and physical, which the raw records
themselves are not:

```
   0-3h = f003         1.0240 mm
   3-6h = f006 - f003  0.9406
   6-9h = f009         0.9852
  9-12h = f012 - f009  1.0286
 12-15h = f015         1.1365
```

**AIFS — cumulative, in mm.** `units = 'kg m**-2'`; step 0 h is identically zero
and step 42 h has a mean of 12.60 mm, i.e. 0.300 mm/h averaged since
initialisation. Confirms both the cumulative handling and finding 12: the export
divides by 6, so differencing two stored records gives
`(C(h) - C(h-6))/6`, the mean rate over that window.

**UKMO — a rate, in `m s-1`.** `standard_name = 'rainfall_rate'`,
`long_name = 'Total rainfall rate (stratiform + convective)'`. React.py's
`x 3 600 000` is therefore correct (1000 mm/m x 3600 s/h), giving a 0.081 mm/h
mean and a 139 mm/h maximum on the file checked. This was worth confirming: had
the units been `kg m-2 s-1` the factor should have been 3600, and every UKMO
value would have been 1000x too wet.

No code change follows — every convention the metric layer implements is
confirmed. The verification is recorded so the next person does not have to
re-derive it from statistics, and because the GEFS filenames actively mislead.

### Independently re-verified on a second run — 2025-09-16 00Z

The GEFS convention and the correction derived from it were both established on
the 2025-09-08 00Z case. A second, unrelated run was later supplied in
`test_data/` — steps f003 to f024, eight consecutive records covering four
complete reset cycles, on a date that never entered the database.

Containment, globally (259,920 points x 30 members per step):

```
  pair          later >= earlier   ratio   reading
  f003 -> f006          91.1%      2.01    contains the earlier (bucket open)
  f006 -> f009          56.0%      0.50    independent (reset)
  f009 -> f012          94.3%      1.99    contains the earlier (bucket open)
  f012 -> f015          60.0%      0.50    independent (reset)
  f015 -> f018          95.1%      2.04    contains the earlier (bucket open)
  f018 -> f021          59.4%      0.51    independent (reset)
  f021 -> f024          95.0%      1.98    contains the earlier (bucket open)
```

Four cycles, alternating without exception, and the ratios land on 2.00 and 0.50
almost exactly — a 0-6 h total is twice the 0-3 h total it contains, and the next
3 h bucket is about half the 0-6 h total it follows.

The implied non-overlapping 3-hour amounts are smooth where the stored records
are not:

```
  amounts  0.419  0.317  0.367  0.402  0.393  0.387  0.407  0.348   0 of 7 jumps >1.6x
  raw records as stored                                             7 of 7
```

**End to end through the real code path.** Simulating the export (÷3 flat) and
running `_precip_rate_series('GEFS', ...)` against the mean rate computed straight
from the raw files:

```
    fh  window   raw mm   stored  code rate  true rate       err
     3      3h   0.4188   0.1396     0.1396     0.1396   0.00e+00
     6      6h   0.7358   0.2453     0.1226     0.1226   0.00e+00
     9      3h   0.3670   0.1223     0.1223     0.1223   0.00e+00
    12      6h   0.7687   0.2562     0.1281     0.1281   0.00e+00
    15      3h   0.3929   0.1310     0.1310     0.1310   0.00e+00
    18      6h   0.7799   0.2600     0.1300     0.1300   0.00e+00
    21      3h   0.4074   0.1358     0.1358     0.1358   0.00e+00
    24      6h   0.7548   0.2516     0.1258     0.1258   0.00e+00
```

Exact to the last digit at every step. This closes the one weakness left in
finding 16: the correction was derived from a single case, and it now demonstrably
generalises to an independent run.

---

## 17. One verification window for every model — High (2026-08-13)

Each model was scored over whatever window it happened to emit: UKMO 1 h, GEFS
3 or 6 h, AIFS 6 h. The observation was averaged over the matching window, so
every model's own score was internally sound — but a threshold then asked a
different question of each.

A short window keeps peaks that a long one averages away. Same UKMO data, same
threshold, only the averaging window changed:

```
  thr mm/6h   1 h records   6 h means   ratio
          1        0.382       0.421     0.91
          5        0.180       0.197     0.91
         10        0.079       0.069     1.14
         25        0.010       0.006     1.64
```

At a high bar the hourly records exceeded 1.64x more often, purely from cadence.
Comparing UKMO's CSI against AIFS's was comparing two different questions.

### Fix

`_rebin_to_common_window()` re-expresses every model's rate series on a single
`COMMON_VERIFICATION_WINDOW_HOURS = 6` before anything is scored. Six hours is
the coarsest native window in the set (AIFS throughout, GEFS at `h%6==0`), so it
is the only one every model can supply without inventing data.

- A record already spanning 6 h passes through untouched.
- Shorter records are combined, **weighted by their own periods**, and only when
  they tile the window exactly. A partly covered window is dropped rather than
  averaged — the same trap `_obs_window_mean` guards against on the observation
  side.
- Where GEFS emits both a 3 h bucket and the 6 h bucket containing it, the 6 h
  one wins; blending them would double-count.
- Combined records report no spread. The spread of a mean is not the mean of
  spreads, and the members needed to do it properly are not in scope there;
  `None` is skipped by SSR/CRPS/Brier rather than fabricated.

Applied to every path that scores against observations — the region/spatial
pairs, `/api/compare/skill`, `/api/compare/categorical`,
`/api/categorical-metrics` and the region categorical path. **Not** applied to
display paths: `/api/compare/timeseries` and the map keep native cadence, because
there the detail is the point.

Wind is untouched. It is an instantaneous rate rather than an accumulation, so
there is no window to reconcile.

### It also removed a double-count

GEFS's records overlap by construction — the `h%6==0` bucket contains the
`h%6==3` one before it — so scoring every record pooled hours 0-3, 6-9, 12-15 and
18-21 **twice**:

```
  before   fh3 (0,3]   fh6 (0,6]   fh9 (6,9]   fh12 (6,12]   fh15 (12,15] ...
           4 overlapping pairs, 36 h of coverage over a 24 h span

  after    fh6 (0,6]   fh12 (6,12]   fh18 (12,18]   fh24 (18,24]
           0 overlaps, 24 h over 24 h — the windows tile exactly
```

Twelve of every twenty-four hours were counted double, weighting those hours'
contribution to bias, MAE and the contingency counts. It was invisible because
each record was individually paired with its own correct observation window —
nothing was wrong per record, only in the pooling.

Re-binning removes it as a side effect: the wider record wins, the narrower one
it contains is dropped, and what survives tiles the span exactly. AIFS and UKMO
never had the problem, their records being non-overlapping already.

### Result

```
  n_cells   AIFS 289   GEFS 289   UKMO 289      <- identical samples

              bias      mae      csi      pod      far      fss
  AIFS      -0.1684   0.5273   0.6603   0.9067   0.2915   0.8994
  GEFS      -0.2220   0.8279   0.2449   0.4067   0.6189   0.4844
  UKMO      +0.0392   0.6057   0.6637   0.8409   0.2410   0.8890
```

Every model now contributes the same number of samples, which is the clearest
sign the window is shared. UKMO's CSI rises from 0.5713 to 0.6637 and its FSS
from 0.8541 to 0.8890 — its hourly peaks are no longer crossing the bar for
reasons of cadence — putting it alongside AIFS, where two good models belong.
GEFS remains the weakest on this case.

Tests: `TestCommonVerificationWindow` (9 cases) pins pass-through, weighted
combination, the wider-record-wins rule, partial-cover rejection, spread
suppression, and that a steady rate reported by an hourly, a bucketed and a
6-hourly model comes out identical. `metrics.py` stays at 100%; 167 backend tests
pass.

---

## Standing decision: GEFS precipitation will not be re-exported

The metric-layer correction in finding 16 was written as a compensation for the
old fixed-factor export, on the assumption a re-export would eventually retire
it. **That is not going to happen** — decided 2026-08-13 — so it is permanent.
`SCALED_EXPORT_DIVISOR_HOURS = {'AIFS': 6.0, 'GEFS': 3.0}` is not debt awaiting
cleanup; it is the description of how the loaded data was produced.

### The footgun, and why it is now the code's problem

That constant describes the **data**, not this code, so it goes stale the moment
anyone re-exports — and a stale value corrects twice with no visible symptom.
Precipitation would simply be wrong by a factor of two, and every score built on
it along with it. A comment saying "remember to update this" is not a safeguard.

The two conventions leave different fingerprints, so the code reads the answer
back out of the data and compares:

```
  flat divisor      stored_6h / stored_3h = A(0-6) / A(0-3)       ~ 2.0
  per-window        stored_6h / stored_3h = A(0-6) / (2 * A(0-3)) ~ 1.0
```

The 6 h accumulation contains the 3 h one and runs about twice it, so a flat
divisor cancels out of the ratio while a per-window one halves it. On the loaded
data the median ratio is **1.938** over 6,498 cell-cycles (quartiles 1.55-2.45)
— unambiguously the flat convention.

`_infer_scaled_export_divisor()` turns that into a verdict, and
`/api/health` reports it:

```json
  "precip_export_convention": {
    "model": "GEFS", "declared_divisor_h": 3.0,
    "inferred_divisor_h": 3.0, "n_samples": 20000, "status": "ok"
  }
```

Flip the constant without re-exporting and the check says so, in the terms
needed to fix it:

```
  status  "MISMATCH"
  detail  "the data looks like a divisor of 3.0 h but the code assumes 6.0 h.
           If GEFS was re-exported, set SCALED_EXPORT_DIVISOR_HOURS['GEFS'] to
           3.0; until then its precipitation is off by a factor of 2."
```

It returns `indeterminate` rather than a guess when the sample is thin or the
median falls between the two predictions — a signal to look, not to pick.

### What remains true

- `Data_convert_weave/"aifs react.py"` is fixed to divide by each record's own
  window, and applies to any **future** ingest. The original is kept at
  `"aifs react.py.orig-backup"`.
- If that script is ever run and the database reloaded, the constant must move to
  `{'AIFS': 6.0, 'GEFS': 6.0}`. Forgetting no longer produces silently wrong
  numbers — the health check fails first and names the fix.
- The numbers in the app today are correct either way. This was only ever about
  which layer owns the correction, and now about making the ownership verifiable.
