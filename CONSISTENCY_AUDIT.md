# Consistency audit — results of phases 1–4

Run 2026-08-19 against `CONSISTENCY_AUDIT_PLAN.md`. **Survey only — nothing was
fixed.** The plan is explicit that each phase changes what the later fixes should
be, so findings are classified and left.

Method: the metric matrix and the wind/precipitation table were built by
**calling every endpoint** against the fixture database rather than by reading
lists, because a metric can be in a registry and still return nothing. Page flow
and chart grammar were read from the components.

Headline: **the gap the plan expected to find is not the one that is there.** It
predicted that wind/precipitation parity was "where gaps hide, because wind was
added second" — phase 2 found no capability gap at all. The real gap is in phase 1
and it is larger than the `fss` discrepancy the plan named.

---

## Phase 1 — Metric parity

Availability by surface, as returned by the endpoints. "map" means a per-cell
field exists, not just a number.

| metric | Analysis point | Analysis region | Comparison point | Comparison region |
|---|---|---|---|---|
| `ssr` (single lead time) | ✓ per hour | ✓ map | — | — |
| `ssr_agg` | — | ✓ map | ✓ as `mean_ssr` | ✓ |
| `correlation` | ✓ | ✓ map | ✓ | ✓ |
| `bias` | **—** | ✓ map | ✓ | ✓ |
| `mae` | **—** | ✓ map | ✓ | ✓ |
| `rmse` | **—** | ✓ map | ✓ | ✓ |
| `crps` | **—** | ✓ map | ✓ as `mean_crps` | ✓ |
| `csi` / `pod` / `far` | ✓ | ✓ map | ✓ | ✓ |
| `brier` | ✓ as `brier_score` | ✓ map + `brier_score` | ✓ | ✓ |
| `fss` | ✓ (needs `box_cells` > 1) | ✓ number, no map | ✓ | ✓ number, no map |
| `fbi` | ✓ | ✓ | **—** | **—** |
| `composite_confidence` | ✓ | ✓ | **—** | **—** |

### 1a. Analysis point has no accuracy metrics — **accidental · FIXED**

The biggest finding of the survey, and not one the plan anticipated. At a point,
Analysis offers spread-skill (`ssr`, `correlation`) and the categorical suite —
but **no `bias`, `mae`, `rmse` or `crps`**. Comparison point has all four.

So "how wrong is this forecast, here?" is answerable in one tab and not the other,
for the same click on the same map.

**Fixed**, but not the way this entry first proposed. Wiring in
`/api/compare/skill` would have made the panel self-contradictory, because that
endpoint turned out to be **the last scored path still reading an aggregate
spread** — the member-grid migration missed it. (Not because that spread is
inflated: `regridded_forecast_ens.std_dev` equals the members' sample spread
exactly. It is because a cumulative model's increment spread has to be
approximated from stored totals, and because re-binning discards the spread
altogether — see NEXT_STEPS.md §3b, corrected 2026-08-20.) On the loaded run the two point
panels reported SSRs up to 31% apart for the same cell and lead time (1.3712
against 1.7959 at +12 h). So:

1. `/api/compare/skill` moved onto `_member_cases_by_cell` like everything else,
   which also gives UKMO precipitation an SSR and CRPS at a point for the first
   time — the aggregate path had none to give.
2. Both point endpoints now share `_point_case_record` and `_point_summary`, so
   they cannot drift in shape or in estimator.
3. `/api/spread-skill` gained the `summary` block, and the Analysis panel reads
   bias, MAE, RMSE and CRPS straight from it — same request, same cases as the
   spread numbers beside them, so there is no way for the two rows to disagree.

Verified at 34.50/−75.50: both panels report ssr_agg 3.28, correlation 0.1084,
bias 0.3099, MAE 0.3789, RMSE 0.445, CRPS 0.3738.

One more thing fell out of it: the Analysis panel computed its own "Mean SSR" as
the **mean of the per-hour ratios**, which is precisely the estimator the backend
avoids (E[X/Y] ≠ E[X]/E[Y], and one near-zero error drags the mean to the clamp).
It now shows the backend's pooled `ssr_agg` under the same label Comparison uses.

