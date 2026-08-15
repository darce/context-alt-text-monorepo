import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

const stylesRoot = join(__dirname, '..');
const avatarScssPath = join(stylesRoot, 'components', '_avatar.scss');

const stripScssComments = (contents: string): string =>
  contents.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');

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

const extractConditionalAtRuleConditions = (
  contents: string,
): Array<{ kind: 'media' | 'container'; condition: string }> => {
  const matches = stripScssComments(contents).matchAll(/@(media|container)\s+([^{]+)\{/g);

  return [...matches].map((match) => ({
    kind: match[1] as 'media' | 'container',
    condition: match[2].replace(/\s+/g, ' ').trim(),
  }));
};

const extractRuleBody = (source: string, selector: string): string => {
  const start = source.indexOf(`${selector} {`);
  if (start === -1) {
    throw new Error(`missing ${selector} rule`);
  }

  const open = source.indexOf('{', start);
  let depth = 0;
  for (let index = open; index < source.length; index += 1) {
    const char = source[index];
    if (char === '{') {
      depth += 1;
    } else if (char === '}') {
      depth -= 1;
      if (depth === 0) {
        return source.slice(open + 1, index);
      }
    }
  }

  throw new Error(`unclosed ${selector} rule`);
};

const topLevelDeclarations = (body: string): string => {
  let depth = 0;
  let declarations = '';

  for (const char of body) {
    if (char === '{') {
      depth += 1;
    } else if (char === '}') {
      depth = Math.max(0, depth - 1);
    } else if (depth === 0) {
      declarations += char;
    }
  }

  return declarations;
};

describe('admin style query conditions', () => {
  it('does not put var() inside @container or @media conditions', () => {
    const violations = collectScssFiles(stylesRoot).flatMap((filePath) => {
      const relPath = relative(stylesRoot, filePath);

      return extractConditionalAtRuleConditions(readFileSync(filePath, 'utf8'))
        .filter(({ condition }) => /var\s*\(/.test(condition))
        .map(({ kind, condition }) => `${relPath}: @${kind} ${condition}`);
    });

    expect(violations, 'var() is not substituted in @media/@container conditions').toEqual([]);
  });

  it('does not declare container-type: size on the .acx-avatar base rule', () => {
    const source = stripScssComments(readFileSync(avatarScssPath, 'utf8'));
    const baseDeclarations = topLevelDeclarations(extractRuleBody(source, '.acx-avatar'));

    expect(baseDeclarations).not.toMatch(/container-type\s*:\s*size\b/);
  });
});
