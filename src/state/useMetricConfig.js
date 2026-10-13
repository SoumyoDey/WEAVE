/**
 * The metric list the UI renders, from `/api/config` where it can be reached.
 *
 * `SYSTEM_DESIGN_PLAN.md` S4's exit criterion is that adding a metric is a
 * single-place change. `/api/config` has served the backend's registry since
 * 2026-10-01 and `src/api/config.js` has had a client for it — but **nothing in
 * the application ever called that client**; it was imported only by its own
 * test. So the selector still mapped over the local `METRIC_CONFIG`, and a
 * metric added to the backend stayed invisible until someone edited
 * `constants.js` too. This hook is the wire that was missing.
 *
 * **It starts local and upgrades.** The first render uses `METRIC_CONFIG`, so
 * the panel is never blank and never waits on a network call; when the config
 * arrives, the merged list replaces it. If the call fails, `fetchConfig`
 * resolves to null, nothing is replaced, and the app behaves exactly as it did
 * before — the soft dependency `config.js` promises.
 *
 * The merge rules live in `metricsFrom`: the server decides which metrics exist
 * and what each requires, the local constants decide labels, descriptions,
 * colours and order.
 */
import { useEffect, useState } from 'react';

import { fetchConfig, metricsFrom } from '../api/config';
import { METRIC_CONFIG } from '../constants';

export const useMetricConfig = (local = METRIC_CONFIG) => {
  const [metrics, setMetrics] = useState(local);

  useEffect(() => {
    let alive = true;
    fetchConfig().then((config) => {
      // `config` is null when the endpoint could not be reached, which is not
      // an error here — it means "keep the local answer".
      if (alive && config) setMetrics(metricsFrom(config, local));
    });
    return () => { alive = false; };
    // `local` is a module constant in every real caller; re-running on identity
    // change would refetch on every render for no gain.
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  return metrics;
};

/**
 * The whole config, for readers that want more than the metric list.
 *
 * `useMetricConfig` merges one specific thing; the obs-source label and the
 * candidate lead times are two more facts the server owns, and giving each its
 * own fetching hook would re-implement the same effect three times.
 * `fetchConfig` is deduplicated per page load, so several consumers cost one
 * request.
 *
 * Returns `null` until the call resolves and `null` forever if it fails, which
 * is what every accessor in `api/config.js` takes as "use the fallback".
 */
export const useConfig = () => {
  const [config, setConfig] = useState(null);

  useEffect(() => {
    let alive = true;
    fetchConfig().then((c) => { if (alive && c) setConfig(c); });
    return () => { alive = false; };
  }, []);

  return config;
};

export default useMetricConfig;
