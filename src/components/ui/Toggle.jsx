import React from 'react';

/**
 * Accessible on/off switch (role="switch", keyboard-operable) — replaces the
 * bespoke div-based toggles that weren't reachable by keyboard.
 */
export function Toggle({ on, onChange, color = '#3498db', label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => onChange(!on)}
      style={{
        width: '40px', height: '22px', borderRadius: '11px', flexShrink: 0,
        border: 'none', padding: 0, cursor: 'pointer', position: 'relative',
        background: on ? color : 'rgba(255,255,255,0.15)', transition: 'background 0.2s',
      }}
    >
      <span style={{ position: 'absolute', top: '3px', left: on ? '21px' : '3px', width: '16px', height: '16px', borderRadius: '50%', background: 'white', transition: 'left 0.2s' }} />
    </button>
  );
}
