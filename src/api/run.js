/**
 * Which forecast run the app is asking about.
 *
 * Every scored endpoint reads the regridded tables, and those rows are keyed by
 * `init_time` as of the phase-1 migration. The backend resolves a missing
 * `init_time` only while exactly one run is loaded; the moment a second appears
 * it refuses rather than silently picking the newest. So the app has to say
 * which run it means, and it has to say it on every request.
 *
 * This module owns both the value and the one fetch that discovers it, because
 * the two cannot be separated without a race. An earlier version had App.js
 * fetch `/api/runs` in an effect and call `setInitTime`; the network log showed
 * `observation-coverage` and `forecast-data` requests going out *before* that
 * resolved, with no `init_time`. Harmless while one run is loaded — the backend
 * falls back — but with two runs those first-paint requests would every one 400,
 * and the app would render errors until something happened to re-fetch. So
 * `whenRunReady()` is awaited by the api functions instead, which makes the
 * ordering a property of the module rather than of effect scheduling.
 *
 * It is module state rather than React state, deliberately and with a limit.
 * The alternative is threading one value from App through every tab, panel and
 * layer into all nineteen fetch sites — a prop no component reads for itself and
 * only forwards. Keeping it beside `API_BASE`, which is already module scope,
 * means the api layer stays the only place that knows the wire format.
 *
 * The limit: this works because the value is set once and never changes. **A
 * real run selector must not build on it** — switching runs needs re-fetches and
 * cache invalidation, which is React state's job, and mutable module state would
 * let a stale request resolve after the switch and paint one run's numbers under
 * another run's label. When that selector is built, move the value into state or
 * context and let `withRun`/`withRunParams` take it as an argument.
 */
const BASE = process.env.REACT_APP_API_URL || 'http://localhost:5000/api';

// How long to wait for /api/runs before giving up and sending requests without
// a run. A single-run backend still answers those, so a slow or broken /api/runs
// degrades to the previous behaviour rather than an app that renders nothing.
const BOOTSTRAP_TIMEOUT_MS = 5000;

let currentInitTime = null;
let bootstrap = null;

/** Set the run every subsequent request will name. */
export const setInitTime = (initTime) => { currentInitTime = initTime || null; };

/** The run currently selected, or null before /api/runs has answered. */
export const getInitTime = () => currentInitTime;

/**
 * Resolve the run once, and hand every later caller the same promise.
 *
 * Never rejects: a failure here must not take the app down with it, so it
 * resolves to null and requests go out unqualified.
 */
export const whenRunReady = () => {
  if (currentInitTime) return Promise.resolve(currentInitTime);
  if (bootstrap) return bootstrap;
  bootstrap = (async () => {
    try {
      const timeout = new Promise((resolve) =>
        setTimeout(() => resolve(null), BOOTSTRAP_TIMEOUT_MS));
      const res = await Promise.race([fetch(`${BASE}/runs`), timeout]);
      if (!res || !res.ok) throw new Error(`/api/runs: ${res ? res.status : 'timeout'}`);
      const data = await res.json();
      setInitTime(data?.latest);
    } catch (err) {
      // Worth a line: a two-run database failing every scored request is
      // traceable to exactly this.
      console.warn('Could not resolve the forecast run; requests will omit '
                   + 'init_time and will fail if more than one run is loaded.', err);
    }
    return currentInitTime;
  })();
  return bootstrap;
};

/** Forget the resolved run and the in-flight bootstrap. For tests. */
export const resetRun = () => { currentInitTime = null; bootstrap = null; };

/**
 * A POST body with `init_time` added.
 *
 * Omits the key entirely when no run is known, rather than sending null: the
 * backend treats absent as "resolve it for me if unambiguous" and would reject
 * an explicit null as a malformed timestamp.
 */
export const withRun = (body) =>
  currentInitTime ? { ...body, init_time: currentInitTime } : body;

/** The same, as a plain object for spreading into a query. */
export const runParams = () =>
  currentInitTime ? { init_time: currentInitTime } : {};

/**
 * Add `init_time` to an existing URLSearchParams in place, and return it.
 * Mutating is what the call sites want — they build params then hand them
 * straight to fetch.
 */
export const withRunParam = (params) => {
  if (currentInitTime) params.set('init_time', currentInitTime);
  return params;
};
