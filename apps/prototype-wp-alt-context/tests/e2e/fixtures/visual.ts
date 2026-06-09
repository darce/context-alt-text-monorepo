import { expect, type Page } from '@playwright/test';

interface StableHeightOptions {
  stableForMs?: number;
  pollMs?: number;
  timeout?: number;
}

/**
 * Block until an element's rendered height stops changing.
 *
 * WHY: the workbench hydrates its media table, per-row detail, and identity
 * data through a cascade of async queries that fire after mount. That cascade
 * grows `.acx-workbench` for several seconds — past Playwright's 5s
 * stable-screenshot window — so `toHaveScreenshot` fails with "Failed to take
 * two consecutive stable screenshots". Settling the layout ourselves (with a
 * timeout we control) before snapshotting removes that race. The empty/idle
 * workbench has no perpetual layout polling, so height does converge.
 */
export const waitForStableHeight = async (
  page: Page,
  selector: string,
  { stableForMs = 600, pollMs = 150, timeout = 30_000 }: StableHeightOptions = {},
): Promise<void> => {
  const requiredSamples = Math.max(2, Math.ceil(stableForMs / pollMs));
  await page.waitForFunction(
    ({ selector: sel, samples }) => {
      const el = document.querySelector(sel);
      if (!el) {
        return false;
      }
      const tracker = window as unknown as { __acxStableHeight?: number; __acxStableCount?: number };
      const height = Math.round(el.getBoundingClientRect().height);
      if (tracker.__acxStableHeight === height) {
        tracker.__acxStableCount = (tracker.__acxStableCount ?? 0) + 1;
      } else {
        tracker.__acxStableHeight = height;
        tracker.__acxStableCount = 0;
      }
      return (tracker.__acxStableCount ?? 0) >= samples;
    },
    { selector, samples: requiredSamples },
    { polling: pollMs, timeout },
  );
};

/**
 * Drive the workbench to a deterministic, fully-hydrated layout before a visual
 * baseline is captured: flush the initial query cascade (network idle), wait
 * out the media-table skeleton rows, ensure web fonts are applied, then settle
 * on a stable height.
 */
export const stabilizeWorkbench = async (page: Page, shellSelector: string): Promise<void> => {
  await page.waitForLoadState('networkidle');
  await expect(page.locator('.acx-media-selection__skeleton-row')).toHaveCount(0);
  await page.evaluate(() => document.fonts.ready);
  await waitForStableHeight(page, shellSelector);
};
