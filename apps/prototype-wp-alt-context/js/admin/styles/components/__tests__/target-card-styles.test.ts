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
const targetCardScssPath = join(componentsRoot, '_target-card.scss');
const indexScssPath = join(componentsRoot, 'index.scss');

describe('E15-25 slice 3: target-card stylesheet', () => {
  let bundle: ProductionCssBundle;

  // FEBT2-W2-U-01: hoisted out of the test body. A cold cache runs a real `vite build`,
  // and lane contention can add a wait on the fixture's 6-minute global build lock, so the
  // old in-body 120s budget was reachable — and its expiry was reported as a target-card
  // stylesheet regression rather than as a build timeout (RES-02/RES-03).
  beforeAll(() => {
    bundle = loadProductionCssBundle();
  }, 600_000);

  it('registers target-card in components index.scss', () => {
    const indexScss = readFileSync(indexScssPath, 'utf8');
    expect(indexScss).toMatch(/@use\s+['"]\.\/target-card['"]/);
  });

  it('defines token-based active and health chip styles', () => {
    expect(existsSync(targetCardScssPath)).toBe(true);
    const source = readFileSync(targetCardScssPath, 'utf8');

    expect(source).toContain('&--active');
    expect(source).toContain('&--reachable');
    expect(source).toContain('var(--acx-color-accent)');
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
  });

  it('ships target-card rules in the production admin CSS bundle', () => {
    // FEBT1-GATE-04 / FEBT1-LH-01: the shared public/assets/dist output is gitignored and is
    // emptied by every `vite build`, so reading it was a check-then-act race. The fixture
    // builds once into a content-addressed directory keyed on the build inputs, so this
    // assertion is still only satisfiable by a bundle emitted from the tree under test, and
    // no other process can empty what we read.
    expect(bundle.cssFilePaths.length).toBeGreaterThan(0);
    expect(readArtifactStamp(bundle)).toBe(bundle.fingerprint);
    expect(bundle.cssFilePaths.every(isInsideFixtureRoot)).toBe(true);
    expect(bundle.cssFilePaths.some((filePath) => filePath.startsWith(SHARED_BUILD_OUT_DIR))).toBe(false);

    // Selector-boundary anchored: `toContain('.acx-target-card__health')` is satisfied by the
    // unrelated `.acx-target-card__health-icon` rule, so renaming the health chip itself
    // survived as a mutant until this assertion was tightened.
    expect(bundle.css).toMatch(/\.acx-target-card--active(?![\w-])/);
    expect(bundle.css).toMatch(/\.acx-target-card__health(?![\w-])/);
  });
});
