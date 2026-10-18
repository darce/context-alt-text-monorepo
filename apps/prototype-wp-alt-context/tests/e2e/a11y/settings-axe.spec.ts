import { expect, test, type Page } from '@playwright/test';

import { assertNoBlockingViolations, requireBaseUrl, seededA11yEnabled } from '../fixtures/axe';
import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';

const SETTINGS_SHELL_SELECTOR = '.acx-settings';

const openSettings = async (baseURL: string, page: Page) => {
  await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-settings'));
  await expect(page).toHaveURL(/page=alt-context-settings/);
  await expect(page.locator(SETTINGS_SHELL_SELECTOR)).toBeVisible();
  await expect(page.getByRole('heading', { name: /Recognition API Settings/i })).toBeVisible();
  await expect(page.locator('#acx-settings-url')).toBeVisible();
  await expect(page.locator('#acx-settings-key')).toBeVisible();
};

test('settings empty state has no serious or critical axe violations', async ({ page, baseURL }) => {
  await openSettings(requireBaseUrl(baseURL), page);
  await expect(page.getByRole('button', { name: /Save Settings/i })).toBeVisible();
  await assertNoBlockingViolations(page, SETTINGS_SHELL_SELECTOR);
});

test('settings seeded state has no serious or critical axe violations', async ({ page, baseURL }) => {
  test.skip(!seededA11yEnabled(), 'Set ACX_E2E_SEEDED=1 to enable populated settings axe coverage.');

  await openSettings(requireBaseUrl(baseURL), page);
  await expect(page.getByRole('button', { name: /Save Settings/i })).toBeVisible();
  await assertNoBlockingViolations(page, SETTINGS_SHELL_SELECTOR);
});
