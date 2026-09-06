import { execFileSync, spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import {
  closeSync,
  existsSync,
  fsyncSync,
  ftruncateSync,
  globSync,
  mkdtempSync,
  mkdirSync,
  openSync,
  readFileSync,
  readdirSync,
  readlinkSync,
  realpathSync,
  renameSync,
  rmSync,
  statSync,
  symlinkSync,
  utimesSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative, resolve } from 'node:path';
import { Worker } from 'node:worker_threads';

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
 *
 * RES-13-TEARDOWN: an uncertain teardown persists `teardown_uncertain` in owner.json.
 * A pre-created .build-in-progress guard also fences an ordinary lease if all later writes fail.
 * Without persisted group metadata this guard requires the operator override below.
 * Owner death or a missing/reused group leader does not clear this fence: recovery must observe
 * ESRCH for the entire PGID. Permission/probe failures retain it. Operator override: stop all
 * fixture users, inspect the recorded PGID/startToken and terminate any surviving build members,
 * then explicitly remove that namespace's .lock directory. Never remove it based on owner age.
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
const BUILD_TERMINATION_GRACE_MS = 5_000;
/**
 * A single identity/liveness probe may outlive the wait phase by this bounded amount. The
 * extension is explicit and finite: a slow `ps` cannot consume the caller's whole wait budget,
 * while repeated probes cannot silently turn a short phase into an unbounded wait.
 */
const PROCESS_PROBE_BUDGET_MS = 250;
const PROCESS_PROBE_EXTENSION_MS = PROCESS_PROBE_BUDGET_MS * 2;
export const LOCK_OWNER_FILE = 'owner.json';
const BUILD_GUARD_FILE = '.build-in-progress';
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
  /** Metadata read under the build lock, before another builder can evict the artifact. */
  readonly artifactStamp: string | null;
  readonly manifestSources: readonly string[];
  readonly manifestEntryPoints: readonly string[];
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

export const computeBuildInputState = (root: string = appRoot): BuildInputState => {
  const files = fingerprintedBuildInputs(root);

  const contentDigest = createHash('sha256');
  const generationDigest = createHash('sha256');
  let maxMtimeNs = 0n;
  for (const file of files) {
    const path = join(root, file);
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
export const fingerprintedBuildInputs = (root: string = appRoot): string[] =>
  BUILD_INPUT_GLOBS.flatMap((pattern) => globSync(pattern, { cwd: root }))
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
export const manifestBuildSources = (bundle: ProductionCssBundle): string[] => [...bundle.manifestSources];

const readManifestMetadata = (outDir: string): {
  manifestSources: readonly string[];
  manifestEntryPoints: readonly string[];
} => {
  const manifestPath = join(outDir, '.vite', 'manifest.json');
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

  const entryPoints = Object.entries(parsed as Record<string, unknown>)
    .filter(([, chunk]) => typeof chunk === 'object' && chunk !== null && 'isEntry' in chunk && chunk.isEntry === true)
    .map(([key]) => key);

  return {
    manifestSources: Object.freeze(sources.sort()),
    manifestEntryPoints: Object.freeze(entryPoints.sort()),
  };
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
  readonly startToken: string;
  readonly nonce: string;
  readonly teardown_uncertain?: SupervisedProcessGroup;
}

interface SupervisedProcessGroup {
  readonly pgid: number;
  /** Null means identity capture failed; only absence of the whole group permits recovery. */
  readonly startToken: string | null;
}

export interface DirectoryLockOptions {
  readonly staleAfterMs?: number;
  readonly timeoutMs?: number;
  readonly pollMs?: number;
  readonly now?: () => number;
  readonly isProcessAlive?: (pid: number, startToken: string) => boolean;
  /** Whole-group probe; leader exit alone cannot prove teardown complete. */
  readonly isProcessGroupAlive?: (pgid: number) => boolean;
  /** Deterministic fault-injection seam for owner-publication tests. */
  readonly publishOwnership?: (
    lockDir: string,
    ownership: DirectoryLockOwnership,
  ) => DirectoryLockOwnership | null;
}

const ownerPathForLock = (lockDir: string): string => join(lockDir, LOCK_OWNER_FILE);

const buildGuardExists = (lockDir: string): boolean => {
  try {
    statSync(join(lockDir, BUILD_GUARD_FILE));
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== 'ENOENT';
  }
};

const sameOwnership = (left: DirectoryLockOwnership, right: DirectoryLockOwnership): boolean =>
  left.pid === right.pid && left.startToken === right.startToken && left.nonce === right.nonce;

const readLockOwnership = (lockDir: string, file = LOCK_OWNER_FILE): DirectoryLockOwnership | null => {
  try {
    const parsed: unknown = JSON.parse(readFileSync(join(lockDir, file), 'utf8'));
    if (
      typeof parsed !== 'object' ||
      parsed === null ||
      !('pid' in parsed) ||
      !('startToken' in parsed) ||
      !('nonce' in parsed)
    ) {
      return null;
    }
    const { pid, startToken, nonce } = parsed;
    let teardown_uncertain: SupervisedProcessGroup | undefined;
    if ('teardown_uncertain' in parsed) {
      const group = parsed.teardown_uncertain;
      if (
        typeof group !== 'object' ||
        group === null ||
        !('pgid' in group) ||
        typeof group.pgid !== 'number' ||
        !Number.isSafeInteger(group.pgid) ||
        group.pgid <= 0 ||
        !('startToken' in group) ||
        (group.startToken !== null && typeof group.startToken !== 'string')
      ) {
        return null;
      }
      teardown_uncertain = { pgid: group.pgid, startToken: group.startToken };
    }
    return typeof pid === 'number' &&
      Number.isSafeInteger(pid) &&
      pid > 0 &&
      typeof startToken === 'string' &&
      isValidProcessStartToken(startToken) &&
      typeof nonce === 'string' &&
      nonce.length > 0
      ? { pid, startToken, nonce, ...(teardown_uncertain === undefined ? {} : { teardown_uncertain }) }
      : null;
  } catch {
    return null;
  }
};

/**
 * Lock identities are local to one host, so metadata from another platform (or an older,
 * unversioned writer) is not authoritative. In particular, an arbitrary non-empty token must
 * never turn a live PID into evidence of PID reuse.
 */
export const isValidProcessStartToken = (startToken: string): boolean => {
  if (process.platform === 'linux') {
    return /^v1:linux:[0-9]+$/.test(startToken);
  }
  const platformPrefix = `v1:${process.platform}:`;
  return startToken.startsWith(platformPrefix) && /^[A-Za-z0-9_-]+$/.test(startToken.slice(platformPrefix.length));
};

const readProcessStartTokenStrict = (pid: number, timeoutMs = PROCESS_PROBE_BUDGET_MS): string | null => {
  if (process.platform === 'linux') {
    let stat: string;
    try {
      stat = readFileSync(`/proc/${pid}/stat`, 'utf8');
    } catch (error) {
      // A vanished leader is a real identity mismatch. Permission/I/O failures are unknown and
      // must reach the bounded probe error path instead of becoming the same `null` value.
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
      throw error;
    }
    const afterCommand = stat.slice(stat.lastIndexOf(')') + 2).trim().split(/\s+/);
    // `afterCommand[0]` is field 3 (state); field 22 is the kernel process start time.
    if (afterCommand.length < 20 || !/^[0-9]+$/.test(afterCommand[19])) {
      throw Object.assign(new Error(`Malformed /proc/${pid}/stat process identity`), { code: 'EPROTO' });
    }
    return `v1:linux:${afterCommand[19]}`;
  }
  const started = execFileSync('ps', ['-o', 'lstart=', '-p', String(pid)], {
    ...processProbeOptions(timeoutMs),
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
  }).trim();
  return started === ''
    ? null
    : `v1:${process.platform}:${Buffer.from(started, 'utf8').toString('base64url')}`;
};

// Lock acquisition intentionally keeps the old fail-closed boolean contract. Supervision uses
// `readProcessStartTokenStrict` through `runBoundedProcessProbe` so a timeout remains distinct
// from a confirmed replacement leader.
const processStartToken = (pid: number, timeoutMs = PROCESS_PROBE_BUDGET_MS): string | null => {
  try {
    return readProcessStartTokenStrict(pid, timeoutMs);
  } catch {
    return null;
  }
};

const processIdentityIsAlive = (pid: number, startToken: string): boolean => {
  const observed = processStartToken(pid);
  if (observed !== null) return observed === startToken;
  // Unreadable /proc or a failed ps is uncertainty, not evidence of death. Only the
  // kernel's ESRCH (or a successfully read different start token above) permits recovery.
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== 'ESRCH';
  }
};

/**
 * Publish recovery ownership atomically: a mkdir followed by owner.json leaves a permanent
 * ownerless claim if the reaper dies between those writes. A symlink carries all metadata in
 * its creation syscall. Its target is data, never a path to follow.
 *
 * Reclaiming a dead claim is itself serialized by a claim keyed to that claim's unique nonce.
 * After taking it we recheck the original target before unlinking, so a delayed contender
 * cannot unlink a replacement claim (ABA). These secondary claims use the same recovery
 * protocol if their owner dies. Bound crash-chain depth and leave uncertain state untouched.
 */
const tryAcquireRecoveryClaim = (
  claimPath: string,
  ownership: DirectoryLockOwnership,
  options: DirectoryLockOptions,
  depth = 0,
  beforeReclaim?: (incumbent: DirectoryLockOwnership) => void,
): boolean => {
  if (depth >= 32) return false;
  const now = options.now ?? Date.now;
  try {
    symlinkSync(JSON.stringify({ ...ownership, createdAt: now() }), claimPath);
    return true;
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === 'ENOENT') return false; // Another reaper removed the incumbent; retry acquisition.
    if (code !== 'EEXIST') throw error;
  }
  let target: string;
  let incumbent: DirectoryLockOwnership & { createdAt: number };
  try {
    target = readlinkSync(claimPath);
    incumbent = JSON.parse(target);
    if (
      incumbent === null || typeof incumbent !== 'object' ||
      !Number.isSafeInteger(incumbent.pid) || incumbent.pid <= 0 ||
      typeof incumbent.startToken !== 'string' || !isValidProcessStartToken(incumbent.startToken) ||
      typeof incumbent.nonce !== 'string' || !/^[a-zA-Z0-9-]{1,64}$/.test(incumbent.nonce) ||
      !Number.isFinite(incumbent.createdAt) ||
      now() - incumbent.createdAt <= (options.staleAfterMs ?? STALE_LOCK_MS) ||
      (options.isProcessAlive ?? processIdentityIsAlive)(incumbent.pid, incumbent.startToken)
    ) return false;
  } catch {
    // Legacy ownerless directories and unreadable metadata require operator inspection.
    return false;
  }
  const recoveryPath = join(dirname(claimPath), `.reaping-${incumbent.nonce}`);
  if (!tryAcquireRecoveryClaim(recoveryPath, ownership, options, depth + 1)) return false;
  try {
    if (readlinkSync(claimPath) === target) {
      beforeReclaim?.(incumbent);
      rmSync(claimPath, { force: true });
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
  } finally {
    rmSync(recoveryPath, { force: true });
  }
  return false; // Re-enter the caller's bounded acquisition loop after clearing a dead claim.
};

const publishLockOwnership = (
  lockDir: string,
  ownership: DirectoryLockOwnership,
): DirectoryLockOwnership | null => {
  const temporaryOwnerPath = join(lockDir, `.owner-${ownership.pid}-${ownership.nonce}.tmp`);
  try {
    writeFileSync(temporaryOwnerPath, `${JSON.stringify(ownership)}\n`, {
      encoding: 'utf8',
      flag: 'wx',
    });
    renameSync(temporaryOwnerPath, ownerPathForLock(lockDir));
    // Fence a namespace replacement between mkdir/recovery and metadata publication.
    const published = readLockOwnership(lockDir);
    return published !== null && sameOwnership(published, ownership) ? ownership : null;
  } catch {
    try {
      rmSync(temporaryOwnerPath, { force: true });
    } catch {
      // A concurrent namespace replacement may already have removed the temporary file.
    }
    return null;
  }
};

export const tryAcquireDirectoryLock = (
  lockDir: string,
  options: DirectoryLockOptions = {},
): DirectoryLockOwnership | null => {
  mkdirSync(dirname(lockDir), { recursive: true });
  const startToken = processStartToken(process.pid);
  if (startToken === null) {
    throw new Error(`Cannot establish the current process identity for lock ${lockDir}.`);
  }
  const ownership = { pid: process.pid, startToken, nonce: randomUUID() };
  const publishOwnership = options.publishOwnership ?? publishLockOwnership;
  const createPublishedLock = (): DirectoryLockOwnership | null => {
    // The initial claim and its recovery identity appear in one syscall, BEFORE mkdir.
    // A dead creator's empty directory can only be removed while holding the recovery
    // claim for this exact creation nonce. Only this creator's unpublished temp file is
    // also safe to remove; other nonempty/malformed leases remain fenced.
    const creationClaim = `${lockDir}.creating`;
    if (!tryAcquireRecoveryClaim(creationClaim, ownership, options, 0, (creator) => {
      try {
        const files = readdirSync(lockDir);
        if (files.every((file) => file === `.owner-${creator.pid}-${creator.nonce}.tmp`)) {
          rmSync(lockDir, { recursive: true });
        }
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
      }
    })) return null;
    try {
      mkdirSync(lockDir);
      const published = publishOwnership(lockDir, ownership);
      if (published === null) {
        // We exclusively created this namespace, so a failed owner publication must not turn it
        // into a permanent malformed lock. Preserve any valid replacement ownership.
        const incumbent = readLockOwnership(lockDir);
        if (incumbent === null || sameOwnership(incumbent, ownership)) {
          rmSync(lockDir, { recursive: true, force: true });
        }
      }
      return published;
    } finally {
      rmSync(creationClaim, { force: true });
    }
  };
  try {
    return createPublishedLock();
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'EEXIST') {
      throw error;
    }
    const incumbent = readLockOwnership(lockDir);
    // Missing or malformed metadata is never evidence of a dead owner. In particular, a
    // contender may be observing the short mkdir-to-rename publication window.
    if (incumbent === null) {
      return null;
    }
    let leaseAgeMs: number;
    try {
      leaseAgeMs = (options.now ?? Date.now)() - statSync(ownerPathForLock(lockDir)).mtimeMs;
    } catch {
      // The holder released between mkdir and inspection; let the caller retry.
      return null;
    }
    const staleAfterMs = options.staleAfterMs ?? STALE_LOCK_MS;
    const isProcessAlive = options.isProcessAlive ?? processIdentityIsAlive;
    const teardownIsComplete = (owner: DirectoryLockOwnership): boolean => {
      if (owner.teardown_uncertain === undefined) {
        if (!buildGuardExists(lockDir)) return true;
        const guard = readLockOwnership(lockDir, BUILD_GUARD_FILE);
        if (guard === null || !sameOwnership(guard, owner) || guard.teardown_uncertain === undefined) {
          return false;
        }
        // The supervisor publishes its identity before starting npm. After an owner crash,
        // confirm the whole group is gone, never just its leader.
        try {
          return !(options.isProcessGroupAlive ??
            ((pgid: number) => processGroupExistsViaSignal(pgid, (id, signal) => process.kill(id, signal))))(
            guard.teardown_uncertain.pgid,
          );
        } catch {
          return false;
        }
      }
      try {
        const isGroupAlive =
          options.isProcessGroupAlive ??
          ((pgid: number) => processGroupExistsViaSignal(pgid, (id, signal) => process.kill(id, signal)));
        return !isGroupAlive(owner.teardown_uncertain.pgid);
      } catch {
        return false;
      }
    };
    if (
      leaseAgeMs > staleAfterMs &&
      !isProcessAlive(incumbent.pid, incumbent.startToken) &&
      teardownIsComplete(incumbent)
    ) {
      // Serialize stale recovery inside the incumbent directory. Without this claim, two
      // reapers can both inspect owner A, then the slower one can delete newly-created owner B
      // after the faster one removes A (the classic ABA unlink race).
      const recoveryClaim = join(lockDir, '.reaping');
      if (!tryAcquireRecoveryClaim(recoveryClaim, ownership, options)) return null;

      const confirmedIncumbent = readLockOwnership(lockDir);
      if (confirmedIncumbent === null || !sameOwnership(confirmedIncumbent, incumbent)) {
        rmSync(recoveryClaim, { recursive: true, force: true });
        return null;
      }
      let confirmedLeaseAgeMs: number;
      try {
        confirmedLeaseAgeMs = (options.now ?? Date.now)() - statSync(ownerPathForLock(lockDir)).mtimeMs;
      } catch {
        rmSync(recoveryClaim, { recursive: true, force: true });
        return null;
      }
      if (
        confirmedLeaseAgeMs > staleAfterMs &&
        !isProcessAlive(confirmedIncumbent.pid, confirmedIncumbent.startToken) &&
        teardownIsComplete(confirmedIncumbent)
      ) {
        rmSync(lockDir, { recursive: true, force: true });
        try {
          return createPublishedLock();
        } catch (replacementError) {
          if ((replacementError as NodeJS.ErrnoException).code !== 'EEXIST') {
            throw replacementError;
          }
          return null;
        }
      } else {
        rmSync(recoveryClaim, { recursive: true, force: true });
      }
    }
    return null;
  }
};

export const acquireDirectoryLock = (
  lockDir: string,
  options: DirectoryLockOptions = {},
): DirectoryLockOwnership => {
  const timeoutMs = options.timeoutMs ?? LOCK_TIMEOUT_MS;
  // `options.now` remains a combined deterministic seam for lease-age tests. In production the
  // wait budget is monotonic while tryAcquireDirectoryLock separately uses wall time for mtimes.
  const deadlineNow = options.now ?? monotonicNow;
  const deadline = deadlineNow() + timeoutMs;
  for (;;) {
    const ownership = tryAcquireDirectoryLock(lockDir, options);
    if (ownership !== null) {
      return ownership;
    }
    if (deadlineNow() > deadline) {
      throw new Error(
        `Timed out after ${timeoutMs}ms waiting for the production-CSS lock at ${lockDir}. ` +
          'Remove it if no build is running.',
      );
    }
    sleepSync(options.pollMs ?? LOCK_POLL_MS);
  }
};

export const releaseDirectoryLock = (
  lockDir: string,
  ownership: DirectoryLockOwnership,
): boolean => {
  const incumbent = readLockOwnership(lockDir);
  if (
    incumbent === null ||
    !sameOwnership(incumbent, ownership) ||
    incumbent.teardown_uncertain !== undefined ||
    buildGuardExists(lockDir)
  ) {
    return false;
  }
  rmSync(lockDir, { recursive: true, force: true });
  return true;
};

export const runWithLockHeartbeat = <T>(
  lockDir: string,
  ownership: DirectoryLockOwnership,
  operation: () => T,
  heartbeatMs: number = LOCK_HEARTBEAT_MS,
): T => {
  const readyPath = join(lockDir, `.heartbeat-${ownership.nonce}.ready`);
  const heartbeatSource = String.raw`
const fs = require('node:fs');
const path = require('node:path');
const [lockDir, expectedToken, intervalText, readyPath] = process.argv.slice(1);
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
fs.writeFileSync(readyPath, 'ready');
setInterval(beat, Number(intervalText)).unref();
setInterval(() => {}, 0x7fffffff);
`;
  const token = JSON.stringify(ownership);
  const heartbeat = spawn(
    process.execPath,
    ['-e', heartbeatSource, lockDir, token, String(heartbeatMs), readyPath],
    { stdio: 'ignore' },
  );
  try {
    const readyTimeoutMs = Math.max(5_000, heartbeatMs * 5);
    const readyDeadline = monotonicNow() + readyTimeoutMs;
    while (!existsSync(readyPath)) {
      if (monotonicNow() >= readyDeadline) {
        throw new Error(`Lock heartbeat did not become ready within ${readyTimeoutMs}ms.`);
      }
      sleepSync(10);
    }
    return operation();
  } finally {
    heartbeat.kill();
    try {
      rmSync(readyPath, { force: true });
    } catch {
      // The lock namespace also owns this sentinel. Permission changes must not replace an
      // uncertain teardown error before runWithBuildLock can persist its group identity.
    }
  }
};

export class ProductionCssBuildTimeoutError extends Error {
  readonly code = 'RES-13';

  constructor(timeoutMs: number) {
    super(`Production CSS build exceeded its ${timeoutMs}ms deadline (RES-13).`);
    this.name = 'ProductionCssBuildTimeoutError';
  }
}

export class ProductionCssBuildTeardownError extends Error {
  readonly code: string = 'RES-13-TEARDOWN';
  /** A successor must not enter while the previous process group may still be alive. */
  readonly retainBuildLock = true;
  supervisedGroup?: SupervisedProcessGroup;

  constructor(timeoutMs: number, detail?: string, options?: ErrorOptions) {
    super(
      detail ?? `Production CSS process group survived SIGKILL for ${timeoutMs}ms (RES-13-TEARDOWN).`,
      options,
    );
    this.name = 'ProductionCssBuildTeardownError';
  }
}

/**
 * A process probe did not produce evidence within its bounded budget.
 *
 * This is deliberately a subtype of the ordinary teardown error so all of the existing lock
 * retention/fencing paths remain armed, while callers and diagnostics can distinguish an
 * unverifiable probe from a confirmed leader-identity change. Treating a timeout as `null` is
 * unsafe: `null` is the value used for a real identity mismatch and would authorize the wrong
 * RES-13 diagnostic (and, in the old implementation, skip signalling entirely).
 */
export class ProductionCssBuildTeardownTimeoutError extends ProductionCssBuildTeardownError {
  readonly code: string = 'RES-13-TEARDOWN-TIMEOUT';
  readonly probe: string;
  readonly budgetMs: number;
  readonly elapsedMs: number;

  constructor(
    probe: string,
    budgetMs: number,
    elapsedMs: number,
    options?: ErrorOptions,
  ) {
    const cause = options?.cause;
    const causeCode = cause !== null && typeof cause === 'object' && 'code' in cause
      ? String(cause.code)
      : 'unknown';
    super(
      budgetMs,
      `Production CSS teardown ${probe} probe failed after ${Math.max(0, Math.ceil(elapsedMs))}ms ` +
        `(budget ${Math.max(0, Math.ceil(budgetMs))}ms; ${causeCode}); process state is unknown; ` +
        'retaining the build lock (RES-13-TEARDOWN-TIMEOUT).',
      options,
    );
    this.name = 'ProductionCssBuildTeardownTimeoutError';
    this.probe = probe;
    this.budgetMs = budgetMs;
    this.elapsedMs = elapsedMs;
  }
}

/** Persist uncertain teardown so the fence survives the lock owner's exit. */
export const runWithBuildLock = <T>(
  lockDir: string,
  ownership: DirectoryLockOwnership,
  operation: () => T,
): T => {
  const incumbent = readLockOwnership(lockDir);
  if (incumbent === null || !sameOwnership(incumbent, ownership) || incumbent.teardown_uncertain !== undefined) {
    throw new Error(`Cannot prepare a build without exclusive ownership of ${lockDir}.`);
  }
  const guardPath = join(lockDir, BUILD_GUARD_FILE);
  let ownerFd: number | undefined;
  let guardCreated = false;
  let retainLock = false;
  try {
    // Prepare both before operation can spawn a group. The open lease remains writable after
    // directory permissions change; the guard survives even a total failure of later writes.
    ownerFd = openSync(ownerPathForLock(lockDir), 'r+');
    const guardFd = openSync(guardPath, 'wx');
    guardCreated = true;
    try {
      writeFileSync(guardFd, `${JSON.stringify(ownership)}\n`);
      fsyncSync(guardFd);
    } finally {
      closeSync(guardFd);
    }
    return operation();
  } catch (error) {
    retainLock = error instanceof ProductionCssBuildTeardownError && error.retainBuildLock;
    if (error instanceof ProductionCssBuildTeardownError) {
      const incumbent = readLockOwnership(lockDir);
      if (incumbent !== null && sameOwnership(incumbent, ownership)) {
        if (error.supervisedGroup !== undefined) {
          const fencedOwner = {
            ...incumbent,
            teardown_uncertain: error.supervisedGroup,
          };
          if (publishLockOwnership(lockDir, fencedOwner) === null && ownerFd !== undefined) {
            try {
              const content = `${JSON.stringify(fencedOwner)}\n`;
              writeFileSync(ownerFd, content);
              ftruncateSync(ownerFd, Buffer.byteLength(content));
              fsyncSync(ownerFd);
            } catch {
              // Partial/unreadable metadata already fails closed. If the ordinary lease survived,
              // the pre-created guard prevents stale recovery after this owner exits as well.
            }
          }
        }
      }
      const group = error.supervisedGroup;
      error.message += ` Lock retained at ${lockDir}; supervised PGID ${group?.pgid ?? 'unknown'}, ` +
        `start token ${group?.startToken ?? 'unknown'}. If group metadata could not be persisted, ` +
        'stop fixture users, terminate surviving build members, then remove the lock directory manually.';
    }
    throw error;
  } finally {
    if (ownerFd !== undefined) closeSync(ownerFd);
    if (!retainLock) {
      if (guardCreated) rmSync(guardPath, { force: true });
      releaseDirectoryLock(lockDir, ownership);
    }
  }
};

type ProcessSignal = NodeJS.Signals | 0;

const monotonicNow = (): number => Number(process.hrtime.bigint()) / 1_000_000;

export interface ProcessGroupWaitOptions {
  readonly timeoutMs: number;
  readonly terminationGraceMs?: number;
  readonly killConfirmationMs?: number;
  readonly now?: () => number;
  readonly sleep?: (milliseconds: number) => void;
  readonly readExitCode: () => number | null;
  /** Test seam retained for deterministic supervision tests; it represents the whole group. */
  readonly isProcessAlive?: (pid: number) => boolean;
  readonly isProcessGroupAlive?: (processGroupId: number) => boolean;
  readonly sendSignal?: (pidOrGroup: number, signal: ProcessSignal) => void;
  /** Identity of the detached group leader, captured immediately after spawn. */
  readonly processGroupStartToken?: string;
  /** Test seam for detecting replacement of a process-group leader. */
  readonly readProcessStartToken?: (pid: number) => string | null;
  /** Complete `ps -A -o pid=,pgid=,stat=` output; failures must throw. */
  readonly listProcesses?: () => string;
}

// Never pass zero to execFileSync: it disables the timeout. An exhausted phase
// cannot establish absence, and must not launch another subprocess.
const processProbeOptions = (timeoutMs: number): { timeout: number; killSignal: 'SIGKILL' } => {
  if (timeoutMs <= 0) throw Object.assign(new Error('Process probe deadline exhausted'), { code: 'ETIMEDOUT' });
  return { timeout: Math.max(1, Math.ceil(timeoutMs)), killSignal: 'SIGKILL' };
};

const runBoundedProcessProbe = <T>(
  probe: string,
  budgetMs: number,
  now: () => number,
  operation: () => T,
): T => {
  const started = now();
  if (budgetMs <= 0) {
    throw new ProductionCssBuildTeardownTimeoutError(
      probe,
      budgetMs,
      0,
      { cause: Object.assign(new Error('Process probe deadline exhausted'), { code: 'ETIMEDOUT' }) },
    );
  }
  try {
    const result = operation();
    const elapsedMs = Math.max(0, now() - started);
    if (elapsedMs > budgetMs) {
      throw Object.assign(new Error('Process probe budget exhausted'), { code: 'ETIMEDOUT' });
    }
    return result;
  } catch (error) {
    if (error instanceof ProductionCssBuildTeardownTimeoutError) throw error;
    throw new ProductionCssBuildTeardownTimeoutError(
      probe,
      budgetMs,
      Math.max(0, now() - started),
      { cause: error },
    );
  }
};

const listProcessStates = (timeoutMs: number): string => execFileSync('ps', ['-A', '-o', 'pid=,pgid=,stat='], {
  ...processProbeOptions(timeoutMs),
  encoding: 'utf8',
  stdio: ['ignore', 'pipe', 'ignore'],
});

// ps emits decimal process identifiers; reject impossible and non-canonical fields.
const isValidProcessIdField = (field: string | undefined): boolean => {
  if (field === undefined || !/^[1-9][0-9]*$/.test(field)) return false;
  const value = Number(field);
  return Number.isSafeInteger(value) && value <= 4194304;
};

const listedGroupIsAliveStrict = (
  processGroupId: number,
  listProcesses: () => string,
  report: (detail: string) => void = () => {},
): boolean => {
  const output = listProcesses();
  // A complete system listing includes at least ps itself. Empty or malformed output
  // cannot establish that a group is gone.
  let parsed = 0;
  let alive = false;
  const matches: string[] = [];
  for (const line of output.split('\n')) {
    const fields = line.trim().split(/\s+/);
    const [pid, pgid, stat] = fields;
    const matchingGroup = pgid !== undefined && Number(pgid) === processGroupId;
    // Check membership before dropping malformed rows: an unreadable member cannot
    // establish teardown, even when other rows in the listing are parsable.
    const valid = fields.length === 3 && isValidProcessIdField(pid) && isValidProcessIdField(pgid) &&
      /^[RSDTtZXxKWPIU][<NLsl+>EXVW-]*$/.test(stat ?? '');
    if (matchingGroup) {
      matches.push(line);
      if (!valid || !stat.startsWith('Z')) alive = true;
    }
    if (!valid) continue;
    parsed++;
  }
  report(parsed === 0
    ? `ps parsed zero lines; output=${JSON.stringify(output)}`
    : `ps matching lines (pid pgid stat)=${JSON.stringify(matches)}`);
  return parsed === 0 || alive;
};

const processGroupHasNonZombieMemberStrict = (
  processGroupId: number,
  timeoutMs: number,
  now: () => number = monotonicNow,
): boolean => {
  const deadline = now() + timeoutMs;
  if (process.platform === 'linux') {
    for (const entry of readdirSync('/proc')) {
      if (now() >= deadline) {
        throw Object.assign(new Error('Process probe deadline exhausted'), { code: 'ETIMEDOUT' });
      }
      if (!/^[0-9]+$/.test(entry)) continue;
      try {
        const stat = readFileSync(`/proc/${entry}/stat`, 'utf8');
        const fields = stat.slice(stat.lastIndexOf(')') + 2).trim().split(/\s+/);
        // fields[0] is state (field 3), fields[2] is process group ID (field 5).
        if (fields[0] !== 'Z' && Number(fields[2]) === processGroupId) return true;
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'ENOENT') continue;
        // stat may be restricted for unrelated users. status exposes group membership
        // separately; never make a known unrelated process fence this build's teardown.
        try {
          const status = readFileSync(`/proc/${entry}/status`, 'utf8');
          const group = /^NSpgid:\s+(\d+)/m.exec(status);
          if (group === null || Number(group[1]) === processGroupId) return true;
        } catch (statusError) {
          if ((statusError as NodeJS.ErrnoException).code !== 'ENOENT') return true;
        }
      }
    }
    return false;
  }
  const states = execFileSync('ps', ['-o', 'stat=', '-g', String(processGroupId)], {
    ...processProbeOptions(Math.max(0, deadline - now())),
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
  })
    .trim()
    .split(/\s+/);
  return states.some((state) => state !== '' && !state.startsWith('Z'));
};

