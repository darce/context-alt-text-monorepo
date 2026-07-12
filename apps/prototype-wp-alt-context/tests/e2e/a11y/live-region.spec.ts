/**
 * Live-region harness for the SyncPresentation status strip (E21-1 seed).
 *
 * Pattern for later E21 tasks:
 * - Assert role="status" (or aria-live) on the real rendered strip.
 * - Assert announcement text from DOM textContent — never by scanning source files.
 * - When a transition is triggered (scan/describe/sync), re-read the strip and
 *   assert the status code and plain-language headline changed.
 *
 * Empty-queue environments still prove the live-region contract: the strip settles
 * from loading (absent) into a role=status node with a non-empty headline.
 */
import { expect, test, type Page } from '@playwright/test';

import { requireBaseUrl } from '../fixtures/axe';
import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';
import { skipUnlessPopulatedWorkbench } from '../fixtures/seeded-state';

const WORKBENCH_SHELL_SELECTOR = '.acx-workbench';
const STATUS_STRIP_SELECTOR = '[data-testid="acx-sync-status-strip"]';

const BANNED = [
  /topology/i,
  /replay/i,
  /projection/i,
  /dead-letter/i,
  /curation acknowledgement/i,
  /Source version/i,
  /projected instances/i,
  /Curriculum/i,
];

const openWorkbench = async (baseURL: string, page: Page): Promise<void> => {
  await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-workbench'));
  await expect(page).toHaveURL(/page=alt-context-workbench/);
  await expect(page.locator(WORKBENCH_SHELL_SELECTOR)).toBeVisible();
};

test('status strip is a polite live region with plain-language copy', async ({ page, baseURL }) => {
  await openWorkbench(requireBaseUrl(baseURL), page);

  const strip = page.locator(STATUS_STRIP_SELECTOR);
  await expect(strip).toBeVisible({ timeout: 15_000 });

  await expect(strip).toHaveAttribute('role', 'status');
  await expect(strip).toHaveAttribute('aria-live', 'polite');
  await expect(strip).toHaveAttribute('data-sync-status', /.+/);

  const headline = strip.locator('.acx-sync-status__label');
  await expect(headline).toBeVisible();
  const text = (await headline.textContent()) ?? '';
  expect(text.trim().length).toBeGreaterThan(0);

  for (const pattern of BANNED) {
    expect(text).not.toMatch(pattern);
  }
});

test('status strip announces after workbench settles (scan surface)', async ({ page, baseURL }) => {
  await openWorkbench(requireBaseUrl(baseURL), page);

  // Capture the first settled strip state from the real DOM.
  const strip = page.locator(STATUS_STRIP_SELECTOR);
  await expect(strip).toBeVisible({ timeout: 15_000 });
  const initialStatus = await strip.getAttribute('data-sync-status');
  const initialHeadline = ((await strip.locator('.acx-sync-status__label').textContent()) ?? '').trim();

  expect(initialStatus).toBeTruthy();
  expect(initialHeadline.length).toBeGreaterThan(0);

  // Switch to Confirm and back to Scan — strip must remain a live region and keep
  // a concrete status code (sync health is independent of tab, so equality is OK).
  await page.getByRole('tab', { name: /Confirm & Publish/i }).click();
  await expect(page.getByRole('heading', { name: /Confirm & Publish/i })).toBeVisible();
  await expect(strip).toBeVisible();
  await expect(strip).toHaveAttribute('role', 'status');

  await page.getByRole('tab', { name: /Scan Media Queue/i }).click();
  await expect(page.getByRole('heading', { name: /Scan Media Queue/i })).toBeVisible();
  await expect(strip).toBeVisible();
  await expect(strip).toHaveAttribute('data-sync-status', /.+/);

  const settledHeadline = ((await strip.locator('.acx-sync-status__label').textContent()) ?? '').trim();
  expect(settledHeadline.length).toBeGreaterThan(0);
  for (const pattern of BANNED) {
    expect(settledHeadline).not.toMatch(pattern);
  }
});

test('seeded workbench status strip stays jargon-free after scan chrome interaction', async ({
  page,
  baseURL,
}) => {
  test.skip(
    process.env.ACX_E2E_SEEDED !== '1' && process.env.ACX_E2E_SEEDED !== 'true',
    'Set ACX_E2E_SEEDED=1 to enable populated workbench live-region coverage.',
  );

  await openWorkbench(requireBaseUrl(baseURL), page);
  await skipUnlessPopulatedWorkbench(page);

  const strip = page.locator(STATUS_STRIP_SELECTOR);
  await expect(strip).toBeVisible({ timeout: 15_000 });

  // Prefer a real primary action when present (Analyze / scan CTA).
  const analyzeButton = page.getByRole('button', { name: /Analyze|Scan|Start/i }).first();
  if (await analyzeButton.isVisible().catch(() => false)) {
    await analyzeButton.focus();
    await expect(analyzeButton).toBeFocused();
  }

  const text = ((await strip.textContent()) ?? '').trim();
  expect(text.length).toBeGreaterThan(0);
  for (const pattern of BANNED) {
    expect(text).not.toMatch(pattern);
  }
  await expect(strip).toHaveAttribute('role', 'status');
});
