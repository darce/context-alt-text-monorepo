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

const hexLiteralRe = /#[0-9a-fA-F]{3,8}/;
const e21Slice2Files = [
  join(__dirname, '..', '..', 'components', '_identity-cluster-list.scss'),
  join(__dirname, '..', '..', 'components', '_combobox.scss'),
  join(__dirname, '..', '..', 'components', '_orientation-card.scss'),
] as const;

describe('E21-4 slice 2', () => {
  it.each(e21Slice2Files)('%s has no raw hex literals except disposition lines', (path) => {
    const source = readFileSync(path, 'utf8');
    const offenders = source
      .split('\n')
      .filter((line) => hexLiteralRe.test(line) && !line.includes('E21-4 disposition:'));

    expect(offenders).toEqual([]);
  });
});

const e21Slice3LiteralPatterns: ReadonlyArray<{ name: string; re: RegExp }> = [
  { name: 'font-size', re: /font-size:\s*[0-9]/ },
  { name: 'font-weight', re: /font-weight:\s*[0-9]/ },
  { name: 'border-radius', re: /border-radius:\s*(999px|50%|[0-9])/ },
  { name: 'box-shadow', re: /box-shadow:\s*[0-9-]/ },
  { name: 'hex', re: /#[0-9a-fA-F]{3,8}/ },
  { name: 'rgb/rgba', re: /rgba?\(/ },
];

const isDispositionLine = (line: string): boolean => /disposition/i.test(line);

describe('E21-4 slice 3', () => {
  const componentFiles = listComponentScssFiles();

  it('collects every components/*.scss file', () => {
    expect(componentFiles.length).toBeGreaterThan(0);
    expect(componentFiles.every((path) => path.endsWith('.scss'))).toBe(true);
  });

  it.each(componentFiles)('%s has no raw scale literals except disposition lines', (path) => {
    const source = readFileSync(path, 'utf8');
    const offenders = source
      .split('\n')
      .flatMap((line, index) => {
        if (isDispositionLine(line)) {
          return [];
        }
        return e21Slice3LiteralPatterns
          .filter(({ re }) => re.test(line))
          .map(({ name }) => `${index + 1}:${name}: ${line.trim()}`);
      });

    expect(offenders).toEqual([]);
  });
});
