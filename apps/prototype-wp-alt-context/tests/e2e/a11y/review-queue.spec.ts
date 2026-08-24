/**
 * E21-5 Slice 1b — review-queue a11y seed.
 *
 * Keyboard-walk reachability, card-transition live region, target sizes.
 * Advance-focus: authoritative gate is ReviewQueue.test.tsx; e2e is
 * skip-guarded corroboration (≥2 pending, bare toBeFocused, consumes one
 * suggestion against local seed only).
 */
import { expect, test, type Page } from '@playwright/test';

import { requireBaseUrl, seededA11yEnabled } from '../fixtures/axe';
import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';
import { skipUnlessPopulatedWorkbench } from '../fixtures/seeded-state';

const WORKBENCH_SHELL_SELECTOR = '.acx-workbench';
const REVIEW_QUEUE_SELECTOR = '.acx-review-queue';
const REVIEW_CARD_SELECTOR = '[data-testid="acx-review-card"]';

const openWorkbench = async (baseURL: string, page: Page): Promise<void> => {
  await page.goto(getAcxAdminRouteUrl(baseURL, 'alt-context-workbench'));
  await expect(page).toHaveURL(/page=alt-context-workbench/);
  await expect(page.locator(WORKBENCH_SHELL_SELECTOR)).toBeVisible();
};

const tabUntilFocused = async (page: Page, target: ReturnType<Page['locator']>, maxSteps: number): Promise<void> => {
  await page.locator('body').press('Tab');
  let reached = false;
  for (let step = 0; step < maxSteps; step += 1) {
    if (await target.evaluate((el) => el === document.activeElement).catch(() => false)) {
      reached = true;
      break;
    }
    await page.keyboard.press('Tab');
  }
  expect(reached, `Target not keyboard-reachable within ${maxSteps} tab stops`).toBe(true);
  await expect(target).toBeFocused();
};

const skipUnlessReviewQueue = async (page: Page): Promise<void> => {
  const queue = page.locator(REVIEW_QUEUE_SELECTOR);
  const visible = await queue.isVisible().catch(() => false);
  test.skip(!visible, 'Review queue not mounted (no findings surface).');
};

test.describe('review queue a11y (E21-5)', () => {
  test.beforeEach(({ baseURL }) => {
    test.skip(!seededA11yEnabled(), 'Set ACX_E2E_SEEDED=1 to enable seeded review-queue a11y coverage.');
    requireBaseUrl(baseURL);
  });

  test('keyboard walk reaches queue chips, nav, and card primary action', async ({ page, baseURL }) => {
    await openWorkbench(requireBaseUrl(baseURL), page);
    await skipUnlessPopulatedWorkbench(page);
    await skipUnlessReviewQueue(page);

    const closeMatches = page.getByRole('button', { name: /Close matches/i });
    const next = page.getByRole('button', { name: /Next review item|Next/i }).first();
    const primary = page.locator(`${REVIEW_CARD_SELECTOR} .acx-suggestion-card__accept, ${REVIEW_CARD_SELECTOR} button.button-primary`).first();

    const MAX = 80;
    if (await closeMatches.isVisible().catch(() => false)) {
      await tabUntilFocused(page, closeMatches, MAX);
    }
    if (await next.isVisible().catch(() => false)) {
      await tabUntilFocused(page, next, MAX);
    }
    if (await primary.isVisible().catch(() => false)) {
      await tabUntilFocused(page, primary, MAX);
    }
  });

  test('card transition live region has role=status', async ({ page, baseURL }) => {
    await openWorkbench(requireBaseUrl(baseURL), page);
    await skipUnlessPopulatedWorkbench(page);
    await skipUnlessReviewQueue(page);

    const live = page.locator(`${REVIEW_QUEUE_SELECTOR} [role="status"]`);
    await expect(live.first()).toBeVisible();
  });

  test('interactive controls meet target-size floors', async ({ page, baseURL }) => {
    await openWorkbench(requireBaseUrl(baseURL), page);
    await skipUnlessPopulatedWorkbench(page);
    await skipUnlessReviewQueue(page);

    const chip = page.locator(`${REVIEW_QUEUE_SELECTOR} .acx-review-queue__chip`).first();
    const nav = page.locator(`${REVIEW_QUEUE_SELECTOR} .acx-review-queue__nav-button`).first();
    const faceCrop = page.locator(`${REVIEW_QUEUE_SELECTOR} .acx-face-crop-control`).first();
    const accept = page.locator(`${REVIEW_CARD_SELECTOR} .acx-suggestion-card__accept`).first();

    for (const control of [chip, nav, accept]) {
      if (!(await control.isVisible().catch(() => false))) {
        continue;
      }
      const box = await control.boundingBox();
      expect(box, 'control bounding box').not.toBeNull();
      expect(box!.width).toBeGreaterThanOrEqual(24);
      expect(box!.height).toBeGreaterThanOrEqual(24);
    }

    if (await faceCrop.isVisible().catch(() => false)) {
      const box = await faceCrop.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.width).toBeGreaterThanOrEqual(48);
      expect(box!.height).toBeGreaterThanOrEqual(48);
    }
  });

  test('advance-focus lands on next primary (conditional; consumes one local suggestion)', async ({
    page,
    baseURL,
  }) => {
    await openWorkbench(requireBaseUrl(baseURL), page);
    await skipUnlessPopulatedWorkbench(page);
    await skipUnlessReviewQueue(page);

    const cards = page.locator(REVIEW_CARD_SELECTOR);
    await expect(cards).toHaveCount(1);

    const position = page.locator(`${REVIEW_QUEUE_SELECTOR} .acx-review-queue__position`);
    const positionText = (await position.textContent()) ?? '0 of 0';
    const match = /(\d+)\s+of\s+(\d+)/i.exec(positionText);
    const total = match ? Number.parseInt(match[2], 10) : 0;
    test.skip(total < 2, 'Need ≥2 pending suggestions for advance-focus corroboration.');

    const accept = page.locator(`${REVIEW_CARD_SELECTOR} .acx-suggestion-card__accept`).first();
    test.skip(!(await accept.isVisible().catch(() => false)), 'No accept primary on current card kind.');

    await accept.focus();
    await expect(accept).toBeFocused();
    await page.keyboard.press('Enter');

    // Bare toBeFocused immediately after action — never re-tab.
    const nextPrimary = page.locator(`${REVIEW_CARD_SELECTOR} .acx-suggestion-card__accept`).first();
    await expect(nextPrimary).toBeFocused({ timeout: 5_000 });
  });
});
