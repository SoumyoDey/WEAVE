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

/**
 * Converts a forecast lead-time hour to a short human-readable date string.
 * Base date: 2025-09-08 00:00 UTC
 */
export const formatDate = (hour) => {
  const baseDate     = new Date('2025-09-08T00:00:00');
  const forecastDate = new Date(baseDate.getTime() + hour * 60 * 60 * 1000);
  return `${forecastDate.toLocaleDateString('en-US', { weekday: 'short' })}, ${forecastDate.getMonth() + 1}/${forecastDate.getDate()}`;
};
