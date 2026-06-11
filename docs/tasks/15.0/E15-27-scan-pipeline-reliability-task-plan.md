# E15-27. Scan Pipeline Reliability — Fail-Fast Intake, Progress Envelope, Tenant Isolation

> **Metadata**
>
> - **Date**: 2026-06-10
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

Scans are currently broken in the way that costs the most trust: when the InsightFace runtime is unavailable, `scan_worker.py` swaps in `UnavailableFaceDetector`/`UnavailableEmbeddingGenerator` and every item fails at process time with `RuntimeError("InsightFace runtime unavailable")`; the job stays `in progress` and the plugin shows a stuck scan (assessment S7). This is fail-late in exactly the place Release It says to fail fast: the missing capability is knowable at job intake. There is no progress contract — the plugin cannot distinguish "working," "queued behind another tenant," and "dead." The latency literature's first rule (feedback within the perceived-latency window, report progress not silence) is unmet, and the asyncio literature's structured-lifecycle rules (explicit terminal states, `return_exceptions` isolation, executor offload for CPU-bound embedding) are only partially applied.

## Constraints

- Recognition-only milestone: InsightFace CPU inference; no new model dependencies.
- rg-007: worker loops keep bounded per-unit no-progress detection; one unit's failure must not halt other units in the same cycle.
- sr-006: no `assert` for runtime validation in production paths — explicit exceptions/HTTP errors.
- sr-007: job/item status values centralized (Python `StrEnum`), no scattered string comparisons.
- Greenfield: schema adjustments go directly in `001_identity_schema.py`.

## Workflow Principles

- Fail fast at intake: validate required capabilities (embedding runtime, blob root writable, DB reachable) when the job is created, returning a structured rejection — not per-item at process time (Release It: fail fast).
- Every job reaches a terminal state in bounded time: `completed` / `completed_with_errors` / `failed(reason)` / `rejected(reason)` — no perpetual `in_progress` (asyncio: tasks are owned, awaited, and finish).
- Progress is data, not logs: a poll-cheap envelope is the contract; rendering belongs to E15-22/Workbench.

## Terminology

- **Capability probe**: startup + on-demand check that the embedding runtime loads (model files present, import succeeds), cached with TTL.
- **Progress envelope**: `{job_id, status, phase, items_total, items_done, items_failed, failure_reason?, updated_at}` served on the existing job-status read path.
- **Stall**: a job whose claimed items make no progress across N worker cycles (bounded per rg-007).

## Current State Analysis

- `ScanQueueService.populate_scan_job_items()` enqueues; `ScanWorker` claims batches (batch_size=10, max_concurrency=5); `ScanItemHandler.process_items()` → detect → embed → cluster handoff.
- InsightFace adapter is resolved lazily per worker (`_ensure_embedding_runtime()`); failure degrades to Unavailable* fakes instead of rejecting work.
- `/health/detailed` exists (E15-2) but does not report embedding-runtime capability.
- Job/items have statuses but no aggregate progress surface consumed by the plugin; stuck jobs are indistinguishable from slow ones.

## Target Outcome

Intake: `POST /recognition/analyze` checks the capability probe; if the runtime is unavailable the job is created in `rejected` state (or the request 503s with a structured reason — decided in Slice 1 against plugin expectations) and the plugin renders the reason immediately. Worker: capability re-checked at cycle start; embedding executes via executor offload (CPU-bound work off the event loop); per-item exceptions are collected (`return_exceptions` semantics) so one tenant's failures mark only its items; stall detection moves jobs to `failed(stalled)` after the bounded threshold. Progress: job-status response carries the envelope; counts update per batch so the plugin can show real progress within the perceived-latency window. `/health/detailed` gains `embedding_runtime: available|unavailable(reason)` so operators see capability before users do (handshaking).

## Context Loading

- Rules: `docs/workstate/rules/backend-python-guidelines.md`, `docs/workstate/rules/testing-python.md`
- Contracts: analyze router (`recognition/interface_adapters/http/routers/analyze.py`), scan queue service + worker, `/health/detailed` shape from E15-2
- Handoff/MCP: E15-27 ref; E15-22 plan (progress consumer expectations); E15-3a-br21 clustering stability plan (adjacent, do not absorb).

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `POST /recognition/analyze` | service | accepts job, fails late | structured rejection/503 when runtime unavailable | yes — plugin must render reason (small PHP/TS change included here) | pytest + PHPUnit envelope test |
| Job status read path | service | item statuses only | + progress envelope fields | yes — additive; E15-22 consumes | pytest shape test + fixture for plugin |
| `/health/detailed` | service | DB/model-cache checks | + embedding-runtime capability | yes — additive | pytest |
| Job status values | service | strings in code | `StrEnum` with terminal-state guarantee | No — internal | mypy + tests |

## Proposed Solution

