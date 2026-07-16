import React from 'react';
import { HelpCircle } from 'lucide-react';
import { t } from '../../theme';

export function Hint({ text }) {
  return (
    <span title={text} aria-label={text} style={{ cursor: 'help', display: 'inline-flex', verticalAlign: '-2px', marginLeft: t.space(1), color: t.textFaint }}>
      <HelpCircle size={12} aria-hidden="true" />
    </span>
  );
}
