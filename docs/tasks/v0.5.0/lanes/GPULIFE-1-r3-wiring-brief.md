# GPULIFE-1 / gpulife-1-r3-wiring — close four test-integrity findings

Four findings say the deploy-wiring tests do not actually test what they claim. Fix the
tests so each one fails when the behaviour it names is removed. Do not weaken any
assertion to make a test pass, and do not change production shell scripts in this lane —
`scripts/deploy/gpu-lifecycle-install.sh` and `scripts/deploy/preflight-gpu-env.sh` are
owned by other lanes and are off limits here.

## Files you own

- `scripts/deploy/tests/test_gpu_lifecycle_deploy_wiring.py`
- `scripts/deploy/tests/test_gpu_lifecycle_install.py`
- `scripts/test_deploy_workflow_gate.py`
- `Makefile` — the `test-deploy-contract` target only, around line 653

Touch nothing else.

## GPULIFE-1-R2D-01 (medium) — collision handling is untested

`test_gpu_lifecycle_deploy_wiring.py`,
`test_group_name_collision_still_provisions_the_gid_the_units_resolve`.

The test still passes after collision handling is removed from the `groupadd` shim,
because it only checks the end state and never observes the collision path being taken.

Make the test fail when collision handling is gone. The assertion must depend on the
collision branch actually executing — for example by seeding a colliding group name and
asserting the recovery command the installer must issue, not merely that a GID exists
afterwards. Prove it: delete the collision handling locally, watch the test fail, restore
it, watch the test pass. Say so in your summary.

## GPULIFE-1-R2D-02 (medium) — an unreachable decoy satisfies the assertion

`test_gpu_lifecycle_install.py`,
`test_installer_provisions_every_supplementary_group_it_references`.

The test passes when the live installer block is deleted and an unreachable `if false`
decoy is added in its place. The assertion is matching text anywhere in the script rather
than behaviour that must run.

Rewrite it so a decoy cannot satisfy it: execute the installer against the fixture and
assert on the observed effects (the groups that were actually provisioned), not on source
text. Prove it with the same delete-and-watch-it-fail check.

## GPULIFE-1-R2D-04 (medium) — the Makefile target can silently lose a suite

`scripts/test_deploy_workflow_gate.py`.

Dropping `test_gpu_lifecycle_deploy_wiring.py` from the `test-deploy-contract` Makefile
target (Makefile:653) leaves `make -n` successful and
`test_make_target_keeps_contract_suites` green. A suite can fall out of the gate with no
test noticing.

Make the guard enumerate the suites the target must run and assert each one is present by
name, so removing any of them fails. Prefer deriving the expected list from the files on
disk over a second hand-maintained list that will itself drift.

## GPULIFE-1-R2L-02 (low) — a docstring that is not true

`test_gpu_lifecycle_deploy_wiring.py`.

A docstring claims `groupadd exiting 0 is not the postcondition`, but the fixture seeds
`acxapi:5000` and `acxgid10001:5001`, so the shim exits 9 on both attempts and never
returns 0. The exit-0 case the comment describes is never exercised.

Either add the case the docstring promises (a `groupadd` that exits 0 while NSS still does
not resolve the GID) or rewrite the docstring to describe what the test really does.
Adding the case is better if the shim can express it.

## Verification

Run only what you own, from the repo root of your worktree:

```
LC_ALL=C python -m pytest scripts/deploy/tests/test_gpu_lifecycle_deploy_wiring.py scripts/deploy/tests/test_gpu_lifecycle_install.py scripts/test_deploy_workflow_gate.py -q
```

`LC_ALL=C` is required — without it these shell-driving suites stall on some hosts.

Every fix needs the mutation proof described above: break the behaviour, confirm the test
now fails, restore it, confirm the test passes. A fix without that proof is not done,
because the whole point of these four findings is that the existing tests passed while the
behaviour was absent.

Commit on your lane branch. In your summary, list each finding id with the mutation you
ran and the observed before/after result.
