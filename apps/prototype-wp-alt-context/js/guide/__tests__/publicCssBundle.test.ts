import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import * as sass from 'sass';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const GUIDE_INDEX_CSS = resolve(here, '../index.css');

const compileGuideCss = (): string =>
  sass.compileString(readFileSync(GUIDE_INDEX_CSS, 'utf8'), {
    style: 'expanded',
    syntax: 'scss',
    url: pathToFileURL(GUIDE_INDEX_CSS),
    loadPaths: [resolve(here, '..'), resolve(here, '../../admin/styles')],
  }).css;

const hasUnscopedTypeRule = (css: string, type: string): boolean =>
  new RegExp(`(?:^|[,}])\\s*${type}\\s*\\{`, 'm').test(css);

describe('public guide stylesheet isolation', () => {
  it('does not import the full admin stylesheet', () => {
    const source = readFileSync(GUIDE_INDEX_CSS, 'utf8');
    expect(source).not.toMatch(/admin\/styles\/main\.scss/);
  });

  it('compiles without admin surfaces or unscoped body/button resets', () => {
    const css = compileGuideCss();

    expect(css.length).toBeGreaterThan(0);
    expect(css).toMatch(/\.acx-guided-page/);
    expect(css).toMatch(/\.acx-dialog__/);
    expect(css).toMatch(/\.acx-radio-group/);
    expect(css).toMatch(/\.acx-public-guide/);
    expect(css).toMatch(/\.acx-public-guide__loading/);
    expect(css).toMatch(/\.acx-public-guide\s+\.acx-guided-page/);
    expect(css).toMatch(/\.acx-public-guide\s+\.acx-button\b/);
    expect(css).toMatch(/\.acx-public-guide\s+\.acx-button--danger\b/);

    for (const surface of ['dashboard', 'workbench', 'roster', 'review-queue'] as const) {
      expect(css, `guide CSS must not contain ${surface} selectors`).not.toMatch(
        new RegExp(`\\.acx-${surface}\\b`),
      );
    }

    expect(hasUnscopedTypeRule(css, 'body'), 'unscoped body { rule').toBe(false);
    expect(hasUnscopedTypeRule(css, 'button'), 'unscoped button { rule').toBe(false);
  });
});
