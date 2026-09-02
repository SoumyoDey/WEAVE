// ── Model registry ────────────────────────────────────────────────────────────
const generateHours = () => {
  const hours = [];
  for (let h = 0; h <= 360; h += 6) hours.push(h);
  return hours;
};
export const ALL_HOURS = generateHours();

export const MODELS = {
  AIFS: { name: 'AIFS', color: '#3498db', hours: ALL_HOURS, hasEnsemble: true, ensembleCount: 50 },
  GEFS: { name: 'GEFS', color: '#e74c3c', hours: ALL_HOURS, hasEnsemble: true, ensembleCount: 30 },
  UKMO: { name: 'UKMO', color: '#2ecc71', hours: ALL_HOURS, hasEnsemble: true, ensembleCount: 18 },
};

// ── Colormaps ─────────────────────────────────────────────────────────────────
export const COLORMAPS = {
  'Default': { name: 'Default', type: 'sequential', colors: ['#FFFFCC', '#C8F0C8', '#A0E6E6', '#70C8D2', '#5098C8', '#3264AA', '#001E6E', '#000050'] },
  'Viridis': { name: 'Viridis', type: 'sequential', colors: ['#440154', '#414487', '#2a788e', '#22a884', '#7ad151', '#fde725'] },
  'Plasma':  { name: 'Plasma',  type: 'sequential', colors: ['#0d0887', '#6a00a8', '#b12a90', '#e16462', '#fca636', '#f0f921'] },
  'Inferno': { name: 'Inferno', type: 'sequential', colors: ['#000004', '#420a68', '#932667', '#dd513a', '#fca50a', '#fcffa4'] },
  'Turbo':   { name: 'Turbo',   type: 'sequential', colors: ['#30123b', '#4662d7', '#36a9e1', '#13eb6b', '#a7fc3c', '#faba39', '#e8443a'] },
  'Cool':    { name: 'Cool',    type: 'sequential', colors: ['#00ffff', '#00d4ff', '#00aaff', '#0080ff', '#0055ff', '#002bff', '#0000ff'] },
  'Warm':    { name: 'Warm',    type: 'sequential', colors: ['#ffff00', '#ffdd00', '#ffbb00', '#ff9900', '#ff7700', '#ff5500', '#ff0000'] },
  'RdYlBu':  { name: 'RdYlBu',  type: 'diverging',  colors: ['#a50026','#d73027','#f46d43','#fdae61','#fee090','#ffffbf','#e0f3f8','#abd9e9','#74add1','#4575b4','#313695'] },
  'Spectral':{ name: 'Spectral',type: 'diverging',  colors: ['#9e0142','#d53e4f','#f46d43','#fdae61','#fee08b','#ffffbf','#e6f598','#abdda4','#66c2a5','#3288bd','#5e4fa2'] },
};

// ── Legacy fixed colour matrices (kept for reference) ─────────────────────────
export const BIVARIATE_COLORS = [
  ['#f0f0f0', '#b4d9cc', '#5dc8a4', '#00916e'],
  ['#e8d9f0', '#a8c8d4', '#4db8a8', '#008878'],
  ['#d4b8e0', '#9cb4c8', '#3da090', '#007060'],
  ['#c8a8d8', '#a0a8c4', '#6898a8', '#3a7890'],
];

export const VSUP_COLORS = [
  ['#eef2e4', '#68d4b0', '#009a78', '#005a48'],
  ['#d8caec', '#82bcc8', '#28a090', '#007068'],
  ['#c0a8e0', '#9ab4c8', '#80b8c4', '#60a8b8'],
  ['#beb0d4', '#bab4d0', '#b8b4d0', '#b6b2ce'],
];

