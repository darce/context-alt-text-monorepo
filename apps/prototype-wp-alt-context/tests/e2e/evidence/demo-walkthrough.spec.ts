import fs from 'node:fs/promises';

import { expect, test, type Page } from '@playwright/test';

import { getAcxAdminRouteUrl, getAcxAdminRouteUrlWithParams } from '../fixtures/acx-routes';
import {
  DEMO_WALKTHROUGH_FRAGMENT_FILENAME,
  renderDemoSmokeLogFragment,
  type DemoWalkthroughManifest,
} from '../fixtures/demo-smoke-log';
import { probeAcxConnection } from '../fixtures/wp-rest';

/**
 * E15-28 public-demo walkthrough proof.
 *
 * Drives the browser-automatable steps of `infra/oci/demo/walkthrough-runbook.md`
 * against the demo origin (`WP_BASE_URL`, default https://demo.altcontext.com) and
 * emits screenshots, an evidence manifest, and a paste-ready smoke-log fragment for
 * `docs/tasks/15.0/E15-28-demo-smoke-log.md`. Run via `make demo-walkthrough-proof`.
 *
 * Scope boundary (per E15-6 v1): this harness captures evidence only. The sovereign
 * boundary's API stop/start stays an operator shell step (runbook §3); this spec
 * captures the degraded banner opportunistically if the operator stopped the API
 * before the run.
 */

const SETTINGS_SHELL = '.acx-settings';
const WORKBENCH_SHELL = '.acx-workbench';
const SCAN_BUTTON_NAME = /Analyze selected media/i;
const MEDIA_CHECKBOX_NAME = /Select media item/i;
const CONSTANT_PROVENANCE_TEXT = /Set via wp-config\.php constant/i;
const DEGRADED_BANNER = '.acx-sync-status--warning';

const MAX_SCAN_MEDIA = 5;
const SCAN_POLL_MS = 5_000;
const SCAN_TIMEOUT_MS = 240_000;

const taskRef = (process.env.ACX_PLAYWRIGHT_TASK_REF ?? 'E15-28').trim();
const recognitionUrl = (process.env.ACX_E2E_RECOGNITION_URL ?? 'https://staging.api.altcontext.com').trim();
const deployCommitSha = (process.env.ACX_DEPLOY_COMMIT_SHA ?? '').trim() || null;

