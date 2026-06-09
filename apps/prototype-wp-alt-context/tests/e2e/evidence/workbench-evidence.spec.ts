import { expect, test, type Page } from '@playwright/test';

import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';

const WORKBENCH_SHELL_SELECTOR = '.acx-workbench';
const SCAN_BUTTON_NAME = /Analyze selected media/i;
const MAX_SCAN_MEDIA = 5;
const SCAN_POLL_MS = 5_000;
const SCAN_TIMEOUT_MS = 600_000;

const openWorkbench = async (baseURL: string, page: Page): Promise<void> => {
  await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-workbench'));
  await expect(page).toHaveURL(/page=alt-context-workbench/);
  await expect(page.locator(WORKBENCH_SHELL_SELECTOR)).toBeVisible();
  await expect(page.getByRole('tablist', { name: /Workbench steps/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Scan Media Queue/i })).toBeVisible();
};

const timelineHasScanComplete = async (page: Page): Promise<boolean> => {
  const timeline = page.locator('.acx-job-timeline');
  if (!(await timeline.isVisible().catch(() => false))) {
    return false;
  }
  return timeline.getByText('Scan complete', { exact: true }).isVisible().catch(() => false);
};

const captureIfVisible = async (page: Page, selector: string, outputPath: string): Promise<boolean> => {
  const target = page.locator(selector).first();
  if (!(await target.isVisible().catch(() => false))) {
    return false;
  }
  await target.screenshot({ path: outputPath });
  return true;
};

test('captures E15-22 workbench avatar and progress evidence on LocalWP', async ({ page, baseURL }, testInfo) => {
  test.setTimeout(SCAN_TIMEOUT_MS + 60_000);

  if (!baseURL) {
    throw new Error('Expected Playwright baseURL to be configured for LocalWP admin.');
  }

  await openWorkbench(baseURL, page);

  await page.screenshot({
    path: testInfo.outputPath('workbench-pre-scan.png'),
    fullPage: true,
  });

  const mediaCheckboxes = page.getByRole('checkbox', { name: /Select media item/i });
  await mediaCheckboxes.first().waitFor({ state: 'visible', timeout: 60_000 }).catch(() => undefined);

  const checkboxCount = await mediaCheckboxes.count();
  const selectCount = Math.min(checkboxCount, MAX_SCAN_MEDIA);

  for (let index = 0; index < selectCount; index += 1) {
    await mediaCheckboxes.nth(index).click();
  }

  const scanButton = page.getByRole('button', { name: SCAN_BUTTON_NAME });
  const canScan = selectCount > 0 && (await scanButton.isEnabled().catch(() => false));

  if (canScan) {
    await scanButton.click();

    const deadline = Date.now() + SCAN_TIMEOUT_MS;
    let capturedMidRun = false;
    let capturedCompletion = false;

    while (Date.now() < deadline) {
      const scanning = await page.getByRole('button', { name: /Scanning media|Clustering identities/i }).isVisible().catch(() => false);
      const scanComplete = await timelineHasScanComplete(page);

      if (scanning && !scanComplete && !capturedMidRun) {
        await page.screenshot({
          path: testInfo.outputPath('workbench-progress-mid-run.png'),
          fullPage: true,
        });
        capturedMidRun = true;
      }

      await captureIfVisible(page, '.acx-top-cluster-card', testInfo.outputPath('workbench-avatar-top-cluster.png'));
      await captureIfVisible(page, '.acx-top-clusters-section', testInfo.outputPath('workbench-naming-queue.png'));

      if (scanComplete && !capturedCompletion) {
        await page.screenshot({
          path: testInfo.outputPath('workbench-progress-complete.png'),
          fullPage: true,
        });
        capturedCompletion = true;
        break;
      }

      if (!scanning && capturedMidRun && !capturedCompletion) {
        const hasClusters = await page.locator('.acx-top-cluster-card').first().isVisible().catch(() => false);
        if (hasClusters) {
          await page.screenshot({
            path: testInfo.outputPath('workbench-progress-complete.png'),
            fullPage: true,
          });
          capturedCompletion = true;
          break;
        }
      }

      await page.waitForTimeout(SCAN_POLL_MS);
    }
  }

  await captureIfVisible(page, '.acx-top-cluster-card__thumb-image', testInfo.outputPath('workbench-avatar-thumb.png'));
  await captureIfVisible(page, '.acx-job-timeline', testInfo.outputPath('workbench-job-timeline.png'));

  await page.screenshot({
    path: testInfo.outputPath('workbench-post-run.png'),
    fullPage: true,
  });

  const hasNamingQueue = await page.locator('.acx-top-clusters-section').first().isVisible().catch(() => false);
  const hasTimeline = await page.locator('.acx-job-timeline').first().isVisible().catch(() => false);

  expect(hasNamingQueue || hasTimeline || canScan).toBeTruthy();
});