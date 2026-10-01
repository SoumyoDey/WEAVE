/**
 * Tests for the `/api/config` client.
 *
 * The behaviour worth pinning is not that it fetches — it is what happens when
 * it cannot. `SYSTEM_DESIGN_PLAN.md` S4's endpoint describes the app; an app
 * that refuses to render because its description is unavailable has traded a
 * cosmetic problem for an outage. So the failure path is tested first.
 *
 * `null` versus `[]` gets its own test because conflating them is how a network
 * error becomes an empty metric selector with no explanation — the same shape
 * as the "honest empty" distinction the observation-coverage work settled.
 */
import { fetchConfig, __resetConfigCache, metricKeysFrom, unitFrom } from './config';

const PAYLOAD = {
  variables: { precipitation: { unit: 'mm/h' }, wind: { unit: 'm/s' } },
  metrics: {
    mae: { requires_hour: false, requires_threshold: false, unit_sensitive: true },
    csi: { requires_hour: false, requires_threshold: true, unit_sensitive: false },
  },
  region_metrics: ['mae', 'fss'],
  verification_window_hours: 6,
};

beforeEach(() => {
  __resetConfigCache();
  jest.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
  jest.restoreAllMocks();
  delete global.fetch;
});

const okOnce = (body) =>
  jest.fn().mockResolvedValue({ ok: true, json: async () => body });

describe('fetchConfig', () => {
  it('returns the payload', async () => {
    global.fetch = okOnce(PAYLOAD);
    await expect(fetchConfig()).resolves.toEqual(PAYLOAD);
  });

  it('fetches once across repeated calls', async () => {
    global.fetch = okOnce(PAYLOAD);
    await fetchConfig();
    await fetchConfig();
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it('deduplicates concurrent callers', async () => {
    // Several components can ask during the first render. Caching the resolved
    // value is not enough — the second call arrives before the first resolves.
    global.fetch = okOnce(PAYLOAD);
    await Promise.all([fetchConfig(), fetchConfig(), fetchConfig()]);
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it('resolves null rather than throwing when the request fails', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('offline'));
    await expect(fetchConfig()).resolves.toBeNull();
  });

  it('resolves null on a non-OK response', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 503 });
    await expect(fetchConfig()).resolves.toBeNull();
  });

  it('can retry after a failure', async () => {
    // A failed attempt must not poison the cache: the API coming back up
    // should not need a page reload.
    global.fetch = jest.fn().mockRejectedValue(new Error('offline'));
    expect(await fetchConfig()).toBeNull();
    global.fetch = okOnce(PAYLOAD);
    expect(await fetchConfig()).toEqual(PAYLOAD);
  });
});

describe('readers', () => {
  it('reads metric keys', () => {
    expect(metricKeysFrom(PAYLOAD).sort()).toEqual(['csi', 'mae']);
  });

  it('distinguishes "could not ask" from "nothing to offer"', () => {
    // null means the config is unavailable and the caller should fall back to
    // the local constants. [] would mean the backend serves no metrics at all,
    // which should show as an empty selector rather than a silent fallback.
    expect(metricKeysFrom(null)).toBeNull();
    expect(metricKeysFrom({ metrics: {} })).toEqual([]);
  });

  it('reads units, and falls back to null for an unknown variable', () => {
    expect(unitFrom(PAYLOAD, 'wind')).toBe('m/s');
    expect(unitFrom(PAYLOAD, 'precipitation')).toBe('mm/h');
    expect(unitFrom(PAYLOAD, 'humidity')).toBeNull();
    expect(unitFrom(null, 'wind')).toBeNull();
  });
});
