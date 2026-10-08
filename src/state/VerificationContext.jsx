/**
 * The four settings that decide what a score means, held once for the app.
 *
 * Threshold, lead range, FSS neighbourhood and scored area are not display
 * options: two readers using different values are answering different
 * questions. The project has corrected that in the same place three times —
 * §41 the estimator, §54 the defaults, §55 Analysis's internal copies — and
 * each fix left the next layer of it in place. This is the last layer: the two
 * scored tabs held their own copies, so Analysis could sit at 5 mm/6h over
 * 24–72 h while Comparison, one click away, read 0–168 h, with nothing on
 * screen saying so (`VERIFICATION_SETTINGS_DESIGN.md` §2).
 *
 * **The precedent is `RunContext`, deliberately.** A forecast run qualifies
 * every number on screen, so it lives above the tabs and every tab reads it; a
 * threshold qualifies every categorical number in exactly the same way. The
 * app settled this shape once and this follows it, including the guard below.
 *
 * **The coupling is the feature.** Changing the threshold in one tab changes
 * what the other will show. That was the decision taken on 2026-10-08, and the
 * alternative was not independence — it was two live answers to one question.
 *
 * Starting values come from `VERIFICATION_DEFAULTS`, which stays the single
 * source of those (§54). The threshold is the exception and cannot be a
 * constant: it is variable-specific (mm/6h against m/s), so it is seeded here
 * and re-seeded when the variable changes.
 */
import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';

import { VERIFICATION_DEFAULTS as VD } from '../constants';

/** The event threshold a variable starts at, in that variable's native units. */
export const defaultThresholdFor = (variable) => (variable === 'wind' ? 10 : 25);

const VerificationContext = createContext(null);

export const VerificationProvider = ({ children, variable = 'precipitation' }) => {
  // Held as strings where a user types them, so a field can be empty
  // mid-keystroke; `*Num` are what callers score with. Same bargain
  // `AnalysisTab` struck in §55.
  const [threshold, setThreshold] = useState(() => defaultThresholdFor(variable));
  const [hourMin, setHourMin]     = useState(VD.HOUR_MIN);
  const [hourMax, setHourMax]     = useState(VD.HOUR_MAX);
  const [fssWindow, setFssWindow] = useState(VD.FSS_WINDOW);
  const [boxCells, setBoxCells]   = useState(VD.BOX_CELLS);

  /**
   * Put the threshold back to the default for a variable.
   *
   * The caller decides when: the tabs do it on a variable switch, because
   * 25 mm/6h and 10 m/s are not the same bar and carrying one across would
   * score wind against a precipitation threshold.
   */
  const resetThresholdFor = useCallback((nextVariable) => {
    setThreshold(defaultThresholdFor(nextVariable));
  }, []);

  const value = useMemo(() => {
    const parsed = parseFloat(threshold);
    return {
      threshold,
      thresholdNum: Number.isFinite(parsed) ? parsed : defaultThresholdFor(variable),
      setThreshold,
      hourMin, setHourMin,
      hourMax, setHourMax,
      fssWindow, setFssWindow,
      boxCells, setBoxCells,
      resetThresholdFor,
    };
  }, [threshold, hourMin, hourMax, fssWindow, boxCells, resetThresholdFor, variable]);

  return (
    <VerificationContext.Provider value={value}>
      {children}
    </VerificationContext.Provider>
  );
};

/**
 * The settings, for any panel that scores.
 *
 * Throws rather than defaulting, for the reason `useRun` throws: a panel that
 * silently rendered with its own private defaults would be the exact defect
 * this context exists to remove, and it would be invisible — the numbers would
 * look fine and simply answer a different question from the panel beside them.
 */
export const useVerification = () => {
  const ctx = useContext(VerificationContext);
  if (!ctx) throw new Error('useVerification must be used inside a <VerificationProvider>');
  return ctx;
};

export default VerificationContext;
