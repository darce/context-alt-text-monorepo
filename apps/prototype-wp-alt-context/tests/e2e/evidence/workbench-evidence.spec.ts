import fs from 'node:fs/promises';

import { expect, test, type Page } from '@playwright/test';

import { getAcxAdminRouteUrlWithParams } from '../fixtures/acx-routes';
import {
  type AcxSettingsSnapshot,
  ensureLocalRecognitionWhenProbeFails,
  ensureServiceRecognitionTarget,
  probeAcxConnection,
  restoreRecognitionSourceIfNeeded,
} from '../fixtures/wp-rest';

const WORKBENCH_SHELL_SELECTOR = '.acx-workbench';
const SCAN_BUTTON_NAME = /Analyze selected media/i;
const MAX_SCAN_MEDIA = 5;
const SCAN_POLL_MS = 5_000;
const SCAN_TIMEOUT_MS = 600_000;
const POST_SCAN_CLUSTERING_GRACE_MS = 90_000;
const CLUSTER_POST_SCAN_WAIT_MS = 90_000;
const REVIEW_PANEL_TIMEOUT_MS = 20_000;

const DEFAULT_RECOGNITION_URL = 'https://api.altcontext.com';
const recognitionUrl = (process.env.ACX_E2E_RECOGNITION_URL ?? DEFAULT_RECOGNITION_URL).trim();
const recognitionApiKey = (process.env.ACX_E2E_RECOGNITION_API_KEY ?? '').trim();
const ensureServiceMode =
  process.env.ACX_E2E_ENSURE_SERVICE_MODE === '1' || process.env.ACX_E2E_ENSURE_SERVICE_MODE === 'true';

interface EvidenceManifest {
  recognition_url: string;
  ensure_service_mode: boolean;
  service_settings_changed: boolean;
  service_settings_restored: boolean;
  settings_probe_outcome: string | null;
  scan_had_failures: boolean;
  captures: Record<string, boolean>;
  cluster_cards_visible: boolean;
  review_panel_visible: boolean;
}

const captureClusterSurfaces = async (
  page: Page,
  testInfo: { outputPath: (name: string) => string },
  captures: Record<string, boolean>,
  options: { includeReview?: boolean; settleMs?: number } = {},
): Promise<void> => {
  const includeReview = options.includeReview ?? true;
  const settleMs = options.settleMs ?? 0;

  if (settleMs > 0) {
    await page
      .locator('.acx-top-cluster-card, .acx-top-clusters-section, .acx-findings-detail-anchor')
      .first()
      .waitFor({ state: 'visible', timeout: settleMs })
      .catch(() => undefined);
  }

  await Promise.race([
    page.locator('.acx-findings-detail-anchor').first().scrollIntoViewIfNeeded(),
    page.waitForTimeout(5_000),
  ]).catch(() => undefined);

  captures['workbench-avatar-top-cluster.png'] =
    (captures['workbench-avatar-top-cluster.png'] ?? false) ||
    (await captureIfVisible(page, '.acx-top-cluster-card', testInfo.outputPath('workbench-avatar-top-cluster.png')));

  captures['workbench-avatar-thumb.png'] =
    (captures['workbench-avatar-thumb.png'] ?? false) ||
    (await captureIfVisible(
      page,
      '.acx-top-cluster-card__thumb-image',
      testInfo.outputPath('workbench-avatar-thumb.png'),
    ));

  captures['workbench-avatar-unavailable.png'] =
    (captures['workbench-avatar-unavailable.png'] ?? false) ||
    (await captureIfVisible(
      page,
      '.acx-top-cluster-card__thumb-image--unavailable',
      testInfo.outputPath('workbench-avatar-unavailable.png'),
    ));

  captures['workbench-naming-queue.png'] =
    (captures['workbench-naming-queue.png'] ?? false) ||
    (await captureIfVisible(page, '.acx-top-clusters-section', testInfo.outputPath('workbench-naming-queue.png')));

  if (includeReview && !captures['workbench-cluster-review-panel.png']) {
    captures['workbench-cluster-review-panel.png'] = await captureReviewDrawer(
      page,
      testInfo.outputPath('workbench-cluster-review-panel.png'),
    );
  }

  if (captures['workbench-cluster-review-panel.png']) {
    captures['workbench-cluster-member-image.png'] =
      (captures['workbench-cluster-member-image.png'] ?? false) ||
      (await captureIfVisible(
        page,
        '.acx-cluster-member-card__image',
        testInfo.outputPath('workbench-cluster-member-image.png'),
      ));
  }
};

