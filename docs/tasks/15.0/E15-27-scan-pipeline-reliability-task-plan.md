# E15-27. Scan Pipeline Reliability — Fail-Fast Intake, Progress Envelope, Tenant Isolation

> **Metadata**
>
> - **Date**: 2026-06-10 00:00 EST
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Target Branch**: `feature/e15-27`
> - **Review Coverage Target**: 2
> - **Companion assessment**: [E15-24-architecture-coherence-assessment.md](E15-24-architecture-coherence-assessment.md)
> - **Scope fence**: E15-22 owns Workbench rendering of avatars/progress. This task owns the **service-side job contract**: intake validation, terminal states, progress envelope, worker isolation.
> - **Literature citation convention**: short form `using-asyncio-in-python.md §Executor Offloading` refers to `literature/extracted/refactoring/distilled/using-asyncio-in-python.md`. **The `literature/` directory is gitignored and exists only in the root checkout** (`~/Development/context-alt-text-monorepo/literature/...`) — read it from there, not from your task worktree.

## Objective

Media analysis scans either run or fail immediately with a stated reason — never silently stall. Jobs expose a progress envelope (counts + phase + terminal reason) that the plugin can poll cheaply, and one tenant's failure cannot stall another tenant's items in the same worker cycle.

## Problem Statement

Scans are currently broken in the way that costs the most trust: when the InsightFace runtime is unavailable, `scan_worker.py` swaps in `UnavailableFaceDetector`/`UnavailableEmbeddingGenerator` and every item fails at process time; retries can keep the job non-terminal long enough that the plugin reads it as stuck (assessment S7). This is fail-late in exactly the place Release It says to fail fast: the missing capability is knowable at job intake. The existing `JobStatusResponse.progress` contract already carries phase and basic counts, but it does not expose failed-item counts, a terminal reason, capability health, or a bounded "this job is dead" state. The latency literature's first rule (feedback within the perceived-latency window, report progress not silence) is only partially met, and the asyncio literature's structured-lifecycle rules need to be turned into explicit terminal-state and regression-test guarantees.

## Constraints

- Recognition-only milestone: InsightFace CPU inference; no new model dependencies.
- rg-007: worker loops keep bounded per-unit no-progress detection; one unit's failure must not halt other units in the same cycle.
- sr-006: no `assert` for runtime validation in production paths — explicit exceptions/HTTP errors.
- sr-007: job/item status values centralized (Python `StrEnum`), no scattered string comparisons.
- Greenfield: schema adjustments go directly in `001_identity_schema.py`.

## Workflow Principles

- Fail fast at intake: validate required capabilities (embedding runtime, blob root writable, DB reachable) when the job is created, returning a structured rejection — not per-item at process time (Release It: fail fast).
- Every accepted job reaches a terminal state in bounded time: `completed` / `completed_with_errors` / `failed(reason)` — no perpetual non-terminal status (asyncio: tasks are owned, awaited, and finish). Prefer `503` at intake over creating a visible `rejected` job unless Slice 1 records a compatibility decision for the new status.
- Progress is data, not logs: extend the existing poll-cheap `JobStatusResponse.progress` contract; rendering belongs to E15-22/Workbench.

## Terminology

- **Capability probe**: worker-published startup + on-demand fact that the embedding runtime loads (model files present, import succeeds), cached with TTL and read by the API.
- **Progress envelope**: additive extension to existing `JobStatusResponse.progress`: current `{completed, total, phase, images_processed?, faces_found?, ...}` plus failed count, terminal reason, and freshness fields served on the existing job-status read path.
- **Stall**: a job whose claimed items make no progress across N worker cycles (bounded per rg-007).

## Current State Analysis

- `ScanQueueService.populate_scan_job_items()` enqueues; `ScanWorker` claims batches (`claim_batch_size=10`, `max_concurrency=5`); `ScanItemHandler.process_items()` → detect → embed → cluster handoff.
- InsightFace adapter is resolved lazily per worker (`_ensure_embedding_runtime()`); failure degrades to `Unavailable*` fakes instead of rejecting new work at intake.
- `/health/detailed` exists in `api/main.py::health_detailed` but does not report embedding-runtime capability.
- Job status already exposes `JobStatusResponse.progress` through `analyze.py::get_job_status`, `job_utils.py::build_job_progress_response`, and `application/scan/progress.py`; the plugin consumes the generated `RecognitionJob` / `JobProgress` types. The missing contract pieces are failed-item counts, terminal reasons, capability health, and bounded stall terminality.
- Worker isolation already has important guardrails: `ScanItemHandler.process_items()` uses `asyncio.gather(..., return_exceptions=True)` and `InsightFaceAdapter.detect_faces()` offloads `self._app.get` through `run_in_executor`. Slice 3 should preserve these and add regression coverage rather than rewrite them.

