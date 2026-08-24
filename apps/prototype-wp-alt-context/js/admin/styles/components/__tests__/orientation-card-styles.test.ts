import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const orientationCardScssPath = join(__dirname, '..', '_orientation-card.scss');

describe('orientation card styles', () => {
  it('gives the dismiss control tokenized spacing and a visible keyboard focus treatment', () => {
    const source = readFileSync(orientationCardScssPath, 'utf8');

    expect(source).toContain('&__dismiss');
    expect(source).toMatch(/padding:\s*var\(--acx-space-/);
    expect(source).toMatch(/&:focus-visible\s*\{/);
    expect(source).toMatch(/outline:\s*[^;]*var\(--acx-color-accent\)/);
    expect(source).not.toMatch(/&__dismiss\s*\{[^}]*padding:\s*\d+px/s);
  });
});
