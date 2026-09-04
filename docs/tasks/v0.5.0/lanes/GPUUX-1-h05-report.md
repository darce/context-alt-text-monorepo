# GPUUX-1 H-05 lane report

## Change summary

GPUUX1-H-05 and GPUUX1-M-06 are duplicate reports of the same deployment-gate
defect, and this change closes both. `check_snapshot` now receives an explicit
snapshot kind and validates the complete boundary shape before applying the
existing freshness checks.

- GPU state snapshots require a producer state, valid optional `instance_id`,
  state-appropriate `reason`, and valid optional `since` metadata.
- Load snapshots require non-negative integer `queue_depth` and `in_flight`;
  optional `batch_in_progress` must be a JSON boolean.
- Invalid JSON, invalid roots, and invalid `written_at` values now fail through
  explicit production errors rather than `assert`. Every schema error names the
  offending file and field/rule.
- Existing `written_at` freshness, readability, and directory checks remain in
  place.

The canonical producer enum is `GpuLifecycleState` in
`infra/oci/gpu_lifecycle/state_snapshot.py:26-33`. The checker is shipped over
stdin to a VM with no repository checkout, so importing that module at runtime
is not possible. It therefore contains a standalone tuple mirror, guarded by
`scripts/deploy/tests/test_check_gpu_snapshot_schema_parity.py`, which compares
the tuple against every canonical enum value so drift fails CI. GPU metadata
rules come from `infra/oci/gpu_lifecycle/state_snapshot.py:92-102` and
`:197-205`. Load keys/types come from the producer at
`apps/prototype-description-service/scene/application/describe_load.py:128-153`
and the contract at `docs/workbay/contracts/gpu-lifecycle.md:60-69`.

## RED evidence

Tests were added before the checker implementation. Command:

```sh
lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -c "import infra.oci.gpu_lifecycle.state_snapshot as module; print(module.__file__)"; "$resolved_python" -m pytest scripts/deploy/tests/test_check_gpu_snapshots_shell.py scripts/deploy/tests/test_check_gpu_snapshot_schema_parity.py -q
```

Tail before the fix (TEST-06):

```text
FAIL: GPU state outside the producer enum fails closed (unexpected exit 0; output: OK: GPU state and per-environment describe-load deployment contract is fresh)
FAIL: GPU state key is required (unexpected exit 0; output: OK: GPU state and per-environment describe-load deployment contract is fresh)
FAIL: degraded GPU state requires a reason (unexpected exit 0; output: OK: GPU state and per-environment describe-load deployment contract is fresh)
FAIL: GPU instance_id must be a non-blank string when present (unexpected exit 0; output: OK: GPU state and per-environment describe-load deployment contract is fresh)
FAIL: GPU reason is forbidden outside degraded state (unexpected exit 0; output: OK: GPU state and per-environment describe-load deployment contract is fresh)
FAIL: load queue_depth is required (unexpected exit 0; output: OK: GPU state and per-environment describe-load deployment contract is fresh)
FAIL: load queue_depth must be an integer (unexpected exit 0; output: OK: GPU state and per-environment describe-load deployment contract is fresh)
FAIL: load counters must be non-negative (unexpected exit 0; output: OK: GPU state and per-environment describe-load deployment contract is fresh)
FAIL: load batch flag must be a real boolean (unexpected exit 0; output: OK: GPU state and per-environment describe-load deployment contract is fresh)
FAILED scripts/deploy/tests/test_check_gpu_snapshots_shell.py::test_check_gpu_snapshots_shell_suite
FAILED scripts/deploy/tests/test_check_gpu_snapshot_schema_parity.py::test_checker_gpu_state_literal_matches_canonical_producer_enum
2 failed, 2 passed in 4.89s
```

## tests_run

Focused green command:

```sh
lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -c "import infra.oci.gpu_lifecycle.state_snapshot as module; print(module.__file__)"; "$resolved_python" -m pytest scripts/deploy/tests/test_check_gpu_snapshots_shell.py scripts/deploy/tests/test_check_gpu_snapshot_schema_parity.py -q
```

```text
/home/gate/grok-sandbox/feature-gpuux-1-h05-7a33b42c/infra/oci/gpu_lifecycle/state_snapshot.py
....                                                                     [100%]
4 passed in 4.47s
```

Full deploy-test command before mutation checks:

```sh
lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -c "import infra.oci.gpu_lifecycle.state_snapshot as module; print(module.__file__)"; "$resolved_python" -m pytest scripts/deploy/tests -q
```

```text
/home/gate/grok-sandbox/feature-gpuux-1-h05-7a33b42c/infra/oci/gpu_lifecycle/state_snapshot.py
...................                                                      [100%]
19 passed in 4.22s
```

Post-mutation final verification repeated the required focused target and the
whole deploy-test directory:

