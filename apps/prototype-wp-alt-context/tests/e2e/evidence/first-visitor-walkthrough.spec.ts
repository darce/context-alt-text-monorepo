import fs from 'node:fs/promises';

import { expect, test, type Locator, type Page } from '@playwright/test';

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
 * instrumented rehearsal, not its replacement (see `manifest.harness`).
 *
 * Naming paths (grounded in TopClusterCard/TopClustersSection/ClusterLabelingPanel
 * and their unit tests), tried in priority order:
 *   1. `top-cluster-card` — an unlabeled card's "Name this person" title action
 *      opens ClusterLabelingPanel; the name is committed through the creatable
 *      Combobox (trigger → CommandInput → Create/option commit → Save).
 *   2. `suggested-label-confirm` — a suggested-label card ("Is this X?") is named
 *      by its "Yes" confirm button (TopClustersSection.confirmSuggestedLabelMutation
 *      labels/merges the cluster directly; no labeling panel is involved).
 *   3. `review-next` — the findings panel's "Review next" opens the labeling panel
 *      only when its next action targets a cluster (NEXT_ACTION_KIND.CLUSTER, hint
 *      "Name the largest unlabeled group"); other kinds merely scroll to the queues,
 *      so this route is guarded by waiting for the panel and falling through.
 * If no route is available the run fails with a diagnostic in the manifest —
 * a failed walkthrough is itself gate evidence and must say why.
 */

const WORKBENCH_SHELL = '.acx-workbench';
const SCAN_BUTTON_NAME = /Analyze selected media/i;
const MEDIA_CHECKBOX_NAME = /Select media item/i;
const TOP_CLUSTERS_SECTION = '.acx-top-clusters-section';
const TOP_CLUSTER_CARD = '.acx-top-cluster-card';
// TopClustersSection renders `--empty` variants (unavailable / no clusters / all
// labeled / singletons-only) that contain no cards; only cards inside the
// non-empty section are actionable.
const ACTIONABLE_TOP_CLUSTER_CARD = `${TOP_CLUSTERS_SECTION}:not(${TOP_CLUSTERS_SECTION}--empty) ${TOP_CLUSTER_CARD}`;
const LABELING_PANEL = '.acx-cluster-labeling-panel';
const FINDINGS_PANEL = '.acx-findings-panel';
// WorkbenchFindingsPanel skeleton variants; "Review next" only exists in the base panel.
const ACTIONABLE_FINDINGS_PANEL = `${FINDINGS_PANEL}:not(${FINDINGS_PANEL}--loading):not(${FINDINGS_PANEL}--error):not(${FINDINGS_PANEL}--unavailable)`;
const SUGGESTION_PANEL = '.acx-suggestion-panel';
const SUGGESTED_CARD_CONFIRM = '.acx-top-cluster-card__confirm-btn';

const MAX_SCAN_MEDIA = 5;
const SCAN_POLL_MS = 5_000;
const SCAN_TIMEOUT_MS = 240_000;
const NAMING_SURFACE_TIMEOUT_MS = 120_000;
// BR-04: a collapsed media queue must not burn the full scan-step budget — the
// summary bar's "Show media table" affordance is detected first, so the checkbox
// wait only needs to cover a rendered (expanded) table.
const MEDIA_TABLE_WAIT_MS = 10_000;
const SAVE_CLOSE_TIMEOUT_MS = 30_000;
const REVIEW_NEXT_PANEL_WAIT_MS = 10_000;

// Mirrors playwright.config.ts `evidence` project (headless: false, launchOptions.slowMo).
const HARNESS_INFO = {
  headed: true,
  slow_mo_ms: 200,
  note: 'instrumented rehearsal; timings not comparable to the unaided human baseline',
};

const NO_NAMING_ROUTE_DIAGNOSTIC =
  'no unlabeled cluster available — reseed or unlabel one ' +
  '(no "Name this person" card, no suggested-label card, and "Review next" did not open the labeling panel)';

const taskRef = (process.env.ACX_PLAYWRIGHT_TASK_REF ?? 'E21-13').trim();
const deployCommitSha = (process.env.ACX_DEPLOY_COMMIT_SHA ?? '').trim() || null;
const visitorName = (process.env.ACX_E2E_WALKTHROUGH_NAME ?? '').trim() || `Walkthrough Visitor ${taskRef}`;

const capture = async (page: Page, outputPath: string, captures: Record<string, boolean>, key: string) => {
  captures[key] = await page
    .screenshot({ path: outputPath, fullPage: true })
    .then(() => true)
    .catch(() => false);
};

type NamingRoute =
  | { kind: 'top-cluster-card' }
  | { kind: 'suggested-label-confirm'; card: Locator; suggestedLabel: string }
  | { kind: 'review-next' };

