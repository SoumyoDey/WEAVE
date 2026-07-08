import React from 'react';

/**
 * Slide-in left panel — Forecast Controls.
 *
 * Props:
 *   open             {boolean}
 *   models           {object}   MODELS constant
 *   selectedModel    {string}
 *   setSelectedModel {fn}
 *   selectedVariable {string}
 *   setSelectedVariable {fn}
 *   currentModel     {object}
 *   getMemberOptions {fn}
 *   selectedMember   {string}
 *   setSelectedMember {fn}
 *   loading          {boolean}
 *   error            {string}
 *   uncertaintyMode  {string|null}
 */
export function LeftPanel({
  open,
  models,
  selectedModel, setSelectedModel,
  selectedVariable, setSelectedVariable,
  currentModel,
  getMemberOptions, selectedMember, setSelectedMember,
  loading, error,
  uncertaintyMode,
}) {
  return (
    <div style={{
      position: 'absolute', top: 0, left: open ? '0' : '-320px',
      width: '300px', height: '100%',
      background: 'rgba(15,25,35,0.97)', color: 'white',
      boxShadow: '4px 0 20px rgba(0,0,0,0.4)',
      transition: 'left 0.3s ease',
      zIndex: 1000, display: 'flex', flexDirection: 'column',
    }}>
      {/* Header */}
      <div style={{ padding: '16px 18px 14px', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingTop: '68px', flexShrink: 0 }}>
        <div style={{ fontSize: '15px', fontWeight: '700', color: 'white', marginBottom: '2px' }}>Forecast Controls</div>
        <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.35)' }}>Init: 2025-09-08 00:00 UTC</div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 18px' }}>

        {/* Model selector */}
        <div style={{ marginBottom: '20px' }}>
          <div style={{ fontSize: '11px', fontWeight: 500, color: 'rgba(255,255,255,0.5)', letterSpacing: '0.01em', marginBottom: '8px' }}>Model</div>
          <div style={{ display: 'flex', gap: '6px' }}>
            {Object.entries(models).map(([key, model]) => (
              <button key={key} onClick={() => setSelectedModel(key)}
                style={{ flex: 1, padding: '9px 6px', fontSize: '12px', fontWeight: '700',
                  border: selectedModel === key ? `2px solid ${model.color}` : '2px solid rgba(255,255,255,0.08)',
                  borderRadius: '8px',
                  background: selectedModel === key ? `${model.color}22` : 'rgba(255,255,255,0.04)',
                  color: selectedModel === key ? model.color : 'rgba(255,255,255,0.45)',
                  cursor: 'pointer', transition: 'all 0.15s', textAlign: 'center',
                }}>
                <div>{model.name}</div>
                <div style={{ fontSize: '10px', fontWeight: '400', opacity: 0.7, marginTop: '2px' }}>{model.ensembleCount} mbrs</div>
              </button>
            ))}
          </div>
        </div>

        <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', marginBottom: '20px' }} />

        {/* Variable selector */}
        <div style={{ marginBottom: '20px' }}>
          <div style={{ fontSize: '11px', fontWeight: 500, color: 'rgba(255,255,255,0.5)', letterSpacing: '0.01em', marginBottom: '8px' }}>Variable</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {[
              { val: 'precipitation', icon: '💧', label: 'Precipitation', unit: 'mm/hr' },
              { val: 'wind',          icon: '🌬️', label: 'Wind Speed',    unit: 'm/s'   },
            ].map(({ val, icon, label, unit }) => {
              const active = selectedVariable === val;
              return (
                <button key={val} onClick={() => setSelectedVariable(val)}
                  style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px',
                    border: active ? '1.5px solid rgba(52,152,219,0.7)' : '1.5px solid rgba(255,255,255,0.07)',
                    borderRadius: '8px',
                    background: active ? 'rgba(52,152,219,0.14)' : 'rgba(255,255,255,0.03)',
                    color: active ? '#7ec8f7' : 'rgba(255,255,255,0.55)',
                    cursor: 'pointer', transition: 'all 0.15s', textAlign: 'left', width: '100%',
                  }}>
                  <span style={{ fontSize: '18px', flexShrink: 0 }}>{icon}</span>
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: '600' }}>{label}</div>
                    <div style={{ fontSize: '10px', color: active ? 'rgba(126,200,247,0.6)' : 'rgba(255,255,255,0.3)', marginTop: '1px' }}>{unit}</div>
                  </div>
                  {active && <div style={{ marginLeft: 'auto', width: '6px', height: '6px', borderRadius: '50%', background: '#3498db', flexShrink: 0 }} />}
                </button>
              );
            })}
          </div>
        </div>

        <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', marginBottom: '20px' }} />

        {/* Ensemble member */}
        {currentModel.hasEnsemble && (
          <div style={{ marginBottom: '20px' }}>
            <div style={{ fontSize: '11px', fontWeight: 500, color: 'rgba(255,255,255,0.5)', letterSpacing: '0.01em', marginBottom: '8px' }}>Ensemble Member</div>
            <select value={selectedMember} onChange={e => setSelectedMember(e.target.value)}
              style={{ width: '100%', padding: '9px 10px', fontSize: '13px', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '7px', background: 'rgba(255,255,255,0.07)', color: 'white', cursor: 'pointer', outline: 'none' }}>
              {getMemberOptions().map(opt => <option key={opt.value} value={opt.value} style={{ background: '#0f1923' }}>{opt.label}</option>)}
            </select>
          </div>
        )}

        {/* Loading / error states */}
        {loading && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 12px', background: 'rgba(241,196,15,0.1)', border: '1px solid rgba(241,196,15,0.25)', borderRadius: '8px', marginBottom: '12px' }}>
            <span style={{ fontSize: '14px' }}>⏳</span>
            <span style={{ fontSize: '12px', color: '#f1c40f' }}>Loading forecast data…</span>
          </div>
        )}
        {error && (
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', padding: '10px 12px', background: 'rgba(231,76,60,0.1)', border: '1px solid rgba(231,76,60,0.25)', borderRadius: '8px', marginBottom: '12px' }}>
            <span style={{ fontSize: '14px', flexShrink: 0 }}>⚠️</span>
            <span style={{ fontSize: '12px', color: '#e74c3c', lineHeight: 1.4 }}>{error}</span>
          </div>
        )}

        {/* Active overlay pill */}
        {uncertaintyMode && (
          <div style={{ marginTop: '8px', padding: '8px 12px', background: 'rgba(52,152,219,0.1)', border: '1px solid rgba(52,152,219,0.25)', borderRadius: '8px' }}>
            <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.35)', marginBottom: '3px', letterSpacing: '0.02em' }}>Active overlay</div>
            <div style={{ fontSize: '12px', color: '#7ec8f7', fontWeight: '600' }}>
              {{ vsup: '⬛ VSup Boxes', bivariate: '🟦 Bivariate Map', fan: '🌀 VSUP Fan' }[uncertaintyMode]}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
