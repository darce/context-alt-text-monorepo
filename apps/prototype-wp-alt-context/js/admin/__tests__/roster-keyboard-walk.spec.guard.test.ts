import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

describe('roster-keyboard-walk e2e spec source guard (UXW2-4-R2-14)', () => {
  it('reads window.AltContextAdmin and never window.acxAdmin', () => {
    const spec = readFileSync(
      path.resolve(
        path.dirname(fileURLToPath(import.meta.url)),
        '../../../tests/e2e/a11y/roster-keyboard-walk.spec.ts',
      ),
      'utf8',
    );
    expect(spec).toContain('AltContextAdmin');
    expect(spec).not.toMatch(/\bacxAdmin\b/);
  });
});
