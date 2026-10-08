/**
 * What the Comparison tab scores, and how each metric is drawn.
 *
 * Data, not components: which metrics appear in which panel, the reference
 * line each one is read against, how many decimals it carries, and the model
 * colours and record notes that travel with them.
 *
 * Lifted out of `ComparisonTab.jsx` whole (`NEXT_STEPS.md` §59). The tab was
 * 2,373 lines and these 114 were the part with no behaviour in them at all —
 * they describe the panels rather than render them, and keeping them beside
 * 1,900 lines of component made both harder to read. Nothing here changed in
 * the move; the registries are character-for-character what the tab carried.
 */

export const MODEL_COLORS = { AIFS: '#3498db', GEFS: '#e74c3c', UKMO: '#2ecc71' };

// Advanced (categorical) metrics rendered per model over lead time in Section 5.
// CSI, POD, FAR and FSS are all bounded in [0, 1], which is why these charts pin
// the axis: auto-scaling makes a CSI of 0.05 fill the panel and look like skill.
// AnalysisTab has always pinned its score axes; this is Comparison catching up.
export const CAT_METRICS = [
  { key: 'csi', label: 'CSI', hint: 'Critical Success Index · higher is better', bounded: true },
  { key: 'pod', label: 'POD', hint: 'Probability of Detection · higher is better', bounded: true },
  { key: 'far', label: 'FAR', hint: 'False Alarm Ratio · lower is better', bounded: true },
  // FBI is NOT bounded in [0, 1] — it is events forecast over events observed,
  // so 1 is perfect and 2 means twice too many. It takes `refLine: 1` like SSR
  // rather than `bounded`, which would clip every over-forecasting model to the
  // top of the axis and make them look identical.
  //
  // Analysis-only until 2026-10-06 for no recorded reason (§43). It earns its
  // place here specifically: CSI says how wrong a model is, FBI says which
  // *direction*, and two models with equal CSI can be over- and
  // under-forecasting respectively with nothing else on this tab showing it.
  { key: 'fbi', label: 'FBI', hint: 'Frequency Bias · 1 = right number of events', refLine: 1 },
  { key: 'fss', label: 'FSS', hint: 'Fractions Skill Score · higher is better', bounded: true },
];

// Verification metrics carried per lead time by /api/compare/skill.
export const SKILL_METRICS = [
  { key: 'ssr',  label: 'SSR',  hint: 'Spread-Skill Ratio · ideal = 1',   refLine: 1, decimals: 3 },
  { key: 'crps', label: 'CRPS', hint: 'Probabilistic error · lower is better',       decimals: 4 },
  { key: 'bias', label: 'Bias', hint: 'Mean error · 0 is unbiased',        refLine: 0, decimals: 3 },
  { key: 'mae',  label: 'MAE',  hint: 'Mean absolute error · lower is better',       decimals: 3 },
  { key: 'rmse', label: 'RMSE', hint: 'Root mean square error · lower is better',    decimals: 3 },
];

// The same suite aggregated over all verified lead times (skill `summary`).
export const SKILL_SUMMARY_METRICS = [
  { key: 'ssr_agg',     label: 'SSR (aggregated)', hint: 'ideal = 1',      refLine: 1, decimals: 3 },
  { key: 'correlation', label: 'Spread–skill corr.', hint: 'spread vs |error|',       decimals: 3 },
  { key: 'crps',        label: 'CRPS',        hint: 'lower is better',                decimals: 4 },
  { key: 'bias',        label: 'Bias',        hint: '0 is unbiased',       refLine: 0, decimals: 3 },
  { key: 'mae',         label: 'MAE',         hint: 'lower is better',                decimals: 3 },
  { key: 'rmse',        label: 'RMSE',        hint: 'lower is better',                decimals: 3 },
];

