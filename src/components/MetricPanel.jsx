import React from 'react';
import { METRIC_CONFIG } from '../constants';

/**
 * Draggable/minimizable floating panel for spatial metric computation.
 *
 * Props:
 *   selectedRegion    {object|null}
 *   panelPos          {{ x, y }}
 *   setPanelPos       {fn}
 *   panelMinimized    {boolean}
 *   setPanelMinimized {fn}
 *   metricType        {string}
 *   setMetricType     {fn}
 *   metricHour        {number}
 *   setMetricHour     {fn}
 *   spatialLoading    {boolean}
 *   spatialData       {object|null}
 *   computeSpatialMetric {fn}
 *   clearSelection    {fn}
 *   isDraggingPanelRef {React.MutableRefObject}
 *   dragStartRef       {React.MutableRefObject}
 */
export function MetricPanel({
  selectedRegion,
  panelPos, setPanelPos,
  panelMinimized, setPanelMinimized,
  metricType, setMetricType,
  metricHour, setMetricHour,
  spatialLoading, spatialData,
  computeSpatialMetric, clearSelection,
  isDraggingPanelRef, dragStartRef,
}) {
  if (!selectedRegion) return null;

  const metricCfg = METRIC_CONFIG.find(m => m.key === metricType);

  return (
    <div style={{
      position: 'fixed', left: panelPos.x, top: panelPos.y,
      width: panelMinimized ? '260px' : '380px',
      background: 'rgba(17,27,39,0.97)', color: 'white',
      borderRadius: '10px', boxShadow: '0 8px 32px rgba(0,0,0,0.55)',
      zIndex: 2000, border: '1px solid rgba(255,255,255,0.12)',
      userSelect: 'none',
    }}>
      {/* Drag handle / title bar */}
      <div
        onMouseDown={(e) => {
          isDraggingPanelRef.current = true;
          dragStartRef.current = { mouseX: e.clientX, mouseY: e.clientY, panelX: panelPos.x, panelY: panelPos.y };
          e.preventDefault();
        }}
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '9px 12px', cursor: 'grab', borderBottom: panelMinimized ? 'none' : '1px solid rgba(255,255,255,0.08)', borderRadius: panelMinimized ? '10px' : '10px 10px 0 0', background: 'rgba(52,152,219,0.15)' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
          <span style={{ fontSize: '13px' }}>{selectedRegion.type === 'rectangle' ? '⬜' : '🔷'}</span>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: '12px', fontWeight: '700', color: 'rgba(255,255,255,0.9)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {selectedRegion.type === 'rectangle' ? 'Rectangle Region' : 'Polygon Region'}
            </div>
            <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', whiteSpace: 'nowrap' }}>
              {selectedRegion.bounds.min_lat.toFixed(1)}°–{selectedRegion.bounds.max_lat.toFixed(1)}°N &nbsp;
              {selectedRegion.bounds.min_lon.toFixed(1)}°–{selectedRegion.bounds.max_lon.toFixed(1)}°E
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '4px', flexShrink: 0, marginLeft: '8px' }}>
          <button
            onMouseDown={e => e.stopPropagation()}
            onClick={() => setPanelMinimized(v => !v)}
            title={panelMinimized ? 'Expand' : 'Minimize'}
            style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.15)', color: 'rgba(255,255,255,0.7)', cursor: 'pointer', borderRadius: '4px', width: '22px', height: '22px', fontSize: '12px', lineHeight: '20px', textAlign: 'center', padding: 0 }}>
            {panelMinimized ? '＋' : '－'}
          </button>
          <button
            onMouseDown={e => e.stopPropagation()}
            onClick={clearSelection}
            title="Close"
            style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.15)', color: 'rgba(255,255,255,0.7)', cursor: 'pointer', borderRadius: '4px', width: '22px', height: '22px', fontSize: '14px', lineHeight: '20px', textAlign: 'center', padding: 0 }}>
            ✕
          </button>
        </div>
      </div>

      {/* Panel body */}
      {!panelMinimized && (
        <div style={{ padding: '14px 14px 12px' }}>
          {/* Metric selector */}
          <div style={{ marginBottom: '11px' }}>
            <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.45)', marginBottom: '5px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Metric</div>
            <select
              value={metricType}
              onChange={e => setMetricType(e.target.value)}
              style={{ width: '100%', padding: '6px 8px', fontSize: '12px', fontWeight: '600', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.18)', borderRadius: '6px', color: 'rgba(255,255,255,0.85)', cursor: 'pointer', outline: 'none' }}>
              {METRIC_CONFIG.map(m => (
                <option key={m.key} value={m.key} style={{ background: '#1a2535', color: 'white' }}>{m.label}</option>
              ))}
            </select>
            {metricCfg && (
              <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.3)', marginTop: '4px', lineHeight: '1.4' }}>
                {metricCfg.description}
              </div>
            )}
          </div>

          {/* Hour selector (SSR only) */}
          {metricCfg?.requiresHour && (
            <div style={{ marginBottom: '11px' }}>
              <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.45)', marginBottom: '5px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Forecast Hour</div>
              <div style={{ display: 'flex', gap: '5px' }}>
                {[0, 6, 12, 18].map(h => (
                  <button key={h} onClick={() => setMetricHour(h)}
                    style={{ flex: 1, padding: '5px 0', fontSize: '11px', fontWeight: '600',
                      border: metricHour === h ? '2px solid #e67e22' : '2px solid rgba(255,255,255,0.12)',
                      borderRadius: '6px',
                      background: metricHour === h ? 'rgba(230,126,34,0.2)' : 'rgba(255,255,255,0.04)',
                      color: metricHour === h ? '#f0a04e' : 'rgba(255,255,255,0.55)',
                      cursor: 'pointer', transition: 'all 0.15s',
                    }}>
                    +{h}h
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Compute */}
          <button onClick={computeSpatialMetric} disabled={spatialLoading}
            style={{ width: '100%', padding: '9px', fontSize: '12px', fontWeight: '700', background: spatialLoading ? 'rgba(52,152,219,0.25)' : 'rgba(52,152,219,0.82)', border: 'none', borderRadius: '7px', color: 'white', cursor: spatialLoading ? 'default' : 'pointer', marginBottom: '11px', transition: 'all 0.2s' }}>
            {spatialLoading ? '⏳ Computing…' : '▶ Compute Spatial Map'}
          </button>

          {/* Results legend */}
          {spatialData && !spatialLoading && (
            <div style={{ borderTop: '1px solid rgba(255,255,255,0.07)', paddingTop: '10px' }}>
              <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.45)', marginBottom: '8px' }}>
                {spatialData.points.length} grid points mapped
                {spatialData.metric === 'correlation' && spatialData.n_hours != null && ` · ${spatialData.n_hours} lead times`}
              </div>
              {(() => {
                const cfg = METRIC_CONFIG.find(m => m.key === spatialData.metric);
                if (!cfg) return null;
                if (cfg.legend) {
                  return (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      {cfg.legend.map(({ color, label }) => (
                        <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '10px', color: 'rgba(255,255,255,0.65)' }}>
                          <div style={{ width: '12px', height: '12px', background: color, borderRadius: '2px', flexShrink: 0 }} />
                          {label}
                        </div>
                      ))}
                    </div>
                  );
                }
                if (cfg.legendGradient) {
                  const lg = cfg.legendGradient;
                  return (
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '3px' }}>
                        <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.45)' }}>{lg.minLabel}</span>
                        <div style={{ flex: 1, height: '12px', borderRadius: '3px', background: lg.css, border: '1px solid rgba(255,255,255,0.08)' }} />
                        <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.45)' }}>{lg.maxLabel}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9px', color: 'rgba(255,255,255,0.3)' }}>
                        {lg.midLabels.map(l => <span key={l}>{l}</span>)}
                      </div>
                    </div>
                  );
                }
                return null;
              })()}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