// ── Dynamic colour-matrix builder ─────────────────────────────────────────────
// Returns a 4×4 array of hex strings derived from any COLORMAPS entry.
//   rows = uncertainty level (0 = low → 3 = high)
//   cols = value level      (0 = low → 3 = high)
// vsup = false → Bivariate: value hue preserved, muted by uncertainty
// vsup = true  → VSUP Fan:  value columns also compressed toward mid-point at
//                            high uncertainty (produces near-identical row-3 colours)
export const buildColorMatrix = (colormapName, vsup = false, invertUncertainty = false, N = 4, flip = false) => {
  const colors  = COLORMAPS[colormapName].colors;
  const lerp    = (a, b, t) => Math.round(a + (b - a) * t);
  const toHex   = (r, g, b) =>
    '#' + [r, g, b].map(v => Math.max(0, Math.min(255, v)).toString(16).padStart(2, '0')).join('');
  const cmapRgb = (t) => {
    t = Math.min(Math.max(t, 0), 1);   // guard against out-of-range → colors[undefined] = NaN
    const seg = colors.length - 1;
    const si  = Math.min(Math.floor(t * seg), seg - 1);
    const lt  = t * seg - si;
    const c1  = colors[si], c2 = colors[Math.min(si + 1, seg)];
    return [
      lerp(parseInt(c1.slice(1,3),16), parseInt(c2.slice(1,3),16), lt),
      lerp(parseInt(c1.slice(3,5),16), parseInt(c2.slice(3,5),16), lt),
      lerp(parseInt(c1.slice(5,7),16), parseInt(c2.slice(5,7),16), lt),
    ];
  };
  const neutral  = 185;
  const strength = vsup ? 0.92 : 0.60;
  const size     = N >= 1 ? N : 4;
  const maxIdx   = Math.max(1, size - 1); // prevent division by zero when size=1
  return Array.from({ length: size }, (_, row) => {
    const uncert = invertUncertainty ? (1 - row / maxIdx) : (row / maxIdx);
    return Array.from({ length: size }, (_, col) => {
      const t0 = vsup
        ? (col / maxIdx) * (1 - uncert * strength) + 0.5 * (uncert * strength)
        : col / maxIdx;
      const [r, g, b] = cmapRgb(flip ? 1 - t0 : t0);
      return toHex(
        lerp(r, neutral, uncert * strength * 0.80),
        lerp(g, neutral, uncert * strength * 0.80),
        lerp(b, neutral, uncert * strength * 0.80),
      );
    });
  });
};

// ── VSUP fan levels ───────────────────────────────────────────────────────────
// True Value-Suppressing Uncertainty Palette: the number of distinguishable
// VALUE buckets shrinks as uncertainty rises (a halving tree). `numBuckets` is
// the max fan width (value buckets at the lowest-uncertainty level); 0/1 falls
// back to the classic 8-wide fan. Returns segCounts ordered LOW→HIGH uncertainty
// ([W, W/2, …, 1]); `rings` is the number of uncertainty levels (tree depth).
// Both the map renderer and the fan legend derive their geometry from this so
// they can never disagree.
export const buildVsupLevels = (numBuckets) => {
  const W = numBuckets >= 2 ? numBuckets : 8;
  const segCounts = [];
  for (let w = W; w >= 1; w = Math.floor(w / 2)) {
    segCounts.push(w);
    if (w === 1) break;
  }
  return { segCounts, rings: segCounts.length };
};

// ── Units ─────────────────────────────────────────────────────────────────────
// The unit a value carries. Bias, MAE, RMSE and CRPS inherit it from the
// variable; CSI, POD, FAR, Brier, SSR and correlation are dimensionless.
// Metric text below writes `{unit}` rather than a literal, because these strings
// are rendered for BOTH variables — a hard-coded 'mm/h' labels a wind map in a
// precipitation unit, which is the defect /api/compare/skill used to have.
export const VALUE_UNITS = {
  precipitation: 'mm/h',
  wind:          'm/s',
};

export const withUnit = (text, variable) =>
  typeof text === 'string'
    ? text.replaceAll('{unit}', VALUE_UNITS[variable] ?? '')
    : text;

