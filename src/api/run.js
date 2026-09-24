import { API_BASE as BASE } from './base';

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
 * **The selector is now being built (2026-09-22), and this is how the warning
 * that used to be here was answered.** It said: move the value into React state
 * and let `withRun`/`withRunParam` take it as an argument. Half of that was
 * right and half was the wrong fix.
 *
 * Right: React state owns the selection. `RunProvider` holds it, and calls
 * `setInitTime` so this module stays the one place that knows the wire format.
 *
 * Wrong: threading the value into `withRun` at every call site. There are 53 of
 * them across four api modules, and not one component reads the value for
 * itself — they would all just forward it. That is the prop-drilling this
 * module was created to avoid, and it would not have fixed the actual bug
 * anyway.
 *
 * Because the real bug is not *where the value lives*. It is that a request
 * issued under run A can resolve after a switch to run B and paint A's numbers
 * under B's label. Moving the value to a prop does not stop that — the fetch
 * already captured the old value when it left. What stops it is knowing which
 * run a response belongs to, so `runEpoch` increments on every change and
 * callers check `isCurrentRun(epoch)` before committing a result. Threading a
 * prop would have moved the value and left the race.
 */

// How long to wait for /api/runs before giving up and sending requests without
// a run. A single-run backend still answers those, so a slow or broken /api/runs
// degrades to the previous behaviour rather than an app that renders nothing.
const BOOTSTRAP_TIMEOUT_MS = 5000;

let currentInitTime = null;
let bootstrap = null;
let runsPromise = null;

// Bumped every time the selection actually changes. A response tagged with a
// stale epoch is from a run nobody is looking at any more.
let runEpoch = 0;

/**
 * Set the run every subsequent request will name.
 *
 * Only bumps the epoch when the value really changes, so a provider re-render
 * that sets the same run does not invalidate requests that are legitimately in
 * flight for it.
 */
export const setInitTime = (initTime) => {
  const next = initTime || null;
  if (next === currentInitTime) return;
  currentInitTime = next;
  runEpoch += 1;
};

/** The run currently selected, or null before /api/runs has answered. */
export const getInitTime = () => currentInitTime;

/**
 * The current epoch. Capture this *before* a fetch, check it after.
 *
 *     const epoch = getRunEpoch();
 *     const data  = await fetchSomething();
 *     if (!isCurrentRun(epoch)) return;   // the run changed under us
 *     setState(data);
 *
 * Checking `getInitTime()` again instead would not be equivalent: switching
 * A → B → A lands back on the same value while the in-flight A response is
 * still wrong to commit, because the component has re-fetched since. A counter
 * does not have that blind spot.
 */
export const getRunEpoch = () => runEpoch;

/** Whether an epoch captured earlier is still the live one. */
export const isCurrentRun = (epoch) => epoch === runEpoch;

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
      const data = await fetchRuns();
      // Only default when nothing has chosen yet. A provider that resolved
      // first — from a URL, or a restored preference — must not be overridden
      // by the bootstrap arriving late and snapping back to `latest`.
      if (!currentInitTime) setInitTime(data?.latest);
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

/**
 * The full `/api/runs` payload, fetched once and shared.
 *
 * The selector and the bootstrap both need this, and they must not be two
 * fetches: the bootstrap exists to make request ordering a property of this
 * module, which a second independent fetch would undo. Memoised on the
 * promise, not the result, so concurrent callers during startup share one
 * request rather than racing.
 *
 * Rejects on failure, unlike `whenRunReady` — a selector wants to say "could
 * not load runs", where the api layer wants to degrade quietly. The memo is
 * cleared on failure so a retry is possible.
 */
export const fetchRuns = () => {
  if (runsPromise) return runsPromise;
  runsPromise = (async () => {
    const timeout = new Promise((resolve) =>
      setTimeout(() => resolve(null), BOOTSTRAP_TIMEOUT_MS));
    const res = await Promise.race([fetch(`${BASE}/runs`), timeout]);
    if (!res) throw new Error('/api/runs: timed out');
    if (!res.ok) throw new Error(`/api/runs: ${res.status}`);
    return res.json();
  })();
  runsPromise.catch(() => { runsPromise = null; });
  return runsPromise;
};

/** Forget the resolved run, the bootstrap and the cached runs. For tests. */
export const resetRun = () => {
  currentInitTime = null;
  bootstrap = null;
  runsPromise = null;
  runEpoch = 0;
};

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