/**
 * Commit a name through the creatable Combobox the way the component does it
 * (grounded in combobox.tsx + ClusterLabelingPanel.test.tsx `selectOrCreateName`):
 * click the role=combobox trigger button, type into the popover's CommandInput
 * ("Search people..." — every keystroke forwards via onValueChange → labelInput),
 * then commit: the CommandEmpty `Create "<name>"` button (onCreate + close) when no
 * option matches, a matching CommandItem (onValueChange(option.label) + close)
 * otherwise, or Escape as a last resort (labelInput is already set live; Escape
 * only closes the popover).
 */
const commitNameViaCombobox = async (page: Page, panel: Locator, name: string): Promise<string> => {
  const comboboxTrigger = panel.getByRole('combobox', { name: 'Name' });
  await comboboxTrigger.click();

  // The popover content renders through a Radix portal, so search page-wide.
  const searchInput = page.getByPlaceholder('Search people...');
  await searchInput.waitFor({ state: 'visible', timeout: 10_000 });
  await searchInput.fill(name);

  const createButton = page.getByRole('button', { name: `Create "${name}"` });
  const matchingOption = page.locator('.acx-combobox__item').filter({ hasText: name }).first();
  if (await createButton.isVisible().catch(() => false)) {
    await createButton.click();
  } else if (await matchingOption.isVisible().catch(() => false)) {
    // Roster already knows this name (e.g. a re-run): selecting the option commits
    // its label and closes the popover.
    await matchingOption.click();
  } else {
    await page.keyboard.press('Escape');
  }
  await searchInput.waitFor({ state: 'hidden', timeout: 10_000 });

  // The trigger echoes the committed labelInput — the exact value Save will submit.
  const committed = ((await comboboxTrigger.innerText().catch(() => '')) ?? '').trim();
  return committed.length > 0 ? committed : name;
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
  let namingRoute: string | null = null;
  let diagnostic: string | null = null;
  let namedPersonLabel = visitorName;

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
        // When findings already exist, ScanTabContent collapses the media queue to
        // the MediaSummaryBar — expand it instead of waiting on absent checkboxes.
        const expandMediaTable = page.getByRole('button', { name: 'Show media table' });
        if (await expandMediaTable.isVisible().catch(() => false)) {
          await expandMediaTable.click();
        }

        const mediaCheckboxes = page.getByRole('checkbox', { name: MEDIA_CHECKBOX_NAME });
        await mediaCheckboxes.first().waitFor({ state: 'visible', timeout: MEDIA_TABLE_WAIT_MS });

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

    // Step 3 — review surface ACTIONABLE, not merely painted: either a real
    // top-cluster card inside a non-empty "Name These People" section, or an
    // enabled "Review next" in the loaded findings panel. Loading/error/empty
    // variants are excluded, so the recorded timing is the moment the visitor
    // can actually act, not when a skeleton first renders.
    await timer.step('review-surface-actionable', async () => {
      const actionableCard = page.locator(ACTIONABLE_TOP_CLUSTER_CARD).first();
      const enabledReviewNext = page
        .locator(`${ACTIONABLE_FINDINGS_PANEL} button:enabled`)
        .filter({ hasText: 'Review next' })
        .first();
      await actionableCard.or(enabledReviewNext).first().waitFor({
        state: 'visible',
        timeout: NAMING_SURFACE_TIMEOUT_MS,
      });
    });
    // Seed-dependent suggestion queues, captured opportunistically for the re-rank read.
    captures['walkthrough-3-suggestions.png'] = await page
      .locator(SUGGESTION_PANEL)
      .first()
      .isVisible()
      .catch(() => false);
    await capture(page, testInfo.outputPath('walkthrough-3-review.png'), captures, 'walkthrough-3-review.png');

    // Step 4 — resolve the naming route in priority order (see header comment).
    const route = await timer.step('open-naming-form', async (): Promise<NamingRoute> => {
      // (a) Unlabeled top-cluster card: title action "Name this person" opens the panel.
      const nameButton = page.getByRole('button', { name: 'Name this person' }).first();
      if (await nameButton.isVisible().catch(() => false)) {
        await nameButton.click();
        await page.locator(LABELING_PANEL).waitFor({ state: 'visible', timeout: 15_000 });
        return { kind: 'top-cluster-card' };
      }

      // (b) Suggested-label card ("Is this X?"): its "Yes" confirms the suggested
      // name directly (TopClustersSection labels/merges the cluster; no panel opens).
      const suggestedCard = page
        .locator(ACTIONABLE_TOP_CLUSTER_CARD)
        .filter({ has: page.locator(SUGGESTED_CARD_CONFIRM) })
        .first();
      if (await suggestedCard.isVisible().catch(() => false)) {
        const title = ((await suggestedCard.locator('.acx-top-cluster-card__title').innerText().catch(() => '')) ?? '')
          .trim();
        const suggestedLabel = /^Is this (.+)\?$/.exec(title)?.[1]?.trim() ?? null;
        if (suggestedLabel) {
          return { kind: 'suggested-label-confirm', card: suggestedCard, suggestedLabel };
        }
      }

      // (c) "Review next" — only opens the labeling panel when the next action is a
      // cluster (hint: "Name the largest unlabeled group"); other kinds scroll to the
      // queues instead, so guard with a bounded wait and fall through on no-show.
      const reviewNext = page
        .locator(`${ACTIONABLE_FINDINGS_PANEL} button:enabled`)
        .filter({ hasText: 'Review next' })
        .first();
      if (await reviewNext.isVisible().catch(() => false)) {
        await reviewNext.click();
        const panelOpened = await page
          .locator(LABELING_PANEL)
          .waitFor({ state: 'visible', timeout: REVIEW_NEXT_PANEL_WAIT_MS })
          .then(() => true)
          .catch(() => false);
        if (panelOpened) {
          return { kind: 'review-next' };
        }
      }

      diagnostic = NO_NAMING_ROUTE_DIAGNOSTIC;
      throw new Error(NO_NAMING_ROUTE_DIAGNOSTIC);
    });
    if (!route) {
      throw new Error(NO_NAMING_ROUTE_DIAGNOSTIC);
    }
    namingRoute = route.kind;
    await capture(page, testInfo.outputPath('walkthrough-4-naming-form.png'), captures, 'walkthrough-4-naming-form.png');

    // Step 5 — name the person.
    await timer.step('name-first-person', async () => {
      if (route.kind === 'suggested-label-confirm') {
        // Confirming "Is this X?" IS naming a person: the mutation labels (or merges)
        // the cluster and optimistically removes the card from the naming queue.
        namedPersonLabel = route.suggestedLabel;
        await route.card.locator(SUGGESTED_CARD_CONFIRM).click();
        await route.card.waitFor({ state: 'hidden', timeout: SAVE_CLOSE_TIMEOUT_MS });
        return;
      }

      // Labeling-panel routes: commit the name through the Combobox, then Save.
      const panel = page.locator(LABELING_PANEL);
      namedPersonLabel = await commitNameViaCombobox(page, panel, visitorName);

      // Save is disabled until labelInput is non-empty — the combobox commit above
      // is what enables it (ClusterLabelingPanel `disabled={!labelInput.trim() ...}`).
      const saveButton = panel.getByRole('button', { name: 'Save' });
      await expect(saveButton).toBeEnabled();
      await saveButton.click();

      // Success = the panel closes (onLabel → close dispatch). A 409 duplicate save
      // surfaces an inline "Is this X?" merge prompt instead — answering Yes merges
      // into the existing person and then closes (grounded in the panel's tests).
      const deadline = Date.now() + SAVE_CLOSE_TIMEOUT_MS;
      while (Date.now() < deadline) {
        if (await panel.isHidden().catch(() => false)) {
          return;
        }
        const duplicateYes = panel.getByRole('button', { name: 'Yes' });
        if (await duplicateYes.isVisible().catch(() => false)) {
          await duplicateYes.click().catch(() => undefined);
        }
        await page.waitForTimeout(500);
      }
      const inlineError = ((await panel.getByRole('alert').innerText().catch(() => '')) ?? '').trim();
      throw new Error(
        `labeling panel did not close within ${SAVE_CLOSE_TIMEOUT_MS}ms after Save${inlineError ? ` — panel error: ${inlineError}` : ''}`,
      );
    });
    timeToFirstNamedPersonMs = timer.elapsedMs();
    firstNamedPersonReached = true;
    await capture(page, testInfo.outputPath('walkthrough-5-named.png'), captures, 'walkthrough-5-named.png');

    // Step 6 — confirm the person landed: the roster page lists the new name.
    await timer.step(
      'confirm-on-roster',
      async () => {
        await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-roster'));
        await page.getByText(namedPersonLabel).first().waitFor({ state: 'visible', timeout: 30_000 });
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
      harness: HARNESS_INFO,
      steps: timer.steps,
      time_to_first_named_person_ms: timeToFirstNamedPersonMs,
      first_named_person_reached: firstNamedPersonReached,
      scan_triggered: scanTriggered,
      scan_completed: scanCompleted,
      naming_route: namingRoute,
      diagnostic,
      captures,
      verdict: firstNamedPersonReached ? 'pass' : 'fail',
    };

    await fs.writeFile(testInfo.outputPath('walkthrough-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
    await fs.writeFile(testInfo.outputPath(WALKTHROUGH_FRAGMENT_FILENAME), renderWalkthroughLogFragment(manifest));
  }
});
