import AxeBuilder from '@axe-core/playwright';
import { expect, type Page } from '@playwright/test';

import {
  assertNoBlockingAxeResults,
  assertNoBlockingIncompletes as assertNoBlockingIncompletesPure,
  isBlockingImpact,
  type AssertEmptyEntries,
} from './axe-impact';

/** Axe violation/incomplete row from analyze(); exported for unit fixtures. */
export type AxeResultEntry = Awaited<ReturnType<AxeBuilder['analyze']>>['violations'][number];

export { isBlockingImpact, assertNoBlockingAxeResults };
export type { AxeImpactEntry, AxeAnalyzeResultsLike, AssertEmptyEntries, BlockingImpact } from './axe-impact';

/**
 * Playwright-bound empty-assert: preserves the existing expect(…).toHaveLength(0)
 * failure surface for e2e runs [REF-26].
 */
const playwrightAssertEmpty: AssertEmptyEntries = (entries, message) => {
  expect(entries, message).toHaveLength(0);
};

/**
 * Fail when axe left serious/critical findings in `results.incomplete`.
 *
 * Thin Playwright wrapper over the pure gate in {@link ./axe-impact}.
 */
export const assertNoBlockingIncompletes = (incomplete: AxeResultEntry[]): void => {
  assertNoBlockingIncompletesPure(incomplete, playwrightAssertEmpty);
};

/**
 * Gate serious/critical axe findings that would otherwise be invisible.
 *
 * `results.incomplete` means "axe could not fully decide" — not a proven
 * violation. Treating *every* incomplete as a hard failure would be too
 * aggressive for a shared e2e fixture. Failing only on serious/critical
 * incompletes is the chosen contract:
 *
 * - [RLSE-05] silent failure is the worst failure: `aria-prohibited-attr`
 *   lands in incomplete (impact serious) and was invisible to this gate
 *   while real browsers refuse the name. A warn-only path would keep CI green.
 * - [sr-001] never weaken a gate: this *adds* a check; violation filtering
 *   for real `results.violations` is unchanged [REF-26].
 * - Minor/moderate incompletes stay non-blocking (still "could not decide"
 *   noise that operators can inspect in full axe reports).
 *
 * Implementation: run AxeBuilder, then hand results to the pure
 * {@link assertNoBlockingAxeResults} gate (violations + incompletes). Unit
 * tests pin the pure gate's filter behaviour [BR-88b] and pin this shell's
 * wiring by mocking AxeBuilder.analyze with a serious incomplete and asserting
 * assertNoBlockingViolations throws — so dropping the incomplete half from the
 * shell cannot leave the fast suite green [BR-113] [TEST-15].
 */
export const assertNoBlockingViolations = async (page: Page, scopeSelector: string): Promise<void> => {
  const results = await new AxeBuilder({ page }).include(scopeSelector).analyze();
  assertNoBlockingAxeResults(results, playwrightAssertEmpty);
};

export const requireBaseUrl = (baseURL: string | undefined): string => {
  if (!baseURL) {
    throw new Error('Expected Playwright baseURL to be configured for LocalWP admin.');
  }

  return baseURL;
};

export const seededA11yEnabled = (): boolean => {
  return process.env.ACX_E2E_SEEDED === '1' || process.env.ACX_E2E_SEEDED === 'true';
};
