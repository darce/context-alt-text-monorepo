import AxeBuilder from '@axe-core/playwright';
import { expect, type Page } from '@playwright/test';

type BlockingImpact = 'serious' | 'critical';

const BLOCKING_IMPACTS: ReadonlySet<BlockingImpact> = new Set(['serious', 'critical']);

const isBlockingImpact = (impact: string | null): impact is BlockingImpact => {
  return impact === 'serious' || impact === 'critical';
};

const formatViolationSummary = (
  violations: Awaited<ReturnType<AxeBuilder['analyze']>>['violations'],
): string => {
  return violations
    .map((violation) => {
      const nodes = violation.nodes.map((node) => node.target.join(' ')).join(', ');

      return `${violation.id} [${violation.impact ?? 'unknown'}] ${violation.help} :: ${nodes}`;
    })
    .join('\n');
};

export const assertNoBlockingViolations = async (page: Page, scopeSelector: string): Promise<void> => {
  const results = await new AxeBuilder({ page }).include(scopeSelector).analyze();
  const blockingViolations = results.violations.filter(
    (violation) => isBlockingImpact(violation.impact) && BLOCKING_IMPACTS.has(violation.impact),
  );

  expect(
    blockingViolations,
    blockingViolations.length === 0
      ? 'Expected no serious or critical axe violations.'
      : `Expected no serious or critical axe violations:\n${formatViolationSummary(blockingViolations)}`,
  ).toHaveLength(0);
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