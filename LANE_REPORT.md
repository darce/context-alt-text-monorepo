# GPU lane report

## DEMO-UX-1-GPU-01 — FIXED

canon rows satisfied:

- INT-08 — the exported `GpuServingStatus.GPU_WARMING` state makes the long warm-up visible; the queued job remains the independently cancellable unit while lifecycle actuation stays out of band.
- INT-10 — enum-backed serving status exposes current state and the `START`/`STOP` decision contract exposes the controller's next action.
- RLSE-05 — START actuator exceptions are logged, returned in `ReapCycleResult.errors`, and make the CLI exit non-zero instead of reporting a successful warm cycle.

what changed (files + why):

- `infra/oci/gpu_lifecycle/controller.py` — added the pure START/STOP/no-op decision, enum-backed instance states/actions, the exported serving-status contract, and the active-session heartbeat gate. Reaping now requires idle job load **and** `active_sessions == 0`; a viewer heartbeat therefore prevents a STOP even after four idle minutes.
- `infra/oci/gpu_lifecycle/reaper.py` — wired START decisions through an `InstanceLifecycleActuator.start_instance` interface and the existing OCI CLI boundary, retained the pre-STOP fence, parsed optional `active_sessions` fail-safe from the load snapshot, and surfaced START failures durably.
- `infra/oci/gpu_lifecycle/__init__.py` — exports the cross-lane enum contracts.
- `scripts/test_vlm3_gpu_lifecycle.py` — added the parametrised truth table over `(state, queue_depth, in_flight, idle_for_seconds)`, warm status/actuation/failure tests, and the explicit four-minute active-viewer case.

Exported status symbol: `GpuServingStatus` (`enum.StrEnum`), importable from `infra.oci.gpu_lifecycle`. Its values are `GPU_OFFLINE = "gpu_offline"`, `GPU_WARMING = "gpu_warming"`, and `GPU_READY = "gpu_ready"`.

RED output (test-first lanes):

Command (the repo root must be on `PYTHONPATH` because the prescribed app working directory otherwise cannot import `infra`):

```text
$ cd apps/prototype-description-service
$ PYTHONPATH=../.. uv run --extra dev pytest ../../scripts/test_vlm3_gpu_lifecycle.py -q

==================================== ERRORS ====================================
_____________ ERROR collecting scripts/test_vlm3_gpu_lifecycle.py ______________
ImportError while importing test module '/home/ubuntu/w/dux-gpu/scripts/test_vlm3_gpu_lifecycle.py'.
../../scripts/test_vlm3_gpu_lifecycle.py:6: in <module>
    from infra.oci.gpu_lifecycle.controller import (
E   ImportError: cannot import name 'GpuInstanceState' from 'infra.oci.gpu_lifecycle.controller' (/home/ubuntu/w/dux-gpu/infra/oci/gpu_lifecycle/controller.py)
=========================== short test summary info ============================
ERROR ../../scripts/test_vlm3_gpu_lifecycle.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.18s
```

GREEN output:

```text
$ cd apps/prototype-description-service
$ PYTHONPATH=../.. uv run --extra dev pytest ../../scripts/test_vlm3_gpu_lifecycle.py -q
...................                                                      [100%]
19 passed in 0.09s

$ PYTHONPATH=../.. uv run --extra dev ruff check ../../infra/oci/gpu_lifecycle ../../scripts/test_vlm3_gpu_lifecycle.py
All checks passed!

$ PYTHONPATH=../.. uv run --extra dev ruff format --check ../../infra/oci/gpu_lifecycle ../../scripts/test_vlm3_gpu_lifecycle.py
5 files already formatted
```

residual risk / what a reviewer should attack:

- The heartbeat interface is intentionally backward-compatible: snapshots without `active_sessions` read as zero. The session-owning lane must write a fresh positive count while a viewer is active; stale/unreadable snapshots remain fail-safe busy. Review the producer-to-file heartbeat expiry semantics when that lane is merged.
- START is unit-tested through a recording actuator only. No live OCI command, credential, OCID, or instance was used in this lane. Exercise the dry-run/operator integration before deployment and verify the configured principal has the existing `INSTANCE_POWER_ACTIONS` permission.
- Running the exact prescribed command without `PYTHONPATH=../..` fails before collection with `ModuleNotFoundError: No module named 'infra'`; focused verification used the same app environment with the repository root added to the import path.
