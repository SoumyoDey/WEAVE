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
 * **One list rather than the date + cycle pair the design document sketches.**
 * That split is right for a long archive and wrong now: two coupled dropdowns
 * can hold a combination that does not exist — a date selected, then a cycle
 * that run does not have — so it needs validation the single list makes
 * impossible by construction. Worth revisiting when the list is long enough to
 * scroll; the formatting below already groups by date visually.
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

  return (
    <label
      style={{ display: 'inline-flex', alignItems: 'center', gap: t.space(1.5) }}
    >
      <span
        style={{
          fontSize: t.fontSize.sm, color: t.textMuted, whiteSpace: 'nowrap',
        }}
      >
        Run
      </span>
      <select
        value={selectedRun ?? ''}
        onChange={(e) => selectRun(e.target.value)}
        aria-label="Forecast run"
        title="Initialisation time of the forecast run, in UTC"
        style={{
          fontSize: t.fontSize.sm,
          fontWeight: t.fontWeight.semibold,
          padding: `${t.space(0.5)} ${t.space(1.5)}`,
          border: `1px solid ${t.borderStrong}`,
          borderRadius: t.radiusSm,
          background: 'rgba(255,255,255,0.06)',
          color: 'white',
          cursor: 'pointer',
          outline: 'none',
        }}
      >
        {runs.map((r) => (
          <option key={r} value={r} style={{ background: t.bg, color: t.text }}>
            {formatRun(r)}
          </option>
        ))}
      </select>
    </label>
  );
}

export default RunSelector;
