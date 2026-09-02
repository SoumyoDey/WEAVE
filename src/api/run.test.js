/**
 * The run the app names on every request.
 *
 * The backend refuses a missing `init_time` once more than one run is loaded, so
 * these pin the two properties that decide whether the app keeps working when
 * that happens: the value is attached to every request shape, and its absence
 * omits the key rather than sending null.
 */
import { setInitTime, getInitTime, withRun, runParams, withRunParam,
         whenRunReady, resetRun } from './run';

const RUN = '2025-09-08T00:00:00';

afterEach(() => resetRun());

describe('before /api/runs has answered', () => {
  it('reports no run', () => {
    expect(getInitTime()).toBeNull();
  });

  it('omits the key entirely rather than sending null', () => {
    // The distinction matters at the other end: absent means "resolve it for me
    // if unambiguous", while an explicit null is rejected as a malformed
    // timestamp. Sending null would break the single-run case that works today.
    const body = withRun({ models: ['AIFS'] });
    expect('init_time' in body).toBe(false);
    expect(body).toEqual({ models: ['AIFS'] });
    expect(runParams()).toEqual({});
  });

  it('leaves query params untouched', () => {
    const p = new URLSearchParams({ model: 'AIFS' });
    expect(withRunParam(p).toString()).toBe('model=AIFS');
  });
});

describe('once a run is set', () => {
  beforeEach(() => setInitTime(RUN));

  it('adds it to a POST body without disturbing the rest', () => {
    expect(withRun({ models: ['AIFS'], lat: 36 }))
      .toEqual({ models: ['AIFS'], lat: 36, init_time: RUN });
  });

  it('does not mutate the caller’s body', () => {
    const original = { models: ['AIFS'] };
    withRun(original);
    expect('init_time' in original).toBe(false);
  });

  it('adds it to query params', () => {
    const p = new URLSearchParams({ model: 'AIFS' });
    expect(withRunParam(p).get('init_time')).toBe(RUN);
    expect(runParams()).toEqual({ init_time: RUN });
  });

  it('mutates the params object, because callers pass it straight to fetch', () => {
    const p = new URLSearchParams();
    expect(withRunParam(p)).toBe(p);
  });
});

describe('clearing', () => {
  it('treats an empty string as no run', () => {
    // /api/runs returns latest: null on an empty database; a falsy value must
    // not become the literal string "null" in a query string.
    setInitTime('');
    expect(getInitTime()).toBeNull();
    expect(withRun({ a: 1 })).toEqual({ a: 1 });
  });

  it('treats undefined as no run', () => {
    setInitTime(RUN);
    setInitTime(undefined);
    expect(getInitTime()).toBeNull();
  });
});


describe('whenRunReady', () => {
  afterEach(() => { resetRun(); delete global.fetch; });

  it('resolves immediately once a run is known, without fetching', async () => {
    setInitTime(RUN);
    global.fetch = jest.fn();
    expect(await whenRunReady()).toBe(RUN);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('fetches /api/runs once however many callers await it', async () => {
    global.fetch = jest.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve({ latest: RUN, runs: [RUN] }),
    }));
    const [a, b, c] = await Promise.all([whenRunReady(), whenRunReady(), whenRunReady()]);
    expect([a, b, c]).toEqual([RUN, RUN, RUN]);
    // The whole point of caching the promise: three concurrent callers, one
    // request. Without it every api function would issue its own.
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(getInitTime()).toBe(RUN);
  });

  it('resolves to null instead of rejecting when /api/runs fails', async () => {
    // A broken /api/runs must degrade to the previous behaviour — requests go
    // out without a run and a single-run backend still answers — rather than
    // taking down every fetch in the app.
    global.fetch = jest.fn(() => Promise.reject(new Error('offline')));
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    expect(await whenRunReady()).toBeNull();
    expect(withRun({ a: 1 })).toEqual({ a: 1 });
    console.warn.mockRestore();
  });

  it('resolves to null on a non-ok response', async () => {
    global.fetch = jest.fn(() => Promise.resolve({ ok: false, status: 500 }));
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    expect(await whenRunReady()).toBeNull();
    console.warn.mockRestore();
  });
});
