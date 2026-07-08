import React, { useState, useEffect } from 'react';
import { SlidersHorizontal, Map as MapIcon, Layers, X } from 'lucide-react';

const STEPS = [
  { icon: SlidersHorizontal, title: 'Pick your data', body: 'Open Controls (top-left) to choose the model, variable, and forecast time. The bar up top always shows what you’re looking at.' },
  { icon: MapIcon,           title: 'Read the map',   body: 'Colours show the forecast value. The legend (bottom-right) spells out what darker or denser shading means.' },
  { icon: Layers,            title: 'Explore uncertainty', body: 'Switch the uncertainty style to see how much the ensemble members disagree, or click any point on the map for detailed analysis.' },
];

/** First-run guided intro. Rendered only when `open`; parent handles the once-only gate. */
export function OnboardingTour({ open, onClose }) {
  const [step, setStep] = useState(0);
  useEffect(() => { if (open) setStep(0); }, [open]);
  if (!open) return null;

  const { icon: Icon, title, body } = STEPS[step];
  const last = step === STEPS.length - 1;

  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 3000, background: 'rgba(6,12,20,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
      <div role="dialog" aria-modal="true" aria-label="Welcome to WEAVE"
        style={{ width: '380px', maxWidth: '100%', background: '#16212c', border: '0.5px solid rgba(255,255,255,0.12)', borderRadius: '14px', boxShadow: '0 20px 60px rgba(0,0,0,0.5)', color: '#e6edf3', overflow: 'hidden' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 14px 0' }}>
          <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)' }}>Step {step + 1} of {STEPS.length}</span>
          <button onClick={onClose} title="Skip" aria-label="Skip tour" style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.5)', cursor: 'pointer', display: 'flex', padding: '4px' }}><X size={16} /></button>
        </div>
        <div style={{ padding: '6px 24px 22px', textAlign: 'center' }}>
          <div style={{ width: '56px', height: '56px', borderRadius: '14px', background: 'rgba(58,160,255,0.15)', color: '#7ec8f7', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '8px auto 16px' }}><Icon size={28} /></div>
          <h2 style={{ margin: '0 0 8px', fontSize: '18px', fontWeight: 600, color: 'white' }}>{title}</h2>
          <p style={{ margin: 0, fontSize: '13px', lineHeight: 1.6, color: 'rgba(255,255,255,0.7)' }}>{body}</p>

          <div style={{ display: 'flex', justifyContent: 'center', gap: '6px', margin: '18px 0' }}>
            {STEPS.map((_, i) => (
              <span key={i} style={{ width: i === step ? '18px' : '6px', height: '6px', borderRadius: '3px', background: i === step ? '#3aa0ff' : 'rgba(255,255,255,0.2)', transition: 'all 0.2s' }} />
            ))}
          </div>

          <div style={{ display: 'flex', gap: '8px' }}>
            {step > 0 && (
              <button onClick={() => setStep(s => s - 1)} style={{ flex: 1, padding: '9px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.15)', background: 'transparent', color: '#cdd8e3', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}>Back</button>
            )}
            <button onClick={() => (last ? onClose() : setStep(s => s + 1))} style={{ flex: 2, padding: '9px', borderRadius: '8px', border: 'none', background: '#3aa0ff', color: '#04213a', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}>
              {last ? 'Get started' : 'Next'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
