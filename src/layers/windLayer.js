// ── Wind arrows ───────────────────────────────────────────────────────────────

/**
 * Draws static wind arrow glyphs on a canvas overlay.
 * @param {L.Map}   map
 * @param {Array}   data           - wind point array (each pt has .u .v .speed)
 * @param {{ current: HTMLCanvasElement | null }} arrowsCanvasRef
 */
export const drawWindArrows = (map, data, arrowsCanvasRef) => {
  if (!map?._loaded) return;
  arrowsCanvasRef.current?.remove();

  const canvas = document.createElement('canvas');
  map.getContainer().appendChild(canvas);
  canvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;z-index:450';
  arrowsCanvasRef.current = canvas;

  const drawArrows = () => {
    const size = map.getSize();
    if (!size || size.x <= 0) return;
    canvas.width  = size.x;
    canvas.height = size.y;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const gridSize = 40;

    for (let x = 0; x < size.x; x += gridSize) {
      for (let y = 0; y < size.y; y += gridSize) {
        let nearest = null, minDist = Infinity;
        for (const point of data) {
          try {
            const sp = map.latLngToContainerPoint([point.lat, point.lon]);
            const dist = Math.sqrt((sp.x - x) ** 2 + (sp.y - y) ** 2);
            if (dist < minDist && dist < gridSize * 1.5) { minDist = dist; nearest = point; }
          } catch { continue; }
        }
        if (!nearest?.u) continue;
        const { u, v } = nearest;
        const speed = nearest.speed || Math.sqrt(u * u + v * v);
        if (speed < 0.5) continue;
        const angle  = Math.atan2(v, u);
        const length = Math.min(speed * 3, gridSize * 0.8);
        const sn     = Math.min(speed / 20, 1);
        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(angle);
        ctx.strokeStyle = ctx.fillStyle = `rgba(255,255,255,${0.6 + sn * 0.4})`;
        ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(length, 0); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(length, 0); ctx.lineTo(length - 6, -3); ctx.lineTo(length - 6, 3);
        ctx.closePath(); ctx.fill();
        ctx.restore();
      }
    }
  };

  drawArrows();
  map.on('move', drawArrows);
  map.on('zoom', drawArrows);
};

// ── Streamlines ───────────────────────────────────────────────────────────────

/**
 * Starts an animated streamline overlay.
 * @param {L.Map}   map
 * @param {Array}   data              - wind point array
 * @param {{ current: number | null }} animationFrameRef
 * @param {{ current: boolean }}       showWindLinesRef
 */
