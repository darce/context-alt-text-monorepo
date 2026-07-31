/**
 * REF-19 single-owner guard: no raw `#/` hash-route string literals outside
 * the appLinks contract module, and no re-declared contract param-name
 * literals outside the pinned reader-hook allowlist.
 *
 * Pinned scope (E21-10 review BR-02):
 * - include: js/admin tree, ts/tsx files
 * - hash-literal exclusion: exactly appLinks.ts (+ its co-located tests)
 * - param-name scan: contract-owned keys with a pinned allowlist of reader hooks
 *   that still spell names at the URL seam (they should import APP_LINK_PARAMS)
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ADMIN_ROOT = path.resolve(__dirname, '../..');
const APP_LINKS_FILE = path.resolve(__dirname, '../appLinks.ts');

/** Match quoted / template-string hash route literals (`#/workbench`, `#/roster?...`). */
const HASH_LITERAL_RE = /(['"`])#\/[^'"`]*\1/g;

/**
 * Contract-owned URL param keys (APP_LINK_PARAMS). Scanned as URL-seam access
 * patterns so domain strings like role="status" or source:'cluster' do not trip.
 */
const CONTRACT_PARAM_KEYS = [
  'tab',
  'panel',
  'panes',
  'advanced',
  'cluster',
  'status',
  'media',
  'run',
  'person',
  'personFilter',
  'queue',
  'face',
  'rq',
] as const;
const PARAM_KEY_ALT = CONTRACT_PARAM_KEYS.join('|');
/** `.get('tab')` / `.set('panel',` / `.delete('advanced')` / `useTabParam('tab',` */
const PARAM_ACCESS_RE = new RegExp(
  String.raw`(?:\.get|\.set|\.delete|useTabParam|useOverlayParam)\(\s*['"](${PARAM_KEY_ALT})['"]`,
  'g',
);
/** `getRouteParam(searchParams, 'person')` */
const GET_ROUTE_PARAM_RE = new RegExp(
  String.raw`getRouteParam\([^,]+,\s*['"](${PARAM_KEY_ALT})['"]`,
  'g',
);

/**
 * Reader-hook files allowed to spell contract param names as string literals.
 * Production emitters must use APP_LINK_PARAMS; these are the URL-read/write seams
 * that still take a raw name (or dual-spell during migration). Paths relative to js/admin.
 */
const PARAM_LITERAL_ALLOWLIST = new Set([
  'navigation/appLinks.ts',
  // Filter/media URL seam — status still dual-spelled; media uses APP_LINK_PARAMS.
  'hooks/useWorkbenchFilters.ts',
  // Tab/panel/advanced URL seam.
  'pages/workbench/WorkbenchNavContext.tsx',
  // Roster person/cluster/tab URL seams.
  'pages/roster/rosterRoute.ts',
  'pages/roster/RosterEntriesSection.tsx',
  'pages/RosterPage.tsx',
  // REST media list query uses status= (API, not hash vocabulary) — pinned exception.
  'api/workbenchMediaApi.ts',
]);

const isTestFile = (absolutePath: string): boolean => {
  const normalized = absolutePath.split(path.sep).join('/');
  return (
    normalized.includes('/__tests__/') ||
    normalized.endsWith('.test.ts') ||
    normalized.endsWith('.test.tsx')
  );
};

const isAppLinksOwner = (absolutePath: string): boolean => {
  const normalized = absolutePath.split(path.sep).join('/');
  const owner = APP_LINKS_FILE.split(path.sep).join('/');
  return normalized === owner || isTestFile(absolutePath);
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
    out.push(full);
  }
  return out;
};

const relAdmin = (absolutePath: string): string => path.relative(ADMIN_ROOT, absolutePath).split(path.sep).join('/');

describe('appLinks single-owner guard (REF-19)', () => {
  it('fails when any js/admin production file outside appLinks.ts contains a raw #/ hash literal', () => {
    const files = collectSourceFiles(ADMIN_ROOT).filter((f) => !isAppLinksOwner(f));
    expect(files.length).toBeGreaterThan(0);

    const violations: string[] = [];
    for (const file of files) {
      if (isTestFile(file)) {
        continue;
      }
      const source = readFileSync(file, 'utf8');
      // Strip line comments so prose like "generic #/roster" does not trip the gate.
      const withoutLineComments = source.replace(/\/\/.*$/gm, '');
      const matches = withoutLineComments.match(HASH_LITERAL_RE);
      if (matches && matches.length > 0) {
        violations.push(`${relAdmin(file)}: ${matches.join(', ')}`);
      }
    }

    expect(violations, `Raw hash literals must live in navigation/appLinks only:\n${violations.join('\n')}`).toEqual(
      [],
    );
  });

  it('fails when contract param-name literals appear outside the reader-hook allowlist', () => {
    const files = collectSourceFiles(ADMIN_ROOT).filter((f) => !isTestFile(f));
    expect(files.length).toBeGreaterThan(0);

    const violations: string[] = [];
    for (const file of files) {
      const rel = relAdmin(file);
      if (PARAM_LITERAL_ALLOWLIST.has(rel)) {
        continue;
      }

      const source = readFileSync(file, 'utf8');
      const withoutLineComments = source.replace(/\/\/.*$/gm, '');
      const found = new Set<string>();
      for (const re of [PARAM_ACCESS_RE, GET_ROUTE_PARAM_RE]) {
        re.lastIndex = 0;
        let match: RegExpExecArray | null;
        while ((match = re.exec(withoutLineComments)) !== null) {
          found.add(match[1] ?? match[0]);
        }
      }
      if (found.size > 0) {
        violations.push(`${rel}: ${[...found].sort().join(', ')}`);
      }
    }

    expect(
      violations,
      `Contract param names must use APP_LINK_PARAMS (or sit on the pinned reader allowlist):\n${violations.join('\n')}`,
    ).toEqual([]);
  });
});
