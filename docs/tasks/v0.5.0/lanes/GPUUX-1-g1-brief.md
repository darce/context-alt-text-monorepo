# GPUUX-1 lane G1 — GPU lifecycle state machine: readiness coverage + snapshot contract

Branch `feature/gpuux-1-g1`, worktree `context-alt-text-monorepo-gpuux-1-g1`, base `56a3d288a`.

Four findings, all in one lane because they share `state_snapshot.py` and are
semantically coupled: H-02's fix is meaningless without H-01's probe coverage.

## H-01 (high) — `infra/oci/gpu_lifecycle/reaper.py`

`wait_ids` is built only from newly-actuated instances plus
`controller.instances_waiting_on_boot(...)` (OCI STARTING). Already-RUNNING
instances are never re-probed. There is also an early return
(`if not decided and not waiting_ids and not errors: return StartCycleResult(...)`)
that skips the readiness path entirely on steady-state cycles.

Consequence: a warming instance can never be promoted to `ready`, and a `ready`
instance can never be demoted to `degraded` when readiness starts failing. Every
timer cycle instead republishes the previous state as if it were fresh evidence.

Fix: include applicable RUNNING instances in periodic readiness probes and derive
`ready` / `warming` / `degraded` from the *current* probe result. Preserve the
existing `HttpReadinessProbe` shared-endpoint refusal (a single non-templated URL
must still refuse multi-id waits — a healthy sibling must not mask a dead one) and
rg-007 per-instance isolation.

## H-02 (high) — `state_snapshot.py:83-94` `state_for_instances`

When WARMING is in `mapped` and `previous_state` is one of
{STARTING, WARMING, READY, DEGRADED}, the code removes WARMING and re-adds
`previous_state`. With the installer default of **no** `--ready-url`, a successful
start writes `starting` and every later cycle re-derives `starting` forever, even
though OCI proves the instance RUNNING.

Fix: do not preserve STARTING once OCI reports RUNNING. Publish `warming` until
current readiness evidence supports `ready` or `degraded`.

## M-04 (medium) — `state_snapshot.py:107-140` contract mismatch

`docs/workbay/contracts/gpu-lifecycle.md` documents `instance_id`, `reason` and
`since`, and requires `reason` for degraded states. `write_gpu_state_snapshot`
emits only `{state, written_at}`. Tests assert the reduced payload, so the
mismatch is locked in rather than detected.

Fix: either implement the documented fields (including state-change timestamps and
degraded reasons) or explicitly revise the contract in this same slice. Do not
leave contract and producer disagreeing. If you revise the contract, say so
plainly in the report.

Consumer constraint: `apps/prototype-description-service/scene/application/gpu_state.py`
`read_gpu_state()` parses this file and is live-wired into `DescribeRunResponse`
on this branch. Any payload change must keep that reader working — extend it in
the same slice if needed, and keep `written_at` freshness semantics intact.

## M-05 (medium) — `state_snapshot.py:45-47` path normalization

Producer: `Path(os.environ.get(GPU_STATE_PATH_ENV, DEFAULT_GPU_STATE_PATH))` — an
empty `ACX_GPU_STATE_PATH` yields `Path('.')`.
Consumer (`scene/application/gpu_state.py:45-50`) treats empty/whitespace-only as
the default path. The writer can therefore target a different location than the
reader.

Fix: normalize missing, empty and whitespace-only identically on both sides,
ideally through one shared path contract. Add producer-side blank-value tests.

## Requirements

- **TDD, RED first.** Each of the four gets a failing test before the fix. Include
  the recovery and post-ready-failure cases H-01 calls out explicitly.
- Preserve atomic publish: `write_gpu_state_snapshot` writes temp + rename. Do not
  convert it to an in-place write — a downstream file-level bind mount would pin a
  stale inode.
- `GpuLifecycleState` is the producer's permitted vocabulary (no `unknown`). Do not
  add a state without updating `scene/application/gpu_state.GpuState` and the
  frontend `GPU_STATE` union in the same slice — an unmatched backend state is
  exactly the class of defect this branch just fixed.
- sr-006: no `assert` for production validation; raise explicit exceptions.
- rg-007: one instance's failure must not halt others in the same cycle.
- rg-008: fail fast on malformed config rather than silently defaulting.

## Do NOT

- Do not touch `docker-compose.env.yml` or the `/run/acx` mount layout — lane G2
  owns that file. Touching it will conflict.
- Do not edit any frontend/JS or PHP file.
- Do not modify the GPUUX-1 task plan.
- Do not relax or delete an existing assertion to make a test pass (sr-001).

## Verify

`cd /Users/daniel/Development/context-alt-text-monorepo-gpuux-1-g1 && python -m pytest infra/oci/gpu_lifecycle/tests -q`
plus `python -m pytest apps/prototype-description-service/scene/tests/test_gpu_state.py -q`.
Both must pass. Report the RED counts before and the GREEN counts after.

## Harvest contract (MANDATORY)

The orchestrator's automatic findings harvest is broken for this backend, so you
must deliver findings twice:

1. Write `docs/tasks/v0.5.0/lanes/GPUUX-1-g1-report.md`, commit it on this branch,
   and end that file with a fenced ```json block:
   `{"findings": [{"finding_id": "...", "severity": "high|medium|low", "file_path": "...", "description": "...", "fix": "..."}], "blockers": [], "tests_run": "...", "handoff_action": "..."}`
2. Repeat that identical JSON verbatim in your final handoff summary text.

If you found no new issues, emit `{"findings": [], ...}` explicitly. Never omit
the block.
