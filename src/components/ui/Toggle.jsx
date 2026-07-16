import React from 'react';
import { t } from '../../theme';

/**
 * Accessible on/off switch (role="switch", keyboard-operable) — replaces the
 * bespoke div-based toggles that weren't reachable by keyboard.
 */
export function Toggle({ on, onChange, color = t.accent, label, disabled = false }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      style={{
        width: '40px', height: '22px', borderRadius: '11px', flexShrink: 0,
        border: 'none', padding: 0, cursor: disabled ? 'not-allowed' : 'pointer', position: 'relative',
        background: on ? color : t.borderStrong, transition: t.transition,
        opacity: disabled ? 0.5 : 1,
      }}
    >
      <span style={{ position: 'absolute', top: '3px', left: on ? '21px' : '3px', width: '16px', height: '16px', borderRadius: t.radiusRound, background: 'white', transition: t.transition }} />
    </button>
  );
}
