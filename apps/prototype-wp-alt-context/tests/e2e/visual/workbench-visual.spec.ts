import { expect, test, type Page } from '@playwright/test';

import { requireBaseUrl, seededA11yEnabled } from '../fixtures/axe';
import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';
import { skipUnlessPopulatedWorkbench } from '../fixtures/seeded-state';
import { stabilizeWorkbench } from '../fixtures/visual';

const WORKBENCH_SHELL_SELECTOR = '.acx-workbench';

const openWorkbench = async (baseURL: string, page: Page) => {
  await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-workbench'));
  await expect(page).toHaveURL(/page=alt-context-workbench/);
  await expect(page.locator(WORKBENCH_SHELL_SELECTOR)).toBeVisible();
  await expect(page.getByRole('tablist', { name: /Workbench steps/i })).toBeVisible();
};

test('workbench empty state matches the visual baseline', async ({ page, baseURL }) => {
  await openWorkbench(requireBaseUrl(baseURL), page);
  await expect(page.getByRole('heading', { name: /Your analysis queue is empty/i })).toBeVisible();
  await stabilizeWorkbench(page, WORKBENCH_SHELL_SELECTOR);
  await expect(page.locator(WORKBENCH_SHELL_SELECTOR)).toHaveScreenshot('workbench-empty.png', {
    animations: 'disabled',
    timeout: 15_000,
  });
});

test('workbench seeded state matches the visual baseline', async ({ page, baseURL }) => {
  test.skip(!seededA11yEnabled(), 'Set ACX_E2E_SEEDED=1 to enable populated workbench visual coverage.');

  await openWorkbench(requireBaseUrl(baseURL), page);
  await skipUnlessPopulatedWorkbench(page);
  await stabilizeWorkbench(page, WORKBENCH_SHELL_SELECTOR);
  await expect(page.locator(WORKBENCH_SHELL_SELECTOR)).toHaveScreenshot('workbench-seeded.png', {
    animations: 'disabled',
    timeout: 15_000,
  });
});
