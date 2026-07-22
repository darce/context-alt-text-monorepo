/**
 * Dashboard keyboard-walk (E21-2).
 *
 * Bounded-Tab pattern from keyboard-walk.spec.ts: Tab from body, max 60 stops,
 * until the Library Coverage CTA is focused. Never programmatic .focus().
 */
import { expect, test, type Page } from '@playwright/test';

import { toWorkbench } from '../../../js/admin/navigation/appLinks';
import { requireBaseUrl } from '../fixtures/axe';
import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';

const DASHBOARD_SHELL_SELECTOR = '.acx-dashboard__shell';
const COVERAGE_CTA_NAME = /Fix missing descriptions/i;
const COVERAGE_CTA_HREF = toWorkbench({ status: 'missing' });

const openDashboard = async (baseURL: string, page: Page): Promise<void> => {
  await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-dashboard'));
  await expect(page).toHaveURL(/page=alt-context-dashboard/);
  await expect(page.locator(DASHBOARD_SHELL_SELECTOR)).toBeVisible();
  await expect(page.getByRole('heading', { name: /Alt Context Dashboard/i })).toBeVisible();
};

test('keyboard walk reaches Library Coverage CTA with real focus', async ({ page, baseURL }) => {
  await openDashboard(requireBaseUrl(baseURL), page);

  const coverageCta = page.getByRole('link', { name: COVERAGE_CTA_NAME });
  await expect(coverageCta).toBeVisible();
  await expect(coverageCta).toHaveAttribute('href', COVERAGE_CTA_HREF);

  // Real keyboard reachability: Tab from the top of the document until the
  // Coverage CTA receives focus (bounded so a broken tab order fails fast).
  await page.locator('body').press('Tab');
  const MAX_TAB_STEPS = 60;
  let reached = false;
  for (let step = 0; step < MAX_TAB_STEPS; step += 1) {
    if (await coverageCta.evaluate((el) => el === document.activeElement)) {
      reached = true;
      break;
    }
    await page.keyboard.press('Tab');
  }
  expect(reached, `Coverage CTA not keyboard-reachable within ${MAX_TAB_STEPS} tab stops`).toBe(true);
  await expect(coverageCta).toBeFocused();
});
