/**
 * How many requests one interaction makes.
 *
 * Every test in this repo asserts what a response *contains*. None asserted how
 * many went out, and that blind spot produced the same defect three times in
 * three commits:
 *
 *   §37  the cyclone tab asked for each new storm with the previous storm's
 *        initialisation, took a 404, then asked again correctly.
 *   §38  `fetchForecastHours` skipped `whenRunReady()`, fired before the run had
 *        resolved, took a 400, then fired again correctly.
 *   §38  the same effect then ran twice per load — once at mount with
 *        `selectedRun` null, once when it arrived — for one answer.
 *
 * All three self-corrected, so the screen was right and the suite was green
 * every time. Each was found by a human reading a network panel, which is not a
 * repeatable check. These tests are.
 *
 * **They assert counts and request shapes, never rendered output.** A test that
 * checked the slider ended up with the right steps passed against all three
 * defects — that was the whole problem.
 *
 * Deliberately tolerant about *which* extra requests the app makes: new
 * features will add endpoints, and a test that pins the total becomes a tax on
 * every change. It pins the endpoints whose call pattern has actually gone
 * wrong, and the invariant that no request leaves without a run.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

/**
 * Leaflet is stubbed because the map is not what this file measures, and a real
 * one in jsdom is actively in the way: `App.js` builds it inside a `setTimeout`,
 * so it lands after a test has unmounted and throws "Map container not found"
 * asynchronously — attributed to whichever test happens to be running. The
 * stub is deliberately dumb; anything that asserts on the map belongs in a file
 * that does not mock it.
 */
jest.mock('leaflet', () => {
  // **Plain functions, not `jest.fn`.** CRA's jest config sets
  // `resetMocks: true`, which clears every mock's implementation before each
  // test — including ones created inside a module factory, which runs once. So
  // `jest.fn(() => x)` here returns `x` in the first test and `undefined` in
  // every one after, and the symptom is a TypeError deep in `App.js` rather
  // than anything pointing at the mock. Cost an hour the first time.
  const noop = () => {};
  const chainable = () => {
    const o = {
      addTo: () => o, remove: noop, setStyle: () => o, setLatLng: () => o,
      bindTooltip: () => o, openTooltip: () => o, closeTooltip: () => o,
      clearLayers: () => o, addLayer: () => o, removeLayer: () => o,
      setOpacity: () => o, bringToFront: () => o,
      getContainer: () => ({ style: {}, appendChild: noop }),
    };
    return o;
  };
  const map = {
    setView() { return this; },
    fitBounds: noop, remove: noop, invalidateSize: noop,
    addLayer: noop, removeLayer: noop, on: noop, off: noop,
    getZoom: () => 6,
    getCenter: () => ({ lat: 37, lng: -82.5 }),
    getBounds: () => ({ getNorth: () => 40, getSouth: () => 34,
                        getEast: () => -78, getWest: () => -87 }),
    latLngToContainerPoint: () => ({ x: 0, y: 0 }),
    containerPointToLatLng: () => ({ lat: 37, lng: -82.5 }),
    getPanes: () => ({ overlayPane: { appendChild: noop } }),
    createPane: () => ({ style: {} }),
    getPane: () => ({ style: {}, appendChild: noop }),
    dragging: { enable: noop, disable: noop },
    getContainer: () => ({ style: {}, appendChild: noop }),
  };
  return {
    __esModule: true,
    default: {
      map: () => map,
      tileLayer: chainable,
      polyline: chainable,
      polygon: chainable,
      rectangle: chainable,
      circleMarker: chainable,
      layerGroup: chainable,
      point: (x, y) => ({ x, y }),
      latLngBounds: () => {
        const b = { isValid: () => true, extend: noop, pad: () => b };
        return b;
      },
      control: { zoom: () => ({ addTo: () => ({ getContainer: () => ({ style: {} }) }) }) },
    },
  };
});
import App from './App';
import { RunProvider } from './state/RunContext';
import { resetRun } from './api/run';

