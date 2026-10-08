import React, { useState, useEffect } from 'react';
import { BarChart3, MapPin, Map as MapIcon } from 'lucide-react';
import { fetchSpatialMetric, fetchSpatialMetricPlot } from '../api/spatialApi';
import { METRIC_CONFIG, VERIFICATION_DEFAULTS as VD } from '../constants';
import { t } from '../theme';
import { useVerification } from '../state/VerificationContext';
import { fmtLat, fmtLon } from '../utils/geoUtils';
import { EmptyState } from './ui/PanelState';
import { REGION_METRICS } from './analysis/metrics';
import { ConeOfUncertaintyPanel } from './analysis/ConeOfUncertaintyPanel';
import { SpreadSkillPanel } from './analysis/SpreadSkillPanel';
import { VerificationPanel } from './analysis/VerificationPanel';

// Format signed lat/lon with hemisphere suffixes (so -75.5 reads "75.5°W", not
// "-75.5°E"). Accepts numbers or numeric strings.



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
 *   obsCoverage          {object|null}  — /api/observation-coverage
 *   onCompare            {fn}
 *   selectedRegion       {object|null}
 */
export function AnalysisTab({
  clickedPoint,
  currentModel,
  selectedVariable,
  timeseriesLoading, timeseriesData,
  ssrLoading, ssrData,
  obsCoverage,
  onCompare,
  selectedRegion,
  active = true,
}) {
  // ── Cone of Uncertainty mode ────────────────────────────────────────────────

  // ── Chart download refs ──────────────────────────────────────────────────────

  // ── Verification Metrics state ──────────────────────────────────────────────
  // **The settings come from the app, not from this tab** (`NEXT_STEPS.md`
  // §62). §55 merged this tab's duplicate threshold and lead range into one
  // copy each; this takes the last step and shares that copy with the
  // Comparison tab, which held its own. Two tabs answering one question with
  // different thresholds is the defect, and it survived every earlier fix
  // because each fix made one tab internally consistent.
  //
  // `threshold` is a string so a field can be empty mid-typing; readers take
  // `thresholdNum`.
  const {
    threshold, thresholdNum, setThreshold,
    hourMin, setHourMin, hourMax, setHourMax,
    resetThresholdFor,
  } = useVerification();


  // Reset the threshold to the variable-appropriate default and clear stale
  // results on variable switch.
  // The threshold is re-seeded here because the tab owns the variable; the
  // verification panel drops its own stale results (§63).
  useEffect(() => {
    resetThresholdFor(selectedVariable);
    setSpatialMaps({});
  }, [selectedVariable]); // eslint-disable-line

  // ── Region mode state ────────────────────────────────────────────────────────
  const [analysisMode,       setAnalysisMode]       = useState('point');
  const [spatialMaps,        setSpatialMaps]        = useState({});
  const [regionRunning,      setRegionRunning]      = useState(false);
  // per-card share feedback: { [key]: 'idle' | 'copied' }
  const [shareStates,        setShareStates]        = useState({});

  // ── Per-card share ───────────────────────────────────────────────────────────
  const shareMap = async (key, url) => {
    if (!url) return;
    const filename = `WEAVE-${currentModel?.name ?? 'model'}-${key}.png`;
    // 1. Try native Web Share (mobile / Electron)
    try {
      const blob = await (await fetch(url)).blob();
      const file = new File([blob], filename, { type: 'image/png' });
      if (navigator.share && navigator.canShare?.({ files: [file] })) {
        await navigator.share({ title: `WEAVE — ${key.toUpperCase()} map`, files: [file] });
        return;
      }
    } catch {}
    // 2. Copy image to clipboard (desktop Chrome / Edge)
    try {
      const blob = await (await fetch(url)).blob();
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
      setShareStates(prev => ({ ...prev, [key]: 'copied' }));
      setTimeout(() => setShareStates(prev => ({ ...prev, [key]: 'idle' })), 2500);
      return;
    } catch {}
    // 3. Fallback — download
    const a = document.createElement('a');
    a.href = url; a.download = filename; a.click();
  };


  const handleComputeAllMaps = async () => {
    if (!selectedRegion?.bounds || !currentModel) return;
    setRegionRunning(true);
    // Mark all as loading
    const init = {};
    REGION_METRICS.forEach(m => { init[m.key] = { loading: true, url: null, error: null }; });
    setSpatialMaps(init);

    const bounds = selectedRegion.bounds;

    const computeOne = async (m) => {
      try {
        const pts = await fetchSpatialMetric({
          metric:    m.key,
          modelName: currentModel.name,
          variable:  selectedVariable,
          hour:      undefined,
          threshold: m.requiresThreshold ? thresholdNum : undefined,
          hourMin,
          hourMax,
          bounds,
        });
        // Nothing to draw is not an error, and asking the renderer to draw it
        // produced one: the plot endpoint rejects an empty list with 400 "No
        // points provided", which was surfaced verbatim. A metric with no
        // exceedances over the region — routine for CSI/POD/FAR at a high
        // threshold — read as a failure in the app's own words rather than the
        // user's. Fall through to the card's "No data for this region" state.
        if (!pts.points?.length) {
          setSpatialMaps(prev => ({
            ...prev,
            [m.key]: { loading: false, url: null, error: null },
          }));
          return;
        }
        const plot = await fetchSpatialMetricPlot({
          metric:         m.key,
          model:          currentModel.name,
          variable:       selectedVariable,
          hour:           undefined,
          threshold_mm_6h: m.requiresThreshold ? thresholdNum : undefined,
          points:         pts.points,
          n_hours:        pts.n_hours,
        });
        setSpatialMaps(prev => ({
          ...prev,
          [m.key]: {
            loading: false,
            url:   plot.image ? 'data:image/png;base64,' + plot.image : null,
            error: plot.error || null,
          },
        }));
      } catch (err) {
        setSpatialMaps(prev => ({
          ...prev,
          [m.key]: { loading: false, url: null, error: err.message },
        }));
      }
    };

    // Throttle to a small concurrency pool: firing all ~10 metrics at once
    // sent a burst of simultaneous requests that could exhaust the DB pool.
    // A 4-worker pool keeps peak concurrency bounded while still overlapping work.
    const CONCURRENCY = 4;
    let next = 0;
    const worker = async () => {
      while (next < REGION_METRICS.length) {
        await computeOne(REGION_METRICS[next++]);
      }
    };
    await Promise.all(
      Array.from({ length: Math.min(CONCURRENCY, REGION_METRICS.length) }, worker)
    );

    setRegionRunning(false);
  };


  // 'mm/h', not 'mm/hr' — the same spelling the API returns in `units`, so a
  // label and the response it describes cannot look like two different things.
  const yAxisUnit = selectedVariable === 'wind' ? 'm/s' : 'mm/h';

  const verifiedAgainst = selectedVariable === 'precipitation'
    ? 'Verified against GPM IMERG V07B observations'
    : 'Verified against ERA5 reanalysis (10-m wind)';

  // Defer chart mount one frame after the tab becomes active so Recharts measures
  // a laid-out container (no width(0)/(-1) warnings). Skipping render while hidden
  // also avoids measuring a display:none container. Hooks run unconditionally above
  // the early return, so state is preserved across tab switches.
  const [chartsReady, setChartsReady] = useState(false);
  useEffect(() => {
    if (!active) { setChartsReady(false); return; }
    const id = requestAnimationFrame(() => setChartsReady(true));
    return () => cancelAnimationFrame(id);
  }, [active]);

  if (!active || !chartsReady) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden', flex: 1 }}>
      {/* ── Header with mode toggle ── */}
      <div style={{ padding: '12px 30px 10px', borderBottom: '1px solid rgba(255,255,255,0.08)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
        <div>
          <h2 style={{ color: 'white', margin: '0 0 3px 0', fontSize: t.fontSize.xl, fontWeight: t.fontWeight.semibold, display: 'flex', alignItems: 'center', gap: '8px' }}><BarChart3 size={18} />Forecast Analysis</h2>
          <p style={{ color: 'rgba(255,255,255,0.4)', margin: 0, fontSize: t.fontSize.sm }}>
            {analysisMode === 'point'
              ? (clickedPoint ? `Point: ${fmtLat(clickedPoint.lat)}, ${fmtLon(clickedPoint.lon)} — ${currentModel?.name} — ${selectedVariable}` : 'Click anywhere on the map to analyse a location')
              : (selectedRegion?.bounds ? `Region: ${fmtLat(selectedRegion.bounds.min_lat, 1)}–${fmtLat(selectedRegion.bounds.max_lat, 1)} · ${fmtLon(selectedRegion.bounds.min_lon, 1)}–${fmtLon(selectedRegion.bounds.max_lon, 1)} — ${currentModel?.name}` : 'Draw a region on the map to compute spatial metrics')}
          </p>
        </div>
        {/* Point / Region toggle */}
        <div style={{ display: 'flex', borderRadius: t.radius, overflow: 'hidden', border: '1px solid rgba(255,255,255,0.15)', flexShrink: 0 }}>
          {[{ id: 'point', icon: MapPin, label: 'Point' }, { id: 'region', icon: MapIcon, label: 'Region' }].map(({ id, icon: Icon, label }) => (
            <button key={id} onClick={() => setAnalysisMode(id)}
              style={{ padding: '6px 18px', fontSize: t.fontSize.sm, fontWeight: t.fontWeight.semibold, cursor: 'pointer', border: 'none', outline: 'none',
                display: 'inline-flex', alignItems: 'center', gap: '6px',
                background: analysisMode === id ? 'rgba(52,152,219,0.25)' : 'rgba(255,255,255,0.04)',
                color:      analysisMode === id ? 'rgba(52,152,219,0.95)' : 'rgba(255,255,255,0.45)' }}>
              <Icon size={14} /> {label}
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
              <EmptyState
                icon={<MapPin size={48} />}
                title="Click a point on the map"
                detail="Switch to Visualization tab, click anywhere, then come back here"
              />
            )}

            {clickedPoint && (
              <>
                <ConeOfUncertaintyPanel
                  timeseriesData={timeseriesData}
                  timeseriesLoading={timeseriesLoading}
                  currentModel={currentModel}
                  selectedVariable={selectedVariable}
                />


                <SpreadSkillPanel
                  ssrData={ssrData}
                  ssrLoading={ssrLoading}
                  currentModel={currentModel}
                  obsCoverage={obsCoverage}
                  verifiedAgainst={verifiedAgainst}
                  yAxisUnit={yAxisUnit}
                />


                <VerificationPanel
                  clickedPoint={clickedPoint}
                  selectedRegion={selectedRegion}
                  currentModel={currentModel}
                  selectedVariable={selectedVariable}
                />


                {/* ── Compare shortcut ── */}
                <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', padding: '14px 0 4px', display: 'flex', justifyContent: 'flex-end' }}>
                  <button
                    onClick={onCompare}
                    style={{ background: 'rgba(52,152,219,0.12)', border: '1px solid rgba(52,152,219,0.3)', color: 'rgba(52,152,219,0.9)', fontSize: t.fontSize.sm, fontWeight: t.fontWeight.semibold, padding: '6px 14px', borderRadius: t.radius, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
                  >
                    Compare models at this point →
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
              <EmptyState
                icon={<MapIcon size={48} />}
                title="Draw a region on the map"
                detail="Use the rectangle or polygon selection tool in the Visualization tab"
              />
            )}

            {selectedRegion?.bounds && (
              <>
                {/* Controls row */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px', flexWrap: 'wrap', background: 'rgba(255,255,255,0.04)', borderRadius: '10px', padding: '12px 16px', border: '1px solid rgba(255,255,255,0.08)' }}>
                  {/* Hour range */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: t.fontSize.xs, whiteSpace: 'nowrap' }}>Lead times</span>
                    <input type="number" min="0" step="6" value={hourMin}
                      onChange={e => setHourMin(parseInt(e.target.value, 10) || VD.HOUR_MIN)}
                      style={{ width: '52px', padding: '4px 6px', fontSize: t.fontSize.sm, background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: t.radiusSm, color: 'white', textAlign: 'center', outline: 'none' }} />
                    <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.xs }}>–</span>
                    <input type="number" min="0" step="24" value={hourMax}
                      onChange={e => { const n = parseInt(e.target.value, 10); setHourMax(Number.isNaN(n) ? VD.HOUR_MAX : n); }}
                      style={{ width: '52px', padding: '4px 6px', fontSize: t.fontSize.sm, background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: t.radiusSm, color: 'white', textAlign: 'center', outline: 'none' }} />
                    <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.xs }}>h</span>
                  </div>

                  {/* Threshold */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: t.fontSize.xs, whiteSpace: 'nowrap' }} title="Event threshold, in native units. One threshold for the whole app: the Verification Metrics panel and the Comparison tab score at this same value.">Threshold</span>
                    <input type="number" min="0" step="1" value={threshold}
                      onChange={e => setThreshold(e.target.value)}
                      style={{ width: '60px', padding: '4px 6px', fontSize: t.fontSize.sm, fontWeight: t.fontWeight.semibold, background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: t.radiusSm, color: 'white', textAlign: 'right', outline: 'none' }} />
                    <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.xs }}>
                      {selectedVariable === 'wind' ? 'm/s' : 'mm/6h'}
                    </span>
                  </div>

                  {/* Compute button */}
                  <button onClick={handleComputeAllMaps} disabled={regionRunning}
                    style={{ padding: '7px 20px', fontSize: t.fontSize.sm, fontWeight: t.fontWeight.bold,
                      cursor: regionRunning ? 'not-allowed' : 'pointer',
                      background: regionRunning ? 'rgba(52,152,219,0.08)' : 'rgba(52,152,219,0.2)',
                      border: '1px solid rgba(52,152,219,0.5)', borderRadius: t.radius,
                      color: regionRunning ? 'rgba(52,152,219,0.4)' : 'rgba(52,152,219,0.95)',
                      display: 'flex', alignItems: 'center', gap: '6px' }}>
                    {regionRunning ? '⏳ Computing…' : '▶ Compute All Maps'}
                  </button>
                </div>

                {/* Metric map groups */}
                {[
                  { id: 'calibration', label: 'Calibration', hint: 'Is the ensemble spread reliable?', keys: ['ssr_agg', 'correlation'] },
                  { id: 'accuracy',    label: 'Accuracy vs Observations', hint: 'How close is the ensemble mean to obs?', keys: ['bias', 'mae', 'rmse', 'crps'] },
                  { id: 'categorical', label: `Categorical  (threshold > ${thresholdNum} ${selectedVariable === 'wind' ? 'm/s' : 'mm/6h'})`, hint: 'Event-based skill for threshold exceedances', keys: ['csi', 'pod', 'far', 'brier'] },
                ].map(group => (
                  <div key={group.id} style={{ marginBottom: '32px' }}>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px', marginBottom: '14px' }}>
                      <h3 style={{ color: 'rgba(255,255,255,0.85)', fontSize: t.fontSize.base, fontWeight: t.fontWeight.bold, margin: 0, letterSpacing: '0.02em' }}>{group.label}</h3>
                      <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.xs }}>{group.hint}</span>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(420px, 100%), 1fr))', gap: '16px' }}>
                      {group.keys.map(key => {
                        const st = spatialMaps[key];
                        const cfg = METRIC_CONFIG.find(m => m.key === key);
                        return (
                          <div key={key} style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.08)', overflow: 'hidden' }}>
                            {/* Card header */}
                            <div style={{ padding: '8px 12px', borderBottom: '1px solid rgba(255,255,255,0.06)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                              <span style={{ fontSize: t.fontSize.sm, fontWeight: t.fontWeight.semibold, color: 'rgba(255,255,255,0.75)' }}>{cfg?.label ?? key.toUpperCase()}</span>
                              {st?.url && (
                                <div style={{ display: 'flex', gap: '4px' }}>
                                  <button
                                    onClick={() => { const a = document.createElement('a'); a.href = st.url; a.download = `WEAVE-${currentModel?.name}-${key}.png`; a.click(); }}
                                    style={{ fontSize: t.fontSize.base, color: 'rgba(255,255,255,0.45)', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '5px', cursor: 'pointer', padding: '2px 7px', lineHeight: 1 }}
                                    title="Download as PNG"
                                  >⬇</button>
                                  <button
                                    onClick={() => shareMap(key, st.url)}
                                    style={{
                                      fontSize: t.fontSize.base, borderRadius: '5px', cursor: 'pointer', padding: '2px 7px', border: '1px solid rgba(255,255,255,0.12)', lineHeight: 1,
                                      ...(shareStates[key] === 'copied'
                                        ? { background: 'rgba(46,204,113,0.15)', borderColor: 'rgba(46,204,113,0.4)', color: '#2ecc71' }
                                        : { background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.45)' }),
                                    }}
                                    title="Copy to clipboard / Share"
                                  >{shareStates[key] === 'copied' ? '✓' : '📤'}</button>
                                </div>
                              )}
                            </div>
                            {/* Card body */}
                            <div style={{ minHeight: '200px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                              {!st && (
                                <span style={{ color: 'rgba(255,255,255,0.2)', fontSize: t.fontSize.sm }}>Click ▶ Compute All Maps</span>
                              )}
                              {st?.loading && (
                                <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.4)', fontSize: t.fontSize.sm }}>
                                  <div style={{ fontSize: t.fontSize.statLg, marginBottom: '8px' }}>⏳</div>Computing…
                                </div>
                              )}
                              {st && !st.loading && st.error && (
                                <div style={{ color: '#e74c3c', fontSize: t.fontSize.xs, padding: '16px', textAlign: 'center' }}>⚠️ {st.error}</div>
                              )}
                              {st && !st.loading && !st.error && st.url && (
                                <img src={st.url} alt={key} style={{ width: '100%', display: 'block' }} />
                              )}
                              {st && !st.loading && !st.error && !st.url && (
                                <span style={{ color: 'rgba(255,255,255,0.25)', fontSize: t.fontSize.sm }}>No data for this region</span>
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

            {/* Compare shortcut — region mode */}
            {selectedRegion?.bounds && (
              <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', padding: '14px 0 4px', display: 'flex', justifyContent: 'flex-end' }}>
                <button
                  onClick={onCompare}
                  style={{ background: 'rgba(52,152,219,0.12)', border: '1px solid rgba(52,152,219,0.3)', color: 'rgba(52,152,219,0.9)', fontSize: t.fontSize.sm, fontWeight: t.fontWeight.semibold, padding: '6px 14px', borderRadius: t.radius, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  Compare models for this region →
                </button>
              </div>
            )}
          </>
        )}

      </div>
    </div>
  );
}
