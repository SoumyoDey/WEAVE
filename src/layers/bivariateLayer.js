import L from 'leaflet';
import { fetchUncertaintyPair } from '../api/forecastApi';
import { COLORMAPS } from '../constants';

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Snap a normalised value [0,1] to the centre of its bucket.
 *  N=0 → no snapping (continuous). */
const snap = (v, N) => {
  const c = Math.min(Math.max(v, 0), 0.9999);
  if (!N || N <= 0) return c;
  return (Math.floor(c * N) + 0.5) / N;
};

/** Compute bivariate colour from normalised value + uncertainty [0,1]. */
const bivColor = (colormapName, normVal, normStd, vsup = false) => {
  const colors   = COLORMAPS[colormapName]?.colors ?? COLORMAPS['Default'].colors;
  const neutral  = 185;
  const strength = vsup ? 0.92 : 0.60;
  const t = vsup
    ? normVal * (1 - normStd * strength) + 0.5 * (normStd * strength)
    : normVal;
  const seg = colors.length - 1;
  const si  = Math.min(Math.floor(Math.min(t, 0.9999) * seg), seg - 1);
  const lt  = t * seg - si;
  const lerp = (a, b) => Math.round(parseInt(a, 16) + (parseInt(b, 16) - parseInt(a, 16)) * lt);
  const r0  = lerp(colors[si].slice(1,3), colors[si+1].slice(1,3));
  const g0  = lerp(colors[si].slice(3,5), colors[si+1].slice(3,5));
  const b0  = lerp(colors[si].slice(5,7), colors[si+1].slice(5,7));
  const sup = normStd * strength * 0.80;
  const clamp = v => Math.max(0, Math.min(255, Math.round(v)));
  const toHex = v => clamp(v).toString(16).padStart(2, '0');
  return '#' + toHex(r0 + (neutral - r0) * sup)
             + toHex(g0 + (neutral - g0) * sup)
             + toHex(b0 + (neutral - b0) * sup);
};

// ── Main draw function ────────────────────────────────────────────────────────

/**
 * Fetches mean + std fields and renders a bivariate (or VSUP Fan) choropleth.
 * numBuckets=0 → continuous. numBuckets=N → N×N discrete bins via snap().
 */
export const drawBivariateLayer = async (
  map, bivariateLayerRef,
  modelName, variable, hour,
  colorMatrix, onRanges,
  numBuckets = 0,
  colormapName = 'Default',
  vsup = false,
) => {
  if (!map?._loaded) return;
  stopBivariate(map, bivariateLayerRef);

  try {
    const { meanData, stdData } = await fetchUncertaintyPair(modelName, variable, hour);
    if (!Array.isArray(meanData) || !Array.isArray(stdData)) return;

    const val = (pt) => parseFloat(variable === 'wind' ? pt.speed : pt.value);

    const meanLookup = {}, stdLookup = {};
    for (const pt of meanData) meanLookup[`${pt.lat}_${pt.lon}`] = val(pt);
    for (const pt of stdData)  stdLookup[`${pt.lat}_${pt.lon}`]  = val(pt);

    const meanVals = Object.values(meanLookup).filter(v => !isNaN(v) && v >= 0);
    const stdVals  = Object.values(stdLookup).filter(v => !isNaN(v) && v >= 0);
    if (!meanVals.length || !stdVals.length) return;

    const meanMax = Math.max(...meanVals) || 1;
    const stdMax  = Math.max(...stdVals)  || 1;
    onRanges?.({ meanMax, stdMax });

    // Auto-detect grid spacing
    const lats    = meanData.map(p => parseFloat(p.lat)).sort((a, b) => a - b);
    const unique  = [...new Set(lats.map(l => Math.round(l * 10) / 10))];
    const spacing = unique.length > 1 ? Math.abs(unique[1] - unique[0]) : 0.5;
    const half    = spacing * 0.5;

    const N = numBuckets > 0 ? numBuckets : 0;

    const layerGroup = L.layerGroup();
    for (const pt of meanData) {
      const lat     = parseFloat(pt.lat);
      const lon     = parseFloat(pt.lon);
      const key     = `${pt.lat}_${pt.lon}`;
      const meanVal = meanLookup[key] ?? 0;
      const stdVal  = stdLookup[key]  ?? 0;

      // snap both dimensions (no-op when N=0)
      const normVal = snap(meanVal / meanMax, N);
      const normStd = snap(stdVal  / stdMax,  N);
      const color   = bivColor(colormapName, normVal, normStd, vsup);

      L.rectangle(
        [[lat - half, lon - half], [lat + half, lon + half]],
        { fillColor: color, color: 'transparent', fillOpacity: 0.85, weight: 0, interactive: false },
      ).addTo(layerGroup);
    }

    layerGroup.addTo(map);
    bivariateLayerRef.current = layerGroup;
  } catch (err) {
    console.error('Bivariate error:', err);
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
