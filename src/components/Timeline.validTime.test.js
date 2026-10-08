/**
 * The "Valid" label is the run's init plus the lead time, or it is absent.
 *
 * The defect (`NEXT_STEPS.md` §68): the init was read from `obsCoverage`, a
 * payload about *observations*, and when that was null — every page load until
 * the request returns, and permanently if it fails — the component fell back to
 * a literal `new Date('2025-09-08T00:00:00Z')`. The app opens on `2025-09-16`,
 * so the label read eight days early, and a reader has no way to tell a valid
 * time from a wrong one by looking at it.
 *
 * The hard-coded date sat directly beneath a comment saying a hard-coded date
 * "silently lied the moment a different run was loaded", so the argument
 * against it was already written down. What was missing was a test that could
 * fail, which is what this is: the first case below renders with no coverage
 * and asserts the label is *gone*, and it fails against the old component with
 * "Sep 8".
 */
import React from 'react';
import { render, screen } from '@testing-library/react';

import { Timeline } from './Timeline';

const HOURS = [0, 6, 12, 18, 24];

const renderTimeline = (props = {}) =>
  render(
    <Timeline
      currentModel={{ name: 'AIFS', color: '#3498db', hours: HOURS }}
      hours={HOURS}
      selectedHour={6}
      setSelectedHour={() => {}}
      obsCoverage={null}
      isNarrow={false}
      {...props}
    />,
  );

describe('the valid-time label', () => {
  it('is measured from the run that is selected', () => {
    renderTimeline({ initTime: '2025-09-16T00:00:00', selectedHour: 6 });
    // 2025-09-16 00Z + 6h.
    expect(screen.getByText(/Tue, Sep 16, 06:00 UTC/)).toBeInTheDocument();
  });

  it('follows the lead time across a day boundary', () => {
    renderTimeline({ initTime: '2025-09-16T00:00:00', selectedHour: 30 });
    expect(screen.getByText(/Wed, Sep 17, 06:00 UTC/)).toBeInTheDocument();
  });

  it('is omitted when no run is selected, rather than guessed', () => {
    // The case the old code got wrong. A missing label is visibly missing;
    // a label eight days early is not.
    renderTimeline({ initTime: null });
    expect(screen.queryByText(/Valid/)).not.toBeInTheDocument();
    expect(screen.queryByText(/2025|Sep|UTC/)).not.toBeInTheDocument();
  });

  it('does not fall back to any date when observation coverage is missing', () => {
    // Pins the specific regression: `obsCoverage` null must not resurrect a
    // literal, and in particular not the 2025-09-08 one that was there.
    renderTimeline({ initTime: null, obsCoverage: null });
    expect(screen.queryByText(/Sep 8/)).not.toBeInTheDocument();
  });

  it('ignores the init the observations endpoint echoes back', () => {
    // The valid time is a fact about the forecast. If these two ever disagree
    // — a stale coverage response during a run switch is the obvious way —
    // the run is what the user chose and what every other panel is showing.
    renderTimeline({
      initTime: '2025-09-16T00:00:00',
      obsCoverage: { init_time: '2025-09-08T00:00:00', last_verifiable_hour: 18 },
      selectedHour: 6,
    });
    expect(screen.getByText(/Sep 16, 06:00 UTC/)).toBeInTheDocument();
    expect(screen.queryByText(/Sep 8/)).not.toBeInTheDocument();
  });

  it('shows nothing rather than "Invalid Date" for an unparseable init', () => {
    renderTimeline({ initTime: 'not-a-date' });
    expect(screen.queryByText(/Invalid Date/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Valid/)).not.toBeInTheDocument();
  });
});
