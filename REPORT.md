# Lane D — GPU-01 managed bursty GPU lifecycle

Final HEAD: recorded by the integrator after transplant.

Verification: `cd apps/prototype-description-service && uv run --extra dev pytest ../../infra/oci/gpu_lifecycle/tests/` → `20 passed`. Pin suite `scripts/test_vlm3_gpu_lifecycle.py` → `8 passed`.

## GPU-01a Start actuator

RED (verbatim): `ImportError: cannot import name 'OciCliStartActuator' from 'infra.oci.gpu_lifecycle.reaper'`

GREEN: 6 passed (`test_start_actuator.py`).

Commit: `feat(gpu-lifecycle): GPU-01a start actuator symmetric with stop`

TEST-15 mutant: `OciCliStartActuator.build_cmd` used `STOP` instead of `START`. RED: `AssertionError: assert 0 == 1` on `start_cmd.count("START") == 1`. Restored; production diff clean.

Evidence: `infra/oci/gpu_lifecycle/controller.py:64` `start_needed_instances`; `infra/oci/gpu_lifecycle/reaper.py:78` `InstanceStartActuator`; `infra/oci/gpu_lifecycle/reaper.py:82` `build_instance_action_cmd`; `infra/oci/gpu_lifecycle/reaper.py:246` `OciCliStartActuator`; `infra/oci/gpu_lifecycle/reaper.py:428` `run_start_cycle`.

## GPU-01b Readiness probe

RED (verbatim): `ModuleNotFoundError: No module named 'infra.oci.gpu_lifecycle.probe'`

GREEN: probe timeout, stall exit code, and one-instance isolation tests pass.

Commit: `feat(gpu-lifecycle): GPU-01b bounded readiness probe with stall isolation`

TEST-15 mutant: `timed_out = []` instead of `list(pending)`. RED: `AssertionError: assert () == ('ocid1.gpu',)`. Restored; production diff clean.

Evidence: `infra/oci/gpu_lifecycle/probe.py:39` stall/timeout `exit_code == 1`; `infra/oci/gpu_lifecycle/probe.py:46` `WarmReadinessWait`; `infra/oci/gpu_lifecycle/probe.py:115` timeout population; `infra/oci/gpu_lifecycle/probe.py:118` loud timeout error.

## GPU-01c Batch-completion fence

RED (verbatim): `TypeError: GpuLifecycleController.reap_idle_instances() got an unexpected keyword argument 'batch_in_progress'`

GREEN: 6 passed (`test_batch_fence.py`). Idle+batch never STOP; fence expiry returns `[]`.

Commit: `feat(gpu-lifecycle): GPU-01c batch-completion fence fails closed`

TEST-15 mutant: `has_work` ignored `batch_in_progress`. RED: `AssertionError: assert [('STOP', 'ocid1.instance.oc1..gpu')] == []`. Restored; production diff clean.

Evidence: `infra/oci/gpu_lifecycle/controller.py:49` `batch_in_progress`; `infra/oci/gpu_lifecycle/controller.py:54` `has_work` includes batch; `infra/oci/gpu_lifecycle/controller.py:89` reap refuses STOP during batch; `infra/oci/gpu_lifecycle/controller.py:111` fence expiry / missing sample fail closed; `infra/oci/gpu_lifecycle/reaper.py:388` `fence_expired`.

## GPU-01d CPU fallback decision

RED (verbatim): `ImportError: cannot import name 'CPU_FALLBACK_PROFILE' from 'infra.oci.gpu_lifecycle.controller'`

GREEN: 3 passed (`test_cpu_fallback.py`). Boot-timeout emits `FALLBACK` / `florence_small`; ready path emits none.

Commit: `feat(gpu-lifecycle): GPU-01d emit florence_small fallback on boot failure`

TEST-15 mutant: `CPU_FALLBACK_PROFILE = "gpu_qwen30b"`. RED: `profile='gpu_qwen30b'` vs expected `florence_small`. Restored; production diff clean.

Evidence: `infra/oci/gpu_lifecycle/controller.py:23` `CPU_FALLBACK_PROFILE = "florence_small"`; `infra/oci/gpu_lifecycle/controller.py:27` `FallbackDecision`; `infra/oci/gpu_lifecycle/controller.py:115` `fallback_on_boot_failure`; `infra/oci/gpu_lifecycle/reaper.py:363` `fallbacks`; `infra/oci/gpu_lifecycle/reaper.py:475` `reason="readiness_timeout"`.

## Undone

- FALLBACK is emitted and logged only; no describe-service consumer is wired (brief: emit, do not wire).
- Load-snapshot producer (`scene/application/describe_load.py`) still writes `{queue_depth,in_flight,written_at}` without `batch_in_progress` — outside ownership. Absent key → false; STOP still fenced by `in_flight`/`queue_depth`. Malformed key fail-closes.
- `HttpReadinessProbe` has no HTTP-server unit test; wait-loop tests inject fakes.
- cloud-init still invokes `--mode reap` only; start/probe flags are CLI, not deployed.
- Existing pin tests in `scripts/test_vlm3_gpu_lifecycle.py` were not moved (outside ownership).

## Canon cited

- `reversible-commitments`: START+STOP is the cheap reversible pair; STOP during a live batch is the irreversible billing/work-loss side, so the fence fails closed.
- `COST-05`: wait bound is sized to the 5 min boot+load peak, not mean idle, so a hung START cannot sit on the A10 hour.
- `COST-10`: readiness budget breach emits `florence_small` so the demo still has a cheaper alt-text path instead of zero captions.
- `fail-loudly-succeed-quietly`: probe timeout/stall writes errors and nonzero exit; first-sample READY is quiet (`errors == ()`, exit 0).
- `TEST-15`: each item had a production mutant that turned its assertion red, then restore.
