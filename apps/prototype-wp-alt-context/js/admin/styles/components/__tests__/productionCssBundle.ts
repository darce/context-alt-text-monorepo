import { execFileSync, spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import {
  existsSync,
  globSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  realpathSync,
  rmSync,
  statSync,
  utimesSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative, resolve } from 'node:path';

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

const testsRoot = __dirname;
const appRoot = resolve(testsRoot, '..', '..', '..', '..', '..');
const CACHE_ROOT = join(tmpdir(), 'acx-style-bundle');

/**
 * Give each worktree lane its own cache and eviction scope.
 *
 * The old single root made the four-entry LRU global: the fifth concurrent lane could delete a
 * sibling's artifact between that lane's test processes. Hashing the resolved application root
 * keeps the path short while ensuring every process in one lane agrees on the same namespace.
 */
export const artifactFixtureRootForAppRoot = (root: string): string => {
  const canonicalRoot = realpathSync.native(resolve(root));
  const laneKey = createHash('sha256').update(canonicalRoot).digest('hex').slice(0, 16);
  return join(CACHE_ROOT, laneKey);
};

const FIXTURE_ROOT = artifactFixtureRootForAppRoot(appRoot);
const LOCK_DIR = join(FIXTURE_ROOT, '.lock');
const STAMP_FILE = 'build-stamp.json';
const NAMESPACE_OWNER_FILE = 'namespace-owner.json';

/** A dead owner's lock lease may be reclaimed after this interval. */
const STALE_LOCK_MS = 5 * 60_000;
/** Give up rather than hang the suite if the lock never frees. */
const LOCK_TIMEOUT_MS = 6 * 60_000;
const LOCK_POLL_MS = 100;
/** Keep the lease fresh while the synchronous Vite child occupies the main thread. */
const LOCK_HEARTBEAT_MS = 1_000;
/** A build cannot outlive the lease that fences it from a successor. */
const BUILD_TIMEOUT_MS = STALE_LOCK_MS - 30_000;
export const LOCK_OWNER_FILE = 'owner.json';
/** Artifact directories untouched for longer than this are pruned. */
const ARTIFACT_TTL_MS = 24 * 60 * 60_000;
/** Stop retrying when build inputs are being rewritten continuously. */
export const MAX_FINGERPRINT_STABILITY_ATTEMPTS = 3;
/** Bound legacy namespaces created before owner metadata was introduced. */
const MAX_RETAINED_UNKNOWN_NAMESPACES = 4;
/**
 * Hard cap on retained artifact directories, TTL notwithstanding (FEBT2-W2-U-03).
 *
 * A TTL alone bounds *age*, not *rate*. During a parallel-lane wave every edit in a lane can mint
 * a new fingerprint and full build artifact, so directories accrue faster than a 24h cutoff
 * collects them — an unbounded cache is a leak (RES-08), and this one filled the host volume
 * twice. The cap now applies inside the worktree-specific root above: four artifacts per active
 * lane, never four artifacts shared by all lanes. The current fingerprint remains protected
 * unconditionally by `keepDirName`.
 */
export const MAX_RETAINED_ARTIFACTS = 4;

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
export interface BuildInputState {
  readonly fingerprint: string;
  /** Metadata generation used to detect content ABA while a build is running. */
  readonly generation: string;
}

export const computeBuildInputState = (): BuildInputState => {
  const files = fingerprintedBuildInputs();

  const contentDigest = createHash('sha256');
  const generationDigest = createHash('sha256');
  let maxMtimeNs = 0n;
  for (const file of files) {
    const path = join(appRoot, file);
    const before = statSync(path, { bigint: true });
    const contents = readFileSync(path);
    const after = statSync(path, { bigint: true });
    maxMtimeNs = before.mtimeNs > maxMtimeNs ? before.mtimeNs : maxMtimeNs;
    maxMtimeNs = after.mtimeNs > maxMtimeNs ? after.mtimeNs : maxMtimeNs;

    contentDigest.update(file);
    contentDigest.update('\0');
    contentDigest.update(
      createHash('sha256')
        .update(contents)
        .digest(),
    );
    contentDigest.update('\n');

    generationDigest.update(file);
    generationDigest.update('\0');
    for (const stat of [before, after]) {
      generationDigest.update(`${stat.dev}:${stat.ino}:${stat.size}:${stat.mtimeNs}:${stat.ctimeNs}\n`);
    }
  }
  return {
    fingerprint: contentDigest.digest('hex').slice(0, 32),
    generation: `${maxMtimeNs}:${generationDigest.digest('hex').slice(0, 32)}`,
  };
};

export const computeBuildInputFingerprint = (): string => computeBuildInputState().fingerprint;

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

export interface DirectoryLockOwnership {
  readonly pid: number;
  readonly nonce: string;
}

interface DirectoryLockTiming {
  readonly staleLockMs?: number;
  readonly timeoutMs?: number;
  readonly pollMs?: number;
}

const ownerPathForLock = (lockDir: string): string => join(lockDir, LOCK_OWNER_FILE);

const sameOwnership = (left: DirectoryLockOwnership, right: DirectoryLockOwnership): boolean =>
  left.pid === right.pid && left.nonce === right.nonce;

const sameOptionalOwnership = (
  left: DirectoryLockOwnership | null,
  right: DirectoryLockOwnership | null,
): boolean => {
  if (left === null || right === null) {
    return left === right;
  }
  return sameOwnership(left, right);
};

const readLockOwnership = (lockDir: string): DirectoryLockOwnership | null => {
  try {
    const parsed: unknown = JSON.parse(readFileSync(ownerPathForLock(lockDir), 'utf8'));
    if (typeof parsed !== 'object' || parsed === null || !('pid' in parsed) || !('nonce' in parsed)) {
      return null;
    }
    const { pid, nonce } = parsed;
    return typeof pid === 'number' && Number.isSafeInteger(pid) && pid > 0 && typeof nonce === 'string'
      ? { pid, nonce }
      : null;
  } catch {
    return null;
  }
};

const processIsAlive = (pid: number): boolean => {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== 'ESRCH';
  }
};

