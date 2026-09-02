import React from 'react';
import { t } from '../../theme';

export function SectionHeader({ icon: Icon, children, style }) {
  return (
    <div style={{
      fontSize: t.fontSize.xs, color: t.textMuted, letterSpacing: '0.01em', marginBottom: t.space(2),
      display: 'flex', alignItems: 'center', gap: t.space(1.5), ...style,
    }}>
      {Icon && <Icon size={13} aria-hidden="true" />}{children}
    </div>
  );
}

export function FieldLabel({ children, style }) {
  return <div style={{ fontSize: t.fontSize.xs, fontWeight: t.fontWeight.medium, color: t.textMuted, marginBottom: t.space(1.5), ...style }}>{children}</div>;
}
