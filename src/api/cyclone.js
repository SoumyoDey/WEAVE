/**
 * Client for the tropical-cyclone track endpoints.
 *
 * `NEXT_STEPS.md` §37, `TC_TAB_DESIGN.md`. These are a different shape from the
 * rest of the API — not a field on the analysis grid but one polyline per
 * ensemble member — so they have their own client rather than extending
 * `forecastApi`.
 *
 * **`nominal_members` is carried through every call and is not decoration.** A
 * member that forecast no cyclone has no track, so the number of tracks
 * returned is the number of members that *developed* a storm, not the number
 * that ran. ECMWF runs carry anywhere from 28 to 51. Drawing 28 lines and
 * letting a reader take that for the ensemble understates the spread in the
 * direction that matters most — whether the storm happens at all — so the
 * caller is expected to print both numbers.
 */
import { API_BASE } from './base';

const json = async (url) => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
};

/** Storms and runs available, optionally filtered to a canonical basin. */
export const fetchCyclones = (basin) =>
  json(`${API_BASE}/cyclones${basin ? `?basin=${encodeURIComponent(basin)}` : ''}`);

/** Every member's track for one storm from one centre, plus the best track. */
export const fetchCycloneTracks = ({ storm, centre, init }) => {
  const q = new URLSearchParams({ storm, centre });
  if (init) q.set('init', init);
  return json(`${API_BASE}/cyclone/tracks?${q}`);
};

/**
 * The strike-probability field: per cell, the fraction of the ensemble passing
 * within `radiusKm`.
 *
 * `radiusKm` is passed explicitly rather than defaulted here, because it
 * changes the answer and a caller that forgets it should be visible in the
 * request rather than silently taking whatever the server prefers.
 */
export const fetchStrikeProbability = ({ storm, centre, init, radiusKm, hourMin, hourMax }) => {
  const q = new URLSearchParams({ storm, centre });
  if (init) q.set('init', init);
  if (radiusKm != null) q.set('radius_km', String(radiusKm));
  if (hourMin != null) q.set('hour_min', String(hourMin));
  if (hourMax != null) q.set('hour_max', String(hourMax));
  return json(`${API_BASE}/cyclone/strike-probability?${q}`);
};

/**
 * Colour for a probability in [0, 1].
 *
 * Sequential and perceptually ordered, and deliberately NOT one of the metric
 * palettes in `constants.js`: those encode calibrated band edges for spread and
 * error, and a probability has no such calibration — reusing one would imply
 * thresholds nobody measured. Low values stay translucent so the tracks beneath
 * remain legible, which is the point of drawing both.
 */
export const strikeColour = (value) => {
  const v = Math.max(0, Math.min(1, value));
  if (v < 0.1)  return 'rgba(80,140,255,0.18)';
  if (v < 0.25) return 'rgba(90,190,235,0.28)';
  if (v < 0.5)  return 'rgba(120,220,170,0.38)';
  if (v < 0.75) return 'rgba(240,210,100,0.50)';
  return 'rgba(240,120,70,0.62)';
};

/**
 * Track error and ensemble spread against lead time, for one run.
 *
 * Recomputed server-side from the loaded positions rather than read from the
 * source's `distance_km` — see `TC_TAB_DESIGN.md` §7. Of the four derived
 * columns shipped with the data, one reproduced exactly and one was out by up
 * to 213°, and nothing distinguished them by inspection.
 */
export const fetchErrorByLead = ({ storm, centre, init }) => {
  const q = new URLSearchParams({ storm, centre });
  if (init) q.set('init', init);
  return json(`${API_BASE}/cyclone/error-by-lead?${q}`);
};

/**
 * Rewrite a track's longitudes so it is continuous across the antimeridian.
 *
 * Leaflet draws a polyline through increasing longitude, so a step from +179 to
 * −179 — two degrees apart on the Earth — is drawn as a 358° line straight back
 * across the entire map. Every Northwest and Southwest Pacific storm does this,
 * and this archive is mostly Pacific.
 *
 * **Unwrapping rather than splitting**, which was the first attempt. Splitting
 * the line into segments stops the streak and leaves two further problems:
 * `fitBounds` still receives points at both −180 and +180, so it zooms to the
 * whole world, and the storm appears as two clusters on opposite edges. Looking
 * at GITA showed exactly that. Unwrapping fixes all three at once: longitudes
 * run continuously past ±180, Leaflet renders them in the adjacent world copy,
 * and the bounds are tight.
 *
 * Every member is unwrapped against the same `reference`, so they land in the
 * same world copy as each other. Unwrapping each independently would scatter
 * them across copies and reintroduce the problem one level up.
 *
 * This is the same hazard that made the source data's `mean_lon` wrong — an
 * arithmetic mean of longitudes, out by up to 213° near the dateline — in the
 * rendering layer. The two are independent: fixing one does nothing for the
 * other.
 */
export const unwrapTrack = (points, reference = null) => {
  const out = [];
  let previous = reference;
  for (const p of points) {
    const lat = p.lat ?? p[0];
    let lon = p.lon ?? p[1];
    if (previous !== null) {
      while (lon - previous > 180) lon -= 360;
      while (previous - lon > 180) lon += 360;
    }
    out.push([lat, lon]);
    previous = lon;
  }
  return out;
};

/** The longitude everything else is unwrapped against: the first point drawn. */
export const referenceLongitude = (data) => {
  const first = (data?.members ?? [])[0]?.points?.[0] ?? (data?.best_track ?? [])[0];
  return first ? (first.lon ?? first[1]) : null;
};

export default fetchCyclones;
