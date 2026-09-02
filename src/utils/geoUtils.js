/**
 * Coordinate labels with a hemisphere suffix.
 *
 * A signed number and a hemisphere letter say the same thing twice, and when
 * they disagree the letter wins in the reader's head: "-83.6°E" reads as
 * eastern longitude, and it is 83.6 degrees WEST. Every drawn region in this
 * app was labelled that way, because MetricPanel hard-coded °N/°E while these
 * two lived unexported inside AnalysisTab. All the loaded data is in the
 * western hemisphere, so the string was wrong every time it was shown.
 *
 * Shared here so there is one implementation to be right.
 */
export const fmtLat = (v, p = 3) => {
  const n = parseFloat(v);
  return Number.isFinite(n) ? `${Math.abs(n).toFixed(p)}°${n >= 0 ? 'N' : 'S'}` : '—';
};

export const fmtLon = (v, p = 3) => {
  const n = parseFloat(v);
  return Number.isFinite(n) ? `${Math.abs(n).toFixed(p)}°${n >= 0 ? 'E' : 'W'}` : '—';
};

/**
 * Ray-casting point-in-polygon test.
 * polygon: array of [lat, lon] pairs
 */
export const pointInPolygon = (lat, lon, polygon) => {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i][1], yi = polygon[i][0];
    const xj = polygon[j][1], yj = polygon[j][0];
    const intersect = ((yi > lat) !== (yj > lat)) &&
      (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
};