```sh
lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -c "import infra.oci.gpu_lifecycle.state_snapshot as module; print(module.__file__)"; "$resolved_python" -m pytest scripts/deploy/tests/test_check_gpu_snapshots_shell.py -q; "$resolved_python" -m pytest scripts/deploy/tests -q; git diff --check; /bin/bash -n scripts/deploy/check-gpu-snapshots.sh scripts/deploy/tests/test-check-gpu-snapshots.sh
```

```text
/home/gate/grok-sandbox/feature-gpuux-1-h05-7a33b42c/infra/oci/gpu_lifecycle/state_snapshot.py
...                                                                      [100%]
3 passed in 4.00s
...................                                                      [100%]
19 passed in 4.49s
```

Syntax/diff checks:

```sh
git diff --check
/bin/bash -n scripts/deploy/check-gpu-snapshots.sh scripts/deploy/tests/test-check-gpu-snapshots.sh
```

Both completed with no output (success).

Python lint command:

```sh
lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -m ruff check --fix scripts/deploy/tests/test_check_gpu_snapshot_schema_parity.py; "$resolved_python" -m ruff check scripts/deploy/tests/test_check_gpu_snapshots_piped.py scripts/deploy/tests/test_check_gpu_snapshot_schema_parity.py
```

```text
Found 1 error (1 fixed, 0 remaining).
All checks passed!
```

## Mutants

Each mutant used:

```sh
lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -m pytest scripts/deploy/tests/test_check_gpu_snapshots_shell.py -q
```

### (a) Delete state-enum membership check — KILLED

Diff:

```diff
-    if not isinstance(state, str) or state not in valid_gpu_states:
+    if not isinstance(state, str):
```

Exact pytest tail:

```text
FAIL: GPU state outside the producer enum fails closed (unexpected exit 0; output: OK: GPU state and per-environment describe-load deployment contract is fresh)
FAILED: 1 case(s)
scripts/deploy/tests/test_check_gpu_snapshots_shell.py:169: AssertionError
=========================== short test summary info ============================
FAILED scripts/deploy/tests/test_check_gpu_snapshots_shell.py::test_check_gpu_snapshots_shell_suite
1 failed, 2 passed in 4.09s
```

### (b) Delete load required-key check — KILLED

Diff:

```diff
-        if field not in payload:
-            fail(f"{field} is required")
```

Exact pytest tail:

```text
FAIL: load queue_depth is required (missing error 'queue_depth is required'; output: Traceback (most recent call last):
  File "<string>", line 66, in <module>
KeyError: 'queue_depth'
ERROR: describe load (dev) snapshot failed schema validation: /tmp/tmp.hgEFhMHCAw/run/acx-write/dev/describe-load.json)
FAILED: 1 case(s)
scripts/deploy/tests/test_check_gpu_snapshots_shell.py:169: AssertionError
=========================== short test summary info ============================
FAILED scripts/deploy/tests/test_check_gpu_snapshots_shell.py::test_check_gpu_snapshots_shell_suite
1 failed, 2 passed in 4.42s
```

### (c) Accept arbitrary numeric counters — KILLED

Diff:

```diff
-        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
+        if isinstance(value, bool) or not isinstance(value, (int, float)):
```

Exact pytest tail:

```text
FAIL: load counters must be non-negative (unexpected exit 0; output: OK: GPU state and per-environment describe-load deployment contract is fresh)
FAILED: 1 case(s)
scripts/deploy/tests/test_check_gpu_snapshots_shell.py:169: AssertionError
=========================== short test summary info ============================
FAILED scripts/deploy/tests/test_check_gpu_snapshots_shell.py::test_check_gpu_snapshots_shell_suite
1 failed, 2 passed in 10.06s
```

### (d) Replace explicit validation with `assert` under `python3 -O` — KILLED

Diff:

```diff
-    written_at=$(python3 -c '
+    written_at=$(python3 -O -c '
-    if not isinstance(state, str) or state not in valid_gpu_states:
-        fail(f"state must be one of {valid_gpu_states}")
+    assert isinstance(state, str) and state in valid_gpu_states
```

Optimized Python deleted the assertion and accepted `state: bogus`; the test
therefore exposed the validation bypass and killed the mutant. Exact pytest
tail:

```text
FAIL: GPU state outside the producer enum fails closed (unexpected exit 0; output: OK: GPU state and per-environment describe-load deployment contract is fresh)
FAILED: 1 case(s)
scripts/deploy/tests/test_check_gpu_snapshots_shell.py:169: AssertionError
=========================== short test summary info ============================
FAILED scripts/deploy/tests/test_check_gpu_snapshots_shell.py::test_check_gpu_snapshots_shell_suite
1 failed, 2 passed in 7.80s
```

All four mutations were reverted before final verification.

## Blockers

None.

## Findings noticed outside ownership

- `infra/oci/gpu_lifecycle/load_source.py:155-157` converts counters with
  `int(...)`, so values such as the string `"0"` can be accepted by that reader
  even though the producer and deployment boundary contract require JSON
  integers. This lane did not change the consumer.
