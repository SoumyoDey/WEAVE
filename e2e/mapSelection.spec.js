const { test, expect } = require('@playwright/test');
const {
  waitForMap, clickMapPoint, drawRectangle, readSelectedPoint, hasRegion,
} = require('./mapHelpers');

/**
 * Point-vs-region selection on the map.
 *
 * The regression these exist for: finishing a rectangle drag used to move the
 * user's clicked point to the box's far corner. `setSelectionMode(null)` runs
 * in the native `pointerup` handler, React flushes it to `selectionModeRef`
 * at the microtask checkpoint when that handler returns, and only *then* does
 * the browser dispatch the `click` for the same mouseup — so the
 * `if (selectionModeRef.current) return` guard in App.js was already open and
 * the synthesised click fell through to `setClickedPoint`.
 *
 * It is invisible to the other two layers: jsdom has no layout, so Leaflet
 * cannot produce real coordinates there, and nothing about it reaches Python.
 * It surfaced as an Analysis tab reporting scores for a point the user never
 * chose, which reads as a data bug rather than an input one — hence the
 * assertions below are on the coordinates the app *reports*, not on internals.
 */

const COAST = { lat: 36.0, lon: -75.5 };          // used throughout the project's docs
const BOX = { minLat: 35, maxLat: 37, minLon: -77, maxLon: -74 };
const BOX_FAR_CORNER = /35\.\d+°N,\s*74\.\d+°W/;  // what the bug used to leave behind

test.beforeEach(async ({ page }) => {
  // Suppress the first-run tour; it covers the map on a fresh profile.
  await page.addInitScript(() => {
    try { localStorage.setItem('weave_onboarded', '1'); } catch { /* private mode */ }
  });
  await page.goto('/');
  await waitForMap(page);
});

test('clicking the map selects that point', async ({ page }) => {
  await clickMapPoint(page, COAST.lat, COAST.lon);
  expect(await readSelectedPoint(page)).toMatch(/36\.\d+°N,\s*75\.\d+°W/);
});

test('rectangle drag creates a region with the drawn bounds', async ({ page }) => {
  await drawRectangle(page, BOX);
  expect(await hasRegion(page)).toBe(true);

  // The Comparison tab prints the bounds it will actually query.
  await page.getByRole('button', { name: 'Comparison' }).click();
  await page.getByRole('button', { name: 'Region', exact: true }).click();
  await expect(page.getByText(/Rectangle\s*35\.0°–37\.0°N,\s*-77\.0°–-74\.0°E/)).toBeVisible();
});

test('rectangle drag does not move an already-selected point', async ({ page }) => {
  await clickMapPoint(page, COAST.lat, COAST.lon);
  const before = await readSelectedPoint(page);
  expect(before).toMatch(/36\.\d+°N,\s*75\.\d+°W/);

  await drawRectangle(page, BOX);

  const after = await readSelectedPoint(page);
  expect(after).toBe(before);
  expect(after).not.toMatch(BOX_FAR_CORNER);
  // The drag still has to do its actual job.
  expect(await hasRegion(page)).toBe(true);
});

test('a genuine click after a rectangle drag still selects a point', async ({ page }) => {
  // Guards the fix's failure mode: suppressing one click too many would leave
  // the map unresponsive to the user's very next click.
  await clickMapPoint(page, COAST.lat, COAST.lon);
  await drawRectangle(page, BOX);

  await clickMapPoint(page, 38.5, -76.5);
  expect(await readSelectedPoint(page)).toMatch(/38\.\d+°N,\s*76\.\d+°W/);
});

test('repeated rectangle drags leave the point alone', async ({ page }) => {
  await clickMapPoint(page, COAST.lat, COAST.lon);
  const before = await readSelectedPoint(page);

  await drawRectangle(page, BOX);
  await drawRectangle(page, { minLat: 33.5, maxLat: 34.5, minLon: -79, maxLon: -77.5 });

  expect(await readSelectedPoint(page)).toBe(before);
});

test('a zero-area tap in rectangle mode selects neither region nor point', async ({ page }) => {
  await clickMapPoint(page, COAST.lat, COAST.lon);
  const before = await readSelectedPoint(page);

  // A tap is a degenerate drag. App.js bails out before creating a sliver
  // region, and leaves selectionMode on — so the click guard still applies and
  // the suppression must NOT have been armed.
  await drawRectangle(page, {
    minLat: COAST.lat, maxLat: COAST.lat, minLon: COAST.lon, maxLon: COAST.lon,
  }, { steps: 1 });

  expect(await hasRegion(page)).toBe(false);
  expect(await readSelectedPoint(page)).toBe(before);
});
