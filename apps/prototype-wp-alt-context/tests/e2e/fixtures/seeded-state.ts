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

export const skipUnlessPopulatedRoster = async (page: Page): Promise<void> => {
  await page.waitForLoadState('networkidle');

  await page.getByRole('tab', { name: /Clusters/i }).click();

  const clusterCard = page.locator('.acx-cluster-card').first();
  const noClusters = page.getByRole('heading', { name: /No clusters yet/i });
  await waitForEither([clusterCard, noClusters], 15_000);

  if (await isVisible(clusterCard)) {
    return;
  }

  await page.getByRole('tab', { name: /Entries/i }).click();

  const entryRow = page.locator('.acx-roster-entries__table tbody tr').first();
  const noPeople = page.getByText(/No people yet\. Add one manually or assign a face group\./i);
  await waitForEither([entryRow, noPeople], 10_000);

  if (await isVisible(entryRow)) {
    return;
  }

  test.skip(true, 'LocalWP roster has no clusters or managed identities — seeded axe requires populated roster data.');
};
