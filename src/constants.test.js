/**
 * Tests for the metric registry's user-visible text.
 *
 * METRIC_CONFIG's descriptions and legend bands are rendered for BOTH variables
 * by MetricPanel, so a literal 'mm/h' in one of them labels a wind map in a
 * precipitation unit. That is the same defect /api/compare/skill had when it
 * hard-coded `units: 'mm/h'`, and it is what CONSISTENCY_AUDIT_PLAN.md phase 6
 * exists to catch. These tests fail if a literal unit comes back.
 */
import { METRIC_CONFIG, VALUE_UNITS, withUnit } from './constants';

// Metrics whose value carries the variable's unit. The rest — the ratios and
// the scores in [0,1] — are dimensionless and must name no unit at all.
const UNITFUL = ['bias', 'mae', 'rmse', 'crps'];

const textOf = (cfg) => [
  cfg.description,
  ...(cfg.legend ?? []).map(l => l.label),
  ...Object.values(cfg.legendGradient ?? {}).flat().filter(v => typeof v === 'string'),
].join(' | ');

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
