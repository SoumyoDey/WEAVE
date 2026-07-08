import L from 'leaflet';
import { fetchUncertaintyPair } from '../api/forecastApi';
import { COLORMAPS, buildVsupLevels } from '../constants';

/** Compute a continuous bivariate colour directly from normVal + normStd (no matrix lookup) */
const continuousColor = (colormapName, normVal, normStd, vsup = false, flip = false) => {
  const colors   = COLORMAPS[colormapName]?.colors ?? COLORMAPS['Default'].colors;
  const neutral  = 185;
  const strength = vsup ? 0.92 : 0.60;
  const lerp = (a, b, t) => Math.round(a + (b - a) * t);
  const t0 = vsup
    ? normVal * (1 - normStd * strength) + 0.5 * (normStd * strength)
    : normVal;
  const t   = flip ? 1 - t0 : t0;   // reverse hue when colormap is flipped
  const seg = colors.length - 1;
  const si  = Math.min(Math.floor(Math.min(t, 0.9999) * seg), seg - 1);
  const lt  = t * seg - si;
  const c1  = colors[si], c2 = colors[si + 1];
  const r0  = lerp(parseInt(c1.slice(1,3),16), parseInt(c2.slice(1,3),16), lt);
  const g0  = lerp(parseInt(c1.slice(3,5),16), parseInt(c2.slice(3,5),16), lt);
  const b0  = lerp(parseInt(c1.slice(5,7),16), parseInt(c2.slice(5,7),16), lt);
  const r   = lerp(r0, neutral, normStd * strength * 0.80);
  const g   = lerp(g0, neutral, normStd * strength * 0.80);
  const b   = lerp(b0, neutral, normStd * strength * 0.80);
  return `rgb(${r},${g},${b})`;
};

/**
 * Fetches mean + std fields and renders a bivariate (or VSUP Fan) choropleth.
 *
 * @param {L.Map}   map
 * @param {{ current: L.LayerGroup | null }} bivariateLayerRef
 * @param {string}  modelName
 * @param {string}  variable
 * @param {number}  hour
 * @param {Array}   colorMatrix   - 4×4 array of hex strings from buildColorMatrix()
 * @param {Function} onRanges     - called with { meanMax, stdMax } once computed
 */
/**
 * Render bivariate layer from already-fetched data.
 * Call this when only display params change (numBuckets, colormap, invert).
 */
export const renderBivariateFromCache = (
  map, bivariateLayerRef, cachedData,
  colorMatrix, numBuckets, colormapName, vsup,
  invertUncertainty = false, flipColormap = false, gridOpacity = 1,
) => {
  if (!map?._loaded || !cachedData) return;
  stopBivariate(map, bivariateLayerRef);

  const { meanData, meanLookup, stdLookup, meanMax, stdMax, half } = cachedData;
  const fillOpacity = 0.85 * Math.min(Math.max(gridOpacity, 0), 1);

  // snap: 0 = continuous (exact value), N > 0 = snap to bucket centre (same as Texture)
  const snap = (norm, N) => {
    if (!N || N <= 0) return Math.min(Math.max(norm, 0), 1);
    const clamped = Math.min(Math.max(norm, 0), 0.9999);
    return (Math.floor(clamped * N) + 0.5) / N;
  };

  // ── True VSUP fan quantization ──────────────────────────────────────────────
  // Uncertainty is split into `rings` levels; the number of VALUE buckets shrinks
  // as uncertainty rises (segCounts, ordered low→high uncertainty). This makes the
  // map match the fan legend: fewer distinguishable values where spread is high.
  const vsupLevels = vsup ? buildVsupLevels(numBuckets) : null;
  const vsupSnap = (normVal0, normStd0) => {
    const { segCounts, rings } = vsupLevels;
    const rIdx  = Math.min(Math.floor(normStd0 * rings), rings - 1);
    const bins  = segCounts[rIdx];
    const vClamp = Math.min(Math.max(normVal0, 0), 0.9999);
    return {
      normVal: (Math.floor(vClamp * bins) + 0.5) / bins,
      normStd: (rIdx + 0.5) / rings,
    };
  };

  const layerGroup = L.layerGroup();
  for (const pt of meanData) {
    const lat     = parseFloat(pt.lat);
    const lon     = parseFloat(pt.lon);
    const key     = `${pt.lat}_${pt.lon}`;
    const meanVal = meanLookup[key] ?? 0;
    const stdVal  = stdLookup[key]  ?? 0;

    const rawVal = Math.min(meanVal / meanMax, 1);
    let   rawStd = Math.min(stdVal  / stdMax,  1);
    if (invertUncertainty) rawStd = 1 - rawStd;
    const { normVal, normStd } = vsup
      ? vsupSnap(rawVal, rawStd)
      : { normVal: snap(rawVal, numBuckets), normStd: snap(rawStd, numBuckets) };
    const color   = continuousColor(colormapName, normVal, normStd, vsup, flipColormap);
    L.rectangle(
      [[lat - half, lon - half], [lat + half, lon + half]],
      { fillColor: color, color: 'transparent', fillOpacity, weight: 0, interactive: false },
    ).addTo(layerGroup);
  }
  layerGroup.addTo(map);
  bivariateLayerRef.current = layerGroup;
};