Slice 1: capability probe module + intake gate + `/health/detailed` field + plugin-side rendering of the rejection reason (one error path, kept small). Slice 2: progress envelope on the job read path with per-batch count updates and `StrEnum` consolidation. Slice 3: worker hardening — executor offload audit for embedding calls, per-item exception isolation, bounded stall detection transitioning to terminal `failed(stalled)`, and a failure-mode pytest harness (runtime missing, runtime dies mid-batch, one tenant poisoned among three).

## Junior Implementer Guide

> Read this before touching code. **Rule zero: re-verify every anchor with the grep provided** — line numbers drift; symbols are truth (rg-010). If reality contradicts a slice's design, STOP and record a blocker instead of improvising.

### Why this task exists (didactic)

Today a runtime-less service accepts a scan job and lets every item die at process time while the job stays `in_progress` forever — the user sees a stuck spinner. `release-it.md §Fail Fast (5.5)` names the fix: check required resources at transaction start (job intake) and reject with a precise reason, instead of wasting cycles and trust on work that cannot succeed. The progress envelope answers `latency-reduce-delay-in-software-systems.md §Perceived vs Actual Latency`: you cannot make clustering faster, but feedback within the perceived-latency window converts "broken" into "working"; §Observability adds the rule that queue-wait and processing time must be separately visible or operators cannot tell slow from dead. Worker hardening applies `using-asyncio-in-python.md` directly: §Executor Offloading (CPU-bound InsightFace calls must not stall the event loop), §Gather with `return_exceptions=True` (one tenant's exception must not abort the batch), and §Cancellation/terminal-state discipline (every task tree ends in an owned, observable state).

### Assumed setup

`make task-start TASK=E15-27 …` → work in the worktree → per slice `cd apps/prototype-description-service && make test` → `record_event(test_result)` → `close_slice` → `render_handoff(kind='dashboard')`.

### Verified code anchors (as of commit `81de3127`; re-verify each)

| What | Where | Verified content | Re-verify with |
| --- | --- | --- | --- |
| Worker config | `recognition/worker/scan_worker.py:46-57` | `poll_interval_seconds=1.0, claim_batch_size=10, max_concurrency=5, stale_after_seconds=600, max_attempts=3` | `grep -n "class ScanWorkerConfig" -A 12 recognition/worker/scan_worker.py` |
| Runtime fallback (the bug) | `scan_worker.py:183-203` (`_ensure_embedding_runtime`) | skips when ready or `runtime_mode == 'test'`; on adapter failure swaps `UnavailableFaceDetector(reason)` / `UnavailableEmbeddingGenerator(reason)` and sets a 30s `_embedding_retry_after` backoff — items then fail one-by-one at process time | `grep -n "Unavailable\|_ensure_embedding_runtime" recognition/worker/scan_worker.py` |
| Status enum exists | `recognition/domain/job.py:12` | `class JobStatus(StrEnum)` — **extend this; do not create a parallel enum** (sr-007) | `grep -n "class JobStatus" -A 15 recognition/domain/job.py` |
| Intake call sites | `routers/analyze.py:201,554`, `routers/analyze_multipart.py:294` | analyze endpoints that enqueue scan work (also where `ensure_tenant_exists` runs — coordinate with E15-24 Slice 2 if both tasks are in flight) | `grep -rn "ensure_tenant_exists" --include="*.py" recognition/` |
| Adapter entry | `recognition/infrastructure/embeddings.py` (`get_shared_insightface_adapter`) | the import/init that actually fails when models are absent | `grep -rn "get_shared_insightface_adapter" --include="*.py"` |
| Health endpoints (E15-2) | health router | `/health`, `/ready`, `/health/detailed` shipped in E15-2 | `grep -rn "health/detailed" recognition/ api/` |

### Architecture caution that changes Slice 1's design (read carefully)

The API process and the scan worker are **separate processes** — separate containers in prod (`docker-compose.prod.yml`: API + Worker services). InsightFace models live where the WORKER runs. Therefore the intake gate in the API process MUST NOT decide capability by attempting a local InsightFace import — that probes the wrong process and will lie in both directions. Slice 1 must instead make capability a **worker-published fact**: the worker (which already learns availability in `_ensure_embedding_runtime`) writes a heartbeat/capability row (e.g. `worker_capabilities`: runtime available bool, reason, updated_at) on startup and on each availability transition; intake and `/health/detailed` read that row, treating a stale heartbeat (older than ~3× poll interval × claim cycle, pick and document) as unavailable. Record the chosen TTL and shape as a Slice 1 decision. If you find an existing worker-heartbeat mechanism (`grep -rn "heartbeat\|capability" recognition/ db/`), extend it rather than inventing a second one.

### Slice 1 notes — capability probe + fail-fast intake

- Probe module in `recognition/application/scan/`: one function the worker calls to publish, one the API calls to read. Pure DB read on the API side — no model imports in the request path.
- Intake gate in `analyze.py` / `analyze_multipart.py`: when capability is unavailable → HTTP 503 with structured detail `{reason: 'embedding_runtime_unavailable', detail: <worker-published reason>}` (sr-006: explicit HTTP errors, never `assert`). Decide-and-record: 503-at-intake (recommended — nothing to clean up) vs creating a `rejected` job row; the plugin error path must render whichever you choose.
- `/health/detailed` gains `embedding_runtime: {available, reason?, heartbeat_age_seconds}` — additive; follow the existing detailed-health response builder style.
- Plugin side (small, one error path): the analyze trigger surfaces the 503 reason verbatim in the scan UI. Find the trigger with `grep -rn "recognition/analyze" apps/prototype-wp-alt-context/js/ apps/prototype-wp-alt-context/src/`.
- Keep the worker's `Unavailable*` fallback classes for now — they remain the worker-internal guard; what this slice removes is silent acceptance of NEW jobs while incapable. Full removal happens only if Slice 3's isolation makes the classes dead (verify with grep before deleting; if still referenced from non-intake paths, leave them and note it).

### Slice 2 notes — progress envelope

- Envelope fields on the existing job-status read path (find it: `grep -rn "scan-jobs\|job_status\|jobs/" recognition/interface_adapters/http/routers/`): `{job_id, status, phase, items_total, items_done, items_failed, failure_reason?, updated_at}`. Counts come from `IdentityScanJobItem` aggregation — add an indexed COUNT query in the scan queue repository, not an N+1 loop.
- Update counts per claimed-batch completion (every ≤10 items at current batch size), giving the plugin sub-second-fresh progress at 1s poll cadence — that satisfies the perceived-latency window without per-item write amplification (`latency-reduce-delay-in-software-systems.md §Request Batching` — amortize, don't chat).
- Extend `JobStatus(StrEnum)` with any missing terminal values (`completed_with_errors`, `rejected`, `failed`) — exhaustive `match`/`if` handling at consumers; mypy must pass.
- Publish a fixture JSON of the envelope for E15-22/plugin consumption (commit it under the service's test fixtures; reference its path in the slice decision).

### Slice 3 notes — worker isolation + stall terminality

- Executor offload audit: InsightFace detect/embed calls are CPU-bound; confirm each call site inside async handlers goes through `loop.run_in_executor`/`asyncio.to_thread` (`using-asyncio-in-python.md §Executor Offloading`; §Future-vs-Task: executor futures are not in `asyncio.all_tasks()` — keep references so shutdown can await them).
- Per-item isolation: where the batch is processed concurrently, use `gather(..., return_exceptions=True)` semantics and record per-item failure without aborting siblings (§Gather for Resilient Shutdown). One poisoned tenant among three in the same cycle is the acceptance test.
- Stall terminality: the worker already has `stale_after_seconds=600` and `max_attempts=3` — wire these to a TERMINAL job transition (`failed` with `failure_reason='stalled'`) instead of perpetual `in_progress`; this is rg-007's bounded no-progress rule applied to jobs, not just items.
- Failure-mode pytest harness scenarios: runtime missing at intake; runtime dies mid-batch (adapter raises after N items); one tenant's items poisoned among three tenants; stall threshold reached. Model the harness on existing worker tests (`grep -rln "ScanWorker" recognition/tests/ tests/`).

### Pitfalls / stop conditions

- `runtime_mode == 'test'` short-circuits `_ensure_embedding_runtime` — your tests will silently use Stub detectors unless you account for it; the harness must set the mode that exercises the real probe path.
- Do not shrink `max_concurrency`/batch defaults while "fixing" isolation — throughput tuning is out of scope.
- The MV-refresh suppression logic around line 85-90 (job-scoped refresh skip) is subtle reviewed behavior — read its comment block before touching anything in the claim cycle, and leave it intact.
- If the job-status read path turns out to live in the plugin (PHP proxy) rather than a service router, stop and re-scope the envelope's boundary row before implementing.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Capability probe | `apps/prototype-description-service/recognition/application/scan/` (new module) | worker-published capability + API-side read (see Architecture caution) |
| Intake | `recognition/interface_adapters/http/routers/analyze.py` | gate + structured rejection |
| Health | health router/service from E15-2 | capability field |
| Worker | `recognition/worker/scan_worker.py`, `handlers/` | offload, isolation, stall detection; remove Unavailable* fallback path |
| Statuses | scan models/enums | `StrEnum` consolidation |
| Plugin error path | `apps/prototype-wp-alt-context` analyze trigger + JS | render rejection reason |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && make test` — intake rejection; envelope counts across simulated batches; stall transition; multi-tenant poisoned-batch isolation; enum exhaustiveness
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

Changes: envelope fields + per-batch updates; `StrEnum` statuses; fixture published for plugin/E15-22.
Proof: pytest shape + monotonic count test; fixture committed.

### Slice 3: Worker isolation + stall terminality

**Goal**: no job can remain non-terminal indefinitely; tenant failures are isolated.

Changes: executor offload audit; per-item exception collection; bounded stall → `failed(stalled)`; failure-mode harness.
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

- [ ] Envelope + enum consolidation + fixture landed
- [ ] Monotonic progress test green
- [ ] Evidence recorded

### Checklist for Slice 3: Worker hardening

- [ ] Offload + isolation + stall terminality landed
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
