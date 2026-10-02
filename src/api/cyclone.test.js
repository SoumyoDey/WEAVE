/**
 * Tests for the cyclone client, and mostly for `unwrapTrack`.
 *
 * The antimeridian is the whole reason that function exists, and it is the case
 * a mocked payload written by hand will not contain unless someone deliberately
 * puts it there — so it is put there, repeatedly. `TC_DATA_ACCESS.md` records
 * that the source data's own `mean_lon` is wrong for exactly this reason, out
 * by up to 213°, across 63 files and 15 storms.
 */
import { unwrapTrack, referenceLongitude } from './cyclone';

const lonsOf = (track) => track.map(([, lon]) => lon);

describe('unwrapTrack', () => {
  it('leaves a track that never crosses alone', () => {
    const pts = [{ lat: 20, lon: -70 }, { lat: 21, lon: -72 }, { lat: 22, lon: -75 }];
    expect(lonsOf(unwrapTrack(pts))).toEqual([-70, -72, -75]);
  });

  it('carries a westward crossing past -180 instead of jumping to +180', () => {
    // Four degrees of travel. Un-unwrapped this is a 356-degree jump, which
    // Leaflet draws as a line back across the entire map.
    const pts = [{ lat: -20, lon: -178 }, { lat: -20, lon: 179 }, { lat: -20, lon: 176 }];
    expect(lonsOf(unwrapTrack(pts))).toEqual([-178, -181, -184]);
  });

  it('carries an eastward crossing past +180', () => {
    const pts = [{ lat: 20, lon: 178 }, { lat: 20, lon: -179 }, { lat: 20, lon: -176 }];
    expect(lonsOf(unwrapTrack(pts))).toEqual([178, 181, 184]);
  });

  it('keeps every step the true distance, which is the actual invariant', () => {
    // Stated as a property rather than as expected numbers: no consecutive pair
    // may be more than 180 apart, because no real 6-hourly step is.
    const pts = [{ lat: 0, lon: 170 }, { lat: 0, lon: 175 }, { lat: 0, lon: -180 },
                 { lat: 0, lon: -175 }, { lat: 0, lon: -170 }];
    const lons = lonsOf(unwrapTrack(pts));
    for (let i = 1; i < lons.length; i += 1) {
      expect(Math.abs(lons[i] - lons[i - 1])).toBeLessThanOrEqual(180);
    }
  });

  it('puts every member in the same world copy when given one reference', () => {
    // Unwrapping each member independently is the bug one level up: the tracks
    // scatter across world copies and the storm renders as two clusters.
    const a = [{ lat: 0, lon: 179 }, { lat: 0, lon: -179 }];
    const b = [{ lat: 0, lon: -179 }, { lat: 0, lon: -177 }];
    const ref = 179;
    const [ua, ub] = [unwrapTrack(a, ref), unwrapTrack(b, ref)];
    expect(lonsOf(ua)).toEqual([179, 181]);
    expect(lonsOf(ub)).toEqual([181, 183]);
  });

  it('accepts bare [lat, lon] pairs as well as objects', () => {
    expect(lonsOf(unwrapTrack([[0, 179], [0, -179]]))).toEqual([179, 181]);
  });

  it('handles an empty track without throwing', () => {
    expect(unwrapTrack([])).toEqual([]);
  });
});

describe('referenceLongitude', () => {
  it('takes the first member point', () => {
    expect(referenceLongitude({ members: [{ points: [{ lat: 1, lon: 150 }] }] })).toBe(150);
  });

  it('falls back to the best track when no member has a point', () => {
    expect(referenceLongitude({ members: [], best_track: [{ lat: 1, lon: -40 }] })).toBe(-40);
  });

  it('is null when there is nothing to anchor to, rather than 0', () => {
    // 0 is a real longitude in the Gulf of Guinea; null means "no anchor".
    expect(referenceLongitude({ members: [], best_track: [] })).toBeNull();
    expect(referenceLongitude(null)).toBeNull();
  });
});
