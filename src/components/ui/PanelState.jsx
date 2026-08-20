import React from 'react';
import { t } from '../../theme';

/**
 * The three states a panel is in before it has a result: loading, nothing asked
 * for yet, and asked-but-nothing-came-back.
 *
 * Extracted because the two tabs treated them differently — Comparison routed
 * every panel through one spinner and one "No results yet" block, while Analysis
 * wrote a bespoke string and its own padding per panel, which is most of why the
 * tabs felt different before any data arrived (CONSISTENCY_AUDIT.md 3c).
 *
 * What is shared is the *treatment*, not the wording. A message that carries
 * information — which observations ran out, and when — still says so; it just
 * says it in the same shape on both sides.
 */

/** Panel is fetching. `label` when it is worth naming what. */
export function LoadingState({ label = 'Loading…' }) {
  return (
    <div style={{
      color: 'rgba(255,255,255,0.4)', fontSize: t.fontSize.md,
      padding: '40px 0', textAlign: 'center',
    }}>
      ⏳ {label}
    </div>
  );
}

/**
 * Nothing has been asked for yet — the full-height "click a point" / "draw a
 * region" / "press Run" state. `icon` is a rendered element so the caller keeps
 * control of which glyph it is.
 */
export function EmptyState({ icon, title, detail }) {
  return (
    <div style={{
      height: '60vh', display: 'flex', alignItems: 'center',
      justifyContent: 'center', textAlign: 'center',
      color: 'rgba(255,255,255,0.25)',
    }}>
      <div>
        {icon && (
          <div style={{ marginBottom: '16px', lineHeight: 1, color: 'rgba(255,255,255,0.3)' }}>
            {icon}
          </div>
        )}
        <p style={{ fontSize: t.fontSize.lg, margin: 0, color: 'rgba(255,255,255,0.4)' }}>
          {title}
        </p>
        {detail && (
          <p style={{ fontSize: t.fontSize.base, margin: '8px 0 0 0' }}>{detail}</p>
        )}
      </div>
    </div>
  );
}

/**
 * Asked, and the answer was "nothing" — inline inside the panel that asked, so
 * the surrounding controls stay put. `detail` is for the reason, which is often
 * the only useful part: "no score here" and "no observations reach this lead
 * time" look identical without it.
 */
export function NoDataNote({ children, detail }) {
  return (
    <div style={{
      color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.base, padding: '20px 0',
    }}>
      {children}
      {detail && (
        <div style={{ fontSize: t.fontSize.sm, color: 'rgba(243,156,18,0.75)', marginTop: '6px' }}>
          {detail}
        </div>
      )}
    </div>
  );
}
