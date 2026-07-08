# WBUX-3. Bulk Florence-Describe with Honest Progress + ETA

> **Task Short ID**: WBUX-3
> **Status**: draft (plan-analyze findings addressed; pending planning-review)
> **Target Branch**: feature/wbux-3
> **Epic**: [Public MVP UX Polish](../../epics/v0.4.1/public-mvp-ux-polish-epic.md) (WBUX assessment lineage; workbench progress-trust surface)
> **Related**: [E19-1 florence_large + async describe worker notes](../19.0/E19-1-florence-large-async-worker-impl-notes.md) (async-describe + `:florence` image precedent — reuse), [E20-11 hosted-provider memo](../20.0/E20-11-hosted-provider-decision-memo.md) (governance; GPU-offload now permitted for self-hosted models per its 2026-07-07 amendment)
> **Source intake**: scope note [`docs/scopes/workbench-batch-progress.md`](../../scopes/workbench-batch-progress.md); MCP decisions `operator_scope_intake_workbench_batch_progress` (`1525`), `operator_scope_confirm_bulk_describe_greenfield` (`1527`)
> **Plan-analyze**: run `plan-analyze-wbux-3-20260707-01` (verdict `pass_with_findings`); findings `WBUX-3-PA-01..08` addressed in this revision.

---

## Objective

Give the workbench a **bulk "Describe with AI"** capability whose progress bar reflects **actual Florence processing time**: per-image completion streamed over SSE with a converging ETA, cancel, and explicit stall/error states. When complete, an operator submits a describe run over a bounded set of library images and trusts the bar — no count-poll that freezes 14–39 s per image, no false ETA, no silent stalls.

## Intake

New capability (not a bug fix). Intake questions were answered via the `scope` skill and recorded as decisions `1525` + `1527`: architecture = **full async worker + SSE** (mirror the recognition scan path); granularity = **per-image**; GPU-procurement toast = **deferred, documented**; success = **bar tracks actual completion + ETA within ±20 % by mid-batch**.

## Problem Statement

There is **no live Florence batch-describe surface today**, and the plumbing to add one honestly does not exist:

- The live "Describe with AI" panel is single-image, one-shot: `DescribePanel.tsx` → `useDescribeMedia.ts:19` → WP `POST /recognition/describe` (`class-describe-controller.php:66`) → FastAPI `POST /scene/describe/multipart` (`describe.py:192-217`, one image, synchronous). No batch, no progress.
- The bulk-describe backend exists but is **orphaned**: `class-description-bulk-run-service.php` (`run()` :45, synchronous `foreach` :53-55) + `class-description-run-repository.php` (tables `acx_description_runs` / `acx_description_run_items`) are referenced by no REST route and no UI.
- The scene/Python service has **no async-job scaffolding** — no run table, worker, or SSE. It is single-image describe only.

A naive wiring (synchronous loop + count-poll) would reproduce the exact failure the recognition batch-run bar has: a bar that steps once per image and freezes for Florence's full per-image latency, with no ETA. This task builds it right the first time, reusing the recognition scan pattern.

## Constraints

- **Mirror the recognition scan path; do not reinvent it.** It proves async-job + SSE + client-ETA + stall-detection end to end, with an existing SQLAlchemy job-model precedent (`db/models/jobs.py`).
- **Scene builds its own job scaffolding.** Recognition's job models/worker are recognition-owned; a shared cross-service job abstraction is out of scope.
- **Greenfield**: no data migration. New tables are added directly to the existing alembic baseline `db/migrations/versions/001_identity_schema.py` (per the repo greenfield policy); no new revision, no backfill.
- **Inference stays self-hosted.** Runs on the local Florence path (`florence_small`). Per the E20-11 amendment (2026-07-07) self-hosted models on GPU are now permitted, but **actual GPU offload is out of scope here** (own task, with subprocessor controls). This task reserves the `gpu_state` SSE field only.
- **No backend-contract regressions** to `/scene/describe/multipart` or the recognition scan path.
- **Bounded runs** (see PA-04 fix): a run has a max item count; oversize submissions are rejected, not silently truncated.
- **Tenant-scoped** (PR-01): the scene service is multi-tenant. The new tables carry `tenant_id` and every query is tenant-filtered under RLS (`set_tenant_context`), exactly like `db/models/scene.py:42` `ImageDescription.tenant_id` + `db/tenant_context.py:57`. The new endpoints enforce `require_write_access` + `auth.tenant_claim` vs the run's tenant, mirroring `describe.py:195,208-209`. A run and its stream are only visible to their owning tenant.