export const tryAcquireDirectoryLock = (
  lockDir: string,
  timing: DirectoryLockTiming = {},
): DirectoryLockOwnership | null => {
  mkdirSync(dirname(lockDir), { recursive: true });
  const ownership = { pid: process.pid, nonce: randomUUID() };
  try {
    mkdirSync(lockDir);
    try {
      writeFileSync(ownerPathForLock(lockDir), `${JSON.stringify(ownership)}\n`, {
        encoding: 'utf8',
        flag: 'wx',
      });
      return ownership;
    } catch (error) {
      rmSync(lockDir, { recursive: true, force: true });
      throw error;
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'EEXIST') {
      throw error;
    }
    const incumbent = readLockOwnership(lockDir);
    let leaseAgeMs: number;
    try {
      const leasePath = incumbent === null ? lockDir : ownerPathForLock(lockDir);
      leaseAgeMs = Date.now() - statSync(leasePath).mtimeMs;
    } catch {
      // The holder released between mkdir and inspection; let the caller retry.
      return null;
    }
    const staleLockMs = timing.staleLockMs ?? STALE_LOCK_MS;
    if (leaseAgeMs > staleLockMs && (incumbent === null || !processIsAlive(incumbent.pid))) {
      // Serialize stale recovery inside the incumbent directory. Without this claim, two
      // reapers can both inspect owner A, then the slower one can delete newly-created owner B
      // after the faster one removes A (the classic ABA unlink race).
      const recoveryClaim = join(lockDir, '.reaping');
      try {
        mkdirSync(recoveryClaim);
      } catch (claimError) {
        if ((claimError as NodeJS.ErrnoException).code !== 'EEXIST') {
          throw claimError;
        }
        return null;
      }

      const confirmedIncumbent = readLockOwnership(lockDir);
      let confirmedLeaseAgeMs = leaseAgeMs;
      try {
        if (confirmedIncumbent !== null) {
          confirmedLeaseAgeMs = Date.now() - statSync(ownerPathForLock(lockDir)).mtimeMs;
        }
      } catch {
        rmSync(recoveryClaim, { recursive: true, force: true });
        return null;
      }
      if (
        sameOptionalOwnership(confirmedIncumbent, incumbent) &&
        confirmedLeaseAgeMs > staleLockMs &&
        (confirmedIncumbent === null || !processIsAlive(confirmedIncumbent.pid))
      ) {
        rmSync(lockDir, { recursive: true, force: true });
      } else {
        rmSync(recoveryClaim, { recursive: true, force: true });
      }
    }
    return null;
  }
};

