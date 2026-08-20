import React, { useRef, useEffect, useState } from 'react';
import { CloudRain, X } from 'lucide-react';
import { t } from '../theme';

/**
 * Full-screen guide to the application.
 *
 * A sectioned tutorial rather than an about box: the onboarding tour covers the
 * first thirty seconds, and this is where someone goes when they want to know
 * what a number actually means. Sections are shown one at a time so the reader
 * is never scrolling through five topics to find one.
 *
 * Props:
 *   onClose        {fn}
 *   onReplayTour   {fn|undefined}
 */

const C = {
  head:  '#2c3e50',
  body:  '#41546a',
  soft:  '#5d6d7e',
  blue:  '#3498db',
  panel: '#f4f6f7',
  line:  '#e1e5e8',
};

// This modal is the app's one light surface and its one long-form reading
// surface, so it keeps its own colours (C, above). Its SIZES are not special
// though, and were the last holdouts outside the type scale. Two moved onto it
// rather than earning a token of their own, both by a rounding:
//   h2   20px -> xl   (18px), the heading tier the rest of the app uses
//   p/ul 13.5 -> base (13px), which merges body prose with the note and row
//                text it sits beside — they were always the same tier
const S = {
  h2:   { fontSize: t.fontSize.xl, color: C.head, margin: '0 0 6px 0', fontWeight: 700 },
  lede: { fontSize: t.fontSize.md, color: C.soft, margin: '0 0 20px 0', lineHeight: 1.6 },
  h3:   { fontSize: t.fontSize.md, color: C.head, margin: '22px 0 8px 0', fontWeight: 700 },
  p:    { fontSize: t.fontSize.base, color: C.body, lineHeight: 1.75, margin: '0 0 12px 0' },
  ul:   { fontSize: t.fontSize.base, color: C.body, lineHeight: 1.75, paddingLeft: '18px', margin: '0 0 12px 0' },
  note: { background: C.panel, border: `1px solid ${C.line}`, borderRadius: t.radius,
          padding: '14px 16px', fontSize: t.fontSize.base, color: C.body, lineHeight: 1.7, margin: '14px 0 0 0' },
  kbd:  { background: '#eef2f5', border: `1px solid ${C.line}`, borderRadius: '4px',
          padding: '1px 6px', fontSize: t.fontSize.sm, fontFamily: 'ui-monospace, monospace', color: C.head },
};

/** Small labelled row used by the tab and metric listings. */
function Row({ label, children, width = 150 }) {
  return (
    <div style={{ display: 'flex', gap: '14px', padding: '9px 0', borderBottom: `1px solid ${C.line}`, alignItems: 'baseline' }}>
      <div style={{ fontSize: t.fontSize.base, fontWeight: 700, color: C.head, minWidth: `${width}px`, flexShrink: 0 }}>{label}</div>
      <div style={{ fontSize: t.fontSize.base, lineHeight: 1.65, color: C.soft }}>{children}</div>
    </div>
  );
}