## Workflow Principles

- Visible progress must match backend truth. `completed/total` + phase is a semantic contract, not a spinner.
- Ship proof with behavior — each slice adds focused tests (red first) or a named run-log artifact in the same slice.
- Reuse over rebuild: extract the shared JS SSE consumer rather than forking `useJobProgressStream`.

## Terminology

- **Describe run**: a scene-owned async job over an ordered, bounded set of media ids, tracked in `image_description_runs` with per-item rows in `image_description_run_items`.
- **Per-image progress**: `completed = terminal items (completed + failed + skipped)`, `total = submitted items`; the bar advances only on whole-image completion.
- **`DescribeRunStatus`** (Python `StrEnum`): `pending | running | completed | completed_with_errors | failed | cancelled`.
- **`DescribeRunPhase`** (Python `StrEnum`, the SSE `phase`): `queued | describing | complete | failed | cancelled`.
- **`DescribeItemStatus`** (Python `StrEnum`): `queued | running | completed | failed | skipped`.
- **Coalesced emit**: the SSE emitter sends only the latest pending progress per run (overwrite, not buffer) — the backpressure mechanism copied from Gradio's queue and the recognition stream.
- **Converged ETA**: remaining-time estimate (client-computed from elapsed + completed/total via the reused `calcEtaSeconds`) landing within ±20 % of actual by mid-batch.
- **Authoritative ledger**: the scene `image_description_runs` table is the single source of truth for run/item status; the WP `acx_description_runs` ledger is a **read-only submission mirror** (see PA-05 fix).

## Current State Analysis

- **Reference (recognition scan) — Python**: SQLAlchemy job models `db/models/jobs.py:30` `IdentityScanJob` + `:56` `IdentityScanJobItem` (the shape to mirror); domain `recognition/domain/job.py:101` (`update_progress` :116); progress snapshot `recognition/application/scan/progress.py:49`; **SSE endpoint** `recognition/interface_adapters/http/routers/analyze.py:435` `GET /jobs/{id}/stream` → `EventSourceResponse` (DB-poll ~100 ms; `event: progress` :496 / `done` :513 / `error`); out-of-process worker `recognition/worker/scan_worker.py`. **ETA is not a server field** — client-computed.
- **Reference (recognition scan) — WP/JS**: WP poll-and-re-emit proxy `class-analysis-jobs-controller.php:182` + `class-job-progress-stream-service.php:58`; JS consumer `useJobProgressStream.ts` (opens `recognitionJobs/${jobId}/stream` :151); field parse + `calcEtaSeconds` `useJobProgressStreamHelpers.ts:37`; monotonic clamp `useMonotonicScanProgress.ts`.
- **To wire (describe) — WP**: `class-description-bulk-run-service.php` + `class-description-run-repository.php` (orphaned run ledger; becomes the read-only WP mirror).
- **To build (describe) — Python**: scene has `scene/application/visual_facts_service.py` (single-image describe via `asyncio.to_thread`) and `scene/application/description_repository.py` / `db/models/scene.py:38` `ImageDescription` (SQLAlchemy async, `db/session.py` `AsyncSession`) — but no run/job layer. Worker-concurrency + timeout settings already exist and explicitly anticipate this: `scene/application/settings/vlm.py:8` ("documents the deferred async worker"), `:26` `ACX_VLM_TIMEOUT_SECONDS`, `:29` `ACX_VLM_WORKER_CONCURRENCY`.
- **Deployment reality (PA-01)**: the deployed image `acx-backend:latest` is **torch-free**; running Florence requires the separate torch-bearing `:florence` image + `ACX_DESCRIPTION_ADAPTER=florence_small`, with a one-time ~11 s cold model load (E19-1 Part A). See § Enablement & Rollout.
- **Contracts**: `packages/shared-contracts/schemas/recognition-job.schema.json` (scan progress event shape to mirror; `progress.completed`+`total` required, **no `eta`**); generated TS precedent `js/admin/api/generated/wp-batch-run.ts`. No describe-progress schema exists yet.

