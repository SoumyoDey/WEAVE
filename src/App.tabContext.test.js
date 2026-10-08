/**
 * The header badge says only what the open tab is reading.
 *
 * It used to say everything on every tab, and on the **cyclone tab that put two
 * "initialised" controls on screen seven years apart**: the header offering the
 * forecast run (16 Sep 2025) beside the tab's own storm initialisation
 * (2018-11-09), with the header one doing nothing at all there. It also
 * announced a model, a variable and a lead time to a tab that has no
 * precipitation field, no wind field and no scrubber.
 *
 * `TAB_CONTEXT` in `App.js` is the rule; these are the four tabs it covers.
 * The assertions are about *absence* as much as presence, because the defect
 * was a control that was present and inert — which looks identical to a
 * control that works until you touch it.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

/**
 * The map is not what this file measures, and a real Leaflet in jsdom fails
 * asynchronously against whichever test is running — see the stub for the
 * full account.
 */
jest.mock('leaflet', () => require('./testing/leafletStub'));

import App from './App';
import { RunProvider } from './state/RunContext';
import { VerificationProvider } from './state/VerificationContext';
import { resetRun } from './api/run';

const RUN = '2025-09-16T00:00:00';
const OLDER = '2025-09-08T00:00:00';

const runsPayload = () => {
  const variables = [
    { variable: 'precipitation', hour_min: 6, hour_max: 360, export_divisor_h: 6 },
    { variable: 'wind_u_10m', hour_min: 0, hour_max: 360, export_divisor_h: null },
    { variable: 'wind_v_10m', hour_min: 0, hour_max: 360, export_divisor_h: null },
  ];
  const models = { AIFS: { n_members: 50, variables }, GEFS: { n_members: 30, variables },
                   UKMO: { n_members: 18, variables } };
  // Two runs, so the selector is a real control rather than the label it
  // collapses to on a single-run backend — the case where "present but inert"
  // would be hardest to see.
  return { runs: [RUN, OLDER], latest: RUN, entries: [],
           detail: [{ init_time: RUN, models, variables: ['precipitation'] },
                    { init_time: OLDER, models, variables: ['precipitation'] }] };
};

beforeEach(() => {
  resetRun();
  global.fetch = jest.fn((input) => {
    const url = String(input);
    const ok = (body) => Promise.resolve({ ok: true, status: 200,
                                           json: () => Promise.resolve(body) });
    if (url.includes('/api/runs')) return ok(runsPayload());
    if (url.includes('/api/cyclones')) return ok({ runs: [], storms: [] });
    return ok({});
  });
});

/** Everything the tab bar renders, including the context badge. */
const header = () =>
  screen.getByRole('button', { name: 'Visualization' }).parentElement.textContent;

const openTab = async (name) => {
  fireEvent.click(screen.getByRole('button', { name }));
  await waitFor(() => expect(header()).toEqual(expect.any(String)));
};

const renderApp = async () => {
  render(<RunProvider><VerificationProvider><App /></VerificationProvider></RunProvider>);
  // The selector renders nothing until /api/runs answers, so every assertion
  // about its absence would otherwise pass before it had a chance to appear.
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Initialisation time' }))
    .toBeInTheDocument());
};

describe('the header badge follows the open tab', () => {
  test('visualization shows the run, model, variable and lead time', async () => {
    await renderApp();
    expect(header()).toContain('AIFS');
    expect(header()).toContain('Precipitation');
    expect(header()).toContain('+6h');
    expect(screen.getByRole('combobox', { name: 'Initialisation time' })).toBeInTheDocument();
  });

  test('analysis drops the lead time, which it has no scrubber for', async () => {
    await renderApp();
    await openTab('Analysis');
    expect(screen.getByRole('combobox', { name: 'Initialisation time' })).toBeInTheDocument();
    expect(header()).toContain('AIFS');
    expect(header()).toContain('Precipitation');
    expect(header()).not.toContain('+6h');
  });

  test('comparison drops the model too, because it picks its own', async () => {
    await renderApp();
    await openTab('Comparison');
    expect(screen.getByRole('combobox', { name: 'Initialisation time' })).toBeInTheDocument();
    expect(header()).toContain('Precipitation');
    expect(header()).not.toContain('AIFS');
    expect(header()).not.toContain('+6h');
  });

  test('cyclones shows no forecast context at all', async () => {
    await renderApp();
    await openTab('Cyclones');
    // The run selector is the one that mattered: the tab has its own
    // initialisation control, and two of them disagreeing is the bug.
    expect(screen.queryByRole('combobox', { name: 'Initialisation time' })).not.toBeInTheDocument();
    expect(header()).not.toContain('AIFS');
    expect(header()).not.toContain('Precipitation');
    expect(header()).not.toContain('+6h');
  });

  test('it comes back when you leave the cyclone tab', async () => {
    await renderApp();
    await openTab('Cyclones');
    expect(screen.queryByRole('combobox', { name: 'Initialisation time' })).not.toBeInTheDocument();
    await openTab('Visualization');
    expect(screen.getByRole('combobox', { name: 'Initialisation time' })).toBeInTheDocument();
    expect(header()).toContain('+6h');
  });
});
