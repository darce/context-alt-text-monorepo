import fs from 'node:fs/promises';

import { expect, test, type Page } from '@playwright/test';

import { getAcxAdminRouteUrl, getAcxAdminRouteUrlWithParams } from '../fixtures/acx-routes';
import {
  DEMO_WALKTHROUGH_FRAGMENT_FILENAME,
  renderDemoSmokeLogFragment,
  type DemoWalkthroughManifest,
} from '../fixtures/demo-smoke-log';
import { fetchAcxSettings, probeAcxConnection } from '../fixtures/wp-rest';

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
// The demo's core pairing proof is constant-provenance (non-derived identity), so it
// gates the verdict by default. LocalWP runs legitimately have no wp-config constants —
// pass ACX_E2E_REQUIRE_CONSTANT_PROVENANCE=0 there so a missing badge does not force fail.
const requireConstantProvenance = (process.env.ACX_E2E_REQUIRE_CONSTANT_PROVENANCE ?? '1') !== '0';
// Independent of the provenance badge: the RECOG-1 single-target contract gate
// (recognition_source === 'service'). Opt out with ACX_E2E_REQUIRE_SERVICE_TARGET=0
// only on LocalWP runs with the wp-config dev hatch active — tolerating a
// provenance-badge flake must not silently disable this unrelated gate.
const requireServiceTarget = (process.env.ACX_E2E_REQUIRE_SERVICE_TARGET ?? '1') !== '0';

const isMonotonic = (samples: number[]): boolean =>
  samples.length < 2 || samples.every((value, index) => index === 0 || value >= samples[index - 1]);

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

// The Workbench renders "Processed X/Y (Z failed)" via jobStateMachineProgress;
// match a non-zero failed count so "(0 failed)" is not a false positive.
const scanHasFailures = async (page: Page): Promise<boolean> =>
  page
    .getByText(/\([1-9]\d* failed\)/i)
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
  let localReadOk = false;

  try {
    // 1. Settings + pairing proof: constant-provenance fields + Test Connection.
    await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-settings'));
    await expect(page).toHaveURL(/page=alt-context-settings/);
    await expect(page.locator(SETTINGS_SHELL)).toBeVisible();

    // RECOG-1 single-target contract (deploy-landed signal for the CI deploy-smoke,
    // DDEP-1): exactly one target card — the hosted-service card — and the settings
    // GET payload no longer carries local_url*. These gate the TEST exit code
    // (deploy landed) independently of the recognition manifest verdict.
    await expect(page.getByTestId('acx-target-card-service')).toBeVisible();
    await expect(page.locator('.acx-target-card')).toHaveCount(1);
    const settingsSnapshot = (await fetchAcxSettings(page)) as unknown as Record<string, unknown>;
    // recognition_source may legitimately be 'local' on a LocalWP run with the
    // RECOG-1 dev hatch active, so this gate has its own opt-out flag (NOT the
    // provenance flag — the two concerns are independent); the local_url*
    // absence checks are hatch-independent.
    if (requireServiceTarget) {
      expect(settingsSnapshot.recognition_source).toBe('service');
    }
    expect(settingsSnapshot).not.toHaveProperty('local_url');
    expect(settingsSnapshot).not.toHaveProperty('local_url_source');

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

    // Opportunistic degraded-banner capture, attempt 1 (pre-scan). The sovereign
    // boundary's API stop/start is an operator shell step (runbook §3, E15-6 v1
    // excludes outage helpers), so this is best-effort: it only catches an outage
    // the operator induced before the run. A second attempt runs post-scan below in
    // case the API was stopped mid-walkthrough. `.acx-sync-status--warning` also
    // covers stale/projection-error states, so this is a degraded *indicator*, not a
    // proven outage.
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
    if (selectCount === 0) {
      expect(
        selectCount,
        'scan path cannot silently degrade: workbench had 0 selectable media',
      ).toBeGreaterThan(0);
    }
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

    // Degraded-banner attempt 2 (post-scan), and the sovereign-boundary read:
    // local/curated data still rendering while the indicator is degraded. Computed
    // here while the page is live so the finally block never touches `page`.
    if (!degradedBannerCaptured) {
      degradedBannerCaptured = await captureIfVisible(
        page,
        DEGRADED_BANNER,
        testInfo.outputPath('demo-degraded-banner.png'),
      );
    }
    captures['demo-degraded-banner.png'] = degradedBannerCaptured;
    localReadOk =
      degradedBannerCaptured && (await page.locator(WORKBENCH_SHELL).isVisible().catch(() => false));

    await page.screenshot({ path: testInfo.outputPath('demo-workbench-post-run.png'), fullPage: true });
    captures['demo-workbench-post-run.png'] = true;

    // The harness only proves something if it actually reached the demo settings
    // and workbench surfaces. Scan/cluster captures are best-effort (depend on
    // seeded media + a live backend), so they do not gate the assertion.
    expect(captures['demo-settings-provenance.png']).toBeTruthy();
    expect(captures['demo-workbench-pre-scan.png']).toBeTruthy();

    if (processedSamples.length >= 2) {
      expect(
        isMonotonic(processedSamples),
        `processed-count samples must be non-decreasing, observed: [${processedSamples.join(', ')}]`,
      ).toBeTruthy();
    }
  } finally {
    // Verdict gates on constant-provenance only when required (demo: yes; LocalWP: opt
    // out). The finally block must not touch `page` — it can be closed if the try threw,
    // which would swallow the failure and skip the manifest+fragment write.
    const provenanceOk = requireConstantProvenance ? constantProvenanceVisible : true;
    const verdict: DemoWalkthroughManifest['verdict'] =
      provenanceOk && probeOutcome === 'connected' && !scanHadFailures ? 'pass' : 'fail';

    const manifest: DemoWalkthroughManifest = {
      task_ref: taskRef,
      captured_at: new Date().toISOString(),
      base_url: baseURL,
      recognition_url: recognitionUrl,
      deploy_commit_sha: deployCommitSha,
      settings: {
        constant_provenance_visible: constantProvenanceVisible,
        constant_provenance_required: requireConstantProvenance,
        probe_outcome: probeOutcome,
      },
      scan: {
        triggered: scanTriggered,
        processed_samples: processedSamples,
        monotonic: isMonotonic(processedSamples),
        had_failures: scanHadFailures,
      },
      sovereignty: {
        degraded_banner_captured: degradedBannerCaptured,
        local_read_ok: localReadOk,
        recovery_captured: false,
      },
      captures,
      verdict,
    };

    await fs.writeFile(testInfo.outputPath('evidence-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
    await fs.writeFile(testInfo.outputPath(DEMO_WALKTHROUGH_FRAGMENT_FILENAME), renderDemoSmokeLogFragment(manifest));
  }
});
