# GPUUX-1 H-06 worker report

## Change summary

- Replaced the aggregate `STOPPED` shortcut in `run_reap_cycle` with a full
  `state_for_instances(...)` reduction over post-actuation instance states.
- Only instance IDs present in successful `actuated` or `lease_expired` STOP
  outcomes are rewritten to `STOPPED`. Untargeted instances and failed STOP
  instances keep their observed state.
- Publish `DEGRADED` with `reason=lifecycle_error` when the reap result contains
  lifecycle errors, so a failed normal or lease-expiry STOP is not silent.
- Preserved the serialized publish lock, aggregate `_snapshot_instance_id`
  behavior, and `_state_reason` reason vocabulary.
- Added regression coverage for a partial idle stop, a mixed STOP
  success/failure, all STOPs succeeding, and a failed lease-expiry STOP.

## RED evidence

Command (with the lane interpreter resolved immediately before invocation):

```text
"$resolved_python" -m pytest infra/oci/gpu_lifecycle/tests/test_batch_fence.py -q
```

Tail before the production change:

```text
FAILED infra/oci/gpu_lifecycle/tests/test_batch_fence.py::test_partial_stop_publishes_state_of_still_running_instance
FAILED infra/oci/gpu_lifecycle/tests/test_batch_fence.py::test_failed_stop_remains_in_full_state_reduction
FAILED infra/oci/gpu_lifecycle/tests/test_batch_fence.py::test_failed_lease_expiry_stop_does_not_publish_stopped
3 failed, 13 passed in 0.82s
```

The partial-stop test observed fabricated `state=stopped`; the mixed-outcome
test proved `state_for_instances` was not called; and the failed lease STOP
published `warming` rather than surfacing its lifecycle error.

## tests_run

Interpreter/import-origin check:

```text
"$resolved_python" -c "import infra.oci.gpu_lifecycle.reaper as module; print(module.__file__)"
/home/gate/grok-sandbox/feature-gpuux-1-h06-9fd5fe31/infra/oci/gpu_lifecycle/reaper.py
```

Lane test after implementation and after all mutants were restored:

```text
"$resolved_python" -m pytest infra/oci/gpu_lifecycle/tests/test_batch_fence.py -q
................                                                         [100%]
16 passed in 0.22s
```

Related snapshot and max-lease regression tests:

```text
"$resolved_python" -m pytest infra/oci/gpu_lifecycle/tests/test_state_snapshot.py infra/oci/gpu_lifecycle/tests/test_max_lease.py -q
........................................................                 [100%]
56 passed in 1.21s
```

Additional full GPU lifecycle test sweep:

```text
"$resolved_python" -m pytest infra/oci/gpu_lifecycle/tests -q
FAILED infra/oci/gpu_lifecycle/tests/test_readiness_probe.py::test_http_probe_templates_instance_id_into_url
FAILED infra/oci/gpu_lifecycle/tests/test_readiness_probe.py::test_http_readiness_probe_local_server_2xx_non_2xx_urlerror
2 failed, 112 passed in 2.60s
```

Both failures occur while constructing `HTTPServer(("127.0.0.1", 0), ...)`:
the managed sandbox denies socket creation with `PermissionError: [Errno 1]
Operation not permitted`. Neither failure exercises this lane's changed files.

## Mutants

Each mutant was applied alone, tested with the lane command, and reverted.

### (a) Restore the aggregate STOPPED shortcut — KILLED

```diff
-        state = state_for_instances(
-            [instance.state for instance in post_actuation_instances],
-            previous_state=read_previous_gpu_state(gpu_state_path),
+        state = (
+            GpuLifecycleState.STOPPED
+            if result.actuated or result.lease_expired
+            else state_for_instances(
+                [instance.state for instance in post_actuation_instances],
+                previous_state=read_previous_gpu_state(gpu_state_path),
+            )
         )
```

```text
FAILED infra/oci/gpu_lifecycle/tests/test_batch_fence.py::test_partial_stop_publishes_state_of_still_running_instance
FAILED infra/oci/gpu_lifecycle/tests/test_batch_fence.py::test_failed_stop_remains_in_full_state_reduction
2 failed, 14 passed in 0.18s
```

### (b) Mark every targeted instance STOPPED — KILLED

```diff
-            for action, instance_id in [*result.actuated, *result.lease_expired]
+            for action, instance_id in [*result.decided, *result.lease_expired]
```

```text
E       AssertionError: assert [['STOPPED', 'STOPPED']] == [['RUNNING', 'STOPPED']]
FAILED infra/oci/gpu_lifecycle/tests/test_batch_fence.py::test_failed_stop_remains_in_full_state_reduction
1 failed, 15 passed in 0.33s
```

### (c) Drop a failed STOP instance from reduction — KILLED

```diff
             for instance in instances
+            if instance.instance_id in stopped_instance_ids
+            or instance.instance_id not in {
+                instance_id for _, instance_id in result.decided
+            }
```

```text
E       AssertionError: assert [['STOPPED']] == [['RUNNING', 'STOPPED']]
FAILED infra/oci/gpu_lifecycle/tests/test_batch_fence.py::test_failed_stop_remains_in_full_state_reduction
1 failed, 15 passed in 0.42s
```

## Blockers

No lane blocker. The required lane test and directly related regression suites
pass. The optional full-suite verification has the sandbox socket limitation
recorded above.

## Findings outside ownership

- The two readiness-probe tests require local socket creation, which is denied
  by this execution sandbox. No out-of-scope code change was made.
