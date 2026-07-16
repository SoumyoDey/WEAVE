import React from 'react';
import { t } from '../../theme';

const variants = {
  primary: { background: t.accent, border: `1px solid ${t.accent}`, color: t.accentInk },
  secondary: { background: t.surface, border: `1px solid ${t.borderStrong}`, color: t.text },
  ghost: { background: 'transparent', border: `1px solid ${t.borderStrong}`, color: t.text },
  danger: { background: t.danger, border: `1px solid ${t.danger}`, color: '#fff' },
};

export function Button({ variant = 'secondary', style, children, disabled = false, ...props }) {
  return (
    <button
      type="button"
      disabled={disabled}
      style={{
        minHeight: '36px', padding: `${t.space(2)} ${t.space(3)}`,
        borderRadius: t.radius, cursor: disabled ? 'not-allowed' : 'pointer',
        fontSize: '13px', fontWeight: 600, transition: t.transition,
        opacity: disabled ? 0.5 : 1, ...variants[variant], ...style,
      }}
      {...props}
    >
      {children}
    </button>
  );
}
