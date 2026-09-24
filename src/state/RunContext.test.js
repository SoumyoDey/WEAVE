/**
 * The run selection, and the staleness guard that makes switching safe.
 *
 * **These deliberately mock `/api/runs` with two runs.** The database has one,
 * so every multi-run behaviour here — switching, epoch invalidation, per-run
 * model availability — is unreachable against real data and would otherwise go
 * untested until the day a second run is loaded, which is exactly the day it
 * needs to already work.
 */
import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';

import { RunProvider, useRun } from './RunContext';
import { getInitTime, getRunEpoch, isCurrentRun, resetRun, withRun } from '../api/run';

const RUN_A = '2025-09-08T00:00:00';
const RUN_B = '2025-09-09T12:00:00';

const PAYLOAD = {
  runs: [RUN_B, RUN_A],            // newest first, as the endpoint returns
  latest: RUN_B,
  detail: [
    { init_time: RUN_B, variables: ['precipitation'],
      models: { AIFS: { n_members: 50, variables: [] } } },
    { init_time: RUN_A, variables: ['precipitation', 'wind'],
      models: { AIFS: { n_members: 50, variables: [] },
                GEFS: { n_members: 30, variables: [] },
                UKMO: { n_members: 18, variables: [] } } },
  ],
};

const mockRuns = (payload = PAYLOAD) => {
  global.fetch = jest.fn(() =>
    Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) }));
};

// A probe that renders the context so assertions can read it from the DOM.
let ctx = null;
const Probe = () => {
  ctx = useRun();
  return (
    <div>
      <span data-testid="selected">{String(ctx.selectedRun)}</span>
      <span data-testid="epoch">{ctx.runEpoch}</span>
      <span data-testid="can-switch">{String(ctx.canSwitch)}</span>
      <span data-testid="status">{ctx.status}</span>
    </div>
  );
};

const renderProvider = async (props = {}) => {
  const out = render(<RunProvider {...props}><Probe /></RunProvider>);
  await waitFor(() => expect(screen.getByTestId('status').textContent).not.toBe('loading'));
  return out;
};

beforeEach(() => { resetRun(); ctx = null; });
afterEach(() => { delete global.fetch; jest.restoreAllMocks(); });

describe('resolving the run', () => {
  it('defaults to the newest run', async () => {
    mockRuns();
    await renderProvider();
    expect(screen.getByTestId('selected').textContent).toBe(RUN_B);
  });

  it('pushes the selection into the api layer, so requests are qualified', async () => {
    mockRuns();
    await renderProvider();
    expect(getInitTime()).toBe(RUN_B);
    expect(withRun({ model: 'AIFS' })).toEqual({ model: 'AIFS', init_time: RUN_B });
  });

  it('does not override a run that was already chosen', async () => {
    // An explicit initialRun must survive /api/runs arriving afterwards and
    // snapping the selection back to `latest`.
    mockRuns();
    await renderProvider({ initialRun: RUN_A });
    expect(screen.getByTestId('selected').textContent).toBe(RUN_A);
    expect(getInitTime()).toBe(RUN_A);
  });

  it('fetches /api/runs exactly once even with several consumers', async () => {
    mockRuns();
    render(
      <RunProvider><Probe /><Probe /><Probe /></RunProvider>,
    );
    await waitFor(() => expect(getInitTime()).toBe(RUN_B));
    const runCalls = global.fetch.mock.calls.filter(([u]) => String(u).includes('/runs'));
    expect(runCalls).toHaveLength(1);
  });
});

describe('switching', () => {
  it('changes the run the api layer names', async () => {
    mockRuns();
    await renderProvider();
    act(() => ctx.selectRun(RUN_A));
    expect(getInitTime()).toBe(RUN_A);
    expect(screen.getByTestId('selected').textContent).toBe(RUN_A);
  });

  it('bumps the epoch, which is what invalidates in-flight results', async () => {
    mockRuns();
    await renderProvider();
    const before = getRunEpoch();
    act(() => ctx.selectRun(RUN_A));
    expect(getRunEpoch()).toBeGreaterThan(before);
    expect(isCurrentRun(before)).toBe(false);
  });

  it('does not bump the epoch when re-selecting the same run', async () => {
    // A provider re-render that sets the same value must not invalidate
    // requests that are legitimately in flight for it.
    mockRuns();
    await renderProvider();
    const before = getRunEpoch();
    act(() => ctx.selectRun(RUN_B));
    expect(getRunEpoch()).toBe(before);
    expect(isCurrentRun(before)).toBe(true);
  });

  it('invalidates a response captured before an A -> B -> A round trip', async () => {
    // The case a value comparison cannot see: the run reads the same at the
    // end, but the component re-fetched in between, so the first response is
    // stale even though `getInitTime()` matches what it was issued under.
    mockRuns();
    await renderProvider();
    const epochAtRequest = getRunEpoch();
    act(() => ctx.selectRun(RUN_A));
    act(() => ctx.selectRun(RUN_B));
    expect(getInitTime()).toBe(RUN_B);          // same value as at request time
    expect(isCurrentRun(epochAtRequest)).toBe(false);   // and still stale
  });
});

describe('what a run contains', () => {
  it('reports the models present in each run, so a missing one can be greyed out', async () => {
    mockRuns();
    await renderProvider();
    expect(ctx.modelsFor(RUN_A).sort()).toEqual(['AIFS', 'GEFS', 'UKMO']);
    expect(ctx.modelsFor(RUN_B)).toEqual(['AIFS']);   // GEFS and UKMO absent
  });

  it('returns the detail entry for a run, and null for one it does not know', async () => {
    mockRuns();
    await renderProvider();
    expect(ctx.runDetail(RUN_A).variables).toContain('wind');
    expect(ctx.runDetail('1999-01-01T00:00:00')).toBeNull();
  });
});

describe('degrading', () => {
  it('reports one run as not switchable', async () => {
    mockRuns({ runs: [RUN_A], latest: RUN_A, detail: [PAYLOAD.detail[1]] });
    await renderProvider();
    expect(screen.getByTestId('can-switch').textContent).toBe('false');
    expect(screen.getByTestId('selected').textContent).toBe(RUN_A);
  });

  it('survives /api/runs failing, because a one-run backend still answers', async () => {
    global.fetch = jest.fn(() => Promise.resolve({ ok: false, status: 500 }));
    await renderProvider();
    expect(screen.getByTestId('status').textContent).toBe('error');
    expect(screen.getByTestId('can-switch').textContent).toBe('false');
  });

  it('omits init_time entirely when no run resolved, rather than sending null', async () => {
    // The backend reads absent as "resolve it if unambiguous" and would reject
    // an explicit null as a malformed timestamp.
    global.fetch = jest.fn(() => Promise.resolve({ ok: false, status: 500 }));
    await renderProvider();
    expect(withRun({ model: 'AIFS' })).toEqual({ model: 'AIFS' });
  });
});

describe('using the hook outside a provider', () => {
  it('throws, rather than quietly sending unqualified requests', async () => {
    const quiet = jest.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/useRun must be used inside/);
    quiet.mockRestore();
  });
});
