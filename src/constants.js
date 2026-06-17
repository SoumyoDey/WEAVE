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
export const buildColorMatrix = (colormapName, vsup = false, invertUncertainty = false, N = 4) => {
  const colors  = COLORMAPS[colormapName].colors;
  const lerp    = (a, b, t) => Math.round(a + (b - a) * t);
  const toHex   = (r, g, b) =>
    '#' + [r, g, b].map(v => Math.max(0, Math.min(255, v)).toString(16).padStart(2, '0')).join('');
  const cmapRgb = (t) => {
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
  const size     = N > 1 ? N : 4;
  const maxIdx   = size - 1;
  return Array.from({ length: size }, (_, row) => {
    const uncert = invertUncertainty ? (1 - row / maxIdx) : (row / maxIdx);
    return Array.from({ length: size }, (_, col) => {
      const t = vsup
        ? (col / maxIdx) * (1 - uncert * strength) + 0.5 * (uncert * strength)
        : col / maxIdx;
      const [r, g, b] = cmapRgb(t);
      return toHex(
        lerp(r, neutral, uncert * strength * 0.80),
        lerp(g, neutral, uncert * strength * 0.80),
        lerp(b, neutral, uncert * strength * 0.80),
      );
    });
  });
};

// ── Spatial metric registry ───────────────────────────────────────────────────
// To add a metric: append one entry here. Selector, overlay, legend, and plot
// all read from this array automatically — no other file needs to change.
export const METRIC_CONFIG = [
  {
    key:          'ssr',
    label:        'Spread-Skill Ratio (SSR)',
    shortLabel:   'SSR',
    requiresHour: true,
    requiresThreshold: false,
    description:  'Ratio of ensemble variance to squared forecast error at a single lead time. Ideal ≈ 1.',
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
    description:  'Time-aggregated SSR: mean(σ²) / mean(ε²) across all verified lead times. Ideal ≈ 1.',
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
    description:  'Ensemble mean minus observation (mm/h). Blue = under-forecast, red = over.',
    colorFn: (v) => {
      if (v == null) return null;
      if (v < -1.0) return 'rgba(41,128,185,0.85)';
      if (v < -0.3) return 'rgba(133,193,233,0.85)';
      if (v <=  0.3) return 'rgba(200,200,200,0.75)';
      if (v <=  1.0) return 'rgba(241,148,138,0.85)';
      return 'rgba(192,57,43,0.85)';
    },
    legend: [
      { color: 'rgba(41,128,185,0.85)',   label: '< −1 mm/h  —  Strong under-forecast' },
      { color: 'rgba(133,193,233,0.85)',  label: '−1 – −0.3  —  Slight under-forecast' },
      { color: 'rgba(200,200,200,0.75)',  label: '−0.3 – 0.3 —  Near-unbiased ✓' },
      { color: 'rgba(241,148,138,0.85)',  label: '0.3 – 1 mm/h — Slight over-forecast' },
      { color: 'rgba(192,57,43,0.85)',    label: '> 1 mm/h  —  Strong over-forecast' },
    ],
    legendGradient: null,
  },
  {
    key:          'mae',
    label:        'Mean Absolute Error (MAE)',
    shortLabel:   'MAE',
    requiresHour: false,
    requiresThreshold: false,
    description:  'Mean |error| across lead times (mm/h). Lower = better.',
    colorFn: (v) => {
      if (v == null) return null;
      if (v < 0.2)  return 'rgba(39,174,96,0.82)';
      if (v < 0.5)  return 'rgba(241,196,15,0.82)';
      if (v < 1.0)  return 'rgba(230,126,34,0.82)';
      return 'rgba(192,57,43,0.82)';
    },
    legend: [
      { color: 'rgba(39,174,96,0.82)',  label: '< 0.2 mm/h  —  Excellent' },
      { color: 'rgba(241,196,15,0.82)', label: '0.2 – 0.5  —  Good' },
      { color: 'rgba(230,126,34,0.82)', label: '0.5 – 1.0  —  Moderate' },
      { color: 'rgba(192,57,43,0.82)',  label: '> 1.0 mm/h  —  Poor' },
    ],
    legendGradient: null,
  },
  {
    key:          'rmse',
    label:        'Root Mean Square Error (RMSE)',
    shortLabel:   'RMSE',
    requiresHour: false,
    requiresThreshold: false,
    description:  'RMSE of ensemble mean vs obs (mm/h). Lower = better.',
    colorFn: (v) => {
      if (v == null) return null;
      if (v < 0.3)  return 'rgba(39,174,96,0.82)';
      if (v < 0.7)  return 'rgba(241,196,15,0.82)';
      if (v < 1.2)  return 'rgba(230,126,34,0.82)';
      return 'rgba(192,57,43,0.82)';
    },
    legend: [
      { color: 'rgba(39,174,96,0.82)',  label: '< 0.3 mm/h  —  Excellent' },
      { color: 'rgba(241,196,15,0.82)', label: '0.3 – 0.7  —  Good' },
      { color: 'rgba(230,126,34,0.82)', label: '0.7 – 1.2  —  Moderate' },
      { color: 'rgba(192,57,43,0.82)',  label: '> 1.2 mm/h  —  Poor' },
    ],
    legendGradient: null,
  },
  {
    key:          'crps',
    label:        'CRPS (Continuous Ranked Probability Score)',
    shortLabel:   'CRPS',
    requiresHour: false,
    requiresThreshold: false,
    description:  'Mean CRPS for Gaussian forecast distribution (mm/h). Lower = better.',
    colorFn: (v) => {
      if (v == null) return null;
      if (v < 0.15) return 'rgba(39,174,96,0.82)';
      if (v < 0.35) return 'rgba(241,196,15,0.82)';
      if (v < 0.6)  return 'rgba(230,126,34,0.82)';
      return 'rgba(192,57,43,0.82)';
    },
    legend: [
      { color: 'rgba(39,174,96,0.82)',  label: '< 0.15 mm/h  —  Excellent' },
      { color: 'rgba(241,196,15,0.82)', label: '0.15 – 0.35  —  Good' },
      { color: 'rgba(230,126,34,0.82)', label: '0.35 – 0.6   —  Moderate' },
      { color: 'rgba(192,57,43,0.82)',  label: '> 0.6 mm/h   —  Poor' },
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
