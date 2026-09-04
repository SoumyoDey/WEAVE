import { withRunParam, whenRunReady } from './run';

const BASE = process.env.REACT_APP_API_URL || 'http://localhost:5000/api';

/**
 * Fetches a single forecast field (mean / std / member).
 * Returns an array of point objects.
 */
export const fetchForecastData = async (modelName, variable, hour, member) => {
  await whenRunReady();
  const endpoint = variable === 'wind' ? 'wind-data' : 'forecast-data';
  const params   = new URLSearchParams({ model: modelName, variable, hour, member });
  const response = await fetch(`${BASE}/${endpoint}?${withRunParam(params)}`);
  if (!response.ok) throw new Error(`API error: ${response.status}`);

  // These endpoints cap how many grid cells they return, because the native
  // grid is a property of the loaded data and nothing in the request bounds it.
  // The cap is inert on the current data — it exists for a finer model or a
  // wider domain — but a shortened map looks complete, so say something rather
  // than draw a partial field silently. If this ever fires in practice it
  // belongs in the UI, not the console.
  if (response.headers.get('X-Truncated') === 'true') {
    // No "of M" here: the server cannot report a true total cheaply, and an
    // understated one would make the loss look negligible.
    console.warn(
      `${endpoint}: returned ${response.headers.get('X-Row-Count')} grid cells, `
      + `which is the server limit (${response.headers.get('X-Row-Limit')}). `
      + `There are more — the map is incomplete. Narrow the request or raise `
      + `POINT_LIST_MAX_CELLS.`);
  }

  const data = await response.json();
  // An empty array is a valid response (e.g. an out-of-range member/hour) —
  // it's not an error, so callers can distinguish it from a thrown failure.
  return Array.isArray(data) ? data : [];
};

/**
 * Fetches the full forecast time-series for a single lat/lon point.
 * Returns an array of objects with { hour, mean, std, p10, p25, p75, p90 }.
 */
export const fetchTimeseries = async (modelName, variable, lat, lon) => {
  await whenRunReady();
  const params = new URLSearchParams({ model: modelName, variable, lat, lon });
  const res    = await fetch(`${BASE}/point-timeseries?${withRunParam(params)}`);
  return res.json();
};

/**
 * Fetches the spread-skill diagnostic for a single lat/lon point.
 * Returns { hours, correlation, n_cases, ... }.
 */
export const fetchSpreadSkill = async (modelName, variable, lat, lon) => {
  await whenRunReady();
  const params = new URLSearchParams({ model: modelName, variable, lat, lon });
  const res    = await fetch(`${BASE}/spread-skill?${withRunParam(params)}`);
  return res.json();
};

/**
 * Fetches how far the observation record reaches, so the interface can say where
 * verification stops instead of leaving the user to infer it from an empty panel.
 * Returns { init_time, obs_start, obs_end, record_end_lead_hours,
 *           last_verifiable_hour, window_hours, source }.
 */
export const fetchObservationCoverage = async (modelName, variable) => {
  await whenRunReady();
  const params = new URLSearchParams({ model: modelName, variable });
  const res    = await fetch(`${BASE}/observation-coverage?${withRunParam(params)}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
};

/**
 * Fetches mean + std fields simultaneously.
 * Used by uncertainty / bivariate layer renderers.
 * Returns { meanData, stdData }.
 */
export const fetchUncertaintyPair = async (modelName, variable, hour) => {
  await whenRunReady();
  const endpoint = variable === 'wind' ? 'wind-data' : 'forecast-data';
  const mkParams = (member) =>
    new URLSearchParams({ model: modelName, variable, hour, member });
  const [resMean, resStd] = await Promise.all([
    fetch(`${BASE}/${endpoint}?${withRunParam(mkParams('mean'))}`),
    fetch(`${BASE}/${endpoint}?${withRunParam(mkParams('std'))}`),
  ]);
  const [meanData, stdData] = await Promise.all([resMean.json(), resStd.json()]);
  return { meanData, stdData };
};

/**
 * What forecast data is loaded: which runs, per model and variable.
 *
 * Returns { runs: [iso, ...], latest: iso|null, detail: [...], entries: [...] }.
 * Deliberately does NOT carry init_time itself — it is the endpoint that tells
 * you what the valid values are.
 */
export const fetchRuns = async () => {
  // Deliberately NOT gated on whenRunReady(): this is the endpoint that answers
  // the question, and run.js does its own bare fetch of it during bootstrap.
  // Gating here would just delay it behind itself.
  const res = await fetch(`${BASE}/runs`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
};
