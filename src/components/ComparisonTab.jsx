import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  ComposedChart, LineChart, Line, BarChart, Bar, Cell,
  Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { Scale, MapPin } from 'lucide-react';
import {
  fetchComparisonTimeseries, fetchComparisonSkill, fetchSpatialAgreement,
  fetchComparisonCategorical, fetchComparisonRegionMetrics,
  fetchComparisonSpatialDiff,
} from '../api/comparisonApi';
import { fetchSpatialMetric, fetchSpatialMetricPlot } from '../api/spatialApi';
import { t } from '../theme';

const MODEL_COLORS = { AIFS: '#3498db', GEFS: '#e74c3c', UKMO: '#2ecc71' };

// Advanced (categorical) metrics rendered per model over lead time in Section 5.
const CAT_METRICS = [
  { key: 'csi', label: 'CSI', hint: 'Critical Success Index · higher is better' },
  { key: 'pod', label: 'POD', hint: 'Probability of Detection · higher is better' },
  { key: 'far', label: 'FAR', hint: 'False Alarm Ratio · lower is better' },
  { key: 'fss', label: 'FSS', hint: 'Fractions Skill Score · higher is better' },
];

// Verification metrics carried per lead time by /api/compare/skill.
const SKILL_METRICS = [
  { key: 'ssr',  label: 'SSR',  hint: 'Spread-Skill Ratio · ideal = 1',   refLine: 1, decimals: 3 },
  { key: 'crps', label: 'CRPS', hint: 'Probabilistic error · lower is better',       decimals: 4 },
  { key: 'bias', label: 'Bias', hint: 'Mean error · 0 is unbiased',        refLine: 0, decimals: 3 },
  { key: 'mae',  label: 'MAE',  hint: 'Mean absolute error · lower is better',       decimals: 3 },
  { key: 'rmse', label: 'RMSE', hint: 'Root mean square error · lower is better',    decimals: 3 },
];

// The same suite aggregated over all verified lead times (skill `summary`).
const SKILL_SUMMARY_METRICS = [
  { key: 'mean_ssr',    label: 'Mean SSR',    hint: 'ideal = 1',           refLine: 1, decimals: 3 },
  { key: 'correlation', label: 'Spread–skill corr.', hint: 'spread vs |error|',       decimals: 3 },
  { key: 'mean_crps',   label: 'Mean CRPS',   hint: 'lower is better',                decimals: 4 },
  { key: 'bias',        label: 'Bias',        hint: '0 is unbiased',       refLine: 0, decimals: 3 },
  { key: 'mae',         label: 'MAE',         hint: 'lower is better',                decimals: 3 },
  { key: 'rmse',        label: 'RMSE',        hint: 'lower is better',                decimals: 3 },
];

// Region-mean metrics from /api/compare/region-metrics, grouped the same way
// the Analysis tab groups its region maps.
const REGION_METRIC_GROUPS = [
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
      { key: 'csi',   label: 'CSI',   hint: 'higher is better', decimals: 3 },
      { key: 'pod',   label: 'POD',   hint: 'higher is better', decimals: 3 },
      { key: 'far',   label: 'FAR',   hint: 'lower is better',  decimals: 3 },
      { key: 'brier', label: 'Brier', hint: '0 is perfect',     decimals: 4 },
    ],
  },
];

// Metrics offered by the per-model spatial small-multiples. Same suite as the
// region bars; the categorical four need the threshold passed through.
const SPATIAL_MAP_METRICS = REGION_METRIC_GROUPS.flatMap(g =>
  g.metrics.map(m => ({
    key: m.key,
    label: m.label,
    requiresThreshold: g.id === 'categorical',
  })),
);

// Categorical scores pooled over lead times (compare/categorical `summaries`).
const CAT_SUMMARY_METRICS = [
  { key: 'csi',   label: 'CSI',   hint: 'higher is better', decimals: 3 },
  { key: 'pod',   label: 'POD',   hint: 'higher is better', decimals: 3 },
  { key: 'far',   label: 'FAR',   hint: 'lower is better',  decimals: 3 },
  { key: 'fss',   label: 'FSS',   hint: 'higher is better', decimals: 3 },
  { key: 'brier', label: 'Brier', hint: '0 is perfect',     decimals: 4 },
];
const MODEL_NAMES  = ['AIFS', 'GEFS', 'UKMO'];

// Nominal output cadence per model, used only for labelling. The unit
// conversion itself lives in the backend (_precip_rate_series), because the
// three models don't share a convention — AIFS stores a running total since
// init and GEFS alternates 3 h and 6 h buckets, so a single client-side divisor
// was wrong for both. /api/compare/timeseries now returns mm/h directly.
const PRECIP_RECORD_NOTE = {
  AIFS: '(6h, de-accumulated)',
  GEFS: '(3h/6h buckets)',
  UKMO: '(hourly)',
};

// ── Shared style tokens ──────────────────────────────────────────────────────
const CARD = {
  background: 'rgba(255,255,255,0.04)',
  borderRadius: 10,
  padding: '16px 20px',
  border: '1px solid rgba(255,255,255,0.07)',
};

const SECTION_TITLE = {
  color: 'rgba(255,255,255,0.85)',
  fontSize: t.fontSize.md,
  fontWeight: '600',
  letterSpacing: '0.02em',
  margin: '0 0 14px 0',
};

const LABEL = {
  fontSize: t.fontSize.xs,
  fontWeight: '500',
  letterSpacing: '0.02em',
  color: 'rgba(255,255,255,0.5)',
  marginBottom: '6px',
};

const INPUT = {
  background: 'rgba(255,255,255,0.06)',
  border: '1px solid rgba(255,255,255,0.12)',
  borderRadius: '7px',
  color: 'rgba(255,255,255,0.85)',
  fontSize: t.fontSize.base,
  padding: '6px 10px',
  outline: 'none',
  width: '80px',
};

const TOOLTIP_STYLE = {
  background: '#1a2535',
  border: '1px solid rgba(255,255,255,0.15)',
  borderRadius: t.radius,
  color: 'white',
  fontSize: t.fontSize.sm,
};

// Shared layout for the small-multiple metric cards.
const SMALL_GRID = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(min(240px, 100%), 1fr))',
  gap: '14px',
};

const SUBHEAD = {
  color: 'rgba(255,255,255,0.55)',
  fontSize: t.fontSize.sm,
  marginBottom: '10px',
  display: 'flex',
  alignItems: 'center',
  gap: '12px',
  flexWrap: 'wrap',
};

// ── Small helpers ────────────────────────────────────────────────────────────
function Spinner() {
  return (
    <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: t.fontSize.md, padding: '40px 0', textAlign: 'center' }}>
      ⏳ Loading…
    </div>
  );
}

// Shown wherever region mode needs a bbox that hasn't been drawn yet.
function RegionNudge() {
  return (
    <div style={{
      borderRadius: '10px',
      padding: '20px 24px',
      border: '1px dashed rgba(255,255,255,0.15)',
      background: 'rgba(255,255,255,0.02)',
      display: 'flex',
      alignItems: 'flex-start',
      gap: '12px',
      color: 'rgba(255,255,255,0.35)',
      fontSize: t.fontSize.base,
      lineHeight: 1.6,
    }}>
      <span style={{ lineHeight: 1, display: 'inline-flex' }}><MapPin size={18} /></span>
      <div>
        <div style={{ fontWeight: '600', color: 'rgba(255,255,255,0.5)', marginBottom: '4px' }}>
          No region selected
        </div>
        Switch to the <strong style={{ color: 'rgba(255,255,255,0.6)' }}>Visualization</strong> tab,
        use the selection toolbar to draw a rectangle or polygon, then return here.
      </div>
    </div>
  );
}

function ssrColor(ssr) {
  if (ssr == null) return '#aaa';
  if (ssr >= 0.8 && ssr <= 1.2) return '#2ecc71';
  if (ssr < 0.8) return '#e74c3c';
  return '#f39c12';
}

function corrColor(c) {
  if (c == null) return '#aaa';
  if (c >= 0.7) return '#2ecc71';
  if (c >= 0.4) return '#f39c12';
  return '#e74c3c';
}

// Y-axis tick labels in the narrow metric cards. A raw domain bound like
// -0.4187 overflows the axis gutter and gets clipped to "4187", so round to a
// width the gutter can actually show.
export const axisTick = (v) => {
  // Guard null explicitly: Number(null) is 0, which would draw a spurious "0.00"
  // label for a missing tick rather than no label at all.
  if (v === null || v === undefined || v === '') return '';
  const n = Number(v);
  if (!Number.isFinite(n)) return '';
  const abs = Math.abs(n);
  if (abs >= 100) return n.toFixed(0);
  if (abs >= 10)  return n.toFixed(1);
  if (abs >= 1)   return n.toFixed(2);
  return n.toFixed(2);
};

// Placeholder used inside a metric card when every model came back empty, so a
// missing metric reads as "no data" rather than an unexplained blank panel.
function NoData({ text = 'No data for this selection' }) {
  return (
    <div style={{
      height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: 'rgba(255,255,255,0.25)', fontSize: t.fontSize.xs, textAlign: 'center', padding: '0 8px',
    }}>
      {text}
    </div>
  );
}

function MetricCard({ label, hint, height, children }) {
  return (
    <div style={{ ...CARD, padding: '12px 10px 6px' }}>
      <div style={{ fontSize: t.fontSize.base, fontWeight: 600, color: 'rgba(255,255,255,0.85)' }}>{label}</div>
      <div style={{ fontSize: t.fontSize.micro, color: 'rgba(255,255,255,0.4)', marginBottom: '4px' }}>
        {hint || ' '}
      </div>
      <div style={{ height }}>{children}</div>
    </div>
  );
}

// One metric over lead time, a line per model. `rows` is [{hour, <key>_<model>}].
function LeadTimeChart({ label, hint, metricKey, rows, models, refLine, decimals = 3 }) {
  const hasData = rows.some(r => models.some(m => r[`${metricKey}_${m}`] != null));
  return (
    <MetricCard label={label} hint={hint} height="160px">
      {hasData ? (
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 6, right: 14, left: -10, bottom: 16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
            <XAxis dataKey="hour" stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 10 }} tickFormatter={h => `+${h}h`} />
            <YAxis stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 10 }} width={46} tickFormatter={axisTick} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(value, name) => [value != null ? Number(value).toFixed(decimals) : 'N/A', name.replace(`${metricKey}_`, '')]}
              labelFormatter={h => `+${h}h`}
            />
            {refLine != null && (
              <ReferenceLine y={refLine} stroke="rgba(255,255,255,0.35)" strokeDasharray="5 3" />
            )}
            {models.map(m => (
              <Line
                key={m}
                type="linear"
                dataKey={`${metricKey}_${m}`}
                name={`${metricKey}_${m}`}
                stroke={MODEL_COLORS[m]}
                strokeWidth={2}
                connectNulls
                dot={{ r: 2.5, fill: MODEL_COLORS[m], strokeWidth: 0 }}
                activeDot={{ r: 5 }}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      ) : <NoData />}
    </MetricCard>
  );
}

