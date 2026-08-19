import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const GETTEXT_RESERVED_VARIABLE =
  /(?:__|_n|_x|_nx)\(\s*(?:RESERVED_LABEL_MESSAGE|[A-Za-z_]*RESERVED[A-Za-z_]*)\s*[,)]/;

const GETTEXT_NON_LITERAL = /(?:__|_n|_x|_nx)\(\s*[A-Z_][A-Z0-9_]*\s*,/;

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
      const match = GETTEXT_NON_LITERAL.exec(source);
      if (match) {
        offenders.push(`${path.relative(root, file)}: ${match[0]}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('fails if useClusterSaveAction reverts the missing-person string', () => {
    const source = readFileSync(path.join(root, 'useClusterSaveAction.ts'), 'utf8');
    expect(source).toContain("Cannot save this name: missing person.");
    expect(source).not.toMatch(/Cannot save this name: missing cluster/);
  });
});
