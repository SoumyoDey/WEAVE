// ── Design tokens ─────────────────────────────────────────────────────────────
// Single source of truth for the dark UI palette, spacing, and radii. Components
// import `t` instead of hard-coding rgba() values, so the look can be retuned in
// one place. (Migration is incremental — new/updated components use these first.)
export const t = {
  // surfaces
  bg:            '#0f1923',
  panel:         'rgba(15,25,35,0.97)',
  panelRaised:   '#16212c',
  overlay:       'rgba(6,12,20,0.6)',
  surface:       'rgba(255,255,255,0.06)',
  surfaceSoft:   'rgba(255,255,255,0.03)',
  surfaceHover:  'rgba(255,255,255,0.1)',
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
  accentInk:     '#04213a',
  danger:        '#e74c3c',
  warn:          '#e67e22',
  success:       '#2ecc71',
  // shape + rhythm
  radius:        '8px',
  radiusSm:      '6px',
  radiusPill:    '11px',
  radiusRound:   '999px',
  shadowPanel:   '0 20px 60px rgba(0,0,0,0.5)',
  shadowControl: '0 4px 12px rgba(0,0,0,0.3)',
  transition:    'all 0.2s ease',
  space:         (n) => `${n * 4}px`,   // 4-pt spacing scale: space(2) => 8px
};
