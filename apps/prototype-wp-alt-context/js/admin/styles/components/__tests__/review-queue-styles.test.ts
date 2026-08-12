import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const componentsRoot = join(__dirname, '..');
const reviewQueueScssPath = join(componentsRoot, '_review-queue.scss');

const readReviewQueueScss = (): string => readFileSync(reviewQueueScssPath, 'utf8');

/** Slice a top-level (2-space indented) BEM element rule out of the sheet. */
const extractRule = (source: string, selector: string): string => {
  const start = source.indexOf(`  ${selector} {`);
  if (start === -1) {
    throw new Error(`Rule "${selector}" is not declared in _review-queue.scss`);
  }
  const end = source.indexOf('\n  }', start);
  return source.slice(start, end === -1 ? undefined : end);
};

describe('E21-14: review-queue outage styling', () => {
  // The outage state is rendered in three places; without a rule it degrades to
  // unstyled body text — visually identical to the ordinary drained state.
  it('styles &__error as a danger surface, not unstyled body text', () => {
    const rule = extractRule(readReviewQueueScss(), '&__error');

    expect(rule).toContain('background-color: var(--acx-color-danger-soft)');
    expect(rule).toContain('border: 1px solid var(--acx-color-danger-border)');
    expect(rule).toContain('color: var(--acx-color-danger-strong)');
    expect(rule).toContain('border-radius: var(--acx-radius-sm)');
    expect(rule).toContain('font-size: var(--acx-text-sm)');
  });

  // sr-004: a status indicator must never rely on colour alone.
  it('pairs the danger colour with a glyph so colour is not the only signal', () => {
    const rule = extractRule(readReviewQueueScss(), '&__error');

    expect(rule).toContain('&::before');
    expect(rule).toMatch(/content:\s*'\\26a0'/i);
  });

  // The whole point of the branch: failure must not look like a drained queue.
  it('gives the error state a distinct treatment from the drained empty state', () => {
    const source = readReviewQueueScss();
    const errorRule = extractRule(source, '&__error');
    const emptyRule = extractRule(source, '&__empty');

    expect(emptyRule).not.toContain('background-color');
    expect(emptyRule).not.toContain('border:');
    expect(errorRule).toContain('background-color');
    expect(errorRule).toContain('border:');
  });

  // sr-004: tokens only — the file-wide tokenization gate also covers this sheet.
  it('declares the error rule without raw colour, size, or radius literals', () => {
    const rule = extractRule(readReviewQueueScss(), '&__error');

    expect(rule).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(rule).not.toMatch(/rgba?\(/);
    expect(rule).not.toMatch(/font-size:\s*(?:\.\d|\d)/);
    expect(rule).not.toMatch(/font-weight:\s*\d/);
    expect(rule).not.toMatch(/border-radius:\s*(?:999px|50%|\d)/);
    expect(rule).not.toMatch(/(?:padding|margin|gap):\s*[0-9]+px/);
  });
});
