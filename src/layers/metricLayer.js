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

  // Tile size based on a representative lat/lon step of 0.25°
  const p1 = map.latLngToContainerPoint([35, -80]);
  const p2 = map.latLngToContainerPoint([35.25, -79.75]);
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