const SECTIONS = [
  {
    id: 'start',
    nav: 'Getting started',
    title: 'What WEAVE does',
    lede: 'Three ensemble weather models, shown with their uncertainty and checked against what actually happened.',
    render: () => (
      <>
        <p style={S.p}>
          A single forecast tells you one story. An <strong>ensemble</strong> runs the same model many
          times from slightly different starting points, and the spread between those runs is the
          model telling you how sure it is. WEAVE shows that spread, and then asks the harder
          question: was it right?
        </p>

        <h3 style={S.h3}>The three tabs</h3>
        <Row label="🌍 Visualization">The map. What the forecast says, how confident it is, and how that changes with lead time.</Row>
        <Row label="📊 Analysis">One model, in depth — at a clicked point or over a drawn region.</Row>
        <Row label="⚖️ Comparison">Several models side by side, scored on equal terms.</Row>

        <h3 style={S.h3}>What is loaded</h3>
        <Row label="AIFS" width={90}>ECMWF's AI model — 50 members, 0.25°</Row>
        <Row label="GEFS" width={90}>NCEP's global ensemble — 30 members, 0.5°</Row>
        <Row label="UKMO" width={90}>Met Office ensemble — 18 members, 0.1875° × 0.28125°</Row>
        <Row label="Variables" width={90}>Precipitation and 10 m wind speed, verified against GPM IMERG and ERA5</Row>

        <div style={S.note}>
          <strong>New here?</strong> Take the tour for a thirty-second walk around the map, then come
          back to <em>Reading the numbers</em> before you trust any score.
        </div>
      </>
    ),
  },
  {
    id: 'viz',
    nav: '🌍 Visualization',
    title: 'The map',
    lede: 'Choose what to look at, then read the forecast and its uncertainty together.',
    render: () => (
      <>
        <h3 style={S.h3}>Controls</h3>
        <p style={S.p}>
          Open <strong>Controls</strong> at the top left to pick a model, a variable, and what to
          show: the <strong>ensemble mean</strong>, the <strong>spread</strong> between members, or a
          single member. The bar along the bottom moves through lead time — how far ahead the
          forecast is looking — and the header always states what is on screen.
        </p>

        <h3 style={S.h3}>Seeing uncertainty</h3>
        <p style={S.p}>
          The colour shows the forecast value. The <strong>uncertainty style</strong> adds a second
          layer showing how much the members disagree, so you can see confidence and value at once
          rather than flipping between two maps.
        </p>
        <Row label="None" width={90}>Value only.</Row>
        <Row label="Boxes / Grid" width={90}>Cells sized or shaded by spread — bigger or denser means less agreement.</Row>
        <Row label="Fan" width={90}>Radial glyphs, useful where the field changes quickly.</Row>
        <Row label="Texture" width={90}>Hatching over uncertain areas, which survives printing and greyscale.</Row>

        <h3 style={S.h3}>Scoring an area</h3>
        <p style={S.p}>
          The <span style={S.kbd}>▢</span> and <span style={S.kbd}>⬡</span> buttons on the right draw
          a rectangle or polygon. Once drawn, a panel offers any spatial metric over that area — pick
          one, set a threshold if it needs one, and <strong>Compute Spatial Map</strong> renders it
          server-side.
        </p>

        <div style={S.note}>
          The map is drawn in <strong>mm/h</strong> for precipitation, and thresholds are typed in
          <strong> mm/6h</strong> — the panel shows the conversion underneath so the two never have to
          be reconciled in your head.
        </div>
      </>
    ),
  },
  {
    id: 'analysis',
    nav: '📊 Analysis',
    title: 'One model, in depth',
    lede: 'Click a point or draw a region, then ask how good the forecast was there.',
    render: () => (
      <>
        <h3 style={S.h3}>Point mode</h3>
        <Row label="Cone of uncertainty">Ensemble mean with ±1σ and ±2σ bands across lead time. A widening cone is the model losing confidence.</Row>
        <Row label="Spread-skill">Compares the spread the ensemble claimed against the error it actually made, per lead time, with a plain-language calibration verdict.</Row>
        <Row label="Verification metrics">CSI, POD, FAR, Brier, FSS at a threshold you choose.</Row>

        <h3 style={S.h3}>What "a point" means</h3>
        <p style={S.p}>
          A click lands inside a grid cell, and scores are computed over that cell — not an
          infinitesimal point. The <strong>Scored area</strong> control widens the box when you want
          FSS, which needs neighbours to measure placement. Widening it does <em>not</em> move the
          other metrics: the contingency table keeps reading the centre cell alone. A badge always
          states the area a number came from.
        </p>

        <h3 style={S.h3}>Region mode</h3>
        <p style={S.p}>
          Draw a box and every spatial metric is computed across it in parallel and rendered as a
          map, so you can see <em>where</em> the model did well rather than only how well on average.
        </p>

        <div style={S.note}>
          <strong>Spread-skill ratio</strong> is the one worth learning. Near 1 means the ensemble's
          confidence matched its accuracy. Below 1 it was overconfident — too narrow a spread for the
          errors it made. Above 1 it hedged.
        </div>
      </>
    ),
  },
  {
    id: 'comparison',
    nav: '⚖️ Comparison',
    title: 'Models side by side',
    lede: 'The same question asked of every model, so the answers can be compared.',
    render: () => (
      <>
        <h3 style={S.h3}>Point mode</h3>
        <Row label="Time series">Each model's ensemble mean and spread on one axis. Normalise when magnitudes differ enough to flatten the smaller one.</Row>
        <Row label="Skill over lead time">Bias, MAE, RMSE, CRPS and SSR per model per lead time, with aggregate cards.</Row>
        <Row label="Categorical skill">CSI, POD, FAR and FSS at a shared threshold.</Row>

        <h3 style={S.h3}>Region mode</h3>
        <Row label="Region metrics">Every metric per model over the box, as grouped bars.</Row>
        <Row label="Small multiples">One map per model for a chosen metric, on a shared colour scale so the panels are directly comparable.</Row>
        <Row label="A − B difference">Per-cell difference between two models, diverging from zero. Swapping A and B flips the sign and the colours, nothing else.</Row>
        <Row label="Spatial agreement">Where the selected models agree, independent of whether any is right.</Row>

        <div style={S.note}>
          A model looking better is not always a better model — check it is not simply being asked an
          easier question. That is what the conventions in the next section exist to prevent.
        </div>
      </>
    ),
  },
  {
    id: 'numbers',
    nav: 'Reading the numbers',
    title: 'What the scores actually mean',
    lede: 'The rules that make a cross-model number honest. Worth five minutes before trusting one.',
    render: () => (
      <>
        <h3 style={S.h3}>Everything is a rate</h3>
        <p style={S.p}>
          The three models do not store precipitation the same way. AIFS accumulates from
          initialisation, GEFS uses alternating 3-hour and 6-hour buckets, UKMO reports an hourly
          rate. Each is converted using its own semantics, so everything you see — map, chart and
          score — is <strong>mm/h</strong>.
        </p>

        <h3 style={S.h3}>Thresholds are quoted over six hours</h3>
        <p style={S.p}>
          An event bar is conventionally stated as an amount over a window: <strong>25 mm/6h</strong>.
          Internally that becomes a rate (25 ÷ 6 = 4.17 mm/h) and is compared against the forecast.
          Wind thresholds are plain <strong>m/s</strong>, since wind is already a rate.
        </p>

        <h3 style={S.h3}>Every precipitation model is scored over the same six hours</h3>
        <p style={S.p}>
          This one is easy to miss and changes conclusions. A one-hour average keeps peaks that a
          six-hour average smooths away, so a model reporting hourly would cross a high threshold
          more often than a model reporting six-hourly — for no reason but its cadence. Every model
          is re-expressed on a common six-hour window first, so a threshold asks one question of all
          of them.
        </p>
        <p style={S.p}>
          <strong>Wind is exempt.</strong> It is an instantaneous value rather than an accumulation,
          so there is no window to reconcile and its records are scored as they stand.
        </p>

        <h3 style={S.h3}>No observation, no score</h3>
        <p style={S.p}>
          A forecast is only scored where an observation covers its whole period. Past the end of the
          observation record you will see nothing rather than a number built from partial truth. An
          empty panel at long lead times usually means exactly this.
        </p>

        <h3 style={S.h3}>FSS needs more than one cell</h3>
        <p style={S.p}>
          Fractions Skill Score measures whether rain was put in the right <em>place</em>. With a
          single cell an event fraction can only be 0 or 1, so FSS collapses into CSI and tells you
          nothing new — it is reported as undefined, and widening the scored area gives it something
          to work with.
        </p>
      </>
    ),
  },
  {
    id: 'glossary',
    nav: 'Metric glossary',
    title: 'Every metric, in one line',
    lede: 'What each score answers, and which direction is good.',
    render: () => (
      <>
        <h3 style={S.h3}>Calibration — was the confidence honest?</h3>
        <Row label="SSR">Spread against error. <strong>≈ 1 ideal</strong>; below is overconfident, above is hedging.</Row>
        <Row label="Spread-skill corr.">Does the spread grow when the error does? <strong>Higher better</strong>.</Row>

        <h3 style={S.h3}>Accuracy — how close to observed?</h3>
        <Row label="Bias">Average signed error. <strong>0 ideal</strong>; negative is under-forecasting.</Row>
        <Row label="MAE">Average size of the error. <strong>Lower better</strong>.</Row>
        <Row label="RMSE">Like MAE but punishes large misses harder. <strong>Lower better</strong>.</Row>
        <Row label="CRPS">Scores the whole forecast distribution, not just its mean. <strong>Lower better</strong>.</Row>

        <h3 style={S.h3}>Events — did it call the threshold?</h3>
        <Row label="CSI">Of everything forecast or observed, how much matched. <strong>Higher better</strong>.</Row>
        <Row label="POD">Of what happened, how much was caught. <strong>Higher better</strong>.</Row>
        <Row label="FAR">Of what was forecast, how much did not happen. <strong>Lower better</strong>.</Row>
        <Row label="Brier">Accuracy of the probability itself. <strong>Lower better</strong>.</Row>
        <Row label="FSS">Was it in the right place, allowing a neighbourhood. <strong>Higher better</strong>.</Row>

        <div style={S.note}>
          A high POD with a high FAR means the model shouts about everything — it catches the events
          by forecasting rain almost everywhere. CSI is the one that refuses to be gamed that way,
          which is why it is usually the first number to read.
        </div>
      </>
    ),
  },
];

