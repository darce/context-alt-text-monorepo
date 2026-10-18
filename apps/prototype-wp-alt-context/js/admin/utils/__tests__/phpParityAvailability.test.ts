import { spawnSync } from 'node:child_process';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { shouldSkipPhpParity } from './helpers/phpParityAvailability';

vi.mock('node:child_process', () => {
  const spawnSync = vi.fn();
  return { spawnSync, default: { spawnSync } };
});

describe('PHP parity availability gate', () => {
  beforeEach(() => {
    vi.stubEnv('ACX_PARITY_ALLOW_SKIP', '');
    vi.stubEnv('CI', '');
    vi.spyOn(process.stderr, 'write').mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  const simulateSpawnError = (code: string) => {
    const error = Object.assign(new Error(`spawnSync php ${code}`), { code });
    vi.mocked(spawnSync).mockReturnValue({
      error,
      status: null,
      signal: null,
      pid: 0,
      output: [],
      stdout: '',
      stderr: '',
    });
    return error;
  };

  // TEST-15 (/home/gate/canon/engineering.md:396): inject the failed probe;
  // the contract gate must not silently certify an unexecuted parity check.
  it.each(['EPERM', 'EACCES', 'ENOENT'])('fails in CI without opt-in when PHP reports %s', (code) => {
    vi.stubEnv('CI', 'true');
    simulateSpawnError(code);

    expect(shouldSkipPhpParity).toThrow(/ACX_PARITY_ALLOW_SKIP=1/);
    expect(process.stderr.write).not.toHaveBeenCalled();
  });

  it('also requires explicit opt-in outside CI', () => {
    simulateSpawnError('ENOENT');
    expect(shouldSkipPhpParity).toThrow(/ACX_PARITY_ALLOW_SKIP=1/);
  });

  it.each(['EPERM', 'EACCES', 'ENOENT'])('allows an explicit sandbox skip for %s', (code) => {
    vi.stubEnv('ACX_PARITY_ALLOW_SKIP', '1');
    simulateSpawnError(code);

    expect(shouldSkipPhpParity()).toBe(true);
    expect(process.stderr.write).toHaveBeenCalledWith(expect.stringContaining(`(${code})`));
  });

  it('does not treat a truthy-looking value as opt-in', () => {
    vi.stubEnv('ACX_PARITY_ALLOW_SKIP', 'true');
    simulateSpawnError('EPERM');
    expect(shouldSkipPhpParity).toThrow(/ACX_PARITY_ALLOW_SKIP=1/);
  });

  it('does not skip a working PHP runtime even with opt-in', () => {
    vi.stubEnv('ACX_PARITY_ALLOW_SKIP', '1');
    vi.mocked(spawnSync).mockReturnValue({
      status: 0,
      signal: null,
      pid: 1,
      output: [],
      stdout: 'PHP 8.0',
      stderr: '',
    });
    expect(shouldSkipPhpParity()).toBe(false);
    expect(process.stderr.write).not.toHaveBeenCalled();
  });

  it('does not skip unexpected spawn failures even with opt-in', () => {
    vi.stubEnv('ACX_PARITY_ALLOW_SKIP', '1');
    const error = simulateSpawnError('ETIMEDOUT');
    expect(shouldSkipPhpParity).toThrow(error);
  });

  it('does not skip a failed PHP command even with opt-in', () => {
    vi.stubEnv('ACX_PARITY_ALLOW_SKIP', '1');
    vi.mocked(spawnSync).mockReturnValue({
      status: 1,
      signal: null,
      pid: 1,
      output: [],
      stdout: '',
      stderr: 'broken PHP runtime',
    });
    expect(shouldSkipPhpParity).toThrow(/broken PHP runtime/);
  });
});