export const acquireDirectoryLock = (
  lockDir: string,
  timing: DirectoryLockTiming = {},
): DirectoryLockOwnership => {
  const timeoutMs = timing.timeoutMs ?? LOCK_TIMEOUT_MS;
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const ownership = tryAcquireDirectoryLock(lockDir, timing);
    if (ownership !== null) {
      return ownership;
    }
    if (Date.now() > deadline) {
      throw new Error(
        `Timed out after ${timeoutMs}ms waiting for the production-CSS lock at ${lockDir}. ` +
          'Remove it if no build is running.',
      );
    }
    sleepSync(timing.pollMs ?? LOCK_POLL_MS);
  }
};

export const releaseDirectoryLock = (
  lockDir: string,
  ownership: DirectoryLockOwnership,
): boolean => {
  const incumbent = readLockOwnership(lockDir);
  if (incumbent === null || !sameOwnership(incumbent, ownership)) {
    return false;
  }
  rmSync(lockDir, { recursive: true, force: true });
  return true;
};

const runWithLockHeartbeat = <T>(
  lockDir: string,
  ownership: DirectoryLockOwnership,
  operation: () => T,
): T => {
  const heartbeatSource = String.raw`
const fs = require('node:fs');
const path = require('node:path');
const [lockDir, expectedToken, intervalText] = process.argv.slice(1);
const expectedOwner = JSON.parse(expectedToken);
const ownerPath = path.join(lockDir, ${JSON.stringify(LOCK_OWNER_FILE)});
const beat = () => {
  try {
    process.kill(expectedOwner.pid, 0);
    if (fs.readFileSync(ownerPath, 'utf8').trim() !== expectedToken) process.exit(0);
    const now = new Date();
    fs.utimesSync(ownerPath, now, now);
    fs.utimesSync(lockDir, now, now);
  } catch { process.exit(0); }
};
beat();
setInterval(beat, Number(intervalText)).unref();
setInterval(() => {}, 0x7fffffff);
`;
  const token = JSON.stringify(ownership);
  const heartbeat = spawn(
    process.execPath,
    ['-e', heartbeatSource, lockDir, token, String(LOCK_HEARTBEAT_MS)],
    { stdio: 'ignore' },
  );
  try {
    return operation();
  } finally {
    heartbeat.kill();
  }
};

/** An artifact directory and the time its stamp was last touched. */
export interface ArtifactEntry {
  readonly name: string;
  /** Stamp mtime; `0` for a directory with no stamp (a crashed or half-written build). */
  readonly lastUsedMs: number;
}

/** A worktree cache namespace as observed by the parent-level collector. */
export interface NamespaceEntry {
  readonly name: string;
  readonly lastUsedMs: number;
  /** `null` means an owner marker from an older fixture version is absent or unreadable. */
  readonly ownerRootExists: boolean | null;
  /** A build process currently owns this namespace's lane-local lock. */
  readonly lockHeld: boolean;
}

