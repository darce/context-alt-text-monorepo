import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const componentsDir = join(__dirname, '..', '..', 'components');
const workbenchScssPath = join(componentsDir, '_workbench.scss');

const readWorkbench = (): string => readFileSync(workbenchScssPath, 'utf8');

const listComponentScssFiles = (): string[] =>
  readdirSync(componentsDir)
    .filter((name) => name.endsWith('.scss'))
    .map((name) => join(componentsDir, name))
    .sort();

/** Shared exemption: REFA-3 / E21-4 disposition comments allow raw scale literals. */
const isExempt = (line: string): boolean =>
  /(?:\/\/|\/\*)\s*(REFA-3|E21-4)\s+disposition:/.test(line);

const literalPatterns: readonly { name: string; re: RegExp }[] = [
  { name: 'hex', re: /#[0-9a-fA-F]{3,8}\b/ },
  { name: 'rgb/rgba', re: /rgba?\(/ },
  // Named color keywords used as color values (not white-space, etc.)
  {
    name: 'named white|black',
    re: /(?:^|[\s:;(])(?:color|background(?:-color)?|border(?:-color)?|fill|stroke|outline-color)\s*:\s*(?:white|black)\b|(?:^|[\s:;(])(?:white|black)\s*(?:!important)?\s*;/,
  },
  // font-size numerics incl. leading-dot (.75rem) and bare integers
  { name: 'font-size', re: /font-size:\s*(?:\.\d|\d)/ },
  { name: 'font-weight', re: /font-weight:\s*\d/ },
  { name: 'border-radius', re: /border-radius:\s*(?:999px|50%|\d)/ },
  // box-shadow numerics incl. inset
  { name: 'box-shadow', re: /box-shadow:\s*(?:inset\s+)?-?\d/ },
  ];

/** Raw px spacing — applied in the generic loop (E21-5 closes the spacing gap). */
const spacingLiteralPatterns: readonly { name: string; re: RegExp }[] = [
  { name: 'spacing-gap', re: /(?<![\w-])gap(?:-(?:x|y))?:\s*[0-9]+px\b/ },
  {
    name: 'spacing-padding',
    re: /(?<![\w-])padding(?:-(?:top|right|bottom|left|inline|block))?:\s*(?:[0-9]+px\b|[0-9]+px\s)/,
  },
  {
    name: 'spacing-margin',
    re: /(?<![\w-])margin(?:-(?:top|right|bottom|left|inline|block))?:\s*-?(?:[0-9]+px\b|[0-9]+px\s)/,
  },
];

/**
 * Spacing patterns live in the generic loop's pattern set for E21-5 sheets.
 * Pre-existing component sheets keep color/type checks only (spacing debt is
 * pre-existing); workbench has intentional raw layout widths/hairlines with
 * disposition comments that also match naive spacing regexes in comments.
 */
const spacingEnforcedFiles = new Set(['_review-queue.scss']);

describe('REFA-3 workbench non-literal assertions', () => {
  it('uses the card shadow token instead of a raw box-shadow literal', () => {
    const source = readWorkbench();

    expect(source).toContain('box-shadow: var(--acx-shadow-card)');
    expect(source).not.toMatch(/box-shadow:\s*[0-9]/);
  });

  it('has no raw border-radius spacing-token misuse', () => {
    const source = readWorkbench();

    expect(source).not.toMatch(/border-radius:\s*var\(--acx-space-/);
  });

  it('records literal disposition for layout widths and hairline borders', () => {
    const source = readWorkbench();

    expect(source).toMatch(/REFA-3 literal disposition/);
    expect(source).toMatch(/1px borders/);
    expect(source).toMatch(/layout widths/);
  });

  it('tokenizes gap spacing (no raw px gaps)', () => {
    const source = readWorkbench();

    // gap is always pure spacing (no kept-raw exceptions), so any raw px gap is a tokenization regression.
    expect(source).not.toMatch(/gap:\s*[0-9]+px/);
  });
});

describe('components/*.scss no unguarded scale literals', () => {
  const componentFiles = listComponentScssFiles();
  const indexScssPath = join(componentsDir, 'index.scss');

  it('collects every components/*.scss file', () => {
    expect(componentFiles.length).toBeGreaterThan(0);
    expect(componentFiles.every((path) => path.endsWith('.scss'))).toBe(true);
  });

  it("registers review-queue via @use './review-queue' in index.scss", () => {
    const source = readFileSync(indexScssPath, 'utf8');
    expect(source).toMatch(/@use\s+['"]\.\/review-queue['"]/);
  });

  it.each(componentFiles)('%s has no raw scale literals except disposition lines', (path) => {
    const source = readFileSync(path, 'utf8');
    const baseName = path.split('/').pop() ?? path;
    const patterns = spacingEnforcedFiles.has(baseName)
      ? [...literalPatterns, ...spacingLiteralPatterns]
      : literalPatterns;
    const offenders = source
      .split('\n')
      .flatMap((line, index) => {
        if (isExempt(line)) {
          return [];
        }
        return patterns
          .filter(({ re }) => re.test(line))
          .map(({ name }) => `${index + 1}:${name}: ${line.trim()}`);
      });

    expect(offenders).toEqual([]);
  });

  it('tokenizes durable/avatar error inset shadow and chip min sizes [REV1-18]', () => {
    const durable = readFileSync(join(componentsDir, '_durable-face-thumb.scss'), 'utf8');
    const avatar = readFileSync(join(componentsDir, '_avatar.scss'), 'utf8');

    expect(durable).toContain('box-shadow: var(--acx-shadow-inset-danger)');
    expect(avatar).toContain('box-shadow: var(--acx-shadow-inset-danger)');
    expect(durable).toMatch(/min-width:\s*var\(--acx-thumb-size-sm\)/);
    expect(durable).toMatch(/min-height:\s*var\(--acx-thumb-size-sm\)/);
    expect(durable).not.toMatch(/min-width:\s*32px/);
    expect(durable).not.toMatch(/min-height:\s*32px/);
    expect(durable).not.toMatch(/box-shadow:\s*inset\s+0\s+0\s+0\s+1px/);
    expect(avatar).not.toMatch(/box-shadow:\s*inset\s+0\s+0\s+0\s+1px/);
  });
});
