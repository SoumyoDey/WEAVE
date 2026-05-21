import React, { useState, useEffect } from 'react';
import {
  ComposedChart, LineChart, Line, BarChart, Bar,
  Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { fetchComparisonTimeseries, fetchComparisonSkill, fetchSpatialAgreement } from '../api/comparisonApi';

const MODEL_COLORS = { AIFS: '#3498db', GEFS: '#e74c3c', UKMO: '#2ecc71' };
const MODEL_NAMES  = ['AIFS', 'GEFS', 'UKMO'];

// Temporal accumulation period for each model's precipitation output.
// Values are divided by this factor to convert to mm/h rate before display
// and before computing skill metrics, so cross-model comparisons are fair.
//   AIFS → 6-hour accumulated totals (mm/6h)  ÷ 6 → mm/h
//   GEFS → 3-hour accumulated totals (mm/3h)  ÷ 3 → mm/h
//   UKMO → Hourly instantaneous values (mm/h) ÷ 1 → mm/h (unchanged)
const MODEL_ACCUM_HOURS = { AIFS: 6, GEFS: 3, UKMO: 1 };

// ── Shared style tokens ──────────────────────────────────────────────────────
const CARD = {
  background: 'rgba(255,255,255,0.04)',
  borderRadius: 10,
  padding: '16px 20px',
  border: '1px solid rgba(255,255,255,0.07)',
};

const SECTION_TITLE = {
  color: 'rgba(255,255,255,0.85)',
  fontSize: '14px',
  fontWeight: '600',
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  margin: '0 0 14px 0',
};

const LABEL = {
  fontSize: '11px',
  fontWeight: '600',
  letterSpacing: '0.06em',
  color: 'rgba(255,255,255,0.4)',
  textTransform: 'uppercase',
  marginBottom: '6px',
};

const INPUT = {
  background: 'rgba(255,255,255,0.06)',
  border: '1px solid rgba(255,255,255,0.12)',
  borderRadius: '7px',
  color: 'rgba(255,255,255,0.85)',
  fontSize: '13px',
  padding: '6px 10px',
  outline: 'none',
  width: '80px',
};

const TOOLTIP_STYLE = {
  background: '#1a2535',
  border: '1px solid rgba(255,255,255,0.15)',
  borderRadius: '8px',
  color: 'white',
  fontSize: '12px',
};

// ── Small helpers ────────────────────────────────────────────────────────────
function Spinner() {
  return (
    <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: '14px', padding: '40px 0', textAlign: 'center' }}>
      ⏳ Loading…
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

// ── Custom Tooltip for Forecast Comparison chart ─────────────────────────────
// Always reads raw values from the data row so the tooltip shows actual
// stored values (mm/6h, mm/3h, mm/h) alongside the converted mm/h rate.
function ForecastTooltip({ active, payload, label, selectedModels, normalized }) {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0]?.payload || {};

  const means = selectedModels
    .map(m => {
      const rawMean = row[`${m}_raw_mean`];
      const rawStd  = row[`${m}_raw_std`];
      if (rawMean == null) return null;
      const accumH  = MODEL_ACCUM_HOURS[m] || 1;
      const rateMean = rawMean / accumH;
      const rateStd  = rawStd  != null ? rawStd  / accumH : null;
      return { model: m, rateMean, rateStd, rawMean, rawStd, accumH };
    })
    .filter(Boolean);

  if (!means.length) return null;

  return (
    <div style={{ ...TOOLTIP_STYLE, padding: '10px 14px', minWidth: '210px' }}>
      <div style={{ color: 'rgba(255,255,255,0.5)', fontSize: '11px', marginBottom: '8px' }}>
        +{label}h forecast
        {normalized && <span style={{ color: '#f39c12', marginLeft: '6px' }}>· per-model normalised</span>}
      </div>
      {means.map(({ model, rateMean, rateStd, rawMean, accumH }) => (
        <div key={model} style={{ marginBottom: '6px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ display: 'inline-block', width: '10px', height: '10px', borderRadius: '2px', background: MODEL_COLORS[model] }} />
            <span style={{ color: 'rgba(255,255,255,0.85)', fontWeight: '600', minWidth: '44px' }}>{model}</span>
            <span style={{ color: 'rgba(255,255,255,0.85)', fontWeight: '700' }}>
              {rateMean.toFixed(3)}
              <span style={{ color: 'rgba(255,255,255,0.5)', fontWeight: '400', fontSize: '10px', marginLeft: '2px' }}>mm/h</span>
            </span>
            {rateStd != null && (
              <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: '11px' }}>±{rateStd.toFixed(3)}</span>
            )}
          </div>
          {/* Raw stored value for reference */}
          <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: '10px', marginLeft: '18px', marginTop: '1px' }}>
            raw: {rawMean.toFixed(3)} mm/{accumH}h
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Build merged timeseries dataset ─────────────────────────────────────────
// Step 1 (always): divide each model's values by MODEL_ACCUM_HOURS[m] to
//   convert to mm/h rate. This is the scientific normalisation that makes
//   AIFS (6h accum), GEFS (3h accum) and UKMO (hourly) directly comparable.
// Step 2 (optional, normalize=true): further divide by each model's peak
//   rate so all curves sit in [0, 1]. Useful when models genuinely forecast
//   different magnitudes even after the unit conversion.
// Raw values are always stored alongside for the tooltip.
function buildMergedTimeseries(tsData, selectedModels, normalize = false) {
  if (!tsData) return [];

  // Per-model peak RATE (after accum conversion) for optional normalisation
  const modelPeaks = {};
  if (normalize) {
    selectedModels.forEach(m => {
      const ah = MODEL_ACCUM_HOURS[m] || 1;
      if (tsData[m]) {
        const peak = Math.max(...tsData[m].map(r => ((r.mean || 0) + (r.std || 0)) / ah));
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
      const entry  = tsData[m]?.find(r => r.hour === hour);
      if (entry) {
        const ah   = MODEL_ACCUM_HOURS[m] || 1;
        const norm = normalize ? (modelPeaks[m] || 1) : 1;
        const mean = entry.mean != null ? entry.mean : null;
        const std  = entry.std  != null ? entry.std  : 0;
        // Display values (mm/h, optionally normalised)
        row[`${m}_mean`] = mean != null ? (mean / ah) / norm : null;
        row[`${m}_hi`]   = mean != null ? ((mean + std) / ah) / norm : null;
        row[`${m}_lo`]   = mean != null ? Math.max(0, (mean - std) / ah) / norm : null;
        // Raw values always kept for tooltip display
        row[`${m}_raw_mean`] = mean;
        row[`${m}_raw_std`]  = entry.std;
      }
    });
    return row;
  });
}

// Computes ratio of max-to-min peak RATE across models.
// After the accum conversion this should be small; a large ratio still
// indicates a genuine magnitude difference (not just a units issue).
function computeScaleRatio(tsData, models) {
  const peaks = models
    .map(m => {
      const ah = MODEL_ACCUM_HOURS[m] || 1;
      return tsData[m]
        ? Math.max(...tsData[m].map(r => ((r.mean || 0) + (r.std || 0)) / ah))
        : 0;
    })
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
}) {
  // Controls
  const [lat, setLat] = useState(defaultLocation ? String(defaultLocation.lat) : '');
  const [lon, setLon] = useState(defaultLocation ? String(defaultLocation.lon) : '');
  const [selectedModels, setSelectedModels] = useState(['AIFS', 'GEFS', 'UKMO']);
  const [hourMin, setHourMin] = useState(0);
  const [hourMax, setHourMax] = useState(168);
  const [spatialHour, setSpatialHour] = useState(defaultHour || 6);
  const [showSpreadBands, setShowSpreadBands] = useState(true);
  const [normalizeScales, setNormalizeScales] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [threshold, setThreshold] = useState(25);
  const [fssWindow, setFssWindow] = useState(5);

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

  // Derived
  const parsedLat = parseFloat(lat);
  const parsedLon = parseFloat(lon);
  const validLocation = !isNaN(parsedLat) && !isNaN(parsedLon);
  const canRun = selectedModels.length >= 2 && validLocation && hourMin < hourMax;

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
    setTsLoading(false);
    if (skill.status === 'fulfilled') setSkillData(skill.value);
    setSkillLoading(false);
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

  // Derived chart data
  const mergedTs = buildMergedTimeseries(tsData, selectedModels, normalizeScales);
  // For precipitation, all display values are in mm/h (rate) after accum conversion
  const yAxisUnit     = selectedVariable === 'wind' ? 'm/s' : 'mm/h';
  const thresholdUnit = selectedVariable === 'wind' ? 'm/s' : 'mm/6h';
  // After the accum conversion the ratio should be much smaller than the raw ratio
  const scaleRatio = tsData ? computeScaleRatio(tsData, selectedModels) : 1;
  const hasScaleMismatch = scaleRatio > 5; // still >5× after unit fix → warn

  return (
    <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden', flex: 1 }}>
      {/* ── Header ── */}
      <div style={{ padding: '16px 30px 10px', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
        <h2 style={{ color: 'white', margin: '0 0 4px 0', fontSize: '18px', fontWeight: '600' }}>
          ⚖️ Model Comparison
        </h2>
        <p style={{ color: 'rgba(255,255,255,0.4)', margin: '0 0 8px 0', fontSize: '13px' }}>
          Configure models, location and lead times then click Run.
        </p>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {/* Variable badge */}
          <span style={{
            fontSize: '11px', fontWeight: '600', padding: '3px 10px', borderRadius: '20px',
            background: 'rgba(52,152,219,0.15)', border: '1px solid rgba(52,152,219,0.3)',
            color: '#3498db',
          }}>
            {selectedVariable === 'precipitation' ? 'Precipitation' : 'Wind'}
          </span>
          {/* Location badge */}
          {validLocation && (
            <span style={{
              fontSize: '11px', fontWeight: '600', padding: '3px 10px', borderRadius: '20px',
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
          {/* LOCATION */}
          <div style={{ marginBottom: '20px' }}>
            <div style={LABEL}>Location</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: '12px' }}>Lat</span>
                <input
                  type="number"
                  value={lat}
                  onChange={e => setLat(e.target.value)}
                  placeholder="e.g. 37.5"
                  style={INPUT}
                />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: '12px' }}>Lon</span>
                <input
                  type="number"
                  value={lon}
                  onChange={e => setLon(e.target.value)}
                  placeholder="e.g. -122.4"
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
                    fontSize: '12px',
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

          {/* MODELS */}
          <div style={{ marginBottom: '20px' }}>
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
                      fontSize: '13px', fontWeight: '600',
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
              <div style={{ color: '#f39c12', fontSize: '11px', marginTop: '6px' }}>
                Select at least 2 models to compare.
              </div>
            )}
          </div>

          {/* LEAD TIMES */}
          <div style={{ marginBottom: '24px' }}>
            <div style={LABEL}>Lead Times</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: '12px' }}>Min</span>
                <input
                  type="number"
                  value={hourMin}
                  min={0} max={360}
                  onChange={e => handleHourMin(e.target.value)}
                  style={{ ...INPUT, width: '64px' }}
                />
                <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: '12px' }}>h</span>
              </div>
              <div style={{
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
                <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: '12px' }}>Max</span>
                <input
                  type="number"
                  value={hourMax}
                  min={0} max={360}
                  onChange={e => handleHourMax(e.target.value)}
                  style={{ ...INPUT, width: '64px' }}
                />
                <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: '12px' }}>h</span>
              </div>
            </div>
            {hourMin >= hourMax && (
              <div style={{ color: '#f39c12', fontSize: '11px', marginTop: '6px' }}>
                Min must be less than Max.
              </div>
            )}
          </div>

          {/* Run button */}
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button
              onClick={handleRun}
              disabled={!canRun}
              style={{
                background: canRun ? '#3498db' : 'rgba(255,255,255,0.08)',
                color: canRun ? 'white' : 'rgba(255,255,255,0.25)',
                border: 'none',
                borderRadius: '8px',
                padding: '9px 24px',
                fontSize: '14px',
                fontWeight: '700',
                cursor: canRun ? 'pointer' : 'not-allowed',
                display: 'flex',
                alignItems: 'center',
                gap: '7px',
                transition: 'background 0.15s',
              }}
            >
              ▶ Run Comparison
            </button>
          </div>
        </div>

        {/* ── Empty state (before first run) ── */}
        {!hasRun && (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            textAlign: 'center', color: 'rgba(255,255,255,0.25)',
            padding: '60px 20px',
          }}>
            <div>
              <div style={{ fontSize: '64px', marginBottom: '16px', lineHeight: 1 }}>⚖️</div>
              <p style={{ fontSize: '16px', margin: '0 0 8px 0', color: 'rgba(255,255,255,0.4)' }}>
                Configure the comparison above and click Run
              </p>
              <p style={{ fontSize: '13px', margin: 0 }}>No results yet</p>
            </div>
          </div>
        )}

        {/* ── Section 3: Forecast Comparison ── */}
        {hasRun && (
          <div style={{ marginBottom: '28px' }}>
            <h3 style={{ ...SECTION_TITLE, marginBottom: '6px' }}>Forecast Comparison</h3>
            {/* Accumulation conversion note — always visible for precipitation */}
            {selectedVariable !== 'wind' && (
              <div style={{
                display: 'flex', gap: '10px', flexWrap: 'wrap',
                marginBottom: '12px', alignItems: 'center',
              }}>
                <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.25)' }}>
                  Converted to mm/h —
                </span>
                {selectedModels.map(m => {
                  const ah = MODEL_ACCUM_HOURS[m] || 1;
                  return (
                    <span key={m} style={{
                      fontSize: '11px', fontWeight: '600',
                      color: MODEL_COLORS[m],
                      opacity: 0.75,
                    }}>
                      {m} {ah > 1 ? `÷${ah}` : '(native)'}
                    </span>
                  );
                })}
                <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.18)', marginLeft: '4px' }}>
                  Hover for raw values
                </span>
              </div>
            )}

            {tsLoading && <Spinner />}

            {!tsLoading && tsData && (
              <>
                {/* Scale mismatch warning banner */}
                {hasScaleMismatch && !normalizeScales && (
                  <div style={{
                    background: 'rgba(243,156,18,0.08)',
                    border: '1px solid rgba(243,156,18,0.25)',
                    borderRadius: '8px',
                    padding: '9px 14px',
                    marginBottom: '12px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '12px',
                    flexWrap: 'wrap',
                  }}>
                    <span style={{ color: '#f39c12', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      ⚠ Models differ by <strong>{scaleRatio.toFixed(0)}×</strong> in magnitude — one or more lines may be invisible.
                      Tooltip hover still shows exact values.
                    </span>
                    <button
                      onClick={() => setNormalizeScales(true)}
                      style={{
                        background: 'rgba(243,156,18,0.15)',
                        border: '1px solid rgba(243,156,18,0.4)',
                        borderRadius: '6px',
                        color: '#f39c12',
                        fontSize: '12px',
                        fontWeight: '600',
                        padding: '4px 12px',
                        cursor: 'pointer',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      Enable normalise
                    </button>
                  </div>
                )}

                {/* Legend row */}
                <div style={{ display: 'flex', gap: '12px', marginBottom: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
                  {selectedModels.map(m => {
                    const ah        = MODEL_ACCUM_HOURS[m] || 1;
                    const modelRows = tsData[m];
                    const lastRow   = modelRows?.length > 0 ? modelRows[modelRows.length - 1] : null;
                    // Show the rate value (mm/h) in the legend chip
                    const rateValue = lastRow?.mean != null ? lastRow.mean / ah : null;
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
                        <span style={{ color: 'rgba(255,255,255,0.85)', fontSize: '12px', fontWeight: '600' }}>{m}</span>
                        {rateValue != null && (
                          <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: '11px' }}>
                            {rateValue.toFixed(3)} {yAxisUnit}
                          </span>
                        )}
                      </div>
                    );
                  })}

                  {/* Toggles */}
                  <div style={{ display: 'flex', gap: '14px', marginLeft: 'auto', alignItems: 'center' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'rgba(255,255,255,0.5)', fontSize: '12px', cursor: 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={normalizeScales}
                        onChange={e => setNormalizeScales(e.target.checked)}
                        style={{ accentColor: '#f39c12', cursor: 'pointer' }}
                      />
                      <span style={{ color: normalizeScales ? '#f39c12' : undefined }}>Normalise</span>
                    </label>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'rgba(255,255,255,0.5)', fontSize: '12px', cursor: 'pointer' }}>
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
                        content={<ForecastTooltip selectedModels={selectedModels} normalized={normalizeScales} yAxisUnit={yAxisUnit} />}
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
                      {/* Per-model: band areas + mean line */}
                      {selectedModels.map(m => {
                        const color = MODEL_COLORS[m];
                        return (
                          <React.Fragment key={m}>
                            {showSpreadBands && (
                              <>
                                {/* Upper band fill (model color, low opacity) */}
                                <Area
                                  dataKey={`${m}_hi`}
                                  stroke="none"
                                  fill={color}
                                  fillOpacity={0.12}
                                  legendType="none"
                                  isAnimationActive={false}
                                />
                                {/* Lower band fill (background color — creates gap effect) */}
                                <Area
                                  dataKey={`${m}_lo`}
                                  stroke="none"
                                  fill="#0f1923"
                                  fillOpacity={1}
                                  legendType="none"
                                  isAnimationActive={false}
                                />
                              </>
                            )}
                            {/* Mean line */}
                            <Line
                              type="monotone"
                              dataKey={`${m}_mean`}
                              stroke={color}
                              strokeWidth={2.5}
                              dot={false}
                              legendType="none"
                              isAnimationActive={false}
                            />
                          </React.Fragment>
                        );
                      })}
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </>
            )}

            {!tsLoading && !tsData && (
              <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: '13px', padding: '20px 0' }}>
                Forecast timeseries unavailable. Check API connectivity.
              </div>
            )}
          </div>
        )}

        {/* ── Section 4: Skill Verification ── */}
        {hasRun && (
          <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '24px', marginBottom: '28px' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px', marginBottom: '14px' }}>
              <h3 style={{ ...SECTION_TITLE, margin: 0 }}>Skill Verification</h3>
              {selectedVariable !== 'wind' && (
                <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.25)', letterSpacing: '0.04em' }}>
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
                      borderRadius: '8px',
                      padding: '10px 14px',
                      marginBottom: '16px',
                      color: '#f39c12',
                      fontSize: '13px',
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
                      fontSize: '13px',
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
                                fontWeight: '700', fontSize: '13px', color,
                                minWidth: '48px',
                              }}>
                                {m}
                              </span>
                              {/* Stat chips */}
                              {stats.map(({ label, value, color: vc }) => (
                                <div key={label} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                                  <span style={{ color: vc, fontSize: '14px', fontWeight: '700', lineHeight: 1 }}>{value}</span>
                                  <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: '10px', marginTop: '2px', whiteSpace: 'nowrap' }}>{label}</span>
                                </div>
                              ))}
                            </div>
                          );
                        })}
                      </div>

                      {/* SSR grouped bar chart */}
                      <div style={{ marginBottom: '24px' }}>
                        <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: '12px', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                          <span style={{ fontWeight: '600' }}>Spread-Skill Ratio by Lead Time</span>
                          {selectedModels.map(m => (
                            <span key={m} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                              <span style={{ display: 'inline-block', width: '10px', height: '10px', background: MODEL_COLORS[m], borderRadius: '2px' }} />
                              <span style={{ fontSize: '11px' }}>{m}</span>
                            </span>
                          ))}
                        </div>
                        <div style={{ height: '220px' }}>
                          <ResponsiveContainer width="100%" height="100%">
                            <BarChart
                              data={obsHours.map(hour => {
                                const row = { hour };
                                selectedModels.forEach(m => {
                                  const hourEntry = skillData.models?.[m]?.hours?.find(h => h.hour === hour);
                                  row[`ssr_${m}`] = hourEntry ? hourEntry.ssr : null;
                                });
                                return row;
                              })}
                              margin={{ top: 8, right: 20, left: 0, bottom: 24 }}
                            >
                              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                              <XAxis
                                dataKey="hour"
                                stroke="rgba(255,255,255,0.3)"
                                tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }}
                                tickFormatter={h => `+${h}h`}
                                label={{ value: 'Forecast Hour', position: 'insideBottom', offset: -10, fill: 'rgba(255,255,255,0.4)', fontSize: 11 }}
                              />
                              <YAxis
                                stroke="rgba(255,255,255,0.3)"
                                tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }}
                                label={{ value: 'SSR', angle: -90, position: 'insideLeft', fill: 'rgba(255,255,255,0.4)', fontSize: 11 }}
                              />
                              <Tooltip
                                contentStyle={TOOLTIP_STYLE}
                                formatter={(value, name) => {
                                  const m = name.replace('ssr_', '');
                                  return [value != null ? Number(value).toFixed(3) : 'N/A', `${m} SSR`];
                                }}
                                labelFormatter={h => `+${h}h`}
                              />
                              <ReferenceLine
                                y={1}
                                stroke="rgba(255,255,255,0.45)"
                                strokeDasharray="6 3"
                                label={{ value: 'ideal (1.0)', position: 'right', fill: 'rgba(255,255,255,0.4)', fontSize: 10 }}
                              />
                              {selectedModels.map(m => (
                                <Bar
                                  key={m}
                                  dataKey={`ssr_${m}`}
                                  name={`ssr_${m}`}
                                  fill={MODEL_COLORS[m]}
                                  radius={[3, 3, 0, 0]}
                                  maxBarSize={28}
                                />
                              ))}
                            </BarChart>
                          </ResponsiveContainer>
                        </div>
                      </div>

                      {/* CRPS line chart */}
                      <div>
                        <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: '12px', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                          <span style={{ fontWeight: '600' }}>CRPS by Lead Time</span>
                          {selectedModels.map(m => {
                            const mHours = skillData.models?.[m]?.hours?.length || 0;
                            return (
                              <span key={m} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                <span style={{ display: 'inline-block', width: '16px', height: '2px', background: MODEL_COLORS[m], borderRadius: '1px' }} />
                                <span style={{ fontSize: '11px' }}>{m}</span>
                                <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.3)' }}>({mHours} pts)</span>
                              </span>
                            );
                          })}
                        </div>
                        <div style={{ height: '220px' }}>
                          <ResponsiveContainer width="100%" height="100%">
                            <LineChart
                              data={(() => {
                                // Union of all hours across all models (not just obsHours)
                                const allHours = new Set();
                                selectedModels.forEach(m => {
                                  skillData.models?.[m]?.hours?.forEach(h => allHours.add(h.hour));
                                });
                                return Array.from(allHours).sort((a, b) => a - b).map(hour => {
                                  const row = { hour };
                                  selectedModels.forEach(m => {
                                    const hourEntry = skillData.models?.[m]?.hours?.find(h => h.hour === hour);
                                    row[`crps_${m}`] = hourEntry ? hourEntry.crps : null;
                                  });
                                  return row;
                                });
                              })()}
                              margin={{ top: 8, right: 20, left: 0, bottom: 24 }}
                            >
                              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                              <XAxis
                                dataKey="hour"
                                stroke="rgba(255,255,255,0.3)"
                                tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }}
                                tickFormatter={h => `+${h}h`}
                                label={{ value: 'Forecast Hour', position: 'insideBottom', offset: -10, fill: 'rgba(255,255,255,0.4)', fontSize: 11 }}
                              />
                              <YAxis
                                stroke="rgba(255,255,255,0.3)"
                                tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }}
                                label={{ value: 'CRPS', angle: -90, position: 'insideLeft', fill: 'rgba(255,255,255,0.4)', fontSize: 11 }}
                              />
                              <Tooltip
                                contentStyle={TOOLTIP_STYLE}
                                formatter={(value, name) => {
                                  const m = name.replace('crps_', '');
                                  return [value != null ? Number(value).toFixed(4) : 'N/A', `${m} CRPS`];
                                }}
                                labelFormatter={h => `+${h}h`}
                              />
                              {selectedModels.map(m => {
                                // Use fewer dots for sparse models (< 10 points)
                                const nPts = skillData.models?.[m]?.hours?.length || 0;
                                return (
                                  <Line
                                    key={m}
                                    type="linear"
                                    dataKey={`crps_${m}`}
                                    name={`crps_${m}`}
                                    stroke={MODEL_COLORS[m]}
                                    strokeWidth={nPts < 10 ? 2.5 : 2}
                                    connectNulls
                                    dot={{ r: nPts < 10 ? 5 : 3, fill: MODEL_COLORS[m], strokeWidth: 0 }}
                                    activeDot={{ r: 6 }}
                                    isAnimationActive={false}
                                  />
                                );
                              })}
                            </LineChart>
                          </ResponsiveContainer>
                        </div>
                      </div>
                    </>
                  )}
                </>
              );
            })()}

            {!skillLoading && !skillData && (
              <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: '13px', padding: '20px 0' }}>
                Skill verification data unavailable. Check API connectivity.
              </div>
            )}
          </div>
        )}

        {/* ── Section 5: Advanced Metrics (collapsible) ── */}
        {hasRun && (
          <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '20px', marginBottom: '28px' }}>
            <button
              onClick={() => setShowAdvanced(v => !v)}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: '8px',
                color: 'rgba(255,255,255,0.7)', fontSize: '14px', fontWeight: '600',
                textTransform: 'uppercase', letterSpacing: '0.08em',
                padding: '0 0 12px 0',
              }}
            >
              <span style={{ fontSize: '11px' }}>{showAdvanced ? '▼' : '▶'}</span>
              Advanced Metrics
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
                      <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: '12px' }}>{thresholdUnit}</span>
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
                      <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: '12px' }}>
                        × {fssWindow} grid points (= {(fssWindow * 0.5).toFixed(1)}°)
                      </span>
                    </div>
                  </div>
                </div>

                {/* Coming soon placeholder */}
                <div style={{
                  ...CARD,
                  textAlign: 'center',
                  padding: '32px 20px',
                  color: 'rgba(255,255,255,0.25)',
                  fontSize: '13px',
                  lineHeight: 1.6,
                }}>
                  <div style={{ fontSize: '28px', marginBottom: '10px' }}>🔬</div>
                  Advanced metric charts — coming in next update
                  <div style={{ fontSize: '11px', marginTop: '6px', color: 'rgba(255,255,255,0.18)' }}>
                    CSI · POD · FAR · FSS charts will appear here
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Section 6: Spatial Agreement ── */}
        {hasRun && (
          <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '20px', marginBottom: '16px' }}>
            <h3 style={SECTION_TITLE}>Spatial Agreement Map</h3>

            {/* No region drawn yet → nudge */}
            {!selectedRegion && (
              <div style={{
                borderRadius: '10px',
                padding: '20px 24px',
                border: '1px dashed rgba(255,255,255,0.15)',
                background: 'rgba(255,255,255,0.02)',
                display: 'flex',
                alignItems: 'flex-start',
                gap: '12px',
                color: 'rgba(255,255,255,0.35)',
                fontSize: '13px',
                lineHeight: 1.6,
              }}>
                <span style={{ fontSize: '20px', lineHeight: 1 }}>🗺️</span>
                <div>
                  <div style={{ fontWeight: '600', color: 'rgba(255,255,255,0.5)', marginBottom: '4px' }}>
                    No region selected
                  </div>
                  Switch to the <strong style={{ color: 'rgba(255,255,255,0.6)' }}>Visualization</strong> tab,
                  use the selection toolbar to draw a rectangle or polygon, then return here.
                </div>
              </div>
            )}

            {/* Region available → controls + map */}
            {selectedRegion && (
              <div>
                {/* Region info pill + controls row */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap', marginBottom: '16px' }}>
                  {/* Region badge */}
                  <span style={{
                    fontSize: '11px', fontWeight: '600', padding: '4px 12px', borderRadius: '20px',
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
                    <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: '12px' }}>Hour</span>
                    <input
                      type="number"
                      value={spatialHour}
                      min={0} max={360}
                      onChange={e => setSpatialHour(Math.max(0, Math.min(360, Number(e.target.value))))}
                      style={{ ...INPUT, width: '60px' }}
                    />
                    <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: '12px' }}>h</span>
                  </div>

                  {/* Run button */}
                  <button
                    onClick={handleRunSpatial}
                    disabled={spatialLoading || selectedModels.length < 2}
                    style={{
                      background: (!spatialLoading && selectedModels.length >= 2) ? '#e67e22' : 'rgba(255,255,255,0.08)',
                      color: (!spatialLoading && selectedModels.length >= 2) ? 'white' : 'rgba(255,255,255,0.25)',
                      border: 'none',
                      borderRadius: '8px',
                      padding: '7px 18px',
                      fontSize: '13px',
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
                          fontSize: '12px',
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
                          fontSize: '12px',
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
                    borderRadius: '8px',
                    padding: '12px 16px',
                    color: '#e74c3c',
                    fontSize: '13px',
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
                          <div style={{ color: 'rgba(255,255,255,0.85)', fontSize: '14px', fontWeight: '700' }}>
                            {value ?? '—'}
                          </div>
                          <div style={{ color: 'rgba(255,255,255,0.35)', fontSize: '10px', marginTop: '1px' }}>
                            {label}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Initial state — region selected but not yet run */}
                {!spatialLoading && !spatialData && (
                  <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: '13px', padding: '16px 0', textAlign: 'center' }}>
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
