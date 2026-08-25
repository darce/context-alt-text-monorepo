# Lane D — GPU-01 managed bursty GPU lifecycle

Final HEAD: recorded by the integrator after transplant.

Verification: `cd infra/oci/gpu_lifecycle && python3 -m pytest tests/ -q` → `41 passed`. Pin suite `PYTHONPATH=. python3 -m pytest scripts/test_vlm3_gpu_lifecycle.py -q` → `8 passed`.

## GPU-01a Start actuator

RED (verbatim): `ImportError: cannot import name 'OciCliStartActuator' from 'infra.oci.gpu_lifecycle.reaper'`

GREEN: 6 passed (`test_start_actuator.py`).

Commit: `feat(gpu-lifecycle): GPU-01a start actuator symmetric with stop`

TEST-15 mutant: `OciCliStartActuator.build_cmd` used `STOP` instead of `START`. RED: `AssertionError: assert 0 == 1` on `start_cmd.count("START") == 1`. Restored; production diff clean.

## GPU-01b Readiness probe

RED (verbatim): `ModuleNotFoundError: No module named 'infra.oci.gpu_lifecycle.probe'`

GREEN: probe timeout, stall exit code, and one-instance isolation tests pass.

Commit: `feat(gpu-lifecycle): GPU-01b bounded readiness probe with stall isolation`

TEST-15 mutant: `timed_out = []` instead of `list(pending)`. RED: `AssertionError: assert () == ('ocid1.gpu',)`. Restored; production diff clean.

## GPU-01c Batch-completion fence

RED (verbatim): `TypeError: GpuLifecycleController.reap_idle_instances() got an unexpected keyword argument 'batch_in_progress'`

GREEN: 6 passed (`test_batch_fence.py`). Explicit `batch_in_progress=True` never STOP; fence expiry returns `[]`. (Overclaim corrected in W3-D-02: absent key is not bulk protection.)

Commit: `feat(gpu-lifecycle): GPU-01c batch-completion fence fails closed`

TEST-15 mutant: `has_work` ignored `batch_in_progress`. RED: `AssertionError: assert [('STOP', 'ocid1.instance.oc1..gpu')] == []`. Restored; production diff clean.

## GPU-01d CPU fallback decision

RED (verbatim): `ImportError: cannot import name 'CPU_FALLBACK_PROFILE' from 'infra.oci.gpu_lifecycle.controller'`

GREEN: 3 passed (`test_cpu_fallback.py`). Boot-timeout emits `FALLBACK` / `florence_small`; ready path emits none.

Commit: `feat(gpu-lifecycle): GPU-01d emit florence_small fallback on boot failure`

TEST-15 mutant: `CPU_FALLBACK_PROFILE = "gpu_qwen30b"`. RED: `profile='gpu_qwen30b'` vs expected `florence_small`. Restored; production diff clean.

## Fix round

### W3-D-01 stall-counts-error-only

Commit: `fix(gpu-lifecycle): W3-D-01 stall-counts-error-only`

RED (verbatim): `AssertionError: assert ('ocid1.gpu',) == ()`

GREEN: `test_not_ready_does_not_count_as_stall` plus probe suite.

TEST-15 mutant: count every non-READY as no-progress. RED: `AssertionError: assert ('ocid1.gpu',) == ()`. Restored; production diff clean.

Evidence: `infra/oci/gpu_lifecycle/probe.py:99` `NOT_READY` skips stall; `infra/oci/gpu_lifecycle/reaper.py:69` `_DEFAULT_READY_MAX_CYCLES = 30`.

### W3-D-02 honest-batch-fence

Commit: `fix(gpu-lifecycle): W3-D-02 honest-batch-fence`

RED (verbatim): `AssertionError: assert 'batch_in_progress' in 'usage: __main__.py [-h] --instance-id INSTANCE_IDS [--mode {reap,start}]\n                   [--idle-seconds IDLE_SEC...t)\n  --ready-sleep-seconds READY_SLEEP_SECONDS\n                        Sleep between readiness polls (default 10s)\n'`

GREEN: absent-key idle STOP; absent-key in_flight no STOP; help/docstring warn bulk unprotected.

