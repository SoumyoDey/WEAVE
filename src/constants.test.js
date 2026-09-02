/**
 * Tests for the metric registry's user-visible text.
 *
 * METRIC_CONFIG's descriptions and legend bands are rendered for BOTH variables
 * by MetricPanel, so a literal 'mm/h' in one of them labels a wind map in a
 * precipitation unit. That is the same defect /api/compare/skill had when it
 * hard-coded `units: 'mm/h'`, and it is what CONSISTENCY_AUDIT_PLAN.md phase 6
 * exists to catch. These tests fail if a literal unit comes back.
 */
import {
  METRIC_CONFIG, VALUE_UNITS, withUnit, metricColorFn, metricLegend,
} from './constants';

// Metrics whose value carries the variable's unit. The rest — the ratios and
// the scores in [0,1] — are dimensionless and must name no unit at all.
const UNITFUL = ['bias', 'mae', 'rmse', 'crps'];

const textOf = (cfg) => [
  cfg.description,
  ...(cfg.legend ?? []).map(l => l.label),
  ...(cfg.windLegend ?? []).map(l => l.label),
  ...Object.values(cfg.legendGradient ?? {}).flat().filter(v => typeof v === 'string'),
].join(' | ');

const cfgFor = (key) => METRIC_CONFIG.find(m => m.key === key);

describe('withUnit', () => {
  it('substitutes every occurrence for the variable', () => {
    expect(withUnit('< 0.2 {unit} and > 1.0 {unit}', 'wind'))
      .toBe('< 0.2 m/s and > 1.0 m/s');
    expect(withUnit('bias ({unit})', 'precipitation')).toBe('bias (mm/h)');
  });

  it('leaves text with no placeholder alone', () => {
    expect(withUnit('CSI, higher = better', 'wind')).toBe('CSI, higher = better');
  });

  it('drops the placeholder rather than printing braces for an unknown variable', () => {
    expect(withUnit('bias ({unit})', 'temperature_2m')).toBe('bias ()');
  });

  it('passes non-strings through', () => {
    expect(withUnit(undefined, 'wind')).toBeUndefined();
  });
});

describe('METRIC_CONFIG text', () => {
  it.each(METRIC_CONFIG.map(c => [c.key, c]))(
    '%s writes no literal unit', (key, cfg) => {
      const text = textOf(cfg);
      Object.values(VALUE_UNITS).forEach(unit => {
        expect(text).not.toContain(unit);
      });
    });

  it.each(UNITFUL)('%s says which unit its value is in', (key) => {
    const cfg = METRIC_CONFIG.find(m => m.key === key);
    expect(cfg.description).toContain('{unit}');
    Object.keys(VALUE_UNITS).forEach(variable => {
      expect(withUnit(cfg.description, variable)).toContain(VALUE_UNITS[variable]);
    });
  });

  it.each(METRIC_CONFIG.filter(c => !UNITFUL.includes(c.key)).map(c => [c.key, c]))(
    '%s is dimensionless and claims no unit', (key, cfg) => {
      expect(textOf(cfg)).not.toContain('{unit}');
    });

  it('describes SSR as spread over error, not as a variance ratio', () => {
    // The code was corrected to sigma/RMSE (METRICS_AUDIT.md finding 7) and these
    // strings kept describing the old convention, which mis-states the wings the
    // legend bands are named for.
    const ssr    = METRIC_CONFIG.find(m => m.key === 'ssr');
    const ssrAgg = METRIC_CONFIG.find(m => m.key === 'ssr_agg');
    expect(ssr.description).toContain('σ / |ε|');
    expect(ssrAgg.description).toContain('√(mean(σ²) / mean(ε²))');
    [ssr, ssrAgg].forEach(cfg => {
      expect(cfg.description).not.toMatch(/ratio of ensemble variance/i);
    });
  });
});

