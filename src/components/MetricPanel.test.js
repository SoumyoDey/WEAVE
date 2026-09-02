/**
 * Tests for the floating spatial-metric panel.
 *
 * At 0% coverage this file carried two defects that shipped: a hard-coded °N/°E
 * on the region badge, so every western longitude read as eastern, and metric
 * text written for precipitation and rendered for both variables. Both were
 * found by looking at the running app, which is not a repeatable check.
 *
 * The emphasis is therefore on what the panel *claims*: the unit it prints, the
 * lead times it offers, and the area it says a number came from.
 */
import { fireEvent, render, screen } from '@testing-library/react';

import { MetricPanel } from './MetricPanel';
import { VALUE_UNITS, METRIC_CONFIG } from '../constants';

const REGION = {
  type: 'rectangle',
  bounds: { min_lat: 35, max_lat: 37, min_lon: -77, max_lon: -74 },
};

const noop = () => {};

function setup(props = {}) {
  const api = {
    setMetricType: jest.fn(), setMetricHour: jest.fn(),
    setMetricThreshold: jest.fn(), setPanelMinimized: jest.fn(),
    computeSpatialMetric: jest.fn(), clearSelection: jest.fn(),
    setPanelPos: jest.fn(),
  };
  const utils = render(
    <MetricPanel
      selectedRegion={REGION}
      selectedVariable="precipitation"
      panelPos={{ x: 10, y: 10 }}
      panelMinimized={false}
      metricType="mae"
      metricHour={6}
      metricThreshold={25}
      spatialLoading={false}
      spatialData={null}
      isDraggingPanelRef={{ current: false }}
      dragStartRef={{ current: null }}
      {...api}
      {...props}
    />,
  );
  return { ...utils, ...api };
}

describe('rendering', () => {
  it('renders nothing until a region is drawn', () => {
    const { container } = render(
      <MetricPanel selectedRegion={null} selectedVariable="precipitation"
                   panelPos={{ x: 0, y: 0 }} setPanelPos={noop}
                   panelMinimized={false} setPanelMinimized={noop}
                   metricType="mae" setMetricType={noop}
                   metricHour={6} setMetricHour={noop}
                   metricThreshold={25} setMetricThreshold={noop}
                   spatialLoading={false} spatialData={null}
                   computeSpatialMetric={noop} clearSelection={noop}
                   isDraggingPanelRef={{ current: false }} dragStartRef={{ current: null }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('names the region type and offers every metric', () => {
    setup();
    expect(screen.getByText('Rectangle Region')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Mean Absolute Error/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Brier Score/ })).toBeInTheDocument();
  });

  it('collapses to the title bar when minimized', () => {
    setup({ panelMinimized: true });
    expect(screen.getByText('Rectangle Region')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Compute Spatial Map/ })).not.toBeInTheDocument();
  });
});

describe('the region badge', () => {
  it('labels western longitudes W and southern latitudes S', () => {
    // The defect: a hard-coded °N/°E printed "-77.0°–-74.0°E" for a box that is
    // 77 to 74 degrees WEST. Every loaded run is in the western hemisphere, so
    // the string was wrong every time it appeared.
    setup();
    expect(screen.getByText(/77\.0°W/)).toBeInTheDocument();
    expect(screen.getByText(/35\.0°N/)).toBeInTheDocument();
    expect(screen.queryByText(/-77/)).not.toBeInTheDocument();
    expect(screen.queryByText(/°E/)).not.toBeInTheDocument();
  });

  it('handles a southern-hemisphere region', () => {
    setup({ selectedRegion: {
      type: 'polygon',
      bounds: { min_lat: -20, max_lat: -10, min_lon: 100, max_lon: 120 } } });
    expect(screen.getByText('Polygon Region')).toBeInTheDocument();
    expect(screen.getByText(/20\.0°S/)).toBeInTheDocument();
    expect(screen.getByText(/100\.0°E/)).toBeInTheDocument();
  });
});

