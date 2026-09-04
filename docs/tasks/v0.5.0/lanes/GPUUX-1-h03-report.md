# GPUUX-1 H-03 lane report

## Change summary

- Replaced the retired load-file variables at both remote snapshot-check call
  sites with the frozen aggregate load-directory contract.
- Added `ACX_GPU_SNAPSHOT_DIR=/run/acx` to both call sites and kept every
  assignment alphabetically ordered.
- Added a pytest regression that parses each real assignment block, remaps its
  paths into a temporary fixture, and executes the real checker through
  `bash -s` from a directory with no repository checkout.
- Updated the existing shell contract's stale production env assertion to the
  already-landed namespaced `/run/acx-write/prod/describe-load.json` path.

## RED evidence

The unfixed call sites were watched failing first. In this isolated checkout,
the real checker still reads the retired `ACX_GPU_UNIT_LOAD_PATH` and
`ACX_DESCRIBE_LOAD_PATH` variables, so the pre-fix failures named the drifted
call sites instead of reaching the line-34 fallback described by the
superseding brief:

```text
FAILED scripts/deploy/tests/test_check_gpu_snapshots_shell.py::test_remote_snapshot_callsite_executes_without_repo_checkout[Makefile-assignments0]
E AssertionError: Makefile remote checker environment drifted: expected ['ACX_DESCRIBE_LOAD_DIR', 'ACX_GPU_COMPOSE_FILE', 'ACX_GPU_SNAPSHOT_DIR', 'ACX_GPU_STATE_PATH', 'ACX_GPU_UNIT_LOAD_DIR', 'ACX_GPU_UNIT_STATE_PATH'], got ['ACX_DESCRIBE_LOAD_PATH', 'ACX_GPU_COMPOSE_FILE', 'ACX_GPU_STATE_PATH', 'ACX_GPU_UNIT_LOAD_PATH', 'ACX_GPU_UNIT_STATE_PATH']
FAILED scripts/deploy/tests/test_check_gpu_snapshots_shell.py::test_remote_snapshot_callsite_executes_without_repo_checkout[scripts/deploy/recognition-service.sh-assignments1]
E AssertionError: scripts/deploy/recognition-service.sh remote checker environment drifted: expected ['ACX_DESCRIBE_LOAD_DIR', 'ACX_GPU_COMPOSE_FILE', 'ACX_GPU_SNAPSHOT_DIR', 'ACX_GPU_STATE_PATH', 'ACX_GPU_UNIT_LOAD_DIR', 'ACX_GPU_UNIT_STATE_PATH'], got ['ACX_DESCRIBE_LOAD_PATH', 'ACX_GPU_COMPOSE_FILE', 'ACX_GPU_STATE_PATH', 'ACX_GPU_UNIT_LOAD_PATH', 'ACX_GPU_UNIT_STATE_PATH']
3 failed in 13.11s
```

After fixing both call sites, the exact remote-shaped execution reaches the
expected line-34 failure because sibling H-04's checker change is absent:

```text
E AssertionError: Makefile remote checker invocation exited with 1
E   /bin/bash: line 10: BASH_SOURCE[0]: unbound variable
E   ERROR: lifecycle install script is missing or unreadable: //scripts/deploy/gpu-lifecycle-install.sh
E AssertionError: scripts/deploy/recognition-service.sh remote checker invocation exited with 1
E   /bin/bash: line 10: BASH_SOURCE[0]: unbound variable
E   ERROR: lifecycle install script is missing or unreadable: //scripts/deploy/gpu-lifecycle-install.sh
2 failed, 1 passed in 2.78s
```

## tests_run

Baseline lane command:

```bash
lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -m pytest scripts/deploy/tests/test_prod_compose_load_mount.py scripts/deploy/tests/test_check_gpu_snapshots_shell.py -q
```

Tail:

```text
FAILED scripts/deploy/tests/test_check_gpu_snapshots_shell.py::test_check_gpu_snapshots_shell_suite
1 failed, 3 passed in 2.79s
```

New execution test after the call-site fix:

```bash
lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -m pytest scripts/deploy/tests/test_check_gpu_snapshots_shell.py -q
```

Tail:

```text
FAILED scripts/deploy/tests/test_check_gpu_snapshots_shell.py::test_remote_snapshot_callsite_executes_without_repo_checkout[Makefile-assignments0]
FAILED scripts/deploy/tests/test_check_gpu_snapshots_shell.py::test_remote_snapshot_callsite_executes_without_repo_checkout[scripts/deploy/recognition-service.sh-assignments1]
2 failed, 1 passed in 2.78s
```

Syntax, rendered recipe, and diff check:

```bash
bash -n scripts/deploy/recognition-service.sh scripts/deploy/tests/test-check-gpu-snapshots.sh && make --no-print-directory -n check-gpu-snapshots-live GPU_SNAPSHOT_ENV=prod >/tmp/gpuux-h03-make-dry-run.txt && tail -12 /tmp/gpuux-h03-make-dry-run.txt && git diff --check && git status --short
```

Tail:

```text
		sudo env ACX_DESCRIBE_LOAD_DIR=/run/acx-write \
			ACX_GPU_COMPOSE_FILE="/opt/acx-backend/prod/docker-compose.env.yml" \
			ACX_GPU_SNAPSHOT_DIR=/run/acx \
			ACX_GPU_STATE_PATH=/run/acx/gpu-state.json \
			ACX_GPU_UNIT_LOAD_DIR=/run/acx-write \
			ACX_GPU_UNIT_STATE_PATH=/run/acx/gpu-state.json \
			bash "$checker"' \
```

## Mutants

Mutants could not be classified as KILLED or SURVIVED because the unmutated
execution test cannot turn green until the sibling-owned checker accepts
`ACX_GPU_UNIT_LOAD_DIR`. Running mutants against an already-red baseline would
not provide valid TEST-15 evidence.

The required pending mutations are:

```diff
# (a) Makefile only
-ACX_GPU_UNIT_LOAD_DIR=/run/acx-write
+ACX_GPU_UNIT_LOAD_PATH=/run/acx-write

# (b) recognition-service.sh only
-ACX_GPU_UNIT_LOAD_DIR=/run/acx-write
+ACX_GPU_UNIT_LOAD_PATH=/run/acx-write

# (c) either call site
-ACX_DESCRIBE_LOAD_DIR=/run/acx-write
+ACX_DESCRIBE_LOAD_DIR=/run/acx-write/prod
```

They must be run after H-04 lands; the test already labels each parameter with
its source file and preserves directory suffixes when remapping fixture paths.

## Blockers

- `scripts/deploy/check-gpu-snapshots.sh` in this checkout still declares
  `unit_load_path=${ACX_GPU_UNIT_LOAD_PATH:-}` and derives `--load-json`; it does
  not read `ACX_GPU_UNIT_LOAD_DIR`. This file is explicitly sibling-owned and
  cannot be fixed in this lane.
- `scripts/deploy/gpu-lifecycle-install.sh` still installs the pre-aggregation
  `/run/acx-write/describe-load.json` lifecycle path rather than
  `--load-dir /run/acx-write`. It is also explicitly sibling-owned.
- Consequently the mandatory lane verification and TEST-15 mutants cannot be
  completed honestly in this isolated branch.

## Findings outside ownership (do not fix)

- The stdin execution also emits `BASH_SOURCE[0]: unbound variable` before the
  install-script failure. The checker continues to its fail-closed diagnostic,
  but its repository-root initialization is not clean under the exact
  `bash -s` transport used by `recognition-service.sh`.