const processGroupExistsViaSignal = (
  processGroupId: number,
  sendSignal: (pidOrGroup: number, signal: ProcessSignal) => void,
): boolean => {
  try {
    sendSignal(-processGroupId, 0);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ESRCH') return false;
    // EPERM still proves that the group exists; unexpected errors fail closed as alive.
    return true;
  }
  return true;
};

const processGroupIsAliveStrict = (
  processGroupId: number,
  sendSignal: (pidOrGroup: number, signal: ProcessSignal) => void,
  listProcesses: (timeoutMs: number) => string,
  report: (detail: string) => void = () => {},
  timeoutMs: number = PROCESS_PROBE_BUDGET_MS,
  now: () => number = monotonicNow,
): boolean => {
  const deadline = now() + timeoutMs;
  const remainingMs = (): number => Math.max(0, deadline - now());
  try {
    sendSignal(-processGroupId, 0);
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code ?? 'unknown';
    if (code === 'ESRCH') { report('signal probe: ESRCH'); return false; }
    // EPERM can also describe a retired zombie-only group on macOS.
    return listedGroupIsAliveStrict(
      processGroupId,
      () => listProcesses(remainingMs()),
      detail => report(`signal probe: ${code}; ${detail}`),
    );
  }
  // kill(2) reports zombie-only groups as existing. They cannot execute or retain resources, and
  // descendants may remain zombies until their own parent reaps them.
  if (process.platform !== 'linux') {
    return listedGroupIsAliveStrict(
      processGroupId,
      () => listProcesses(remainingMs()),
      detail => report(`signal probe: success; ${detail}`),
    );
  }
  const alive = processGroupHasNonZombieMemberStrict(processGroupId, remainingMs(), now);
  report(`signal probe: success; /proc non-zombie member or uncertain inspection: ${alive}`);
  if (alive) {
    return listedGroupIsAliveStrict(
      processGroupId,
      () => listProcesses(remainingMs()),
      detail => report(`signal probe: success; /proc alive; ${detail}`),
    );
  }
  return alive;
};

