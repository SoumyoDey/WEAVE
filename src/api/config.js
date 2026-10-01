/**
 * The backend's own account of which metrics exist and what they need.
 *
 * `SYSTEM_DESIGN_PLAN.md` S4 asks for one backend source of truth exposed to
 * the frontend, so that adding a model, variable or metric is a single-place
 * change. `/api/config` is that source; this is the client for it.
 *
 * **What this does and does not replace.** `constants.js` keeps the
 * presentation — labels, descriptions, colour functions, legends and the band
 * edges with their calibration rationale. Those are genuinely frontend
 * concerns, and the server-rendered PNG deliberately uses a different rendering
 * (a continuous `Normalize` where the overlay uses discrete bands), so pulling
 * colours through here would make the two agree by breaking one of them.
 *
 * What moves is the *facts*: which metrics exist, which need a single lead time
 * rather than a range, which need a threshold, which variables exist and in
 * what unit. Those were restated in `constants.js` and nothing checked the two
 * agreed — `Data/test_config_endpoint.py` now does, in both directions, and
 * fails naming the metric that drifted.
 *
 * **Why this is a soft dependency.** The app must render if `/api/config` is
 * slow or unreachable, so every reader falls back to the local constants and
 * the UI is never blocked on this call. The endpoint touches no database, so
 * the realistic failure is a network one rather than a busy pool.
 */
import { API_BASE } from './base';

let cached = null;
let inFlight = null;

/**
 * Fetch the config once per page load.
 *
 * Deduplicated rather than merely cached: several components may ask during the
 * first render, and three identical requests at startup is the kind of thing
 * that only shows up under a slow connection.
 */
export const fetchConfig = async () => {
  if (cached) return cached;
  if (inFlight) return inFlight;
  inFlight = fetch(`${API_BASE}/config`)
    .then((r) => {
      if (!r.ok) throw new Error(`config: HTTP ${r.status}`);
      return r.json();
    })
    .then((data) => {
      cached = data;
      inFlight = null;
      return data;
    })
    .catch((err) => {
      inFlight = null;
      // Not fatal. The caller falls back to the local constants, which are
      // pinned against this endpoint by a test, so they are correct unless
      // someone shipped a drift that CI would have caught.
      console.warn('config unavailable, using local constants:', err.message);
      return null;
    });
  return inFlight;
};

/** Reset between tests. */
export const __resetConfigCache = () => {
  cached = null;
  inFlight = null;
};

/**
 * Metric keys the backend will actually serve, or `null` when unknown.
 *
 * `null` means "could not ask" and is deliberately distinguishable from `[]`,
 * which would mean "the backend serves no metrics". A caller that conflates
 * them hides an empty selector behind a network error.
 */
export const metricKeysFrom = (config) =>
  config && config.metrics ? Object.keys(config.metrics) : null;

/** The unit for a variable, from the server, falling back to `null`. */
export const unitFrom = (config, variable) =>
  config && config.variables && config.variables[variable]
    ? config.variables[variable].unit
    : null;

export default fetchConfig;
