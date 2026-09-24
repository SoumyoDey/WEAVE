/**
 * The run selector in the header.
 *
 * Like the context tests, the multi-run cases mock `/api/runs`: the database
 * has one run, so the switchable rendering is unreachable against real data
 * and would otherwise first be exercised on the day a second run lands.
 */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { RunSelector, formatRun } from './RunSelector';
import { RunProvider } from '../state/RunContext';
import { getInitTime, resetRun } from '../api/run';

const RUN_A = '2025-09-08T00:00:00';
const RUN_B = '2025-09-09T12:00:00';

const mockRuns = (payload) => {
  global.fetch = jest.fn(() =>
    Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) }));
};

const twoRuns = {
  runs: [RUN_B, RUN_A],
  latest: RUN_B,
  detail: [
    { init_time: RUN_B, variables: ['precipitation'], models: { AIFS: {} } },
    { init_time: RUN_A, variables: ['precipitation'], models: { AIFS: {}, GEFS: {} } },
  ],
};

const oneRun = { runs: [RUN_A], latest: RUN_A, detail: [twoRuns.detail[1]] };

const renderSelector = async (props = {}) => {
  render(<RunProvider><RunSelector {...props} /></RunProvider>);
  await waitFor(() => expect(getInitTime() || global.fetch.mock.calls.length).toBeTruthy());
};

beforeEach(() => resetRun());
afterEach(() => { delete global.fetch; jest.restoreAllMocks(); });

describe('formatRun', () => {
  it('renders a UTC initialisation compactly', () => {
    expect(formatRun('2025-09-08T00:00:00')).toBe('8 Sep 00Z');
    expect(formatRun('2025-12-01T18:00:00')).toBe('1 Dec 18Z');
  });

  it('does not shift the date into local time', () => {
    // `new Date('2025-09-08T00:00:00')` is parsed as *local* time, so west of
    // Greenwich a 00Z run would display as 7 Sep. That is the same class of
    // quiet error as the 4-hour IMERG shift, so the formatter parses the
    // string rather than going through Date.
    expect(formatRun('2025-09-08T00:00:00')).toContain('8 Sep');
  });

  it('degrades rather than throwing on something unexpected', () => {
    expect(formatRun(null)).toBe('—');
    expect(formatRun('not-a-timestamp')).toBe('not-a-timestamp');
  });
});

describe('with one run loaded', () => {
  it('renders a label, not a disabled dropdown', async () => {
    // A greyed-out control reads as "broken"; a label reads as "this is what
    // you are looking at", which is the true statement.
    mockRuns(oneRun);
    await renderSelector();
    await screen.findByText(/8 Sep 00Z/);
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });
});

describe('with more than one run', () => {
  it('offers every run, newest first', async () => {
    mockRuns(twoRuns);
    await renderSelector();
    const select = await screen.findByRole('combobox', { name: 'Forecast run' });
    const options = Array.from(select.querySelectorAll('option')).map((o) => o.textContent);
    expect(options).toEqual(['9 Sep 12Z', '8 Sep 00Z']);
  });

  it('starts on the newest run', async () => {
    mockRuns(twoRuns);
    await renderSelector();
    const select = await screen.findByRole('combobox', { name: 'Forecast run' });
    expect(select).toHaveValue(RUN_B);
  });

  it('switching updates the run the api layer names', async () => {
    mockRuns(twoRuns);
    await renderSelector();
    const select = await screen.findByRole('combobox', { name: 'Forecast run' });
    await userEvent.selectOptions(select, RUN_A);
    await waitFor(() => expect(getInitTime()).toBe(RUN_A));
    expect(select).toHaveValue(RUN_A);
  });
});

describe('when /api/runs fails', () => {
  it('says switching is unavailable without implying the data is wrong', async () => {
    global.fetch = jest.fn(() => Promise.resolve({ ok: false, status: 500 }));
    render(<RunProvider><RunSelector /></RunProvider>);
    await screen.findByText('Run unavailable');
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });
});
