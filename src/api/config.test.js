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
import {
  fetchConfig, __resetConfigCache, metricKeysFrom, unitFrom, metricsFrom,
} from './config';

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


describe('metricsFrom — the selector S4 asks for', () => {
  // Deliberately NOT in the backend's order, and carrying presentation the
  // server does not serve, so a merge that simply used one side is visible.
  const LOCAL = [
    { key: 'mae', label: 'Mean Absolute Error', description: 'MAE',
      requiresHour: false, requiresThreshold: false, colorFn: () => '#fff' },
    { key: 'csi', label: 'Critical Success Index', description: 'CSI',
      requiresHour: false, requiresThreshold: true, colorFn: () => '#000' },
    { key: 'retired', label: 'A metric the backend no longer serves',
      description: 'gone', requiresHour: false, requiresThreshold: false },
  ];

  it('falls back to the local list when the config is unavailable', () => {
    // The soft-dependency promise: no server, no change in behaviour. Identity
    // rather than equality, so a "fallback" that rebuilt the list and lost the
    // colour functions on the way would not pass.
    expect(metricsFrom(null, LOCAL)).toBe(LOCAL);
    expect(metricsFrom({}, LOCAL)).toBe(LOCAL);
  });

  it('keeps presentation that only the frontend has', () => {
    const out = metricsFrom(PAYLOAD, LOCAL);
    const mae = out.find((m) => m.key === 'mae');
    expect(mae.label).toBe('Mean Absolute Error');
    expect(mae.description).toBe('MAE');
    expect(mae.colorFn()).toBe('#fff');
  });

  it('drops a metric the backend does not serve', () => {
    // Offering one the backend will refuse is worse than not offering it: the
    // user picks it and gets an error where they expected a map.
    expect(metricsFrom(PAYLOAD, LOCAL).map((m) => m.key)).not.toContain('retired');
  });

  it('offers a metric the frontend has never heard of', () => {
    // S4's exit criterion, as one assertion: adding a metric to the backend
    // registry puts it in the selector with no frontend change at all.
    const served = {
      ...PAYLOAD,
      metrics: {
        ...PAYLOAD.metrics,
        pod: { requires_hour: false, requires_threshold: true },
      },
    };
    const pod = metricsFrom(served, LOCAL).find((m) => m.key === 'pod');
    expect(pod).toBeDefined();
    expect(pod.requiresThreshold).toBe(true);
  });

  it('labels an unknown metric by its key rather than inventing prose', () => {
    const served = { ...PAYLOAD, metrics: { ...PAYLOAD.metrics, pod: {} } };
    const pod = metricsFrom(served, LOCAL).find((m) => m.key === 'pod');
    expect(pod.label).toBe('pod');
    expect(pod.description).toBe('');
  });

  it('lets the server decide what a metric requires', () => {
    // These choose which controls the panel shows and which parameters the
    // request carries, so a local copy that disagreed would build a request the
    // backend rejects. test_config_endpoint.py pins that they agree today; this
    // pins which one wins if they ever stop.
    const served = {
      ...PAYLOAD,
      metrics: { ...PAYLOAD.metrics, mae: { requires_hour: true, requires_threshold: false } },
    };
    expect(metricsFrom(served, LOCAL).find((m) => m.key === 'mae').requiresHour).toBe(true);
    // ...and the local value is what it disagreed with.
    expect(LOCAL.find((m) => m.key === 'mae').requiresHour).toBe(false);
  });

  it('keeps the curated order and puts unknown metrics last', () => {
    // METRIC_CONFIG's order is a UI decision — spread, then continuous, then
    // categorical. Nothing about the backend's registry order is.
    const served = {
      ...PAYLOAD,
      metrics: { zzz: {}, ...PAYLOAD.metrics },      // first in the server's order
    };
    expect(metricsFrom(served, LOCAL).map((m) => m.key)).toEqual(['mae', 'csi', 'zzz']);
  });

  it('does not mutate the local list', () => {
    const before = JSON.stringify(LOCAL.map((m) => [m.key, m.requiresHour]));
    metricsFrom({ ...PAYLOAD, metrics: { mae: { requires_hour: true } } }, LOCAL);
    expect(JSON.stringify(LOCAL.map((m) => [m.key, m.requiresHour]))).toBe(before);
  });
});