// One aggregate metric, a bar per model. `values` is parallel to `models`.
function AggregateBar({ label, hint, models, values, refLine, decimals = 3 }) {
  const data    = models.map((m, i) => ({ model: m, value: values[i] }));
  const hasData = values.some(v => v != null);
  return (
    <MetricCard label={label} hint={hint} height="150px">
      {hasData ? (
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 6, right: 12, left: -10, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
            <XAxis dataKey="model" stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.6)', fontSize: 10 }} />
            {/* Bar length encodes magnitude, so the axis has to include 0 —
                otherwise all-negative metrics (e.g. a negative spread-skill
                correlation) hang from the top and read as large positives. */}
            <YAxis
              stroke="rgba(255,255,255,0.3)"
              tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 10 }}
              width={46}
              domain={[v => Math.min(0, v), v => Math.max(0, v)]}
              tickFormatter={axisTick}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              cursor={{ fill: 'rgba(255,255,255,0.04)' }}
              formatter={v => [v != null ? Number(v).toFixed(decimals) : 'N/A', label]}
            />
            {refLine != null && (
              <ReferenceLine y={refLine} stroke="rgba(255,255,255,0.35)" strokeDasharray="5 3" />
            )}
            <Bar dataKey="value" radius={[3, 3, 0, 0]} maxBarSize={44} isAnimationActive={false}>
              {data.map(d => <Cell key={d.model} fill={MODEL_COLORS[d.model]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      ) : <NoData />}
    </MetricCard>
  );
}