/**
 * Fetch data then render. Use when model/variable/hour changes.
 * Returns the cached data object for reuse.
 */
export const drawBivariateLayer = async (
  map, bivariateLayerRef,
  modelName, variable, hour,
  colorMatrix, onRanges,
  numBuckets = 0,
  colormapName = 'Default',
  vsup = false,
  invertUncertainty = false,
  flipColormap = false,
  gridOpacity = 1,
) => {
  if (!map?._loaded) return null;
  stopBivariate(map, bivariateLayerRef);

  try {
    const { meanData, stdData } = await fetchUncertaintyPair(modelName, variable, hour);
    if (!Array.isArray(meanData) || !Array.isArray(stdData)) return null;

    const val = (pt) => parseFloat(variable === 'wind' ? pt.speed : pt.value);

    const meanLookup = {}, stdLookup = {};
    for (const pt of meanData) meanLookup[`${pt.lat}_${pt.lon}`] = val(pt);
    for (const pt of stdData)  stdLookup[`${pt.lat}_${pt.lon}`]  = val(pt);

    const meanVals = Object.values(meanLookup).filter(v => !isNaN(v) && v >= 0);
    const stdVals  = Object.values(stdLookup).filter(v => !isNaN(v) && v >= 0);
    if (!meanVals.length || !stdVals.length) return null;

    const meanMax = Math.max(...meanVals) || 1;
    const stdMax  = Math.max(...stdVals)  || 1;
    onRanges?.({ meanMax, stdMax });

    // Auto-detect grid spacing
    const lats    = meanData.map(p => parseFloat(p.lat)).sort((a, b) => a - b);
    const unique  = [...new Set(lats.map(l => Math.round(l * 10) / 10))];
    const spacing = unique.length > 1 ? Math.abs(unique[1] - unique[0]) : 0.5;
    const half    = spacing * 0.5;

    const cachedData = { meanData, meanLookup, stdLookup, meanMax, stdMax, half };

    renderBivariateFromCache(map, bivariateLayerRef, cachedData, colorMatrix, numBuckets, colormapName, vsup, invertUncertainty, flipColormap, gridOpacity);

    return cachedData;
  } catch (err) {
    console.error('Bivariate error:', err);
    return null;
  }
};

/**
 * Removes the bivariate/VSUP-Fan layer from the map.
 */
export const stopBivariate = (map, bivariateLayerRef) => {
  if (bivariateLayerRef.current && map) {
    map.removeLayer(bivariateLayerRef.current);
    bivariateLayerRef.current = null;
  }
};
