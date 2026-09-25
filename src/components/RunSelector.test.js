/**
 * The run selector in the header.
 *
 * Like the context tests, the multi-run cases mock `/api/runs`: the database
 * has one run, so the switchable rendering is unreachable against real data
 * and would otherwise first be exercised on the day a second run lands.
 */
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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

const DAY = '2025-09-08';
const mk = (list) => ({ runs: list, latest: list[0],
                        detail: list.map((r) => ({ init_time: r, variables: ['precipitation'],
                                                   models: { UKMO: {} } })) });

// One date, several cycles — the case a flat list handles worst.
const sameDayCycles = mk([`${DAY}T18:00:00`, `${DAY}T12:00:00`,
                          `${DAY}T06:00:00`, `${DAY}T00:00:00`]);
// Two dates with different cycles available on each.
const unevenCycles = mk(['2025-09-09T00:00:00', `${DAY}T12:00:00`,
                         `${DAY}T06:00:00`, `${DAY}T00:00:00`]);
// Two dates, same cycles on both.
const bothDaysAllCycles = mk(['2025-09-09T12:00:00', '2025-09-09T00:00:00',
                              `${DAY}T12:00:00`, `${DAY}T00:00:00`]);

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
  it('offers a date control and a cycle control, not one combined list', async () => {
    // The combined list does not scale: four cycles a day is sixteen flat
    // entries for four days.
    mockRuns(twoRuns);
    await renderSelector();
    expect(await screen.findByRole('combobox', { name: 'Forecast date' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Initialisation time' })).toBeInTheDocument();
  });

  it('lists each date once, newest first', async () => {
    mockRuns(twoRuns);
    await renderSelector();
    const dates = await screen.findByRole('combobox', { name: 'Forecast date' });
    expect(Array.from(dates.querySelectorAll('option')).map((o) => o.textContent))
      .toEqual(['9 Sep 2025', '8 Sep 2025']);
  });

  it('starts on the newest run', async () => {
    mockRuns(twoRuns);
    await renderSelector();
    const cycle = await screen.findByRole('combobox', { name: 'Initialisation time' });
    expect(cycle).toHaveValue(RUN_B);
  });

  it('switching cycle updates the run the api layer names', async () => {
    mockRuns(sameDayCycles);
    await renderSelector();
    const cycle = await screen.findByRole('combobox', { name: 'Initialisation time' });
    await userEvent.selectOptions(cycle, `${DAY}T18:00:00`);
    await waitFor(() => expect(getInitTime()).toBe(`${DAY}T18:00:00`));
  });

  it('offers only the cycles the selected date actually has', async () => {
    // The whole reason the combined list was defensible: two loose dropdowns
    // can express a pair that does not exist. Deriving the cycles from the
    // date makes that impossible rather than merely validated.
    mockRuns(unevenCycles);
    await renderSelector();
    const dates = await screen.findByRole('combobox', { name: 'Forecast date' });
    const cycles = () => Array.from(
      screen.getByRole('combobox', { name: 'Initialisation time' })
        .querySelectorAll('option')).map((o) => o.textContent);

    await userEvent.selectOptions(dates, '2025-09-09');
    expect(cycles()).toEqual(['00Z']);            // 9 Sep has only 00Z

    await userEvent.selectOptions(dates, '2025-09-08');
    expect(cycles()).toEqual(['00Z', '06Z', '12Z']);
  });

  it('keeps the cycle when moving to a date that has it', async () => {
    // Snapping to 00Z on every date change loses the user's place for no
    // reason; comparing the same cycle across days is the normal question.
    mockRuns(bothDaysAllCycles);
    await renderSelector();
    const dates = await screen.findByRole('combobox', { name: 'Forecast date' });
    const cycle = () => screen.getByRole('combobox', { name: 'Initialisation time' });

    await userEvent.selectOptions(cycle(), '2025-09-09T12:00:00');
    await userEvent.selectOptions(dates, '2025-09-08');
    await waitFor(() => expect(getInitTime()).toBe('2025-09-08T12:00:00'));
  });

  it('falls back to the newest cycle when the new date lacks the current one', async () => {
    mockRuns(unevenCycles);
    await renderSelector();
    const dates = await screen.findByRole('combobox', { name: 'Forecast date' });
    const cycle = () => screen.getByRole('combobox', { name: 'Initialisation time' });

    // Get onto 8 Sep first — 12Z is not offered while 9 Sep is selected,
    // which is the constraint being tested.
    await userEvent.selectOptions(dates, '2025-09-08');
    await userEvent.selectOptions(cycle(), '2025-09-08T12:00:00');
    await userEvent.selectOptions(dates, '2025-09-09');     // has only 00Z
    await waitFor(() => expect(getInitTime()).toBe('2025-09-09T00:00:00'));
  });
});

describe('when the archive is large', () => {
  // 90 days x 4 cycles = 360 runs. A dropdown of 90 dates is not a control,
  // it is a scroll; this is the shape the app has to hold as runs accumulate.
  const bigArchive = (() => {
    const list = [];
    for (let d = 0; d < 90; d += 1) {
      const day = new Date(Date.UTC(2025, 5, 1 + d)).toISOString().slice(0, 10);
      ['00', '06', '12', '18'].forEach((c) => list.push(`${day}T${c}:00:00`));
    }
    list.reverse();
    return mk(list);
  })();

  it('becomes a date input rather than a 90-option dropdown', async () => {
    mockRuns(bigArchive);
    await renderSelector();
    const date = await screen.findByLabelText('Forecast date');
    expect(date.tagName).toBe('INPUT');
    expect(date).toHaveAttribute('type', 'date');
  });

  it('bounds the input to the dates actually loaded', async () => {
    mockRuns(bigArchive);
    await renderSelector();
    const date = await screen.findByLabelText('Forecast date');
    expect(date).toHaveAttribute('min', '2025-06-01');
    expect(date).toHaveAttribute('max', '2025-08-29');
  });

  it('still offers only that date\'s cycles', async () => {
    mockRuns(bigArchive);
    await renderSelector();
    const select = await screen.findByRole('combobox', { name: 'Initialisation time' });
    const cycles = Array.from(select.querySelectorAll('option')).map((o) => o.textContent);
    expect(cycles).toEqual(['00Z', '06Z', '12Z', '18Z']);
  });

  it('refuses a date inside the range that has no runs, and names it', async () => {
    // The cost of a date input: min/max bound the range but cannot express
    // holes in it. Snapping silently to a neighbour would show a different day
    // than the one asked for, which is worse than saying no.
    const withHole = mk(['2025-09-10T00:00:00', '2025-09-08T00:00:00',
                         '2025-09-06T00:00:00', '2025-09-04T00:00:00',
                         '2025-09-02T00:00:00', '2025-08-31T00:00:00',
                         '2025-08-29T00:00:00', '2025-08-27T00:00:00',
                         '2025-08-25T00:00:00', '2025-08-23T00:00:00',
                         '2025-08-21T00:00:00', '2025-08-19T00:00:00',
                         '2025-08-17T00:00:00']);
    mockRuns(withHole);
    await renderSelector();
    const date = await screen.findByLabelText('Forecast date');
    const before = getInitTime();

    fireEvent.change(date, { target: { value: '2025-09-09' } });   // no runs

    expect(await screen.findByText(/no runs on 9 Sep 2025/)).toBeInTheDocument();
    expect(getInitTime()).toBe(before);        // selection unchanged
  });

  it('clears the warning once a date with runs is chosen', async () => {
    const withHole = mk(Array.from({ length: 13 }, (_, i) =>
      `2025-09-${String(24 - i * 2).padStart(2, '0')}T00:00:00`));
    mockRuns(withHole);
    await renderSelector();
    const date = await screen.findByLabelText('Forecast date');

    fireEvent.change(date, { target: { value: '2025-09-23' } });   // odd day: none
    await screen.findByText(/no runs on/);
    fireEvent.change(date, { target: { value: '2025-09-22' } });   // even day: exists
    await waitFor(() => expect(screen.queryByText(/no runs on/)).not.toBeInTheDocument());
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
