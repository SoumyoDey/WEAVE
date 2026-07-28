# Plan — Comparison Tab: Point + Region model-comparison analytics

> Feature plan/spec. Self-contained; executable in a fresh session.
> Companion to `SYSTEM_DESIGN_PLAN.md`. Written 2026-07-28.
> Target branch: `p0-reliability` (PR #2). Backend `Data/flask_api.py`,
> frontend `src/components/ComparisonTab.jsx`.

---

## 1. Goal
Bring the Analysis tab's full verification-metric capability into the Comparison
tab, in a **multi-model** form, for **both a point and a region**:
1. Point-based and region-based model-comparison analytics (a mode toggle).
2. Verification-metric comparison across models, per-lead-time **and** aggregate.
3. Spatial (map) comparison of those metrics across models.

## 2. Confirmed design decisions
- **Mode:** add a **Point | Region** toggle (mirror Analysis's `catMode`).
- **Point granularity:** show **per-lead-time charts and an aggregate summary**.
- **Spatial comparison:** provide **both** per-model small-multiples **and**
  model-difference (A − B) maps.
- **Metric suite** (= Analysis spatial set): `ssr_agg`, `correlation`, `bias`,
  `mae`, `rmse`, `crps`, `csi`, `pod`, `far`, `brier`. Point mode may also expose
  FBI / composite from `/api/categorical-metrics`.

## 3. Current state & key leverage (what already exists)
Most of the backend is already in place — build the missing pieces only.
- **`POST /api/compare/skill`** returns, per model: per-hour
  `ssr/crps/bias/mae/rmse/spread/mean_val/obs` in `hours[]`, and aggregates
  `mean_ssr/correlation/mean_crps/bias/mae/rmse` in `summary`. → **Point accuracy/
  calibration comparison is frontend-only.**
- **`POST /api/compare/categorical`** returns per-hour `csi/pod/far/fss` per
  model. → needs only a per-model `summary` (+ optional Brier) added.
- **`GET /api/spatial-metric`** (per-model point list) + **`POST
  /api/spatial-metric-plot`** (Cartopy render) exist. → per-model spatial
  small-multiples are **frontend-only** (loop models).
- **Reuse:** `SPATIAL_METRIC_REGISTRY`, `_fetch_fcst_obs_pairs_spatial`,
  `PLOT_STYLE_REGISTRY` (fixed per-metric color norms ⇒ small-multiples already
  share a scale), the 4-worker Compute-All-Maps throttle, release-conn-before-
  render, and the plot cache.

Comparison tab today: point location (lat/lon); sections = Forecast Comparison,
Skill Verification (SSR/MAE/RMSE), Advanced Metrics (CSI/POD/FAR/FSS), Spatial
Agreement (the only region piece).

---

## 4. Incremental plan
Each increment is independently shippable, verified live (wind + precip + a
precip-regression check), and committed to `p0-reliability`.

### Increment 1 — Structure *(frontend only, low risk)*
- Add `compareMode` state (`'point' | 'region'`) + a Point|Region toggle in the
  config card (mirror Analysis).
- Gate sections: **Point** → Forecast Comparison, Metric comparison, Categorical.
  **Region** → Region-metric comparison, Spatial maps, Spatial Agreement.
- Region mode requires a drawn `selectedRegion` (reuse the existing "no region"
  nudge).
- **Exit:** toggle switches section sets cleanly; existing point features
  unchanged.

### Increment 2 — Point metric comparison *(mostly frontend, small backend add)*
- Render the full `/api/compare/skill` output:
  - **Per-lead-time:** small per-metric line charts (SSR, bias, MAE, RMSE, CRPS),
    one line per model (reuse the Section-5 chart pattern).
  - **Aggregate:** a grouped-bar summary — each metric with a bar per model (from
    `summary`).
- Fold in categorical aggregates: **extend `/api/compare/categorical`** to also
  return a per-model `summary` for CSI/POD/FAR/FSS (+ optional Brier). Additive,
  backward-compatible.
- **Exit:** point-mode values match Analysis point mode for wind + precip.

### Increment 3 — Region aggregate comparison *(new backend, medium risk)*
- **New `POST /api/compare/region-metrics`**: loop `models`; for each metric run
  its `SPATIAL_METRIC_REGISTRY` dispatcher over the bbox and return a **region-mean
  scalar per metric per model**, e.g.
  `{ "AIFS": {"mae":2.1,"bias":-0.3,...}, "GEFS": {...} }`.
  Reuses the existing compute functions; applies the threshold to categorical
  metrics and the hour-range to all.
- API client `fetchComparisonRegionMetrics`; frontend grouped-bar per metric
  across models.
- **Exit:** region-mean per model is sane; precip path un-regressed; a golden test
  covers the aggregation.

### Increment 4 — Spatial small-multiples *(frontend only, low–med risk)*
- Metric picker (the 10). For the chosen metric, loop `selectedModels`:
  `fetchSpatialMetric` → `fetchSpatialMetricPlot` → render a **row of per-model
  Cartopy maps**. Fixed per-metric norms mean the maps already share a scale.
- Reuse the **4-worker throttle** so models × render doesn't burst the pool.
- **Exit:** per-model maps render for a metric with no 500s / pool exhaustion.

### Increment 5 — Spatial difference maps *(new backend, medium risk)*
- **New `POST /api/compare/spatial-diff`**: given model A, model B, a metric, and
  a bbox, compute each model's per-cell metric, subtract at matching grid cells,
  and render a **diverging-colormap PNG** (A − B, centered at 0). Reuse the
  Cartopy render path; release the DB conn before rendering.
- A/B model pickers; render the diff beneath the small-multiples.
- **Exit:** diff map renders with a diverging scale centered at 0; golden test on
  the diff aggregation.

---

## 5. New / changed surface
| Layer | New | Reused / extended |
|---|---|---|
| Backend | `POST /api/compare/region-metrics`, `POST /api/compare/spatial-diff`; add per-model `summary` to `/api/compare/categorical` | `compare/skill`, `spatial-metric`, `spatial-metric-plot`, `SPATIAL_METRIC_REGISTRY`, throttle, plot cache, release-conn-before-render |
| API client (`src/api/comparisonApi.js`) | `fetchComparisonRegionMetrics`, `fetchComparisonSpatialDiff` | `fetchComparisonSkill/Categorical`, `fetchSpatialMetric/Plot` |
| Frontend (`ComparisonTab.jsx`) | `compareMode` toggle; point per-lead-time charts + aggregate bars; region aggregate bars; spatial small-multiples + diff | Section-5 chart pattern, spatial-agreement layout, `MODEL_COLORS` |
| Tests (`Data/test_metrics.py`) | golden tests for region-metrics aggregation + spatial-diff | existing monkeypatch / FakeCursor harness |

---

## 6. Decisions (open considerations, resolved — no dangling gaps)
1. **Point categorical uses a neighborhood; accuracy uses the exact cell.** Keep
   this existing convention; label the categorical section with its FSS-window
   size so the difference is explicit. *(No code fork.)*
2. **Difference maps compare two models at a time.** Provide **A/B model pickers**
   defaulting to the first two `selectedModels`; the small-multiples still show
   all selected models. *(Decided: A/B pickers.)*
3. **Grid alignment for diffs & region aggregates** reuses the existing rounded-
   key match; reuse the match-rate logging and, if the match rate is ~0, surface
   a "grid misalignment / no overlap" message instead of a blank/zero map.
4. **Shared color scale for small-multiples:** most metrics already use fixed
   per-metric norms in `PLOT_STYLE_REGISTRY`, so per-model maps are directly
   comparable; no extra work. Diff maps use a symmetric diverging norm computed
   from the data's max abs difference.
5. **Metric applicability:** categorical metrics (`csi/pod/far/brier`) require a
   threshold input; all metrics take the lead-time range. The region-metrics and
   diff endpoints accept `threshold_mm_6h`/`threshold_ms` and `hour_min/hour_max`
   like the existing spatial endpoints.
6. **Wind:** all new paths inherit the `√(u²+v²)` forecast-speed handling via the
   existing `_fcst_speed_sql`/`_ensemble_speed_rows` helpers and `accum_h=1` for
   wind. The `|mean vector|` aggregate approximation and domain-aggregate FSS
   carry over (documented, point SSR remains exact).
7. **Empty/insufficient data:** every new view shows an explicit "no data for this
   location/region/threshold" state (consistent with the existing tabs) rather
   than a blank panel.

---

## 7. Effort & sequencing
~3–5 days total. Order **1 → 2 → 3 → 4 → 5**; each committed to `p0-reliability`
(PR #2) after live verification (wind + precip, precip-regression check, backend
+ frontend tests green). No dependency reversals: 2 depends on 1; 3–5 depend on 1.

## 8. Fresh-session kickoff
> Continue the Comparison-tab feature in WEAVE_v3 (branch `p0-reliability`).
> Read `COMPARISON_TAB_PLAN.md` and `SYSTEM_DESIGN_PLAN.md`. Start at Increment 1
> (Point/Region toggle in `ComparisonTab.jsx`), then 2–5. Backend
> `~/miniconda3/envs/afw/bin/python Data/flask_api.py` (:5000, DB `weave_weather`);
> frontend `npm start` (:3000). Data is US East Coast, single init 2025-09-08 —
> use coastal points/regions. Verify each increment live (wind + precip) and run
> `cd Data && python -m pytest -q`. Don't trigger cybersecurity safeguards.
