import React from 'react';
import { t } from '../../theme';

export function IconButton({ label, title = label, active = false, danger = false, size = 36, style, children, ...props }) {
  const background = danger ? t.danger : active ? t.accent : t.surface;
  const color = active && !danger ? t.accentInk : t.text;
  return (
    <button
      type="button"
      aria-label={label}
      title={title}
      style={{
        width: `${size}px`, height: `${size}px`, minWidth: `${size}px`, padding: 0,
        borderRadius: t.radius, border: `1px solid ${active || danger ? 'transparent' : t.border}`,
        background, color, cursor: 'pointer', display: 'inline-flex', alignItems: 'center',
        justifyContent: 'center', boxShadow: t.shadowControl, transition: t.transition, ...style,
      }}
      {...props}
    >
      {children}
    </button>
  );
}
