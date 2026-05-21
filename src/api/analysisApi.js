const API_BASE = 'http://localhost:5000/api';

/**
 * Fetches categorical verification metrics (CSI, POD, FAR, FBI, Brier Score,
 * Composite Confidence) for a single model at a point, matched against observations.
 *
 * Precipitation threshold is expressed in mm/6h convention; the backend converts
 * internally to mm/h before comparison so results are accumulation-period-aware.
 *
 * @param {{
 *   model: string,
 *   variable: string,
 *   lat: number,
 *   lon: number,
 *   thresholdMm6h: number,
 *   hourMin: number,
 *   hourMax: number
 * }} params
 *
 * @returns {Promise<{
 *   hours: Array<{hour, is_fcst, is_obs, p_event, mean_rate, obs_rate}>,
 *   summary: {
 *     hits, misses, false_alarms, correct_neg,
 *     pod, far, fbi, csi,
 *     brier_score, composite_confidence
 *   },
 *   obs_hours: number[],
 *   obs_warning: string,
 *   threshold_info: { threshold_mm_6h, threshold_rate, accum_h, model }
 * }>}
 */
export async function fetchCategoricalMetrics({
  model,
  variable,
  lat,
  lon,
  thresholdMm6h,
  hourMin,
  hourMax,
}) {
  const response = await fetch(`${API_BASE}/categorical-metrics`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      variable,
      lat,
      lon,
      threshold_mm_6h: thresholdMm6h,
      hour_min: hourMin,
      hour_max: hourMax,
    }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.error || `categorical-metrics failed with status ${response.status}`);
  }

  return response.json();
}
