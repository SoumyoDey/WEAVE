/**
 * The Comparison tab's style tokens, built from the theme.
 *
 * Plain objects passed to `style={...}`: the card, the section title, the form
 * label and input, the chart tooltip, and the two grid/subhead wrappers. They
 * are here rather than in `theme.js` because they are this tab's composition
 * of the theme's primitives, not new primitives.
 */
import { t } from '../../theme';

export const CARD = {
  background: 'rgba(255,255,255,0.04)',
  borderRadius: 10,
  padding: '16px 20px',
  border: '1px solid rgba(255,255,255,0.07)',
};

export const SECTION_TITLE = {
  color: 'rgba(255,255,255,0.85)',
  fontSize: t.fontSize.md,
  fontWeight: t.fontWeight.semibold,
  letterSpacing: '0.02em',
  margin: '0 0 14px 0',
};

export const LABEL = {
  fontSize: t.fontSize.xs,
  fontWeight: t.fontWeight.medium,
  letterSpacing: '0.02em',
  color: 'rgba(255,255,255,0.5)',
  marginBottom: '6px',
};

export const INPUT = {
  background: 'rgba(255,255,255,0.06)',
  border: '1px solid rgba(255,255,255,0.12)',
  borderRadius: '7px',
  color: 'rgba(255,255,255,0.85)',
  fontSize: t.fontSize.base,
  padding: '6px 10px',
  outline: 'none',
  width: '80px',
};

export const TOOLTIP_STYLE = {
  background: '#1a2535',
  border: '1px solid rgba(255,255,255,0.15)',
  borderRadius: t.radius,
  color: 'white',
  fontSize: t.fontSize.sm,
};

// Shared layout for the small-multiple metric cards.
export const SMALL_GRID = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(min(240px, 100%), 1fr))',
  gap: '14px',
};

export const SUBHEAD = {
  color: 'rgba(255,255,255,0.55)',
  fontSize: t.fontSize.sm,
  marginBottom: '10px',
  display: 'flex',
  alignItems: 'center',
  gap: '12px',
  flexWrap: 'wrap',
};