const RUN = '2025-09-16T00:00:00';
const OLDER = '2025-09-08T00:00:00';

/** `/api/runs`, in the shape `RunContext` actually reads. */
const runsPayload = () => {
  const variables = (hourMax) => [
    { variable: 'precipitation', hour_min: 6, hour_max: hourMax, export_divisor_h: 6 },
    { variable: 'wind_u_10m',    hour_min: 0, hour_max: hourMax, export_divisor_h: null },
    { variable: 'wind_v_10m',    hour_min: 0, hour_max: hourMax, export_divisor_h: null },
  ];
  const models = {
    AIFS: { n_members: 50, variables: variables(360) },
    GEFS: { n_members: 30, variables: variables(240) },
    UKMO: { n_members: 18, variables: variables(198) },
  };
  return {
    runs: [RUN, OLDER],
    latest: RUN,
    detail: [{ init_time: RUN, models, variables: ['precipitation', 'wind_u_10m', 'wind_v_10m'] },
             { init_time: OLDER, models, variables: ['precipitation', 'wind_u_10m', 'wind_v_10m'] }],
    entries: [],
  };
};

const HOURS = { AIFS: [6, 12, 18], GEFS: [3, 6, 9], UKMO: [0, 1, 2, 3] };

let calls;

/** Routes every endpoint App touches; records each URL. */
const installFetch = () => {
  calls = [];
  global.fetch = jest.fn((input) => {
    const url = String(input);
    calls.push(url);
    const ok = (body) => Promise.resolve({
      ok: true, status: 200, json: () => Promise.resolve(body),
    });
    if (url.includes('/api/runs'))            return ok(runsPayload());
    if (url.includes('/api/config'))          return ok({});
    if (url.includes('/api/forecast-hours')) {
      const m = /model=([A-Z]+)/.exec(url);
      return ok({ model: m?.[1], variable: 'precipitation', init_time: RUN,
                  hours: HOURS[m?.[1]] ?? [], count: (HOURS[m?.[1]] ?? []).length });
    }
    if (url.includes('/api/observation-coverage'))
      return ok({ last_verifiable_hour: 18, window_hours: 6 });
    if (url.includes('/api/forecast-data'))   return ok({ data: [] });
    if (url.includes('/api/cyclones'))        return ok({ runs: [], storms: [] });
    return ok({});
  });
};

const to = (fragment) => calls.filter((u) => u.includes(fragment));

const renderApp = () => render(<RunProvider><App /></RunProvider>);

beforeEach(() => { resetRun(); installFetch(); });
afterEach(() => { resetRun(); jest.restoreAllMocks(); });

const pause = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Wait until the app has stopped issuing requests.
 *
 * **Quiescence, not a fixed number of ticks.** The first version of this looped
 * eight times at 30 ms and stopped, which was enough when this file ran alone
 * and not enough under the full suite, where jest runs workers in parallel and
 * everything is slower. The result was a test that passed five times in
 * isolation and failed in `npm test` — the worst kind, because it teaches
 * people that a red run means nothing.
 *
 * This waits for `QUIET_MS` with no new request, twice over, up to `BUDGET_MS`.
 * Requiring two consecutive quiet windows matters: one is satisfied by the gap
 * between a response landing and the effect it triggers firing.
 */
const QUIET_MS = 80;
const BUDGET_MS = 4000;
const settle = async () => {
  await waitFor(() => expect(to('/api/runs').length).toBeGreaterThan(0));
  const deadline = Date.now() + BUDGET_MS;
  let quiet = 0;
  let last = calls.length;
  /* eslint-disable no-await-in-loop */
  while (Date.now() < deadline && quiet < 2) {
    await pause(QUIET_MS);
    quiet = calls.length === last ? quiet + 1 : 0;
    last = calls.length;
  }
  /* eslint-enable no-await-in-loop */
};