const captureIfVisible = async (page: Page, selector: string, outputPath: string): Promise<boolean> => {
  const target = page.locator(selector).first();
  if (!(await target.isVisible().catch(() => false))) {
    return false;
  }

  await target.scrollIntoViewIfNeeded().catch(() => undefined);
  await target.screenshot({ path: outputPath });
  return true;
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

const scanHasFailures = async (page: Page): Promise<boolean> =>
  page
    .getByText(/Client could not submit this batch|\(\d+ failed\)/i)
    .first()
    .isVisible()
    .catch(() => false);

test('captures E15-28 public demo walkthrough proof', async ({ page, baseURL }, testInfo) => {
  test.setTimeout(SCAN_TIMEOUT_MS + 180_000);

  if (!baseURL) {
    throw new Error('Expected Playwright baseURL to be configured for the demo WP admin.');
  }

  const captures: Record<string, boolean> = {};
  const processedSamples: number[] = [];
  let constantProvenanceVisible = false;
  let probeOutcome: string | null = null;
  let scanTriggered = false;
  let scanHadFailures = false;
  let degradedBannerCaptured = false;

  try {
    // 1. Settings + pairing proof: constant-provenance fields + Test Connection.
    await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-settings'));
    await expect(page).toHaveURL(/page=alt-context-settings/);
    await expect(page.locator(SETTINGS_SHELL)).toBeVisible();

    constantProvenanceVisible = await page
      .getByText(CONSTANT_PROVENANCE_TEXT)
      .first()
      .isVisible()
      .catch(() => false);

    await page.screenshot({ path: testInfo.outputPath('demo-settings-provenance.png'), fullPage: true });
    captures['demo-settings-provenance.png'] = true;

    probeOutcome = await probeAcxConnection(page).catch(() => null);

    // 2. Scan -> recognition -> curation on the Workbench.
    await page.goto(getAcxAdminRouteUrlWithParams(baseURL, 'alt-context-workbench', { status: 'missing' }));
    await expect(page.locator(WORKBENCH_SHELL)).toBeVisible();

    await page.screenshot({ path: testInfo.outputPath('demo-workbench-pre-scan.png'), fullPage: true });
    captures['demo-workbench-pre-scan.png'] = true;

    // Opportunistic degraded-banner capture (operator may have stopped the API per runbook §3).
    degradedBannerCaptured = await captureIfVisible(
      page,
      DEGRADED_BANNER,
      testInfo.outputPath('demo-degraded-banner.png'),
    );
    captures['demo-degraded-banner.png'] = degradedBannerCaptured;

    const mediaCheckboxes = page.getByRole('checkbox', { name: MEDIA_CHECKBOX_NAME });
    await mediaCheckboxes
      .first()
      .waitFor({ state: 'visible', timeout: 60_000 })
      .catch(() => undefined);

    const selectCount = Math.min(await mediaCheckboxes.count(), MAX_SCAN_MEDIA);
    for (let index = 0; index < selectCount; index += 1) {
      await mediaCheckboxes.nth(index).click();
    }

    const scanButton = page.getByRole('button', { name: SCAN_BUTTON_NAME });
    if (selectCount > 0 && (await scanButton.isEnabled().catch(() => false))) {
      await scanButton.click();
      scanTriggered = true;

      const deadline = Date.now() + SCAN_TIMEOUT_MS;
      while (Date.now() < deadline) {
        const processed = await readProcessedCount(page);
        if (processed !== null) {
          processedSamples.push(processed);
        }

        captures['demo-avatar-top-cluster.png'] =
          (captures['demo-avatar-top-cluster.png'] ?? false) ||
          (await captureIfVisible(page, '.acx-top-cluster-card', testInfo.outputPath('demo-avatar-top-cluster.png')));

        if (await page.getByText(/Scan complete/i).first().isVisible().catch(() => false)) {
          break;
        }

        await page.waitForTimeout(SCAN_POLL_MS);
      }

      scanHadFailures = await scanHasFailures(page);
    }

    captures['demo-job-timeline.png'] = await captureIfVisible(
      page,
      '.acx-job-timeline',
      testInfo.outputPath('demo-job-timeline.png'),
    );
    captures['demo-naming-queue.png'] = await captureIfVisible(
      page,
      '.acx-top-clusters-section',
      testInfo.outputPath('demo-naming-queue.png'),
    );

    await page.screenshot({ path: testInfo.outputPath('demo-workbench-post-run.png'), fullPage: true });
    captures['demo-workbench-post-run.png'] = true;

    // The harness only proves something if it actually reached the demo settings
    // and workbench surfaces. Scan/cluster captures are best-effort (depend on
    // seeded media + a live backend), so they do not gate the assertion.
    expect(captures['demo-settings-provenance.png']).toBeTruthy();
    expect(captures['demo-workbench-pre-scan.png']).toBeTruthy();

    if (processedSamples.length >= 2) {
      const monotonic = processedSamples.every((value, index) => index === 0 || value >= processedSamples[index - 1]);
      expect(
        monotonic,
        `processed-count samples must be non-decreasing, observed: [${processedSamples.join(', ')}]`,
      ).toBeTruthy();
    }
  } finally {
    const monotonic =
      processedSamples.length < 2 ||
      processedSamples.every((value, index) => index === 0 || value >= processedSamples[index - 1]);

    const verdict: DemoWalkthroughManifest['verdict'] =
      constantProvenanceVisible && probeOutcome === 'connected' && !scanHadFailures ? 'pass' : 'fail';

    const manifest: DemoWalkthroughManifest = {
      task_ref: taskRef,
      captured_at: new Date().toISOString(),
      base_url: baseURL,
      recognition_url: recognitionUrl,
      deploy_commit_sha: deployCommitSha,
      settings: { constant_provenance_visible: constantProvenanceVisible, probe_outcome: probeOutcome },
      scan: { triggered: scanTriggered, processed_samples: processedSamples, monotonic, had_failures: scanHadFailures },
      sovereignty: {
        degraded_banner_captured: degradedBannerCaptured,
        local_read_ok: degradedBannerCaptured ? await page.locator(WORKBENCH_SHELL).isVisible().catch(() => false) : false,
        recovery_captured: false,
      },
      captures,
      verdict,
    };

    await fs.writeFile(testInfo.outputPath('evidence-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
    await fs.writeFile(testInfo.outputPath(DEMO_WALKTHROUGH_FRAGMENT_FILENAME), renderDemoSmokeLogFragment(manifest));
  }
});
