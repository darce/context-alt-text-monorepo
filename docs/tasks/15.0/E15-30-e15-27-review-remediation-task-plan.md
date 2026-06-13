# E15-30. E15-27 Review-Finding Remediation

**Status:** in_progress (planned; not yet sliced)
**Branch:** `feature/e15-30`
**Source:** the 21 medium/low review findings deferred from E15-27 (recorded on reviewer refs `E15-27-REV-A` / `E15-27-REV-B`, status `deferred`). Finding **bodies live in handoff** — query them live, do not paste them here:

```
review_findings(review={"operation":"list","task_ref":"E15-27-REV-A","status":"deferred"})
review_findings(review={"operation":"list","task_ref":"E15-27-REV-B","status":"deferred"})
```

These were deferred (not bugs) when E15-27 merged; the 3 HIGHs + the two behavioral findings (BR-24/BR-25) were already fixed. This task works the remaining quality backlog as bounded TDD slices. As each finding is addressed, flip its handoff status from `deferred` → `fixed` with `verified_commit_sha` — **do not track status in this doc** (it drifts; the DB is the source of truth).

## Scope (revised 2026-06-13 — cherry-pick)

Per the 2026-06-11 MVP strategy assessment ("ship the demo URL, stop polishing the chassis past it"), this task is **narrowed to the demo-visible findings only**; the rest of the quality backlog stays `deferred` in handoff for post-demo:

- **E15-27-BR-11** — scan error fallback surfaced raw HTTP/proxy body text to the UI → addressed.
- **E15-27-BR-21** — JobStatus→JobPhase exhaustiveness; terminal statuses fell through a silent `else` → addressed.

The Slice tables below remain the deferred backlog inventory — they are **not** being worked now; do not treat unaddressed rows as in-progress. Live status: `review_findings(operation="list", status="deferred", task_ref="E15-27-REV-A"|"E15-27-REV-B")`.

## Context already shipped (do not redo)
- BR-22 (contract docs) is **partially done**: E15-29 added `completed_with_errors`/`rejected` to the JobStatus wire vocabulary + a "Scan job terminal states" section in `docs/workstate/contracts/recognition-clustering.md`. Remaining: document the `progress_envelope` additive read shape (overlaps BR-14).

## Slices

### Slice 1 — Contract / runbook docs
Document the additive job-status read shape + capability/503 surfaces in the owning contract.

| Finding | Subject |
|---|---|
| E15-27-BR-14 | progress_envelope additive JobStatusResponse read shape — no owning contract |
| E15-27-BR-04 | boundary contracts/runbook not updated for embedding_runtime health field + analyze 503 |
| E15-27-BR-22 | clustering/job contract docs omit progress_envelope (rest done in E15-29) |
| E15-27-BR-23 | fixture documents only running state; add terminal envelope examples for E15-22 consumers |

### Slice 2 — Test coverage gaps
Add the missing tests (RED→GREEN each).

| Finding | Subject |
|---|---|
| E15-27-BR-06 | multipart analyze intake-gate rejection path untested |
| E15-27-BR-05 | no test for publish_embedding_runtime_capability worker upsert |
| E15-27-BR-15 | no HTTP integration test asserts progress_envelope on GET /jobs/{id} |
| E15-27-BR-09 | stale-heartbeat rejection unit-tested only, not at HTTP intake |
| E15-27-BR-18 | published fixture not validated against ScanProgressEnvelopeResponse in pytest |
| E15-27-BR-12 | onScanError wiring untested beyond scanApiError unit tests |

### Slice 3 — Enum consolidation + cleanups
| Finding | Subject |
|---|---|
| E15-27-BR-17 | item-row paths use JobStatus instead of ScanItemStatus (sr-007) |
| E15-27-BR-26 | get_job_item_identities_detected filters with JobStatus.COMPLETED not ScanItemStatus.COMPLETED |
| E15-27-BR-21 | JobStatus exhaustiveness: COMPLETED_WITH_ERRORS/REJECTED fall through to JobPhase.COMPLETE without explicit branches/tests |
| E15-27-BR-19 | job_to_response duplicates get_job_item_status_counts on poll path |
| E15-27-BR-28 | ValueError building progress_envelope silently swallowed (no log) |
| E15-27-BR-08 | read_embedding_runtime_capability docstring inaccurate (uses WorkerCapability ORM) |
| E15-27-BR-10 | worker __aenter__ double-publishes capability heartbeat (redundant DB write) |

### Slice 4 — Behavior / robustness nits
| Finding | Subject |
|---|---|
| E15-27-BR-03 | embedding_runtime_unavailable 503 lacks Retry-After; WP proxy retries 3x |
| E15-27-BR-07 | /ready probes API-local model cache only; worker embedding_runtime only on auth-gated /health/detailed |
| E15-27-BR-11 | scan error fallback surfaces raw HTTP error text when JSON parse fails |
| E15-27-BR-13 | HEARTBEAT_STALE_SECONDS=90 TTL/shape decision not recorded in handoff (record a decision) |

## Acceptance
Each finding either flipped to `fixed` (with evidence) or re-classified `wontfix` (with rationale) in handoff. Slices closed via `close_slice`. Service `make check` + frontend `make check` green. Pre-merge gate passes.

## Stretch Goals
- Re-evaluate BR-03/BR-07 against the live demo (E15 Phase 4) before investing — they may be lower priority than the demo critical path per the MVP assessment.
