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
import { spawn, spawnSync } from 'node:child_process';
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  symlinkSync,
  utimesSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, join } from 'node:path';

import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

import type { ProductionCssBundle } from './productionCssBundle';
import {
  artifactFixtureRootForAppRoot,
  acquireDirectoryLock,
  type BuildInputState,
  type ArtifactEntry,
  buildInputCandidates,
  computeBuildInputState,
  fingerprintedBuildInputs,
  loadFingerprintStableArtifact,
  loadProductionCssBundle,
  manifestBuildSources,
  readArtifactStamp,
  readProductionCssArtifact,
  MAX_RETAINED_ARTIFACTS,
  LOCK_OWNER_FILE,
  type NamespaceEntry,
  registerAndPruneNamespaces,
  selectArtifactsToPrune,
  selectNamespacesToPrune,
  selectUnfingerprinted,
  releaseDirectoryLock,
  runWithBuildLock,
  runWithLockHeartbeat,
  tryAcquireDirectoryLock,
  uncoveredBuildInputs,
  unfingerprintedManifestSources,
  waitForProcessGroup,
  ProductionCssBuildTimeoutError,
  ProductionCssBuildTeardownError,
} from './productionCssBundle';

const ROLLUP_ENTRY_POINTS = ['js/admin/main.tsx', 'js/attachment-edit/main.tsx'] as const;

const expectProductionEntryPoints = (bundle: ProductionCssBundle): void => {
  expect(bundle.manifestEntryPoints).toEqual([...ROLLUP_ENTRY_POINTS].sort());
};

// Isolate builtin interception from Vitest and exercise the actual fixture and supervisor.
const fixtureProbePrelude = String.raw`
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import { dirname, join } from 'node:path';
import { stripTypeScriptTypes, syncBuiltinESMExports } from 'node:module';
const [sourcePath, root, scenario] = process.argv.slice(1);
const source = 'const __dirname = ' + JSON.stringify(dirname(sourcePath)) + ';\n' +
  stripTypeScriptTypes(fs.readFileSync(sourcePath, 'utf8')) + '\nexport { runProductionBuild };';
const fixture = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
`;

const runFixtureProbe = (root: string, scenario: string, body: string): void => {
  const result = spawnSync(process.execPath, [
    '--input-type=module', '-e', fixtureProbePrelude + body,
    join(__dirname, 'productionCssBundle.ts'), root, scenario,
  ], { timeout: 15_000, stdio: 'inherit' });
  expect(result.error).toBeUndefined();
  expect(result.status).toBe(0);
};

