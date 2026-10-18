# GPULIFE-1 / gpulife-1-r3-preflight — three findings in the preflight suite

Two of these say a test passes while the behaviour it names is absent. One says a test
depends on which python happens to run it. Fix all three without weakening an assertion.

## Files you own

- `scripts/deploy/tests/test_preflight_gpu_env.py`
- `scripts/deploy/preflight-gpu-env.sh`

Touch nothing else. `scripts/deploy/gpu-lifecycle-install.sh` and the deploy-wiring tests
belong to other lanes running right now — editing them will conflict.

## GPULIFE-1-R2D-03 (medium) — the getent shim accepts anything

The preflight DNS tests still pass after the production call `getent ahosts` is mutated to
`getent passwd`, because the fake `getent` shim accepts every non-group database and
answers the same way regardless.

Make the shim faithful: it should answer only for the databases the real `getent` would
answer for in this context, and fail (or record an unexpected-database marker the test
asserts on) for anything else. Then the `ahosts` to `passwd` mutation must break the test.
Prove it — mutate the production line, watch the DNS tests fail, restore, watch them pass.

## GPULIFE-1-R2D-05 (medium) — the test depends on which python runs it

`test_probe_harness_handles_old_system_python_and_missing_proc` fails under
`/usr/bin/python3` and passes under the lane venv, because its rewrite maps
`/usr/bin/python3` in a way that only holds for one interpreter.

A test that passes or fails on interpreter choice is not evidence. Make the test pin the
interpreter it exercises explicitly rather than inheriting whatever runs pytest — construct
the probe against a named interpreter path from the fixture, so the result is the same
under `/usr/bin/python3` and under the venv. Verify by running the single test under both:

```
LC_ALL=C /usr/bin/python3 -m pytest scripts/deploy/tests/test_preflight_gpu_env.py -k probe_harness_handles_old_system_python -q
LC_ALL=C python -m pytest scripts/deploy/tests/test_preflight_gpu_env.py -k probe_harness_handles_old_system_python -q
```

Both must pass. If `/usr/bin/python3` cannot run pytest at all in your sandbox, say so
plainly in your summary rather than claiming a verification you did not perform.

## GPULIFE-1-R2L-03 (low) — the healthy baseline is never asserted healthy

The positive half of the pair does `healthy = run_preflight(...)` and asserts only that
`"216/GROUP" not in healthy.stderr`. `returncode == 0` is never checked, so preflight could
regress to failing outright and the positive assertion would still hold while the negative
half stayed green — the regression would be invisible and unattributable.

Assert `healthy.returncode == 0` with the stderr in the failure message, so a regressed
baseline names itself. Check whether the same omission appears in sibling positive-path
helpers in this file and fix those too.

## Verification

```
LC_ALL=C python -m pytest scripts/deploy/tests/test_preflight_gpu_env.py -q -p no:cacheprovider
```

`LC_ALL=C` is required — without it these shell-driving suites stall on some hosts.

If any test in this file errors with `ModuleNotFoundError: No module named 'httpx'`, that is
a known venv gap in some worktrees and not your defect: report it and move on, do not
delete or skip the test.

Commit on your lane branch. In your summary, list each finding id with the mutation or the
two-interpreter run you performed and the observed before/after result.
