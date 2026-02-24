import React, { useState, useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { ChevronLeft, ChevronRight, Info } from 'lucide-react';

const generateHours = () => {
  const hours = [];
  for (let h = 0; h <= 360; h += 6) {
    hours.push(h);
  }
  return hours;
};

const ALL_HOURS = generateHours();

const MODELS = {
  AIFS: { 
    name: 'AIFS', 
    color: '#3498db', 
    hours: ALL_HOURS, 
    hasEnsemble: true,
    ensembleCount: 50
  },
  GEFS: { 
    name: 'GEFS', 
    color: '#e74c3c', 
    hours: ALL_HOURS, 
    hasEnsemble: true,
    ensembleCount: 30
  },
  UKMO: { 
    name: 'UKMO', 
    color: '#2ecc71', 
    hours: ALL_HOURS, 
    hasEnsemble: true,
    ensembleCount: 18
  }
};

const COLORMAPS = {
  'Default': {
    name: 'Default',
    type: 'sequential',
    colors: ['#FFFFCC', '#C8F0C8', '#A0E6E6', '#70C8D2', '#5098C8', '#3264AA', '#001E6E', '#000050']
  },
  'Viridis': {
    name: 'Viridis',
    type: 'sequential',
    colors: ['#440154', '#414487', '#2a788e', '#22a884', '#7ad151', '#fde725']
  },
  'Plasma': {
    name: 'Plasma',
    type: 'sequential',
    colors: ['#0d0887', '#6a00a8', '#b12a90', '#e16462', '#fca636', '#f0f921']
  },
  'Inferno': {
    name: 'Inferno',
    type: 'sequential',
    colors: ['#000004', '#420a68', '#932667', '#dd513a', '#fca50a', '#fcffa4']
  },
  'Turbo': {
    name: 'Turbo',
    type: 'sequential',
    colors: ['#30123b', '#4662d7', '#36a9e1', '#13eb6b', '#a7fc3c', '#faba39', '#e8443a']
  },
  'Cool': {
    name: 'Cool',
    type: 'sequential',
    colors: ['#00ffff', '#00d4ff', '#00aaff', '#0080ff', '#0055ff', '#002bff', '#0000ff']
  },
  'Warm': {
    name: 'Warm',
    type: 'sequential',
    colors: ['#ffff00', '#ffdd00', '#ffbb00', '#ff9900', '#ff7700', '#ff5500', '#ff0000']
  },
  'RdYlBu': {
    name: 'RdYlBu',
    type: 'diverging',
    colors: ['#a50026', '#d73027', '#f46d43', '#fdae61', '#fee090', '#ffffbf', '#e0f3f8', '#abd9e9', '#74add1', '#4575b4', '#313695']
  },
  'Spectral': {
    name: 'Spectral',
    type: 'diverging',
    colors: ['#9e0142', '#d53e4f', '#f46d43', '#fdae61', '#fee08b', '#ffffbf', '#e6f598', '#abdda4', '#66c2a5', '#3288bd', '#5e4fa2']
  }
};

function App() {
  const [selectedModel, setSelectedModel] = useState('AIFS');
  const [selectedHour, setSelectedHour] = useState(6);
  const [selectedMember, setSelectedMember] = useState('mean');
  const [selectedVariable, setSelectedVariable] = useState('precipitation');
  const [showData, setShowData] = useState(false);
  const [stats, setStats] = useState(null);
  const [dataRange, setDataRange] = useState({ min: 0, max: 100 });
  const [fileName, setFileName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [panelCollapsed, setPanelCollapsed] = useState(false);
  const [currentPage, setCurrentPage] = useState('application');
  const [selectedColormap, setSelectedColormap] = useState('Default');
  
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const dataRef = useRef(null);
  const canvasRef = useRef(null);
  const isInitializedRef = useRef(false);

  const currentModel = MODELS[selectedModel];

  useEffect(() => {
    if (currentPage !== 'application') return;
    
    if (mapInstanceRef.current) {
      setTimeout(() => {
        mapInstanceRef.current.invalidateSize();
        if (dataRef.current && dataRef.current.length > 0) {
          drawOnMap(dataRef.current, selectedMember === 'std', dataRange);
        }
      }, 100);
      return;
    }
    
    if (isInitializedRef.current || !mapRef.current) return;
    
    if (mapRef.current._leaflet_id) {
      console.log('Map container already has Leaflet instance');
      return;
    }
    
    isInitializedRef.current = true;
    
    setTimeout(() => {
      if (!mapRef.current) return;
      
      const map = L.map(mapRef.current, {
        center: [37, -82.5],
        zoom: 6,
        zoomControl: true
      });

      L.tileLayer('https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap, &copy; CartoDB'
      }).addTo(map);

      L.tileLayer('https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png', {
        attribution: ''
      }).addTo(map);

      mapInstanceRef.current = map;
      
      setTimeout(() => {
        if (map) map.invalidateSize();
      }, 100);
    }, 100);
  }, [currentPage]);

  useEffect(() => {
    if (currentPage === 'application' && mapInstanceRef.current) {
      loadDataForHour();
    }
  }, [selectedHour, selectedModel, selectedMember, selectedVariable, currentPage]);

  useEffect(() => {
    if (currentPage === 'application' && dataRef.current && dataRef.current.length > 0) {
      setTimeout(() => drawOnMap(dataRef.current, selectedMember === 'std', dataRange), 100);
    }
  }, [selectedColormap]);

  const loadDataForHour = async () => {
    if (!mapInstanceRef.current) return;
    
    setLoading(true);
    setError('');
    
    try {
      const params = new URLSearchParams({
        model: currentModel.name,
        variable: selectedVariable,
        hour: selectedHour,
        member: selectedMember
      });
      
      const endpoint = selectedVariable === 'wind' ? 'wind-data' : 'forecast-data';
      const apiUrl = `http://localhost:5000/api/${endpoint}?${params}`;
      
      setFileName(`PostgreSQL: ${currentModel.name} ${selectedVariable} +${selectedHour}h (${selectedMember})`);
      
      const response = await fetch(apiUrl);
      
      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }
      
      const data = await response.json();
      
      if (!Array.isArray(data) || data.length === 0) {
        throw new Error('No data returned');
      }
      
      dataRef.current = data;
      
      const values = selectedVariable === 'wind' 
        ? data.map(d => parseFloat(d.speed))
        : data.map(d => parseFloat(d.value));
      
      const minVal = Math.min(...values.filter(v => v > 0)) || 0.01;
      const maxVal = Math.max(...values) || 100;
      
      setDataRange({ min: minVal, max: maxVal });
      
      setStats({
        total: values.length,
        average: (values.reduce((a, b) => a + b, 0) / values.length).toFixed(2),
        max: maxVal.toFixed(2),
        min: minVal.toFixed(2)
      });
      
      setShowData(true);
      setLoading(false);
      
      setTimeout(() => drawOnMap(data, selectedMember === 'std', { min: minVal, max: maxVal }), 300);
      
    } catch (err) {
      console.error('Load error:', err);
      setError(`Could not load: ${err.message}`);
      setLoading(false);
      setShowData(false);
    }
  };

  const drawOnMap = (data, isStdDev = false, range = { min: 0, max: 100 }) => {
    if (!mapInstanceRef.current || !mapInstanceRef.current._loaded) {
      setTimeout(() => drawOnMap(data, isStdDev, range), 200);
      return;
    }

    if (canvasRef.current) {
      canvasRef.current.remove();
      canvasRef.current = null;
    }

    const canvas = document.createElement('canvas');
    const container = mapInstanceRef.current.getContainer();
    canvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;z-index:400';
    container.appendChild(canvas);
    canvasRef.current = canvas;

    const getDynamicColor = (value) => {
      const colormap = COLORMAPS[selectedColormap];
      const colors = colormap.colors;
      const normalized = Math.min(value / range.max, 1);
      
      if (normalized < 0.01) return 'rgba(255, 255, 255, 0)';
      
      const segments = colors.length - 1;
      const segmentSize = 1 / segments;
      const segmentIndex = Math.min(Math.floor(normalized / segmentSize), segments - 1);
      const segmentT = (normalized - segmentIndex * segmentSize) / segmentSize;
      
      const color1 = colors[segmentIndex];
      const color2 = colors[segmentIndex + 1];
      
      const r1 = parseInt(color1.slice(1, 3), 16);
      const g1 = parseInt(color1.slice(3, 5), 16);
      const b1 = parseInt(color1.slice(5, 7), 16);
      
      const r2 = parseInt(color2.slice(1, 3), 16);
      const g2 = parseInt(color2.slice(3, 5), 16);
      const b2 = parseInt(color2.slice(5, 7), 16);
      
      const r = Math.round(r1 + (r2 - r1) * segmentT);
      const g = Math.round(g1 + (g2 - g1) * segmentT);
      const b = Math.round(b1 + (b2 - b1) * segmentT);
      
      const opacity = 0.5 + normalized * 0.3;
      
      return `rgba(${r}, ${g}, ${b}, ${opacity})`;
    };

    const draw = () => {
      if (!mapInstanceRef.current || !mapInstanceRef.current._loaded) return;
      
      const size = mapInstanceRef.current.getSize();
      
      if (!size || size.x <= 0 || size.y <= 0) {
        console.log('Map size invalid, skipping draw');
        return;
      }
      
      canvas.width = size.x;
      canvas.height = size.y;
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const spatialData = data.map(p => {
        try {
          const point = mapInstanceRef.current.latLngToContainerPoint([parseFloat(p.lat), parseFloat(p.lon)]);
          const dataValue = p.speed !== undefined ? parseFloat(p.speed) : parseFloat(p.value);
          return {
            x: point.x,
            y: point.y,
            value: dataValue,
            lat: parseFloat(p.lat),
            lon: parseFloat(p.lon)
          };
        } catch (e) {
          return null;
        }
      }).filter(p => p !== null);

      const pixelSize = 4;
      const influenceRadius = 40;
      
      const tempCanvas = document.createElement('canvas');
      tempCanvas.width = Math.ceil(size.x / pixelSize);
      tempCanvas.height = Math.ceil(size.y / pixelSize);
      
      if (tempCanvas.width <= 0 || tempCanvas.height <= 0) {
        console.log('Invalid canvas dimensions, skipping draw');
        return;
      }
      
      const tempCtx = tempCanvas.getContext('2d');
      const imageData = tempCtx.createImageData(tempCanvas.width, tempCanvas.height);
      
      const allLats = spatialData.map(p => p.lat).filter(l => l !== undefined);
      const allLons = spatialData.map(p => p.lon).filter(l => l !== undefined);
      
      const minLat = Math.min(...allLats);
      const maxLat = Math.max(...allLats);
      const minLon = Math.min(...allLons);
      const maxLon = Math.max(...allLons);
      
      const topLeft = mapInstanceRef.current.latLngToContainerPoint([maxLat, minLon]);
      const bottomRight = mapInstanceRef.current.latLngToContainerPoint([minLat, maxLon]);
      
      for (let py = 0; py < tempCanvas.height; py++) {
        for (let px = 0; px < tempCanvas.width; px++) {
          const screenX = px * pixelSize;
          const screenY = py * pixelSize;
          
          const isInBounds = screenX >= topLeft.x && screenX <= bottomRight.x &&
                           screenY >= topLeft.y && screenY <= bottomRight.y;
          
          if (!isInBounds) continue;
          
          let weightedSum = 0;
          let totalWeight = 0;
          
          for (const point of spatialData) {
            const dx = point.x - screenX;
            const dy = point.y - screenY;
            const distance = Math.sqrt(dx * dx + dy * dy);
            
            if (distance < influenceRadius) {
              const weight = distance < 1 ? 1 : 1 / (distance * distance);
              weightedSum += point.value * weight;
              totalWeight += weight;
            }
          }
          
          let interpolatedValue = 0;
          
          if (totalWeight > 0) {
            interpolatedValue = weightedSum / totalWeight;
          }
          
          const color = getDynamicColor(Math.max(interpolatedValue, 0));
          const rgba = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/);
          
          if (rgba) {
            const idx = (py * tempCanvas.width + px) * 4;
            imageData.data[idx] = parseInt(rgba[1]);
            imageData.data[idx + 1] = parseInt(rgba[2]);
            imageData.data[idx + 2] = parseInt(rgba[3]);
            imageData.data[idx + 3] = totalWeight > 0 ? (rgba[4] ? parseFloat(rgba[4]) * 255 : 255) : 100;
          }
        }
      }
      
      tempCtx.putImageData(imageData, 0, 0);
      
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = 'high';
      
      ctx.drawImage(tempCanvas, 0, 0, size.x, size.y);
    };

    draw();
    mapInstanceRef.current.on('move', draw);
    mapInstanceRef.current.on('zoom', draw);
  };

  const getMemberOptions = () => {
    if (!currentModel.hasEnsemble) return [];
    
    const options = [
      { value: 'mean', label: '📊 Ensemble Mean' },
      { value: 'std', label: '📈 Uncertainty (Std Dev)' }
    ];
    
    for (let i = 0; i < currentModel.ensembleCount; i++) {
      options.push({ value: i.toString(), label: `Member ${i + 1}` });
    }
    
    return options;
  };

  return (
    <div style={{ display: 'flex', height: '100vh', fontFamily: 'Arial' }}>
      {/* Left Panel */}
      <div style={{ 
        width: panelCollapsed ? '0px' : '300px',
        background: '#2c3e50',
        color: 'white',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '2px 0 8px rgba(0,0,0,0.3)',
        transition: 'width 0.3s ease',
        overflow: 'hidden',
        position: 'relative'
      }}>
        {/* Header */}
        <div style={{ 
          padding: '20px', 
          background: '#1a252f',
          borderBottom: '2px solid rgba(255,255,255,0.1)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ fontSize: '28px' }}>🌧️</span>
            <div>
              <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '600' }}>
                WEAVE
              </h2>
            </div>
          </div>
        </div>

        {/* Application Controls */}
        {currentPage === 'application' && (
          <>
            <div>
              <label style={{ 
                display: 'block', 
                fontSize: '10px', 
                fontWeight: '600', 
                marginBottom: '6px',
                opacity: 0.7,
                textTransform: 'uppercase',
                letterSpacing: '0.5px',
                padding: '0 20px',
                marginTop: '20px'
              }}>
                Variable
              </label>
              <div style={{ padding: '0 20px' }}>
                <select
                  value={selectedVariable}
                  onChange={(e) => setSelectedVariable(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px',
                    fontSize: '13px',
                    border: '1px solid rgba(255,255,255,0.2)',
                    borderRadius: '4px',
                    background: 'rgba(255,255,255,0.1)',
                    color: 'white',
                    cursor: 'pointer'
                  }}
                >
                  <option value="precipitation" style={{ background: '#2c3e50' }}>Precipitation</option>
                  <option value="wind" style={{ background: '#2c3e50' }}>Wind Speed</option>
                </select>
              </div>
            </div>

            <div style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.1)', marginTop: '15px' }}>
              {Object.entries(MODELS).map(([key, model]) => (
                <button
                  key={key}
                  onClick={() => setSelectedModel(key)}
                  style={{
                    flex: 1,
                    padding: '12px 8px',
                    fontSize: '13px',
                    fontWeight: '600',
                    border: 'none',
                    borderBottom: selectedModel === key ? `3px solid ${model.color}` : 'none',
                    background: selectedModel === key ? 'rgba(255,255,255,0.1)' : 'transparent',
                    color: selectedModel === key ? model.color : 'rgba(255,255,255,0.5)',
                    cursor: 'pointer',
                    transition: 'all 0.2s'
                  }}
                >
                  {model.name}
                </button>
              ))}
            </div>

            <div style={{ padding: '20px', flex: 1, overflowY: 'auto' }}>
              <div style={{ marginBottom: '20px' }}>
                <label style={{ 
                  display: 'block', 
                  fontSize: '11px', 
                  fontWeight: '600', 
                  marginBottom: '8px',
                  opacity: 0.7,
                  textTransform: 'uppercase'
                }}>
                  Forecast Hour
                </label>
                <select
                  value={selectedHour}
                  onChange={(e) => setSelectedHour(parseInt(e.target.value))}
                  style={{
                    width: '100%',
                    padding: '10px',
                    fontSize: '13px',
                    border: '1px solid rgba(255,255,255,0.2)',
                    borderRadius: '4px',
                    background: 'rgba(255,255,255,0.1)',
                    color: 'white',
                    cursor: 'pointer'
                  }}
                >
                  {currentModel.hours.map(h => (
                    <option key={h} value={h} style={{ background: '#2c3e50' }}>
                      +{h}h ({(h/24).toFixed(1)} days)
                    </option>
                  ))}
                </select>
              </div>

              {currentModel.hasEnsemble && (
                <div style={{ marginBottom: '20px' }}>
                  <label style={{ 
                    display: 'block', 
                    fontSize: '11px', 
                    fontWeight: '600', 
                    marginBottom: '8px',
                    opacity: 0.7,
                    textTransform: 'uppercase'
                  }}>
                    Ensemble Member
                  </label>
                  <select
                    value={selectedMember}
                    onChange={(e) => setSelectedMember(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '10px',
                      fontSize: '13px',
                      border: '1px solid rgba(255,255,255,0.2)',
                      borderRadius: '4px',
                      background: 'rgba(255,255,255,0.1)',
                      color: 'white',
                      cursor: 'pointer'
                    }}
                  >
                    {getMemberOptions().map(opt => (
                      <option key={opt.value} value={opt.value} style={{ background: '#2c3e50' }}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                  <div style={{ 
                    marginTop: '8px', 
                    fontSize: '10px', 
                    opacity: 0.6,
                    padding: '8px',
                    background: 'rgba(255,255,255,0.05)',
                    borderRadius: '4px'
                  }}>
                    {selectedMember === 'mean' && '📊 Average of all ensemble members'}
                    {selectedMember === 'std' && '📈 Shows forecast uncertainty'}
                    {selectedMember !== 'mean' && selectedMember !== 'std' && `🎲 Individual forecast scenario ${parseInt(selectedMember) + 1}`}
                  </div>
                </div>
              )}

              <div style={{ marginBottom: '20px' }}>
                <label style={{ 
                  display: 'block', 
                  fontSize: '11px', 
                  fontWeight: '600', 
                  marginBottom: '8px',
                  opacity: 0.7,
                  textTransform: 'uppercase'
                }}>
                  Color Scheme
                </label>
                <select
                  value={selectedColormap}
                  onChange={(e) => setSelectedColormap(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '10px',
                    fontSize: '13px',
                    border: '1px solid rgba(255,255,255,0.2)',
                    borderRadius: '4px',
                    background: 'rgba(255,255,255,0.1)',
                    color: 'white',
                    cursor: 'pointer'
                  }}
                >
                  {Object.keys(COLORMAPS).map(name => (
                    <option key={name} value={name} style={{ background: '#2c3e50' }}>
                      {name}
                    </option>
                  ))}
                </select>
                <div style={{
                  marginTop: '8px',
                  height: '20px',
                  borderRadius: '4px',
                  background: `linear-gradient(to right, ${COLORMAPS[selectedColormap].colors.join(', ')})`,
                  border: '1px solid rgba(255,255,255,0.2)'
                }} />
              </div>

              {loading && (
                <div style={{ padding: '12px', background: 'rgba(241, 196, 15, 0.2)', borderRadius: '4px', marginBottom: '15px', textAlign: 'center', fontSize: '12px', color: '#f1c40f' }}>
                  ⏳ Loading from PostgreSQL...
                </div>
              )}

              {error && (
                <div style={{ padding: '10px', background: 'rgba(231, 76, 60, 0.2)', borderRadius: '4px', marginBottom: '15px', fontSize: '11px', color: '#e74c3c' }}>
                  ⚠️ {error}
                </div>
              )}
            </div>
          </>
        )}

        {/* About Page Content */}
        {currentPage === 'about' && (
          <div style={{ padding: '20px', flex: 1, overflowY: 'auto' }}>
            <h3 style={{ fontSize: '16px', marginBottom: '15px', color: '#3498db' }}>About WEAVE</h3>
            <p style={{ fontSize: '13px', lineHeight: '1.6', opacity: 0.9, marginBottom: '20px' }}>
              WEAVE is an advanced visualization platform that displays ensemble forecast data from multiple weather models.
            </p>

            <h4 style={{ fontSize: '14px', marginBottom: '10px', color: '#e74c3c' }}>Features</h4>
            <ul style={{ fontSize: '12px', lineHeight: '1.8', opacity: 0.9, paddingLeft: '20px', marginBottom: '20px' }}>
              <li>Multi-model ensemble forecasts (AIFS, GEFS, UKMO)</li>
              <li>Precipitation and wind speed visualization</li>
              <li>Interactive map with real-time data</li>
              <li>Ensemble uncertainty analysis</li>
              <li>PostgreSQL-backed data storage</li>
            </ul>

            <h4 style={{ fontSize: '14px', marginBottom: '10px', color: '#2ecc71' }}>Technology Stack</h4>
            <ul style={{ fontSize: '12px', lineHeight: '1.8', opacity: 0.9, paddingLeft: '20px', marginBottom: '20px' }}>
              <li>Frontend: React + Leaflet</li>
              <li>Backend: Flask + PostgreSQL</li>
              <li>Visualization: Canvas 2D + IDW Interpolation</li>
              <li>Data: NetCDF ensemble forecasts</li>
            </ul>

            {stats && (
              <>
                <h4 style={{ fontSize: '14px', marginBottom: '10px', color: '#9b59b6' }}>Current Data Statistics</h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <div style={{ padding: '10px', background: 'rgba(255,255,255,0.08)', borderRadius: '4px', borderLeft: '3px solid ' + currentModel.color }}>
                    <div style={{ fontSize: '9px', opacity: 0.6 }}>DATA POINTS</div>
                    <div style={{ fontSize: '18px', fontWeight: 'bold' }}>{stats.total.toLocaleString()}</div>
                  </div>
                  <div style={{ padding: '10px', background: 'rgba(255,255,255,0.08)', borderRadius: '4px', borderLeft: '3px solid #3498db' }}>
                    <div style={{ fontSize: '9px', opacity: 0.6 }}>AVERAGE</div>
                    <div style={{ fontSize: '18px', fontWeight: 'bold' }}>
                      {stats.average} {selectedVariable === 'wind' ? 'm/s' : 'mm/hr'}
                    </div>
                  </div>
                  <div style={{ padding: '10px', background: 'rgba(255,255,255,0.08)', borderRadius: '4px', borderLeft: '3px solid #e74c3c' }}>
                    <div style={{ fontSize: '9px', opacity: 0.6 }}>MAXIMUM</div>
                    <div style={{ fontSize: '18px', fontWeight: 'bold' }}>
                      {stats.max} {selectedVariable === 'wind' ? 'm/s' : 'mm/hr'}
                    </div>
                  </div>
                  <div style={{ padding: '10px', background: 'rgba(255,255,255,0.08)', borderRadius: '4px', borderLeft: '3px solid #2ecc71' }}>
                    <div style={{ fontSize: '9px', opacity: 0.6 }}>MINIMUM</div>
                    <div style={{ fontSize: '18px', fontWeight: 'bold' }}>
                      {stats.min} {selectedVariable === 'wind' ? 'm/s' : 'mm/hr'}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Collapse/Expand Button */}
      <button
        onClick={() => setPanelCollapsed(!panelCollapsed)}
        style={{
          position: 'absolute',
          left: panelCollapsed ? '0px' : '300px',
          top: '50%',
          transform: 'translateY(-50%)',
          width: '30px',
          height: '60px',
          background: '#2c3e50',
          border: 'none',
          borderRadius: '0 8px 8px 0',
          color: 'white',
          cursor: 'pointer',
          zIndex: 1000,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          transition: 'left 0.3s ease',
          boxShadow: '2px 0 8px rgba(0,0,0,0.3)'
        }}
      >
        {panelCollapsed ? <ChevronRight size={20} /> : <ChevronLeft size={20} />}
      </button>

      {/* About Button - Top Right Corner */}
      <button
        onClick={() => setCurrentPage(currentPage === 'about' ? 'application' : 'about')}
        style={{
          position: 'absolute',
          top: '20px',
          right: '20px',
          width: '40px',
          height: '40px',
          background: currentPage === 'about' ? '#e74c3c' : '#3498db',
          border: 'none',
          borderRadius: '50%',
          color: 'white',
          cursor: 'pointer',
          zIndex: 1001,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          transition: 'all 0.3s ease'
        }}
        title={currentPage === 'about' ? 'Back to Application' : 'About WEAVE'}
      >
        <Info size={20} />
      </button>

      {/* Main Content Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {currentPage === 'application' && (
          <>
            <div ref={mapRef} style={{ width: '100%', height: '100%', background: '#f5f5f5' }} />

            {showData && (
              <div style={{ 
                position: 'absolute', 
                bottom: '20px', 
                right: '20px', 
                background: 'white', 
                padding: '15px', 
                borderRadius: '8px', 
                boxShadow: '0 4px 15px rgba(0,0,0,0.3)', 
                zIndex: 500
              }}>
                <h3 style={{ margin: '0 0 10px 0', fontSize: '13px', fontWeight: '600' }}>
                  {selectedVariable === 'wind' ? 'Wind Speed (m/s)' : 
                   selectedMember === 'std' ? 'Uncertainty (mm/hr)' : 'Precipitation (mm/hr)'}
                </h3>
                <div style={{ 
                  height: '160px', 
                  width: '30px', 
                  background: `linear-gradient(to top, ${COLORMAPS[selectedColormap].colors.join(', ')})`,
                  borderRadius: '4px',
                  border: '1px solid #ccc',
                  position: 'relative'
                }}>
                  <div style={{ position: 'absolute', right: '-50px', top: '-2px', fontSize: '10px', fontWeight: '600' }}>
                    {stats ? stats.max : '100+'}
                  </div>
                  <div style={{ position: 'absolute', right: '-50px', top: '40px', fontSize: '10px', fontWeight: '600' }}>
                    {stats ? (parseFloat(stats.max) * 0.67).toFixed(1) : '50'}
                  </div>
                  <div style={{ position: 'absolute', right: '-50px', top: '80px', fontSize: '10px', fontWeight: '600' }}>
                    {stats ? (parseFloat(stats.max) * 0.33).toFixed(1) : '25'}
                  </div>
                  <div style={{ position: 'absolute', right: '-35px', bottom: '0', fontSize: '10px', fontWeight: '600' }}>0</div>
                </div>
              </div>
            )}
          </>
        )}

        {currentPage === 'about' && (
          <div style={{
            width: '100%',
            height: '100%',
            background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '40px'
          }}>
            <div style={{
              maxWidth: '800px',
              background: 'rgba(255,255,255,0.95)',
              borderRadius: '16px',
              padding: '40px',
              boxShadow: '0 20px 60px rgba(0,0,0,0.3)'
            }}>
              <h1 style={{ fontSize: '32px', marginBottom: '20px', color: '#2c3e50' }}>
                🌧️ WEAVE
              </h1>
              
              <p style={{ fontSize: '16px', lineHeight: '1.8', color: '#34495e', marginBottom: '30px' }}>
                WEAVE is an advanced visualization platform that displays ensemble forecast data from multiple weather models. Our system provides real-time visualization of precipitation and wind speed data, enabling better understanding of forecast uncertainty and model agreement.
              </p>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '30px' }}>
                <div style={{ background: '#ecf0f1', padding: '20px', borderRadius: '8px' }}>
                  <h3 style={{ fontSize: '16px', color: '#3498db', marginBottom: '10px' }}>Models</h3>
                  <ul style={{ fontSize: '14px', color: '#34495e', lineHeight: '1.8', paddingLeft: '20px' }}>
                    <li>AIFS (50 members)</li>
                    <li>GEFS (30 members)</li>
                    <li>UKMO (18 members)</li>
                  </ul>
                </div>

                <div style={{ background: '#ecf0f1', padding: '20px', borderRadius: '8px' }}>
                  <h3 style={{ fontSize: '16px', color: '#e74c3c', marginBottom: '10px' }}>Variables</h3>
                  <ul style={{ fontSize: '14px', color: '#34495e', lineHeight: '1.8', paddingLeft: '20px' }}>
                    <li>Precipitation (mm/hr)</li>
                    <li>Wind Speed (m/s)</li>
                    <li>Ensemble Statistics</li>
                  </ul>
                </div>
              </div>

              <div style={{ background: '#3498db', color: 'white', padding: '20px', borderRadius: '8px', marginBottom: '20px' }}>
                <h3 style={{ fontSize: '16px', marginBottom: '10px' }}>Visualization Technology</h3>
                <p style={{ fontSize: '14px', lineHeight: '1.6' }}>
                  Dynamic canvas-based rendering using Inverse Distance Weighting (IDW) interpolation. 
                  Real-time calculation of spatial gradients from point-based weather data stored in PostgreSQL.
                </p>
              </div>

              <div style={{ textAlign: 'center', fontSize: '14px', color: '#7f8c8d' }}>
                <p>Built with React, Leaflet, Flask, and PostgreSQL</p>
                <p style={{ marginTop: '10px' }}>© 2026 WEAVE Team</p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;