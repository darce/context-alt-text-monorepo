/**
 * Pure axe severity gate — no Playwright, no @axe-core/playwright.
 *
 * The Playwright-bound wrapper lives in `axe.ts` (AxeBuilder + expect).
 * This module owns the severity predicate, the incomplete/violations filter,
 * and the full results gate so vitest can pin behaviour without loading
 * playwright-core into the jsdom fork [BR-99].
 */

export type BlockingImpact = 'serious' | 'critical';

/**
 * Minimal structural shape of an axe violation/incomplete row.
 * Intentionally a subset of axe-core's Result so pure unit fixtures need no
 * Playwright types. `target` is wider than string[] because axe-core's
 * UnlabelledFrameSelector is (string | nested selector)[].
 */
export interface AxeImpactEntry {
  id: string;
  impact?: string | null;
  help: string;
  nodes: readonly { target: readonly unknown[] }[];
}

/** Shape of `AxeBuilder.analyze()` results that the gate inspects. */
export interface AxeAnalyzeResultsLike {
  violations: readonly AxeImpactEntry[];
  incomplete: readonly AxeImpactEntry[];
}

/**
 * Caller-supplied empty-assert. Playwright's `expect(x, msg).toHaveLength(0)`
 * and a vitest-side `if (x.length) throw` both fit. Keeps this module free of
 * any test-runner import.
 */
export type AssertEmptyEntries = (entries: AxeImpactEntry[], message: string) => void;

/**
 * Serious/critical axe impacts are blocking; minor/moderate/null are not.
 * Exported so the filter can be unit-pinned without a Playwright page [TEST-15].
 */
export const isBlockingImpact = (impact: string | null): impact is BlockingImpact => {
  return impact === 'serious' || impact === 'critical';
};

export const formatAxeEntrySummary = (entries: readonly AxeImpactEntry[]): string => {
  return entries
    .map((entry) => {
      const nodes = entry.nodes.map((node) => node.target.join(' ')).join(', ');

      return `${entry.id} [${entry.impact ?? 'unknown'}] ${entry.help} :: ${nodes}`;
    })
    .join('\n');
};

export const filterBlockingEntries = <T extends AxeImpactEntry>(entries: readonly T[]): T[] => {
  return entries.filter((entry) => isBlockingImpact(entry.impact ?? null));
};

/**
 * Fail when axe left serious/critical findings in `results.incomplete`.
 *
 * Pure over the incomplete list so vitest can pin the gate without a browser.
 * Behaviour matches the incomplete half of {@link assertNoBlockingAxeResults}.
 */
export const assertNoBlockingIncompletes = (
  incomplete: readonly AxeImpactEntry[],
  assertEmpty: AssertEmptyEntries,
): void => {
  const blockingIncompletes = filterBlockingEntries(incomplete);

  assertEmpty(
    blockingIncompletes,
    blockingIncompletes.length === 0
      ? 'Expected no serious or critical axe incompletes.'
      : `Expected no serious or critical axe incompletes:\n${formatAxeEntrySummary(blockingIncompletes)}`,
  );
};

/**
 * Full gate over already-collected axe analyze() results.
 *
 * Checks `violations` then `incomplete` for serious/critical findings.
 * This is the function `assertNoBlockingViolations` must call after analyze —
 * unit-pinning it closes the MUT12b hole where the incomplete half could be
 * dropped from the Playwright wrapper while every incomplete-only unit test
 * stayed green [BR-88b] [TEST-15].
 */
export const assertNoBlockingAxeResults = (
  results: AxeAnalyzeResultsLike,
  assertEmpty: AssertEmptyEntries,
): void => {
  const blockingViolations = filterBlockingEntries(results.violations);

  assertEmpty(
    blockingViolations,
    blockingViolations.length === 0
      ? 'Expected no serious or critical axe violations.'
      : `Expected no serious or critical axe violations:\n${formatAxeEntrySummary(blockingViolations)}`,
  );

  assertNoBlockingIncompletes(results.incomplete, assertEmpty);
};
