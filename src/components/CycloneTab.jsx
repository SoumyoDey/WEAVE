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

import { fetchCyclones, fetchCycloneTracks, fetchStrikeProbability,
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

export function CycloneTab({ active }) {
  const mapRef   = useRef(null);
  const divRef   = useRef(null);
  const layerRef = useRef(null);

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

  // Reset the initialisation whenever the storm or centre changes, because an
  // init from another run is not a valid choice here and would 404.
  useEffect(() => {
    if (!storm || !centre) return;
    const options = initsFor(storm, centre).map((r) => r.init_time);
    if (!options.includes(init)) setInit(options[0] ?? null);
  }, [storm, centre, init, initsFor]);

  // ── The tracks ─────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!storm || !centre || !init) return;
    let alive = true;
    setLoading(true);
    setError(null);
    fetchCycloneTracks({ storm, centre, init })
      .then((d) => { if (alive) { setData(d); setLoading(false); } })
      .catch((e) => { if (alive) { setError(e.message); setLoading(false); } });
    return () => { alive = false; };
  }, [storm, centre, init]);

  // ── The strike-probability field ───────────────────────────────────────────
  useEffect(() => {
    if (!showStrike || !storm || !centre || !init) { setStrike(null); return; }
    let alive = true;
    fetchStrikeProbability({ storm, centre, init, radiusKm })
      .then((d) => { if (alive) setStrike(d); })
      .catch((e) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [showStrike, storm, centre, init, radiusKm]);

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
  useEffect(() => {
    if (active && mapRef.current) setTimeout(() => mapRef.current.invalidateSize(), 0);
  }, [active]);

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
    if (bounds.length) map.fitBounds(L.latLngBounds(bounds).pad(0.15));
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
          <select aria-label="Initialisation" value={init ?? ''}
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

      <div ref={divRef} style={{ flex: 1, minHeight: 0 }} />
    </div>
  );
}

const selectStyle = {
  display: 'block', marginTop: '4px', padding: '5px 8px',
  fontSize: t.fontSize.sm, fontWeight: t.fontWeight.semibold,
  background: 'rgba(255,255,255,0.06)',
  border: '1px solid rgba(255,255,255,0.18)', borderRadius: '6px',
  color: 'rgba(255,255,255,0.9)', cursor: 'pointer', outline: 'none',
  minWidth: '150px',
};

export default CycloneTab;
