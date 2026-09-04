/**
 * FEBT2-LA-NEW-01 / FEBT2-LC-NEW-03 / FEBT2-W2-P-01 — the js/admin module graph
 * must be a DAG.
 *
 * `api/config -> utils/logger -> utils/appError -> utils/http -> api/config` was a
 * load-time ESM cycle. Entered from `api/config`, the `NonceRefreshFailedError`
 * binding was still in its temporal dead zone when `http.ts` evaluated, so a
 * top-level `class NonceRefreshError extends NonceRefreshFailedError` threw
 * `TypeError: Class extends value undefined` and took down every suite that
 * transitively imported `http.ts`. tsc cannot see it; only module evaluation can
 * (that non-coverage is written down in tsconfig.type-check.json, FEBT2-W2-P-02).
 *
 * SCOPE (FEBT2-W2-P-01): the walk seeds EVERY first-party `.ts`/`.tsx` file under
 * `js/admin`, not just the four former cycle members. `eslint import-x/no-cycle`
 * is scoped to `js/admin/utils/**` + `js/admin/api/**`; a cycle first closed in
 * `js/admin/hooks` or `js/admin/pages` — where several lanes add cross-imports —
 * would be outside that scope and would surface only as a mystery collection
 * crash. ARCH-13 (lexicons/engineering.md:563): a property that must always hold
 * gets structural enforcement over the whole tree, not over the corner where it
 * last broke.
 *
 * The widened walk immediately earned its keep: it found a live cycle
 * (`navigation/appLinks -> pages/workbench/WorkbenchNavContext -> hooks/useTabParam
 * -> hooks/pendingSearchWrites -> navigation/appLinks`) that the eslint scope could
 * not see. It is TYPE-ONLY at its closing edge and therefore not a load-time
 * hazard, which is why this file walks two graphs rather than one — see EdgeKind.
 *
 * GRPH-02 (lexicons/graph-theory.md:72) — a cycle is one indivisible unit; name the
 * back-edge and cut it. REF-19 (lexicons/engineering.md:338) — the resolution rules
 * live here once. RLSE-05 (lexicons/engineering.md:696) — a walker that silently
 * drops an edge it cannot resolve reports "acyclic" while looking at less than the
 * real graph, so every unresolved first-party specifier throws.
 */

// ORDER IS THE ASSERTION. `api/config` is imported FIRST, deliberately: this is the
// entry point that used to leave `NonceRefreshFailedError` undefined at http.ts's
// class-extends site. Do not reorder these two imports, and do not "tidy" them.
import { registerConfig, resetConfigCache, NonceRefreshFailedError } from '../../api/config';
import { toNonceRefreshError, NonceRefreshError } from '../http';

import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { afterEach, describe, expect, it } from 'vitest';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
/** Plugin root. Anchored on this file, never on `process.cwd()`, so the walk is
 *  independent of where vitest was invoked from. */
const PLUGIN_ROOT = path.resolve(__dirname, '../../../..');
const ADMIN_ROOT = path.resolve(__dirname, '../..');

const UTILS = 'js/admin/utils';
const API = 'js/admin/api';

/**
 * The four former cycle members. Any of these missing from the walked seed set is
 * a red test, not a quiet reduction in coverage: this is the fail-closed floor
 * under the tree-wide walk below.
 */
const REQUIRED_SEEDS = [`${UTILS}/http.ts`, `${UTILS}/appError.ts`, `${UTILS}/logger.ts`, `${API}/config.ts`] as const;

/**
 * Directories the finding calls out by name as the places a NEW cycle is most
 * likely to close, because several lanes add cross-imports there. Asserting the
 * walk reaches them keeps a future "scope it back down to utils" edit honest.
 */
const REQUIRED_SEED_DIRS = ['js/admin/hooks/', 'js/admin/pages/', 'js/admin/components/'] as const;

/**
 * Every static `import`/`export ... from` specifier. Group 1 is the clause between
 * the keyword and `from`, which is what decides the edge KIND below.
 */
const SPECIFIER = /(?:^|\n)\s*(?:import|export)\b([^;\n]*?)from\s*['"]([^'"]+)['"]/g;

/** Bare side-effect imports (`import './x';`) evaluate the module and are edges too. */
const SIDE_EFFECT = /(?:^|\n)\s*import\s*['"]([^'"]+)['"]\s*;/g;