### 1b. The `fss` gap is real but narrower than the plan states — **deliberate · DOCUMENTED**

The plan said `fss` is "in the Comparison region registry, not the Analysis one".
Analysis region *does* report FSS, through `/api/region-categorical-metrics`; what
it lacks is FSS in the region **metric explorer** (`REGION_METRICS` in
`AnalysisTab.jsx`), the list that drives the bars and maps.

And FSS has **no map on either side** — correctly, since it is a property of a
whole field at a lead time and has no per-cell value. `COMPARE_REGION_NO_CELL_VALUE`
already encodes that. So the honest statement is: FSS is available in all four
surfaces, is never a map, and is reached through a different panel in Analysis
than in Comparison. Worth documenting rather than fixing.

**Documented** at `SPATIAL_METRIC_REGISTRY` (which says why `fss` is absent from
it, alongside the existing note on `COMPARE_REGION_NO_CELL_VALUE`) and in the
README's metrics table, which now has a "Map?" column and states the rule: FSS
compares the *fraction* of exceedances in a neighbourhood against the observed
fraction, so its value belongs to a field at a lead time, not to a cell.

### 1c. One metric, three key names — **accidental · FIXED**

| quantity | Analysis | Comparison point | Comparison region |
|---|---|---|---|
| Brier | `brier_score` | `brier` | `brier` |
| CRPS | — | `mean_crps` | `crps` |
| aggregate SSR | — | `mean_ssr` | `ssr_agg` |

Same number, three names depending on which endpoint you ask.

**Fixed.** `brier_score` → `brier`, `mean_crps` → `crps`, `mean_ssr` → `ssr_agg`.
The last was more than a naming tidy: `mean_ssr` is computed as
mean(σ²)/mean(err²), *deliberately not* the mean of per-case ratios — the code
comment says so explicitly — so the key and its "Mean SSR" label both claimed the
one thing it is not. It now carries the registry name for the estimator it
actually uses, and the point summary and the region bars finally agree on both
the key and the label ("SSR (aggregated)").

### 1d. `fbi` and `composite_confidence` are Analysis-only — **undecided · DOCUMENTED**

This entry first guessed "deliberate: summary devices for a single model, and
Comparison arguably needs none". Looking for the reason in the code found **none**,
and the guess does not hold up — both are ordinary per-model scores and either
would compare across models perfectly well. On the evidence the gap is incidental,
not decided.

**Documented as such**, in `categorical_metrics_endpoint`'s docstring and the
README, rather than dressed up as a decision. The one substantive consideration
recorded there: Composite Confidence is a weighted blend, and the weights are a
judgement call, so ranking models by it is a different kind of claim from ranking
them by CSI. FBI carries no such caveat and is the cheaper of the two to add.

### 1e. `ssr` at a single lead time is Analysis-only — **deliberate**

As the plan predicted. It drives the live map overlay, and region views aggregate
over a lead-time range, which is what `ssr_agg` is for.

---

## Phase 2 — Wind / precipitation parity

**No capability gap.** Every metric, both spatial map families, and the A−B
difference map work for both variables. Tested by calling each one twice.

| capability | precipitation | wind |
|---|---|---|
| all 11 Analysis region maps | ✓ | ✓ |
| all 11 Comparison region metrics | ✓ | ✓ |
| Comparison point categorical incl. FSS | ✓ | ✓ |
| spatial agreement map | ✓ | ✓ |
| A−B difference map | ✓ | ✓ |
| CRPS, Brier | ✓ | ✓ |

Two cells come back empty **in the fixture** for physical reasons, not gaps:
precipitation `correlation` (its spread is flat in lead time by design, so there is
nothing to correlate) and wind `pod` (no observed event exceeds the test threshold,
so POD is undefined). Both are correct behaviour and both are already pinned by
tests.

Every variable-conditional branch in the frontend is a **threshold default, a
threshold-parameter name, or a unit label** — 13 in `AnalysisTab.jsx`, 7 in `ComparisonTab.jsx` (the plan recorded
13 and 6; Comparison gained one, a threshold-key selector). Not one forks a
capability.
The legitimate forks the plan listed all hold: thresholds are `mm/6h` versus `m/s`,
wind is exempt from the common 6 h window, and wind has no accumulation semantics.

