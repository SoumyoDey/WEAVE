/**
 * Renders the spatial-metric colour overlay on the Leaflet map container.
 * @param {L.Map}   map
 * @param {Array}   points     - [{ lat, lon, value }]
 * @param {string}  metricKey  - key into METRIC_CONFIG
 * @param {Array}   metricConfig - the METRIC_CONFIG array
 */
export const renderMetricCanvas = (map, points, metricKey, metricConfig) => {
  if (!map) return;
  const container = map.getContainer();
  let canvas = container.querySelector('#metric-overlay-canvas');
  if (!canvas) {
    canvas = document.createElement('canvas');
    canvas.id = 'metric-overlay-canvas';
    canvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;z-index:450';
    container.appendChild(canvas);
  }
  canvas.width  = container.offsetWidth;
  canvas.height = container.offsetHeight;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Derive tile size from the actual data grid spacing rather than a hardcoded
  // 0.25° assumption — if the data is on a coarser grid the tiles would otherwise
  // leave visible gaps between them.
  let gridStep = 0.25; // fallback
  if (points.length >= 2) {
    const lats = [...new Set(points.map(p => Math.round(parseFloat(p.lat) * 1000) / 1000))].sort((a, b) => a - b);
    const lons = [...new Set(points.map(p => Math.round(parseFloat(p.lon) * 1000) / 1000))].sort((a, b) => a - b);
    const latStep = lats.length >= 2 ? lats[1] - lats[0] : gridStep;
    const lonStep = lons.length >= 2 ? lons[1] - lons[0] : gridStep;
    gridStep = Math.max(latStep, lonStep);
  }
  const refLat = 35, refLon = -80;
  const p1 = map.latLngToContainerPoint([refLat, refLon]);
  const p2 = map.latLngToContainerPoint([refLat + gridStep, refLon + gridStep]);
  const tileW = Math.max(3, Math.abs(p2.x - p1.x));
  const tileH = Math.max(3, Math.abs(p2.y - p1.y));

  const metricCfg = metricConfig.find(m => m.key === metricKey);
  const colorFn   = metricCfg ? metricCfg.colorFn : () => null;

  for (const pt of points) {
    const color = colorFn(pt.value);
    if (!color) continue;
    const cp = map.latLngToContainerPoint([pt.lat, pt.lon]);
    ctx.fillStyle = color;
    ctx.fillRect(cp.x - tileW / 2, cp.y - tileH / 2, tileW, tileH);
  }
};

/**
 * Removes the metric overlay canvas from the map container.
 */
export const clearMetricCanvas = (map) => {
  if (!map) return;
  map.getContainer().querySelector('#metric-overlay-canvas')?.remove();
};