/**
 * TWO GRAPHS, ONE FILE — they answer different questions and only one of them is
 * the load-time hazard.
 *
 * `value`: the module-EVALUATION graph. A cycle here is the defect this file
 * exists for: the base binding is in its TDZ when the extending class evaluates.
 *
 * `type`: `import type X` / `export type X from` is erased by TypeScript before
 * anything runs, so it creates no evaluation edge and cannot produce a TDZ
 * failure. Note this is the *statement-level* modifier only: `import { type A, B }`
 * still pulls `B` at runtime and is therefore a value edge.
 *
 * Both are walked. Collapsing them into one graph would either report a harmless
 * erased edge as a load-time cycle (a false red that pressures the next agent to
 * weaken the check — sr-001) or, if type edges were simply dropped, lose the
 * design signal entirely. They are reported separately instead.
 */
type EdgeKind = 'value' | 'type';

const TYPE_ONLY_CLAUSE = /^type\b/;

/**
 * Non-module assets. A `.json`/`.css`/image import is a leaf with no imports of
 * its own, so it cannot participate in a cycle. Enumerated explicitly rather than
 * handled by a catch-all `catch { continue }`: an extension nobody has thought
 * about must reach the throw below, not be silently swallowed (RLSE-05).
 */
const ASSET_EXTENSIONS = ['.json', '.css', '.scss', '.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp'];

/** Resolution candidates, in Node/Vite order. */
const CANDIDATE_SUFFIXES = ['.ts', '.tsx', '.js', '.jsx', '/index.ts', '/index.tsx', '/index.js', '/index.jsx'];

/** All first-party `.ts`/`.tsx` under `js/admin`, as plugin-root-relative posix paths. */
const collectAdminSources = (dir: string, out: string[] = []): string[] => {
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) {
      collectAdminSources(full, out);
      continue;
    }
    if (!/\.(ts|tsx)$/.test(entry)) {
      continue;
    }
    out.push(path.relative(PLUGIN_ROOT, full).split(path.sep).join('/'));
  }
  return out;
};

/** Seeds: the whole `js/admin` tree, sorted so a failure is reproducible. */
const SEEDS: readonly string[] = collectAdminSources(ADMIN_ROOT).sort();

const readImports = (root: string, rel: string, kinds: readonly EdgeKind[]): string[] => {
  const source = readFileSync(path.join(root, rel), 'utf8');
  const specifiers: string[] = [];
  for (const match of source.matchAll(SPECIFIER)) {
    const kind: EdgeKind = TYPE_ONLY_CLAUSE.test(match[1].trim()) ? 'type' : 'value';
    if (kinds.includes(kind)) {
      specifiers.push(match[2]);
    }
  }
  if (kinds.includes('value')) {
    for (const match of source.matchAll(SIDE_EFFECT)) {
      specifiers.push(match[1]);
    }
  }
  const dir = path.posix.dirname(rel);
  const resolved: string[] = [];
  for (const specifier of specifiers) {
    if (!specifier.startsWith('.')) {
      continue; // external package — never part of a first-party cycle
    }
    if (ASSET_EXTENSIONS.some((extension) => specifier.endsWith(extension))) {
      continue; // leaf asset, imports nothing, cannot close a cycle
    }
    const base = path.posix.normalize(path.posix.join(dir, specifier));
    let hit: string | undefined;
    for (const suffix of CANDIDATE_SUFFIXES) {
      const candidate = `${base}${suffix}`;
      if (existsSync(path.join(root, candidate))) {
        hit = candidate;
        break;
      }
    }
    // Fail closed: a relative specifier this walker cannot resolve is an edge it
    // would otherwise drop, and a dropped edge can hide the cycle it was added to
    // find (ARCH-13 — the check must not be able to pass by seeing less).
    if (hit === undefined) {
      throw new Error(`unresolvable first-party specifier "${specifier}" in ${rel}`);
    }
    resolved.push(hit);
  }
  return resolved;
};

/**
 * Iterative DFS (an explicit frame stack, not recursion): the `js/admin` closure is
 * deep enough that a recursive walk risks a stack overflow, and a RangeError would
 * read as an infrastructure failure rather than as the cycle report this owes its
 * caller. Returns the first cycle found as a module path, or null. `kinds` selects
 * which edges count; see EdgeKind.
 */
