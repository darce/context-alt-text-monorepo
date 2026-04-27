# Task Plan — PDS Pipeline Stability (`pds-pipeline-stability-26`)

> - **Date**: 2026-04-27
> - **Author**: claude-opus-4-7
> - **Project**: `apps/prototype-description-service`
> - **Task ID**: `pds-pipeline-stability-26`
> - **Target Branch**: `feature/pds-pipeline-stability-26`
> - **Review Coverage Target**: 2

## pds-pipeline-stability-26. Apply assessment findings F-1, F-2, F-3, F-6, F-7

## Objective

Land five literature-backed fixes from [docs/assessments/clustering-pipeline-postgres-refactor-literature-2026-04-26.md](../../assessments/clustering-pipeline-postgres-refactor-literature-2026-04-26.md): per-call timeouts on external adapters, a `commit→external-call→commit` phase split for scan jobs, an `AdapterCircuitBreaker` reused at the application boundary, replacement of bare-string job statuses with the existing `JobStatus(StrEnum)`, and a parameter-object refactor at the clustering orchestration entry. One ADR documents the new external-integration shape.

## Intake

- **Scope one-pager**: [docs/scopes/pds-pipeline-stability-26.md](../../scopes/pds-pipeline-stability-26.md)
- **Key Q&A decisions**: `pds_pipeline_stability_intake_answers`, `pds_pipeline_stability_scope_committed`, `pds_pipeline_stability_plan_findings_addressed`
- **Not-Doing**: F-4 (per-chunk asyncio.timeout), F-5 (latency histogram), F-8 (snapshot-isolation ADR), F-9 (chunk_commit_boundary CM), F-10 (pool-utilization signal), retention/export status-enum sites, native Postgres enum migration, worker/admission-lock concurrency changes, frontend changes, schema migrations.

## Problem Statement

Current state has three concrete stability gaps and two readability gaps:

