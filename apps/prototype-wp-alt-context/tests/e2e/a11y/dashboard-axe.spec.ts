import { expect, test, type Page } from '@playwright/test';

import { assertNoBlockingViolations, requireBaseUrl, seededA11yEnabled } from '../fixtures/axe';
import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';

const DASHBOARD_SHELL_SELECTOR = '.acx-dashboard__shell';

const openDashboard = async (baseURL: string, page: Page) => {
  await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-dashboard'));
  await expect(page).toHaveURL(/page=alt-context-dashboard/);
  const dashboardShell = page.locator(DASHBOARD_SHELL_SELECTOR);

  await expect(dashboardShell).toBeVisible();
  await expect(dashboardShell.getByRole('heading', { name: /Alt Context Dashboard/i })).toBeVisible();
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