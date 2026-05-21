const API_BASE = 'http://localhost:5000/api';

/**
 * Fetches per-hour ensemble mean and std for multiple models at a single point.
 *
 * @param {{ models: string[], lat: number, lon: number, hourMin: number, hourMax: number, variable: string }} params
 * @returns {Promise<Object>} e.g. { AIFS: [{hour, mean, std}, ...], GEFS: [...] }
 */
export async function fetchComparisonTimeseries({ models, lat, lon, hourMin, hourMax, variable }) {
  const response = await fetch(`${API_BASE}/compare/timeseries`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      models,
      lat,
      lon,
      hour_min: hourMin,
      hour_max: hourMax,
      variable,
    }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.error || `compare/timeseries failed with status ${response.status}`);
  }

  return response.json();
}

/**
 * Fetches skill metrics (SSR, CRPS, Bias, MAE, RMSE) for multiple models
 * by matching forecasts against observations at the given point.
 *
 * @param {{ models: string[], lat: number, lon: number, hourMin: number, hourMax: number, variable: string }} params
 * @returns {Promise<{ models: Object, obs_hours: number[], obs_warning: string }>}
 */
export async function fetchComparisonSkill({ models, lat, lon, hourMin, hourMax, variable }) {
  const response = await fetch(`${API_BASE}/compare/skill`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      models,
      lat,
      lon,
      hour_min: hourMin,
      hour_max: hourMax,
      variable,
    }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.error || `compare/skill failed with status ${response.status}`);
  }

  return response.json();
}

/**
 * Fetches a base64-encoded PNG map of inter-model disagreement for a bounding
 * box and a single forecast hour.
 *
 * @param {{ models: string[], minLat: number, maxLat: number, minLon: number, maxLon: number, hour: number, variable: string }} params
 * @returns {Promise<{ image: string, hour: number, n_models: number, n_points: number }>}
 */
export async function fetchSpatialAgreement({ models, minLat, maxLat, minLon, maxLon, hour, variable }) {
  const response = await fetch(`${API_BASE}/compare/spatial-agreement`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      models,
      min_lat: minLat,
      max_lat: maxLat,
      min_lon: minLon,
      max_lon: maxLon,
      hour,
      variable,
    }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.error || `compare/spatial-agreement failed with status ${response.status}`);
  }

  return response.json();
}
