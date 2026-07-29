import AxeBuilder from '@axe-core/playwright';
import { expect, type Page } from '@playwright/test';

type BlockingImpact = 'serious' | 'critical';
/** Axe violation/incomplete row from analyze(); exported for unit fixtures. */
export type AxeResultEntry = Awaited<ReturnType<AxeBuilder['analyze']>>['violations'][number];

/**
 * Serious/critical axe impacts are blocking; minor/moderate are not.
 * Exported so the filter can be unit-pinned without a Playwright page [TEST-15].
 */
export const isBlockingImpact = (impact: string | null): impact is BlockingImpact => {
  return impact === 'serious' || impact === 'critical';
};

const formatViolationSummary = (entries: AxeResultEntry[]): string => {
  return entries
    .map((entry) => {
      const nodes = entry.nodes.map((node) => node.target.join(' ')).join(', ');

      return `${entry.id} [${entry.impact ?? 'unknown'}] ${entry.help} :: ${nodes}`;
    })
    .join('\n');
};

/**
 * Fail when axe left serious/critical findings in `results.incomplete`.
 *
 * Pure over the incomplete list so vitest can pin the gate without a browser.
 * Behaviour matches the incomplete half of {@link assertNoBlockingViolations}.
 */
export const assertNoBlockingIncompletes = (incomplete: AxeResultEntry[]): void => {
  const blockingIncompletes = incomplete.filter((entry) => isBlockingImpact(entry.impact ?? null));

  expect(
    blockingIncompletes,
    blockingIncompletes.length === 0
      ? 'Expected no serious or critical axe incompletes.'
      : `Expected no serious or critical axe incompletes:\n${formatViolationSummary(blockingIncompletes)}`,
  ).toHaveLength(0);
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
 */
export const assertNoBlockingViolations = async (page: Page, scopeSelector: string): Promise<void> => {
  const results = await new AxeBuilder({ page }).include(scopeSelector).analyze();
  const blockingViolations = results.violations.filter((violation) => isBlockingImpact(violation.impact ?? null));

  expect(
    blockingViolations,
    blockingViolations.length === 0
      ? 'Expected no serious or critical axe violations.'
      : `Expected no serious or critical axe violations:\n${formatViolationSummary(blockingViolations)}`,
  ).toHaveLength(0);

  assertNoBlockingIncompletes(results.incomplete);
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
