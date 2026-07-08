import React from 'react';
import { HelpCircle, Minus, Square, Grid3x3, Fan, AlignJustify, Navigation, Waves, RefreshCw, BarChart3, LayoutGrid } from 'lucide-react';

/**
 * Slide-in right panel — Display Settings.
 *
 * Props:
 *   open               {boolean}
 *   colormaps          {object}  COLORMAPS constant
 *   selectedColormap   {string}
 *   setSelectedColormap {fn}
 *   selectedVariable   {string}
 *   showWindArrows     {boolean}
 *   setShowWindArrows  {fn}
 *   showWindLines      {boolean}
 *   setShowWindLines   {fn}
 *   uncertaintyMode    {string|null}
 *   setUncertaintyMode {fn}
 */
export function RightPanel({
  open,
  colormaps,
  selectedColormap,    setSelectedColormap,
  selectedVariable,
  showWindArrows,      setShowWindArrows,
  showWindLines,       setShowWindLines,
  uncertaintyMode,     setUncertaintyMode,
  invertUncertainty,   setInvertUncertainty,
  numBuckets,          setNumBuckets,
  flipColormap,        setFlipColormap,
  gridOpacity,         setGridOpacity,
  textureStyle,        setTextureStyle,
}) {
  const showTexture = uncertaintyMode === 'texture';
  const label = { fontSize: '11px', fontWeight: 500, color: 'rgba(255,255,255,0.5)', letterSpacing: '0.01em', marginBottom: '8px' };
  const row   = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' };
  // Small "?" that shows a plain-language explanation on hover (native title tooltip).
  const Hint = ({ text }) => (
    <span title={text} aria-label={text} style={{ cursor: 'help', display: 'inline-flex', verticalAlign: '-2px', marginLeft: '5px', color: 'rgba(255,255,255,0.35)' }}>
      <HelpCircle size={12} />
    </span>
  );

  return (
    <div style={{
      position: 'absolute', top: 0, right: open ? '0' : '-290px',
      width: '270px', height: '100%',
      background: 'rgba(15,25,35,0.97)', color: 'white',
      boxShadow: '-4px 0 20px rgba(0,0,0,0.4)',
      transition: 'right 0.3s ease',
      zIndex: 1000, overflowY: 'auto', display: 'flex', flexDirection: 'column',
    }}>
      {/* Header */}
      <div style={{ padding: '16px 18px 14px', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingTop: '20px', flexShrink: 0 }}>
        <div style={label}>Display</div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 18px' }}>

        {/* ── Colour Scheme ──────────────────────────────────────────────── */}
        <div style={{ marginBottom: '22px' }}>
          <div style={label}>Colour scheme</div>
          <select value={selectedColormap} onChange={e => setSelectedColormap(e.target.value)}
            style={{ width: '100%', padding: '8px 10px', fontSize: '13px', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '7px', background: 'rgba(255,255,255,0.07)', color: 'white', cursor: 'pointer', outline: 'none', marginBottom: '8px' }}>
            {Object.keys(colormaps).map(name => (
              <option key={name} value={name} style={{ background: '#0f1923' }}>{name}</option>
            ))}
          </select>
          {/* Gradient preview — reversed when flip is on */}
          <div style={{ height: '10px', borderRadius: '5px', marginBottom: '12px', background: `linear-gradient(to right, ${(flipColormap ? [...colormaps[selectedColormap].colors].reverse() : colormaps[selectedColormap].colors).join(', ')})`, border: '1px solid rgba(255,255,255,0.12)' }} />

          {/* Flip Colormap */}
          <div style={row}>
            <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.7)' }}>Flip colours<Hint text="Reverse the colour scale — e.g. so heavy rain reads dark instead of light." /></span>
            <div onClick={() => setFlipColormap(v => !v)} style={{ width: '40px', height: '22px', borderRadius: '11px', cursor: 'pointer', flexShrink: 0, background: flipColormap ? '#3498db' : 'rgba(255,255,255,0.15)', position: 'relative', transition: 'background 0.2s' }}>
              <div style={{ position: 'absolute', top: '3px', left: flipColormap ? '21px' : '3px', width: '16px', height: '16px', borderRadius: '50%', background: 'white', transition: 'left 0.2s' }} />
            </div>
          </div>

          {/* Grid Opacity */}
          <div style={{ marginBottom: '10px' }}>
            <div style={{ ...row, marginBottom: '4px' }}>
              <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.7)' }}>Grid opacity<Hint text="How see-through the overlay is, so the map underneath shows through." /></span>
              <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.45)' }}>{(gridOpacity ?? 1).toFixed(1)}</span>
            </div>
            <input type="range" min="0" max="1" step="0.05" value={gridOpacity ?? 1} onChange={e => setGridOpacity(parseFloat(e.target.value))} style={{ width: '100%', accentColor: '#3498db', cursor: 'pointer' }} />
          </div>

          {/* Number of Buckets */}
          <div style={row}>
              <div>
                <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.7)' }}>Number of buckets<Hint text="Group values into this many discrete colour/size steps. 0 = smooth, continuous shading." /></span>
                <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.3)' }}>0 = continuous</div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <button onClick={() => setNumBuckets(v => Math.max(0, v - 1))} style={{ width: '24px', height: '24px', borderRadius: '4px', border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.07)', color: 'white', cursor: 'pointer', fontSize: '16px', lineHeight: '22px', textAlign: 'center' }}>−</button>
                <span style={{ fontSize: '13px', minWidth: '22px', textAlign: 'center', fontWeight: '600' }}>{numBuckets ?? 0}</span>
                <button onClick={() => setNumBuckets(v => Math.min(20, v + 1))} style={{ width: '24px', height: '24px', borderRadius: '4px', border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.07)', color: 'white', cursor: 'pointer', fontSize: '16px', lineHeight: '22px', textAlign: 'center' }}>+</button>
              </div>
          </div>
        </div>

        {/* ── Wind overlays ─────────────────────────────────────────────── */}
        {selectedVariable === 'wind' && (
          <div style={{ marginBottom: '22px' }}>
            <div style={label}>Wind overlay</div>
            <div style={{ display: 'flex', gap: '6px' }}>
              {[
                { key: 'arrows',      state: showWindArrows, setter: () => { setShowWindArrows(v => !v); if (showWindLines)  setShowWindLines(false);  }, icon: Navigation, btnLabel: 'Arrows' },
                { key: 'streamlines', state: showWindLines,  setter: () => { setShowWindLines(v => !v);  if (showWindArrows) setShowWindArrows(false); }, icon: Waves, btnLabel: 'Streamlines' },
              ].map(({ key, state, setter, icon: Icon, btnLabel }) => (
                <button key={key} onClick={setter}
                  style={{ flex: 1, padding: '8px 6px', fontSize: '12px', fontWeight: '600',
                    border: state ? '1.5px solid rgba(52,152,219,0.8)' : '1.5px solid rgba(255,255,255,0.1)',
                    borderRadius: '7px',
                    background: state ? 'rgba(52,152,219,0.18)' : 'rgba(255,255,255,0.04)',
                    color: state ? '#7ec8f7' : 'rgba(255,255,255,0.5)',
                    cursor: 'pointer', transition: 'all 0.15s', textAlign: 'center',
                  }}>
                  <div style={{ marginBottom: '2px', display: 'flex', justifyContent: 'center' }}><Icon size={16} /></div>
                  <div>{btnLabel}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* ── Uncertainty Overlay ───────────────────────────────────────── */}
        <div style={{ marginBottom: '22px' }}>
          <div style={label}>Uncertainty style<Hint text="How the ensemble's spread — the model's uncertainty — is drawn over the forecast." /></div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {[
              { mode: null,        icon: Minus,        label: 'None',    tech: '',          desc: 'Standard forecast colours' },
              { mode: 'vsup',      icon: Square,       label: 'Boxes',   tech: 'VSUP',      desc: 'Box size shows spread' },
              { mode: 'bivariate', icon: Grid3x3,      label: 'Grid',    tech: 'bivariate', desc: 'Value × uncertainty' },
              { mode: 'fan',       icon: Fan,          label: 'Fan',     tech: 'VSUP fan',  desc: 'Detail fades as spread grows' },
              { mode: 'texture',   icon: AlignJustify, label: 'Texture', tech: '',          desc: 'Hatching shows spread' },
            ].map(({ mode, icon: Icon, label: modeLabel, tech, desc }) => {
              const active = uncertaintyMode === mode;
              return (
                <button key={String(mode)} onClick={() => setUncertaintyMode(mode)}
                  style={{ display: 'flex', alignItems: 'center', gap: '10px', width: '100%', padding: '9px 12px', textAlign: 'left',
                    border: active ? '1.5px solid rgba(52,152,219,0.7)' : '1.5px solid rgba(255,255,255,0.07)',
                    borderRadius: '8px',
                    background: active ? 'rgba(52,152,219,0.14)' : 'rgba(255,255,255,0.03)',
                    cursor: 'pointer', transition: 'all 0.15s',
                  }}>
                  <div style={{ width: '14px', height: '14px', borderRadius: '50%', border: active ? '4px solid #3498db' : '2px solid rgba(255,255,255,0.3)', flexShrink: 0, background: active ? 'white' : 'transparent', transition: 'all 0.15s' }} />
                  <Icon size={17} style={{ flexShrink: 0, color: active ? '#7ec8f7' : 'rgba(255,255,255,0.6)' }} />
                  <div>
                    <div style={{ fontSize: '12px', fontWeight: '600', color: active ? '#7ec8f7' : 'rgba(255,255,255,0.75)', lineHeight: 1.2 }}>{modeLabel}{tech && <span style={{ fontWeight: 400, color: 'rgba(255,255,255,0.35)' }}> · {tech}</span>}</div>
                    <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.3)', marginTop: '2px', lineHeight: 1.3 }}>{desc}</div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* ── Texture Settings ──────────────────────────────────────────── */}
        {showTexture && (
          <div style={{ marginBottom: '22px' }}>
            <div style={label}>Texture settings</div>
            <div style={{ display: 'flex', gap: '6px' }}>
              {['Lines', 'Squares'].map(s => {
                const active = textureStyle === s;
                return (
                  <button key={s} onClick={() => setTextureStyle(s)}
                    style={{ flex: 1, padding: '9px 8px', fontSize: '12px', fontWeight: '600', border: active ? '1.5px solid rgba(52,152,219,0.8)' : '1.5px solid rgba(255,255,255,0.1)', borderRadius: '7px', background: active ? 'rgba(52,152,219,0.18)' : 'rgba(255,255,255,0.04)', color: active ? '#7ec8f7' : 'rgba(255,255,255,0.5)', cursor: 'pointer', transition: 'all 0.15s', textAlign: 'center' }}>
                    <div style={{ marginBottom: '3px', display: 'flex', justifyContent: 'center' }}>{s === 'Lines' ? <AlignJustify size={18} /> : <LayoutGrid size={18} />}</div>
                    {s}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* ── Uncertainty Direction ──────────────────────────────────────── */}
        {uncertaintyMode !== null && (
          <div style={{ marginBottom: '22px' }}>
            <div style={label}>Uncertainty direction<Hint text="Whether high uncertainty is shown muted (normal) or vivid (inverted)." /></div>
            <button
              onClick={() => setInvertUncertainty(v => !v)}
              style={{
                display: 'flex', alignItems: 'center', gap: '10px',
                width: '100%', padding: '9px 12px', textAlign: 'left',
                border: invertUncertainty
                  ? '1.5px solid rgba(231,76,60,0.7)'
                  : '1.5px solid rgba(255,255,255,0.07)',
                borderRadius: '8px',
                background: invertUncertainty
                  ? 'rgba(231,76,60,0.14)'
                  : 'rgba(255,255,255,0.03)',
                cursor: 'pointer', transition: 'all 0.15s', color: 'white',
              }}
            >
              <span style={{ display: 'inline-flex' }}>{invertUncertainty ? <RefreshCw size={18} /> : <BarChart3 size={18} />}</span>
              <div>
                <div style={{ fontSize: '12px', fontWeight: '600', color: invertUncertainty ? '#f1948a' : 'rgba(255,255,255,0.75)', lineHeight: 1.2 }}>
                  {invertUncertainty ? 'Inverted' : 'Normal'}
                </div>
                <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.3)', marginTop: '2px', lineHeight: 1.3 }}>
                  {invertUncertainty ? 'High uncertainty = vivid' : 'High uncertainty = muted'}
                </div>
              </div>
            </button>
          </div>
        )}

      </div>
    </div>
  );
}
