/**
 * Guards the fixture's own silent-staleness failure mode (FEBT2-LG-NEW-02).
 *
 * `BUILD_INPUT_GLOBS` enumerates extensions. Add a build-input file type it does not
 * list — an `.svg` imported by rollup, an `.mjs`, a font — and nothing errors: the
 * fingerprint stops changing, the cached artifact is reused, and every style suite
 * asserts against yesterday's bundle while reporting green (RLSE-05).
 *
 * `expect(uncoveredBuildInputs()).toEqual([])` alone would be a passing test that cannot
 * fail today, so the pure `selectUnfingerprinted` seam is exercised with a planted
 * unlisted file — the permanent discrimination guard TEST-15 asks for.
 */
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, join } from 'node:path';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import type { ProductionCssBundle } from './productionCssBundle';
import {
  artifactFixtureRootForAppRoot,
  type ArtifactEntry,
  buildInputCandidates,
  fingerprintedBuildInputs,
  loadProductionCssBundle,
  manifestBuildSources,
  MAX_RETAINED_ARTIFACTS,
  type NamespaceEntry,
  registerAndPruneNamespaces,
  selectArtifactsToPrune,
  selectNamespacesToPrune,
  selectUnfingerprinted,
  uncoveredBuildInputs,
  unfingerprintedManifestSources,
} from './productionCssBundle';

const ROLLUP_ENTRY_POINTS = ['js/admin/main.tsx', 'js/attachment-edit/main.tsx'] as const;

describe('build-input fingerprint coverage [FEBT2-LG-NEW-02]', () => {
  it('hashes every non-test file under js/', () => {
    const uncovered = uncoveredBuildInputs();

    expect(
      uncovered,
      'These files can change the production bundle but are not hashed by BUILD_INPUT_GLOBS, ' +
        'so editing them reuses a stale cached artifact and the style suites pass against the ' +
        'old CSS. Add their extension to BUILD_INPUT_GLOBS in productionCssBundle.ts:\n' +
        uncovered.join('\n'),
    ).toEqual([]);
  });

  it('reports a build input whose extension nobody listed', () => {
    const planted = 'js/admin/styles/icons/logo.svg';

    expect(selectUnfingerprinted([...fingerprintedBuildInputs(), planted], fingerprintedBuildInputs())).toEqual([
      planted,
    ]);
  });

  it('reports nothing when every candidate is hashed', () => {
    const fingerprinted = fingerprintedBuildInputs();

    expect(selectUnfingerprinted(fingerprinted, fingerprinted)).toEqual([]);
  });

  it('hashes both rollup entry points and no test source', () => {
    const fingerprinted = fingerprintedBuildInputs();

    for (const entry of ROLLUP_ENTRY_POINTS) {
      expect(fingerprinted).toContain(entry);
    }
    expect(fingerprinted.filter((file) => file.includes('__tests__'))).toEqual([]);
    expect(buildInputCandidates().filter((file) => file.includes('__tests__'))).toEqual([]);
  });

  it('offers every hashed js/ file as a candidate, so the detector cannot be narrowed blind', () => {
    const candidates = buildInputCandidates();

    // A candidate glob narrowed to one extension still reports "nothing uncovered" while
    // seeing none of the file types that could go missing (mutant LG2-M2).
    expect(candidates).toEqual(
      expect.arrayContaining(fingerprintedBuildInputs().filter((file) => file.startsWith('js/'))),
    );
    for (const extension of ['.ts', '.tsx', '.scss']) {
      expect(candidates.some((file) => file.endsWith(extension))).toBe(true);
    }
  });
});

