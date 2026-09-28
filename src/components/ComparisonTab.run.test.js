/**
 * The Comparison tab only offers models the selected run actually holds.
 *
 * `ControlsSidebar` has greyed out absent models since phase 3, but this tab
 * did not, and its own default selection is all three. The request then failed
 * with `no GEFS run at init_time ...` — a 400 the user could not have avoided,
 * because the control that caused it looked available.
 *
 * Unreachable until 2026-09-28: it needs two runs whose *model lists differ*,
 * and until AIFS 06Z was loaded every run held the same three models. Mocked
 * here for the same reason `RunSelector.test.js` mocks `/api/runs` — otherwise
 * this would first be exercised on the day the database changes again.
 */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ComparisonTab } from './ComparisonTab';
import { RunSelector } from './RunSelector';
import { RunProvider } from '../state/RunContext';
import { resetRun } from '../api/run';

const FULL = '2025-09-08T00:00:00';     // AIFS, GEFS, UKMO
const PARTIAL = '2025-09-08T06:00:00';  // AIFS, UKMO only — the real 06Z shape

const runs = {
  runs: [PARTIAL, FULL],
  latest: PARTIAL,
  detail: [
    { init_time: PARTIAL, variables: ['precipitation'],
      models: { AIFS: {}, UKMO: {} } },
    { init_time: FULL, variables: ['precipitation'],
      models: { AIFS: {}, GEFS: {}, UKMO: {} } },
  ],
};

const chip = (name) => screen.getByRole('button', { name: new RegExp(`^(✓ )?${name}$`) });

beforeEach(() => {
  resetRun();
  global.fetch = jest.fn((url) => {
    if (String(url).includes('/runs')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(runs) });
    }
    // Every other endpoint: empty but successful, so nothing here depends on
    // comparison data actually arriving.
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  });
});
afterEach(() => { delete global.fetch; jest.restoreAllMocks(); });

const renderTab = async () => {
  // The run control lives in the header, not in this tab. Rendered alongside so
  // a switch goes through the same path production uses, rather than by poking
  // the context directly.
  render(
    <RunProvider>
      <RunSelector />
      <ComparisonTab selectedVariable="precipitation" />
    </RunProvider>,
  );
  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  await screen.findByText('Models');
};

describe('on a run that is missing a model', () => {
  it('disables that model and says why', async () => {
    await renderTab();                       // starts on PARTIAL, the newest
    await waitFor(() => expect(chip('GEFS')).toBeDisabled());
    expect(chip('GEFS')).toHaveAttribute(
      'title', 'GEFS is not loaded for the selected forecast run');
  });

  it('leaves the models the run does have selectable', async () => {
    await renderTab();
    await waitFor(() => expect(chip('GEFS')).toBeDisabled());
    expect(chip('AIFS')).toBeEnabled();
    expect(chip('UKMO')).toBeEnabled();
  });

  it('drops it from the selection, not just from the controls', async () => {
    // The part a disabled chip does not achieve on its own: the default
    // selection is all three, so without narrowing, GEFS would still be sent
    // and the request would 400.
    await renderTab();
    await waitFor(() => expect(chip('GEFS')).toBeDisabled());
    expect(chip('AIFS').textContent).toContain('✓');
    expect(chip('UKMO').textContent).toContain('✓');
    expect(chip('GEFS').textContent).not.toContain('✓');
  });

  it('will not let the two remaining models be reduced to one', async () => {
    // The floor counts usable models, not ticks. Counting ticks read "three
    // selected" here and allowed a deselect that left a single model.
    await renderTab();
    await waitFor(() => expect(chip('GEFS')).toBeDisabled());
    await userEvent.click(chip('UKMO'));
    expect(chip('UKMO').textContent).toContain('✓');
  });
});

describe('on a run that has every model', () => {
  it('offers all three', async () => {
    await renderTab();
    const cycle = await screen.findByRole('combobox', { name: 'Initialisation time' });
    await userEvent.selectOptions(cycle, FULL);
    await waitFor(() => expect(chip('GEFS')).toBeEnabled());
    expect(chip('GEFS').textContent).toContain('✓');
    expect(chip('AIFS')).toBeEnabled();
    expect(chip('UKMO')).toBeEnabled();
  });

  it('restores a model that the previous run lacked', async () => {
    // The narrowing is derived during render rather than written back into
    // state, so switching to a run that has GEFS brings the original tick back
    // instead of having silently discarded it.
    await renderTab();
    await waitFor(() => expect(chip('GEFS')).toBeDisabled());
    const cycle = screen.getByRole('combobox', { name: 'Initialisation time' });
    await userEvent.selectOptions(cycle, FULL);
    await waitFor(() => expect(chip('GEFS').textContent).toContain('✓'));
  });
});
