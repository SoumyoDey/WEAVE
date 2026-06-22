import { fetchUncertaintyPair } from '../api/forecastApi';
import { COLORMAPS } from '../constants';

// ── Helpers ───────────────────────────────────────────────────────────────────

const snap = (v, N) => {
  const c = Math.min(Math.max(v, 0), 0.9999);
  if (!N || N <= 0) return c;
  return (Math.floor(c * N) + 0.5) / N;
};

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

// ── Main draw function ────────────────────────────────────────────────────────

export const drawTextureLayer = async (
  map, textureLayerRef,
  modelName, variable, hour,
  colormapName, textureStyle, numBuckets,
  flipColormap, gridOpacity, invertUncertainty,
  onRanges,
) => {
  if (!map?._loaded) return;
  stopTexture(map, textureLayerRef);

  try {
    const { meanData, stdData } = await fetchUncertaintyPair(modelName, variable, hour);
    if (!Array.isArray(meanData) || !Array.isArray(stdData) || !meanData.length) return;

    const getVal = (pt) => parseFloat(variable === 'wind' ? pt.speed : pt.value);

    const meanLookup = {}, stdLookup = {};
    for (const pt of meanData) meanLookup[`${pt.lat}_${pt.lon}`] = getVal(pt);
    for (const pt of stdData)  stdLookup[`${pt.lat}_${pt.lon}`]  = getVal(pt);

    const meanVals = Object.values(meanLookup).filter(v => !isNaN(v) && v >= 0);
    const stdVals  = Object.values(stdLookup).filter(v => !isNaN(v)  && v >= 0);
    if (!meanVals.length || !stdVals.length) return;

    const meanMax = Math.max(...meanVals) || 1;
    const stdMax  = Math.max(...stdVals)  || 1;
    onRanges?.({ meanMax, stdMax });

    const colors = COLORMAPS[colormapName]?.colors ?? COLORMAPS['Default'].colors;

    // Auto-detect grid spacing
    const sortedLats = [...new Set(meanData.map(p => Math.round(parseFloat(p.lat) * 10) / 10))].sort((a, b) => a - b);
    const latSpacing = sortedLats.length > 1 ? Math.abs(sortedLats[1] - sortedLats[0]) : 0.5;
    const half       = latSpacing * 0.5;

    const N = numBuckets > 0 ? numBuckets : 0;

    // Canvas overlay
    const canvas = document.createElement('canvas');
    canvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;z-index:425';
    canvas.style.opacity = String(Math.min(Math.max(gridOpacity ?? 1, 0), 1));
    map.getContainer().appendChild(canvas);

    const draw = () => {
      if (!map?._loaded) return;
      const size = map.getSize();
      if (!size || size.x <= 0 || size.y <= 0) return;
      canvas.width  = size.x;
      canvas.height = size.y;
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      for (const pt of meanData) {
        const lat = parseFloat(pt.lat);
        const lon = parseFloat(pt.lon);
        const key = `${pt.lat}_${pt.lon}`;
        const meanVal = meanLookup[key] ?? 0;
        const stdVal  = stdLookup[key]  ?? 0;

        let normVal = snap(Math.min(meanVal / meanMax, 1), N);
        let normStd = snap(Math.min(stdVal  / stdMax,  1), N);
        if (invertUncertainty) normStd = 1 - normStd;

        try {
          const tl = map.latLngToContainerPoint([lat + half, lon - half]);
          const br = map.latLngToContainerPoint([lat - half, lon + half]);
          const cw = Math.max(1, br.x - tl.x);
          const ch = Math.max(1, br.y - tl.y);

          // Value colour fill
          ctx.fillStyle = cmapHex(colors, normVal, flipColormap);
          ctx.fillRect(tl.x, tl.y, cw, ch);

          // Texture overlay
          ctx.save();
          ctx.beginPath();
          ctx.rect(tl.x, tl.y, cw, ch);
          ctx.clip();

          if (textureStyle === 'Squares') {
            const squareSize = Math.min(cw, ch) * normStd * 0.90;
            if (squareSize > 0.5) {
              ctx.fillStyle = 'rgba(255,255,255,0.82)';
              ctx.fillRect(tl.x + cw/2 - squareSize/2, tl.y + ch/2 - squareSize/2, squareSize, squareSize);
            }
          } else {
            // Lines — denser = more uncertain, globally phase-aligned
            const maxSpacing = Math.max(cw, ch) * 2.5;
            const spacing    = Math.max(1.5, maxSpacing * (1 - normStd * 0.95));
            const phase      = ((tl.x - tl.y) % spacing + spacing) % spacing;
            ctx.strokeStyle = 'rgba(255,255,255,0.85)';
            ctx.lineWidth   = 0.9;
            ctx.beginPath();
            for (let x = tl.x - ch - phase; x <= tl.x + cw + spacing; x += spacing) {
              ctx.moveTo(x,      tl.y);
              ctx.lineTo(x + ch, tl.y + ch);
            }
            ctx.stroke();
          }

          ctx.restore();
        } catch { /* skip off-screen */ }
      }
    };

    textureLayerRef.current = { canvas, draw };
    draw();
    map.on('move', draw);
    map.on('zoom', draw);

  } catch (err) {
    console.error('Texture layer error:', err);
  }
};

export const stopTexture = (map, textureLayerRef) => {
  if (textureLayerRef.current) {
    const { canvas, draw } = textureLayerRef.current;
    if (map && draw) { map.off('move', draw); map.off('zoom', draw); }
    canvas?.remove();
    textureLayerRef.current = null;
  }
};
