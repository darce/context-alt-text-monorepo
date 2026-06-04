import { expect, test, type Page } from '@playwright/test';

import { assertNoBlockingViolations, requireBaseUrl, seededA11yEnabled } from '../fixtures/axe';
import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';

const DASHBOARD_SHELL_SELECTOR = '.acx-dashboard';

const openDashboard = async (baseURL: string, page: Page) => {
  await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-dashboard'));
  await expect(page).toHaveURL(/page=alt-context-dashboard/);
  await expect(page.locator(DASHBOARD_SHELL_SELECTOR)).toBeVisible();
  await expect(page.getByRole('heading', { name: /Identity Recognition/i })).toBeVisible();
};

test('dashboard empty state has no serious or critical axe violations', async ({ page, baseURL }) => {
  await openDashboard(requireBaseUrl(baseURL), page);
  await assertNoBlockingViolations(page, DASHBOARD_SHELL_SELECTOR);
});

test('dashboard seeded state has no serious or critical axe violations', async ({ page, baseURL }) => {
  test.skip(!seededA11yEnabled(), 'Set ACX_E2E_SEEDED=1 to enable populated dashboard axe coverage.');

  await openDashboard(requireBaseUrl(baseURL), page);
  await expect(page.locator('.acx-dashboard__activity-item').first()).toBeVisible();
  await assertNoBlockingViolations(page, DASHBOARD_SHELL_SELECTOR);
});