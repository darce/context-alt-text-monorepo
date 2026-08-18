import { expect, test, type Page } from '@playwright/test';

import { requireBaseUrl } from '../fixtures/axe';
import { getAcxAdminRouteUrl, getAcxAdminRouteUrlWithParams } from '../fixtures/acx-routes';

const ROSTER_SHELL_SELECTOR = '.acx-roster';

const openRoster = async (baseURL: string, page: Page, params: Record<string, string> = {}) => {
  const url =
    Object.keys(params).length > 0
      ? getAcxAdminRouteUrlWithParams(baseURL, 'alt-context-roster', params)
      : getAcxAdminRouteUrl(baseURL, 'alt-context-roster');
  await page.goto(url);
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
 * UXW2-4: the needs-assignment rail is retired — Roster links to the workbench
 * review queue instead. Member-fix walks the `cluster=` deep-link shim after
 * discovering an unlabeled group from the same REST envelope the CTA counts.
 */
test('roster review CTA links to the workbench queue; no rail is rendered', async ({ page, baseURL }) => {
  await openRoster(requireBaseUrl(baseURL), page);

  const cta = page.getByTestId('roster-review-cta');
  await expect(cta).toBeVisible();
  await expect(cta.getByRole('link', { name: /Review in Workbench/i })).toHaveAttribute(
    'href',
    '#/workbench?tab=scan&rq=all.all.0',
  );
  await expect(page.getByTestId('needs-assignment-section')).toHaveCount(0);
});

test('keyboard member-fix loop: cluster= shim opens drawer with honest Move copy', async ({
  page,
  baseURL,
}) => {
  const base = requireBaseUrl(baseURL);
  await openRoster(base, page);

  const clusterId = await page.evaluate(async () => {
    const config = (
      window as unknown as {
        acxAdmin?: { tenantId?: string; restUrl?: string; nonce?: string };
      }
    ).acxAdmin;
    const restBase = config?.restUrl ?? '/wp-json/acx/v1/';
    const tenant = config?.tenantId ?? '';
    const url = new URL(`${restBase.replace(/\/?$/, '/')}recognition/clusters/top-unlabeled`, window.location.origin);
    if (tenant) {
      url.searchParams.set('tenant_id', tenant);
    }
    url.searchParams.set('limit', '1');
    const response = await fetch(url.toString(), {
      headers: config?.nonce ? { 'X-WP-Nonce': config.nonce } : {},
    });
    if (!response.ok) {
      return null;
    }
    const payload = (await response.json()) as { clusters?: Array<{ id?: string }> };
    return payload.clusters?.[0]?.id ?? null;
  });

  if (!clusterId) {
    test.skip(true, 'No unlabeled face group from /clusters/top-unlabeled — drawer walk needs a live row');
    return;
  }

  await openRoster(base, page, { cluster: clusterId });

  const drawer = page.locator('.acx-cluster-drawer');
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole('button', { name: /^Close$/i })).toBeVisible();
  await expect(drawer.getByText(/Move faces between groups in the Workbench/i)).toBeVisible();
  await expect(drawer.getByRole('button', { name: /Move to/i })).toHaveCount(0);
});
