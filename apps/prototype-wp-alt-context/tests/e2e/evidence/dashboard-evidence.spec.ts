import { expect, test } from '@playwright/test';

import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';

const DASHBOARD_SHELL_SELECTOR = '.acx-dashboard__shell';

test('captures dashboard evidence for the LocalWP operator bundle', async ({ page, baseURL }, testInfo) => {
  if (!baseURL) {
    throw new Error('Expected Playwright baseURL to be configured for LocalWP admin.');
  }

  await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-dashboard'));
  await expect(page).toHaveURL(/page=alt-context-dashboard/);

  const dashboardShell = page.locator(DASHBOARD_SHELL_SELECTOR);

  await expect(dashboardShell).toBeVisible();
  await expect(dashboardShell.getByRole('heading', { name: /Alt Context Dashboard/i })).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath('dashboard-evidence.png'),
    fullPage: true,
  });
});
