import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const stylesRoot = join(__dirname, '..', '..');
const tokensRoot = join(stylesRoot, 'tokens');
const mainScssPath = join(stylesRoot, 'main.scss');

const REQUIRED_RADIUS_TOKENS = [
  '--acx-radius-sm',
  '--acx-radius-md',
  '--acx-radius-lg',
  '--acx-radius-8',
  '--acx-radius-10',
  '--acx-radius-pill',
  '--acx-radius-circle',
] as const;

const REQUIRED_TEXT_TOKENS = [
  '--acx-text-icon',
  '--acx-text-micro',
  '--acx-text-2xs',
  '--acx-text-xs',
  '--acx-text-sm',
  '--acx-text-md',
  '--acx-text-lg',
  '--acx-text-base',
  '--acx-text-xl',
  '--acx-text-2xl',
  '--acx-text-3xl',
] as const;

const REQUIRED_FONT_WEIGHT_TOKENS = [
  '--acx-font-weight-normal',
  '--acx-font-weight-semibold',
  '--acx-font-weight-bold',
] as const;

const REQUIRED_COLOR_TOKENS = [
  '--acx-color-info-border',
  '--acx-color-primary-subtle',
  '--acx-color-primary',
  '--acx-color-text-secondary',
  '--acx-color-data-placeholder',
] as const;

const REQUIRED_SHADOW_TOKENS = ['--acx-shadow-card', '--acx-shadow-inset-danger'] as const;

// Strip SCSS line (//) and block comments before token regex parsing (S1-03).
const stripScssComments = (contents: string): string =>
  contents
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1');

const collectScssFiles = (directory: string): string[] => {
  const entries = readdirSync(directory, { withFileTypes: true });

  return entries.flatMap((entry) => {
    const fullPath = join(directory, entry.name);

    if (entry.isDirectory()) {
      return collectScssFiles(fullPath);
    }

    return entry.name.endsWith('.scss') ? [fullPath] : [];
  });
};

const extractDefinedTokens = (contents: string): Set<string> => {
  const stripped = stripScssComments(contents);
  const matches = stripped.matchAll(/(--acx-[a-z0-9-]+)\s*:/g);

  return new Set([...matches].map((match) => match[1]));
};

