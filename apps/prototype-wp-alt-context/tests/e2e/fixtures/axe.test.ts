import { describe, expect, it } from 'vitest';

import { assertNoBlockingIncompletes, isBlockingImpact, type AxeResultEntry } from './axe';

type AxeImpact = NonNullable<AxeResultEntry['impact']>;

/** Minimal axe incomplete entry for pure unit pins (structural fixture). */
const incompleteEntry = (impact: AxeImpact | null | undefined, id = 'aria-prohibited-attr'): AxeResultEntry =>
  ({
    id,
    impact: impact ?? undefined,
    help: `help for ${id}`,
    description: `description for ${id}`,
    helpUrl: 'https://example.test/axe',
    tags: ['cat.aria'],
    nodes: [
      {
        target: ['#fixture'],
        html: '<div id="fixture"></div>',
        any: [],
        all: [],
        none: [],
        failureSummary: '',
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
    expect(() => assertNoBlockingIncompletes([incompleteEntry('serious')])).toThrow(
      /Expected no serious or critical axe incompletes/,
    );
  });

  it('throws when results include a critical incomplete', () => {
    expect(() => assertNoBlockingIncompletes([incompleteEntry('critical', 'button-name')])).toThrow(
      /Expected no serious or critical axe incompletes/,
    );
  });

  it('does not throw when incompletes are only minor [TEST-15]', () => {
    expect(() => assertNoBlockingIncompletes([incompleteEntry('minor', 'color-contrast')])).not.toThrow();
  });

  it('does not throw when incompletes are only moderate', () => {
    expect(() => assertNoBlockingIncompletes([incompleteEntry('moderate', 'region')])).not.toThrow();
  });

  it('does not throw on an empty incomplete list', () => {
    expect(() => assertNoBlockingIncompletes([])).not.toThrow();
  });
});