## Target Outcome

An operator selects a bounded library subset, clicks "Describe with AI (bulk)", and sees a bar that advances per completed image with a converging remaining-time estimate, a "stuck — last update N ago" affordance if the worker stalls, a cancel control, and an explicit failed-items summary. Inference stays on the self-hosted CPU Florence path. The SSE envelope carries a reserved `gpu_state` field so a future (now governance-permitted) GPU-procurement toast attaches without a protocol change.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`, `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/testing-typescript.md`, `docs/workbay/rules/backend-php-guidelines.md`, `docs/workbay/rules/engineering-heuristics.md`
- Contracts: `packages/shared-contracts/schemas/recognition-job.schema.json`, `docs/workbay/contracts/image-description-api.md`, `docs/workbay/contracts/workbench-media-api.md`
- Precedent: `db/models/jobs.py`, `recognition/interface_adapters/http/routers/analyze.py`, `docs/tasks/19.0/E19-1-florence-large-async-worker-impl-notes.md`
- Handoff/MCP: task ref `WBUX-3`; decisions `1525`, `1527`, `1566`; findings `WBUX-3-PA-01..08`

## Contract and Boundary Impact

- **New scene HTTP surface** (additive; no change to `/scene/describe/multipart`): `POST /scene/describe/run` (submit, bounded), `GET /scene/describe/run/{run_id}` (status poll fallback), `GET /scene/describe/run/{run_id}/stream` (SSE), `DELETE /scene/describe/run/{run_id}` (cancel).
- **New shared contract**: `packages/shared-contracts/schemas/scene-describe-run.schema.json` (run status) + `scene-describe-progress.schema.json` (SSE event), with generated TS mirror. `progress` mirrors `recognition-job.schema.json` (`completed`+`total` required) and adds `run_id`, `phase` (the `DescribeRunPhase` enum), optional `desc`, and a reserved nullable `gpu_state`.
- **New WP REST routes** under `acx/v1/` (submit / status / stream-proxy / cancel) — additive; auth/nonce parity with `class-analysis-jobs-controller.php`.
- **New scene DB tables**: `image_description_runs`, `image_description_run_items` (SQLAlchemy models in `db/models/scene.py`; DDL added to `db/migrations/versions/001_identity_schema.py`; greenfield, no backfill).
- **Consistency (PA-05)**: scene ledger authoritative; WP `acx_description_runs` is a read-only mirror. Poll/stream view staleness is bounded by the stream poll interval (~ sub-second) / WP poll cadence.
- **Status enums** centralized as Python `StrEnum` (scene) + a single TS `as const` mirror (sr-007).

## Proposed Solution

Build a minimal scene-side async job engine that copies the recognition scan shape: SQLAlchemy run/item models → submit endpoint that creates the run and launches a **tracked, cancellable** background task → the task runs each image through the existing `VisualFactsService` with bounded concurrency + per-image timeout, writing idempotent per-item status → an SSE endpoint that DB-polls and coalesces progress → shared contracts → WP proxy routes wiring the existing (read-only) run ledger → a workbench panel reusing the recognition SSE consumer. Cancel is cheap because the worker task is tracked. GPU offload is explicitly future work, gated behind the reserved `gpu_state` field.

## Files and Surfaces to Change

- **Scene models**: `db/models/scene.py` — new `DescribeRun` (`__tablename__ = "image_description_runs"`) + `DescribeRunItem` (`"image_description_run_items"`), mirroring `db/models/jobs.py:30/56`; both carry `tenant_id` (FK + index) like `ImageDescription` (`scene.py:42,73`). DDL into `db/migrations/versions/001_identity_schema.py`.
- **Scene domain/enums**: new `scene/domain/describe_run.py` — `DescribeRunStatus` / `DescribeRunPhase` / `DescribeItemStatus` (`StrEnum`), a `DescribeRun` aggregate with `update_progress()` and an invariant guard so a run cannot be constructed with `total < 1` or `> ACX_DESCRIBE_RUN_MAX_ITEMS`.
- **Scene repository**: new `scene/application/describe_run_repository.py` — `create_run`, `mark_item(run_id, media_id, status)` (idempotent — a repeat call for the same terminal item does not re-increment totals), `get_run`, `list_run_items`, `request_cancel(run_id)`, and `reclaim_interrupted_runs(cutoff)` to move stale `running` items back to `queued` after a worker restart. All methods take `tenant_id` and run under `set_tenant_context` (RLS), mirroring `ImageDescriptionRepository`.
- **Scene worker**: new `scene/application/describe_run_worker.py` — `run_describe_job(run_id)` tracked via a module-level registry (not fire-and-forget); bounded by `ACX_VLM_WORKER_CONCURRENCY`; per-image `asyncio.wait_for(..., ACX_VLM_TIMEOUT_SECONDS)`; checks the cancel flag between items; drives `VisualFactsService`; calls the interrupted-run reclaim once on worker startup so non-terminal runs resume instead of hanging forever.
- **Scene router**: new `scene/interface_adapters/http/routers/describe_run.py` — `POST /scene/describe/run`, `GET /scene/describe/run/{id}`, `GET /scene/describe/run/{id}/stream` (`EventSourceResponse`, coalesced), `DELETE /scene/describe/run/{id}`; each guarded by `Depends(require_write_access)` + `auth.tenant_claim` vs the run's tenant (mirroring `describe.py:195,208-209`) so a tenant cannot read/cancel another's run; request/response schemas in `scene/interface_adapters/http/schemas/`.
- **Contracts**: `packages/shared-contracts/schemas/scene-describe-run.schema.json`, `packages/shared-contracts/schemas/scene-describe-progress.schema.json`; regenerated TS mirror under `apps/prototype-wp-alt-context/js/admin/api/generated/`.
- **WP controller/service**: new submit + stream-proxy + cancel routes (new `class-*.php` alongside `class-analysis-jobs-controller.php`, using `run_transactional` from `trait-runs-transactional.php:30` for writes); wire `class-description-bulk-run-service.php` / `class-description-run-repository.php` as the read-only mirror (drop the synchronous `foreach`).
- **WP JS**: generalize `useJobProgressStream.ts` into a shared hook consumed by both recognition and describe; new `useBulkDescribe.ts` (submit + cancel mutations); new bulk-describe panel component reusing `useMonotonicScanProgress` + `calcEtaSeconds`.

## Related Files

`scene/application/visual_facts_service.py`, `scene/application/settings/vlm.py`, `db/session.py`, `recognition/worker/scan_worker.py` (worker shape reference), `useJobProgressStreamHelpers.ts`, `Panels.tsx` (bar component reference).

## Verification Strategy

All commands run from the repo root unless noted. Scene: `cd apps/prototype-description-service && uv run pytest <path> -k <selector>` (or `make test` for the full suite; `make check` for lint+type+test). WP JS: `cd apps/prototype-wp-alt-context && npm run test:agent -- <pattern>` (or `npm test`). WP PHP: `cd apps/prototype-wp-alt-context && composer test` (aka `npm run test:php`). Contracts: `python3 scripts/check_shared_contract_fixtures.py` validates the schema-backed shared fixtures per `packages/shared-contracts/README.md`; this repo does **not** currently expose a shared-contracts TS codegen target, so Slice 4 must add the describe schemas plus the generated/mirrored TS consumer artifacts in the same slice and use that script as the concrete contract validation command. Each slice writes its red test first.

## Enablement & Rollout (PA-01)

Bulk describe actually runs Florence, so it is only functional where the torch-bearing image is deployed. Per E19-1 Part A: build/deploy `acx-backend:florence` (the `runtime-vlm` stage), set `ACX_DESCRIPTION_ADAPTER=florence_small`, and account for a one-time ~11 s cold model load into the persisted `HF_HOME` cache on first run. The default `:latest` image (torch-free) will `503` fail-closed for describe — so the bulk feature is **gated to the florence-image deployment** and should surface a clear "describe backend unavailable" state on `:latest`. Worst-case run duration ≈ `N × ~14 s` (florence_small); see the run-size cap in Slice 2. GPU offload of this self-hosted path is a governance-permitted future (E20-11 amendment) but out of scope here.

## Slice Delivery

### Slice 1 — Scene describe-run persistence (models + enums + idempotent repository)
Add `DescribeRun`/`DescribeRunItem` SQLAlchemy models to `db/models/scene.py` (DDL into `001_identity_schema.py`), the three `StrEnum`s + aggregate in `scene/domain/describe_run.py` (invalid-state-at-construction guard; run rejected if `total<1` or `>ACX_DESCRIBE_RUN_MAX_ITEMS`), and `scene/application/describe_run_repository.py` with **idempotent** `mark_item` (a repeated terminal write must not double-count run totals), `request_cancel`, and `reclaim_interrupted_runs(cutoff)` that returns stale `running` items to `queued` without touching terminal items.
- **Test**: `uv run pytest scene/tests -k describe_run_repo` — item-status idempotency, run-total aggregation, skipped-item accounting, cap enforcement, interrupted-run reclaim.

### Slice 2 — Submit endpoint + tracked, bounded, cancellable worker
`POST /scene/describe/run` validates the media list explicitly (raise HTTP 422 on empty/oversize — not `assert`, sr-006; cap `ACX_DESCRIBE_RUN_MAX_ITEMS`, default 200 — PA-04), creates the run + queued items, returns `run_id` immediately. `describe_run_worker.run_describe_job` runs each image through `VisualFactsService` (`asyncio.to_thread`), bounded by `ACX_VLM_WORKER_CONCURRENCY`, each call wrapped in `asyncio.wait_for(ACX_VLM_TIMEOUT_SECONDS)`; a per-image failure marks that item `failed` and continues (fault ≠ failure; rg-007); the task is **tracked** (registry), reclaims stale non-terminal work on startup, and honors cancellation between items; unhandled exceptions transition the run to `failed` and emit an error.
- **Test**: `uv run pytest scene/tests -k describe_run_worker` — per-item advance; one failing image does not abort the run; cancel stops before the next item and marks remaining `skipped`; per-image timeout marks item `failed`; oversize submit → 422; startup reclaim resumes a stale run.

### Slice 3 — SSE progress endpoint (coalesced) + status/cancel
`GET /scene/describe/run/{id}/stream` → `EventSourceResponse` mirroring `analyze.py:435`: DB-poll loop emitting `event: progress` `{type:"describe_progress", run_id, status, completed, total, phase, desc, gpu_state:null}`, `event: done` on terminal, `event: error`; **coalesce to latest pending** per run; bounded poll interval + connection idle timeout. `GET /scene/describe/run/{id}` status poll fallback; `DELETE /scene/describe/run/{id}` cancel (PA-06).
- **Test**: `uv run pytest scene/tests -k describe_run_stream` — event ordering (progress\* → done), coalescing under fast completion, error event on worker failure, cancel path emits terminal `cancelled`, terminal closes the stream.

### Slice 4 — Shared contracts + generated TS mirror
Add `scene-describe-run.schema.json` + `scene-describe-progress.schema.json` alongside `recognition-job.schema.json`; regenerate the TS mirror (real generation, no hand shim — rg-001; validate column parity vs the new tables — rg-005). Reserve nullable `gpu_state` in the event schema.
- **Test**: `python3 scripts/check_shared_contract_fixtures.py`; scene response-shape test asserts the emitted payload validates against the new schema (`cd apps/prototype-description-service && uv run pytest scene/tests -k describe_run_contract`). If Slice 4 adds a first-class generator target, replace this checklist item with that new concrete command in the same diff.

### Slice 5 — WP REST submit/stream/cancel routes (wire the orphaned service as read-only mirror)
Register submit / status / stream-proxy / cancel routes (new `class-*.php`, `run_transactional` for writes, auth+nonce parity with `class-analysis-jobs-controller.php`), proxying to the scene endpoints; wire `DescriptionBulkRunService`/`DescriptionRunRepository` as the **read-only** WP mirror of the scene run (no synchronous inference on the WP side). The stream proxy must avoid holding a PHP-FPM worker for an entire worst-case Florence run: bound each SSE hold with a max duration, send reconnect hints, and retain the `GET /status` poll fallback for long runs; document the expected PHP worker budget in the route/service test fixture or class doc. Autoload parity check for new `class-*.php` (rg-016).
- **Test**: `composer test` (filter the new describe-run test class) — route registration, proxy submit, stream re-emit shape, cancel, auth/nonce enforcement, autoload parity.

### Slice 6 — WP bulk-describe panel + generalized SSE consumer
Extract a shared `useJobProgressStream` used by recognition + describe (no fork); add `useBulkDescribe.ts`; new workbench panel: select a bounded subset → submit → monotonic bar (`useMonotonicScanProgress`) + client ETA (`calcEtaSeconds`) + "stuck — last update N ago" stall banner (reuse 30 s threshold) + cancel button + explicit failed-items summary. Primary control reachable from a sensible zero state (rg-003); backend-unavailable (`:latest`) surfaces an explicit disabled state (per § Enablement).
- **Test**: `npm run test:agent -- useBulkDescribe` + a panel render test — bar monotonicity under out-of-order polls, ETA display, stall banner, cancel, error/failed-items state, disabled-when-unavailable.

### Slice 7 — ETA-tolerance + end-to-end proof
Integration test: a fake-latency describe run of N images asserts the bar reflects actual completion fraction and the ETA converges within **±20 % by mid-batch** (measured against realistic per-image latency, not the <1 ms seeded profile — QA ≠ production). Capture a named run-log artifact.
- **Test**: `uv run pytest scene/tests -k describe_run_eta_tolerance` + a JS integration test for ETA-convergence display.

## Consolidated Checklist

### Context and Ownership
- **Owner**: WBUX-3 (feature/wbux-3). **Reviewers**: backend-python (scene engine + SSE), frontend (panel + consumer), php-plugin (WP proxy). **Datastore**: scene Postgres via alembic baseline `001_identity_schema.py`. **Authoritative ledger**: scene `image_description_runs`; WP mirror read-only.

### Checklist for Slice 1: Scene describe-run persistence
- [x] Models `DescribeRun`/`DescribeRunItem` in `db/models/scene.py` + DDL in `001_identity_schema.py` (`apps/prototype-description-service/db/models/scene.py`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`)
- [x] `StrEnum`s + aggregate guard in `scene/domain/describe_run.py` (`apps/prototype-description-service/scene/domain/describe_run.py`)
- [x] Idempotent `describe_run_repository.py` (mark_item, request_cancel, cap, interrupted-run reclaim) (`apps/prototype-description-service/scene/application/describe_run_repository.py`)
- [x] `cd apps/prototype-description-service && VIRTUAL_ENV= uv run --locked --extra dev python -m pytest scene/tests/test_describe_run_repository.py -q` green (red first, including reclaim; MCP tests `588`/`589`)