// ── Where the wind bands come from ────────────────────────────────────────────
// The error-magnitude bands below were calibrated for precipitation in mm/h and
// were being applied unchanged to wind in m/s. Measured per cell over the whole
// domain and all three models on the loaded run (4,883 scored cells per metric),
// that put nearly everything in the worst band:
//
//   metric  mm/h bands        -> share "Poor"      m/s bands        -> share "Poor"
//   MAE     0.2 / 0.5 / 1.0      79.1%             1.0 / 2.0 / 3.5     22.8%
//   RMSE    0.3 / 0.7 / 1.2      78.4%             1.2 / 2.5 / 4.0     21.6%
//   CRPS    0.15 / 0.35 / 0.6    85.6%             0.7 / 1.5 / 2.8     22.0%
//
// Observed distribution, pooled: MAE median 1.79 m/s (p90 4.65), RMSE median
// 2.05 (p90 5.00), CRPS median 1.38 (p90 3.80). The three models are nearly
// identical, so the bands are shared.
//
// **These are absolute judgements, not quantiles.** Exact quartiles would give a
// perfect 25/25/25/25 split, and were deliberately not used: a quantile band
// means "worse than three quarters of this run" while the label says "Poor", so
// every run would report 25% Poor cells however good the forecast was. The edges
// are round numbers anchored on ~1 m/s being a good short-range 10 m wind
// forecast and 3.5+ m/s being genuinely poor; they merely happen to read well
// here, with no band under 19%.
//
// Caveat worth keeping: this run's errors are on the high side, verification
// reaches only +23 h, and the domain is mostly ocean and coastline. Re-deriving
// the edges from a different run would be re-calibrating to its difficulty —
// change them because the meteorology says so, not because a percentage moved.
export const WIND_BAND_BASIS =
  'per-cell, all models, full domain, loaded run 2025-09-08 00Z (n=4883/metric)';

