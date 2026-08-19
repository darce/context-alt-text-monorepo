import { expect, test, type Locator, type Page } from '@playwright/test';

const isVisible = async (locator: Locator, timeout = 1_000): Promise<boolean> => {
  try {
    await expect(locator).toBeVisible({ timeout });
    return true;
  } catch {
    return false;
  }
};

const waitForEither = async (candidates: Locator[], timeout: number): Promise<void> => {
  await Promise.race(
    candidates.map((locator) => locator.waitFor({ state: 'visible', timeout }).catch(() => undefined)),
  ).catch(() => undefined);
};

/**
 * ACX_E2E_SEEDED only opts into populated-state coverage; LocalWP may still
 * be empty/offline. Skip (do not fail) when the operator flag is set but the
 * expected hydrated anchor never appears.
 */
export const skipUnlessPopulatedWorkbench = async (page: Page): Promise<void> => {
  await page.waitForLoadState('networkidle');

  const emptyQueue = page.getByRole('heading', { name: /Your analysis queue is empty/i });
  const mediaTitle = page.locator('.acx-media-selection__media-title').first();

  await waitForEither([emptyQueue, mediaTitle], 30_000);

  if (await isVisible(mediaTitle)) {
    return;
  }

  test.skip(
    true,
    'LocalWP workbench queue is empty or still offline — seeded axe requires media rows in the analysis queue.',
  );
};

type AcxE2eSeed = { unlabeledClusterId?: string };

/** Producer: write `window.acxE2eSeed.unlabeledClusterId` for later reads. */
export const plantUnlabeledClusterId = async (page: Page, clusterId: string): Promise<void> => {
  await page.evaluate((id) => {
    const w = window as unknown as { acxE2eSeed?: AcxE2eSeed };
    w.acxE2eSeed = { ...(w.acxE2eSeed ?? {}), unlabeledClusterId: id };
  }, clusterId);
};

export const readSeededUnlabeledClusterId = async (page: Page): Promise<string | null> =>
  page.evaluate(() => {
    const seeded = (window as unknown as { acxE2eSeed?: AcxE2eSeed }).acxE2eSeed?.unlabeledClusterId;
    return typeof seeded === 'string' && seeded.length > 0 ? seeded : null;
  });

/**
 * Prefer planted `window.acxE2eSeed.unlabeledClusterId`. Else discover the first
 * unlabeled group from AltContextAdmin.endpoints.recognitionClusters /top-unlabeled
 * and plant it. Returns null when both miss (empty LocalWP).
 */
export const discoverUnlabeledClusterId = async (page: Page): Promise<string | null> => {
  const seeded = await readSeededUnlabeledClusterId(page);
  if (seeded) {
    return seeded;
  }
  const fromApi = await page.evaluate(async () => {
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
    const payload = (await response.json()) as { clusters?: { id?: string }[] };
    const id = payload.clusters?.[0]?.id;
    return typeof id === 'string' && id.length > 0 ? id : null;
  });
  if (fromApi) {
    await plantUnlabeledClusterId(page, fromApi);
  }
  return fromApi;
};

export const skipUnlessPopulatedRoster = async (page: Page): Promise<void> => {
  await page.waitForLoadState('networkidle');

  const entryRow = page.locator('.acx-roster-entries__table tbody tr').first();
  const noPeople = page.getByText(/No people yet\. Add one manually or assign a face group\./i);
  await waitForEither([entryRow, noPeople], 10_000);

  if (await isVisible(entryRow)) {
    return;
  }

  test.skip(true, 'LocalWP roster has no people — seeded axe requires populated roster data.');
};
