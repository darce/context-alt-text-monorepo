/**
 * E21-9 Slice 6: roster URL retarget + no tab=clusters producer.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { getConfig, registerConfig, resetConfigCache } from '../../api/config';
import { mediaEditUrl, rosterUrl } from '../adminUrls';

const adminRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const pluginRoot = path.resolve(adminRoot, '../..');

/** Walk production sources (exclude tests/docs/archives) looking for retired producers. */
const collectSourceFiles = (dir: string, out: string[] = []): string[] => {
  for (const entry of readdirSync(dir)) {
    if (
      entry === 'node_modules' ||
      entry === 'dist' ||
      entry === 'vendor' ||
      entry === '__tests__' ||
      entry === 'docs' ||
      entry === 'archive'
    ) {
      continue;
    }
    const full = path.join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) {
      collectSourceFiles(full, out);
      continue;
    }
    if (
      entry.endsWith('.test.ts') ||
      entry.endsWith('.test.tsx') ||
      entry.endsWith('.spec.ts') ||
      entry.endsWith('.spec.tsx')
    ) {
      continue;
    }
    if (/\.(ts|tsx|php|js|jsx)$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
};

describe('adminUrls (E21-9 Slice 6)', () => {
  beforeEach(() => {
    resetConfigCache();
    vi.stubGlobal('location', { origin: 'https://example.test' });
  });

  afterEach(() => {
    resetConfigCache();
    vi.unstubAllGlobals();
  });

  it('rosterUrl falls back to roster root without tab=clusters', () => {
    const url = rosterUrl();
    expect(url).toContain('page=alt-context-roster');
    expect(url).not.toContain('tab=clusters');
    expect(url).not.toContain('tab=');
  });

  it('rosterUrl uses localized adminUrls.roster when configured', () => {
    registerConfig({
      nonce: 'n',
      endpoints: {},
      adminUrls: {
        roster: '/wp-admin/admin.php?page=alt-context-roster&person=p1',
      },
    });
    const url = rosterUrl();
    expect(url).toContain('page=alt-context-roster');
    expect(url).toContain('person=p1');
    expect(url).not.toContain('tab=clusters');
    expect(getConfig().adminUrls.roster).toContain('page=alt-context-roster');
  });

  it('mediaEditUrl still builds post edit links', () => {
    const url = mediaEditUrl(42);
    expect(url).toContain('post=42');
    expect(url).toContain('action=edit');
  });

  it('does not export retired rosterClustersUrl symbol', async () => {
    const mod = await import('../adminUrls');
    expect('rosterClustersUrl' in mod).toBe(false);
    expect(typeof mod.rosterUrl).toBe('function');
  });
});

describe('E21-9 retired surface producer guard', () => {
  it('no production producer of tab=clusters remains (grep-asserted)', () => {
    const roots = [
      path.join(pluginRoot, 'js', 'admin'),
      path.join(pluginRoot, 'src'),
    ];
    const hits: string[] = [];
    for (const root of roots) {
      for (const file of collectSourceFiles(root)) {
        const text = readFileSync(file, 'utf8');
        // Producer = constructs a URL/path with tab=clusters (not legacy parse comments/tests).
        if (/[?&]tab=clusters|page=alt-context-roster&tab=clusters|'tab=clusters'|"tab=clusters"|`tab=clusters`/.test(text)) {
          // Allow legacy *consumer* docs in comments that only describe parse behavior,
          // but never a string literal used as a URL target containing the param.
          // Hard fail any literal path that embeds the retired tab.
          if (
            text.includes('page=alt-context-roster&tab=clusters') ||
            text.includes('&tab=clusters') ||
            /[`'"][^`'"]*tab=clusters[^`'"]*[`'"]/.test(text)
          ) {
            // rosterRoute + page comments may mention the legacy param for parse docs;
            // only flag when the file also looks like a URL builder/localizer.
            const rel = path.relative(pluginRoot, file);
            const isLegacyParseCommentOnly =
              (rel.includes('rosterRoute.ts') || rel.includes('RosterPage')) &&
              !text.includes('page=alt-context-roster&tab=clusters') &&
              !/admin_url\s*\(\s*['"]admin\.php\?page=alt-context-roster&tab=clusters/.test(text);
            if (!isLegacyParseCommentOnly) {
              hits.push(rel);
            }
          }
        }
      }
    }
    expect(hits).toEqual([]);
  });

  it('retired RosterClustersTab module and ROSTER_TABS symbol stay gone', () => {
    const rosterDir = path.join(pluginRoot, 'js', 'admin', 'pages', 'roster');
    const files = readdirSync(rosterDir);
    expect(files).not.toContain('RosterClustersTab.tsx');
    expect(files).not.toContain('ClusterGrid.tsx');

    const adminJs = collectSourceFiles(path.join(pluginRoot, 'js', 'admin'));
    const importHits = adminJs.filter((file) => {
      const text = readFileSync(file, 'utf8');
      return (
        /RosterClustersTab/.test(text) ||
        /ROSTER_TABS/.test(text) ||
        /rosterClustersUrl/.test(text)
      );
    });
    expect(importHits.map((f) => path.relative(pluginRoot, f))).toEqual([]);
  });
});
