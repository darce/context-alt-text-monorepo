# FEBT-1 G5/G6 verification evidence

## PREMISE CHECK

- `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useLiveReviewTarget.ts` imports `isAbortOrTimeout` from `../../../utils/retryPolicy` and its retry predicate contains `if (isClusterNotFound(error) || isAbortOrTimeout(error)) { return false; }`.
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx` contains no `user.click`, `user.clear`, or `user.type` call nested inside an `actFlow(...)` callback. Calls routed through `runWithTimers(...)` are outside `actFlow(...)` callbacks.

Both premises were present, so dependency installation was attempted.

## INSTALL

First attempt, from `apps/prototype-wp-alt-context`:

```text
$ npm ci
npm warn deprecated abab@2.0.6: Use your platform's native atob() and btoa() methods instead
npm warn deprecated whatwg-encoding@2.0.0: Use @exodus/bytes instead for a more spec-conformant and faster implementation
npm warn deprecated domexception@4.0.0: Use your platform's native DOMException instead
npm warn deprecated node-domexception@1.0.0: Use your platform's native DOMException instead
npm warn deprecated glob@10.5.0: Old versions of glob are not supported, and contain widely publicized security vulnerabilities, which have been fixed in the current version. Please update. Support for old versions may be purchased (at exorbitant rates) by contacting i@izs.me
npm error code 1
npm error path /home/gate/grok-sandbox/feature-febt-1-g1-e248d59a/apps/prototype-wp-alt-context/node_modules/esbuild
npm error command failed
npm error command sh -c node install.js
npm error node:internal/child_process:1120
npm error     result.error = new ErrnoException(result.error, 'spawnSync ' + options.file);
npm error                    ^
npm error
npm error <ref *1> Error: spawnSync /home/gate/grok-sandbox/feature-febt-1-g1-e248d59a/apps/prototype-wp-alt-context/node_modules/esbuild/bin/esbuild EPERM
npm error     at Object.spawnSync (node:internal/child_process:1120:20)
npm error     at spawnSync (node:child_process:902:24)
npm error     at Object.execFileSync (node:child_process:945:15)
npm error     at validateBinaryVersion (/home/gate/grok-sandbox/feature-febt-1-g1-e248d59a/apps/prototype-wp-alt-context/node_modules/esbuild/install.js:102:28)
npm error     at /home/gate/grok-sandbox/feature-febt-1-g1-e248d59a/apps/prototype-wp-alt-context/node_modules/esbuild/install.js:287:5 {
npm error   errno: -1,
npm error   code: 'EPERM',
npm error   syscall: 'spawnSync /home/gate/grok-sandbox/feature-febt-1-g1-e248d59a/apps/prototype-wp-alt-context/node_modules/esbuild/bin/esbuild',
npm error   path: '/home/gate/grok-sandbox/feature-febt-1-g1-e248d59a/apps/prototype-wp-alt-context/node_modules/esbuild/bin/esbuild',
npm error   spawnargs: [ '--version' ],
npm error   error: [Circular *1],
npm error   status: 0,
npm error   signal: null,
npm error   output: [
npm error     null,
npm error     Buffer(7) [Uint8Array] [
npm error       48, 46, 50, 55,
npm error       46, 55, 10
npm error     ],
npm error     Buffer(0) [Uint8Array] []
npm error   ],
npm error   pid: 42,
npm error   stdout: Buffer(7) [Uint8Array] [
npm error     48, 46, 50, 55,
npm error     46, 55, 10
npm error   ],
npm error   stderr: Buffer(0) [Uint8Array] []
npm error }
npm error
npm error Node.js v22.23.1
npm error Log files were not written due to an error writing to the directory: /home/gate/.npm/_logs
npm error You can rerun the command with `--loglevel=verbose` to see the logs in your terminal
```

Exit code: `1`.

Required fallback attempt, from `apps/prototype-wp-alt-context`:

```text
$ npm install
npm warn deprecated abab@2.0.6: Use your platform's native atob() and btoa() methods instead
npm warn deprecated whatwg-encoding@2.0.0: Use @exodus/bytes instead for a more spec-conformant and faster implementation
npm warn deprecated domexception@4.0.0: Use your platform's native DOMException instead
npm warn deprecated node-domexception@1.0.0: Use your platform's native DOMException instead
npm warn deprecated glob@10.5.0: Old versions of glob are not supported, and contain widely publicized security vulnerabilities, which have been fixed in the current version. Please update. Support for old versions may be purchased (at exorbitant rates) by contacting i@izs.me
npm error code 1
npm error path /home/gate/grok-sandbox/feature-febt-1-g1-e248d59a/apps/prototype-wp-alt-context/node_modules/esbuild
npm error command failed
npm error command sh -c node install.js
npm error node:internal/child_process:1120
npm error     result.error = new ErrnoException(result.error, 'spawnSync ' + options.file);
npm error                    ^
npm error
npm error <ref *1> Error: spawnSync /home/gate/grok-sandbox/feature-febt-1-g1-e248d59a/apps/prototype-wp-alt-context/node_modules/esbuild/bin/esbuild EPERM
npm error     at Object.spawnSync (node:internal/child_process:1120:20)
npm error     at spawnSync (node:child_process:902:24)
npm error     at Object.execFileSync (node:child_process:945:15)
npm error     at validateBinaryVersion (/home/gate/grok-sandbox/feature-febt-1-g1-e248d59a/apps/prototype-wp-alt-context/node_modules/esbuild/install.js:102:28)
npm error     at /home/gate/grok-sandbox/feature-febt-1-g1-e248d59a/apps/prototype-wp-alt-context/node_modules/esbuild/install.js:287:5 {
npm error   errno: -1,
npm error   code: 'EPERM',
npm error   syscall: 'spawnSync /home/gate/grok-sandbox/feature-febt-1-g1-e248d59a/apps/prototype-wp-alt-context/node_modules/esbuild/bin/esbuild',
npm error   path: '/home/gate/grok-sandbox/feature-febt-1-g1-e248d59a/apps/prototype-wp-alt-context/node_modules/esbuild/bin/esbuild',
npm error   spawnargs: [ '--version' ],
npm error   error: [Circular *1],
npm error   status: 0,
npm error   signal: null,
npm error   output: [
npm error     null,
npm error     Buffer(7) [Uint8Array] [
npm error       48, 46, 50, 55,
npm error       46, 55, 10
npm error     ],
npm error     Buffer(0) [Uint8Array] []
npm error   ],
npm error   pid: 42,
npm error   stdout: Buffer(7) [Uint8Array] [
npm error     48, 46, 50, 55,
npm error     46, 55, 10
npm error   ],
npm error   stderr: Buffer(0) [Uint8Array] []
npm error }
npm error
npm error Node.js v22.23.1
npm error Log files were not written due to an error writing to the directory: /home/gate/.npm/_logs
npm error You can rerun the command with `--loglevel=verbose` to see the logs in your terminal
```

Exit code: `1`.

Classification: neither attempt failed because of network/registry reachability, and neither failed because of package resolution. Both reached the `esbuild` postinstall and failed because the sandbox denied spawning the installed `node_modules/esbuild/bin/esbuild` executable with `EPERM`. No install command succeeded.

## STEP 2 SCOPED RUN

Not reached. The dependency brief requires stopping immediately when both `npm ci` and the single `npm install` fallback fail. Consequently, there is no observed scoped-run exit code, tail, or TIMEOUT-versus-ASSERTION classification.

## STEP 3 FULL RUN

Not reached because dependency installation failed and the lane was required to stop before running Vitest. No comparison with the 15-failed / 2969-passed baseline was observed.

VERDICT: BLOCKED
