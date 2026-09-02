import { withRun, whenRunReady } from './run';

const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:5000/api';

/**
 * Fetches per-hour ensemble mean and std for multiple models at a single point.
 *
 * @param {{ models: string[], lat: number, lon: number, hourMin: number, hourMax: number, variable: string }} params
 * @returns {Promise<Object>} e.g. { AIFS: [{hour, mean, std}, ...], GEFS: [...] }
 */
export async function fetchComparisonTimeseries({ models, lat, lon, hourMin, hourMax, variable }) {
  await whenRunReady();
  const response = await fetch(`${API_BASE}/compare/timeseries`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(withRun({
      models,
      lat,
      lon,
      hour_min: hourMin,
      hour_max: hourMax,
      variable,
    })),
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
  await whenRunReady();
  const response = await fetch(`${API_BASE}/compare/skill`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(withRun({
      models,
      lat,
      lon,
      hour_min: hourMin,
      hour_max: hourMax,
      variable,
    })),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.error || `compare/skill failed with status ${response.status}`);
  }

  return response.json();
}

/**
 * Fetches per-model categorical skill (CSI/POD/FAR/FSS) over lead time,
 * evaluated over a small neighbourhood around a point.
 *
 * @param {{ models: string[], lat: number, lon: number, hourMin: number, hourMax: number, variable: string, threshold: number, fssWindow: number }} params
 * @returns {Promise<{ models: Object, threshold_info: Object, fss_window: number, bbox: number[] }>}
 *   models is e.g. { AIFS: [{hour, csi, pod, far, fss, n_pts}], ... }
 */
export async function fetchComparisonCategorical({ models, lat, lon, hourMin, hourMax, variable, threshold, fssWindow, boxCells }) {
  await whenRunReady();
  const body = {
    models,
    lat,
    lon,
    hour_min: hourMin,
    hour_max: hourMax,
    variable,
    fss_window: fssWindow,
    // The verification box is separate from the FSS neighbourhood — widening
    // the neighbourhood must not silently change the sample CSI/POD/FAR use.
    ...(boxCells != null ? { box_cells: boxCells } : {}),
  };
  // Threshold units differ by variable: m/s for wind, mm/6h for precipitation.
  if (variable === 'wind') body.threshold_ms = threshold;
  else                     body.threshold_mm_6h = threshold;

  const response = await fetch(`${API_BASE}/compare/categorical`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(withRun(body)),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.error || `compare/categorical failed with status ${response.status}`);
  }

  return response.json();
}

/**
 * Fetches region-mean verification metrics for several models over one bbox.
 *
 * @param {{ models: string[], variable: string, bounds: object, hourMin: number,
 *           hourMax: number, threshold?: number, metrics?: string[] }} params
 *   bounds is { min_lat, max_lat, min_lon, max_lon } (camelCase also accepted).
 * @returns {Promise<{ models: Object, n_points: Object, n_cells: Object,
 *                     metrics: string[], threshold_info: Object, warnings: Object }>}
 *   models is e.g. { AIFS: { mae: 2.1, bias: -0.3, ... }, GEFS: {...} }
 */
export async function fetchComparisonRegionMetrics({ models, variable, bounds, hourMin, hourMax, threshold, metrics, fssWindow }) {
  await whenRunReady();
  const body = {
    models,
    variable,
    min_lat: bounds.min_lat ?? bounds.minLat,
    max_lat: bounds.max_lat ?? bounds.maxLat,
    min_lon: bounds.min_lon ?? bounds.minLon,
    max_lon: bounds.max_lon ?? bounds.maxLon,
    hour_min: hourMin,
    hour_max: hourMax,
    // Neighbourhood width for FSS. Independent of the bbox above.
    ...(fssWindow != null ? { fss_window: fssWindow } : {}),
  };
  if (metrics) body.metrics = metrics;
  // Threshold units differ by variable: m/s for wind, mm/6h for precipitation.
  if (threshold != null) {
    if (variable === 'wind') body.threshold_ms = threshold;
    else                     body.threshold_mm_6h = threshold;
  }

  const response = await fetch(`${API_BASE}/compare/region-metrics`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(withRun(body)),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.error || `compare/region-metrics failed with status ${response.status}`);
  }

  return response.json();
}

/**
 * Fetches a base64-encoded PNG of the per-cell metric difference (A − B)
 * between two models, on a diverging scale centred at 0.
 *
 * @param {{ modelA: string, modelB: string, metric: string, variable: string,
 *           bounds: object, hourMin: number, hourMax: number, threshold?: number }} params
 * @returns {Promise<{ image?: string, error?: string, n_common: number,
 *                     n_a: number, n_b: number, max_abs_diff?: number, mean_diff?: number }>}
 *   `error` (with n_common 0) means the two models share no grid cells.
 */
export async function fetchComparisonSpatialDiff({ modelA, modelB, metric, variable, bounds, hourMin, hourMax, threshold }) {
  await whenRunReady();
  const body = {
    model_a: modelA,
    model_b: modelB,
    metric,
    variable,
    min_lat: bounds.min_lat ?? bounds.minLat,
    max_lat: bounds.max_lat ?? bounds.maxLat,
    min_lon: bounds.min_lon ?? bounds.minLon,
    max_lon: bounds.max_lon ?? bounds.maxLon,
    hour_min: hourMin,
    hour_max: hourMax,
  };
  if (threshold != null) {
    if (variable === 'wind') body.threshold_ms = threshold;
    else                     body.threshold_mm_6h = threshold;
  }

  const response = await fetch(`${API_BASE}/compare/spatial-diff`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(withRun(body)),
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `compare/spatial-diff failed with status ${response.status}`);
  }
  return data;
}

/**
 * Fetches a base64-encoded PNG map of inter-model disagreement for a bounding
 * box and a single forecast hour.
 *
 * @param {{ models: string[], minLat: number, maxLat: number, minLon: number, maxLon: number, hour: number, variable: string }} params
 * @returns {Promise<{ image: string, hour: number, n_models: number, n_points: number }>}
 */
export async function fetchSpatialAgreement({ models, minLat, maxLat, minLon, maxLon, hour, variable }) {
  await whenRunReady();
  const response = await fetch(`${API_BASE}/compare/spatial-agreement`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(withRun({
      models,
      min_lat: minLat,
      max_lat: maxLat,
      min_lon: minLon,
      max_lon: maxLon,
      hour,
      variable,
    })),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.error || `compare/spatial-agreement failed with status ${response.status}`);
  }

  return response.json();
}
