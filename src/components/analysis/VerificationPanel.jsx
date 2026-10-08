/**
 * Verification metrics: the contingency-table scores for one model, at a
 * clicked cell or over a drawn region.
 *
 * **This panel takes no settings props.** Threshold, lead range, FSS
 * neighbourhood and scored area come from `useVerification()`, which is the
 * whole reason the four stages in `VERIFICATION_SETTINGS_DESIGN.md` were done
 * in that order: §60 could not extract this panel because the settings were
 * the tab's, and passing eight props down would have moved lines without
 * moving behaviour. They are the app's now, so this is a plain move.
 *
 * What it does own is its own results — the point scores, the region scores,
 * and which of the two the "Score over" toggle is showing. `catMode` is that
 * toggle, and it is deliberately NOT the tab's Point/Region mode:
 * `CONSISTENCY_AUDIT.md` 3a found the two reading as duplicates, checked
 * whether the nested one was redundant, and found it was the only route to the
 * region-scored categorical numbers. It names the areas rather than repeating
 * the mode for that reason.
 *
 * Stale results are dropped when the variable changes, because 25 mm/6h and
 * 10 m/s are not the same bar and a panel showing precipitation CSI under a
 * wind heading is worse than an empty one.
 */
import React, { useEffect, useRef, useState } from 'react';
import {
  Bar, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';

import { fetchCategoricalMetrics, fetchRegionCategoricalMetrics } from '../../api/analysisApi';
import { VERIFICATION_DEFAULTS as VD } from '../../constants';
import { useVerification } from '../../state/VerificationContext';
import { t } from '../../theme';
import { fmtLat, fmtLon } from '../../utils/geoUtils';
import { downloadChartAsPng } from './chartExport';


export function VerificationPanel({
  clickedPoint, selectedRegion, currentModel, selectedVariable,
}) {
  const {
    threshold, thresholdNum, setThreshold,
    hourMin, setHourMin, hourMax, setHourMax,
    fssWindow, setFssWindow,
    boxCells: catBoxCells, setBoxCells: setCatBoxCells,
  } = useVerification();

  const catChartRef = useRef(null);

  const [catLoading,   setCatLoading]     = useState(false);
  const [catData,      setCatData]        = useState(null);  // full API response
  const [catError,     setCatError]       = useState(null);
  const [catHasRun,    setCatHasRun]      = useState(false);

  // ── Region categorical state ────────────────────────────────────────────────
  const [catMode,        setCatMode]        = useState('point');  // 'point' | 'region'
  // `fssWindow` and `catBoxCells` come from the same context as the threshold
  // above. FSS only means something relative to a spatial scale — "skilful at
  // 2.5 degrees" — and the scored area affects FSS and nothing else: the
  // contingency table reads the centre cell at every width (verified — hits,
  // misses and false alarms are identical at 1, 3, 5 and 9).
  const [regCatLoading,  setRegCatLoading]  = useState(false);
  const [regCatData,     setRegCatData]     = useState(null);
  const [regCatError,    setRegCatError]    = useState(null);
  const [regCatHasRun,   setRegCatHasRun]   = useState(false);

  // A threshold in mm/6h means nothing in m/s, so results do not survive the
  // switch. The threshold itself is re-seeded by the tab, which owns the
  // variable.
  useEffect(() => {
    setCatData(null);
    setCatHasRun(false);
    setRegCatData(null);
    setRegCatHasRun(false);
  }, [selectedVariable]);

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
        thresholdMm6h: thresholdNum,
        hourMin,
        hourMax,
        boxCells:     catBoxCells,
        fssWindow,
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
        thresholdMm6h: thresholdNum,
        hourMin,
        hourMax,
        fssWindow,
      });
      setRegCatData(data);
    } catch (err) {
      setRegCatError(err.message || 'Failed to load region metrics');
    } finally {
      setRegCatLoading(false);
    }
  };

  return (
    <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '24px', marginTop: '32px' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '16px', marginBottom: '14px', flexWrap: 'wrap' }}>
        <h3 style={{ color: 'rgba(255,255,255,0.85)', fontSize: t.fontSize.md, fontWeight: t.fontWeight.semibold, margin: 0, letterSpacing: '0.02em' }}>
          Verification metrics
        </h3>
        <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: t.fontSize.sm }}>
          CSI · POD · FAR · FBI · Brier Score · Composite Confidence
        </span>
        {(catMode === 'point' ? catData : regCatData) && (
          <button onClick={() => downloadChartAsPng(catChartRef, `WEAVE-verification-${currentModel?.name}.png`)}
            style={{ marginLeft: 'auto', fontSize: t.fontSize.base, color: 'rgba(255,255,255,0.45)', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '5px', cursor: 'pointer', padding: '2px 8px' }}
            title="Download chart as PNG">⬇</button>
        )}
      </div>

      {/* Non-precipitation warning */}
      {selectedVariable !== 'precipitation' && (
        <div style={{ background: 'rgba(243,156,18,0.10)', border: '1px solid rgba(243,156,18,0.3)', borderRadius: t.radius, padding: '8px 14px', marginBottom: '14px', color: '#f39c12', fontSize: t.fontSize.sm }}>
          ⚠️ Categorical metrics (CSI, POD, FAR, Brier) are defined for precipitation exceedance thresholds. Results for <strong>{selectedVariable}</strong> may be unreliable — switch the variable to <em>precipitation</em> for meaningful scores.
        </div>
      )}

      {/* Controls row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>

        {/* What this panel scores over.

            NOT a second copy of the tab's Point|Region switch, though
            it used to read exactly like one — same two words, in the
            same tab, scoping different things
            (CONSISTENCY_AUDIT.md 3a). The tab switch chooses what the
            whole tab is about; this chooses the area the contingency
            table is built from, and it is the only route to the
            region-scored categorical numbers, so it stays. It now
            names the areas instead of repeating the mode. */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: t.fontSize.xs, whiteSpace: 'nowrap' }}>
            Score over
          </span>
          <div style={{ display: 'flex', borderRadius: t.radius, overflow: 'hidden', border: '1px solid rgba(255,255,255,0.15)' }}>
            {[{ id: 'point', label: 'Around a point' },
              { id: 'region', label: 'Drawn region' }].map(({ id, label }) => (
              <button
                key={id}
                onClick={() => setCatMode(id)}
                aria-pressed={catMode === id}
                style={{
                  padding: '5px 14px', fontSize: t.fontSize.sm, fontWeight: t.fontWeight.semibold, cursor: 'pointer',
                  background: catMode === id ? 'rgba(52,152,219,0.25)' : 'rgba(255,255,255,0.04)',
                  color:  catMode === id ? 'rgba(52,152,219,0.95)' : 'rgba(255,255,255,0.4)',
                  border: 'none', outline: 'none',
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Region badge — shown in region mode */}
        {catMode === 'region' && selectedRegion?.bounds && (() => {
          const b = selectedRegion.bounds;
          const mn = b.minLat ?? b.min_lat, mx = b.maxLat ?? b.max_lat;
          const mw = b.minLon ?? b.min_lon, me = b.maxLon ?? b.max_lon;
          return (
            <span style={{ fontSize: t.fontSize.xs, color: 'rgba(52,152,219,0.8)', background: 'rgba(52,152,219,0.10)', padding: '3px 10px', borderRadius: '10px', border: '1px solid rgba(52,152,219,0.25)' }}>
              {fmtLat(mn, 1)}–{fmtLat(mx, 1)} · {fmtLon(mw, 1)}–{fmtLon(me, 1)}
            </span>
          );
        })()}

        {/* No-region warning */}
        {catMode === 'region' && !selectedRegion?.bounds && (
          <span style={{ fontSize: t.fontSize.sm, color: 'rgba(243,156,18,0.8)' }}>
            ⚠️ Draw a region on the map first
          </span>
        )}

        {/* Threshold */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ color: 'rgba(255,255,255,0.55)', fontSize: t.fontSize.sm, whiteSpace: 'nowrap' }} title="Event threshold, in native units. One threshold for this tab: the Region spatial maps score at the same value.">Threshold</span>
          <input
            type="number" min="0" step="1" value={threshold}
            aria-label={`Threshold (${selectedVariable === 'wind' ? 'm/s' : 'mm/6h'})`}
            onChange={e => setThreshold(e.target.value)}
            style={{ width: '72px', padding: '4px 8px', fontSize: t.fontSize.base, fontWeight: t.fontWeight.semibold, background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: t.radiusSm, color: 'white', textAlign: 'right', outline: 'none' }}
          />
          <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: t.fontSize.sm }}>
            {selectedVariable === 'wind' ? 'm/s' : 'mm/6h'}
          </span>
        </div>

        {/* The area every metric here is scored over — point mode
            only, since region mode uses the drawn bbox instead.

            **Called "Scored area" since 2026-10-06, and the previous
            label was right until that day.** It read "FSS area"
            because the control moved FSS and nothing else: CSI, POD,
            FAR, FBI and Brier read the centre cell at every width,
            so "Scored area: 9 cells (≈4.5°)" would have claimed a
            contingency table covering 4.5° that did not exist. The
            comment here used to end by noting that Comparison's
            "Scored area" was a true scored area and that the two
            tabs therefore used different words for the same control.

            That difference is what `NEXT_STEPS.md` §41 removed: the
            point endpoint now pools every categorical metric over
            this box, exactly as Comparison always did, so the two
            tabs mean the same thing and say the same word. At 1 the
            box IS the cell, which is the exact-point case. */}
        {catMode === 'point' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span
              style={{ color: 'rgba(255,255,255,0.55)', fontSize: t.fontSize.sm, whiteSpace: 'nowrap' }}
              title="The area every metric here is scored over, centred on the clicked cell: the contingency table pools every cell in it. Set it to 1 to score the clicked cell alone — FSS is then undefined, since one cell has no neighbourhood."
            >
              Scored area
            </span>
            <input
              type="number" min="1" max="41" step="2" value={catBoxCells}
              aria-label="Scored area width (grid cells)"
              onChange={e => setCatBoxCells(Math.max(1, Math.min(41, parseInt(e.target.value, 10) || 1)))}
              style={{ width: '56px', padding: '4px 6px', fontSize: t.fontSize.sm, fontWeight: t.fontWeight.semibold, background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: t.radiusSm, color: 'white', textAlign: 'center', outline: 'none' }}
            />
            <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: t.fontSize.sm, whiteSpace: 'nowrap' }}>
              {catBoxCells === 1 ? 'cell — FSS undefined' : `cells (≈${(catBoxCells * 0.5).toFixed(1)}°)`}
            </span>
          </div>
        )}

        {/* FSS sliding window, inside that field. Always shown rather
            than appearing once the field is wide enough: a control
            that materialises is harder to find than one that is
            simply inert, and this is the parameter that gives FSS its
            meaning ("skilful at 2.5 degrees"). */}
        {(catMode === 'region' || catMode === 'point') && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span
              style={{ color: 'rgba(255,255,255,0.55)', fontSize: t.fontSize.sm, whiteSpace: 'nowrap' }}
              title="Width of the box FSS compares event fractions over. Wider neighbourhoods forgive small displacement errors."
            >
              FSS neighbourhood
            </span>
            <input
              type="number" min="1" max="21" step="2" value={fssWindow}
              aria-label="FSS neighbourhood width (grid cells)"
              onChange={e => setFssWindow(Math.max(1, Math.min(21, parseInt(e.target.value, 10) || 1)))}
              style={{ width: '56px', padding: '4px 6px', fontSize: t.fontSize.sm, fontWeight: t.fontWeight.semibold, background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: t.radiusSm, color: 'white', textAlign: 'center', outline: 'none' }}
            />
            <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: t.fontSize.sm, whiteSpace: 'nowrap' }}>
              cells (≈{(fssWindow * 0.5).toFixed(1)}°)
            </span>
          </div>
        )}

        {/* Hour range */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ color: 'rgba(255,255,255,0.55)', fontSize: t.fontSize.sm, whiteSpace: 'nowrap' }}>Lead times</span>
          <input type="number" min="0" step="6" value={hourMin}
            onChange={e => setHourMin(parseInt(e.target.value, 10) || VD.HOUR_MIN)}
            style={{ width: '60px', padding: '4px 6px', fontSize: t.fontSize.sm, background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: t.radiusSm, color: 'white', textAlign: 'center', outline: 'none' }} />
          <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.sm }}>–</span>
          <input type="number" min="0" step="24" value={hourMax}
            onChange={e => { const n = parseInt(e.target.value, 10); setHourMax(Number.isNaN(n) ? VD.HOUR_MAX : n); }}
            style={{ width: '60px', padding: '4px 6px', fontSize: t.fontSize.sm, background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: t.radiusSm, color: 'white', textAlign: 'center', outline: 'none' }} />
          <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: t.fontSize.sm }}>h</span>
        </div>

        {/* Run button */}
        <button
          onClick={catMode === 'point' ? handleRunCategorical : handleRunRegionCategorical}
          disabled={catMode === 'point' ? (catLoading || !clickedPoint) : (regCatLoading || !selectedRegion?.bounds)}
          style={{
            padding: '6px 16px', fontSize: t.fontSize.sm, fontWeight: t.fontWeight.bold,
            cursor: (catMode === 'point' ? catLoading : regCatLoading) ? 'not-allowed' : 'pointer',
            background: (catMode === 'point' ? catLoading : regCatLoading) ? 'rgba(52,152,219,0.08)' : 'rgba(52,152,219,0.18)',
            border: '1px solid rgba(52,152,219,0.45)', borderRadius: t.radius,
            color: (catMode === 'point' ? catLoading : regCatLoading) ? 'rgba(52,152,219,0.45)' : 'rgba(52,152,219,0.95)',
            display: 'flex', alignItems: 'center', gap: '6px',
          }}
        >
          {(catMode === 'point' ? catLoading : regCatLoading) ? '⏳ Running…' : '▶ Run Metrics'}
        </button>

        {/* Active result label */}
        {catMode === 'point' && catData && !catLoading && (() => {
          const ti = catData.threshold_info ?? {};
          const thr = ti.threshold_ms ?? ti.threshold_mm_6h ?? thresholdNum;
          const unit = ti.unit ?? (selectedVariable === 'wind' ? 'm/s' : 'mm/6h');
          const rateLabel = ti.unit === 'm/s' ? '' : ` (≡ ${ti.threshold_rate?.toFixed(3) ?? '—'} mm/h)`;
          return (
            <span style={{ fontSize: t.fontSize.xs, color: 'rgba(255,255,255,0.3)' }}>
              {currentModel.name} · &gt;{thr} {unit}{rateLabel}
            </span>
          );
        })()}
        {catMode === 'region' && regCatData && !regCatLoading && (() => {
          const ti = regCatData.threshold_info ?? {};
          const thr = ti.threshold_ms ?? ti.threshold_mm_6h ?? thresholdNum;
          const unit = ti.unit ?? (selectedVariable === 'wind' ? 'm/s' : 'mm/6h');
          return (
            <span style={{ fontSize: t.fontSize.xs, color: 'rgba(255,255,255,0.3)' }}>
              {currentModel.name} · &gt;{thr} {unit} · {regCatData.summary?.n_grid_pts ?? '?'} grid pts
            </span>
          );
        })()}
      </div>

      {/* Error banner */}
      {/* What was actually scored — never leave the area implicit */}
      {(() => {
        const a = catMode === 'point' ? catData?.scored_area : null;
        const shown = catMode === 'point'
          ? (a && `${a.n_cells} cell${a.n_cells === 1 ? '' : 's'} at ${fmtLat(a.centre[0], 2)}, ${fmtLon(a.centre[1], 2)}`)
          : (regCatData?.summary?.n_grid_pts != null
              && `${regCatData.summary.n_grid_pts} cells over the drawn region`);
        if (!shown) return null;
        return (
          <div style={{ marginBottom: '12px' }}>
            <span style={{
              fontSize: t.fontSize.xs, color: 'rgba(255,255,255,0.45)',
              background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.12)',
              borderRadius: '10px', padding: '3px 10px',
            }}>
              scored: {shown}
            </span>
          </div>
        );
      })()}

      {(catMode === 'point' ? catError : regCatError) && (
        <div style={{ background: 'rgba(231,76,60,0.12)', border: '1px solid rgba(231,76,60,0.3)', borderRadius: t.radius, padding: '10px 14px', marginBottom: '14px', color: '#e74c3c', fontSize: t.fontSize.sm }}>
          ⚠️ {catMode === 'point' ? catError : regCatError}
        </div>
      )}

      {/* Obs coverage warning banner */}
      {(catMode === 'point' ? catData : regCatData)?.obs_warning && (
        <div style={{ background: 'rgba(243,156,18,0.10)', border: '1px solid rgba(243,156,18,0.3)', borderRadius: t.radius, padding: '8px 14px', marginBottom: '16px', color: '#f39c12', fontSize: t.fontSize.sm, display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
          <span style={{ flexShrink: 0 }}>⚠️</span>
          <span>{(catMode === 'point' ? catData : regCatData).obs_warning}</span>
        </div>
      )}

      {/* Empty-hours result */}
      {(catMode === 'point' ? (catHasRun && !catLoading && catData && catData.hours?.length === 0)
                            : (regCatHasRun && !regCatLoading && regCatData && regCatData.hours?.length === 0)) && (
        <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.base, padding: '16px 0' }}>
          No overlapping observations found for this location and time window. Try a different point or extend the hour range.
        </div>
      )}

      {/* ── Stat badges ── */}
      {(() => {
        const activeData = catMode === 'point' ? catData : regCatData;
        if (!activeData || !activeData.summary || !activeData.hours?.length) return null;
        const s   = activeData.summary;
        const cc  = s.composite_confidence;
        // Non-null in both modes now. It was region-only in practice,
        // because point mode defaulted the FSS field to a single cell.
        const fss = s.fss;

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
          { key: 'bs',  label: 'Brier', hint: 'Brier Score (0=perfect)',             val: s.brier },
        ];
        // Always a badge, even when undefined. It used to be pushed
        // only when non-null, so an unavailable FSS did not render at
        // all — five badges and no gap to ask about. Every other
        // metric here shows N/A rather than vanishing.
        {
          const w = (catMode === 'region' ? regCatData?.fss_window
                                         : catData?.scored_area?.fss_window) ?? fssWindow;
          const box = catData?.scored_area?.box_cells ?? catBoxCells;
          badges.push({
            key: 'fss', label: 'FSS', val: fss,
            hint: fss != null
              ? `Fractions Skill Score over a ${w}×${w}-cell neighbourhood (0→1, higher=better)`
              : catMode === 'point' && box <= 1
                ? 'Undefined at one cell — raise the scored area above'
                : 'Undefined here: no cell in the field crosses the threshold, in the forecast or the observation',
          });
        }

        const contingencyTotal = s.hits + s.misses + s.false_alarms + s.correct_neg;

        return (
          <>
            {/* Badges */}
            <div style={{ display: 'flex', gap: '10px', marginBottom: '20px', flexWrap: 'wrap' }}>
              {badges.map(({ key, label, hint, val }) => (
                <div key={key} style={{ background: 'rgba(255,255,255,0.06)', borderRadius: '10px', padding: '12px 16px', minWidth: '100px', borderLeft: `3px solid ${metricColor(key, val)}` }}>
                  <div style={{ color: metricColor(key, val), fontSize: t.fontSize.stat, fontWeight: t.fontWeight.bold, lineHeight: 1 }}>
                    {Number.isFinite(val) ? val.toFixed(3) : 'N/A'}
                  </div>
                  <div style={{ color: 'rgba(255,255,255,0.7)', fontSize: t.fontSize.sm, marginTop: '4px', fontWeight: t.fontWeight.semibold }}>{label}</div>
                  <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.micro, marginTop: '2px' }}>{hint}</div>
                </div>
              ))}

              {/* Composite Confidence */}
              <div style={{
                background: Number.isFinite(cc) ? `rgba(${cc >= 0.6 ? '46,204,113' : cc >= 0.4 ? '243,156,18' : '231,76,60'},0.10)` : 'rgba(255,255,255,0.06)',
                borderRadius: '10px', padding: '12px 16px', minWidth: '130px',
                borderLeft: `3px solid ${metricColor('cc', cc)}`,
                borderTop: `1px solid ${metricColor('cc', cc)}33`,
              }}>
                <div style={{ color: metricColor('cc', cc), fontSize: t.fontSize.statLg, fontWeight: t.fontWeight.heavy, lineHeight: 1 }}>
                  {Number.isFinite(cc) ? cc.toFixed(3) : 'N/A'}
                </div>
                <div style={{ color: 'rgba(255,255,255,0.8)', fontSize: t.fontSize.sm, marginTop: '4px', fontWeight: t.fontWeight.bold }}>Composite Confidence</div>
                <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.micro, marginTop: '2px' }}>
                  {fss != null
                    ? '0.40×CSI + 0.30×FSS + 0.20×POD + 0.10×(1–FAR)'
                    : '0.40×CSI + 0.20×POD + 0.10×(1–FAR) ÷ 0.70'}
                </div>
                {/* Which of the two formulas produced the number
                    above. The composite silently changes definition
                    when FSS drops out — same label, same colour
                    bands, 30% of the blend gone — so it has to say
                    so. textFaint, not 0.2: theme.js raised the faint
                    tier to 0.5 precisely because anything below it
                    fails WCAG AA at this size. */}
                {fss == null && (
                  <div style={{ color: t.textFaint, fontSize: t.fontSize.micro, marginTop: '1px' }}>
                    Re-weighted without FSS — not comparable with a value that includes it
                  </div>
                )}
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
                <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '5px', background: 'rgba(255,255,255,0.04)', borderRadius: t.radiusSm, padding: '5px 10px', border: `1px solid ${color}33` }}>
                  <span style={{ color, fontWeight: t.fontWeight.bold, fontSize: t.fontSize.base }}>{val}</span>
                  <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.xs }}>{label}</span>
                </div>
              ))}
              <div style={{ display: 'flex', alignItems: 'center', gap: '5px', background: 'rgba(255,255,255,0.04)', borderRadius: t.radiusSm, padding: '5px 10px', border: '1px solid rgba(255,255,255,0.1)' }}>
                <span style={{ color: 'rgba(255,255,255,0.6)', fontWeight: t.fontWeight.bold, fontSize: t.fontSize.base }}>{contingencyTotal}</span>
                <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: t.fontSize.xs }}>
                  Total {catMode === 'region' ? `(${(s.n_grid_pts ?? '?')} pts × hours)` : 'cases'}
                </span>
              </div>
            </div>

            {/* Chart — different per mode */}
            {catMode === 'point' && (
              <>
              <div ref={catChartRef}>
                <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: t.fontSize.sm, marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
                  <span>Event Probability per Lead Time (threshold &gt; {activeData.threshold_info?.threshold_ms ?? activeData.threshold_info?.threshold_mm_6h ?? thresholdNum} {activeData.threshold_info?.unit ?? (selectedVariable === 'wind' ? 'm/s' : 'mm/6h')})</span>
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
                      contentStyle={{ background: '#1a2535', border: '1px solid rgba(255,255,255,0.15)', borderRadius: t.radius, color: 'white', fontSize: t.fontSize.sm }}
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

              {/* Cumulative CSI / POD / FAR by lead time */}
              {(() => {
                let hits = 0, misses = 0, fas = 0;
                const cumData = activeData.hours.map(r => {
                  if (r.is_fcst && r.is_obs)       hits++;
                  else if (r.is_fcst && !r.is_obs) fas++;
                  else if (!r.is_fcst && r.is_obs) misses++;
                  const denom = hits + misses + fas;
                  const fcstYes = hits + fas;
                  return {
                    hour: r.hour,
                    csi: denom > 0 ? +(hits / denom).toFixed(3) : null,
                    pod: (hits + misses) > 0 ? +(hits / (hits + misses)).toFixed(3) : null,
                    far: fcstYes > 0 ? +(fas / fcstYes).toFixed(3) : null,
                  };
                });
                return (
                  <div style={{ marginTop: '18px' }}>
                    <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: t.fontSize.sm, marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
                      <span>Cumulative Skill Scores by Lead Time</span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ display: 'inline-block', width: '14px', height: '3px', background: '#3498db' }} />CSI</span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ display: 'inline-block', width: '14px', height: '3px', background: '#2ecc71' }} />POD</span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ display: 'inline-block', width: '14px', background: '#e74c3c', borderTop: '2px dashed #e74c3c', height: '0' }} />FAR</span>
                    </div>
                    <ResponsiveContainer width="100%" height={200}>
                      <ComposedChart data={cumData} margin={{ top: 8, right: 20, left: 0, bottom: 20 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                        <XAxis dataKey="hour" stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }} tickFormatter={h => `+${h}h`} label={{ value: 'Forecast Hour', position: 'insideBottom', offset: -12, fill: 'rgba(255,255,255,0.4)', fontSize: 11 }} />
                        <YAxis domain={[0, 1]} stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }} label={{ value: 'Score', angle: -90, position: 'insideLeft', fill: 'rgba(255,255,255,0.4)', fontSize: 11 }} />
                        <Tooltip
                          contentStyle={{ background: '#1a2535', border: '1px solid rgba(255,255,255,0.15)', borderRadius: t.radius, color: 'white', fontSize: t.fontSize.sm }}
                          formatter={(v, n) => [Number.isFinite(v) ? v.toFixed(3) : 'N/A', n]}
                          labelFormatter={h => `Cumulative through +${h}h`}
                        />
                        <ReferenceLine y={0.5} stroke="rgba(255,255,255,0.10)" strokeDasharray="4 4" />
                        <Line type="monotone" dataKey="csi" name="CSI" stroke="#3498db" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
                        <Line type="monotone" dataKey="pod" name="POD" stroke="#2ecc71" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
                        <Line type="monotone" dataKey="far" name="FAR" stroke="#e74c3c" strokeWidth={1.5} strokeDasharray="5 3" dot={false} isAnimationActive={false} connectNulls />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                );
              })()}
              </>
            )}

            {catMode === 'region' && (
              <div>
                {/* Two sub-charts side by side */}
                <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
                  {/* Chart A: Forecast vs Observed fraction per hour */}
                  <div style={{ flex: '1 1 300px', minWidth: 0 }}>
                    <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: t.fontSize.sm, marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
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
                          contentStyle={{ background: '#1a2535', border: '1px solid rgba(255,255,255,0.15)', borderRadius: t.radius, color: 'white', fontSize: t.fontSize.sm }}
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
                    <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: t.fontSize.sm, marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
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
                          contentStyle={{ background: '#1a2535', border: '1px solid rgba(255,255,255,0.15)', borderRadius: t.radius, color: 'white', fontSize: t.fontSize.sm }}
                          formatter={(v, n) => [Number.isFinite(Number(v)) ? Number(v).toFixed(3) : 'N/A', n]}
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
        <div style={{ color: 'rgba(255,255,255,0.25)', fontSize: t.fontSize.base, padding: '28px 0', textAlign: 'center' }}>
          Set a threshold and click <strong style={{ color: 'rgba(52,152,219,0.6)' }}>▶ Run Metrics</strong> to generate verification scores
        </div>
      )}
    </div>
  );
}

export default VerificationPanel;