### Checklist for Slice 2: Submit endpoint + worker
- [x] `POST /scene/describe/run` with explicit validation + `ACX_DESCRIBE_RUN_MAX_ITEMS` cap (422 on oversize) (`apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py`)
- [x] Tracked, bounded, cancellable `run_describe_job` with per-image timeout and startup reclaim (`apps/prototype-description-service/scene/application/describe_run_worker.py`; reclaim repository landed in Slice 1)
- [x] `cd apps/prototype-description-service && VIRTUAL_ENV= uv run --locked --extra dev python -m pytest scene/tests/test_describe_run_repository.py scene/tests/test_describe_run_worker.py -q` green (failure-continues, cancel, timeout, oversize; MCP tests `590`/`592`)

### Checklist for Slice 3: SSE + status/cancel
- [x] `GET /stream` coalesced `EventSourceResponse` (progress/done/error, gpu_state reserved) (`apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py`)
- [x] `GET /{id}` status + `DELETE /{id}` cancel (`apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py`)
- [x] `cd apps/prototype-description-service && VIRTUAL_ENV= uv run --locked --extra dev python -m pytest scene/tests/test_describe_run_repository.py scene/tests/test_describe_run_worker.py scene/tests/test_describe_run_stream.py -q` green (MCP tests `593`/`594`)