describe('rollup agrees with the fingerprint [FEBT2-LG-NEW-02]', () => {
  let bundle: ProductionCssBundle;
  const cacheRoot = dirname(artifactFixtureRootForAppRoot('/unused/app-root'));
  const retiredNamespaces = Array.from({ length: 6 }, (_, index) =>
    join(cacheRoot, `retired-fixture-${process.pid}-${index}`),
  );

  // A cold cache runs a real `vite build`, which is far past the 5s default. The
  // fixture memoises per fingerprint, so this is paid once for the whole suite.
  beforeAll(() => {
    for (const [index, namespaceRoot] of retiredNamespaces.entries()) {
      mkdirSync(join(namespaceRoot, 'old-fingerprint'), { recursive: true });
      writeFileSync(
        join(namespaceRoot, 'namespace-owner.json'),
        `${JSON.stringify({ appRoot: join(cacheRoot, `removed-worktree-${process.pid}-${index}`) })}\n`,
        'utf8',
      );
    }
    bundle = loadProductionCssBundle();
  }, 600_000);

  afterAll(() => {
    for (const namespaceRoot of retiredNamespaces) {
      rmSync(namespaceRoot, { recursive: true, force: true });
    }
  });

  it('collects namespaces accumulated by retired worktrees before building', () => {
    expect(retiredNamespaces.filter((namespaceRoot) => existsSync(namespaceRoot))).toEqual([]);
  });

  it('hashes every source rollup recorded in its manifest', () => {
    // Assert the input side too: an empty source list passes the coverage check while
    // proving nothing (mutant LG2-M7).
    expect(manifestBuildSources(bundle)).toEqual([...ROLLUP_ENTRY_POINTS].sort());
    expect(unfingerprintedManifestSources(bundle)).toEqual([]);
  });

  it('ships both entry points, so the post.php bundle is really built', () => {
    const manifest = JSON.parse(readFileSync(join(bundle.outDir, '.vite', 'manifest.json'), 'utf8')) as Record<
      string,
      { isEntry?: boolean; file?: string }
    >;

    const entries = Object.keys(manifest).filter((key) => manifest[key].isEntry === true);
    expect(entries.sort()).toEqual([...ROLLUP_ENTRY_POINTS].sort());
  });
});

/**
 * Retention policy for $TMPDIR/acx-style-bundle (FEBT2-W2-U-03).
 *
 * The TTL alone bounds artifact *age*, never artifact *count*. In a parallel-lane wave every
 * edit in every lane mints a new fingerprint and a full build artifact, so directories accrue
 * far faster than a 24h cutoff collects them — an unbounded cache is a leak (RES-08), and this
 * one filled the host volume twice. Every case below is stated in explicit millisecond
 * arithmetic rather than `Date.now()`: a policy test that reads the wall clock is
 * non-deterministic by construction (TEST-08).
 */
