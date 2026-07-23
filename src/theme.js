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
  // 0.5 (was 0.35) — 0.35 computed ~2.7:1 against the panel background at the
  // small sizes this is used at, below the WCAG AA minimum (4.5:1). 0.5 clears
  // it (~5.2:1) while staying visually de-emphasised relative to textMuted.
  textFaint:     'rgba(255,255,255,0.5)',
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
  // type scale — one source of truth in place of the ad-hoc literal sizes
  // (10/10.5/11/12/13/14/15/16/18/22/24/28px) scattered across components.
  fontSize: {
    micro:  '10px',   // chart tick labels, tiny captions
    xs:     '11px',   // hints, secondary captions
    sm:     '12px',   // default secondary label size
    base:   '13px',   // default primary label size
    md:     '14px',   // emphasised body / small headings
    lg:     '16px',   // panel titles
    xl:     '18px',   // sub-headings
    stat:   '22px',   // stat-card numbers
    statLg: '24px',   // larger stat-card numbers
    hero:   '28px',   // largest number displays
  },
  // subtle hover lift for interactive elements that don't have a bespoke
  // hover treatment — merge into a style object on mouse-enter.
  hoverLift: { filter: 'brightness(1.18)' },
};
