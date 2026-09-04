import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  existsSync,
  globSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  utimesSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative, resolve } from 'node:path';

/**
 * Why this exists (FEBT1-LH-01 / FEBT1-GATE-04):
 *
 * The style-bundle suites used to each spawn `vite build` into `public/assets/dist`, which is
 * configured `emptyOutDir: true`. Any concurrent build — the sibling suite, another worktree lane,
 * a parallel CI job — could empty that directory between a suite's `globSync` and its
 * `readFileSync`. That is a check-then-act race on shared mutable state, not flaky infrastructure
 * (CON-17), and its failures are unreproducible on demand.
 *
 * Structural argument for correctness under every interleaving (CON-22):
 *   1. The artifact directory is content-addressed by a fingerprint of the build inputs, and is
 *      never `public/assets/dist`. No non-fixture build can write to or empty it.
 *   2. A process only targets a directory whose name equals its own input fingerprint. Such a
 *      process finds a matching stamp and reuses the artifact — it never re-empties it. So an
 *      already-stamped artifact directory is immutable (FLOW-01: immutable inputs, versioned
 *      outputs, atomic cutover via the stamp).
 *   3. Build, prune and read all run inside a single global cross-process lock, so the only
 *      window in which a directory is not yet stamped is not observable by any reader. One lock
 *      means no acquisition order and no circular wait (CON-13/CON-21).
 *   4. The returned bundle is a frozen snapshot of already-read strings, so no test body can
 *      mutate a shared fixture (TEST-07).
 */

const FIXTURE_ROOT = join(tmpdir(), 'acx-style-bundle');
const LOCK_DIR = join(FIXTURE_ROOT, '.lock');
const STAMP_FILE = 'build-stamp.json';

/** A lock held longer than this is assumed to belong to a crashed process. */
const STALE_LOCK_MS = 5 * 60_000;
/** Give up rather than hang the suite if the lock never frees. */
const LOCK_TIMEOUT_MS = 6 * 60_000;
const LOCK_POLL_MS = 100;
/** Artifact directories untouched for longer than this are pruned. */
const ARTIFACT_TTL_MS = 24 * 60 * 60_000;
/**
 * Hard cap on retained artifact directories, TTL notwithstanding (FEBT2-W2-U-03).
 *
 * A TTL alone bounds *age*, not *rate*. During a parallel-lane wave every edit in every
 * lane mints a new fingerprint and a full build artifact, so directories accrue far faster
 * than a 24h cutoff collects them — an unbounded cache is a leak (RES-08), and this one
 * filled the host volume twice. The cap makes retention proportional to concurrent lanes
 * rather than to edit rate. Small on purpose: the only artifact whose reuse matters is the
 * current fingerprint's, which `keepDirName` protects unconditionally.
 */
export const MAX_RETAINED_ARTIFACTS = 4;

const testsRoot = __dirname;
const appRoot = resolve(testsRoot, '..', '..', '..', '..', '..');

/**
 * Files whose contents can change the production bundle. Test sources are excluded: vitest never
 * feeds them to rollup, so including them would force a rebuild every time a suite is edited.
 */
const BUILD_INPUT_GLOBS = [
  'js/**/*.ts',
  'js/**/*.tsx',
  'js/**/*.scss',
  'js/**/*.css',
  'js/**/*.json',
  'vite.config.ts',
  'tsconfig.json',
  'tsconfig.type-check.json',
  'package.json',
  'package-lock.json',
] as const;

const isBuildInput = (relativePath: string): boolean => {
  if (relativePath.includes('__tests__')) {
    return false;
  }
  return !/\.(test|spec)\.[cm]?tsx?$/.test(relativePath);
};

export interface ProductionCssBundle {
  /** Every emitted CSS file, concatenated. */
  readonly css: string;
  /** Absolute paths of the CSS files the bundle was read from. */
  readonly cssFilePaths: readonly string[];
  /** Fingerprint of the build inputs the artifact was produced from. */
  readonly fingerprint: string;
  /** Content-addressed directory the artifact was read from. */
  readonly outDir: string;
}

