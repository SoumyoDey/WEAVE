import { COLORMAPS } from '../constants';

/**
 * Returns a CSS linear-gradient that matches the visual appearance of the
 * colormap on a light basemap (pre-composited against white, same as the
 * IDW canvas renderer's getDynamicColor formula).
 */
export const getLegendGradient = (colormapName, flip = false) => {
  const base = COLORMAPS[colormapName].colors;
  const colors = flip ? [...base].reverse() : base;
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

// Pre-parsed colormap cache: { colormapName -> [{r,g,b}, ...] }
const _parsedColormaps = {};
function _getParsedColors(colormapName) {
  if (!_parsedColormaps[colormapName]) {
    _parsedColormaps[colormapName] = COLORMAPS[colormapName].colors.map(hex => ({
      r: parseInt(hex.slice(1, 3), 16),
      g: parseInt(hex.slice(3, 5), 16),
      b: parseInt(hex.slice(5, 7), 16),
    }));
  }
  return _parsedColormaps[colormapName];
}

/**
 * Like getDynamicColor but returns { r, g, b, a } integers directly —
 * avoids the rgba string → regex round-trip in canvas rendering.
 * a is 0-255.
 */
export const getDynamicColorRGB = (value, range, colormapName, flip = false) => {
  const normalized = Math.min(value / range.max, 1);
  if (normalized < 0.01) return { r: 255, g: 255, b: 255, a: 0 };
  const parsed = _getParsedColors(colormapName);
  const seg = parsed.length - 1;
  // Colour (hue) position may be reversed by flip; opacity still tracks the true value.
  const cpos = flip ? 1 - normalized : normalized;
  const si  = Math.min(Math.floor(cpos * seg), seg - 1);
  const t   = cpos * seg - si;
  const c1  = parsed[si], c2 = parsed[si + 1];
  return {
    r: Math.round(c1.r + (c2.r - c1.r) * t),
    g: Math.round(c1.g + (c2.g - c1.g) * t),
    b: Math.round(c1.b + (c2.b - c1.b) * t),
    a: Math.round((0.5 + normalized * 0.3) * 255),
  };
};