describe('units follow the variable', () => {
  it.each([['precipitation', 'mm/h'], ['wind', 'm/s']])(
    'describes a %s metric in %s', (variable, unit) => {
      setup({ selectedVariable: variable, metricType: 'mae' });
      expect(screen.getByText(new RegExp(`\\(${unit.replace('/', '\\/')}\\)`)))
        .toBeInTheDocument();
    });

  it('never shows the other variable\'s unit in the legend', () => {
    const spatialData = {
      metric: 'mae',
      points: [{ lat: 36, lon: -75, value: 1 }],
    };
    const { container, unmount } = setup({ selectedVariable: 'wind', spatialData });
    const wind = container.textContent;
    unmount();
    expect(wind).toContain(VALUE_UNITS.wind);
    expect(wind).not.toContain(VALUE_UNITS.precipitation);
  });

  it('uses a different set of band edges for wind than for precipitation', () => {
    // This replaces a test that asserted the panel *warned* the bands were
    // calibrated for precipitation. That warning was true when written and this
    // change made it false, so the assertion went with it. Asserting the
    // invariant instead — the two variables get genuinely different edges —
    // survives a re-calibration of either scale, where asserting the sentence
    // would have to be rewritten by the same change that breaks it.
    const spatialData = { metric: 'mae', points: [{ lat: 36, lon: -75, value: 1 }] };
    const w = setup({ selectedVariable: 'wind', spatialData });
    const wind = w.container.textContent;
    w.unmount();
    const p = setup({ selectedVariable: 'precipitation', spatialData });
    const precip = p.container.textContent;
    p.unmount();

    // Both label the same four verdicts...
    for (const verdict of ['Excellent', 'Good', 'Moderate', 'Poor']) {
      expect(wind).toContain(verdict);
      expect(precip).toContain(verdict);
    }
    // ...but the numbers differ, and each quotes its own unit.
    expect(wind).toContain('1.0 – 2.0');
    expect(precip).toContain('0.2 – 0.5');
    expect(wind).not.toContain('0.2 – 0.5');
    expect(wind).toContain(VALUE_UNITS.wind);
    expect(precip).toContain(VALUE_UNITS.precipitation);
    // The old warning is not merely absent in one mode — it is gone, because a
    // wind band edge is no longer a precipitation judgement.
    expect(wind).not.toMatch(/calibrated for precipitation/);
  });

  it('still warns for a unitful metric that has no wind bands of its own', () => {
    // The fallback path. If a future unit-sensitive metric arrives without a
    // wind scale, the panel must go back to naming whose scale it is rather
    // than silently presenting mm/h verdicts for m/s.
    const cfg = METRIC_CONFIG.find(m => m.key === 'mae');
    const saved = cfg.windLegend;
    try {
      delete cfg.windLegend;
      const spatialData = { metric: 'mae', points: [{ lat: 36, lon: -75, value: 1 }] };
      const w = setup({ selectedVariable: 'wind', spatialData });
      expect(w.container.textContent).toMatch(/calibrated for precipitation, not for wind/);
      w.unmount();
    } finally {
      cfg.windLegend = saved;
    }
  });

  it('shows the threshold in its own unit, with the rate it becomes', () => {
    const { unmount } = setup({ metricType: 'csi', metricThreshold: 25 });
    expect(screen.getByText('mm/6h')).toBeInTheDocument();
    // 25 mm over 6 h is what the backend actually compares against.
    expect(screen.getByText(/4\.17 mm\/h/)).toBeInTheDocument();
    unmount();

    setup({ metricType: 'csi', selectedVariable: 'wind', metricThreshold: 10 });
    expect(screen.getByText('m/s')).toBeInTheDocument();
  });
});

describe('lead times', () => {
  it('offers +0h for wind, which is instantaneous', () => {
    setup({ metricType: 'ssr', selectedVariable: 'wind', metricHour: 0 });
    expect(screen.getByRole('button', { name: '+0h' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '+24h' })).not.toBeInTheDocument();
  });

  it('withholds +0h for precipitation, which needs a window before it', () => {
    // Precipitation is scored over a common 6 h window, so +0h has no window
    // behind it and always came back empty.
    setup({ metricType: 'ssr', selectedVariable: 'precipitation', metricHour: 6 });
    expect(screen.queryByRole('button', { name: '+0h' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '+24h' })).toBeInTheDocument();
  });

  it('re-selects a valid lead time when the variable changes under it', () => {
    // Switching wind → precipitation with +0h selected would otherwise compute
    // an empty map with nothing to say why.
    const { setMetricHour } = setup({
      metricType: 'ssr', selectedVariable: 'precipitation', metricHour: 0 });
    expect(setMetricHour).toHaveBeenCalledWith(6);
  });

  it('leaves a valid lead time alone', () => {
    const { setMetricHour } = setup({
      metricType: 'ssr', selectedVariable: 'precipitation', metricHour: 12 });
    expect(setMetricHour).not.toHaveBeenCalled();
  });

  it('hides the hour picker for metrics aggregated over lead time', () => {
    setup({ metricType: 'mae' });
    expect(screen.queryByRole('button', { name: '+6h' })).not.toBeInTheDocument();
  });
});

