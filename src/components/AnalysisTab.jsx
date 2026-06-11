import React from 'react';
import {
  AreaChart, Area, BarChart, Bar, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';

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
}) {
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

        {/* ── Section 3: Spatial Metric Map ── */}
        {spatialData?.points?.length > 0 && (
          <div style={{ marginTop: clickedPoint ? '32px' : '0', marginBottom: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <h3 style={{ color: 'rgba(255,255,255,0.85)', fontSize: '14px', fontWeight: '600', margin: 0, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                🗺️ Spatial Metric Map
              </h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)' }}>
                  {spatialData.metric === 'ssr'
                    ? `SSR · +${spatialData.hour ?? metricHour}h · ${spatialData.points.length} pts`
                    : `Spread-Skill Corr. · ${spatialData.n_hours} lead times · ${spatialData.points.length} pts`}
                </span>
                <span style={{ fontSize: '10px', color: 'rgba(52,152,219,0.7)', background: 'rgba(52,152,219,0.12)', padding: '2px 8px', borderRadius: '10px', border: '1px solid rgba(52,152,219,0.25)' }}>
                  {currentModel.name}
                </span>
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
                  style={{ width: '100%', display: 'block' }}
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

      </div>
    </div>
  );
}
