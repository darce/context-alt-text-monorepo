import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const stylesRoot = join(__dirname, '..', '..');
const tokensRoot = join(stylesRoot, 'tokens');
const componentsRoot = join(stylesRoot, 'components');
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
  '--acx-text-2xs',
  '--acx-text-xs',
  '--acx-text-sm',
  '--acx-text-md',
  '--acx-text-lg',
  '--acx-text-base',
] as const;

const REQUIRED_FONT_WEIGHT_TOKENS = [
  '--acx-font-weight-normal',
  '--acx-font-weight-semibold',
  '--acx-font-weight-bold',
] as const;

const REQUIRED_COLOR_TOKENS = ['--acx-color-info-border', '--acx-color-primary-subtle'] as const;

const REQUIRED_SHADOW_TOKENS = ['--acx-shadow-card'] as const;

const GOVERNED_VAR_PREFIXES = ['--acx-radius-', '--acx-text-', '--acx-font-weight-'] as const;

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
  const matches = contents.matchAll(/(--acx-[a-z0-9-]+)\s*:/g);

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

const readGovernedReferences = (): string[] => {
  const componentFiles = collectScssFiles(componentsRoot);

  return componentFiles.flatMap((filePath) =>
    extractReferencedTokens(readFileSync(filePath, 'utf8')).filter((token) =>
      GOVERNED_VAR_PREFIXES.some((prefix) => token.startsWith(prefix)),
    ),
  );
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

  it('resolves every governed var() reference in component styles', () => {
    const defined = readTokenDefinitions();
    const referenced = readGovernedReferences();
    const dangling = [...new Set(referenced)].filter((token) => !defined.has(token));

    expect(dangling, `dangling governed tokens: ${dangling.join(', ')}`).toEqual([]);
  });
});
