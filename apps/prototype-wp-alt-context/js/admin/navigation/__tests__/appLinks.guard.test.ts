/**
 * REF-19 single-owner guard: no raw `#/` hash-route string literals outside
 * the appLinks contract module. Scans production sources under js/admin.
 *
 * Pinned globs (plan Slice 2):
 * - include: js/admin tree, ts/tsx files
 * - exclude: js/admin/navigation tree and any __tests__ directories
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ADMIN_ROOT = path.resolve(__dirname, '../..');
const NAVIGATION_ROOT = path.resolve(__dirname, '..');

/** Match quoted / template-string hash route literals (`#/workbench`, `#/roster?...`). */
const HASH_LITERAL_RE = /(['"`])#\/[^'"`]*\1/g;

const isExcluded = (absolutePath: string): boolean => {
  const normalized = absolutePath.split(path.sep).join('/');
  if (normalized.includes('/__tests__/') || normalized.endsWith('.test.ts') || normalized.endsWith('.test.tsx')) {
    return true;
  }
  if (normalized.startsWith(NAVIGATION_ROOT.split(path.sep).join('/'))) {
    return true;
  }
  return false;
};

const collectSourceFiles = (dir: string, out: string[] = []): string[] => {
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) {
      collectSourceFiles(full, out);
      continue;
    }
    if (!/\.(ts|tsx)$/.test(entry)) {
      continue;
    }
    if (isExcluded(full)) {
      continue;
    }
    out.push(full);
  }
  return out;
};

describe('appLinks single-owner guard (REF-19)', () => {
  it('fails when any js/admin production file contains a raw #/ hash literal', () => {
    const files = collectSourceFiles(ADMIN_ROOT);
    expect(files.length).toBeGreaterThan(0);

    const violations: string[] = [];
    for (const file of files) {
      const source = readFileSync(file, 'utf8');
      // Strip line comments so prose like "generic #/roster" does not trip the gate.
      const withoutLineComments = source.replace(/\/\/.*$/gm, '');
      const matches = withoutLineComments.match(HASH_LITERAL_RE);
      if (matches && matches.length > 0) {
        const rel = path.relative(ADMIN_ROOT, file);
        violations.push(`${rel}: ${matches.join(', ')}`);
      }
    }

    expect(violations, `Raw hash literals must live in navigation/appLinks only:\n${violations.join('\n')}`).toEqual(
      [],
    );
  });
});