const openWorkbench = async (baseURL: string, page: Page): Promise<void> => {
  const workbenchUrl = getAcxAdminRouteUrlWithParams(baseURL, 'alt-context-workbench', {
    status: 'missing',
  });

  await page.goto(workbenchUrl);
  await expect(page).toHaveURL(/page=alt-context-workbench/);
  await expect(page.locator(WORKBENCH_SHELL_SELECTOR)).toBeVisible();
  await expect(page.getByRole('tablist', { name: /Workbench steps/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Scan Media Queue/i })).toBeVisible();
};

const timelineHasLabel = async (page: Page, label: string): Promise<boolean> => {
  const timeline = page.locator('.acx-job-timeline');
  if (!(await timeline.isVisible().catch(() => false))) {
    return false;
  }

  return timeline
    .getByText(label, { exact: true })
    .isVisible()
    .catch(() => false);
};

const readProcessedCount = async (page: Page): Promise<number | null> => {
  const text = await page
    .getByText(/Processed\s+\d+\/\d+/i)
    .first()
    .textContent()
    .catch(() => null);
  if (!text) {
    return null;
  }

  const match = /Processed\s+(\d+)\/(\d+)/i.exec(text);
  return match ? Number.parseInt(match[1], 10) : null;
};

const scanHasFailures = async (page: Page): Promise<boolean> => {
  return page
    .getByText(/Client could not submit this batch|\(\d+ failed\)/i)
    .first()
    .isVisible()
    .catch(() => false);
};

const captureIfVisible = async (page: Page, selector: string, outputPath: string): Promise<boolean> => {
  const target = page.locator(selector).first();
  if (!(await target.isVisible().catch(() => false))) {
    return false;
  }

  await target.scrollIntoViewIfNeeded().catch(() => undefined);
  await target.screenshot({ path: outputPath });
  return true;
};

const waitForTopClusterSurface = async (page: Page, deadlineMs: number): Promise<boolean> => {
  const deadline = Date.now() + deadlineMs;

  while (Date.now() < deadline) {
    const hasCard = await page
      .locator('.acx-top-cluster-card')
      .first()
      .isVisible()
      .catch(() => false);
    if (hasCard) {
      return true;
    }

    const hasFallback = await page
      .locator('.acx-top-cluster-card__thumb-image--unavailable')
      .first()
      .isVisible()
      .catch(() => false);
    if (hasFallback) {
      return true;
    }

    await page.waitForTimeout(SCAN_POLL_MS);
  }

  return false;
};

const captureReviewDrawer = async (page: Page, outputPath: string): Promise<boolean> => {
  const reviewButton = page.locator('.acx-top-cluster-card__review-btn').first();
  if (!(await reviewButton.isVisible().catch(() => false))) {
    return false;
  }

  await reviewButton.scrollIntoViewIfNeeded();
  await reviewButton.click();

  const panel = page.locator('.acx-cluster-review-panel').first();
  await panel.waitFor({ state: 'visible', timeout: REVIEW_PANEL_TIMEOUT_MS }).catch(() => undefined);

  if (!(await panel.isVisible().catch(() => false))) {
    return false;
  }

  await panel
    .locator('.acx-cluster-member-card__image, .acx-cluster-member-card__thumbnail img')
    .first()
    .waitFor({ state: 'visible', timeout: REVIEW_PANEL_TIMEOUT_MS })
    .catch(() => undefined);

  await panel.screenshot({ path: outputPath });
  return true;
};