describe('controls', () => {
  it('computes, clears and minimizes through its callbacks', () => {
    const { computeSpatialMetric, clearSelection, setPanelMinimized } = setup();
    fireEvent.click(screen.getByRole('button', { name: /Compute Spatial Map/ }));
    expect(computeSpatialMetric).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(clearSelection).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Minimize panel' }));
    expect(setPanelMinimized).toHaveBeenCalled();
  });

  it('disables compute while a map is rendering', () => {
    setup({ spatialLoading: true });
    expect(screen.getByRole('button', { name: /Computing/ })).toBeDisabled();
  });

  it('clamps the threshold input to a number', () => {
    const { setMetricThreshold } = setup({ metricType: 'csi' });
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '30' } });
    expect(setMetricThreshold).toHaveBeenCalledWith(30);
  });

  it('starts a drag from the title bar', () => {
    const isDraggingPanelRef = { current: false };
    const dragStartRef = { current: null };
    setup({ isDraggingPanelRef, dragStartRef });
    fireEvent.mouseDown(screen.getByText('Rectangle Region'), { clientX: 5, clientY: 7 });
    expect(isDraggingPanelRef.current).toBe(true);
    expect(dragStartRef.current).toMatchObject({ mouseX: 5, mouseY: 7 });
  });
});

describe('results', () => {
  it('counts the points and shows the metric\'s band legend', () => {
    setup({ spatialData: { metric: 'mae', points: [
      { lat: 36, lon: -75, value: 1 }, { lat: 36.5, lon: -75, value: 2 }] } });
    expect(screen.getByText(/2 grid points mapped/)).toBeInTheDocument();
    expect(screen.getByText(/Excellent/)).toBeInTheDocument();
  });

  it('shows a gradient legend for correlation, and the lead-time count', () => {
    // correlation is the one metric with a continuous scale rather than bands,
    // and the only one that reports how many lead times went into it.
    setup({ metricType: 'correlation', spatialData: {
      metric: 'correlation', n_hours: 4, points: [{ lat: 36, lon: -75, value: 0.5 }] } });
    expect(screen.getByText(/4 lead times/)).toBeInTheDocument();
    expect(screen.getByText('−1')).toBeInTheDocument();
    expect(screen.getByText('+1')).toBeInTheDocument();
  });

  it('hides the legend while a new map is computing', () => {
    setup({ spatialLoading: true, spatialData: { metric: 'mae', points: [] } });
    expect(screen.queryByText(/grid points mapped/)).not.toBeInTheDocument();
  });

  it('shows no legend for a metric that has neither bands nor a gradient', () => {
    // Every entry in METRIC_CONFIG has one or the other today; the branch exists
    // so an entry added without either degrades to the point count rather than
    // throwing on a missing `legend`.
    setup({ spatialData: { metric: 'not-a-metric', points: [{ lat: 36, lon: -75, value: 1 }] } });
    expect(screen.getByText(/1 grid points mapped/)).toBeInTheDocument();
    expect(screen.queryByText(/Excellent/)).not.toBeInTheDocument();
  });

  it('omits the lead-time count when correlation reports none', () => {
    // Match the count line, not the metric description — that also says "lead
    // times", which is what made the first version of this test pass wrongly.
    setup({ metricType: 'correlation',
            spatialData: { metric: 'correlation', points: [{ lat: 36, lon: -75, value: 0.2 }] } });
    expect(screen.getByText(/1 grid points mapped/).textContent).not.toMatch(/lead times/);
  });
});

describe('the minimized panel', () => {
  it('offers Expand rather than Minimize, and says so to a screen reader', () => {
    setup({ panelMinimized: true });
    const btn = screen.getByRole('button', { name: 'Expand panel' });
    expect(btn).toHaveAttribute('title', 'Expand');
    fireEvent.click(btn);
  });

  it('does not swallow the drag handler when a header button is pressed', () => {
    // mouseDown on the buttons stops propagation so clicking Close or Minimize
    // does not also start dragging the panel out from under the pointer.
    const isDraggingPanelRef = { current: false };
    setup({ isDraggingPanelRef });
    fireEvent.mouseDown(screen.getByRole('button', { name: 'Close' }));
    expect(isDraggingPanelRef.current).toBe(false);
  });
});
