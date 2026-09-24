import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { fetchRuns, getInitTime, getRunEpoch, setInitTime } from '../api/run';

/**
 * Which forecast run the app is looking at, as React state.
 *
 * `src/api/run.js` owns the wire format and the module-scope value every api
 * function reads; this owns the *selection*, because changing it has to
 * re-render and invalidate, which is React's job and not a module variable's.
 * The two are kept in sync in one direction only — provider to module — so
 * there is exactly one writer and no loop.
 *
 * **Global, but shaped for per-tab later.** DATA_EXPANSION_DESIGN.md phase 3
 * asks for that: comparing the same model across two runs (00Z against 12Z) is
 * a real question the Comparison tab may eventually want. So consumers take
 * their run from `useRun()` rather than reaching for a global, and a future
 * per-tab version overrides the provider for a subtree instead of rewriting
 * every consumer.
 *
 * **Why `runEpoch` is exposed rather than just the run.** An async result must
 * be discarded if the run changed while it was in flight, and comparing the
 * run value cannot detect A → B → A. The epoch can. Consumers either pass it
 * to `isCurrentRun` before committing state, or use it as an effect dependency
 * so the effect simply re-runs.
 *
 * With one run loaded this is inert — `runs` has a single entry and nothing can
 * be switched. That is expected: the selector has no user-visible value until a
 * second run exists, and this exists so that loading one is not also a
 * front-end project. The multi-run behaviour is covered by tests against a
 * mocked `/api/runs`, since the database has one run to offer.
 */

const RunContext = createContext(null);

export const RunProvider = ({ children, initialRun = null }) => {
  const [runs, setRuns]       = useState([]);
  const [detail, setDetail]   = useState([]);
  const [selected, setSelectedState] = useState(initialRun);
  const [status, setStatus]   = useState('loading');   // loading | ready | error
  const [error, setError]     = useState(null);
  const [epoch, setEpoch]     = useState(getRunEpoch);

  // Seed the module before the first paint when a run was supplied, so the
  // earliest requests are already qualified rather than relying on the
  // bootstrap. Layout effect timing is not needed: api calls await
  // `whenRunReady`, which this satisfies.
  useEffect(() => {
    if (initialRun) {
      setInitTime(initialRun);
      setEpoch(getRunEpoch());
    }
  }, [initialRun]);

  useEffect(() => {
    let cancelled = false;
    fetchRuns()
      .then((data) => {
        if (cancelled) return;
        const list = data?.runs ?? [];
        setRuns(list);
        setDetail(data?.detail ?? []);
        setStatus('ready');
        // Default to the newest, but never override a selection already made —
        // the bootstrap or an explicit `initialRun` may have got here first.
        setSelectedState((current) => {
          const next = current ?? getInitTime() ?? data?.latest ?? null;
          if (next) setInitTime(next);
          return next;
        });
        setEpoch(getRunEpoch());
      })
      .catch((err) => {
        if (cancelled) return;
        // Not fatal. A single-run backend answers unqualified requests, so the
        // app keeps working and only the selector is unavailable.
        setStatus('error');
        setError(err);
      });
    return () => { cancelled = true; };
  }, []);

  const selectRun = useCallback((initTime) => {
    setSelectedState((current) => {
      if (initTime === current) return current;   // no epoch bump for a no-op
      setInitTime(initTime);
      setEpoch(getRunEpoch());
      return initTime;
    });
  }, []);

  /**
   * What a given run actually holds, for greying out a model that is missing
   * from it rather than letting it silently return nothing (phase 3).
   */
  const runDetail = useCallback(
    (initTime) => detail.find((d) => d.init_time === initTime) ?? null,
    [detail],
  );

  const modelsFor = useCallback((initTime) => {
    const d = detail.find((x) => x.init_time === initTime);
    return d ? Object.keys(d.models) : [];
  }, [detail]);

  const value = useMemo(() => ({
    runs,
    detail,
    selectedRun: selected,
    selectRun,
    runDetail,
    modelsFor,
    runEpoch: epoch,
    // One run is not a choice. The selector renders as a static label rather
    // than a disabled dropdown, which reads as "this is what you are looking
    // at" instead of "something is broken".
    canSwitch: runs.length > 1,
    status,
    error,
  }), [runs, detail, selected, selectRun, runDetail, modelsFor, epoch, status, error]);

  return <RunContext.Provider value={value}>{children}</RunContext.Provider>;
};

/**
 * The selected run and the tools to change it.
 *
 * Throws outside a provider rather than returning a null-ish default: a
 * component that silently renders with no run would send unqualified requests,
 * which work against one run and 400 against two. That is precisely the class
 * of failure the `init_time` migration exists to prevent, so it should be loud
 * in development rather than latent until a second run lands.
 */
export const useRun = () => {
  const ctx = useContext(RunContext);
  if (!ctx) throw new Error('useRun must be used inside a <RunProvider>');
  return ctx;
};

export default RunContext;
