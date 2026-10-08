/**
 * No component writes its own hemisphere letter.
 *
 * A signed number and a hemisphere letter say the same thing twice, and when
 * they disagree the letter wins in the reader's head: `-81.19°E` reads as
 * eastern longitude and is 81.19 degrees WEST. `utils/geoUtils.js` exists to
 * be the one implementation that gets this right, and it says so.
 *
 * It was adopted by `MetricPanel`, `AnalysisTab` and the panels extracted from
 * Analysis — and not by the Comparison side, which kept printing
 * `{lon.toFixed(1)}°E` in four places. Found by reading the running app on
 * 2026-10-08: the Comparison tab's own location chip said **39.99°N,
 * -81.19°E** for a point the Analysis tab, one click away, labelled
 * **39.99°N, 81.19°W**. Every loaded region in this archive is west of
 * Greenwich, so the Comparison label was wrong every time it was shown.
 *
 * **This asserts on the source rather than the DOM** for the reason
 * `verificationDefaults.test.js` does: most of these strings appear only after
 * a point is clicked or a region is drawn and a Run button is pressed, so a
 * rendering test would cover a few of them and miss the rest. A scan covers
 * every component, including ones not written yet — which is the point, since
 * this is the second time the same mistake has been made in a new file.
 */
import fs from 'fs';
import path from 'path';

import { fmtLat, fmtLon } from './utils/geoUtils';

const SRC = path.join(__dirname);

/** Every component source, recursively; tests and the helper itself excluded. */
const componentFiles = (dir = SRC) =>
  fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) return componentFiles(full);
    if (!/\.jsx?$/.test(e.name) || e.name.includes('.test.')) return [];
    if (full === path.join(SRC, 'utils', 'geoUtils.js')) return [];
    return [full];
  });

/**
 * A hemisphere letter attached to a formatted number — `}°E`, `}°N` and so on.
 *
 * Deliberately narrow: it matches the letter only where it directly follows an
 * interpolated value, which is the shape that can disagree with its sign. Prose
 * that merely mentions a hemisphere, and axis labels like `°C`, are left alone.
 */
const HARDCODED_HEMISPHERE = /\}\s*°\s*[NSEW]\b/g;

describe('coordinate labels', () => {
  it.each(componentFiles().map((f) => [path.relative(SRC, f), f]))(
    '%s does not hard-code a hemisphere letter',
    (_rel, file) => {
      const found = fs.readFileSync(file, 'utf8').match(HARDCODED_HEMISPHERE) ?? [];
      expect(found).toEqual([]);
    },
  );

  // The scan above is only worth having if the helper it points people to is
  // itself right about the sign, which is the thing that was actually wrong.
  it('fmtLon calls a negative longitude West', () => {
    expect(fmtLon(-81.189, 2)).toBe('81.19°W');
    expect(fmtLon(12.5, 1)).toBe('12.5°E');
  });

  it('fmtLat calls a negative latitude South', () => {
    expect(fmtLat(-33.9, 1)).toBe('33.9°S');
    expect(fmtLat(39.994, 2)).toBe('39.99°N');
  });

  it('both render a non-numeric coordinate as a dash rather than NaN', () => {
    expect(fmtLon(undefined)).toBe('—');
    expect(fmtLat(null)).toBe('—');
  });
});