const findCycle = (
  root: string,
  seeds: readonly string[],
  kinds: readonly EdgeKind[] = ['value', 'type'],
): string[] | null => {
  const onStack = new Set<string>();
  const done = new Set<string>();

  for (const seed of seeds) {
    if (done.has(seed)) {
      continue;
    }
    const stack: { rel: string; edges: string[]; index: number }[] = [
      { rel: seed, edges: readImports(root, seed, kinds), index: 0 },
    ];
    onStack.add(seed);

    while (stack.length > 0) {
      const frame = stack[stack.length - 1];
      if (frame.index >= frame.edges.length) {
        stack.pop();
        onStack.delete(frame.rel);
        done.add(frame.rel);
        continue;
      }
      const next = frame.edges[frame.index];
      frame.index += 1;
      if (onStack.has(next)) {
        const path_ = stack.map((entry) => entry.rel);
        return [...path_.slice(path_.indexOf(next)), next];
      }
      if (done.has(next)) {
        continue;
      }
      onStack.add(next);
      stack.push({ rel: next, edges: readImports(root, next, kinds), index: 0 });
    }
  }
  return null;
};

/** Adjacency for the full closure reachable from `seeds`, keyed by module path. */
const buildGraph = (root: string, seeds: readonly string[], kinds: readonly EdgeKind[]): Map<string, string[]> => {
  const graph = new Map<string, string[]>();
  const queue = [...seeds];
  while (queue.length > 0) {
    const rel = queue.pop();
    if (rel === undefined || graph.has(rel)) {
      continue;
    }
    const edges = readImports(root, rel, kinds);
    graph.set(rel, edges);
    queue.push(...edges);
  }
  return graph;
};

/**
 * Every module that lies on at least one cycle (i.e. is a member of a non-trivial
 * strongly connected component), sorted so the set can be pinned. `findCycle`
 * reports only the FIRST cycle it meets, which is the right shape for a hard gate
 * but useless for an allowlist: an allowlist that can only see one member would go
 * green the moment a second, unrelated cycle appeared earlier in DFS order
 * (ARCH-13 — the check must not pass by seeing less). Modules, not edges: an SCC's
 * edge set churns on every unrelated import added inside it, which would make the
 * pin rot for reasons that have nothing to do with the cycle.
 */
const findCyclicModules = (root: string, seeds: readonly string[], kinds: readonly EdgeKind[]): string[] => {
  const graph = buildGraph(root, seeds, kinds);
  const reaches = (from: string, target: string): boolean => {
    const seen = new Set<string>();
    const queue = [from];
    while (queue.length > 0) {
      const node = queue.pop();
      if (node === undefined || seen.has(node)) {
        continue;
      }
      seen.add(node);
      if (node === target) {
        return true;
      }
      queue.push(...(graph.get(node) ?? []));
    }
    return false;
  };

  const cyclic: string[] = [];
  for (const [from, edges] of graph) {
    if ([...new Set(edges)].some((to) => reaches(to, from))) {
      cyclic.push(from);
    }
  }
  return [...new Set(cyclic)].sort();
};

/**
 * The one known TYPE-ONLY cycle in `js/admin`, pinned as its SCC membership.
 *
 * Discovered by this widened walk (FEBT2-W2-P-01) — `import-x/no-cycle` is scoped
 * to `js/admin/utils/**` + `js/admin/api/**` and could not see it, which is exactly
 * the blind spot the finding predicted. It survives the EVALUATION gate above
 * because the only edge closing it, `navigation/appLinks.ts -> pages/workbench/
 * WorkbenchNavContext.tsx`, is `import type { WorkbenchTab }` and is erased before
 * anything runs; the return path (WorkbenchNavContext -> hooks/useTabParam ->
 * hooks/pendingSearchWrites -> navigation/appLinks) is all value edges.
 *
 * Pinned rather than cut: every file in it is owned by another lane. Cutting it
 * means relocating `WorkbenchTab` to a leaf type module, which is that owner's
 * call. Raised as a cross-lane item under FEBT2-W2-P-01.
 */
const KNOWN_TYPE_ONLY_CYCLE_MODULES = [
  'js/admin/hooks/pendingSearchWrites.ts',
  'js/admin/hooks/useOverlayParam.ts',
  'js/admin/hooks/useTabParam.ts',
  'js/admin/navigation/appLinks.ts',
  'js/admin/pages/workbench/WorkbenchNavContext.tsx',
] as const;