## Target Outcome

Intake: `POST /recognition/analyze` and `/recognition/analyze/multipart` check the worker-published capability probe; if the runtime is unavailable, the request returns HTTP 503 with structured detail `{reason: 'embedding_runtime_unavailable', detail: <worker-published reason>}` and the plugin renders the reason immediately. Worker: capability re-checked at cycle start; existing executor offload and `return_exceptions` isolation stay intact and gain regression tests; stall detection moves accepted jobs to `failed(stalled)` after the bounded threshold. Progress: the existing job-status response carries the extended envelope; counts update per batch so the plugin can show live progress within the perceived-latency window. `/health/detailed` gains `embedding_runtime: {available, reason?, heartbeat_age_seconds}` so operators see capability before users do (handshaking).

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`
- Contracts: analyze router (`recognition/interface_adapters/http/routers/analyze.py`), multipart analyze router, scan queue service + worker, `/health/detailed` shape from E15-2, `docs/workbay/contracts/clustering-api.md`, generated plugin `RecognitionJob` type
- Handoff/MCP: E15-27 ref; E15-22 plan (progress consumer expectations); E15-3a-br21 clustering stability plan (adjacent, do not absorb).

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `POST /recognition/analyze` and `/recognition/analyze/multipart` | service | accepts job, fails late | structured 503 when worker-published runtime capability is unavailable | yes — plugin must render reason (small PHP/TS change included here) | pytest + PHPUnit/TS rejection test |
| Job status read path | service + WP proxy | existing `JobStatusResponse.progress` has basic phase/counts | additive progress fields: failed count, terminal reason, freshness | yes — update contract doc, generated TS type, fixture; E15-22 consumes | pytest shape test + fixture for plugin |
| `/health/detailed` | service | DB/model-cache checks | + embedding-runtime capability | yes — additive | pytest |
| Job status values | service + WP proxy + TS client | `JobStatus(StrEnum)` serializes as `pending/running/completed/failed`; plugin generated type mirrors these | add `completed_with_errors` only if required; avoid `rejected` by using 503-at-intake unless a compatibility decision records the visible status change | yes — status vocabulary is externally observed | mypy + pytest + generated TS type/test |

## Proposed Solution

Slice 1: worker-published capability module + intake gate + `/health/detailed` field + plugin-side rendering of the 503 reason (one error path, kept small). Slice 2: additive progress-envelope fields on the existing job read path, generated TS/contract fixture update, and status vocabulary consolidation. Slice 3: worker hardening without rewriting existing guardrails — audit/preserve executor offload and `return_exceptions` isolation, add bounded stall transition to terminal `failed(stalled)`, and add failure-mode pytest harness coverage (runtime missing at intake, runtime dies mid-batch, one tenant poisoned among three).

## Junior Implementer Guide

> Read this before touching code. **Rule zero: re-verify every anchor with the grep provided** — line numbers drift; symbols are truth (rg-010). If reality contradicts a slice's design, STOP and record a blocker instead of improvising.

### Why this task exists (didactic)

Today a runtime-less worker can let accepted scan work churn through retries before surfacing a terminal result, while the user only sees a long-running scan. `release-it.md §Fail Fast (5.5)` names the fix: check required resources at transaction start (job intake) and reject with a precise reason, instead of wasting cycles and trust on work that cannot succeed. The progress-envelope extension answers `latency-reduce-delay-in-software-systems.md §Perceived vs Actual Latency`: you cannot make clustering faster, but feedback within the perceived-latency window converts "broken" into "working"; §Observability adds the rule that queue-wait and processing time must be separately visible or operators cannot tell slow from dead. Worker hardening applies `using-asyncio-in-python.md` directly: preserve existing §Executor Offloading and §Gather with `return_exceptions=True`, then prove with tests that one tenant's exception cannot abort the batch and every task tree ends in an owned, observable state.

### Assumed setup

`make task-start TASK=E15-27 …` → work in the worktree → per slice `cd apps/prototype-description-service && make test` → `record_event(test_result)` → `close_slice` → `render_handoff(kind='dashboard')`.

### Verified code anchors (as of commit `19e42fb78b17de6ab95a784bc9e2fefeceb286a0`; re-verify each)

| What | Where | Verified content | Re-verify with |
| --- | --- | --- | --- |
| Worker config | `recognition/worker/scan_worker.py::ScanWorkerConfig` | `poll_interval_seconds=1.0`, `claim_batch_size=10`, `max_concurrency=5`, `stale_after_seconds=600`, `max_attempts=3` | `grep -n "class ScanWorkerConfig" -A 12 recognition/worker/scan_worker.py` |
| Runtime fallback (the bug) | `recognition/worker/scan_worker.py::ScanWorker._ensure_embedding_runtime` | skips when ready or `runtime_mode == 'test'`; on adapter failure swaps `UnavailableFaceDetector(reason)` / `UnavailableEmbeddingGenerator(reason)` and sets a 30s `_embedding_retry_after` backoff | `grep -n "Unavailable\\|_ensure_embedding_runtime" recognition/worker/scan_worker.py` |
| Existing isolation | `recognition/worker/handlers/scan.py::ScanItemHandler.process_items` | uses `asyncio.gather(..., return_exceptions=True)`; preserve this and add poisoned-tenant regression coverage | `grep -n "gather.*return_exceptions" recognition/worker/handlers/scan.py` |
| Existing executor offload | `recognition/infrastructure/embeddings/__init__.py::InsightFaceAdapter.detect_faces` | runs synchronous InsightFace `self._app.get` through `loop.run_in_executor` | `grep -n "run_in_executor\\|def detect_faces" recognition/infrastructure/embeddings/__init__.py` |
| Status enum + API type | `recognition/domain/job.py::JobStatus`, `schemas/responses.py::JobStatusResponse`, plugin generated `RecognitionJob` type | `JobStatus` currently exposes `pending/running/completed/failed`; plugin generated type mirrors that union | `grep -rn "class JobStatus\\|status: 'pending'" recognition/ apps/prototype-wp-alt-context/js/admin/api/generated` |
| Intake call sites | `routers/analyze.py::analyze_media`, `routers/analyze.py::_prepare_tenant_context`, `routers/analyze_multipart.py::analyze_media_multipart` | analyze endpoints that enqueue scan work and validate tenant context | `grep -rn "def analyze_media\\|require_tenant_record\\|scan_worker_available" recognition/interface_adapters/http/routers/` |
| Adapter entry | `recognition/infrastructure/embeddings/__init__.py::get_shared_insightface_adapter` | the import/init that actually fails when models are absent | `grep -rn "get_shared_insightface_adapter" --include="*.py"` |
| Health endpoints (E15-2) | `api/main.py::health_detailed` | `/health`, `/ready`, `/health/detailed` shipped in E15-2; detailed health currently reports DB, breaker, and model-cache, not worker embedding capability | `grep -rn "health/detailed\\|def health_detailed" api/ recognition/` |
| Existing progress path | `routers/analyze.py::get_job_status`, `job_utils.py::build_job_progress_response`, `application/scan/progress.py::build_scan_progress_snapshot` | job-status response already includes `progress` with phase/basic counts; extend it additively | `grep -rn "build_job_progress_response\\|build_scan_progress_snapshot\\|class JobProgressResponse" recognition/` |

### Architecture caution that changes Slice 1's design (read carefully)

The API process and the scan worker are **separate processes** — separate containers in prod (`docker-compose.prod.yml`: API + Worker services). InsightFace models live where the WORKER runs. Therefore the intake gate in the API process MUST NOT decide capability by attempting a local InsightFace import — that probes the wrong process and will lie in both directions. Slice 1 must instead make capability a **worker-published fact**: the worker (which already learns availability in `_ensure_embedding_runtime`) writes a heartbeat/capability row (e.g. `worker_capabilities`: runtime available bool, reason, updated_at) on startup and on each availability transition; intake and `/health/detailed` read that row, treating a stale heartbeat (older than ~3× poll interval × claim cycle, pick and document) as unavailable. Record the chosen TTL and shape as a Slice 1 decision. If you find an existing worker-heartbeat mechanism (`grep -rn "heartbeat\|capability" recognition/ db/`), extend it rather than inventing a second one.

### Slice 1 notes — capability probe + fail-fast intake

- Probe module in `recognition/application/scan/`: one function the worker calls to publish, one the API calls to read. Pure DB read on the API side — no model imports in the request path.
- Intake gate in `analyze.py` / `analyze_multipart.py`: when capability is unavailable → HTTP 503 with structured detail `{reason: 'embedding_runtime_unavailable', detail: <worker-published reason>}` (sr-006: explicit HTTP errors, never `assert`). Decide-and-record: 503-at-intake (recommended — nothing to clean up) vs creating a `rejected` job row; the plugin error path must render whichever you choose.
- `/health/detailed` gains `embedding_runtime: {available, reason?, heartbeat_age_seconds}` — additive; follow the existing detailed-health response builder style.
- Plugin side (small, one error path): the analyze trigger surfaces the 503 reason verbatim in the scan UI. Find the trigger with `grep -rn "recognition/analyze" apps/prototype-wp-alt-context/js/ apps/prototype-wp-alt-context/src/`.
- Keep the worker's `Unavailable*` fallback classes for now — they remain the worker-internal guard; what this slice removes is silent acceptance of NEW jobs while incapable. Full removal happens only if Slice 3's isolation makes the classes dead (verify with grep before deleting; if still referenced from non-intake paths, leave them and note it).

### Slice 2 notes — progress envelope

- Add fields on the existing job-status read path (`analyze.py::get_job_status` → `job_utils.py::build_job_progress_response`): keep current `progress.completed`, `progress.total`, and `progress.phase`; add `items_failed`, `failure_reason`, and `updated_at` or explicitly record why an existing timestamp satisfies freshness. Counts come from `IdentityScanJobItem` aggregation via `SqlAlchemyScanQueueRepository`, not an N+1 loop.
- Update counts per claimed-batch completion (every ≤10 items at current batch size), giving the plugin sub-second-fresh progress at 1s poll cadence — that satisfies the perceived-latency window without per-item write amplification (`latency-reduce-delay-in-software-systems.md §Request Batching` — amortize, don't chat).
- Extend `JobStatus(StrEnum)` only for statuses that must be visible on accepted jobs (likely `completed_with_errors`; avoid `rejected` if Slice 1 uses 503-at-intake). Update `JobStatusResponse`, generated plugin types, and consumers exhaustively; mypy/TS tests must pass.
- Publish a fixture JSON of the extended envelope for E15-22/plugin consumption (commit it under the service's test fixtures; reference its path in the slice decision and update `docs/workbay/contracts/clustering-api.md`).

### Slice 3 notes — worker isolation + stall terminality

- Executor offload audit: InsightFace detect/embed calls are CPU-bound; preserve the existing `loop.run_in_executor` path in `InsightFaceAdapter.detect_faces`, verify no new sync InsightFace call bypasses it, and add coverage if the audit finds a missing call site (`using-asyncio-in-python.md §Executor Offloading`; §Future-vs-Task: executor futures are not in `asyncio.all_tasks()` — keep references so shutdown can await them).
- Per-item isolation: preserve existing `ScanItemHandler.process_items()` `gather(..., return_exceptions=True)` semantics and add the missing one-poisoned-tenant-among-three acceptance test; do not replace the working pattern unless the test exposes a real bug.
- Stall terminality: the worker already has `stale_after_seconds=600` and `max_attempts=3` — wire these to a TERMINAL job transition (`failed` with `failure_reason='stalled'`) instead of perpetual `in_progress`; this is rg-007's bounded no-progress rule applied to jobs, not just items.
- Failure-mode pytest harness scenarios: runtime missing at intake; runtime dies mid-batch (adapter raises after N items); one tenant's items poisoned among three tenants; stall threshold reached. Model the harness on existing worker tests (`grep -rln "ScanWorker" recognition/tests/ tests/`).

### Pitfalls / stop conditions

- `runtime_mode == 'test'` short-circuits `_ensure_embedding_runtime` — your tests will silently use Stub detectors unless you account for it; the harness must set the mode that exercises the real probe path.
- Do not shrink `max_concurrency`/batch defaults while "fixing" isolation — throughput tuning is out of scope.
- The MV-refresh suppression logic in `ScanWorker.__init__` (`_retry_suppressed_job_id` comment block) is subtle reviewed behavior — read it before touching anything in the claim cycle, and leave it intact.
- The job-status read path lives in the service router and is proxied by the plugin; update both service contract/tests and plugin generated types where the serialized shape/status vocabulary changes.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Capability probe | `apps/prototype-description-service/recognition/application/scan/` (new module), `db/migrations/versions/001_identity_schema.py` | worker-published capability + API-side read (see Architecture caution); baseline schema row/table if needed |
| Intake | `recognition/interface_adapters/http/routers/analyze.py`, `recognition/interface_adapters/http/routers/analyze_multipart.py` | gate + structured 503 rejection before job persistence |
| Health | `apps/prototype-description-service/api/main.py::health_detailed` | additive capability field |
| Progress/status API | `recognition/interface_adapters/http/schemas/responses.py`, `recognition/interface_adapters/http/job_utils.py`, `recognition/application/scan/progress.py`, `recognition/infrastructure/repositories/scan_queue_repository.py` | additive failed/reason/freshness fields; status vocabulary only if accepted jobs need a new terminal state |
| Worker | `recognition/worker/scan_worker.py`, `recognition/worker/handlers/scan.py` | publish capability transitions; preserve existing offload/isolation; add stall terminality |
| Contracts/types | `docs/workbay/contracts/clustering-api.md`, `apps/prototype-wp-alt-context/js/admin/api/generated/recognition-job.ts` (or generator source) | update visible response/status vocabulary and generated TS type |
| Plugin error path | `apps/prototype-wp-alt-context` analyze trigger + JS/PHP proxy tests | render structured 503 reason |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && make test` — intake rejection; extended envelope counts across simulated batches; stall transition; multi-tenant poisoned-batch isolation; enum exhaustiveness
  - plugin PHP/TS focused tests for structured 503 rendering and generated type compatibility
