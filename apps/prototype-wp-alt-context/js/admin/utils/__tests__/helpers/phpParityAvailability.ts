import { spawnSync } from 'node:child_process';

export const shouldSkipPhpParity = (): boolean => {
  const probe = spawnSync('php', ['--version'], { encoding: 'utf8', timeout: 5000 });
  const errorCode = (probe.error as NodeJS.ErrnoException | undefined)?.code;
  const unavailable = ['EPERM', 'EACCES', 'ENOENT'].includes(errorCode ?? '');
  if (unavailable) {
    // A missing/forbidden runtime is an unverified contract, including in CI.
    // Only an explicit sandbox opt-in may bypass this gate; never set it in CI.
    if (process.env.ACX_PARITY_ALLOW_SKIP !== '1') {
      throw new Error(
        `PHP wire-code parity cannot execute (${errorCode}). Run on a PHP-enabled worker. ` +
          'For a local sandbox only, explicitly set ACX_PARITY_ALLOW_SKIP=1 to skip this check.',
      );
    }
    process.stderr.write(
      `SKIP PHP wire-code parity: ACX_PARITY_ALLOW_SKIP=1; php cannot execute (${errorCode}). ` +
        'Run on a PHP-enabled worker before merging.\n',
    );
  } else if (probe.error || probe.status !== 0) {
    throw probe.error ?? new Error(`PHP availability check failed: ${probe.stderr}`);
  }
  return unavailable;
};