describe('js/admin module graph [FEBT2-LA-NEW-01][FEBT2-W2-P-01]', () => {
  afterEach(() => {
    resetConfigCache();
    delete window.AltContextAdmin;
  });

  it('walks the whole js/admin tree, including every former cycle member [fail-closed seeds]', () => {
    // An emptied or trimmed seed set makes findCycle() trivially return null.
    // The check must not be able to pass by looking at nothing (ARCH-13).
    expect(new Set(SEEDS).size, 'SEEDS contains duplicates').toBe(SEEDS.length);
    expect(SEEDS.length, 'js/admin walk collected implausibly few files').toBeGreaterThan(100);
    for (const required of REQUIRED_SEEDS) {
      expect(SEEDS, `SEEDS no longer walks ${required}`).toContain(required);
    }
    for (const dir of REQUIRED_SEED_DIRS) {
      expect(
        SEEDS.some((seed) => seed.startsWith(dir)),
        `SEEDS no longer reaches ${dir} — the walk has been narrowed back to the corner the cycle last broke in`,
      ).toBe(true);
    }
  });

  it('has no EVALUATION cycle anywhere in js/admin [GRPH-02][hard gate]', () => {
    // The load-time property. A failure here is the outage shape: some suite dies
    // at collection with "Class extends value undefined" and names the wrong file.
    const cycle = findCycle(PLUGIN_ROOT, SEEDS, ['value']);
    expect(cycle === null ? 'acyclic' : `CYCLE: ${cycle.join(' -> ')}`).toBe('acyclic');
  });

  it('has no UNPINNED type-inclusive cycle in js/admin [GRPH-02][design gate]', () => {
    // Type-only edges are erased and cannot deadlock module evaluation, but a
    // type-only cycle still means two modules cannot be reasoned about
    // independently, and `import-x/no-cycle` counts them. Pinned, not ignored:
    // a NEW one is red even though the known one is not this lane's to cut.
    const cyclic = findCyclicModules(PLUGIN_ROOT, SEEDS, ['value', 'type']);
    const unexpected = cyclic.filter(
      (module) => !(KNOWN_TYPE_ONLY_CYCLE_MODULES as readonly string[]).includes(module),
    );
    expect(unexpected, `module(s) newly on an import cycle: ${unexpected.join(' | ')}`).toEqual([]);
  });

  it('the pinned type-only cycle still exists [no rotting allowlist]', () => {
    // If an owner cuts the pinned cycle, this goes red and the pin must be
    // deleted. An allowlist nobody is forced to prune becomes a permanent hole
    // (ARCH-13, lexicons/engineering.md:563).
    const cyclic = findCyclicModules(PLUGIN_ROOT, SEEDS, ['value', 'type']);
    expect(
      cyclic,
      'the pinned appLinks/WorkbenchNavContext type-only cycle is gone — delete KNOWN_TYPE_ONLY_CYCLE_MODULES',
    ).toEqual([...KNOWN_TYPE_ONLY_CYCLE_MODULES]);
  });

  it('distinguishes a type-only cycle from an evaluation cycle [TEST-15]', () => {
    const root = mkdtempSync(path.join(tmpdir(), 'acx-cycle-'));
    try {
      // a -> b is TYPE-ONLY; b -> a is a value import. Erased at runtime, so the
      // evaluation graph is acyclic while the type-inclusive graph is not.
      writeFileSync(
        path.join(root, 'a.ts'),
        "import type { B } from './b';\nexport type A = B;\nexport const a = 1;\n",
      );
      writeFileSync(
        path.join(root, 'b.ts'),
        "import { a } from './a';\nexport interface B { v: number }\nexport const b = a;\n",
      );

      expect(findCycle(root, ['a.ts'], ['value'])).toBe(null);
      expect(findCycle(root, ['a.ts'], ['value', 'type'])?.join(' -> ')).toBe('a.ts -> b.ts -> a.ts');
      expect(findCyclicModules(root, ['a.ts'], ['value', 'type'])).toEqual(['a.ts', 'b.ts']);
      expect(findCyclicModules(root, ['a.ts'], ['value'])).toEqual([]);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('an inline `{ type A, B }` import is still a value edge [erasure boundary]', () => {
    const root = mkdtempSync(path.join(tmpdir(), 'acx-cycle-'));
    try {
      writeFileSync(
        path.join(root, 'a.ts'),
        "import { type B, bee } from './b';\nexport const a = bee;\nexport type A = B;\n",
      );
      writeFileSync(
        path.join(root, 'b.ts'),
        "import { a } from './a';\nexport interface B { v: number }\nexport const bee = a;\n",
      );

      expect(findCycle(root, ['a.ts'], ['value'])?.join(' -> ')).toBe('a.ts -> b.ts -> a.ts');
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('reports the back-edge when a real cycle exists [TEST-15 discrimination guard]', () => {
    // The detector is run against a graph that IS cyclic, using the same walker
    // over real files on disk. The fixture is materialised in a temp directory
    // rather than committed under js/admin, because a committed cycle would be a
    // genuine cycle: the tree-wide walk above and `import-x/no-cycle` would both
    // (correctly) go red on it, and the only way to keep it would be to weaken
    // one of them (sr-001). Without this case, "acyclic" above is a green nobody
    // has ever seen go red (TEST-15, lexicons/engineering.md:396).
    const root = mkdtempSync(path.join(tmpdir(), 'acx-cycle-'));
    try {
      mkdirSync(path.join(root, 'a/b'), { recursive: true });
      writeFileSync(path.join(root, 'a/b/one.ts'), "import { two } from './two';\nexport const one = two;\n");
      writeFileSync(path.join(root, 'a/b/two.ts'), "import { one } from './one';\nexport const two = one;\n");

      const cycle = findCycle(root, ['a/b/one.ts']);
      expect(cycle, 'the DFS failed to report a known two-node cycle').not.toBe(null);
      expect(cycle?.join(' -> ')).toBe('a/b/one.ts -> a/b/two.ts -> a/b/one.ts');
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('follows a re-export edge and an index barrel into a cycle [edge-kind coverage]', () => {
    // `export ... from` and `<dir>/index.ts` resolution are separate code paths
    // from a plain value import; both were load-bearing in the original defect
    // (utils/http re-exports the taxonomy, api/recognition is a barrel).
    const root = mkdtempSync(path.join(tmpdir(), 'acx-cycle-'));
    try {
      mkdirSync(path.join(root, 'pkg'), { recursive: true });
      writeFileSync(path.join(root, 'entry.ts'), "export { deep } from './pkg';\n");
      writeFileSync(path.join(root, 'pkg/index.ts'), "import '../entry';\nexport const deep = 1;\n");

      const cycle = findCycle(root, ['entry.ts']);
      expect(cycle?.join(' -> ')).toBe('entry.ts -> pkg/index.ts -> entry.ts');
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('throws rather than dropping an edge it cannot resolve [fail-closed walker]', () => {
    const root = mkdtempSync(path.join(tmpdir(), 'acx-cycle-'));
    try {
      writeFileSync(path.join(root, 'orphan.ts'), "import { gone } from './not-here';\nexport const x = gone;\n");
      expect(() => findCycle(root, ['orphan.ts'])).toThrow(
        /unresolvable first-party specifier "\.\/not-here" in orphan\.ts/,
      );
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('does not mistake a diamond (shared dependency, no back-edge) for a cycle [negative control]', () => {
    const root = mkdtempSync(path.join(tmpdir(), 'acx-cycle-'));
    try {
      writeFileSync(path.join(root, 'top.ts'), "import './left';\nimport './right';\nexport const t = 1;\n");
      writeFileSync(path.join(root, 'left.ts'), "export { leaf } from './leaf';\n");
      writeFileSync(path.join(root, 'right.ts'), "export { leaf } from './leaf';\n");
      writeFileSync(path.join(root, 'leaf.ts'), 'export const leaf = 1;\n');

      expect(findCycle(root, ['top.ts'])).toBe(null);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('entering the graph from api/config first still yields a usable NonceRefreshError [FEBT2-LC-NEW-03]', () => {
    // If the cycle is back, this file dies at collection with
    // "Class extends value undefined" and never reaches this assertion.
    const source = new NonceRefreshFailedError({
      message: 'refresh timed out',
      causeStatus: undefined,
      bodyPreview: '',
    });
    const tagged = toNonceRefreshError(source);

    expect(tagged).toBeInstanceOf(NonceRefreshError);
    expect(tagged).toBeInstanceOf(NonceRefreshFailedError);
    expect(tagged._tag).toBe('nonce_refresh');
    expect(tagged.message).toBe('refresh timed out');
    expect(tagged.cause).toBe(source);
  });

  it('re-wrapping an already-tagged nonce error is idempotent', () => {
    const tagged = toNonceRefreshError(new NonceRefreshFailedError({ message: 'once' }));
    expect(toNonceRefreshError(tagged)).toBe(tagged);
  });

  it('NonceRefreshError preserves causeStatus and bodyPreview from its source', () => {
    registerConfig({ nonce: 'abcdef0123', ajaxUrl: '/x', endpoints: {} });
    const tagged = toNonceRefreshError(
      new NonceRefreshFailedError({ message: 'rejected', causeStatus: 403, bodyPreview: '-1' }),
    );
    expect(tagged.causeStatus).toBe(403);
    expect(tagged.bodyPreview).toBe('-1');
  });
});