test('captures E15-22 workbench avatar and progress evidence on LocalWP', async ({ page, baseURL }, testInfo) => {
  test.setTimeout(SCAN_TIMEOUT_MS + POST_SCAN_CLUSTERING_GRACE_MS + CLUSTER_POST_SCAN_WAIT_MS + 180_000);

  if (!baseURL) {
    throw new Error('Expected Playwright baseURL to be configured for LocalWP admin.');
  }

  const captures: Record<string, boolean> = {};
  const processedSamples: number[] = [];
  let settingsResult: { changed: boolean; before: AcxSettingsSnapshot; after: AcxSettingsSnapshot } = {
    changed: false,
    before: { recognition_source: 'local', recognition_source_source: 'default', url: '', api_key_set: false },
    after: { recognition_source: 'local', recognition_source_source: 'default', url: '', api_key_set: false },
  };
  let settingsProbeOutcome: string | null = null;
  let serviceSettingsRestored = false;
  let scanHadFailures = false;
  let clusterCardsVisible = false;
  let canScan = false;

  try {
    await openWorkbench(baseURL, page);

    const localFallback = await ensureLocalRecognitionWhenProbeFails(page);
    settingsResult = {
      changed: localFallback.restored,
      before: localFallback.before,
      after: localFallback.after,
    };
    settingsProbeOutcome = localFallback.probeOutcome;
    serviceSettingsRestored = localFallback.restored;

    if (localFallback.restored) {
      await openWorkbench(baseURL, page);
    }

    if (ensureServiceMode) {
      settingsResult = await ensureServiceRecognitionTarget(page, {
        recognitionUrl,
        recognitionApiKey: recognitionApiKey || undefined,
        enabled: true,
      });

      if (settingsResult.changed) {
        await openWorkbench(baseURL, page);
      }

      settingsProbeOutcome = await probeAcxConnection(page).catch(() => null);

      if (settingsProbeOutcome !== 'connected') {
        serviceSettingsRestored = await restoreRecognitionSourceIfNeeded(page, settingsResult.before);
        if (serviceSettingsRestored) {
          await openWorkbench(baseURL, page);
          settingsProbeOutcome = await probeAcxConnection(page).catch(() => null);
        }
      }
    }

    await page.screenshot({
      path: testInfo.outputPath('workbench-pre-scan.png'),
      fullPage: true,
    });
    captures['workbench-pre-scan.png'] = true;

    await captureClusterSurfaces(page, testInfo, captures, {
      includeReview: false,
      settleMs: 15_000,
    });
    clusterCardsVisible = Boolean(
      captures['workbench-avatar-top-cluster.png'] || captures['workbench-avatar-unavailable.png'],
    );

    const mediaCheckboxes = page.getByRole('checkbox', { name: /Select media item/i });
    await mediaCheckboxes
      .first()
      .waitFor({ state: 'visible', timeout: 60_000 })
      .catch(() => undefined);

    const checkboxCount = await mediaCheckboxes.count();
    const selectCount = Math.min(checkboxCount, MAX_SCAN_MEDIA);

    for (let index = 0; index < selectCount; index += 1) {
      await mediaCheckboxes.nth(index).click();
    }

    const scanButton = page.getByRole('button', { name: SCAN_BUTTON_NAME });
    const hasExistingClusterEvidence =
      Boolean(captures['workbench-avatar-top-cluster.png']) ||
      Boolean(captures['workbench-cluster-review-panel.png']) ||
      Boolean(captures['workbench-avatar-unavailable.png']);
    canScan = !hasExistingClusterEvidence && selectCount > 0 && (await scanButton.isEnabled().catch(() => false));

    if (canScan) {
      await scanButton.click();

      const deadline = Date.now() + SCAN_TIMEOUT_MS;
      let capturedMidRun = false;
      let capturedClusteringMidRun = false;
      let capturedClusteringComplete = false;
      let capturedCompletion = false;
      let scanCompleteAt: number | null = null;

      while (Date.now() < deadline) {
        const scanning = await page
          .getByRole('button', { name: /Scanning media|Clustering identities/i })
          .isVisible()
          .catch(() => false);
        const scanComplete = await timelineHasLabel(page, 'Scan complete');
        const clusteringActive = await timelineHasLabel(page, 'Clustering…');
        const clusteringComplete = await timelineHasLabel(page, 'Clustering complete');

        const processed = await readProcessedCount(page);
        if (processed !== null) {
          processedSamples.push(processed);
        }

        if (scanComplete && scanCompleteAt === null) {
          scanCompleteAt = Date.now();
        }

        if (scanning && !scanComplete && !capturedMidRun) {
          await page.screenshot({
            path: testInfo.outputPath('workbench-progress-mid-run.png'),
            fullPage: true,
          });
          capturedMidRun = true;
          captures['workbench-progress-mid-run.png'] = true;
        }

        if (clusteringActive && !capturedClusteringMidRun) {
          captures['workbench-clustering-mid-run.png'] = await captureIfVisible(
            page,
            '.acx-job-timeline',
            testInfo.outputPath('workbench-clustering-mid-run.png'),
          );
          if (!captures['workbench-clustering-mid-run.png']) {
            await page.screenshot({
              path: testInfo.outputPath('workbench-clustering-mid-run.png'),
              fullPage: true,
            });
            captures['workbench-clustering-mid-run.png'] = true;
          }
          capturedClusteringMidRun = true;
        }

        if (clusteringComplete && !capturedClusteringComplete) {
          captures['workbench-clustering-complete.png'] = await captureIfVisible(
            page,
            '.acx-job-timeline',
            testInfo.outputPath('workbench-clustering-complete.png'),
          );
          capturedClusteringComplete = captures['workbench-clustering-complete.png'];
        }

        captures['workbench-avatar-top-cluster.png'] =
          (captures['workbench-avatar-top-cluster.png'] ?? false) ||
          (await captureIfVisible(
            page,
            '.acx-top-cluster-card',
            testInfo.outputPath('workbench-avatar-top-cluster.png'),
          ));

        captures['workbench-naming-queue.png'] =
          (captures['workbench-naming-queue.png'] ?? false) ||
          (await captureIfVisible(
            page,
            '.acx-top-clusters-section',
            testInfo.outputPath('workbench-naming-queue.png'),
          ));

        if (scanComplete && !capturedCompletion) {
          await page.screenshot({
            path: testInfo.outputPath('workbench-progress-complete.png'),
            fullPage: true,
          });
          capturedCompletion = true;
          captures['workbench-progress-complete.png'] = true;
        }

        if (scanComplete && capturedCompletion) {
          scanHadFailures = await scanHasFailures(page);

          if (clusteringComplete) {
            break;
          }

          if (scanHadFailures) {
            break;
          }

          const hasClusters = await page
            .locator('.acx-top-cluster-card')
            .first()
            .isVisible()
            .catch(() => false);
          if (hasClusters) {
            break;
          }

          if (scanCompleteAt !== null && Date.now() - scanCompleteAt >= POST_SCAN_CLUSTERING_GRACE_MS) {
            break;
          }
        }

        await page.waitForTimeout(SCAN_POLL_MS);
      }

      const clusterButton = page.getByRole('button', { name: /Cluster the latest job results/i });
      if (await clusterButton.isVisible().catch(() => false)) {
        if (await clusterButton.isEnabled().catch(() => false)) {
          await clusterButton.click();
        }
      }
    }

    if (!scanHadFailures && !clusterCardsVisible) {
      clusterCardsVisible = await waitForTopClusterSurface(page, CLUSTER_POST_SCAN_WAIT_MS);
    }

    await captureClusterSurfaces(page, testInfo, captures);
    clusterCardsVisible =
      clusterCardsVisible ||
      Boolean(captures['workbench-avatar-top-cluster.png'] || captures['workbench-avatar-unavailable.png']);

    captures['workbench-job-timeline.png'] = await captureIfVisible(
      page,
      '.acx-job-timeline',
      testInfo.outputPath('workbench-job-timeline.png'),
    );

    try {
      await page.screenshot({
        path: testInfo.outputPath('workbench-post-run.png'),
        fullPage: true,
      });
      captures['workbench-post-run.png'] = true;
    } catch {
      captures['workbench-post-run.png'] = false;
    }

    const hasNamingQueue = await page
      .locator('.acx-top-clusters-section')
      .first()
      .isVisible()
      .catch(() => false);
    const hasTimeline = await page
      .locator('.acx-job-timeline')
      .first()
      .isVisible()
      .catch(() => false);

    // The harness only proves something if it actually reached the Workbench and
    // landed on a real evidence surface — a naming queue, a job timeline, or
    // rendered cluster cards. `canScan` (merely clicking Scan) is not evidence.
    expect(captures['workbench-pre-scan.png']).toBeTruthy();
    expect(hasNamingQueue || hasTimeline || clusterCardsVisible).toBeTruthy();

    // Honest-progress regression guard: the displayed processed count must never
    // decrease across the scan run. Only asserts when a scan produced >=2 samples;
    // the scan-complete predicate itself is unit-proven in JobTimeline.test.tsx.
    if (processedSamples.length >= 2) {
      const monotonic = processedSamples.every((value, index) => index === 0 || value >= processedSamples[index - 1]);
      expect(
        monotonic,
        `processed-count samples must be non-decreasing, observed: [${processedSamples.join(', ')}]`,
      ).toBeTruthy();
    }
  } finally {
    if (ensureServiceMode && settingsResult.changed && !serviceSettingsRestored) {
      serviceSettingsRestored = await restoreRecognitionSourceIfNeeded(page, settingsResult.before).catch(() => false);
    }

    const manifest: EvidenceManifest = {
      recognition_url: recognitionUrl,
      ensure_service_mode: ensureServiceMode,
      service_settings_changed: settingsResult.changed,
      service_settings_restored: serviceSettingsRestored,
      settings_probe_outcome: settingsProbeOutcome,
      scan_had_failures: scanHadFailures,
      captures,
      cluster_cards_visible: clusterCardsVisible,
      review_panel_visible: Boolean(captures['workbench-cluster-review-panel.png']),
    };

    await fs.writeFile(testInfo.outputPath('evidence-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
  }
});
