import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const GETTEXT_RESERVED_VARIABLE =
  /(?:__|_n|_x|_nx)\(\s*(?:RESERVED_LABEL_MESSAGE|[A-Za-z_]*RESERVED[A-Za-z_]*)\s*[,)]/;

const GETTEXT_NON_LITERAL = /(?:__|_n|_x|_nx)\(\s*[A-Z_][A-Z0-9_]*\s*,/;

const GETTEXT_CALL = /(?:\b__|\b_n|\b_x|\b_nx)\(/g;
const LITERAL_FIRST_ARG = /^\s*(?:'[^']*'|"[^"]*"|`[^`${}]*`)\s*$/;

/** First __() argument, quote-aware so commas inside literals are not cuts. */
const extractFirstArg = (source: string, openParenIndex: number): string | null => {
  let i = openParenIndex + 1;
  while (i < source.length && /\s/.test(source[i] ?? '')) {
    i += 1;
  }
  if (i >= source.length) {
    return null;
  }
  const start = i;
  const quote = source[i];
  if (quote === "'" || quote === '"' || quote === '`') {
    i += 1;
    while (i < source.length) {
      if (source[i] === '\\') {
        i += 2;
        continue;
      }
      if (source[i] === quote) {
        i += 1;
        break;
      }
      i += 1;
    }
    return source.slice(start, i);
  }
  let depth = 0;
  while (i < source.length) {
    const ch = source[i] ?? '';
    if (ch === "'" || ch === '"' || ch === '`') {
      const inner = ch;
      i += 1;
      while (i < source.length) {
        if (source[i] === '\\') {
          i += 2;
          continue;
        }
        if (source[i] === inner) {
          i += 1;
          break;
        }
        i += 1;
      }
      continue;
    }
    if (ch === '(' || ch === '[' || ch === '{') {
      depth += 1;
    } else if (ch === ')' || ch === ']' || ch === '}') {
      if (depth === 0) {
        break;
      }
      depth -= 1;
    } else if (ch === ',' && depth === 0) {
      break;
    }
    i += 1;
  }
  return source.slice(start, i);
};

const collectTsFiles = (dir: string): string[] => {
  const entries = readdirSync(dir, { withFileTypes: true });
  const files: string[] = [];
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === '__tests__' || entry.name === 'node_modules') {
        continue;
      }
      files.push(...collectTsFiles(full));
      continue;
    }
    if (entry.name.endsWith('.ts') || entry.name.endsWith('.tsx')) {
      files.push(full);
    }
  }
  return files;
};

describe('gettext first arguments are literals (UXW2-3-R1-10 / R2-06)', () => {
  it('does not pass RESERVED_LABEL_MESSAGE into __() in naming files', () => {
    const scoped = [
      'reservedLabel.ts',
      'PersonCommitControl.tsx',
      'ClusterLabelingPanel.tsx',
      'useClusterSaveAction.ts',
    ];
    const offenders: string[] = [];
    for (const file of scoped) {
      const source = readFileSync(path.join(root, file), 'utf8');
      const match = GETTEXT_RESERVED_VARIABLE.exec(source);
      if (match) {
        offenders.push(`${file}: ${match[0]}`);
      }
    }
    expect(offenders).toEqual([]);
    const reserved = readFileSync(path.join(root, 'reservedLabel.ts'), 'utf8');
    expect(reserved).toMatch(/__\(\s*'This label format is reserved/);
  });

  it('does not pass CONST identifiers into __() across identity-clusters', () => {
    const offenders: string[] = [];
    for (const file of collectTsFiles(root)) {
      const source = readFileSync(file, 'utf8');
      const rel = path.relative(root, file);
      GETTEXT_NON_LITERAL.lastIndex = 0;
      const match = GETTEXT_NON_LITERAL.exec(source);
      if (match) {
        offenders.push(`${rel}: ${match[0]}`);
      }
      GETTEXT_CALL.lastIndex = 0;
      let call: RegExpExecArray | null;
      while ((call = GETTEXT_CALL.exec(source)) !== null) {
        const openParen = call.index + call[0].length - 1;
        const arg = extractFirstArg(source, openParen);
        if (arg === null || LITERAL_FIRST_ARG.test(arg)) {
          continue;
        }
        const line = source.slice(0, call.index).split('\n').length;
        const entry = `${rel}:${line} ${arg.trim()}`;
        if (!offenders.includes(entry)) {
          offenders.push(entry);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it('fails if useClusterSaveAction reverts the missing-person string', () => {
    const source = readFileSync(path.join(root, 'useClusterSaveAction.ts'), 'utf8');
    expect(source).toContain('Cannot save this name: missing person.');
    expect(source).not.toMatch(/Cannot save this name: missing cluster/);
  });
});
