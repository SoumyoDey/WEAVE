// ── Design tokens ─────────────────────────────────────────────────────────────
// Single source of truth for the dark UI palette, spacing, and radii. Components
// import `t` instead of hard-coding rgba() values, so the look can be retuned in
// one place. (Migration is incremental — new/updated components use these first.)
export const t = {
  // surfaces
  bg:            '#0f1923',
  panel:         'rgba(15,25,35,0.97)',
  surface:       'rgba(255,255,255,0.06)',
  surfaceSoft:   'rgba(255,255,255,0.03)',
  // borders
  border:        'rgba(255,255,255,0.1)',
  borderStrong:  'rgba(255,255,255,0.15)',
  // text
  text:          '#e6edf3',
  textMuted:     'rgba(255,255,255,0.55)',
  textFaint:     'rgba(255,255,255,0.35)',
  // accent + roles
  accent:        '#3aa0ff',
  accentText:    '#7ec8f7',
  accentSoft:    'rgba(58,160,255,0.14)',
  accentBorder:  'rgba(58,160,255,0.7)',
  danger:        '#e74c3c',
  warn:          '#e67e22',
  // shape + rhythm
  radius:        '8px',
  radiusSm:      '6px',
  radiusPill:    '11px',
  space:         (n) => `${n * 4}px`,   // 4-pt spacing scale: space(2) => 8px
};
