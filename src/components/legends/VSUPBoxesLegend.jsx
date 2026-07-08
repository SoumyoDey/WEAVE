import React from 'react';

export function VSUPBoxesLegend({ stats, selectedVariable, invertUncertainty = false, numBuckets = 0, stdMax }) {
  // When bucketing is on, show one row per bucket centre (largest → smallest) so the
  // key matches the discrete box sizes drawn on the map; otherwise a continuous scale.
  const fracs = numBuckets > 1
    ? Array.from({ length: numBuckets }, (_, i) => (numBuckets - i - 0.5) / numBuckets)
    : [1.0, 0.75, 0.5, 0.25, 0.05];
  const unit = selectedVariable === 'wind' ? 'm/s' : 'mm/hr';
  // Labels are std-dev values → use the true stdMax from the layer, not the value-max stat.
  const maxStd = Number.isFinite(stdMax) ? stdMax : parseFloat(stats.max);

  const cardStyle = {
    background: 'rgba(10,18,28,0.92)',
    border: '1px solid rgba(255,255,255,0.1)',
    backdropFilter: 'blur(8px)',
    padding: '12px 14px',
    borderRadius: '10px',
    boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
    minWidth: '160px',
    userSelect: 'none',
  };

  return (
    <div style={cardStyle}>
      <div style={{ color: 'white', fontSize: '12px', fontWeight: 600, marginBottom: '8px' }}>
        Boxes — spread
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {fracs.map((frac, i) => {
          const stdVal   = (maxStd * frac).toFixed(2);
          const sizeFrac = invertUncertainty ? (1 - frac) : frac;
          const boxSize  = Math.round(4 + Math.sqrt(sizeFrac) * (28 - 4));
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div
                style={{
                  width: boxSize,
                  height: boxSize,
                  background: 'rgba(52,152,219,0.35)',
                  border: '1.5px solid rgba(52,152,219,0.7)',
                  borderRadius: '2px',
                  flexShrink: 0,
                }}
              />
              <span style={{ color: 'rgba(255,255,255,0.8)', fontSize: '11px' }}>{stdVal}</span>
            </div>
          );
        })}
      </div>

      <div style={{ color: 'rgba(255,255,255,0.45)', fontSize: '10px', marginTop: '10px' }}>
        Std Dev ({unit}) — {invertUncertainty ? 'smaller = more uncertain' : 'larger = more uncertain'}
      </div>
    </div>
  );
}