describe('production build status cleanup', () => {
  it.each(['live', 'empty', 'malformed', 'failed'])('retains the lock on EPERM with a %s listing', (listing) => {
    const root = mkdtempSync(join(tmpdir(), 'acx-eperm-probe-'));
    const lockDir = join(root, '.lock');
    const ownership = acquireDirectoryLock(lockDir);
    const denied = Object.assign(new Error('kill EPERM'), { code: 'EPERM' });
    // No real process is signalled; the listing is controlled independently of kill.
    const kill = vi.spyOn(process, 'kill').mockImplementation(() => { throw denied; });
    try {
      let caught: unknown;
      try {
        runWithBuildLock(lockDir, ownership, () => waitForProcessGroup(2147483647, {
          timeoutMs: 1,
          readExitCode: () => 0,
          processGroupStartToken: 'supervised',
          readProcessStartToken: () => 'supervised',
          listProcesses: () => {
            if (listing === 'failed') throw new Error('ps failed');
            if (listing === 'empty') return '';
            if (listing === 'malformed') return 'unreadable';
            return '123 2147483647 S\n';
          },
        }));
      } catch (error) { caught = error; }
      expect(caught).toBeInstanceOf(ProductionCssBuildTeardownError);
      expect((caught as Error).cause).toBe(denied);
      expect(existsSync(join(lockDir, '.build-in-progress'))).toBe(true);
      expect(tryAcquireDirectoryLock(lockDir)).toBeNull();
    } finally {
      kill.mockRestore();
      rmSync(root, { recursive: true, force: true });
    }
  });

  it.each(['EPERM', 'EIO'])('releases the lock on %s when a complete listing has no live group members', (code) => {
    const root = mkdtempSync(join(tmpdir(), 'acx-retired-probe-'));
    const lockDir = join(root, '.lock');
    const ownership = acquireDirectoryLock(lockDir);
    const kill = vi.spyOn(process, 'kill').mockImplementation(() => {
      throw Object.assign(new Error('probe failed'), { code });
    });
    try {
      expect(runWithBuildLock(lockDir, ownership, () => waitForProcessGroup(2147483647, {
        timeoutMs: 1,
        readExitCode: () => 0,
        processGroupStartToken: 'supervised',
        readProcessStartToken: () => 'supervised',
        listProcesses: () => '1 1 S\n123 2147483647 Z\n',
      }))).toBe(0);
      expect(existsSync(lockDir)).toBe(false);
    } finally {
      kill.mockRestore();
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('retains the teardown error and lock when signalling and status cleanup both fail', () => {
    const root = mkdtempSync(join(tmpdir(), 'acx-status-cleanup-test-'));
    try {
      runFixtureProbe(root, 'status-cleanup', String.raw`
const originalKill = process.kill;
const originalRemove = fs.rmSync;
const originalRead = fs.readFileSync;
const originalPath = process.env.PATH;
const lockDir = join(root, '.lock');
const ownership = fixture.tryAcquireDirectoryLock(lockDir);
let supervisor;
let statusRoot;
let signalDenied = false;
let cleanupFailed = false;
const groupHasExecutableMembers = (groupId) => {
  const members = execFileSync('ps', ['-A', '-o', 'pid=,pgid=,stat='], { encoding: 'utf8' });
  return members.trim().split('\n').some(line => {
    const [, pgid, state] = line.trim().split(/\s+/);
    return Number(pgid) === groupId && !state.startsWith('Z');
  });
};
const readyPath = join(root, 'build-ready');
// Keep the supervisor away from its post-exit self-teardown timer. Publish a result to
// the parent only after the real build member is alive, then inject the signal failure.
fs.writeFileSync(join(root, 'npm'), '#!' + process.execPath + '\n' +
  'require("node:fs").writeFileSync(' + JSON.stringify(readyPath) + ', "ready");\n' +
  'setInterval(() => {}, 1000);\n', { mode: 0o755 });
process.env.PATH = root + ':' + originalPath;
fs.readFileSync = (path, ...args) => {
  if (typeof path === 'string' && path.includes('/acx-style-build-status-') &&
      path.endsWith('/exit-code') && fs.existsSync(readyPath)) return '0';
  return originalRead(path, ...args);
};
process.kill = (pid, signal) => {
  if (pid < 0) supervisor = { pid: -pid };
  if (pid === -supervisor?.pid && signal !== 0) {
    signalDenied = true;
    throw Object.assign(new Error('signal denied'), { code: 'EPERM' });
  }
  return originalKill(pid, signal);
};
fs.rmSync = (path, ...args) => {
  if (typeof path === 'string' && path.includes('/acx-style-build-status-')) {
    assert.ok(signalDenied, 'cleanup must fail after teardown signalling');
    statusRoot = path;
    cleanupFailed = true;
    throw Object.assign(new Error('status cleanup failed'), { code: 'EIO' });
  }
  return originalRemove(path, ...args);
};
syncBuiltinESMExports();
try {
  let caught;
  try {
    fixture.runWithBuildLock(lockDir, ownership, () => fixture.runProductionBuild(join(root, 'out'), lockDir));
  } catch (error) { caught = error; }
  assert.ok(signalDenied && cleanupFailed, 'both failures must be exercised');
  assert.ok(groupHasExecutableMembers(supervisor.pid), 'the supervised group must still be alive');
  assert.ok(fs.existsSync(join(lockDir, '.build-in-progress')), 'uncertain teardown must retain the guard');
  assert.equal(fixture.tryAcquireDirectoryLock(lockDir, { now: () => Date.now() + 1000000 }), null,
    'a successor must not acquire while the previous group is alive');
  assert.ok(caught instanceof fixture.ProductionCssBuildTeardownError, 'cleanup must preserve the teardown error');
  assert.equal(caught.cause.code, 'EPERM');
} finally {
  process.kill = originalKill;
  fs.rmSync = originalRemove;
  fs.readFileSync = originalRead;
  process.env.PATH = originalPath;
  syncBuiltinESMExports();
  if (supervisor?.pid) {
    try { originalKill(-supervisor.pid, 'SIGKILL'); } catch {}
    const deadline = performance.now() + 5000;
    for (;;) {
      // macOS can report EPERM for the retired group. Independently confirm that
      // no executable members remain instead of requiring kill(0) to yield ESRCH.
      if (!groupHasExecutableMembers(supervisor.pid)) break;
      assert.ok(performance.now() < deadline, 'worker must reap the supervisor');
      await new Promise(resolve => setTimeout(resolve, 20));
    }
  }
  if (statusRoot) originalRemove(statusRoot, { recursive: true, force: true });
}
`);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});

describe('atomic initial lock claim', () => {
  it.each(['mkdir', 'temporary-owner', 'published-owner'])(
    'recovers when the creator is killed after %s', (scenario) => {
      const root = mkdtempSync(join(tmpdir(), 'acx-initial-claim-test-'));
      try {
        runFixtureProbe(root, scenario, String.raw`
const { spawn } = await import('node:child_process');
const lockDir = join(root, '.gc-lock');
const crashDuringPublication = () => {
for (const method of ['mkdirSync', 'writeFileSync', 'renameSync']) {
  const original = fs[method];
  fs[method] = (...args) => {
    const result = original(...args);
    if ((scenario === 'mkdir' && method === 'mkdirSync' && args[0] === lockDir) ||
        (scenario === 'temporary-owner' && method === 'writeFileSync' && String(args[0]).includes('/.owner-')) ||
        (scenario === 'published-owner' && method === 'renameSync' && args[1] === lockDir + '/owner.json')) {
      process.kill(process.pid, 'SIGKILL');
    }
    return result;
  };
}
syncBuiltinESMExports();
fixture.tryAcquireDirectoryLock(lockDir);
process.exit(24);
};
const childSource = 'import fs from "node:fs"; import { syncBuiltinESMExports } from "node:module";\n' +
  'const fixture = await import(' + JSON.stringify('data:text/javascript;base64,' + Buffer.from(source).toString('base64')) + ');\n' +
  'const lockDir = ' + JSON.stringify(lockDir) + '; const scenario = ' + JSON.stringify(scenario) + ';\n' +
  '(' + crashDuringPublication.toString() + ')();';
const child = spawn(process.execPath, ['--input-type=module', '-e', childSource], { stdio: 'inherit' });
const outcome = await new Promise((resolve, reject) => {
  child.once('error', reject);
  child.once('exit', (code, signal) => resolve({ code, signal }));
});
assert.equal(outcome.signal, 'SIGKILL', 'creator must die inside initial publication');
assert.equal(fixture.tryAcquireDirectoryLock(lockDir), null, 'fresh claims stay fenced');
let successor;
for (let attempt = 0; attempt < 4 && !successor; attempt++) {
  successor = fixture.tryAcquireDirectoryLock(lockDir, { now: () => Date.now() + 1000000 });
}
assert.ok(successor, 'a killed creator must not permanently strand the shared GC lock');
assert.equal(fixture.releaseDirectoryLock(lockDir, successor), true);
assert.throws(() => fs.lstatSync(lockDir + '.creating'), { code: 'ENOENT' });
`);
      } finally {
        rmSync(root, { recursive: true, force: true });
      }
    },
  );
});

describe('restricted host process metadata', () => {
  it.skipIf(process.platform !== 'linux').each(['matching-group', 'unknown-group'])(
    'retains the lock when unreadable metadata belongs to a %s', (scenario) => {
      const root = mkdtempSync(join(tmpdir(), 'acx-target-proc-test-'));
      try {
        runFixtureProbe(root, scenario, String.raw`
const lockDir = join(root, '.lock');
const owner = fixture.tryAcquireDirectoryLock(lockDir);
const read = fs.readFileSync;
const list = fs.readdirSync;
fs.readdirSync = (path, ...args) => path === '/proc' ? ['4321'] : list(path, ...args);
fs.readFileSync = (path, ...args) => {
  if (path === '/proc/4321/stat' || (scenario === 'unknown-group' && path === '/proc/4321/status')) {
    throw Object.assign(new Error('target metadata denied'), { code: 'EACCES' });
  }
  if (path === '/proc/4321/status') return 'NSpgid:\t4321\n';
  return read(path, ...args);
};
const kill = process.kill;
process.kill = (pid, signal) => pid === -4321 ? true : kill(pid, signal);
syncBuiltinESMExports();
let now = 0;
assert.throws(() => fixture.runWithBuildLock(lockDir, owner, () => fixture.waitForProcessGroup(4321, {
  timeoutMs: 1, terminationGraceMs: 1, killConfirmationMs: 1,
  now: () => now, sleep: (milliseconds) => { now += milliseconds; },
  readExitCode: () => 0, readProcessStartToken: () => 'leader', processGroupStartToken: 'leader',
})), fixture.ProductionCssBuildTeardownError);
assert.ok(fs.existsSync(join(lockDir, '.build-in-progress')));
assert.equal(fixture.tryAcquireDirectoryLock(lockDir), null);
`);
      } finally {
        rmSync(root, { recursive: true, force: true });
      }
    },
  );

  it.skipIf(process.platform !== 'linux').each(['stat-denied', 'all-metadata-denied'])(
    'reaps a successful build despite an unrelated process with %s', (scenario) => {
      const root = mkdtempSync(join(tmpdir(), 'acx-restricted-proc-test-'));
      try {
        runFixtureProbe(root, scenario, String.raw`
const lockDir = join(root, '.lock');
const owner = fixture.tryAcquireDirectoryLock(lockDir);
fs.writeFileSync(join(root, 'npm'), '#!' + process.execPath + '\nprocess.exit(0);', { mode: 0o755 });
process.env.PATH = root + ':' + process.env.PATH;
const read = fs.readFileSync;
const list = fs.readdirSync;
let deniedReads = 0;
fs.readdirSync = (path, ...args) => path === '/proc' ? ['2147483600', ...list(path, ...args)] : list(path, ...args);
fs.readFileSync = (path, ...args) => {
  if (path === '/proc/2147483600/stat' ||
      (scenario === 'all-metadata-denied' && path === '/proc/2147483600/status')) {
    deniedReads++;
    throw Object.assign(new Error('unrelated process is private'), { code: 'EACCES' });
  }
  if (path === '/proc/2147483600/status') return 'NSpgid:\t2147483600\n';
  return read(path, ...args);
};
syncBuiltinESMExports();
fixture.runWithBuildLock(lockDir, owner, () => fixture.runProductionBuild(join(root, 'out'), lockDir));
assert.ok(deniedReads > 0, 'restricted metadata must be exercised');
assert.equal(fs.existsSync(lockDir), false, 'confirmed teardown must release its lock');
const successor = fixture.tryAcquireDirectoryLock(lockDir);
assert.ok(successor);
assert.equal(fixture.releaseDirectoryLock(lockDir, successor), true);
`);
      } finally {
        rmSync(root, { recursive: true, force: true });
      }
    },
    15_000,
  );
});

describe('supervisor lifetime and owner death', () => {
  it.each(['owner-dies-running', 'owner-dies-finished', 'deadline'])(
    'tears down the whole group and recovers the lock after %s',
    (scenario) => {
      const root = mkdtempSync(join(tmpdir(), 'acx-supervisor-lifetime-test-'));
      try {
        runFixtureProbe(root, scenario, String.raw`
const { spawn } = await import('node:child_process');
const lockDir = join(root, '.lock');
const readyPath = join(root, 'build-ready');
fs.writeFileSync(join(root, 'npm'), '#!' + process.execPath + '\n' +
  'require("node:fs").writeFileSync(' + JSON.stringify(readyPath) + ', String(process.pid));\n' +
  (scenario === 'owner-dies-finished' ? '' : 'process.on("SIGTERM", () => {}); setInterval(() => {}, 1000);'),
  { mode: 0o755 });
const ownerSource = source
  .replace('const BUILD_TERMINATION_GRACE_MS = 5_000;', 'const BUILD_TERMINATION_GRACE_MS = 100;')
  .replace('timeoutMs: BUILD_TIMEOUT_MS,', 'timeoutMs: 20000,')
  .replace('const BUILD_TIMEOUT_MS = STALE_LOCK_MS - 30_000;',
    'const BUILD_TIMEOUT_MS = ' + (scenario === 'deadline' ? 800 : 10000) + ';');
const owner = spawn(process.execPath, ['--input-type=module', '-e',
  'import fs from "node:fs"; import { syncBuiltinESMExports } from "node:module";\n' +
  'const fixture = await import(' + JSON.stringify('data:text/javascript;base64,' + Buffer.from(ownerSource).toString('base64')) + ');\n' +
  // Keep the owner waiting even after a fast npm exit so its death exercises the result state.
  'const read = fs.readFileSync; fs.readFileSync = (path, ...args) => typeof path === "string" && path.endsWith("/exit-code") ? "" : read(path, ...args); syncBuiltinESMExports();\n' +
  'const lock = ' + JSON.stringify(lockDir) + '; const ownership = fixture.tryAcquireDirectoryLock(lock);\n' +
  'try { fixture.runWithBuildLock(lock, ownership, () => fixture.runProductionBuild(' + JSON.stringify(join(root, 'out')) + ', lock)); } catch {}',
], { env: { ...process.env, PATH: root + ':' + process.env.PATH }, stdio: 'inherit' });
let pgid;
const exited = new Promise(resolve => owner.once('exit', resolve));
const waitUntil = async (predicate) => {
  const deadline = performance.now() + 5000;
  while (!predicate()) {
    assert.ok(performance.now() < deadline, 'supervisor did not complete bounded teardown');
    await new Promise(resolve => setTimeout(resolve, 20));
  }
};
const running = (pid) => {
  try {
    if (process.platform === 'linux') {
      const stat = fs.readFileSync('/proc/' + pid + '/stat', 'utf8');
      return stat.slice(stat.lastIndexOf(')') + 2).split(' ')[0] !== 'Z';
    }
    process.kill(pid, 0); return true;
  } catch (error) { if (['ENOENT', 'ESRCH'].includes(error.code)) return false; throw error; }
};
try {
  await waitUntil(() => fs.existsSync(readyPath));
  const guard = JSON.parse(fs.readFileSync(join(lockDir, '.build-in-progress'), 'utf8'));
  pgid = guard.teardown_uncertain?.pgid;
  // On the pre-fix implementation the guard has no group metadata; locate the supervisor
  // through /proc so the mutation probe can still clean up its orphan in finally.
  if (!pgid && process.platform === 'linux') {
    pgid = Number(fs.readFileSync('/proc/' + owner.pid + '/task/' + owner.pid + '/children', 'utf8').trim().split(' ')[0]);
  }
  const buildPid = Number(fs.readFileSync(readyPath, 'utf8'));
  if (scenario === 'owner-dies-finished') await waitUntil(() => !running(buildPid));
  assert.ok(running(pgid), 'supervisor must still hold the group identity');
  assert.equal(fixture.tryAcquireDirectoryLock(lockDir, { now: () => Date.now() + 1000000 }), null);
  if (scenario !== 'deadline') owner.kill('SIGKILL');
  await waitUntil(() => !running(pgid) && !running(buildPid));
  await exited;
  // SIGKILL can leave a zombie briefly until the OS reaps it. Recovery deliberately waits
  // for ESRCH for the whole group instead of treating a dead leader as sufficient evidence.
  let recovered;
  await waitUntil(() => (recovered = fixture.tryAcquireDirectoryLock(lockDir, {
    now: () => Date.now() + 1000000,
  })) !== null);
  assert.ok(recovered, 'confirmed teardown must permit stale lock recovery');
  fixture.releaseDirectoryLock(lockDir, recovered);
} finally {
  owner.kill('SIGKILL');
  if (pgid) { try { process.kill(-pgid, 'SIGKILL'); } catch {} }
  await exited;
}
`);
      } finally {
        rmSync(root, { recursive: true, force: true });
      }
    },
  );
});

describe('production status publication races', () => {
  it.each(['publication-race', '', ' ', '0x0', '0\n', '1.5', '256'])(
    'does not accept partial or malformed status %j as build success',
    (scenario) => {
      const root = mkdtempSync(join(tmpdir(), 'acx-status-race-test-'));
      try {
        writeFileSync(join(root, 'npm'), '#!/bin/sh\nexit 42\n', { mode: 0o755 });
        // Force the real supervisor to pause between file creation and writing status 42.
        writeFileSync(join(root, 'pause-status.cjs'), String.raw`
const fs = require('node:fs');
const write = fs.writeFileSync;
fs.writeFileSync = (path, ...args) => {
  if (typeof path === 'string' && /\/exit-code(?:\.tmp)?$/.test(path)) {
    const fd = fs.openSync(path, 'w');
    fs.closeSync(fd);
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 200);
  }
  return write(path, ...args);
};
`);
        runFixtureProbe(root, scenario, String.raw`
process.env.PATH = root + ':' + process.env.PATH;
process.env.NODE_OPTIONS = '--require=' + join(root, 'pause-status.cjs');
const read = fs.readFileSync;
let statusReads = 0;
let sawEmptyPublication = false;
fs.readFileSync = (path, ...args) => {
  const value = read(path, ...args);
  if (typeof path === 'string' && path.endsWith('/exit-code')) {
    statusReads++;
    sawEmptyPublication ||= value === '';
    if (scenario !== 'publication-race' && statusReads === 1) return scenario;
  }
  return value;
};
syncBuiltinESMExports();
assert.throws(() => fixture.runProductionBuild(join(root, 'out')), /exited with status 42/);
assert.equal(sawEmptyPublication, false, 'the public status file must never be empty');
if (scenario !== 'publication-race') assert.ok(statusReads >= 2, 'invalid status must be rejected');
`);
      } finally {
        rmSync(root, { recursive: true, force: true });
      }
    },
    15_000,
  );
});

describe('namespace registration during sibling pruning', () => {
  it.each(['live', 'locked', 'current', 'vanished-stamp', 'vanished-root', 'io-error'])(
    'handles %s activity metadata',
    (scenario) => {
      const root = mkdtempSync(join(tmpdir(), 'acx-namespace-race-test-'));
      try {
        runFixtureProbe(root, scenario, String.raw`
const cache = join(root, 'cache');
const owner = join(root, 'owner');
const sibling = join(cache, 'sibling');
const current = scenario === 'current' ? sibling : join(cache, 'current');
const stamp = join(sibling, 'artifact', 'build-stamp.json');
fs.mkdirSync(owner);
fs.mkdirSync(dirname(stamp), { recursive: true });
fs.writeFileSync(stamp, '{}');
if (scenario === 'live') {
  fs.writeFileSync(join(sibling, 'namespace-owner.json'), JSON.stringify({ appRoot: owner }));
}
if (scenario === 'locked') fs.mkdirSync(join(sibling, '.lock'));
const stat = fs.statSync;
let intercepted = false;
fs.statSync = (path, ...args) => {
  if (['live', 'locked', 'current'].includes(scenario) && path === sibling) {
    throw new Error('Protected namespace activity must not be inspected');
  }
  if (scenario === 'vanished-root' && path === sibling) {
    intercepted = true;
    fs.rmSync(sibling, { recursive: true });
  }
  if (path === stamp) {
    intercepted = true;
    if (scenario === 'io-error') throw Object.assign(new Error('Injected I/O failure'), { code: 'EIO' });
    // Prune after enumeration (and after existsSync in the original collector), before stat.
    fs.rmSync(dirname(stamp), { recursive: true });
  }
  return stat(path, ...args);
};
syncBuiltinESMExports();
const register = () => fixture.registerAndPruneNamespaces(cache, current, owner);
if (scenario === 'io-error') assert.throws(register, /Injected I\/O failure/);
else register();
if (['vanished-stamp', 'vanished-root', 'io-error'].includes(scenario)) assert.ok(intercepted);
else assert.ok(fs.existsSync(stamp), 'protected sibling artifacts must be untouched');
assert.equal(fs.existsSync(join(cache, '.gc-lock')), false);
`);
      } finally {
        rmSync(root, { recursive: true, force: true });
      }
    },
  );
});

describe('production bundle metadata snapshot', () => {
  it('asserts production entry points after the artifact is evicted', () => {
    const outDir = mkdtempSync(join(tmpdir(), 'acx-entry-snapshot-'));
    try {
      mkdirSync(join(outDir, 'assets'));
      mkdirSync(join(outDir, '.vite'));
      writeFileSync(join(outDir, 'assets/admin.css'), 'body { color: red; }');
      writeFileSync(join(outDir, '.vite/manifest.json'), JSON.stringify({
        [ROLLUP_ENTRY_POINTS[1]]: { isEntry: true, src: ROLLUP_ENTRY_POINTS[1] },
        shared: { src: 'js/shared.ts' },
        dynamic: { isEntry: false, isDynamicEntry: true },
        [ROLLUP_ENTRY_POINTS[0]]: { isEntry: true, src: ROLLUP_ENTRY_POINTS[0] },
      }));
      const bundle = readProductionCssArtifact(outDir, 'snapshot');
      rmSync(outDir, { recursive: true });

      expectProductionEntryPoints(bundle);
      expect(Object.isFrozen(bundle.manifestEntryPoints)).toBe(true);
    } finally {
      rmSync(outDir, { recursive: true, force: true });
    }
  });
});

describe('fingerprint stability while building [FIXWAV-M-03]', () => {
  it.each(['waiting', 'reading'])('preserves existing readers when inputs change during %s [D5-R11-01]', (timing) => {
    const root = mkdtempSync(join(tmpdir(), 'acx-reader-snapshot-'));
    const state = (fingerprint: string): BuildInputState => ({ fingerprint, generation: fingerprint });
    const create = (fingerprint: string): string => {
      const outDir = join(root, fingerprint);
      mkdirSync(join(outDir, 'assets'), { recursive: true });
      mkdirSync(join(outDir, '.vite'), { recursive: true });
      writeFileSync(join(outDir, 'assets/admin.css'), fingerprint);
      writeFileSync(join(outDir, '.vite/manifest.json'), JSON.stringify({ main: { src: 'js/admin/main.tsx' } }));
      writeFileSync(join(outDir, 'build-stamp.json'), JSON.stringify({ fingerprint }));
      return outDir;
    };
    try {
      const oldDir = create('A');
      const reader = readProductionCssArtifact(oldDir, 'A');
      let current = timing === 'waiting' ? 'B' : 'A';
      const result = loadFingerprintStableArtifact(state('A'), () => state(current), {
        artifactDirForFingerprint: (fingerprint) => join(root, fingerprint),
        prepareArtifact: () => undefined,
        readStampedFingerprint: (outDir) => existsSync(join(outDir, 'build-stamp.json'))
          ? JSON.parse(readFileSync(join(outDir, 'build-stamp.json'), 'utf8')).fingerprint as string : null,
        touchArtifact: () => undefined,
        discardArtifact: (outDir) => rmSync(outDir, { recursive: true, force: true }),
        buildArtifact: (outDir) => { create(basename(outDir)); },
        stampArtifact: () => undefined,
        readArtifact: (outDir, fingerprint) => {
          const bundle = readProductionCssArtifact(outDir, fingerprint);
          current = 'B';
          return bundle;
        },
      });
      expect(result.fingerprint).toBe('B');
      expect(existsSync(oldDir)).toBe(true);
      // Even eventual TTL/cap eviction cannot invalidate the first reader's metadata.
      rmSync(oldDir, { recursive: true });
      expect(readArtifactStamp(reader)).toBe('A');
      expect(manifestBuildSources(reader)).toEqual(['js/admin/main.tsx']);
      expect(reader.css).toBe('A');
    } finally { rmSync(root, { recursive: true, force: true }); }
  });

  it('detects an A-B-A rewrite from real temporary inputs', () => {
    const fixtureRoot = mkdtempSync(join(tmpdir(), 'acx-style-input-generation-test-'));
    const sourcePath = join(fixtureRoot, 'js', 'source.scss');
    mkdirSync(dirname(sourcePath), { recursive: true });
    writeFileSync(sourcePath, 'A', 'utf8');

    try {
      const firstA = computeBuildInputState(fixtureRoot);
      writeFileSync(sourcePath, 'B', 'utf8');
      const stateB = computeBuildInputState(fixtureRoot);
      writeFileSync(sourcePath, 'A', 'utf8');
      const secondA = computeBuildInputState(fixtureRoot);

      expect(stateB.fingerprint).not.toBe(firstA.fingerprint);
      expect(secondA.fingerprint).toBe(firstA.fingerprint);
      expect(secondA.generation).not.toBe(firstA.generation);
    } finally {
      rmSync(fixtureRoot, { recursive: true, force: true });
    }
  });

  it('discards and retries an artifact when a source changes during the build', () => {
    const fixtureRoot = mkdtempSync(join(tmpdir(), 'acx-style-bundle-race-test-'));
    const sourcePath = join(fixtureRoot, 'source.scss');
    const discardedBuiltArtifacts: string[] = [];
    const stampedBuilds: number[] = [];
    let buildCount = 0;
    let generation = 0;

    writeFileSync(sourcePath, 'old-source', 'utf8');
    const computeState = (): BuildInputState => ({
      fingerprint: readFileSync(sourcePath, 'utf8'),
      generation: String(generation),
    });
    const initialState = computeState();

    try {
      const artifact = loadFingerprintStableArtifact(
        initialState,
        computeState,
        {
          artifactDirForFingerprint: (fingerprint) => join(fixtureRoot, fingerprint),
          prepareArtifact: () => undefined,
          readStampedFingerprint: (outDir) => {
            const stampPath = join(outDir, 'stamp');
            return existsSync(stampPath) ? readFileSync(stampPath, 'utf8') : null;
          },
          touchArtifact: () => undefined,
          discardArtifact: (outDir) => {
            if (existsSync(join(outDir, 'built-source'))) {
              discardedBuiltArtifacts.push(outDir);
            }
            rmSync(outDir, { recursive: true, force: true });
          },
          buildArtifact: (outDir) => {
            mkdirSync(outDir, { recursive: true });
            writeFileSync(join(outDir, 'built-source'), readFileSync(sourcePath, 'utf8'), 'utf8');
            buildCount += 1;
            if (buildCount === 1) {
              // Model an editor or generator replacing an input while Vite is running.
              writeFileSync(sourcePath, 'new-source', 'utf8');
              generation += 1;
            }
          },
          stampArtifact: (outDir, fingerprint) => {
            stampedBuilds.push(buildCount);
            writeFileSync(join(outDir, 'stamp'), fingerprint, 'utf8');
          },
          readArtifact: (outDir, fingerprint) => ({
            builtSource: readFileSync(join(outDir, 'built-source'), 'utf8'),
            fingerprint,
            outDir,
          }),
        },
      );

      expect(buildCount).toBe(2);
      expect(stampedBuilds).toEqual([2]);
      expect(discardedBuiltArtifacts).toContain(join(fixtureRoot, 'old-source'));
      expect(existsSync(join(fixtureRoot, 'old-source'))).toBe(false);
      expect(artifact).toEqual({
        builtSource: 'new-source',
        fingerprint: 'new-source',
        outDir: join(fixtureRoot, 'new-source'),
      });
      expect(readFileSync(join(artifact.outDir, 'stamp'), 'utf8')).toBe('new-source');
    } finally {
      rmSync(fixtureRoot, { recursive: true, force: true });
    }
  });

  it('rejects an A-to-B-to-A change generation even when the content hash returns to A', () => {
    let generation = 1;
    let buildCount = 0;
    const stampedBuilds: number[] = [];
    const discardedBuilds: number[] = [];
    const computeState = (): BuildInputState => ({ fingerprint: 'A', generation: String(generation) });

    const artifact = loadFingerprintStableArtifact(
      computeState(),
      computeState,
      {
        artifactDirForFingerprint: (fingerprint) => fingerprint,
        prepareArtifact: () => undefined,
        readStampedFingerprint: () => null,
        touchArtifact: () => undefined,
        discardArtifact: () => discardedBuilds.push(buildCount),
        buildArtifact: () => {
          buildCount += 1;
          if (buildCount === 1) {
            // The contents are A again when observed, but the metadata generation advanced.
            generation += 1;
          }
        },
        stampArtifact: () => stampedBuilds.push(buildCount),
        readArtifact: () => ({ buildCount }),
      },
    );

    expect(artifact).toEqual({ buildCount: 2 });
    expect(buildCount).toBe(2);
    expect(stampedBuilds).toEqual([2]);
    expect(discardedBuilds).toEqual([0, 1, 1]);
  });

  it('bounds continuously mutating builds and never stamps a discarded attempt', () => {
    let generation = 1;
    let buildCount = 0;
    let discardCount = 0;
    const stampCalls: string[] = [];
    const maxAttempts = 2;
    const computeState = (): BuildInputState => ({ fingerprint: 'A', generation: String(generation) });

    expect(() =>
      loadFingerprintStableArtifact(
        computeState(),
        computeState,
        {
          artifactDirForFingerprint: (fingerprint) => fingerprint,
          prepareArtifact: () => undefined,
          readStampedFingerprint: () => null,
          touchArtifact: () => undefined,
          discardArtifact: () => {
            discardCount += 1;
          },
          buildArtifact: () => {
            buildCount += 1;
            generation += 1;
          },
          stampArtifact: (_outDir, fingerprint) => stampCalls.push(fingerprint),
          readArtifact: () => 'unreachable',
        },
        maxAttempts,
      ),
    ).toThrow(`changed during ${maxAttempts} consecutive attempts`);
    expect(buildCount).toBe(maxAttempts);
    expect(discardCount).toBe(maxAttempts * 2);
    expect(stampCalls).toEqual([]);
  });
});

describe('fenced directory lock', () => {
  it.skipIf(process.platform !== 'linux').each([
    'EACCES', 'EPERM', 'EIO', 'ENOENT', 'malformed', 'signal-EPERM', 'different-token', 'ESRCH',
  ])('retains owners whose identity inspection is uncertain: %s [D5-R9-01]', (scenario) => {
    const root = mkdtempSync(join(tmpdir(), 'acx-lock-inspection-'));
    try {
      runFixtureProbe(root, scenario, String.raw`
const lockDir = join(root, '.gc-lock');
const ownerPath = join(lockDir, fixture.LOCK_OWNER_FILE);
const owner = fixture.tryAcquireDirectoryLock(lockDir);
// The parent is a real live process, distinct from this contender's identity probe.
const statPath = '/proc/' + process.ppid + '/stat';
const fields = fs.readFileSync(statPath, 'utf8').split(') ').pop().trim().split(/\s+/);
owner.pid = process.ppid;
owner.startToken = 'v1:linux:' + fields[19];
fs.writeFileSync(ownerPath, JSON.stringify(owner));
fs.utimesSync(ownerPath, new Date(0), new Date(0));
const read = fs.readFileSync;
fs.readFileSync = (path, ...args) => {
  if (path !== statPath) return read(path, ...args);
  if (scenario === 'different-token') {
    return read(path, ...args).replace(/\) (.*)/, (_, tail) => {
      const fields = tail.split(' ');
      fields[19] = String(BigInt(fields[19]) + 1n);
      return ') ' + fields.join(' ');
    });
  }
  if (scenario === 'malformed') return 'unparseable stat';
  throw Object.assign(new Error('Injected inspection failure'), { code: scenario });
};
if (scenario === 'ESRCH' || scenario === 'signal-EPERM') {
  const kill = process.kill;
  process.kill = (pid, signal) => {
    if (pid === owner.pid) {
      throw Object.assign(new Error('Injected signal probe failure'), {
        code: scenario === 'ESRCH' ? 'ESRCH' : 'EPERM',
      });
    }
    return kill(pid, signal);
  };
}
syncBuiltinESMExports();
const successor = fixture.tryAcquireDirectoryLock(lockDir, { staleAfterMs: 1 });
if (scenario === 'different-token' || scenario === 'ESRCH') {
  assert.notEqual(successor, null, 'positive evidence of death permits recovery');
} else {
  assert.equal(successor, null, 'inspection failure must not steal a live lease');
  assert.deepEqual(JSON.parse(read(ownerPath, 'utf8')), owner);
}
`);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('retries when the incumbent vanishes before recovery claim creation [D5-R9-02]', () => {
    const root = mkdtempSync(join(tmpdir(), 'acx-lock-vanished-'));
    try {
      runFixtureProbe(root, '', String.raw`
const lockDir = join(root, '.gc-lock');
fixture.tryAcquireDirectoryLock(lockDir);
fs.utimesSync(join(lockDir, fixture.LOCK_OWNER_FILE), new Date(0), new Date(0));
let intercepted = false;
// Cover both the old mkdir claim and the atomic metadata claim used by the fix.
for (const method of ['mkdirSync', 'symlinkSync']) {
  const original = fs[method];
  fs[method] = (...args) => {
    const path = args[method === 'symlinkSync' ? 1 : 0];
    if (path === join(lockDir, '.reaping') && !intercepted) {
      intercepted = true;
      fs.rmSync(lockDir, { recursive: true });
    }
    return original(...args);
  };
}
syncBuiltinESMExports();
assert.equal(fixture.tryAcquireDirectoryLock(lockDir, {
  staleAfterMs: 1, isProcessAlive: () => false,
}), null);
assert.equal(intercepted, true);
assert.notEqual(fixture.tryAcquireDirectoryLock(lockDir), null);
`);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('recovers a claim abandoned immediately after creation by a dying reaper [D5-R9-03]', () => {
    const root = mkdtempSync(join(tmpdir(), 'acx-lock-abandoned-'));
    try {
      const child = spawnSync(process.execPath, [
        '--input-type=module', '-e', fixtureProbePrelude + String.raw`
const lockDir = join(root, '.gc-lock');
fixture.tryAcquireDirectoryLock(lockDir);
fs.utimesSync(join(lockDir, fixture.LOCK_OWNER_FILE), new Date(0), new Date(0));
for (const method of ['mkdirSync', 'symlinkSync']) {
  const original = fs[method];
  fs[method] = (...args) => {
    const result = original(...args);
    if (args[method === 'symlinkSync' ? 1 : 0] === join(lockDir, '.reaping')) process.exit(23);
    return result;
  };
}
syncBuiltinESMExports();
fixture.tryAcquireDirectoryLock(lockDir, { staleAfterMs: 1, isProcessAlive: () => false });
throw new Error('The reaper never acquired its claim');
`, join(__dirname, 'productionCssBundle.ts'), root, '',
      ], { timeout: 10_000, stdio: 'inherit' });
      expect(child.error).toBeUndefined();
      expect(child.status).toBe(23);
      const lockDir = join(root, '.gc-lock');
      // A young claim remains fenced even when its owner is dead.
      expect(tryAcquireDirectoryLock(lockDir, { staleAfterMs: 60_000 })).toBeNull();
      const options = { staleAfterMs: 1, now: () => Date.now() + 60_000 };
      // The first attempt clears the abandoned claim; the bounded caller retries acquisition.
      let successor = tryAcquireDirectoryLock(lockDir, options);
      if (successor === null) successor = tryAcquireDirectoryLock(lockDir, options);
      expect(successor).not.toBeNull();
      if (successor !== null) expect(releaseDirectoryLock(lockDir, successor)).toBe(true);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it.each(['live', 'secondary', 'replacement'])(
    'preserves recovery ownership under %s contention [D5-R9-03]', (scenario) => {
      const root = mkdtempSync(join(tmpdir(), 'acx-lock-reaper-contention-'));
      try {
        runFixtureProbe(root, scenario, String.raw`
const lockDir = join(root, '.gc-lock');
const owner = fixture.tryAcquireDirectoryLock(lockDir);
const claimPath = join(lockDir, '.reaping');
const dead = { ...owner, nonce: 'abandoned', createdAt: 0 };
const live = { ...owner, nonce: 'replacement', createdAt: 0 };
fs.utimesSync(join(lockDir, fixture.LOCK_OWNER_FILE), new Date(0), new Date(0));
const options = {
  staleAfterMs: 1,
  isProcessAlive: () => scenario === 'live' && ++probes > 1,
};
let probes = 0;
fs.symlinkSync(JSON.stringify(dead), claimPath);
if (scenario === 'secondary') {
  fs.symlinkSync(JSON.stringify({ ...dead, nonce: 'secondary' }), join(lockDir, '.reaping-abandoned'));
}
if (scenario === 'replacement') {
  const symlink = fs.symlinkSync;
  fs.symlinkSync = (target, path, ...args) => {
    const result = symlink(target, path, ...args);
    if (path === join(lockDir, '.reaping-abandoned')) {
      // Another reaper replaced the primary after this contender inspected it.
      fs.rmSync(claimPath);
      symlink(JSON.stringify(live), claimPath);
    }
    return result;
  };
  syncBuiltinESMExports();
}
assert.equal(fixture.tryAcquireDirectoryLock(lockDir, options), null);
if (scenario === 'live' || scenario === 'replacement') {
  assert.deepEqual(JSON.parse(fs.readlinkSync(claimPath)), scenario === 'live' ? dead : live);
} else {
  assert.equal(fixture.tryAcquireDirectoryLock(lockDir, options), null);
  assert.notEqual(fixture.tryAcquireDirectoryLock(lockDir, options), null);
}
`);
      } finally {
        rmSync(root, { recursive: true, force: true });
      }
    },
  );

  it('removes its exclusive lock directory when owner publication fails', () => {
    const fixtureRoot = mkdtempSync(join(tmpdir(), 'acx-style-lock-publication-test-'));
    const lockDir = join(fixtureRoot, '.lock');

    try {
      expect(
        tryAcquireDirectoryLock(lockDir, {
          publishOwnership: () => null,
        }),
      ).toBeNull();
      expect(existsSync(lockDir)).toBe(false);
    } finally {
      rmSync(fixtureRoot, { recursive: true, force: true });
    }
  });

  it('does not steal an expired-looking lease from a live holder process', () => {
    const fixtureRoot = mkdtempSync(join(tmpdir(), 'acx-style-lock-test-'));
    const lockDir = join(fixtureRoot, '.lock');
    const holder = tryAcquireDirectoryLock(lockDir);
    expect(holder).not.toBeNull();
    expect(holder!.startToken.startsWith(`v1:${process.platform}:`)).toBe(true);

    try {
      const ownerPath = join(lockDir, LOCK_OWNER_FILE);
      utimesSync(ownerPath, new Date(0), new Date(0));

      expect(tryAcquireDirectoryLock(lockDir, { staleAfterMs: 10 })).toBeNull();
      expect(JSON.parse(readFileSync(ownerPath, 'utf8'))).toEqual(holder);
      expect(
        releaseDirectoryLock(lockDir, { pid: process.pid, startToken: 'impostor', nonce: 'impostor' }),
      ).toBe(false);
      expect(existsSync(lockDir)).toBe(true);
    } finally {
      if (holder !== null) releaseDirectoryLock(lockDir, holder);
      rmSync(fixtureRoot, { recursive: true, force: true });
    }
  });

  it('fails closed on stale malformed metadata', () => {
    const fixtureRoot = mkdtempSync(join(tmpdir(), 'acx-style-lock-malformed-test-'));
    const lockDir = join(fixtureRoot, '.lock');
    mkdirSync(lockDir);
    const ownerPath = join(lockDir, LOCK_OWNER_FILE);
    writeFileSync(ownerPath, '{not-json', 'utf8');
    utimesSync(ownerPath, new Date(0), new Date(0));
    utimesSync(lockDir, new Date(0), new Date(0));

    try {
      expect(
        tryAcquireDirectoryLock(lockDir, {
          now: () => 10_000,
          staleAfterMs: 1,
          isProcessAlive: () => false,
        }),
      ).toBeNull();
      expect(readFileSync(ownerPath, 'utf8')).toBe('{not-json');
    } finally {
      rmSync(fixtureRoot, { recursive: true, force: true });
    }
  });

  it('does not reap a live PID whose start token has malformed syntax', () => {
    const fixtureRoot = mkdtempSync(join(tmpdir(), 'acx-style-lock-token-test-'));
    const lockDir = join(fixtureRoot, '.lock');
    const ownerPath = join(lockDir, LOCK_OWNER_FILE);
    mkdirSync(lockDir);
    writeFileSync(
      ownerPath,
      `${JSON.stringify({ pid: process.pid, startToken: 'not-a-versioned-token', nonce: 'owner' })}\n`,
      'utf8',
    );
    utimesSync(ownerPath, new Date(0), new Date(0));

    try {
      expect(
        tryAcquireDirectoryLock(lockDir, {
          now: () => 10_000,
          staleAfterMs: 1,
        }),
      ).toBeNull();
      expect(JSON.parse(readFileSync(ownerPath, 'utf8'))).toEqual({
        pid: process.pid,
        startToken: 'not-a-versioned-token',
        nonce: 'owner',
      });
    } finally {
      rmSync(fixtureRoot, { recursive: true, force: true });
    }
  });

  it('waits for heartbeat readiness and observes lease progress by a bounded deadline', () => {
    const fixtureRoot = mkdtempSync(join(tmpdir(), 'acx-style-lock-heartbeat-test-'));
    const lockDir = join(fixtureRoot, '.lock');
    const ownership = tryAcquireDirectoryLock(lockDir);
    expect(ownership).not.toBeNull();

    try {
      const before = statMtime(join(lockDir, LOCK_OWNER_FILE));
      let observedHeartbeatMtime = before;
      runWithLockHeartbeat(
        lockDir,
        ownership!,
        () => {
          const observationDeadline = Date.now() + 10_000;
          while (observedHeartbeatMtime <= before && Date.now() < observationDeadline) {
            observedHeartbeatMtime = statMtime(join(lockDir, LOCK_OWNER_FILE));
            if (observedHeartbeatMtime <= before) {
              Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 100);
            }
          }
        },
      );
      const after = statMtime(join(lockDir, LOCK_OWNER_FILE));
      expect(observedHeartbeatMtime).toBeGreaterThan(before);
      expect(after).toBeGreaterThanOrEqual(observedHeartbeatMtime);
      expect(
        tryAcquireDirectoryLock(lockDir, {
          staleAfterMs: 60_000,
          now: () => after + 60_000,
          isProcessAlive: () => false,
        }),
      ).toBeNull();
      expect(existsSync(lockDir)).toBe(true);
    } finally {
      if (ownership !== null) releaseDirectoryLock(lockDir, ownership);
      rmSync(fixtureRoot, { recursive: true, force: true });
    }
  });

  it('times out before an unexpired lease can be reclaimed', () => {
    const fixtureRoot = mkdtempSync(join(tmpdir(), 'acx-style-lock-timeout-test-'));
    const lockDir = join(fixtureRoot, '.lock');
    const ownership = tryAcquireDirectoryLock(lockDir);
    expect(ownership).not.toBeNull();
    let now = 10_000;

    try {
      expect(() =>
        acquireDirectoryLock(lockDir, {
          now: () => (now += 1),
          timeoutMs: 0,
          staleAfterMs: 60_000,
          pollMs: 0,
          isProcessAlive: () => false,
        }),
      ).toThrow('Timed out after 0ms');
      expect(existsSync(lockDir)).toBe(true);
    } finally {
      if (ownership !== null) releaseDirectoryLock(lockDir, ownership);
      rmSync(fixtureRoot, { recursive: true, force: true });
    }
  });

  it('rechecks process identity after claiming stale recovery', () => {
    const fixtureRoot = mkdtempSync(join(tmpdir(), 'acx-style-lock-recheck-test-'));
    const lockDir = join(fixtureRoot, '.lock');
    const ownership = tryAcquireDirectoryLock(lockDir);
    expect(ownership).not.toBeNull();
    const old = new Date(0);
    utimesSync(join(lockDir, LOCK_OWNER_FILE), old, old);
    const livenessChecks: boolean[] = [];

    try {
      expect(
        tryAcquireDirectoryLock(lockDir, {
          now: () => 10_000,
          staleAfterMs: 1,
          isProcessAlive: () => {
            const alive = livenessChecks.length > 0;
            livenessChecks.push(alive);
            return alive;
          },
        }),
      ).toBeNull();
      expect(livenessChecks).toEqual([false, true]);
      expect(existsSync(lockDir)).toBe(true);
    } finally {
      if (ownership !== null) releaseDirectoryLock(lockDir, ownership);
      rmSync(fixtureRoot, { recursive: true, force: true });
    }
  });
});

const statMtime = (path: string): number => {
  return statSync(path).mtimeMs;
};

describe('production build deadline', () => {
  it.each([
    ['SIGTERM', false], ['SIGTERM', true], ['SIGKILL', false], ['SIGKILL', true],
  ] as const)('rechecks group liveness when the leader vanishes before %s (survives=%s) [D5-R11-02]', (signal, survives) => {
    let reads = 0;
    let alive = true;
    const signals: Array<NodeJS.Signals | 0> = [];
    const wait = () => waitForProcessGroup(2468, {
      timeoutMs: 100,
      terminationGraceMs: 0,
      readExitCode: () => 42,
      processGroupStartToken: 'leader',
      readProcessStartToken: () => {
        // groupState, TERM identity, grace liveness, KILL liveness, KILL identity.
        if (++reads >= (signal === 'SIGTERM' ? 2 : 5)) {
          alive = survives;
          return null;
        }
        return 'leader';
      },
      isProcessGroupAlive: () => alive,
      sendSignal: (_pid, sent) => { signals.push(sent); },
    });
    if (survives) expect(wait).toThrow(ProductionCssBuildTeardownError);
    else expect(wait()).toBe(42);
    expect(signals).toEqual(signal === 'SIGTERM' ? [] : ['SIGTERM']);
  });

  it('terminates and then kills the detached process group before reporting RES-13', () => {
    let now = 0;
    let alive = true;
    const signals: Array<[number, NodeJS.Signals | 0]> = [];

    expect(() =>
      waitForProcessGroup(4321, {
        timeoutMs: 20,
        terminationGraceMs: 5,
        now: () => now,
        sleep: (milliseconds) => {
          now += milliseconds;
        },
        readExitCode: () => null,
        processGroupStartToken: 'leader-4321',
        readProcessStartToken: () => 'leader-4321',
        sendSignal: (pidOrGroup, signal) => {
          signals.push([pidOrGroup, signal]);
          if (signal === 0 && !alive) {
            const error = new Error('No such process group') as NodeJS.ErrnoException;
            error.code = 'ESRCH';
            throw error;
          }
          if (signal === 'SIGKILL') alive = false;
        },
      }),
    ).toThrow(ProductionCssBuildTimeoutError);
    expect(signals).toContainEqual([-4321, 0]);
    expect(signals.filter(([, signal]) => signal !== 0)).toEqual([
      [-4321, 'SIGTERM'],
      [-4321, 'SIGKILL'],
    ]);
  });

  it('bounds post-SIGKILL confirmation when group liveness never clears', () => {
    let now = 0;
    const signals: Array<[number, NodeJS.Signals | 0]> = [];

    expect(() =>
      waitForProcessGroup(9876, {
        timeoutMs: 1,
        terminationGraceMs: 2,
        killConfirmationMs: 3,
        now: () => now,
        sleep: (milliseconds) => {
          now += milliseconds;
        },
        readExitCode: () => null,
        processGroupStartToken: 'leader-9876',
        readProcessStartToken: () => 'leader-9876',
        isProcessGroupAlive: () => true,
        sendSignal: (pidOrGroup, signal) => signals.push([pidOrGroup, signal]),
      }),
    ).toThrow(ProductionCssBuildTeardownError);
    expect(now).toBe(6);
    expect(signals).toEqual([
      [-9876, 'SIGTERM'],
      [-9876, 'SIGKILL'],
    ]);
  });

  it('cleans up a surviving process group before returning a published exit code', () => {
    let alive = true;
    const signals: Array<[number, NodeJS.Signals | 0]> = [];

    expect(
      waitForProcessGroup(2468, {
        timeoutMs: 100,
        terminationGraceMs: 0,
        readExitCode: () => 0,
        processGroupStartToken: 'leader-2468',
        readProcessStartToken: () => 'leader-2468',
        isProcessGroupAlive: () => alive,
        sendSignal: (pidOrGroup, signal) => {
          signals.push([pidOrGroup, signal]);
          if (signal === 'SIGKILL') alive = false;
        },
      }),
    ).toBe(0);
    expect(signals).toEqual([
      [-2468, 'SIGTERM'],
      [-2468, 'SIGKILL'],
    ]);
  });

  it('never signals a live group after the supervised PGID has been reused', () => {
    const signals: Array<[number, NodeJS.Signals | 0]> = [];

    expect(() =>
      waitForProcessGroup(2468, {
        timeoutMs: 100,
        readExitCode: () => 0,
        isProcessGroupAlive: () => true,
        processGroupStartToken: 'original-leader',
        readProcessStartToken: () => 'replacement-leader',
        sendSignal: (pidOrGroup, signal) => signals.push([pidOrGroup, signal]),
      }),
    ).toThrow(ProductionCssBuildTeardownError);
    expect(signals).toEqual([]);
  });

  it.each([false, true])('releases the prepared guard after a settled build (failure=%s)', (failure) => {
    const fixtureRoot = mkdtempSync(join(tmpdir(), 'acx-style-settled-build-test-'));
    const lockDir = join(fixtureRoot, '.lock');
    const ownership = acquireDirectoryLock(lockDir);
    try {
      const build = () => runWithBuildLock(lockDir, ownership, () => {
        if (failure) throw new Error('Build failed with no surviving group');
        return 'complete';
      });
      if (failure) {
        expect(build).toThrow('Build failed with no surviving group');
      } else {
        expect(build()).toBe('complete');
      }
      expect(existsSync(lockDir)).toBe(false);
      const successor = tryAcquireDirectoryLock(lockDir);
      expect(successor).not.toBeNull();
      if (successor !== null) releaseDirectoryLock(lockDir, successor);
    } finally {
      rmSync(fixtureRoot, { recursive: true, force: true });
    }
  });

  it('retains the build lock when signalling the live group fails with EPERM', () => {
    const fixtureRoot = mkdtempSync(join(tmpdir(), 'acx-style-lock-teardown-test-'));
    const lockDir = join(fixtureRoot, '.lock');
    const ownership = tryAcquireDirectoryLock(lockDir);
    expect(ownership).not.toBeNull();

    try {
      expect(() =>
        runWithBuildLock(lockDir, ownership!, () =>
          waitForProcessGroup(1357, {
            timeoutMs: 100,
            readExitCode: () => 0,
            isProcessGroupAlive: () => true,
            processGroupStartToken: 'leader-1357',
            readProcessStartToken: () => 'leader-1357',
            sendSignal: () => {
              const error = new Error('Operation not permitted') as NodeJS.ErrnoException;
              error.code = 'EPERM';
              throw error;
            },
          }),
        ),
      ).toThrow(ProductionCssBuildTeardownError);
      expect(existsSync(lockDir)).toBe(true);
    } finally {
      if (ownership !== null) releaseDirectoryLock(lockDir, ownership);
      rmSync(fixtureRoot, { recursive: true, force: true });
    }
  });

  it.each(['EPERM', 'kill-confirmation'] as const)(
    'persists %s uncertainty through stale recovery and rechecks the group under the claim',
    (failure) => {
      const fixtureRoot = mkdtempSync(join(tmpdir(), 'acx-style-fence-policy-test-'));
      const lockDir = join(fixtureRoot, '.lock');
      const ownership = tryAcquireDirectoryLock(lockDir);
      let now = 0;
      try {
        expect(() => runWithBuildLock(lockDir, ownership!, () => waitForProcessGroup(1357, {
          timeoutMs: 1, terminationGraceMs: 1, killConfirmationMs: 1,
          now: () => now,
          sleep: (milliseconds) => { now += milliseconds; },
          readExitCode: () => null,
          processGroupStartToken: 'leader-1357',
          readProcessStartToken: () => 'leader-1357',
          isProcessGroupAlive: () => true,
          sendSignal: () => {
            if (failure === 'EPERM') {
              const error = new Error('Operation not permitted') as NodeJS.ErrnoException;
              error.code = 'EPERM';
              throw error;
            }
          },
        }))).toThrow(ProductionCssBuildTeardownError);
        const old = new Date(Date.now() - 60_000);
        utimesSync(join(lockDir, LOCK_OWNER_FILE), old, old);
        const deadOwner = { staleAfterMs: 1, isProcessAlive: () => false };
        expect(tryAcquireDirectoryLock(lockDir, {
          ...deadOwner, isProcessGroupAlive: () => true,
        })).toBeNull();
        const owner = JSON.parse(readFileSync(join(lockDir, LOCK_OWNER_FILE), 'utf8'));
        expect(owner.teardown_uncertain).toEqual({ pgid: 1357, startToken: 'leader-1357' });
        let probes = 0;
        expect(tryAcquireDirectoryLock(lockDir, {
          ...deadOwner, isProcessGroupAlive: () => ++probes > 1,
        })).toBeNull();
        expect(probes).toBe(2);
        expect(existsSync(join(lockDir, '.reaping'))).toBe(false);
        const successor = tryAcquireDirectoryLock(lockDir, {
          ...deadOwner, isProcessGroupAlive: () => false,
        });
        expect(successor).not.toBeNull();
        if (successor !== null) releaseDirectoryLock(lockDir, successor);
      } finally {
        rmSync(fixtureRoot, { recursive: true, force: true });
      }
    },
  );

  it.skipIf(process.platform === 'win32').each([
    'EPERM', 'kill-confirmation', 'publication-failure', 'unwritable-directory', 'all-writes-fail',
  ] as const)(
    'fences successors after the owner exits following %s teardown [D5-R6-02/D5-R7-01/D5-R8-01]',
    (failure) => {
      const fixtureRoot = mkdtempSync(join(tmpdir(), 'acx-style-orphan-fence-test-'));
      const lockDir = join(fixtureRoot, '.lock');
      const pidPath = join(fixtureRoot, 'group-pid');
      // A separate, reaped owner is essential: retaining an ordinary lease only fences successors
      // while that owner lives. Load the actual fixture so this exercises its public entrypoints.
      const ownerSource = String.raw`
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import { dirname } from 'node:path';
import { stripTypeScriptTypes, syncBuiltinESMExports } from 'node:module';
const [sourcePath, lockDir, pidPath, failure] = process.argv.slice(1);
const source = 'const __dirname = ' + JSON.stringify(dirname(sourcePath)) + ';\n' +
  stripTypeScriptTypes(fs.readFileSync(sourcePath, 'utf8'));
const fixture = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const { tryAcquireDirectoryLock, runWithBuildLock, runWithLockHeartbeat, waitForProcessGroup,
  ProductionCssBuildTeardownError } = fixture;
const ownership = tryAcquireDirectoryLock(lockDir);
const group = spawn(process.execPath, ['-e', 'setInterval(() => {}, 0x7fffffff)'], {
  detached: true, stdio: 'ignore',
});
group.unref();
fs.writeFileSync(pidPath, String(group.pid));
let now = 0;
try {
  runWithBuildLock(lockDir, ownership, () => runWithLockHeartbeat(lockDir, ownership, () => {
    // Inject after preparation, exactly when the real build could have changed permissions.
    if (failure === 'unwritable-directory') {
      fs.chmodSync(lockDir, 0o500);
      try {
        fs.writeFileSync(lockDir + '/permission-check', 'must fail');
        throw new Error('Directory permission probe requires an unprivileged process');
      } catch (error) {
        if (error.code !== 'EACCES') throw error;
      }
    }
    if (failure === 'publication-failure' || failure === 'all-writes-fail') {
      const write = fs.writeFileSync;
      fs.writeFileSync = (path, ...args) => {
        if (failure === 'all-writes-fail' || typeof path === 'string') {
          throw Object.assign(new Error('Injected fence write failure'), { code: 'EIO' });
        }
        return write(path, ...args);
      };
      fs.renameSync = () => {
        throw Object.assign(new Error('Injected fence rename failure'), { code: 'EIO' });
      };
      syncBuiltinESMExports();
    }
    return waitForProcessGroup(group.pid, {
      timeoutMs: 1, terminationGraceMs: 1, killConfirmationMs: 1,
      now: () => now, sleep: ms => { now += ms; }, readExitCode: () => null,
      sendSignal: (id, signal) => {
        if (signal === 0) return process.kill(id, 0);
        if (failure !== 'kill-confirmation') {
          const error = new Error('Injected signal permission failure');
          error.code = 'EPERM';
          throw error;
        }
        // Model accepted signals whose teardown cannot be confirmed; the real group survives.
      },
    });
  }));
  throw new Error('Expected uncertain teardown');
} catch (error) {
  console.error(error.message);
  process.exitCode = error instanceof ProductionCssBuildTeardownError ? 23 : 24;
}
`;
      try {
        const ownerResult = spawnSync(process.execPath, ['--input-type=module', '-e', ownerSource,
          join(__dirname, 'productionCssBundle.ts'),
          lockDir, pidPath, failure,
        ], { timeout: 10_000, stdio: 'inherit' });
        expect(ownerResult.error).toBeUndefined();
        expect(ownerResult.status).toBe(23);
        chmodSync(lockDir, 0o700);
        const pgid = Number(readFileSync(pidPath, 'utf8'));
        expect(() => process.kill(-pgid, 0)).not.toThrow();
        const ownerPath = join(lockDir, LOCK_OWNER_FILE);
        const old = new Date(Date.now() - 60_000);
        utimesSync(ownerPath, old, old);

        // This assertion fails on the original code: the owner is dead and its ordinary lease
        // is stale, yet the supervised process group can still mutate the build artifacts.
        expect(tryAcquireDirectoryLock(lockDir, { staleAfterMs: 1 })).toBeNull();
        const owner = JSON.parse(readFileSync(ownerPath, 'utf8'));
        if (failure !== 'all-writes-fail') {
          expect(owner.teardown_uncertain).toEqual({ pgid, startToken: expect.any(String) });
        }
        expect(releaseDirectoryLock(lockDir, owner)).toBe(false);

        // A group-probe failure is uncertainty, including after the owner has exited.
        expect(tryAcquireDirectoryLock(lockDir, {
          staleAfterMs: 1,
          isProcessGroupAlive: () => { throw new Error('Probe unavailable'); },
        })).toBeNull();
        // Deterministically exercise recovery once the whole group is proven absent. Real group
        // teardown is in finally; orphan reaping latency must not make this policy test flaky.
        const successor = tryAcquireDirectoryLock(lockDir, {
          staleAfterMs: 1, isProcessGroupAlive: () => false,
        });
        if (failure === 'all-writes-fail') {
          // No persisted group identity: only the documented operator override can release it.
          expect(successor).toBeNull();
        } else {
          expect(successor).not.toBeNull();
          if (successor !== null) releaseDirectoryLock(lockDir, successor);
        }
      } finally {
        if (existsSync(lockDir)) chmodSync(lockDir, 0o700);
        if (existsSync(pidPath)) {
          try {
            process.kill(-Number(readFileSync(pidPath, 'utf8')), 'SIGKILL');
          } catch (error) {
            if ((error as NodeJS.ErrnoException).code !== 'ESRCH') throw error;
          }
        }
        rmSync(fixtureRoot, { recursive: true, force: true });
      }
    },
    15_000,
  );

  it('does not consult the wall clock for process or termination deadlines', () => {
    let alive = true;
    const wallClock = vi.spyOn(Date, 'now').mockImplementation(() => {
      throw new Error('wall clock unavailable');
    });

    try {
      expect(
        waitForProcessGroup(8642, {
          timeoutMs: 100,
          readExitCode: () => 0,
          isProcessGroupAlive: () => alive,
          processGroupStartToken: 'leader-8642',
          readProcessStartToken: () => 'leader-8642',
          sendSignal: (_pidOrGroup, signal) => {
            if (signal === 'SIGTERM') alive = false;
          },
        }),
      ).toBe(0);
    } finally {
      wallClock.mockRestore();
    }
  });

  it.skipIf(process.platform === 'win32')(
    'kills a SIGTERM-ignoring descendant after the process-group leader exits',
    () => {
      const fixtureRoot = mkdtempSync(join(tmpdir(), 'acx-style-process-group-test-'));
      const readyPath = join(fixtureRoot, 'descendant-ready');
      const pidPath = join(fixtureRoot, 'descendant-pid');
      const descendantSource = String.raw`
const fs = require('node:fs');
const [readyPath, pidPath] = process.argv.slice(1);
process.on('SIGTERM', () => {});
fs.writeFileSync(pidPath, String(process.pid));
fs.writeFileSync(readyPath, 'ready');
setInterval(() => {}, 0x7fffffff);
`;
      const leaderSource = String.raw`
const { spawn } = require('node:child_process');
const [readyPath, pidPath, descendantSource] = process.argv.slice(1);
spawn(process.execPath, ['-e', descendantSource, readyPath, pidPath], { stdio: 'ignore' });
setInterval(() => {}, 0x7fffffff);
`;
      const leader = spawn(
        process.execPath,
        ['-e', leaderSource, readyPath, pidPath, descendantSource],
        { detached: true, stdio: 'ignore' },
      );
      expect(leader.pid).toBeDefined();

      try {
        const readyDeadline = Date.now() + 5_000;
        while (!existsSync(readyPath) && Date.now() < readyDeadline) {
          Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 25);
        }
        expect(existsSync(readyPath)).toBe(true);
        const descendantPid = Number(readFileSync(pidPath, 'utf8'));

        expect(() =>
          waitForProcessGroup(leader.pid!, {
            timeoutMs: 250,
            terminationGraceMs: 250,
            killConfirmationMs: 5_000,
            readExitCode: () => null,
          }),
        ).toThrow(ProductionCssBuildTimeoutError);

        if (process.platform === 'linux') {
          let state: string | null = null;
          try {
            const stat = readFileSync(`/proc/${descendantPid}/stat`, 'utf8');
            state = stat.slice(stat.lastIndexOf(')') + 2).trim().split(/\s+/, 1)[0];
          } catch {
            // A missing proc entry is the expected fully-reaped case.
          }
          expect(state === null || state === 'Z').toBe(true);
        } else {
          expect(() => process.kill(descendantPid, 0)).toThrow();
        }
      } finally {
        if (leader.pid !== undefined) {
          try {
            process.kill(-leader.pid, 'SIGKILL');
          } catch {
            // The supervised group is expected to be gone already.
          }
        }
        rmSync(fixtureRoot, { recursive: true, force: true });
      }
    },
    15_000,
  );
});

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
  const cacheRoot = dirname(artifactFixtureRootForAppRoot(process.cwd()));
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
    expectProductionEntryPoints(bundle);
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
    const fixtureRoot = mkdtempSync(join(tmpdir(), 'acx-style-namespace-test-'));
    const laneARoot = join(fixtureRoot, 'feature-a', 'apps', 'prototype-wp-alt-context');
    const laneBRoot = join(fixtureRoot, 'feature-b', 'apps', 'prototype-wp-alt-context');
    mkdirSync(laneARoot, { recursive: true });
    mkdirSync(laneBRoot, { recursive: true });

    const laneA = artifactFixtureRootForAppRoot(laneARoot);
    const laneAAgain = artifactFixtureRootForAppRoot(join(laneARoot, '.'));
    const laneB = artifactFixtureRootForAppRoot(laneBRoot);

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
    rmSync(fixtureRoot, { recursive: true, force: true });
  });

  it('maps a symlink alias to the real worktree namespace', () => {
    const fixtureRoot = mkdtempSync(join(tmpdir(), 'acx-style-symlink-test-'));
    const realRoot = join(fixtureRoot, 'real-app');
    const aliasRoot = join(fixtureRoot, 'alias-app');
    try {
      mkdirSync(realRoot);
      symlinkSync(realRoot, aliasRoot, 'dir');

      expect(artifactFixtureRootForAppRoot(aliasRoot)).toBe(artifactFixtureRootForAppRoot(realRoot));
    } finally {
      rmSync(fixtureRoot, { recursive: true, force: true });
    }
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

  it.each(['dead', 'live', 'uncertain', 'gone-group', 'malformed', 'fresh'])(
    'uses fenced recovery for a retired namespace with a %s lock',
    (scenario) => {
      const root = mkdtempSync(join(tmpdir(), 'acx-retired-lock-test-'));
      try {
        runFixtureProbe(root, scenario, String.raw`
const cache = join(root, 'cache');
const retired = join(cache, 'retired');
const lock = join(retired, '.lock');
fs.mkdirSync(retired, { recursive: true });
fs.writeFileSync(join(retired, 'namespace-owner.json'), JSON.stringify({ appRoot: join(root, 'removed') }));
const owner = fixture.tryAcquireDirectoryLock(lock);
const deadPid = 2147483647;
const record = { ...owner, pid: scenario === 'live' ? process.pid : deadPid };
if (scenario === 'uncertain' || scenario === 'gone-group') {
  record.teardown_uncertain = { pgid: scenario === 'uncertain' ? process.pid : deadPid, startToken: owner.startToken };
}
fs.writeFileSync(join(lock, 'owner.json'), scenario === 'malformed' ? '{' : JSON.stringify(record));
if (scenario !== 'fresh') fs.utimesSync(join(lock, 'owner.json'), new Date(0), new Date(0));
// Deterministically model a surviving group, including permission-denied inspection.
if (scenario === 'uncertain') {
  const kill = process.kill;
  process.kill = (pid, signal) => {
    if (pid === -process.pid) throw Object.assign(new Error('denied'), { code: 'EPERM' });
    return kill(pid, signal);
  };
}
fixture.registerAndPruneNamespaces(cache, join(cache, 'current'), root);
assert.equal(fs.existsSync(retired), !['dead', 'gone-group'].includes(scenario));
assert.equal(fs.existsSync(join(cache, '.gc-lock')), false);
`);
      } finally {
        rmSync(root, { recursive: true, force: true });
      }
    },
  );

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