### Checklist for Slice 4: Contracts
- [x] `scene-describe-run` + `scene-describe-progress` schemas + regenerated TS mirror (`packages/shared-contracts/schemas/scene-describe-run.schema.json`, `packages/shared-contracts/schemas/scene-describe-progress.schema.json`)
- [x] `python3 scripts/check_shared_contract_fixtures.py` + `cd apps/prototype-description-service && VIRTUAL_ENV= uv run --locked --extra dev python -m pytest scene/tests/test_describe_run_contract.py -q` green (MCP tests `595`/`596`)

### Checklist for Slice 5: WP proxy routes
- [x] Submit/status/stream/cancel routes + read-only mirror wiring; autoload parity in `apps/prototype-wp-alt-context` (`apps/prototype-wp-alt-context/src/api/class-describe-controller.php`)
- [x] Bounded SSE hold + reconnect/poll fallback documented in the WP stream service tests for Slice 5 (`get_describe_run_stream_max_hold_seconds()` = 25s)
- [x] `cd apps/prototype-wp-alt-context && composer test -- --filter 'DescribeRunControllerTest|DescribeControllerAutoloadTest'` green (MCP tests `600`/`601`)

### Checklist for Slice 6: WP panel + consumer
- [ ] Shared `useJobProgressStream` extraction + `useBulkDescribe` + panel
- [ ] `cd apps/prototype-wp-alt-context && npm run test:agent -- useBulkDescribe` green

