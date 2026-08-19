import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const specPath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../tests/e2e/a11y/roster-keyboard-walk.spec.ts',
);

const readSpec = (): string => readFileSync(specPath, 'utf8');

describe('roster-keyboard-walk e2e spec source guard (UXW2-4-R2-14)', () => {
  it('reads window.AltContextAdmin and never window.acxAdmin', () => {
    const spec = readSpec();
    expect(spec).toContain('AltContextAdmin');
    expect(spec).not.toMatch(/\bacxAdmin\b/);
  });

  it('follows the Review in Workbench CTA onto the queue, not href-only (UXW2-4-R1-24)', () => {
    const spec = readSpec();
    expect(spec).toMatch(/getByRole\('link',\s*\{\s*name:\s*\/Review in Workbench\/i\s*\}\)\.click\(\)/);
    expect(spec).toContain("window.location.hash)).toBe('#/workbench?tab=scan&rq=all.all.0')");
    expect(spec).toContain("page.locator('.acx-workbench')");
    expect(spec).toContain("page.locator('.acx-review-queue')");
    expect(spec).not.toMatch(/toHaveURL\(\/page=alt-context-workbench\/\)/);
  });

  it('keeps an honest drawer-walk skip when unlabeled seed is absent', () => {
    const spec = readSpec();
    expect(spec).toContain('discoverUnlabeledClusterId');
    expect(spec).toMatch(/test\.skip\(\s*true,/);
    expect(spec).not.toMatch(/E2E_ROSTER_CLUSTER_ID/);
    expect(spec).not.toMatch(/getByRole\('listbox'\)/);
    expect(spec).not.toMatch(/getByRole\('option'\)/);
  });
});
