import React from 'react';
import { t } from '../../theme';

export function Select({ style, children, ...props }) {
  return (
    <select
      style={{
        width: '100%', minHeight: '36px', padding: `${t.space(2)} ${t.space(2.5)}`,
        fontSize: '12px', border: `1px solid ${t.borderStrong}`, borderRadius: t.radiusSm,
        background: t.surface, color: t.text, cursor: 'pointer', outline: 'none', ...style,
      }}
      {...props}
    >
      {children}
    </select>
  );
}

export function SelectOption({ children, style, ...props }) {
  return <option style={{ background: t.bg, color: t.text, ...style }} {...props}>{children}</option>;
}
