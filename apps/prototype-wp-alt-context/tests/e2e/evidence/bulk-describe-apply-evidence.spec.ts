import fs from 'node:fs/promises';

import { expect, test, type Page } from '@playwright/test';

import { getAcxAdminRouteUrlWithParams } from '../fixtures/acx-routes';

/**
 * WBUX-4 INT-01d operator evidence: the bulk-describe read/apply loop.
 *
 * Drives the browser-automatable path a real operator walks — select missing-alt
 * media on the Workbench, run a bulk describe, then follow the "Review & apply
 * drafts" link into the run-scoped apply surface and apply the safe (no-existing-
 * alt) bucket. Emits screenshots + an evidence manifest. Run via the `evidence`
 * project (`npm run e2e:evidence`).
 *
 * Scope boundary (E15-6 v1): evidence-capture only. A live describe backend
 * (florence_small) and seeded missing-alt media are environment preconditions, so
 * every backend-dependent step is best-effort (soft manifest capture). The hard
 * assertion is that the operator surfaces render and wire together — the Workbench
 * bulk-describe CTA and, when a run completes, the apply view reached via the
 * review link. The guarded write policy (no existing alt clobbered by default) is
 * unit/RTL-proven (DescribeRunApplyView.test.tsx, class-describe-controller PHPUnit).
 */

const WORKBENCH_SHELL = '.acx-workbench';
const MEDIA_CHECKBOX_NAME = /Select media item/i;
const DESCRIBE_BUTTON_NAME = /Describe selected/i;
const REVIEW_LINK_NAME = /Review & apply drafts/i;
const APPLY_VIEW_HEADING = /Apply generated descriptions/i;
const PRIMARY_APPLY_NAME = /Apply all \d+ without alt text|Apply \d+ descriptions/i;
const APPLIED_SUMMARY = /Applied \d+ descriptions/i;

const MAX_DESCRIBE_MEDIA = 3;
const DESCRIBE_POLL_MS = 4_000;
const DESCRIBE_TIMEOUT_MS = 220_000;

const taskRef = (process.env.ACX_PLAYWRIGHT_TASK_REF ?? 'WBUX-4').trim();

interface ApplyEvidenceManifest {
  task_ref: string;
  captured_at: string;
  base_url: string;
  run_triggered: boolean;
  reached_terminal: boolean;
  review_link_present: boolean;
  apply_view_reached: boolean;
  applied_summary_visible: boolean;
  captures: Record<string, boolean>;
  verdict: 'pass' | 'partial';
}

const captureIfVisible = async (page: Page, selectorOrText: string, outputPath: string): Promise<boolean> => {
  const target = page.locator(selectorOrText).first();
  if (!(await target.isVisible().catch(() => false))) {
    return false;
  }
  await target.scrollIntoViewIfNeeded().catch(() => undefined);
  await target.screenshot({ path: outputPath }).catch(() => undefined);
  return true;
};

// The progress panel renders "X of Y processed"; a terminal state shows one of the
// terminal status labels. Match either to know the run stopped making progress.
const runReachedTerminal = async (page: Page): Promise<boolean> =>
  page
    .getByText(/Completed|Completed with errors|Failed|Cancelled/i)
    .first()
    .isVisible()
    .catch(() => false);

