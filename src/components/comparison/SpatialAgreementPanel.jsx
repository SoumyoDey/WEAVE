/**
 * The Spatial Agreement Map, owning its own state.
 *
 * Where models disagree, rendered as a Cartopy PNG: one lead time, the
 * selected models, the drawn region. It is a feature rather than a view —
 * it holds a lead time, a result, a loading flag and the share state, and
 * nothing else in the Comparison tab reads any of them.
 *
 * That is what made it the first *stateful* piece to leave `ComparisonTab.jsx`
 * (`NEXT_STEPS.md` §59). The charts that moved before it were presentational;
 * this one takes four pieces of state with it, which is the only kind of
 * extraction that actually makes the parent smaller rather than merely
 * shorter.
 *
 * `defaultHour` seeds the lead time from whatever the map was showing when the
 * user arrived, and keeps following it — the same behaviour the tab had.
 */
import React, { useState, useEffect } from 'react';

import { fetchSpatialAgreement } from '../../api/comparisonApi';
import { t } from '../../theme';
import { LoadingState as Spinner } from '../ui/PanelState';
import { INPUT, SECTION_TITLE } from './styles';


export function SpatialAgreementPanel({ models, variable, region, defaultHour }) {
  const [spatialHour, setSpatialHour] = useState(defaultHour || 6);
  const [spatialData, setSpatialData] = useState(null);
  const [spatialLoading, setSpatialLoading] = useState(false);
  const [spatialShareState, setSpatialShareState] = useState('idle'); // 'idle' | 'copied'

  // Follow the lead time the visualization map is on, as the tab did.
  useEffect(() => {
    if (defaultHour != null) setSpatialHour(defaultHour);
  }, [defaultHour]);

  const handleRunSpatial = async () => {
    if (!region || models.length < 2) return;
    setSpatialData(null);
    setSpatialLoading(true);
    const { min_lat, max_lat, min_lon, max_lon } = region.bounds;
    try {
      const result = await fetchSpatialAgreement({
        models: models,
        minLat: min_lat,
        maxLat: max_lat,
        minLon: min_lon,
        maxLon: max_lon,
        hour: spatialHour,
        variable: variable,
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
    a.download = `spatial_agreement_${variable}_+${spatialHour}h.png`;
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

  return (
      <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '20px', marginBottom: '16px' }}>
        <h3 style={SECTION_TITLE}>Spatial Agreement Map</h3>

        {/* Region available → controls + map */}
        {region && (
          <div>
            {/* Region info pill + controls row */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap', marginBottom: '16px' }}>
              {/* Region badge */}
              <span style={{
                fontSize: t.fontSize.xs, fontWeight: t.fontWeight.semibold, padding: '4px 12px', borderRadius: '20px',
                background: 'rgba(230,126,34,0.12)', border: '1px solid rgba(230,126,34,0.3)',
                color: '#e67e22',
              }}>
                {region.type === 'polygon' ? '⬡ Polygon' : '▭ Rectangle'}
                {' '}
                {region.bounds.min_lat.toFixed(1)}°–{region.bounds.max_lat.toFixed(1)}°N,{' '}
                {region.bounds.min_lon.toFixed(1)}°–{region.bounds.max_lon.toFixed(1)}°E
              </span>

              {/* Spatial hour input */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.sm }}>Hour</span>
                <input
                  type="number"
                  value={spatialHour}
                  min={0} max={360}
                  onChange={e => setSpatialHour(Math.max(0, Math.min(360, Number(e.target.value))))}
                  style={{ ...INPUT, width: '60px' }}
                />
                <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: t.fontSize.sm }}>h</span>
              </div>

              {/* Run button */}
              <button
                onClick={handleRunSpatial}
                disabled={spatialLoading || models.length < 2}
                style={{
                  background: (!spatialLoading && models.length >= 2) ? '#e67e22' : 'rgba(255,255,255,0.08)',
                  color: (!spatialLoading && models.length >= 2) ? 'white' : 'rgba(255,255,255,0.25)',
                  border: 'none',
                  borderRadius: t.radius,
                  padding: '7px 18px',
                  fontSize: t.fontSize.base,
                  fontWeight: t.fontWeight.bold,
                  cursor: (!spatialLoading && models.length >= 2) ? 'pointer' : 'not-allowed',
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
                      fontSize: t.fontSize.sm,
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
                      fontSize: t.fontSize.sm,
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
                borderRadius: t.radius,
                padding: '12px 16px',
                color: '#e74c3c',
                fontSize: t.fontSize.base,
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
                      <div style={{ color: 'rgba(255,255,255,0.85)', fontSize: t.fontSize.md, fontWeight: t.fontWeight.bold }}>
                        {value ?? '—'}
                      </div>
                      <div style={{ color: 'rgba(255,255,255,0.35)', fontSize: t.fontSize.micro, marginTop: '1px' }}>
                        {label}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Initial state — region selected but not yet run */}
            {!spatialLoading && !spatialData && (
              <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.base, padding: '16px 0', textAlign: 'center' }}>
                Click <strong style={{ color: 'rgba(255,255,255,0.5)' }}>▶ Run Map</strong> to compute model disagreement for the selected region.
              </div>
            )}
          </div>
        )}
      </div>
  );
}

export default SpatialAgreementPanel;