const terminateProcessGroup = (
  processGroupId: number,
  options: ProcessGroupWaitOptions,
  isGroupAlive: () => boolean,
  now: () => number,
  pause: (milliseconds: number) => void,
  sendSignal: (pidOrGroup: number, signal: ProcessSignal) => void,
  identityMatches: () => boolean,
  setProbePhaseDeadline: (deadline: number) => void,
): void => {
  const signalGroup = (signal: NodeJS.Signals): void => {
    if (!identityMatches()) {
      // The supervisor can finish its own teardown and be reaped between the liveness
      // check and this identity check. Confirm the whole group is gone before refusing;
      // a missing leader with surviving members must still keep the lock fenced.
      if (!isGroupAlive()) return;
      throw new ProductionCssBuildTeardownError(
        options.killConfirmationMs ?? BUILD_TERMINATION_GRACE_MS,
        `Refusing to send ${signal} because process group ${processGroupId} no longer has the supervised leader identity (RES-13-TEARDOWN).`,
      );
    }
    try {
      sendSignal(-processGroupId, signal);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ESRCH') {
        throw new ProductionCssBuildTeardownError(
          options.killConfirmationMs ?? BUILD_TERMINATION_GRACE_MS,
          `Could not send ${signal} to production CSS process group ${processGroupId}; its lock must remain held (RES-13-TEARDOWN).`,
          { cause: error },
        );
      }
    }
  };

  const termDeadline = now() + (options.terminationGraceMs ?? BUILD_TERMINATION_GRACE_MS);
  setProbePhaseDeadline(termDeadline);
  signalGroup('SIGTERM');
  while (isGroupAlive() && now() < termDeadline) {
    pause(Math.min(25, Math.max(1, termDeadline - now())));
  }
  if (!isGroupAlive()) return;

  const killConfirmationMs = options.killConfirmationMs ?? BUILD_TERMINATION_GRACE_MS;
  const killDeadline = now() + killConfirmationMs;
  setProbePhaseDeadline(killDeadline);
  signalGroup('SIGKILL');
  while (isGroupAlive() && now() < killDeadline) {
    pause(Math.min(25, Math.max(1, killDeadline - now())));
  }
  if (isGroupAlive()) {
    throw new ProductionCssBuildTeardownError(killConfirmationMs);
  }
};

