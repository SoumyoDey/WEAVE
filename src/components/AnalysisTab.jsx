import React, { useState } from 'react';
import {
  AreaChart, Area, BarChart, Bar, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, ComposedChart, Line,
} from 'recharts';
import { fetchCategoricalMetrics } from '../api/analysisApi';

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
 *   spatialData          {object|null}
 *   metricHour           {number}
 *   analysisPlotLoading  {boolean}
 *   analysisPlotUrl      {string|null}
 *   analysisSpatialCanvasRef {React.Ref}
 */
export function AnalysisTab({
  clickedPoint,
  currentModel,
  selectedVariable,
  timeseriesLoading, timeseriesData,
  ssrLoading, ssrData,
  spatialData, metricHour,
  analysisPlotLoading, analysisPlotUrl,
  analysisSpatialCanvasRef,
  onCompare,
}) {
  const [shareState, setShareState] = useState('idle'); // 'idle' | 'copied'

  // ── Verification Metrics state ──────────────────────────────────────────────
  const [catThreshold, setCatThreshold]   = useState(25);    // mm/6h
  const [catHourMin,   setCatHourMin]     = useState(0);
  const [catHourMax,   setCatHourMax]     = useState(240);
  const [catLoading,   setCatLoading]     = useState(false);
  const [catData,      setCatData]        = useState(null);  // full API response
  const [catError,     setCatError]       = useState(null);
  const [catHasRun,    setCatHasRun]      = useState(false);

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

  const handleDownload = () => {
    if (!analysisPlotUrl) return;
    const label = spatialData?.metric === 'ssr'
      ? `ssr-h${spatialData.hour ?? metricHour}`
      : `corr-${spatialData?.n_hours ?? ''}leads`;
    const a = document.createElement('a');
    a.href = analysisPlotUrl;
    a.download = `WEAVE-${currentModel.name}-${label}.png`;
    a.click();
  };

  const handleShare = async () => {
    if (!analysisPlotUrl) return;
    // 1. Try native Web Share API (mobile / Electron)
    try {
      const res  = await fetch(analysisPlotUrl);
      const blob = await res.blob();
      const file = new File([blob], 'weave-spatial-metric.png', { type: 'image/png' });
      if (navigator.share && navigator.canShare?.({ files: [file] })) {
        await navigator.share({ title: 'WEAVE — Spatial Metric Map', files: [file] });
        return;
      }
    } catch {}
    // 2. Copy image to clipboard (desktop Chrome / Edge)
    try {
      const res  = await fetch(analysisPlotUrl);
      const blob = await res.blob();
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
      setShareState('copied');
      setTimeout(() => setShareState('idle'), 2500);
      return;
    } catch {}
    // 3. Fallback — trigger download
    handleDownload();
  };

  const btnBase = {
    display: 'flex', alignItems: 'center', gap: '5px',
    fontSize: '11px', fontWeight: '600',
    padding: '4px 10px', borderRadius: '8px', cursor: 'pointer',
    border: '1px solid rgba(255,255,255,0.12)',
    background: 'rgba(255,255,255,0.06)',
    color: 'rgba(255,255,255,0.7)',
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
      {/* Header */}
      <div style={{ padding: '16px 30px 10px', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
        <h2 style={{ color: 'white', margin: '0 0 4px 0', fontSize: '18px', fontWeight: '600' }}>📊 Forecast Analysis</h2>
        <p style={{ color: 'rgba(255,255,255,0.4)', margin: 0, fontSize: '13px' }}>
          {clickedPoint
            ? `Point: ${clickedPoint.lat}°N, ${clickedPoint.lon}°E — ${currentModel.name} — ${selectedVariable}`
            : 'Click anywhere on the map to generate analysis for that location'}
        </p>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 30px' }}>

        {/* Empty state */}
        {!clickedPoint && !spatialData && (
          <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center', color: 'rgba(255,255,255,0.25)' }}>
            <div>
              <div style={{ fontSize: '64px', marginBottom: '16px' }}>🖱️</div>
              <p style={{ fontSize: '16px', margin: 0 }}>Click a point on the map</p>
              <p style={{ fontSize: '13px', margin: '8px 0 0 0' }}>Switch to Visualization tab, click anywhere, then come back here</p>
              <p style={{ fontSize: '13px', margin: '4px 0 0 0', color: 'rgba(255,255,255,0.18)' }}>Or draw a region and compute a spatial metric to see it here</p>
            </div>
          </div>
        )}

        {/* ── Section 1: Cone of Uncertainty ── */}
        {clickedPoint && (
          <>
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
          </>
        )}

        {/* ── Section 3: Verification Metrics ── */}
        {clickedPoint && (
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
              {/* Threshold */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ color: 'rgba(255,255,255,0.55)', fontSize: '12px', whiteSpace: 'nowrap' }}>Threshold</span>
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={catThreshold}
                  onChange={e => setCatThreshold(e.target.value)}
                  style={{
                    width: '72px', padding: '4px 8px', fontSize: '13px', fontWeight: '600',
                    background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)',
                    borderRadius: '6px', color: 'white', textAlign: 'right', outline: 'none',
                  }}
                />
                <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: '12px' }}>mm/6h</span>
              </div>

              {/* Hour range */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ color: 'rgba(255,255,255,0.55)', fontSize: '12px', whiteSpace: 'nowrap' }}>Hours</span>
                <input
                  type="number" min="0" step="6" value={catHourMin}
                  onChange={e => setCatHourMin(parseInt(e.target.value, 10) || 0)}
                  style={{ width: '60px', padding: '4px 6px', fontSize: '12px', background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: '6px', color: 'white', textAlign: 'center', outline: 'none' }}
                />
                <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: '12px' }}>–</span>
                <input
                  type="number" min="0" step="24" value={catHourMax}
                  onChange={e => setCatHourMax(parseInt(e.target.value, 10) || 240)}
                  style={{ width: '60px', padding: '4px 6px', fontSize: '12px', background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: '6px', color: 'white', textAlign: 'center', outline: 'none' }}
                />
                <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: '12px' }}>h</span>
              </div>

              {/* Run button */}
              <button
                onClick={handleRunCategorical}
                disabled={catLoading}
                style={{
                  padding: '6px 16px', fontSize: '12px', fontWeight: '700', cursor: catLoading ? 'not-allowed' : 'pointer',
                  background: catLoading ? 'rgba(52,152,219,0.08)' : 'rgba(52,152,219,0.18)',
                  border: '1px solid rgba(52,152,219,0.45)', borderRadius: '8px',
                  color: catLoading ? 'rgba(52,152,219,0.45)' : 'rgba(52,152,219,0.95)',
                  display: 'flex', alignItems: 'center', gap: '6px', transition: 'all 0.15s',
                }}
              >
                {catLoading ? '⏳ Running…' : '▶ Run Metrics'}
              </button>

              {catData && !catLoading && (
                <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.3)' }}>
                  {currentModel.name} · >{catData.threshold_info?.threshold_mm_6h ?? catThreshold} mm/6h
                  {' '}(≡ {catData.threshold_info?.threshold_rate?.toFixed(3) ?? '—'} mm/h)
                </span>
              )}
            </div>

            {/* Error banner */}
            {catError && (
              <div style={{ background: 'rgba(231,76,60,0.12)', border: '1px solid rgba(231,76,60,0.3)', borderRadius: '8px', padding: '10px 14px', marginBottom: '14px', color: '#e74c3c', fontSize: '12px' }}>
                ⚠️ {catError}
              </div>
            )}

            {/* Obs coverage warning banner */}
            {catData && catData.obs_warning && (
              <div style={{ background: 'rgba(243,156,18,0.10)', border: '1px solid rgba(243,156,18,0.3)', borderRadius: '8px', padding: '8px 14px', marginBottom: '16px', color: '#f39c12', fontSize: '12px', display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                <span style={{ flexShrink: 0 }}>⚠️</span>
                <span>{catData.obs_warning}</span>
              </div>
            )}

            {/* Empty-hours result */}
            {catHasRun && !catLoading && catData && catData.hours?.length === 0 && (
              <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: '13px', padding: '16px 0' }}>
                No overlapping observations found for this location and time window. Try a different point or extend the hour range.
              </div>
            )}

            {/* ── Stat badges ── */}
            {catData && catData.summary && catData.hours?.length > 0 && (() => {
              const s = catData.summary;
              const cc = s.composite_confidence;

              const metricColor = (key, val) => {
                if (val == null) return '#666';
                if (key === 'csi')  return val >= 0.5 ? '#2ecc71' : val >= 0.3 ? '#f39c12' : '#e74c3c';
                if (key === 'pod')  return val >= 0.7 ? '#2ecc71' : val >= 0.5 ? '#f39c12' : '#e74c3c';
                if (key === 'far')  return val <= 0.3 ? '#2ecc71' : val <= 0.5 ? '#f39c12' : '#e74c3c';
                if (key === 'fbi')  return val >= 0.8 && val <= 1.2 ? '#2ecc71' : '#f39c12';
                if (key === 'bs')   return val <= 0.1 ? '#2ecc71' : val <= 0.25 ? '#f39c12' : '#e74c3c';
                if (key === 'cc')   return val >= 0.6 ? '#2ecc71' : val >= 0.4 ? '#f39c12' : '#e74c3c';
                return '#aaa';
              };

              const badges = [
                { key: 'csi', label: 'CSI',    hint: 'Critical Success Index (0→1, higher=better)', val: s.csi   },
                { key: 'pod', label: 'POD',    hint: 'Probability of Detection (hit rate)',          val: s.pod   },
                { key: 'far', label: 'FAR',    hint: 'False Alarm Ratio (0=perfect)',                val: s.far   },
                { key: 'fbi', label: 'FBI',    hint: 'Frequency Bias (1=unbiased)',                  val: s.fbi   },
                { key: 'bs',  label: 'Brier',  hint: 'Brier Score (0=perfect)',                      val: s.brier_score },
              ];

              const contingencyTotal = s.hits + s.misses + s.false_alarms + s.correct_neg;

              return (
                <>
                  {/* Badges row */}
                  <div style={{ display: 'flex', gap: '10px', marginBottom: '20px', flexWrap: 'wrap' }}>
                    {badges.map(({ key, label, hint, val }) => (
                      <div key={key} style={{
                        background: 'rgba(255,255,255,0.06)', borderRadius: '10px',
                        padding: '12px 16px', minWidth: '100px',
                        borderLeft: `3px solid ${metricColor(key, val)}`,
                      }}>
                        <div style={{ color: metricColor(key, val), fontSize: '22px', fontWeight: '700', lineHeight: 1 }}>
                          {val != null ? val.toFixed(3) : 'N/A'}
                        </div>
                        <div style={{ color: 'rgba(255,255,255,0.7)', fontSize: '12px', marginTop: '4px', fontWeight: '600' }}>{label}</div>
                        <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: '10px', marginTop: '2px' }}>{hint}</div>
                      </div>
                    ))}

                    {/* Composite Confidence badge — wider, highlighted */}
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
                        0.40×CSI + 0.20×POD + 0.10×(1–FAR) ÷ 0.70
                      </div>
                      <div style={{ color: 'rgba(255,255,255,0.2)', fontSize: '10px', marginTop: '1px' }}>FSS = N/A (spatial-only)</div>
                    </div>
                  </div>

                  {/* Contingency table mini-summary */}
                  <div style={{ display: 'flex', gap: '8px', marginBottom: '20px', flexWrap: 'wrap' }}>
                    {[
                      { label: 'Hits',         val: s.hits,         color: '#2ecc71' },
                      { label: 'Misses',        val: s.misses,       color: '#e74c3c' },
                      { label: 'False Alarms',  val: s.false_alarms, color: '#f39c12' },
                      { label: 'Correct Neg.',  val: s.correct_neg,  color: '#3498db' },
                    ].map(({ label, val, color }) => (
                      <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '5px', background: 'rgba(255,255,255,0.04)', borderRadius: '6px', padding: '5px 10px', border: `1px solid ${color}33` }}>
                        <span style={{ color, fontWeight: '700', fontSize: '13px' }}>{val}</span>
                        <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: '11px' }}>{label}</span>
                      </div>
                    ))}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px', background: 'rgba(255,255,255,0.04)', borderRadius: '6px', padding: '5px 10px', border: '1px solid rgba(255,255,255,0.1)' }}>
                      <span style={{ color: 'rgba(255,255,255,0.6)', fontWeight: '700', fontSize: '13px' }}>{contingencyTotal}</span>
                      <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: '11px' }}>Total cases</span>
                    </div>
                  </div>

                  {/* Event Probability chart */}
                  <div>
                    <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: '12px', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
                      <span>Event Probability per Lead Time (threshold &gt; {catData.threshold_info?.threshold_mm_6h ?? catThreshold} mm/6h)</span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <span style={{ display: 'inline-block', width: '10px', height: '10px', background: 'rgba(52,152,219,0.6)', borderRadius: '2px' }} />
                        P(event) — Gaussian
                      </span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <span style={{ display: 'inline-block', width: '14px', height: '3px', background: '#2ecc71', borderRadius: '1px' }} />
                        Observed event
                      </span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <span style={{ display: 'inline-block', width: '14px', height: '2px', background: '#e74c3c', borderRadius: '1px', borderTop: '2px dashed #e74c3c' }} />
                        Forecast event (deterministic)
                      </span>
                    </div>
                    <ResponsiveContainer width="100%" height={230}>
                      <ComposedChart data={catData.hours} margin={{ top: 8, right: 20, left: 0, bottom: 20 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                        <XAxis
                          dataKey="hour"
                          stroke="rgba(255,255,255,0.3)"
                          tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }}
                          tickFormatter={h => `+${h}h`}
                          label={{ value: 'Forecast Hour', position: 'insideBottom', offset: -12, fill: 'rgba(255,255,255,0.4)', fontSize: 11 }}
                        />
                        <YAxis
                          domain={[0, 1]}
                          stroke="rgba(255,255,255,0.3)"
                          tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }}
                          tickFormatter={v => `${(v * 100).toFixed(0)}%`}
                          label={{ value: 'Probability', angle: -90, position: 'insideLeft', fill: 'rgba(255,255,255,0.4)', fontSize: 11 }}
                        />
                        <Tooltip
                          contentStyle={{ background: '#1a2535', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '8px', color: 'white', fontSize: '12px' }}
                          formatter={(value, name) => {
                            if (name === 'P(event)')          return [`${(value * 100).toFixed(1)}%`, 'P(event) Gaussian'];
                            if (name === 'Obs event')         return [value === 1 ? 'Yes' : 'No', 'Observed event'];
                            if (name === 'Fcst event')        return [value === 1 ? 'Yes' : 'No', 'Forecast event (det.)'];
                            if (name === 'Mean rate (mm/h)')  return [Number(value).toFixed(4) + ' mm/h', 'Ens. mean rate'];
                            return [value, name];
                          }}
                          labelFormatter={h => `Forecast +${h}h`}
                        />
                        {/* P(event) bars */}
                        <Bar dataKey="p_event" name="P(event)" fill="rgba(52,152,219,0.55)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
                        {/* Observed event step line */}
                        <Line type="stepAfter" dataKey="is_obs"  name="Obs event"  stroke="#2ecc71" strokeWidth={2.5} dot={{ r: 4, fill: '#2ecc71' }} isAnimationActive={false} connectNulls />
                        {/* Deterministic forecast event dashed line */}
                        <Line type="stepAfter" dataKey="is_fcst" name="Fcst event" stroke="#e74c3c" strokeWidth={1.5} strokeDasharray="5 3" dot={false} isAnimationActive={false} connectNulls />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </>
              );
            })()}

            {/* Pre-run placeholder */}
            {!catHasRun && !catLoading && (
              <div style={{ color: 'rgba(255,255,255,0.25)', fontSize: '13px', padding: '28px 0', textAlign: 'center' }}>
                Set a threshold and click <strong style={{ color: 'rgba(52,152,219,0.6)' }}>▶ Run Metrics</strong> to generate verification scores
              </div>
            )}
          </div>
        )}

        {/* ── Section 4: Spatial Metric Map ── */}
        {spatialData?.points?.length > 0 && (
          <div style={{ marginTop: clickedPoint ? '32px' : '0', marginBottom: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
              <h3 style={{ color: 'rgba(255,255,255,0.85)', fontSize: '14px', fontWeight: '600', margin: 0, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                🗺️ Spatial Metric Map
              </h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)' }}>
                  {spatialData.metric === 'ssr'
                    ? `SSR · +${spatialData.hour ?? metricHour}h · ${spatialData.points.length} pts`
                    : `Spread-Skill Corr. · ${spatialData.n_hours} lead times · ${spatialData.points.length} pts`}
                </span>
                <span style={{ fontSize: '10px', color: 'rgba(52,152,219,0.7)', background: 'rgba(52,152,219,0.12)', padding: '2px 8px', borderRadius: '10px', border: '1px solid rgba(52,152,219,0.25)' }}>
                  {currentModel.name}
                </span>
                {/* Export actions — only shown when image is ready */}
                {analysisPlotUrl && !analysisPlotLoading && (
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <button onClick={handleDownload} style={btnBase} title="Download as PNG">
                      ⬇ Download
                    </button>
                    <button
                      onClick={handleShare}
                      style={{
                        ...btnBase,
                        ...(shareState === 'copied' ? { background: 'rgba(46,204,113,0.15)', borderColor: 'rgba(46,204,113,0.4)', color: '#2ecc71' } : {}),
                      }}
                      title="Copy image to clipboard"
                    >
                      {shareState === 'copied' ? '✓ Copied!' : '⎘ Share'}
                    </button>
                  </div>
                )}
              </div>
            </div>

            <div style={{ width: '100%', borderRadius: '10px', overflow: 'hidden', border: '1px solid rgba(255,255,255,0.1)', background: '#111', minHeight: '120px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              {analysisPlotLoading && (
                <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: '13px', padding: '60px 0', textAlign: 'center' }}>
                  <div style={{ fontSize: '28px', marginBottom: '10px' }}>⏳</div>
                  Rendering map…
                </div>
              )}
              {!analysisPlotLoading && analysisPlotUrl && (
                <img
                  ref={analysisSpatialCanvasRef}
                  src={analysisPlotUrl}
                  alt="Spatial metric map"
                  style={{ maxWidth: '100%', maxHeight: '380px', width: 'auto', display: 'block', margin: '0 auto' }}
                />
              )}
              {!analysisPlotLoading && !analysisPlotUrl && (
                <div style={{ color: 'rgba(255,255,255,0.2)', fontSize: '12px', padding: '40px 0' }}>
                  Map will appear here after computing a spatial metric
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Compare shortcut ── */}
        {clickedPoint && (
          <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', padding: '14px 0 4px', display: 'flex', justifyContent: 'flex-end' }}>
            <button
              onClick={onCompare}
              style={{ background: 'rgba(52,152,219,0.12)', border: '1px solid rgba(52,152,219,0.3)', color: 'rgba(52,152,219,0.9)', fontSize: '12px', fontWeight: '600', padding: '6px 14px', borderRadius: '8px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              ⚖️ Compare models at this point →
            </button>
          </div>
        )}

      </div>
    </div>
  );
}
