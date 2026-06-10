import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const workbenchScssPath = join(__dirname, '..', '..', 'components', '_workbench.scss');

const readWorkbench = (): string => readFileSync(workbenchScssPath, 'utf8');

describe('REFA-3 slice 2: _workbench.scss color + shadow', () => {
  it('has no raw hex or rgba color literals', () => {
    const source = readWorkbench();

    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(source).not.toMatch(/rgba?\(/);
  });

  it('uses the card shadow token instead of a raw box-shadow literal', () => {
    const source = readWorkbench();

    expect(source).toContain('box-shadow: var(--acx-shadow-card)');
    expect(source).not.toMatch(/box-shadow:\s*[0-9]/);
  });
});

describe('REFA-3 slice 3: _workbench.scss radius', () => {
  it('has no raw border-radius literals or spacing-token misuse', () => {
    const source = readWorkbench();

    expect(source).not.toMatch(/border-radius:\s*(?:999px|50%|[0-9]+px)/);
    expect(source).not.toMatch(/border-radius:\s*var\(--acx-space-/);
  });
});

describe('REFA-3 slice 4: _workbench.scss typography', () => {
  it('has no raw font-size or font-weight literals', () => {
    const source = readWorkbench();

    expect(source).not.toMatch(/font-size:\s*[0-9]/);
    expect(source).not.toMatch(/font-weight:\s*[0-9]/);
  });
});

describe('REFA-3 slice 5: _workbench.scss spacing disposition', () => {
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
