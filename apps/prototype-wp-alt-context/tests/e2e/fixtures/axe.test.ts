import { describe, expect, it } from 'vitest';

import {
  assertNoBlockingAxeResults,
  assertNoBlockingIncompletes,
  isBlockingImpact,
  type AxeImpactEntry,
  type AssertEmptyEntries,
} from './axe-impact';

type AxeImpact = 'minor' | 'moderate' | 'serious' | 'critical';

/**
 * Vitest-side assertEmpty: throw Error with the gate message when non-empty.
 * Mirrors Playwright expect(…).toHaveLength(0) failure semantics without
 * importing @playwright/test into this pure suite.
 */
const throwIfNonEmpty: AssertEmptyEntries = (entries, message) => {
  if (entries.length !== 0) {
    throw new Error(message);
  }
};

/** Minimal axe incomplete/violation entry for pure unit pins (structural fixture). */
const axeEntry = (impact: AxeImpact | null | undefined, id = 'aria-prohibited-attr'): AxeImpactEntry => ({
  id,
  impact: impact ?? undefined,
  help: `help for ${id}`,
  nodes: [
    {
      target: ['#fixture'],
    },
  ],
});

describe('isBlockingImpact', () => {
  it('treats serious and critical as blocking [TEST-15]', () => {
    expect(isBlockingImpact('serious')).toBe(true);
    expect(isBlockingImpact('critical')).toBe(true);
  });

  it('treats minor and moderate as non-blocking [TEST-15]', () => {
    expect(isBlockingImpact('minor')).toBe(false);
    expect(isBlockingImpact('moderate')).toBe(false);
  });

  it('rejects null and unknown impacts', () => {
    expect(isBlockingImpact(null)).toBe(false);
    expect(isBlockingImpact('unknown')).toBe(false);
  });
});

describe('assertNoBlockingIncompletes', () => {
  it('throws when results include a serious incomplete [TEST-15]', () => {
    expect(() => assertNoBlockingIncompletes([axeEntry('serious')], throwIfNonEmpty)).toThrow(
      /Expected no serious or critical axe incompletes/,
    );
  });

  it('throws when results include a critical incomplete', () => {
    expect(() =>
      assertNoBlockingIncompletes([axeEntry('critical', 'button-name')], throwIfNonEmpty),
    ).toThrow(/Expected no serious or critical axe incompletes/);
  });

  it('does not throw when incompletes are only minor [TEST-15]', () => {
    expect(() =>
      assertNoBlockingIncompletes([axeEntry('minor', 'color-contrast')], throwIfNonEmpty),
    ).not.toThrow();
  });

  it('does not throw when incompletes are only moderate', () => {
    expect(() => assertNoBlockingIncompletes([axeEntry('moderate', 'region')], throwIfNonEmpty)).not.toThrow();
  });

  it('does not throw on an empty incomplete list', () => {
    expect(() => assertNoBlockingIncompletes([], throwIfNonEmpty)).not.toThrow();
  });
});

/**
 * BR-88b / MUT12b wiring pin: assertNoBlockingAxeResults must gate incompletes
 * even when violations is empty. Removing only the incomplete call from that
 * function (the pure half of assertNoBlockingViolations) must turn these red.
 */
describe('assertNoBlockingAxeResults wiring [BR-88b]', () => {
  it('throws on empty violations + serious incomplete [TEST-15]', () => {
    expect(() =>
      assertNoBlockingAxeResults(
        { violations: [], incomplete: [axeEntry('serious')] },
        throwIfNonEmpty,
      ),
    ).toThrow(/Expected no serious or critical axe incompletes/);
  });

  it('throws on empty violations + critical incomplete [TEST-15]', () => {
    expect(() =>
      assertNoBlockingAxeResults(
        { violations: [], incomplete: [axeEntry('critical', 'button-name')] },
        throwIfNonEmpty,
      ),
    ).toThrow(/Expected no serious or critical axe incompletes/);
  });

  it('does not throw on empty violations + minor incomplete', () => {
    expect(() =>
      assertNoBlockingAxeResults(
        { violations: [], incomplete: [axeEntry('minor', 'color-contrast')] },
        throwIfNonEmpty,
      ),
    ).not.toThrow();
  });

  it('does not throw on empty violations + moderate incomplete', () => {
    expect(() =>
      assertNoBlockingAxeResults(
        { violations: [], incomplete: [axeEntry('moderate', 'region')] },
        throwIfNonEmpty,
      ),
    ).not.toThrow();
  });

  it('still throws on serious violations with empty incomplete', () => {
    expect(() =>
      assertNoBlockingAxeResults(
        { violations: [axeEntry('serious', 'image-alt')], incomplete: [] },
        throwIfNonEmpty,
      ),
    ).toThrow(/Expected no serious or critical axe violations/);
  });
});
