import React from 'react';
import { t } from '../../theme';

export function SectionHeader({ icon: Icon, children, style }) {
  return (
    <div style={{
      fontSize: '11px', color: t.textMuted, letterSpacing: '0.01em', marginBottom: t.space(2),
      display: 'flex', alignItems: 'center', gap: t.space(1.5), ...style,
    }}>
      {Icon && <Icon size={13} aria-hidden="true" />}{children}
    </div>
  );
}

export function FieldLabel({ children, style }) {
  return <div style={{ fontSize: '11px', fontWeight: 500, color: t.textMuted, marginBottom: t.space(1.5), ...style }}>{children}</div>;
}
