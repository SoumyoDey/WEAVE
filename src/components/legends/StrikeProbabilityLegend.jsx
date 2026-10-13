/**
 * What the shaded cells on the cyclone map mean.
 *
 * The strike-probability overlay shipped without one. A reader saw a field
 * going blue → green → orange and had to infer both the direction and the
 * scale from the colours, which is the one thing a sequential palette cannot
 * tell you on its own: whether orange is 60% or 100%, and whether the faintest
 * blue is "unlikely" or "no data".
 *
 * **Discrete swatches, not a gradient bar**, because the field is discrete.
 * `strikeColour` puts every cell into one of five bands, so a continuous ramp
 * would show a precision the map does not have — the same objection this
 * project raised to the metric palettes, which encode calibrated edges a
 * probability has none of.
 *
 * **It reads `STRIKE_BANDS`** rather than restating the colours. A legend with
 * its own copy of the scale is a caption that can drift from what it captions,
 * and drifted captions are what §19 (four metrics labelled `mm/h` for wind) and
 * §75 (the observation sources) were.
 *
 * The denominator is on the card for the reason `cyclone_metrics` returns it:
 * **the fraction is of the members that ran, not of the members that drew a
 * track.** A storm no member forecast is 0%, and that zero is a real forecast
 * rather than missing data — which is exactly what someone reading a faint blue
 * cell needs to know.
 */
import React from 'react';

import { STRIKE_BANDS } from '../../api/cyclone';
import { t } from '../../theme';

export function StrikeProbabilityLegend({ radiusKm, nominalMembers, peak }) {
  return (
    <div style={{
      background: 'rgba(10,18,28,0.92)',
      border: '1px solid rgba(255,255,255,0.1)',
      backdropFilter: 'blur(8px)',
      padding: '10px 12px',
      borderRadius: '10px',
      boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
      userSelect: 'none',
      pointerEvents: 'none',
    }}>
      <div style={{ color: 'white', fontSize: t.fontSize.sm,
                    fontWeight: t.fontWeight.semibold, marginBottom: '2px' }}>
        Strike probability{' '}
        <span style={{ fontWeight: t.fontWeight.normal, opacity: 0.7 }}>(%)</span>
      </div>

      {radiusKm != null && (
        <div style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.micro,
                      marginBottom: '8px' }}>
          members passing within {radiusKm} km
          {nominalMembers != null && ` · of ${nominalMembers}`}
        </div>
      )}

      {/* Highest band first: the map is read for where the storm is most
          likely to go, so the number someone is looking for is at the top. */}
      {[...STRIKE_BANDS].reverse().map((band) => (
        <div key={band.label}
             style={{ display: 'flex', alignItems: 'center', gap: '8px',
                      marginTop: '3px' }}>
          <span style={{
            width: '22px', height: '12px', borderRadius: '3px',
            background: band.colour,
            // The cells are translucent over a dark basemap; the same colour on
            // a pale swatch would read as a different one, so the swatch keeps
            // the map's background underneath it.
            border: '1px solid rgba(255,255,255,0.18)',
            flexShrink: 0,
          }} />
          <span style={{ color: 'rgba(255,255,255,0.7)', fontSize: t.fontSize.micro }}>
            {band.label}
          </span>
        </div>
      ))}

      {peak != null && (
        <div style={{ color: 'rgba(255,255,255,0.45)', fontSize: t.fontSize.micro,
                      marginTop: '8px', paddingTop: '6px',
                      borderTop: '1px solid rgba(255,255,255,0.08)' }}>
          peak <strong style={{ color: 'rgba(255,255,255,0.75)' }}>
            {(peak * 100).toFixed(0)}%
          </strong>
        </div>
      )}
    </div>
  );
}

export default StrikeProbabilityLegend;
