const BASE = 'http://localhost:5000/api';

/**
 * Fetches a single forecast field (mean / std / member).
 * Returns an array of point objects.
 */
export const fetchForecastData = async (modelName, variable, hour, member) => {
  const endpoint = variable === 'wind' ? 'wind-data' : 'forecast-data';
  const params   = new URLSearchParams({ model: modelName, variable, hour, member });
  const response = await fetch(`${BASE}/${endpoint}?${params}`);
  if (!response.ok) throw new Error(`API error: ${response.status}`);
  const data = await response.json();
  if (!Array.isArray(data) || data.length === 0) throw new Error('No data returned');
  return data;
};

/**
 * Fetches the full forecast time-series for a single lat/lon point.
 * Returns an array of objects with { hour, mean, std, p10, p25, p75, p90 }.
 */
export const fetchTimeseries = async (modelName, variable, lat, lon) => {
  const params = new URLSearchParams({ model: modelName, variable, lat, lon });
  const res    = await fetch(`${BASE}/point-timeseries?${params}`);
  return res.json();
};

/**
 * Fetches the spread-skill diagnostic for a single lat/lon point.
 * Returns { hours, correlation, n_cases, ... }.
 */
export const fetchSpreadSkill = async (modelName, variable, lat, lon) => {
  const params = new URLSearchParams({ model: modelName, variable, lat, lon });
  const res    = await fetch(`${BASE}/spread-skill?${params}`);
  return res.json();
};

/**
 * Fetches mean + std fields simultaneously.
 * Used by uncertainty / bivariate layer renderers.
 * Returns { meanData, stdData }.
 */
export const fetchUncertaintyPair = async (modelName, variable, hour) => {
  const endpoint = variable === 'wind' ? 'wind-data' : 'forecast-data';
  const mkParams = (member) =>
    new URLSearchParams({ model: modelName, variable, hour, member });
  const [resMean, resStd] = await Promise.all([
    fetch(`${BASE}/${endpoint}?${mkParams('mean')}`),
    fetch(`${BASE}/${endpoint}?${mkParams('std')}`),
  ]);
  const [meanData, stdData] = await Promise.all([resMean.json(), resStd.json()]);
  return { meanData, stdData };
};
