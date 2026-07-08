import { getDynamicColorRGB } from '../utils/colorUtils';

/**
 * Draws the IDW-interpolated forecast field onto a canvas overlaid on the map.
 *
 * @param {L.Map}   map
 * @param {Array}   data          - point array from the API
 * @param {string}  colormapName  - key of COLORMAPS
 * @param {boolean} isStdDev
 * @param {{ min: number, max: number }} range
 * @param {{ canvasRef: React.MutableRefObject,
 *           drawFnRef: React.MutableRefObject,
 *           uncertaintyModeRef: React.MutableRefObject }} refs
 */
export const drawOnMap = (map, data, colormapName, isStdDev, range, refs, options = {}) => {
  const { canvasRef, drawFnRef, uncertaintyModeRef } = refs;
  const { flipColormap = false, gridOpacity = 1 } = options;

  if (!map || !map._loaded) {
    setTimeout(() => drawOnMap(map, data, colormapName, isStdDev, range, refs, options), 200);
    return;
  }

  // Remove the previous canvas
  canvasRef.current?.remove();
  canvasRef.current = null;

  const canvas = document.createElement('canvas');
  map.getContainer().appendChild(canvas);
  canvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;z-index:420';
  canvas.style.opacity = String(Math.min(Math.max(gridOpacity, 0), 1));
  canvasRef.current = canvas;

  // Hide when an uncertainty overlay is active
  if (uncertaintyModeRef.current !== null) canvas.style.display = 'none';

  const influenceRadius    = 60;
  const influenceRadiusSq  = influenceRadius * influenceRadius;
  const pixelSize          = 2;

  // Project data points once per draw call (map units don't change during a
  // single frame, only between redraws triggered by move/zoom).
  let rafId = null;

  const draw = () => {
    if (!map?._loaded) return;
    const size = map.getSize();
    if (!size || size.x <= 0 || size.y <= 0) return;

    canvas.width  = size.x;
    canvas.height = size.y;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Project all data points to screen coords once.
    const spatialData = data.map(p => {
      try {
        const pt = map.latLngToContainerPoint([parseFloat(p.lat), parseFloat(p.lon)]);
        return {
          x: pt.x, y: pt.y,
          value: p.speed !== undefined ? parseFloat(p.speed) : parseFloat(p.value),
          lat: parseFloat(p.lat), lon: parseFloat(p.lon),
        };
      } catch { return null; }
    }).filter(Boolean);

    const allLats = spatialData.map(p => p.lat);
    const allLons = spatialData.map(p => p.lon);
    const topLeft     = map.latLngToContainerPoint([Math.max(...allLats), Math.min(...allLons)]);
    const bottomRight = map.latLngToContainerPoint([Math.min(...allLats), Math.max(...allLons)]);

    const tempCanvas = document.createElement('canvas');
    tempCanvas.width  = Math.ceil(size.x / pixelSize);
    tempCanvas.height = Math.ceil(size.y / pixelSize);
    if (tempCanvas.width <= 0 || tempCanvas.height <= 0) return;

    const tempCtx   = tempCanvas.getContext('2d');
    const imageData = tempCtx.createImageData(tempCanvas.width, tempCanvas.height);
    const buf       = imageData.data;

    for (let py = 0; py < tempCanvas.height; py++) {
      for (let px = 0; px < tempCanvas.width; px++) {
        const screenX = px * pixelSize;
        const screenY = py * pixelSize;
        if (screenX < topLeft.x || screenX > bottomRight.x ||
            screenY < topLeft.y || screenY > bottomRight.y) continue;

        let weightedSum = 0, totalWeight = 0;
        for (const point of spatialData) {
          const dx  = point.x - screenX;
          const dy  = point.y - screenY;
          const d2  = dx * dx + dy * dy;
          if (d2 < influenceRadiusSq) {
            // Avoid sqrt — compare squared distance, compute weight from d2.
            // weight = 1/d^4 = 1/(d2^2). For d < 1px use weight=1.
            const weight = d2 < 1 ? 1 : 1 / (d2 * d2);
            weightedSum += point.value * weight;
            totalWeight += weight;
          }
        }

        if (totalWeight > 0) {
          const interpolated = weightedSum / totalWeight;
          const { r, g, b, a } = getDynamicColorRGB(Math.max(interpolated, 0), range, colormapName, flipColormap);
          const idx = (py * tempCanvas.width + px) * 4;
          buf[idx]   = r;
          buf[idx+1] = g;
          buf[idx+2] = b;
          buf[idx+3] = a;
        }
      }
    }

    tempCtx.putImageData(imageData, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.filter = 'blur(1.5px)';
    ctx.drawImage(tempCanvas, 0, 0, size.x, size.y);
    ctx.filter = 'none';
  };

  // Throttle redraws during pan/zoom to one frame per animation frame —
  // map fires dozens of 'move' events per pan, we only need one redraw.
  const scheduleDraw = () => {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(() => { rafId = null; draw(); });
  };

  // Deregister previous draw listener so stale closures don't accumulate
  if (drawFnRef.current) {
    map.off('move', drawFnRef.current);
    map.off('zoom', drawFnRef.current);
  }
  drawFnRef.current = scheduleDraw;

  draw();
  map.on('move', scheduleDraw);
  map.on('zoom', scheduleDraw);
};
