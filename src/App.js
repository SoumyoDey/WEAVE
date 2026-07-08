import React, { useState, useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { ChevronLeft, Info, Menu, CloudRain, Map as MapIcon, BarChart3, Scale } from 'lucide-react';

// ── Constants & utilities ─────────────────────────────────────────────────────
import { MODELS, COLORMAPS, METRIC_CONFIG, buildColorMatrix } from './constants';
import { getLegendGradient }  from './utils/colorUtils';
import { pointInPolygon }     from './utils/geoUtils';

// ── API ───────────────────────────────────────────────────────────────────────
import { fetchForecastData, fetchTimeseries as apiFetchTimeseries, fetchSpreadSkill as apiFetchSpreadSkill } from './api/forecastApi';
import { fetchSpatialMetric } from './api/spatialApi';

// ── Layer renderers ───────────────────────────────────────────────────────────
import { drawOnMap }            from './layers/idwLayer';
import { drawWindArrows, startStreamlines, stopStreamlines } from './layers/windLayer';
import { drawUncertaintyBoxes, stopUncertainty } from './layers/vsupLayer';
import { drawBivariateLayer, stopBivariate } from './layers/bivariateLayer';
import { drawTextureLayer, stopTexture }         from './layers/textureLayer';
import { renderMetricCanvas, clearMetricCanvas } from './layers/metricLayer';

// ── UI Components ─────────────────────────────────────────────────────────────
import { ControlsSidebar }    from './components/ControlsSidebar';
import { Timeline }           from './components/Timeline';
import { AboutModal }         from './components/AboutModal';
import { SelectionToolbar }   from './components/SelectionToolbar';
import { MetricPanel }        from './components/MetricPanel';
import { AnalysisTab }        from './components/AnalysisTab';
import { ComparisonTab }      from './components/ComparisonTab';
import { IDWLegend }          from './components/legends/IDWLegend';
import { BivariateLegend }    from './components/legends/BivariateLegend';
import { VSUPFanLegend }      from './components/legends/VSUPFanLegend';
import { VSUPBoxesLegend }    from './components/legends/VSUPBoxesLegend';
import { TextureLegend }      from './components/legends/TextureLegend';

const TAB_BAR_H = 48;

function App() {
  // ── UI state ────────────────────────────────────────────────────────────────
  const [activeTab, setActiveTab]               = useState('visualization');
  const [menuOpen, setMenuOpen]                 = useState(false);
  const [showAbout, setShowAbout]               = useState(false);

  // ── Forecast controls state ──────────────────────────────────────────────────
  const [selectedModel, setSelectedModel]       = useState('AIFS');
  const [selectedHour, setSelectedHour]         = useState(6);
  const [selectedMember, setSelectedMember]     = useState('mean');
  const [selectedVariable, setSelectedVariable] = useState('precipitation');
  const [selectedColormap, setSelectedColormap] = useState('Default');
  const [showWindArrows, setShowWindArrows]     = useState(false);
  const [showWindLines, setShowWindLines]       = useState(false);

  // ── Uncertainty overlay state (mutually exclusive) ───────────────────────────
  const [uncertaintyMode, setUncertaintyMode]   = useState(null);  // null | 'vsup' | 'bivariate' | 'fan' | 'texture'
  const [bivariateRanges, setBivariateRanges]   = useState(null);
  const [invertUncertainty, setInvertUncertainty] = useState(false);

  // ── Map Chart controls ────────────────────────────────────────────────────────
  const [numBuckets,   setNumBuckets]   = useState(0);
  const [flipColormap, setFlipColormap] = useState(false);
  const [gridOpacity,  setGridOpacity]  = useState(1.0);
  const [textureStyle, setTextureStyle] = useState('Lines');

  // ── Data & stats state ───────────────────────────────────────────────────────
  const [showData, setShowData]     = useState(false);
  const [stats, setStats]           = useState(null);
  const [dataRange, setDataRange]   = useState({ min: 0, max: 100 });
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState('');

  // ── Point-click analysis state ───────────────────────────────────────────────
  const [clickedPoint, setClickedPoint]             = useState(null);
  const [timeseriesData, setTimeseriesData]         = useState(null);
  const [timeseriesLoading, setTimeseriesLoading]   = useState(false);
  const [ssrData, setSsrData]                       = useState(null);
  const [ssrLoading, setSsrLoading]                 = useState(false);

  // ── Spatial metric / region selection state ──────────────────────────────────
  const [selectionMode, setSelectionMode]       = useState(null);
  const [selectedRegion, setSelectedRegion]     = useState(null);
  const [metricType, setMetricType]             = useState('ssr');
  const [metricHour, setMetricHour]             = useState(6);
  const [metricThreshold, setMetricThreshold]   = useState(25);
  const [spatialData, setSpatialData]           = useState(null);
  const [spatialLoading, setSpatialLoading]     = useState(false);
  const [showMetricPanel, setShowMetricPanel]   = useState(false);
  const [panelPos, setPanelPos]                 = useState({ x: 16, y: 120 });
  const [panelMinimized, setPanelMinimized]     = useState(false);

  // ── Analysis tab state ────────────────────────────────────────────────────────

  // ── Refs ─────────────────────────────────────────────────────────────────────
  const mapRef                = useRef(null);
  const mapInstanceRef        = useRef(null);
  const dataRef               = useRef(null);
  const canvasRef             = useRef(null);
  const drawFnRef             = useRef(null);
  const isInitializedRef      = useRef(false);
  const arrowsCanvasRef       = useRef(null);
  const animationFrameRef     = useRef(null);
  const showWindLinesRef      = useRef(false);
  const uncertaintyCanvasRef  = useRef(null);
  const uncertaintyLayerRef   = useRef(null);
  const bivariateLayerRef     = useRef(null);
  const textureLayerRef       = useRef(null);
  const clickMarkerRef        = useRef(null);
  const selectionLayerRef     = useRef(null);
  const selectionModeRef      = useRef(null);
  const spatialDataRef        = useRef(null);
  const metricTypeRef         = useRef('ssr');
  const isDraggingPanelRef    = useRef(false);
  const dragStartRef          = useRef({ mouseX: 0, mouseY: 0, panelX: 0, panelY: 0 });
  const uncertaintyModeRef      = useRef(null);
  const invertUncertaintyRef    = useRef(false);

  const currentModel = MODELS[selectedModel];

  // Derived booleans
  const showUncertainty = uncertaintyMode === 'vsup';
  const showBivariate   = uncertaintyMode === 'bivariate';
  const showFanChart    = uncertaintyMode === 'fan';
  const showTexture     = uncertaintyMode === 'texture';

  // ── Ref mirrors ──────────────────────────────────────────────────────────────
  useEffect(() => { selectionModeRef.current = selectionMode; }, [selectionMode]);
  useEffect(() => { spatialDataRef.current   = spatialData;   }, [spatialData]);
  useEffect(() => { metricTypeRef.current    = metricType;    }, [metricType]);
  useEffect(() => { showWindLinesRef.current = showWindLines; }, [showWindLines]);
  useEffect(() => {
    uncertaintyModeRef.current = uncertaintyMode;
    if (canvasRef.current) canvasRef.current.style.display = uncertaintyMode !== null ? 'none' : 'block';
  }, [uncertaintyMode]);
  useEffect(() => { invertUncertaintyRef.current = invertUncertainty; }, [invertUncertainty]);

  // ── Map init ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (isInitializedRef.current || !mapRef.current) return;
    isInitializedRef.current = true;
    setTimeout(() => {
      const map = L.map(mapRef.current, { center: [37, -82.5], zoom: 6, zoomControl: false });
      const zoomCtrl = L.control.zoom({ position: 'topleft' }).addTo(map);
      const zoomEl = zoomCtrl.getContainer();
      zoomEl.style.marginTop  = '68px';
      zoomEl.style.marginLeft = '12px';
      L.tileLayer('https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap, &copy; CartoDB' }).addTo(map);
      L.tileLayer('https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png',   { attribution: '' }).addTo(map);
      mapInstanceRef.current = map;
      setTimeout(() => { map.invalidateSize(); loadDataForHour(); }, 100);
    }, 100);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Resize map when switching to visualization tab
  useEffect(() => {
    if (activeTab === 'visualization' && mapInstanceRef.current)
      setTimeout(() => mapInstanceRef.current.invalidateSize(), 50);
  }, [activeTab]);

  // ── Reload data on control changes (debounced) ───────────────────────────────
  // 300 ms debounce so rapid timeline scrubbing fires only one request.
  useEffect(() => {
    if (!mapInstanceRef.current) return;
    const t = setTimeout(loadDataForHour, 300);
    return () => clearTimeout(t);
  }, [selectedHour, selectedModel, selectedMember, selectedVariable]); // eslint-disable-line

  // ── Redraw IDW / VSup when colormap or invert changes ────────────────────────
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !dataRef.current?.length) return;
    setTimeout(() => {
      if (showUncertainty) {
        drawUncertaintyBoxes(map, uncertaintyLayerRef, uncertaintyCanvasRef, currentModel.name, selectedVariable, selectedHour, selectedColormap, invertUncertainty, numBuckets, flipColormap, gridOpacity, setBivariateRanges);
      } else if (!showBivariate && !showFanChart && !showTexture) {
        drawOnMap(map, dataRef.current, selectedColormap, selectedMember === 'std', dataRange, { canvasRef, drawFnRef, uncertaintyModeRef }, { flipColormap, gridOpacity, numBuckets });
      }
    }, 100);
  }, [selectedColormap, invertUncertainty]); // eslint-disable-line

  // ── Redraw IDW when numBuckets / flipColormap / gridOpacity changes ───────────
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !dataRef.current?.length) return;
    if (!showBivariate && !showFanChart && !showTexture && !showUncertainty) {
      drawOnMap(map, dataRef.current, selectedColormap, selectedMember === 'std', dataRange, { canvasRef, drawFnRef, uncertaintyModeRef }, { flipColormap, gridOpacity, numBuckets });
    }
  }, [numBuckets, flipColormap, gridOpacity]); // eslint-disable-line

  // ── Wind arrows / streamlines ─────────────────────────────────────────────────
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (selectedVariable === 'wind' && dataRef.current?.length && map) {
      if (showWindArrows) drawWindArrows(map, dataRef.current, arrowsCanvasRef);
      else { arrowsCanvasRef.current?.remove(); arrowsCanvasRef.current = null; }
      if (showWindLines) startStreamlines(map, dataRef.current, animationFrameRef, showWindLinesRef);
      else stopStreamlines(animationFrameRef);
    } else {
      arrowsCanvasRef.current?.remove();
      arrowsCanvasRef.current = null;
      stopStreamlines(animationFrameRef);
    }
  }, [showWindArrows, showWindLines, selectedVariable, selectedHour, selectedModel, selectedMember]); // eslint-disable-line

  // ── VSup Boxes overlay ────────────────────────────────────────────────────────
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (showUncertainty && dataRef.current?.length && map) {
      if (canvasRef.current) canvasRef.current.style.display = 'none';
      drawUncertaintyBoxes(map, uncertaintyLayerRef, uncertaintyCanvasRef, currentModel.name, selectedVariable, selectedHour, selectedColormap, invertUncertainty, numBuckets, flipColormap, gridOpacity, setBivariateRanges);
    } else {
      if (canvasRef.current && uncertaintyMode === null) canvasRef.current.style.display = 'block';
      stopUncertainty(map, uncertaintyLayerRef, uncertaintyCanvasRef);
    }
  }, [showUncertainty, selectedHour, selectedModel, selectedVariable, selectedColormap, invertUncertainty, numBuckets, flipColormap, gridOpacity]); // eslint-disable-line

  // ── Bivariate / VSUP Fan overlay ─────────────────────────────────────────────
  useEffect(() => {
    const map = mapInstanceRef.current;
    if ((showBivariate || showFanChart) && map) {
      if (canvasRef.current) canvasRef.current.style.display = 'none';
      drawBivariateLayer(
        map, bivariateLayerRef, currentModel.name, selectedVariable, selectedHour,
        buildColorMatrix(selectedColormap, showFanChart, invertUncertainty, numBuckets || 4),
        setBivariateRanges, numBuckets, selectedColormap, showFanChart,
        invertUncertainty, flipColormap, gridOpacity,
      );
    } else {
      if (canvasRef.current && uncertaintyMode === null) canvasRef.current.style.display = 'block';
      stopBivariate(map, bivariateLayerRef);
    }
  }, [showBivariate, showFanChart, selectedHour, selectedModel, selectedVariable, numBuckets, selectedColormap, invertUncertainty, flipColormap, gridOpacity]); // eslint-disable-line

  // ── Texture overlay ───────────────────────────────────────────────────────────
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (showTexture && map) {
      if (canvasRef.current) canvasRef.current.style.display = 'none';
      drawTextureLayer(map, textureLayerRef, currentModel.name, selectedVariable, selectedHour, selectedColormap, textureStyle, numBuckets, flipColormap, gridOpacity, invertUncertainty, setBivariateRanges);
    } else {
      if (canvasRef.current && uncertaintyMode === null) canvasRef.current.style.display = 'block';
      stopTexture(map, textureLayerRef);
    }
  }, [showTexture, selectedHour, selectedModel, selectedVariable, selectedColormap, textureStyle, numBuckets, flipColormap, gridOpacity, invertUncertainty]); // eslint-disable-line

  // ── Data fetch ────────────────────────────────────────────────────────────────
  const loadDataForHour = async () => {
    if (!mapInstanceRef.current) return;
    setLoading(true); setError('');
    try {
      const data = await fetchForecastData(currentModel.name, selectedVariable, selectedHour, selectedMember);
      dataRef.current = data;

      // Single pass — avoids spreading a large array into Math.min/max (RangeError
      // risk on fine grids) and handles an all-zero field (Math.min([]) → Infinity).
      const valueKey = selectedVariable === 'wind' ? 'speed' : 'value';
      let minVal = Infinity, maxVal = -Infinity, sum = 0, count = 0;
      for (const d of data) {
        const v = parseFloat(d[valueKey]);
        if (!Number.isFinite(v)) continue;
        if (v > 0 && v < minVal) minVal = v;
        if (v > maxVal) maxVal = v;
        sum += v; count++;
      }
      if (!Number.isFinite(minVal)) minVal = 0.01;
      if (!Number.isFinite(maxVal) || maxVal <= 0) maxVal = 100;
      const average = count ? sum / count : 0;

      setDataRange({ min: minVal, max: maxVal });
      setStats({ total: count, average: average.toFixed(2), max: maxVal.toFixed(2), min: minVal.toFixed(2) });
      setShowData(true);
      setLoading(false);

      setTimeout(() => {
        const map = mapInstanceRef.current;
        drawOnMap(map, data, selectedColormap, selectedMember === 'std', { min: minVal, max: maxVal }, { canvasRef, drawFnRef, uncertaintyModeRef }, { flipColormap, gridOpacity, numBuckets });
        if (selectedVariable === 'wind') {
          if (showWindArrows) drawWindArrows(map, data, arrowsCanvasRef);
          if (showWindLines)  { stopStreamlines(animationFrameRef); startStreamlines(map, data, animationFrameRef, showWindLinesRef); }
        }
        if (uncertaintyModeRef.current === 'vsup')
          drawUncertaintyBoxes(map, uncertaintyLayerRef, uncertaintyCanvasRef, currentModel.name, selectedVariable, selectedHour, selectedColormap, invertUncertaintyRef.current, numBuckets, flipColormap, gridOpacity, setBivariateRanges);
        if (uncertaintyModeRef.current === 'bivariate')
          drawBivariateLayer(map, bivariateLayerRef, currentModel.name, selectedVariable, selectedHour, buildColorMatrix(selectedColormap, false, invertUncertaintyRef.current, numBuckets > 1 ? numBuckets : 4), setBivariateRanges, numBuckets, selectedColormap, false, invertUncertaintyRef.current, flipColormap, gridOpacity);
        if (uncertaintyModeRef.current === 'fan')
          drawBivariateLayer(map, bivariateLayerRef, currentModel.name, selectedVariable, selectedHour, buildColorMatrix(selectedColormap, true, invertUncertaintyRef.current, numBuckets > 1 ? numBuckets : 4), setBivariateRanges, numBuckets, selectedColormap, true, invertUncertaintyRef.current, flipColormap, gridOpacity);
      }, 300);
    } catch (err) {
      console.error('Load error:', err);
      setError(`Could not load: ${err.message}`);
      setLoading(false);
      setShowData(false);
    }
  };

  // ── Point-click: fetch timeseries + spread-skill ──────────────────────────────
  useEffect(() => {
    if (!mapInstanceRef.current) return;
    const map = mapInstanceRef.current;
    const handleClick = (e) => {
      if (selectionModeRef.current) return;
      const { lat, lng } = e.latlng;
      setClickedPoint({ lat: lat.toFixed(3), lon: lng.toFixed(3) });
      if (clickMarkerRef.current) map.removeLayer(clickMarkerRef.current);
      clickMarkerRef.current = L.circleMarker([lat, lng], { radius: 7, fillColor: '#e74c3c', color: 'white', weight: 2, fillOpacity: 1 }).addTo(map);
    };
    map.on('click', handleClick);
    return () => map.off('click', handleClick);
  }, [mapInstanceRef.current]); // eslint-disable-line

  useEffect(() => {
    if (!clickedPoint) return;
    const { lat, lon } = clickedPoint;

    setTimeseriesLoading(true); setTimeseriesData(null);
    apiFetchTimeseries(currentModel.name, selectedVariable, lat, lon)
      .then(data => {
        if (Array.isArray(data) && data.length) {
          setTimeseriesData(data.map(d => ({
            hour:    d.hour,
            mean:    d.mean,
            p10:     d.p10, p90: d.p90, p25: d.p25, p75: d.p75,
            band1Lo: Math.max(0, d.mean - d.std),
            band1Hi: d.mean + d.std,
            band2Lo: Math.max(0, d.mean - 2 * d.std),
            band2Hi: d.mean + 2 * d.std,
          })));
        }
      })
      .catch(err => console.error('Timeseries error:', err))
      .finally(() => setTimeseriesLoading(false));

    setSsrLoading(true); setSsrData(null);
    apiFetchSpreadSkill(currentModel.name, selectedVariable, lat, lon)
      .then(data => { if (data?.hours) setSsrData(data); })
      .catch(err => console.error('Spread-skill error:', err))
      .finally(() => setSsrLoading(false));
  }, [clickedPoint, selectedModel, selectedVariable]); // eslint-disable-line

  // ── Spatial metric computation ────────────────────────────────────────────────
  const computeSpatialMetric = async () => {
    if (!selectedRegion) return;
    setSpatialLoading(true);
    try {
      const metricCfg = METRIC_CONFIG.find(m => m.key === metricType);
      let data = await fetchSpatialMetric({
        metric:    metricType,
        modelName: currentModel.name,
        variable:  selectedVariable,
        hour:      metricCfg?.requiresHour ? metricHour : undefined,
        threshold: metricCfg?.requiresThreshold ? metricThreshold : undefined,
        bounds:    selectedRegion.bounds,
      });
      let pts = data.points || [];
      if (selectedRegion.type === 'polygon' && selectedRegion.polygon)
        pts = pts.filter(p => pointInPolygon(p.lat, p.lon, selectedRegion.polygon));
      data = { ...data, points: pts };
      setSpatialData(data);
      renderMetricCanvas(mapInstanceRef.current, pts, metricType, METRIC_CONFIG);
    } catch (err) {
      console.error('Spatial metric error:', err);
    }
    setSpatialLoading(false);
  };

  const clearSelection = () => {
    const map = mapInstanceRef.current;
    if (map && selectionLayerRef.current) { map.removeLayer(selectionLayerRef.current); selectionLayerRef.current = null; }
    clearMetricCanvas(map);
    setSpatialData(null); setSelectedRegion(null); setShowMetricPanel(false); setSelectionMode(null);
  };

  // ── Rectangle selection ───────────────────────────────────────────────────────
  useEffect(() => { // eslint-disable-line react-hooks/exhaustive-deps
    const map = mapInstanceRef.current;
    if (!map || selectionMode !== 'rectangle') return;
    map.dragging.disable(); map.scrollWheelZoom.disable(); map.doubleClickZoom.disable();
    map.getContainer().style.cursor = 'crosshair';
    let startLL = null, previewRect = null;
    const onMouseDown = (e) => { startLL = e.latlng; };
    const onMouseMove = (e) => {
      if (!startLL) return;
      if (previewRect) map.removeLayer(previewRect);
      previewRect = L.rectangle(L.latLngBounds(startLL, e.latlng), { color: '#3498db', weight: 2, dashArray: '5 4', fillOpacity: 0.08, fillColor: '#3498db', interactive: false }).addTo(map);
    };
    const onMouseUp = (e) => {
      if (!startLL) return;
      if (previewRect) { map.removeLayer(previewRect); previewRect = null; }
      const bounds = L.latLngBounds(startLL, e.latlng);
      const sw = bounds.getSouthWest(), ne = bounds.getNorthEast();
      if (Math.abs(ne.lat - sw.lat) < 0.1 || Math.abs(ne.lng - sw.lng) < 0.1) { startLL = null; return; }
      if (selectionLayerRef.current) map.removeLayer(selectionLayerRef.current);
      selectionLayerRef.current = L.rectangle(bounds, { color: '#e67e22', weight: 2, dashArray: '6 4', fillOpacity: 0.06, fillColor: '#e67e22', interactive: false }).addTo(map);
      setSelectedRegion({ type: 'rectangle', bounds: { min_lat: sw.lat, max_lat: ne.lat, min_lon: sw.lng, max_lon: ne.lng } });
      setSelectionMode(null); setShowMetricPanel(true); startLL = null;
    };
    map.on('mousedown', onMouseDown); map.on('mousemove', onMouseMove); map.on('mouseup', onMouseUp);
    return () => {
      map.off('mousedown', onMouseDown); map.off('mousemove', onMouseMove); map.off('mouseup', onMouseUp);
      if (previewRect) map.removeLayer(previewRect);
      map.dragging.enable(); map.scrollWheelZoom.enable(); map.doubleClickZoom.enable();
      map.getContainer().style.cursor = '';
    };
  }, [selectionMode, mapInstanceRef.current]); // eslint-disable-line

  // ── Polygon selection ─────────────────────────────────────────────────────────
  useEffect(() => { // eslint-disable-line react-hooks/exhaustive-deps
    const map = mapInstanceRef.current;
    if (!map || selectionMode !== 'polygon') return;
    map.dragging.disable(); map.scrollWheelZoom.disable(); map.doubleClickZoom.disable();
    map.getContainer().style.cursor = 'crosshair';
    const vertices = [], markers = [];
    let polyline = null;
    const updatePolyline = () => {
      if (polyline) map.removeLayer(polyline);
      if (vertices.length >= 2) polyline = L.polyline(vertices, { color: '#3498db', weight: 2, dashArray: '5 4' }).addTo(map);
    };
    const onClick = (e) => {
      const { lat, lng } = e.latlng;
      vertices.push([lat, lng]);
      markers.push(L.circleMarker([lat, lng], { radius: 4, color: '#3498db', fillColor: '#3498db', fillOpacity: 1, weight: 2 }).addTo(map));
      updatePolyline();
    };
    const onDblClick = (e) => {
      vertices.splice(-2); const removed = markers.splice(-2); removed.forEach(m => map.removeLayer(m));
      updatePolyline();
      if (vertices.length < 3) return;
      if (polyline) { map.removeLayer(polyline); polyline = null; }
      markers.forEach(m => map.removeLayer(m));
      const sw_lat = Math.min(...vertices.map(v => v[0])), ne_lat = Math.max(...vertices.map(v => v[0]));
      const sw_lng = Math.min(...vertices.map(v => v[1])), ne_lng = Math.max(...vertices.map(v => v[1]));
      if (selectionLayerRef.current) map.removeLayer(selectionLayerRef.current);
      selectionLayerRef.current = L.polygon(vertices, { color: '#e67e22', weight: 2, dashArray: '6 4', fillOpacity: 0.06, fillColor: '#e67e22', interactive: false }).addTo(map);
      setSelectedRegion({ type: 'polygon', bounds: { min_lat: sw_lat, max_lat: ne_lat, min_lon: sw_lng, max_lon: ne_lng }, polygon: vertices.map(v => [v[0], v[1]]) });
      setSelectionMode(null); setShowMetricPanel(true);
    };
    map.on('click', onClick); map.on('dblclick', onDblClick);
    return () => {
      map.off('click', onClick); map.off('dblclick', onDblClick);
      if (polyline) map.removeLayer(polyline);
      markers.forEach(m => map.removeLayer(m));
      map.dragging.enable(); map.scrollWheelZoom.enable(); map.doubleClickZoom.enable();
      map.getContainer().style.cursor = '';
    };
  }, [selectionMode, mapInstanceRef.current]); // eslint-disable-line

  // ── Redraw metric canvas on map move/zoom ─────────────────────────────────────
  useEffect(() => { // eslint-disable-line react-hooks/exhaustive-deps
    const map = mapInstanceRef.current;
    if (!map) return;
    const redraw = () => {
      if (spatialDataRef.current?.points)
        renderMetricCanvas(map, spatialDataRef.current.points, metricTypeRef.current, METRIC_CONFIG);
    };
    map.on('moveend', redraw); map.on('zoomend', redraw);
    return () => { map.off('moveend', redraw); map.off('zoomend', redraw); };
  }, [mapInstanceRef.current]); // eslint-disable-line

  // ── Draggable panel (window-level mouse handlers) ────────────────────────────
  useEffect(() => {
    const onMouseMove = (e) => {
      if (!isDraggingPanelRef.current) return;
      const { mouseX, mouseY, panelX, panelY } = dragStartRef.current;
      setPanelPos({ x: panelX + e.clientX - mouseX, y: panelY + e.clientY - mouseY });
    };
    const onMouseUp = () => { isDraggingPanelRef.current = false; };
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup',   onMouseUp);
    return () => { window.removeEventListener('mousemove', onMouseMove); window.removeEventListener('mouseup', onMouseUp); };
  }, []);

  // ── Helpers ───────────────────────────────────────────────────────────────────
  const getMemberOptions = () => {
    if (!currentModel.hasEnsemble) return [];
    const opts = [
      { value: 'mean', label: 'Ensemble Mean' },
      { value: 'std',  label: 'Uncertainty (Std Dev)' },
    ];
    for (let i = 0; i < currentModel.ensembleCount; i++)
      opts.push({ value: i.toString(), label: `Member ${i + 1}` });
    return opts;
  };

  // ── Render ────────────────────────────────────────────────────────────────────
  return (
    <div style={{ position: 'relative', height: '100vh', fontFamily: 'Arial', overflow: 'hidden' }}>

      {/* Tab bar */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: TAB_BAR_H, background: 'rgba(22,33,44,0.98)', display: 'flex', alignItems: 'center', zIndex: 1100, boxShadow: '0 2px 8px rgba(0,0,0,0.35)', paddingLeft: '16px', gap: '4px' }}>
        <span style={{ color: 'white', fontWeight: '700', fontSize: '16px', marginRight: '16px', letterSpacing: '1px', display: 'inline-flex', alignItems: 'center', gap: '7px' }}><CloudRain size={18} style={{ color: '#3aa0ff' }} />WEAVE</span>
        {[['visualization', MapIcon, 'Visualization'], ['analysis', BarChart3, 'Analysis'], ['comparison', Scale, 'Comparison']].map(([id, Icon, label]) => (
          <button key={id} onClick={() => setActiveTab(id)}
            style={{ padding: '6px 20px', fontSize: '13px', fontWeight: '600', border: 'none', borderRadius: '6px', cursor: 'pointer', transition: 'all 0.2s', background: activeTab === id ? 'rgba(255,255,255,0.15)' : 'transparent', color: activeTab === id ? 'white' : 'rgba(255,255,255,0.45)', borderBottom: activeTab === id ? '2px solid #3498db' : '2px solid transparent', display: 'inline-flex', alignItems: 'center', gap: '7px' }}>
            <Icon size={15} />{label}
          </button>
        ))}
        {/* Persistent context: what you're currently looking at */}
        <span style={{ marginLeft: 'auto', marginRight: '16px', display: 'flex', alignItems: 'center', gap: '8px', padding: '5px 12px', borderRadius: '20px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', color: 'rgba(255,255,255,0.75)', fontSize: '12px', whiteSpace: 'nowrap' }}>
          {currentModel.name} · {selectedVariable === 'wind' ? 'Wind' : 'Precipitation'} · +{selectedHour}h
        </span>
      </div>

      {/* ══ VISUALIZATION TAB ══ */}
      <div style={{ display: activeTab === 'visualization' ? 'block' : 'none', position: 'absolute', top: TAB_BAR_H, left: 0, right: 0, bottom: 0 }}>
        {/* Range-input thumb styling */}
        <style>{`
          input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 16px; height: 16px; border-radius: 50%; background: #3498db; border: 2.5px solid white; cursor: pointer; box-shadow: 0 0 0 3px rgba(52,152,219,0.25); }
          input[type=range]::-moz-range-thumb      { width: 16px; height: 16px; border-radius: 50%; background: #3498db; border: 2.5px solid white; cursor: pointer; box-shadow: 0 0 0 3px rgba(52,152,219,0.25); }
          input[type=range] { -webkit-appearance: none; appearance: none; }
        `}</style>

        {/* Map canvas */}
        <div ref={mapRef} style={{ width: '100%', height: '100%', background: '#f5f5f5' }} />

        {/* Click-away backdrop — closes the sidebar when user clicks the map */}
        {menuOpen && (
          <div
            onClick={() => setMenuOpen(false)}
            style={{ position: 'absolute', inset: 0, zIndex: 999, cursor: 'default' }}
          />
        )}

        {/* Controls toggle */}
        <button onClick={() => setMenuOpen(!menuOpen)} title="Controls"
          style={{ position: 'absolute', top: '12px', left: menuOpen ? '312px' : '12px', width: '44px', height: '44px', background: 'rgba(15,25,35,0.95)', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer', zIndex: 1002, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 12px rgba(0,0,0,0.3)', transition: 'left 0.3s ease' }}>
          {menuOpen ? <ChevronLeft size={22} /> : <Menu size={22} />}
        </button>

        {/* About button */}
        <button onClick={() => setShowAbout(!showAbout)} title="About WEAVE"
          style={{ position: 'absolute', top: '12px', right: '12px', width: '44px', height: '44px', background: showAbout ? 'rgba(231,76,60,0.95)' : 'rgba(15,25,35,0.95)', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer', zIndex: 1001, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 12px rgba(0,0,0,0.3)', transition: 'background 0.2s' }}>
          <Info size={20} />
        </button>

        {/* Unified controls sidebar (Data · Display · Advanced) */}
        <ControlsSidebar
          open={menuOpen}
          models={MODELS}
          selectedModel={selectedModel} setSelectedModel={setSelectedModel}
          selectedVariable={selectedVariable} setSelectedVariable={setSelectedVariable}
          currentModel={currentModel}
          getMemberOptions={getMemberOptions} selectedMember={selectedMember} setSelectedMember={setSelectedMember}
          loading={loading} error={error}
          colormaps={COLORMAPS}
          selectedColormap={selectedColormap} setSelectedColormap={setSelectedColormap}
          uncertaintyMode={uncertaintyMode} setUncertaintyMode={setUncertaintyMode}
          invertUncertainty={invertUncertainty} setInvertUncertainty={setInvertUncertainty}
          numBuckets={numBuckets} setNumBuckets={setNumBuckets}
          flipColormap={flipColormap} setFlipColormap={setFlipColormap}
          gridOpacity={gridOpacity} setGridOpacity={setGridOpacity}
          textureStyle={textureStyle} setTextureStyle={setTextureStyle}
          showWindArrows={showWindArrows} setShowWindArrows={setShowWindArrows}
          showWindLines={showWindLines} setShowWindLines={setShowWindLines}
        />

        {/* Timeline */}
        <Timeline
          currentModel={currentModel}
          selectedHour={selectedHour} setSelectedHour={setSelectedHour}
          selectedVariable={selectedVariable}
        />

        {/* Legends */}
        {showData && (
          <div style={{ position: 'absolute', bottom: '72px', right: '20px', display: 'flex', flexDirection: 'column', gap: '10px', zIndex: 500, alignItems: 'flex-end' }}>
            {showBivariate && (
              <BivariateLegend
                bivariateRanges={bivariateRanges}
                selectedColormap={selectedColormap}
                selectedVariable={selectedVariable}
                buildColorMatrix={buildColorMatrix}
                invertUncertainty={invertUncertainty}
                numBuckets={numBuckets}
                flipColormap={flipColormap}
              />
            )}
            {showFanChart && (
              <VSUPFanLegend
                bivariateRanges={bivariateRanges}
                selectedColormap={selectedColormap}
                colormaps={COLORMAPS}
                selectedVariable={selectedVariable}
                invertUncertainty={invertUncertainty}
                numBuckets={numBuckets}
                flipColormap={flipColormap}
              />
            )}
            {showUncertainty && stats && (
              <VSUPBoxesLegend stats={stats} selectedVariable={selectedVariable} invertUncertainty={invertUncertainty} numBuckets={numBuckets} stdMax={bivariateRanges?.stdMax} />
            )}
            {showTexture && (
              <TextureLegend
                bivariateRanges={bivariateRanges}
                selectedColormap={selectedColormap}
                selectedVariable={selectedVariable}
                textureStyle={textureStyle}
                numBuckets={numBuckets}
                flipColormap={flipColormap}
                invertUncertainty={invertUncertainty}
              />
            )}
            {!showBivariate && !showFanChart && !showUncertainty && !showTexture && (
              <IDWLegend
                selectedColormap={selectedColormap}
                stats={stats}
                selectedVariable={selectedVariable}
                selectedMember={selectedMember}
                getLegendGradient={getLegendGradient}
                numBuckets={numBuckets}
                flipColormap={flipColormap}
              />
            )}
          </div>
        )}

        {/* Selection toolbar + metric panel */}
        <SelectionToolbar
          selectionMode={selectionMode} setSelectionMode={setSelectionMode}
          selectedRegion={selectedRegion} clearSelection={clearSelection}
        />
        {showMetricPanel && selectedRegion && !selectionMode && (
          <MetricPanel
            selectedRegion={selectedRegion}
            panelPos={panelPos} setPanelPos={setPanelPos}
            panelMinimized={panelMinimized} setPanelMinimized={setPanelMinimized}
            metricType={metricType} setMetricType={setMetricType}
            metricHour={metricHour} setMetricHour={setMetricHour}
            metricThreshold={metricThreshold} setMetricThreshold={setMetricThreshold}
            spatialLoading={spatialLoading} spatialData={spatialData}
            computeSpatialMetric={computeSpatialMetric}
            clearSelection={clearSelection}
            isDraggingPanelRef={isDraggingPanelRef}
            dragStartRef={dragStartRef}
          />
        )}

        {/* About modal */}
        {showAbout && (
          <AboutModal
            onClose={() => setShowAbout(false)}
            stats={stats}
            selectedVariable={selectedVariable}
            currentModel={currentModel}
          />
        )}
      </div>

      {/* ══ ANALYSIS TAB ══ */}
      <div style={{ display: activeTab === 'analysis' ? 'flex' : 'none', position: 'absolute', top: TAB_BAR_H, left: 0, right: 0, bottom: 0, background: '#0f1923', flexDirection: 'column', overflow: 'hidden' }}>
        <AnalysisTab
          clickedPoint={clickedPoint}
          currentModel={currentModel}
          selectedVariable={selectedVariable}
          timeseriesLoading={timeseriesLoading} timeseriesData={timeseriesData}
          ssrLoading={ssrLoading} ssrData={ssrData}
          onCompare={() => setActiveTab('comparison')}
          selectedRegion={selectedRegion}
          active={activeTab === 'analysis'}
        />
      </div>

      {/* ══ COMPARISON TAB ══ */}
      <div style={{ display: activeTab === 'comparison' ? 'flex' : 'none', position: 'absolute', top: TAB_BAR_H, left: 0, right: 0, bottom: 0, background: '#0f1923', flexDirection: 'column', overflow: 'hidden' }}>
        <ComparisonTab
          defaultLocation={clickedPoint}
          defaultHour={selectedHour}
          selectedVariable={selectedVariable}
          selectedRegion={selectedRegion}
          onJumpToComparison={(lat, lon) => setActiveTab('comparison')}
          active={activeTab === 'comparison'}
        />
      </div>

    </div>
  );
}

export default App;