### Checklist for Slice 7: ETA proof
- [ ] ETA ±20 % mid-batch integration test + run-log artifact (`cd apps/prototype-description-service && uv run pytest scene/tests -k describe_run_eta_tolerance`)

## Review Readiness
- Fresh `test_result` evidence at HEAD for scene (`make check`), WP (`npm test`, `composer test`), and contracts.
- All `WBUX-3-PA-*` planning findings resolved or explicitly deferred with rationale.
- Contract parity validated (schema vs migration columns) before merge.
- Pre-merge gate: ≥1 review pass recorded, 0 open findings, `handoff_close_check(enforce=True)`, slice-complete decision.

## Stretch Goals
- Server-emitted `avg_item_ms` to sharpen early-batch ETA (client still computes display).
- Per-Florence-sub-task `desc` label (caption/OD/grounding) without driving the bar %.

## Success Criteria
- Bar monotonically reflects actual completion fraction; no freeze beyond one image's latency.
- Remaining-time ETA shown, converging within **~±20 % by mid-batch**.
- Cancel stops the run promptly; failed items surface explicitly; backend-unavailable state is explicit on `:latest`.
- Affordance parity with the recognition scan path (progress / eta / stall / error / cancel).

## Risks & Unknowns
- **ETA fidelity** under high per-image variance (14–39 s) — target is "±20 % by mid-batch"; verify against real florence_small timings, not seeded.
- **SSE through the WP poll-and-re-emit proxy** — confirm added poll cadence doesn't compound latency or leak connections on a stalled/cancelled run (resource-pool exhaustion).
- **Run-table growth** — `image_description_runs` accumulates; a retention/purge sweep is noted as a follow-on (steady-state reclaimer); confirm deferral acceptable for MVP.
- **Worker restart mid-run** — handled in Slice 1/2 by `reclaim_interrupted_runs(cutoff)`, which returns stale non-terminal work to `queued` and is covered by repository + worker tests.

## Not Doing
- No actual GPU offload/procurement (now governance-permitted per E20-11 amendment, but its own scoped task with subprocessor controls). SSE reserves `gpu_state` only.
- No GPU "acquired/unavailable/quota" toast state machine (deferred; see scope note).
- No per-Florence-sub-task progress steps (stretch only).
- No shared cross-service job abstraction refactor.
- No change to `/scene/describe/multipart` or the recognition scan path beyond extracting the shared JS consumer.
- No data migration / backward-compat shims (greenfield).

## Deferred — documented for future implementation
**GPU-procurement toast + self-hosted GPU offload.** Now governance-permitted (E20-11 amendment 2026-07-07: self-hosted models on rented GPU are allowed, subject to infra-subprocessor disclosure/no-retention controls). When a future task greenlights it, run our own Florence container on Modal or RunPod Serverless (WBUX-3 research: ZeroGPU is unusable server-to-server — anonymous `X-IP-Token` quota; Modal/RunPod can run our container, scale-to-zero, per-second, sub-15 s cold start), add run phases `acquiring_gpu → gpu_ready | gpu_unavailable | quota_exceeded` on the reserved `gpu_state` field, and surface them as toasts with cold-start-aware ETA.