TEST-15 mutant: absent key → `batch_in_progress = True`. RED: `assert True is False` on `snap.batch_in_progress is False`. Restored.

Corrects GPU-01c overclaim: the fence does not protect bulk runs. It covers only `queue_depth`/`in_flight` plus an explicit `batch_in_progress: true`. Absent key is not protection.

Evidence: `infra/oci/gpu_lifecycle/reaper.py:211` absent-key warning; `infra/oci/gpu_lifecycle/reaper.py:605` `--load-json` help.

### W3-D-03 start-timeout-covers-max-wait

Commit: `fix(gpu-lifecycle): W3-D-03 start-timeout-covers-max-wait`

RED (verbatim): `TypeError: OciCliStartActuator.__init__() got an unexpected keyword argument 'max_wait_seconds'` and `AssertionError: assert 0 == 1` on `len(result.fallbacks)`.

GREEN: timeout >= 600; START failure emits `reason=start_failed` with empty actuated.

TEST-15 mutant: `_timeout_seconds = timeout_seconds` (no max). RED: `assert 120 >= 600`. Restored.

Evidence: `infra/oci/gpu_lifecycle/reaper.py:288` `max(timeout_seconds, max_wait_seconds)`; `infra/oci/gpu_lifecycle/reaper.py:526` `reason="start_failed"`.

### W3-D-04 split-load-sentinels

Commit: `fix(gpu-lifecycle): W3-D-04 split-load-sentinels`

RED (verbatim): `AssertionError: assert [(<LifecycleA... 'ocid1.gpu')] == []`

GREEN: corrupt JSON → zero START, zero STOP, loud START error.

TEST-15 mutant: skip `untrustworthy` START refuse. RED: same START-emitted assert. Restored.

Evidence: `infra/oci/gpu_lifecycle/reaper.py:60` `_BUSY_LOAD` with `untrustworthy=True`; `infra/oci/gpu_lifecycle/reaper.py:478` START refuse; `infra/oci/gpu_lifecycle/reaper.py:404` STOP refuse; `infra/oci/gpu_lifecycle/controller.py:55` `untrustworthy`.

### W3-D-05 starting-wait-unknown-fail-closed

Commit: `fix(gpu-lifecycle): W3-D-05 starting-wait-unknown-fail-closed`

RED (verbatim): `assert None is not None` (`wait_result`); `assert []` (`errors`) for STOPPING and UNKNOWN.

GREEN: STARTING waits and fallbacks without re-START; STOPPING/UNKNOWN log and refuse START.

TEST-15 mutant: `waiting_ids = []`. RED: `assert None is not None`. Restored.

Evidence: `infra/oci/gpu_lifecycle/controller.py:91` `instances_waiting_on_boot`; `infra/oci/gpu_lifecycle/controller.py:99` `instances_blocking_start`; `infra/oci/gpu_lifecycle/reaper.py:494` wait STARTING; `infra/oci/gpu_lifecycle/reaper.py:497` block STOPPING/UNKNOWN.

### W3-D-06 per-instance-probe-url

Commit: `fix(gpu-lifecycle): W3-D-06 per-instance-probe-url`

RED (verbatim): `AssertionError: assert '/ready/ocid1.a' in ['/ready/{instance_id}', '/ready/{instance_id}']` and `AssertionError: assert <ProbeStatus.READY: 'ready'> == <ProbeStatus....: 'not_ready'>`

GREEN: templated paths; missing status is NOT_READY; shared URL refuses multi-id wait.

TEST-15 mutant: shared URL + `getattr(..., 200)`. RED: same two asserts. Restored.

Evidence: `infra/oci/gpu_lifecycle/probe.py:148` `is_per_instance`; `infra/oci/gpu_lifecycle/probe.py:151` `_url_for`; `infra/oci/gpu_lifecycle/probe.py:159` missing status → NOT_READY.

### W3-D-07 tests-lens-pins

Commit: `fix(gpu-lifecycle): W3-D-07 tests-lens-pins`

RED: characterization pins of already-fixed production were green on first run. TEST-15 mutant skipped malformed-bool sentinel. RED (verbatim): `AssertionError: assert JobLoadSnapsh...tworthy=False) == JobLoadSnapsh...stworthy=True)` with `queue_depth: 0 != 1`. Restored.

