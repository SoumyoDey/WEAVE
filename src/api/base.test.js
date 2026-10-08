/**
 * Where the API base resolves to, which is a security property rather than a
 * convenience one.
 *
 * `REACT_APP_API_URL` is baked into the bundle at build time, so if a
 * production build resolves to an absolute URL on another host, that address
 * ships to every browser in readable JavaScript and the reviewer deployment's
 * single password stops protecting the API — anyone who opens the bundle can
 * call it directly. See `REVIEW_DEPLOY_PREREQS.md` §1.
 *
 * So these pin the default per environment. `NODE_ENV` is read at module load,
 * which is why each case re-imports through `jest.isolateModules` rather than
 * asserting on one already-evaluated constant.
 */

const load = (env) => {
  const previousNodeEnv = process.env.NODE_ENV;
  const previousApiUrl = process.env.REACT_APP_API_URL;
  // NODE_ENV is read-only on the real `process.env` type under CRA's babel
  // transform, so assign through a cast-free indirection.
  Object.defineProperty(process.env, 'NODE_ENV', {
    value: env.NODE_ENV, configurable: true, writable: true,
  });
  if ('REACT_APP_API_URL' in env) {
    if (env.REACT_APP_API_URL === undefined) delete process.env.REACT_APP_API_URL;
    else process.env.REACT_APP_API_URL = env.REACT_APP_API_URL;
  }

  let resolved;
  jest.isolateModules(() => {
    // eslint-disable-next-line global-require
    resolved = require('./base').API_BASE;
  });

  Object.defineProperty(process.env, 'NODE_ENV', {
    value: previousNodeEnv, configurable: true, writable: true,
  });
  if (previousApiUrl === undefined) delete process.env.REACT_APP_API_URL;
  else process.env.REACT_APP_API_URL = previousApiUrl;
  return resolved;
};

describe('a production build', () => {
  it('defaults to same-origin /api, shipping no second origin', () => {
    expect(load({ NODE_ENV: 'production', REACT_APP_API_URL: undefined }))
      .toBe('/api');
  });

  it('never resolves to an absolute URL by default', () => {
    const base = load({ NODE_ENV: 'production', REACT_APP_API_URL: undefined });
    expect(base).not.toMatch(/^https?:\/\//);
    expect(base).not.toContain('localhost');
  });
});

describe('development', () => {
  it('keeps the absolute dev URL, because CRA serves the app on another port', () => {
    // Same-origin would resolve to the :3000 dev server, which has no API.
    //
    // This expected `http://localhost:5000/api` until 2026-10-08. The dev
    // server binds `0.0.0.0` — IPv4 only — while `localhost` resolves to `::1`
    // first, so every dev request began with a connection to an address
    // nothing was listening on, and when Chrome's fallback to IPv4 did not
    // happen it surfaced as `TypeError: Failed to fetch` with no server-side
    // log entry (`NEXT_STEPS.md` §66).
    expect(load({ NODE_ENV: 'development', REACT_APP_API_URL: undefined }))
      .toBe('http://127.0.0.1:5000/api');
  });

  it('uses a literal address, not a name that can resolve to two families', () => {
    // The point of the change, pinned separately from the exact string: any
    // hostname here reintroduces the race, because which family it tries first
    // is the resolver's choice and not ours.
    const base = load({ NODE_ENV: 'development', REACT_APP_API_URL: undefined });
    expect(base).not.toContain('localhost');
    expect(new URL(base).hostname).toMatch(/^\d+\.\d+\.\d+\.\d+$/);
  });
});

describe('an explicit REACT_APP_API_URL', () => {
  it('still wins, for a deliberately two-host deployment', () => {
    expect(load({
      NODE_ENV: 'production',
      REACT_APP_API_URL: 'https://api.example.com/api',
    })).toBe('https://api.example.com/api');
  });
});
