/**
 * The cyclone tab must never request a (storm, centre, init) triple that
 * cannot exist.
 *
 * An initialisation belongs to one storm at one centre. The first version of
 * this component held the init in state and reset it in an effect, which is
 * one commit too late: effects run *after* the render, so on the render where
 * the storm had changed and the init had not, the three fetch effects had
 * already fired with the old init. Each returned 404, each was a real database
 * query, and the `alive` guards meant none of them was ever displayed — so the
 * tab looked entirely correct and only the network log disagreed.
 *
 * That is the failure this file exists to pin, and it is pinned by asserting a
 * property of **every** request made, not by asserting the final state. The
 * final state was always right; that was the problem.
 *
 * The API module is mocked rather than `fetch`, because the point is which
 * arguments the component chose, not how they were serialised.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { CycloneTab } from './CycloneTab';
import {
  fetchCyclones, fetchCycloneTracks, fetchErrorByLead, fetchStrikeProbability,
} from '../api/cyclone';

jest.mock('../api/cyclone', () => ({
  fetchCyclones: jest.fn(),
  fetchCycloneTracks: jest.fn(),
  fetchErrorByLead: jest.fn(),
  fetchStrikeProbability: jest.fn(),
  unwrapTrack: (points) => points.map((p) => [p.lat, p.lon]),
  referenceLongitude: () => 0,
  strikeColour: () => 'rgba(0,0,0,0.2)',
}));

/**
 * Rendered **inactive**, which is not a dodge: `active` gates only the two map
 * effects, and the three fetch effects under test here are independent of it.
 * The controls render either way. Leaflet wants a real layout engine that
 * jsdom does not have, and stubbing it would add a large mock whose fidelity
 * nothing here checks — the map is verified in the browser instead.
 */
const renderTab = () => render(<CycloneTab active={false} />);

/**
 * Two storms whose initialisations do not overlap.
 *
 * That non-overlap is the whole fixture: if ALCIDE and DORIAN shared an init,
 * carrying a stale one across a storm switch would still resolve and the bug
 * would be invisible. The real archive is like this — inits are storm-specific
 * — so the fixture matches it rather than being convenient.
 */
const RUNS = [
  { storm_name: 'ALCIDE', centre: 'ecmf', system: 'ECMWF-ENS',
    init_time: '2018-11-09T00:00:00', nominal_members: 51, tracked_members: 51,
    basin: 'SI', basin_source: 'SI', lead_min: 0, lead_max: 144 },
  { storm_name: 'DORIAN', centre: 'ecmf', system: 'ECMWF-ENS',
    init_time: '2019-08-31T00:00:00', nominal_members: 51, tracked_members: 28,
    basin: 'NA', basin_source: 'AL', lead_min: 0, lead_max: 144 },
  { storm_name: 'DORIAN', centre: 'egrr', system: 'MOGREPS',
    init_time: '2019-08-30T12:00:00', nominal_members: 36, tracked_members: 23,
    basin: null, basin_source: 'AL', lead_min: 0, lead_max: 144 },
];

/** Which (storm, centre) each init legitimately belongs to. */
const OWNER = new Map(RUNS.map((r) => [r.init_time, `${r.storm_name}/${r.centre}`]));

const tracksFor = ({ storm, centre, init }) => ({
  storm_name: storm, centre, init_time: init,
  nominal_members: 51, tracked_members: 51,
  members: [{ member_id: 0, points: [{ lat: 15, lon: -50, lead: 0 }] }],
  best_track: [{ lat: 15.1, lon: -50.1 }],
});

beforeEach(() => {
  jest.clearAllMocks();
  fetchCyclones.mockResolvedValue({ runs: RUNS });
  fetchCycloneTracks.mockImplementation((a) => Promise.resolve(tracksFor(a)));
  fetchErrorByLead.mockResolvedValue({ rows: [], nominal_members: 51 });
  fetchStrikeProbability.mockResolvedValue({
    cells: [], nominal_members: 51, tracked_members: 51, peak: 0, radius_km: 120,
  });
});

/** Change a <select>, the way the other component tests in this repo do. */
const select = (label, value) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

/** Every (storm, centre, init) triple the component asked for, in order. */
const everyRequest = () => [
  ...fetchCycloneTracks.mock.calls,
  ...fetchErrorByLead.mock.calls,
  ...fetchStrikeProbability.mock.calls,
].map(([a]) => a);

describe('the initialisation is never stale', () => {
  it('asks for nothing whose init belongs to a different run', async () => {
    renderTab();

    await screen.findByDisplayValue('ALCIDE');
    await waitFor(() => expect(fetchCycloneTracks).toHaveBeenCalled());

    select(/storm/i, 'DORIAN');
    await waitFor(() =>
      expect(fetchCycloneTracks).toHaveBeenCalledWith(
        expect.objectContaining({ storm: 'DORIAN' })));

    // The assertion that would have caught the original defect. Before the
    // fix this failed on `{storm: 'DORIAN', init: '2018-11-09T00:00:00'}` —
    // ALCIDE's init, carried across the switch.
    for (const req of everyRequest()) {
      expect(OWNER.get(req.init)).toBe(`${req.storm}/${req.centre}`);
    }
  });

  it('makes exactly one round of requests per storm change', async () => {
    renderTab();
    await screen.findByDisplayValue('ALCIDE');
    await waitFor(() => expect(fetchCycloneTracks).toHaveBeenCalled());

    fetchCycloneTracks.mockClear();
    select(/storm/i, 'DORIAN');
    await waitFor(() => expect(fetchCycloneTracks).toHaveBeenCalled());

    // One, not two. The doomed request and its correction were two.
    await waitFor(() => expect(fetchCycloneTracks).toHaveBeenCalledTimes(1));
    expect(fetchCycloneTracks).toHaveBeenCalledWith(
      expect.objectContaining({ storm: 'DORIAN', init: '2019-08-31T00:00:00' }));
  });

  it('follows the centre as well as the storm', async () => {
    renderTab();
    await screen.findByDisplayValue('ALCIDE');

    select(/storm/i, 'DORIAN');
    await waitFor(() =>
      expect(fetchCycloneTracks).toHaveBeenCalledWith(
        expect.objectContaining({ storm: 'DORIAN', centre: 'ecmf' })));

    select(/centre/i, 'egrr');
    await waitFor(() =>
      expect(fetchCycloneTracks).toHaveBeenCalledWith(
        expect.objectContaining({ centre: 'egrr', init: '2019-08-30T12:00:00' })));

    for (const req of everyRequest()) {
      expect(OWNER.get(req.init)).toBe(`${req.storm}/${req.centre}`);
    }
  });

  it('keeps the select showing the init that was actually used', async () => {
    // The value is derived rather than stored, so the control must still
    // reflect it — a derived value that the <select> disagreed with would be
    // the same class of bug pointing the other way.
    renderTab();
    await screen.findByDisplayValue('ALCIDE');

    select(/storm/i, 'DORIAN');
    await waitFor(() => {
      const select = screen.getByLabelText(/initialisation/i);
      expect(select.value).toBe('2019-08-31T00:00:00');
    });
  });
});
