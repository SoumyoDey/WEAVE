const BASE = process.env.REACT_APP_API_URL || 'http://localhost:5000/api';

/**
 * Fetches a spatial metric (SSR, correlation, …) for a bounding box.
 * @param {object} p
 * @param {string} p.metric      - metric key, e.g. 'ssr'
 * @param {string} p.modelName
 * @param {string} p.variable
 * @param {number} [p.hour]      - required when metric.requiresHour === true
 * @param {number} [p.threshold] - threshold value in native units: mm/6h for precipitation, m/s for wind
 * @param {number} [p.hourMin]   - start of lead-time range
 * @param {number} [p.hourMax]   - end of lead-time range
 * @param {object} p.bounds      - { min_lat, max_lat, min_lon, max_lon }
 */
export const fetchSpatialMetric = async ({ metric, modelName, variable, hour, threshold, hourMin, hourMax, bounds }) => {
  const params = new URLSearchParams({
    metric,
    model:    modelName,
    variable,
    min_lat:  bounds.min_lat ?? bounds.minLat,
    max_lat:  bounds.max_lat ?? bounds.maxLat,
    min_lon:  bounds.min_lon ?? bounds.minLon,
    max_lon:  bounds.max_lon ?? bounds.maxLon,
  });
  if (hour     != null) params.set('hour', hour);
  if (threshold != null) {
    params.set(variable === 'wind' ? 'threshold_ms' : 'threshold_mm_6h', threshold);
  }
  if (hourMin  != null) params.set('hour_min', hourMin);
  if (hourMax  != null) params.set('hour_max',         hourMax);
  const res  = await fetch(`${BASE}/spatial-metric?${params}`);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data;
};

/**
 * Requests a matplotlib/cartopy PNG of the spatial metric result.
 * Returns { image: '<base64>' } or { error: '...' }.
 */
export const fetchSpatialMetricPlot = async (payload) => {
  const res = await fetch(`${BASE}/spatial-metric-plot`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(payload),
  });
  return res.json();
};