const extractReferencedTokens = (contents: string): string[] => {
  const matches = contents.matchAll(/var\((--acx-[a-z0-9-]+)/g);

  return [...matches].map((match) => match[1]);
};

const readTokenDefinitions = (): Set<string> => {
  const tokenFiles = collectScssFiles(tokensRoot);

  return tokenFiles.reduce((defined, filePath) => {
    const contents = readFileSync(filePath, 'utf8');
    const fileTokens = extractDefinedTokens(contents);

    fileTokens.forEach((token) => defined.add(token));

    return defined;
  }, new Set<string>());
};

describe('REFA-3 slice 1 token surface', () => {
  it('wires radius tokens into main.scss', () => {
    const mainScss = readFileSync(mainScssPath, 'utf8');

    expect(mainScss).toMatch(/@use\s+['"]\.\/tokens\/radius['"]/);
  });

  it('defines the radius, typography, color, and shadow token families', () => {
    expect(existsSync(join(tokensRoot, '_radius.scss'))).toBe(true);

    const defined = readTokenDefinitions();

    for (const token of REQUIRED_RADIUS_TOKENS) {
      expect(defined, `missing ${token}`).toContain(token);
    }

    for (const token of REQUIRED_TEXT_TOKENS) {
      expect(defined, `missing ${token}`).toContain(token);
    }

    for (const token of REQUIRED_FONT_WEIGHT_TOKENS) {
      expect(defined, `missing ${token}`).toContain(token);
    }

    for (const token of REQUIRED_COLOR_TOKENS) {
      expect(defined, `missing ${token}`).toContain(token);
    }

    for (const token of REQUIRED_SHADOW_TOKENS) {
      expect(defined, `missing ${token}`).toContain(token);
    }
  });
});

// --- E21-4 token direction acceptance -------------------------------------
// The design step is value ranking before hue [COL-04]; these assertions are
// the readout that the step happened [A11Y-01]. Duty pairs mirror the tables
// in docs/tasks/21.0/E21-4-design-token-system-task-plan.md.

const readTokenValueMap = (): Map<string, string> => {
  const map = new Map<string, string>();

  for (const filePath of collectScssFiles(tokensRoot)) {
    const contents = stripScssComments(readFileSync(filePath, 'utf8'));

    for (const match of contents.matchAll(/(--acx-[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
      map.set(match[1], match[2].trim());
    }
  }

  return map;
};

const resolveToken = (map: Map<string, string>, name: string, depth = 0): string => {
  if (depth > 10) {
    throw new Error(`token alias cycle at ${name}`);
  }

  const raw = map.get(name);

  if (raw === undefined) {
    throw new Error(`token ${name} is not defined`);
  }

  const aliasMatch = /^var\((--acx-[a-z0-9-]+)\)$/.exec(raw);

  return aliasMatch ? resolveToken(map, aliasMatch[1], depth + 1) : raw;
};

const relativeLuminance = (hex: string): number => {
  const normalized = hex.replace('#', '');
  const channels = [0, 2, 4].map((offset) => {
    const channel = parseInt(normalized.slice(offset, offset + 2), 16) / 255;

    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });

  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
};

const contrastRatio = (foregroundHex: string, backgroundHex: string): number => {
  const [lighter, darker] = [relativeLuminance(foregroundHex), relativeLuminance(backgroundHex)].sort(
    (a, b) => b - a,
  );

  return (lighter + 0.05) / (darker + 0.05);
};

const TEXT_FLOOR = 4.5;
const NON_TEXT_FLOOR = 3;

// [foreground token, background token, floor]
const DUTY_PAIRS: readonly (readonly [string, string, number])[] = [
  ['--acx-color-text-muted', '--acx-color-surface-alt', TEXT_FLOOR],
  ['--acx-color-text-muted', '--acx-gray-50', TEXT_FLOOR],
  ['--acx-color-text-muted', '--acx-gray-100', TEXT_FLOOR],
  ['--acx-gray-700', '--acx-color-panel', TEXT_FLOOR],
  ['--acx-color-text', '--acx-gray-50', TEXT_FLOOR],
  ['--acx-color-text', '--acx-gray-100', TEXT_FLOOR],
  ['--acx-color-text', '--acx-color-panel', TEXT_FLOOR],
  ['--acx-color-text', '--acx-color-warning-pill-bg', TEXT_FLOOR],
  ['--acx-gray-500', '--acx-gray-50', TEXT_FLOOR],
  ['--acx-gray-500', '--acx-color-surface-alt', TEXT_FLOOR],
  ['--acx-color-accent', '--acx-color-surface-alt', TEXT_FLOOR],
  ['--acx-color-accent-contrast', '--acx-color-accent', TEXT_FLOOR],
  ['--acx-color-danger', '--acx-color-surface-alt', TEXT_FLOOR],
  ['--acx-color-danger-strong', '--acx-color-danger-soft', TEXT_FLOOR],
  ['--acx-color-success', '--acx-color-surface-alt', TEXT_FLOOR],
  ['--acx-color-success', '--acx-color-success-bg', TEXT_FLOOR],
  ['--acx-color-success-text', '--acx-color-success-bg', TEXT_FLOOR],
  ['--acx-color-success-border', '--acx-color-surface-alt', NON_TEXT_FLOOR],
  ['--acx-color-warning-pill-text', '--acx-color-warning-pill-bg', TEXT_FLOOR],
  ['--acx-color-warning-border', '--acx-color-surface-alt', NON_TEXT_FLOOR],
  ['--acx-color-warning-border', '--acx-color-warning-bg', NON_TEXT_FLOOR],
  ['--acx-color-info-border', '--acx-color-surface-alt', NON_TEXT_FLOOR],
  ['--acx-color-error', '--acx-color-surface-alt', NON_TEXT_FLOOR],
] as const;

describe('E21-4 slice 1: token direction acceptance', () => {
  it('resolves every --acx-* var() reference anywhere in styles/', () => {
    // Definitions include component-scoped custom properties, not just tokens/.
    const defined = collectScssFiles(stylesRoot).reduce((all, filePath) => {
      extractDefinedTokens(readFileSync(filePath, 'utf8')).forEach((token) => all.add(token));

      return all;
    }, new Set<string>());
    const referenced = collectScssFiles(stylesRoot).flatMap((filePath) =>
      extractReferencedTokens(readFileSync(filePath, 'utf8')),
    );
    const dangling = [...new Set(referenced)].filter((token) => !defined.has(token));

    expect(dangling, `dangling tokens: ${dangling.join(', ')}`).toEqual([]);
  });

  it('meets WCAG floors for every declared duty pair', () => {
    const map = readTokenValueMap();
    const failures = DUTY_PAIRS.flatMap(([foreground, background, floor]) => {
      const ratio = contrastRatio(resolveToken(map, foreground), resolveToken(map, background));

      return ratio >= floor ? [] : [`${foreground} on ${background}: ${ratio.toFixed(2)} < ${floor}`];
    });

    expect(failures, failures.join('; ')).toEqual([]);
  });

  it('pins the modular type ladder and aliases', () => {
    const map = readTokenValueMap();

    expect(resolveToken(map, '--acx-text-2xs')).toBe('0.702rem');
    expect(resolveToken(map, '--acx-text-xs')).toBe('0.79rem');
    expect(resolveToken(map, '--acx-text-sm')).toBe('0.889rem');
    expect(map.get('--acx-text-md')).toBe('var(--acx-text-sm)');
    expect(resolveToken(map, '--acx-text-base')).toBe('1rem');
    expect(resolveToken(map, '--acx-text-lg')).toBe('1.125rem');
    expect(resolveToken(map, '--acx-text-xl')).toBe('1.266rem');
    expect(resolveToken(map, '--acx-text-2xl')).toBe('1.424rem');
    expect(resolveToken(map, '--acx-text-3xl')).toBe('1.802rem');
    expect(resolveToken(map, '--acx-leading-tight')).toBe('1.3');
    expect(resolveToken(map, '--acx-font-weight-medium')).toBe('500');
  });

  it('pins the elevation scale and re-valued functional colors', () => {
    const map = readTokenValueMap();

    expect(map.get('--acx-shadow-card')).toBe('var(--acx-shadow-1)');
    expect(map.has('--acx-shadow-2')).toBe(true);
    expect(map.has('--acx-shadow-3')).toBe(true);
    expect(map.get('--acx-shadow-inset-danger')).toBe('inset 0 0 0 1px var(--acx-color-danger)');
    expect(map.get('--acx-thumb-size-sm')).toBe('var(--acx-space-32)');
    expect(resolveToken(map, '--acx-radius-xl')).toBe('0.75rem');
    expect(resolveToken(map, '--acx-color-success')).toBe('#047857');
    expect(resolveToken(map, '--acx-color-success-border')).toBe('#16a34a');
    expect(resolveToken(map, '--acx-color-warning-border')).toBe('#b45309');
    expect(resolveToken(map, '--acx-color-frame-muted')).toBe('#cbd5e1');
  });
});