- Runtime-parity:
  - `make serve` without InsightFace models → analyze returns structured rejection, job not stuck; with models → progress counts advance
- Manual:
  - LocalWP scan trigger shows reason immediately in unavailable case; progress visible in available case (rendering via existing UI until E15-22 lands).

## Slice Delivery

### Slice 1: Capability probe + fail-fast intake

**Goal**: a scan against a runtime-less service fails at submission with a stated reason, visible in the plugin.

Changes: worker-published capability + API-side read (see Junior Implementer Guide — Architecture caution); intake gate; health field; plugin rejection rendering. `Unavailable*` classes stay as the worker-internal guard; what ends is silent acceptance of new jobs while incapable.
Proof: pytest rejection + health; manual LocalWP rejection message.

### Slice 2: Progress envelope

**Goal**: job status reads answer "how far along, and is it alive?"

Changes: additive envelope fields + per-batch updates; `StrEnum` statuses only where externally required; contract/generated type update; fixture published for plugin/E15-22.
Proof: pytest shape + monotonic count test; generated type/contract fixture committed.

### Slice 3: Worker isolation + stall terminality

**Goal**: no job can remain non-terminal indefinitely; tenant failures are isolated.

Changes: executor offload audit preserving existing `run_in_executor`; per-item isolation regression coverage preserving existing `return_exceptions`; bounded stall → `failed(stalled)`; failure-mode harness.
Proof: pytest harness scenarios green, including one-poisoned-tenant-of-three isolation.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded scan worker/queue code, E15-2 health contract, E15-22 consumer expectations.
- [ ] Confirmed `ctx7` need only if asyncio executor semantics require upstream doc checks.
- [ ] Boundary rows recorded in slice-close decisions.

### Checklist for Slice 1: Fail-fast intake

- [ ] Worker-published capability + intake gate + health field + plugin reason rendering landed
- [ ] Capability TTL/shape decision recorded; no model imports in the API request path
- [ ] Evidence recorded

### Checklist for Slice 2: Progress envelope

- [ ] Additive envelope + required enum/generated-type consolidation + fixture landed
- [ ] Monotonic progress test green
- [ ] Evidence recorded

### Checklist for Slice 3: Worker hardening

- [ ] Existing offload/isolation preserved with regression coverage; stall terminality landed
- [ ] Failure-mode harness scenarios green
- [ ] Slice-complete decision + dashboard render

## Review Readiness

- [ ] Every new failure path has a structured reason and a test.
- [ ] No job state can persist non-terminally past the stall threshold.
- [ ] Handoff decisions per slice.

## Success Criteria

- [ ] Scan submission against a capability-less service returns a stated reason in <5s; nothing gets stuck.
- [ ] Plugin can render live progress counts for a running scan.
- [ ] A poisoned tenant batch fails alone; other tenants' items complete in the same cycle.
