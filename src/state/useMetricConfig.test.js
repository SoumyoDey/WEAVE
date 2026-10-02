/**
 * Tests for the hook that renders the metric selector from `/api/config`.
 *
 * What matters here is the *timing*, not the merge — `metricsFrom` is tested
 * directly in `api/config.test.js`. The app must render immediately with the
 * local constants and upgrade when the server answers, because the alternative
 * is a selector that is empty or absent until a network call returns. An app
 * that will not render because its own description is unavailable has traded a
 * cosmetic problem for an outage.
 *
 * The "stays local when the call fails" test is the one that would catch the
 * worst regression: `fetchConfig` resolves to `null` rather than rejecting, so
 * a careless `setMetrics(metricsFrom(cfg, local))` without the null check would
 * replace a working list with whatever the merge made of nothing.
 */
import { renderHook, waitFor } from '@testing-library/react';

import { useMetricConfig } from './useMetricConfig';
import { __resetConfigCache } from '../api/config';
import { METRIC_CONFIG } from '../constants';

const LOCAL = [
  { key: 'mae', label: 'Mean Absolute Error', requiresHour: false, requiresThreshold: false },
  { key: 'gone', label: 'No longer served', requiresHour: false, requiresThreshold: false },
];

const SERVED = {
  metrics: {
    mae: { requires_hour: false, requires_threshold: false },
    brand_new: { requires_hour: true, requires_threshold: false },
  },
};

beforeEach(() => {
  __resetConfigCache();
  jest.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
  jest.restoreAllMocks();
  delete global.fetch;
});

describe('useMetricConfig', () => {
  it('renders the local list on the very first pass', () => {
    // Never blank, never waiting. Asserted before any flush, so a hook that
    // started from [] and filled in later would fail here even though its
    // settled state is right.
    global.fetch = jest.fn(() => new Promise(() => {}));   // never resolves
    const { result } = renderHook(() => useMetricConfig(LOCAL));
    expect(result.current).toBe(LOCAL);
  });

  it('upgrades to the served inventory once the config arrives', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => SERVED });
    const { result } = renderHook(() => useMetricConfig(LOCAL));
    await waitFor(() => expect(result.current.map((m) => m.key)).toEqual(['mae', 'brand_new']));
    // The whole point: a metric added to the backend is now selectable, and one
    // the backend dropped is not.
    expect(result.current.find((m) => m.key === 'brand_new').requiresHour).toBe(true);
    expect(result.current.find((m) => m.key === 'gone')).toBeUndefined();
  });

  it('keeps the local list when the endpoint cannot be reached', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('offline'));
    const { result } = renderHook(() => useMetricConfig(LOCAL));
    await waitFor(() => expect(console.warn).toHaveBeenCalled());
    expect(result.current).toBe(LOCAL);
  });

  it('keeps the local list when the endpoint answers with an error status', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 503 });
    const { result } = renderHook(() => useMetricConfig(LOCAL));
    await waitFor(() => expect(console.warn).toHaveBeenCalled());
    expect(result.current).toBe(LOCAL);
  });

  it('defaults to the real METRIC_CONFIG when given no list', () => {
    global.fetch = jest.fn(() => new Promise(() => {}));
    const { result } = renderHook(() => useMetricConfig());
    expect(result.current).toBe(METRIC_CONFIG);
  });
});