// ── Spatial metric registry ───────────────────────────────────────────────────
// To add a metric: append one entry here. Selector, overlay, legend, and plot
// all read from this array automatically — no other file needs to change.
//
// `colorFn`/`legend` are the precipitation scale. A metric whose bands are
// unit-sensitive also carries `windColorFn`/`windLegend`; read them through
// `metricColorFn` and `metricLegend` below rather than reaching for the keys, so
// a metric without a wind variant falls back instead of rendering nothing.
export const METRIC_CONFIG = [
  {
    key:          'ssr',
    label:        'Spread-Skill Ratio (SSR)',
    shortLabel:   'SSR',
    requiresHour: true,
    requiresThreshold: false,
    // σ / |ε|, NOT the variance ratio the wording used to claim: the code was
    // corrected to the conventional spread-over-error form (METRICS_AUDIT.md
    // finding 7) and this string was left describing the old convention, which
    // mis-states the wings — a variance ratio of 0.5 is a spread/error ratio of
    // 0.71, which the bands below would not call "severely" anything.
    description:  'Ensemble spread over the size of the forecast error (σ / |ε|) at a single lead time. Ideal ≈ 1.',
    colorFn: (v) => {
      if (v == null) return null;
      if (v < 0.5)  return 'rgba(192,0,0,0.82)';
      if (v < 0.8)  return 'rgba(231,76,60,0.82)';
      if (v <= 1.2) return 'rgba(39,174,96,0.82)';
      if (v <= 2.0) return 'rgba(230,126,34,0.82)';
      return 'rgba(52,152,219,0.82)';
    },
    legend: [
      { color: 'rgba(192,0,0,0.82)',   label: '< 0.5  —  Severely underdispersive' },
      { color: 'rgba(231,76,60,0.82)',  label: '0.5 – 0.8  —  Overconfident' },
      { color: 'rgba(39,174,96,0.82)',  label: '0.8 – 1.2  —  Well calibrated ✓' },
      { color: 'rgba(230,126,34,0.82)', label: '1.2 – 2.0  —  Underconfident' },
      { color: 'rgba(52,152,219,0.82)', label: '> 2.0  —  Severely overdispersive' },
    ],
    legendGradient: null,
  },
  {
    key:          'ssr_agg',
    label:        'Spread-Skill Ratio (time-aggregated)',
    shortLabel:   'SSR',
    requiresHour: false,
    requiresThreshold: false,
    description:  'Time-aggregated SSR: √(mean(σ²) / mean(ε²)) across all verified lead times — RMS spread over RMSE. Ideal ≈ 1.',
    colorFn: (v) => {
      if (v == null) return null;
      if (v < 0.5)  return 'rgba(192,0,0,0.82)';
      if (v < 0.8)  return 'rgba(231,76,60,0.82)';
      if (v <= 1.2) return 'rgba(39,174,96,0.82)';
      if (v <= 2.0) return 'rgba(230,126,34,0.82)';
      return 'rgba(52,152,219,0.82)';
    },
    legend: [
      { color: 'rgba(192,0,0,0.82)',   label: '< 0.5  —  Severely underdispersive' },
      { color: 'rgba(231,76,60,0.82)',  label: '0.5 – 0.8  —  Overconfident' },
      { color: 'rgba(39,174,96,0.82)',  label: '0.8 – 1.2  —  Well calibrated ✓' },
      { color: 'rgba(230,126,34,0.82)', label: '1.2 – 2.0  —  Underconfident' },
      { color: 'rgba(52,152,219,0.82)', label: '> 2.0  —  Severely overdispersive' },
    ],
    legendGradient: null,
  },
  {
    key:          'correlation',
    label:        'Spread-Skill Correlation',
    shortLabel:   'Corr.',
    requiresHour: false,
    requiresThreshold: false,
    description:  'Pearson r(σ, |ε|) across verified lead times. Ideal → 1.',
    colorFn: (v) => {
      if (v == null) return null;
      const t = (v + 1) / 2;
      const lerp = (a, b, x) => Math.round(a + (b - a) * x);
      const [r, g, b2] = t <= 0.5
        ? [lerp(52,240,t*2),       lerp(152,240,t*2),      lerp(219,240,t*2)]
        : [lerp(240,231,(t-.5)*2), lerp(240,76,(t-.5)*2),  lerp(240,60,(t-.5)*2)];
      return `rgba(${r},${g},${b2},0.82)`;
    },
    legend: null,
    legendGradient: {
      css:       'linear-gradient(to right, rgba(52,152,219,0.9), rgba(240,240,240,0.9), rgba(231,76,60,0.9))',
      minLabel:  '−1',
      maxLabel:  '+1',
      midLabels: ['Negative', 'No corr.', 'Positive'],
    },
  },
  {
    key:          'bias',
    label:        'Bias (Mean Error)',
    shortLabel:   'Bias',
    requiresHour: false,
    requiresThreshold: false,
    description:  'Ensemble mean minus observation ({unit}). Blue = under-forecast, red = over.',
    colorFn: (v) => {
      if (v == null) return null;
      if (v < -1.0) return 'rgba(41,128,185,0.85)';
      if (v < -0.3) return 'rgba(133,193,233,0.85)';
      if (v <=  0.3) return 'rgba(200,200,200,0.75)';
      if (v <=  1.0) return 'rgba(241,148,138,0.85)';
      return 'rgba(192,57,43,0.85)';
    },
    legend: [
      { color: 'rgba(41,128,185,0.85)',   label: '< −1 {unit}  —  Strong under-forecast' },
      { color: 'rgba(133,193,233,0.85)',  label: '−1 – −0.3  —  Slight under-forecast' },
      { color: 'rgba(200,200,200,0.75)',  label: '−0.3 – 0.3 —  Near-unbiased ✓' },
      { color: 'rgba(241,148,138,0.85)',  label: '0.3 – 1 {unit} — Slight over-forecast' },
      { color: 'rgba(192,57,43,0.85)',    label: '> 1 {unit}  —  Strong over-forecast' },
    ],
    // ±1 m/s is not a "strong" wind bias: measured over the loaded run, 42% of
    // cells fell in the strongest under-forecast band and only 12% read as
    // near-unbiased. |bias| has a median of 1.47 m/s.
    windColorFn: (v) => {
      if (v == null) return null;
      if (v < -2.5)  return 'rgba(41,128,185,0.85)';
      if (v < -0.75) return 'rgba(133,193,233,0.85)';
      if (v <=  0.75) return 'rgba(200,200,200,0.75)';
      if (v <=  2.5)  return 'rgba(241,148,138,0.85)';
      return 'rgba(192,57,43,0.85)';
    },
    windLegend: [
      { color: 'rgba(41,128,185,0.85)',   label: '< −2.5 {unit}  —  Strong under-forecast' },
      { color: 'rgba(133,193,233,0.85)',  label: '−2.5 – −0.75  —  Slight under-forecast' },
      { color: 'rgba(200,200,200,0.75)',  label: '−0.75 – 0.75 —  Near-unbiased ✓' },
      { color: 'rgba(241,148,138,0.85)',  label: '0.75 – 2.5 {unit} — Slight over-forecast' },
      { color: 'rgba(192,57,43,0.85)',    label: '> 2.5 {unit}  —  Strong over-forecast' },
    ],
    legendGradient: null,
  },
  {
    key:          'mae',
    label:        'Mean Absolute Error (MAE)',
    shortLabel:   'MAE',
    requiresHour: false,
    requiresThreshold: false,
    description:  'Mean |error| across lead times ({unit}). Lower = better.',
    colorFn: (v) => {
      if (v == null) return null;
      if (v < 0.2)  return 'rgba(39,174,96,0.82)';
      if (v < 0.5)  return 'rgba(241,196,15,0.82)';
      if (v < 1.0)  return 'rgba(230,126,34,0.82)';
      return 'rgba(192,57,43,0.82)';
    },
    legend: [
      { color: 'rgba(39,174,96,0.82)',  label: '< 0.2 {unit}  —  Excellent' },
      { color: 'rgba(241,196,15,0.82)', label: '0.2 – 0.5  —  Good' },
      { color: 'rgba(230,126,34,0.82)', label: '0.5 – 1.0  —  Moderate' },
      { color: 'rgba(192,57,43,0.82)',  label: '> 1.0 {unit}  —  Poor' },
    ],
    // Wind. Measured over the loaded run, the mm/h edges above put 79% of
    // cells in "Poor" — one colour over most of the map. See WIND_BAND_BASIS.
    windColorFn: (v) => {
      if (v == null) return null;
      if (v < 1.0) return 'rgba(39,174,96,0.82)';
      if (v < 2.0) return 'rgba(241,196,15,0.82)';
      if (v < 3.5) return 'rgba(230,126,34,0.82)';
      return 'rgba(192,57,43,0.82)';
    },
    windLegend: [
      { color: 'rgba(39,174,96,0.82)',  label: '< 1.0 {unit}  —  Excellent' },
      { color: 'rgba(241,196,15,0.82)', label: '1.0 – 2.0  —  Good' },
      { color: 'rgba(230,126,34,0.82)', label: '2.0 – 3.5  —  Moderate' },
      { color: 'rgba(192,57,43,0.82)',  label: '> 3.5 {unit}  —  Poor' },
    ],
    legendGradient: null,
  },
  {
    key:          'rmse',
    label:        'Root Mean Square Error (RMSE)',
    shortLabel:   'RMSE',
    requiresHour: false,
    requiresThreshold: false,
    description:  'RMSE of ensemble mean vs obs ({unit}). Lower = better.',
    colorFn: (v) => {
      if (v == null) return null;
      if (v < 0.3)  return 'rgba(39,174,96,0.82)';
      if (v < 0.7)  return 'rgba(241,196,15,0.82)';
      if (v < 1.2)  return 'rgba(230,126,34,0.82)';
      return 'rgba(192,57,43,0.82)';
    },
    legend: [
      { color: 'rgba(39,174,96,0.82)',  label: '< 0.3 {unit}  —  Excellent' },
      { color: 'rgba(241,196,15,0.82)', label: '0.3 – 0.7  —  Good' },
      { color: 'rgba(230,126,34,0.82)', label: '0.7 – 1.2  —  Moderate' },
      { color: 'rgba(192,57,43,0.82)',  label: '> 1.2 {unit}  —  Poor' },
    ],
    windColorFn: (v) => {
      if (v == null) return null;
      if (v < 1.2) return 'rgba(39,174,96,0.82)';
      if (v < 2.5) return 'rgba(241,196,15,0.82)';
      if (v < 4.0) return 'rgba(230,126,34,0.82)';
      return 'rgba(192,57,43,0.82)';
    },
    windLegend: [
      { color: 'rgba(39,174,96,0.82)',  label: '< 1.2 {unit}  —  Excellent' },
      { color: 'rgba(241,196,15,0.82)', label: '1.2 – 2.5  —  Good' },
      { color: 'rgba(230,126,34,0.82)', label: '2.5 – 4.0  —  Moderate' },
      { color: 'rgba(192,57,43,0.82)',  label: '> 4.0 {unit}  —  Poor' },
    ],
    legendGradient: null,
  },
  {
    key:          'crps',
    label:        'CRPS (Continuous Ranked Probability Score)',
    shortLabel:   'CRPS',
    requiresHour: false,
    requiresThreshold: false,
    description:  'Mean CRPS for the Gaussian forecast distribution, censored at zero for a non-negative variable ({unit}). Lower = better.',
    colorFn: (v) => {
      if (v == null) return null;
      if (v < 0.15) return 'rgba(39,174,96,0.82)';
      if (v < 0.35) return 'rgba(241,196,15,0.82)';
      if (v < 0.6)  return 'rgba(230,126,34,0.82)';
      return 'rgba(192,57,43,0.82)';
    },
    legend: [
      { color: 'rgba(39,174,96,0.82)',  label: '< 0.15 {unit}  —  Excellent' },
      { color: 'rgba(241,196,15,0.82)', label: '0.15 – 0.35  —  Good' },
      { color: 'rgba(230,126,34,0.82)', label: '0.35 – 0.6   —  Moderate' },
      { color: 'rgba(192,57,43,0.82)',  label: '> 0.6 {unit}   —  Poor' },
    ],
    windColorFn: (v) => {
      if (v == null) return null;
      if (v < 0.7) return 'rgba(39,174,96,0.82)';
      if (v < 1.5) return 'rgba(241,196,15,0.82)';
      if (v < 2.8) return 'rgba(230,126,34,0.82)';
      return 'rgba(192,57,43,0.82)';
    },
    windLegend: [
      { color: 'rgba(39,174,96,0.82)',  label: '< 0.7 {unit}  —  Excellent' },
      { color: 'rgba(241,196,15,0.82)', label: '0.7 – 1.5  —  Good' },
      { color: 'rgba(230,126,34,0.82)', label: '1.5 – 2.8  —  Moderate' },
      { color: 'rgba(192,57,43,0.82)',  label: '> 2.8 {unit}  —  Poor' },
    ],
    legendGradient: null,
  },
  {
    key:          'csi',
    label:        'CSI (Critical Success Index)',
    shortLabel:   'CSI',
    requiresHour: false,
    requiresThreshold: true,
    description:  'Threat score for threshold exceedance events. Higher = better.',
    colorFn: (v) => {
      if (v == null) return null;
      if (v >= 0.6)  return 'rgba(39,174,96,0.85)';
      if (v >= 0.4)  return 'rgba(241,196,15,0.85)';
      if (v >= 0.2)  return 'rgba(230,126,34,0.85)';
      return 'rgba(192,57,43,0.85)';
    },
    legend: [
      { color: 'rgba(39,174,96,0.85)',  label: '≥ 0.6  —  Good' },
      { color: 'rgba(241,196,15,0.85)', label: '0.4 – 0.6  —  Moderate' },
      { color: 'rgba(230,126,34,0.85)', label: '0.2 – 0.4  —  Poor' },
      { color: 'rgba(192,57,43,0.85)',  label: '< 0.2  —  Very poor' },
    ],
    legendGradient: null,
  },
  {
    key:          'pod',
    label:        'POD (Probability of Detection)',
    shortLabel:   'POD',
    requiresHour: false,
    requiresThreshold: true,
    description:  'Fraction of observed events correctly forecast. Higher = better.',
    colorFn: (v) => {
      if (v == null) return null;
      if (v >= 0.7)  return 'rgba(39,174,96,0.85)';
      if (v >= 0.5)  return 'rgba(241,196,15,0.85)';
      if (v >= 0.3)  return 'rgba(230,126,34,0.85)';
      return 'rgba(192,57,43,0.85)';
    },
    legend: [
      { color: 'rgba(39,174,96,0.85)',  label: '≥ 0.7  —  Good' },
      { color: 'rgba(241,196,15,0.85)', label: '0.5 – 0.7  —  Moderate' },
      { color: 'rgba(230,126,34,0.85)', label: '0.3 – 0.5  —  Poor' },
      { color: 'rgba(192,57,43,0.85)',  label: '< 0.3  —  Very poor' },
    ],
    legendGradient: null,
  },
  {
    key:          'far',
    label:        'FAR (False Alarm Ratio)',
    shortLabel:   'FAR',
    requiresHour: false,
    requiresThreshold: true,
    description:  'Fraction of forecast events that were false alarms. Lower = better.',
    colorFn: (v) => {
      if (v == null) return null;
      if (v <= 0.2)  return 'rgba(39,174,96,0.85)';
      if (v <= 0.4)  return 'rgba(241,196,15,0.85)';
      if (v <= 0.6)  return 'rgba(230,126,34,0.85)';
      return 'rgba(192,57,43,0.85)';
    },
    legend: [
      { color: 'rgba(39,174,96,0.85)',  label: '≤ 0.2  —  Good' },
      { color: 'rgba(241,196,15,0.85)', label: '0.2 – 0.4  —  Moderate' },
      { color: 'rgba(230,126,34,0.85)', label: '0.4 – 0.6  —  Poor' },
      { color: 'rgba(192,57,43,0.85)',  label: '> 0.6  —  Very poor' },
    ],
    legendGradient: null,
  },
  {
    key:          'brier',
    label:        'Brier Score',
    shortLabel:   'Brier',
    requiresHour: false,
    requiresThreshold: true,
    description:  'Mean squared error of event probability (0=perfect). Lower = better.',
    colorFn: (v) => {
      if (v == null) return null;
      if (v <= 0.05) return 'rgba(39,174,96,0.85)';
      if (v <= 0.15) return 'rgba(241,196,15,0.85)';
      if (v <= 0.25) return 'rgba(230,126,34,0.85)';
      return 'rgba(192,57,43,0.85)';
    },
    legend: [
      { color: 'rgba(39,174,96,0.85)',  label: '≤ 0.05  —  Excellent' },
      { color: 'rgba(241,196,15,0.85)', label: '0.05 – 0.15  —  Good' },
      { color: 'rgba(230,126,34,0.85)', label: '0.15 – 0.25  —  Moderate' },
      { color: 'rgba(192,57,43,0.85)',  label: '> 0.25  —  Poor' },
    ],
    legendGradient: null,
  },
];

// ── Reading a metric's scale for a variable ───────────────────────────────────
// Both fall back to the precipitation scale when a metric has no wind variant,
// which is correct for the dimensionless ones: CSI, POD, FAR, SSR and
// correlation are ratios, so their bands mean the same thing in any unit and
// deliberately have no override.

export const metricColorFn = (cfg, variable) => {
  if (!cfg) return () => null;
  return (variable === 'wind' && cfg.windColorFn) ? cfg.windColorFn : cfg.colorFn;
};

export const metricLegend = (cfg, variable) => {
  if (!cfg) return [];
  return ((variable === 'wind' && cfg.windLegend) ? cfg.windLegend : cfg.legend) ?? [];
};
