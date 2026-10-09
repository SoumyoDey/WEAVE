/**
 * A tab that throws costs you that tab, and nothing else.
 *
 * `ErrorBoundary.test.js` proves the component contains a throw. It would pass
 * just as well if `App` never used it — which is the **"well-tested component
 * wired to nothing"** failure this project has now hit three times (§28's
 * vacuous tests, §32's `src/api/config.js` imported only by its own test, §33's
 * untested `/api/runs`). So this file renders the real `App`, makes a real tab
 * throw, and asserts the rest of the application is still on screen.
 *
 * The arrangement under test (`NEXT_STEPS.md` §70): one boundary per tab, plus
 * a backstop in `index.js`. Before it, the four tabs shared one tree with no
 * boundary anywhere, so a render throw in any of them blanked everything —
 * including the three tabs that were fine and the map that was still drawing.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

jest.mock('leaflet', () => require('./testing/leafletStub'));

// Analysis is the tab made to fail. Mocked at the module boundary so the throw
// happens during *render* — the only kind a boundary can catch, and the kind
// that used to take the page with it.
jest.mock('./components/AnalysisTab', () => ({
  AnalysisTab: () => { throw new Error('analysis exploded'); },
}));

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
  // Two runs, because the selector collapses to a plain label on a one-run
  // backend and this file waits on it to know the app has finished starting.
  return { runs: [RUN, OLDER], latest: RUN, entries: [],
           detail: [{ init_time: RUN, models, variables: ['precipitation'] },
                    { init_time: OLDER, models, variables: ['precipitation'] }] };
};

let consoleError;
beforeEach(() => {
  resetRun();
  // React prints every caught error plus its component stack; that noise is
  // expected here and asserted on in ErrorBoundary.test.js instead.
  consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
  global.fetch = jest.fn((input) => {
    const url = String(input);
    const ok = (body) => Promise.resolve({ ok: true, status: 200,
                                           json: () => Promise.resolve(body) });
    if (url.includes('/api/runs')) return ok(runsPayload());
    if (url.includes('/api/cyclones')) return ok({ runs: [], storms: [] });
    return ok({});
  });
});
afterEach(() => consoleError.mockRestore());

const renderApp = async () => {
  render(<RunProvider><VerificationProvider><App /></VerificationProvider></RunProvider>);
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Initialisation time' }))
    .toBeInTheDocument());
};

test('the app survives a tab that throws on render', async () => {
  await renderApp();

  // The throw happens immediately: every tab is mounted at once and merely
  // hidden with `display: none`, which is exactly why one of them failing used
  // to be fatal.
  expect(screen.getByText(/The Analysis panel stopped/)).toBeInTheDocument();

  // The things that must still be there.
  expect(screen.getByRole('button', { name: 'Visualization' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Comparison' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Cyclones' })).toBeInTheDocument();
  expect(screen.getByRole('combobox', { name: 'Initialisation time' })).toBeInTheDocument();
});

test('the other tabs still open and render', async () => {
  await renderApp();

  fireEvent.click(screen.getByRole('button', { name: 'Comparison' }));
  await waitFor(() =>
    expect(screen.getByRole('button', { name: /Run Comparison/ })).toBeInTheDocument());

  // And the broken one is still contained rather than having spread.
  expect(screen.getByText(/The Analysis panel stopped/)).toBeInTheDocument();
});

test('the failure is attributed to the tab that failed', async () => {
  await renderApp();
  // Naming it is the difference between "the app is broken" and "Analysis is
  // broken, use the other three" — the whole reason the boundaries are
  // per-tab rather than one at the root.
  expect(screen.getByText(/The Analysis panel stopped/)).toBeInTheDocument();
  expect(screen.queryByText(/The Comparison panel stopped/)).not.toBeInTheDocument();
  expect(screen.queryByText(/The Visualization panel stopped/)).not.toBeInTheDocument();
});

test('the thrown message is shown, not hidden behind an apology', async () => {
  await renderApp();
  expect(screen.getByText(/analysis exploded/)).toBeInTheDocument();
});
