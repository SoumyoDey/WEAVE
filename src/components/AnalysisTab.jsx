import React, { useState, useRef, useEffect } from 'react';
import {
  AreaChart, Area, BarChart, Bar, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, ComposedChart, Line,
} from 'recharts';
import { BarChart3, MapPin, Map as MapIcon } from 'lucide-react';
import { fetchCategoricalMetrics, fetchRegionCategoricalMetrics } from '../api/analysisApi';
import { fetchSpatialMetric, fetchSpatialMetricPlot } from '../api/spatialApi';
import { METRIC_CONFIG } from '../constants';
import { t } from '../theme';
import { LoadingState, EmptyState, NoDataNote } from './ui/PanelState';

// Format signed lat/lon with hemisphere suffixes (so -75.5 reads "75.5°W", not
// "-75.5°E"). Accepts numbers or numeric strings.
const fmtLat = (v, p = 3) => { const n = parseFloat(v); return `${Math.abs(n).toFixed(p)}°${n >= 0 ? 'N' : 'S'}`; };
const fmtLon = (v, p = 3) => { const n = parseFloat(v); return `${Math.abs(n).toFixed(p)}°${n >= 0 ? 'E' : 'W'}`; };

// ── Region metric definitions (defined outside component to avoid recreation) ──
const REGION_METRICS = [
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

// Downloads the first SVG found inside a container div as a PNG.
function downloadChartAsPng(containerRef, filename) {
  if (!containerRef.current) return;
  const svg = containerRef.current.querySelector('svg');
  if (!svg) return;
  const svgData = new XMLSerializer().serializeToString(svg);
  const canvas  = document.createElement('canvas');
  const bbox    = svg.getBoundingClientRect();
  canvas.width  = bbox.width  || 800;
  canvas.height = bbox.height || 400;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#0f1923';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  const img = new Image();
  img.onload = () => {
    ctx.drawImage(img, 0, 0);
    const a = document.createElement('a');
    a.href     = canvas.toDataURL('image/png');
    a.download = filename;
    a.click();
  };
  img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgData)));
}

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
  const [coneMode, setConeMode] = useState('gaussian');  // 'gaussian' | 'empirical'

  // ── Chart download refs ──────────────────────────────────────────────────────
  const coneChartRef  = useRef(null);
  const ssrChartRef   = useRef(null);
  const catChartRef   = useRef(null);

  // ── Verification Metrics state ──────────────────────────────────────────────
  // Default threshold: 25 mm/6h for precip, 10 m/s for wind
  const defaultThreshold = selectedVariable === 'wind' ? 10 : 25;
  const [catThreshold, setCatThreshold]   = useState(defaultThreshold);
  const [catHourMin,   setCatHourMin]     = useState(0);
  const [catHourMax,   setCatHourMax]     = useState(240);

  const [catLoading,   setCatLoading]     = useState(false);
  const [catData,      setCatData]        = useState(null);  // full API response
  const [catError,     setCatError]       = useState(null);
  const [catHasRun,    setCatHasRun]      = useState(false);

  // ── Region categorical state ────────────────────────────────────────────────
  const [catMode,        setCatMode]        = useState('point');  // 'point' | 'region'
  // FSS neighbourhood width in grid cells. FSS only means something relative to
  // a spatial scale — "skilful at 2.5 degrees" — so this is a parameter of the
  // score, not a display option. Odd values centre cleanly on a cell.
  // Defaults match the Comparison tab so the same score is asked the same
  // question in both places.
  const [fssWindow,      setFssWindow]      = useState(5);
  // The field FSS is evaluated over, in cells. It affects FSS and nothing else:
  // the contingency table reads the centre cell at every width (verified — hits,
  // misses and false alarms are identical at 1, 3, 5 and 9). It was 1, which made
  // FSS structurally undefined and therefore invisible in this tab.
  const [catBoxCells,    setCatBoxCells]    = useState(9);
  const [regCatLoading,  setRegCatLoading]  = useState(false);
  const [regCatData,     setRegCatData]     = useState(null);
  const [regCatError,    setRegCatError]    = useState(null);
  const [regCatHasRun,   setRegCatHasRun]   = useState(false);

  // Reset thresholds to variable-appropriate defaults and clear stale results on variable switch.
  useEffect(() => {
    const def = selectedVariable === 'wind' ? 10 : 25;
    setCatThreshold(def);
    setRegionThreshold(def);
    setCatData(null);
    setCatHasRun(false);
    setRegCatData(null);
    setRegCatHasRun(false);
    setSpatialMaps({});
  }, [selectedVariable]); // eslint-disable-line

  // ── Region mode state ────────────────────────────────────────────────────────
  const [analysisMode,       setAnalysisMode]       = useState('point');
  const [regionHourMin,      setRegionHourMin]      = useState(0);
  const [regionHourMax,      setRegionHourMax]      = useState(168);
  const [regionThreshold,    setRegionThreshold]    = useState(selectedVariable === 'wind' ? 10 : 25);
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
        thresholdMm6h: parseFloat(catThreshold) || 25,
        hourMin:       catHourMin,
        hourMax:       catHourMax,
        fssWindow,
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

    const computeOne = async (m) => {
      try {
        const pts = await fetchSpatialMetric({
          metric:    m.key,
          modelName: currentModel.name,
          variable:  selectedVariable,
          hour:      undefined,
          threshold: m.requiresThreshold ? regionThreshold : undefined,
          hourMin:   regionHourMin,
          hourMax:   regionHourMax,
          bounds,
        });
        const plot = await fetchSpatialMetricPlot({
          metric:         m.key,
          model:          currentModel.name,
          variable:       selectedVariable,
          hour:           undefined,
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

  // Mirrors the 5-tier SSR scale used by the backend's map legend
  // (flask_api.py PLOT_STYLE_REGISTRY['ssr']) so every SSR view agrees.
  const ssrBarColor = (ssr) => {
    if (ssr === null) return '#555';
    if (ssr < 0.5) return '#c00000';
    if (ssr < 0.8) return '#e74c3c';
    if (ssr <= 1.2) return '#27ae60';
    if (ssr <= 2.0) return '#e67e22';
    return '#3498db';
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
                {/* ── Section 1: Cone of Uncertainty ── */}
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

                {/* ── Section 2: Spread-Skill Analysis ── */}
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

                {/* ── Section 3: Verification Metrics ── */}
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
                        {[{ id: 'point', label: 'This cell' },
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
                      <span style={{ color: 'rgba(255,255,255,0.55)', fontSize: t.fontSize.sm, whiteSpace: 'nowrap' }} title="Separate from the Region spatial-maps threshold above">Threshold</span>
                      <input
                        type="number" min="0" step="1" value={catThreshold}
                        aria-label={`Threshold (${selectedVariable === 'wind' ? 'm/s' : 'mm/6h'})`}
                        onChange={e => setCatThreshold(e.target.value)}
                        style={{ width: '72px', padding: '4px 8px', fontSize: t.fontSize.base, fontWeight: t.fontWeight.semibold, background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: t.radiusSm, color: 'white', textAlign: 'right', outline: 'none' }}
                      />
                      <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: t.fontSize.sm }}>
                        {selectedVariable === 'wind' ? 'm/s' : 'mm/6h'}
                      </span>
                    </div>

                    {/* The field FSS is evaluated over — point mode only, since
                        region mode uses the drawn bbox instead.

                        Called "FSS area", NOT "Scored area", which is what it
                        said while it defaulted to 1. This control moves FSS and
                        nothing else: CSI, POD, FAR, FBI and Brier read the centre
                        cell at every width. At the old default of 1 the
                        distinction did not matter because the box WAS the cell;
                        at 9 a label saying "Scored area: 9 cells (≈4.5°)" would
                        claim the contingency table covered 4.5°, which is false.
                        Comparison's "Scored area" is a true scored area — it
                        pools every metric over the box — so the two tabs use
                        different words because they mean different things. */}
                    {catMode === 'point' && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span
                          style={{ color: 'rgba(255,255,255,0.55)', fontSize: t.fontSize.sm, whiteSpace: 'nowrap' }}
                          title="The field FSS compares over, centred on the clicked cell. FSS needs neighbours, so at 1 cell it is undefined. Every other metric here reads the clicked cell alone, whatever this is set to."
                        >
                          FSS area
                        </span>
                        <input
                          type="number" min="1" max="41" step="2" value={catBoxCells}
                          aria-label="FSS field width (grid cells)"
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
                          FSS window
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
                      <span style={{ color: 'rgba(255,255,255,0.55)', fontSize: t.fontSize.sm, whiteSpace: 'nowrap' }}>Hours</span>
                      <input type="number" min="0" step="6" value={catHourMin}
                        onChange={e => setCatHourMin(parseInt(e.target.value, 10) || 0)}
                        style={{ width: '60px', padding: '4px 6px', fontSize: t.fontSize.sm, background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: t.radiusSm, color: 'white', textAlign: 'center', outline: 'none' }} />
                      <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.sm }}>–</span>
                      <input type="number" min="0" step="24" value={catHourMax}
                        onChange={e => { const n = parseInt(e.target.value, 10); setCatHourMax(Number.isNaN(n) ? 240 : n); }}
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
                      const thr = ti.threshold_ms ?? ti.threshold_mm_6h ?? catThreshold;
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
                      const thr = ti.threshold_ms ?? ti.threshold_mm_6h ?? catThreshold;
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
                            ? 'Undefined at one cell — raise the FSS area above'
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
                              <span>Event Probability per Lead Time (threshold &gt; {activeData.threshold_info?.threshold_ms ?? activeData.threshold_info?.threshold_mm_6h ?? catThreshold} {activeData.threshold_info?.unit ?? (selectedVariable === 'wind' ? 'm/s' : 'mm/6h')})</span>
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
                    <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: t.fontSize.xs, whiteSpace: 'nowrap' }}>Hours</span>
                    <input type="number" min="0" step="6" value={regionHourMin}
                      onChange={e => setRegionHourMin(parseInt(e.target.value, 10) || 0)}
                      style={{ width: '52px', padding: '4px 6px', fontSize: t.fontSize.sm, background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: t.radiusSm, color: 'white', textAlign: 'center', outline: 'none' }} />
                    <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.xs }}>–</span>
                    <input type="number" min="0" step="24" value={regionHourMax}
                      onChange={e => { const n = parseInt(e.target.value, 10); setRegionHourMax(Number.isNaN(n) ? 168 : n); }}
                      style={{ width: '52px', padding: '4px 6px', fontSize: t.fontSize.sm, background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: t.radiusSm, color: 'white', textAlign: 'center', outline: 'none' }} />
                    <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.xs }}>h</span>
                  </div>

                  {/* Threshold */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: t.fontSize.xs, whiteSpace: 'nowrap' }} title="For spatial metric maps only. Verification Metrics below uses its own threshold setting.">Threshold (maps)</span>
                    <input type="number" min="0" step="1" value={regionThreshold}
                      onChange={e => setRegionThreshold(parseFloat(e.target.value) || (selectedVariable === 'wind' ? 10 : 25))}
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
                  { id: 'categorical', label: `Categorical  (threshold > ${regionThreshold} ${selectedVariable === 'wind' ? 'm/s' : 'mm/6h'})`, hint: 'Event-based skill for threshold exceedances', keys: ['csi', 'pod', 'far', 'brier'] },
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
