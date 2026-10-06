/**
 * `fetchForecastHours` must never go out without a run.
 *
 * The timeline reads its steps from `/api/forecast-hours`, and the backend
 * refuses a missing `init_time` once more than one run is loaded — three are.
 * The first version of this fetcher built its query by hand and skipped the
 * api layer's two gating lines, so on every page load it fired before the run
 * had resolved, took a **400**, and then re-ran with the run and succeeded.
 *
 * Two doomed requests per load, self-correcting, and invisible anywhere except
 * the network panel. The 250 existing frontend tests all passed through it.
 * That is the same shape as the cyclone tab's stale-init 404s — an effect
 * firing before its dependency resolves — and the same reason it survived: the
 * final state was right.
 *
 * So these assert a property of **the request**, not of the returned value.
 */
import { setInitTime, resetRun } from './run';
import { fetchForecastHours } from './forecastApi';

const RUN = '2025-09-16T00:00:00';

const okJson = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });

beforeEach(() => {
  global.fetch = jest.fn(() => okJson({ hours: [0, 3, 6], count: 3 }));
});
afterEach(() => { resetRun(); jest.restoreAllMocks(); });

/** Every URL `fetch` was called with. */
const urls = () => global.fetch.mock.calls.map(([u]) => String(u));

describe('with a run resolved', () => {
  beforeEach(() => setInitTime(RUN));

  it('attaches init_time without being told to', async () => {
    await fetchForecastHours({ model: 'AIFS', variable: 'precipitation' });
    expect(urls()).toHaveLength(1);
    expect(urls()[0]).toContain(`init_time=${encodeURIComponent(RUN)}`);
  });

  it('never sends a request with no init_time', async () => {
    // The assertion that would have failed before the fix.
    await fetchForecastHours({ model: 'AIFS', variable: 'precipitation' });
    for (const u of urls()) expect(u).toMatch(/init_time=/);
  });

  it('honours an explicit initTime over the ambient run', async () => {
    const other = '2025-09-08T06:00:00';
    await fetchForecastHours({ model: 'GEFS', variable: 'wind_u_10m', initTime: other });
    expect(urls()[0]).toContain(encodeURIComponent(other));
    expect(urls()[0]).not.toContain(encodeURIComponent(RUN));
  });

  it('sends the stored variable name it was given, unaltered', async () => {
    // The endpoint takes `wind_u_10m`, not the UI's `wind`; the UI spelling
    // returns an empty list silently. The translation is the caller's job, so
    // this pins that the client does not "helpfully" rewrite it.
    await fetchForecastHours({ model: 'GEFS', variable: 'wind_u_10m' });
    expect(urls()[0]).toContain('variable=wind_u_10m');
  });

  it('throws on a non-ok response rather than returning undefined', async () => {
    global.fetch = jest.fn(() => Promise.resolve({ ok: false, status: 404 }));
    await expect(fetchForecastHours({ model: 'NOPE', variable: 'precipitation' }))
      .rejects.toThrow('404');
  });
});

describe('before /api/runs has answered', () => {
  it('waits for the run instead of firing without it', async () => {
    // `whenRunReady()` bootstraps by fetching /api/runs itself. Answer that,
    // then assert the forecast-hours request that follows carries the run —
    // i.e. nothing went out during the gap.
    global.fetch = jest.fn((url) => String(url).includes('/runs')
      ? okJson({ runs: [RUN], latest: RUN, detail: [], entries: [] })
      : okJson({ hours: [0, 6], count: 2 }));

    await fetchForecastHours({ model: 'AIFS', variable: 'precipitation' });

    const hoursCalls = urls().filter((u) => u.includes('/forecast-hours'));
    expect(hoursCalls).toHaveLength(1);
    expect(hoursCalls[0]).toContain('init_time=');
  });
});