// Region-mean metrics from /api/compare/region-metrics, grouped the same way
// the Analysis tab groups its region maps.
export const REGION_METRIC_GROUPS = [
  {
    id: 'calibration', label: 'Calibration', hint: 'Is the ensemble spread reliable?',
    metrics: [
      { key: 'ssr_agg',     label: 'SSR (aggregated)',   hint: 'ideal = 1',         refLine: 1, decimals: 3 },
      { key: 'correlation', label: 'Spread–skill corr.', hint: 'spread vs |error|',             decimals: 3 },
    ],
  },
  {
    id: 'accuracy', label: 'Accuracy vs observations', hint: 'How close is the ensemble mean to obs?',
    metrics: [
      { key: 'bias', label: 'Bias', hint: '0 is unbiased',    refLine: 0, decimals: 3 },
      { key: 'mae',  label: 'MAE',  hint: 'lower is better',              decimals: 3 },
      { key: 'rmse', label: 'RMSE', hint: 'lower is better',              decimals: 3 },
      { key: 'crps', label: 'CRPS', hint: 'lower is better',              decimals: 4 },
    ],
  },
  {
    id: 'categorical', label: 'Categorical', hint: 'Event-based skill for threshold exceedances',
    metrics: [
      { key: 'csi',   label: 'CSI',   hint: 'higher is better', decimals: 3, bounded: true },
      { key: 'pod',   label: 'POD',   hint: 'higher is better', decimals: 3, bounded: true },
      { key: 'far',   label: 'FAR',   hint: 'lower is better',  decimals: 3, bounded: true },
      // Unbounded with an ideal of 1 — see CAT_METRICS above. `noMap` for the
      // same reason as FSS but a different mechanism: at one cell the two
      // counts are each 0 or 1, so a per-cell FBI is only ever 0, 1 or
      // undefined, and the backend has no dispatcher for it (§49).
      { key: 'fbi',   label: 'FBI',   hint: '1 = right number of events',
        decimals: 3, refLine: 1, noMap: true },
      { key: 'brier', label: 'Brier', hint: '0 is perfect',     decimals: 4, bounded: true },
      // FSS is a property of the whole field at a lead time, so it has a
      // region value but no per-cell value — hence no map (noMap).
      { key: 'fss',   label: 'FSS',   hint: 'placement skill · higher is better',
        decimals: 3, noMap: true, bounded: true },
    ],
  },
];

// Metrics offered by the per-model spatial small-multiples. Same suite as the
// region bars; the categorical four need the threshold passed through.
export const SPATIAL_MAP_METRICS = REGION_METRIC_GROUPS.flatMap(g =>
  g.metrics
    .filter(m => !m.noMap)          // no per-cell value → nothing to draw
    .map(m => ({
      key: m.key,
      label: m.label,
      requiresThreshold: g.id === 'categorical',
    })),
);

// Categorical scores pooled over lead times (compare/categorical `summaries`).
export const CAT_SUMMARY_METRICS = [
  { key: 'csi',   label: 'CSI',   hint: 'higher is better', decimals: 3, bounded: true },
  { key: 'pod',   label: 'POD',   hint: 'higher is better', decimals: 3, bounded: true },
  { key: 'far',   label: 'FAR',   hint: 'lower is better',  decimals: 3, bounded: true },
  { key: 'fss',   label: 'FSS',   hint: 'higher is better', decimals: 3, bounded: true },
  { key: 'brier', label: 'Brier', hint: '0 is perfect',     decimals: 4, bounded: true },
];
export const MODEL_NAMES  = ['AIFS', 'GEFS', 'UKMO'];

// Nominal output cadence per model, used only for labelling. The unit
// conversion itself lives in the backend (_precip_rate_series), because the
// three models don't share a convention — AIFS stores a running total since
// init and GEFS alternates 3 h and 6 h buckets, so a single client-side divisor
// was wrong for both. /api/compare/timeseries now returns mm/h directly.
export const PRECIP_RECORD_NOTE = {
  AIFS: '(6h, de-accumulated)',
  GEFS: '(3h/6h buckets)',
  UKMO: '(hourly)',
};