/**
 * Select retired or ownerless namespace directories for parent-level collection.
 *
 * A namespace whose recorded application root still exists belongs to a live worktree and is
 * never selected, even when old. A recorded owner that no longer exists is safe to collect in
 * full: no future process in that retired lane can revisit its lane-local artifact pruner.
 * Ownerless legacy namespaces fall back to the same TTL plus count bound as the old cache.
 */
export const selectNamespacesToPrune = (
  entries: readonly NamespaceEntry[],
  keepNamespace: string,
  cutoffMs: number,
  maxRetainedUnknown: number = MAX_RETAINED_UNKNOWN_NAMESPACES,
): string[] => {
  const candidates = entries.filter(
    (entry) =>
      entry.name !== keepNamespace && entry.name !== '.gc-lock' && !entry.lockHeld,
  );
  const retired = candidates.filter((entry) => entry.ownerRootExists === false);
  const unknown = candidates.filter((entry) => entry.ownerRootExists === null);
  const expiredUnknown = unknown.filter((entry) => entry.lastUsedMs < cutoffMs);
  const retainableUnknown = unknown
    .filter((entry) => entry.lastUsedMs >= cutoffMs)
    .sort((a, b) => b.lastUsedMs - a.lastUsedMs || a.name.localeCompare(b.name));
  const overflowUnknown = retainableUnknown.slice(Math.max(maxRetainedUnknown, 0));

  return [
    ...new Set(
      [...retired, ...expiredUnknown, ...overflowUnknown].map((entry) => entry.name),
    ),
  ].sort();
};

const readNamespaceOwner = (namespaceRoot: string): string | null => {
  try {
    const parsed: unknown = JSON.parse(
      readFileSync(join(namespaceRoot, NAMESPACE_OWNER_FILE), 'utf8'),
    );
    if (typeof parsed !== 'object' || parsed === null || !('appRoot' in parsed)) {
      return null;
    }
    const { appRoot: recordedRoot } = parsed;
    return typeof recordedRoot === 'string' ? recordedRoot : null;
  } catch {
    return null;
  }
};

const namespaceLastUsedMs = (namespaceRoot: string): number => {
  let latest = statSync(namespaceRoot).mtimeMs;
  for (const child of readdirSync(namespaceRoot, { withFileTypes: true })) {
    const activityPath = child.isDirectory()
      ? join(namespaceRoot, child.name, STAMP_FILE)
      : join(namespaceRoot, child.name);
    if (existsSync(activityPath)) {
      latest = Math.max(latest, statSync(activityPath).mtimeMs);
    }
  }
  return latest;
};

const readNamespaceEntries = (cacheRoot: string): NamespaceEntry[] =>
  readdirSync(cacheRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name !== '.gc-lock')
    .map((entry) => {
      const namespaceRoot = join(cacheRoot, entry.name);
      const ownerRoot = readNamespaceOwner(namespaceRoot);
      return {
        name: entry.name,
        lastUsedMs: namespaceLastUsedMs(namespaceRoot),
        ownerRootExists: ownerRoot === null ? null : existsSync(ownerRoot),
        lockHeld: existsSync(join(namespaceRoot, '.lock')),
      };
    });

/**
 * Register this lane and collect namespaces left behind by removed worktrees.
 *
 * This parent operation has its own shared lock: lane-local build locks cannot coordinate two
 * different namespace directories. Live owners are excluded from deletion, so sibling lanes can
 * still build concurrently after this short metadata/GC phase.
 */
