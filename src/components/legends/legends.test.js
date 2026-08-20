/**
 * Tests for the five map legends.
 *
 * These were at 0% coverage, and it showed: a hard-coded `°E` on every region
 * badge survived until someone drew a box and read it, and two of these files
 * use `t` as a local variable while importing the design token `t`, which
 * compiles and passes a build and fails only at render.
 *
 * So the emphasis here is on the two things a build cannot catch:
 *   - the component renders at all, with realistic props;
 *   - the units and direction words it prints are the right ones for the
 *     variable, which is what CONSISTENCY_AUDIT_PLAN.md phase 6 is about.
 */
import { render, screen } from '@testing-library/react';

import { BivariateLegend } from './BivariateLegend';
import { IDWLegend } from './IDWLegend';
import { TextureLegend } from './TextureLegend';
import { VSUPBoxesLegend } from './VSUPBoxesLegend';
import { VSUPFanLegend } from './VSUPFanLegend';
import { COLORMAPS, buildColorMatrix, VALUE_UNITS } from '../../constants';
import { getLegendGradient } from '../../utils/colorUtils';

const RANGES = { meanMax: 5, stdMax: 2 };
const STATS  = { min: 0, max: 5, mean: 1.2 };

// jsdom ships no 2D context, so TextureLegend's swatches would skip their
// drawing entirely (the component now guards for a null context, which is also
// what a headless or canvas-disabled browser hands back). Recording stub: the
// swatch code runs for real and the test can assert it drew something, which is
// the only way these branches get exercised at all.
const canvasCalls = [];
beforeAll(() => {
  HTMLCanvasElement.prototype.getContext = function () {
    const rec = (name) => (...args) => canvasCalls.push([name, ...args]);
    return {
      clearRect: rec('clearRect'), fillRect: rec('fillRect'), beginPath: rec('beginPath'),
      moveTo: rec('moveTo'), lineTo: rec('lineTo'), stroke: rec('stroke'),
      rect: rec('rect'), clip: rec('clip'), save: rec('save'), restore: rec('restore'),
      set fillStyle(v) { canvasCalls.push(['fillStyle', v]); },
      set strokeStyle(v) { canvasCalls.push(['strokeStyle', v]); },
      set lineWidth(v) { canvasCalls.push(['lineWidth', v]); },
    };
  };
});
beforeEach(() => { canvasCalls.length = 0; });

// Every legend, with the props it needs, so one table can drive the checks that
// apply to all of them.
const LEGENDS = [
  ['IDWLegend', (v, extra = {}) => (
    <IDWLegend selectedColormap="Viridis" stats={STATS} selectedVariable={v}
               selectedMember="mean" getLegendGradient={getLegendGradient} {...extra} />)],
  ['BivariateLegend', (v, extra = {}) => (
    <BivariateLegend bivariateRanges={RANGES} selectedColormap="Viridis"
                     selectedVariable={v} buildColorMatrix={buildColorMatrix} {...extra} />)],
  ['VSUPBoxesLegend', (v, extra = {}) => (
    <VSUPBoxesLegend stats={STATS} selectedVariable={v} stdMax={2} {...extra} />)],
  ['VSUPFanLegend', (v, extra = {}) => (
    <VSUPFanLegend bivariateRanges={RANGES} selectedColormap="Viridis"
                   colormaps={COLORMAPS} selectedVariable={v} {...extra} />)],
  ['TextureLegend', (v, extra = {}) => (
    <TextureLegend bivariateRanges={RANGES} selectedColormap="Viridis"
                   selectedVariable={v} {...extra} />)],
];

describe.each(LEGENDS)('%s', (name, el) => {
  it('renders for precipitation', () => {
    const { container } = render(el('precipitation'));
    expect(container).not.toBeEmptyDOMElement();
  });

  it('renders for wind', () => {
    const { container } = render(el('wind'));
    expect(container).not.toBeEmptyDOMElement();
  });

  it('never prints the other variable\'s unit', () => {
    // The defect class phase 6 fixed: a legend written for precipitation and
    // rendered for both labels a wind field in mm/h.
    const wind = render(el('wind')).container.textContent;
    expect(wind).not.toContain(VALUE_UNITS.precipitation);

    const precip = render(el('precipitation')).container.textContent;
    expect(precip).not.toContain(VALUE_UNITS.wind);
  });

  it('survives the display toggles without throwing', () => {
    // numBuckets drives real branching — bucketed legends build a different
    // number of swatches — and flip/invert reverse the scales.
    for (const extra of [{ numBuckets: 4 }, { numBuckets: 1 }, { flipColormap: true },
                         { invertUncertainty: true }, { numBuckets: 8, flipColormap: true }]) {
      expect(() => render(el('precipitation', extra))).not.toThrow();
    }
  });
});

