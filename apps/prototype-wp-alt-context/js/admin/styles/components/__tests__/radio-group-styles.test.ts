import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';

import type { ProductionCssBundle } from './productionCssBundle';
import {
  isInsideFixtureRoot,
  loadProductionCssBundle,
  readArtifactStamp,
  SHARED_BUILD_OUT_DIR,
} from './productionCssBundle';

const componentsRoot = join(__dirname, '..');
const radioGroupScssPath = join(componentsRoot, '_radio-group.scss');
const indexScssPath = join(componentsRoot, 'index.scss');

describe('E15-25 slice 1: radio-group stylesheet', () => {
  let bundle: ProductionCssBundle;

  // FEBT2-W2-U-01: the build is hoisted out of the test body. On a cold artifact cache
  // `loadProductionCssBundle` runs a real `vite build`, and under lane contention it can
  // also wait out the fixture's 6-minute global build lock — so the old in-body 120s
  // budget was reachable, and when it fired the failure read as a radio-group stylesheet
  // regression rather than as the build/lock timeout it actually was (RES-02/RES-03:
  // the bound must exceed the operation it guards, and a misattributed failure is worse
  // than a slow one). Paying it in `beforeAll` prices the setup as setup.
  beforeAll(() => {
    bundle = loadProductionCssBundle();
  }, 600_000);

  it('registers radio-group in components index.scss', () => {
    const indexScss = readFileSync(indexScssPath, 'utf8');

    expect(indexScss).toMatch(/@use\s+['"]\.\/radio-group['"]/);
  });

  it('defines token-based radio item and checked indicator styles', () => {
    expect(existsSync(radioGroupScssPath)).toBe(true);
    const source = readFileSync(radioGroupScssPath, 'utf8');

    expect(source).toContain('.acx-radio-group__item');
    expect(source).toContain('.acx-radio-group__indicator');
    expect(source).toMatch(/data-state=['"]checked['"]/);
    expect(source).toContain('var(--acx-color-border)');
    expect(source).toContain('var(--acx-color-accent)');
    expect(source).toContain('appearance: none');
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
  });

  it('includes focus-visible ring for keyboard users', () => {
    const source = readFileSync(radioGroupScssPath, 'utf8');

    expect(source).toMatch(/:focus-visible/);
  });

  it('ships radio-group rules in the production admin CSS bundle', () => {
    // FEBT1-GATE-04 / FEBT1-LH-01: this assertion is only meaningful against a bundle built
    // from the tree under test. The fixture pins that boundary by content-addressing the
    // artifact on the build inputs, so a missing or stale artifact fails as a build problem
    // instead of masquerading as a source regression (or a green pass), and no concurrent
    // `vite build` can empty the directory we read from.
    expect(bundle.cssFilePaths.length).toBeGreaterThan(0);
    expect(readArtifactStamp(bundle)).toBe(bundle.fingerprint);
    expect(bundle.cssFilePaths.every(isInsideFixtureRoot)).toBe(true);
    expect(bundle.cssFilePaths.some((filePath) => filePath.startsWith(SHARED_BUILD_OUT_DIR))).toBe(false);

    // Selector-boundary anchored: a plain substring match is satisfied by a longer sibling
    // class (`__indicator-dot`), and `data-state=.?checked` is satisfied by `unchecked`.
    // Both mutants survived until these assertions were tightened.
    expect(bundle.css).toMatch(/\.acx-radio-group__item(?![\w-])/);
    expect(bundle.css).toMatch(/\.acx-radio-group__indicator(?![\w-])/);
    // Scoped to the radio-group item: an unscoped `[data-state=checked]` match is satisfied by
    // _media-selection.scss, which emits the same attribute selector, so renaming the
    // radio-group's own checked rule survived as a mutant until this was scoped.
    expect(bundle.css).toMatch(/\.acx-radio-group__item\[data-state=['"]?checked['"]?\]/);
    expect(bundle.css).toMatch(
      /\.acx-radio-group__item\[data-state=['"]?checked['"]?\]\s+\.acx-radio-group__indicator(?![\w-])/,
    );
  });
});