export const startStreamlines = (map, data, animationFrameRef, showWindLinesRef) => {
  if (!map) return;
  stopStreamlines(animationFrameRef);

  const container = map.getContainer();
  const lats = data.map(p => parseFloat(p.lat));
  const lons = data.map(p => parseFloat(p.lon));
  const minLat = Math.min(...lats), maxLat = Math.max(...lats);
  const minLon = Math.min(...lons), maxLon = Math.max(...lons);

  const getBounds = () => {
    const tl  = map.latLngToContainerPoint([maxLat, minLon]);
    const br  = map.latLngToContainerPoint([minLat, maxLon]);
    const pad = 8;
    return { xMin: tl.x + pad, xMax: br.x - pad, yMin: tl.y + pad, yMax: br.y - pad };
  };

  const buildWindGrid = (gridRes = 8) => {
    const size = map.getSize();
    const cols = Math.ceil(size.x / gridRes);
    const rows = Math.ceil(size.y / gridRes);
    const grid = new Float32Array(cols * rows * 2);
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const ll = map.containerPointToLatLng([col * gridRes, row * gridRes]);
        let best = null, bestD = Infinity;
        for (const pt of data) {
          const d = (pt.lat - ll.lat) ** 2 + (pt.lon - ll.lng) ** 2;
          if (d < bestD) { bestD = d; best = pt; }
        }
        const idx = (row * cols + col) * 2;
        grid[idx]   = best?.u ?? 0;
        grid[idx+1] = best?.v ?? 0;
      }
    }
    return { grid, cols, rows, gridRes };
  };

  const sampleWind = (wg, sx, sy) => {
    const col = Math.round(sx / wg.gridRes);
    const row = Math.round(sy / wg.gridRes);
    if (col < 0 || col >= wg.cols || row < 0 || row >= wg.rows) return { u: 0, v: 0 };
    const idx = (row * wg.cols + col) * 2;
    return { u: wg.grid[idx], v: wg.grid[idx + 1] };
  };

  const traceLine = (wg, bounds, x0, y0, steps = 120, stepLen = 3) => {
    if (x0 < bounds.xMin || x0 > bounds.xMax || y0 < bounds.yMin || y0 > bounds.yMax) return [];
    const pts = [{ x: x0, y: y0 }];
    let x = x0, y = y0;
    for (let i = 0; i < steps; i++) {
      const { u, v } = sampleWind(wg, x, y);
      const spd = Math.sqrt(u * u + v * v);
      if (spd < 0.3) break;
      const nx = x + (u / spd) * stepLen;
      const ny = y - (v / spd) * stepLen;
      if (nx < bounds.xMin || nx > bounds.xMax || ny < bounds.yMin || ny > bounds.yMax) break;
      pts.push({ x: nx, y: ny });
      x = nx; y = ny;
    }
    return pts;
  };

  const linesCanvas = document.createElement('canvas');
  linesCanvas.id    = 'streamlines-canvas';
  linesCanvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;z-index:460';
  container.appendChild(linesCanvas);

  const dotCanvas = document.createElement('canvas');
  dotCanvas.id    = 'streamlines-dots';
  dotCanvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;z-index:461';
  container.appendChild(dotCanvas);

  const drawLines = (allPts) => {
    const size = map.getSize();
    linesCanvas.width = size.x; linesCanvas.height = size.y;
    const ctx = linesCanvas.getContext('2d');
    ctx.clearRect(0, 0, size.x, size.y);
    for (const pts of allPts) {
      if (pts.length < 3) continue;
      const grad = ctx.createLinearGradient(pts[0].x, pts[0].y, pts[pts.length-1].x, pts[pts.length-1].y);
      grad.addColorStop(0,    'rgba(255,255,255,0)');
      grad.addColorStop(0.25, 'rgba(255,255,255,0.75)');
      grad.addColorStop(0.75, 'rgba(255,255,255,0.75)');
      grad.addColorStop(1,    'rgba(255,255,255,0)');
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
      ctx.strokeStyle = grad; ctx.lineWidth = 1.4; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      ctx.stroke();
      const ai = Math.floor(pts.length * 0.6);
      if (ai > 0) {
        const p0 = pts[ai - 1], p1 = pts[ai];
        const angle = Math.atan2(p1.y - p0.y, p1.x - p0.x);
        ctx.save(); ctx.translate(p1.x, p1.y); ctx.rotate(angle);
        ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(-7, -3); ctx.lineTo(-7, 3); ctx.closePath();
        ctx.fillStyle = 'rgba(255,255,255,0.8)'; ctx.fill(); ctx.restore();
      }
    }
  };

  let dotOffset = 0;
  const animateDots = (allPts) => {
    if (!showWindLinesRef.current) return;
    const size = map.getSize();
    dotCanvas.width = size.x; dotCanvas.height = size.y;
    const ctx = dotCanvas.getContext('2d');
    ctx.clearRect(0, 0, size.x, size.y);
    dotOffset = (dotOffset + 0.6) % 40;
    for (const pts of allPts) {
      const arcLen = [0];
      for (let i = 1; i < pts.length; i++) {
        const dx = pts[i].x - pts[i-1].x, dy = pts[i].y - pts[i-1].y;
        arcLen.push(arcLen[i-1] + Math.sqrt(dx * dx + dy * dy));
      }
      const total = arcLen[arcLen.length - 1];
      if (total < 10) continue;
      let d = dotOffset % 40;
      while (d < total) {
        let seg = 0;
        while (seg < arcLen.length - 1 && arcLen[seg + 1] < d) seg++;
        if (seg >= pts.length - 1) { d += 40; continue; }
        const t  = (d - arcLen[seg]) / (arcLen[seg + 1] - arcLen[seg]);
        const px = pts[seg].x + t * (pts[seg + 1].x - pts[seg].x);
        const py = pts[seg].y + t * (pts[seg + 1].y - pts[seg].y);
        ctx.beginPath(); ctx.arc(px, py, 2, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(255,255,255,0.9)'; ctx.fill();
        d += 40;
      }
    }
    animationFrameRef.current = requestAnimationFrame(() => animateDots(allPts));
  };

  const rebuild = () => {
    const wg      = buildWindGrid();
    const bounds  = getBounds();
    const size    = map.getSize();
    const spacing = 28;
    const allPts  = [];
    for (let sx = spacing / 2; sx < size.x; sx += spacing) {
      for (let sy = spacing / 2; sy < size.y; sy += spacing) {
        const pts = traceLine(wg, bounds, sx, sy);
        if (pts.length >= 3) allPts.push(pts);
      }
    }
    drawLines(allPts);
    if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
    animateDots(allPts);
  };

  rebuild();
  map.on('move', rebuild);
  map.on('zoom', rebuild);
};

/**
 * Stops and removes all streamline canvases + animation frame.
 */
export const stopStreamlines = (animationFrameRef) => {
  if (animationFrameRef?.current) {
    cancelAnimationFrame(animationFrameRef.current);
    animationFrameRef.current = null;
  }
  document.getElementById('streamlines-canvas')?.remove();
  document.getElementById('streamlines-dots')?.remove();
};
