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

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Capability probe | `apps/prototype-description-service/recognition/application/scan/` (new module) | cached runtime probe |
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

Changes: probe; intake gate; health field; plugin rejection rendering; delete Unavailable* fallback usage at intake-reachable paths.
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

- [ ] Probe + gate + health field + plugin reason rendering landed
- [ ] Unavailable* fallback removed from intake-reachable paths
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
