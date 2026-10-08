/**
 * The metrics the Analysis tab draws as region maps, and what each one needs.
 *
 * `requiresThreshold` decides which maps are redrawn when the threshold moves;
 * `requiresHour` marks the single-lead metrics. Data, not behaviour — the tab
 * reads it to build the map grid (`NEXT_STEPS.md` §60).
 */
export const REGION_METRICS = [
  { key: 'ssr_agg',     group: 'calibration',  label: 'Spread-Skill Ratio',         requiresHour: false, requiresThreshold: false },
  { key: 'correlation', group: 'calibration',  label: 'Spread-Skill Correlation',   requiresHour: false, requiresThreshold: false },
  { key: 'bias',        group: 'accuracy',     label: 'Bias (Mean Error)',          requiresHour: false, requiresThreshold: false },
  { key: 'mae',         group: 'accuracy',     label: 'MAE',                        requiresHour: false, requiresThreshold: false },
  { key: 'rmse',        group: 'accuracy',     label: 'RMSE',                       requiresHour: false, requiresThreshold: false },
  { key: 'crps',        group: 'accuracy',     label: 'CRPS',                       requiresHour: false, requiresThreshold: false },
  { key: 'csi',         group: 'categorical',  label: 'CSI',                        requiresHour: false, requiresThreshold: true  },
  { key: 'pod',         group: 'categorical',  label: 'POD',                        requiresHour: false, requiresThreshold: true  },
  { key: 'far',         group: 'categorical',  label: 'FAR',                        requiresHour: false, requiresThreshold: true  },
  { key: 'brier',       group: 'categorical',  label: 'Brier Score',                requiresHour: false, requiresThreshold: true  },
];
