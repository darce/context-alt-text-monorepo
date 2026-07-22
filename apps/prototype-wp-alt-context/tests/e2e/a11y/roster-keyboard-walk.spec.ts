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

  // Real keyboard reachability: Tab from the top of the document until the
  // Add Person button receives focus (bounded so a broken tab order fails fast).
  await page.locator('body').press('Tab');
  const MAX_TAB_STEPS = 60;
  let reached = false;
  for (let step = 0; step < MAX_TAB_STEPS; step += 1) {
    if (await addPerson.evaluate((el) => el === document.activeElement)) {
      reached = true;
      break;
    }
    await page.keyboard.press('Tab');
  }
  expect(reached, `Add Person not keyboard-reachable within ${MAX_TAB_STEPS} tab stops`).toBe(true);
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

/**
 * E21-9 Slice 3: full member-fix keyboard loop when a cluster drawer is open.
 * Skips cleanly when the local environment has no openable cluster (no LocalWP fixtures).
 */
test('keyboard member-fix loop: Move to… → pick target → role=status (≥24px control)', async ({
  page,
  baseURL,
}) => {
  await openRoster(requireBaseUrl(baseURL), page);

  const clustersTab = page.getByRole('tab', { name: /Clusters/i });
  if ((await clustersTab.count()) === 0) {
    test.skip(true, 'Clusters tab not present in this build');
    return;
  }
  await clustersTab.click();

  const firstClusterCard = page.locator('.acx-cluster-card').first();
  if ((await firstClusterCard.count()) === 0) {
    test.skip(true, 'No clusters available for member-fix keyboard walk');
    return;
  }
  await firstClusterCard.click();

  const drawer = page.locator('.acx-cluster-drawer');
  await expect(drawer).toBeVisible();

  const moveButton = drawer.getByRole('button', { name: /Move to/i }).first();
  if ((await moveButton.count()) === 0) {
    test.skip(true, 'No face Move to… control in drawer (empty identities)');
    return;
  }

  await expect(moveButton).toBeVisible();
  const box = await moveButton.boundingBox();
  expect(box, 'Move to… must expose a layout box').not.toBeNull();
  expect(box!.width, 'Move to… min width ≥24 CSS px (A11Y-14)').toBeGreaterThanOrEqual(24);
  expect(box!.height, 'Move to… min height ≥24 CSS px (A11Y-14)').toBeGreaterThanOrEqual(24);

  if (await moveButton.isDisabled()) {
    await expect(moveButton).toHaveAttribute('title', /No other clusters available/i);
    test.skip(true, 'Only one cluster present — empty-target disabled-with-reason path covered by unit tests');
    return;
  }

  await moveButton.focus();
  await expect(moveButton).toBeFocused();
  await page.keyboard.press('Enter');

  const picker = drawer.getByRole('listbox', { name: /Choose a target cluster/i });
  await expect(picker).toBeVisible();
  const firstOption = picker.getByRole('option').first();
  await expect(firstOption).toBeFocused();
  await page.keyboard.press('Enter');

  const status = drawer.getByTestId('cluster-drawer-reassign-status');
  await expect(status).toHaveAttribute('role', 'status');
  await expect(status).toContainText(/Moving identity|Moved identity/i);
});