The plan's remaining phase-2 question — whether the two variables' units are
described with equal care — passes. Both axes are labelled explicitly
(`Wind Speed (m/s)`, `Precipitation (mm/hr)`), and `threshold_info` carries an
explicit `unit` for both variables on every endpoint that takes a threshold.

---

## Phase 3 — Page flow

### 3a. Analysis has two "Point | Region" toggles — **accidental · FIXED**

| | control | scope | treatment |
|---|---|---|---|
| Analysis, tab level | `AnalysisTab.jsx:322` | the whole tab | icon + label (`MapPin` / `Map`) |
| Analysis, verification panel | `AnalysisTab.jsx:673` | that panel only (`catMode`) | text only |
| Comparison | `ComparisonTab.jsx:941` | the whole tab (`mode`) | text only |

Two controls with the same two words in one tab, scoping different things and
styled differently. A user who learns Comparison's single toggle meets two in
Analysis, one of which looks like the one they know and does something narrower.

**Fixed by removing the ambiguity, not the control.** Checking first showed the
nested toggle is *not* a duplicate: tab-Region mode is only the spatial metric
maps, so `catMode = 'region'` is the sole route to the region-scored categorical
numbers — FSS, FBI, the composite and the contingency counts over a box. Deleting
it would have cost capability.

So it now names the areas instead of repeating the mode: **"Score over: This cell |
Drawn region"**, with an `aria-pressed` state. Nothing moved, nothing was lost, and
the two words no longer appear twice in one tab meaning two things.

### 3b. The scored area has two names — **accidental · FIXED**

Analysis calls it **"Scored area"** (`AnalysisTab.jsx:724`), Comparison calls it
**"Verification box"** (`ComparisonTab.jsx:1765`). Same concept, both good names,
only one should survive. **Fixed:** Comparison now says "Scored area" too, which
also matches the backend's `scored_area` key.

### 3c. Loading and empty states are per-panel in Analysis, shared in Comparison — **FIXED**

