/**
 * The Cone of Uncertainty: the ensemble's spread at a clicked point, over lead
 * time.
 *
 * Owns the one piece of state it is about — whether the band is drawn as a
 * Gaussian ±σ or as the empirical P10–P90 — and the chart ref its PNG export
 * reads. Everything else arrives as props (`NEXT_STEPS.md` §60).
 *
 * The two bands answer different questions and the toggle is not cosmetic: ±σ
 * assumes a shape the ensemble may not have, while P10–P90 is what the members
 * actually did. A skewed precipitation distribution shows the difference
 * plainly, which is why both are offered rather than one being chosen here.
 */
import React, { useState, useRef } from 'react';
import {
  Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';

import { t } from '../../theme';
import { LoadingState, NoDataNote } from '../ui/PanelState';
import { downloadChartAsPng } from './chartExport';


export function ConeOfUncertaintyPanel({
  timeseriesData, timeseriesLoading, currentModel, selectedVariable,
}) {
  const [coneMode, setConeMode] = useState('gaussian');  // 'gaussian' | 'empirical'
  const coneChartRef = useRef(null);

  return (
        <div style={{ marginBottom: '32px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '12px', flexWrap: 'wrap' }}>
            <h3 style={{ color: 'rgba(255,255,255,0.85)', fontSize: t.fontSize.md, fontWeight: t.fontWeight.semibold, margin: 0, letterSpacing: '0.02em' }}>
              Cone of Uncertainty
            </h3>
            {/* Gaussian / Empirical toggle */}
            <div style={{ display: 'flex', borderRadius: t.radiusSm, overflow: 'hidden', border: '1px solid rgba(255,255,255,0.12)' }}>
              {[{ id: 'gaussian', label: 'Gaussian ±σ' }, { id: 'empirical', label: 'Empirical P10–P90' }].map(({ id, label }) => (
                <button key={id} onClick={() => setConeMode(id)}
                  style={{ padding: '4px 12px', fontSize: t.fontSize.xs, fontWeight: t.fontWeight.semibold, cursor: 'pointer', border: 'none', outline: 'none',
                    background: coneMode === id ? 'rgba(52,152,219,0.22)' : 'rgba(255,255,255,0.04)',
                    color:      coneMode === id ? 'rgba(52,152,219,0.95)' : 'rgba(255,255,255,0.4)' }}>
                  {label}
                </button>
              ))}
            </div>
            {coneMode === 'gaussian' && selectedVariable === 'precipitation' && (
              <span style={{ fontSize: t.fontSize.xs, color: 'rgba(243,156,18,0.7)' }} title="Gaussian bands can go negative for skewed precipitation distributions">⚠ Gaussian bands may go negative for precip — try Empirical</span>
            )}
            {timeseriesData && (
              <button onClick={() => downloadChartAsPng(coneChartRef, `WEAVE-cone-${currentModel?.name}.png`)}
                style={{ marginLeft: 'auto', fontSize: t.fontSize.base, color: 'rgba(255,255,255,0.45)', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '5px', cursor: 'pointer', padding: '2px 8px' }}
                title="Download chart as PNG">⬇</button>
            )}
          </div>

          {timeseriesLoading && (
            <LoadingState label="Loading forecast data…" />
          )}

          {!timeseriesLoading && timeseriesData && (
            <div ref={coneChartRef} style={{ height: '320px' }}>
              {/* Legend */}
              {(() => {
                const legendItems = coneMode === 'gaussian' ? [
                  { color: '#7ec8f7',              label: 'Ensemble Mean', solid: true },
                  { color: 'rgba(52,152,219,0.4)', label: '±1σ (68%)',     solid: false },
                  { color: 'rgba(52,152,219,0.15)',label: '±2σ (95%)',     solid: false },
                ] : [
                  { color: '#7ec8f7',              label: 'Ensemble Mean', solid: true },
                  { color: 'rgba(52,152,219,0.45)',label: 'P25–P75 (IQR)', solid: false },
                  { color: 'rgba(52,152,219,0.18)',label: 'P10–P90',       solid: false },
                ];
                return (
                  <div style={{ display: 'flex', gap: '20px', marginBottom: '10px', flexWrap: 'wrap' }}>
                    {legendItems.map(({ color, label, solid }) => (
                      <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <div style={{ width: '24px', height: solid ? '3px' : '12px', background: color, borderRadius: '2px' }} />
                        <span style={{ color: 'rgba(255,255,255,0.6)', fontSize: t.fontSize.sm }}>{label}</span>
                      </div>
                    ))}
                  </div>
                );
              })()}
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
                    label={{ value: selectedVariable === 'wind' ? 'Wind Speed (m/s)' : 'Precipitation (mm/h)', angle: -90, position: 'insideLeft', fill: 'rgba(255,255,255,0.4)', fontSize: 12 }} />
                  <Tooltip
                    contentStyle={{ background: '#1a2535', border: '1px solid rgba(255,255,255,0.15)', borderRadius: t.radius, color: 'white', fontSize: t.fontSize.sm }}
                    formatter={(value, name) => {
                      if (value == null) return null;
                      const labels = coneMode === 'gaussian'
                        ? { mean: 'Mean', band2Hi: '+2σ', band2Lo: '-2σ', band1Hi: '+1σ', band1Lo: '-1σ' }
                        : { mean: 'Mean', p90: 'P90', p10: 'P10', p75: 'P75', p25: 'P25' };
                      return [typeof value === 'number' ? value.toFixed(3) : value, labels[name] || name];
                    }}
                    labelFormatter={hour => `Forecast +${hour}h (Day ${(hour/24).toFixed(1)})`} />
                  {coneMode === 'gaussian' ? <>
                    <Area type="monotone" dataKey="band2Hi" stroke="none" fill="url(#cone2grad)" fillOpacity={1} legendType="none" name="band2Hi" />
                    <Area type="monotone" dataKey="band2Lo" stroke="none" fill="#0f1923"         fillOpacity={1} legendType="none" name="band2Lo" />
                    <Area type="monotone" dataKey="band1Hi" stroke="none" fill="url(#cone1grad)" fillOpacity={1} legendType="none" name="band1Hi" />
                    <Area type="monotone" dataKey="band1Lo" stroke="none" fill="#0f1923"         fillOpacity={1} legendType="none" name="band1Lo" />
                  </> : <>
                    <Area type="monotone" dataKey="p90" stroke="none" fill="url(#cone2grad)" fillOpacity={1} legendType="none" name="p90" />
                    <Area type="monotone" dataKey="p10" stroke="none" fill="#0f1923"         fillOpacity={1} legendType="none" name="p10" />
                    <Area type="monotone" dataKey="p75" stroke="none" fill="url(#cone1grad)" fillOpacity={1} legendType="none" name="p75" />
                    <Area type="monotone" dataKey="p25" stroke="none" fill="#0f1923"         fillOpacity={1} legendType="none" name="p25" />
                  </>}
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
            <NoDataNote>No forecast data available for this location</NoDataNote>
          )}
        </div>
  );
}

export default ConeOfUncertaintyPanel;
