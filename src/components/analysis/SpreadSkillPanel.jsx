/**
 * Spread-Skill: does the ensemble's disagreement match its error?
 *
 * Presentational — the data arrives as props from the tab, which fetches it
 * for the clicked point. It keeps only the chart ref its PNG export reads
 * (`NEXT_STEPS.md` §60).
 *
 * `ssrBarColor` mirrors the five-tier SSR scale the backend's map legend uses
 * (`flask_api.py` PLOT_STYLE_REGISTRY['ssr']), so the bar a reader sees here
 * and the cell they see on the map agree about what 0.9 looks like. It lives
 * beside the only panel that draws it.
 */
import React, { useRef } from 'react';
import {
  Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';

import { t } from '../../theme';
import { fmtLat, fmtLon } from '../../utils/geoUtils';
import { LoadingState, NoDataNote } from '../ui/PanelState';
import { downloadChartAsPng } from './chartExport';


/** The backend's five-tier SSR scale, so every SSR view agrees. */
export const ssrBarColor = (ssr) => {
  if (ssr === null) return '#555';
  if (ssr < 0.5) return '#c00000';
  if (ssr < 0.8) return '#e74c3c';
  if (ssr <= 1.2) return '#27ae60';
  if (ssr <= 2.0) return '#e67e22';
  return '#3498db';
};


export function SpreadSkillPanel({
  ssrData, ssrLoading, currentModel, obsCoverage, verifiedAgainst, yAxisUnit,
}) {
  const ssrChartRef = useRef(null);

  return (
        <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '24px' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '16px', marginBottom: '12px', flexWrap: 'wrap' }}>
            <h3 style={{ color: 'rgba(255,255,255,0.85)', fontSize: t.fontSize.md, fontWeight: t.fontWeight.semibold, margin: 0, letterSpacing: '0.02em' }}>
              Spread-Skill Analysis
            </h3>
            <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: t.fontSize.sm }}>
              {verifiedAgainst}{' · Lead times with obs shown'}
            </span>
            {/* Which sample these numbers came from. This used to warn that
                Analysis and Comparison could legitimately disagree, because
                Analysis read the members and Comparison the regridded
                aggregates. Both point paths now run `_member_cases_by_cell`
                and share `_point_summary`, so they agree exactly — the old
                wording would send a user looking for a difference that the
                member-grid migration removed. */}
            {ssrData?.cell && (
              <span
                style={{
                  fontSize: t.fontSize.xs, color: 'rgba(255,255,255,0.4)',
                  background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.12)',
                  borderRadius: '10px', padding: '2px 9px',
                }}
                title="Scored from the individual ensemble members in the nearest cell of the shared 0.5° grid. The Comparison tab scores this point from the same members by the same method, so the two tabs agree at any lead time they both cover."
              >
                ensemble members @ {fmtLat(ssrData.cell[0], 2)}, {fmtLon(ssrData.cell[1], 2)}
                {ssrData.hours?.[0]?.n_members != null && ` · ${ssrData.hours[0].n_members} members`}
              </span>
            )}
            {ssrData && ssrData.n_cases > 0 && (
              <button onClick={() => downloadChartAsPng(ssrChartRef, `WEAVE-ssr-${currentModel?.name}.png`)}
                style={{ marginLeft: 'auto', fontSize: t.fontSize.base, color: 'rgba(255,255,255,0.45)', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '5px', cursor: 'pointer', padding: '2px 8px' }}
                title="Download chart as PNG">⬇</button>
            )}
          </div>

          {ssrLoading && (
            <LoadingState label="Loading spread-skill data…" />
          )}

          {!ssrLoading && ssrData && ssrData.n_cases === 0 && (
            <NoDataNote
              /* Name the extent rather than leaving the user to guess whether
                 this is missing data, the wrong place, or a broken app. */
              detail={obsCoverage?.last_verifiable_hour != null
                ? `${obsCoverage.source} observations for this run end `
                  + `${obsCoverage.record_end_lead_hours}h after initialisation, `
                  + `so verification is available to +${obsCoverage.last_verifiable_hour}h.`
                : null}>
              No overlapping observations found for this location and time window
            </NoDataNote>
          )}

          {!ssrLoading && ssrData && ssrData.n_cases > 0 && (() => {
            const corrVal      = ssrData.correlation;
            const corrColor    = corrVal === null ? '#aaa' : corrVal >= 0.7 ? '#2ecc71' : corrVal >= 0.4 ? '#f39c12' : '#e74c3c';
            // Mean over hours that actually have an SSR. If none do, SSR is
            // undefined (no matched obs / zero error everywhere) — must not
            // collapse to 0 and read as "severely overconfident".
            // The backend's pooled SSR, not a mean of the per-hour
            // ratios: E[X/Y] != E[X]/E[Y], and one near-zero error drags a
            // mean to the clamp. Comparison shows the same estimator, so
            // computing a different one here made the panels disagree.
            const summary = ssrData.summary || {};
            const meanSSR = summary.ssr_agg ?? null;
            // Mirrors the 5-tier SSR scale used by the backend's map legend
            // (flask_api.py PLOT_STYLE_REGISTRY['ssr']) for colors/thresholds,
            // but uses plain confidence language (matching the readout sentence
            // below) instead of "-dispersive" jargon.
            const ssrTier = (
              meanSSR === null ? { label: 'Undefined', color: '#95a5a6' } :
              meanSSR < 0.5 ? { label: 'Severely overconfident', color: '#c00000' } :
              meanSSR < 0.8 ? { label: 'Overconfident', color: '#e74c3c' } :
              meanSSR <= 1.2 ? { label: 'Well calibrated', color: '#27ae60' } :
              meanSSR <= 2.0 ? { label: 'Underconfident', color: '#e67e22' } :
              { label: 'Severely underconfident', color: '#3498db' }
            );
            const meanSSRColor = ssrTier.color;
            const ssrInterpret = ssrTier.label;
            return (
              <>
                {/* Stat badges */}
                <div style={{ display: 'flex', gap: '12px', marginBottom: '20px', flexWrap: 'wrap' }}>
                  {[
                    { label: 'Spread-Skill Correlation', value: corrVal !== null ? corrVal.toFixed(3) : 'N/A', color: corrColor, hint: 'corr(σ, |ε|) across lead times' },
                    { label: 'SSR (aggregated)', value: meanSSR !== null ? meanSSR.toFixed(3) : 'N/A', color: meanSSRColor, hint: ssrInterpret },
                    { label: 'Verified Hours',   value: ssrData.n_cases,    color: '#3498db',    hint: 'Lead times with matching observations' },
                  ].map(({ label, value, color, hint }) => (
                    <div key={label} style={{ background: 'rgba(255,255,255,0.06)', borderRadius: '10px', padding: '12px 18px', minWidth: '140px', borderLeft: `3px solid ${color}` }}>
                      <div style={{ color, fontSize: t.fontSize.stat, fontWeight: t.fontWeight.bold, lineHeight: 1 }}>{value}</div>
                      <div style={{ color: 'rgba(255,255,255,0.7)', fontSize: t.fontSize.sm, marginTop: '4px', fontWeight: t.fontWeight.medium }}>{label}</div>
                      <div style={{ color: 'rgba(255,255,255,0.35)', fontSize: t.fontSize.xs, marginTop: '2px' }}>{hint}</div>
                    </div>
                  ))}
                </div>

                {/* Accuracy against observations.

                    CONSISTENCY_AUDIT.md finding 1a: these four were
                    available at a point in Comparison and nowhere in
                    Analysis, so "how wrong is this forecast, here?" was
                    answerable in one tab and not the other for the same
                    click. They come from the same /api/spread-skill cases
                    as the spread numbers above — no second request, and no
                    way for the two to disagree. */}
                <div style={{ display: 'flex', gap: '12px', marginBottom: '20px', flexWrap: 'wrap' }}>
                  {[
                    { label: 'Bias', value: summary.bias, hint: `mean error · 0 is unbiased · ${yAxisUnit}` },
                    { label: 'MAE',  value: summary.mae,  hint: `mean absolute error · ${yAxisUnit}` },
                    { label: 'RMSE', value: summary.rmse, hint: `root mean square error · ${yAxisUnit}` },
                    { label: 'CRPS', value: summary.crps, hint: `probabilistic error · ${yAxisUnit}` },
                  ].map(({ label, value, hint }) => (
                    <div key={label} style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '10px', padding: '10px 16px', minWidth: '120px', borderLeft: '3px solid rgba(255,255,255,0.18)' }}>
                      <div style={{ color: 'rgba(255,255,255,0.85)', fontSize: t.fontSize.stat, fontWeight: t.fontWeight.bold, lineHeight: 1 }}>
                        {value != null ? value.toFixed(3) : 'N/A'}
                      </div>
                      <div style={{ color: 'rgba(255,255,255,0.7)', fontSize: t.fontSize.sm, marginTop: '4px', fontWeight: t.fontWeight.medium }}>{label}</div>
                      <div style={{ color: 'rgba(255,255,255,0.35)', fontSize: t.fontSize.xs, marginTop: '2px' }}>{hint}</div>
                    </div>
                  ))}
                </div>

                {/* Plain-language readout */}
                <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start', marginBottom: '20px', padding: '10px 14px', background: `${meanSSRColor}22`, border: `1px solid ${meanSSRColor}55`, borderRadius: t.radius, fontSize: t.fontSize.base, color: 'rgba(255,255,255,0.85)', lineHeight: 1.5 }}>
                  <span style={{ fontSize: t.fontSize.lg, lineHeight: 1.2 }}>ℹ️</span>
                  <span>
                    {meanSSR === null
                      ? "Not enough matched observations here to assess calibration — the spread-skill ratio is undefined."
                      : meanSSR >= 0.8 && meanSSR <= 1.2
                      ? "The ensemble spread here looks about right — its uncertainty roughly matches its actual errors."
                      : meanSSR < 0.5
                        ? "The forecast looks severely overconfident here — the members agree far more closely than the model's real errors justify."
                        : meanSSR < 0.8
                          ? "The forecast looks overconfident here — the members agree more closely than the model's real errors would justify."
                          : meanSSR <= 2.0
                            ? "The forecast looks underconfident here — the members disagree more than the model's real errors would justify."
                            : "The forecast looks severely underconfident here — the members disagree far more than the model's real errors justify."}
                  </span>
                </div>

                {/* Two charts */}
                <div ref={ssrChartRef} style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
                  {/* Chart A: SSR per hour */}
                  <div style={{ flex: '1 1 340px', minWidth: 0 }}>
                    <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: t.fontSize.sm, marginBottom: '6px' }}>
                      Spread-Skill Ratio per Lead Time &nbsp;
                      <span style={{ color: '#c00000' }}>■</span> sev. overconfident &nbsp;
                      <span style={{ color: '#e74c3c' }}>■</span> overconfident &nbsp;
                      <span style={{ color: '#27ae60' }}>■</span> calibrated &nbsp;
                      <span style={{ color: '#e67e22' }}>■</span> underconfident &nbsp;
                      <span style={{ color: '#3498db' }}>■</span> sev. underconfident
                    </div>
                    <ResponsiveContainer width="100%" height={220}>
                      <BarChart data={ssrData.hours} margin={{ top: 8, right: 20, left: 0, bottom: 20 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                        <XAxis dataKey="hour" stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }} tickFormatter={h => `+${h}h`} label={{ value: 'Forecast Hour', position: 'insideBottom', offset: -10, fill: 'rgba(255,255,255,0.4)', fontSize: 11 }} />
                        <YAxis stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }} label={{ value: 'SSR', angle: -90, position: 'insideLeft', fill: 'rgba(255,255,255,0.4)', fontSize: 11 }} />
                        <Tooltip
                          contentStyle={{ background: '#1a2535', border: '1px solid rgba(255,255,255,0.15)', borderRadius: t.radius, color: 'white', fontSize: t.fontSize.sm }}
                          formatter={(value) => [value !== null ? Number(value).toFixed(3) : 'N/A (zero error)', 'SSR']}
                          labelFormatter={h => `Forecast +${h}h — ${ssrData.hours.find(r => r.hour === h)?.n_members} members`} />
                        <ReferenceLine y={1} stroke="rgba(255,255,255,0.5)" strokeDasharray="6 3" label={{ value: 'SSR=1', position: 'right', fill: 'rgba(255,255,255,0.5)', fontSize: 10 }} />
                        <Bar dataKey="ssr" radius={[4, 4, 0, 0]} name="SSR">
                          {ssrData.hours.map((entry, i) => (
                            <Cell key={`${entry.hour}-${i}`} fill={ssrBarColor(entry.ssr)} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>

                  {/* Chart B: Spread vs |Error| */}
                  <div style={{ flex: '1 1 340px', minWidth: 0 }}>
                    <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: t.fontSize.sm, marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                      <span>Ensemble Spread vs Absolute Error per Lead Time</span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: t.fontSize.xs }}>
                        <span style={{ display: 'inline-block', width: '10px', height: '10px', background: '#3498db', borderRadius: '2px' }} />Spread (σ)
                      </span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: t.fontSize.xs }}>
                        <span style={{ display: 'inline-block', width: '10px', height: '10px', background: '#e74c3c', borderRadius: '2px' }} />|Error|
                      </span>
                    </div>
                    <ResponsiveContainer width="100%" height={220}>
                      <BarChart data={ssrData.hours} margin={{ top: 8, right: 20, left: 0, bottom: 28 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                        <XAxis dataKey="hour" stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }} tickFormatter={h => `+${h}h`} label={{ value: 'Forecast Hour', position: 'insideBottom', offset: -12, fill: 'rgba(255,255,255,0.4)', fontSize: 11 }} />
                        <YAxis stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }} label={{ value: yAxisUnit, angle: -90, position: 'insideLeft', fill: 'rgba(255,255,255,0.4)', fontSize: 11 }} />
                        <Tooltip
                          contentStyle={{ background: '#1a2535', border: '1px solid rgba(255,255,255,0.15)', borderRadius: t.radius, color: 'white', fontSize: t.fontSize.sm }}
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
            <NoDataNote>Spread-skill data unavailable</NoDataNote>
          )}
        </div>
  );
}

export default SpreadSkillPanel;
