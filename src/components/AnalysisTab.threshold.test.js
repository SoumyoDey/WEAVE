/**
 * One threshold for the Analysis tab.
 *
 * It used to hold two: `catThreshold` behind the Verification Metrics panel and
 * `regionThreshold` behind the spatial maps. Both scored **the same region**,
 * both were labelled "Threshold" (one qualified "(maps)"), and only one was
 * visible in each mode. They started equal, so the tab agreed with itself until
 * someone changed one — and then the same region was scored at two thresholds
 * with nothing on screen saying so.
 *
 * Merging them is only safe because the units already matched: both paths send
 * `threshold_mm_6h` for precipitation and `threshold_ms` for wind, in native
 * units. That is checked here too, because it is the assumption the merge rests
 * on and it is not visible from either call site.
 *
 * These render the component rather than reading its source: the point is that
 * typing in one box changes what the other box shows, which source cannot say.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import fs from 'fs';
import path from 'path';

import { AnalysisTab } from './AnalysisTab';

const PROPS = {
  clickedPoint: { lat: 36.0, lon: -75.5 },
  currentModel: { name: 'AIFS', color: '#3498db', hasEnsemble: true, ensembleCount: 50 },
  selectedVariable: 'precipitation',
  timeseriesLoading: false,
  timeseriesData: null,
  ssrLoading: false,
  ssrData: null,
  obsCoverage: null,
  onCompare: () => {},
  selectedRegion: { bounds: { min_lat: 35, max_lat: 37, min_lon: -76, max_lon: -74 } },
  active: true,
};

/** Both threshold inputs on screen, in whichever mode is open. */
const thresholdInputs = () =>
  screen.getAllByTitle(/Event threshold, in native units/)
    .map((label) => label.parentElement.querySelector('input[type=number]'))
    .filter(Boolean);

/**
 * The tab defers its first render by one animation frame, so Recharts measures
 * a laid-out container rather than a hidden one. Every test has to wait for
 * that frame or it asserts against an empty document.
 */
const renderTab = async (props = {}) => {
  const view = render(<AnalysisTab {...PROPS} {...props} />);
  await waitFor(() => expect(thresholdInputs().length).toBeGreaterThan(0));
  return view;
};

const switchTo = (mode) => fireEvent.click(screen.getByRole('button', { name: mode }));

beforeEach(() => {
  global.fetch = jest.fn(() => Promise.resolve({
    ok: true, status: 200, json: () => Promise.resolve({}),
  }));
});

describe('the Analysis tab has one threshold', () => {
  it('starts both inputs at the variable default', async () => {
    await renderTab();
    const inputs = thresholdInputs();
    expect(inputs.length).toBeGreaterThan(0);
    inputs.forEach((i) => expect(i.value).toBe('25'));
  });

  it('carries a change in one mode over to the other', async () => {
    await renderTab();
    const [first] = thresholdInputs();
    fireEvent.change(first, { target: { value: '8' } });
    expect(thresholdInputs().every((i) => i.value === '8')).toBe(true);

    // And across the tab's own mode switch, which is where the two used to
    // part company: each mode showed its own box.
    switchTo('Region');
    expect(thresholdInputs().every((i) => i.value === '8')).toBe(true);
    switchTo('Point');
    expect(thresholdInputs().every((i) => i.value === '8')).toBe(true);
  });

  it('labels it the same in both modes, with no "(maps)" qualifier left', async () => {
    await renderTab();
    switchTo('Region');
    expect(screen.queryByText('Threshold (maps)')).not.toBeInTheDocument();
    expect(screen.getAllByText('Threshold').length).toBeGreaterThan(0);
  });

  it('switches the default with the variable, in one place', async () => {
    const { rerender } = await renderTab();
    rerender(<AnalysisTab {...PROPS} selectedVariable="wind" />);
    await waitFor(() =>
      expect(thresholdInputs().every((i) => i.value === '10')).toBe(true));
  });
});

describe('the assumption the merge rests on', () => {
  it('sends the same field and the same units from both paths', () => {
    // The maps go through spatialApi and the scores through analysisApi. If
    // these ever disagree about which field carries the number, one threshold
    // would mean two different things again — silently, since both are just
    // a number in a box.
    const spatial = fs.readFileSync(path.join(__dirname, '..', 'api', 'spatialApi.js'), 'utf8');
    const analysis = fs.readFileSync(path.join(__dirname, '..', 'api', 'analysisApi.js'), 'utf8');
    for (const source of [spatial, analysis]) {
      expect(source).toContain('threshold_ms');
      expect(source).toContain('threshold_mm_6h');
      expect(source).toMatch(/wind.*threshold_ms|threshold_ms.*wind/s);
    }
  });
});