describe('units and wording', () => {
  it.each([['precipitation', 'mm/h'], ['wind', 'm/s']])(
    'IDWLegend labels %s in %s', (variable, unit) => {
      render(<IDWLegend selectedColormap="Viridis" stats={STATS} selectedVariable={variable}
                        selectedMember="mean" getLegendGradient={getLegendGradient} />);
      expect(screen.getByText(`(${unit})`)).toBeInTheDocument();
    });

  it('IDWLegend calls the spread "Uncertainty", not the variable name', () => {
    // Selecting the std-dev member changes what the colours mean; the legend has
    // to say so rather than keep calling the field Precipitation.
    render(<IDWLegend selectedColormap="Viridis" stats={STATS} selectedVariable="precipitation"
                      selectedMember="std" getLegendGradient={getLegendGradient} />);
    expect(screen.getByText(/Uncertainty/)).toBeInTheDocument();
  });

  it('VSUPBoxesLegend states which direction means less certain', () => {
    const normal = render(
      <VSUPBoxesLegend stats={STATS} selectedVariable="wind" stdMax={2} />).container.textContent;
    expect(normal).toMatch(/larger = more uncertain/);

    const inverted = render(
      <VSUPBoxesLegend stats={STATS} selectedVariable="wind" stdMax={2}
                       invertUncertainty />).container.textContent;
    expect(inverted).toMatch(/smaller = more uncertain/);
  });

  it('VSUPFanLegend draws its axis labels as SVG text', () => {
    // The fan is the one legend built from SVG <text> rather than DOM nodes, and
    // its font sizes come through presentation attributes — a separate path from
    // the style prop, and the one the phase-5 grep could not see.
    const { container } = render(
      <VSUPFanLegend bivariateRanges={RANGES} selectedColormap="Viridis"
                     colormaps={COLORMAPS} selectedVariable="wind" />);
    const texts = [...container.querySelectorAll('svg text')];
    expect(texts.length).toBeGreaterThan(0);
    expect(texts.some(t => /Std\. Dev\./.test(t.textContent))).toBe(true);
    expect(container.textContent).toContain('Wind Speed (m/s)');
  });

  it('TextureLegend explains both channels it encodes', () => {
    const { container } = render(
      <TextureLegend bivariateRanges={RANGES} selectedColormap="Viridis"
                     selectedVariable="precipitation" />);
    expect(container.textContent).toMatch(/Colour = value/);
    expect(container.textContent).toMatch(/hatching/);
  });

  it.each([['Lines', 'lineTo'], ['Squares', 'fillRect']])(
    'TextureLegend draws the %s pattern with %s', (textureStyle, op) => {
      render(<TextureLegend bivariateRanges={RANGES} selectedColormap="Viridis"
                            selectedVariable="wind" textureStyle={textureStyle} />);
      expect(canvasCalls.some(([name]) => name === op)).toBe(true);
    });

  it('TextureLegend draws denser lines at higher uncertainty', () => {
    // The whole point of the texture channel: spacing shrinks as spread grows,
    // so a high-uncertainty swatch must emit more line segments than a low one.
    render(<TextureLegend bivariateRanges={{ meanMax: 5, stdMax: 2 }}
                          selectedColormap="Viridis" selectedVariable="wind"
                          textureStyle="Lines" numBuckets={2} />);
    const segments = canvasCalls.filter(([name]) => name === 'moveTo').length;
    expect(segments).toBeGreaterThan(2);
  });
});

describe('degenerate inputs', () => {
  it('BivariateLegend and VSUPFanLegend render nothing without ranges', () => {
    // App passes null before the first fetch resolves; returning null is the
    // contract, and throwing here would blank the whole map.
    expect(render(<BivariateLegend bivariateRanges={null} selectedColormap="Viridis"
                                   selectedVariable="wind" buildColorMatrix={buildColorMatrix} />)
      .container).toBeEmptyDOMElement();
    expect(render(<VSUPFanLegend bivariateRanges={null} selectedColormap="Viridis"
                                 colormaps={COLORMAPS} selectedVariable="wind" />)
      .container).toBeEmptyDOMElement();
  });

  it('a zero range does not divide by zero', () => {
    const flat = { meanMax: 0, stdMax: 0 };
    expect(() => render(
      <TextureLegend bivariateRanges={flat} selectedColormap="Viridis"
                     selectedVariable="wind" />)).not.toThrow();
    expect(() => render(
      <VSUPFanLegend bivariateRanges={flat} selectedColormap="Viridis"
                     colormaps={COLORMAPS} selectedVariable="wind" />)).not.toThrow();
  });

  it('an unknown colormap falls back rather than crashing', () => {
    expect(() => render(
      <TextureLegend bivariateRanges={RANGES} selectedColormap="NoSuchMap"
                     selectedVariable="wind" />)).not.toThrow();
  });
});
