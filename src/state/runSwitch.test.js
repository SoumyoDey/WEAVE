/**
 * What a run switch does to the rest of the app.
 *
 * `hourRangeFor` is the piece the clamping is built on, and it is the piece
 * most likely to go wrong quietly: a wrong range does not error, it scrubs the
 * timeline across lead times the run does not hold and shows nothing.
 *
 * The invalidation and clamping *effects* live in App.js and are exercised
 * there; these pin the contract they read from, plus the epoch semantics that
 * decide when they fire. All of it needs two runs, which the database does not
 * have — see RunContext.test.js for why that is mocked rather than skipped.
 */
import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';

import { RunProvider, useRun } from './RunContext';
import { resetRun } from '../api/run';

const RUN_A = '2025-09-08T00:00:00';   // full run: three models, both variables
const RUN_B = '2025-09-09T12:00:00';   // partial: AIFS only, shorter, precip only

const PAYLOAD = {
  runs: [RUN_B, RUN_A],
  latest: RUN_B,
  detail: [
    {
      init_time: RUN_B,
      variables: ['precipitation'],
      models: {
        AIFS: { n_members: 50, variables: [
          { variable: 'precipitation', hour_min: 0, hour_max: 24, export_divisor_h: 6.0 },
        ] },
      },
    },
    {
      init_time: RUN_A,
      // The stored spelling, which is what /api/runs really returns: there is
      // no `wind`, there are two components. Verified against the live
      // endpoint — an earlier version of this payload said `wind`, agreed with
      // the code, and hid the fact that wind never resolved a range at all.
      variables: ['precipitation', 'wind_u_10m', 'wind_v_10m'],
      models: {
        AIFS: { n_members: 50, variables: [
          { variable: 'precipitation', hour_min: 6, hour_max: 168, export_divisor_h: 6.0 },
          { variable: 'wind_u_10m',    hour_min: 0, hour_max: 120, export_divisor_h: null },
          // v stops earlier than u on purpose, so the intersection is testable.
          { variable: 'wind_v_10m',    hour_min: 0, hour_max: 96,  export_divisor_h: null },
        ] },
        GEFS: { n_members: 30, variables: [
          { variable: 'precipitation', hour_min: 3, hour_max: 240, export_divisor_h: 3.0 },
        ] },
      },
    },
  ],
};

let ctx = null;
const Probe = () => { ctx = useRun(); return <span data-testid="status">{ctx.status}</span>; };

const setup = async () => {
  global.fetch = jest.fn(() =>
    Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(PAYLOAD) }));
  render(<RunProvider><Probe /></RunProvider>);
  await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('ready'));
};

beforeEach(() => { resetRun(); ctx = null; });
afterEach(() => { delete global.fetch; });

describe('lead-time range per run', () => {
  it('reports what the run actually loaded, not what the model can produce', async () => {
    await setup();
    // MODELS.hours would claim the full forecast range for both.
    expect(ctx.hourRangeFor(RUN_A, 'AIFS', 'precipitation')).toEqual({ min: 6, max: 168 });
    expect(ctx.hourRangeFor(RUN_B, 'AIFS', 'precipitation')).toEqual({ min: 0, max: 24 });
  });

  it('is per variable, not per model', async () => {
    await setup();
    expect(ctx.hourRangeFor(RUN_A, 'AIFS', 'precipitation')).toEqual({ min: 6, max: 168 });
    expect(ctx.hourRangeFor(RUN_A, 'GEFS', 'precipitation')).toEqual({ min: 3, max: 240 });
  });

  it("resolves the UI's `wind` onto the two components the database stores", async () => {
    // The UI has one wind because a user picks wind and gets speed; the
    // database has wind_u_10m and wind_v_10m because speed is derived per
    // member. Looking up `wind` literally finds nothing, which reads as "this
    // run has no wind" and silently disables clamping on that variable.
    await setup();
    expect(ctx.hourRangeFor(RUN_A, 'AIFS', 'wind')).not.toBeNull();
  });

  it('intersects the wind components rather than trusting one', async () => {
    // u reaches +120 and v stops at +96. Offering +120 would let the timeline
    // scrub to a lead time where no speed can be computed.
    await setup();
    expect(ctx.hourRangeFor(RUN_A, 'AIFS', 'wind')).toEqual({ min: 0, max: 96 });
  });

  it('returns null for a combination the run does not hold', async () => {
    // Null rather than a default range on purpose: a fabricated {0,168} would
    // let the timeline scrub happily across lead times that return nothing.
    await setup();
    expect(ctx.hourRangeFor(RUN_B, 'GEFS', 'precipitation')).toBeNull();  // model absent
    expect(ctx.hourRangeFor(RUN_B, 'AIFS', 'wind')).toBeNull();           // no components
    expect(ctx.hourRangeFor(RUN_A, 'GEFS', 'wind')).toBeNull();           // precip only
    expect(ctx.hourRangeFor('1999-01-01T00:00:00', 'AIFS', 'precipitation')).toBeNull();
  });

  it('clamps a lead time that the new run does not reach', async () => {
    // The arithmetic App.js applies: +48h is valid in RUN_A and past the end
    // of RUN_B, so switching must pull it back to 24 rather than leave the
    // timeline pointing at nothing.
    await setup();
    const clamp = (h, r) => Math.min(Math.max(h, r.min), r.max);
    expect(clamp(48, ctx.hourRangeFor(RUN_B, 'AIFS', 'precipitation'))).toBe(24);
    // and leaves one that is still valid alone — phase 3 asks for persistence
    // where possible, not a reset to zero on every switch.
    expect(clamp(12, ctx.hourRangeFor(RUN_B, 'AIFS', 'precipitation'))).toBe(12);
  });
});

describe('model availability per run', () => {
  it('lists only the models a run holds', async () => {
    await setup();
    expect(ctx.modelsFor(RUN_A).sort()).toEqual(['AIFS', 'GEFS']);
    expect(ctx.modelsFor(RUN_B)).toEqual(['AIFS']);
  });

  it('gives the sidebar enough to grey out a missing model', async () => {
    await setup();
    const available = ctx.modelsFor(RUN_B);
    expect(available.includes('GEFS')).toBe(false);   // disabled, with a reason
    expect(available.includes('AIFS')).toBe(true);
  });
});

describe('when the switch should invalidate', () => {
  it('bumps the epoch, which is what the data effects depend on', async () => {
    await setup();
    const before = ctx.runEpoch;
    await act(async () => { ctx.selectRun(RUN_A); });
    expect(ctx.runEpoch).toBeGreaterThan(before);
  });

  it('bumps again switching back, so a returning run still refetches', async () => {
    // The case that makes the epoch necessary rather than comparing the run:
    // B -> A -> B ends where it started, and every result computed in between
    // is still stale.
    await setup();
    const start = ctx.runEpoch;
    await act(async () => { ctx.selectRun(RUN_A); });
    await act(async () => { ctx.selectRun(RUN_B); });
    expect(ctx.selectedRun).toBe(RUN_B);
    expect(ctx.runEpoch).toBeGreaterThan(start + 1);
  });

  it('does not bump when the same run is re-selected', async () => {
    await setup();
    const before = ctx.runEpoch;
    await act(async () => { ctx.selectRun(ctx.selectedRun); });
    expect(ctx.runEpoch).toBe(before);
  });
});
