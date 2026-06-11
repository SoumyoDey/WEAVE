import React from 'react';

/**
 * Bottom timeline scrubber.
 *
 * Props:
 *   currentModel   {object}  — { name, color, hours, ... }
 *   selectedHour   {number}
 *   setSelectedHour {fn}
 *   selectedVariable {string}
 */
export function Timeline({ currentModel, selectedHour, setSelectedHour, selectedVariable }) {
  const currentIdx = currentModel.hours.indexOf(selectedHour);
  const maxIdx     = currentModel.hours.length - 1;
  const pct        = maxIdx > 0 ? (currentIdx / maxIdx) * 100 : 0;
  const maxHour    = currentModel.hours[maxIdx] || 360;

  const baseDate  = new Date('2025-09-08T00:00:00Z');
  const validDate = new Date(baseDate.getTime() + selectedHour * 3600000);
  const validStr  = validDate.toLocaleString('en-US', {
    weekday: 'short', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', timeZone: 'UTC', hour12: false,
  }) + ' UTC';

  const dayTicks = Array.from({ length: Math.floor(maxHour / 24) + 1 }, (_, d) => d * 24)
    .filter(h => h <= maxHour);

  return (
    <div style={{
      position: 'absolute', bottom: 0, left: 0, right: 0,
      background: 'rgba(10,18,28,0.97)',
      backdropFilter: 'blur(12px)',
      borderTop: '1px solid rgba(255,255,255,0.07)',
      zIndex: 900,
      boxShadow: '0 -4px 24px rgba(0,0,0,0.4)',
      padding: '6px 20px 0',
    }}>
      {/* Info row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '5px' }}>
        <span style={{ fontSize: '10px', fontWeight: '700', color: currentModel.color, background: `${currentModel.color}22`, border: `1px solid ${currentModel.color}55`, padding: '1px 7px', borderRadius: '8px', whiteSpace: 'nowrap' }}>
          {currentModel.name}
        </span>
        <span style={{ fontSize: '10px', fontWeight: '600', color: 'rgba(255,255,255,0.4)', background: 'rgba(255,255,255,0.06)', padding: '1px 7px', borderRadius: '8px', whiteSpace: 'nowrap' }}>
          {selectedVariable === 'precipitation' ? '💧 Precip' : '🌬️ Wind'}
        </span>
        <div style={{ flex: 1, textAlign: 'center' }}>
          <span style={{ fontSize: '17px', fontWeight: '800', color: 'white', letterSpacing: '-0.5px' }}>+{selectedHour}h</span>
          <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.38)', marginLeft: '5px' }}>({(selectedHour / 24).toFixed(1)}d)</span>
          <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)', marginLeft: '10px' }}>
            <span style={{ color: 'rgba(255,255,255,0.28)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Valid </span>
            {validStr}
          </span>
        </div>
      </div>

      {/* Slider + day ticks */}
      <div style={{ position: 'relative', paddingBottom: '28px' }}>
        <input
          type="range"
          min="0"
          max={maxIdx}
          value={currentIdx}
          onChange={e => setSelectedHour(currentModel.hours[parseInt(e.target.value)])}
          style={{
            width: '100%', height: '4px', borderRadius: '2px',
            outline: 'none', cursor: 'pointer',
            appearance: 'none', WebkitAppearance: 'none',
            background: `linear-gradient(to right, #3498db 0%, #3498db ${pct}%, rgba(255,255,255,0.15) ${pct}%, rgba(255,255,255,0.15) 100%)`,
            display: 'block',
          }}
        />
        <div style={{ position: 'absolute', top: '10px', left: 0, right: 0, pointerEvents: 'none' }}>
          {dayTicks.map(h => {
            const pos    = maxHour > 0 ? (h / maxHour) * 100 : 0;
            const dayNum = h / 24;
            return (
              <div key={h} style={{ position: 'absolute', left: `${pos}%`, transform: 'translateX(-50%)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px' }}>
                <div style={{ width: '1px', height: dayNum % 2 === 0 ? '6px' : '4px', background: dayNum % 2 === 0 ? 'rgba(255,255,255,0.35)' : 'rgba(255,255,255,0.18)' }} />
                {dayNum % 2 === 0 && (
                  <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.3)', whiteSpace: 'nowrap', fontWeight: h === selectedHour ? '700' : '400' }}>
                    {h === 0 ? 'Now' : `+${dayNum}d`}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Copyright footer */}
      <div style={{
        borderTop: '1px solid rgba(255,255,255,0.06)',
        marginLeft: '-20px', marginRight: '-20px',
        padding: '3px 20px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '6px',
      }}>
        <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.2)', letterSpacing: '0.03em' }}>
          © {new Date().getFullYear()} Northeastern University
        </span>
        <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.1)' }}>·</span>
        <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.15)', letterSpacing: '0.05em', fontWeight: 600 }}>
          WEAVE
        </span>
      </div>
    </div>
  );
}
