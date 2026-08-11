/**
 * E21-10 Slice 4 — canonical deep-link coverage via the appLinks contract.
 *
 * Specs navigate with getAcxAdminHashUrl + contract builders (no raw legacy params).
 * tab=confirm degrade proof: lands scan without advanced=open and without tab rewrite.
 */
import { expect, test, type Page } from '@playwright/test';

import { toDescriptionHistoryRun, toWorkbench } from '../../../js/admin/navigation/appLinks';
import { getAcxAdminHashUrl, getAcxAdminRouteUrlWithParams } from '../fixtures/acx-routes';
import { requireBaseUrl } from '../fixtures/axe';

const WORKBENCH_SHELL = '.acx-workbench';
/** Apply-view section chrome (DescribeRunApplyView) — discriminating vs list. */
const RUN_APPLY_SECTION = 'section.acx-run-apply';
/** List chrome present only on the full history list surface. */
const HISTORY_LIST = '.acx-history__list';

const openHash = async (page: Page, baseURL: string, slug: Parameters<typeof getAcxAdminHashUrl>[1], hashHref: string) => {
  const url = getAcxAdminHashUrl(baseURL, slug, hashHref);
  await page.goto(url);
};

test('workbench status=missing deep-link via contract builder lands filter active', async ({
  page,
  baseURL,
}) => {
  const base = requireBaseUrl(baseURL);
  await openHash(page, base, 'alt-context-workbench', toWorkbench({ status: 'missing' }));
  await expect(page).toHaveURL(/page=alt-context-workbench/);
  await expect(page.locator(WORKBENCH_SHELL)).toBeVisible();
  await expect(page.getByRole('heading', { name: /Scan Media Queue/i })).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Status' })).toContainText('Missing alt text');
});

test('description-history run= deep-link via contract builder lands apply surface', async ({
  page,
  baseURL,
}) => {
  const base = requireBaseUrl(baseURL);
  // Synthetic run id — surface must still switch into the apply view chrome.
  await openHash(page, base, 'alt-context-description-history', toDescriptionHistoryRun('e21-10-deep-link'));
  await expect(page).toHaveURL(/page=alt-context-description-history/);
  await expect(page).toHaveURL(/#\/description-history\?run=/);
  // Discriminating apply-view chrome (not the history list).
  await expect(page.getByRole('heading', { name: /Apply generated descriptions/i })).toBeVisible();
  await expect(page.locator(RUN_APPLY_SECTION)).toBeVisible();
  await expect(page.getByRole('link', { name: /Back to full history/i })).toBeVisible();
  // List chrome must be absent on the run-scoped apply surface.
  await expect(page.locator(HISTORY_LIST)).toHaveCount(0);
});


test('legacy tab=confirm does not open advanced or rewrite tab (shim retired)', async ({
  page,
  baseURL,
}) => {
  const base = requireBaseUrl(baseURL);
  // Plan §Slice 4 / Verification: plain-scan landing — no rewrite to advanced=open.
  // Raw confirm shape — must NOT be produced by any builder; this is the degrade probe.
  await openHash(page, base, 'alt-context-workbench', '#/workbench?tab=confirm');
  await expect(page.locator(WORKBENCH_SHELL)).toBeVisible();
  await expect(page.getByRole('heading', { name: /Scan Media Queue/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /Advanced: jobs & recovery/i })).toHaveAttribute(
    'aria-expanded',
    'false',
  );
  // URL keeps tab=confirm (no rewrite) and must not gain advanced=open.
  await expect(page).toHaveURL(/tab=confirm/);
  await expect(page).not.toHaveURL(/advanced=open/);
  await expect(page).not.toHaveURL(/tab=scan/);
});

test('WP-menu entry param-forwarding still works (non-regression)', async ({ page, baseURL }) => {
  const base = requireBaseUrl(baseURL);
  // Keep one WP search-param forward path green (ensureHashInitialized when no hash).
  const url = getAcxAdminRouteUrlWithParams(base, 'alt-context-workbench', { status: 'missing' });
  await page.goto(url);
  await expect(page.locator(WORKBENCH_SHELL)).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Status' })).toContainText('Missing alt text');
});
