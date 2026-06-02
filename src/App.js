import React, { useState, useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { ChevronLeft, Info, Menu, SlidersHorizontal } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';

const generateHours = () => {
  const hours = [];
  for (let h = 0; h <= 360; h += 6) hours.push(h);
  return hours;
};
const ALL_HOURS = generateHours();

const MODELS = {
  AIFS: { name: 'AIFS', color: '#3498db', hours: ALL_HOURS, hasEnsemble: true, ensembleCount: 50 },
  GEFS: { name: 'GEFS', color: '#e74c3c', hours: ALL_HOURS, hasEnsemble: true, ensembleCount: 30 },
  UKMO: { name: 'UKMO', color: '#2ecc71', hours: ALL_HOURS, hasEnsemble: true, ensembleCount: 18 }
};

const COLORMAPS = {
  'Default': { name: 'Default', type: 'sequential', colors: ['#FFFFCC', '#C8F0C8', '#A0E6E6', '#70C8D2', '#5098C8', '#3264AA', '#001E6E', '#000050'] },
  'Viridis': { name: 'Viridis', type: 'sequential', colors: ['#440154', '#414487', '#2a788e', '#22a884', '#7ad151', '#fde725'] },
  'Plasma':  { name: 'Plasma',  type: 'sequential', colors: ['#0d0887', '#6a00a8', '#b12a90', '#e16462', '#fca636', '#f0f921'] },
  'Inferno': { name: 'Inferno', type: 'sequential', colors: ['#000004', '#420a68', '#932667', '#dd513a', '#fca50a', '#fcffa4'] },
  'Turbo':   { name: 'Turbo',   type: 'sequential', colors: ['#30123b', '#4662d7', '#36a9e1', '#13eb6b', '#a7fc3c', '#faba39', '#e8443a'] },
  'Cool':    { name: 'Cool',    type: 'sequential', colors: ['#00ffff', '#00d4ff', '#00aaff', '#0080ff', '#0055ff', '#002bff', '#0000ff'] },
  'Warm':    { name: 'Warm',    type: 'sequential', colors: ['#ffff00', '#ffdd00', '#ffbb00', '#ff9900', '#ff7700', '#ff5500', '#ff0000'] },
  'RdYlBu':  { name: 'RdYlBu',  type: 'diverging',  colors: ['#a50026', '#d73027', '#f46d43', '#fdae61', '#fee090', '#ffffbf', '#e0f3f8', '#abd9e9', '#74add1', '#4575b4', '#313695'] },
  'Spectral':{ name: 'Spectral',type: 'diverging',  colors: ['#9e0142', '#d53e4f', '#f46d43', '#fdae61', '#fee08b', '#ffffbf', '#e6f598', '#abdda4', '#66c2a5', '#3288bd', '#5e4fa2'] }
};

// 4×4 bivariate color matrix — equal discrimination at every uncertainty level
const BIVARIATE_COLORS = [
  ['#f0f0f0', '#b4d9cc', '#5dc8a4', '#00916e'],
  ['#e8d9f0', '#a8c8d4', '#4db8a8', '#008878'],
  ['#d4b8e0', '#9cb4c8', '#3da090', '#007060'],
  ['#c8a8d8', '#a0a8c4', '#6898a8', '#3a7890'],
];

// 4×4 VSUP color matrix for MAP rendering — colors converge at high uncertainty rows
// Row 0 (low uncert): 4 distinct colors. Row 3 (high): all nearly identical → suppresses value signal
const VSUP_COLORS = [
  ['#eef2e4', '#68d4b0', '#009a78', '#005a48'],  // row 0: low uncertainty — full discrimination
  ['#d8caec', '#82bcc8', '#28a090', '#007068'],  // row 1: slightly muted
  ['#c0a8e0', '#9ab4c8', '#80b8c4', '#60a8b8'],  // row 2: bins converging
  ['#beb0d4', '#bab4d0', '#b8b4d0', '#b6b2ce'],  // row 3: high uncertainty — near-identical (fully suppressed)
];

function App() {
  const [activeTab, setActiveTab]               = useState('visualization');
  const [selectedModel, setSelectedModel]       = useState('AIFS');
  const [selectedHour, setSelectedHour]         = useState(6);
  const [selectedMember, setSelectedMember]     = useState('mean');
  const [selectedVariable, setSelectedVariable] = useState('precipitation');
  const [showData, setShowData]                 = useState(false);
  const [stats, setStats]                       = useState(null);
  const [dataRange, setDataRange]               = useState({ min: 0, max: 100 });
  const [loading, setLoading]                   = useState(false);
  const [error, setError]                       = useState('');
  const [menuOpen, setMenuOpen]                 = useState(false);
  const [showAbout, setShowAbout]               = useState(false);
  const [selectedColormap, setSelectedColormap] = useState('Default');
  const [showWindArrows, setShowWindArrows]     = useState(false);
  const [showWindLines, setShowWindLines]       = useState(false);
  const [showUncertainty, setShowUncertainty]   = useState(false);
  const [showBivariate, setShowBivariate]       = useState(false);
  const [showFanChart, setShowFanChart]         = useState(false);
  const [selectedTexture, setSelectedTexture]   = useState('none');
  const [bivariateRanges, setBivariateRanges]   = useState(null);
  const [rightPanelOpen, setRightPanelOpen]     = useState(false);
  const [clickedPoint, setClickedPoint]         = useState(null);
  const [timeseriesData, setTimeseriesData]     = useState(null);
  const [timeseriesLoading, setTimeseriesLoading] = useState(false);

  const mapRef               = useRef(null);
  const mapInstanceRef       = useRef(null);
  const dataRef              = useRef(null);
  const canvasRef            = useRef(null);
  const isInitializedRef     = useRef(false);
  const arrowsCanvasRef      = useRef(null);
  const animationFrameRef    = useRef(null);
  const showWindLinesRef     = useRef(false);
  const uncertaintyCanvasRef = useRef(null);
  const uncertaintyLayerRef  = useRef(null);
  const bivariateLayerRef    = useRef(null);
  const clickMarkerRef       = useRef(null);
  const textureCanvasRef     = useRef(null);
  const textureDataRef       = useRef(null);

  const currentModel = MODELS[selectedModel];

  // ── Map init ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (isInitializedRef.current || !mapRef.current) return;
    isInitializedRef.current = true;
    setTimeout(() => {
      const map = L.map(mapRef.current, { center: [37, -82.5], zoom: 6, zoomControl: false });
      const zoomCtrl = L.control.zoom({ position: 'topleft' }).addTo(map);
      // Position below the menu button (top:12 + height:44 + gap:12 = 68px)
      const zoomEl = zoomCtrl.getContainer();
      zoomEl.style.marginTop = '68px';
      zoomEl.style.marginLeft = '12px';
      L.tileLayer('https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap, &copy; CartoDB' }).addTo(map);
      L.tileLayer('https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png',   { attribution: '' }).addTo(map);
      mapInstanceRef.current = map;
      setTimeout(() => map.invalidateSize(), 100);
    }, 100);
  }, []);

  useEffect(() => {
    if (activeTab === 'visualization' && mapInstanceRef.current)
      setTimeout(() => mapInstanceRef.current.invalidateSize(), 50);
  }, [activeTab]);

  useEffect(() => { if (mapInstanceRef.current) loadDataForHour(); }, // eslint-disable-line react-hooks/exhaustive-deps
    [selectedHour, selectedModel, selectedMember, selectedVariable]);

  useEffect(() => {
    if (dataRef.current?.length > 0)
      setTimeout(() => drawOnMap(dataRef.current, selectedMember === 'std', dataRange), 100);
  }, [selectedColormap]); // eslint-disable-line

  useEffect(() => {
    showWindLinesRef.current = showWindLines;
    if (selectedVariable === 'wind' && dataRef.current?.length > 0 && mapInstanceRef.current) {
      if (showWindArrows) drawWindArrows(dataRef.current);
      else { arrowsCanvasRef.current?.remove(); arrowsCanvasRef.current = null; }
      if (showWindLines) startStreamlines(dataRef.current);
      else stopStreamlines();
    } else {
      arrowsCanvasRef.current?.remove();
      arrowsCanvasRef.current = null;
      stopStreamlines();
    }
  }, [showWindArrows, showWindLines, selectedVariable, selectedHour, selectedModel, selectedMember]); // eslint-disable-line

  useEffect(() => {
    if (showUncertainty && dataRef.current?.length > 0 && mapInstanceRef.current) {
      if (canvasRef.current) canvasRef.current.style.display = 'none';
      drawUncertaintyBoxes();
    } else {
      if (canvasRef.current) canvasRef.current.style.display = 'block';
      stopUncertainty();
    }
  }, [showUncertainty, selectedHour, selectedModel, selectedVariable]); // eslint-disable-line

  // ── Bivariate / Fan Chart useEffect ─────────────────────────────────────────
  useEffect(() => {
    if ((showBivariate || showFanChart) && mapInstanceRef.current) {
      if (canvasRef.current) canvasRef.current.style.display = 'none';
      drawBivariateLayer(showFanChart ? buildVsupMatrix() : BIVARIATE_COLORS);
    } else {
      if (canvasRef.current) canvasRef.current.style.display = 'block';
      stopBivariate();
    }
  }, [showBivariate, showFanChart, selectedHour, selectedModel, selectedVariable, selectedColormap]); // eslint-disable-line

  useEffect(() => {
    if (mapInstanceRef.current) loadTextureData();
  }, [selectedTexture, selectedHour, selectedModel, selectedVariable]); // eslint-disable-line

  // ── Data fetch ────────────────────────────────────────────────────────────────
  const loadDataForHour = async () => {
    if (!mapInstanceRef.current) return;
    setLoading(true); setError('');
    try {
      const params   = new URLSearchParams({ model: currentModel.name, variable: selectedVariable, hour: selectedHour, member: selectedMember });
      const endpoint = selectedVariable === 'wind' ? 'wind-data' : 'forecast-data';
      const response = await fetch(`http://localhost:5000/api/${endpoint}?${params}`);
      if (!response.ok) throw new Error(`API error: ${response.status}`);
      const data = await response.json();
      if (!Array.isArray(data) || data.length === 0) throw new Error('No data returned');

      dataRef.current = data;
      const values = selectedVariable === 'wind' ? data.map(d => parseFloat(d.speed)) : data.map(d => parseFloat(d.value));
      const minVal = Math.min(...values.filter(v => v > 0)) || 0.01;
      const maxVal = Math.max(...values) || 100;

      setDataRange({ min: minVal, max: maxVal });
      setStats({ total: values.length, average: (values.reduce((a, b) => a + b, 0) / values.length).toFixed(2), max: maxVal.toFixed(2), min: minVal.toFixed(2) });
      setShowData(true); setLoading(false);

      setTimeout(() => {
        drawOnMap(data, selectedMember === 'std', { min: minVal, max: maxVal });
        if (selectedVariable === 'wind') {
          if (showWindArrows) drawWindArrows(data);
          if (showWindLines) { stopStreamlines(); startStreamlines(data); }
        }
        if (showUncertainty) drawUncertaintyBoxes();
        if (showBivariate)   drawBivariateLayer(BIVARIATE_COLORS);
        if (showFanChart)    drawBivariateLayer(buildVsupMatrix());
      }, 300);
    } catch (err) {
      console.error('Load error:', err);
      setError(`Could not load: ${err.message}`); setLoading(false); setShowData(false);
    }
  };

  // Returns a CSS gradient that matches the visual appearance of colors on the light basemap.
  // Composites each color against white using the same opacity formula as getDynamicColor.
  const getLegendGradient = (colormapName) => {
    const colors = COLORMAPS[colormapName].colors;
    const stops = colors.map((hex, i) => {
      const normalized = i / (colors.length - 1);
      const opacity = 0.5 + normalized * 0.3;
      const r = parseInt(hex.slice(1, 3), 16);
      const g = parseInt(hex.slice(3, 5), 16);
      const b = parseInt(hex.slice(5, 7), 16);
      // Pre-composite against white (#FFF) — same result as rendering on the light CartoDB basemap
      const cr = Math.round(r * opacity + 255 * (1 - opacity));
      const cg = Math.round(g * opacity + 255 * (1 - opacity));
      const cb = Math.round(b * opacity + 255 * (1 - opacity));
      return `rgb(${cr},${cg},${cb})`;
    });
    return `linear-gradient(to top, ${stops.join(', ')})`;
  };

  // ── IDW map render ────────────────────────────────────────────────────────────
  const drawOnMap = (data, isStdDev = false, range = { min: 0, max: 100 }) => {
    if (!mapInstanceRef.current || !mapInstanceRef.current._loaded) {
      setTimeout(() => drawOnMap(data, isStdDev, range), 200); return;
    }
    canvasRef.current?.remove(); canvasRef.current = null;
    const canvas = document.createElement('canvas');
    mapInstanceRef.current.getContainer().appendChild(canvas);
    canvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;z-index:400';
    canvasRef.current = canvas;
    if (showUncertainty || showBivariate || showFanChart) canvas.style.display = 'none';

    // Texture overlay canvas (drawn on top of everything)
    textureCanvasRef.current?.remove(); textureCanvasRef.current = null;
    const textureCanvas = document.createElement('canvas');
    mapInstanceRef.current.getContainer().appendChild(textureCanvas);
    textureCanvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;z-index:500';
    textureCanvasRef.current = textureCanvas;

    const getDynamicColor = (value) => {
      const colors = COLORMAPS[selectedColormap].colors;
      const normalized = Math.min(value / range.max, 1);
      if (normalized < 0.01) return 'rgba(255,255,255,0)';
      const seg = colors.length - 1;
      const ss  = 1 / seg;
      const si  = Math.min(Math.floor(normalized / ss), seg - 1);
      const t   = (normalized - si * ss) / ss;
      const c1  = colors[si], c2 = colors[si + 1];
      const r   = Math.round(parseInt(c1.slice(1,3),16) + (parseInt(c2.slice(1,3),16) - parseInt(c1.slice(1,3),16)) * t);
      const g   = Math.round(parseInt(c1.slice(3,5),16) + (parseInt(c2.slice(3,5),16) - parseInt(c1.slice(3,5),16)) * t);
      const b   = Math.round(parseInt(c1.slice(5,7),16) + (parseInt(c2.slice(5,7),16) - parseInt(c1.slice(5,7),16)) * t);
      return `rgba(${r},${g},${b},${0.5 + normalized * 0.3})`;
    };

    const draw = () => {
      if (!mapInstanceRef.current?._loaded) return;
      const size = mapInstanceRef.current.getSize();
      if (!size || size.x <= 0 || size.y <= 0) return;
      canvas.width = size.x; canvas.height = size.y;
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const spatialData = data.map(p => {
        try {
          const pt = mapInstanceRef.current.latLngToContainerPoint([parseFloat(p.lat), parseFloat(p.lon)]);
          return { x: pt.x, y: pt.y, value: p.speed !== undefined ? parseFloat(p.speed) : parseFloat(p.value), lat: parseFloat(p.lat), lon: parseFloat(p.lon) };
        } catch { return null; }
      }).filter(Boolean);

      const pixelSize = 2, influenceRadius = 60;
      const tempCanvas = document.createElement('canvas');
      tempCanvas.width  = Math.ceil(size.x / pixelSize);
      tempCanvas.height = Math.ceil(size.y / pixelSize);
      if (tempCanvas.width <= 0 || tempCanvas.height <= 0) return;
      const tempCtx   = tempCanvas.getContext('2d');
      const imageData = tempCtx.createImageData(tempCanvas.width, tempCanvas.height);

      const allLats = spatialData.map(p => p.lat);
      const allLons = spatialData.map(p => p.lon);
      const topLeft     = mapInstanceRef.current.latLngToContainerPoint([Math.max(...allLats), Math.min(...allLons)]);
      const bottomRight = mapInstanceRef.current.latLngToContainerPoint([Math.min(...allLats), Math.max(...allLons)]);

      for (let py = 0; py < tempCanvas.height; py++) {
        for (let px = 0; px < tempCanvas.width; px++) {
          const screenX = px * pixelSize, screenY = py * pixelSize;
          if (screenX < topLeft.x || screenX > bottomRight.x || screenY < topLeft.y || screenY > bottomRight.y) continue;
          let weightedSum = 0, totalWeight = 0;
          for (const point of spatialData) {
            const dx = point.x - screenX, dy = point.y - screenY;
            const distance = Math.sqrt(dx * dx + dy * dy);
            if (distance < influenceRadius) {
              const weight = distance < 1 ? 1 : 1 / (distance * distance * distance * distance);
              weightedSum += point.value * weight; totalWeight += weight;
            }
          }
          const interpolatedValue = totalWeight > 0 ? weightedSum / totalWeight : 0;
          const color = getDynamicColor(Math.max(interpolatedValue, 0));
          const rgba  = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/);
          if (rgba) {
            const idx = (py * tempCanvas.width + px) * 4;
            imageData.data[idx]   = parseInt(rgba[1]);
            imageData.data[idx+1] = parseInt(rgba[2]);
            imageData.data[idx+2] = parseInt(rgba[3]);
            imageData.data[idx+3] = totalWeight > 0 ? (rgba[4] ? parseFloat(rgba[4]) * 255 : 255) : 100;
          }
        }
      }
      tempCtx.putImageData(imageData, 0, 0);
      ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
      ctx.filter = 'blur(1.5px)';
      ctx.drawImage(tempCanvas, 0, 0, size.x, size.y);
      ctx.filter = 'none';
    };

    draw();
    mapInstanceRef.current.on('move', draw);
    mapInstanceRef.current.on('zoom', draw);
  };

  // ── Wind arrows ───────────────────────────────────────────────────────────────
  const drawWindArrows = (data) => {
    if (!mapInstanceRef.current?._loaded) return;
    arrowsCanvasRef.current?.remove();
    const canvas = document.createElement('canvas');
    mapInstanceRef.current.getContainer().appendChild(canvas);
    canvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;z-index:450';
    arrowsCanvasRef.current = canvas;

    const drawArrows = () => {
      const size = mapInstanceRef.current.getSize();
      if (!size || size.x <= 0) return;
      canvas.width = size.x; canvas.height = size.y;
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const gridSize = 40;
      for (let x = 0; x < size.x; x += gridSize) {
        for (let y = 0; y < size.y; y += gridSize) {
          let nearest = null, minDist = Infinity;
          for (const point of data) {
            try {
              const sp = mapInstanceRef.current.latLngToContainerPoint([point.lat, point.lon]);
              const dist = Math.sqrt((sp.x - x) ** 2 + (sp.y - y) ** 2);
              if (dist < minDist && dist < gridSize * 1.5) { minDist = dist; nearest = point; }
            } catch { continue; }
          }
          if (!nearest?.u) continue;
          const u = nearest.u, v = nearest.v;
          const speed = nearest.speed || Math.sqrt(u * u + v * v);
          if (speed < 0.5) continue;
          const angle = Math.atan2(v, u);
          const length = Math.min(speed * 3, gridSize * 0.8);
          const sn = Math.min(speed / 20, 1);
          ctx.save(); ctx.translate(x, y); ctx.rotate(angle);
          ctx.strokeStyle = ctx.fillStyle = `rgba(255,255,255,${0.6 + sn * 0.4})`;
          ctx.lineWidth = 2;
          ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(length, 0); ctx.stroke();
          ctx.beginPath(); ctx.moveTo(length, 0); ctx.lineTo(length - 6, -3); ctx.lineTo(length - 6, 3); ctx.closePath(); ctx.fill();
          ctx.restore();
        }
      }
    };
    drawArrows();
    mapInstanceRef.current.on('move', drawArrows);
    mapInstanceRef.current.on('zoom', drawArrows);
  };

  // ── Streamlines ───────────────────────────────────────────────────────────────
  const startStreamlines = (data) => {
    if (!mapInstanceRef.current) return;
    stopStreamlines();
    const map = mapInstanceRef.current;
    const container = map.getContainer();

    const lats = data.map(p => parseFloat(p.lat));
    const lons = data.map(p => parseFloat(p.lon));
    const minLat = Math.min(...lats), maxLat = Math.max(...lats);
    const minLon = Math.min(...lons), maxLon = Math.max(...lons);

    const getBounds = () => {
      const tl = map.latLngToContainerPoint([maxLat, minLon]);
      const br = map.latLngToContainerPoint([minLat, maxLon]);
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
          const idx   = (row * cols + col) * 2;
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
    linesCanvas.id = 'streamlines-canvas';
    linesCanvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;z-index:460';
    container.appendChild(linesCanvas);

    const dotCanvas = document.createElement('canvas');
    dotCanvas.id = 'streamlines-dots';
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
      const wg     = buildWindGrid();
      const bounds = getBounds();
      const size   = map.getSize();
      const spacing = 28;
      const allPts = [];
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

  const stopStreamlines = () => {
    if (animationFrameRef.current) { cancelAnimationFrame(animationFrameRef.current); animationFrameRef.current = null; }
    document.getElementById('streamlines-canvas')?.remove();
    document.getElementById('streamlines-dots')?.remove();
  };

  // ── Map click → fetch timeseries ─────────────────────────────────────────────
  useEffect(() => {
    if (!mapInstanceRef.current) return;
    const map = mapInstanceRef.current;
    const handleClick = (e) => {
      const { lat, lng } = e.latlng;
      setClickedPoint({ lat: lat.toFixed(3), lon: lng.toFixed(3) });
      if (clickMarkerRef.current) map.removeLayer(clickMarkerRef.current);
      clickMarkerRef.current = L.circleMarker([lat, lng], {
        radius: 7, fillColor: '#e74c3c', color: 'white', weight: 2, fillOpacity: 1
      }).addTo(map);
    };
    map.on('click', handleClick);
    return () => map.off('click', handleClick);
  }, [mapInstanceRef.current]); // eslint-disable-line

  useEffect(() => {
    if (!clickedPoint) return;
    fetchTimeseries(clickedPoint.lat, clickedPoint.lon);
  }, [clickedPoint, selectedModel, selectedVariable]); // eslint-disable-line

  const fetchTimeseries = async (lat, lon) => {
    setTimeseriesLoading(true); setTimeseriesData(null);
    try {
      const params = new URLSearchParams({ model: currentModel.name, variable: selectedVariable, lat, lon });
      const res  = await fetch(`http://localhost:5000/api/point-timeseries?${params}`);
      const data = await res.json();
      if (Array.isArray(data) && data.length > 0) {
        const processed = data.map(d => ({
          hour:    d.hour,
          mean:    d.mean,
          p10:     d.p10,
          p90:     d.p90,
          p25:     d.p25,
          p75:     d.p75,
          band1Lo: Math.max(0, d.mean - d.std),
          band1Hi: d.mean + d.std,
          band2Lo: Math.max(0, d.mean - 2 * d.std),
          band2Hi: d.mean + 2 * d.std,
        }));
        setTimeseriesData(processed);
      }
    } catch (err) { console.error('Timeseries error:', err); }
    setTimeseriesLoading(false);
  };

  // ── Uncertainty boxes (VSup) — UNCHANGED from working version ─────────────────
  const drawUncertaintyBoxes = async () => {
    if (!mapInstanceRef.current?._loaded) return;
    if (uncertaintyLayerRef.current) {
      mapInstanceRef.current.removeLayer(uncertaintyLayerRef.current);
      uncertaintyLayerRef.current = null;
    }
    try {
      const endpoint = selectedVariable === 'wind' ? 'wind-data' : 'forecast-data';
      const [resMean, resStd] = await Promise.all([
        fetch(`http://localhost:5000/api/${endpoint}?${new URLSearchParams({ model: currentModel.name, variable: selectedVariable, hour: selectedHour, member: 'mean' })}`),
        fetch(`http://localhost:5000/api/${endpoint}?${new URLSearchParams({ model: currentModel.name, variable: selectedVariable, hour: selectedHour, member: 'std'  })}`)
      ]);
      const meanData = await resMean.json();
      const stdData  = await resStd.json();
      if (!Array.isArray(stdData) || stdData.length === 0) return;

      const meanLookup = {};
      if (Array.isArray(meanData)) {
        for (const pt of meanData)
          meanLookup[`${pt.lat}_${pt.lon}`] = parseFloat(selectedVariable === 'wind' ? pt.speed : pt.value);
      }

      const meanVals = Object.values(meanLookup).filter(v => !isNaN(v) && v > 0);
      const stdVals  = stdData.map(d => parseFloat(selectedVariable === 'wind' ? d.speed : d.value)).filter(v => !isNaN(v) && v >= 0);
      const meanMax  = Math.max(...meanVals) || 1;
      const stdMax   = Math.max(...stdVals)  || 1;

      const vsupColor = (meanVal, stdVal) => {
        const normVal = Math.min(meanVal / meanMax, 1);
        const normStd = Math.min(stdVal  / stdMax,  1);
        const colors  = COLORMAPS[selectedColormap].colors;
        const seg = colors.length - 1;
        const ss  = 1 / seg;
        const mappedVal = 0.15 + normVal * 0.85;
        const si  = Math.min(Math.floor(mappedVal / ss), seg - 1);
        const t   = (mappedVal - si * ss) / ss;
        const c1  = colors[si], c2 = colors[si + 1];
        let r = Math.round(parseInt(c1.slice(1,3),16) + (parseInt(c2.slice(1,3),16) - parseInt(c1.slice(1,3),16)) * t);
        let g = Math.round(parseInt(c1.slice(3,5),16) + (parseInt(c2.slice(3,5),16) - parseInt(c1.slice(3,5),16)) * t);
        let b = Math.round(parseInt(c1.slice(5,7),16) + (parseInt(c2.slice(5,7),16) - parseInt(c1.slice(5,7),16)) * t);
        const grey = 210, blend = normStd * 0.85;
        r = Math.round(r + (grey - r) * blend);
        g = Math.round(g + (grey - g) * blend);
        b = Math.round(b + (grey - b) * blend);
        return `rgba(${r},${g},${b},${0.75 - normStd * 0.3})`;
      };

      // smaller box = more uncertain
      const minDeg = 0.15, maxDeg = 0.6;
      const sizeScale = (stdVal) => {
        if (stdMax === 0) return (minDeg + maxDeg) / 2;
        const t = Math.sqrt(Math.min(stdVal / stdMax, 1));
        return maxDeg - t * (maxDeg - minDeg);
      };

      const cellMap = {};
      for (const pt of stdData) {
        const cellLat = Math.round(parseFloat(pt.lat));
        const cellLon = Math.round(parseFloat(pt.lon));
        const key = `${cellLat}_${cellLon}`;
        if (!cellMap[key]) cellMap[key] = pt;
      }

      const layerGroup = L.layerGroup();
      for (const pt of Object.values(cellMap)) {
        const lat     = parseFloat(pt.lat);
        const lon     = parseFloat(pt.lon);
        const stdVal  = parseFloat(selectedVariable === 'wind' ? pt.speed : pt.value);
        const meanVal = meanLookup[`${pt.lat}_${pt.lon}`] ?? 0;
        if (isNaN(stdVal) || isNaN(meanVal)) continue;
        const half  = sizeScale(stdVal);
        const color = vsupColor(meanVal, stdVal);
        L.rectangle([[lat - half, lon - half], [lat + half, lon + half]],
          { fillColor: color, color: color, fillOpacity: 1, weight: 0.3, opacity: 0.4, interactive: false }
        ).addTo(layerGroup);
      }
      layerGroup.addTo(mapInstanceRef.current);
      uncertaintyLayerRef.current = layerGroup;
    } catch (err) { console.error('Uncertainty fetch error:', err); }
  };

  const stopUncertainty = () => {
    if (uncertaintyLayerRef.current && mapInstanceRef.current) {
      mapInstanceRef.current.removeLayer(uncertaintyLayerRef.current);
      uncertaintyLayerRef.current = null;
    }
    uncertaintyCanvasRef.current?.remove();
    uncertaintyCanvasRef.current = null;
  };

  // ── Builds a 4×4 VSUP color matrix from the currently selected colormap ────────
  // rowIdx 0 = low uncertainty (full color), rowIdx 3 = high uncertainty (mostly neutral)
  // colIdx 0..3 = low..high forecast value — mirrors the legend's cmapColor + suppress logic
  const buildVsupMatrix = () => {
    const cols    = COLORMAPS[selectedColormap].colors;
    const neutral = [180, 175, 185];
    const lerp    = (t) => {
      const seg = cols.length - 1;
      const si  = Math.min(Math.floor(t * seg), seg - 1);
      const st  = t * seg - si;
      const c1  = cols[si], c2 = cols[Math.min(si + 1, seg)];
      const r1 = parseInt(c1.slice(1,3),16), g1 = parseInt(c1.slice(3,5),16), b1 = parseInt(c1.slice(5,7),16);
      const r2 = parseInt(c2.slice(1,3),16), g2 = parseInt(c2.slice(3,5),16), b2 = parseInt(c2.slice(5,7),16);
      return [Math.round(r1+(r2-r1)*st), Math.round(g1+(g2-g1)*st), Math.round(b1+(b2-b1)*st)];
    };
    return Array.from({ length: 4 }, (_, rowIdx) => {
      const suppress = (rowIdx / 3) * 0.72;  // rowIdx 0 → 0, rowIdx 3 → 0.72
      return Array.from({ length: 4 }, (_, colIdx) => {
        const t        = colIdx / 3;
        const [r,g,b]  = lerp(Math.min(t, 0.999));
        return `rgb(${Math.round(r*(1-suppress)+neutral[0]*suppress)},${Math.round(g*(1-suppress)+neutral[1]*suppress)},${Math.round(b*(1-suppress)+neutral[2]*suppress)})`;
      });
    });
  };

  // ── Texture Overlay (hatching lines) ─────────────────────────────────────────
  const drawTextureOverlay = () => {
    const canvas = textureCanvasRef.current;
    const map    = mapInstanceRef.current;
    if (!canvas || !map || !textureDataRef.current) return;

    const container = map.getContainer();
    canvas.width  = container.clientWidth;
    canvas.height = container.clientHeight;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (selectedTexture === 'none') return;

    const { points, stdMax } = textureDataRef.current;
    const SPACING = 7; // fixed line spacing (px) — same for all cells for clean look
    ctx.strokeStyle = 'rgba(80,80,80,0.55)';
    ctx.lineWidth   = 0.8;

    for (const { lat, lon, stdVal, half } of points) {
      const normStd = Math.min(stdVal / stdMax, 1);
      if (normStd < 0.1) continue; // skip near-zero uncertainty

      const tl = map.latLngToContainerPoint([lat + half, lon - half]);
      const br = map.latLngToContainerPoint([lat - half, lon + half]);
      const cw = br.x - tl.x, ch = br.y - tl.y;
      if (cw <= 0 || ch <= 0) continue;

      ctx.save();
      // Higher uncertainty → more visible/opaque lines (continuous gradient)
      ctx.globalAlpha = 0.15 + normStd * 0.7;
      ctx.beginPath();
      ctx.rect(tl.x, tl.y, cw, ch);
      ctx.clip();

      // Globally aligned lines: phase based on absolute position so adjacent
      // cells share the same line grid — no arrow artefact at boundaries
      const phase = ((tl.x - tl.y) % SPACING + SPACING) % SPACING;
      const startX = tl.x - ch - phase;
      for (let x = startX; x <= tl.x + cw + SPACING; x += SPACING) {
        ctx.beginPath();
        ctx.moveTo(x,      tl.y);
        ctx.lineTo(x + ch, tl.y + ch);
        ctx.stroke();
      }
      ctx.restore();
    }
    ctx.globalAlpha = 1;
  };

  const loadTextureData = async () => {
    const canvas = textureCanvasRef.current;
    if (!canvas) return;
    if (selectedTexture === 'none') {
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      return;
    }
    try {
      const endpoint = selectedVariable === 'wind' ? 'wind-data' : 'forecast-data';
      const res  = await fetch(`http://localhost:5000/api/${endpoint}?${new URLSearchParams({
        model: currentModel.name, variable: selectedVariable, hour: selectedHour, member: 'std'
      })}`);
      const stdData = await res.json();
      if (!Array.isArray(stdData) || !stdData.length) return;

      const stdVals = stdData.map(pt => parseFloat(selectedVariable === 'wind' ? pt.speed : pt.value)).filter(v => !isNaN(v) && v >= 0);
      const stdMax  = Math.max(...stdVals) || 1;
      const lats    = [...new Set(stdData.map(p => Math.round(parseFloat(p.lat) * 10) / 10))].sort((a,b) => a-b);
      const spacing = lats.length > 1 ? Math.abs(lats[1] - lats[0]) : 0.5;
      const half    = spacing * 0.5;

      textureDataRef.current = {
        points: stdData.map(pt => ({
          lat:    parseFloat(pt.lat),
          lon:    parseFloat(pt.lon),
          stdVal: parseFloat(selectedVariable === 'wind' ? pt.speed : pt.value),
          half
        })),
        stdMax
      };
      drawTextureOverlay();

      // Redraw on map move/zoom
      mapInstanceRef.current.off('moveend zoomend', drawTextureOverlay);
      mapInstanceRef.current.on('moveend zoomend',  drawTextureOverlay);
    } catch (err) { console.error('Texture error:', err); }
  };

  // ── Bivariate Choropleth ──────────────────────────────────────────────────────
  const drawBivariateLayer = async (colorMatrix = BIVARIATE_COLORS) => {
    if (!mapInstanceRef.current?._loaded) return;
    stopBivariate();
    try {
      const endpoint = selectedVariable === 'wind' ? 'wind-data' : 'forecast-data';
      const [resMean, resStd] = await Promise.all([
        fetch(`http://localhost:5000/api/${endpoint}?${new URLSearchParams({ model: currentModel.name, variable: selectedVariable, hour: selectedHour, member: 'mean' })}`),
        fetch(`http://localhost:5000/api/${endpoint}?${new URLSearchParams({ model: currentModel.name, variable: selectedVariable, hour: selectedHour, member: 'std'  })}`)
      ]);
      const meanData = await resMean.json();
      const stdData  = await resStd.json();
      if (!Array.isArray(meanData) || !Array.isArray(stdData)) return;

      // Build lookups
      const meanLookup = {}, stdLookup = {};
      for (const pt of meanData) meanLookup[`${pt.lat}_${pt.lon}`] = parseFloat(selectedVariable === 'wind' ? pt.speed : pt.value);
      for (const pt of stdData)  stdLookup[`${pt.lat}_${pt.lon}`]  = parseFloat(selectedVariable === 'wind' ? pt.speed : pt.value);

      const meanVals = Object.values(meanLookup).filter(v => !isNaN(v) && v >= 0);
      const stdVals  = Object.values(stdLookup).filter(v => !isNaN(v) && v >= 0);
      if (!meanVals.length || !stdVals.length) return;

      const meanMax = Math.max(...meanVals) || 1;
      const stdMax  = Math.max(...stdVals)  || 1;

      setBivariateRanges({ meanMax, stdMax });

      const bin = (val, max) => Math.min(3, Math.floor((Math.min(val, max) / max) * 4));

      // Auto-detect grid spacing from data
      const lats = meanData.map(p => parseFloat(p.lat)).sort((a,b) => a - b);
      const uniqueLats = [...new Set(lats.map(l => Math.round(l * 10) / 10))];
      const spacing = uniqueLats.length > 1 ? Math.abs(uniqueLats[1] - uniqueLats[0]) : 0.5;
      const half = spacing * 0.5;

      const layerGroup = L.layerGroup();
      for (const pt of meanData) {
        const lat     = parseFloat(pt.lat);
        const lon     = parseFloat(pt.lon);
        const key     = `${pt.lat}_${pt.lon}`;
        const meanVal = meanLookup[key] ?? 0;
        const stdVal  = stdLookup[key]  ?? 0;
        const colIdx  = bin(meanVal, meanMax);  // X = mean value
        const rowIdx  = bin(stdVal,  stdMax);   // Y = uncertainty
        const color   = colorMatrix[rowIdx][colIdx];
        L.rectangle(
          [[lat - half, lon - half], [lat + half, lon + half]],
          { fillColor: color, color: 'transparent', fillOpacity: 0.85, weight: 0, interactive: false }
        ).addTo(layerGroup);
      }
      layerGroup.addTo(mapInstanceRef.current);
      bivariateLayerRef.current = layerGroup;
    } catch (err) { console.error('Bivariate error:', err); }
  };

  const stopBivariate = () => {
    if (bivariateLayerRef.current && mapInstanceRef.current) {
      mapInstanceRef.current.removeLayer(bivariateLayerRef.current);
      bivariateLayerRef.current = null;
    }
  };

  // ── Helpers ───────────────────────────────────────────────────────────────────
  const getMemberOptions = () => {
    if (!currentModel.hasEnsemble) return [];
    const options = [
      { value: 'mean', label: '📊 Ensemble Mean' },
      { value: 'std',  label: '📈 Uncertainty (Std Dev)' }
    ];
    for (let i = 0; i < currentModel.ensembleCount; i++)
      options.push({ value: i.toString(), label: `Member ${i + 1}` });
    return options;
  };

  const formatDate = (hour) => {
    const baseDate     = new Date('2025-09-08T00:00:00');
    const forecastDate = new Date(baseDate.getTime() + hour * 60 * 60 * 1000);
    return `${forecastDate.toLocaleDateString('en-US', { weekday: 'short' })}, ${forecastDate.getMonth() + 1}/${forecastDate.getDate()}`;
  };

  const TAB_BAR_H = 48;

  return (
    <div style={{ position: 'relative', height: '100vh', fontFamily: 'Arial', overflow: 'hidden' }}>

      {/* Tab bar */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: TAB_BAR_H, background: 'rgba(22,33,44,0.98)', display: 'flex', alignItems: 'center', zIndex: 1100, boxShadow: '0 2px 8px rgba(0,0,0,0.35)', paddingLeft: '16px', gap: '4px' }}>
        <span style={{ color: 'white', fontWeight: '700', fontSize: '16px', marginRight: '16px', letterSpacing: '1px' }}>🌧️ WEAVE</span>
        {[['visualization','🗺 Visualization'], ['analysis','📊 Analysis']].map(([id, label]) => (
          <button key={id} onClick={() => setActiveTab(id)} style={{ padding: '6px 22px', fontSize: '13px', fontWeight: '600', border: 'none', borderRadius: '6px', cursor: 'pointer', transition: 'all 0.2s', background: activeTab === id ? 'rgba(255,255,255,0.15)' : 'transparent', color: activeTab === id ? 'white' : 'rgba(255,255,255,0.45)', borderBottom: activeTab === id ? '2px solid #3498db' : '2px solid transparent' }}>{label}</button>
        ))}
      </div>

      {/* ══ VISUALIZATION TAB ══ */}
      <div style={{ display: activeTab === 'visualization' ? 'block' : 'none', position: 'absolute', top: TAB_BAR_H, left: 0, right: 0, bottom: 0 }}>
        <div ref={mapRef} style={{ width: '100%', height: '100%', background: '#f5f5f5' }} />

        <button onClick={() => setMenuOpen(!menuOpen)} style={{ position: 'absolute', top: '12px', left: menuOpen ? '310px' : '12px', width: '44px', height: '44px', background: 'rgba(44,62,80,0.95)', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer', zIndex: 1002, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 12px rgba(0,0,0,0.3)', transition: 'left 0.3s ease' }}>
          {menuOpen ? <ChevronLeft size={22} /> : <Menu size={22} />}
        </button>

        <button onClick={() => setShowAbout(!showAbout)} style={{ position: 'absolute', top: '12px', right: '12px', width: '44px', height: '44px', background: showAbout ? 'rgba(231,76,60,0.95)' : 'rgba(52,152,219,0.95)', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer', zIndex: 1001, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 12px rgba(0,0,0,0.3)', transition: 'all 0.3s ease' }}>
          <Info size={22} />
        </button>

        {/* Right settings toggle button — sits below the "i" button */}
        <button onClick={() => setRightPanelOpen(!rightPanelOpen)} style={{ position: 'absolute', top: '68px', right: '12px', width: '44px', height: '44px', background: rightPanelOpen ? 'rgba(46,204,113,0.95)' : 'rgba(44,62,80,0.95)', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer', zIndex: 1001, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 12px rgba(0,0,0,0.3)', transition: 'all 0.3s ease' }}>
          <SlidersHorizontal size={20} />
        </button>

        {/* Right settings panel */}
        <div style={{ position: 'absolute', top: 0, right: rightPanelOpen ? '0' : '-300px', width: '280px', height: '100%', background: 'rgba(44,62,80,0.98)', color: 'white', boxShadow: '-4px 0 15px rgba(0,0,0,0.3)', transition: 'right 0.3s ease', zIndex: 1000, overflowY: 'auto' }}>
          <div style={{ padding: '20px' }}>
            <div style={{ marginBottom: '25px', paddingBottom: '15px', borderBottom: '2px solid rgba(255,255,255,0.1)', paddingTop: '56px' }}>
              <p style={{ margin: 0, fontSize: '12px', opacity: 0.7 }}>Display Settings</p>
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', fontSize: '11px', fontWeight: '600', marginBottom: '10px', opacity: 0.7, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Color Scheme</label>
              <select value={selectedColormap} onChange={e => setSelectedColormap(e.target.value)} style={{ width: '100%', padding: '10px', fontSize: '14px', border: '1px solid rgba(255,255,255,0.2)', borderRadius: '6px', background: 'rgba(255,255,255,0.1)', color: 'white', cursor: 'pointer' }}>
                {Object.keys(COLORMAPS).map(name => <option key={name} value={name} style={{ background: '#2c3e50' }}>{name}</option>)}
              </select>
              <div style={{ marginTop: '10px', height: '20px', borderRadius: '4px', background: `linear-gradient(to right, ${COLORMAPS[selectedColormap].colors.join(', ')})`, border: '1px solid rgba(255,255,255,0.2)' }} />
            </div>

            {selectedVariable === 'wind' && (
              <div style={{ marginBottom: '20px' }}>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: '600', marginBottom: '10px', opacity: 0.7, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Wind Direction</label>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {[{ state: showWindArrows, setter: setShowWindArrows, label: '↗ Arrows' }, { state: showWindLines, setter: setShowWindLines, label: '〰 Streamlines' }].map(({ state, setter, label }) => (
                    <label key={label} style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer', padding: '10px', background: 'rgba(255,255,255,0.05)', borderRadius: '6px', border: state ? '1px solid rgba(255,255,255,0.3)' : '1px solid transparent' }}>
                      <input type="checkbox" checked={state} onChange={e => setter(e.target.checked)} style={{ width: '18px', height: '18px', cursor: 'pointer' }} />
                      <span style={{ fontSize: '14px' }}>{label}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', fontSize: '11px', fontWeight: '600', marginBottom: '10px', opacity: 0.7, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Uncertainty</label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer', padding: '10px', background: 'rgba(255,255,255,0.05)', borderRadius: '6px', border: showUncertainty ? '1px solid rgba(255,255,255,0.3)' : '1px solid transparent' }}>
                  <input type="checkbox" checked={showUncertainty} onChange={e => setShowUncertainty(e.target.checked)} style={{ width: '18px', height: '18px', cursor: 'pointer' }} />
                  <div>
                    <div style={{ fontSize: '14px' }}>⬛ VSup Boxes</div>
                    <div style={{ fontSize: '11px', opacity: 0.5, marginTop: '2px' }}>Size + color = value + spread</div>
                  </div>
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer', padding: '10px', background: 'rgba(255,255,255,0.05)', borderRadius: '6px', border: showBivariate ? '1px solid rgba(255,255,255,0.3)' : '1px solid transparent' }}>
                  <input type="checkbox" checked={showBivariate} onChange={e => setShowBivariate(e.target.checked)} style={{ width: '18px', height: '18px', cursor: 'pointer' }} />
                  <div>
                    <div style={{ fontSize: '14px' }}>🟦 Bivariate Map</div>
                    <div style={{ fontSize: '11px', opacity: 0.5, marginTop: '2px' }}>4×4 color grid: value × uncertainty</div>
                  </div>
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer', padding: '10px', background: 'rgba(255,255,255,0.05)', borderRadius: '6px', border: showFanChart ? '1px solid rgba(255,255,255,0.3)' : '1px solid transparent' }}>
                  <input type="checkbox" checked={showFanChart} onChange={e => setShowFanChart(e.target.checked)} style={{ width: '18px', height: '18px', cursor: 'pointer' }} />
                  <div>
                    <div style={{ fontSize: '14px' }}>🌀 VSUP Fan</div>
                    <div style={{ fontSize: '11px', opacity: 0.5, marginTop: '2px' }}>Fan legend: value-suppressing palette</div>
                  </div>
                </label>
              </div>
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', fontSize: '11px', fontWeight: '600', marginBottom: '10px', opacity: 0.7, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Texture</label>
              <select value={selectedTexture} onChange={e => setSelectedTexture(e.target.value)}
                style={{ width: '100%', padding: '10px', fontSize: '14px', border: '1px solid rgba(255,255,255,0.2)', borderRadius: '6px', background: 'rgba(255,255,255,0.1)', color: 'white', cursor: 'pointer' }}>
                <option value="none"  style={{ background: '#2c3e50' }}>None</option>
                <option value="lines" style={{ background: '#2c3e50' }}>Lines</option>
              </select>
              {selectedTexture === 'lines' && (
                <div style={{ marginTop: '8px', fontSize: '11px', opacity: 0.6, lineHeight: '1.4' }}>
                  Denser hatching = higher uncertainty
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Side panel */}
        <div style={{ position: 'absolute', top: 0, left: menuOpen ? '0' : '-350px', width: '350px', height: '100%', background: 'rgba(44,62,80,0.98)', color: 'white', boxShadow: '4px 0 15px rgba(0,0,0,0.3)', transition: 'left 0.3s ease', zIndex: 1000, overflowY: 'auto' }}>
          <div style={{ padding: '20px' }}>
            <div style={{ marginBottom: '25px', paddingBottom: '15px', borderBottom: '2px solid rgba(255,255,255,0.1)', paddingTop: '56px' }}>
              <p style={{ margin: 0, fontSize: '12px', opacity: 0.7 }}>Forecast Controls</p>
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', fontSize: '11px', fontWeight: '600', marginBottom: '10px', opacity: 0.7, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Model</label>
              <div style={{ display: 'flex', gap: '8px' }}>
                {Object.entries(MODELS).map(([key, model]) => (
                  <button key={key} onClick={() => setSelectedModel(key)} style={{ flex: 1, padding: '10px 8px', fontSize: '13px', fontWeight: '600', border: selectedModel === key ? `2px solid ${model.color}` : '2px solid transparent', borderRadius: '6px', background: selectedModel === key ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.05)', color: selectedModel === key ? model.color : 'rgba(255,255,255,0.6)', cursor: 'pointer', transition: 'all 0.2s' }}>{model.name}</button>
                ))}
              </div>
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', fontSize: '11px', fontWeight: '600', marginBottom: '10px', opacity: 0.7, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Variable</label>
              <select value={selectedVariable} onChange={e => setSelectedVariable(e.target.value)} style={{ width: '100%', padding: '10px', fontSize: '14px', border: '1px solid rgba(255,255,255,0.2)', borderRadius: '6px', background: 'rgba(255,255,255,0.1)', color: 'white', cursor: 'pointer' }}>
                <option value="precipitation" style={{ background: '#2c3e50' }}>💧 Precipitation</option>
                <option value="wind"          style={{ background: '#2c3e50' }}>🌬️ Wind Speed</option>
              </select>
            </div>

            {currentModel.hasEnsemble && (
              <div style={{ marginBottom: '20px' }}>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: '600', marginBottom: '10px', opacity: 0.7, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Ensemble Member</label>
                <select value={selectedMember} onChange={e => setSelectedMember(e.target.value)} style={{ width: '100%', padding: '10px', fontSize: '14px', border: '1px solid rgba(255,255,255,0.2)', borderRadius: '6px', background: 'rgba(255,255,255,0.1)', color: 'white', cursor: 'pointer' }}>
                  {getMemberOptions().map(opt => <option key={opt.value} value={opt.value} style={{ background: '#2c3e50' }}>{opt.label}</option>)}
                </select>
              </div>
            )}

            {loading && <div style={{ padding: '12px', background: 'rgba(241,196,15,0.2)', borderRadius: '6px', marginBottom: '15px', textAlign: 'center', fontSize: '12px', color: '#f1c40f' }}>⏳ Loading...</div>}
            {error   && <div style={{ padding: '12px', background: 'rgba(231,76,60,0.2)',  borderRadius: '6px', marginBottom: '15px', fontSize: '12px', color: '#e74c3c' }}>⚠️ {error}</div>}
          </div>
        </div>

        {/* Timeline */}
        <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, background: 'rgba(44,62,80,0.95)', backdropFilter: 'blur(10px)', padding: '15px 20px', zIndex: 900, boxShadow: '0 -4px 15px rgba(0,0,0,0.3)' }}>
          <div style={{ marginBottom: '10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ color: 'white', fontSize: '14px', fontWeight: '600' }}>+{selectedHour}h ({(selectedHour / 24).toFixed(1)} days)</div>
            <div style={{ color: 'rgba(255,255,255,0.7)', fontSize: '12px' }}>{formatDate(selectedHour)}</div>
          </div>
          <input type="range" min="0" max={currentModel.hours.length - 1} value={currentModel.hours.indexOf(selectedHour)} onChange={e => setSelectedHour(currentModel.hours[parseInt(e.target.value)])} style={{ width: '100%', height: '8px', borderRadius: '4px', background: 'rgba(255,255,255,0.2)', outline: 'none', cursor: 'pointer' }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '8px' }}>
            <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.5)' }}>Now</span>
            <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.5)' }}>7 days</span>
            <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.5)' }}>15 days</span>
          </div>
        </div>

        {/* Legends */}
        {showData && (
          <div style={{ position: 'absolute', bottom: '120px', right: '20px', display: 'flex', flexDirection: 'column', gap: '10px', zIndex: 500, alignItems: 'flex-end' }}>

            {showBivariate && bivariateRanges && (() => {
              const { meanMax, stdMax } = bivariateRanges;
              const cols = 4, rows = 4;
              const cellSize = 36;
              // 5 tick values (boundaries of the 4 bins) for each axis
              const xTicks = Array.from({ length: cols + 1 }, (_, i) => +(meanMax * i / cols).toFixed(2));
              const yTicks = Array.from({ length: rows + 1 }, (_, i) => +(stdMax  * i / rows).toFixed(2));
              const xLabel = selectedVariable === 'wind' ? 'Wind Speed' : 'Precipitation';
              const unit   = selectedVariable === 'wind' ? 'm/s' : 'mm/hr';
              return (
                <div style={{ background: 'rgba(255,255,255,0.95)', padding: '14px 14px 10px 14px', borderRadius: '8px', boxShadow: '0 4px 15px rgba(0,0,0,0.3)', userSelect: 'none' }}>
                  {/* Title */}
                  <div style={{ fontSize: '13px', fontWeight: '700', color: '#2c3e50', textAlign: 'center', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    {xLabel}
                  </div>

                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: '4px' }}>
                    {/* Color grid + X-axis ticks */}
                    <div>
                      {/* X-axis tick labels above grid */}
                      <div style={{ display: 'flex', marginBottom: '3px', marginLeft: '0px' }}>
                        {xTicks.map((v, i) => (
                          <div key={i} style={{ width: i === 0 ? cellSize / 2 : i === cols ? cellSize / 2 : cellSize, fontSize: '10px', color: '#555', textAlign: 'center', lineHeight: 1 }}>
                            {v}
                          </div>
                        ))}
                      </div>

                      {/* Grid rows (bottom row = low uncertainty) */}
                      <div style={{ display: 'flex', flexDirection: 'column-reverse' }}>
                        {BIVARIATE_COLORS.map((row, ri) => (
                          <div key={ri} style={{ display: 'flex' }}>
                            {row.map((color, ci) => (
                              <div key={ci} style={{ width: cellSize, height: cellSize, background: color }} />
                            ))}
                          </div>
                        ))}
                      </div>

                      {/* X-axis label */}
                      <div style={{ textAlign: 'center', fontSize: '11px', color: '#2c3e50', fontWeight: '600', marginTop: '6px' }}>
                        {xLabel} ({unit}) →
                      </div>
                    </div>

                    {/* Y-axis tick labels + axis label */}
                    <div style={{ display: 'flex', flexDirection: 'row', alignItems: 'flex-start' }}>
                      {/* Y tick labels aligned to row boundaries */}
                      <div style={{ display: 'flex', flexDirection: 'column-reverse', justifyContent: 'space-between', height: cellSize * rows, marginLeft: '4px' }}>
                        {yTicks.map((v, i) => (
                          <div key={i} style={{ fontSize: '10px', color: '#555', lineHeight: 1, marginTop: i === yTicks.length - 1 ? 0 : `-4px` }}>
                            {v}
                          </div>
                        ))}
                      </div>
                      {/* Rotated Y-axis label */}
                      <div style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)', fontSize: '11px', color: '#2c3e50', fontWeight: '600', marginLeft: '4px', alignSelf: 'center', whiteSpace: 'nowrap' }}>
                        Uncertainty ({unit}) ↑
                      </div>
                    </div>
                  </div>
                </div>
              );
            })()}

            {showFanChart && bivariateRanges && (() => {
              const { meanMax, stdMax } = bivariateRanges;

              // Fan geometry: pivot at bottom-center, opens upward
              // Standard math angles: 0°=right, 90°=up; SVG y-flipped: py = cy - r*sin(d)
              const fanLeft = 150, fanRight = 30;
              const totalSpan = fanLeft - fanRight;   // 120°
              const cx = 150, cy = 220;
              const rInner = 22, rOuter = 140;
              const ROWS = 4;
              const dR = (rOuter - rInner) / ROWS;
              const toRad = d => d * Math.PI / 180;
              const px = (r, d) => cx + r * Math.cos(toRad(d));
              const py = (r, d) => cy - r * Math.sin(toRad(d));
              const arcPath = (r1, r2, a1d, a2d) =>
                `M${px(r1,a1d).toFixed(2)} ${py(r1,a1d).toFixed(2)} ` +
                `A${r1} ${r1} 0 0 1 ${px(r1,a2d).toFixed(2)} ${py(r1,a2d).toFixed(2)} ` +
                `L${px(r2,a2d).toFixed(2)} ${py(r2,a2d).toFixed(2)} ` +
                `A${r2} ${r2} 0 0 0 ${px(r2,a1d).toFixed(2)} ${py(r2,a1d).toFixed(2)}Z`;

              // Derive color for a normalized value t∈[0,1] from the selected colormap
              const cmapColor = (t) => {
                const cols = COLORMAPS[selectedColormap].colors;
                const seg = cols.length - 1;
                const si  = Math.min(Math.floor(t * seg), seg - 1);
                const st  = t * seg - si;
                const c1 = cols[si], c2 = cols[si + 1];
                const ri = parseInt(c1.slice(1,3),16), gi = parseInt(c1.slice(3,5),16), bi = parseInt(c1.slice(5,7),16);
                const ro = parseInt(c2.slice(1,3),16), go = parseInt(c2.slice(3,5),16), bo = parseInt(c2.slice(5,7),16);
                return [Math.round(ri+(ro-ri)*st), Math.round(gi+(go-gi)*st), Math.round(bi+(bo-bi)*st)];
              };

              // VSUP rows: ri=0 innermost = HIGH uncertainty (1 bin), ri=3 outermost = LOW uncertainty (4 bins)
              // segs: 1 → 2 → 4 → 4 from inner to outer
              // suppression: blend toward neutral (180,175,185) proportional to uncertainty
              const neutral = [180, 175, 185];
              // True VSUP binary tree: 1 → 2 → 4 → 8 from inner (high uncert) to outer (low uncert)
              const segCounts = [1, 2, 4, 8];
              const vsupRows = segCounts.map((segs, ri) => {
                const uncertFrac = 1 - ri / (ROWS - 1);  // ri=0 → 1.0 (max suppression), ri=3 → 0
                const suppress   = uncertFrac * 0.72;
                const colors = Array.from({ length: segs }, (_, ci) => {
                  const t = segs === 1 ? 0.5 : ci / (segs - 1);
                  const [r, g, b] = cmapColor(Math.min(t, 0.999));
                  const fr = Math.round(r * (1-suppress) + neutral[0] * suppress);
                  const fg = Math.round(g * (1-suppress) + neutral[1] * suppress);
                  const fb = Math.round(b * (1-suppress) + neutral[2] * suppress);
                  return `rgb(${fr},${fg},${fb})`;
                });
                return { segs, colors };
              });

              const title = selectedVariable === 'wind' ? 'WIND_SPEED' : 'PRECIPITATION';

              // Value ticks: 8 ticks (skip last one which lands on right spine = collision with uncertainty axis)
              const dAngle8 = totalSpan / 8;
              const valTicks = Array.from({ length: 8 }, (_, i) => {
                const deg = fanLeft - i * dAngle8;
                return {
                  deg,
                  tx: px(rOuter, deg), ty: py(rOuter, deg),
                  lx: px(rOuter + 20, deg), ly: py(rOuter + 20, deg),
                  val: (meanMax * i / 8).toFixed(2)
                };
              });

              // Uncertainty ticks: along right spine (fanRight=30°), outer=low, inner=high
              const stdTicks = Array.from({ length: 5 }, (_, j) => {
                const r = rOuter - j * dR;
                return {
                  bx: px(r, fanRight), by: py(r, fanRight),
                  val: (stdMax * j / 4).toFixed(2)
                };
              });

              // "Std. Error" label: fixed position to the right of all spine tick labels,
              // vertically centred between j=0 (outermost) and j=4 (innermost)
              const smeLx = px(rOuter, fanRight) + 38;  // right of the widest tick label
              const smeLy = (py(rOuter, fanRight) + py(rInner, fanRight)) / 2;

              return (
                <div style={{ background: 'rgba(255,255,255,0.95)', padding: '16px 16px 12px 16px', borderRadius: '8px', boxShadow: '0 4px 15px rgba(0,0,0,0.3)' }}>
                  <div style={{ fontSize: '14px', fontWeight: '700', color: '#2c3e50', textAlign: 'center', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    {title}
                  </div>
                  <svg width="320" height="240" style={{ overflow: 'visible', display: 'block' }}>
                    {/* VSUP fan: innermost=high uncert (1 bin) → outermost=low uncert (4 bins) */}
                    {vsupRows.map(({ segs, colors }, ri) => {
                      const segSpan = totalSpan / segs;
                      const r1 = rInner + ri * dR, r2 = rInner + (ri + 1) * dR;
                      return colors.map((color, ci) => {
                        const a1 = fanLeft - ci * segSpan;
                        const a2 = fanLeft - (ci + 1) * segSpan;
                        return <path key={`${ri}-${ci}`} d={arcPath(r1, r2, a1, a2)} fill={color} stroke="white" strokeWidth="1.5" />;
                      });
                    })}

                    {/* Value ticks: outer arc, labels rotated radially */}
                    {valTicks.map((t, i) => (
                      <g key={i}>
                        <line x1={t.tx} y1={t.ty}
                              x2={px(rOuter+6, t.deg)} y2={py(rOuter+6, t.deg)}
                              stroke="#999" strokeWidth="1" />
                        <text x={t.lx} y={t.ly} fontSize="9" fill="#444"
                          textAnchor="middle" dominantBaseline="middle"
                          transform={`rotate(${90 - t.deg}, ${t.lx.toFixed(1)}, ${t.ly.toFixed(1)})`}>
                          {t.val}
                        </text>
                      </g>
                    ))}

                    {/* Uncertainty ticks: right spine, outer=low → inner=high */}
                    {stdTicks.map((t, j) => (
                      <g key={j}>
                        <line x1={t.bx} y1={t.by}
                              x2={px(rOuter - j*dR + 6, fanRight).toFixed(2)}
                              y2={py(rOuter - j*dR + 6, fanRight).toFixed(2)}
                              stroke="#999" strokeWidth="1" />
                        <text x={(t.bx + 9).toFixed(1)} y={t.by.toFixed(1)} fontSize="9" fill="#444"
                          textAnchor="start" dominantBaseline="middle">
                          {t.val}
                        </text>
                      </g>
                    ))}

                    {/* "Std. Error" axis title — vertical, centred beside the right-spine tick numbers */}
                    <text x={smeLx.toFixed(1)} y={smeLy.toFixed(1)} fontSize="9" fill="#2c3e50" fontWeight="600"
                      textAnchor="middle" dominantBaseline="middle"
                      transform={`rotate(90, ${smeLx.toFixed(1)}, ${smeLy.toFixed(1)})`}>
                      Std. Error
                    </text>
                    {/* "Forecast Value" axis title — centered below the outer arc */}
                    <text x={cx} y={cy + 18} fontSize="9" fill="#2c3e50" fontWeight="600"
                      textAnchor="middle" dominantBaseline="auto">
                      ← Forecast Value →
                    </text>
                  </svg>
                </div>
              );
            })()}

            {showUncertainty && stats && (
              <div style={{ background: 'rgba(255,255,255,0.95)', padding: '12px 16px', borderRadius: '8px', boxShadow: '0 4px 15px rgba(0,0,0,0.3)', minWidth: '150px' }}>
                <h3 style={{ margin: '0 0 10px 0', fontSize: '13px', fontWeight: '600', color: '#2c3e50' }}>Uncertainty Size</h3>
                {[0.05, 0.25, 0.5, 0.75, 1.0].map((frac, i) => {
                  const stdVal = (parseFloat(stats.max) * frac).toFixed(2);
                  const minPx = 5, maxPx = 30;
                  const px = Math.round(maxPx - Math.sqrt(frac) * (maxPx - minPx));
                  return (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', marginBottom: '7px', gap: '8px' }}>
                      <div style={{ width: '34px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <div style={{ width: px, height: px, background: 'rgba(100,160,210,0.45)', border: '1px solid rgba(52,152,219,0.55)', borderRadius: '2px', flexShrink: 0 }} />
                      </div>
                      <span style={{ fontSize: '11px', color: '#2c3e50', fontWeight: '600' }}>{stdVal}</span>
                    </div>
                  );
                })}
                <div style={{ fontSize: '10px', color: '#7f8c8d', marginTop: '6px', borderTop: '1px solid #eee', paddingTop: '6px' }}>
                  {selectedVariable === 'wind' ? 'Std Dev (m/s)' : 'Std Dev (mm/hr)'}
                </div>
              </div>
            )}

            {!showBivariate && !showFanChart && <div style={{ background: 'rgba(255,255,255,0.95)', padding: '15px', borderRadius: '8px', boxShadow: '0 4px 15px rgba(0,0,0,0.3)' }}>
              <h3 style={{ margin: '0 0 10px 0', fontSize: '13px', fontWeight: '600', color: '#2c3e50' }}>
                {selectedVariable === 'wind' ? 'Wind Speed (m/s)' : selectedMember === 'std' ? 'Uncertainty (mm/hr)' : 'Precipitation (mm/hr)'}
              </h3>

              {selectedTexture === 'lines' ? (() => {
                // 2-row certainty grid legend matching reference image
                const cmapColors = COLORMAPS[selectedColormap].colors;
                const steps = 5;
                const cellW = 28, cellH = 24;
                const maxVal = stats ? parseFloat(stats.max) : 10;
                return (
                  <div>
                    <svg width={steps * cellW + 36} height={cellH * 2 + 40} style={{ overflow: 'visible' }}>
                      {/* Y-axis label */}
                      <text x={-2} y={cellH} fontSize="8" fill="#2c3e50" fontWeight="600" textAnchor="middle"
                        transform={`rotate(-90, -2, ${cellH})`}>Certainty</text>

                      {[0, 1].map(row => {
                        const isLowCert = row === 1; // bottom row = Low certainty = lines
                        return steps && Array.from({ length: steps }, (_, ci) => {
                          const t = ci / (steps - 1);
                          const seg = cmapColors.length - 1;
                          const si  = Math.min(Math.floor(t * seg), seg - 1);
                          const tf  = t * seg - si;
                          const c1  = cmapColors[si], c2 = cmapColors[Math.min(si+1, seg)];
                          const r = Math.round(parseInt(c1.slice(1,3),16)+(parseInt(c2.slice(1,3),16)-parseInt(c1.slice(1,3),16))*tf);
                          const g = Math.round(parseInt(c1.slice(3,5),16)+(parseInt(c2.slice(3,5),16)-parseInt(c1.slice(3,5),16))*tf);
                          const b = Math.round(parseInt(c1.slice(5,7),16)+(parseInt(c2.slice(5,7),16)-parseInt(c1.slice(5,7),16))*tf);
                          const fill = `rgb(${r},${g},${b})`;
                          const x = 14 + ci * cellW, y = row * cellH;
                          return (
                            <g key={`${row}-${ci}`}>
                              <rect x={x} y={y} width={cellW} height={cellH} fill={fill} stroke="white" strokeWidth="1" />
                              {isLowCert && Array.from({ length: 6 }, (_, li) => {
                                const lx = x - cellH + li * 7;
                                return <line key={li} x1={lx} y1={y} x2={lx + cellH} y2={y + cellH}
                                  stroke="rgba(80,80,80,0.55)" strokeWidth="0.8"
                                  clipPath={`inset(0 0 0 0)`} />;
                              })}
                            </g>
                          );
                        });
                      })}

                      {/* Clip hatching to cells */}
                      <defs>
                        {Array.from({ length: steps }, (_, ci) => (
                          <clipPath key={ci} id={`cell-clip-${ci}`}>
                            <rect x={14 + ci * cellW} y={cellH} width={cellW} height={cellH} />
                          </clipPath>
                        ))}
                      </defs>
                      {/* Hatching on bottom row (Low certainty = high uncertainty) */}
                      {Array.from({ length: steps }, (_, ci) => (
                        Array.from({ length: 8 }, (_, li) => {
                          const x = 14 + ci * cellW;
                          const lx = x - 4 + li * 7;
                          return <line key={`h-${ci}-${li}`}
                            x1={lx} y1={cellH} x2={lx + cellH} y2={cellH * 2}
                            stroke="rgba(80,80,80,0.7)" strokeWidth="1.0"
                            clipPath={`url(#cell-clip-${ci})`} />;
                        })
                      ))}

                      {/* X-axis value labels */}
                      {Array.from({ length: steps }, (_, ci) => (
                        <text key={ci} x={14 + ci * cellW + cellW / 2} y={cellH * 2 + 12}
                          fontSize="8" fill="#2c3e50" textAnchor="middle">
                          {(maxVal * ci / (steps - 1)).toFixed(1)}
                        </text>
                      ))}
                      {/* X-axis title */}
                      <text x={14 + (steps * cellW) / 2} y={cellH * 2 + 26}
                        fontSize="8" fill="#2c3e50" fontWeight="600" textAnchor="middle">
                        {selectedVariable === 'wind' ? 'Wind Speed (m/s)' : 'Precipitation (mm/hr)'}
                      </text>

                      {/* Y-axis: top = High certainty (no lines), bottom = Low certainty (lines) */}
                      <text x={14 + steps * cellW + 4} y={cellH / 2 + 4} fontSize="8" fill="#2c3e50" textAnchor="start">High certainty</text>
                      <text x={14 + steps * cellW + 4} y={cellH + cellH / 2 + 4} fontSize="8" fill="#2c3e50" textAnchor="start">Low certainty</text>
                    </svg>
                  </div>
                );
              })() : (
                <div style={{ height: '160px', width: '30px', background: getLegendGradient(selectedColormap), borderRadius: '4px', border: '1px solid #ccc', position: 'relative' }}>
                  <div style={{ position: 'absolute', right: '-50px', top: '-2px',  fontSize: '10px', fontWeight: '600', color: '#2c3e50' }}>{stats ? stats.max : '100+'}</div>
                  <div style={{ position: 'absolute', right: '-50px', top: '40px',  fontSize: '10px', fontWeight: '600', color: '#2c3e50' }}>{stats ? (parseFloat(stats.max) * 0.67).toFixed(1) : '50'}</div>
                  <div style={{ position: 'absolute', right: '-50px', top: '80px',  fontSize: '10px', fontWeight: '600', color: '#2c3e50' }}>{stats ? (parseFloat(stats.max) * 0.33).toFixed(1) : '25'}</div>
                  <div style={{ position: 'absolute', right: '-35px', bottom: '0',  fontSize: '10px', fontWeight: '600', color: '#2c3e50' }}>0</div>
                </div>
              )}
            </div>}
          </div>
        )}

        <div style={{ position: 'absolute', bottom: '8px', left: '50%', transform: 'translateX(-50%)', color: 'rgba(255,255,255,0.35)', fontSize: '11px', zIndex: 950, pointerEvents: 'none', whiteSpace: 'nowrap' }}>
          © Northeastern University
        </div>

        {showAbout && (
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(102,126,234,0.98)', backdropFilter: 'blur(10px)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px', zIndex: 1500 }}>
            <div style={{ maxWidth: '800px', background: 'rgba(255,255,255,0.98)', borderRadius: '16px', padding: '40px', boxShadow: '0 20px 60px rgba(0,0,0,0.4)', maxHeight: '80vh', overflowY: 'auto' }}>
              <h1 style={{ fontSize: '32px', marginBottom: '20px', color: '#2c3e50' }}>🌧️ WEAVE</h1>
              <p style={{ fontSize: '16px', lineHeight: '1.8', color: '#34495e', marginBottom: '30px' }}>WEAVE is an advanced visualization platform that displays ensemble forecast data from multiple weather models. Our system provides real-time visualization of precipitation and wind speed data, enabling better understanding of forecast uncertainty and model agreement.</p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '30px' }}>
                <div style={{ background: '#ecf0f1', padding: '20px', borderRadius: '8px' }}>
                  <h3 style={{ fontSize: '16px', color: '#3498db', marginBottom: '10px' }}>Models</h3>
                  <ul style={{ fontSize: '14px', color: '#34495e', lineHeight: '1.8', paddingLeft: '20px', margin: 0 }}>
                    <li>AIFS (50 members)</li><li>GEFS (30 members)</li><li>UKMO (18 members)</li>
                  </ul>
                </div>
                <div style={{ background: '#ecf0f1', padding: '20px', borderRadius: '8px' }}>
                  <h3 style={{ fontSize: '16px', color: '#e74c3c', marginBottom: '10px' }}>Variables</h3>
                  <ul style={{ fontSize: '14px', color: '#34495e', lineHeight: '1.8', paddingLeft: '20px', margin: 0 }}>
                    <li>Precipitation (mm/hr)</li><li>Wind Speed (m/s)</li><li>Ensemble Statistics</li>
                  </ul>
                </div>
              </div>
              <div style={{ background: '#3498db', color: 'white', padding: '20px', borderRadius: '8px', marginBottom: '20px' }}>
                <h3 style={{ fontSize: '16px', marginBottom: '10px' }}>Visualization Technology</h3>
                <p style={{ fontSize: '14px', lineHeight: '1.6', margin: 0 }}>Dynamic canvas-based rendering using Inverse Distance Weighting (IDW) interpolation. Real-time spatial gradients from point-based weather data stored in PostgreSQL.</p>
              </div>
              {stats && (
                <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px', marginBottom: '20px' }}>
                  <h4 style={{ fontSize: '14px', marginBottom: '15px', color: '#9b59b6', marginTop: 0 }}>Current Data Statistics</h4>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                    {[['DATA POINTS', stats.total.toLocaleString(), currentModel.color], ['AVERAGE', `${stats.average} ${selectedVariable === 'wind' ? 'm/s' : 'mm/hr'}`, '#3498db'], ['MAXIMUM', `${stats.max} ${selectedVariable === 'wind' ? 'm/s' : 'mm/hr'}`, '#e74c3c'], ['MINIMUM', `${stats.min} ${selectedVariable === 'wind' ? 'm/s' : 'mm/hr'}`, '#2ecc71']].map(([label, value, color]) => (
                      <div key={label} style={{ padding: '12px', background: 'white', borderRadius: '6px', borderLeft: `3px solid ${color}` }}>
                        <div style={{ fontSize: '9px', opacity: 0.6, color: '#34495e' }}>{label}</div>
                        <div style={{ fontSize: '20px', fontWeight: 'bold', color: '#2c3e50' }}>{value}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <div style={{ textAlign: 'center', fontSize: '14px', color: '#7f8c8d' }}>
                <p style={{ margin: '0 0 10px 0' }}>Built with React, Leaflet, Flask, and PostgreSQL</p>
                <p style={{ margin: 0 }}>© 2026 WEAVE Team — Northeastern University</p>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ══ ANALYSIS TAB ══ */}
      <div style={{ display: activeTab === 'analysis' ? 'flex' : 'none', position: 'absolute', top: TAB_BAR_H, left: 0, right: 0, bottom: 0, background: '#0f1923', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{ padding: '20px 30px 10px', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          <h2 style={{ color: 'white', margin: '0 0 4px 0', fontSize: '18px', fontWeight: '600' }}>📊 Forecast Uncertainty — Cone of Uncertainty</h2>
          <p style={{ color: 'rgba(255,255,255,0.4)', margin: 0, fontSize: '13px' }}>
            {clickedPoint ? `Point: ${clickedPoint.lat}°N, ${clickedPoint.lon}°E — ${currentModel.name} — ${selectedVariable}` : 'Click anywhere on the map to generate a forecast cone for that location'}
          </p>
        </div>

        <div style={{ flex: 1, padding: '20px 30px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          {!clickedPoint && (
            <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.25)' }}>
              <div style={{ fontSize: '64px', marginBottom: '16px' }}>🖱️</div>
              <p style={{ fontSize: '16px', margin: 0 }}>Click a point on the map</p>
              <p style={{ fontSize: '13px', margin: '8px 0 0 0' }}>Switch to Visualization tab, click anywhere, then come back here</p>
            </div>
          )}
          {clickedPoint && timeseriesLoading && <div style={{ color: 'rgba(255,255,255,0.5)', fontSize: '16px' }}>⏳ Loading forecast data...</div>}
          {clickedPoint && !timeseriesLoading && timeseriesData && (
            <div style={{ width: '100%', height: '100%' }}>
              <div style={{ display: 'flex', gap: '20px', marginBottom: '12px', flexWrap: 'wrap' }}>
                {[{ color: '#3498db', label: 'Ensemble Mean', solid: true }, { color: 'rgba(52,152,219,0.4)', label: '±1σ (68%)', solid: false }, { color: 'rgba(52,152,219,0.15)', label: '±2σ (95%)', solid: false }].map(({ color, label, solid }) => (
                  <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <div style={{ width: '24px', height: solid ? '3px' : '12px', background: color, borderRadius: '2px' }} />
                    <span style={{ color: 'rgba(255,255,255,0.6)', fontSize: '12px' }}>{label}</span>
                  </div>
                ))}
              </div>
              <ResponsiveContainer width="100%" height="85%">
                <AreaChart data={timeseriesData} margin={{ top: 10, right: 30, left: 10, bottom: 30 }}>
                  <defs>
                    <linearGradient id="cone2grad" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor="#3498db" stopOpacity={0.12} />
                      <stop offset="100%" stopColor="#3498db" stopOpacity={0.22} />
                    </linearGradient>
                    <linearGradient id="cone1grad" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor="#3498db" stopOpacity={0.25} />
                      <stop offset="100%" stopColor="#3498db" stopOpacity={0.45} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="hour" stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }} tickFormatter={h => `+${h}h`} ticks={[0,24,48,72,96,120,144,168,192,216,240,264,288,312,336,360]} label={{ value: 'Forecast Hour', position: 'insideBottom', offset: -15, fill: 'rgba(255,255,255,0.4)', fontSize: 12 }} />
                  <YAxis stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }} label={{ value: selectedVariable === 'wind' ? 'Wind Speed (m/s)' : 'Precipitation (mm/hr)', angle: -90, position: 'insideLeft', fill: 'rgba(255,255,255,0.4)', fontSize: 12 }} />
                  <Tooltip contentStyle={{ background: '#1a2535', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '8px', color: 'white', fontSize: '12px' }}
                    formatter={(value, name) => { if (value == null) return null; const labels = { mean: 'Mean', band2Hi: '+2σ', band2Lo: '-2σ', band1Hi: '+1σ', band1Lo: '-1σ' }; return [typeof value === 'number' ? value.toFixed(3) : value, labels[name] || name]; }}
                    labelFormatter={hour => `Forecast +${hour}h (Day ${(hour/24).toFixed(1)})`} />
                  <Area type="monotone" dataKey="band2Hi" stroke="none" fill="url(#cone2grad)" fillOpacity={1} legendType="none" name="band2Hi" />
                  <Area type="monotone" dataKey="band2Lo" stroke="none" fill="#0f1923" fillOpacity={1} legendType="none" name="band2Lo" />
                  <Area type="monotone" dataKey="band1Hi" stroke="none" fill="url(#cone1grad)" fillOpacity={1} legendType="none" name="band1Hi" />
                  <Area type="monotone" dataKey="band1Lo" stroke="none" fill="#0f1923" fillOpacity={1} legendType="none" name="band1Lo" />
                  <Area type="monotone" dataKey="mean" stroke="#7ec8f7" strokeWidth={2.5} fill="none" dot={false} name="mean" />
                  {[24,48,72,96,120,144,168,192,216,240,264,288,312,336].map(h => (
                    <ReferenceLine key={h} x={h} stroke="rgba(255,255,255,0.07)" strokeDasharray="4 4" label={{ value: `D${h/24}`, position: 'top', fill: 'rgba(255,255,255,0.2)', fontSize: 9 }} />
                  ))}
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
          {clickedPoint && !timeseriesLoading && !timeseriesData && <div style={{ color: 'rgba(255,255,255,0.35)', fontSize: '14px' }}>No data available for this location</div>}
        </div>
      </div>

    </div>
  );
}

export default App;