/**
 * Hash of every file that can influence the production bundle. Equality with a built artifact's
 * stamp proves the artifact came from the tree under test — a strictly stronger guarantee than the
 * mtime-recency check it replaces, which only proved *some* build had run recently.
 */
export const computeBuildInputFingerprint = (): string => {
  const files = fingerprintedBuildInputs();

  const digest = createHash('sha256');
  for (const file of files) {
    digest.update(file);
    digest.update('\0');
    digest.update(
      createHash('sha256')
        .update(readFileSync(join(appRoot, file)))
        .digest(),
    );
    digest.update('\n');
  }
  return digest.digest('hex').slice(0, 32);
};

const toPosix = (entry: string): string => entry.split('\\').join('/');

/** Repository-relative paths, POSIX-separated, that BUILD_INPUT_GLOBS actually hashes. */
export const fingerprintedBuildInputs = (): string[] =>
  BUILD_INPUT_GLOBS.flatMap((pattern) => globSync(pattern, { cwd: appRoot }))
    .map(toPosix)
    .filter(isBuildInput)
    .sort();

/**
 * Every non-test file under `js/`, regardless of extension — the set rollup is allowed
 * to consume. Deliberately NOT filtered by BUILD_INPUT_GLOBS: this is the independent
 * side of the comparison below.
 */
export const buildInputCandidates = (): string[] =>
  globSync('js/**/*', { cwd: appRoot })
    .map(toPosix)
    .filter((entry) => statSync(join(appRoot, entry)).isFile())
    .filter(isBuildInput)
    .sort();

/** Pure seam so a test can prove the detector detects (TEST-15) without planting a file. */
export const selectUnfingerprinted = (candidates: readonly string[], fingerprinted: Iterable<string>): string[] => {
  const covered = new Set(fingerprinted);
  return candidates.filter((entry) => !covered.has(entry)).sort();
};

/**
 * Build inputs the fingerprint would not see (FEBT2-LG-NEW-02).
 *
 * BUILD_INPUT_GLOBS enumerates extensions. A lane that adds a new build-input file type
 * under `js/` — an `.svg` imported by rollup, an `.mjs`, a `.woff2` — and forgets to
 * extend the globs does not get an error: the fingerprint simply stops changing, the
 * cached artifact is reused, and the style suites assert against yesterday's bundle
 * while reporting green. Silent staleness, not a failure (RLSE-05). Non-empty here
 * means the omission is now loud.
 */
export const uncoveredBuildInputs = (): string[] =>
  selectUnfingerprinted(buildInputCandidates(), fingerprintedBuildInputs());

/**
 * Sources rollup itself recorded as build inputs, read from the build's own manifest
 * rather than guessed from the entry list. Throws on a missing manifest: an absent one
 * would otherwise yield an empty source list, which every coverage check trivially passes.
 */
export const manifestBuildSources = (bundle: ProductionCssBundle): string[] => {
  const manifestPath = join(bundle.outDir, '.vite', 'manifest.json');
  if (!existsSync(manifestPath)) {
    throw new Error(
      `No rollup manifest at ${manifestPath}. vite.config.ts sets build.manifest; a missing ` +
        'manifest means the artifact was not produced by the configured build.',
    );
  }
  const parsed: unknown = JSON.parse(readFileSync(manifestPath, 'utf8'));
  if (typeof parsed !== 'object' || parsed === null) {
    throw new Error(`Rollup manifest at ${manifestPath} is not an object.`);
  }
  const sources = Object.values(parsed as Record<string, unknown>)
    .map((chunk) => (typeof chunk === 'object' && chunk !== null && 'src' in chunk ? chunk.src : undefined))
    .filter((src): src is string => typeof src === 'string')
    .map(toPosix);

  return sources.sort();
};

