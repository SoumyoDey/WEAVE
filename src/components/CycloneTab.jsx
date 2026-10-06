/**
 * The spaghetti map — every ensemble member's predicted track, at once.
 *
 * `NEXT_STEPS.md` §37 feature 1, `TC_TAB_DESIGN.md` §6. The question it answers
 * is the one the whole application is about: do the members agree? Here that is
 * asked of *where the storm goes* rather than of a field, so the answer is a
 * shape rather than a number, and the shape is the point.
 *
 * **The denominator is rendered, not hidden.** When 28 of 51 members tracked a
 * storm, the other 23 forecast no cyclone at all — which is a forecast, not a
 * gap, and often the most interesting thing on the chart. Drawing 28 lines and
 * letting a reader take that for the ensemble understates the spread in the
 * direction that matters most. So the header prints both numbers and says what
 * the difference means.
 *
 * This tab owns its own Leaflet map. The Visualization tab's instance is bound
 * to its own overlays, lifecycle and resize handling, and sharing it would
 * couple two tabs that have nothing else in common.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import {
  ComposedChart, Line, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Legend,
} from 'recharts';

import { fetchCyclones, fetchCycloneTracks, fetchStrikeProbability,
         fetchErrorByLead,
         unwrapTrack, referenceLongitude, strikeColour } from '../api/cyclone';
import { t } from '../theme';
import { ESRI_CANVAS_BASE } from '../constants';

const CENTRE_LABEL = {
  ecmf: 'ECMWF ENS',
  egrr: 'MOGREPS',
  kwbc: 'GEFS',
};

// Deliberately not the model colours from `constants.js`: those name AIFS, GEFS
// and UKMO, and these are different systems — ECMWF's physics ensemble, not
// AIFS, and MOGREPS, not the UKMO deterministic model. Reusing the palette
// would imply an identity that does not hold (NEXT_STEPS.md §20, §24).
const MEMBER_STYLE  = { color: '#6fb1ff', weight: 1.2, opacity: 0.45 };
const BEST_STYLE    = { color: '#ffffff', weight: 3.5, opacity: 0.95 };
const BEST_CASING   = { color: '#111b27', weight: 6,   opacity: 0.9 };

export function CycloneTab({ active, isNarrow = false }) {
  const mapRef   = useRef(null);
  const divRef   = useRef(null);
  const layerRef = useRef(null);
  // What the draw effect last fitted, so a resize can re-fit the same thing.
  const boundsRef = useRef(null);

  const [runs, setRuns]       = useState([]);
  const [storm, setStorm]     = useState(null);
  const [centre, setCentre]   = useState(null);
  const [init, setInit]       = useState(null);
  const [data, setData]       = useState(null);
  const [error, setError]     = useState(null);
  const [loading, setLoading] = useState(false);
  // The map is built in an effect; the draw effect below must wait for it.
  // Without this the two race, and whichever loses leaves an empty map with
  // a populated header — which is exactly how this first rendered.
  const [mapReady, setMapReady] = useState(false);
  // Feature 2: the derived field. Off by default — the tracks are the primary
  // reading and the field is the summary of them, so it is opt-in rather than
  // something a reader has to dismiss.
  const [showStrike, setShowStrike] = useState(false);
  const [radiusKm, setRadiusKm]     = useState(120);
  const [strike, setStrike]         = useState(null);
  const [errorByLead, setErrorByLead] = useState(null);

  // ── What is available ──────────────────────────────────────────────────────
  useEffect(() => {
    let alive = true;
    fetchCyclones()
      .then((r) => { if (alive) setRuns(r.runs || []); })
      .catch((e) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, []);

  const storms = useMemo(
    () => [...new Set(runs.map((r) => r.storm_name))].sort(), [runs]);
  const centresFor = useMemo(
    () => (s) => [...new Set(runs.filter((r) => r.storm_name === s)
                                 .map((r) => r.centre))].sort(), [runs]);
  /**
   * The initialisations available for a storm and centre, newest first.
   *
   * Keyed on the **actual** `init_time`, never on the source filename's
   * `<offset>h` label: that label is wrong for ECMWF by a factor of two,
   * because the generating script wrote `T * 6` hours while ECMWF runs
   * 12-hourly (TC_DATA_ACCESS.md). Two centres' "24h" files are not the same
   * age, so the only honest label is the timestamp itself.
   */
  const initsFor = useMemo(
    () => (s, c) => runs.filter((r) => r.storm_name === s && r.centre === c)
                        .sort((a, b) => b.init_time.localeCompare(a.init_time)),
    [runs]);

  // Pick something as soon as there is something to pick, so the tab is never
  // an empty map with no explanation.
  useEffect(() => {
    if (!storm && storms.length) setStorm(storms[0]);
  }, [storms, storm]);
  useEffect(() => {
    if (!storm) return;
    const options = centresFor(storm);
    if (!options.includes(centre)) setCentre(options[0] ?? null);
  }, [storm, centre, centresFor]);

  /**
   * The initialisation actually used — **derived during render, not stored.**
   *
   * An init belongs to one storm at one centre, so the moment the storm
   * changes the one in state is stale. Resetting it in an effect is too late:
   * effects run after the commit, so the fetch effects below have already
   * fired for the new storm with the *old* init — a pair that cannot exist and
   * returns 404. Measured on a storm switch: two doomed requests, each a real
   * database query, before the corrected pair goes out.
   *
   * The `alive` guards meant the 404 was never *displayed*, which is why this
   * looked fine for as long as nobody read the network log. It was still being
   * sent, and a tab that reliably emits 404s is a tab whose logs cannot be used
   * to find the 404s that matter.
   *
   * Deriving it means the invalid pair never exists in the first place, rather
   * than existing briefly and being cleaned up afterwards.
   */
  const initOptions = useMemo(
    () => initsFor(storm, centre).map((r) => r.init_time),
    [initsFor, storm, centre]);
  const activeInit = (storm && centre)
    ? (initOptions.includes(init) ? init : (initOptions[0] ?? null))
    : null;

  // State still follows, so the <select> stays controlled and a user's explicit
  // choice survives. This no longer gates any request — by the time it runs,
  // the fetches below have already used the derived value.
  useEffect(() => {
    if (activeInit !== init) setInit(activeInit);
  }, [activeInit, init]);

  // ── The tracks ─────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!storm || !centre || !activeInit) return;
    let alive = true;
    setLoading(true);
    setError(null);
    fetchCycloneTracks({ storm, centre, init: activeInit })
      .then((d) => { if (alive) { setData(d); setLoading(false); } })
      .catch((e) => { if (alive) { setError(e.message); setLoading(false); } });
    return () => { alive = false; };
  }, [storm, centre, activeInit]);

  // ── The strike-probability field ───────────────────────────────────────────
  useEffect(() => {
    if (!showStrike || !storm || !centre || !activeInit) { setStrike(null); return; }
    let alive = true;
    fetchStrikeProbability({ storm, centre, init: activeInit, radiusKm })
      .then((d) => { if (alive) setStrike(d); })
      .catch((e) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [showStrike, storm, centre, activeInit, radiusKm]);

  // ── Error and spread against lead ──────────────────────────────────────────
  useEffect(() => {
    if (!storm || !centre || !activeInit) { setErrorByLead(null); return; }
    let alive = true;
    fetchErrorByLead({ storm, centre, init: activeInit })
      .then((d) => { if (alive) setErrorByLead(d); })
      .catch((e) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [storm, centre, activeInit]);

  // ── The map ────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!active || mapRef.current || !divRef.current) return;
    const map = L.map(divRef.current, { worldCopyJump: true })
                 .setView([20, -60], 3);
    // The same Esri basemap the Visualization tab uses, imported rather than
    // restated. A first version reached for CARTO's dark tiles, which now
    // require an API key and rendered the map as a grid of "API KEY REQUIRED"
    // — caught by looking at it, which is the only way that kind of defect is
    // ever caught.
    L.tileLayer(`${ESRI_CANVAS_BASE}/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
                { attribution: '&copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors',
                  maxZoom: 16 }).addTo(map);
    L.tileLayer(`${ESRI_CANVAS_BASE}/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
                { attribution: '', maxZoom: 16 }).addTo(map);
    mapRef.current = map;
    layerRef.current = L.layerGroup().addTo(map);
    setMapReady(true);
  }, [active]);

  // Leaflet measures the container on creation; a tab that was hidden then has
  // a zero-size map until it is told to look again.
  //
  // **`isNarrow` belongs in here too.** Crossing the 760px breakpoint moves the
  // map from a column beside the panel to a row above it — a far bigger change
  // of shape than showing the tab — and Leaflet does not notice container
  // resizes on its own. Without this the map kept the view it had computed at
  // 28px wide: tracks running off the edge and unpainted tiles in the newly
  // exposed area, which looks like a rendering bug and is really a stale
  // measurement.
  //
  // Re-fitting after the resize, not just invalidating: the bounds that framed
  // the storm in a sliver do not frame it in a full-width map. `boundsRef`
  // holds what the draw effect last fitted, so the two cannot disagree about
  // what "the storm" is.
  useEffect(() => {
    if (!active || !mapRef.current) return;
    const id = setTimeout(() => {
      const map = mapRef.current;
      if (!map) return;
      map.invalidateSize();
      if (boundsRef.current) map.fitBounds(boundsRef.current);
    }, 0);
    return () => clearTimeout(id);
  }, [active, isNarrow]);

  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!map || !layer || !data) return;
    layer.clearLayers();

    // One reference for every track, so a storm straddling the dateline is
    // drawn in one place rather than as two clusters on opposite edges.
    const ref = referenceLongitude(data);
    const bounds = [];
    for (const m of data.members || []) {
      const line = unwrapTrack(m.points, ref);
      if (line.length > 1) L.polyline(line, MEMBER_STYLE).addTo(layer);
      bounds.push(...line);
    }
    // The field goes down first, so the tracks draw over it rather than under.
    // A cell is drawn as a rectangle on the lattice it was computed on, not as
    // a marker: the value describes the cell, and a dot would imply a point
    // measurement that does not exist.
    if (strike && strike.points) {
      const half = 0.25;                       // the 0.5 degree analysis cell
      for (const pt of strike.points) {
        const lon = unwrapTrack([{ lat: pt.lat, lon: pt.lon }], ref)[0][1];
        L.rectangle(
          [[pt.lat - half, lon - half], [pt.lat + half, lon + half]],
          { stroke: false, fillColor: strikeColour(pt.value),
            fillOpacity: 1, interactive: false },
        ).addTo(layer);
      }
    }

    const best = unwrapTrack(data.best_track || [], ref);
    if (best.length > 1) {
      L.polyline(best, BEST_CASING).addTo(layer);
      L.polyline(best, BEST_STYLE).addTo(layer);
    }
    bounds.push(...best);
    if (bounds.length) {
      boundsRef.current = L.latLngBounds(bounds).pad(0.15);
      map.fitBounds(boundsRef.current);
    }
  }, [data, strike, mapReady]);

  const missing = data ? data.nominal_members - data.tracked_members : 0;

  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex',
                  flexDirection: 'column', background: '#0d151f' }}>
      {/* Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px',
                    padding: '10px 14px', background: 'rgba(17,27,39,0.97)',
                    borderBottom: '1px solid rgba(255,255,255,0.08)',
                    flexWrap: 'wrap' }}>
        <label style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.micro,
                        textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Storm
          <select aria-label="Storm" value={storm ?? ''}
                  onChange={(e) => setStorm(e.target.value)}
                  style={selectStyle}>
            {storms.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.micro,
                        textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Centre
          <select aria-label="Centre" value={centre ?? ''}
                  onChange={(e) => setCentre(e.target.value)}
                  style={selectStyle}>
            {(storm ? centresFor(storm) : []).map((c) => (
              <option key={c} value={c}>{CENTRE_LABEL[c] ?? c}</option>
            ))}
          </select>
        </label>

        <label style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.micro,
                        textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Initialised
          <select aria-label="Initialisation" value={activeInit ?? ''}
                  onChange={(e) => setInit(e.target.value)}
                  style={{ ...selectStyle, minWidth: '230px' }}>
            {(storm && centre ? initsFor(storm, centre) : []).map((r) => (
              // The member counts are in the option itself: how many members
              // developed the storm varies between initialisations, and that
              // variation is a result rather than a detail. Reading it only
              // after selecting would hide the comparison.
              <option key={r.init_time} value={r.init_time}>
                {r.init_time.replace('T', ' ').slice(0, 16)}
                {'  ·  '}{r.tracked_members}/{r.nominal_members} members
              </option>
            ))}
          </select>
        </label>

        <label style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.micro,
                        textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Strike probability
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px',
                        marginTop: '4px' }}>
            <input type="checkbox" aria-label="Show strike probability"
                   checked={showStrike}
                   onChange={(e) => setShowStrike(e.target.checked)} />
            {/* The radius is a control because it changes the answer, the same
                bargain the threshold metrics strike. Stated beside the value,
                never implied. */}
            <select aria-label="Strike radius" value={radiusKm} disabled={!showStrike}
                    onChange={(e) => setRadiusKm(Number(e.target.value))}
                    style={{ ...selectStyle, marginTop: 0, minWidth: '110px',
                             opacity: showStrike ? 1 : 0.4 }}>
              {[60, 120, 200, 300].map((r) => (
                <option key={r} value={r}>within {r} km</option>
              ))}
            </select>
          </div>
        </label>

        {data && (
          <div style={{ marginLeft: 'auto', textAlign: 'right',
                        color: 'rgba(255,255,255,0.8)', fontSize: t.fontSize.sm }}>
            <div>
              <strong>{data.tracked_members} of {data.nominal_members}</strong>
              {' '}members tracked this storm
            </div>
            <div style={{ color: 'rgba(255,255,255,0.45)',
                          fontSize: t.fontSize.micro, marginTop: '2px' }}>
              {missing > 0
                ? `the other ${missing} forecast no cyclone`
                : 'every member produced a track'}
              {' · '}init {String(data.init_time).replace('T', ' ')}
            </div>
            {/*
              Stated for MOGREPS as a whole, not per run, and that distinction
              is the finding. MOGREPS-G is a 36-member **time-lagged** ensemble:
              18 members from the stated cycle pooled with 18 from six hours
              earlier, aligned by valid time. So half of any 36 are a staler
              forecast at the same moment.

              Only 1 of the 432 MOGREPS files here lets you tell which half.
              Where you can (GITA's 12Z run, whose cyclone_ids name the cycle),
              the lagged members are measurably worse at every lead — +15 km at
              T+0 rising to +54 km at T+144, pooled +26 km. Everywhere else the
              member ids do not preserve the grouping, so the two id blocks are
              each a 50/50 mix and the effect washes out to -2 km archive-wide.

              That null is not evidence of no lag; it is evidence the ids do not
              encode it. Hence a statement about the system, which is documented
              and always true, rather than a per-run number that would be
              unknowable for 431 of 432 runs. See TC_TAB_DESIGN.md.
            */}
            {data.system === 'MOGREPS' && (
              <div style={{ color: 'rgba(255,255,255,0.45)',
                            fontSize: t.fontSize.micro, marginTop: '2px' }}>
                time-lagged ensemble — 18 members from this cycle, 18 from six
                hours earlier, so half are staler at the same valid time
              </div>
            )}
            {showStrike && strike && (
              <div style={{ color: 'rgba(255,255,255,0.55)',
                            fontSize: t.fontSize.micro, marginTop: '2px' }}>
                peak strike probability{' '}
                <strong>{(strike.peak * 100).toFixed(0)}%</strong>{' '}
                within {strike.radius_km} km, of {strike.nominal_members} members
                {/* Only worth saying when the two differ. Spelling out "of 51,
                    not 51" reads as a mistake and buries the case where it is
                    the whole point. */}
                {strike.tracked_members < strike.nominal_members
                  && ` — not ${strike.tracked_members}, which is how many drew a track`}
              </div>
            )}
          </div>
        )}
      </div>

      {error && (
        <div role="alert" style={{ padding: '10px 14px', color: '#ffb4a2',
                                   fontSize: t.fontSize.sm }}>
          {error}
        </div>
      )}
      {loading && !error && (
        <div style={{ padding: '10px 14px', color: 'rgba(255,255,255,0.45)',
                      fontSize: t.fontSize.sm }}>Loading tracks…</div>
      )}

      {/*
          **The panel is a fixed 340px that does not shrink**, which is right
          beside a map and wrong inside one. Below 760px the two were still laid
          out side by side, so the panel took its 340 and the map got whatever
          remained — measured at a 397px viewport: **28 pixels**, a sliver with
          its own zoom buttons hanging off the edge. The map is the primary view
          of this tab, and it was the part that disappeared.

          Stacking below the app's own 760px breakpoint rather than inventing a
          second one, and `isNarrow` is passed from `App.js` rather than
          recomputed here so there is one resize listener and one threshold.
          The map keeps a fixed height when stacked, because `flex: 1` inside a
          column whose parent scrolls collapses it to nothing — the same defect
          one axis over.
      */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0,
                    flexDirection: isNarrow ? 'column' : 'row' }}>
        <div ref={divRef} style={isNarrow
                  ? { height: '55vh', flexShrink: 0, minHeight: '260px' }
                  : { flex: 1, minWidth: 0 }} />

        {/* Error and spread against lead. Beside the map rather than below it
            when there is room: the map answers "where", this answers "how
            wrong, and did the ensemble know" — the question the rest of this
            application is about, asked in track space. */}
        <div style={{ ...(isNarrow
                        ? { width: 'auto', flex: 1, minHeight: 0,
                            borderTop: '1px solid rgba(255,255,255,0.08)' }
                        : { width: '340px', flexShrink: 0,
                            borderLeft: '1px solid rgba(255,255,255,0.08)' }),
                      padding: '12px 14px',
                      background: 'rgba(17,27,39,0.97)',
                      overflowY: 'auto' }}>
          <div style={{ color: 'rgba(255,255,255,0.75)', fontSize: t.fontSize.sm,
                        fontWeight: t.fontWeight.semibold, marginBottom: '2px' }}>
            Track error and spread
          </div>
          <div style={{ color: 'rgba(255,255,255,0.35)',
                        fontSize: t.fontSize.micro, marginBottom: '10px',
                        lineHeight: 1.5 }}>
            Error is each member against the best track; spread is each member
            against the ensemble mean. They are different quantities — an
            ensemble can agree with itself and be wrong together.
          </div>

          {errorByLead && errorByLead.points?.length ? (
            <>
              <ResponsiveContainer width="100%" height={230}>
                <ComposedChart data={errorByLead.points}
                               margin={{ top: 6, right: 8, left: -14, bottom: 14 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="lead" stroke="rgba(255,255,255,0.3)"
                         tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 10 }}
                         tickFormatter={(h) => `+${h}h`} />
                  <YAxis stroke="rgba(255,255,255,0.3)" width={46}
                         tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 10 }}
                         tickFormatter={(v) => `${Math.round(v)}`} />
                  <Tooltip contentStyle={TOOLTIP_STYLE}
                           labelFormatter={(h) => `+${h} h`}
                           formatter={(v, n) => (n === 'members'
                             ? [v, 'members still forecasting a storm']
                             : [v == null ? '—' : `${v} km`, n])} />
                  <Legend wrapperStyle={{ fontSize: 10, color: 'rgba(255,255,255,0.6)' }} />
                  {/* The member range, so the mean is not read as the forecast. */}
                  <Area type="monotone" dataKey="p90_km" name="p10–p90"
                        stroke="none" fill="rgba(111,177,255,0.16)" />
                  <Area type="monotone" dataKey="p10_km" name=" "
                        stroke="none" fill="#0f1923" />
                  <Line type="monotone" dataKey="mean_km" name="error"
                        stroke="#ff9f6f" strokeWidth={2} dot={false}
                        connectNulls={false} />
                  <Line type="monotone" dataKey="spread_km" name="spread"
                        stroke="#6fb1ff" strokeWidth={2} strokeDasharray="4 3"
                        dot={false} />
                  {/* Hidden from the plot, present in the tooltip: the count is
                      needed to read any point honestly but shares no axis with
                      kilometres. */}
                  <Line dataKey="members" name="members" stroke="none"
                        dot={false} activeDot={false} legendType="none" />
                  {/* Where the observation record stops. The error line simply
                      ending would otherwise read as the forecast ending. */}
                  {errorByLead.last_verified_lead != null
                    && errorByLead.last_verified_lead
                       < errorByLead.points[errorByLead.points.length - 1].lead && (
                    <ReferenceLine x={errorByLead.last_verified_lead}
                                   stroke="rgba(255,255,255,0.35)"
                                   strokeDasharray="2 3"
                                   label={{ value: 'truth ends', fill: 'rgba(255,255,255,0.45)',
                                            fontSize: 9, position: 'insideTopRight' }} />
                  )}
                </ComposedChart>
              </ResponsiveContainer>
              <div style={{ color: 'rgba(255,255,255,0.4)',
                            fontSize: t.fontSize.micro, marginTop: '6px',
                            lineHeight: 1.5 }}>
                km, against lead time.
                {errorByLead.last_verified_lead != null
                  && ` Scored to +${errorByLead.last_verified_lead} h, where the best track stops.`}
                {/* The second denominator, and the one a line chart hides
                    hardest: members drop out as their forecast storm
                    dissipates, so a long lead can be scored over a handful.
                    Dorian's earliest ECMWF run falls from 28 members at +0 h to
                    4 at +144 h — the same line, a tenth of the ensemble. */}
                {(() => {
                  const pts = errorByLead.points;
                  const first = pts[0]?.members;
                  const last = pts[pts.length - 1]?.members;
                  if (first == null || last == null || last >= first) return null;
                  return (
                    <>
                      {' '}
                      <span style={{ color: 'rgba(255,200,140,0.85)' }}>
                        Members still forecasting a storm falls from {first} at
                        {' '}+{pts[0].lead} h to {last} at +{pts[pts.length - 1].lead} h,
                        so the long leads are scored over fewer.
                      </span>
                    </>
                  );
                })()}
              </div>
            </>
          ) : (
            <div style={{ color: 'rgba(255,255,255,0.35)', fontSize: t.fontSize.sm }}>
              {errorByLead ? 'No scored lead times for this run.' : 'Loading…'}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const TOOLTIP_STYLE = {
  background: '#1a2535',
  border: '1px solid rgba(255,255,255,0.15)',
  borderRadius: t.radius,
  color: 'white',
  fontSize: t.fontSize.sm,
};

const selectStyle = {
  display: 'block', marginTop: '4px', padding: '5px 8px',
  fontSize: t.fontSize.sm, fontWeight: t.fontWeight.semibold,
  background: 'rgba(255,255,255,0.06)',
  border: '1px solid rgba(255,255,255,0.18)', borderRadius: '6px',
  color: 'rgba(255,255,255,0.9)', cursor: 'pointer', outline: 'none',
  minWidth: '150px',
};

export default CycloneTab;
