import { expect, test, type Page } from '@playwright/test';

import { assertNoBlockingViolations, requireBaseUrl, seededA11yEnabled } from '../fixtures/axe';
import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';

const ROSTER_SHELL_SELECTOR = '.acx-roster';

const openRoster = async (baseURL: string, page: Page) => {
  await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-roster'));
  await expect(page).toHaveURL(/page=alt-context-roster/);
  await expect(page.locator(ROSTER_SHELL_SELECTOR)).toBeVisible();
  await expect(page.getByRole('heading', { name: /Roster Management/i })).toBeVisible();
  await expect(page.getByTestId('roster-entries-section')).toBeVisible();
};

test('roster empty state has no serious or critical axe violations', async ({ page, baseURL }) => {
  await openRoster(requireBaseUrl(baseURL), page);
  await expect(page.getByText(/No people yet\. Add one manually or assign a cluster\./i)).toBeVisible();
  await assertNoBlockingViolations(page, ROSTER_SHELL_SELECTOR);
});

test('roster seeded state has no serious or critical axe violations', async ({ page, baseURL }) => {
  test.skip(!seededA11yEnabled(), 'Set ACX_E2E_SEEDED=1 to enable populated roster axe coverage.');

  await openRoster(requireBaseUrl(baseURL), page);
  await expect(page.locator('.acx-roster-entries__table tbody tr').first()).toBeVisible();
  await assertNoBlockingViolations(page, ROSTER_SHELL_SELECTOR);
});