/** Synchronously supervise a detached process group without relying on an unbounded sync timeout. */
export const waitForProcessGroup = (pid: number, options: ProcessGroupWaitOptions): number => {
  const now = options.now ?? monotonicNow;
  const deadline = now() + options.timeoutMs;
  let lastProbe = 'group liveness probe not run (or supplied by caller)';
  let startToken: string | null = options.processGroupStartToken ?? null;
  try {
    if (startToken === null) {
      // Capture the leader independently of the wait phase. A short caller timeout must not turn
      // the identity probe into an already-expired `ps` invocation, and a failed capture must be
      // retained as an unknown probe rather than silently becoming a replacement identity.
      startToken = runBoundedProcessProbe(
        'leader identity',
        PROCESS_PROBE_BUDGET_MS,
        now,
        () => (options.readProcessStartToken ?? ((id: number) => readProcessStartTokenStrict(id, PROCESS_PROBE_BUDGET_MS)))(pid),
      );
    }
    return waitForIdentifiedProcessGroup(pid, options, startToken, deadline, detail => { lastProbe = detail; });
  } catch (error) {
    if (error instanceof ProductionCssBuildTeardownError) {
      error.supervisedGroup = { pgid: pid, startToken };
      error.message += ` Final group confirmation: ${lastProbe}.`;
    }
    throw error;
  }
};

