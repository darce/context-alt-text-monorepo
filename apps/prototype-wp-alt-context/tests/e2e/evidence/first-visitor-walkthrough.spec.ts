import fs from 'node:fs/promises';

import { expect, test, type Page } from '@playwright/test';

import { getAcxAdminRouteUrl, getAcxAdminRouteUrlWithParams } from '../fixtures/acx-routes';
import {
  type FirstVisitorWalkthroughManifest,
  renderWalkthroughLogFragment,
  WALKTHROUGH_FRAGMENT_FILENAME,
  WalkthroughTimer,
} from '../fixtures/walkthrough-timings';

/**
 * E21-13 scripted first-visitor walkthrough (roadmap §Phase-3 Gate).
 *
 * Drives the roadmap §8 outcome loop — scan → review → **first named person** —
 * against the demo origin and records per-step timings so
 * `time-to-first-named-person` has a measured baseline before Phase-3
 * construction (E21-5/P3-A funding gate). Run via `make walkthrough-first-visitor`.
 *
 * Scope boundary: this harness measures the *automatable* walkthrough — timing,
 * reachability, and evidence capture. The roadmap's "unaided first-time visitor"
 * observation is a human session that follows the same script; this spec is its
 * instrumented rehearsal, not its replacement.
 *
 * Naming path (grounded against main): the always-available route is the
 * "Name These People" section → "Name this person" → labeling form → "Save"
 * (TopClusterCard → ClusterLabelingPanel, label-only). Suggestion accept/reject
 * surfaces are seed-dependent and captured opportunistically, not gated on.
 */

const WORKBENCH_SHELL = '.acx-workbench';
const SCAN_BUTTON_NAME = /Analyze selected media/i;
const MEDIA_CHECKBOX_NAME = /Select media item/i;
const TOP_CLUSTERS_SECTION = '.acx-top-clusters-section';
const LABELING_PANEL = '.acx-cluster-labeling-panel';
const FINDINGS_PANEL = '.acx-findings-panel';
const SUGGESTION_PANEL = '.acx-suggestion-panel';

const MAX_SCAN_MEDIA = 5;
const SCAN_POLL_MS = 5_000;
const SCAN_TIMEOUT_MS = 240_000;
const NAMING_SURFACE_TIMEOUT_MS = 120_000;

const taskRef = (process.env.ACX_PLAYWRIGHT_TASK_REF ?? 'E21-13').trim();
const deployCommitSha = (process.env.ACX_DEPLOY_COMMIT_SHA ?? '').trim() || null;
const visitorName = (process.env.ACX_E2E_WALKTHROUGH_NAME ?? '').trim() || `Walkthrough Visitor ${taskRef}`;

const capture = async (page: Page, outputPath: string, captures: Record<string, boolean>, key: string) => {
  await page.screenshot({ path: outputPath, fullPage: true }).catch(() => undefined);
  captures[key] = true;
};

