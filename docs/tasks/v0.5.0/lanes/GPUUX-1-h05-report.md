# GPUUX-1 H-05 snapshot freshness report

## Change summary

- `read_previous_gpu_state()` now validates the whole snapshot before returning
  a state: `written_at` must be finite numeric UTC epoch seconds, no more than
  5 seconds in the future, and no older than 180 seconds.
- Invalid `instance_id` and `reason` shapes fail closed to `None`, so live OCI
  instance state reduction determines the next published state.
- The keyword-only `now`, `max_age_seconds`, and `max_future_skew_seconds`
  parameters preserve the existing positional call from `reaper.py`.
- The 180-second producer default is locked to the real consumer default by a
  cross-package contract test. The existing contract states at
  `docs/workbay/contracts/gpu-lifecycle.md`: “default 180 s”.
- Atomic temp-file-plus-rename publication and the reaper flock were unchanged.

## RED evidence

The required tests were added before the implementation and run once against
the vulnerable reader. Exact pytest tail:

```text
FAILED infra/oci/gpu_lifecycle/tests/test_state_snapshot.py::test_previous_snapshot_rejects_invalid_contract_metadata[degraded-ocid1.gpu-None]
FAILED infra/oci/gpu_lifecycle/tests/test_state_snapshot.py::test_previous_snapshot_rejects_invalid_contract_metadata[degraded-ocid1.gpu-]
13 failed, 41 passed in 6.99s
```

The failures were `TypeError: read_previous_gpu_state() got an unexpected
keyword argument 'now'`, proving the new freshness behavior was absent.

## tests_run

Import-origin check plus RED run:

```sh
lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -c "import infra.oci.gpu_lifecycle.state_snapshot as module; print(module.__file__)"; "$resolved_python" -m pytest infra/oci/gpu_lifecycle/tests/test_state_snapshot.py infra/oci/gpu_lifecycle/tests/test_state_snapshot_contract.py -q
```

Import origin:

```text
/home/gate/grok-sandbox/feature-gpuux-1-h05-7a33b42c/infra/oci/gpu_lifecycle/state_snapshot.py
```

First implementation run:

```sh
lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -m pytest infra/oci/gpu_lifecycle/tests/test_state_snapshot.py infra/oci/gpu_lifecycle/tests/test_state_snapshot_contract.py -q
```

```text
FAILED infra/oci/gpu_lifecycle/tests/test_state_snapshot.py::test_reap_cycle_refreshes_ready_without_demoting_it
1 failed, 53 passed in 0.59s
```

The prior regression fixture used `written_at=1.0`; it was corrected to create
a genuinely fresh writer-produced snapshot.

Green run before mutation testing:

```sh
lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -m pytest infra/oci/gpu_lifecycle/tests/test_state_snapshot.py infra/oci/gpu_lifecycle/tests/test_state_snapshot_contract.py -q
```

```text
.......................................................                  [100%]
55 passed in 1.10s
```

Each mutant below used that same exact pytest command.

Final post-mutant verification (with the import-origin check repeated):

```sh
lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -c "import infra.oci.gpu_lifecycle.state_snapshot as module; print(module.__file__)"; "$resolved_python" -m pytest infra/oci/gpu_lifecycle/tests/test_state_snapshot.py infra/oci/gpu_lifecycle/tests/test_state_snapshot_contract.py -q; git diff --check
```

```text
/home/gate/grok-sandbox/feature-gpuux-1-h05-7a33b42c/infra/oci/gpu_lifecycle/state_snapshot.py
.......................................................                  [100%]
55 passed in 0.96s
```

## mutants

### A: delete the age check — KILLED

```diff
-    if current_time - written_at > max_age_seconds:
-        return None
```

Exact pytest tail:

```text
FAILED infra/oci/gpu_lifecycle/tests/test_state_snapshot.py::test_stale_ready_snapshot_is_not_preserved
1 failed, 54 passed in 0.87s
```

### B: invert the future-skew comparison — KILLED

```diff
-    if written_at - current_time > max_future_skew_seconds:
+    if written_at - current_time < max_future_skew_seconds:
```

Exact pytest tail:

```text
FAILED infra/oci/gpu_lifecycle/tests/test_state_snapshot.py::test_future_dated_ready_snapshot_is_not_preserved
FAILED infra/oci/gpu_lifecycle/tests/test_state_snapshot.py::test_fresh_ready_snapshot_is_preserved_for_running_instance
FAILED infra/oci/gpu_lifecycle/tests/test_state_snapshot.py::test_written_snapshot_round_trips_to_previous_state_within_freshness_bound
FAILED infra/oci/gpu_lifecycle/tests/test_state_snapshot.py::test_reap_cycle_refreshes_ready_without_demoting_it
4 failed, 51 passed in 0.94s
```

### C: replace the max-age default with infinity — KILLED

```diff
-    max_age_seconds: float = DEFAULT_PREVIOUS_GPU_STATE_MAX_AGE_SECONDS,
+    max_age_seconds: float = float("inf"),
```

Exact pytest tail:

```text
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED infra/oci/gpu_lifecycle/tests/test_state_snapshot.py::test_stale_ready_snapshot_is_not_preserved
FAILED infra/oci/gpu_lifecycle/tests/test_state_snapshot.py::test_future_dated_ready_snapshot_is_not_preserved
FAILED infra/oci/gpu_lifecycle/tests/test_state_snapshot.py::test_fresh_ready_snapshot_is_preserved_for_running_instance
FAILED infra/oci/gpu_lifecycle/tests/test_state_snapshot.py::test_written_snapshot_round_trips_to_previous_state_within_freshness_bound
FAILED infra/oci/gpu_lifecycle/tests/test_state_snapshot.py::test_reap_cycle_refreshes_ready_without_demoting_it
FAILED infra/oci/gpu_lifecycle/tests/test_state_snapshot.py::test_reap_publish_cannot_be_overwritten_by_stale_start_read
6 failed, 49 passed, 1 warning in 2.94s
```

All mutants were reverted after their runs.

## blockers

None.

## findings you noticed outside your ownership

None.
