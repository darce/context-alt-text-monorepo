/**
 * Shared keyboard-walk harness (E21-1 seed).
 *
 * Pattern for later E21 tasks:
 * 1. Open the target admin route.
 * 2. Locate the primary focusable chrome (tabs, primary actions).
 * 3. Drive focus with page.keyboard.press() — never click-only.
 * 4. Assert focus with toBeFocused() on real DOM nodes.
 *
 * This seed covers the workbench scan/status flow: tablist → Scan/Confirm tabs
 * → status strip remains reachable in the accessibility tree.
 */
import { expect, test, type Page } from '@playwright/test';

import { requireBaseUrl } from '../fixtures/axe';
import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';

const WORKBENCH_SHELL_SELECTOR = '.acx-workbench';
const STATUS_STRIP_SELECTOR = '[data-testid="acx-sync-status-strip"]';

const openWorkbench = async (baseURL: string, page: Page): Promise<void> => {
  await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-workbench'));
  await expect(page).toHaveURL(/page=alt-context-workbench/);
  await expect(page.locator(WORKBENCH_SHELL_SELECTOR)).toBeVisible();
  await expect(page.getByRole('tablist', { name: /Workbench steps/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Scan Media Queue/i })).toBeVisible();
};

test('keyboard walk reaches workbench scan and confirm tabs with real focus', async ({ page, baseURL }) => {
  await openWorkbench(requireBaseUrl(baseURL), page);

  const scanTab = page.getByRole('tab', { name: /Scan Media Queue/i });
  const confirmTab = page.getByRole('tab', { name: /Confirm & Publish/i });

  await scanTab.focus();
  await expect(scanTab).toBeFocused();
  await expect(scanTab).toHaveAttribute('aria-selected', 'true');

  // Arrow keys move between tabs (Radix Tabs keyboard contract).
  await page.keyboard.press('ArrowRight');
  await expect(confirmTab).toBeFocused();
  await expect(confirmTab).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('heading', { name: /Confirm & Publish/i })).toBeVisible();

  await page.keyboard.press('ArrowLeft');
  await expect(scanTab).toBeFocused();
  await expect(scanTab).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('heading', { name: /Scan Media Queue/i })).toBeVisible();

  // Tab forward into the active panel; some focusable control must receive focus.
  await page.keyboard.press('Tab');
  const focused = page.locator(':focus');
  await expect(focused).toBeVisible();
  // Focus left the tablist into page chrome (panel or status-adjacent control).
  await expect(scanTab).not.toBeFocused();
});

test('status strip remains present during keyboard tab switches', async ({ page, baseURL }) => {
  await openWorkbench(requireBaseUrl(baseURL), page);

  const strip = page.locator(STATUS_STRIP_SELECTOR);
  // Strip may be absent while sync status is still loading; wait for settled state.
  await expect(strip).toBeVisible({ timeout: 15_000 });
  await expect(strip).toHaveAttribute('role', 'status');

  const confirmTab = page.getByRole('tab', { name: /Confirm & Publish/i });
  await confirmTab.focus();
  await page.keyboard.press('Enter');
  await expect(confirmTab).toHaveAttribute('aria-selected', 'true');
  await expect(strip).toBeVisible();
  await expect(strip).toHaveAttribute('data-sync-status', /.+/);
});
