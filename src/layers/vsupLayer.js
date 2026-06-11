import L from 'leaflet';
import { COLORMAPS } from '../constants';
import { fetchUncertaintyPair } from '../api/forecastApi';

/**
 * Fetches mean + std data and renders VSup boxes on the map.
 *
 * @param {L.Map}   map
 * @param {{ current: L.LayerGroup | null }} uncertaintyLayerRef
 * @param {{ current: HTMLCanvasElement | null }} uncertaintyCanvasRef
 * @param {string}  modelName
 * @param {string}  variable
 * @param {number}  hour
 * @param {string}  selectedColormap
 */
export const drawUncertaintyBoxes = async (
  map, uncertaintyLayerRef, uncertaintyCanvasRef,
  modelName, variable, hour, selectedColormap,
  invertUncertainty = false,
) => {
  if (!map?._loaded) return;

  // Remove previous layer
  if (uncertaintyLayerRef.current) {
    map.removeLayer(uncertaintyLayerRef.current);
    uncertaintyLayerRef.current = null;
  }

  try {
    const { meanData, stdData } = await fetchUncertaintyPair(modelName, variable, hour);
    if (!Array.isArray(stdData) || stdData.length === 0) return;

    const val = (pt) => parseFloat(variable === 'wind' ? pt.speed : pt.value);

    // Build mean lookup
    const meanLookup = {};
    if (Array.isArray(meanData)) {
      for (const pt of meanData) meanLookup[`${pt.lat}_${pt.lon}`] = val(pt);
    }

    const meanVals = Object.values(meanLookup).filter(v => !isNaN(v) && v > 0);
    const stdVals  = stdData.map(val).filter(v => !isNaN(v) && v >= 0);
    const meanMax  = Math.max(...meanVals) || 1;
    const stdMax   = Math.max(...stdVals)  || 1;

    const vsupColor = (meanVal, stdVal) => {
      const normVal    = Math.min(meanVal / meanMax, 1);
      const normStd    = Math.min(stdVal / stdMax, 1);
      // Colour encoding is never changed by inversion — precipitation colours stay identical.
      // Only box size is affected by the invert flag (handled in sizeScale below).
      const colors = COLORMAPS[selectedColormap].colors;
      const seg    = colors.length - 1;
      const ss     = 1 / seg;
      const mapped = 0.15 + normVal * 0.85;
      const si     = Math.min(Math.floor(mapped / ss), seg - 1);
      const t      = (mapped - si * ss) / ss;
      const c1 = colors[si], c2 = colors[si + 1];
      let r = Math.round(parseInt(c1.slice(1,3),16) + (parseInt(c2.slice(1,3),16) - parseInt(c1.slice(1,3),16)) * t);
      let g = Math.round(parseInt(c1.slice(3,5),16) + (parseInt(c2.slice(3,5),16) - parseInt(c1.slice(3,5),16)) * t);
      let b = Math.round(parseInt(c1.slice(5,7),16) + (parseInt(c2.slice(5,7),16) - parseInt(c1.slice(5,7),16)) * t);
      const grey  = 210;
      const blend = normStd * 0.85;
      r = Math.round(r + (grey - r) * blend);
      g = Math.round(g + (grey - g) * blend);
      b = Math.round(b + (grey - b) * blend);
      return `rgba(${r},${g},${b},${0.75 - normStd * 0.3})`;
    };

    // maxDeg = 0.4 → boxes are 0.8° wide on a 1° deduplicated grid → no overlap
    const minDeg = 0.08, maxDeg = 0.4;
    const sizeScale = (stdVal) => {
      if (stdMax === 0) return (minDeg + maxDeg) / 2;
      // Inversion flips box size: normal = large box means high uncertainty;
      //                           inverted = small box means high uncertainty
      const normStd = invertUncertainty
        ? (1 - Math.min(stdVal / stdMax, 1))
        : Math.min(stdVal / stdMax, 1);
      const t = Math.sqrt(normStd);
      return minDeg + t * (maxDeg - minDeg);
    };

    // Deduplicate to 1° grid cells
    const cellMap = {};
    for (const pt of stdData) {
      const key = `${Math.round(parseFloat(pt.lat))}_${Math.round(parseFloat(pt.lon))}`;
      if (!cellMap[key]) cellMap[key] = pt;
    }

    const layerGroup = L.layerGroup();
    for (const pt of Object.values(cellMap)) {
      const lat     = parseFloat(pt.lat);
      const lon     = parseFloat(pt.lon);
      const stdVal  = val(pt);
      const meanVal = meanLookup[`${pt.lat}_${pt.lon}`] ?? 0;
      if (isNaN(stdVal) || isNaN(meanVal)) continue;
      const half  = sizeScale(stdVal);
      const color = vsupColor(meanVal, stdVal);
      L.rectangle(
        [[lat - half, lon - half], [lat + half, lon + half]],
        { fillColor: color, color, fillOpacity: 1, weight: 0.3, opacity: 0.4, interactive: false },
      ).addTo(layerGroup);
    }

    layerGroup.addTo(map);
    uncertaintyLayerRef.current = layerGroup;
  } catch (err) {
    console.error('Uncertainty fetch error:', err);
  }
};

/**
 * Removes the VSup uncertainty overlay from the map.
 */
export const stopUncertainty = (map, uncertaintyLayerRef, uncertaintyCanvasRef) => {
  if (uncertaintyLayerRef.current && map) {
    map.removeLayer(uncertaintyLayerRef.current);
    uncertaintyLayerRef.current = null;
  }
  uncertaintyCanvasRef.current?.remove();
  uncertaintyCanvasRef.current = null;
};
