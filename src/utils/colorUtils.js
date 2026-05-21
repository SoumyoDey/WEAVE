import { COLORMAPS } from '../constants';

/**
 * Returns a CSS linear-gradient that matches the visual appearance of the
 * colormap on a light basemap (pre-composited against white, same as the
 * IDW canvas renderer's getDynamicColor formula).
 */
export const getLegendGradient = (colormapName) => {
  const colors = COLORMAPS[colormapName].colors;
  const stops = colors.map((hex, i) => {
    const normalized = i / (colors.length - 1);
    const opacity = 0.5 + normalized * 0.3;
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    // Pre-composite against white — same result as rendering on the CartoDB light basemap
    const cr = Math.round(r * opacity + 255 * (1 - opacity));
    const cg = Math.round(g * opacity + 255 * (1 - opacity));
    const cb = Math.round(b * opacity + 255 * (1 - opacity));
    return `rgb(${cr},${cg},${cb})`;
  });
  return `linear-gradient(to right, ${stops.join(', ')})`;
};

/**
 * Returns an rgba CSS color string for a given data value.
 * range: { min, max }
 * colormapName: key of COLORMAPS
 */
export const getDynamicColor = (value, range, colormapName) => {
  const colors = COLORMAPS[colormapName].colors;
  const normalized = Math.min(value / range.max, 1);
  if (normalized < 0.01) return 'rgba(255,255,255,0)';
  const seg = colors.length - 1;
  const ss  = 1 / seg;
  const si  = Math.min(Math.floor(normalized / ss), seg - 1);
  const t   = (normalized - si * ss) / ss;
  const c1  = colors[si], c2 = colors[si + 1];
  const r   = Math.round(parseInt(c1.slice(1,3),16) + (parseInt(c2.slice(1,3),16) - parseInt(c1.slice(1,3),16)) * t);
  const g   = Math.round(parseInt(c1.slice(3,5),16) + (parseInt(c2.slice(3,5),16) - parseInt(c1.slice(3,5),16)) * t);
  const b   = Math.round(parseInt(c1.slice(5,7),16) + (parseInt(c2.slice(5,7),16) - parseInt(c1.slice(5,7),16)) * t);
  return `rgba(${r},${g},${b},${0.5 + normalized * 0.3})`;
};