Comparison routes its panels through one `⏳ Loading…` treatment
(`ComparisonTab.jsx:176`) and one "No results yet" empty state. Analysis writes a
bespoke string per panel ("⏳ Loading spread-skill data…", "No forecast data
available for this location", "Spread-skill data unavailable"). Cosmetic, but it is
why the two tabs feel different before any data arrives.

**Fixed.** `ui/PanelState.jsx` now holds the three states a panel can be in before
it has a result — `LoadingState`, `EmptyState`, `NoDataNote` — and both tabs use
them: eight sites in Analysis, and Comparison's local `Spinner` and two
"No results yet" blocks. Comparison's `Spinner` is kept as a one-line alias so its
six call sites read unchanged.

What is shared is the **treatment, not the wording**. Every message that carries
information still carries it — including the observation-coverage line, which
moved into `NoDataNote`'s `detail` slot rather than being flattened away. "No
score here" and "no observations reach this lead time" have to stay
distinguishable.

### 3d. Observation-coverage states now agree — **resolved**

The plan asked whether both tabs distinguish "no data" from "no observations at
this lead time". They do, as of the observation-coverage work: both render
`obs_warning`, Comparison renders per-model `warnings`, the Analysis spread-skill
empty state names the record's extent, and the timeline marks where verification
stops. Nothing to do.

---

## Phase 4 — Visualisation grammar

| what | Analysis | Comparison | same? |
|---|---|---|---|
| metric over lead time | `<Line>` in `ComposedChart` | `LineChart` | **yes** |
| several models at one lead time | n/a (single model) | grouped `BarChart` | n/a |
| spatial field | Cartopy PNG + canvas overlay | Cartopy PNG | yes |
| distribution / spread | `AreaChart` cone (±1σ, ±2σ) | none | Analysis only |
| diverging quantity | none | `domain={[min(0,v), max(0,v)]}` | n/a |

Both tabs already follow the plan's first rule (one metric over lead time → line).
My initial read of the chart-type counts suggested otherwise — Analysis has no
`LineChart` component at all — but it draws lines inside `ComposedChart`, so the
mark is the same. Worth recording because the same wrong inference is easy to make
twice.

### 4a. Bounded scores get a fixed axis in Analysis and an auto axis in Comparison — **accidental · FIXED**

The plan's own rule: "Bounded scores (CSI, POD, FAR, FSS ∈ [0,1]) → a fixed 0–1
axis, so panels are comparable at a glance and a bad score looks bad."

- Analysis pins `domain={[0, 1]}` on three score charts (`AnalysisTab.jsx:976`,
  `1022`, `1082`).
- Comparison's categorical-by-lead-time chart sets **no domain**
  (`ComparisonTab.jsx:1854`), so Recharts auto-scales.

A CSI of 0.05 therefore fills the panel in Comparison and sits on the floor in
Analysis. This is the clearest phase-4 finding and the cheapest to fix.

**Fixed.** The metric descriptors now carry `bounded: true` for CSI, POD, FAR, FSS
and Brier, and both shared chart components honour it — `AggregateBar` swaps its
include-zero domain for `[0, 1]`, and the categorical line chart pins the same.
Verified in the browser: all five now run 0.00 → 1.00. Unbounded metrics (SSR,
CRPS, bias, MAE, RMSE) keep auto-scaling, which is correct for them.

Note that Comparison's `normalizeScales` toggle also produces a `[0, 1]` axis
(`ComparisonTab.jsx:1477`) but is a different thing: it normalises **raw forecast
values** in the time-series so models on different scales can share an axis. It is
off by default and unrelated to bounded scores.

---

---

# Phase 6 — Text correctness

Run 2026-08-20. **Seven findings, all fixed**, plus two things that are true as
written but need a decision rather than an edit. Phase 5 (typography) is still
unrun.

The prior held: the plan predicted a sweep would find more wrong strings, and it
did. Every finding below is a string that contradicted the code it described —
in each case the code had been corrected and the string left behind.

Method: the plan's two greps for unit labels and literal JSX text, then each
string checked against `metrics.py` and `flask_api.py` rather than against
another string. Where a claim was about behaviour it was checked by calling the
endpoint, not by reading the code — 6.3 is the one that needed it.

### 6.1 Four spatial metrics label wind maps in mm/h — **accidental · FIXED**

`bias`, `mae`, `rmse` and `crps` inherit the variable's unit. Their text was
written for precipitation and rendered for both variables:

| where | string | shown for |
|---|---|---|
| `constants.js` descriptions | `Mean \|error\| across lead times (mm/h)` | wind and precipitation |
| `constants.js` legends, 12 bands | `< 0.2 mm/h — Excellent` | wind and precipitation |
| `flask_api.py` `PLOT_STYLE_REGISTRY` | `MAE (mm/h)` | drawn into the PNG **and** its title |

Exactly the defect the fixture layer found in `/api/compare/skill`
(`units: 'mm/h'` hard-coded), in three more places — and the backend one is worse,
because it is burned into an image a user can download and pass on.

**Fixed** by making the unit a property of the variable in both layers:
`VALUE_UNITS` + `withUnit()` in `constants.js`, `VALUE_UNITS` +
`_metric_cbar_label()` in `flask_api.py`. Verified by rendering the same 35
points as both variables: the title and colourbar read `MAE (m/s)` for wind and
`MAE (mm/h)` for precipitation.

Tests pin both directions and, more usefully, the invariant: no registry entry
may contain a literal unit, no dimensionless metric may gain one, and no
`{unit}` placeholder may reach a label unsubstituted.

### 6.2 SSR is described as a variance ratio — **accidental · FIXED**

`METRICS_AUDIT.md` finding 7 changed SSR from a variance ratio to the
conventional σ/RMSE, because the interpretation bands were always the σ/RMSE
ones. The code moved; three descriptions did not:

- `ssr`: "Ratio of ensemble variance to squared forecast error"
- `ssr_agg`: "mean(σ²) / mean(ε²)" — **missing the square root**
- the README's `ssr` vs `ssr_agg` note, repeating the same formula

The app therefore contradicted itself: `AboutModal`'s glossary said "spread
against error", which is right, next to a panel saying variance over squared
error, which is not. And the bands are named for the σ/RMSE convention, so the
description as written could not be reconciled with the legend beside it.

**Fixed** to `σ / |ε|` and `√(mean(σ²) / mean(ε²))`, with the README stating the
square root explicitly and why it is there.

### 6.3 The Analysis badge tells users the two tabs legitimately disagree — **accidental · FIXED**

The spread-skill badge carried: *"Analysis verifies individual ensemble members at
the nearest **native** grid cell. The Comparison tab uses the **regridded ensemble
mean and spread**, so its values for the same metric can differ."*

Both halves are now false. The member grid is on the shared 0.5° grid, not a
native one; and `/api/compare/skill` was moved onto `_member_cases_by_cell` in
1a, so the two panels share an estimator and a summary. The string survived the
migration that existed to remove the difference it describes — and it sends a
user looking for a discrepancy that is no longer there.

Re-measured rather than assumed, at 36.0/−75.5 over +6/12/18h:

| | bias | mae | rmse | crps | correlation | ssr_agg |
|---|---|---|---|---|---|---|
| Analysis point | 0.0628 | 0.0918 | 0.1013 | 0.0546 | 0.9889 | 1.2331 |
| Comparison point | 0.0628 | 0.0918 | 0.1013 | 0.0546 | 0.9889 | 1.2331 |

**Fixed** to state the shared grid and the agreement, hedged only on lead-time
range, which is the one thing the two tabs can genuinely differ on because
Comparison has its own hour controls.

### 6.4 The timeline denies observations that exist — **accidental · FIXED**

The hatched track read *"No observations beyond +18h — nothing to verify
against"*. Observations run to **+19.5h**; verification stops at +18h because a
precipitation record needs its whole 6 h window observed. The distinction is the
entire point of `record_end_lead_hours` vs `last_verifiable_hour`, and the other
two surfaces that report coverage state it correctly — this one flattened them
into a claim about the data that was not true.

**Fixed**, and the two cases are worded apart: precipitation gets "observations
run to +19.5h, and a score needs its whole window observed"; wind, being
instantaneous, gets "the observation record ends there" — the window clause is
meaningless for it. Caught only by reading the rendered tooltip in both variables;
the first fix said "whole window" for wind too.

### 6.5 "Every model is scored over the same six hours" omits wind — **accidental · FIXED**

An `AboutModal` section heading and its paragraph, stated without qualification.
Wind is exempt — instantaneous, no window to reconcile — and that is a standing
decision, not an oversight. The README's verification-conventions bullet
("Everything is compared in mm/h") had the same shape.

**Fixed**: the heading now says "Every precipitation model", with the exemption
stated in its own sentence.

### 6.6 One unit, two spellings — **cosmetic · FIXED**

`mm/h` in `constants.js`, `ComparisonTab` and every API response; `mm/hr` in the
Analysis axis label and all five map legends. Both true, one product.
**Standardised on `mm/h`**, which is what the API returns in `units`, so a label
and the response behind it can no longer look like two different quantities.

### 6.7 UKMO's grid is quoted as one number — **accidental · FIXED**

`AboutModal` said 0.1875°; the grid is **0.1875° × 0.28125°** and is anisotropic,
which is exactly why its latitudes collapsed under a 0.25° snap and its
longitudes did not (defect 6). **Fixed** to state both.

---

## Two things phase 6 found that are not text bugs

Recorded rather than edited, because both need a decision and one needs a
meteorologist.

### The point categorical metrics use different estimators in the two tabs — **open**

Analysis pools CSI/POD/FAR over the **clicked cell alone**; `box_cells` only
feeds FSS, and the control says so. Comparison pools the same metrics over the
**whole `box_cells`×`box_cells` box** (default 9×9), and its caption says so too.
Both are honest about themselves; neither says the other exists, so the same
point at the same threshold gives two different CSIs with no visible reason.

This is a phase-1 finding that phase 1 missed, because the matrix asked whether a
metric is *available* in each surface and not which estimator produced it — the
same blind spot as `METRICS_AUDIT.md` finding 8. **A cross-reference was added to
Comparison's caption** so the difference is at least visible; which estimator is
right is a real decision and is left open.

### The metric colour bands are calibrated for precipitation — **open**

`< 0.2 — Excellent` through `> 1.0 — Poor` are mm/h judgements, and the same
numbers are applied to m/s. The backend norms have the same problem: MAE and RMSE
cap at `vmax=2`, and a wind MAE map over 35–37 N, 77–74 W runs to **2.18 m/s**, so
most of the domain saturates into one flat colour and the map stops discriminating.

Setting wind bands is a judgement about what a good wind MAE is, and this project's
own method lesson is not to guess a constant. So the panel now **says whose scale
it is** ("Band edges and verdicts are calibrated for precipitation, not for wind")
and the decision is left to someone who can make it.

---

## What phase 6 checked and found correct

Worth recording so it is not re-swept:

- **Every direction claim.** All 30-odd "higher/lower is better", "0 = perfect"
  and "ideal ≈ 1" strings match `metrics.py`, including the ones that are easy to
  get backwards (FAR lower, FBI ideal 1, bias 0). SSR's five-tier verdict in
  `AnalysisTab` is correct in the σ/RMSE convention — under 1 is overconfident —
  and agrees with the backend colourbar band for band.
- **The scope claims in `AboutModal`**, which are the app's most load-bearing
  prose. Checked against the code, not assumed: `box_cells` really does leave the
  contingency table on the centre cell, FSS really is `None` at one cell, and a
  partially observed window really is rejected.
- **Threshold labels**, already variable-aware everywhere (phase 2 found this too).
- **Backend `obs_warning` strings**, all honest about what was and was not found.

The one tonal wart left alone: two empty states tell the user to "ingest more
data", which addresses an operator rather than a reader. Not false, so not phase 6.

## Suggested sequencing, by risk

The plan says to budget by risk, and the findings sort cleanly:

1. ~~**Safe and mechanical** — 1c key names, 3b one name for the scored area, 4a
   the fixed 0–1 axis.~~ **Done 2026-08-19.**
2. ~~**Safe and worth it** — 1d and 1b.~~ **Done 2026-08-20.** 1b's rule is now at
   the registry and in the README; 1d is recorded as *undecided* rather than
   justified, because no reason for it exists. The same pass corrected a claim
   this audit had repeated — that the aggregate spread is inflated — which is true
   of `regridded_forecast` and false of `regridded_forecast_ens`.
3. ~~**A real feature, small** — 1a, accuracy metrics at an Analysis point.~~
   **Done 2026-08-19**, and it was not small: it surfaced one endpoint left behind
   by the member-grid migration and a client-side estimator that disagreed with
   the backend's. "The backend already returns them; this is wiring plus a panel"
   was wrong, and worth remembering as a caution about sizing work from a survey.
4. ~~**Do deliberately or not at all** — 3a the duplicate toggles and 3c the state
   treatments.~~ **Done 2026-08-20**, and deliberately: 3a relabels rather than
   removes, because the "duplicate" turned out to be the only route to the
   region-scored categorical numbers; 3c unifies the treatment while leaving every
   informative message intact. No control moved and no capability changed, which
   is what the plan's warning was about.

**Phases 1–4 and 6 are now closed.** Phase 5 (typography) is the only one left,
and it is the mechanical one.

The guardrail in the plan still applies: `ComparisonTab.jsx` is 2,300 lines and
`AnalysisTab.jsx` is 1,264. Land these as fixes with tests, and decide about
extraction separately.

---

## The pattern across all five phases

Every phase found the same shape of defect, and it is worth naming because it
predicts where the next one is. **Not one finding was a mistake made at the time
it was written.** 1a, 1c, 6.2, 6.3 and 6.4 were all correct when written and were
falsified later by a fix somewhere else — a migration, a renamed key, a corrected
convention. The code moved and the sentence describing it did not.

That is an argument for the tests this phase added, which pin *invariants* rather
than strings: no literal unit in the registry, no dimensionless metric with a
unit, no unsubstituted placeholder. A test on the wording would have to be
rewritten by the same change that breaks the wording, and would therefore never
catch it.
