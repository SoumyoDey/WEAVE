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

/**
 * The metric list to render, with the server deciding *which* and the local
 * constants deciding *how each looks*.
 *
 * This is S4's exit criterion made real: adding a metric to
 * `SPATIAL_METRIC_REGISTRY` makes it appear in the selector without a frontend
 * change. Until now the selector mapped over `METRIC_CONFIG`, so a metric the
 * backend served was invisible until someone also edited `constants.js` — the
 * two-place change S4 exists to remove.
 *
 * Three rules, and the second and third are the ones worth stating:
 *
 * 1. **The server is the inventory.** A metric it does not serve is dropped,
 *    even if `constants.js` still describes it. Offering a metric the backend
 *    will refuse is worse than not offering it: the user picks it and gets an
 *    error instead of a map.
 * 2. **The server owns `requires_hour` and `requires_threshold`.** These decide
 *    which controls the panel shows and which parameters the request carries,
 *    so a local copy that disagreed would send a request the backend rejects.
 *    `Data/test_config_endpoint.py` pins that the two agree today; this makes
 *    the server's answer the one that renders, so a future drift is invisible
 *    to the user rather than broken for them.
 * 3. **Local ordering is kept**, and metrics the frontend has never heard of go
 *    at the end. The order in `METRIC_CONFIG` is curated — spread metrics, then
 *    continuous errors, then categorical — and nothing about the backend's
 *    registry order is a UI decision. A new metric appearing last, labelled by
 *    its key, is the honest default: it works, and it looks unfinished until
 *    someone gives it a label and a colour scale, which is accurate.
 *
 * Returns `local` untouched when `config` is null, which is the soft-dependency
 * promise: no server, no change in behaviour.
 */
export const metricsFrom = (config, local) => {
  const served = config && config.metrics;
  if (!served) return local;

  const fromServer = (key, cfg) => ({
    requiresHour:      !!cfg.requires_hour,
    requiresThreshold: !!cfg.requires_threshold,
  });

  const known = local
    .filter((m) => served[m.key])
    .map((m) => ({ ...m, ...fromServer(m.key, served[m.key]) }));

  const describedLocally = new Set(local.map((m) => m.key));
  const novel = Object.keys(served)
    .filter((key) => !describedLocally.has(key))
    .map((key) => ({
      key,
      // No invented prose. The key is what the backend calls it, and a label
      // that says so beats a guess that reads like a decision someone made.
      label:       key,
      shortLabel:  key,
      description: '',
      ...fromServer(key, served[key]),
    }));

  return [...known, ...novel];
};

export default fetchConfig;
