/**
 * The two scored tabs start at the same settings.
 *
 * §41 made Analysis and Comparison use the same *estimator* for the same
 * question. It did not make them start at the same *settings*, and four
 * independently written defaults had drifted: the Analysis categorical panel
 * scored 0-240 h where everything else scored 0-168, and Comparison's region
 * mode used a 3-cell FSS neighbourhood where the other three used 5.
 *
 * The cost was two tabs answering one question differently. Same region, same
 * model, same threshold, each tab at its own defaults, AIFS at 2 mm/6h:
 *
 *     Analysis    CSI 0.3082   POD 0.7313   FSS 0.6492
 *     Comparison  CSI 0.3630   POD 0.8167   FSS 0.6582
 *
 * 18% apart on CSI with the estimator identical — forced to the same settings
 * they agreed exactly, so the whole difference was the defaults. UKMO's CSI
 * matched either way (nothing exceeds the threshold past 168 h at that point)
 * while its FSS still differed by 6%, which is the kind of partial agreement
 * that makes this hard to notice by eye.
 *
 * **This file reads the source, not the DOM**, because the defaults are what
 * matter and most of them only reach the screen after a point is clicked, a
 * region is drawn and a Run button is pressed. A rendering test would cover
 * fewer of them and would break for unrelated reasons.
 */
import fs from 'fs';
import path from 'path';

import { VERIFICATION_DEFAULTS } from './constants';

const read = (file) =>
  fs.readFileSync(path.join(__dirname, 'components', file), 'utf8');

const SOURCES = { AnalysisTab: read('AnalysisTab.jsx'), ComparisonTab: read('ComparisonTab.jsx') };

/** Every `useState(...)` for a verification setting, with its initialiser. */
const settingsIn = (source) => {
  const out = {};
  const re = /const \[(\w*(?:[Hh]our(?:Min|Max)|[Ff]ssWindow|[Bb]oxCells))[,\]][^=]*=\s*useState\(([^)]*)\)/g;
  let m;
  while ((m = re.exec(source))) out[m[1]] = m[2].trim();
  return out;
};

describe('the scored surfaces start at the same settings', () => {
  it.each(Object.keys(SOURCES))('%s has verification settings to check', (file) => {
    // Guard against the regex silently matching nothing, which would make
    // every test below vacuously true.
    expect(Object.keys(settingsIn(SOURCES[file])).length).toBeGreaterThanOrEqual(4);
  });

  it.each(Object.keys(SOURCES))('%s takes every one from the shared constant', (file) => {
    const literals = Object.entries(settingsIn(SOURCES[file]))
      .filter(([, init]) => !init.startsWith('VD.'));
    expect(literals).toEqual([]);
  });

  it('is one range, one neighbourhood and one box for the whole app', () => {
    // The values themselves, so a change to them is a deliberate edit here and
    // not a side effect of editing one tab.
    expect(VERIFICATION_DEFAULTS).toEqual({
      HOUR_MIN: 0, HOUR_MAX: 168, FSS_WINDOW: 5, BOX_CELLS: 9,
    });
  });

  it('no longer scores one surface over ten days and the rest over seven', () => {
    const all = Object.values(SOURCES).join('\n');
    expect(all).not.toMatch(/useState\(240\)/);
    expect(all).not.toMatch(/setCatHourMax\]\s*=\s*useState\(\d/);
  });
});

describe('the same control is called the same thing on both tabs', () => {
  // Phase 6 of CONSISTENCY_AUDIT.md is this class of defect: a reader who
  // learns a control on one tab should recognise it on the other.
  it.each([
    ['the FSS neighbourhood', 'FSS neighbourhood', 'FSS window'],
    ['the lead-time range', 'Lead times', '>Hours<'],
  ])('%s', (_name, agreed, abandoned) => {
    expect(SOURCES.AnalysisTab).toContain(agreed);
    expect(SOURCES.AnalysisTab).not.toContain(abandoned);
    expect(SOURCES.ComparisonTab).toContain(agreed);
  });

  it('no longer needs the qualifier that used to be doing work', () => {
    /**
     * This test used to assert the opposite, and was right to: while Analysis
     * carried two thresholds — one for the spatial maps, one the verification
     * panel applied over the same region — "Threshold (maps)" and its tooltip
     * were the only thing telling them apart, and renaming it to match
     * Comparison would have made the tab less clear.
     *
     * §55 merged the two into one piece of state, which removed the thing the
     * qualifier was qualifying. Both boxes now edit the same threshold and both
     * read "Threshold", as Comparison's do. `AnalysisTab.threshold.test.js`
     * holds the behaviour; this pins that the label did not survive the merge.
     */
    expect(SOURCES.AnalysisTab).not.toContain('Threshold (maps)');
    expect(SOURCES.AnalysisTab).not.toContain('uses its own threshold setting');
    expect(SOURCES.AnalysisTab).not.toContain('regionThreshold');
  });
});