describe('artifact retention policy [FEBT2-W2-U-03]', () => {
  const CUTOFF = 1_000_000;
  const at = (name: string, lastUsedMs: number): ArtifactEntry => ({ name, lastUsedMs });
  /** `n` fresh artifacts, newest first by name: `fresh-0` is the most recently used. */
  const freshRun = (n: number): ArtifactEntry[] =>
    Array.from({ length: n }, (_, i) => at(`fresh-${i}`, CUTOFF + 1_000 - i));

  it('gives concurrent lanes independent eviction scopes', () => {
    const laneA = artifactFixtureRootForAppRoot('/worktrees/feature-a/apps/prototype-wp-alt-context');
    const laneAAgain = artifactFixtureRootForAppRoot('/worktrees/feature-a/apps/./prototype-wp-alt-context');
    const laneB = artifactFixtureRootForAppRoot('/worktrees/feature-b/apps/prototype-wp-alt-context');

    const laneAKey = basename(laneA);
    const laneBKey = basename(laneB);
    expect(laneAAgain).toBe(laneA);
    for (const key of [laneAKey, laneBKey]) {
      expect(key.length).toBeGreaterThan(0);
      expect(key.length).toBeLessThanOrEqual(64);
      expect(key).toMatch(/^[A-Za-z0-9._-]+$/);
    }

    expect(
      laneA,
      'Sibling lanes sharing one artifact root consume the same four-entry LRU and can evict the ' +
        "current lane's CSS bundle while its gate is still running.",
    ).not.toBe(laneB);
  });

  it('keeps the in-use artifact even when it is the oldest thing on disk', () => {
    const entries = [at('in-use', 0), ...freshRun(2)];

    expect(selectArtifactsToPrune(entries, 'in-use', CUTOFF)).not.toContain('in-use');
  });

  it('never prunes the lock directory', () => {
    // `.lock` has no stamp, so it reads as lastUsedMs 0 — maximally expired. Deleting it
    // out from under a holder would let a second process build into the same directory.
    const entries = [at('.lock', 0), at('stale', CUTOFF - 1)];

    expect(selectArtifactsToPrune(entries, 'keep', CUTOFF)).toEqual(['stale']);
  });

  it('prunes artifacts older than the cutoff and keeps ones exactly at it', () => {
    const entries = [at('older', CUTOFF - 1), at('exactly-at', CUTOFF), at('newer', CUTOFF + 1)];

    // Boundary pinned in both directions: `<` widened to `<=` deletes `exactly-at`, and
    // narrowed to a strict `<` on the wrong side spares `older` (mutants G-M1 / G-M2).
    expect(selectArtifactsToPrune(entries, 'keep', CUTOFF)).toEqual(['older']);
  });

  it('caps the count even when every artifact is fresh — the TTL alone cannot', () => {
    const entries = freshRun(20);

    const doomed = selectArtifactsToPrune(entries, 'keep', CUTOFF);

    // The whole point of the finding: 20 same-hour artifacts, zero of them expired.
    expect(entries.every((entry) => entry.lastUsedMs >= CUTOFF)).toBe(true);
    expect(doomed.length).toBeGreaterThan(0);
    expect(entries.length - doomed.length).toBe(MAX_RETAINED_ARTIFACTS - 1);
  });

  it('evicts the least recently used first, so the warm artifacts survive', () => {
    const entries = freshRun(6);

    // fresh-0 is newest .. fresh-5 is oldest. With `keep` holding one slot, the survivors
    // are the (MAX - 1) newest. An eviction order mutated to newest-first, or to name
    // order, deletes the artifacts most likely to be reused next (mutant G-M3).
    expect(selectArtifactsToPrune(entries, 'keep', CUTOFF)).toEqual(['fresh-3', 'fresh-4', 'fresh-5']);
  });

  it('counts the in-use artifact against the cap rather than on top of it', () => {
    const entries = [at('in-use', CUTOFF + 9_000), ...freshRun(MAX_RETAINED_ARTIFACTS - 1)];

    // in-use is retained unconditionally, so total retained is exactly the cap — an
    // off-by-one that gives in-use a free slot lets the directory grow to MAX + 1.
    const survivors = entries.length - selectArtifactsToPrune(entries, 'in-use', CUTOFF).length;
    expect(survivors).toBe(MAX_RETAINED_ARTIFACTS);
  });

  it('prunes nothing when the tree is fresh and under the cap', () => {
    // Negative control: the policy must not be a delete-everything sweep.
    const entries = freshRun(MAX_RETAINED_ARTIFACTS - 1);

    expect(selectArtifactsToPrune(entries, 'in-use', CUTOFF)).toEqual([]);
    expect(selectArtifactsToPrune([], 'in-use', CUTOFF)).toEqual([]);
  });

  it('is deterministic when a wave stamps several artifacts in the same millisecond', () => {
    const tied = ['b', 'a', 'd', 'c'].map((name) => at(name, CUTOFF + 5));

    // Equal mtimes are the common case in a wave, and an unstable comparator would make
    // the retained set differ run to run (TEST-08).
    const first = selectArtifactsToPrune(tied, 'keep', CUTOFF);
    expect(selectArtifactsToPrune([...tied].reverse(), 'keep', CUTOFF)).toEqual(first);
    // Four tied candidates, three retention slots: the name tiebreak makes `d` the loser
    // in either input order. Asserting the exact name — not just "the two runs agree" —
    // is what fails when the comparator drops its tiebreak (mutant G-M4).
    expect(first).toEqual(['d']);
  });

  it('reports each doomed directory once, so the caller cannot double-delete', () => {
    // An expired artifact is also over the cap; naive concatenation would list it twice.
    const entries = [at('stale', 0), ...freshRun(8)];

    const doomed = selectArtifactsToPrune(entries, 'keep', CUTOFF);
    expect(new Set(doomed).size).toBe(doomed.length);
    expect(doomed).toContain('stale');
  });
});