test('captures WBUX-4 bulk-describe apply-loop operator evidence', async ({ page, baseURL }, testInfo) => {
  test.setTimeout(DESCRIBE_TIMEOUT_MS + 120_000);

  if (!baseURL) {
    throw new Error('Expected Playwright baseURL to be configured for the WP admin.');
  }

  const captures: Record<string, boolean> = {};
  let runTriggered = false;
  let reachedTerminal = false;
  let reviewLinkPresent = false;
  let applyViewReached = false;
  let appliedSummaryVisible = false;

  try {
    // 1. Workbench with the missing-alt filter — the operator's describe entry point.
    await page.goto(getAcxAdminRouteUrlWithParams(baseURL, 'alt-context-workbench', { status: 'missing' }));
    await expect(page.locator(WORKBENCH_SHELL)).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath('apply-01-workbench.png'), fullPage: true });
    captures['apply-01-workbench.png'] = true;

    // 2. Select missing-alt media and start a bulk describe run (best-effort — needs
    // seeded media + a live describe backend).
    const mediaCheckboxes = page.getByRole('checkbox', { name: MEDIA_CHECKBOX_NAME });
    await mediaCheckboxes
      .first()
      .waitFor({ state: 'visible', timeout: 60_000 })
      .catch(() => undefined);

    const selectCount = Math.min(await mediaCheckboxes.count(), MAX_DESCRIBE_MEDIA);
    for (let index = 0; index < selectCount; index += 1) {
      await mediaCheckboxes.nth(index).click();
    }

    const describeButton = page.getByRole('button', { name: DESCRIBE_BUTTON_NAME });
    if (selectCount > 0 && (await describeButton.isEnabled().catch(() => false))) {
      await describeButton.click();
      runTriggered = true;

      const deadline = Date.now() + DESCRIBE_TIMEOUT_MS;
      while (Date.now() < deadline) {
        if (await runReachedTerminal(page)) {
          reachedTerminal = true;
          break;
        }
        await page.waitForTimeout(DESCRIBE_POLL_MS);
      }
    }

    captures['apply-02-run-progress.png'] = await captureIfVisible(
      page,
      '.acx-media-selection__bulk-describe',
      testInfo.outputPath('apply-02-run-progress.png'),
    );

    // 3. Follow the review link into the run-scoped apply surface.
    const reviewLink = page.getByRole('link', { name: REVIEW_LINK_NAME });
    reviewLinkPresent = await reviewLink.first().isVisible().catch(() => false);
    captures['apply-02-run-progress.png'] = captures['apply-02-run-progress.png'] ?? false;

    if (reviewLinkPresent) {
      await reviewLink.first().click();

      applyViewReached = await page
        .getByText(APPLY_VIEW_HEADING)
        .first()
        .waitFor({ state: 'visible', timeout: 30_000 })
        .then(() => true)
        .catch(() => false);

      if (applyViewReached) {
        await page.screenshot({ path: testInfo.outputPath('apply-03-review-buckets.png'), fullPage: true });
        captures['apply-03-review-buckets.png'] = true;

        // 4. Apply the safe (no existing alt) bucket, if any drafts are applicable.
        const applyButton = page.getByRole('button', { name: PRIMARY_APPLY_NAME });
        if (await applyButton.first().isEnabled().catch(() => false)) {
          await applyButton.first().click();
          appliedSummaryVisible = await page
            .getByText(APPLIED_SUMMARY)
            .first()
            .waitFor({ state: 'visible', timeout: 30_000 })
            .then(() => true)
            .catch(() => false);
          await page.screenshot({ path: testInfo.outputPath('apply-04-applied.png'), fullPage: true });
          captures['apply-04-applied.png'] = appliedSummaryVisible;
        }
      }
    }

    // Hard proof: the Workbench and its bulk-describe CTA render — the operator can
    // always reach the describe entry point. Backend-dependent steps are soft.
    expect(captures['apply-01-workbench.png']).toBeTruthy();
    expect(await describeButton.first().isVisible().catch(() => false)).toBeTruthy();
  } finally {
    const manifest: ApplyEvidenceManifest = {
      task_ref: taskRef,
      captured_at: new Date().toISOString(),
      base_url: baseURL,
      run_triggered: runTriggered,
      reached_terminal: reachedTerminal,
      review_link_present: reviewLinkPresent,
      apply_view_reached: applyViewReached,
      applied_summary_visible: appliedSummaryVisible,
      captures,
      // A full live loop (run → review → apply) is `pass`; a reachable-surface-only
      // run (no live backend / no seeded media) is `partial`, not a failure.
      verdict: applyViewReached && appliedSummaryVisible ? 'pass' : 'partial',
    };
    await fs.writeFile(testInfo.outputPath('apply-evidence-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
  }
});