export function AboutModal({ onClose, onReplayTour }) {
  const dialogRef   = useRef(null);
  const closeBtnRef = useRef(null);
  const bodyRef     = useRef(null);
  const [active, setActive] = useState(SECTIONS[0].id);

  // Move focus into the dialog on open and trap Tab within it (Escape is handled
  // globally in App.js; the overlay click also closes).
  useEffect(() => {
    closeBtnRef.current?.focus();
    const node = dialogRef.current;
    const onKeyDown = (e) => {
      if (e.key !== 'Tab' || !node) return;
      const f = node.querySelectorAll('button, a[href], input, [tabindex]:not([tabindex="-1"])');
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    node?.addEventListener('keydown', onKeyDown);
    return () => node?.removeEventListener('keydown', onKeyDown);
  }, []);

  // A new section starts at the top rather than wherever the last one was left.
  useEffect(() => { if (bodyRef.current) bodyRef.current.scrollTop = 0; }, [active]);

  const section = SECTIONS.find(s => s.id === active) ?? SECTIONS[0];

  return (
    <div
      onClick={onClose}
      style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(102,126,234,0.98)', backdropFilter: 'blur(10px)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '32px', zIndex: 1500 }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="WEAVE guide"
        onClick={e => e.stopPropagation()}
        style={{ position: 'relative', maxWidth: '900px', width: '100%', maxHeight: '84vh', background: 'rgba(255,255,255,0.98)', borderRadius: '16px', boxShadow: '0 20px 60px rgba(0,0,0,0.4)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
      >
        {/* Header */}
        <div style={{ padding: '22px 28px 16px', borderBottom: `1px solid ${C.line}`, flexShrink: 0 }}>
          <h1 style={{ fontSize: t.fontSize.statLg, margin: 0, color: C.head, display: 'flex', alignItems: 'center', gap: '10px' }}>
            <CloudRain size={24} style={{ color: C.blue }} />WEAVE
            <span style={{ fontSize: t.fontSize.base, fontWeight: 400, color: C.soft, marginLeft: '2px' }}>· guide</span>
          </h1>
          <button
            ref={closeBtnRef}
            onClick={onClose}
            style={{ position: 'absolute', top: '18px', right: '18px', width: '32px', height: '32px', background: 'rgba(0,0,0,0.06)', border: 'none', borderRadius: '8px', cursor: 'pointer', color: '#555', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            aria-label="Close guide"
            title="Close"
          ><X size={18} /></button>
        </div>

        {/* overflow:hidden confines the two columns to this row — without it the
            body grows to its content and runs under the footer instead of scrolling */}
        <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
          {/* Section nav */}
          <nav
            aria-label="Guide sections"
            style={{ flex: '0 0 auto', width: '196px', minHeight: 0, borderRight: `1px solid ${C.line}`, padding: '14px 10px', background: '#fbfcfc', overflowY: 'auto' }}
          >
            {SECTIONS.map(s => {
              const on = s.id === active;
              return (
                <button
                  key={s.id}
                  onClick={() => setActive(s.id)}
                  aria-current={on ? 'true' : undefined}
                  style={{ display: 'block', width: '100%', textAlign: 'left', padding: '9px 12px', marginBottom: '3px', fontSize: t.fontSize.base, fontWeight: on ? 700 : 500, color: on ? '#1b6aa5' : C.soft, background: on ? 'rgba(52,152,219,0.12)' : 'transparent', border: 'none', borderRadius: '7px', cursor: 'pointer', lineHeight: 1.4 }}
                >{s.nav}</button>
              );
            })}
            {onReplayTour && (
              <button
                onClick={onReplayTour}
                style={{ display: 'block', width: '100%', textAlign: 'left', padding: '9px 12px', marginTop: '10px', fontSize: t.fontSize.base, fontWeight: 600, color: '#2980b9', background: 'rgba(52,152,219,0.08)', border: `1px solid rgba(52,152,219,0.35)`, borderRadius: '7px', cursor: 'pointer' }}
              >▸ Take the tour</button>
            )}
          </nav>

          {/* Section body */}
          <div ref={bodyRef} style={{ flex: '1 1 auto', padding: '24px 28px 28px', overflowY: 'auto', minWidth: 0, minHeight: 0 }}>
            <h2 style={S.h2}>{section.title}</h2>
            <p style={S.lede}>{section.lede}</p>
            {section.render()}
          </div>
        </div>

        <div style={{ padding: '12px 28px', borderTop: `1px solid ${C.line}`, fontSize: t.fontSize.sm, color: '#95a5a6', display: 'flex', justifyContent: 'space-between', flexShrink: 0, flexWrap: 'wrap', gap: '6px' }}>
          <span>React · Leaflet · Flask · PostgreSQL</span>
          <span>© 2026 WEAVE Team — Northeastern University</span>
        </div>
      </div>
    </div>
  );
}
