import React from 'react';
import { CloudRain, X } from 'lucide-react';

/**
 * Full-screen About / info modal.
 *
 * Props:
 *   onClose        {fn}
 *   stats          {object|null}  — { total, average, max, min }
 *   selectedVariable {string}
 *   currentModel   {object}
 */
export function AboutModal({ onClose, stats, selectedVariable, currentModel }) {
  return (
    <div
      onClick={onClose}
      style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(102,126,234,0.98)', backdropFilter: 'blur(10px)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px', zIndex: 1500 }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{ position: 'relative', maxWidth: '800px', width: '100%', background: 'rgba(255,255,255,0.98)', borderRadius: '16px', padding: '40px', boxShadow: '0 20px 60px rgba(0,0,0,0.4)', maxHeight: '80vh', overflowY: 'auto' }}
      >
        <button
          onClick={onClose}
          style={{ position: 'absolute', top: '16px', right: '16px', width: '32px', height: '32px', background: 'rgba(0,0,0,0.08)', border: 'none', borderRadius: '8px', cursor: 'pointer', color: '#555', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          title="Close"
        ><X size={18} /></button>

        <h1 style={{ fontSize: '32px', marginBottom: '20px', color: '#2c3e50', display: 'flex', alignItems: 'center', gap: '10px' }}><CloudRain size={30} style={{ color: '#3498db' }} />WEAVE</h1>
        <p style={{ fontSize: '16px', lineHeight: '1.8', color: '#34495e', marginBottom: '30px' }}>
          WEAVE is an advanced visualization platform that displays ensemble forecast data from multiple weather models. Our system provides real-time visualization of precipitation and wind speed data, enabling better understanding of forecast uncertainty and model agreement.
        </p>

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
          <p style={{ fontSize: '14px', lineHeight: '1.6', margin: 0 }}>
            Dynamic canvas-based rendering using Inverse Distance Weighting (IDW) interpolation. Real-time spatial gradients from point-based weather data stored in PostgreSQL.
          </p>
        </div>

        {stats && (
          <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px', marginBottom: '20px' }}>
            <h4 style={{ fontSize: '14px', marginBottom: '15px', color: '#9b59b6', marginTop: 0 }}>Current Data Statistics</h4>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
              {[
                ['DATA POINTS', stats.total.toLocaleString(),                                          currentModel.color],
                ['AVERAGE',     `${stats.average} ${selectedVariable === 'wind' ? 'm/s' : 'mm/hr'}`, '#3498db'],
                ['MAXIMUM',     `${stats.max} ${selectedVariable === 'wind' ? 'm/s' : 'mm/hr'}`,     '#e74c3c'],
                ['MINIMUM',     `${stats.min} ${selectedVariable === 'wind' ? 'm/s' : 'mm/hr'}`,     '#2ecc71'],
              ].map(([label, value, color]) => (
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
  );
}
