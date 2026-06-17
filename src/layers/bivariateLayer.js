import L from 'leaflet';
import { fetchUncertaintyPair } from '../api/forecastApi';

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
export const drawBivariateLayer = async (
  map, bivariateLayerRef,
  modelName, variable, hour,
  colorMatrix, onRanges,
  numBuckets = 0,
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

    const N   = numBuckets > 1 ? numBuckets : colorMatrix.length;
    const bin = (v, max) => Math.min(N - 1, Math.floor((Math.min(v, max) / max) * N));

    // Auto-detect grid spacing from data
    const lats    = meanData.map(p => parseFloat(p.lat)).sort((a, b) => a - b);
    const unique  = [...new Set(lats.map(l => Math.round(l * 10) / 10))];
    const spacing = unique.length > 1 ? Math.abs(unique[1] - unique[0]) : 0.5;
    const half    = spacing * 0.5;

    const layerGroup = L.layerGroup();
    for (const pt of meanData) {
      const lat     = parseFloat(pt.lat);
      const lon     = parseFloat(pt.lon);
      const key     = `${pt.lat}_${pt.lon}`;
      const meanVal = meanLookup[key] ?? 0;
      const stdVal  = stdLookup[key]  ?? 0;
      const colIdx  = bin(meanVal, meanMax);  // X = mean value
      const rowIdx  = bin(stdVal,  stdMax);   // Y = uncertainty
      const color   = colorMatrix[rowIdx][colIdx];
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