const waitForIdentifiedProcessGroup = (
  pid: number,
  options: ProcessGroupWaitOptions,
  expectedStartToken: string | null,
  deadline: number,
  report: (detail: string) => void,
): number => {
  const now = options.now ?? monotonicNow;
  const pause = options.sleep ?? sleepSync;
  // The wait phase owns `deadline`; each probe gets its own budget plus a finite, documented
  // extension. This prevents one slow identity/listing probe from starving the phase while also
  // preventing a sequence of probes from extending it without bound.
  let probePhaseDeadline = deadline;
  const setProbePhaseDeadline = (value: number): void => { probePhaseDeadline = value; };
  const probeBudget = (probe: string): number => {
    const remainingMs = probePhaseDeadline + PROCESS_PROBE_EXTENSION_MS - now();
    if (remainingMs <= 0) {
      throw new ProductionCssBuildTeardownTimeoutError(
        probe,
        PROCESS_PROBE_BUDGET_MS,
        PROCESS_PROBE_EXTENSION_MS,
        { cause: Object.assign(new Error('Process probe extension budget exhausted'), { code: 'ETIMEDOUT' }) },
      );
    }
    return Math.min(PROCESS_PROBE_BUDGET_MS, remainingMs);
  };
  const sendSignal = options.sendSignal ?? ((pidOrGroup, signal) => process.kill(pidOrGroup, signal));
  const listProcesses = (timeoutMs: number): string => {
    if (timeoutMs <= 0) {
      throw Object.assign(new Error('Process probe deadline exhausted'), { code: 'ETIMEDOUT' });
    }
    return options.listProcesses === undefined
      ? listProcessStates(timeoutMs)
      : options.listProcesses();
  };
  const rawGroupIsAlive = (_groupId: number): boolean => {
    const budgetMs = probeBudget('process-group liveness');
    return runBoundedProcessProbe('process-group liveness', budgetMs, now, () => {
      if (options.isProcessGroupAlive !== undefined) return options.isProcessGroupAlive(pid);
      if (options.isProcessAlive !== undefined) return options.isProcessAlive(pid);
      return options.sendSignal === undefined
        ? processGroupIsAliveStrict(pid, sendSignal, listProcesses, report, budgetMs, now)
        : processGroupExistsViaSignal(pid, sendSignal);
    });
  };
  const readStartToken = (id: number): string | null => {
    const budgetMs = probeBudget('leader identity');
    return runBoundedProcessProbe('leader identity', budgetMs, now, () =>
      (options.readProcessStartToken ?? ((processId: number) => readProcessStartTokenStrict(processId, budgetMs)))(id));
  };
  if (expectedStartToken === null) {
    throw new ProductionCssBuildTeardownError(
      options.killConfirmationMs ?? BUILD_TERMINATION_GRACE_MS,
      `Cannot establish the supervised leader identity for process group ${pid} (RES-13-TEARDOWN).`,
    );
  }
  const identityMatches = (): boolean => readStartToken(pid) === expectedStartToken;
  let unknownProbeError: ProductionCssBuildTeardownTimeoutError | undefined;
  const groupState = (): 'owned' | 'gone' | 'unverifiable' | 'unknown' => {
    unknownProbeError = undefined;
    let matches: boolean;
    try {
      matches = identityMatches();
    } catch (error) {
      if (error instanceof ProductionCssBuildTeardownTimeoutError) {
        unknownProbeError = error;
        return 'unknown';
      }
      throw error;
    }
    let alive: boolean;
    try {
      alive = rawGroupIsAlive(pid);
    } catch (error) {
      if (error instanceof ProductionCssBuildTeardownTimeoutError) {
        unknownProbeError = error;
        return 'unknown';
      }
      throw error;
    }
    if (!alive) return 'gone';
    return matches ? 'owned' : 'unverifiable';
  };
  const assertVerifiable = (state: ReturnType<typeof groupState>): void => {
    if (state === 'unknown') {
      throw unknownProbeError ?? new ProductionCssBuildTeardownTimeoutError(
        'process-group state',
        PROCESS_PROBE_BUDGET_MS,
        PROCESS_PROBE_BUDGET_MS,
        { cause: Object.assign(new Error('Process state is unknown'), { code: 'ETIMEDOUT' }) },
      );
    }
    if (state === 'unverifiable') {
      throw new ProductionCssBuildTeardownError(
        options.killConfirmationMs ?? BUILD_TERMINATION_GRACE_MS,
        `Process group ${pid} is live but its leader identity changed; refusing to signal a reused PGID (RES-13-TEARDOWN).`,
      );
    }
  };
  const isOwnedGroupAlive = (): boolean => {
    const state = groupState();
    assertVerifiable(state);
    return state === 'owned';
  };

  for (;;) {
    const exitCode = options.readExitCode();
    const state = groupState();
    assertVerifiable(state);
    if (exitCode !== null) {
      if (state === 'owned') {
        terminateProcessGroup(pid, options, isOwnedGroupAlive, now, pause, sendSignal, identityMatches, setProbePhaseDeadline);
      }
      return exitCode;
    }
    if (state === 'gone') {
      throw new Error('Production CSS build exited without publishing an exit status.');
    }
    if (now() >= deadline) {
      break;
    }
    pause(Math.min(25, Math.max(1, deadline - now())));
  }

  terminateProcessGroup(pid, options, isOwnedGroupAlive, now, pause, sendSignal, identityMatches, setProbePhaseDeadline);
  throw new ProductionCssBuildTimeoutError(options.timeoutMs);
};