describe('no request leaves without a run', () => {
  it('every run-scoped request carries init_time', async () => {
    renderApp();
    await settle();

    // `/api/runs` and `/api/config` are the two that legitimately precede the
    // run — /api/runs is the endpoint that answers the question, and config is
    // not run-scoped. Everything else must name one.
    const unqualified = calls.filter((u) =>
      u.includes('/api/')
      && !u.includes('/api/runs')
      && !u.includes('/api/config')
      && !u.includes('/api/cyclones')
      && !u.includes('init_time='));
    expect(unqualified).toEqual([]);
  });

  it('forecast-hours never fires before the run resolves', async () => {
    // The §38 defect: it fired unqualified, took a 400, then refired. The
    // request that 400ed looked exactly like this.
    renderApp();
    await settle();
    for (const u of to('/api/forecast-hours')) expect(u).toMatch(/init_time=/);
  });
});

/**
 * These counts are PRODUCTION counts, and that is load-bearing.
 *
 * `src/index.js` wraps the app in `<React.StrictMode>`, which deliberately
 * invokes every effect twice in development to surface effects that are not
 * idempotent. `renderApp` here does not wrap in StrictMode — RTL's `render`
 * mounts what it is given — so one effect run is one request, and "exactly one"
 * means what it says.
 *
 * **Get this wrong in either direction and the file is worthless.** Wrapping in
 * StrictMode would double every expected count, so the numbers below would have
 * to be 2, and a genuine duplicate-fetch defect would then be indistinguishable
 * from the doubling. Leaving it out, as here, means these numbers do not match
 * what a developer sees in a dev-server network panel — which is a feature, not
 * a discrepancy to reconcile.
 *
 * Observed on 2026-10-06: in the dev server `/api/cyclones` fires twice per
 * load while `/api/forecast-hours` fires once. That is not a defect in one and
 * not the other. It is StrictMode doubling both, with `forecast-hours` absorbing
 * its second run in the `if (!selectedRun) return;` guard — confirmed by
 * disabling StrictMode, where `/api/cyclones` drops to one. The same reasoning
 * also explains why `forecast-hours` measured *three* before that guard: two
 * doubled mounts plus one when the run arrived.
 *
 * So when these tests disagree with a dev-server network panel, suspect
 * StrictMode before suspecting either. And a future version of this file that
 * exercises the Cyclones tab must account for it: `/api/cyclones` would trip
 * the duplicate-URL assertion below under StrictMode and be perfectly correct.
 */
describe('one answer, one request', () => {
  it('fetches forecast-hours once for the initial selection', async () => {
    // Was three in the dev server and two in production: the effect ran at
    // mount with `selectedRun` still null and again when it arrived.
    renderApp();
    await settle();
    expect(to('/api/forecast-hours')).toHaveLength(1);
  });

  it('fetches once more when the model changes, not twice', async () => {
    renderApp();
    await settle();
    const before = to('/api/forecast-hours').length;

    fireEvent.click(screen.getByRole('button', { name: 'Controls' }));
    fireEvent.click(await screen.findByRole('button', { name: /UKMO/ }));

    // Wait for the request to appear before waiting for quiet, or a slow run
    // settles during the gap before it is issued and reads zero added — which
    // is how the first version of this test flaked only in the full suite.
    await waitFor(() =>
      expect(to('/api/forecast-hours').length).toBeGreaterThan(before));
    await settle();

    const added = to('/api/forecast-hours').slice(before);
    expect(added).toHaveLength(1);
    expect(added[0]).toContain('model=UKMO');
  });

  it('asks for no duplicate URLs at all', async () => {
    // The general form of the defect, independent of which endpoint. Two
    // identical URLs in one settled load means an effect ran twice for one
    // answer, whatever the cause.
    renderApp();
    await settle();
    const api = calls.filter((u) => u.includes('/api/'));
    const seen = new Set();
    const dupes = api.filter((u) => (seen.has(u) ? true : (seen.add(u), false)));
    expect(dupes).toEqual([]);
  });
});
