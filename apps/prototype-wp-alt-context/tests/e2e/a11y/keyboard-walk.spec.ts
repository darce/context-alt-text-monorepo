/**
 * Shared keyboard-walk harness (E21-1 seed; E21-3 drawer migration).
 *
 * Pattern for later E21 tasks:
 * 1. Open the target admin route.
 * 2. Locate the primary focusable chrome (tabs, primary actions).
 * 3. Drive focus with page.keyboard.press() — never click-only / programmatic .focus().
 * 4. Assert focus with toBeFocused() on real DOM nodes.
 *
 * Covers the workbench scan surface + Advanced: jobs & recovery disclosure:
 * Tab to the advanced trigger → Enter opens → focus inside → Esc restores.
 */
import { expect, test, type Page } from '@playwright/test';

import { requireBaseUrl } from '../fixtures/axe';
import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';

const WORKBENCH_SHELL_SELECTOR = '.acx-workbench';
const STATUS_STRIP_SELECTOR = '[data-testid="acx-sync-status-strip"]';
const ADVANCED_TRIGGER_NAME = /Advanced: jobs & recovery/i;
const ADVANCED_REGION_NAME = /Advanced: jobs & recovery/i;

const openWorkbench = async (baseURL: string, page: Page): Promise<void> => {
  await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-workbench'));
  await expect(page).toHaveURL(/page=alt-context-workbench/);
  await expect(page.locator(WORKBENCH_SHELL_SELECTOR)).toBeVisible();
  await expect(page.getByRole('tablist', { name: /Workbench steps/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Scan Media Queue/i })).toBeVisible();
};

const tabUntilFocused = async (page: Page, target: ReturnType<Page['getByRole']>, maxSteps: number): Promise<void> => {
  await page.locator('body').press('Tab');
  let reached = false;
  for (let step = 0; step < maxSteps; step += 1) {
    if (await target.evaluate((el) => el === document.activeElement)) {
      reached = true;
      break;
    }
    await page.keyboard.press('Tab');
  }
  expect(reached, `Target not keyboard-reachable within ${maxSteps} tab stops`).toBe(true);
  await expect(target).toBeFocused();
};

test('keyboard walk reaches scan tab and advanced drawer with real focus', async ({ page, baseURL }) => {
  await openWorkbench(requireBaseUrl(baseURL), page);

  const scanTab = page.getByRole('tab', { name: /Scan Media Queue/i });
  const advancedTrigger = page.getByRole('button', { name: ADVANCED_TRIGGER_NAME });

  // Confirm tab is gone — single scan step + advanced disclosure.
  await expect(page.getByRole('tab', { name: /Confirm & Publish/i })).toHaveCount(0);

  const MAX_TAB_STEPS = 60;
  await tabUntilFocused(page, scanTab, MAX_TAB_STEPS);
  await expect(scanTab).toHaveAttribute('aria-selected', 'true');

  // Bounded Tab walk to the Advanced trigger — never programmatic .focus().
  await tabUntilFocused(page, advancedTrigger, MAX_TAB_STEPS);
  await expect(advancedTrigger).toHaveAttribute('aria-expanded', 'false');

  await page.keyboard.press('Enter');
  await expect(advancedTrigger).toHaveAttribute('aria-expanded', 'true');

  const advancedRegion = page.getByRole('region', { name: ADVANCED_REGION_NAME });
  await expect(advancedRegion).toBeVisible();
  await expect
    .poll(async () => advancedRegion.evaluate((el) => el.contains(document.activeElement)))
    .toBe(true);

  await page.keyboard.press('Escape');
  await expect(advancedTrigger).toHaveAttribute('aria-expanded', 'false');
  await expect(advancedRegion).toHaveCount(0);
  await expect(advancedTrigger).toBeFocused();
});

test('status strip remains present while advanced drawer is open', async ({ page, baseURL }) => {
  await openWorkbench(requireBaseUrl(baseURL), page);

  const strip = page.locator(STATUS_STRIP_SELECTOR);
  await expect(strip).toBeVisible({ timeout: 15_000 });
  await expect(strip).toHaveAttribute('role', 'status');

  const advancedTrigger = page.getByRole('button', { name: ADVANCED_TRIGGER_NAME });
  const MAX_TAB_STEPS = 60;
  await tabUntilFocused(page, advancedTrigger, MAX_TAB_STEPS);
  await page.keyboard.press('Enter');
  await expect(advancedTrigger).toHaveAttribute('aria-expanded', 'true');
  await expect(strip).toBeVisible();
  await expect(strip).toHaveAttribute('data-sync-status', /.+/);
});
