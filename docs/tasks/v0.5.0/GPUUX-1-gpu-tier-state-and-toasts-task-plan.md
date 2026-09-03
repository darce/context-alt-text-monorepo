# Task Plan — GPUUX-1

> - **Date**: 2026-09-02
> - **Author**: Claude Fable 5.1 (operator session)
> - **Project**: context-alt-text-monorepo (description-service + WP plugin)
> - **Task ID**: `GPUUX-1`
> - **Target Branch**: `feature/gpuux-1`
> - **Review Coverage Target**: 1 local + ≥2 grok-remote per wave (`/wb-review-slice`)
> - **Derived from**: `apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.uxmap.{json,md}`, decision `claude_gpuux1_open_lane_dag_w1_w2_w3`

---

## GPUUX-1. Surface burst-GPU lifecycle state in the describe UI

## Objective

Replace the `gpu_state: null` placeholder on `DescribeRunResponse` with a live, single-writer GPU state (`unknown|stopped|starting|warming|ready|degraded`) and render it in the Workbench describe flow: a tier chip on the progress zone, an upgrade notice on apply, and edge-triggered toasts. Nothing in the UI derives GPU state locally; the lifecycle controller is the only writer.

## Problem Statement

`gpu_state` is a typed-null placeholder end to end (`scene/interface_adapters/http/routers/describe_run.py` `_run_response`, `class-describe-controller.php` passthrough, `describeApi.ts` `gpu_state: null`). A cold GPU costs ~104 s to health 200 (GPUUX-1 smoke, test 1449) and the operator sees a stalled bar with no explanation — the exact silent failure DEMO-UX-1-GPU-01 names. Toasts for GPU transitions do not exist.

## Constraints

- **Single writer** (DATA-14): only `infra.oci.gpu_lifecycle` writes `/run/acx/gpu-state.json`; API reads; PHP/SPA pass through (rg-015).
- **Fail closed to `unknown`** (OBS-08, RLSE-05): missing/stale/corrupt snapshot → `unknown`, logged once per transition.
- **Enum centralised** (sr-007): Python `StrEnum`, TS `as const`, PHP passthrough only.
- **Toasts are edge-triggered** (PERC-05/07, A11Y-21): one toast per state transition, suppressed while the progress zone is on screen, never on poll ticks.
- **Design tokens only** in CSS (sr-004); status colour always paired with an icon.
- **All tests run on the remote VM** via grok-remote lanes; local Claude reviews only.
- **Excluded from this task**: reaper lease bug (fixed elsewhere) and the VM end-to-end run that depends on it.

## Lane DAG (GRPH-01/09/31/32)

```
L0 contract ──► W1 { B env/producer , C API reader , F lifecycle writer }
                      C ──► W2 { D PHP passthrough , E1 FE states }
                                     E1 ──► W3 { E2 toasts }
```

No two lanes in one wave touch the same file (GRPH-09). Critical path `L0→C→D/E1→E2` (GRPH-31); width 3 matches the lane cap.

## Slices

### Slice 0 — Contract (coordinator, this commit)

- [x] `docs/workbay/contracts/gpu-lifecycle.md` § GPU state snapshot: vocabulary, writer, freshness, ownership.
- [x] `packages/shared-contracts/schemas/scene-describe-run.schema.json` `gpu_state` enum (was `null`).
- [x] This plan; ux-map `describe-gpu-tier.uxmap.json` already committed.

### Slice B — Producer/env freshness (W1, lane B)

- [x] `apps/prototype-description-service/.env.prod.example` documents `ACX_GPU_STATE_PATH`, `ACX_GPU_STATE_STALE_SECONDS`, `ACX_DESCRIBE_LOAD_PATH`, `ACX_DESCRIBE_LOAD_REFRESH_SECONDS` next to the `ACX_GPU_ENDPOINT_*` block.
- [x] `scripts/deploy/check-gpu-snapshots.sh` (new): exits non-zero when `/run/acx/describe-load.json` or `/run/acx/gpu-state.json` is missing, unreadable by uid 10001, or older than the stale window; test in `scripts/deploy/tests/test_check_gpu_snapshots.py` (RED first via `make slice-start`).
- [x] `infra/oci/README.md` § snapshots: both files, owners, freshness, how to read them.

> **Slice B deviations.** The check test landed as `scripts/deploy/tests/test-check-gpu-snapshots.sh`
> (bash, wired into `make test-scripts`), not the planned `test_check_gpu_snapshots.py`. No RED gate was
> recorded via `make slice-start`, so TEST-06 is unsatisfied for this slice. The lane's own self-verify
> reported exit 4 / zero tests collected because it was pointed at the pytest path that was never created.
> The suite is unrun, not red.

### Slice C — API reader (W1, lane C)