export const registerAndPruneNamespaces = (
  cacheRoot: string,
  fixtureRoot: string,
  ownerAppRoot: string,
  nowMs: number = Date.now(),
  buildLockDir?: string,
): DirectoryLockOwnership | null => {
  const gcLockDir = join(cacheRoot, '.gc-lock');
  const buildDeadline = Date.now() + LOCK_TIMEOUT_MS;
  const relativeFixtureRoot = relative(cacheRoot, fixtureRoot);
  if (
    relativeFixtureRoot === '' ||
    relativeFixtureRoot.startsWith('..') ||
    relativeFixtureRoot.includes('/') ||
    relativeFixtureRoot.includes('\\')
  ) {
    throw new Error(`Fixture namespace ${fixtureRoot} must be a direct child of ${cacheRoot}.`);
  }

  for (;;) {
    let buildOwnership: DirectoryLockOwnership | null = null;
    const gcOwnership = acquireDirectoryLock(gcLockDir);
    try {
      mkdirSync(fixtureRoot, { recursive: true });
      writeFileSync(
        join(fixtureRoot, NAMESPACE_OWNER_FILE),
        `${JSON.stringify({ appRoot: ownerAppRoot }, null, 2)}\n`,
        'utf8',
      );
      const doomed = selectNamespacesToPrune(
        readNamespaceEntries(cacheRoot),
        relativeFixtureRoot,
        nowMs - ARTIFACT_TTL_MS,
      );
      for (const name of doomed) {
        rmSync(join(cacheRoot, name), { recursive: true, force: true });
      }
      // Build/read ownership is acquired before the shared GC lock is released. A collector can
      // therefore never observe a live namespace in the gap between registration and lane locking.
      if (buildLockDir !== undefined) {
        buildOwnership = tryAcquireDirectoryLock(buildLockDir);
      }
    } finally {
      releaseDirectoryLock(gcLockDir, gcOwnership);
    }
    if (buildLockDir === undefined || buildOwnership !== null) {
      return buildOwnership;
    }
    // Never wait for a lane-local build while holding the cache-parent GC lock: a second process
    // in one lane must not stall unrelated lanes from registering or collecting their namespaces.
    if (Date.now() > buildDeadline) {
      throw new Error(
        `Timed out after ${LOCK_TIMEOUT_MS}ms waiting for the production-CSS lock at ${buildLockDir}. ` +
          'Remove it if no build is running.',
      );
    }
    sleepSync(LOCK_POLL_MS);
  }
};

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

export interface FingerprintStableArtifactOperations<T> {
  readonly artifactDirForFingerprint: (fingerprint: string) => string;
  readonly prepareArtifact: (fingerprint: string) => void;
  readonly readStampedFingerprint: (outDir: string) => string | null;
  readonly touchArtifact: (outDir: string) => void;
  readonly discardArtifact: (outDir: string) => void;
  readonly buildArtifact: (outDir: string) => void;
  readonly stampArtifact: (outDir: string, fingerprint: string) => void;
  readonly readArtifact: (outDir: string, fingerprint: string) => T;
}

/**
 * Resolve an artifact while its caller holds the build lock.
 *
 * The fingerprint supplied by the caller was observed before lock acquisition. Rechecking it here
 * closes both long race windows: waiting for another process and running Vite. The final check also
 * prevents a source change during artifact reads from entering the in-process cache.
 */
export const loadFingerprintStableArtifact = <T>(
  initialState: BuildInputState,
  computeState: () => BuildInputState,
  operations: FingerprintStableArtifactOperations<T>,
  maxAttempts: number = MAX_FINGERPRINT_STABILITY_ATTEMPTS,
): T => {
  let state = initialState;
  const stateAfterLock = computeState();
  if (stateAfterLock.fingerprint !== state.fingerprint) {
    operations.discardArtifact(operations.artifactDirForFingerprint(state.fingerprint));
  }
  state = stateAfterLock;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const { fingerprint } = state;
    const outDir = operations.artifactDirForFingerprint(fingerprint);
    operations.prepareArtifact(fingerprint);

    if (operations.readStampedFingerprint(outDir) === fingerprint) {
      operations.touchArtifact(outDir);
    } else {
      operations.discardArtifact(outDir);
      operations.buildArtifact(outDir);

      const stateAfterBuild = computeState();
      if (
        stateAfterBuild.fingerprint !== state.fingerprint ||
        stateAfterBuild.generation !== state.generation
      ) {
        operations.discardArtifact(outDir);
        state = stateAfterBuild;
        continue;
      }
      operations.stampArtifact(outDir, fingerprint);
    }

    const artifact = operations.readArtifact(outDir, fingerprint);
    const stateBeforeReturn = computeState();
    if (stateBeforeReturn.fingerprint === fingerprint) {
      return artifact;
    }

    operations.discardArtifact(outDir);
    state = stateBeforeReturn;
  }

  throw new Error(
    `Production CSS build inputs changed during ${maxAttempts} consecutive attempts; ` +
      'refusing to cache an artifact whose fingerprint does not match its contents.',
  );
};

