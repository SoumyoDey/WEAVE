/**
 * The Comparison tab's drawing pieces: cards, charts, bars and tooltips.
 *
 * Presentational and stateless — every one takes its data as props and holds
 * nothing. That is what made them safe to lift out of a 2,373-line component
 * (`NEXT_STEPS.md` §59) and it is the line worth keeping: a piece moves here
 * when it stops owning state, not merely when the file gets long.
 *
 * `LeadTimeChart` and `AggregateBar` are the two shapes the tab repeats — a
 * metric against lead time, and the same metric aggregated per model — so the
 * region, point and categorical panels all read as variations of two charts
 * rather than as twelve separate blocks.
 */
import React from 'react';
import {
  BarChart, Bar, Cell, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { MapPin } from 'lucide-react';

import { t } from '../../theme';
import { LoadingState } from '../ui/PanelState';
import { MODEL_COLORS } from './metrics';
import { CARD, TOOLTIP_STYLE } from './styles';

// Kept as a thin alias so the ~6 call sites read the same as before; the
// treatment itself is now shared with AnalysisTab (ui/PanelState).
export const Spinner = LoadingState;

// Shown wherever region mode needs a bbox that hasn't been drawn yet.
export function RegionNudge() {
  return (
    <div style={{
      borderRadius: '10px',
      padding: '20px 24px',
      border: '1px dashed rgba(255,255,255,0.15)',
      background: 'rgba(255,255,255,0.02)',
      display: 'flex',
      alignItems: 'flex-start',
      gap: '12px',
      color: 'rgba(255,255,255,0.35)',
      fontSize: t.fontSize.base,
      lineHeight: 1.6,
    }}>
      <span style={{ lineHeight: 1, display: 'inline-flex' }}><MapPin size={18} /></span>
      <div>
        <div style={{ fontWeight: t.fontWeight.semibold, color: 'rgba(255,255,255,0.5)', marginBottom: '4px' }}>
          No region selected
        </div>
        Switch to the <strong style={{ color: 'rgba(255,255,255,0.6)' }}>Visualization</strong> tab,
        use the selection toolbar to draw a rectangle or polygon, then return here.
      </div>
    </div>
  );
}

export function ssrColor(ssr) {
  if (ssr == null) return '#aaa';
  if (ssr >= 0.8 && ssr <= 1.2) return '#2ecc71';
  if (ssr < 0.8) return '#e74c3c';
  return '#f39c12';
}

export function corrColor(c) {
  if (c == null) return '#aaa';
  if (c >= 0.7) return '#2ecc71';
  if (c >= 0.4) return '#f39c12';
  return '#e74c3c';
}

// Y-axis tick labels in the narrow metric cards. A raw domain bound like
// -0.4187 overflows the axis gutter and gets clipped to "4187", so round to a
// width the gutter can actually show.
export const axisTick = (v) => {
  // Guard null explicitly: Number(null) is 0, which would draw a spurious "0.00"
  // label for a missing tick rather than no label at all.
  if (v === null || v === undefined || v === '') return '';
  const n = Number(v);
  if (!Number.isFinite(n)) return '';
  const abs = Math.abs(n);
  if (abs >= 100) return n.toFixed(0);
  if (abs >= 10)  return n.toFixed(1);
  if (abs >= 1)   return n.toFixed(2);
  return n.toFixed(2);
};

// Placeholder used inside a metric card when every model came back empty, so a
// missing metric reads as "no data" rather than an unexplained blank panel.
export function NoData({ text = 'No data for this selection' }) {
  return (
    <div style={{
      height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: 'rgba(255,255,255,0.25)', fontSize: t.fontSize.xs, textAlign: 'center', padding: '0 8px',
    }}>
      {text}
    </div>
  );
}

export function MetricCard({ label, hint, height, children }) {
  return (
    <div style={{ ...CARD, padding: '12px 10px 6px' }}>
      <div style={{ fontSize: t.fontSize.base, fontWeight: t.fontWeight.semibold, color: 'rgba(255,255,255,0.85)' }}>{label}</div>
      <div style={{ fontSize: t.fontSize.micro, color: 'rgba(255,255,255,0.4)', marginBottom: '4px' }}>
        {hint || ' '}
      </div>
      <div style={{ height }}>{children}</div>
    </div>
  );
}

// One metric over lead time, a line per model. `rows` is [{hour, <key>_<model>}].
export function LeadTimeChart({ label, hint, metricKey, rows, models, refLine, decimals = 3 }) {
  const hasData = rows.some(r => models.some(m => r[`${metricKey}_${m}`] != null));
  return (
    <MetricCard label={label} hint={hint} height="160px">
      {hasData ? (
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 6, right: 14, left: -10, bottom: 16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
            <XAxis dataKey="hour" stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 10 }} tickFormatter={h => `+${h}h`} />
            <YAxis stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 10 }} width={46} tickFormatter={axisTick} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(value, name) => [value != null ? Number(value).toFixed(decimals) : 'N/A', name.replace(`${metricKey}_`, '')]}
              labelFormatter={h => `+${h}h`}
            />
            {refLine != null && (
              <ReferenceLine y={refLine} stroke="rgba(255,255,255,0.35)" strokeDasharray="5 3" />
            )}
            {models.map(m => (
              <Line
                key={m}
                type="linear"
                dataKey={`${metricKey}_${m}`}
                name={`${metricKey}_${m}`}
                stroke={MODEL_COLORS[m]}
                strokeWidth={2}
                connectNulls
                dot={{ r: 2.5, fill: MODEL_COLORS[m], strokeWidth: 0 }}
                activeDot={{ r: 5 }}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      ) : <NoData />}
    </MetricCard>
  );
}

