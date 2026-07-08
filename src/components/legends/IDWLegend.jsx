import React from 'react';

export function IDWLegend({ selectedColormap, stats, selectedVariable, selectedMember, getLegendGradient, flipColormap = false, numBuckets = 0 }) {
  const isWind = selectedVariable === 'wind';
  const isStd = selectedMember === 'std';

  const varLabel = isWind ? 'Wind Speed' : isStd ? 'Uncertainty' : 'Precipitation';
  const unit = isWind ? 'm/s' : 'mm/hr';

  const maxVal = stats ? parseFloat(stats.max) : 5;
  const fracs = [0, 0.25, 0.5, 0.75, 1];
  const tickLabels = fracs.map(f => (maxVal * f).toFixed(f === 1 ? 0 : 2));

  const cardStyle = {
    background: 'rgba(10,18,28,0.92)',
    border: '1px solid rgba(255,255,255,0.1)',
    backdropFilter: 'blur(8px)',
    padding: '12px 14px',
    borderRadius: '10px',
    boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
    minWidth: '200px',
    userSelect: 'none',
  };

  return (
    <div style={cardStyle}>
      <div style={{ color: 'white', fontSize: '12px', fontWeight: 600, marginBottom: '8px' }}>
        {varLabel} <span style={{ fontWeight: 400, opacity: 0.7 }}>({unit})</span>
      </div>

      {/* Gradient bar */}
      <div style={{ position: 'relative', marginBottom: '4px' }}>
        <div
          style={{
            height: '14px',
            borderRadius: '6px',
            background: getLegendGradient(selectedColormap, flipColormap, numBuckets),
          }}
        />
        {/* Tick lines */}
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '14px', display: 'flex', justifyContent: 'space-between', pointerEvents: 'none' }}>
          {[0, 25, 50, 75, 100].map(pct => (
            <div
              key={pct}
              style={{
                width: '1px',
                height: '100%',
                background: 'rgba(255,255,255,0.4)',
              }}
            />
          ))}
        </div>
      </div>

      {/* Tick labels */}
      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        {tickLabels.map((label, i) => (
          <div key={i} style={{ color: 'rgba(255,255,255,0.7)', fontSize: '10px', textAlign: 'center' }}>
            {label}
          </div>
        ))}
      </div>

      <div style={{ color: 'rgba(255,255,255,0.6)', fontSize: '10px', marginTop: '8px' }}>
        Darker = {isWind ? 'faster wind' : isStd ? 'more uncertainty' : 'more rain'}.
      </div>
    </div>
  );
}
