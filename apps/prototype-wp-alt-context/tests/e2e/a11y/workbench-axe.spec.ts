import { expect, test, type Page } from '@playwright/test';

import { assertNoBlockingViolations, requireBaseUrl, seededA11yEnabled } from '../fixtures/axe';
import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';

const WORKBENCH_SHELL_SELECTOR = '.acx-workbench';

const openWorkbench = async (baseURL: string, page: Page) => {
  await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-workbench'));
  await expect(page).toHaveURL(/page=alt-context-workbench/);
  await expect(page.locator(WORKBENCH_SHELL_SELECTOR)).toBeVisible();
  await expect(page.getByRole('tablist', { name: /Workbench steps/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Scan Media Queue/i })).toBeVisible();
};

test('workbench empty state has no serious or critical axe violations', async ({ page, baseURL }) => {
  await openWorkbench(requireBaseUrl(baseURL), page);
  await expect(page.getByRole('heading', { name: /Your analysis queue is empty/i })).toBeVisible();
  await assertNoBlockingViolations(page, WORKBENCH_SHELL_SELECTOR);
});

test('workbench seeded state has no serious or critical axe violations', async ({ page, baseURL }) => {
  test.skip(!seededA11yEnabled(), 'Set ACX_E2E_SEEDED=1 to enable populated workbench axe coverage.');

  await openWorkbench(requireBaseUrl(baseURL), page);
  await expect(page.locator('.acx-media-selection__media-title').first()).toBeVisible();
  await assertNoBlockingViolations(page, WORKBENCH_SHELL_SELECTOR);
});