describe('retired worktree namespace collection [FEBT2-W2-U-03]', () => {
  const CUTOFF = 1_000_000;
  const namespace = (
    name: string,
    lastUsedMs: number,
    ownerRootExists: boolean | null,
    lockHeld = false,
  ): NamespaceEntry => ({ name, lastUsedMs, ownerRootExists, lockHeld });

  it('collects artifacts accumulated by every retired worktree root', () => {
    const entries = [
      namespace('active-a', CUTOFF + 10, true),
      namespace('active-b', CUTOFF + 9, true),
      ...Array.from({ length: 12 }, (_, index) =>
        namespace(`retired-${index}`, CUTOFF + index, false),
      ),
    ];

    const doomed = selectNamespacesToPrune(entries, 'active-a', CUTOFF);

    expect(doomed).toEqual(
      Array.from({ length: 12 }, (_, index) => `retired-${index}`).sort(),
    );
    expect(doomed).not.toContain('active-a');
    expect(doomed).not.toContain('active-b');
  });

  it('removes retired namespaces from the shared cache under the parent collector', () => {
    const cacheRoot = mkdtempSync(join(tmpdir(), 'acx-style-bundle-gc-test-'));
    const activeAppRoot = join(cacheRoot, 'active-worktree', 'app');
    const activeNamespace = join(cacheRoot, 'active-namespace');
    const liveForeignAppRoot = join(cacheRoot, 'live-foreign-worktree', 'app');
    const liveForeignNamespace = join(cacheRoot, 'live-foreign-namespace');
    const retiredNamespaces = ['retired-namespace-a', 'retired-namespace-b'].map((name) =>
      join(cacheRoot, name),
    );

    try {
      mkdirSync(activeAppRoot, { recursive: true });
      mkdirSync(liveForeignAppRoot, { recursive: true });
      mkdirSync(join(liveForeignNamespace, 'warm-fingerprint'), { recursive: true });
      writeFileSync(
        join(liveForeignNamespace, 'namespace-owner.json'),
        `${JSON.stringify({ appRoot: liveForeignAppRoot })}\n`,
        'utf8',
      );
      for (const [index, retiredNamespace] of retiredNamespaces.entries()) {
        mkdirSync(join(retiredNamespace, 'old-fingerprint'), { recursive: true });
        writeFileSync(
          join(retiredNamespace, 'namespace-owner.json'),
          `${JSON.stringify({ appRoot: join(cacheRoot, `removed-worktree-${index}`, 'app') })}\n`,
          'utf8',
        );
      }

      registerAndPruneNamespaces(cacheRoot, activeNamespace, activeAppRoot, CUTOFF);

      expect(existsSync(activeNamespace)).toBe(true);
      expect(existsSync(liveForeignNamespace)).toBe(true);
      expect(retiredNamespaces.map((namespaceRoot) => existsSync(namespaceRoot))).toEqual([
        false,
        false,
      ]);
      expect(existsSync(join(cacheRoot, '.gc-lock'))).toBe(false);
    } finally {
      rmSync(cacheRoot, { recursive: true, force: true });
    }
  });

  it('bounds ownerless legacy namespaces without deleting live worktrees', () => {
    const entries = [
      namespace('active', CUTOFF - 100, true),
      namespace('stale-unknown', CUTOFF - 1, null),
      namespace('fresh-unknown', CUTOFF + 1, null),
    ];

    expect(selectNamespacesToPrune(entries, 'active', CUTOFF)).toEqual([
      'stale-unknown',
    ]);
  });

  it('caps fresh ownerless namespaces and protects an in-progress retired lane', () => {
    const entries = [
      namespace('retired-but-building', CUTOFF - 10, false, true),
      ...Array.from({ length: 7 }, (_, index) =>
        namespace(`unknown-${index}`, CUTOFF + 100 - index, null),
      ),
    ];

    expect(selectNamespacesToPrune(entries, 'current', CUTOFF)).toEqual([
      'unknown-4',
      'unknown-5',
      'unknown-6',
    ]);
  });
});