test('first-visitor walkthrough: scan → review → first named person, timed', async ({ page, baseURL }, testInfo) => {
  test.setTimeout(SCAN_TIMEOUT_MS + NAMING_SURFACE_TIMEOUT_MS + 180_000);

  if (!baseURL) {
    throw new Error('Expected Playwright baseURL to be configured for the demo WP admin.');
  }

  const captures: Record<string, boolean> = {};
  const timer = new WalkthroughTimer();
  let scanTriggered = false;
  let scanCompleted = false;
  let firstNamedPersonReached = false;
  let timeToFirstNamedPersonMs: number | null = null;

  try {
    // Step 1 — first landing on the Workbench (timer origin ≈ what a visitor sees first).
    await timer.step('land-on-workbench', async () => {
      await page.goto(getAcxAdminRouteUrlWithParams(baseURL, 'alt-context-workbench', { status: 'missing' }));
      await expect(page.locator(WORKBENCH_SHELL)).toBeVisible();
    });
    await capture(page, testInfo.outputPath('walkthrough-1-landing.png'), captures, 'walkthrough-1-landing.png');

    // Step 2 — scan: select media, trigger, poll to completion. Optional: on an
    // already-scanned demo there may be nothing scannable; naming can still proceed
    // off existing clusters, so a missing scan is recorded but does not abort.
    await timer.step(
      'scan',
      async () => {
        const mediaCheckboxes = page.getByRole('checkbox', { name: MEDIA_CHECKBOX_NAME });
        await mediaCheckboxes.first().waitFor({ state: 'visible', timeout: 30_000 });

        const selectCount = Math.min(await mediaCheckboxes.count(), MAX_SCAN_MEDIA);
        for (let index = 0; index < selectCount; index += 1) {
          await mediaCheckboxes.nth(index).click();
        }

        const scanButton = page.getByRole('button', { name: SCAN_BUTTON_NAME });
        if (selectCount === 0 || !(await scanButton.isEnabled().catch(() => false))) {
          throw new Error('no scannable media / scan CTA disabled');
        }

        await scanButton.click();
        scanTriggered = true;

        const deadline = Date.now() + SCAN_TIMEOUT_MS;
        while (Date.now() < deadline) {
          if (await page.getByText(/Scan complete/i).first().isVisible().catch(() => false)) {
            scanCompleted = true;
            return;
          }
          await page.waitForTimeout(SCAN_POLL_MS);
        }
        throw new Error(`scan did not report completion within ${SCAN_TIMEOUT_MS}ms`);
      },
      { optional: true },
    );
    await capture(page, testInfo.outputPath('walkthrough-2-post-scan.png'), captures, 'walkthrough-2-post-scan.png');

    // Step 3 — review surface reachable: the "Name These People" queue (always-available
    // naming path) or the findings panel's "Review next". This is the moment the visitor
    // can see what to do next.
    await timer.step('review-surface-visible', async () => {
      await page
        .locator(`${TOP_CLUSTERS_SECTION}, ${FINDINGS_PANEL}`)
        .first()
        .waitFor({ state: 'visible', timeout: NAMING_SURFACE_TIMEOUT_MS });
    });
    // Seed-dependent suggestion queues, captured opportunistically for the re-rank read.
    captures['walkthrough-3-suggestions.png'] = await page
      .locator(SUGGESTION_PANEL)
      .first()
      .isVisible()
      .catch(() => false);
    await capture(page, testInfo.outputPath('walkthrough-3-review.png'), captures, 'walkthrough-3-review.png');

    // Step 4 — open the naming form. Primary route: "Name this person" on a top-cluster
    // card. Fallback: the findings panel's "Review next" when it targets a cluster.
    await timer.step('open-naming-form', async () => {
      const nameButton = page.getByRole('button', { name: 'Name this person' }).first();
      if (await nameButton.isVisible().catch(() => false)) {
        await nameButton.click();
      } else {
        await page.getByRole('button', { name: /Review next/ }).click();
      }
      await page.locator(LABELING_PANEL).waitFor({ state: 'visible', timeout: 15_000 });
    });
    await capture(page, testInfo.outputPath('walkthrough-4-naming-form.png'), captures, 'walkthrough-4-naming-form.png');

    // Step 5 — name the person and save. Success = the labeling panel closes (the
    // panel's onLabel → close dispatch) and the unlabeled queue no longer offers the
    // same card — the visitor's first named person now exists.
    await timer.step('name-first-person', async () => {
      await page.getByPlaceholder('Enter name...').fill(visitorName);
      await page.getByRole('button', { name: 'Save' }).click();
      await page.locator(LABELING_PANEL).waitFor({ state: 'hidden', timeout: 30_000 });
    });
    timeToFirstNamedPersonMs = timer.elapsedMs();
    firstNamedPersonReached = true;
    await capture(page, testInfo.outputPath('walkthrough-5-named.png'), captures, 'walkthrough-5-named.png');

    // Step 6 — confirm the person landed: the roster page lists the new name.
    await timer.step(
      'confirm-on-roster',
      async () => {
        await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-roster'));
        await page.getByText(visitorName).first().waitFor({ state: 'visible', timeout: 30_000 });
      },
      { optional: true },
    );
    await capture(page, testInfo.outputPath('walkthrough-6-roster.png'), captures, 'walkthrough-6-roster.png');

    expect(firstNamedPersonReached, 'walkthrough must reach a first named person').toBeTruthy();
  } finally {
    // The manifest must be written even when a step threw — a failed walkthrough is
    // itself gate evidence. Never touch `page` here (it may be closed).
    const manifest: FirstVisitorWalkthroughManifest = {
      task_ref: taskRef,
      captured_at: new Date().toISOString(),
      base_url: baseURL ?? 'unknown',
      deploy_commit_sha: deployCommitSha,
      steps: timer.steps,
      time_to_first_named_person_ms: timeToFirstNamedPersonMs,
      first_named_person_reached: firstNamedPersonReached,
      scan_triggered: scanTriggered,
      scan_completed: scanCompleted,
      captures,
      verdict: firstNamedPersonReached ? 'pass' : 'fail',
    };

    await fs.writeFile(testInfo.outputPath('walkthrough-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
    await fs.writeFile(testInfo.outputPath(WALKTHROUGH_FRAGMENT_FILENAME), renderWalkthroughLogFragment(manifest));
  }
});