const runProductionBuild = (outDir: string, lockDir?: string): void => {
  if (lockDir !== undefined) {
    // A stability retry starts a new group. Do not leave the previous group's now-dead
    // identity in the guard during this supervisor's startup window.
    const owner = readLockOwnership(lockDir);
    if (owner === null || owner.pid !== process.pid) throw new Error(`Lost build ownership of ${lockDir}.`);
    writeFileSync(join(lockDir, BUILD_GUARD_FILE), JSON.stringify(owner));
  }
  const statusRoot = mkdtempSync(join(tmpdir(), 'acx-style-build-status-'));
  const statusPath = join(statusRoot, 'exit-code');
  const supervisorSource = String.raw`
const { spawn, execFileSync } = require('node:child_process');
const fs = require('node:fs');
const { readFileSync } = fs;
const [statusPath, cwd, command, argsToken, parentText, guardPath, lifetimeText, graceText] = process.argv.slice(1);
const processStartToken = (pid) => {
  try {
    if (process.platform === 'linux') {
      const stat = readFileSync('/proc/' + pid + '/stat', 'utf8');
      const fields = stat.slice(stat.lastIndexOf(')') + 2).trim().split(/\s+/);
      return /^[0-9]+$/.test(fields[19]) ? 'v1:linux:' + fields[19] : null;
    }
    const started = execFileSync('ps', ['-o', 'lstart=', '-p', String(pid)], {
      encoding: 'utf8', timeout: 1000, killSignal: 'SIGKILL' }).trim();
    return started ? 'v1:' + process.platform + ':' + Buffer.from(started).toString('base64url') : null;
  } catch { return null; }
};
// Publish before any build member exists. An interrupted/failed publication leaves the
// pre-created guard closed to recovery, and this supervisor never launches npm.
if (guardPath) {
  const owner = JSON.parse(fs.readFileSync(guardPath, 'utf8'));
  const temporaryPath = guardPath + '.supervisor';
  fs.writeFileSync(temporaryPath, JSON.stringify({ ...owner,
    teardown_uncertain: { pgid: process.pid, startToken: processStartToken(process.pid) } }));
  fs.renameSync(temporaryPath, guardPath);
}
let stopping = false;
const stopGroup = () => {
  if (stopping) return;
  stopping = true;
  // Retain the leader identity through TERM grace, then kill our entire group in one syscall.
  // Recovery independently confirms teardown using the persisted group metadata.
  process.kill(-process.pid, 'SIGTERM');
  setTimeout(() => process.kill(-process.pid, 'SIGKILL'), Number(graceText));
};
process.on('SIGTERM', stopGroup);
const deadline = process.hrtime.bigint() + BigInt(lifetimeText) * 1000000n;
setInterval(() => {
  if (process.ppid !== Number(parentText) || process.hrtime.bigint() >= deadline) stopGroup();
}, 100).unref();
// This bounded timer also keeps the supervisor identifiable after publishing a result.
setTimeout(stopGroup, Number(lifetimeText));
if (process.ppid !== Number(parentText)) {
  stopGroup();
} else {
const child = spawn(command, JSON.parse(argsToken), { cwd, stdio: 'ignore' });
let published = false;
const publishExitCode = (code) => {
  if (published) return;
  published = true;
  const temporaryPath = statusPath + '.tmp';
  try {
    fs.writeFileSync(temporaryPath, String(code));
    fs.renameSync(temporaryPath, statusPath);
  } catch {
    stopGroup();
  }
  setTimeout(stopGroup, Number(graceText)).unref();
};
child.once('error', () => { publishExitCode(127); });
child.once('exit', (code, signal) => {
  const exitCode = code === null ? 128 + ({ SIGTERM: 15, SIGKILL: 9 }[signal] || 1) : code;
  // Stay alive as the group leader until the parent tears the group down. A live leader with a
  // stable start token prevents this numeric PGID from being recycled before the signal.
  publishExitCode(exitCode);
});
}
`;
  const buildArgs = ['run', 'build', '--', '--outDir', outDir, '--emptyOutDir'];
  // The fixture API is synchronous. Spawn on a separate event loop so libuv can reap the
  // supervised child while this thread waits; a successfully killed leader must not remain
  // a zombie solely because its parent is polling synchronously.
  const launchState = new Int32Array(new SharedArrayBuffer(4));
  const reaper = new Worker(String.raw`
const { workerData } = require('node:worker_threads');
const { spawn } = require('node:child_process');
const state = new Int32Array(workerData.state);
const report = (pid) => { Atomics.store(state, 0, pid); Atomics.notify(state, 0); };
try {
  const child = spawn(process.execPath, workerData.args, { detached: true, stdio: 'ignore' });
  child.once('error', () => report(-1));
  child.once('exit', () => {}); // Keep the event loop alive until waitpid has reaped the child.
  report(child.pid ?? -1);
} catch { report(-1); }
`, { eval: true, execArgv: [], workerData: {
    state: launchState.buffer,
    args: ['-e', supervisorSource, statusPath, appRoot, 'npm', JSON.stringify(buildArgs),
      String(process.pid), lockDir === undefined ? '' : join(lockDir, BUILD_GUARD_FILE),
      String(BUILD_TIMEOUT_MS + BUILD_TERMINATION_GRACE_MS), String(BUILD_TERMINATION_GRACE_MS)],
  } });
  reaper.on('error', () => {}); // Startup is checked through the bounded shared-state handshake.
  reaper.unref();
  Atomics.wait(launchState, 0, 0, Math.max(5_000, BUILD_TERMINATION_GRACE_MS));
  const supervisor = { pid: Atomics.load(launchState, 0) };
  let teardownUncertain = false;
  try {
    if (supervisor.pid <= 0) {
      void reaper.terminate();
      if (supervisor.pid === -1) {
        throw new Error('Failed to start the detached production CSS build process group.');
      }
      throw new ProductionCssBuildTeardownError(BUILD_TERMINATION_GRACE_MS,
        'Could not confirm production CSS supervisor startup; retaining the build lock.');
    }
    const supervisorStartToken = processStartToken(supervisor.pid);
    const exitCode = waitForProcessGroup(supervisor.pid, {
      timeoutMs: BUILD_TIMEOUT_MS,
      processGroupStartToken: supervisorStartToken ?? undefined,
      readExitCode: () => {
        try {
          const contents = readFileSync(statusPath, 'utf8');
          if (contents === '' || /[^0-9]/.test(contents)) return null;
          const value = Number(contents);
          return Number.isSafeInteger(value) && value <= 255 ? value : null;
        } catch {
          return null;
        }
      },
    });
    if (exitCode !== 0) {
      throw new Error(`Production CSS build exited with status ${exitCode}.`);
    }
  } catch (error) {
    teardownUncertain = error instanceof ProductionCssBuildTeardownError;
    throw error;
  } finally {
    try {
      rmSync(statusRoot, { recursive: true, force: true });
    } catch (cleanupError) {
      // Preserve the teardown error so runWithBuildLock keeps the surviving group fenced.
      if (!teardownUncertain) throw cleanupError;
    }
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
  let latest = 0;
  try {
    latest = statSync(namespaceRoot).mtimeMs;
    for (const child of readdirSync(namespaceRoot, { withFileTypes: true })) {
      const activityPath = child.isDirectory()
        ? join(namespaceRoot, child.name, STAMP_FILE)
        : join(namespaceRoot, child.name);
      try {
        latest = Math.max(latest, statSync(activityPath).mtimeMs);
      } catch (error) {
        // Sibling artifact pruning does not take the parent GC lock.
        if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
      }
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
  }
  return latest;
};

const readNamespaceEntries = (cacheRoot: string, keepNamespace: string): NamespaceEntry[] =>
  readdirSync(cacheRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name !== '.gc-lock' && entry.name !== keepNamespace)
    .flatMap((entry) => {
      const namespaceRoot = join(cacheRoot, entry.name);
      const ownerRoot = readNamespaceOwner(namespaceRoot);
      const ownerRootExists = ownerRoot === null ? null : existsSync(ownerRoot);
      if (ownerRootExists === true) return [];
      const lockDir = join(namespaceRoot, '.lock');
      if (existsSync(lockDir)) {
        // Registration/acquisition also takes the GC lock, so no worker can enter between
        // this fenced recovery and collection. Never wait here for a live or uncertain owner.
        if (ownerRootExists !== false) return [];
        const recovered = tryAcquireDirectoryLock(lockDir);
        if (recovered === null) return [];
        releaseDirectoryLock(lockDir, recovered);
      }
      return [{
        name: entry.name,
        lastUsedMs: namespaceLastUsedMs(namespaceRoot),
        ownerRootExists,
        lockHeld: false,
      }];
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
  const buildDeadline = monotonicNow() + LOCK_TIMEOUT_MS;
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
        readNamespaceEntries(cacheRoot, relativeFixtureRoot),
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
    if (monotonicNow() > buildDeadline) {
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
  _initialState: BuildInputState,
  computeState: () => BuildInputState,
  operations: FingerprintStableArtifactOperations<T>,
  maxAttempts: number = MAX_FINGERPRINT_STABILITY_ATTEMPTS,
): T => {
  // No artifact was built on this caller's behalf while it waited. In particular, a
  // changed fingerprint does not invalidate a stamped artifact another reader holds.
  let state = computeState();

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

    // This artifact was successfully stamped for its own fingerprint. Keep it reusable;
    // a later source change does not invalidate its contents or existing readers.
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
  return runWithBuildLock(LOCK_DIR, lockOwnership, () => {
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
            runProductionBuild(outDir, LOCK_DIR);
          });
        },
        stampArtifact: (outDir, fingerprint) => {
          writeFileSync(join(outDir, STAMP_FILE), `${JSON.stringify({ fingerprint }, null, 2)}\n`, 'utf8');
        },
        readArtifact: readProductionCssArtifact,
      },
    );
    return cachedBundle;
  });
};

/** Read an artifact while holding its build lock. */
export const readProductionCssArtifact = (outDir: string, fingerprint: string): ProductionCssBundle => {
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
    artifactStamp: readStampedFingerprint(join(outDir, STAMP_FILE)),
    ...readManifestMetadata(outDir),
  });
};

/**
 * Read back the fingerprint an artifact directory was stamped with. A stamp is only written after
 * a successful build, so `stamp === bundle.fingerprint` proves the CSS under assertion was emitted
 * by a build of a tree hashing to that fingerprint — not by a leftover or half-written artifact.
 * Safe after cache eviction: this metadata was read with the CSS while holding the build lock.
 */
export const readArtifactStamp = (bundle: ProductionCssBundle): string | null => {
  return bundle.artifactStamp;
};

/** Exposed so a test can assert the fixture never reads from the shared, emptyable build output. */
export const SHARED_BUILD_OUT_DIR = join(appRoot, 'public/assets/dist');

export const isInsideFixtureRoot = (path: string): boolean => {
  const rel = relative(FIXTURE_ROOT, path);
  return rel !== '' && !rel.startsWith('..');
};