// ── Custom Tooltip for Forecast Comparison chart ─────────────────────────────
// The API already returns rates (mm/h or m/s); `raw_mean` is the stored value,
// shown underneath for precipitation so the conversion stays inspectable.
function ForecastTooltip({ active, payload, label, selectedModels, normalized, variable = 'precipitation', displayUnit = 'mm/h' }) {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0]?.payload || {};
  const isPrecip = variable === 'precipitation';

  const means = selectedModels
    .map(m => {
      const rateMean = row[`${m}_rate_mean`];
      if (rateMean == null) return null;
      return {
        model: m,
        rateMean,
        rateStd: row[`${m}_rate_std`] ?? null,
        rawMean: row[`${m}_raw_mean`] ?? null,
        periodH: row[`${m}_period_h`] ?? 1,
      };
    })
    .filter(Boolean);

  if (!means.length) return null;

  return (
    <div style={{ ...TOOLTIP_STYLE, padding: '10px 14px', minWidth: '210px' }}>
      <div style={{ color: 'rgba(255,255,255,0.5)', fontSize: t.fontSize.xs, marginBottom: '8px' }}>
        +{label}h forecast
        {normalized && <span style={{ color: '#f39c12', marginLeft: '6px' }}>· per-model normalised</span>}
      </div>
      {means.map(({ model, rateMean, rateStd, rawMean, periodH }) => (
        <div key={model} style={{ marginBottom: '6px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ display: 'inline-block', width: '10px', height: '10px', borderRadius: '2px', background: MODEL_COLORS[model] }} />
            <span style={{ color: 'rgba(255,255,255,0.85)', fontWeight: '600', minWidth: '44px' }}>{model}</span>
            <span style={{ color: 'rgba(255,255,255,0.85)', fontWeight: '700' }}>
              {rateMean.toFixed(3)}
              <span style={{ color: 'rgba(255,255,255,0.5)', fontWeight: '400', fontSize: t.fontSize.micro, marginLeft: '2px' }}>{displayUnit}</span>
            </span>
            {rateStd != null && (
              <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: t.fontSize.xs }}>±{rateStd.toFixed(3)}</span>
            )}
          </div>
          {/* Stored value — informative for precipitation, where it differs
              from the rate (a running total for AIFS, a bucket for GEFS) */}
          {isPrecip && rawMean != null && periodH > 1 && (
            <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.micro, marginLeft: '18px', marginTop: '1px' }}>
              stored: {rawMean.toFixed(3)} · {periodH}h period
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Build merged timeseries dataset ─────────────────────────────────────────
// `mean`/`std` arrive from the API already as rates (mm/h or m/s) — the unit
// conversion belongs to the backend, which knows each model's record semantics.
// Optionally (normalize=true) scale each model to its [0,1] peak.
export function buildMergedTimeseries(tsData, selectedModels, normalize = false) {
  if (!tsData) return [];

  // Per-model peak for optional normalisation
  const modelPeaks = {};
  if (normalize) {
    selectedModels.forEach(m => {
      if (tsData[m]) {
        const peak = Math.max(...tsData[m].map(r => (r.mean || 0) + (r.std || 0)));
        modelPeaks[m] = peak > 1e-9 ? peak : 1;
      }
    });
  }

  const hourSet = new Set();
  selectedModels.forEach(m => {
    if (tsData[m]) tsData[m].forEach(row => hourSet.add(row.hour));
  });
  const hours = Array.from(hourSet).sort((a, b) => a - b);

  return hours.map(hour => {
    const row = { hour };
    selectedModels.forEach(m => {
      const entry = tsData[m]?.find(r => r.hour === hour);
      if (entry) {
        const norm = normalize ? (modelPeaks[m] || 1) : 1;
        const mean = entry.mean != null ? entry.mean : null;
        const std  = entry.std  != null ? entry.std  : 0;
        row[`${m}_mean`] = mean != null ? mean / norm : null;
        row[`${m}_hi`]   = mean != null ? (mean + std) / norm : null;
        row[`${m}_lo`]   = mean != null ? Math.max(0, (mean - std) / norm) : null;
        // Un-normalised rate + stored value, both kept for the tooltip
        row[`${m}_rate_mean`] = mean;
        row[`${m}_rate_std`]  = entry.std;
        row[`${m}_raw_mean`]  = entry.raw_mean;
        row[`${m}_period_h`]  = entry.period_h;
      }
    });
    return row;
  });
}

// Ratio of max-to-min peak across models, on the rates the API returns.
export function computeScaleRatio(tsData, models) {
  const peaks = models
    .map(m => (tsData[m]
      ? Math.max(...tsData[m].map(r => (r.mean || 0) + (r.std || 0)))
      : 0))
    .filter(v => v > 0);
  if (peaks.length < 2) return 1;
  return Math.max(...peaks) / Math.min(...peaks);
}

// ── Main component ───────────────────────────────────────────────────────────
export function ComparisonTab({
  defaultLocation,
  defaultHour,
  selectedVariable,
  selectedRegion,
  onJumpToComparison,
  active = true,
}) {
  // Controls
  // Point vs region analytics (mirrors AnalysisTab's catMode). Point mode compares
  // models at a single lat/lon; region mode compares them over the drawn bbox.
  const [compareMode, setCompareMode] = useState('point');   // 'point' | 'region'
  const [lat, setLat] = useState(defaultLocation ? String(defaultLocation.lat) : '');
  const [lon, setLon] = useState(defaultLocation ? String(defaultLocation.lon) : '');
  const [selectedModels, setSelectedModels] = useState(['AIFS', 'GEFS', 'UKMO']);
  const [hourMin, setHourMin] = useState(0);
  const [hourMax, setHourMax] = useState(168);
  const [spatialHour, setSpatialHour] = useState(defaultHour || 6);
  const [showSpreadBands, setShowSpreadBands] = useState(true);
  const [normalizeScales, setNormalizeScales] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [threshold, setThreshold] = useState(selectedVariable === 'wind' ? 10 : 25);
  const [fssWindow, setFssWindow] = useState(5);
  // Region mode keeps its own threshold: it drives the region-metric and map
  // views, while `threshold` above drives point-mode advanced metrics.
  const [regionThreshold, setRegionThreshold] = useState(selectedVariable === 'wind' ? 10 : 25);

  // Loading
  const [tsLoading, setTsLoading] = useState(false);
  const [skillLoading, setSkillLoading] = useState(false);

  // Results
  const [tsData, setTsData] = useState(null);
  const [skillData, setSkillData] = useState(null);
  const [spatialData, setSpatialData] = useState(null);
  const [spatialLoading, setSpatialLoading] = useState(false);
  const [spatialShareState, setSpatialShareState] = useState('idle'); // 'idle' | 'copied'
  const [hasRun, setHasRun] = useState(false);
  const [hasRunRegion, setHasRunRegion] = useState(false);
  const [regionData, setRegionData] = useState(null);
  const [regionLoading, setRegionLoading] = useState(false);
  const [regionError, setRegionError] = useState('');
  const regionSeqRef = useRef(0);   // drops stale region-metric responses
  const [mapMetric, setMapMetric] = useState('mae');
  const [modelMaps, setModelMaps] = useState({});     // model -> {loading, url, error}
  const [mapsRunning, setMapsRunning] = useState(false);
  const mapsSeqRef = useRef(0);     // drops stale small-multiple responses
  // A/B difference map. null = follow the first two selected models.
  const [diffA, setDiffA] = useState(null);
  const [diffB, setDiffB] = useState(null);
  const [diffData, setDiffData] = useState(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState('');
  const diffSeqRef = useRef(0);     // drops stale difference-map responses
  const [catData, setCatData] = useState(null);
  const [catLoading, setCatLoading] = useState(false);
  const [catError, setCatError] = useState('');
  const [runError, setRunError] = useState('');   // surfaces compare fetch failures
  const catSeqRef = useRef(0);   // drops stale advanced-metric responses

  // Effects
  useEffect(() => {
    if (defaultLocation) {
      setLat(String(defaultLocation.lat));
      setLon(String(defaultLocation.lon));
    }
  }, [defaultLocation]);

  useEffect(() => {
    if (defaultHour != null) setSpatialHour(defaultHour);
  }, [defaultHour]);

  // Thresholds are variable-specific (mm/6h vs m/s), so reset them to a sane
  // default and drop now-stale results whenever the variable changes.
  useEffect(() => {
    const def = selectedVariable === 'wind' ? 10 : 25;
    setThreshold(def);
    setRegionThreshold(def);
    setCatData(null);
    setRegionData(null);
    setModelMaps({});
    setDiffData(null);
    setHasRunRegion(false);   // back to the "click Run" prompt, not an empty section
  }, [selectedVariable]);

  // Derived
  const parsedLat = parseFloat(lat);
  const parsedLon = parseFloat(lon);
  const validLocation = !isNaN(parsedLat) && !isNaN(parsedLon);
  const isRegionMode = compareMode === 'region';
  const hasRegion = !!selectedRegion?.bounds;
  const canRun = selectedModels.length >= 2 && hourMin < hourMax
    && (isRegionMode ? hasRegion : validLocation);

  // Handlers
  const toggleModel = (m) => {
    setSelectedModels(prev => {
      if (prev.includes(m)) {
        if (prev.length <= 2) return prev; // min 2
        return prev.filter(x => x !== m);
      }
      return [...prev, m];
    });
  };

  const handleHourMin = (val) => {
    const n = Math.max(0, Math.min(360, Number(val)));
    setHourMin(n);
  };

  const handleHourMax = (val) => {
    const n = Math.max(0, Math.min(360, Number(val)));
    setHourMax(n);
  };

  const handleRun = async () => {
    if (!canRun) return;
    setHasRun(true);
    setRunError('');
    setTsData(null);
    setSkillData(null);
    setTsLoading(true);
    setSkillLoading(true);
    const params = {
      models: selectedModels,
      lat: parsedLat,
      lon: parsedLon,
      hourMin,
      hourMax,
      variable: selectedVariable,
    };
    const [ts, skill] = await Promise.allSettled([
      fetchComparisonTimeseries(params),
      fetchComparisonSkill(params),
    ]);
    if (ts.status === 'fulfilled') setTsData(ts.value);
    else console.error('compare/timeseries failed:', ts.reason);
    setTsLoading(false);
    if (skill.status === 'fulfilled') setSkillData(skill.value);
    else console.error('compare/skill failed:', skill.reason);
    setSkillLoading(false);
    // Surface the actual reason (not just a generic "unavailable") when a fetch
    // fails outright — most useful when both fail (e.g. API down / CORS).
    if (ts.status === 'rejected' && skill.status === 'rejected') {
      setRunError(ts.reason?.message || skill.reason?.message || 'Comparison request failed. Check API connectivity.');
    }
  };

  // Region mode's top-level Run: fetches the region-mean metric comparison and
  // reveals the region sections (the maps below have their own run controls).
  const handleRunRegion = async () => {
    if (!canRun) return;
    const seq = ++regionSeqRef.current;
    setHasRunRegion(true);
    setRegionError('');
    setRegionData(null);
    setRegionLoading(true);
    try {
      const result = await fetchComparisonRegionMetrics({
        models: selectedModels,
        variable: selectedVariable,
        bounds: selectedRegion.bounds,
        hourMin, hourMax,
        threshold: Number(regionThreshold),
      });
      if (seq !== regionSeqRef.current) return;   // a newer run superseded this one
      setRegionData(result);
    } catch (err) {
      if (seq !== regionSeqRef.current) return;
      console.error('compare/region-metrics failed:', err);
      setRegionError(err.message || 'Failed to compute region metrics.');
    } finally {
      if (seq === regionSeqRef.current) setRegionLoading(false);
    }
  };

  // Per-model spatial maps of one metric — the same Cartopy render the Analysis
  // tab uses, looped over the selected models. PLOT_STYLE_REGISTRY pins each
  // metric's colour norm, so the resulting maps already share a scale.
  const handleRunModelMaps = async () => {
    if (!hasRegion || selectedModels.length === 0) return;
    const seq = ++mapsSeqRef.current;
    setMapsRunning(true);
    setModelMaps(Object.fromEntries(
      selectedModels.map(m => [m, { loading: true, url: null, error: null }]),
    ));

    const def    = SPATIAL_MAP_METRICS.find(x => x.key === mapMetric);
    const bounds = selectedRegion.bounds;
    const thr    = def?.requiresThreshold ? Number(regionThreshold) : undefined;
    const isWind = selectedVariable === 'wind';

    const computeOne = async (m) => {
      try {
        const pts = await fetchSpatialMetric({
          metric: mapMetric, modelName: m, variable: selectedVariable,
          threshold: thr, hourMin, hourMax, bounds,
        });
        const plot = await fetchSpatialMetricPlot({
          metric: mapMetric, model: m, variable: selectedVariable,
          ...(thr != null && (isWind ? { threshold_ms: thr } : { threshold_mm_6h: thr })),
          points: pts.points || [], n_hours: pts.n_hours,
        });
        if (seq !== mapsSeqRef.current) return;
        setModelMaps(prev => ({
          ...prev,
          [m]: {
            loading: false,
            url:   plot.image ? 'data:image/png;base64,' + plot.image : null,
            error: plot.error || ((pts.points?.length || 0) === 0
              ? 'No forecast/observation matches in this region' : null),
          },
        }));
      } catch (err) {
        if (seq !== mapsSeqRef.current) return;
        setModelMaps(prev => ({
          ...prev,
          [m]: { loading: false, url: null, error: err.message },
        }));
      }
    };

    // Same 4-worker pool as the Analysis tab's Compute-All-Maps: each map is a
    // DB query plus a Cartopy render, so firing them all at once can exhaust
    // the connection pool.
    const CONCURRENCY = 4;
    let next = 0;
    const worker = async () => {
      while (next < selectedModels.length) await computeOne(selectedModels[next++]);
    };
    await Promise.all(
      Array.from({ length: Math.min(CONCURRENCY, selectedModels.length) }, worker),
    );
    if (seq === mapsSeqRef.current) setMapsRunning(false);
  };

  // A/B default to the first two selected models and re-derive if the model
  // selection changes underneath them.
  const effDiffA = selectedModels.includes(diffA) ? diffA : selectedModels[0];
  const effDiffB = (selectedModels.includes(diffB) && diffB !== effDiffA)
    ? diffB
    : selectedModels.find(m => m !== effDiffA);

  const handleRunDiff = async () => {
    if (!hasRegion || !effDiffA || !effDiffB) return;
    const seq = ++diffSeqRef.current;
    setDiffError('');
    setDiffData(null);
    setDiffLoading(true);
    const def = SPATIAL_MAP_METRICS.find(x => x.key === mapMetric);
    try {
      const result = await fetchComparisonSpatialDiff({
        modelA: effDiffA, modelB: effDiffB,
        metric: mapMetric, variable: selectedVariable,
        bounds: selectedRegion.bounds,
        hourMin, hourMax,
        threshold: def?.requiresThreshold ? Number(regionThreshold) : undefined,
      });
      if (seq !== diffSeqRef.current) return;
      setDiffData(result);
    } catch (err) {
      if (seq !== diffSeqRef.current) return;
      console.error('compare/spatial-diff failed:', err);
      setDiffError(err.message || 'Failed to compute the difference map.');
    } finally {
      if (seq === diffSeqRef.current) setDiffLoading(false);
    }
  };

  const downloadMap = (name, url) => {
    if (!url) return;
    const a = document.createElement('a');
    a.href = url;
    a.download = `WEAVE-${name}-${mapMetric}-${selectedVariable}.png`;
    a.click();
  };

  const handleRunCategorical = async () => {
    if (!validLocation || selectedModels.length < 1) return;
    const thr = Number(threshold);
    if (!Number.isFinite(thr)) { setCatError('Threshold must be a number.'); return; }
    const seq = ++catSeqRef.current;
    setCatError('');
    setCatData(null);
    setCatLoading(true);
    try {
      const result = await fetchComparisonCategorical({
        models: selectedModels, lat: parsedLat, lon: parsedLon,
        hourMin, hourMax, variable: selectedVariable,
        threshold: thr, fssWindow,
      });
      if (seq !== catSeqRef.current) return;   // a newer run superseded this one
      setCatData(result);
    } catch (err) {
      if (seq !== catSeqRef.current) return;
      console.error('Comparison categorical error:', err);
      setCatError(err.message || 'Failed to compute advanced metrics.');
    } finally {
      if (seq === catSeqRef.current) setCatLoading(false);
    }
  };

  // Union of hours across models → one row per hour with a per-model column.
  const buildCatRows = (metricKey) => {
    if (!catData?.models) return [];
    const allHours = new Set();
    selectedModels.forEach(m => catData.models[m]?.forEach(h => allHours.add(h.hour)));
    return Array.from(allHours).sort((a, b) => a - b).map(hour => {
      const row = { hour };
      selectedModels.forEach(m => {
        const e = catData.models[m]?.find(h => h.hour === hour);
        row[`${metricKey}_${m}`] = e ? e[metricKey] : null;
      });
      return row;
    });
  };

  const handleRunSpatial = async () => {
    if (!selectedRegion || selectedModels.length < 2) return;
    setSpatialData(null);
    setSpatialLoading(true);
    const { min_lat, max_lat, min_lon, max_lon } = selectedRegion.bounds;
    try {
      const result = await fetchSpatialAgreement({
        models: selectedModels,
        minLat: min_lat,
        maxLat: max_lat,
        minLon: min_lon,
        maxLon: max_lon,
        hour: spatialHour,
        variable: selectedVariable,
      });
      setSpatialData(result);
    } catch (err) {
      console.error('Spatial agreement error:', err);
      setSpatialData({ error: err.message });
    }
    setSpatialLoading(false);
  };

  const handleSpatialDownload = () => {
    if (!spatialData?.image) return;
    const a = document.createElement('a');
    a.href = 'data:image/png;base64,' + spatialData.image;
    a.download = `spatial_agreement_${selectedVariable}_+${spatialHour}h.png`;
    a.click();
  };

  const handleSpatialShare = async () => {
    if (!spatialData?.image) return;
    const dataUrl = 'data:image/png;base64,' + spatialData.image;
    const blob = await (await fetch(dataUrl)).blob();
    const file = new File([blob], `spatial_agreement_+${spatialHour}h.png`, { type: 'image/png' });
    if (navigator.canShare?.({ files: [file] })) {
      try { await navigator.share({ files: [file], title: 'WEAVE Spatial Agreement' }); return; }
      catch (e) { if (e.name !== 'AbortError') console.warn('Share failed:', e); }
    }
    try {
      await navigator.clipboard.write([
        new ClipboardItem({ 'image/png': blob }),
      ]);
      setSpatialShareState('copied');
      setTimeout(() => setSpatialShareState('idle'), 2500);
    } catch {
      handleSpatialDownload();
    }
  };

  // Derived chart data. Memoised: buildMergedTimeseries is O(hours × models) with
  // a per-hour .find, and previously reran on every render (incl. unrelated state
  // like share/advanced toggles).
  const mergedTs = useMemo(
    () => buildMergedTimeseries(tsData, selectedModels, normalizeScales),
    [tsData, selectedModels, normalizeScales],
  );

  // Per-metric rows for the lead-time small-multiples: one row per hour with a
  // `<metric>_<model>` column. Built once per skill payload — indexing each
  // model's hours in a Map avoids a linear .find() per (metric, hour, model).
  const skillRows = useMemo(() => {
    const out = {};
    SKILL_METRICS.forEach(({ key }) => { out[key] = []; });
    if (!skillData?.models) return out;
    const index   = {};
    const hourSet = new Set();
    selectedModels.forEach(m => {
      const hours = skillData.models[m]?.hours || [];
      index[m] = new Map(hours.map(h => [h.hour, h]));
      hours.forEach(h => hourSet.add(h.hour));
    });
    const hours = Array.from(hourSet).sort((a, b) => a - b);
    SKILL_METRICS.forEach(({ key }) => {
      out[key] = hours.map(hour => {
        const row = { hour };
        selectedModels.forEach(m => {
          const e = index[m].get(hour);
          row[`${key}_${m}`] = e ? e[key] : null;
        });
        return row;
      });
    });
    return out;
  }, [skillData, selectedModels]);
  // For precipitation, all display values are in mm/h (rate) after accum conversion
  const yAxisUnit     = selectedVariable === 'wind' ? 'm/s' : 'mm/h';
  const thresholdUnit = selectedVariable === 'wind' ? 'm/s' : 'mm/6h';
  // After the accum conversion the ratio should be much smaller than the raw ratio
  const scaleRatio = useMemo(
    () => (tsData ? computeScaleRatio(tsData, selectedModels) : 1),
    [tsData, selectedModels],
  );
  const hasScaleMismatch = scaleRatio > 5; // still >5× after unit fix → warn

  // Defer chart mount one frame after the tab becomes active so Recharts measures
  // a laid-out container (no width(0)/(-1) warnings). Hooks run unconditionally
  // above the early return, so form inputs and results survive tab switches.
  const [chartsReady, setChartsReady] = useState(false);
  useEffect(() => {
    if (!active) { setChartsReady(false); return; }
    const id = requestAnimationFrame(() => setChartsReady(true));
    return () => cancelAnimationFrame(id);
  }, [active]);

  if (!active || !chartsReady) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden', flex: 1 }}>
      {/* ── Header ── */}
      <div style={{ padding: '16px 30px 10px', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
        <h2 style={{ color: 'white', margin: '0 0 4px 0', fontSize: t.fontSize.xl, fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Scale size={18} />Model comparison
        </h2>
        <p style={{ color: 'rgba(255,255,255,0.4)', margin: '0 0 8px 0', fontSize: t.fontSize.base }}>
          Configure models, {isRegionMode ? 'region' : 'location'} and lead times then click Run.
        </p>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {/* Variable badge */}
          <span style={{
            fontSize: t.fontSize.xs, fontWeight: '600', padding: '3px 10px', borderRadius: '20px',
            background: 'rgba(52,152,219,0.15)', border: '1px solid rgba(52,152,219,0.3)',
            color: '#3498db',
          }}>
            {selectedVariable === 'precipitation' ? 'Precipitation' : 'Wind'}
          </span>
          {/* Location badge */}
          {validLocation && (
            <span style={{
              fontSize: t.fontSize.xs, fontWeight: '600', padding: '3px 10px', borderRadius: '20px',
              background: 'rgba(46,204,113,0.12)', border: '1px solid rgba(46,204,113,0.25)',
              color: '#2ecc71',
            }}>
              {parsedLat.toFixed(2)}°N, {parsedLon.toFixed(2)}°E
            </span>
          )}
        </div>
      </div>

      {/* ── Scrollable body ── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 30px' }}>

        {/* ── Section 2: Configuration card ── */}
        <div style={{ ...CARD, marginBottom: '24px' }}>
          {/* Point | Region mode toggle — decides which analytics sections show. */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '18px', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', borderRadius: t.radius, overflow: 'hidden', border: '1px solid rgba(255,255,255,0.15)' }}>
              {['point', 'region'].map(mode => (
                <button
                  key={mode}
                  onClick={() => setCompareMode(mode)}
                  aria-pressed={compareMode === mode}
                  style={{
                    padding: '6px 18px', fontSize: t.fontSize.sm, fontWeight: '600', cursor: 'pointer',
                    background: compareMode === mode ? 'rgba(52,152,219,0.25)' : 'rgba(255,255,255,0.04)',
                    color: compareMode === mode ? 'rgba(52,152,219,0.95)' : 'rgba(255,255,255,0.4)',
                    border: 'none', outline: 'none',
                  }}
                >
                  {mode === 'point' ? 'Point' : 'Region'}
                </button>
              ))}
            </div>
            <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.xs }}>
              {isRegionMode
                ? 'Compare models over the region drawn on the map'
                : 'Compare models at a single location'}
            </span>
          </div>

          {/* Location / Models / Lead times sit side by side on wide screens
              instead of stacking full-width with mostly-empty rows, and wrap
              back to a single column once the viewport gets too narrow. */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(260px, 100%), 1fr))', gap: '24px', marginBottom: '20px' }}>
          {/* LOCATION (point mode) / REGION (region mode) */}
          {isRegionMode ? (
          <div>
            <div style={LABEL}>Region</div>
            {hasRegion ? (
              <span style={{
                fontSize: t.fontSize.xs, fontWeight: '600', padding: '5px 12px', borderRadius: '20px',
                background: 'rgba(230,126,34,0.12)', border: '1px solid rgba(230,126,34,0.3)',
                color: '#e67e22', display: 'inline-block',
              }}>
                {selectedRegion.type === 'polygon' ? '⬡ Polygon' : '▭ Rectangle'}
                {' '}
                {selectedRegion.bounds.min_lat.toFixed(1)}°–{selectedRegion.bounds.max_lat.toFixed(1)}°N,{' '}
                {selectedRegion.bounds.min_lon.toFixed(1)}°–{selectedRegion.bounds.max_lon.toFixed(1)}°E
              </span>
            ) : (
              <span style={{ color: '#f39c12', fontSize: t.fontSize.sm }}>
                ⚠️ Draw a region on the map first
              </span>
            )}
          </div>
          ) : (
          <div>
            <div style={LABEL}>Location</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.sm }}>Lat</span>
                <input
                  type="number"
                  value={lat}
                  onChange={e => setLat(e.target.value)}
                  placeholder="e.g. 37.5"
                  aria-label="Latitude"
                  style={INPUT}
                />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.sm }}>Lon</span>
                <input
                  type="number"
                  value={lon}
                  onChange={e => setLon(e.target.value)}
                  placeholder="e.g. -122.4"
                  aria-label="Longitude"
                  style={INPUT}
                />
              </div>
              {defaultLocation && (
                <button
                  onClick={() => {
                    setLat(String(defaultLocation.lat));
                    setLon(String(defaultLocation.lon));
                  }}
                  style={{
                    background: 'rgba(52,152,219,0.12)',
                    border: '1px solid rgba(52,152,219,0.25)',
                    borderRadius: '7px',
                    color: '#3498db',
                    fontSize: t.fontSize.sm,
                    fontWeight: '600',
                    padding: '6px 12px',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '5px',
                  }}
                >
                  ◎ Use clicked point
                </button>
              )}
            </div>
          </div>
          )}

          {/* MODELS */}
          <div>
            <div style={LABEL}>Models</div>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              {MODEL_NAMES.map(m => {
                const active = selectedModels.includes(m);
                const color = MODEL_COLORS[m];
                return (
                  <button
                    key={m}
                    onClick={() => toggleModel(m)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: '6px',
                      padding: '6px 14px', borderRadius: '20px', cursor: 'pointer',
                      fontSize: t.fontSize.base, fontWeight: '600',
                      background: active ? `${color}22` : 'rgba(255,255,255,0.04)',
                      border: `1px solid ${active ? color : 'rgba(255,255,255,0.12)'}`,
                      color: active ? color : 'rgba(255,255,255,0.4)',
                      transition: 'all 0.15s',
                    }}
                  >
                    <span style={{
                      display: 'inline-block', width: '8px', height: '8px',
                      borderRadius: '50%', background: active ? color : 'rgba(255,255,255,0.2)',
                    }} />
                    {active ? '✓ ' : ''}{m}
                  </button>
                );
              })}
            </div>
            {selectedModels.length < 2 && (
              <div style={{ color: '#f39c12', fontSize: t.fontSize.xs, marginTop: '6px' }}>
                Select at least 2 models to compare.
              </div>
            )}
          </div>

          {/* LEAD TIMES */}
          <div>
            <div style={LABEL}>Lead times</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.sm }}>Min</span>
                <input
                  type="number"
                  value={hourMin}
                  min={0} max={360}
                  onChange={e => handleHourMin(e.target.value)}
                  aria-label="Minimum lead time (hours)"
                  style={{ ...INPUT, width: '64px' }}
                />
                <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: t.fontSize.sm }}>h</span>
              </div>
              <div aria-hidden="true" style={{
                flex: 1, height: '3px', background: 'rgba(255,255,255,0.1)',
                borderRadius: '2px', minWidth: '40px', maxWidth: '120px',
                position: 'relative',
              }}>
                <div style={{
                  position: 'absolute', top: 0, bottom: 0,
                  left: `${(hourMin / 360) * 100}%`,
                  right: `${100 - (hourMax / 360) * 100}%`,
                  background: '#3498db', borderRadius: '2px',
                }} />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.sm }}>Max</span>
                <input
                  type="number"
                  value={hourMax}
                  min={0} max={360}
                  onChange={e => handleHourMax(e.target.value)}
                  aria-label="Maximum lead time (hours)"
                  style={{ ...INPUT, width: '64px' }}
                />
                <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: t.fontSize.sm }}>h</span>
              </div>
            </div>
            {hourMin >= hourMax && (
              <div style={{ color: '#f39c12', fontSize: t.fontSize.xs, marginTop: '6px' }}>
                Min must be less than Max.
              </div>
            )}
          </div>

          {/* THRESHOLD (region mode) — categorical region metrics need one */}
          {isRegionMode && (
            <div>
              <div style={LABEL}>Threshold</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <input
                  type="number"
                  min={0}
                  value={regionThreshold}
                  onChange={e => setRegionThreshold(e.target.value)}
                  aria-label={`Threshold (${thresholdUnit})`}
                  style={{ ...INPUT, width: '72px' }}
                />
                <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.sm }}>{thresholdUnit}</span>
              </div>
              <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.micro, marginTop: '5px' }}>
                CSI · POD · FAR · Brier only
              </div>
            </div>
          )}
          </div>

          {/* Run button */}
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button
              onClick={isRegionMode ? handleRunRegion : handleRun}
              disabled={!canRun}
              style={{
                background: canRun ? '#3498db' : 'rgba(255,255,255,0.08)',
                color: canRun ? 'white' : 'rgba(255,255,255,0.25)',
                border: 'none',
                borderRadius: t.radius,
                padding: '9px 24px',
                fontSize: t.fontSize.md,
                fontWeight: '700',
                cursor: canRun ? 'pointer' : 'not-allowed',
                display: 'flex',
                alignItems: 'center',
                gap: '7px',
                transition: 'background 0.15s',
              }}
            >
              ▶ {isRegionMode ? 'Run Region Comparison' : 'Run Comparison'}
            </button>
          </div>
        </div>

        {/* ── Fetch error banner ── */}
        {runError && (
          <div role="alert" style={{
            ...CARD, borderLeft: '3px solid #e74c3c', color: '#e74c3c',
            fontSize: t.fontSize.sm, marginBottom: '20px',
          }}>
            Couldn’t load the comparison: {runError}
          </div>
        )}

        {/* ── Empty state (before first run) ── */}
        {!isRegionMode && !hasRun && (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            textAlign: 'center', color: 'rgba(255,255,255,0.25)',
            padding: '60px 20px',
          }}>
            <div>
              <div style={{ marginBottom: '16px', lineHeight: 1, color: 'rgba(255,255,255,0.3)' }}><Scale size={52} /></div>
              <p style={{ fontSize: t.fontSize.lg, margin: '0 0 8px 0', color: 'rgba(255,255,255,0.4)' }}>
                Configure the comparison above and click Run
              </p>
              <p style={{ fontSize: t.fontSize.base, margin: 0 }}>No results yet</p>
            </div>
          </div>
        )}

        {/* ── Region mode: needs a bbox before anything can run ── */}
        {isRegionMode && !hasRegion && <RegionNudge />}

        {/* ── Region mode empty state (region drawn, nothing run yet) ── */}
        {isRegionMode && hasRegion && !hasRunRegion && (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            textAlign: 'center', color: 'rgba(255,255,255,0.25)',
            padding: '60px 20px',
          }}>
            <div>
              <div style={{ marginBottom: '16px', lineHeight: 1, color: 'rgba(255,255,255,0.3)' }}><MapPin size={52} /></div>
              <p style={{ fontSize: t.fontSize.lg, margin: '0 0 8px 0', color: 'rgba(255,255,255,0.4)' }}>
                Click Run Region Comparison to compare models over this region
              </p>
              <p style={{ fontSize: t.fontSize.base, margin: 0 }}>No results yet</p>
            </div>
          </div>
        )}

        {/* ── Region metric comparison (region mode) ── */}
        {isRegionMode && hasRegion && hasRunRegion && (
          <div style={{ marginBottom: '28px' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px', marginBottom: '14px', flexWrap: 'wrap' }}>
              <h3 style={{ ...SECTION_TITLE, margin: 0 }}>Region metric comparison</h3>
              <span style={{ fontSize: t.fontSize.micro, color: 'rgba(255,255,255,0.25)', letterSpacing: '0.04em' }}>
                Pooled over every grid cell × lead time · +{hourMin}h–{hourMax}h · {yAxisUnit} except SSR / correlation / categorical
              </span>
            </div>

            {regionLoading && <Spinner />}

            {!regionLoading && regionError && (
              <div role="alert" style={{
                ...CARD, borderLeft: '3px solid #e74c3c', color: '#e74c3c',
                fontSize: t.fontSize.sm, marginBottom: '16px',
              }}>
                Couldn’t compute region metrics: {regionError}
              </div>
            )}

            {!regionLoading && !regionError && regionData && (() => {
              const warned = Object.entries(regionData.warnings || {});
              const anyValue = selectedModels.some(m =>
                Object.values(regionData.models?.[m] || {}).some(v => v != null));
              return (
                <>
                  {/* Grid-misalignment / no-overlap notice, per model */}
                  {warned.length > 0 && (
                    <div style={{
                      background: 'rgba(243,156,18,0.1)',
                      border: '1px solid rgba(243,156,18,0.3)',
                      borderRadius: t.radius,
                      padding: '10px 14px',
                      marginBottom: '16px',
                      color: '#f39c12',
                      fontSize: t.fontSize.sm,
                    }}>
                      {warned.map(([m, msg]) => (
                        <div key={m}><strong>{m}:</strong> {msg}</div>
                      ))}
                    </div>
                  )}

                  {!anyValue ? (
                    <div style={{
                      ...CARD, textAlign: 'center', padding: '32px 20px',
                      color: 'rgba(255,255,255,0.35)', fontSize: t.fontSize.base, lineHeight: 1.6,
                    }}>
                      No forecast/observation matches for this region, threshold, and lead-time range.
                      Try a wider region or lead-time range.
                    </div>
                  ) : (
                    <>
                      {/* Matched-cell count per model — the sample behind each mean */}
                      <div style={{ ...SUBHEAD, marginBottom: '16px' }}>
                        {selectedModels.map(m => (
                          <span key={m} style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                            <span style={{ display: 'inline-block', width: '10px', height: '10px', borderRadius: '2px', background: MODEL_COLORS[m] }} />
                            <span style={{ fontSize: t.fontSize.xs }}>{m}</span>
                            <span style={{ fontSize: t.fontSize.micro, color: 'rgba(255,255,255,0.3)' }}>
                              ({regionData.n_cells?.[m] ?? 0} cells)
                            </span>
                          </span>
                        ))}
                      </div>

                      {REGION_METRIC_GROUPS.map(group => (
                        <div key={group.id} style={{ marginBottom: '24px' }}>
                          <div style={SUBHEAD}>
                            <span style={{ fontWeight: '600' }}>
                              {group.label}
                              {group.id === 'categorical' && ` (> ${regionThreshold} ${thresholdUnit})`}
                            </span>
                            {group.id === 'categorical' && (
                              <span style={{ fontSize: t.fontSize.micro, color: 'rgba(255,255,255,0.3)' }}>
                                pooled from hit / miss / false-alarm counts, not averaged per cell
                              </span>
                            )}
                            <span style={{ fontSize: t.fontSize.micro, color: 'rgba(255,255,255,0.3)' }}>{group.hint}</span>
                          </div>
                          <div style={SMALL_GRID}>
                            {group.metrics.map(({ key, label, hint, refLine, decimals }) => (
                              <AggregateBar
                                key={key}
                                label={label}
                                hint={hint}
                                models={selectedModels}
                                values={selectedModels.map(m => regionData.models?.[m]?.[key] ?? null)}
                                refLine={refLine}
                                decimals={decimals}
                              />
                            ))}
                          </div>
                        </div>
                      ))}
                    </>
                  )}
                </>
              );
            })()}
          </div>
        )}

        {/* ── Section 3: Forecast Comparison (point mode) ── */}
        {!isRegionMode && hasRun && (
          <div style={{ marginBottom: '28px' }}>
            <h3 style={{ ...SECTION_TITLE, marginBottom: '6px' }}>Forecast Comparison</h3>
            {/* Unit note — the backend converts each model's own record type */}
            {selectedVariable !== 'wind' && (
              <div style={{
                display: 'flex', gap: '10px', flexWrap: 'wrap',
                marginBottom: '12px', alignItems: 'center',
              }}>
                <span style={{ fontSize: t.fontSize.xs, color: 'rgba(255,255,255,0.25)' }}>
                  Rates in mm/h —
                </span>
                {selectedModels.map(m => (
                  <span key={m} style={{
                    fontSize: t.fontSize.xs, fontWeight: '600',
                    color: MODEL_COLORS[m],
                    opacity: 0.75,
                  }}>
                    {m} {PRECIP_RECORD_NOTE[m] || 'native'}
                  </span>
                ))}
                <span style={{ fontSize: t.fontSize.micro, color: 'rgba(255,255,255,0.18)', marginLeft: '4px' }}>
                  Hover for the stored value
                </span>
              </div>
            )}

            {tsLoading && <Spinner />}

            {!tsLoading && tsData && (
              <>
                {/* Scale mismatch warning banner */}
                {hasScaleMismatch && !normalizeScales && (
                  <div style={{
                    background: 'rgba(52,152,219,0.10)',
                    border: '1px solid rgba(52,152,219,0.3)',
                    borderRadius: t.radius,
                    padding: '9px 14px',
                    marginBottom: '12px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '12px',
                    flexWrap: 'wrap',
                  }}>
                    <span style={{ color: '#bcd8f2', fontSize: t.fontSize.sm, display: 'flex', alignItems: 'center', gap: '6px' }}>
                      These models report at different scales ({scaleRatio.toFixed(0)}× apart), so one line may look flat. Turn on normalise to compare their shapes.
                    </span>
                    <button
                      onClick={() => setNormalizeScales(true)}
                      style={{
                        background: 'rgba(52,152,219,0.18)',
                        border: '1px solid rgba(52,152,219,0.45)',
                        borderRadius: t.radiusSm,
                        color: '#7ec8f7',
                        fontSize: t.fontSize.sm,
                        fontWeight: '600',
                        padding: '4px 12px',
                        cursor: 'pointer',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      Normalise scales
                    </button>
                  </div>
                )}

                {/* Legend row */}
                <div style={{ display: 'flex', gap: '12px', marginBottom: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
                  {selectedModels.map(m => {
                    const modelRows = tsData[m];
                    const lastRow   = modelRows?.length > 0 ? modelRows[modelRows.length - 1] : null;
                    // The API already returns a rate — no client-side division
                    const rateValue = lastRow?.mean != null ? lastRow.mean : null;
                    const color     = MODEL_COLORS[m];
                    return (
                      <div key={m} style={{
                        display: 'flex', alignItems: 'center', gap: '7px',
                        background: 'rgba(255,255,255,0.04)',
                        border: `1px solid ${color}44`,
                        borderRadius: '20px',
                        padding: '4px 12px',
                      }}>
                        <span style={{ display: 'inline-block', width: '12px', height: '3px', background: color, borderRadius: '2px' }} />
                        <span style={{ color: 'rgba(255,255,255,0.85)', fontSize: t.fontSize.sm, fontWeight: '600' }}>{m}</span>
                        {rateValue != null && (
                          <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.xs }}>
                            {rateValue.toFixed(3)} {yAxisUnit}
                          </span>
                        )}
                      </div>
                    );
                  })}

                  {/* Toggles */}
                  <div style={{ display: 'flex', gap: '14px', marginLeft: 'auto', alignItems: 'center' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'rgba(255,255,255,0.5)', fontSize: t.fontSize.sm, cursor: 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={normalizeScales}
                        onChange={e => setNormalizeScales(e.target.checked)}
                        style={{ accentColor: '#f39c12', cursor: 'pointer' }}
                      />
                      <span style={{ color: normalizeScales ? '#f39c12' : undefined }}>Normalise</span>
                    </label>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'rgba(255,255,255,0.5)', fontSize: t.fontSize.sm, cursor: 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={showSpreadBands}
                        onChange={e => setShowSpreadBands(e.target.checked)}
                        style={{ accentColor: '#3498db', cursor: 'pointer' }}
                      />
                      Spread bands
                    </label>
                  </div>
                </div>

                {/* Chart */}
                <div style={{ height: '300px' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={mergedTs} margin={{ top: 10, right: 24, left: 10, bottom: 24 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                      <XAxis
                        dataKey="hour"
                        stroke="rgba(255,255,255,0.3)"
                        tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }}
                        tickFormatter={h => `+${h}h`}
                        label={{ value: 'Forecast Hour', position: 'insideBottom', offset: -10, fill: 'rgba(255,255,255,0.4)', fontSize: 12 }}
                      />
                      <YAxis
                        stroke="rgba(255,255,255,0.3)"
                        tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }}
                        label={{
                          value: normalizeScales ? 'Normalised (0–1)' : yAxisUnit,
                          angle: -90,
                          position: 'insideLeft',
                          fill: normalizeScales ? '#f39c12' : 'rgba(255,255,255,0.4)',
                          fontSize: 11,
                        }}
                        domain={normalizeScales ? [0, 1] : ['auto', 'auto']}
                        tickFormatter={normalizeScales ? v => v.toFixed(1) : undefined}
                      />
                      <Tooltip
                        content={<ForecastTooltip selectedModels={selectedModels} normalized={normalizeScales} variable={selectedVariable} displayUnit={yAxisUnit} />}
                      />
                      {/* 24h boundary reference lines */}
                      {[24, 48, 72, 96, 120, 144, 168].filter(h => h >= hourMin && h <= hourMax).map(h => (
                        <ReferenceLine
                          key={h}
                          x={h}
                          stroke="rgba(255,255,255,0.07)"
                          strokeDasharray="4 4"
                          label={{ value: `D${h / 24}`, position: 'top', fill: 'rgba(255,255,255,0.18)', fontSize: 9 }}
                        />
                      ))}
                      {/* Per-model: spread bands + mean line
                          ─────────────────────────────────────────────────────
                          IMPORTANT: Do NOT use the "background-erase" (lo fill
                          with solid background color) technique here.
                          With 3 models, each model's lo-erase layer overwrites
                          the previous models' colored fills — leaving only the
                          last model's band visible.
                          Instead: render a simple top-down fill from 0 → hi for
                          each model at low opacity. All models remain visible
                          and their bands can overlap transparently. */}

                      {/* Pass 1: all spread band fills (drawn first, underneath lines) */}
                      {showSpreadBands && selectedModels.map(m => (
                        <Area
                          key={`band_${m}`}
                          dataKey={`${m}_hi`}
                          stroke="none"
                          fill={MODEL_COLORS[m]}
                          fillOpacity={0.10}
                          connectNulls
                          legendType="none"
                          isAnimationActive={false}
                        />
                      ))}

                      {/* Pass 2: all mean lines (drawn on top of all fills) */}
                      {selectedModels.map(m => (
                        <Line
                          key={`line_${m}`}
                          type="monotone"
                          dataKey={`${m}_mean`}
                          stroke={MODEL_COLORS[m]}
                          strokeWidth={2.5}
                          dot={false}
                          connectNulls
                          legendType="none"
                          isAnimationActive={false}
                        />
                      ))}
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </>
            )}

            {!tsLoading && !tsData && (
              <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.base, padding: '20px 0' }}>
                Forecast timeseries unavailable. Check API connectivity.
              </div>
            )}
          </div>
        )}

        {/* ── Section 4: Skill Verification (point mode) ── */}
        {!isRegionMode && hasRun && (
          <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '24px', marginBottom: '28px' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px', marginBottom: '14px' }}>
              <h3 style={{ ...SECTION_TITLE, margin: 0 }}>Skill Verification</h3>
              {selectedVariable !== 'wind' && (
                <span style={{ fontSize: t.fontSize.micro, color: 'rgba(255,255,255,0.25)', letterSpacing: '0.04em' }}>
                  Metrics in mm/h · accumulation window matched per model
                </span>
              )}
            </div>

            {skillLoading && <Spinner />}

            {!skillLoading && skillData && (() => {
              const obsHours = skillData.obs_hours || [];
              const noObs = obsHours.length === 0;

              return (
                <>
                  {/* Obs warning banner */}
                  {skillData.obs_warning && (
                    <div style={{
                      background: 'rgba(243,156,18,0.1)',
                      border: '1px solid rgba(243,156,18,0.3)',
                      borderRadius: t.radius,
                      padding: '10px 14px',
                      marginBottom: '16px',
                      color: '#f39c12',
                      fontSize: t.fontSize.base,
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '8px',
                    }}>
                      <span>⚠️</span>
                      <span>{skillData.obs_warning}</span>
                    </div>
                  )}

                  {noObs ? (
                    <div style={{
                      ...CARD,
                      textAlign: 'center',
                      padding: '32px 20px',
                      color: 'rgba(255,255,255,0.35)',
                      fontSize: t.fontSize.base,
                      lineHeight: 1.6,
                    }}>
                      No observations available for verification at this location.
                      Check back when additional observation data is ingested.
                    </div>
                  ) : (
                    <>
                      {/* Stat badges — one row per model */}
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '24px' }}>
                        {selectedModels.map(m => {
                          const mData = skillData.models?.[m];
                          if (!mData) return null;
                          const s = mData.summary || {};
                          const color = MODEL_COLORS[m];
                          const mSSR = s.mean_ssr;
                          const mCorr = s.correlation;
                          const stats = [
                            { label: 'Mean SSR', value: mSSR != null ? mSSR.toFixed(3) : 'N/A', color: ssrColor(mSSR) },
                            { label: 'Corr', value: mCorr != null ? mCorr.toFixed(3) : 'N/A', color: corrColor(mCorr) },
                            { label: 'Mean CRPS', value: s.mean_crps != null ? s.mean_crps.toFixed(3) : 'N/A', color: 'rgba(255,255,255,0.85)' },
                            { label: 'Bias', value: s.bias != null ? s.bias.toFixed(3) : 'N/A', color: 'rgba(255,255,255,0.85)' },
                            { label: 'MAE', value: s.mae != null ? s.mae.toFixed(3) : 'N/A', color: 'rgba(255,255,255,0.85)' },
                            { label: 'RMSE', value: s.rmse != null ? s.rmse.toFixed(3) : 'N/A', color: 'rgba(255,255,255,0.85)' },
                          ];
                          return (
                            <div key={m} style={{
                              background: 'rgba(255,255,255,0.04)',
                              borderRadius: '10px',
                              padding: '12px 16px',
                              border: '1px solid rgba(255,255,255,0.07)',
                              borderLeft: `3px solid ${color}`,
                              display: 'flex',
                              alignItems: 'center',
                              gap: '16px',
                              flexWrap: 'wrap',
                            }}>
                              {/* Model name */}
                              <span style={{
                                fontWeight: '700', fontSize: t.fontSize.base, color,
                                minWidth: '48px',
                              }}>
                                {m}
                              </span>
                              {/* Stat chips */}
                              {stats.map(({ label, value, color: vc }) => (
                                <div key={label} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                                  <span style={{ color: vc, fontSize: t.fontSize.md, fontWeight: '700', lineHeight: 1 }}>{value}</span>
                                  <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: t.fontSize.micro, marginTop: '2px', whiteSpace: 'nowrap' }}>{label}</span>
                                </div>
                              ))}
                            </div>
                          );
                        })}
                      </div>

                      {/* Aggregate comparison — one bar per model, per metric */}
                      <div style={{ marginBottom: '26px' }}>
                        <div style={SUBHEAD}>
                          <span style={{ fontWeight: '600' }}>
                            Aggregate over {obsHours.length} verified lead time{obsHours.length === 1 ? '' : 's'}
                          </span>
                          <span style={{ fontSize: t.fontSize.micro, color: 'rgba(255,255,255,0.3)' }}>
                            {yAxisUnit} — SSR and correlation are unitless
                          </span>
                        </div>
                        <div style={SMALL_GRID}>
                          {SKILL_SUMMARY_METRICS.map(({ key, label, hint, refLine, decimals }) => (
                            <AggregateBar
                              key={key}
                              label={label}
                              hint={hint}
                              models={selectedModels}
                              values={selectedModels.map(m => skillData.models?.[m]?.summary?.[key] ?? null)}
                              refLine={refLine}
                              decimals={decimals}
                            />
                          ))}
                        </div>
                      </div>

                      {/* Per-lead-time comparison — one line per model, per metric */}
                      <div>
                        <div style={SUBHEAD}>
                          <span style={{ fontWeight: '600' }}>By lead time</span>
                          {selectedModels.map(m => (
                            <span key={m} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                              <span style={{ display: 'inline-block', width: '16px', height: '2px', background: MODEL_COLORS[m], borderRadius: '1px' }} />
                              <span style={{ fontSize: t.fontSize.xs }}>{m}</span>
                              <span style={{ fontSize: t.fontSize.micro, color: 'rgba(255,255,255,0.3)' }}>
                                ({skillData.models?.[m]?.hours?.length || 0} pts)
                              </span>
                            </span>
                          ))}
                        </div>
                        <div style={SMALL_GRID}>
                          {SKILL_METRICS.map(({ key, label, hint, refLine, decimals }) => (
                            <LeadTimeChart
                              key={key}
                              label={label}
                              hint={hint}
                              metricKey={key}
                              rows={skillRows[key]}
                              models={selectedModels}
                              refLine={refLine}
                              decimals={decimals}
                            />
                          ))}
                        </div>
                      </div>
                    </>
                  )}
                </>
              );
            })()}

            {!skillLoading && !skillData && (
              <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.base, padding: '20px 0' }}>
                Skill verification data unavailable. Check API connectivity.
              </div>
            )}
          </div>
        )}

        {/* ── Section 5: Advanced Metrics (collapsible, point mode) ── */}
        {!isRegionMode && hasRun && (
          <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '20px', marginBottom: '28px' }}>
            <button
              onClick={() => setShowAdvanced(v => !v)}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: '8px',
                color: 'rgba(255,255,255,0.7)', fontSize: t.fontSize.md, fontWeight: '600',
                letterSpacing: '0.02em',
                padding: '0 0 12px 0',
              }}
            >
              <span style={{ fontSize: t.fontSize.xs }}>{showAdvanced ? '▼' : '▶'}</span>
              Advanced metrics
            </button>

            {showAdvanced && (
              <div>
                {/* Controls */}
                <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap', marginBottom: '20px', alignItems: 'flex-end' }}>
                  <div>
                    <div style={LABEL}>Threshold</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <input
                        type="number"
                        value={threshold}
                        onChange={e => setThreshold(Number(e.target.value))}
                        style={{ ...INPUT, width: '64px' }}
                      />
                      <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.sm }}>{thresholdUnit}</span>
                    </div>
                  </div>
                  <div>
                    <div style={LABEL}>FSS Window</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <input
                        type="number"
                        value={fssWindow}
                        min={1}
                        onChange={e => setFssWindow(Math.max(1, Number(e.target.value)))}
                        style={{ ...INPUT, width: '56px' }}
                      />
                      <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.sm }}>
                        × {fssWindow} grid points (= {(fssWindow * 0.5).toFixed(1)}°)
                      </span>
                    </div>
                  </div>
                </div>

                {/* Run + charts */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '16px', flexWrap: 'wrap' }}>
                  <button
                    onClick={handleRunCategorical}
                    disabled={catLoading || !validLocation}
                    style={{
                      background: (!catLoading && validLocation) ? '#9b59b6' : 'rgba(255,255,255,0.08)',
                      color: (!catLoading && validLocation) ? 'white' : 'rgba(255,255,255,0.25)',
                      border: 'none', borderRadius: t.radius, padding: '7px 18px',
                      fontSize: t.fontSize.base, fontWeight: '700',
                      cursor: (!catLoading && validLocation) ? 'pointer' : 'not-allowed',
                      display: 'flex', alignItems: 'center', gap: '6px', transition: 'background 0.15s',
                    }}
                  >
                    {catLoading ? '⏳ Computing…' : '▶ Run advanced metrics'}
                  </button>
                  <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: t.fontSize.sm }}>
                    CSI · POD · FAR · FSS per model, over a {fssWindow}×{fssWindow}-cell neighbourhood at the point
                  </span>
                </div>

                {catError && (
                  <div style={{ ...CARD, color: '#e74c3c', fontSize: t.fontSize.sm, marginBottom: '16px' }}>
                    {catError}
                  </div>
                )}

                {catData && !catError && (() => {
                  const anyData = selectedModels.some(m => (catData.models?.[m]?.length || 0) > 0);
                  if (!anyData) {
                    return (
                      <div style={{ ...CARD, textAlign: 'center', padding: '24px', color: 'rgba(255,255,255,0.4)', fontSize: t.fontSize.sm }}>
                        No overlapping forecast/observation data for this location, threshold, and lead-time range.
                      </div>
                    );
                  }
                  return (
                    <>
                    {/* Aggregate — scores pooled over every verified lead time */}
                    <div style={{ marginBottom: '26px' }}>
                      <div style={SUBHEAD}>
                        <span style={{ fontWeight: '600' }}>Aggregate</span>
                        <span style={{ fontSize: t.fontSize.micro, color: 'rgba(255,255,255,0.3)' }}>
                          CSI / POD / FAR pooled from hit-miss-false-alarm counts across lead times
                        </span>
                      </div>
                      <div style={SMALL_GRID}>
                        {CAT_SUMMARY_METRICS.map(({ key, label, hint, decimals }) => (
                          <AggregateBar
                            key={key}
                            label={label}
                            hint={hint}
                            models={selectedModels}
                            values={selectedModels.map(m => catData.summaries?.[m]?.[key] ?? null)}
                            decimals={decimals}
                          />
                        ))}
                      </div>
                    </div>

                    <div style={SUBHEAD}><span style={{ fontWeight: '600' }}>By lead time</span></div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
                      {CAT_METRICS.map(({ key, label, hint }) => (
                        <div key={key} style={{ ...CARD, padding: '14px 12px 8px' }}>
                          <div style={{ fontSize: t.fontSize.md, fontWeight: 600, color: 'rgba(255,255,255,0.85)' }}>{label}</div>
                          <div style={{ fontSize: t.fontSize.xs, color: 'rgba(255,255,255,0.4)', marginBottom: '6px' }}>{hint}</div>
                          <div style={{ height: '180px' }}>
                            <ResponsiveContainer width="100%" height="100%">
                              <LineChart data={buildCatRows(key)} margin={{ top: 6, right: 16, left: -8, bottom: 20 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                                <XAxis dataKey="hour" stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 10 }} tickFormatter={h => `+${h}h`} />
                                <YAxis stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 10 }} width={34} />
                                <Tooltip
                                  contentStyle={TOOLTIP_STYLE}
                                  formatter={(value, name) => [value != null ? Number(value).toFixed(3) : 'N/A', name.replace(`${key}_`, '')]}
                                  labelFormatter={h => `+${h}h`}
                                />
                                {selectedModels.map(m => {
                                  const nPts = catData.models?.[m]?.length || 0;
                                  return (
                                    <Line
                                      key={m}
                                      type="linear"
                                      dataKey={`${key}_${m}`}
                                      name={`${key}_${m}`}
                                      stroke={MODEL_COLORS[m]}
                                      strokeWidth={2}
                                      connectNulls
                                      dot={{ r: nPts < 10 ? 4 : 2.5, fill: MODEL_COLORS[m], strokeWidth: 0 }}
                                      activeDot={{ r: 5 }}
                                      isAnimationActive={false}
                                    />
                                  );
                                })}
                              </LineChart>
                            </ResponsiveContainer>
                          </div>
                        </div>
                      ))}
                    </div>
                    </>
                  );
                })()}

                {catData && catData.threshold_info && (
                  <div style={{ marginTop: '10px', fontSize: t.fontSize.xs, color: 'rgba(255,255,255,0.35)' }}>
                    Threshold {catData.threshold_info.unit === 'm/s'
                      ? `${catData.threshold_info.threshold_ms} m/s`
                      : `${catData.threshold_info.threshold_mm_6h} mm/6h`}
                    {catData.bbox && <> · neighbourhood bbox [{catData.bbox.join(', ')}]</>}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── Spatial maps by model (region mode) ── */}
        {isRegionMode && hasRegion && hasRunRegion && (
          <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '24px', marginBottom: '28px' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px', marginBottom: '14px', flexWrap: 'wrap' }}>
              <h3 style={{ ...SECTION_TITLE, margin: 0 }}>Spatial maps by model</h3>
              <span style={{ fontSize: t.fontSize.micro, color: 'rgba(255,255,255,0.25)', letterSpacing: '0.04em' }}>
                Each metric uses a fixed colour scale, so the maps are directly comparable
              </span>
            </div>

            {/* Controls */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.sm }}>Metric</span>
                <select
                  value={mapMetric}
                  onChange={e => setMapMetric(e.target.value)}
                  aria-label="Spatial metric"
                  style={{ ...INPUT, width: 'auto', cursor: 'pointer' }}
                >
                  {SPATIAL_MAP_METRICS.map(({ key, label }) => (
                    <option key={key} value={key} style={{ background: '#1a2535' }}>{label}</option>
                  ))}
                </select>
              </div>

              <button
                onClick={handleRunModelMaps}
                disabled={mapsRunning}
                style={{
                  background: mapsRunning ? 'rgba(255,255,255,0.08)' : '#9b59b6',
                  color: mapsRunning ? 'rgba(255,255,255,0.25)' : 'white',
                  border: 'none', borderRadius: t.radius, padding: '7px 18px',
                  fontSize: t.fontSize.base, fontWeight: '700',
                  cursor: mapsRunning ? 'not-allowed' : 'pointer',
                  display: 'flex', alignItems: 'center', gap: '6px', transition: 'background 0.15s',
                }}
              >
                {mapsRunning ? '⏳ Computing…' : '▶ Compute maps'}
              </button>

              <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: t.fontSize.sm }}>
                One map per selected model
                {SPATIAL_MAP_METRICS.find(x => x.key === mapMetric)?.requiresThreshold
                  && ` · threshold > ${regionThreshold} ${thresholdUnit}`}
              </span>
            </div>

            {Object.keys(modelMaps).length === 0 ? (
              <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.base, padding: '16px 0', textAlign: 'center' }}>
                Pick a metric and click <strong style={{ color: 'rgba(255,255,255,0.5)' }}>▶ Compute maps</strong>.
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(420px, 100%), 1fr))', gap: '16px' }}>
                {selectedModels.map(m => {
                  const st = modelMaps[m];
                  return (
                    <div key={m} style={{
                      background: 'rgba(255,255,255,0.04)', borderRadius: '10px',
                      border: '1px solid rgba(255,255,255,0.08)',
                      borderLeft: `3px solid ${MODEL_COLORS[m]}`, overflow: 'hidden',
                    }}>
                      <div style={{
                        padding: '8px 12px', borderBottom: '1px solid rgba(255,255,255,0.06)',
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      }}>
                        <span style={{ fontSize: t.fontSize.sm, fontWeight: '700', color: MODEL_COLORS[m] }}>{m}</span>
                        {st?.url && (
                          <button
                            onClick={() => downloadMap(m, st.url)}
                            title="Download PNG"
                            style={{
                              fontSize: t.fontSize.base, color: 'rgba(255,255,255,0.45)',
                              background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)',
                              borderRadius: '5px', cursor: 'pointer', padding: '2px 7px', lineHeight: 1,
                            }}
                          >⬇</button>
                        )}
                      </div>
                      <div style={{ minHeight: '200px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        {st?.loading && (
                          <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.4)', fontSize: t.fontSize.sm }}>
                            <div style={{ fontSize: t.fontSize.statLg, marginBottom: '8px' }}>⏳</div>Computing…
                          </div>
                        )}
                        {st && !st.loading && st.error && (
                          <div style={{ color: '#e74c3c', fontSize: t.fontSize.xs, padding: '16px', textAlign: 'center' }}>
                            ⚠️ {st.error}
                          </div>
                        )}
                        {st && !st.loading && !st.error && st.url && (
                          <img src={st.url} alt={`${m} ${mapMetric} map`} style={{ width: '100%', display: 'block' }} />
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* ── Model-difference map (region mode) ── */}
        {isRegionMode && hasRegion && hasRunRegion && selectedModels.length >= 2 && (
          <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '24px', marginBottom: '28px' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px', marginBottom: '14px', flexWrap: 'wrap' }}>
              <h3 style={{ ...SECTION_TITLE, margin: 0 }}>Difference map (A − B)</h3>
              <span style={{ fontSize: t.fontSize.micro, color: 'rgba(255,255,255,0.25)', letterSpacing: '0.04em' }}>
                Uses the metric picked above · diverging scale centred at 0
              </span>
            </div>

            {/* A/B pickers */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
              {[['A', effDiffA, setDiffA], ['B', effDiffB, setDiffB]].map(([side, value, setter]) => (
                <div key={side} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.sm }}>{side}</span>
                  <select
                    value={value || ''}
                    onChange={e => setter(e.target.value)}
                    aria-label={`Model ${side}`}
                    style={{ ...INPUT, width: 'auto', cursor: 'pointer', color: MODEL_COLORS[value] || INPUT.color, fontWeight: 600 }}
                  >
                    {selectedModels.map(m => (
                      <option key={m} value={m} style={{ background: '#1a2535' }}>{m}</option>
                    ))}
                  </select>
                </div>
              ))}

              <button
                onClick={handleRunDiff}
                disabled={diffLoading || !effDiffA || !effDiffB}
                style={{
                  background: (!diffLoading && effDiffA && effDiffB) ? '#e67e22' : 'rgba(255,255,255,0.08)',
                  color: (!diffLoading && effDiffA && effDiffB) ? 'white' : 'rgba(255,255,255,0.25)',
                  border: 'none', borderRadius: t.radius, padding: '7px 18px',
                  fontSize: t.fontSize.base, fontWeight: '700',
                  cursor: (!diffLoading && effDiffA && effDiffB) ? 'pointer' : 'not-allowed',
                  display: 'flex', alignItems: 'center', gap: '6px', transition: 'background 0.15s',
                }}
              >
                {diffLoading ? '⏳ Computing…' : '▶ Compute difference'}
              </button>

              <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: t.fontSize.sm }}>
                {SPATIAL_MAP_METRICS.find(x => x.key === mapMetric)?.label}
                {effDiffA && effDiffB && <> · {effDiffA} − {effDiffB}</>}
              </span>
            </div>

            {diffLoading && <Spinner />}

            {!diffLoading && diffError && (
              <div role="alert" style={{
                ...CARD, borderLeft: '3px solid #e74c3c', color: '#e74c3c',
                fontSize: t.fontSize.sm,
              }}>
                {diffError}
              </div>
            )}

            {/* No shared cells — the endpoint reports this instead of a blank map */}
            {!diffLoading && !diffError && diffData && !diffData.image && (
              <div style={{
                background: 'rgba(243,156,18,0.1)', border: '1px solid rgba(243,156,18,0.3)',
                borderRadius: t.radius, padding: '12px 16px', color: '#f39c12', fontSize: t.fontSize.sm,
              }}>
                ⚠️ {diffData.error}
              </div>
            )}

            {!diffLoading && !diffError && diffData?.image && (
              <div>
                <img
                  src={'data:image/png;base64,' + diffData.image}
                  alt={`${effDiffA} minus ${effDiffB} ${mapMetric} difference map`}
                  style={{
                    maxWidth: '100%', maxHeight: '460px', width: 'auto', display: 'block',
                    margin: '0 auto', borderRadius: '10px', boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
                  }}
                />
                <div style={{ display: 'flex', gap: '16px', marginTop: '10px', justifyContent: 'center', flexWrap: 'wrap' }}>
                  {[
                    { label: 'Shared cells', value: `${diffData.n_common} of ${diffData.n_a}/${diffData.n_b}` },
                    { label: `Mean (${effDiffA} − ${effDiffB})`, value: diffData.mean_diff?.toFixed(4) },
                    { label: 'Largest difference', value: diffData.max_abs_diff?.toFixed(4) },
                  ].map(({ label, value }) => (
                    <div key={label} style={{ textAlign: 'center' }}>
                      <div style={{ color: 'rgba(255,255,255,0.85)', fontSize: t.fontSize.md, fontWeight: '700' }}>
                        {value ?? '—'}
                      </div>
                      <div style={{ color: 'rgba(255,255,255,0.35)', fontSize: t.fontSize.micro, marginTop: '1px' }}>
                        {label}
                      </div>
                    </div>
                  ))}
                  <button
                    onClick={() => downloadMap(`${effDiffA}-minus-${effDiffB}`, 'data:image/png;base64,' + diffData.image)}
                    style={{
                      background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)',
                      borderRadius: '7px', color: 'rgba(255,255,255,0.7)', fontSize: t.fontSize.sm,
                      padding: '5px 12px', cursor: 'pointer', alignSelf: 'center',
                    }}
                  >
                    ⬇ Download
                  </button>
                </div>
              </div>
            )}

            {!diffLoading && !diffError && !diffData && (
              <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.base, padding: '16px 0', textAlign: 'center' }}>
                Pick two models and click <strong style={{ color: 'rgba(255,255,255,0.5)' }}>▶ Compute difference</strong>.
              </div>
            )}
          </div>
        )}

        {/* ── Section 6: Spatial Agreement (region mode) ── */}
        {isRegionMode && hasRegion && hasRunRegion && (
          <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '20px', marginBottom: '16px' }}>
            <h3 style={SECTION_TITLE}>Spatial Agreement Map</h3>

            {/* Region available → controls + map */}
            {selectedRegion && (
              <div>
                {/* Region info pill + controls row */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap', marginBottom: '16px' }}>
                  {/* Region badge */}
                  <span style={{
                    fontSize: t.fontSize.xs, fontWeight: '600', padding: '4px 12px', borderRadius: '20px',
                    background: 'rgba(230,126,34,0.12)', border: '1px solid rgba(230,126,34,0.3)',
                    color: '#e67e22',
                  }}>
                    {selectedRegion.type === 'polygon' ? '⬡ Polygon' : '▭ Rectangle'}
                    {' '}
                    {selectedRegion.bounds.min_lat.toFixed(1)}°–{selectedRegion.bounds.max_lat.toFixed(1)}°N,{' '}
                    {selectedRegion.bounds.min_lon.toFixed(1)}°–{selectedRegion.bounds.max_lon.toFixed(1)}°E
                  </span>

                  {/* Spatial hour input */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.sm }}>Hour</span>
                    <input
                      type="number"
                      value={spatialHour}
                      min={0} max={360}
                      onChange={e => setSpatialHour(Math.max(0, Math.min(360, Number(e.target.value))))}
                      style={{ ...INPUT, width: '60px' }}
                    />
                    <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: t.fontSize.sm }}>h</span>
                  </div>

                  {/* Run button */}
                  <button
                    onClick={handleRunSpatial}
                    disabled={spatialLoading || selectedModels.length < 2}
                    style={{
                      background: (!spatialLoading && selectedModels.length >= 2) ? '#e67e22' : 'rgba(255,255,255,0.08)',
                      color: (!spatialLoading && selectedModels.length >= 2) ? 'white' : 'rgba(255,255,255,0.25)',
                      border: 'none',
                      borderRadius: t.radius,
                      padding: '7px 18px',
                      fontSize: t.fontSize.base,
                      fontWeight: '700',
                      cursor: (!spatialLoading && selectedModels.length >= 2) ? 'pointer' : 'not-allowed',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      transition: 'background 0.15s',
                    }}
                  >
                    {spatialLoading ? '⏳ Computing…' : '▶ Run Map'}
                  </button>

                  {/* Export buttons (only when image is ready) */}
                  {spatialData?.image && !spatialLoading && (
                    <div style={{ display: 'flex', gap: '6px', marginLeft: 'auto' }}>
                      <button
                        onClick={handleSpatialDownload}
                        title="Download PNG"
                        style={{
                          background: 'rgba(255,255,255,0.06)',
                          border: '1px solid rgba(255,255,255,0.12)',
                          borderRadius: '7px',
                          color: 'rgba(255,255,255,0.7)',
                          fontSize: t.fontSize.sm,
                          padding: '5px 12px',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '5px',
                        }}
                      >
                        ⬇ Download
                      </button>
                      <button
                        onClick={handleSpatialShare}
                        title="Copy or share image"
                        style={{
                          background: spatialShareState === 'copied' ? 'rgba(46,204,113,0.15)' : 'rgba(255,255,255,0.06)',
                          border: `1px solid ${spatialShareState === 'copied' ? 'rgba(46,204,113,0.4)' : 'rgba(255,255,255,0.12)'}`,
                          borderRadius: '7px',
                          color: spatialShareState === 'copied' ? '#2ecc71' : 'rgba(255,255,255,0.7)',
                          fontSize: t.fontSize.sm,
                          padding: '5px 12px',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '5px',
                          transition: 'all 0.2s',
                        }}
                      >
                        {spatialShareState === 'copied' ? '✓ Copied!' : '⎘ Share'}
                      </button>
                    </div>
                  )}
                </div>

                {/* Loading spinner */}
                {spatialLoading && <Spinner />}

                {/* Error */}
                {!spatialLoading && spatialData?.error && (
                  <div style={{
                    background: 'rgba(231,76,60,0.08)',
                    border: '1px solid rgba(231,76,60,0.25)',
                    borderRadius: t.radius,
                    padding: '12px 16px',
                    color: '#e74c3c',
                    fontSize: t.fontSize.base,
                  }}>
                    ⚠ {spatialData.error}
                  </div>
                )}

                {/* Result image */}
                {!spatialLoading && spatialData?.image && (
                  <div style={{ marginTop: '8px' }}>
                    <img
                      src={'data:image/png;base64,' + spatialData.image}
                      alt="Spatial Agreement Map"
                      style={{
                        maxWidth: '100%',
                        maxHeight: '420px',
                        width: 'auto',
                        display: 'block',
                        margin: '0 auto',
                        borderRadius: '10px',
                        boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
                      }}
                    />
                    {/* Metadata row */}
                    <div style={{
                      display: 'flex',
                      gap: '16px',
                      marginTop: '10px',
                      justifyContent: 'center',
                      flexWrap: 'wrap',
                    }}>
                      {[
                        { label: 'Models', value: spatialData.n_models },
                        { label: 'Grid points', value: spatialData.n_points?.toLocaleString() },
                        { label: 'Lead time', value: `+${spatialData.hour}h` },
                      ].map(({ label, value }) => (
                        <div key={label} style={{ textAlign: 'center' }}>
                          <div style={{ color: 'rgba(255,255,255,0.85)', fontSize: t.fontSize.md, fontWeight: '700' }}>
                            {value ?? '—'}
                          </div>
                          <div style={{ color: 'rgba(255,255,255,0.35)', fontSize: t.fontSize.micro, marginTop: '1px' }}>
                            {label}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Initial state — region selected but not yet run */}
                {!spatialLoading && !spatialData && (
                  <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.base, padding: '16px 0', textAlign: 'center' }}>
                    Click <strong style={{ color: 'rgba(255,255,255,0.5)' }}>▶ Run Map</strong> to compute model disagreement for the selected region.
                  </div>
                )}
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  );
}
