import React from 'react';
import { buildVsupLevels } from '../../constants';

export function VSUPFanLegend({ bivariateRanges, selectedColormap, colormaps, selectedVariable, invertUncertainty = false, numBuckets = 0, flipColormap = false }) {
  if (!bivariateRanges) return null;

  const { meanMax, stdMax } = bivariateRanges;
  const fanLeft = 120, fanRight = 60;
  const totalSpan = fanLeft - fanRight; // 120
  const cx = 150, cy = 220;
  const rInner = 22, rOuter = 140;
  // Fan geometry is derived from the SAME helper the map uses, so legend and
  // overlay always agree. segCounts low→high uncertainty ([W…1]); reverse for
  // rings drawn inner (ri=0, high uncertainty, narrowest) → outer (low, widest).
  const vsupLevels = buildVsupLevels(numBuckets);
  const ROWS = vsupLevels.rings;
  const segCounts = [...vsupLevels.segCounts].reverse();
  const dR = (rOuter - rInner) / ROWS;
  const toRad = d => d * Math.PI / 180;
  const px = (r, d) => cx + r * Math.cos(toRad(d));
  const py = (r, d) => cy - r * Math.sin(toRad(d));
  const arcPath = (r1, r2, a1d, a2d) =>
    `M${px(r1,a1d).toFixed(2)} ${py(r1,a1d).toFixed(2)} ` +
    `A${r1} ${r1} 0 0 1 ${px(r1,a2d).toFixed(2)} ${py(r1,a2d).toFixed(2)} ` +
    `L${px(r2,a2d).toFixed(2)} ${py(r2,a2d).toFixed(2)} ` +
    `A${r2} ${r2} 0 0 0 ${px(r2,a1d).toFixed(2)} ${py(r2,a1d).toFixed(2)}Z`;

  const cmapColor = (tRaw) => {
    const t = flipColormap ? 1 - tRaw : tRaw;   // reverse hue when colormap is flipped
    const cols = colormaps[selectedColormap].colors;
    const seg = cols.length - 1;
    const si  = Math.min(Math.floor(t * seg), seg - 1);
    const st  = t * seg - si;
    const c1 = cols[si], c2 = cols[si + 1];
    const ri = parseInt(c1.slice(1,3),16), gi = parseInt(c1.slice(3,5),16), bi = parseInt(c1.slice(5,7),16);
    const ro = parseInt(c2.slice(1,3),16), go = parseInt(c2.slice(3,5),16), bo = parseInt(c2.slice(5,7),16);
    return [Math.round(ri+(ro-ri)*st), Math.round(gi+(go-gi)*st), Math.round(bi+(bo-bi)*st)];
  };

  const neutral = [180, 175, 185];
  const vsupRows = segCounts.map((segs, ri) => {
    // Colours never change with inversion — only the σ axis tick labels flip
    const uncertFrac = 1 - ri / Math.max(1, ROWS - 1);   // inner ring (ri=0) = most suppressed
    const suppress   = uncertFrac * 0.72;
    const colors = Array.from({ length: segs }, (_, ci) => {
      const t = segs === 1 ? 0.5 : ci / (segs - 1);
      const [r, g, b] = cmapColor(Math.min(t, 0.999));
      const fr = Math.round(r * (1-suppress) + neutral[0] * suppress);
      const fg = Math.round(g * (1-suppress) + neutral[1] * suppress);
      const fb = Math.round(b * (1-suppress) + neutral[2] * suppress);
      return `rgb(${fr},${fg},${fb})`;
    });
    return { segs, colors };
  });

  const title = selectedVariable === 'wind' ? 'WIND_SPEED' : 'PRECIPITATION';
  const varLabel = selectedVariable === 'wind' ? 'Wind Speed' : 'Precipitation';
  const unit     = selectedVariable === 'wind' ? 'm/s' : 'mm/hr';

  // 6 intervals → 7 ticks, 6 labels (skip last which lands on std dev axis)
  const VAL_SEGS = 6;
  const dAngle = totalSpan / VAL_SEGS;
  const valTicks = Array.from({ length: VAL_SEGS + 1 }, (_, i) => {
    const deg = fanLeft - i * dAngle;
    const lx  = px(rOuter + 20, deg);
    const ly  = py(rOuter + 20, deg);
    return {
      deg,
      tx: px(rOuter, deg), ty: py(rOuter, deg),
      lx, ly,
      anchor: deg > 100 ? 'end' : deg < 80 ? 'start' : 'middle',
      val: (meanMax * i / VAL_SEGS).toFixed(2),
      showLabel: i < VAL_SEGS,
    };
  });

  // All 5 ring boundaries labeled — 45° spine gives ~21px y-spacing, enough for 11px font
  // When inverted: tick labels flip direction (outer ring relabeled as stdMax, inner as 0)
  // so the legend stays visually identical but the σ scale is read in reverse
  const stdTickData = Array.from({ length: ROWS + 1 }, (_, j) => {
    const r = rOuter - j * dR;
    const tickVal = invertUncertainty
      ? (stdMax * (ROWS - j) / ROWS)   // outer (j=0) → stdMax, inner (j=ROWS) → 0
      : (stdMax * j / ROWS);            // outer (j=0) → 0,      inner (j=ROWS) → stdMax
    return {
      bx: px(r, fanRight), by: py(r, fanRight),
      lx: px(r + 20, fanRight), ly: py(r + 20, fanRight),
      val: tickVal.toFixed(2),
      showLabel: true,
    };
  });

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
        🌀 VSUP Fan — {title}
      </div>

      <svg width="330" height="255" style={{ overflow: 'visible' }}>
        {/* Fan arcs */}
        {vsupRows.map(({ segs, colors }, ri) => {
          const segSpan = totalSpan / segs;
          const r1 = rInner + ri * dR;
          const r2 = rInner + (ri + 1) * dR;
          return colors.map((color, ci) => {
            const a1 = fanLeft - ci * segSpan;
            const a2 = fanLeft - (ci + 1) * segSpan;
            return (
              <path
                key={`${ri}-${ci}`}
                d={arcPath(r1, r2, a1, a2)}
                fill={color}
                stroke="white"
                strokeWidth="1.5"
              />
            );
          });
        })}

        {/* Value ticks */}
        {valTicks.map((t, i) => (
          <g key={i}>
            <line
              x1={t.tx.toFixed(1)} y1={t.ty.toFixed(1)}
              x2={px(rOuter + 6, t.deg).toFixed(1)} y2={py(rOuter + 6, t.deg).toFixed(1)}
              stroke="rgba(255,255,255,0.4)" strokeWidth="1"
            />
            {t.showLabel && (
              <text
                x={t.lx.toFixed(1)} y={t.ly.toFixed(1)}
                fontSize="11" fill="rgba(255,255,255,0.92)"
                textAnchor={t.anchor} dominantBaseline="middle"
              >
                {t.val}
              </text>
            )}
          </g>
        ))}

        {/* Value axis title */}
        <text
          x={cx} y={cy + 26}
          fontSize="11" fill="rgba(255,255,255,0.78)"
          textAnchor="middle" fontWeight="600"
        >
          ← {varLabel} ({unit}) →
        </text>

        {/* Uncertainty ticks */}
        {stdTickData.map((t, j) => (
          <g key={j}>
            <line
              x1={t.bx.toFixed(1)} y1={t.by.toFixed(1)}
              x2={t.lx.toFixed(1)} y2={t.ly.toFixed(1)}
              stroke="rgba(255,255,255,0.4)" strokeWidth="1"
            />
            {t.showLabel && (
              <text
                x={(t.lx + 4).toFixed(1)} y={t.ly.toFixed(1)}
                fontSize="11" fill="rgba(255,255,255,0.92)"
                textAnchor="start" dominantBaseline="middle"
              >
                {t.val}
              </text>
            )}
          </g>
        ))}

        {/* Std dev axis label — vertically centered on right side */}
        <text
          x={(stdTickData[0].lx + 4).toFixed(1)}
          y={((stdTickData[0].ly + stdTickData[ROWS].ly) / 2).toFixed(1)}
          fontSize="10" fill="rgba(255,255,255,0.7)" fontWeight="600"
          textAnchor="start" dominantBaseline="middle"
        >
          Std. Dev. (σ)
        </text>

      </svg>
    </div>
  );
}
