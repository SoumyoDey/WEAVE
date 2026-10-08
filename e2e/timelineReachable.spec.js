const { test, expect } = require('@playwright/test');
const { waitForMap } = require('./mapHelpers');

/**
 * The timeline stays operable while the Controls drawer is open.
 *
 * The defect (`NEXT_STEPS.md` §65): the click-away backdrop was `inset: 0` at
 * `z-index: 999` over a timeline bar at 900, so opening the drawer put a
 * **transparent** sheet across the whole bar. Every click on the scrubber and
 * on Play/Prev/Next went to the backdrop, which closed the drawer and did
 * nothing else. The drawer itself, `height: 100%`, additionally covered the
 * transport buttons with an opaque panel.
 *
 * It read as "the buttons do nothing", and the half the drawer did not visibly
 * cover is what makes it a defect rather than a layout choice — a user can see
 * the scrubber perfectly well at x=800 and cannot use it.
 *
 * **These assertions have to be real clicks.** Playwright's `click()` performs
 * a hit test and refuses an element something else is on top of, which is
 * exactly the condition under test; `dispatchEvent` or `.click()` in page
 * script would pass against the broken build, because the DOM node was never
 * the problem. jsdom cannot host this test at all — it has no layout, so
 * nothing is ever on top of anything.
 */

const openDrawer = async (page) => {
  const toggle = page.getByRole('button', { name: 'Controls' });
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  return toggle;
};

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('weave_onboarded', '1'); } catch { /* private mode */ }
  });
  await page.goto('/');
  await waitForMap(page);
});

test('the transport buttons work while the drawer is open', async ({ page }) => {
  const scrubber = page.locator('input[type="range"]');
  const before = await scrubber.inputValue();

  const toggle = await openDrawer(page);
  await page.getByRole('button', { name: 'Next lead time' }).click();

  await expect(scrubber).not.toHaveValue(before);
  // Operating the timeline is not "clicking away": the bar is a control, not
  // the map, so the drawer it sits beside stays open.
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
});

test('the scrubber is reachable along its whole width while the drawer is open', async ({ page }) => {
  const scrubber = page.locator('input[type="range"]');
  await openDrawer(page);

  // The far right of the bar was never covered by the visible drawer — only by
  // the invisible backdrop — so this is the half of the defect a screenshot
  // cannot show.
  const box = await scrubber.boundingBox();
  await scrubber.click({ position: { x: Math.round(box.width * 0.85), y: Math.round(box.height / 2) } });

  expect(Number(await scrubber.inputValue())).toBeGreaterThan(0);
});

test('the drawer still closes when the map itself is clicked', async ({ page }) => {
  const toggle = await openDrawer(page);

  // Guards the other direction: the backdrop was narrowed, not removed.
  //
  // `page.mouse.click` rather than a locator click, and the difference is the
  // point of the test. Over the map the backdrop is *supposed* to be on top,
  // so asking Playwright to click `.leaflet-container` fails its actionability
  // check — against the fixed build and the broken one alike. What a user does
  // here is click a position and let whatever is on top receive it, which is
  // what this does.
  await page.mouse.click(500, 200);
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
});

test('the timeline survives the narrow breakpoint, where the bar is taller', async ({ page }) => {
  // Two stacked rows instead of one, which is why the height is measured
  // rather than named: 83px here against 69px at desktop width.
  await page.setViewportSize({ width: 420, height: 800 });
  await waitForMap(page);

  const scrubber = page.locator('input[type="range"]');
  const before = await scrubber.inputValue();

  await openDrawer(page);
  await page.getByRole('button', { name: 'Next lead time' }).click();

  await expect(scrubber).not.toHaveValue(before);
});
