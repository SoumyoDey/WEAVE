import React from 'react';

import { t } from '../theme';
import { useRun } from '../state/RunContext';

/**
 * Which forecast run the app is showing, in the header.
 *
 * DATA_EXPANSION_DESIGN.md phase 3 asks for this, populated from `/api/runs`
 * rather than hard-coded.
 *
 * **One run renders as a label, not a disabled dropdown.** A greyed-out control
 * reads as "something is broken"; a label reads as "this is what you are
 * looking at", which is the true statement while one run is loaded. The control
 * becomes interactive the moment a second run exists, with no code change.
 *
 * **Date and cycle, as the design document asked for.** An earlier version
 * used one combined list, on the argument that two coupled dropdowns can hold
 * a combination that does not exist — a date chosen, then a cycle that date
 * does not have. That risk is real and it is not a reason to merge the
 * controls: the cycle list is derived from the selected date, so an impossible
 * pair cannot be expressed. The combined list also does not scale — four
 * cycles a day means sixteen entries for four days of AIFS, in one flat list
 * with no structure.
 *
 * Changing date keeps the cycle where the new date has it, so moving between
 * days at 12Z stays at 12Z rather than snapping to 00Z.
 */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/**
 * `2025-09-08T00:00:00` -> `8 Sep 00Z`.
 *
 * Parsed by hand rather than with `new Date(...)`. The backend sends a naive
 * timestamp that is already UTC, and `Date` would read it as local time on
 * every machine east or west of Greenwich, so a 00Z run would display as the
 * previous evening for anyone in the Americas. That is the same class of
 * mistake as the 4-hour IMERG shift, and it would be just as quiet.
 */
export const formatRun = (initTime) => {
  if (!initTime) return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2})/.exec(initTime);
  if (!m) return initTime;
  const [, , month, day, hour] = m;
  const name = MONTHS[Number(month) - 1] ?? month;
  return `${Number(day)} ${name} ${hour}Z`;
};

/** `2025-09-08` -> `8 Sep 2025`. Parsed by hand, for the reason `formatRun` is. */
export const formatDate = (date) => {
  if (!date) return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!m) return date;
  const [, year, month, day] = m;
  return `${Number(day)} ${MONTHS[Number(month) - 1] ?? month} ${year}`;
};

export function RunSelector({ compact = false }) {
  const { runs, selectedRun, selectRun, canSwitch, status } = useRun();

  // Nothing useful to say yet, and a spinner in the header for a request that
  // usually takes milliseconds is worse than the gap it fills.
  if (status === 'loading' && !selectedRun) return null;

  // `/api/runs` failed. The app still works — a single-run backend answers
  // unqualified requests — so this says what is unavailable rather than
  // implying the data is wrong.
  if (status === 'error' && !selectedRun) {
    return (
      <span
        title="Could not load the list of forecast runs. The app is still showing data; only run switching is unavailable."
        style={{
          fontSize: t.fontSize.sm, color: t.textMuted, whiteSpace: 'nowrap',
        }}
      >
        Run unavailable
      </span>
    );
  }

  const label = formatRun(selectedRun);

  if (!canSwitch) {
    return (
      <span
        title={`Forecast run ${selectedRun} (UTC). One run is loaded.`}
        style={{
          fontSize: t.fontSize.sm, color: t.textMuted, whiteSpace: 'nowrap',
        }}
      >
        {compact ? label : `Run ${label}`}
      </span>
    );
  }

  // Grouped by date, so the two controls can only offer real combinations.
  const byDate = {};
  runs.forEach((r) => {
    const [date, time] = r.split('T');
    (byDate[date] = byDate[date] || []).push({ run: r, cycle: time.slice(0, 2) });
  });
  // Dates newest first, because the newest run is the one usually wanted.
  // Cycles ascending within a day, because 00/06/12/18 is how a forecast day
  // is read — reversing them here would be consistency at the cost of sense.
  const dates = Object.keys(byDate).sort().reverse();
  Object.values(byDate).forEach((cs) => cs.sort((a, b) => a.cycle.localeCompare(b.cycle)));
  const selectedDate = (selectedRun || '').split('T')[0];
  const cycles = byDate[selectedDate] || [];

  // Moving to another date keeps the cycle when that date has it, and falls to
  // the date's newest otherwise. Jumping to 00Z on every date change would
  // lose the user's place for no reason; offering a cycle the date does not
  // have is the thing this layout has to make impossible.
  const onDateChange = (date) => {
    const options = byDate[date] || [];
    if (!options.length) return;
    const currentCycle = (selectedRun || '').split('T')[1]?.slice(0, 2);
    const keep = options.find((o) => o.cycle === currentCycle);
    selectRun((keep || options[options.length - 1]).run);
  };

  const control = {
    fontSize: t.fontSize.sm,
    fontWeight: t.fontWeight.semibold,
    padding: `${t.space(0.5)} ${t.space(1.5)}`,
    border: `1px solid ${t.borderStrong}`,
    borderRadius: t.radiusSm,
    background: 'rgba(255,255,255,0.06)',
    color: 'white',
    cursor: 'pointer',
    outline: 'none',
  };
  const optionStyle = { background: t.bg, color: t.text };

  return (
    <span
      style={{ display: 'inline-flex', alignItems: 'center', gap: t.space(1.5) }}
    >
      {!compact && (
        <span
          style={{
            fontSize: t.fontSize.sm, color: t.textMuted, whiteSpace: 'nowrap',
          }}
        >
          Run
        </span>
      )}

      <select
        value={selectedDate}
        onChange={(e) => onDateChange(e.target.value)}
        aria-label="Forecast date"
        title="Initialisation date of the forecast run (UTC)"
        style={control}
      >
        {dates.map((d) => (
          <option key={d} value={d} style={optionStyle}>{formatDate(d)}</option>
        ))}
      </select>

      <select
        value={selectedRun ?? ''}
        onChange={(e) => selectRun(e.target.value)}
        aria-label="Initialisation time"
        title="Initialisation cycle, in UTC"
        style={control}
      >
        {cycles.map(({ run, cycle }) => (
          <option key={run} value={run} style={optionStyle}>{cycle}Z</option>
        ))}
      </select>
    </span>
  );
}

export default RunSelector;
