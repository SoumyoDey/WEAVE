import React, { useRef, useEffect } from 'react';
import { COLORMAPS } from '../../constants';

/** Interpolate hex colour from a colormap at position t ∈ [0,1] */
const cmapHex = (colors, t, flip = false) => {
  const cs  = flip ? [...colors].reverse() : colors;
  const seg = cs.length - 1;
  const si  = Math.min(Math.floor(Math.min(t, 0.9999) * seg), seg - 1);
  const lt  = t * seg - si;
  const lerp = (h1, h2) =>
    Math.round(parseInt(h1, 16) + (parseInt(h2, 16) - parseInt(h1, 16)) * lt)
      .toString(16).padStart(2, '0');
  return `#${lerp(cs[si].slice(1,3), cs[si+1].slice(1,3))}${lerp(cs[si].slice(3,5), cs[si+1].slice(3,5))}${lerp(cs[si].slice(5,7), cs[si+1].slice(5,7))}`;
};

/** Small canvas swatch showing a texture pattern at a given uncertainty level */
function TextureSwatch({ normStd, textureStyle, size = 28 }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, size, size);
    // Background — neutral grey to show texture clearly
    ctx.fillStyle = '#6aaa80';
    ctx.fillRect(0, 0, size, size);

    if (textureStyle === 'Lines') {
      const maxSpacing = size * 2.5;
      const minSpacing = 1.5;
      const spacing = Math.max(minSpacing, maxSpacing * (1 - normStd * 0.95));
      ctx.strokeStyle = 'rgba(255,255,255,0.85)';
      ctx.lineWidth = 0.9;
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, size, size);
      ctx.clip();
      ctx.beginPath();
      for (let x = -size; x <= size * 2; x += spacing) {
        ctx.moveTo(x,        0);
        ctx.lineTo(x + size, size);
      }
      ctx.stroke();
      ctx.restore();
    } else if (textureStyle === 'Squares') {
      const squareSize = size * normStd * 0.88;
      if (squareSize > 0.5) {
        ctx.fillStyle = 'rgba(255,255,255,0.82)';
        ctx.fillRect(
          (size - squareSize) / 2,
          (size - squareSize) / 2,
          squareSize,
          squareSize,
        );
      }
    }
  }, [normStd, textureStyle, size]);

  return <canvas ref={ref} width={size} height={size} style={{ borderRadius: '3px', display: 'block' }} />;
}

/**
 * Legend for Texture uncertainty mode.
 * Shows two rows: Value (coloured swatches) and Uncertainty (texture swatches).
 */
export function TextureLegend({
  bivariateRanges,
  selectedColormap,
  selectedVariable,
  textureStyle = 'Lines',
  numBuckets = 0,
  flipColormap = false,
  invertUncertainty = false,
}) {
  const colors  = COLORMAPS[selectedColormap]?.colors ?? COLORMAPS['Default'].colors;
  const N       = numBuckets > 0 ? numBuckets : 8;
  const maxVal  = bivariateRanges?.meanMax ?? 5;
  const maxStd  = bivariateRanges?.stdMax  ?? 5;
  const unit    = selectedVariable === 'wind' ? 'm/s' : 'mm/hr';
  const swatchW = Math.max(14, Math.min(30, Math.floor(200 / N)));

  const cardStyle = {
    background: 'rgba(10,18,28,0.92)',
    border: '1px solid rgba(255,255,255,0.1)',
    backdropFilter: 'blur(8px)',
    padding: '12px 14px',
    borderRadius: '10px',
    boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
    userSelect: 'none',
    minWidth: '180px',
  };

  const rowLabelStyle = {
    fontSize: '10px', fontWeight: 600, color: 'rgba(255,255,255,0.5)',
    textTransform: 'uppercase', letterSpacing: '0.06em',
    marginBottom: '4px',
  };

  const bins = Array.from({ length: N }, (_, i) => (i + 0.5) / N);

  return (
    <div style={cardStyle}>
      <div style={{ color: 'white', fontSize: '12px', fontWeight: 600, marginBottom: '10px' }}>
        ▦ Texture
        {numBuckets > 0 && (
          <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', marginLeft: '6px' }}>
            {N} bins
          </span>
        )}
      </div>

      {/* Value row */}
      <div style={{ marginBottom: '10px' }}>
        <div style={rowLabelStyle}>Value</div>
        <div style={{ display: 'flex', gap: '2px', marginBottom: '3px' }}>
          {bins.map((t, i) => (
            <div
              key={i}
              title={`${(t * maxVal).toFixed(1)} ${unit}`}
              style={{
                width: swatchW, height: swatchW,
                background: cmapHex(colors, t, flipColormap),
                borderRadius: i === 0 ? '3px 0 0 3px' : i === N - 1 ? '0 3px 3px 0' : 0,
                flexShrink: 0,
              }}
            />
          ))}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.5)' }}>
            {flipColormap ? maxVal.toFixed(1) : '0'}
          </span>
          <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.5)' }}>
            {flipColormap ? '0' : maxVal.toFixed(1)} {unit}
          </span>
        </div>
      </div>

      {/* Uncertainty / texture row */}
      <div>
        <div style={rowLabelStyle}>Uncertainty</div>
        <div style={{ display: 'flex', gap: '2px', marginBottom: '3px' }}>
          {bins.map((t, i) => {
            const normStd = invertUncertainty ? (1 - t) : t;
            return (
              <div key={i} style={{ flexShrink: 0 }}>
                <TextureSwatch normStd={normStd} textureStyle={textureStyle} size={swatchW} />
              </div>
            );
          })}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.5)' }}>
            {invertUncertainty ? maxStd.toFixed(1) : '0'}
          </span>
          <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.5)' }}>
            {invertUncertainty ? '0' : maxStd.toFixed(1)} {unit}
          </span>
        </div>
      </div>
    </div>
  );
}
