# GPULIFE-1 lane `gpulife-1-r3-wiring` (round 4): close the last open finding, R2L-01

Branch `feature/gpulife-1-r3-wiring` @ `be38976674bd186715efb1151e6f6729140f720b` (main merged in on top of
`d1928c2c2`). Findings in scope: exactly one, `GPULIFE-1-R2L-01`. Do not open new ids unless you hit a genuine blocker;
if you do, use `GPULIFE-1-R4-01` .. `GPULIFE-1-R4-03`.
Owned paths: `scripts/deploy/gpu-lifecycle-install.sh`, `scripts/deploy/tests/test_gpu_lifecycle_deploy_wiring.py`,
`scripts/test_deploy_workflow_gate.py`. Nothing else.

## Coordinator verification of round 3 (so you do not redo it)

Seven of the eight round-2 findings were verified fixed at `d1928c2c2` by static inspection. Do not touch them.
One is not:

**GPULIFE-1-R2L-01 (low)** — `scripts/deploy/gpu-lifecycle-install.sh:773-776` is byte-identical to the round-2 anchor.
Line 775 is a bare `getent group 10001 >/dev/null 2>&1`. Under `set -e` inside the spliced ssh payload it fails closed
with **no message at all**: when `groupadd` exits 0 but NSS still does not resolve the GID, the operator sees only the
generic `error:` line from the ERR trap (lines 271-287) and has nothing to act on. Canon: CARD-07
fail-loudly-succeed-quietly — the failure is correct, the silence is the defect; [DIAG-07] an error must name what to
check.

## Required change

Replace line 775 with a diagnostic-bearing assertion. The block is spliced into a **double-quoted** ssh payload (see the
editing note at lines 770-772: no literal double-quote, dollar, backtick or backslash survives transport), so single
quotes only:

```
    getent group 10001 >/dev/null 2>&1 || { echo 'ERROR gpu-lifecycle: groupadd exited 0 but NSS still does not resolve GID 10001; both lifecycle units would die at 216/GROUP before ExecStart. Check nsswitch group sources on the host, then re-run.' >&2; exit 1; }
```

Then extend `test_install_fails_closed_when_the_gid_is_unresolvable_after_groupadd`
(`test_gpu_lifecycle_deploy_wiring.py` ~line 876, the one using the `groupadd_noop` knob) with
`assert "does not resolve GID 10001" in result.stderr` so the message itself is covered, not just the exit code.

## Also close, same commit

- `scripts/test_deploy_workflow_gate.py` `_contract_lifecycle_suites()` is never asserted non-empty; deleting every
  `test_gpu_lifecycle_*.py` silently shrinks the expectation to `[]` and the guard stays green. Add
  `assert suites, "lifecycle suites vanished from scripts/deploy/tests"` right after the glob.
- `test_gpu_lifecycle_install.py` imports `_run_lifecycle` from the wiring test module by
  `scripts.deploy.tests...` path, which only resolves when the repo root is on `sys.path`. That file is NOT in your owned
  paths — do not edit it. Confirm the Makefile target `test-deploy-contract` (Makefile ~line 653) invokes
  `python3 -m pytest` from the root and record the observation in your report; the coordinator decides.

## Verification you must run and report

- `LC_ALL=C python3 -m pytest scripts/deploy/tests/test_gpu_lifecycle_deploy_wiring.py -q` — green, and the extended
  test must have been observed red first (remove your new `echo` and run it; state the failure).
- `LC_ALL=C python3 -m pytest scripts/test_deploy_workflow_gate.py -q` — green.
- `bash -n scripts/deploy/gpu-lifecycle-install.sh` — clean.

(`LC_ALL=C` matters: the deploy suites stall on macOS bash 3.2 without it.)

Never weaken or delete a test.

## Commit

One commit, subject `gpu-lifecycle: name the NSS failure when groupadd succeeds but the GID still does not resolve`.
No attribution trailers.
