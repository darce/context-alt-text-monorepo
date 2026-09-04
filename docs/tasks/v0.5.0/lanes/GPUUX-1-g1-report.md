# GPUUX-1 lane G1 report

Implemented all four lifecycle remediations with RED-first coverage. The
finding bodies live in WorkBay handoff; see `GPUUX1-H-01`, `GPUUX1-H-02`,
`GPUUX1-M-04` and `GPUUX1-M-05` on task ref `GPUUX-1`.

Steady-state OCI `RUNNING` instances now participate in bounded readiness waits
whenever a probe is configured; current probe evidence promotes warming to ready
and demotes ready to degraded, while shared HTTP endpoint refusal and
per-instance failure isolation remain intact. `RUNNING` no longer preserves the
prior `starting` state — with no readiness URL the producer advances to
`warming`. The atomic producer emits `instance_id`, `reason` and state-change
`since` alongside `state` and `written_at`, and degraded snapshots require a
non-blank reason through explicit production validation; the live
describe-service reader accepts the enriched payload and retains its freshness
behavior. Missing, empty and whitespace-only `ACX_GPU_STATE_PATH` values resolve
to the same default in producer and consumer.

RED was recorded before implementation as `8 failed, 20 passed` in `test_state_snapshot.py`. The complete non-network lane selection is green at `119 passed, 2 deselected`. The mandatory unchanged command reaches `119 passed` but its two localhost HTTP-server tests fail before exercising application code because this managed sandbox denies socket creation with `PermissionError: [Errno 1] Operation not permitted`.

No additional lane findings were discovered.

```json
{"findings":[],"blockers":["Managed sandbox denies localhost socket creation, blocking two unchanged HTTP readiness integration tests; all 119 non-network tests pass."],"tests_run":"RED: python -m pytest infra/oci/gpu_lifecycle/tests/test_state_snapshot.py -q => 8 failed, 20 passed. GREEN: python -m pytest infra/oci/gpu_lifecycle/tests/test_state_snapshot.py infra/oci/gpu_lifecycle/tests/test_state_snapshot_contract.py apps/prototype-description-service/scene/tests/test_gpu_state.py -q => 52 passed; python -m pytest infra/oci/gpu_lifecycle/tests apps/prototype-description-service/scene/tests/test_gpu_state.py -q -k 'not test_http_probe_templates_instance_id_into_url and not test_http_readiness_probe_local_server_2xx_non_2xx_urlerror' => 119 passed, 2 deselected; mandatory unchanged pytest command => 119 passed, 2 sandbox-blocked; ruff check => passed; mypy => passed.","handoff_action":"needs_guidance"}
```
