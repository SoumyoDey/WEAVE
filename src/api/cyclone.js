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
