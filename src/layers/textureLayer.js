import { fetchUncertaintyPair } from '../api/forecastApi';
import { COLORMAPS } from '../constants';

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Interpolate RGB from colormap at position t ∈ [0,1] */
const cmapRGB = (colors, t, flip = false) => {
  const cs  = flip ? [...colors].reverse() : colors;
  const seg = cs.length - 1;
  const si  = Math.min(Math.floor(t * seg), seg - 1);
  const lt  = t * seg - si;
  const lerp = (h1, h2) =>
    Math.round(parseInt(h1, 16) + (parseInt(h2, 16) - parseInt(h1, 16)) * lt);
  return [
    lerp(cs[si].slice(1, 3), cs[si + 1].slice(1, 3)),
    lerp(cs[si].slice(3, 5), cs[si + 1].slice(3, 5)),
    lerp(cs[si].slice(5, 7), cs[si + 1].slice(5, 7)),
  ];
};

/** Snap a normalised value to the centre of its bucket */
const snap = (norm, buckets) => {
  if (!buckets || buckets <= 0) return Math.min(Math.max(norm, 0), 1);
  const clamped = Math.min(Math.max(norm, 0), 0.9999);
  return (Math.floor(clamped * buckets) + 0.5) / buckets;
};

// ── Main draw function ────────────────────────────────────────────────────────

/**
 * Draws a per-cell texture overlay that encodes forecast value as colour
 * and ensemble spread as texture density (Lines) or square size (Squares).
 *
 * @param {L.Map}    map
 * @param {{ current: { canvas, draw } | null }} textureLayerRef
 * @param {string}   modelName
 * @param {string}   variable
 * @param {number}   hour
 * @param {string}   colormapName
 * @param {'Lines'|'Squares'} textureStyle
 * @param {number}   numBuckets      0 = continuous
 * @param {boolean}  flipColormap
 * @param {number}   gridOpacity     0–1
 * @param {boolean}  invertUncertainty
 * @param {Function} [onRanges]      called with { meanMax, stdMax }
 */
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

    // Build lookup maps
    const meanLookup = {}, stdLookup = {};
    for (const pt of meanData) meanLookup[`${pt.lat}_${pt.lon}`] = getVal(pt);
    for (const pt of stdData)  stdLookup[`${pt.lat}_${pt.lon}`]  = getVal(pt);

    const meanVals = Object.values(meanLookup).filter(v => !isNaN(v) && v >= 0);
    const stdVals  = Object.values(stdLookup).filter(v  => !isNaN(v) && v >= 0);
    if (!meanVals.length || !stdVals.length) return;

    const meanMax = Math.max(...meanVals) || 1;
    const stdMax  = Math.max(...stdVals)  || 1;
    onRanges?.({ meanMax, stdMax });

    const colors = COLORMAPS[colormapName]?.colors ?? COLORMAPS['Default'].colors;

    // Auto-detect grid spacing from data
    const sortedLats = [
      ...new Set(meanData.map(p => Math.round(parseFloat(p.lat) * 10) / 10)),
    ].sort((a, b) => a - b);
    const latSpacing = sortedLats.length > 1 ? Math.abs(sortedLats[1] - sortedLats[0]) : 0.5;
    const half = latSpacing * 0.5;

    // Canvas overlay
    const canvas = document.createElement('canvas');
    canvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;z-index:425';
    canvas.style.opacity = String(Math.min(Math.max(gridOpacity, 0), 1));
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

        // Normalise
        let normVal = Math.min(meanVal / meanMax, 1);
        let normStd = Math.min(stdVal  / stdMax,  1);
        if (invertUncertainty) normStd = 1 - normStd;

        // Discretise if buckets > 0
        normVal = snap(normVal, numBuckets);
        normStd = snap(normStd, numBuckets);

        try {
          const tl = map.latLngToContainerPoint([lat + half, lon - half]);
          const br = map.latLngToContainerPoint([lat - half, lon + half]);
          const cw = Math.max(1, br.x - tl.x);
          const ch = Math.max(1, br.y - tl.y);

          // ── Value colour fill ───────────────────────────────────────────────
          const [r, g, b] = cmapRGB(colors, normVal, flipColormap);
          ctx.fillStyle = `rgb(${r},${g},${b})`;
          ctx.fillRect(tl.x, tl.y, cw, ch);

          // ── Texture overlay (clipped to cell) ───────────────────────────────
          ctx.save();
          ctx.beginPath();
          ctx.rect(tl.x, tl.y, cw, ch);
          ctx.clip();

          if (textureStyle === 'Lines') {
            // White diagonal hatching — denser spacing = more uncertain
            const maxSpacing = Math.max(cw, ch) * 2.5;
            const minSpacing = 1.5;
            // At normStd=0 → very wide spacing (barely visible)
            // At normStd=1 → very dense (nearly solid white)
            const spacing = Math.max(minSpacing, maxSpacing * (1 - normStd * 0.95));
            // Phase-align to map coordinates so lines don't jump at cell boundaries
            const phase = ((tl.x - tl.y) % spacing + spacing) % spacing;
            ctx.strokeStyle = 'rgba(255,255,255,0.85)';
            ctx.lineWidth = 0.9;
            ctx.beginPath();
            for (let x = tl.x - ch - phase; x <= tl.x + cw + spacing; x += spacing) {
              ctx.moveTo(x,      tl.y);
              ctx.lineTo(x + ch, tl.y + ch);
            }
            ctx.stroke();

          } else if (textureStyle === 'Squares') {
            // White centre square — bigger = more uncertain
            const maxSize = Math.min(cw, ch) * 0.92;
            const squareSize = maxSize * normStd;
            if (squareSize > 0.5) {
              const cx = tl.x + cw / 2;
              const cy = tl.y + ch / 2;
              ctx.fillStyle = 'rgba(255,255,255,0.82)';
              ctx.fillRect(
                cx - squareSize / 2,
                cy - squareSize / 2,
                squareSize,
                squareSize,
              );
            }
          }

          ctx.restore();
        } catch { /* skip off-screen points */ }
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

// ── Stop / cleanup ────────────────────────────────────────────────────────────

export const stopTexture = (map, textureLayerRef) => {
  if (textureLayerRef.current) {
    const { canvas, draw } = textureLayerRef.current;
    if (map && draw) {
      map.off('move', draw);
      map.off('zoom', draw);
    }
    canvas?.remove();
    textureLayerRef.current = null;
  }
};

// ── Legend helpers ────────────────────────────────────────────────────────────

/**
 * Returns N evenly-spaced normalised positions for the legend swatches.
 */
export const getTextureLegendBins = (numBuckets) => {
  const N = numBuckets > 0 ? numBuckets : 8;
  return Array.from({ length: N }, (_, i) => (i + 0.5) / N);
};
