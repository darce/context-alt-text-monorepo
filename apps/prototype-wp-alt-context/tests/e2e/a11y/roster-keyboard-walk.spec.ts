import { expect, test, type Page } from '@playwright/test';

import { requireBaseUrl } from '../fixtures/axe';
import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';

const ROSTER_SHELL_SELECTOR = '.acx-roster';

const openRoster = async (baseURL: string, page: Page) => {
  await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-roster'));
  await expect(page).toHaveURL(/page=alt-context-roster/);
  await expect(page.locator(ROSTER_SHELL_SELECTOR)).toBeVisible();
  await expect(page.getByRole('heading', { name: /Roster Management/i })).toBeVisible();
  await expect(page.getByTestId('roster-entries-section')).toBeVisible();
};

test('keyboard path from roster load reaches Add Person and opens the form', async ({ page, baseURL }) => {
  await openRoster(requireBaseUrl(baseURL), page);

  const addPerson = page.getByRole('button', { name: /Add Person/i }).first();
  await expect(addPerson).toBeVisible();

  await addPerson.focus();
  await expect(addPerson).toBeFocused();

  await page.keyboard.press('Enter');
  await expect(page.getByPlaceholder('Full Name')).toBeVisible();
  await expect(page.getByPlaceholder('Full Name')).toBeFocused();
});

test('roster empty state is announced via live region', async ({ page, baseURL }) => {
  await openRoster(requireBaseUrl(baseURL), page);

  const zeroState = page.getByTestId('roster-zero-state');
  await expect(zeroState).toBeVisible();
  await expect(zeroState).toHaveAttribute('role', 'status');
  await expect(zeroState).toHaveAttribute('aria-live', 'polite');
  await expect(zeroState).toContainText(/No people yet/i);
  await expect(zeroState).toContainText(/run a scan/i);
  await expect(page.getByRole('button', { name: /Add Person/i }).first()).toBeVisible();
});