1. External adapter calls (`InsightFaceEmbeddingGenerator.generate` and the auto-labeler entrypoint) have no per-call timeout and are caught by a bare `except Exception` that swallows failures with a log line. A hung upstream blocks an asyncio task indefinitely.
2. The same calls run inside open `AsyncSession` scopes (e.g. [scan/service.py:100](../../../apps/prototype-description-service/recognition/application/scan/service.py#L100) inside the `save_job_results` flow), so a slow upstream also holds a Postgres transaction open until `idle_in_transaction_session_timeout` kills it.
3. There is no application-boundary circuit breaker around external adapters. The only breaker (`clustering_circuit_breaker.py`) wraps the HTTP admission endpoint, so adapter saturation degrades latency silently rather than shedding load fast.
4. Job-status assignments and comparisons in the clustering and scan paths use bare strings (`"running"`, `"completed"`, `"failed"`, `"pending"`) rather than the existing `JobStatus(StrEnum)` at [domain/job.py:12](../../../apps/prototype-description-service/recognition/domain/job.py#L12). Typos pass type-check; an exhaustive switch is impossible.
5. `cluster_unclustered_identities` and `IncrementalClusteringRunner.__init__` each take 14 keyword arguments and duplicate them ([orchestrator.py:54-113](../../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L54)). Adding any new dependency (timeout config, breaker) makes the parameter list worse before it gets better, violating sr-008.

The literature crosswalk diagnoses these as Nygard's *Use Timeouts*, *Integration Points*, *Cascading Failures*, *Circuit Breaker* (chs. 4-5), Fowler's *Replace Magic Number with Symbolic Constant* (ch. 9), and *Introduce Parameter Object* (ch. 6).

## Constraints

- **Greenfield (no backcompat).** No production users; in-flight scan-job semantics may change without a migration story.
- **No new infra dependencies.** No Prometheus client, no OTel SDK, no Redis-backed breaker, no new sidecars. FastAPI + asyncpg + SQLAlchemy + stdlib only.
- **No DB schema changes.** Status columns remain `text`. Any SQLAlchemy `Enum(JobStatus, native_enum=False)` wiring is opt-in per column we touch and does not change column type.
- **No worker / admission-lock concurrency changes.** F-2's phase split touches `scan/service.py` boundaries only. `scan_worker` reclaim semantics, the `with_for_update()` admission lock, and clustering-pool sizing are out of scope.
- **Idempotency must survive the phase split.** F-2 may break atomicity of "reserve + analyze + persist"; the post-split persistence step must use a deterministic idempotency key and `ON CONFLICT DO NOTHING` (rg-002 spirit: do not split an atomic write into multiple non-idempotent steps).

## Workflow Principles

- **Adapter calls follow `commit → call → commit`.** Any code path that holds `_session.in_transaction()` while awaiting an external adapter is a defect.
- **Adapter calls are bounded by an `asyncio.wait_for` timeout** sourced from settings, never a hardcoded literal (rg-008: validate at load time).
- **Status values are `JobStatus`/`JobPhase` enum members at every assignment site in clustering and scan paths.** Bare strings are review-blocking (sr-007).
- **Orchestration entrypoints take ≤4 grouped dataclasses, not 14 kwargs** (sr-008).
- **One ADR per architectural seam, not per finding.** A single ADR codifies the external-integration shape (timeout + breaker + phase split); per-finding rationale lives in slice-complete decisions and the assessment doc.

## Terminology

- **Adapter** — concrete implementation of an external integration (`InsightFaceAdapter`, auto-labeler client). Lives under `recognition/application/embedding/` or `recognition/application/labeling/`.
- **AdapterCircuitBreaker** — new (or refactored-out) reusable breaker wrapping adapter calls at the application boundary. Distinct from the existing HTTP-admission `clustering_circuit_breaker`.
- **Phase split** — refactoring `scan/service.py` so the external adapter call sits between two committed transactions, never inside one.
- **`JobStatus`** — the existing `StrEnum` at [domain/job.py:12](../../../apps/prototype-description-service/recognition/domain/job.py#L12) (`PENDING`/`RUNNING`/`COMPLETED`/`FAILED`).
- **`JobPhase`** — the existing `StrEnum` at [domain/job.py:30](../../../apps/prototype-description-service/recognition/domain/job.py#L30) (`QUEUED`/`DETECTING`/`CLUSTERING`/`RETRYING`/`AWAITING_PROJECTION`/`FAILED`/`COMPLETE`).

## Current State Analysis

- **Works today:** chunked durable clustering, three-pool engine bulkhead, admission-side circuit breaker, adaptive chunk sizing (EWMA), per-tenant RLS via `SET LOCAL`, idempotent member writes via `ON CONFLICT DO NOTHING`. None of these regress in this task.
- **Broken/drifting:** items 1-5 in Problem Statement above.
- **Misleading:** the existence of `JobStatus(StrEnum)` plus the prevalence of bare-string assignments suggests a partial enum migration that stalled. Consumers (`job_utils.py`) already import the enum, but writers (`scan/service.py:89`, `routers/clusters.py:361`, `deps/stores.py:40,55`) still use string literals.

## Target Outcome

External integrations follow `commit → wait_for(adapter call, timeout) within a breaker → commit`. A failing or slow adapter trips the breaker after a configurable failure-rate window and is rejected fast at the application boundary, not silently retried by every caller. Job-status writes in clustering and scan paths go through `JobStatus`/`JobPhase` members. Orchestration entry takes three frozen dataclasses (`ClusteringDependencies`, `ClusteringRuntimeConfig`, `ClusteringContext`) instead of 14 kwargs. A single ADR documents the integration-point shape so the next adapter we add follows the same template.

## Context Loading

- Rules: `docs/agentic/constitution.md` (sr-007, sr-008, rg-002, rg-008)
- Contracts: none touched (no cross-service API change; HTTP responses keep current shape)
- Source assessment: [docs/assessments/clustering-pipeline-postgres-refactor-literature-2026-04-26.md](../../assessments/clustering-pipeline-postgres-refactor-literature-2026-04-26.md)
- Scope: [docs/scopes/pds-pipeline-stability-26.md](../../scopes/pds-pipeline-stability-26.md)
- Existing breaker reference: [recognition/interface_adapters/http/deps/clustering_circuit_breaker.py](../../../apps/prototype-description-service/recognition/interface_adapters/http/deps/clustering_circuit_breaker.py)
- Existing enum: [recognition/domain/job.py](../../../apps/prototype-description-service/recognition/domain/job.py)
- Handoff/MCP state: task `pds-pipeline-stability-26`; open findings list before each slice.
- External docs via `ctx7`: not required. asyncio `wait_for` and SQLAlchemy `AsyncSession` semantics are stable in our pinned versions; the changes use stdlib + already-vendored primitives.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| HTTP `POST /recognition/scan/...` (response shape) | backend | `apps/prototype-description-service/recognition/interface_adapters/http/schemas/responses.py` | none — status field still serializes as string via `JobStatus.value` | no (greenfield + StrEnum is str) | existing pytest API tests must pass unchanged |
| HTTP `POST /recognition/clustering/jobs` (admission) | backend | same | none — admission breaker untouched | no | existing breaker tests pass unchanged |
| `InsightFaceAdapter.analyze` (Python interface) | backend | `recognition/application/embedding/generator.py` adapter protocol | callers now wrap in `wait_for` and breaker; adapter signature unchanged | no | adapter unit tests unchanged; new wrapper tests added |
| Auto-labeler call surface | backend | `recognition/application/labeling/` (location verify in slice 3) | callers wrap in `wait_for` and breaker | no | new wrapper tests |
| `cluster_unclustered_identities` keyword surface | backend | `recognition/application/orchestration/clustering/orchestrator.py:54` | takes 3 dataclasses + 2 positional context fields instead of 14 kwargs | **yes — internal callers updated in same slice** | mypy + existing orchestrator tests pass |

## Proposed Solution

Five small refactors landed in dependency order, each its own slice with tests. The ADR is drafted alongside slice 4 (the phase split) and references the timeout helper (slice 2) and breaker (slice 3) it builds on.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `recognition/application/orchestration/clustering/orchestrator.py` | Group 14 kwargs into 3 dataclasses; refactor `_persist_and_cache_new_clusters` (L374) signature similarly |
| backend (new) | `recognition/application/orchestration/clustering/dependencies.py` (or sibling) | Define `ClusteringDependencies`, `ClusteringRuntimeConfig`, `ClusteringContext` frozen dataclasses |
| backend | `recognition/interface_adapters/http/routers/clusters.py` (~L361), `recognition/interface_adapters/http/deps/stores.py` (L40, L55), `recognition/application/scan/service.py` (L89), other clustering/scan-path string-status sites | Replace bare-string status writes/comparisons with `JobStatus`/`JobPhase` members |
| backend (new) | `recognition/application/integrations/timeouts.py` | `wait_for_adapter(coro, *, timeout, adapter_name)` helper raising typed `AdapterTimeoutError` (parity with `integrations/circuit_breaker.py`) |
| backend (new) | `recognition/application/integrations/circuit_breaker.py` | `AdapterCircuitBreaker` (state machine extracted from / shared with `clustering_circuit_breaker.py`) |
| backend | `recognition/application/embedding/generator.py` (~L99) | Wrap `await self._adapter.analyze(...)` in timeout + breaker; remove blanket `except Exception` swallowing |
| backend | `recognition/application/labeling/` (call site TBD slice 3) | Same wrapping pattern at the auto-labeler entrypoint |
| backend | `recognition/application/scan/service.py` (`save_job_results`, ~L94+) | Three explicit phases: reserve+commit, external call (no open tx), persist+commit with `ON CONFLICT DO NOTHING` keyed on `(job_id, media_id)` |
| settings | `recognition/application/settings/adapters.py` (new, sibling to existing `adaptive.py`/`clustering.py`/`scan.py`) | Add per-adapter `timeout_s` and breaker config (validated at load time per rg-008) |
| docs | `docs/adrs/ADR-008-external-adapter-stability-pattern.md` (new) | Codify `commit → call → commit`, `AdapterCircuitBreaker` reuse, per-adapter timeout convention, `JobStatus`/`JobPhase` location |

## Related Files

| File | Note |
| --- | --- |
| `recognition/interface_adapters/http/deps/clustering_circuit_breaker.py` | State-machine reference; possible source for the extracted `AdapterCircuitBreaker` core |
| `recognition/interface_adapters/http/job_utils.py` | Already imports `JobStatus`/`JobPhase`; verify it doesn't duplicate the new enum-adoption logic |
| `recognition/domain/job.py` | Owns `JobStatus`/`JobPhase`/`Job`; do not modify unless slice 1 grep finds a status value not yet on either enum |
| `apps/prototype-description-service/recognition/worker/scan_worker.py` | Worker-side caller of scan service; verify the phase split does not require worker changes (constraint says it must not) |

## Verification Strategy

- **Deterministic tests:**
  - `cd apps/prototype-description-service && pytest recognition/tests/unit/test_orchestrator_dependencies.py recognition/tests/unit/test_adapter_circuit_breaker.py recognition/tests/unit/test_wait_for_adapter.py recognition/tests/unit/test_scan_service_phase_split.py recognition/tests/unit/test_job_status_enum_adoption.py -x`
  - `cd apps/prototype-description-service && pytest recognition/tests/integration/test_assignment_writer.py recognition/tests/integration/test_end_to_end.py -x` (regression)
  - `cd apps/prototype-description-service && mypy recognition/` (catch enum drift and dataclass refactor regressions)
  - `cd apps/prototype-description-service && ruff check recognition/`
- **Runtime-parity / environment checks:**
  - `cd apps/prototype-description-service && python -m pytest recognition/tests/integration/test_clustering_pool_isolation.py -x` (confirms pool bulkhead still holds after orchestrator refactor)
- **Contract/fixture verification:**
  - Manual grep gate: `! grep -rn 'status\s*=\s*"\(running\|completed\|failed\|pending\)"' apps/prototype-description-service/recognition/application/scan apps/prototype-description-service/recognition/application/orchestration apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py apps/prototype-description-service/recognition/interface_adapters/http/deps/stores.py` returns no matches at slice 2 close.
- **Manual verification:**
  - None required — no UI surface changes. Document the absence in the slice-complete decision.

## Slice Delivery

### Slice 1: Parameter-object groupings (F-7)

**Goal:** Replace 14 kwargs at `cluster_unclustered_identities` and `IncrementalClusteringRunner.__init__` with three frozen dataclasses; apply the same shape to `_persist_and_cache_new_clusters` at orchestrator.py:374.

**Proposed grouping** (cohesion = lifetime + mutability; finalize against the live signature in slice prep):

| Dataclass | Holds | Lifetime |
| --- | --- | --- |
| `ClusteringDependencies` | injectable services: session factory, embedding adapter, similarity index, assignment writer, breaker, repositories | process / DI scope |
| `ClusteringRuntimeConfig` | numeric knobs: chunk size, EWMA params, similarity thresholds, max iterations, adaptive-sizing limits | config-load scope |
| `ClusteringContext` | per-call values: `tenant_id`, `job_id`, `snapshot_version`, optional run correlation id | per-invocation |

Changes:

- New module `recognition/application/orchestration/clustering/dependencies.py` with `ClusteringDependencies`, `ClusteringRuntimeConfig`, `ClusteringContext` (all `@dataclass(frozen=True)`).
- Update `cluster_unclustered_identities`, `IncrementalClusteringRunner.__init__`, `_persist_and_cache_new_clusters`, and all internal callers in the same diff.
- New unit test asserts the entrypoint takes ≤4 args and that mypy round-trips the new types.

Proof:

- `pytest recognition/tests/unit/test_orchestrator_dependencies.py -x`
- `mypy recognition/application/orchestration/clustering/orchestrator.py`
- Existing orchestrator tests pass unchanged.

### Slice 2: Adopt existing `JobStatus`/`JobPhase` (F-6)

**Goal:** Replace bare-string status writes and comparisons in clustering + scan paths with enum members; do not introduce a new enum.

Changes:

- Grep clustering + scan paths for bare-string status assignments and comparisons; replace with `JobStatus.<MEMBER>` / `JobPhase.<MEMBER>`.
- If grep finds a status value not in either enum, extend `JobStatus` (preferred) or `JobPhase` and call out the addition in the slice-complete decision.
- Wire SQLAlchemy `Enum(JobStatus, native_enum=False)` only on columns this slice touches; do not change DB schema.
- New test `recognition/tests/unit/test_job_status_enum_adoption.py` asserts the grep gate (no bare-string status literals in scan + clustering paths). Lives under the default pytest collection root, so `make check-all` (which runs the recognition suite without `-k` filters) enforces the gate on every CI run — no separate `make` target required.

Proof:

- `pytest recognition/tests/unit/test_job_status_enum_adoption.py -x`
- `mypy recognition/`
- Manual grep gate from Verification Strategy returns 0 matches.

### Slice 3: Adapter timeout helper + `AdapterCircuitBreaker` (F-1, F-3)

**Goal:** Bound every external adapter call with `asyncio.wait_for` and an `AdapterCircuitBreaker`. Wire both at `InsightFaceEmbeddingGenerator.generate` and the auto-labeler entrypoint at `recognition/application/labeling/auto_labeler.py` (confirmed present).

**Breaker configuration surface** (frozen dataclass `AdapterBreakerConfig` in the new settings module, validated at load time per rg-008):

| Field | Default (initial; tune against existing `clustering_circuit_breaker.py`) |
| --- | --- |
| `failure_count_threshold` | 5 |
| `failure_window_seconds` | 60 |
| `half_open_probe_count` | 1 |
| `success_close_threshold` | 1 |
| `open_state_cooldown_seconds` | 30 |

Per-adapter timeout: `embedding_timeout_s` (default 10), `auto_labeler_timeout_s` (default 15). Defaults must be overridable via environment-driven settings.

**Failure handling at the application boundary** (resolves the gap left by removing the blanket `except`):

- `AdapterTimeoutError` and `BreakerOpenError` are caught at the orchestrator/scan-service boundary, not inside the generator.
- Mapping: timeout or breaker-open → `JobStatus.FAILED` with `JobPhase.RETRYING` if the worker's retry budget remains; `JobStatus.FAILED` (terminal) once exhausted. Error message records adapter name and error class.
- The clustering chunk loop treats a single chunk's adapter failure as a chunk-level failure (skip + record), not a job-level failure, preserving rg-007 (bounded stall detection).

Changes:

- New `wait_for_adapter(coro, *, timeout, adapter_name)` helper raising typed `AdapterTimeoutError`. Timeout sourced from `recognition/application/settings/adapters.py`.
- New `AdapterCircuitBreaker` in `recognition/application/integrations/circuit_breaker.py`. Slice prep grep decides extract-vs-new against the existing `clustering_circuit_breaker.py` state machine; if extraction is invasive, ship a minimal new breaker and defer the existing-breaker refactor to a follow-up task (out of slice scope).
- Wrap `embedding/generator.py:99` and `labeling/auto_labeler.py` adapter call sites.
- Remove blanket `except Exception` from generator; declare typed propagation contract above.
- Update orchestrator/scan-service catch sites to apply the failure-handling mapping; cover with unit tests.
- New unit tests: timeout fires; breaker opens after N failures; half-open probe; closed→open→half-open transitions; orchestrator/scan caller maps typed errors to expected `JobStatus`/`JobPhase`.

Proof:

- `pytest recognition/tests/unit/test_wait_for_adapter.py recognition/tests/unit/test_adapter_circuit_breaker.py -x`
- Existing embedding tests pass unchanged.

### Slice 4: `commit → call → commit` phase split for scan jobs + ADR (F-2)

**Goal:** Refactor `scan/service.py:save_job_results` so the external adapter call sits between two committed transactions. Land the ADR codifying the pattern.

Changes:

- Phase 1: reserve job + commit. Phase 2: external adapter call (no open tx). Phase 3: persist results + commit, idempotent on `(job_id, media_id)` via `ON CONFLICT DO NOTHING`.
- Audit other call sites for the same anti-pattern; if any found, document in the slice-complete decision with a follow-up task ref.
- Land `docs/adrs/ADR-008-external-adapter-stability-pattern.md` documenting the three-phase shape, breaker reuse, timeout settings convention, and enum location.

Proof:

- `pytest recognition/tests/unit/test_scan_service_phase_split.py -x` — asserts `session.in_transaction()` is False at the moment the adapter call is awaited.
- `pytest recognition/tests/integration/test_assignment_writer.py recognition/tests/integration/test_end_to_end.py -x`
- ADR file exists and links back to this task plan.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded constitution rules sr-007, sr-008, rg-002, rg-008.
- [ ] Loaded the source assessment and scope before each slice.
- [ ] Confirmed `ctx7` is not required (asyncio + SQLAlchemy stable surfaces).
- [ ] Recorded ownership: backend Python only; no PHP/frontend/contract surface.

### Checklist for Slice 1: Parameter-object groupings

- [ ] Implement `ClusteringDependencies`, `ClusteringRuntimeConfig`, `ClusteringContext` as frozen dataclasses.
- [ ] Refactor `cluster_unclustered_identities`, `IncrementalClusteringRunner.__init__`, `_persist_and_cache_new_clusters` and all internal callers.
- [ ] Add `test_orchestrator_dependencies.py` covering arity and mypy round-trip.
- [ ] Run `pytest` + `mypy` + `ruff` for the recognition package.

### Checklist for Slice 2: Adopt existing `JobStatus`/`JobPhase`

- [ ] Grep clustering + scan paths for bare-string status sites; produce a checklist of files to edit.
- [ ] Replace assignments and comparisons with enum members.
- [ ] Extend `JobStatus`/`JobPhase` only if grep finds a value not yet on either enum; record the extension in the slice decision.
- [ ] Add `test_job_status_enum_adoption.py` enforcing the grep gate.
- [ ] Run `pytest` + `mypy` + grep gate.

### Checklist for Slice 3: Adapter timeout + circuit breaker

- [ ] Implement `wait_for_adapter` helper + `AdapterTimeoutError`.
- [ ] Implement `AdapterCircuitBreaker` (extract or new minimal); decide via slice-1 prep grep whether the existing breaker can share core.
- [ ] Wrap `embedding/generator.py:99` and the auto-labeler call site.
- [ ] Remove blanket `except Exception` from `generator.py` (let typed errors propagate).
- [ ] Add unit tests for timeout, breaker state transitions, and half-open behavior.
- [ ] Add per-adapter timeout settings, validated at load time.

### Checklist for Slice 4: Phase split + ADR

- [ ] Refactor `scan/service.py:save_job_results` into reserve-commit / call / persist-commit.
- [ ] Add `ON CONFLICT DO NOTHING` keyed on `(job_id, media_id)` for the persist step.
- [ ] Add `test_scan_service_phase_split.py` proving no open tx at adapter-call time.
- [ ] Audit other call sites for the same anti-pattern; record findings or follow-up tasks.
- [ ] Land ADR-008 documenting the integration-point pattern.
- [ ] Run integration regression suite.

## Review Readiness

- [ ] No boundary-touching implementation is left without matching test or ADR evidence.
- [ ] Runtime-parity check (`test_clustering_pool_isolation.py`) passes — bulkhead is intact after the orchestrator refactor.
- [ ] Handoff decision per slice records the change, the verification commands run, and any contract/ADR implications.
- [ ] `make review-run` lands a `pass` or `pass_with_findings` verdict before merge.
- [ ] All open findings on the task ref are `fixed` or explicitly `deferred`/`wontfix` with rationale.
- [ ] `handoff_close_check(enforce=True)` passes against the merge SHA.

## Stretch Goals

- [ ] If `AdapterCircuitBreaker` extraction goes cleanly, refactor `clustering_circuit_breaker.py` to reuse the new core. If it requires touching the HTTP admission contract, defer to a follow-up task.
- [ ] If grep finds duplicated breaker-state logic outside the two known sites, fold them into the new helper and note in the slice-complete decision.

## Success Criteria

- [ ] Unit tests prove timeout + breaker behavior for the embedding adapter and the auto-labeler entrypoint.
- [ ] Unit test proves `session.in_transaction()` is False at the moment the scan service awaits the adapter.
- [ ] Grep gate proves zero bare-string status assignments in clustering + scan paths.
- [ ] Orchestration entry takes ≤4 args (3 dataclasses + tenant/job context).
- [ ] ADR `docs/adrs/ADR-008-external-adapter-stability-pattern.md` exists, links to this task plan, and codifies the timeout + breaker + phase-split shape.
- [ ] `handoff_close_check(enforce=True)` passes.
- [ ] No new infra dependency in `pyproject.toml`.
