/**
 * GPFACE-1-V-04: the guided contrast fix (RA-04) and the border-shorthand ordering fix
 * (L-02) live only in SCSS, so the shared token tests stay green if either is reverted.
 * These assertions pin both to the stylesheet.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const SCSS_PATH = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../components/_guided-prototype.scss');

const stylesheet = (): string => readFileSync(SCSS_PATH, 'utf8');

/** Declarations of one block, in source order, from the line that opens it. */
const blockDeclarations = (css: string, selector: string): string[] => {
  const lines = css.split('\n');
  const start = lines.findIndex((line) => line.trim().startsWith(selector));
  expect(start, `block ${selector} not found`).toBeGreaterThan(-1);

  const declarations: string[] = [];
  let depth = 0;
  for (const line of lines.slice(start)) {
    depth += (line.match(/\{/g) ?? []).length - (line.match(/\}/g) ?? []).length;
    if (depth === 1 && line.includes(':') && !line.includes('{')) {
      declarations.push(line.trim());
    }
    if (depth === 0 && declarations.length > 0) {
      break;
    }
  }
  return declarations;
};

describe('guided prototype stylesheet', () => {
  it('sets the eyebrow and the boundary note in the accent-contrast token', () => {
    const css = stylesheet();

    for (const selector of ['&__eyebrow', '&__boundary']) {
      const blocks = css
        .split('\n')
        .map((line, index) => ({ line: line.trim(), index }))
        .filter((entry) => entry.line.startsWith(selector));
      expect(blocks.length, `no ${selector} block`).toBeGreaterThan(0);
    }

    // Both surfaces sit on --acx-color-primary; the contrast token is what makes them legible.
    expect((css.match(/color:\s*var\(--acx-color-accent-contrast\)/g) ?? []).length).toBeGreaterThanOrEqual(4);
    expect(css).not.toMatch(/color:\s*#[0-9a-fA-F]{3,8}/);
  });

  it('declares the status border-left after the border shorthand so it is not reset', () => {
    const declarations = blockDeclarations(stylesheet(), '&__status');
    const border = declarations.findIndex((line) => line.startsWith('border:'));
    const borderLeft = declarations.findIndex((line) => line.startsWith('border-left:'));

    expect(border).toBeGreaterThan(-1);
    expect(borderLeft).toBeGreaterThan(border);
    expect(declarations[borderLeft]).toContain('var(--acx-color-success-border)');
  });
});