describe('wind band scales', () => {
  // The bands below were calibrated for precipitation in mm/h and were being
  // applied unchanged to wind in m/s, which put ~79-86% of scored cells in the
  // worst band and made the map one colour. WIND_BAND_BASIS documents the
  // measurement; these tests pin the properties that measurement establishes.
  const UNIT_SENSITIVE = ['bias', 'mae', 'rmse', 'crps'];

  it.each(UNIT_SENSITIVE)('%s carries a wind scale distinct from precipitation', (key) => {
    const cfg = cfgFor(key);
    expect(cfg.windColorFn).toBeInstanceOf(Function);
    expect(cfg.windLegend).toEqual(expect.any(Array));
    expect(cfg.windLegend).toHaveLength(cfg.legend.length);
    // Distinct edges, not a copy — a copied scale would pass every other test
    // here while reintroducing the bug.
    const labels = (l) => l.map(x => x.label).join('|');
    expect(labels(cfg.windLegend)).not.toBe(labels(cfg.legend));
  });

  it.each(UNIT_SENSITIVE)('%s selects its scale from the variable', (key) => {
    const cfg = cfgFor(key);
    expect(metricColorFn(cfg, 'wind')).toBe(cfg.windColorFn);
    expect(metricColorFn(cfg, 'precipitation')).toBe(cfg.colorFn);
    expect(metricLegend(cfg, 'wind')).toBe(cfg.windLegend);
    expect(metricLegend(cfg, 'precipitation')).toBe(cfg.legend);
  });

  it('falls back to the single scale for dimensionless metrics', () => {
    // CSI, POD, FAR, SSR and correlation are ratios: the same bands mean the
    // same thing in any unit, so they deliberately have no override and must
    // not render an empty legend in wind mode.
    for (const key of ['csi', 'pod', 'far', 'ssr']) {
      const cfg = cfgFor(key);
      expect(cfg.windColorFn).toBeUndefined();
      expect(metricColorFn(cfg, 'wind')).toBe(cfg.colorFn);
      expect(metricLegend(cfg, 'wind')).toBe(cfg.legend);
      expect(metricLegend(cfg, 'wind').length).toBeGreaterThan(0);
    }
  });

  it('spreads a realistic wind error distribution across all four bands', () => {
    // The actual defect, expressed as a test. These deciles are the measured
    // per-cell wind MAE distribution over the loaded run (all models, full
    // domain): p10 0.70, median 1.79, p90 4.65. Under the precipitation bands
    // all but one of them came out 'Poor'.
    const observedMae = [0.09, 0.70, 1.09, 1.40, 1.79, 2.30, 3.30, 4.65, 7.05];
    const cfg = cfgFor('mae');
    const colours = new Set(observedMae.map(v => cfg.windColorFn(v)));
    expect(colours.size).toBe(4);

    // And the old scale really did collapse it, so this is not a vacuous claim.
    const precipColours = new Set(observedMae.map(v => cfg.colorFn(v)));
    expect(precipColours.size).toBeLessThan(4);
  });

  it('leaves the precipitation scale untouched', () => {
    // A regression guard on the other side: this change must not move any
    // published precipitation number's colour.
    expect(cfgFor('mae').colorFn(0.1)).toBe(cfgFor('mae').colorFn(0.19));
    expect(cfgFor('mae').colorFn(0.3)).not.toBe(cfgFor('mae').colorFn(0.1));
    expect(cfgFor('rmse').colorFn(0.25)).toBe(cfgFor('mae').colorFn(0.1));
    expect(cfgFor('crps').colorFn(0.1)).toBe(cfgFor('mae').colorFn(0.1));
  });

  it.each(UNIT_SENSITIVE)('%s wind bands are ordered and quote the unit', (key) => {
    const cfg = cfgFor(key);
    const text = cfg.windLegend.map(l => l.label).join(' ');
    expect(text).toContain('{unit}');
    // Every band a distinct colour, in the same order as precipitation's.
    expect(cfg.windLegend.map(l => l.color)).toEqual(cfg.legend.map(l => l.color));
  });
});
