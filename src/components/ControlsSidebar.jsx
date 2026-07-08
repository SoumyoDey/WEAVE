import React, { useState } from 'react';
import {
  HelpCircle, Fan, AlignJustify, Navigation, Waves, LayoutGrid,
  Droplet, Wind, ChevronDown, ChevronRight, Loader, AlertTriangle,
  Database, Palette, SlidersHorizontal,
} from 'lucide-react';
import { Toggle } from './ui/Toggle';
import { t } from '../theme';

const sectionLabel = { fontSize: '11px', color: 'rgba(255,255,255,0.45)', letterSpacing: '0.01em', marginBottom: '9px', display: 'flex', alignItems: 'center', gap: '6px' };
const ctlLabel = { fontSize: '11px', fontWeight: 500, color: 'rgba(255,255,255,0.5)', marginBottom: '7px' };
const rowStyle = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' };

// Small "?" that shows a plain-language explanation on hover.
const Hint = ({ text }) => (
  <span title={text} aria-label={text} style={{ cursor: 'help', display: 'inline-flex', verticalAlign: '-2px', marginLeft: '5px', color: 'rgba(255,255,255,0.35)' }}>
    <HelpCircle size={12} />
  </span>
);

// Mini preview of what each uncertainty style looks like on the map.
const Thumb = ({ mode }) => {
  const box = { height: '26px', borderRadius: '4px', marginBottom: '5px', overflow: 'hidden' };
  if (mode === null) return <div style={{ ...box, display: 'flex' }}><span style={{ flex: 1, background: '#cfe0b8' }} /><span style={{ flex: 1, background: '#7fbfc9' }} /><span style={{ flex: 1, background: '#2f6fb5' }} /></div>;
  if (mode === 'vsup') return <div style={{ ...box, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '3px' }}><span style={{ width: '6px', height: '6px', background: '#2f6fb5' }} /><span style={{ width: '11px', height: '11px', background: '#3f86c9' }} /><span style={{ width: '16px', height: '16px', background: '#5b9bd0' }} /></div>;
  if (mode === 'bivariate') return <div style={{ ...box, display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gridTemplateRows: 'repeat(3,1fr)', gap: '1px', padding: '0 6px' }}>{['#eef7d9', '#a9cfc2', '#2f6fb5', '#dfe6cf', '#9fc3c9', '#5a86b0', '#cdd4c9', '#a7b6bd', '#8a9aa6'].map((c, i) => <span key={i} style={{ background: c }} />)}</div>;
  if (mode === 'fan') return <div style={{ ...box, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Fan size={20} style={{ color: '#5b9bd0' }} /></div>;
  if (mode === 'texture') return <div style={{ ...box, background: 'repeating-linear-gradient(45deg,#5b9bd0 0 2px,transparent 2px 5px)' }} />;
  return null;
};

const MODES = [
  { mode: null,        label: 'None' },
  { mode: 'vsup',      label: 'Boxes' },
  { mode: 'bivariate', label: 'Grid' },
  { mode: 'fan',       label: 'Fan' },
  { mode: 'texture',   label: 'Texture' },
];

/**
 * Unified left "Controls" sidebar — merges the former Data (left) and Display
 * (right) panels into one, with progressive disclosure (Data / Display / Advanced).
 */
export function ControlsSidebar({
  open, isNarrow = false,
  models, selectedModel, setSelectedModel,
  selectedVariable, setSelectedVariable,
  currentModel, getMemberOptions, selectedMember, setSelectedMember,
  loading, error,
  colormaps, selectedColormap, setSelectedColormap,
  uncertaintyMode, setUncertaintyMode,
  invertUncertainty, setInvertUncertainty,
  numBuckets, setNumBuckets,
  flipColormap, setFlipColormap,
  gridOpacity, setGridOpacity,
  textureStyle, setTextureStyle,
  showWindArrows, setShowWindArrows,
  showWindLines, setShowWindLines,
}) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const showTexture = uncertaintyMode === 'texture';

  return (
    <div style={{ position: 'absolute', top: 0, left: open ? '0' : (isNarrow ? '-92vw' : '-330px'), width: isNarrow ? '86vw' : '300px', maxWidth: '360px', height: '100%', background: t.panel, color: 'white', boxShadow: '4px 0 20px rgba(0,0,0,0.4)', transition: 'left 0.3s ease', zIndex: 1000, display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '14px 16px', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingTop: '64px', flexShrink: 0, display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 500 }}>
        <SlidersHorizontal size={16} style={{ color: '#3aa0ff' }} />Controls
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '14px 16px' }}>

        {/* ── Data ── */}
        <div style={sectionLabel}><Database size={13} />Data</div>
        <div style={{ display: 'flex', gap: '6px', marginBottom: '10px' }}>
          {Object.entries(models).map(([key, model]) => (
            <button key={key} onClick={() => setSelectedModel(key)} title={`${model.ensembleCount} members`}
              style={{ flex: 1, padding: '8px 4px', fontSize: '12px', fontWeight: '700', border: selectedModel === key ? `2px solid ${model.color}` : '2px solid rgba(255,255,255,0.08)', borderRadius: '8px', background: selectedModel === key ? `${model.color}22` : 'rgba(255,255,255,0.04)', color: selectedModel === key ? model.color : 'rgba(255,255,255,0.45)', cursor: 'pointer', transition: 'all 0.15s' }}>
              {model.name}
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: '6px', marginBottom: '10px' }}>
          {[{ val: 'precipitation', icon: Droplet, label: 'Precip' }, { val: 'wind', icon: Wind, label: 'Wind' }].map(({ val, icon: Icon, label }) => {
            const active = selectedVariable === val;
            return (
              <button key={val} onClick={() => setSelectedVariable(val)}
                style={{ flex: 1, padding: '8px', fontSize: '12px', fontWeight: '600', border: active ? '1.5px solid rgba(52,152,219,0.7)' : '1.5px solid rgba(255,255,255,0.07)', borderRadius: '8px', background: active ? 'rgba(52,152,219,0.14)' : 'rgba(255,255,255,0.03)', color: active ? '#7ec8f7' : 'rgba(255,255,255,0.55)', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                <Icon size={14} />{label}
              </button>
            );
          })}
        </div>
        {currentModel.hasEnsemble && (
          <select value={selectedMember} onChange={e => setSelectedMember(e.target.value)}
            style={{ width: '100%', padding: '8px 10px', fontSize: '12px', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '7px', background: 'rgba(255,255,255,0.07)', color: 'white', cursor: 'pointer', outline: 'none', marginBottom: '18px' }}>
            {getMemberOptions().map(opt => <option key={opt.value} value={opt.value} style={{ background: '#0f1923' }}>{opt.label}</option>)}
          </select>
        )}

        {/* ── Display ── */}
        <div style={sectionLabel}><Palette size={13} />Display</div>
        <div style={ctlLabel}>Colour scheme</div>
        <select value={selectedColormap} onChange={e => setSelectedColormap(e.target.value)}
          style={{ width: '100%', padding: '8px 10px', fontSize: '12px', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '7px', background: 'rgba(255,255,255,0.07)', color: 'white', cursor: 'pointer', outline: 'none', marginBottom: '8px' }}>
          {Object.keys(colormaps).map(n => <option key={n} value={n} style={{ background: '#0f1923' }}>{n}</option>)}
        </select>
        <div style={{ height: '9px', borderRadius: '4px', marginBottom: '14px', background: `linear-gradient(to right, ${(flipColormap ? [...colormaps[selectedColormap].colors].reverse() : colormaps[selectedColormap].colors).join(', ')})`, border: '1px solid rgba(255,255,255,0.12)' }} />

        <div style={ctlLabel}>Uncertainty style<Hint text="How the ensemble's spread — the model's uncertainty — is drawn over the forecast." /></div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '6px', marginBottom: '16px' }}>
          {MODES.map(({ mode, label }) => {
            const active = uncertaintyMode === mode;
            return (
              <button key={String(mode)} onClick={() => setUncertaintyMode(mode)}
                style={{ border: active ? '1.5px solid rgba(58,160,255,0.7)' : '0.5px solid rgba(255,255,255,0.1)', background: active ? 'rgba(58,160,255,0.12)' : 'rgba(255,255,255,0.03)', borderRadius: '8px', padding: '6px 4px 5px', cursor: 'pointer', textAlign: 'center' }}>
                <Thumb mode={mode} />
                <div style={{ fontSize: '11px', color: active ? '#cfe8fb' : 'rgba(255,255,255,0.75)' }}>{label}</div>
              </button>
            );
          })}
        </div>

        {/* ── Advanced (progressive disclosure) ── */}
        <button onClick={() => setShowAdvanced(v => !v)}
          style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'none', borderTop: '0.5px solid rgba(255,255,255,0.08)', borderLeft: 'none', borderRight: 'none', borderBottom: 'none', padding: '11px 0 0', color: 'rgba(255,255,255,0.6)', fontSize: '12px', cursor: 'pointer' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}><SlidersHorizontal size={13} />Advanced</span>
          {showAdvanced ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </button>

        {showAdvanced && (
          <div style={{ paddingTop: '12px' }}>
            <div style={rowStyle}>
              <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.7)' }}>Flip colours<Hint text="Reverse the colour scale — e.g. so heavy rain reads dark instead of light." /></span>
              <Toggle on={flipColormap} onChange={setFlipColormap} label="Flip colours" />
            </div>

            <div style={{ marginBottom: '10px' }}>
              <div style={{ ...rowStyle, marginBottom: '4px' }}>
                <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.7)' }}>Grid opacity<Hint text="How see-through the overlay is, so the map underneath shows through." /></span>
                <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.45)' }}>{(gridOpacity ?? 1).toFixed(1)}</span>
              </div>
              <input type="range" min="0" max="1" step="0.05" value={gridOpacity ?? 1} onChange={e => setGridOpacity(parseFloat(e.target.value))} style={{ width: '100%', accentColor: '#3498db', cursor: 'pointer' }} />
            </div>

            <div style={rowStyle}>
              <div>
                <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.7)' }}>Number of buckets<Hint text="Group values into this many discrete colour/size steps. 0 = smooth, continuous shading." /></span>
                <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.3)' }}>0 = continuous</div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <button onClick={() => setNumBuckets(v => Math.max(0, v - 1))} style={{ width: '24px', height: '24px', borderRadius: '4px', border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.07)', color: 'white', cursor: 'pointer', fontSize: '16px', lineHeight: '22px' }}>−</button>
                <span style={{ fontSize: '13px', minWidth: '22px', textAlign: 'center', fontWeight: '600' }}>{numBuckets ?? 0}</span>
                <button onClick={() => setNumBuckets(v => Math.min(20, v + 1))} style={{ width: '24px', height: '24px', borderRadius: '4px', border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.07)', color: 'white', cursor: 'pointer', fontSize: '16px', lineHeight: '22px' }}>+</button>
              </div>
            </div>

            {uncertaintyMode !== null && (
              <div style={rowStyle}>
                <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.7)' }}>Invert uncertainty<Hint text="Whether high uncertainty is shown muted (off) or vivid (on)." /></span>
                <Toggle on={invertUncertainty} onChange={setInvertUncertainty} color={t.warn} label="Invert uncertainty" />
              </div>
            )}

            {showTexture && (
              <div style={{ marginTop: '6px' }}>
                <div style={ctlLabel}>Texture settings</div>
                <div style={{ display: 'flex', gap: '6px' }}>
                  {['Lines', 'Squares'].map(s => {
                    const active = textureStyle === s;
                    return (
                      <button key={s} onClick={() => setTextureStyle(s)} style={{ flex: 1, padding: '8px', fontSize: '12px', fontWeight: '600', border: active ? '1.5px solid rgba(52,152,219,0.8)' : '1.5px solid rgba(255,255,255,0.1)', borderRadius: '7px', background: active ? 'rgba(52,152,219,0.18)' : 'rgba(255,255,255,0.04)', color: active ? '#7ec8f7' : 'rgba(255,255,255,0.5)', cursor: 'pointer', display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: '3px' }}>
                        {s === 'Lines' ? <AlignJustify size={16} /> : <LayoutGrid size={16} />}{s}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {selectedVariable === 'wind' && (
              <div style={{ marginTop: '12px' }}>
                <div style={ctlLabel}>Wind overlay</div>
                <div style={{ display: 'flex', gap: '6px' }}>
                  {[
                    { key: 'arrows', state: showWindArrows, setter: () => { setShowWindArrows(v => !v); if (showWindLines) setShowWindLines(false); }, icon: Navigation, label: 'Arrows' },
                    { key: 'streamlines', state: showWindLines, setter: () => { setShowWindLines(v => !v); if (showWindArrows) setShowWindArrows(false); }, icon: Waves, label: 'Streamlines' },
                  ].map(({ key, state, setter, icon: Icon, label }) => (
                    <button key={key} onClick={setter} style={{ flex: 1, padding: '8px 6px', fontSize: '12px', fontWeight: '600', border: state ? '1.5px solid rgba(52,152,219,0.8)' : '1.5px solid rgba(255,255,255,0.1)', borderRadius: '7px', background: state ? 'rgba(52,152,219,0.18)' : 'rgba(255,255,255,0.04)', color: state ? '#7ec8f7' : 'rgba(255,255,255,0.5)', cursor: 'pointer', display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: '2px' }}>
                      <Icon size={15} />{label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {loading && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 12px', background: 'rgba(241,196,15,0.1)', border: '1px solid rgba(241,196,15,0.25)', borderRadius: '8px', marginTop: '14px' }}>
            <Loader size={14} style={{ color: '#f1c40f' }} /><span style={{ fontSize: '12px', color: '#f1c40f' }}>Loading forecast data…</span>
          </div>
        )}
        {error && (
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', padding: '10px 12px', background: 'rgba(231,76,60,0.1)', border: '1px solid rgba(231,76,60,0.25)', borderRadius: '8px', marginTop: '14px' }}>
            <AlertTriangle size={14} style={{ color: '#e74c3c', flexShrink: 0 }} /><span style={{ fontSize: '12px', color: '#e74c3c', lineHeight: 1.4 }}>{error}</span>
          </div>
        )}
      </div>
    </div>
  );
}
