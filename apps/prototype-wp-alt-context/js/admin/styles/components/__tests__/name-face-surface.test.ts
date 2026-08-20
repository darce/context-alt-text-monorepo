import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import * as sass from 'sass';
import { describe, expect, it } from 'vitest';

const here = path.dirname(fileURLToPath(import.meta.url));
const componentsDir = path.resolve(here, '..');
const stylesDir = path.resolve(componentsDir, '..');

const SHARED_SURFACE_MARKERS = [
  'position: absolute',
  'box-shadow: var(--acx-shadow-2)',
  'border-radius: var(--acx-radius-md)',
] as const;

const PREFIXES = ['.acx-name-face', '.acx-cluster-labeling-panel', '.acx-person-commit'] as const;

describe('acx-name-face-surface mixin (UXW2-3-R1-03)', () => {
  it('compiled selectors carry the shared overlay declarations', () => {
    const compiled = sass.compile(path.join(componentsDir, '_name-face.scss'), {
      loadPaths: [stylesDir, componentsDir],
      style: 'expanded',
    });
    const css = compiled.css;

    for (const prefix of PREFIXES) {
      const overlay = `${prefix}__suggestions-overlay`;
      expect(css, `${overlay} missing`).toContain(overlay);
      const overlayBlock = extractRule(css, overlay);
      for (const marker of SHARED_SURFACE_MARKERS) {
        expect(overlayBlock, `${overlay} missing ${marker}`).toContain(marker);
      }
    }
  });

  it('identity-cluster list include compiles the same overlay surface', () => {
    const compiled = sass.compile(path.join(componentsDir, '_identity-cluster-list.scss'), {
      loadPaths: [stylesDir, componentsDir],
      style: 'expanded',
    });
    const css = compiled.css;
    const overlayBlock = extractRule(css, '.acx-identity-cluster__suggestions-overlay');
    for (const marker of SHARED_SURFACE_MARKERS) {
      expect(overlayBlock).toContain(marker);
    }
  });

  it('the hidden suggestion-reject is not click-targetable (UXW2-3-R3-15)', () => {
    const compiled = sass.compile(path.join(componentsDir, '_name-face.scss'), {
      loadPaths: [stylesDir, componentsDir],
      style: 'expanded',
    });
    const css = compiled.css;
    expect(css, 'expected compiled css to match /__suggestion-reject[^}]*pointer-events:\\s*none/').toMatch(
      /__suggestion-reject[^}]*pointer-events:\s*none/,
    );
    expect(css, 'reveal selector must restore pointer-events: auto').toMatch(
      /__suggestion-reject[^}]*pointer-events:\s*auto/,
    );
  });

  it('source includes the mixin on every naming prefix (mutant: drop one @include)', () => {
    const nameFace = readFileSync(path.join(componentsDir, '_name-face.scss'), 'utf8');
    const list = readFileSync(path.join(componentsDir, '_identity-cluster-list.scss'), 'utf8');
    expect(nameFace.match(/@include acx-name-face-surface/g)).toHaveLength(3);
    expect(list).toMatch(/@include name-face\.acx-name-face-surface/);
  });
});

const extractRule = (css: string, selector: string): string => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = new RegExp(`${escaped}\\s*\\{([^}]+)\\}`).exec(css);
  return match?.[1] ?? '';
};
