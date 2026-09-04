# GPUUX-1 lane F report

## Outcome

The lifecycle snapshot producer remains wired to the end of every reap and
start cycle. The writer publishes exactly `state` and `written_at`, uses an
exhaustive OCI lifecycle-state mapping, refuses `unknown`, and atomically
replaces the target from a same-directory temporary file.

The writer coverage is now independent of the description-service package.
`test_state_snapshot.py` uses only the standard library and lane-owned modules,
so the root test runner executes all 15 writer, atomicity, transition, and
cycle-integration cases. Cross-package round trips through the real reader and
the reader's missing-file fail-closed default live in
`test_state_snapshot_contract.py`; only that file skips when `scene` is not
installed.

## TEST-06 mutation evidence

After the split, the expected `written_at` value in
`test_replace_is_atomic_and_target_is_never_partial` was deliberately changed
from `2.0` to `3.0`. The focused run failed with:

```text
FAILED infra/oci/gpu_lifecycle/tests/test_state_snapshot.py::test_replace_is_atomic_and_target_is_never_partial
1 failed in 0.10s
```

The assertion detail was:

```text
E     {'written_at': 2.0} != {'written_at': 3.0}
```

The mutation was restored before commit. The root writer plus contract-file
GREEN summary was:

```text
15 passed, 1 skipped in 0.15s
```

Running from the description-service directory with `scene` resolving from
this worktree exercised the cross-package contract instead of skipping it:

```text
21 passed in 0.15s
```

## Full-suite verification

The complete non-socket suite, including all tests in `test_start_actuator.py`,
`test_cpu_fallback.py`, `test_batch_fence.py`, `test_instance_states.py`, and
`test_max_lease.py`, plus all non-server readiness tests, passed:

```text
65 passed, 1 skipped, 2 deselected in 0.22s
```

The exact unfiltered root command executed all writer tests and reported:

```text
2 failed, 65 passed, 1 skipped in 0.29s
```

Both failures are pre-existing localhost HTTP-server tests in
`test_readiness_probe.py`; this managed sandbox rejects `socket.socket()` with
`PermissionError: [Errno 1] Operation not permitted` before the code under test
runs.

The prescribed service-side `uv run --locked --extra dev` command was also
attempted with a writable temporary cache. It could not download the uncached
locked dependency `mcp==1.27.1` because network and DNS access are disabled.
The lane-managed Python was therefore used from the service directory for the
21-test contract GREEN above; its import-origin check resolved `scene` to
`apps/prototype-description-service/scene/__init__.py` in this worktree.

`python -m compileall` and `git diff --check` passed for the touched tests.
`ruff` is unavailable in the lane environment.

## Commit and open threads

Test split commit: `fd42592d24116dadb4da3ccb3ef26f0e2938e56d`.

There are no known code or mapping issues. The only open verification threads
are the sandbox socket restriction and the unavailable network dependency
needed to recreate the service environment with `uv`.