/**
 * Manifest-recorded sources the fingerprint does not hash. Split from
 * `manifestBuildSources` so a test can assert the source list is non-empty: a comparison
 * against an accidentally-empty list reports "all covered" and certifies nothing (TEST-15).
 */
export const unfingerprintedManifestSources = (bundle: ProductionCssBundle): string[] =>
  selectUnfingerprinted(manifestBuildSources(bundle), fingerprintedBuildInputs());

const sleepSync = (milliseconds: number): void => {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, milliseconds);
};

const acquireGlobalLock = (): void => {
  const deadline = Date.now() + LOCK_TIMEOUT_MS;
  mkdirSync(FIXTURE_ROOT, { recursive: true });

  for (;;) {
    try {
      mkdirSync(LOCK_DIR);
      return;
    } catch {
      let heldForMs = 0;
      try {
        heldForMs = Date.now() - statSync(LOCK_DIR).mtimeMs;
      } catch {
        // The holder released between mkdir and stat; retry immediately.
        continue;
      }
      if (heldForMs > STALE_LOCK_MS) {
        rmSync(LOCK_DIR, { recursive: true, force: true });
        continue;
      }
      if (Date.now() > deadline) {
        throw new Error(
          `Timed out after ${LOCK_TIMEOUT_MS}ms waiting for the production-CSS build lock at ${LOCK_DIR}. ` +
            'Remove it if no build is running.',
        );
      }
      sleepSync(LOCK_POLL_MS);
    }
  }
};

const releaseGlobalLock = (): void => {
  rmSync(LOCK_DIR, { recursive: true, force: true });
};

/** An artifact directory and the time its stamp was last touched. */
export interface ArtifactEntry {
  readonly name: string;
  /** Stamp mtime; `0` for a directory with no stamp (a crashed or half-written build). */
  readonly lastUsedMs: number;
}

/**
 * Which artifact directories to delete. Pure so the retention policy can be tested without
 * a filesystem or a clock — `Date.now()` in the decision would make every assertion about
 * "older than the TTL" depend on wall time (TEST-08).
 *
 * Two independent bounds, both required: the TTL evicts *stale* artifacts, the cap evicts
 * *excess* ones. Neither subsumes the other — a wave can mint 50 artifacts in an hour, all
 * inside the TTL; a quiet week leaves 2 artifacts, both past it.
 */
export const selectArtifactsToPrune = (
  entries: readonly ArtifactEntry[],
  keepDirName: string,
  cutoffMs: number,
  maxRetained: number = MAX_RETAINED_ARTIFACTS,
): string[] => {
  const candidates = entries.filter((entry) => entry.name !== keepDirName && entry.name !== '.lock');
  const expired = candidates.filter((entry) => entry.lastUsedMs < cutoffMs);
  // Most-recently-used first; name breaks ties so the selection is deterministic under equal
  // mtimes, which a same-second wave produces routinely (TEST-08).
  const retainable = candidates
    .filter((entry) => entry.lastUsedMs >= cutoffMs)
    .sort((a, b) => b.lastUsedMs - a.lastUsedMs || a.name.localeCompare(b.name));
  // `keepDirName` is retained unconditionally above, so it consumes one of the slots.
  const overflow = retainable.slice(Math.max(maxRetained - 1, 0));

  return [...expired, ...overflow].map((entry) => entry.name).sort();
};

/** Artifact directories currently on disk, with the stamp mtime the policy reads. */
const readArtifactEntries = (): ArtifactEntry[] => {
  if (!existsSync(FIXTURE_ROOT)) {
    return [];
  }
  return readdirSync(FIXTURE_ROOT, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => {
      const stampPath = join(FIXTURE_ROOT, entry.name, STAMP_FILE);
      return {
        name: entry.name,
        lastUsedMs: existsSync(stampPath) ? statSync(stampPath).mtimeMs : 0,
      };
    });
};

