# GPUUX-1 H-04 lane report

## Change summary

- Added `AggregateJobLoadSource`, which scans every
  `/run/acx-write/*/describe-load.json`, sums fresh work, preserves fail-closed
  busy behavior for malformed input and stale files within the bounded grace
  window, and logs the environment when a beyond-grace file is ignored.
- Replaced the production `--load-json` CLI with `--load-dir`; added the
  `--load-stale-grace-seconds` flag and
  `ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS` default (600 seconds).
- Isolated the environment compose writer at
  `/run/acx-write/${ACX_ENV}/describe-load.json` with only that environment
  subdirectory mounted writable.
- Updated both lifecycle units to consume `/run/acx-write` and provisioned
  `/run/acx-write/{dev,staging,prod}` as `root:10001` mode `0775`, including
  boot-time tmpfiles recreation.
- Updated the snapshot checker to derive the compose load parent, compare it
  with the units' `--load-dir`, preserve the separate state/load directories,
  and fail closed unless all three environment directories are writable by uid
  10001 and their snapshots are fresh/readable.

## RED evidence

Command:

```text
/home/gate/grok-sandbox/feature-gpuux-1-h04-e6e97e4d/.venv/bin/python -m pytest infra/oci/gpu_lifecycle/tests/test_load_source_aggregate.py -q
```

Tail before implementation:

```text
infra/oci/gpu_lifecycle/tests/test_load_source_aggregate.py:12: in <module>
    from infra.oci.gpu_lifecycle.load_source import AggregateJobLoadSource
E   ModuleNotFoundError: No module named 'infra.oci.gpu_lifecycle.load_source'
=========================== short test summary info ============================
ERROR infra/oci/gpu_lifecycle/tests/test_load_source_aggregate.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.49s
```

## tests_run

Command:

```text
/bin/bash scripts/deploy/tests/test-check-gpu-snapshots.sh
```

Tail:

```text
PASS: compose-derived parent must agree with lifecycle load directory
PASS: unrendered snapshot mount template fails
PASS: unrendered GPU state environment template fails
ALL PASS
```

Command:

```text
/home/gate/grok-sandbox/feature-gpuux-1-h04-e6e97e4d/.venv/bin/python -m pytest infra/oci/gpu_lifecycle/tests/test_load_source_aggregate.py scripts/deploy/tests/test_check_gpu_snapshots_shell.py -q
```

Tail:

```text
..............                                                           [100%]
14 passed in 2.85s
```

Command (required broad lane command):

```text
/home/gate/grok-sandbox/feature-gpuux-1-h04-e6e97e4d/.venv/bin/python -m pytest infra/oci/gpu_lifecycle/tests scripts/deploy/tests/test_check_gpu_snapshots_shell.py -q
```

Tail:

```text
FAILED infra/oci/gpu_lifecycle/tests/test_max_lease.py::test_cli_defaults_the_cap_on_rather_than_off
FAILED infra/oci/gpu_lifecycle/tests/test_max_lease.py::test_cli_accepts_an_explicit_cap
FAILED infra/oci/gpu_lifecycle/tests/test_max_lease.py::test_cli_accepts_running_since_path_override
FAILED infra/oci/gpu_lifecycle/tests/test_readiness_probe.py::test_http_probe_templates_instance_id_into_url
FAILED infra/oci/gpu_lifecycle/tests/test_readiness_probe.py::test_http_readiness_probe_local_server_2xx_non_2xx_urlerror
FAILED infra/oci/gpu_lifecycle/tests/test_state_snapshot_contract.py::test_deployed_compose_keeps_load_writable_and_gpu_state_read_only
6 failed, 118 passed in 6.10s
```

The three max-lease tests and the compose contract test assert the deleted
single-file interface and are outside this lane's frozen file ownership. The
two readiness tests cannot create an AF_INET socket in this sandbox
(`PermissionError: [Errno 1] Operation not permitted`).

## mutants

All mutations were applied one at a time, tested, and immediately restored.

### (a) Drop the grace window

```diff
-            elif age <= self.stale_grace_seconds:
+            elif False:  # MUTANT: ignore stale files immediately
```

KILLED by `test_stale_within_grace_is_busy_while_fresh_busy_is_aggregated`:
expected aggregate queue depth 3, mutant returned 2. Focused suite result:
`1 failed, 12 passed in 0.14s`.

### (b) Treat beyond-grace input as busy forever

```diff
             else:
+                snapshots.append(_FAIL_CLOSED_BUSY)  # MUTANT: stale remains busy forever
```

KILLED by `test_stale_beyond_grace_is_ignored_when_a_fresh_idle_file_exists`:
expected a trustworthy idle snapshot, mutant returned the untrustworthy busy
sentinel. Focused suite result: `1 failed, 12 passed in 0.31s`.

### (c) Glob only the first environment

```diff
-            paths = sorted(self.directory.glob("*/describe-load.json"))
+            paths = sorted(self.directory.glob("*/describe-load.json"))[:1]  # MUTANT
```

KILLED by four aggregate cases, including
`test_two_fresh_files_one_busy_aggregates_all_environments`. Focused suite
result: `4 failed, 9 passed in 0.15s`.

## blockers

- The required broad command cannot be fully green without changing frozen,
  non-owned legacy tests that still require `--load-json` and the shared
  `/run/acx-write/describe-load.json` path.
- This execution sandbox denies local AF_INET socket creation, blocking two
  unrelated readiness-probe tests.

## findings outside ownership

- `infra/oci/gpu_lifecycle/tests/test_max_lease.py` has three CLI fixtures that
  must migrate from `--load-json /tmp/x` to `--load-dir /tmp`.
- `infra/oci/gpu_lifecycle/tests/test_state_snapshot_contract.py` still asserts
  the old shared compose load path and mount; it must assert the `${ACX_ENV}`
  subdirectory contract.
- `infra/oci/gpu_lifecycle/tests/test_readiness_probe.py` requires local socket
  permission not available in this worker sandbox.
