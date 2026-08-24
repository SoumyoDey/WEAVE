/**
 * Shared helpers for driving the Leaflet map in e2e specs.
 *
 * The map is created imperatively in App.js (`L.map(...)`) and its instance is
 * held in a ref, so there is no handle to it from the page. Rather than export
 * one purely for tests, these helpers reconstruct the Web Mercator projection
 * from what is already in the DOM, and clicks are then issued at real screen
 * coordinates through real input events — which is what the selection code
 * listens for (`pointerdown`/`pointermove`/`pointerup`, not React synthetics).
 */

// Map init in App.js: L.map(el, { center: [37, -82.5], zoom: 6 }).
const FALLBACK_CENTER = { lat: 37, lon: -82.5 };
const FALLBACK_ZOOM = 6;

/**
 * Convert lat/lon to a viewport pixel coordinate.
 *
 * Preferred path derives the projection from a loaded basemap tile, which is
 * exact and survives any pan or zoom. If tiles are unavailable (offline, or the
 * CDN is blocked) it falls back to the map's known init centre/zoom — still
 * correct for a freshly loaded page, which is all these specs need. That
 * fallback is why the suite does not depend on network access to CartoDB.
 */
async function geoToPixel(page, lat, lon) {
  return await page.evaluate(({ lat, lon, fc, fz }) => {
    const project = (la, lo, zoom) => {
      const world = 256 * Math.pow(2, zoom);
      const p = la * Math.PI / 180;
      return {
        x: world * (lo + 180) / 360,
        y: world * (1 - Math.log(Math.tan(p) + 1 / Math.cos(p)) / Math.PI) / 2,
      };
    };

    const tile = [...document.querySelectorAll('img.leaflet-tile')].find(
      i => i.complete && i.naturalWidth > 0 && /\/(\d+)\/(\d+)\/(\d+)\.png/.test(i.src),
    );

    if (tile) {
      const [, z, tx, ty] = tile.src.match(/\/(\d+)\/(\d+)\/(\d+)\.png/).map(Number);
      const r = tile.getBoundingClientRect();
      const t = project(lat, lon, z);
      return { x: r.left + (t.x - tx * 256), y: r.top + (t.y - ty * 256), via: 'tile' };
    }

    const el = document.querySelector('.leaflet-container');
    if (!el) throw new Error('no .leaflet-container on the page');
    const r = el.getBoundingClientRect();
    const c = project(fc.lat, fc.lon, fz);
    const t = project(lat, lon, fz);
    return {
      x: r.left + r.width / 2 + (t.x - c.x),
      y: r.top + r.height / 2 + (t.y - c.y),
      via: 'center',
    };
  }, { lat, lon, fc: FALLBACK_CENTER, fz: FALLBACK_ZOOM });
}

/** Wait until Leaflet has built the map and (best effort) drawn some tiles. */
async function waitForMap(page) {
  await page.waitForSelector('.leaflet-container', { timeout: 60_000 });
  await page.waitForFunction(
    () => document.querySelectorAll('.leaflet-tile').length > 0,
    null, { timeout: 60_000 },
  ).catch(() => { /* offline: the fallback projection covers us */ });
  // Leaflet calls invalidateSize on a timer just after init.
  await page.waitForTimeout(1200);
}

/** Click a geographic point on the map. */
async function clickMapPoint(page, lat, lon) {
  const p = await geoToPixel(page, lat, lon);
  await page.mouse.click(p.x, p.y);
  await page.waitForTimeout(500);
  return p;
}

/**
 * Drag a rectangle selection across the given bounds.
 * Intermediate moves are required — a single jump produces no pointermove and
 * the preview rectangle (and therefore the selection) never forms.
 */
async function drawRectangle(page, { minLat, maxLat, minLon, maxLon }, { steps = 12 } = {}) {
  await page.getByRole('button', { name: 'Rectangle selection' }).click();
  await page.waitForTimeout(300);

  const a = await geoToPixel(page, maxLat, minLon);
  const b = await geoToPixel(page, minLat, maxLon);

  await page.mouse.move(a.x, a.y);
  await page.mouse.down();
  for (let i = 1; i <= steps; i++) {
    await page.mouse.move(a.x + (b.x - a.x) * i / steps, a.y + (b.y - a.y) * i / steps);
  }
  await page.mouse.up();
  await page.waitForTimeout(700);
  return { a, b };
}

/**
 * Read the point the app currently considers selected.
 *
 * `clickedPoint` lives in App state with no test hook, but the Analysis tab
 * header renders it verbatim, and does so straight from state — no API call —
 * so this works with the Flask API down. Returns e.g. "36.014°N, 75.520°W",
 * or null when no point has been chosen. Leaves the Visualization tab active.
 */
async function readSelectedPoint(page) {
  await page.getByRole('button', { name: 'Analysis' }).click();
  await page.waitForTimeout(500);
  const text = await page.evaluate(() => {
    const m = document.body.innerText.match(/Point:\s*([\d.]+°[NS],\s*[\d.]+°[EW])/);
    return m ? m[1] : null;
  });
  await page.getByRole('button', { name: 'Visualization' }).click();
  await page.waitForTimeout(400);
  return text;
}

/** True when a region selection exists (the Clear button only renders then). */
async function hasRegion(page) {
  return (await page.getByRole('button', { name: 'Clear selection' }).count()) > 0;
}

module.exports = {
  geoToPixel,
  waitForMap,
  clickMapPoint,
  drawRectangle,
  readSelectedPoint,
  hasRegion,
};
