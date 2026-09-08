# Round 18 verification

D2-R17-01 remains open pending a green boundary run under 60 seconds on an
idle host. This change moves the exhaustive declaration matrix to pure scanner
calls in Python and TypeScript, deduplicates generated emphasis strings and
expanded cases, and samples formatting classes through both Python check paths.
The sample retains partial-word underscore emphasis, whole-label italic emphasis,
and indented declarations from rounds 14–16. Existing other boundary probes remain.

All Node parity subprocesses have a 10-second deadline with an explicit diagnostic.
All Vitest synchronous children have a 55-second deadline and SIGKILL on expiry;
the existing 300-second Vitest budget was not increased.

Results in the managed Linux sandbox:

- `./node_modules/.bin/vitest run js/admin/__tests__/uxmap-render-parity.test.ts`:
  157 passed, 13 failed; 98.49 seconds overall. Twelve failures report sandbox
  `spawnSync EPERM`; the boundary probe hits its 55-second deadline.
- Same command with `-t 'every shared declaration variant'`: all four matrix
  tests pass, 579 ms test time (4.13 seconds overall).
- `python -m unittest discover -s apps/prototype-wp-alt-context/docs/ux-maps -p test_render_ux_maps.py`:
  all 21 tests pass, 188.689 seconds. This does **not** establish the required
  sub-60-second boundary runtime.
- `python -m unittest discover -s apps/prototype-wp-alt-context/docs/ux-maps -p test_sync_unicode_width.py`:
  both tests pass, 23.578 seconds.
- `python apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py --check`:
  all six maps current.
- `python apps/prototype-wp-alt-context/docs/ux-maps/sync_unicode_width.py --check`:
  property ranges match Python Unicode 15.0.0.
- `./node_modules/.bin/tsc --noEmit`: passes.
- `git diff --check`: passes.

Python above means the lane-local interpreter resolved immediately before each
command. No importable Python package is owned by this lane. The authorized
read-only dependency symlink was used; no packages were installed.

Mutation experiment (inline Python harness): monkeypatch the Python scanner's
label substitution from `[_*\x60]+` to edge-only stripping, then run
`test_declaration_matrix_in_process`: 724 failures. Copy the TypeScript module
tree into a temporary directory, apply the corresponding edge-only replacement,
patch the renderer's repository root to that copy, and run
`test_declaration_variants_fail_both_check_paths`: 50 failures. Production files
were never mutated. The restored Python matrix passes in 381 ms; restored
sampled boundaries passed as part of the 21-test suite above.

Further timing work or an unrestricted idle-host measurement is required before
closing D2-R17-01. The sandbox result must not be recorded as a green lane gate.
