import React from 'react';

export function BivariateLegend({ bivariateRanges, selectedColormap, selectedVariable, buildColorMatrix, invertUncertainty = false, numBuckets = 0, flipColormap = false }) {
  if (!bivariateRanges) return null;

  const { meanMax, stdMax } = bivariateRanges;
  // Grid size follows the Number of Buckets control (0/1 → default 4×4 preview).
  const size = numBuckets > 1 ? numBuckets : 4;
  const cols = size;
  const rows = size;
  const cellSize = size <= 4 ? 36 : Math.max(12, Math.round(144 / size));

  const xTicks = Array.from({ length: cols + 1 }, (_, i) => +(meanMax * i / cols).toFixed(2));
  // Normal:   top row = row 0 (vivid, low σ) → tick 0 at top, stdMax at bottom
  // Inverted: top row = row 0 (now muted, high σ) → tick stdMax at top, 0 at bottom
  const yTicks = Array.from({ length: rows + 1 }, (_, i) =>
    +(stdMax * (invertUncertainty ? (rows - i) / rows : i / rows)).toFixed(2)
  );

  const xLabel = selectedVariable === 'wind' ? 'Wind Speed' : 'Precipitation';
  const unit   = selectedVariable === 'wind' ? 'm/s' : 'mm/hr';

  const colorMatrix = buildColorMatrix(selectedColormap, false, invertUncertainty, size, flipColormap);

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
        Grid — {xLabel}
      </div>

      {/* X-tick row — sits only above the grid, no right-block interference */}
      <div style={{ display: 'flex', flexDirection: 'row', marginBottom: '2px' }}>
        {xTicks.map((tick, i) => (
          <div
            key={i}
            style={{
              width: (i === 0 || i === cols) ? cellSize / 2 : cellSize,
              fontSize: '10px',
              color: 'rgba(255,255,255,0.7)',
              textAlign: 'center',
            }}
          >
            {tick}
          </div>
        ))}
      </div>

      {/* Grid + Y-ticks in the same row so Y-ticks align exactly with grid rows */}
      <div style={{ display: 'flex', flexDirection: 'row', alignItems: 'flex-start' }}>
        {/* Color grid — row 0 (vivid, low σ) at top, row 3 (muted, high σ) at bottom */}
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {colorMatrix.map((row, ri) => (
            <div key={ri} style={{ display: 'flex', flexDirection: 'row' }}>
              {row.map((color, ci) => (
                <div
                  key={ci}
                  style={{ width: cellSize, height: cellSize, background: color }}
                />
              ))}
            </div>
          ))}
        </div>

        {/* Y-tick labels + rotated Y-axis label — aligned with grid */}
        <div style={{ display: 'flex', flexDirection: 'row', marginLeft: '4px' }}>
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              height: cellSize * rows,
              justifyContent: 'space-between',
            }}
          >
            {yTicks.map((tick, i) => (
              <div
                key={i}
                style={{ fontSize: '10px', color: 'rgba(255,255,255,0.7)' }}
              >
                {tick}
              </div>
            ))}
          </div>

          <div
            style={{
              writingMode: 'vertical-rl',
              transform: 'rotate(180deg)',
              fontSize: '10px',
              color: 'rgba(255,255,255,0.6)',
              marginLeft: '4px',
              alignSelf: 'center',
            }}
          >
            Uncertainty ({unit}) {invertUncertainty ? '↑' : '↓'}
          </div>
        </div>
      </div>

      {/* X-axis label */}
      <div style={{ color: 'rgba(255,255,255,0.6)', fontSize: '10px', textAlign: 'center', marginTop: '4px' }}>
        {xLabel} ({unit}) →
      </div>
      <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: '10px', textAlign: 'center', marginTop: '6px' }}>
        Right = more · down = less certain.
      </div>
    </div>
  );
}
