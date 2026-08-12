/**
 * Unit tests for the Comparison tab's pure data helpers.
 *
 * These turn API payloads into what Recharts draws, so a mistake here shows up
 * as a silently wrong chart rather than an error. They're pure functions, so
 * they're worth testing directly instead of through the rendered component.
 *
 * Unit conversion deliberately is NOT tested here: the backend owns it now
 * (see Data/metrics.py `_precip_rate_series`), because the three models don't
 * share a precipitation convention and a single client-side divisor was wrong
 * for two of them.
 */
import { buildMergedTimeseries, computeScaleRatio, axisTick } from './ComparisonTab';

const MODELS = ['AIFS', 'GEFS'];

// One entry as /api/compare/timeseries returns it — `mean`/`std` are already rates.
const row = (hour, mean, std, extra = {}) => ({ hour, mean, std, ...extra });

describe('buildMergedTimeseries', () => {
  it('returns nothing without data', () => {
    expect(buildMergedTimeseries(null, MODELS)).toEqual([]);
    expect(buildMergedTimeseries({}, MODELS)).toEqual([]);
  });

  it('merges models onto a shared hour axis', () => {
    const ts = {
      AIFS: [row(0, 1, 0.5), row(6, 2, 0.5)],
      GEFS: [row(6, 3, 1)],
    };
    const merged = buildMergedTimeseries(ts, MODELS);
    expect(merged.map(r => r.hour)).toEqual([0, 6]);
    // a model with no entry at that hour simply has no key for it
    expect(merged[0].AIFS_mean).toBe(1);
    expect(merged[0].GEFS_mean).toBeUndefined();
    expect(merged[1].GEFS_mean).toBe(3);
  });

  it('sorts hours numerically, not lexically', () => {
    const ts = { AIFS: [row(120, 1, 0), row(24, 1, 0), row(6, 1, 0)] };
    expect(buildMergedTimeseries(ts, ['AIFS']).map(r => r.hour)).toEqual([6, 24, 120]);
  });

  it('passes the API rate through untouched', () => {
    // The backend already de-accumulated; the client must not rescale.
    const ts = { AIFS: [row(6, 0.0842, 0.01)] };
    expect(buildMergedTimeseries(ts, ['AIFS'])[0].AIFS_mean).toBe(0.0842);
  });

  it('builds a spread band from the mean and std', () => {
    const ts = { AIFS: [row(6, 2, 0.5)] };
    const [r] = buildMergedTimeseries(ts, ['AIFS']);
    expect(r.AIFS_hi).toBe(2.5);
    expect(r.AIFS_lo).toBe(1.5);
  });

  it('clamps the lower band at zero — precipitation cannot be negative', () => {
    const ts = { AIFS: [row(6, 0.2, 1.0)] };
    expect(buildMergedTimeseries(ts, ['AIFS'])[0].AIFS_lo).toBe(0);
  });

  it('treats a missing std as no spread', () => {
    const ts = { AIFS: [row(6, 2, null)] };
    const [r] = buildMergedTimeseries(ts, ['AIFS']);
    expect(r.AIFS_hi).toBe(2);
    expect(r.AIFS_lo).toBe(2);
  });

  it('keeps the raw value and period for the tooltip', () => {
    const ts = { AIFS: [row(6, 0.1, 0.05, { raw_mean: 0.6, period_h: 6 })] };
    const [r] = buildMergedTimeseries(ts, ['AIFS']);
    expect(r.AIFS_raw_mean).toBe(0.6);
    expect(r.AIFS_period_h).toBe(6);
    expect(r.AIFS_rate_mean).toBe(0.1);
  });

  it('normalises each model to its own peak', () => {
    const ts = {
      AIFS: [row(0, 1, 0), row(6, 2, 0)],      // peak 2
      GEFS: [row(0, 50, 0), row(6, 100, 0)],   // peak 100
    };
    const merged = buildMergedTimeseries(ts, MODELS, true);
    expect(merged[1].AIFS_mean).toBe(1);
    expect(merged[1].GEFS_mean).toBe(1);
    expect(merged[0].AIFS_mean).toBe(0.5);
    expect(merged[0].GEFS_mean).toBe(0.5);
  });

  it('normalisation leaves the un-normalised rate intact for the tooltip', () => {
    const ts = { AIFS: [row(0, 1, 0), row(6, 2, 0)] };
    const merged = buildMergedTimeseries(ts, ['AIFS'], true);
    expect(merged[0].AIFS_mean).toBe(0.5);
    expect(merged[0].AIFS_rate_mean).toBe(1);
  });

  it('survives an all-zero series without dividing by zero', () => {
    const ts = { AIFS: [row(0, 0, 0), row(6, 0, 0)] };
    const merged = buildMergedTimeseries(ts, ['AIFS'], true);
    expect(merged.every(r => Number.isFinite(r.AIFS_mean))).toBe(true);
  });

  it('ignores models that were not selected', () => {
    const ts = { AIFS: [row(0, 1, 0)], UKMO: [row(0, 9, 0)] };
    expect(buildMergedTimeseries(ts, ['AIFS'])[0].UKMO_mean).toBeUndefined();
  });
});

describe('computeScaleRatio', () => {
  it('is 1 when fewer than two models have data', () => {
    expect(computeScaleRatio({ AIFS: [row(0, 5, 0)] }, MODELS)).toBe(1);
    expect(computeScaleRatio({}, MODELS)).toBe(1);
  });

  it('is the ratio of the largest to smallest peak', () => {
    const ts = { AIFS: [row(0, 1, 0)], GEFS: [row(0, 10, 0)] };
    expect(computeScaleRatio(ts, MODELS)).toBe(10);
  });

  it('includes the spread in the peak', () => {
    const ts = { AIFS: [row(0, 1, 1)], GEFS: [row(0, 4, 0)] };
    expect(computeScaleRatio(ts, MODELS)).toBe(2);   // peaks 2 and 4
  });

  it('skips models whose peak is zero rather than dividing by it', () => {
    const ts = { AIFS: [row(0, 0, 0)], GEFS: [row(0, 5, 0)] };
    expect(Number.isFinite(computeScaleRatio(ts, MODELS))).toBe(true);
  });
});

describe('axisTick', () => {
  it('keeps a bound like -0.4187 legible in a narrow gutter', () => {
    // Untrimmed, this overflowed the axis and rendered as "4187".
    expect(axisTick(-0.4187)).toBe('-0.42');
  });

  it('drops decimals as the magnitude grows', () => {
    expect(axisTick(0.5)).toBe('0.50');
    expect(axisTick(12.345)).toBe('12.3');
    expect(axisTick(1234.5)).toBe('1235');
  });

  it('renders zero and negatives', () => {
    expect(axisTick(0)).toBe('0.00');
    expect(axisTick(-2.5)).toBe('-2.50');
  });

  it('returns empty for non-numeric input rather than NaN', () => {
    expect(axisTick(undefined)).toBe('');
    expect(axisTick(null)).toBe('');
    expect(axisTick('abc')).toBe('');
  });
});