- [x] `scene/application/gpu_state.py` (new): `GpuState(StrEnum)`, `resolve_gpu_state_path()`, `resolve_gpu_state_stale_seconds()`, `read_gpu_state(now=…) -> GpuState` fail-closed to `unknown`; log once per transition.
- [x] `scene/interface_adapters/http/schemas/responses.py` `DescribeRunResponse.gpu_state: GpuState = GpuState.UNKNOWN`; `_run_response` in `describe_run.py` fills it from the reader on every status/submit/cancel response.
- [x] `scene/tests/test_gpu_state.py` (new).
- [ ] `scene/tests/test_describe_run_contract.py` schema parity — **not done**. The file predates this task
  and the branch diff does not touch it, so nothing asserts the response model against the Slice 0 enum.
  No RED gate was recorded for this slice either.

### Slice F — Lifecycle writer (W1, lane F)

- [x] `infra/oci/gpu_lifecycle/state_snapshot.py` (new): `GpuStateSnapshot` dataclass + `write_gpu_state_snapshot(path, state, instance_id, reason, since)` atomic tmp+rename `0644`.
- [x] `run_reap_cycle` and `run_start_cycle` in `reaper.py` derive the state from the OCI probe + readiness result + FALLBACK decision and write it at the end of every cycle; `--gpu-state-json` flag in `_build_parser` (default `/run/acx/gpu-state.json`).
- [x] `infra/oci/gpu_lifecycle/tests/test_state_snapshot.py` (new): every state reachable; writer never emits `unknown`; write failure logs loudly and does not abort the cycle; `scripts/deploy/gpu-lifecycle-install.sh` unit lines carry the flag.

> **Slices D, E1 and E2 are DEFERRED** to a follow-up task by operator decision (`claude_gpuux1_land_backend_half_defer_ui`,
> decision 7468; blocker 296). Remote implement lanes cannot run their suites: the remote test-cmd allowlist admits only
> `pytest <path>` and `python3 -m pytest <path>`, refusing `composer`, `npm`, `npx`, `node`, `vitest`, `phpunit`, `php`,
> `uv run` and `bash`. Independently, the codex-remote sandbox provisions no `node_modules`. Both need an upstream
> workbay fix. Boxes below stay unchecked deliberately — this is undone work, not unrecorded work.

### Slice D — PHP passthrough (W2, lane D)

- [ ] `class-describe-controller.php` submit/status/cancel proxy responses carry `gpu_state` verbatim; unknown or missing upstream value → explicit `unknown`, never fabricated `ready` (rg-015).
- [ ] `tests/Unit/DescribeRunControllerTest.php`: passthrough for each enum member + missing key.

### Slice E1 — FE states (W2, lane E1)

- [ ] `describeApi.ts` `GPU_STATE` `as const` + `GpuState` type; `DescribeRunResponse.gpu_state: GpuState`.
- [ ] `syncVocabulary.ts` `gpu*` strings; `phasePresentation.ts` `GPU_STATE_PRESENTATION` strategy rows (label, icon name, tone) `satisfies Record<GpuState, …>`.
- [ ] `MediaSelection.tsx` `BulkDescribeProgress` renders the tier chip (`z-gpu-tier-chip`) from `progress.run.gpu_state`; `warming`/`starting` render the calm waiting notice (no `role=alert`); `useDescribeRunProgress` exposes `gpuState`.
- [ ] Tests in `hooks/__tests__/useDescribeRunProgress.test.tsx` and `pages/workbench/__tests__/BulkDescribeProgress.test.tsx`.

### Slice E2 — Toasts (W3, lane E2)

- [ ] `hooks/useGpuStateToasts.ts` (new): previous→next edge detection; toasts only for `starting→warming`, `warming→ready`, `*→degraded`; suppressed while `BulkDescribeProgress` is mounted; `unknown` never toasts.
- [ ] Mounted once at the SPA shell next to `ToastProvider`; strings from `syncVocabulary.ts`.
- [ ] `hooks/__tests__/useGpuStateToasts.test.tsx`: no toast on repeated polls, one per edge, suppression flag honoured.

## Verification

- Remote gate per lane: only `pytest <files>` and `python3 -m pytest <files>` are accepted by the remote
  test-cmd allowlist. The `uv run --extra dev pytest` / `npx vitest run` / `composer test` forms this plan
  originally specified are all refused before dispatch — that is why slices D/E1/E2 are deferred.
  RED recorded by `make slice-start`, GREEN by `record_event(test_result)`.
- Wave gate: `/wb-review-slice` — 1 local Claude reviewer + grok-remote reviewers with `semantic_reinjection_packet` context, canon lenses `ddia`, `latency`, `release-it`, `interaction`.
- Manual (post-merge, operator): cold-GPU bulk describe on demo shows `warming` chip then `ready` toast; excluded VM e2e follows the reaper fix.

## Context Loading

- Contract: `docs/workbay/contracts/gpu-lifecycle.md`
- UX map: `apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.uxmap.md`
- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/backend-php-guidelines.md`
- Handoff: task `GPUUX-1`; prior art findings `DEMO-UX-1-GPU-01`, `WBUX-6-REV-r0902rd3-HARM-A-F2`; decisions 6449/6456 (GPUW-1), 2266 (VLM-3B warm-start).
