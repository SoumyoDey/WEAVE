/**
 * A Leaflet stub for tests that are not measuring the map.
 *
 * A real Leaflet in jsdom is actively in the way: `App.js` builds the map
 * inside a `setTimeout`, so it lands after a test has unmounted and throws
 * "Map container not found" **asynchronously — attributed to whichever test
 * happens to be running**. That is a failure that moves when you add a test,
 * which is the worst kind to debug.
 *
 * Use it as `jest.mock('leaflet', () => require('./testing/leafletStub'))`.
 * Anything that asserts on the map belongs in a file that does not mock it.
 *
 * **Plain functions, not `jest.fn`.** CRA's jest config sets `resetMocks:
 * true`, which clears every mock's implementation before each test —
 * including ones created inside a module factory, which runs once. So
 * `jest.fn(() => x)` returns `x` in the first test and `undefined` in every
 * one after, and the symptom is a TypeError deep in `App.js` rather than
 * anything pointing at the stub. Cost an hour the first time.
 */
module.exports = (() => {
  // **Plain functions, not `jest.fn`.** CRA's jest config sets
  // `resetMocks: true`, which clears every mock's implementation before each
  // test — including ones created inside a module factory, which runs once. So
  // `jest.fn(() => x)` here returns `x` in the first test and `undefined` in
  // every one after, and the symptom is a TypeError deep in `App.js` rather
  // than anything pointing at the mock. Cost an hour the first time.
  const noop = () => {};
  const chainable = () => {
    const o = {
      addTo: () => o, remove: noop, setStyle: () => o, setLatLng: () => o,
      bindTooltip: () => o, openTooltip: () => o, closeTooltip: () => o,
      clearLayers: () => o, addLayer: () => o, removeLayer: () => o,
      setOpacity: () => o, bringToFront: () => o,
      getContainer: () => ({ style: {}, appendChild: noop }),
    };
    return o;
  };
  const map = {
    setView() { return this; },
    fitBounds: noop, remove: noop, invalidateSize: noop,
    addLayer: noop, removeLayer: noop, on: noop, off: noop,
    getZoom: () => 6,
    getCenter: () => ({ lat: 37, lng: -82.5 }),
    getBounds: () => ({ getNorth: () => 40, getSouth: () => 34,
                        getEast: () => -78, getWest: () => -87 }),
    latLngToContainerPoint: () => ({ x: 0, y: 0 }),
    containerPointToLatLng: () => ({ lat: 37, lng: -82.5 }),
    getPanes: () => ({ overlayPane: { appendChild: noop } }),
    createPane: () => ({ style: {} }),
    getPane: () => ({ style: {}, appendChild: noop }),
    dragging: { enable: noop, disable: noop },
    getContainer: () => ({ style: {}, appendChild: noop }),
  };
  return {
    __esModule: true,
    default: {
      map: () => map,
      tileLayer: chainable,
      polyline: chainable,
      polygon: chainable,
      rectangle: chainable,
      circleMarker: chainable,
      layerGroup: chainable,
      point: (x, y) => ({ x, y }),
      latLngBounds: () => {
        const b = { isValid: () => true, extend: noop, pad: () => b };
        return b;
      },
      control: { zoom: () => ({ addTo: () => ({ getContainer: () => ({ style: {} }) }) }) },
    },
  };
})();
