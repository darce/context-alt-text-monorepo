import { expect, test } from '@playwright/test';

import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';

test('loads the dashboard route and captures a proof screenshot', async ({ page, baseURL }, testInfo) => {
  if (!baseURL) {
    throw new Error('Expected Playwright baseURL to be configured for LocalWP admin.');
  }

  await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-dashboard'));
  await expect(page).toHaveURL(/page=alt-context-dashboard/);

  const identityRecognitionHeading = page.getByRole('heading', { name: /Identity Recognition/i });

  await expect(identityRecognitionHeading).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath('dashboard-loads.png'),
    fullPage: true,
  });
});