# Consistency audit — Analysis and Comparison tabs

A plan, not a result. Written 2026-08-14 while the metric audit
(`METRICS_AUDIT.md`) was closing, to cover what that one did not: whether the two
tabs *behave* like one product. The metric audit asked whether each number is
right. This asks whether the same question, asked in two places, is presented the
same way — and whether anything is silently missing.

Run it in the order below. Each phase produces a table of findings, and only
then a fix. Resist fixing while surveying: the first three phases are cheap and
each one changes what the later fixes should be.

---

## Phase 1 — Metric parity

**Question: can you get the same number in both tabs, and if not, is that deliberate?**

A concrete gap is already visible from the registries:

```
Analysis region (SPATIAL_METRIC_REGISTRY)
  bias brier correlation crps csi far mae pod rmse ssr ssr_agg
Comparison region (COMPARE_REGION_METRICS)
  bias brier correlation crps csi far mae pod rmse     ssr_agg  fss
```

- **`fss` is in Comparison but not Analysis region.** Analysis point mode has FSS
  (via `box_cells`), so a user finds it at a point, loses it over a region, and
  finds it again in the other tab. Either add it or state why not.
- **`ssr` (single lead time) is Analysis-only**, which is defensible — it drives
  the live map overlay — but it should be named as such rather than look absent.

Build the full matrix before changing anything:

| metric | Analysis point | Analysis region | Comparison point | Comparison region | deliberate? |
|---|---|---|---|---|---|

Fill it by reading the registries and the tab components, not by clicking. Then
mark each gap **deliberate** (with the reason, which goes in the docs) or
**accidental** (which goes in the backlog). A gap is only a bug once you have
decided it should not exist.

## Phase 2 — Wind / precipitation parity

**Question: is every capability available for both variables, in every context?**

This is where gaps hide, because wind was added second. Static count of
variable-conditional branches today: **13 in `AnalysisTab.jsx`, 6 in
`ComparisonTab.jsx`**. Each is a place behaviour forks, and each is either a real
physical difference or an unfinished feature wearing the same clothes.

Legitimate forks — these should stay, and should be *stated* in the UI:

- Thresholds are `mm/6h` for precipitation and `m/s` for wind.
- Wind is instantaneous, so it is exempt from the common 6-hour verification
  window and from the accumulation semantics entirely.
- Wind has no cumulative or bucketed models, so no differencing.

For every other fork, ask: *would a user reasonably expect this to work for wind?*
Produce a table:

| capability | precipitation | wind | reason for the difference |
|---|---|---|---|

Known items to check specifically: FSS for wind (does a wind neighbourhood score
make sense — probably yes, for gust placement); CRPS and Brier for wind; the
spatial small-multiples and A−B difference map; whether the wind legend and the
precipitation legend describe their units with equal care.

## Phase 3 — Page flow

**Question: does a user who learns one tab already know the other?**

Compare the two side by side and write down the order of: mode toggle, location
input, model selection, lead-time range, threshold, run button, results. Where the
order differs, decide which is right and move the other — **do not** invent a
third order.

Specific things to check:

- Point ↔ region toggles: same control, same place, same words?
- Is there always a visible "what am I looking at" statement (model, variable,
  lead time, scored area)? Analysis and Comparison both grew a scored-area badge;
  confirm they say it the same way.
- Empty and loading states: same treatment, or does one show a spinner and the
  other a blank panel?
- Error and no-data states: after the observation-window fix, both should
  distinguish "no data" from "no observations at this lead time". Verify they do,
  and in the same words.

## Phase 4 — Visualisation grammar

**Question: does the same kind of number get the same kind of chart?**

Write down every chart in both tabs and its encoding:

| what | Analysis | Comparison | same? |
|---|---|---|---|
| metric over lead time | | | |
| metric per model | | | |
| spatial field | | | |
| distribution / spread | | | |

Rules worth adopting, once, and then enforcing:

- One metric over lead time → line. Several models at one lead time → grouped bars.
- Diverging quantities (bias, A−B) → diverging scale centred at zero, always.
- Bounded scores (CSI, POD, FAR, FSS ∈ [0,1]) → a fixed 0–1 axis, so panels are
  comparable at a glance and a bad score looks bad.
- Every spatial panel in a set shares one colour scale, or says loudly that it
  does not.

## Phase 5 — Typography and shared components

**Good news: most of this is already solved and just needs finishing.**

`src/theme.js` exists and both tabs use it — neither `AnalysisTab.jsx` nor
`ComparisonTab.jsx` contains a single inline `fontSize`. The shared primitives in
`src/components/ui/` (`Button`, `Select`, `Toggle`, `SectionHeader`, `Hint`,
`IconButton`) are the vocabulary.

The holdouts still styling themselves inline:

```
SelectionToolbar.jsx   Timeline.jsx   OnboardingTour.jsx   AboutModal.jsx
MetricPanel.jsx        legends/BivariateLegend.jsx   legends/VSUPBoxesLegend.jsx
ui/Select.jsx   ui/SectionHeader.jsx   ui/Button.jsx
```

`MetricPanel.jsx` alone uses four sizes (9, 10, 11, 12 px). The `ui/` files are
the primitives themselves, so inline is expected there — but the sizes they hard-code
should move into `theme.js` as a named scale.

Tasks:

1. Add a type scale to `theme.js` (e.g. `fs.xs / sm / base / lg`, plus weights)
   and a spacing scale if one is not already there.
2. Convert the holdouts, starting with `MetricPanel` since it sits over the map
   and is the most visible.
3. Then grep for `fontSize: '` returning nothing outside `theme.js` and `ui/`.

## Phase 6 — Text correctness

**Question: does every string still tell the truth?**

This audit has already found three user-visible strings that were wrong: the
threshold unit label in `MetricPanel` (said `mm/6h` in wind mode), the README's
accumulation line, and the map legend claiming mm/hr over un-converted data. Assume
there are more.

Sweep every user-visible string and check:

- **Units** — does the label match what the value actually is, for *both* variables?
- **Metric direction** — anywhere "higher is better" or a colour ramp implies a
  direction, does it match `METRICS_AUDIT.md`?
- **Claims about scope** — "at this point" is false if a box was scored;
  "across the region" is false if only matched cells contributed.
- **Tense and certainty** — a forecast score is not a fact about the weather.

Mechanical starting point:

```bash
grep -rnoE ">[A-Z][^<>{]{12,}<" src/components/ | less   # literal JSX text
grep -rn "mm/6h\|mm/h\|mm/hr\|m/s" src/                  # every unit label
```

Cross-check each unit string against `metrics.py`, which is the authority.

---

## Sequencing

Phases 1–4 are survey and produce tables; 5–6 are the work. Do the surveys first
and in order — a parity gap found in Phase 2 may make a Phase 4 chart unnecessary,
and Phase 3 may show that two components should merge rather than be aligned.

Budget the fixes by risk: typography is safe and mechanical, text correctness is
safe and high-value, metric parity may need backend work, and page-flow changes
are the ones most likely to annoy an existing user — do those deliberately or not
at all.

## Guardrail

`ComparisonTab.jsx` is 2308 lines and `AnalysisTab.jsx` is 1251. Any consistency
work will be tempted into a refactor. Keep them separate: land the audit fixes
first, with tests, then decide about extraction. A refactor mixed into a
consistency pass makes both impossible to review.