/**
 * Build the production admin bundle at most once per fingerprint across all processes, then return
 * its CSS as an immutable snapshot. Throws — rather than returning an empty bundle — when the build
 * emits no CSS, so a broken build fails as a build problem instead of masquerading as a source
 * regression or passing on someone else's leftover artifact.
 */
export const loadProductionCssBundle = (): ProductionCssBundle => {
  if (cachedBundle !== null) {
    if (computeBuildInputState().fingerprint === cachedBundle.fingerprint) {
      return cachedBundle;
    }
    cachedBundle = null;
  }

  const stateBeforeLock = computeBuildInputState();

  const lockOwnership = registerAndPruneNamespaces(
    CACHE_ROOT,
    FIXTURE_ROOT,
    appRoot,
    Date.now(),
    LOCK_DIR,
  );
  if (lockOwnership === null) {
    throw new Error(`Failed to acquire the production-CSS lock at ${LOCK_DIR}.`);
  }
  try {
    cachedBundle = loadFingerprintStableArtifact(
      stateBeforeLock,
      computeBuildInputState,
      {
        artifactDirForFingerprint: (fingerprint) => join(FIXTURE_ROOT, fingerprint),
        prepareArtifact: (fingerprint) => {
          // Before the build, not after: pruning afterwards means the disk must hold the old
          // artifacts *and* the new one simultaneously, which is exactly the moment the volume
          // fills. `fingerprint` protects the artifact we are about to reuse.
          pruneStaleArtifacts(fingerprint);
        },
        readStampedFingerprint: (outDir) => readStampedFingerprint(join(outDir, STAMP_FILE)),
        touchArtifact: (outDir) => {
          const now = new Date();
          utimesSync(join(outDir, STAMP_FILE), now, now);
        },
        discardArtifact: (outDir) => rmSync(outDir, { recursive: true, force: true }),
        buildArtifact: (outDir) => {
          runWithLockHeartbeat(LOCK_DIR, lockOwnership, () => {
            execFileSync('npm', ['run', 'build', '--', '--outDir', outDir, '--emptyOutDir'], {
              cwd: appRoot,
              stdio: 'pipe',
              timeout: BUILD_TIMEOUT_MS,
            });
          });
        },
        stampArtifact: (outDir, fingerprint) => {
          writeFileSync(join(outDir, STAMP_FILE), `${JSON.stringify({ fingerprint }, null, 2)}\n`, 'utf8');
        },
        readArtifact: (outDir, fingerprint) => {
          const cssFilePaths = globSync(join(outDir, 'assets/*.css')).sort();
          if (cssFilePaths.length === 0) {
            throw new Error(
              `The production build emitted no CSS into ${outDir}. This is a build failure, not a stylesheet regression.`,
            );
          }
          const css = cssFilePaths.map((filePath) => readFileSync(filePath, 'utf8')).join('\n');
          return Object.freeze({
            css,
            cssFilePaths: Object.freeze([...cssFilePaths]),
            fingerprint,
            outDir,
          });
        },
      },
    );
    return cachedBundle;
  } finally {
    releaseDirectoryLock(LOCK_DIR, lockOwnership);
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
