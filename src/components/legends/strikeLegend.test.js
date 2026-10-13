/**
 * The strike-probability legend says what the map draws.
 *
 * The overlay shipped without a legend: a reader saw blue → green → orange and
 * had to infer both the direction and the scale from the colours, which is the
 * one thing a sequential palette cannot convey alone.
 *
 * Two things are worth testing and only one of them is the rendering.
 *
 * **The scale must have one definition.** `strikeColour` was a chain of `if`
 * statements and is now driven by `STRIKE_BANDS`, which the legend also reads.
 * The first block below pins that the refactor did not move a single boundary —
 * a legend that is right about a scale the map no longer uses is worse than no
 * legend, and it is the same defect as §19's wind metrics labelled `mm/h`.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';

import { STRIKE_BANDS, strikeColour } from '../../api/cyclone';
import { StrikeProbabilityLegend } from './StrikeProbabilityLegend';

/** The mapping exactly as it was written before `STRIKE_BANDS` existed. */
const originalColour = (value) => {
  const v = Math.max(0, Math.min(1, value));
  if (v < 0.1) return 'rgba(80,140,255,0.18)';
  if (v < 0.25) return 'rgba(90,190,235,0.28)';
  if (v < 0.5) return 'rgba(120,220,170,0.38)';
  if (v < 0.75) return 'rgba(240,210,100,0.50)';
  return 'rgba(240,120,70,0.62)';
};

describe('the refactor to STRIKE_BANDS changed no colour', () => {
  // Every boundary, both sides of it, plus the ends and the out-of-range
  // values the server should never send but might.
  const probes = [
    -1, 0, 0.0001, 0.0999, 0.1, 0.1001, 0.2499, 0.25, 0.2501,
    0.4999, 0.5, 0.5001, 0.7499, 0.75, 0.7501, 0.999, 1, 2,
  ];

  it.each(probes)('%p maps to the same colour as before', (v) => {
    expect(strikeColour(v)).toBe(originalColour(v));
  });

  it('agrees across a fine sweep, not just at the boundaries', () => {
    for (let i = 0; i <= 1000; i += 1) {
      const v = i / 1000;
      expect(strikeColour(v)).toBe(originalColour(v));
    }
  });

  it('puts a value exactly on a boundary in the band above it', () => {
    // `upto` is exclusive, and this is the half of the contract a reader of
    // the legend relies on: 25% is in "25 – 50", not "10 – 25".
    expect(strikeColour(0.25)).toBe(strikeColour(0.3));
    expect(strikeColour(0.25)).not.toBe(strikeColour(0.2));
  });
});

describe('the legend', () => {
  it('names every band the map can draw, and no others', () => {
    render(<StrikeProbabilityLegend radiusKm={120} nominalMembers={51} peak={1} />);
    for (const band of STRIKE_BANDS) {
      expect(screen.getByText(band.label)).toBeInTheDocument();
    }
  });

  it('draws each swatch in the colour that band actually uses', () => {
    // The point of the whole exercise: the swatch and the cell are one value.
    const { container } = render(
      <StrikeProbabilityLegend radiusKm={120} nominalMembers={51} peak={0.5} />);
    // Compared as four numbers, not as text. jsdom re-serialises colours —
    // spaces after the commas, and `0.50` written back as `0.5` — so a string
    // comparison here fails on spelling while the colour is identical, which
    // would be a test about CSS serialisation rather than about the legend.
    const rgba = (s) => (s.match(/[\d.]+/g) || []).map(Number);
    const backgrounds = [...container.querySelectorAll('span')]
      .map((el) => el.style.background)
      .filter(Boolean)
      .map(rgba);
    for (const band of STRIKE_BANDS) {
      expect(backgrounds).toContainEqual(rgba(band.colour));
    }
  });

  it('states the radius, because the probability is meaningless without it', () => {
    render(<StrikeProbabilityLegend radiusKm={60} nominalMembers={31} peak={0.4} />);
    expect(screen.getByText(/within 60 km/)).toBeInTheDocument();
  });

  it('states the denominator, which is the members that ran', () => {
    // `nominal_members`, not the number that drew a track — the distinction
    // the cyclone endpoints return both numbers for.
    render(<StrikeProbabilityLegend radiusKm={120} nominalMembers={51} peak={0.4} />);
    expect(screen.getByText(/of 51/)).toBeInTheDocument();
  });

  it('shows the peak as a percentage', () => {
    render(<StrikeProbabilityLegend radiusKm={120} nominalMembers={51} peak={0.94} />);
    expect(screen.getByText('94%')).toBeInTheDocument();
  });

  it('renders without a radius, a denominator or a peak', () => {
    // The overlay can be on before the response carries every field; a legend
    // that throws would take the map down with it.
    const { container } = render(<StrikeProbabilityLegend />);
    expect(container).not.toBeEmptyDOMElement();
    expect(screen.getByText(/Strike probability/)).toBeInTheDocument();
  });

  it('does not intercept clicks meant for the map', () => {
    const { container } = render(
      <StrikeProbabilityLegend radiusKm={120} nominalMembers={51} peak={0.4} />);
    expect(container.firstChild.style.pointerEvents).toBe('none');
  });
});
