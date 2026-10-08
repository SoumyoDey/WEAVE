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

/** Any `useState(...)` a file declares for a verification setting. */
const localSettingsIn = (source) => {
  const out = [];
  const re = /const \[(\w*(?:[Hh]our(?:Min|Max)|[Tt]hreshold|[Ff]ssWindow|[Bb]oxCells))[,\]][^=]*=\s*useState\(/g;
  let m;
  while ((m = re.exec(source))) out.push(m[1]);
  return out;
};

describe('the scored surfaces share one set of settings', () => {
  /**
   * **This describe block asserted the opposite until §62, and was right to.**
   * While each tab held its own copies, the most that could be asked was that
   * they all *started* from `VERIFICATION_DEFAULTS` — which is what §54 fixed,
   * after the two tabs were found 18% apart on CSI from drifted defaults
   * alone.
   *
   * §62 moved the settings above the tabs into `VerificationProvider`, so the
   * question is no longer "do the copies agree at the start" but "is there
   * more than one copy". A tab declaring any of these as local state has
   * stepped back out of the shared one, which is the regression worth
   * catching — the numbers would look perfectly reasonable and simply answer a
   * different question from the tab beside them.
   */
  it.each(Object.keys(SOURCES))('%s declares none of its own', (file) => {
    expect(localSettingsIn(SOURCES[file])).toEqual([]);
  });

  it('reads all four from the context', () => {
    // The replacement for the old "takes every one from the shared constant":
    // both tabs now get them from one provider rather than four initialisers.
    for (const source of Object.values(SOURCES)) {
      expect(source).toContain('useVerification()');
    }
  });

  it('seeds the context from the shared constant', () => {
    const context = fs.readFileSync(
      path.join(__dirname, 'state', 'VerificationContext.jsx'), 'utf8');
    for (const key of ['HOUR_MIN', 'HOUR_MAX', 'FSS_WINDOW', 'BOX_CELLS']) {
      expect(context).toContain(`VD.${key}`);
    }
    // The threshold is the exception and cannot come from the constant: it is
    // variable-specific (mm/6h against m/s).
    expect(context).toContain('defaultThresholdFor');
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
