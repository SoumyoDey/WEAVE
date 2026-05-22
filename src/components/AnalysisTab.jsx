import React, { useState } from 'react';
import {
  AreaChart, Area, BarChart, Bar, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, ComposedChart, Line,
} from 'recharts';
import { fetchCategoricalMetrics, fetchRegionCategoricalMetrics } from '../api/analysisApi';
import { fetchSpatialMetric, fetchSpatialMetricPlot } from '../api/spatialApi';
import { METRIC_CONFIG } from '../constants';

// ── Region metric definitions (defined outside component to avoid recreation) ──
const REGION_METRICS = [
  { key: 'ssr',         group: 'calibration',  label: 'Spread-Skill Ratio',         requiresHour: true,  requiresThreshold: false },
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

/**
 * Full Analysis tab content.
 *
 * Props:
 *   clickedPoint         {object|null}  — { lat, lon }
 *   currentModel         {object}
 *   selectedVariable     {string}
 *   timeseriesLoading    {boolean}
 *   timeseriesData       {Array|null}
 *   ssrLoading           {boolean}
 *   ssrData              {object|null}
 *   onCompare            {fn}
 *   selectedRegion       {object|null}
 */
export function AnalysisTab({
  clickedPoint,
  currentModel,
  selectedVariable,
  timeseriesLoading, timeseriesData,
  ssrLoading, ssrData,
  onCompare,
  selectedRegion,
}) {
  // ── Verification Metrics state ──────────────────────────────────────────────
  const [catThreshold, setCatThreshold]   = useState(25);    // mm/6h
  const [catHourMin,   setCatHourMin]     = useState(0);
  const [catHourMax,   setCatHourMax]     = useState(240);
  const [catLoading,   setCatLoading]     = useState(false);
  const [catData,      setCatData]        = useState(null);  // full API response
  const [catError,     setCatError]       = useState(null);
  const [catHasRun,    setCatHasRun]      = useState(false);

  // ── Region categorical state ────────────────────────────────────────────────
  const [catMode,        setCatMode]        = useState('point');  // 'point' | 'region'
  const [regCatLoading,  setRegCatLoading]  = useState(false);
  const [regCatData,     setRegCatData]     = useState(null);
  const [regCatError,    setRegCatError]    = useState(null);
  const [regCatHasRun,   setRegCatHasRun]   = useState(false);

  // ── Region mode state ────────────────────────────────────────────────────────
  const [analysisMode,       setAnalysisMode]       = useState('point');
  const [regionHour,         setRegionHour]         = useState(24);
  const [regionHourMin,      setRegionHourMin]      = useState(0);
  const [regionHourMax,      setRegionHourMax]      = useState(168);
  const [regionThreshold,    setRegionThreshold]    = useState(25);
  const [spatialMaps,        setSpatialMaps]        = useState({});
  const [regionRunning,      setRegionRunning]      = useState(false);

  const handleRunCategorical = async () => {
    if (!clickedPoint || !currentModel) return;
    setCatLoading(true);
    setCatError(null);
    setCatHasRun(true);
    try {
      const data = await fetchCategoricalMetrics({
        model:        currentModel.name,
        variable:     selectedVariable,
        lat:          clickedPoint.lat,
        lon:          clickedPoint.lon,
        thresholdMm6h: parseFloat(catThreshold) || 25,
        hourMin:      catHourMin,
        hourMax:      catHourMax,
      });
      setCatData(data);
    } catch (err) {
      setCatError(err.message || 'Failed to load verification metrics');
    } finally {
      setCatLoading(false);
    }
  };

  const handleRunRegionCategorical = async () => {
    if (!selectedRegion?.bounds) return;
    setRegCatLoading(true);
    setRegCatError(null);
    setRegCatHasRun(true);
    try {
      const b = selectedRegion.bounds;
      const data = await fetchRegionCategoricalMetrics({
        model:         currentModel.name,
        variable:      selectedVariable,
        minLat:        b.minLat ?? b.min_lat,
        maxLat:        b.maxLat ?? b.max_lat,
        minLon:        b.minLon ?? b.min_lon,
        maxLon:        b.maxLon ?? b.max_lon,
        thresholdMm6h: parseFloat(catThreshold) || 25,
        hourMin:       catHourMin,
        hourMax:       catHourMax,
      });
      setRegCatData(data);
    } catch (err) {
      setRegCatError(err.message || 'Failed to load region metrics');
    } finally {
      setRegCatLoading(false);
    }
  };

  const handleComputeAllMaps = async () => {
    if (!selectedRegion?.bounds || !currentModel) return;
    setRegionRunning(true);
    // Mark all as loading
    const init = {};
    REGION_METRICS.forEach(m => { init[m.key] = { loading: true, url: null, error: null }; });
    setSpatialMaps(init);

    const bounds = selectedRegion.bounds;

    REGION_METRICS.forEach(async (m) => {
      try {
        const pts = await fetchSpatialMetric({
          metric:    m.key,
          modelName: currentModel.name,
          variable:  selectedVariable,
          hour:      m.requiresHour ? regionHour : undefined,
          threshold: m.requiresThreshold ? regionThreshold : undefined,
          hourMin:   (!m.requiresHour && !m.requiresThreshold) || m.requiresThreshold ? regionHourMin : undefined,
          hourMax:   (!m.requiresHour && !m.requiresThreshold) || m.requiresThreshold ? regionHourMax : undefined,
          bounds,
        });
        const plot = await fetchSpatialMetricPlot({
          metric:         m.key,
          model:          currentModel.name,
          variable:       selectedVariable,
          hour:           regionHour,
          threshold_mm_6h: m.requiresThreshold ? regionThreshold : undefined,
          points:         pts.points || [],
          n_hours:        pts.n_hours,
        });
        setSpatialMaps(prev => ({
          ...prev,
          [m.key]: {
            loading: false,
            url:   plot.image ? 'data:image/png;base64,' + plot.image : null,
            error: plot.error || (pts.points?.length === 0 ? 'No data returned' : null),
          },
        }));
      } catch (err) {
        setSpatialMaps(prev => ({
          ...prev,
          [m.key]: { loading: false, url: null, error: err.message },
        }));
      }
    });

    setRegionRunning(false);
  };

  const ssrBarColor = (ssr) => {
    if (ssr === null) return '#555';
    if (ssr >= 0.8 && ssr <= 1.2) return '#2ecc71';
    if (ssr < 0.8) return '#e74c3c';
    return '#f39c12';
  };

  const yAxisUnit = selectedVariable === 'wind' ? 'm/s'
    : selectedVariable === 'temperature_2m' ? 'K'
    : 'mm/hr';

  const verifiedAgainst = selectedVariable === 'precipitation'
    ? 'Verified against GPM IMERG V07B observations'
    : selectedVariable === 'wind'
    ? 'Verified against ERA5 reanalysis (10-m wind)'
    : selectedVariable === 'temperature_2m'
    ? 'Verified against ERA5 reanalysis (2-m temperature)'
    : selectedVariable === 'pressure_msl'
    ? 'Verified against ERA5 reanalysis (MSLP)'
    : 'Verified against reanalysis observations';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden', flex: 1 }}>
      {/* ── Header with mode toggle ── */}
      <div style={{ padding: '12px 30px 10px', borderBottom: '1px solid rgba(255,255,255,0.08)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
        <div>
          <h2 style={{ color: 'white', margin: '0 0 3px 0', fontSize: '18px', fontWeight: '600' }}>📊 Forecast Analysis</h2>
          <p style={{ color: 'rgba(255,255,255,0.4)', margin: 0, fontSize: '12px' }}>
            {analysisMode === 'point'
              ? (clickedPoint ? `Point: ${clickedPoint.lat}°N, ${clickedPoint.lon}°E — ${currentModel?.name} — ${selectedVariable}` : 'Click anywhere on the map to analyse a location')
              : (selectedRegion?.bounds ? `Region: ${selectedRegion.bounds.min_lat?.toFixed(1)}°–${selectedRegion.bounds.max_lat?.toFixed(1)}°N · ${selectedRegion.bounds.min_lon?.toFixed(1)}°–${selectedRegion.bounds.max_lon?.toFixed(1)}°E — ${currentModel?.name}` : 'Draw a region on the map to compute spatial metrics')}
          </p>
        </div>
        {/* Point / Region toggle */}
        <div style={{ display: 'flex', borderRadius: '8px', overflow: 'hidden', border: '1px solid rgba(255,255,255,0.15)', flexShrink: 0 }}>
          {[{ id: 'point', icon: '📍', label: 'Point' }, { id: 'region', icon: '🗺', label: 'Region' }].map(({ id, icon, label }) => (
            <button key={id} onClick={() => setAnalysisMode(id)}
              style={{ padding: '6px 18px', fontSize: '12px', fontWeight: '600', cursor: 'pointer', border: 'none', outline: 'none',
                background: analysisMode === id ? 'rgba(52,152,219,0.25)' : 'rgba(255,255,255,0.04)',
                color:      analysisMode === id ? 'rgba(52,152,219,0.95)' : 'rgba(255,255,255,0.45)' }}>
              {icon} {label}
            </button>
          ))}
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 30px' }}>

        {/* ══════════ POINT MODE ══════════ */}
        {analysisMode === 'point' && (
          <>
            {/* Empty state */}
            {!clickedPoint && (
              <div style={{ height: '60vh', display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center', color: 'rgba(255,255,255,0.25)' }}>
                <div>
                  <div style={{ fontSize: '64px', marginBottom: '16px' }}>🖱️</div>
                  <p style={{ fontSize: '16px', margin: 0 }}>Click a point on the map</p>
                  <p style={{ fontSize: '13px', margin: '8px 0 0 0' }}>Switch to Visualization tab, click anywhere, then come back here</p>
                </div>
              </div>
            )}

            {clickedPoint && (
              <>
                {/* ── Section 1: Cone of Uncertainty ── */}
                <div style={{ marginBottom: '32px' }}>
                  <h3 style={{ color: 'rgba(255,255,255,0.85)', fontSize: '14px', fontWeight: '600', margin: '0 0 12px 0', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                    Cone of Uncertainty
                  </h3>

                  {timeseriesLoading && (
                    <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: '14px', padding: '40px 0' }}>⏳ Loading forecast data…</div>
                  )}

                  {!timeseriesLoading && timeseriesData && (
                    <div style={{ height: '320px' }}>
                      <div style={{ display: 'flex', gap: '20px', marginBottom: '10px', flexWrap: 'wrap' }}>
                        {[
                          { color: '#7ec8f7',             label: 'Ensemble Mean', solid: true },
                          { color: 'rgba(52,152,219,0.4)', label: '±1σ (68%)',    solid: false },
                          { color: 'rgba(52,152,219,0.15)',label: '±2σ (95%)',    solid: false },
                        ].map(({ color, label, solid }) => (
                          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <div style={{ width: '24px', height: solid ? '3px' : '12px', background: color, borderRadius: '2px' }} />
                            <span style={{ color: 'rgba(255,255,255,0.6)', fontSize: '12px' }}>{label}</span>
                          </div>
                        ))}
                      </div>
                      <ResponsiveContainer width="100%" height="90%">
                        <AreaChart data={timeseriesData} margin={{ top: 10, right: 30, left: 10, bottom: 30 }}>
                          <defs>
                            <linearGradient id="cone2grad" x1="0" y1="0" x2="1" y2="0">
                              <stop offset="0%"   stopColor="#3498db" stopOpacity={0.12} />
                              <stop offset="100%" stopColor="#3498db" stopOpacity={0.22} />
                            </linearGradient>
                            <linearGradient id="cone1grad" x1="0" y1="0" x2="1" y2="0">
                              <stop offset="0%"   stopColor="#3498db" stopOpacity={0.25} />
                              <stop offset="100%" stopColor="#3498db" stopOpacity={0.45} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                          <XAxis dataKey="hour" stroke="rgba(255,255,255,0.3)"
                            tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }}
                            tickFormatter={h => `+${h}h`}
                            ticks={[0,24,48,72,96,120,144,168,192,216,240,264,288,312,336,360]}
                            label={{ value: 'Forecast Hour', position: 'insideBottom', offset: -15, fill: 'rgba(255,255,255,0.4)', fontSize: 12 }} />
                          <YAxis stroke="rgba(255,255,255,0.3)"
                            tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }}
                            label={{ value: selectedVariable === 'wind' ? 'Wind Speed (m/s)' : 'Precipitation (mm/hr)', angle: -90, position: 'insideLeft', fill: 'rgba(255,255,255,0.4)', fontSize: 12 }} />
                          <Tooltip
                            contentStyle={{ background: '#1a2535', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '8px', color: 'white', fontSize: '12px' }}
                            formatter={(value, name) => {
                              if (value == null) return null;
                              const labels = { mean: 'Mean', band2Hi: '+2σ', band2Lo: '-2σ', band1Hi: '+1σ', band1Lo: '-1σ' };
                              return [typeof value === 'number' ? value.toFixed(3) : value, labels[name] || name];
                            }}
                            labelFormatter={hour => `Forecast +${hour}h (Day ${(hour/24).toFixed(1)})`} />
                          <Area type="monotone" dataKey="band2Hi" stroke="none" fill="url(#cone2grad)" fillOpacity={1} legendType="none" name="band2Hi" />
                          <Area type="monotone" dataKey="band2Lo" stroke="none" fill="#0f1923"         fillOpacity={1} legendType="none" name="band2Lo" />
                          <Area type="monotone" dataKey="band1Hi" stroke="none" fill="url(#cone1grad)" fillOpacity={1} legendType="none" name="band1Hi" />
                          <Area type="monotone" dataKey="band1Lo" stroke="none" fill="#0f1923"         fillOpacity={1} legendType="none" name="band1Lo" />
                          <Area type="monotone" dataKey="mean" stroke="#7ec8f7" strokeWidth={2.5} fill="none" dot={false} name="mean" />
                          {[24,48,72,96,120,144,168,192,216,240,264,288,312,336].map(h => (
                            <ReferenceLine key={h} x={h} stroke="rgba(255,255,255,0.07)" strokeDasharray="4 4"
                              label={{ value: `D${h/24}`, position: 'top', fill: 'rgba(255,255,255,0.2)', fontSize: 9 }} />
                          ))}
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  )}

                  {!timeseriesLoading && !timeseriesData && (
                    <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: '13px', padding: '20px 0' }}>No forecast data available for this location</div>
                  )}
                </div>

                {/* ── Section 2: Spread-Skill Analysis ── */}
                <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '24px' }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: '16px', marginBottom: '12px', flexWrap: 'wrap' }}>
                    <h3 style={{ color: 'rgba(255,255,255,0.85)', fontSize: '14px', fontWeight: '600', margin: 0, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                      Spread-Skill Analysis
                    </h3>
                    <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: '12px' }}>
                      {verifiedAgainst}{' · Lead times with obs shown'}
                    </span>
                  </div>

                  {ssrLoading && (
                    <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: '14px', padding: '40px 0' }}>⏳ Loading spread-skill data…</div>
                  )}

                  {!ssrLoading && ssrData && ssrData.n_cases === 0 && (
                    <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: '13px', padding: '20px 0' }}>No overlapping observations found for this location and time window</div>
                  )}

                  {!ssrLoading && ssrData && ssrData.n_cases > 0 && (() => {
                    const corrVal      = ssrData.correlation;
                    const corrColor    = corrVal === null ? '#aaa' : corrVal >= 0.7 ? '#2ecc71' : corrVal >= 0.4 ? '#f39c12' : '#e74c3c';
                    const meanSSR      = ssrData.hours.filter(h => h.ssr !== null).reduce((a, h, _, arr) => a + h.ssr / arr.length, 0);
                    const meanSSRColor = meanSSR >= 0.8 && meanSSR <= 1.2 ? '#2ecc71' : meanSSR < 0.8 ? '#e74c3c' : '#f39c12';
                    const ssrInterpret = meanSSR >= 0.8 && meanSSR <= 1.2 ? 'Well calibrated' : meanSSR < 0.8 ? 'Overconfident (underdispersed)' : 'Underconfident (overdispersed)';
                    return (
                      <>
                        {/* Stat badges */}
                        <div style={{ display: 'flex', gap: '12px', marginBottom: '20px', flexWrap: 'wrap' }}>
                          {[
                            { label: 'Spread-Skill Correlation', value: corrVal !== null ? corrVal.toFixed(3) : 'N/A', color: corrColor, hint: 'corr(σ, |ε|) across lead times' },
                            { label: 'Mean SSR',         value: meanSSR.toFixed(3), color: meanSSRColor, hint: ssrInterpret },
                            { label: 'Verified Hours',   value: ssrData.n_cases,    color: '#3498db',    hint: 'Lead times with matching observations' },
                          ].map(({ label, value, color, hint }) => (
                            <div key={label} style={{ background: 'rgba(255,255,255,0.06)', borderRadius: '10px', padding: '12px 18px', minWidth: '140px', borderLeft: `3px solid ${color}` }}>
                              <div style={{ color, fontSize: '22px', fontWeight: '700', lineHeight: 1 }}>{value}</div>
                              <div style={{ color: 'rgba(255,255,255,0.7)', fontSize: '12px', marginTop: '4px', fontWeight: '500' }}>{label}</div>
                              <div style={{ color: 'rgba(255,255,255,0.35)', fontSize: '11px', marginTop: '2px' }}>{hint}</div>
                            </div>
                          ))}
                        </div>

                        {/* Two charts */}
                        <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
                          {/* Chart A: SSR per hour */}
                          <div style={{ flex: '1 1 340px', minWidth: 0 }}>
                            <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: '12px', marginBottom: '6px' }}>
                              Spread-Skill Ratio per Lead Time &nbsp;
                              <span style={{ color: '#2ecc71' }}>■</span> calibrated &nbsp;
                              <span style={{ color: '#e74c3c' }}>■</span> overconfident &nbsp;
                              <span style={{ color: '#f39c12' }}>■</span> underconfident
                            </div>
                            <ResponsiveContainer width="100%" height={220}>
                              <BarChart data={ssrData.hours} margin={{ top: 8, right: 20, left: 0, bottom: 20 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                                <XAxis dataKey="hour" stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }} tickFormatter={h => `+${h}h`} label={{ value: 'Forecast Hour', position: 'insideBottom', offset: -10, fill: 'rgba(255,255,255,0.4)', fontSize: 11 }} />
                                <YAxis stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }} label={{ value: 'SSR', angle: -90, position: 'insideLeft', fill: 'rgba(255,255,255,0.4)', fontSize: 11 }} />
                                <Tooltip
                                  contentStyle={{ background: '#1a2535', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '8px', color: 'white', fontSize: '12px' }}
                                  formatter={(value) => [value !== null ? Number(value).toFixed(3) : 'N/A (zero error)', 'SSR']}
                                  labelFormatter={h => `Forecast +${h}h — ${ssrData.hours.find(r => r.hour === h)?.n_members} members`} />
                                <ReferenceLine y={1} stroke="rgba(255,255,255,0.5)" strokeDasharray="6 3" label={{ value: 'SSR=1', position: 'right', fill: 'rgba(255,255,255,0.5)', fontSize: 10 }} />
                                <Bar dataKey="ssr" radius={[4, 4, 0, 0]} name="SSR">
                                  {ssrData.hours.map(entry => (
                                    <Cell key={entry.hour} fill={ssrBarColor(entry.ssr)} />
                                  ))}
                                </Bar>
                              </BarChart>
                            </ResponsiveContainer>
                          </div>

                          {/* Chart B: Spread vs |Error| */}
                          <div style={{ flex: '1 1 340px', minWidth: 0 }}>
                            <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: '12px', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                              <span>Ensemble Spread vs Absolute Error per Lead Time</span>
                              <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px' }}>
                                <span style={{ display: 'inline-block', width: '10px', height: '10px', background: '#3498db', borderRadius: '2px' }} />Spread (σ)
                              </span>
                              <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px' }}>
                                <span style={{ display: 'inline-block', width: '10px', height: '10px', background: '#e74c3c', borderRadius: '2px' }} />|Error|
                              </span>
                            </div>
                            <ResponsiveContainer width="100%" height={220}>
                              <BarChart data={ssrData.hours} margin={{ top: 8, right: 20, left: 0, bottom: 28 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                                <XAxis dataKey="hour" stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }} tickFormatter={h => `+${h}h`} label={{ value: 'Forecast Hour', position: 'insideBottom', offset: -12, fill: 'rgba(255,255,255,0.4)', fontSize: 11 }} />
                                <YAxis stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }} label={{ value: yAxisUnit, angle: -90, position: 'insideLeft', fill: 'rgba(255,255,255,0.4)', fontSize: 11 }} />
                                <Tooltip
                                  contentStyle={{ background: '#1a2535', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '8px', color: 'white', fontSize: '12px' }}
                                  formatter={(value, name) => [Number(value).toFixed(4), name]}
                                  labelFormatter={h => {
                                    const r = ssrData.hours.find(x => x.hour === h);
                                    return r ? `+${h}h  ·  Ens. mean: ${Number(r.ens_mean).toFixed(4)}, Obs: ${Number(r.obs).toFixed(4)}` : `+${h}h`;
                                  }} />
                                <Bar dataKey="spread" name="Spread (σ)" fill="#3498db" radius={[3, 3, 0, 0]} />
                                <Bar dataKey="error"  name="|Error|"   fill="#e74c3c" radius={[3, 3, 0, 0]} />
                              </BarChart>
                            </ResponsiveContainer>
                          </div>
                        </div>
                      </>
                    );
                  })()}

                  {!ssrLoading && !ssrData && (
                    <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: '13px', padding: '20px 0' }}>Spread-skill data unavailable</div>
                  )}
                </div>

                {/* ── Section 3: Verification Metrics ── */}
                <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '24px', marginTop: '32px' }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: '16px', marginBottom: '14px', flexWrap: 'wrap' }}>
                    <h3 style={{ color: 'rgba(255,255,255,0.85)', fontSize: '14px', fontWeight: '600', margin: 0, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                      🎯 Verification Metrics
                    </h3>
                    <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: '12px' }}>
                      CSI · POD · FAR · FBI · Brier Score · Composite Confidence
                    </span>
                  </div>

                  {/* Controls row */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>

                    {/* Point / Region mode toggle */}
                    <div style={{ display: 'flex', borderRadius: '8px', overflow: 'hidden', border: '1px solid rgba(255,255,255,0.15)' }}>
                      {['point', 'region'].map(mode => (
                        <button
                          key={mode}
                          onClick={() => setCatMode(mode)}
                          style={{
                            padding: '5px 14px', fontSize: '12px', fontWeight: '600', cursor: 'pointer',
                            background: catMode === mode ? 'rgba(52,152,219,0.25)' : 'rgba(255,255,255,0.04)',
                            color:  catMode === mode ? 'rgba(52,152,219,0.95)' : 'rgba(255,255,255,0.4)',
                            border: 'none', outline: 'none',
                          }}
                        >
                          {mode === 'point' ? '📍 Point' : '🗺 Region'}
                        </button>
                      ))}
                    </div>

                    {/* Region badge — shown in region mode */}
                    {catMode === 'region' && selectedRegion?.bounds && (() => {
                      const b = selectedRegion.bounds;
                      const mn = b.minLat ?? b.min_lat, mx = b.maxLat ?? b.max_lat;
                      const mw = b.minLon ?? b.min_lon, me = b.maxLon ?? b.max_lon;
                      return (
                        <span style={{ fontSize: '11px', color: 'rgba(52,152,219,0.8)', background: 'rgba(52,152,219,0.10)', padding: '3px 10px', borderRadius: '10px', border: '1px solid rgba(52,152,219,0.25)' }}>
                          {mn?.toFixed(1)}°–{mx?.toFixed(1)}°N · {mw?.toFixed(1)}°–{me?.toFixed(1)}°E
                        </span>
                      );
                    })()}

                    {/* No-region warning */}
                    {catMode === 'region' && !selectedRegion?.bounds && (
                      <span style={{ fontSize: '12px', color: 'rgba(243,156,18,0.8)' }}>
                        ⚠️ Draw a region on the map first
                      </span>
                    )}

                    {/* Threshold */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span style={{ color: 'rgba(255,255,255,0.55)', fontSize: '12px', whiteSpace: 'nowrap' }}>Threshold</span>
                      <input
                        type="number" min="0" step="1" value={catThreshold}
                        onChange={e => setCatThreshold(e.target.value)}
                        style={{ width: '72px', padding: '4px 8px', fontSize: '13px', fontWeight: '600', background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: '6px', color: 'white', textAlign: 'right', outline: 'none' }}
                      />
                      <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: '12px' }}>mm/6h</span>
                    </div>

                    {/* Hour range */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span style={{ color: 'rgba(255,255,255,0.55)', fontSize: '12px', whiteSpace: 'nowrap' }}>Hours</span>
                      <input type="number" min="0" step="6" value={catHourMin}
                        onChange={e => setCatHourMin(parseInt(e.target.value, 10) || 0)}
                        style={{ width: '60px', padding: '4px 6px', fontSize: '12px', background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: '6px', color: 'white', textAlign: 'center', outline: 'none' }} />
                      <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: '12px' }}>–</span>
                      <input type="number" min="0" step="24" value={catHourMax}
                        onChange={e => setCatHourMax(parseInt(e.target.value, 10) || 240)}
                        style={{ width: '60px', padding: '4px 6px', fontSize: '12px', background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: '6px', color: 'white', textAlign: 'center', outline: 'none' }} />
                      <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: '12px' }}>h</span>
                    </div>

                    {/* Run button */}
                    <button
                      onClick={catMode === 'point' ? handleRunCategorical : handleRunRegionCategorical}
                      disabled={catMode === 'point' ? (catLoading || !clickedPoint) : (regCatLoading || !selectedRegion?.bounds)}
                      style={{
                        padding: '6px 16px', fontSize: '12px', fontWeight: '700',
                        cursor: (catMode === 'point' ? catLoading : regCatLoading) ? 'not-allowed' : 'pointer',
                        background: (catMode === 'point' ? catLoading : regCatLoading) ? 'rgba(52,152,219,0.08)' : 'rgba(52,152,219,0.18)',
                        border: '1px solid rgba(52,152,219,0.45)', borderRadius: '8px',
                        color: (catMode === 'point' ? catLoading : regCatLoading) ? 'rgba(52,152,219,0.45)' : 'rgba(52,152,219,0.95)',
                        display: 'flex', alignItems: 'center', gap: '6px',
                      }}
                    >
                      {(catMode === 'point' ? catLoading : regCatLoading) ? '⏳ Running…' : '▶ Run Metrics'}
                    </button>

                    {/* Active result label */}
                    {catMode === 'point' && catData && !catLoading && (
                      <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.3)' }}>
                        {currentModel.name} · &gt;{catData.threshold_info?.threshold_mm_6h ?? catThreshold} mm/6h
                        {' '}(≡ {catData.threshold_info?.threshold_rate?.toFixed(3) ?? '—'} mm/h)
                      </span>
                    )}
                    {catMode === 'region' && regCatData && !regCatLoading && (
                      <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.3)' }}>
                        {currentModel.name} · &gt;{regCatData.threshold_info?.threshold_mm_6h ?? catThreshold} mm/6h
                        {' '}· {regCatData.summary?.n_grid_pts ?? '?'} grid pts
                      </span>
                    )}
                  </div>

                  {/* Error banner */}
                  {(catMode === 'point' ? catError : regCatError) && (
                    <div style={{ background: 'rgba(231,76,60,0.12)', border: '1px solid rgba(231,76,60,0.3)', borderRadius: '8px', padding: '10px 14px', marginBottom: '14px', color: '#e74c3c', fontSize: '12px' }}>
                      ⚠️ {catMode === 'point' ? catError : regCatError}
                    </div>
                  )}

                  {/* Obs coverage warning banner */}
                  {(catMode === 'point' ? catData : regCatData)?.obs_warning && (
                    <div style={{ background: 'rgba(243,156,18,0.10)', border: '1px solid rgba(243,156,18,0.3)', borderRadius: '8px', padding: '8px 14px', marginBottom: '16px', color: '#f39c12', fontSize: '12px', display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                      <span style={{ flexShrink: 0 }}>⚠️</span>
                      <span>{(catMode === 'point' ? catData : regCatData).obs_warning}</span>
                    </div>
                  )}

                  {/* Empty-hours result */}
                  {(catMode === 'point' ? (catHasRun && !catLoading && catData && catData.hours?.length === 0)
                                        : (regCatHasRun && !regCatLoading && regCatData && regCatData.hours?.length === 0)) && (
                    <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: '13px', padding: '16px 0' }}>
                      No overlapping observations found for this location and time window. Try a different point or extend the hour range.
                    </div>
                  )}

                  {/* ── Stat badges ── */}
                  {(() => {
                    const activeData = catMode === 'point' ? catData : regCatData;
                    if (!activeData || !activeData.summary || !activeData.hours?.length) return null;
                    const s   = activeData.summary;
                    const cc  = s.composite_confidence;
                    const fss = s.fss;   // only non-null for region mode

                    const metricColor = (key, val) => {
                      if (val == null) return '#666';
                      if (key === 'csi')  return val >= 0.5 ? '#2ecc71' : val >= 0.3 ? '#f39c12' : '#e74c3c';
                      if (key === 'pod')  return val >= 0.7 ? '#2ecc71' : val >= 0.5 ? '#f39c12' : '#e74c3c';
                      if (key === 'far')  return val <= 0.3 ? '#2ecc71' : val <= 0.5 ? '#f39c12' : '#e74c3c';
                      if (key === 'fbi')  return val >= 0.8 && val <= 1.2 ? '#2ecc71' : '#f39c12';
                      if (key === 'bs')   return val <= 0.1 ? '#2ecc71' : val <= 0.25 ? '#f39c12' : '#e74c3c';
                      if (key === 'fss')  return val >= 0.5 ? '#2ecc71' : val >= 0.3 ? '#f39c12' : '#e74c3c';
                      if (key === 'cc')   return val >= 0.6 ? '#2ecc71' : val >= 0.4 ? '#f39c12' : '#e74c3c';
                      return '#aaa';
                    };

                    const badges = [
                      { key: 'csi', label: 'CSI',   hint: 'Critical Success Index (0→1)',       val: s.csi   },
                      { key: 'pod', label: 'POD',   hint: 'Probability of Detection (hit rate)', val: s.pod   },
                      { key: 'far', label: 'FAR',   hint: 'False Alarm Ratio (0=perfect)',       val: s.far   },
                      { key: 'fbi', label: 'FBI',   hint: 'Frequency Bias (1=unbiased)',         val: s.fbi   },
                      { key: 'bs',  label: 'Brier', hint: 'Brier Score (0=perfect)',             val: s.brier_score },
                    ];
                    if (catMode === 'region') {
                      badges.push({ key: 'fss', label: 'FSS', hint: 'Fractions Skill Score (0→1, higher=better)', val: fss });
                    }

                    const contingencyTotal = s.hits + s.misses + s.false_alarms + s.correct_neg;

                    return (
                      <>
                        {/* Badges */}
                        <div style={{ display: 'flex', gap: '10px', marginBottom: '20px', flexWrap: 'wrap' }}>
                          {badges.map(({ key, label, hint, val }) => (
                            <div key={key} style={{ background: 'rgba(255,255,255,0.06)', borderRadius: '10px', padding: '12px 16px', minWidth: '100px', borderLeft: `3px solid ${metricColor(key, val)}` }}>
                              <div style={{ color: metricColor(key, val), fontSize: '22px', fontWeight: '700', lineHeight: 1 }}>
                                {val != null ? val.toFixed(3) : 'N/A'}
                              </div>
                              <div style={{ color: 'rgba(255,255,255,0.7)', fontSize: '12px', marginTop: '4px', fontWeight: '600' }}>{label}</div>
                              <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: '10px', marginTop: '2px' }}>{hint}</div>
                            </div>
                          ))}

                          {/* Composite Confidence */}
                          <div style={{
                            background: cc != null ? `rgba(${cc >= 0.6 ? '46,204,113' : cc >= 0.4 ? '243,156,18' : '231,76,60'},0.10)` : 'rgba(255,255,255,0.06)',
                            borderRadius: '10px', padding: '12px 16px', minWidth: '130px',
                            borderLeft: `3px solid ${metricColor('cc', cc)}`,
                            borderTop: `1px solid ${metricColor('cc', cc)}33`,
                          }}>
                            <div style={{ color: metricColor('cc', cc), fontSize: '24px', fontWeight: '800', lineHeight: 1 }}>
                              {cc != null ? cc.toFixed(3) : 'N/A'}
                            </div>
                            <div style={{ color: 'rgba(255,255,255,0.8)', fontSize: '12px', marginTop: '4px', fontWeight: '700' }}>Composite Confidence</div>
                            <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: '10px', marginTop: '2px' }}>
                              {catMode === 'region' && fss != null
                                ? '0.40×CSI + 0.30×FSS + 0.20×POD + 0.10×(1–FAR)'
                                : '0.40×CSI + 0.20×POD + 0.10×(1–FAR) ÷ 0.70'}
                            </div>
                            {catMode === 'point' && <div style={{ color: 'rgba(255,255,255,0.2)', fontSize: '10px', marginTop: '1px' }}>FSS = N/A (spatial-only)</div>}
                          </div>
                        </div>

                        {/* Contingency mini-table */}
                        <div style={{ display: 'flex', gap: '8px', marginBottom: '20px', flexWrap: 'wrap' }}>
                          {[
                            { label: 'Hits',        val: s.hits,         color: '#2ecc71' },
                            { label: 'Misses',      val: s.misses,       color: '#e74c3c' },
                            { label: 'False Alarms',val: s.false_alarms, color: '#f39c12' },
                            { label: 'Correct Neg.',val: s.correct_neg,  color: '#3498db' },
                          ].map(({ label, val, color }) => (
                            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '5px', background: 'rgba(255,255,255,0.04)', borderRadius: '6px', padding: '5px 10px', border: `1px solid ${color}33` }}>
                              <span style={{ color, fontWeight: '700', fontSize: '13px' }}>{val}</span>
                              <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: '11px' }}>{label}</span>
                            </div>
                          ))}
                          <div style={{ display: 'flex', alignItems: 'center', gap: '5px', background: 'rgba(255,255,255,0.04)', borderRadius: '6px', padding: '5px 10px', border: '1px solid rgba(255,255,255,0.1)' }}>
                            <span style={{ color: 'rgba(255,255,255,0.6)', fontWeight: '700', fontSize: '13px' }}>{contingencyTotal}</span>
                            <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: '11px' }}>
                              Total {catMode === 'region' ? `(${(s.n_grid_pts ?? '?')} pts × hours)` : 'cases'}
                            </span>
                          </div>
                        </div>

                        {/* Chart — different per mode */}
                        {catMode === 'point' && (
                          <div>
                            <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: '12px', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
                              <span>Event Probability per Lead Time (threshold &gt; {activeData.threshold_info?.threshold_mm_6h ?? catThreshold} mm/6h)</span>
                              <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ display: 'inline-block', width: '10px', height: '10px', background: 'rgba(52,152,219,0.6)', borderRadius: '2px' }} />P(event) — Gaussian</span>
                              <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ display: 'inline-block', width: '14px', height: '3px', background: '#2ecc71', borderRadius: '1px' }} />Observed event</span>
                              <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ display: 'inline-block', width: '14px', height: '2px', background: '#e74c3c' }} />Forecast event (det.)</span>
                            </div>
                            <ResponsiveContainer width="100%" height={230}>
                              <ComposedChart data={activeData.hours} margin={{ top: 8, right: 20, left: 0, bottom: 20 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                                <XAxis dataKey="hour" stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }} tickFormatter={h => `+${h}h`} label={{ value: 'Forecast Hour', position: 'insideBottom', offset: -12, fill: 'rgba(255,255,255,0.4)', fontSize: 11 }} />
                                <YAxis domain={[0, 1]} stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }} tickFormatter={v => `${(v * 100).toFixed(0)}%`} label={{ value: 'Probability', angle: -90, position: 'insideLeft', fill: 'rgba(255,255,255,0.4)', fontSize: 11 }} />
                                <Tooltip
                                  contentStyle={{ background: '#1a2535', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '8px', color: 'white', fontSize: '12px' }}
                                  formatter={(value, name) => {
                                    if (name === 'P(event)')   return [`${(value * 100).toFixed(1)}%`, 'P(event) Gaussian'];
                                    if (name === 'Obs event')  return [value === 1 ? 'Yes' : 'No', 'Observed event'];
                                    if (name === 'Fcst event') return [value === 1 ? 'Yes' : 'No', 'Forecast event (det.)'];
                                    return [value, name];
                                  }}
                                  labelFormatter={h => `Forecast +${h}h`}
                                />
                                <Bar dataKey="p_event" name="P(event)" fill="rgba(52,152,219,0.55)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
                                <Line type="stepAfter" dataKey="is_obs"  name="Obs event"  stroke="#2ecc71" strokeWidth={2.5} dot={{ r: 4, fill: '#2ecc71' }} isAnimationActive={false} connectNulls />
                                <Line type="stepAfter" dataKey="is_fcst" name="Fcst event" stroke="#e74c3c" strokeWidth={1.5} strokeDasharray="5 3" dot={false} isAnimationActive={false} connectNulls />
                              </ComposedChart>
                            </ResponsiveContainer>
                          </div>
                        )}

                        {catMode === 'region' && (
                          <div>
                            {/* Two sub-charts side by side */}
                            <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
                              {/* Chart A: Forecast vs Observed fraction per hour */}
                              <div style={{ flex: '1 1 300px', minWidth: 0 }}>
                                <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: '12px', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                                  <span>Event Frequency per Lead Time</span>
                                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ display: 'inline-block', width: '10px', height: '10px', background: 'rgba(52,152,219,0.6)', borderRadius: '2px' }} />Fcst fraction</span>
                                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ display: 'inline-block', width: '10px', height: '10px', background: 'rgba(46,204,113,0.6)', borderRadius: '2px' }} />Obs fraction</span>
                                </div>
                                <ResponsiveContainer width="100%" height={210}>
                                  <ComposedChart data={activeData.hours} margin={{ top: 8, right: 16, left: 0, bottom: 20 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                                    <XAxis dataKey="hour" stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 10 }} tickFormatter={h => `+${h}h`} label={{ value: 'Forecast Hour', position: 'insideBottom', offset: -12, fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} />
                                    <YAxis domain={[0, 'auto']} stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 10 }} tickFormatter={v => `${(v * 100).toFixed(0)}%`} label={{ value: 'Grid-pt fraction', angle: -90, position: 'insideLeft', fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} />
                                    <Tooltip
                                      contentStyle={{ background: '#1a2535', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '8px', color: 'white', fontSize: '12px' }}
                                      formatter={(v, n) => [`${(v*100).toFixed(1)}%`, n]}
                                      labelFormatter={h => {
                                        const r = activeData.hours.find(x => x.hour === h);
                                        return r ? `+${h}h · ${r.n_pts} grid pts` : `+${h}h`;
                                      }}
                                    />
                                    <Bar dataKey="fcst_frac" name="Fcst fraction" fill="rgba(52,152,219,0.55)" radius={[3,3,0,0]} isAnimationActive={false} />
                                    <Bar dataKey="obs_frac"  name="Obs fraction"  fill="rgba(46,204,113,0.55)" radius={[3,3,0,0]} isAnimationActive={false} />
                                  </ComposedChart>
                                </ResponsiveContainer>
                              </div>

                              {/* Chart B: CSI and FSS per hour */}
                              <div style={{ flex: '1 1 300px', minWidth: 0 }}>
                                <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: '12px', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                                  <span>Skill Scores per Lead Time</span>
                                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ display: 'inline-block', width: '14px', height: '3px', background: '#3498db' }} />CSI</span>
                                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ display: 'inline-block', width: '14px', height: '3px', background: '#f39c12' }} />FSS</span>
                                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ display: 'inline-block', width: '14px', height: '3px', background: '#2ecc71' }} />POD</span>
                                </div>
                                <ResponsiveContainer width="100%" height={210}>
                                  <ComposedChart data={activeData.hours} margin={{ top: 8, right: 16, left: 0, bottom: 20 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                                    <XAxis dataKey="hour" stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 10 }} tickFormatter={h => `+${h}h`} label={{ value: 'Forecast Hour', position: 'insideBottom', offset: -12, fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} />
                                    <YAxis domain={[0, 1]} stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 10 }} label={{ value: 'Score', angle: -90, position: 'insideLeft', fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} />
                                    <Tooltip
                                      contentStyle={{ background: '#1a2535', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '8px', color: 'white', fontSize: '12px' }}
                                      formatter={(v, n) => [v != null ? Number(v).toFixed(3) : 'N/A', n]}
                                      labelFormatter={h => `+${h}h`}
                                    />
                                    <ReferenceLine y={0.5} stroke="rgba(255,255,255,0.12)" strokeDasharray="4 4" />
                                    <Line type="monotone" dataKey="csi" name="CSI" stroke="#3498db" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} connectNulls />
                                    <Line type="monotone" dataKey="fss" name="FSS" stroke="#f39c12" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} connectNulls />
                                    <Line type="monotone" dataKey="pod" name="POD" stroke="#2ecc71" strokeWidth={1.5} strokeDasharray="5 3" dot={false} isAnimationActive={false} connectNulls />
                                  </ComposedChart>
                                </ResponsiveContainer>
                              </div>
                            </div>
                          </div>
                        )}
                      </>
                    );
                  })()}

                  {/* Pre-run placeholder */}
                  {(catMode === 'point' ? (!catHasRun && !catLoading) : (!regCatHasRun && !regCatLoading)) && (
                    <div style={{ color: 'rgba(255,255,255,0.25)', fontSize: '13px', padding: '28px 0', textAlign: 'center' }}>
                      Set a threshold and click <strong style={{ color: 'rgba(52,152,219,0.6)' }}>▶ Run Metrics</strong> to generate verification scores
                    </div>
                  )}
                </div>

                {/* ── Compare shortcut ── */}
                <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', padding: '14px 0 4px', display: 'flex', justifyContent: 'flex-end' }}>
                  <button
                    onClick={onCompare}
                    style={{ background: 'rgba(52,152,219,0.12)', border: '1px solid rgba(52,152,219,0.3)', color: 'rgba(52,152,219,0.9)', fontSize: '12px', fontWeight: '600', padding: '6px 14px', borderRadius: '8px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
                  >
                    ⚖️ Compare models at this point →
                  </button>
                </div>
              </>
            )}
          </>
        )}

        {/* ══════════ REGION MODE ══════════ */}
        {analysisMode === 'region' && (
          <>
            {/* Empty state — no region drawn */}
            {!selectedRegion?.bounds && (
              <div style={{ height: '60vh', display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center', color: 'rgba(255,255,255,0.25)' }}>
                <div>
                  <div style={{ fontSize: '64px', marginBottom: '16px' }}>🗺</div>
                  <p style={{ fontSize: '16px', margin: 0 }}>Draw a region on the map</p>
                  <p style={{ fontSize: '13px', margin: '8px 0 0 0' }}>Use the rectangle or polygon selection tool in the Visualization tab</p>
                </div>
              </div>
            )}

            {selectedRegion?.bounds && (
              <>
                {/* Controls row */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px', flexWrap: 'wrap', background: 'rgba(255,255,255,0.04)', borderRadius: '10px', padding: '12px 16px', border: '1px solid rgba(255,255,255,0.08)' }}>
                  {/* SSR Hour */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: '11px', whiteSpace: 'nowrap' }}>SSR Hour</span>
                    <input type="number" min="0" step="6" value={regionHour}
                      onChange={e => setRegionHour(parseInt(e.target.value, 10) || 24)}
                      style={{ width: '56px', padding: '4px 6px', fontSize: '12px', background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: '6px', color: 'white', textAlign: 'center', outline: 'none' }} />
                    <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: '11px' }}>h</span>
                  </div>

                  {/* Hour range for accuracy/categorical */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: '11px', whiteSpace: 'nowrap' }}>Hours</span>
                    <input type="number" min="0" step="6" value={regionHourMin}
                      onChange={e => setRegionHourMin(parseInt(e.target.value, 10) || 0)}
                      style={{ width: '52px', padding: '4px 6px', fontSize: '12px', background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: '6px', color: 'white', textAlign: 'center', outline: 'none' }} />
                    <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: '11px' }}>–</span>
                    <input type="number" min="0" step="24" value={regionHourMax}
                      onChange={e => setRegionHourMax(parseInt(e.target.value, 10) || 168)}
                      style={{ width: '52px', padding: '4px 6px', fontSize: '12px', background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: '6px', color: 'white', textAlign: 'center', outline: 'none' }} />
                    <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: '11px' }}>h</span>
                  </div>

                  {/* Threshold */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: '11px', whiteSpace: 'nowrap' }}>Threshold</span>
                    <input type="number" min="0" step="1" value={regionThreshold}
                      onChange={e => setRegionThreshold(parseFloat(e.target.value) || 25)}
                      style={{ width: '60px', padding: '4px 6px', fontSize: '12px', fontWeight: '600', background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: '6px', color: 'white', textAlign: 'right', outline: 'none' }} />
                    <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: '11px' }}>mm/6h</span>
                  </div>

                  {/* Compute button */}
                  <button onClick={handleComputeAllMaps} disabled={regionRunning}
                    style={{ padding: '7px 20px', fontSize: '12px', fontWeight: '700',
                      cursor: regionRunning ? 'not-allowed' : 'pointer',
                      background: regionRunning ? 'rgba(52,152,219,0.08)' : 'rgba(52,152,219,0.2)',
                      border: '1px solid rgba(52,152,219,0.5)', borderRadius: '8px',
                      color: regionRunning ? 'rgba(52,152,219,0.4)' : 'rgba(52,152,219,0.95)',
                      display: 'flex', alignItems: 'center', gap: '6px' }}>
                    {regionRunning ? '⏳ Computing…' : '▶ Compute All Maps'}
                  </button>
                </div>

                {/* Metric map groups */}
                {[
                  { id: 'calibration', label: 'Calibration', hint: 'Is the ensemble spread reliable?', keys: ['ssr', 'correlation'] },
                  { id: 'accuracy',    label: 'Accuracy vs Observations', hint: 'How close is the ensemble mean to obs?', keys: ['bias', 'mae', 'rmse', 'crps'] },
                  { id: 'categorical', label: `Categorical  (threshold > ${regionThreshold} mm/6h)`, hint: 'Event-based skill for threshold exceedances', keys: ['csi', 'pod', 'far', 'brier'] },
                ].map(group => (
                  <div key={group.id} style={{ marginBottom: '32px' }}>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px', marginBottom: '14px' }}>
                      <h3 style={{ color: 'rgba(255,255,255,0.85)', fontSize: '13px', fontWeight: '700', margin: 0, textTransform: 'uppercase', letterSpacing: '0.08em' }}>{group.label}</h3>
                      <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: '11px' }}>{group.hint}</span>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))', gap: '16px' }}>
                      {group.keys.map(key => {
                        const st = spatialMaps[key];
                        const cfg = METRIC_CONFIG.find(m => m.key === key);
                        return (
                          <div key={key} style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.08)', overflow: 'hidden' }}>
                            {/* Card header */}
                            <div style={{ padding: '8px 12px', borderBottom: '1px solid rgba(255,255,255,0.06)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                              <span style={{ fontSize: '12px', fontWeight: '600', color: 'rgba(255,255,255,0.75)' }}>{cfg?.label ?? key.toUpperCase()}</span>
                              {st?.url && (
                                <button onClick={() => {
                                  const a = document.createElement('a');
                                  a.href = st.url; a.download = `WEAVE-${currentModel?.name}-${key}.png`; a.click();
                                }} style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', background: 'none', border: 'none', cursor: 'pointer', padding: '2px 6px' }}>⬇ Save</button>
                              )}
                            </div>
                            {/* Card body */}
                            <div style={{ minHeight: '200px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                              {!st && (
                                <span style={{ color: 'rgba(255,255,255,0.2)', fontSize: '12px' }}>Click ▶ Compute All Maps</span>
                              )}
                              {st?.loading && (
                                <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.4)', fontSize: '12px' }}>
                                  <div style={{ fontSize: '24px', marginBottom: '8px' }}>⏳</div>Computing…
                                </div>
                              )}
                              {st && !st.loading && st.error && (
                                <div style={{ color: '#e74c3c', fontSize: '11px', padding: '16px', textAlign: 'center' }}>⚠️ {st.error}</div>
                              )}
                              {st && !st.loading && !st.error && st.url && (
                                <img src={st.url} alt={key} style={{ width: '100%', display: 'block' }} />
                              )}
                              {st && !st.loading && !st.error && !st.url && (
                                <span style={{ color: 'rgba(255,255,255,0.25)', fontSize: '12px' }}>No data for this region</span>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </>
            )}
          </>
        )}

      </div>
    </div>
  );
}
