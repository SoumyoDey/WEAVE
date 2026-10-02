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

import { fetchCyclones, fetchCycloneTracks, unwrapTrack, referenceLongitude } from '../api/cyclone';
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
  const [data, setData]       = useState(null);
  const [error, setError]     = useState(null);
  const [loading, setLoading] = useState(false);
  // The map is built in an effect; the draw effect below must wait for it.
  // Without this the two race, and whichever loses leaves an empty map with
  // a populated header — which is exactly how this first rendered.
  const [mapReady, setMapReady] = useState(false);

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

  // ── The tracks ─────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!storm || !centre) return;
    let alive = true;
    setLoading(true);
    setError(null);
    fetchCycloneTracks({ storm, centre })
      .then((d) => { if (alive) { setData(d); setLoading(false); } })
      .catch((e) => { if (alive) { setError(e.message); setLoading(false); } });
    return () => { alive = false; };
  }, [storm, centre]);

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
    const best = unwrapTrack(data.best_track || [], ref);
    if (best.length > 1) {
      L.polyline(best, BEST_CASING).addTo(layer);
      L.polyline(best, BEST_STYLE).addTo(layer);
    }
    bounds.push(...best);
    if (bounds.length) map.fitBounds(L.latLngBounds(bounds).pad(0.15));
  }, [data, mapReady]);

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