// One aggregate metric, a bar per model. `values` is parallel to `models`.
export function AggregateBar({ label, hint, models, values, refLine, decimals = 3, bounded = false }) {
  const data    = models.map((m, i) => ({ model: m, value: values[i] }));
  const hasData = values.some(v => v != null);
  return (
    <MetricCard label={label} hint={hint} height="150px">
      {hasData ? (
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 6, right: 12, left: -10, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
            <XAxis dataKey="model" stroke="rgba(255,255,255,0.3)" tick={{ fill: 'rgba(255,255,255,0.6)', fontSize: 10 }} />
            {/* Bar length encodes magnitude, so the axis has to include 0 —
                otherwise all-negative metrics (e.g. a negative spread-skill
                correlation) hang from the top and read as large positives. A
                bounded score gets the whole [0, 1] instead, so a bad score looks
                bad rather than filling the panel. */}
            <YAxis
              stroke="rgba(255,255,255,0.3)"
              tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 10 }}
              width={46}
              domain={bounded ? [0, 1] : [v => Math.min(0, v), v => Math.max(0, v)]}
              tickFormatter={axisTick}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              cursor={{ fill: 'rgba(255,255,255,0.04)' }}
              formatter={v => [v != null ? Number(v).toFixed(decimals) : 'N/A', label]}
            />
            {refLine != null && (
              <ReferenceLine y={refLine} stroke="rgba(255,255,255,0.35)" strokeDasharray="5 3" />
            )}
            <Bar dataKey="value" radius={[3, 3, 0, 0]} maxBarSize={44} isAnimationActive={false}>
              {data.map(d => <Cell key={d.model} fill={MODEL_COLORS[d.model]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      ) : <NoData />}
    </MetricCard>
  );
}

// ── Custom Tooltip for Forecast Comparison chart ─────────────────────────────
// The API already returns rates (mm/h or m/s); `raw_mean` is the stored value,
// shown underneath for precipitation so the conversion stays inspectable.
export function ForecastTooltip({ active, payload, label, selectedModels, normalized, variable = 'precipitation', displayUnit = 'mm/h' }) {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0]?.payload || {};
  const isPrecip = variable === 'precipitation';

  const means = selectedModels
    .map(m => {
      const rateMean = row[`${m}_rate_mean`];
      if (rateMean == null) return null;
      return {
        model: m,
        rateMean,
        rateStd: row[`${m}_rate_std`] ?? null,
        rawMean: row[`${m}_raw_mean`] ?? null,
        periodH: row[`${m}_period_h`] ?? 1,
      };
    })
    .filter(Boolean);

  if (!means.length) return null;

  return (
    <div style={{ ...TOOLTIP_STYLE, padding: '10px 14px', minWidth: '210px' }}>
      <div style={{ color: 'rgba(255,255,255,0.5)', fontSize: t.fontSize.xs, marginBottom: '8px' }}>
        +{label}h forecast
        {normalized && <span style={{ color: '#f39c12', marginLeft: '6px' }}>· per-model normalised</span>}
      </div>
      {means.map(({ model, rateMean, rateStd, rawMean, periodH }) => (
        <div key={model} style={{ marginBottom: '6px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ display: 'inline-block', width: '10px', height: '10px', borderRadius: '2px', background: MODEL_COLORS[model] }} />
            <span style={{ color: 'rgba(255,255,255,0.85)', fontWeight: t.fontWeight.semibold, minWidth: '44px' }}>{model}</span>
            <span style={{ color: 'rgba(255,255,255,0.85)', fontWeight: t.fontWeight.bold }}>
              {rateMean.toFixed(3)}
              <span style={{ color: 'rgba(255,255,255,0.5)', fontWeight: t.fontWeight.normal, fontSize: t.fontSize.micro, marginLeft: '2px' }}>{displayUnit}</span>
            </span>
            {rateStd != null && (
              <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: t.fontSize.xs }}>±{rateStd.toFixed(3)}</span>
            )}
          </div>
          {/* Stored value — informative for precipitation, where it differs
              from the rate (a running total for AIFS, a bucket for GEFS) */}
          {isPrecip && rawMean != null && periodH > 1 && (
            <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: t.fontSize.micro, marginLeft: '18px', marginTop: '1px' }}>
              stored: {rawMean.toFixed(3)} · {periodH}h period
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
