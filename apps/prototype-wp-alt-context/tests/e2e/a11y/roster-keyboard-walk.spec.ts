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
    const seeded = (
      window as unknown as { acxE2eSeed?: { unlabeledClusterId?: string } }
    ).acxE2eSeed?.unlabeledClusterId;
    if (seeded) {
      return seeded;
    }
    const config = (
      window as unknown as {
        AltContextAdmin?: {
          nonce?: string;
          tenant_id?: string;
          endpoints?: Record<string, string>;
        };
      }
    ).AltContextAdmin;
    const clustersBase = config?.endpoints?.recognitionClusters;
    if (!clustersBase || !config?.nonce) {
      return null;
    }
    const url = new URL(`${clustersBase.replace(/\/?$/, '/')}top-unlabeled`, window.location.origin);
    if (config.tenant_id) {
      url.searchParams.set('tenant_id', config.tenant_id);
    }
    url.searchParams.set('limit', '1');
    const response = await fetch(url.toString(), {
      headers: { 'X-WP-Nonce': config.nonce },
    });
    if (!response.ok) {
      return null;
    }
    const payload = (await response.json()) as { clusters?: Array<{ id?: string }> };
    return payload.clusters?.[0]?.id ?? null;
  });

  if (!clusterId) {
    test.skip(
      true,
      'seeded fixture acxE2eSeed.unlabeledClusterId / top-unlabeled row absent — drawer walk needs a live face group',
    );
    return;
  }

  await openRoster(base, page, { cluster: clusterId });

  const drawer = page.locator('.acx-cluster-drawer');
  await expect(drawer).toBeVisible();
  const close = drawer.getByRole('button', { name: /^Close$/i });
  await expect(close).toBeVisible();
  const box = await close.boundingBox();
  expect(box, 'Close target ≥24×24').not.toBeNull();
  expect(box!.width).toBeGreaterThanOrEqual(24);
  expect(box!.height).toBeGreaterThanOrEqual(24);
  await expect(drawer.getByText(/Face moves happen in the Workbench review queue/i)).toBeVisible();
  await expect(drawer.getByRole('button', { name: /Move to/i })).toHaveCount(0);

  const interactive = drawer.locator(
    'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
  );
  const count = await interactive.count();
  expect(count).toBeGreaterThan(0);
  await close.focus();
  await expect(close).toBeFocused();
  const visited = new Set<string>();
  for (let step = 0; step < count + 2; step += 1) {
    await page.keyboard.press('Tab');
    const id = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || !el.closest('.acx-cluster-drawer')) {
        return null;
      }
      return el.tagName + (el.getAttribute('aria-label') ?? el.textContent ?? '').slice(0, 40);
    });
    if (id) {
      visited.add(id);
    }
  }
  expect(visited.size, 'Tab walk visits drawer controls').toBeGreaterThan(0);
});

test('roster review CTA follows to the workbench default review queue', async ({ page, baseURL }) => {
  await openRoster(requireBaseUrl(baseURL), page);
  await page.getByRole('link', { name: /Review in Workbench/i }).click();
  await expect(page).toHaveURL(/page=alt-context-workbench/);
  await expect.poll(() => page.evaluate(() => window.location.hash)).toBe('#/workbench?tab=scan&rq=all.all.0');
});
