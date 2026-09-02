/**
 * Tests for the geometry and coordinate helpers.
 *
 * `fmtLat`/`fmtLon` live here because MetricPanel hard-coded °N/°E while an
 * identical pair sat unexported inside AnalysisTab, and the hard-coded copy
 * labelled every western longitude East. One implementation, tested once.
 */
import { fmtLat, fmtLon, pointInPolygon } from './geoUtils';

describe('fmtLat / fmtLon', () => {
  it.each([
    [35, '35.000°N'], [-35, '35.000°S'], [0, '0.000°N'], [90, '90.000°N'], [-90, '90.000°S'],
  ])('formats latitude %p as %p', (v, want) => expect(fmtLat(v)).toBe(want));

  it.each([
    [-75.5, '75.500°W'], [75.5, '75.500°E'], [0, '0.000°E'], [180, '180.000°E'], [-180, '180.000°W'],
  ])('formats longitude %p as %p', (v, want) => expect(fmtLon(v)).toBe(want));

  it('never emits a sign and a hemisphere at once', () => {
    // The bug this replaced: "-83.6°E" says west with the number and east with
    // the letter, and the letter is what a reader believes.
    for (const v of [-83.6, -0.1, -180, 12.3]) {
      expect(fmtLon(v)).not.toContain('-');
      expect(fmtLat(v)).not.toContain('-');
    }
  });

  it('honours the precision argument', () => {
    expect(fmtLat(35.12345, 1)).toBe('35.1°N');
    expect(fmtLon(-75.98765, 0)).toBe('76°W');
  });

  it('accepts numeric strings, as the API returns them', () => {
    expect(fmtLat('36.5')).toBe('36.500°N');
    expect(fmtLon('-75.25')).toBe('75.250°W');
  });

  it('returns a dash rather than NaN for a missing value', () => {
    // These render straight into a badge, so "NaN°N" would be the visible result.
    for (const bad of [undefined, null, '', 'abc', NaN]) {
      expect(fmtLat(bad)).toBe('—');
      expect(fmtLon(bad)).toBe('—');
    }
  });
});

describe('pointInPolygon', () => {
  // A unit square, as [lat, lon] pairs.
  const square = [[0, 0], [0, 10], [10, 10], [10, 0]];

  it('finds an interior point', () => {
    expect(pointInPolygon(5, 5, square)).toBe(true);
  });

  it.each([[15, 5], [5, 15], [-5, 5], [5, -5]])(
    'rejects a point outside at (%p, %p)', (lat, lon) => {
      expect(pointInPolygon(lat, lon, square)).toBe(false);
    });

  it('handles a concave polygon, where a bounding box would not', () => {
    // An L shape: the notch is inside the bounding box and outside the polygon.
    const L = [[0, 0], [0, 10], [4, 10], [4, 4], [10, 4], [10, 0]];
    expect(pointInPolygon(2, 2, L)).toBe(true);    // in the vertical arm
    expect(pointInPolygon(8, 2, L)).toBe(true);    // in the horizontal arm
    expect(pointInPolygon(8, 8, L)).toBe(false);   // in the notch
  });

  it('is false for a degenerate polygon', () => {
    expect(pointInPolygon(5, 5, [])).toBe(false);
    expect(pointInPolygon(5, 5, [[0, 0], [0, 10]])).toBe(false);
  });
});