GREEN: 6 named pins + tautology removed. Package `39 passed`.

## Micro fix round

### W3-D-08 refuse-shared-probe-before-start

Commit: `fix(gpu-lifecycle): W3-D-08 refuse-shared-probe-before-start`

RED (verbatim): `AssertionError: assert [(<LifecycleA...>, 'ocid1.b')] == []`

GREEN: `test_shared_http_probe_refuses_multi_id_wait` — `wait_result is None`, `actuated == []`, `actuator.started == []`.

TEST-15 mutant: drop the early return so actuation proceeds. RED (verbatim): `AssertionError: assert ReadinessWaitResult(ready=(), stalled=(), timed_out=('ocid1.a', 'ocid1.b'), errors=('ocid1.a: readiness timeout after 1 cycles', 'ocid1.b: readiness timeout after 1 cycles')) is None`. Restored; production diff clean.

Evidence: `infra/oci/gpu_lifecycle/reaper.py:516` `start_ids` before actuation; `infra/oci/gpu_lifecycle/reaper.py:535` `return StartCycleResult(..., actuated=[], ...)`.

### W3-D-09 absent-batch-key-warn-once

Commit: `fix(gpu-lifecycle): W3-D-09 absent-batch-key-warn-once`

RED (verbatim): `assert 2 == 1`

GREEN: two `snapshot()` calls emit one WARNING for absent `batch_in_progress`; malformed-value still warns every snapshot.

TEST-15 mutant: always `logger.warning` (no once-guard). RED (verbatim): `assert 2 == 1`. Restored; production diff clean.

Evidence: `infra/oci/gpu_lifecycle/reaper.py:73` `_ABSENT_BATCH_KEY_WARNED`; `infra/oci/gpu_lifecycle/reaper.py:215` DEBUG after first warn; `infra/oci/gpu_lifecycle/reaper.py:222` flag set.

## Undone

- FALLBACK is logged only; no describe-service consumer is wired.
- Producer `describe_load.py` still omits `batch_in_progress` (outside ownership). Bulk runs that never bump `queue_depth`/`in_flight` remain unprotected. This lane made the consumer honest; it did not add the producer.
- cloud-init still invokes `--mode reap` only; start/probe flags are CLI, not deployed.
- STARTING wait requires a probe; without `--ready-url` an in-flight boot is not waited or fallen back.
- Pin suite `scripts/test_vlm3_gpu_lifecycle.py` was not moved (outside ownership).
- Shared-URL single-id wait still allowed (probe cannot mask a sibling). Contract doc not updated this round (ownership was `infra/oci/gpu_lifecycle/**` only).
- Absent-key warn-once is process-global, not per path: a second load file in the same process is DEBUG.

## Canon cited

- `reversible-commitments`: START is cheap to retry; unfenced A10 burn and STOP-during-batch are the irreversible sides, so START/STOP fail closed on untrustworthy load. Shared-URL multi-id START is refused before actuation so billing does not start without a watch.
- `COST-04`: busy-on-error START would bill GPU hours without accepted captions; untrustworthy load must not count as work. Starting instances the probe cannot distinguish is cost-per-attempt, not cost-per-accepted.
- `COST-05`: readiness budget is the 5 min A10 boot peak (`30×10s`), not a 30s stall on `NOT_READY`.
- `COST-10`: boot/start failure emits `florence_small` (`readiness_timeout`/`readiness_stall`/`start_failed`) so the demo still has a cheaper path.
- `fail-loudly-succeed-quietly`: STOPPING/UNKNOWN, untrustworthy load, shared-endpoint multi-id, and probe timeout/stall log errors; idle no-work stays quiet. Absent `batch_in_progress` is the live dump's success shape — one WARNING, then DEBUG.
- `OBS-04`: WARNING every poll on an expected omitted key trains operators to ignore real malformed-value alarms; keep those WARNING every time.
- `feedback-bounded-waiting`: START subprocess timeout covers `--max-wait-seconds` so the waiter is not killed mid-boot; stall is ERROR-only.
- `designed-unknown`: `UNKNOWN` (and `STOPPING`) is a designed fail-closed state, not a silent skip.
- `TEST-15`: each finding had a production mutant that turned its pin red, then restore.
