import React, { useState, useEffect, useRef } from 'react';
import { Play, Pause, SkipBack, SkipForward } from 'lucide-react';
import { IconButton } from './ui/IconButton';
import { t } from '../theme';

/**
 * Bottom timeline scrubber with transport controls.
 *
 * Props:
 *   currentModel     {object}  — { name, color, hours, ... }
 *   selectedHour     {number}
 *   setSelectedHour  {fn}
 *   selectedVariable {string}
 *   obsCoverage      {object|null} — /api/observation-coverage, or null while
 *                                    loading / if it failed
 *   isNarrow         {boolean} — compact, stacked layout for narrow viewports
 */
export function Timeline({ currentModel, selectedHour, setSelectedHour, obsCoverage, isNarrow }) {
  const hours      = currentModel.hours;
  const currentIdx = hours.indexOf(selectedHour);
  const maxIdx     = hours.length - 1;
  const pct        = maxIdx > 0 ? (currentIdx / maxIdx) * 100 : 0;
  const maxHour    = hours[maxIdx] || 360;

  // Verification stops where the observation record does. Past that point every
  // scored panel is correctly empty, which used to be indistinguishable from a
  // bug — so the boundary is drawn on the axis the lead time is chosen on.
  const verifiedTo   = obsCoverage?.last_verifiable_hour ?? null;
  const verifiedPct  = verifiedTo != null && maxHour > 0
    ? Math.min(100, (verifiedTo / maxHour) * 100) : null;
  const pastVerified = verifiedTo != null && selectedHour > verifiedTo;

  // The initialisation time comes from the run, not a hard-coded date — the
  // latter silently lied the moment a different run was loaded.
  const baseDate  = obsCoverage?.init_time
    ? new Date(`${obsCoverage.init_time}Z`)
    : new Date('2025-09-08T00:00:00Z');
  const validDate = new Date(baseDate.getTime() + selectedHour * 3600000);
  const validStr  = validDate.toLocaleString('en-US', {
    weekday: 'short', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', timeZone: 'UTC', hour12: false,
  }) + ' UTC';

  const dayTicks = Array.from({ length: Math.floor(maxHour / 24) + 1 }, (_, d) => d * 24)
    .filter(h => h <= maxHour);

  const [playing, setPlaying] = useState(false);

  // Step by index, clamped; used by buttons and keyboard.
  const step = (dir) => {
    const idx = hours.indexOf(selectedHour);
    const n = Math.min(Math.max(idx + dir, 0), maxIdx);
    setSelectedHour(hours[n]);
  };

  // Latest values for the play interval (avoids stale closures).
  const ref = useRef({ hours, selectedHour });
  ref.current = { hours, selectedHour };
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      const { hours: hrs, selectedHour: h } = ref.current;
      const idx = hrs.indexOf(h);
      setSelectedHour(idx >= hrs.length - 1 ? hrs[0] : hrs[idx + 1]);
    }, 700);
    return () => clearInterval(id);
  }, [playing, setSelectedHour]);

  // ← / → step through lead times (ignored while typing in a field).
  useEffect(() => {
    const onKey = (e) => {
      const tag = e.target?.tagName;
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
      if (e.key === 'ArrowLeft')  { e.preventDefault(); step(-1); }
      if (e.key === 'ArrowRight') { e.preventDefault(); step(1); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }); // re-bind each render so step() sees current values

  return (
    <div style={{
      position: 'absolute', bottom: 0, left: 0, right: 0,
      background: 'rgba(10,18,28,0.97)', backdropFilter: 'blur(12px)',
      borderTop: '1px solid rgba(255,255,255,0.07)', zIndex: 900,
      boxShadow: '0 -4px 24px rgba(0,0,0,0.4)', padding: isNarrow ? '8px 12px 0' : '10px 20px 0',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: isNarrow ? '10px' : '14px', flexWrap: isNarrow ? 'wrap' : 'nowrap' }}>

        {/* Transport controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <IconButton onClick={() => step(-1)} title="Previous lead time (←)" label="Previous lead time" size={30} style={{ boxShadow: 'none' }}>
            <SkipBack size={15} />
          </IconButton>
          <IconButton onClick={() => setPlaying(p => !p)} label={playing ? 'Pause' : 'Play'} active size={34}
            style={{ borderRadius: t.radiusRound, boxShadow: 'none' }}>
            {playing ? <Pause size={16} /> : <Play size={16} />}
          </IconButton>
          <IconButton onClick={() => step(1)} title="Next lead time (→)" label="Next lead time" size={30} style={{ boxShadow: 'none' }}>
            <SkipForward size={15} />
          </IconButton>
        </div>

        {/* Scrubber + day ticks */}
        <div style={{ flex: isNarrow ? '1 1 100%' : 1, order: isNarrow ? 3 : 0, position: 'relative', paddingBottom: '22px' }}>
          <input
            type="range" min="0" max={maxIdx} value={currentIdx < 0 ? 0 : currentIdx}
            onChange={e => setSelectedHour(hours[parseInt(e.target.value)])}
            aria-label="Forecast lead time"
            style={{
              width: '100%', height: '4px', borderRadius: '2px', outline: 'none', cursor: 'pointer',
              appearance: 'none', WebkitAppearance: 'none', display: 'block',
              background: `linear-gradient(to right, ${t.accent} 0%, ${t.accent} ${pct}%, ${t.borderStrong} ${pct}%, ${t.borderStrong} 100%)`,
            }}
          />
          {/* Where verification runs out. The track past this point is dimmed and
              hatched, so "no score here" reads as a property of the data rather
              than a failure of the app. */}
          {verifiedPct != null && verifiedPct < 100 && (
            <div style={{
              position: 'absolute', top: 0, left: `${verifiedPct}%`, right: 0,
              height: '4px', borderRadius: '0 2px 2px 0', pointerEvents: 'none',
              background: 'repeating-linear-gradient(45deg, rgba(243,156,18,0.30) 0 3px, rgba(243,156,18,0.08) 3px 6px)',
            }} title={`No observations beyond +${verifiedTo}h — nothing to verify against`} />
          )}
          <div style={{ position: 'absolute', top: '10px', left: 0, right: 0, pointerEvents: 'none' }}>
            {verifiedPct != null && verifiedPct < 100 && (
              <div style={{ position: 'absolute', left: `${verifiedPct}%`, top: '-11px', display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
                <div style={{ width: '1px', height: '17px', background: 'rgba(243,156,18,0.75)' }} />
                {!isNarrow && (
                  <span style={{ fontSize: '9px', color: 'rgba(243,156,18,0.8)', whiteSpace: 'nowrap', paddingLeft: '3px', marginTop: '-2px' }}>
                    verified to +{verifiedTo}h
                  </span>
                )}
              </div>
            )}
            {dayTicks.map(h => {
              const pos    = maxHour > 0 ? (h / maxHour) * 100 : 0;
              const dayNum = h / 24;
              // Narrow viewports can't fit a label every 2 days without overlap — thin them out.
              const labelEvery = isNarrow ? 4 : 2;
              const showLabel = dayNum % labelEvery === 0;
              return (
                <div key={h} style={{ position: 'absolute', left: `${pos}%`, transform: 'translateX(-50%)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px' }}>
                  <div style={{ width: '1px', height: showLabel ? '6px' : '4px', background: showLabel ? 'rgba(255,255,255,0.35)' : 'rgba(255,255,255,0.18)' }} />
                  {showLabel && (
                    <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.3)', whiteSpace: 'nowrap' }}>
                      {h === 0 ? 'Now' : `+${dayNum}d`}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Valid time */}
        <div style={{
          textAlign: isNarrow ? 'left' : 'right', whiteSpace: 'nowrap', flexShrink: 0,
          minWidth: isNarrow ? 'auto' : '150px', order: isNarrow ? 2 : 0,
          marginLeft: isNarrow ? 'auto' : 0,
        }}>
          <div>
            <span style={{ fontSize: isNarrow ? '14px' : '17px', fontWeight: '800', color: 'white', letterSpacing: '-0.5px' }}>+{selectedHour}h</span>
            <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.38)', marginLeft: '5px' }}>({(selectedHour / 24).toFixed(1)}d)</span>
          </div>
          {!isNarrow && (
            <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)' }}>
              <span style={{ color: 'rgba(255,255,255,0.28)', fontSize: '9px', letterSpacing: '0.05em' }}>Valid </span>{validStr}
            </div>
          )}
          {/* Say it at the lead time the user has actually chosen, not only on the
              axis — this is the readout they are looking at when a panel is empty. */}
          {pastVerified && (
            <div style={{ fontSize: '10px', color: '#f39c12', marginTop: '1px' }}
                 title={`Observations for ${obsCoverage.variable} end ${obsCoverage.record_end_lead_hours}h after initialisation`}>
              beyond verification (+{verifiedTo}h)
            </div>
          )}
        </div>
      </div>

      {/* Copyright footer */}
      {!isNarrow && (
        <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', marginLeft: '-20px', marginRight: '-20px', padding: '3px 20px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', marginTop: '6px' }}>
          <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.2)', letterSpacing: '0.03em' }}>© {new Date().getFullYear()} Northeastern University</span>
          <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.1)' }}>·</span>
          <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.15)', letterSpacing: '0.05em', fontWeight: 600 }}>WEAVE</span>
        </div>
      )}
    </div>
  );
}
