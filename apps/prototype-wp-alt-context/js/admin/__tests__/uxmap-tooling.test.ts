/**
 * Prettier ownership of `docs/ux-maps/` — the formatter half of the ux-map SSOT contract.
 *
 * WBUX6-W4-A-01: the `.md` files are rendered by `docs/ux-maps/render_ux_maps.py`.
 * Prettier reflows that render, the next render undoes the reflow, and the two rewrite
 * each other forever, so the parity gate can no longer tell real drift from formatter
 * churn. A derived artifact gets exactly one writer (DATA-14).
 *
 * WBUX6-W4-A-07: the generator itself lives in that directory and Prettier has no Python
 * parser, so an aggregate glob over `docs/ux-maps/**` that is not extension-scoped exits
 * non-zero with `No parser could be inferred` instead of checking any map.
 *
 * Both are asserted through Prettier's own resolver (`getFileInfo` with the real
 * `.prettierignore`) rather than by string-matching the ignore file, so a rule that stops
 * matching — a rename, a glob typo, a moved ignore file — turns this red (TEST-15: the
 * assertion must be able to go red for the reason it claims to guard).
 */
import { readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { getFileInfo } from 'prettier';
import { describe, expect, it } from 'vitest';

const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const uxMapsDir = path.join(pluginRoot, 'docs/ux-maps');
const ignorePath = path.join(pluginRoot, '.prettierignore');

const resolve = async (fileName: string) =>
  getFileInfo(path.join(uxMapsDir, fileName), { ignorePath, resolveConfig: true });

/**
 * Recursive, because the glob this models is `docs/ux-maps/**`. A top-level-only sweep
 * cannot see `__pycache__/render_ux_maps.cpython-*.pyc`, which CPython writes beside the
 * generator the first time anyone runs it — and which killed the glob in exactly the way
 * WBUX6-W4-A-07 describes, after that finding was believed fixed.
 */
const uxMapFiles = () =>
  readdirSync(uxMapsDir, { withFileTypes: true, recursive: true })
    .filter((entry) => entry.isFile() && !entry.name.startsWith('.'))
    .map((entry) => path.relative(uxMapsDir, path.join(entry.parentPath, entry.name)));

describe('prettier ownership of docs/ux-maps', () => {
  it('reads a non-empty ux-map directory', () => {
    expect(uxMapFiles().length, 'no files found — every sweep below would pass vacuously').toBeGreaterThan(3);
  });

  it('ignores every generated .md so the renderer is its only writer', async () => {
    const mdFiles = uxMapFiles().filter((name) => name.endsWith('.md'));
    expect(mdFiles.length, 'no .md renders found').toBeGreaterThan(0);
    const owned: string[] = [];
    for (const name of mdFiles) {
      if (!(await resolve(name)).ignored) {
        owned.push(name);
      }
    }
    expect(
      owned,
      `prettier still claims these generated renders — the generator and the formatter will rewrite each other: ${owned.join(', ')}`,
    ).toEqual([]);
  });

  it('keeps the hand-authored *.uxmap.json sources formatted, not ignored', async () => {
    const jsonFiles = uxMapFiles().filter((name) => name.endsWith('.uxmap.json'));
    expect(jsonFiles.length, 'no *.uxmap.json sources found').toBeGreaterThan(0);
    for (const name of jsonFiles) {
      const info = await resolve(name);
      expect(info.ignored, `${name} is a hand-authored source — prettier must stay its owner`).toBe(false);
      expect(info.inferredParser, `${name} must resolve to the json parser`).toBe('json');
    }
  });

  it('leaves no file a directory-wide prettier glob cannot parse', async () => {
    const unparseable: string[] = [];
    for (const name of uxMapFiles()) {
      const info = await resolve(name);
      if (!info.ignored && info.inferredParser === null) {
        unparseable.push(name);
      }
    }
    expect(
      unparseable,
      `prettier "docs/ux-maps/**" would die with "No parser could be inferred" on: ${unparseable.join(', ')}`,
    ).toEqual([]);
  });
});
