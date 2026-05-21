const BASE = 'http://localhost:5000/api';

/**
 * Fetches a spatial metric (SSR, correlation, …) for a bounding box.
 * @param {object} p
 * @param {string} p.metric      - metric key, e.g. 'ssr'
 * @param {string} p.modelName
 * @param {string} p.variable
 * @param {number} [p.hour]      - required when metric.requiresHour === true
 * @param {object} p.bounds      - { min_lat, max_lat, min_lon, max_lon }
 */
export const fetchSpatialMetric = async ({ metric, modelName, variable, hour, bounds }) => {
  const params = new URLSearchParams({
    metric,
    model:    modelName,
    variable,
    min_lat:  bounds.min_lat,
    max_lat:  bounds.max_lat,
    min_lon:  bounds.min_lon,
    max_lon:  bounds.max_lon,
  });
  if (hour != null) params.set('hour', hour);
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