/** Bounded tmpdir growth. Runs under the global lock, so it cannot race a reader. */
const pruneStaleArtifacts = (keepDirName: string): void => {
  const doomed = selectArtifactsToPrune(readArtifactEntries(), keepDirName, Date.now() - ARTIFACT_TTL_MS);
  for (const name of doomed) {
    rmSync(join(FIXTURE_ROOT, name), { recursive: true, force: true });
  }
};

const readStampedFingerprint = (stampPath: string): string | null => {
  if (!existsSync(stampPath)) {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(stampPath, 'utf8'));
  } catch {
    return null;
  }
  if (typeof parsed !== 'object' || parsed === null || !('fingerprint' in parsed)) {
    return null;
  }
  const { fingerprint } = parsed;
  return typeof fingerprint === 'string' ? fingerprint : null;
};

let cachedBundle: ProductionCssBundle | null = null;

/**
 * Build the production admin bundle at most once per fingerprint across all processes, then return
 * its CSS as an immutable snapshot. Throws — rather than returning an empty bundle — when the build
 * emits no CSS, so a broken build fails as a build problem instead of masquerading as a source
 * regression or passing on someone else's leftover artifact.
 */
export const loadProductionCssBundle = (): ProductionCssBundle => {
  if (cachedBundle !== null) {
    return cachedBundle;
  }

  const fingerprint = computeBuildInputFingerprint();
  const outDir = join(FIXTURE_ROOT, fingerprint);
  const stampPath = join(outDir, STAMP_FILE);

  acquireGlobalLock();
  try {
    // Before the build, not after: pruning afterwards means the disk must hold the old
    // artifacts *and* the new one simultaneously, which is exactly the moment the volume
    // fills. `keepDirName` protects the artifact we are about to reuse.
    pruneStaleArtifacts(fingerprint);

    if (readStampedFingerprint(stampPath) === fingerprint) {
      // Mark the artifact as in use so the pruner keeps it.
      const now = new Date();
      utimesSync(stampPath, now, now);
    } else {
      rmSync(outDir, { recursive: true, force: true });
      execFileSync('npm', ['run', 'build', '--', '--outDir', outDir, '--emptyOutDir'], {
        cwd: appRoot,
        stdio: 'pipe',
      });
      writeFileSync(stampPath, `${JSON.stringify({ fingerprint }, null, 2)}\n`, 'utf8');
    }

    const cssFilePaths = globSync(join(outDir, 'assets/*.css')).sort();
    if (cssFilePaths.length === 0) {
      throw new Error(
        `The production build emitted no CSS into ${outDir}. This is a build failure, not a stylesheet regression.`,
      );
    }
    const css = cssFilePaths.map((filePath) => readFileSync(filePath, 'utf8')).join('\n');

    cachedBundle = Object.freeze({
      css,
      cssFilePaths: Object.freeze([...cssFilePaths]),
      fingerprint,
      outDir,
    });
    return cachedBundle;
  } finally {
    releaseGlobalLock();
  }
};

/**
 * Read back the fingerprint an artifact directory was stamped with. A stamp is only written after
 * a successful build, so `stamp === bundle.fingerprint` proves the CSS under assertion was emitted
 * by a build of a tree hashing to that fingerprint — not by a leftover or half-written artifact.
 * Safe to call at any time: a stamped artifact directory is immutable.
 */
export const readArtifactStamp = (bundle: ProductionCssBundle): string | null => {
  return readStampedFingerprint(join(bundle.outDir, STAMP_FILE));
};

/** Exposed so a test can assert the fixture never reads from the shared, emptyable build output. */
export const SHARED_BUILD_OUT_DIR = join(appRoot, 'public/assets/dist');

export const isInsideFixtureRoot = (path: string): boolean => {
  const rel = relative(FIXTURE_ROOT, path);
  return rel !== '' && !rel.startsWith('..');
};
