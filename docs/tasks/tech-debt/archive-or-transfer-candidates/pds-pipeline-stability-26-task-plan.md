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

Current state has three concrete stability gaps and two readability gaps. The single external adapter in scope is the InsightFace embedding/detector backend (`InsightFaceAdapter`). The auto-labeler under `recognition/application/labeling/auto_labeler.py` is a local DB allocator + pure helper, not a remote integration, and is **out of scope** for adapter-stability wrapping (see Not-Doing list below).

1. The InsightFace adapter call (`InsightFaceEmbeddingGenerator.generate` at [generator.py:99](../../../apps/prototype-description-service/recognition/application/embedding/generator.py#L99)) has no per-call timeout and is caught by a bare `except Exception` that swallows failures with a log line. A hung upstream blocks an asyncio task indefinitely.
2. The legacy/monolithic `ScanService.process_scan_job` wrapper at [scan/service.py:148](../../../apps/prototype-description-service/recognition/application/scan/service.py#L148) calls `mark_job_running` → `_detector.detect` → `save_job_results` in one method. The two `save_job_results` / `mark_job_running` commits do bracket the call, but the wrapper still hides the boundary and is the call shape used by `analyze_media` and tests. The newer `recognition/application/tasks/scan.py:process_scan_job_inline` already implements the explicit three-phase split (mark-running short tx → inference no DB → save-results short tx); this task formalizes that pattern as the canonical shape and deprecates the monolithic wrapper.
3. There is no application-boundary circuit breaker around the InsightFace adapter. The only breaker (`clustering_circuit_breaker.py`) wraps the HTTP admission endpoint, so adapter saturation degrades latency silently rather than shedding load fast.
4. Job-status assignments and comparisons in the clustering and scan paths use bare strings (`"running"`, `"completed"`, `"failed"`, `"pending"`) rather than the existing `JobStatus(StrEnum)` at [domain/job.py:12](../../../apps/prototype-description-service/recognition/domain/job.py#L12). Typos pass type-check; an exhaustive switch is impossible. Confirmed sites at slice-2 prep grep include `scan/service.py:89`, `routers/clusters.py:~361`, `deps/stores.py:40,55`, `routers/analyze.py:266`, `routers/analyze_multipart.py:368`.
5. `cluster_unclustered_identities` and `IncrementalClusteringRunner.__init__` each take 14 keyword arguments and duplicate them ([orchestrator.py:54-113](../../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L54)). Adding any new dependency (timeout config, breaker) makes the parameter list worse before it gets better, violating sr-008.

The literature crosswalk diagnoses these as Nygard's *Use Timeouts*, *Integration Points*, *Cascading Failures*, *Circuit Breaker* (chs. 4-5), Fowler's *Replace Magic Number with Symbolic Constant* (ch. 9), and *Introduce Parameter Object* (ch. 6).

## Constraints

- **Greenfield (no backcompat).** No production users; in-flight scan-job semantics may change without a migration story.
- **No new infra dependencies.** No Prometheus client, no OTel SDK, no Redis-backed breaker, no new sidecars. FastAPI + asyncpg + SQLAlchemy + stdlib only.
- **No DB schema changes.** Status columns remain `text`. Any SQLAlchemy `Enum(JobStatus, native_enum=False)` wiring is opt-in per column we touch and does not change column type.
- **No worker / admission-lock concurrency changes.** F-2's phase split touches `scan/service.py` boundaries only. `scan_worker` reclaim semantics, the `with_for_update()` admission lock, and clustering-pool sizing are out of scope.
- **Idempotency relies on existing constraints, not new schema.** The persist step is already idempotent via `MediaIdentity`'s `unique_media_identity` constraint on `(tenant_id, media_id, identity_type, bbox_x, bbox_y)` ([identity.py:83](../../../apps/prototype-description-service/db/models/identity.py#L83)) plus the Identity-ID-Recycling logic in `ScanService._persist_identities`. F-2 must preserve this property — no new `ON CONFLICT` clause keyed on `(job_id, media_id)` is added (which would require a schema change ruled out by the no-DB-schema-changes constraint), and the persist phase must remain replayable against the existing constraint (rg-002 spirit: do not split an atomic write into multiple non-idempotent steps).

## Workflow Principles

- **Adapter calls follow `commit → call → commit`.** Any code path that holds `_session.in_transaction()` while awaiting an external adapter is a defect.
- **Adapter calls are bounded by an `asyncio.wait_for` timeout** sourced from settings, never a hardcoded literal (rg-008: validate at load time).
- **Status values are `JobStatus`/`JobPhase` enum members at every assignment site in clustering and scan paths.** Bare strings are review-blocking (sr-007).
- **Orchestration entrypoints take ≤4 grouped dataclasses, not 14 kwargs** (sr-008).
- **One ADR per architectural seam, not per finding.** A single ADR codifies the external-integration shape (timeout + breaker + phase split); per-finding rationale lives in slice-complete decisions and the assessment doc.

## Terminology

- **Adapter** — concrete implementation of a remote/external integration. In this task the only adapter is `InsightFaceAdapter` (under `recognition/application/embedding/` and `recognition/infrastructure/embeddings/`). The auto-labeler under `recognition/application/labeling/` is a local DB allocator + pure helper, not an adapter.
- **AdapterCircuitBreaker** — new (or refactored-out) reusable breaker wrapping adapter calls at the application boundary. Distinct from the existing HTTP-admission `clustering_circuit_breaker`.
- **Phase split** — making the explicit reserve-commit / detect / save-results-commit shape (already realized in `tasks/scan.py:process_scan_job_inline`) the canonical scan call pattern, replacing the legacy monolithic `ScanService.process_scan_job` wrapper.
- **`JobStatus`** — the existing `StrEnum` at [domain/job.py:12](../../../apps/prototype-description-service/recognition/domain/job.py#L12) (`PENDING`/`RUNNING`/`COMPLETED`/`FAILED`).
- **`JobPhase`** — the existing `StrEnum` at [domain/job.py:30](../../../apps/prototype-description-service/recognition/domain/job.py#L30) (`QUEUED`/`DETECTING`/`CLUSTERING`/`RETRYING`/`AWAITING_PROJECTION`/`FAILED`/`COMPLETE`).

## Current State Analysis

- **Works today:** chunked durable clustering, three-pool engine bulkhead, admission-side circuit breaker, adaptive chunk sizing (EWMA), per-tenant RLS via `SET LOCAL`, idempotent member writes via `ON CONFLICT DO NOTHING`. None of these regress in this task.
- **Broken/drifting:** items 1-5 in Problem Statement above.
- **Misleading:** the existence of `JobStatus(StrEnum)` plus the prevalence of bare-string assignments suggests a partial enum migration that stalled. Consumers (`job_utils.py`) already import the enum, but writers across the scan path (`scan/service.py:68,89,143`, `routers/clusters.py:~361`, `routers/analyze.py:266`, `routers/analyze_multipart.py:368`, `deps/stores.py:40,55`) still use string literals. Likewise, the `tasks/scan.py:process_scan_job_inline` worker entrypoint already implements the explicit `commit → call → commit` shape — the legacy `ScanService.process_scan_job` wrapper is what hides the boundary.

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

### 2026-04-29 Env Template No-Change Rationale

The `codex_slice_complete_pds_pipeline_stability_26_env_example_fixture_durable_fix` slice changes branch tracking for `apps/prototype-description-service/.env.example` and refreshes the example fixture, but it does **not** change the runtime environment contract, variable vocabulary, default semantics, or downstream assumptions. The owning boundary remains the local environment contract documented by the checked-in `.env.example` template plus the existing operator/docs surfaces. This slice is fixture durability and review-readiness hygiene only: `.gitignore` now preserves `.env*.example` files in normal git flow so the canonical example template stays reviewable and mergeable without force-add workarounds.

Verification for this no-change rationale:

- `pyenv exec python -m pytest recognition/tests/unit -q` on commit `9234b8b21a23c179371472ef3852747defc11eaa`
- `make review-ready TASK=pds-pipeline-stability-26` should treat the env-example slice as checklist-backed no-contract-change work once this note lands

## Proposed Solution

Five small refactors landed in dependency order, each its own slice with tests. The ADR is drafted alongside slice 4 (the phase split) and references the timeout helper (slice 2) and breaker (slice 3) it builds on.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `recognition/application/orchestration/clustering/orchestrator.py` | Group 14 kwargs into 3 dataclasses; refactor `_persist_and_cache_new_clusters` (L374) signature similarly |
| backend (new) | `recognition/application/orchestration/clustering/dependencies.py` (or sibling) | Define `ClusteringDependencies`, `ClusteringRuntimeConfig`, `ClusteringContext` frozen dataclasses |
| backend | Bare-string status sites confirmed at slice-2 prep grep: `recognition/interface_adapters/http/routers/clusters.py` (~L361), `recognition/interface_adapters/http/routers/analyze.py` (L266), `recognition/interface_adapters/http/routers/analyze_multipart.py` (L368), `recognition/interface_adapters/http/deps/stores.py` (L40, L55), `recognition/application/scan/service.py` (L68 `analyze_media`, L89 `mark_job_running`, L143 `save_job_results`). Slice-2 grep gate widens to all of these surfaces. | Replace bare-string status writes/comparisons with `JobStatus`/`JobPhase` members |
| backend (new) | `recognition/application/integrations/timeouts.py` | `wait_for_adapter(coro, *, timeout, adapter_name)` helper raising typed `AdapterTimeoutError` (parity with `integrations/circuit_breaker.py`) |
| backend (new) | `recognition/application/integrations/circuit_breaker.py` | `AdapterCircuitBreaker` (state machine extracted from / shared with `clustering_circuit_breaker.py`) |
| backend | `recognition/application/embedding/generator.py` (~L99) | Wrap `await self._adapter.analyze(...)` in timeout + breaker; remove blanket `except Exception` swallowing. Sole adapter wrapping site. |
| backend | `recognition/application/scan/service.py` (`process_scan_job` L148, `analyze_media` L51) | Replace the monolithic `process_scan_job` wrapper with an explicit reserve-commit / detect / save-results-commit shape that mirrors `tasks/scan.py:process_scan_job_inline`. `analyze_media` either composes the same three phases or is deprecated in favor of the explicit caller. No new `ON CONFLICT` clause; idempotency is preserved by the existing `unique_media_identity` constraint and `_persist_identities` recycling logic. |
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
  - Manual grep gate: `! grep -rnE 'status\s*=\s*"(running|completed|failed|pending|processing|cancelled|skipped)"' apps/prototype-description-service/recognition/application/scan apps/prototype-description-service/recognition/application/orchestration apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze_multipart.py apps/prototype-description-service/recognition/interface_adapters/http/deps/stores.py` returns no matches at slice 2 close. Retention/export router sites (`retention.py`, `analyze.py:266` is in scope but retention is not — see Not-Doing) remain bare strings until a follow-up task.
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

- Grep clustering + scan paths for bare-string status assignments and comparisons; replace with `JobStatus.<MEMBER>` / `JobPhase.<MEMBER>`. Surface includes `scan/service.py`, `orchestration/`, `routers/clusters.py`, `routers/analyze.py`, `routers/analyze_multipart.py`, `deps/stores.py` (including the in-memory fallback at L40, L55).
- If grep finds a status value not in either enum, extend `JobStatus` (preferred) or `JobPhase` and call out the addition in the slice-complete decision.
- Wire SQLAlchemy `Enum(JobStatus, native_enum=False)` only on columns this slice touches; do not change DB schema.
- New test `recognition/tests/unit/test_job_status_enum_adoption.py` asserts the grep gate (no bare-string status literals in scan + clustering paths). Lives under the default pytest collection root, so `make check-all` (which runs the recognition suite without `-k` filters) enforces the gate on every CI run — no separate `make` target required.

Proof:

- `pytest recognition/tests/unit/test_job_status_enum_adoption.py -x`
- `mypy recognition/`
- Manual grep gate from Verification Strategy returns 0 matches.

### Slice 3: Adapter timeout helper + `AdapterCircuitBreaker` (F-1, F-3)

**Goal:** Bound the InsightFace adapter call with `asyncio.wait_for` and an `AdapterCircuitBreaker`. Wired at `InsightFaceEmbeddingGenerator.generate` (the sole external adapter seam in the recognition pipeline). The auto-labeler is local DB + pure logic and is **explicitly out of scope** for adapter wrapping (it has no remote latency or failure mode to bound).

**Breaker configuration surface** (frozen dataclass `AdapterBreakerConfig` in the new settings module, validated at load time per rg-008):

| Field | Default (initial; tune against existing `clustering_circuit_breaker.py`) |
| --- | --- |
| `failure_count_threshold` | 5 |
| `failure_window_seconds` | 60 |
| `half_open_probe_count` | 1 |
| `success_close_threshold` | 1 |
| `open_state_cooldown_seconds` | 30 |

Per-adapter timeout: `embedding_timeout_s` (default 10). Sole adapter setting; overridable via environment-driven settings.

**Failure handling at the application boundary** (resolves the gap left by removing the blanket `except`):

- `AdapterTimeoutError` and `BreakerOpenError` are caught at the orchestrator/scan-service boundary, not inside the generator.
- Mapping: timeout or breaker-open → `JobStatus.FAILED` with `JobPhase.RETRYING` if the worker's retry budget remains; `JobStatus.FAILED` (terminal) once exhausted. Error message records adapter name and error class.
- The clustering chunk loop treats a single chunk's adapter failure as a chunk-level failure (skip + record), not a job-level failure, preserving rg-007 (bounded stall detection).

Changes:

- New `wait_for_adapter(coro, *, timeout, adapter_name)` helper raising typed `AdapterTimeoutError`. Timeout sourced from `recognition/application/settings/adapters.py`.
- New `AdapterCircuitBreaker` in `recognition/application/integrations/circuit_breaker.py`. Slice prep grep decides extract-vs-new against the existing `clustering_circuit_breaker.py` state machine; if extraction is invasive, ship a minimal new breaker and defer the existing-breaker refactor to a follow-up task (out of slice scope).
- Wrap the `embedding/generator.py:99` adapter call site only. Auto-labeler intentionally not wrapped (local DB + pure logic).
- Remove blanket `except Exception` from generator; declare typed propagation contract above.
- Update orchestrator/scan-service catch sites to apply the failure-handling mapping; cover with unit tests.
- New unit tests: timeout fires; breaker opens after N failures; half-open probe; closed→open→half-open transitions; orchestrator/scan caller maps typed errors to expected `JobStatus`/`JobPhase`.

Proof:

- `pytest recognition/tests/unit/test_wait_for_adapter.py recognition/tests/unit/test_adapter_circuit_breaker.py -x`
- Existing embedding tests pass unchanged.

### Slice 4: Canonicalize `commit → call → commit` for scan jobs + ADR (F-2)

**Goal:** Make the explicit three-phase shape from `tasks/scan.py:process_scan_job_inline` the canonical scan call pattern, and remove or formalize the legacy monolithic `ScanService.process_scan_job` wrapper. Land the ADR codifying the pattern.

**Current-state baseline** (verified at plan time, commit `21d1a90e`):

- `recognition/application/tasks/scan.py:process_scan_job_inline` already implements the explicit split: short tx for mark-running → no-DB inference → short tx for save-results.
- `ScanService.mark_job_running` (L83-92) and `ScanService.save_job_results` (L94-146) each commit on exit, so the *individual* helpers respect the boundary.
- The gap is the legacy wrapper `ScanService.process_scan_job` (L148-169) and `ScanService.analyze_media` (L51-81), which call the helpers in one method and obscure the boundary; tests and `analyze_media` still hit the wrapper. No transaction is currently held across the adapter call by the `tasks/scan.py` path; the risk is that a future caller adds a new code path that *does* hold one.

Changes:

- Either (a) deprecate `ScanService.process_scan_job` and `ScanService.analyze_media` in favor of an explicit caller pattern documented in the ADR, or (b) inline them as thin pass-throughs to a shared helper (`run_scan_three_phase(...)`) that owns the reserve-commit / detect / save-results-commit shape. Decision recorded in slice-complete.
- Idempotency: persist phase remains backed by the existing `unique_media_identity` constraint and Identity-ID-Recycling logic in `_persist_identities`. **No new `ON CONFLICT DO NOTHING` clause is added** (would require a schema change ruled out by constraints).
- Audit any other adapter call sites under `recognition/application/` for the `_session.in_transaction() == True at adapter call` anti-pattern; if any are found beyond the known wrapper, document them in the slice-complete decision with a follow-up task ref.
- Land `docs/adrs/ADR-008-external-adapter-stability-pattern.md` documenting (a) the three-phase shape, (b) `AdapterCircuitBreaker` reuse, (c) per-adapter timeout settings convention, (d) `JobStatus`/`JobPhase` enum location, (e) why idempotency relies on `unique_media_identity` rather than a new `(job_id, media_id)` constraint.

Proof:

- `pytest recognition/tests/unit/test_scan_service_phase_split.py -x` — asserts `session.in_transaction()` is False at the moment the adapter call is awaited (covering both the shared helper and `analyze_media`'s callers).
- `pytest recognition/tests/integration/test_assignment_writer.py recognition/tests/integration/test_end_to_end.py -x` (regression: re-running detection on the same media yields the same `MediaIdentity` rows via the existing constraint).
- ADR file exists and links back to this task plan.

## Consolidated Checklist

> **Status note (2026-04-29):** Remaining unchecked items are either blocked by repo-wide baseline failures outside this slice (`mypy recognition/`, `ruff check recognition/`) or require a clean committed branch and pre-merge review evidence (`make review-run`, `handoff_close_check(enforce=True)`).

## Context and Ownership

- [x] Loaded constitution rules sr-007, sr-008, rg-002, rg-008.
- [x] Loaded the source assessment and scope before each slice.
- [x] Confirmed `ctx7` is not required (asyncio + SQLAlchemy stable surfaces).
- [x] Recorded ownership: backend Python only; no PHP/frontend/contract surface.

### Checklist for Slice 1: Parameter-object groupings

- [x] Implement `ClusteringDependencies`, `ClusteringRuntimeConfig`, `ClusteringContext` as frozen dataclasses.
- [x] Refactor `cluster_unclustered_identities`, `IncrementalClusteringRunner.__init__`, `_persist_and_cache_new_clusters` and all internal callers.
- [x] Add `test_orchestrator_dependencies.py` covering arity and mypy round-trip.
- [ ] Run `pytest` + `mypy` + `ruff` for the recognition package.

### Checklist for Slice 2: Adopt existing `JobStatus`/`JobPhase`

- [x] Grep clustering + scan paths for bare-string status sites; minimum surface = `scan/service.py`, `orchestration/`, `routers/clusters.py`, `routers/analyze.py`, `routers/analyze_multipart.py`, `deps/stores.py`.
- [x] Replace assignments and comparisons with enum members at every confirmed site (including the in-memory fallback service in `stores.py`).
- [x] Extend `JobStatus`/`JobPhase` only if grep finds a value not yet on either enum (e.g. `processing`, `cancelled`, `skipped` from `IdentityScanJobItem.valid_item_status`); record the extension in the slice decision.
- [x] Add `test_job_status_enum_adoption.py` enforcing the widened grep gate.
- [ ] Run `pytest` + `mypy` + grep gate.

### Checklist for Slice 3: Adapter timeout + circuit breaker

- [x] Implement `wait_for_adapter` helper + `AdapterTimeoutError`.
- [x] Implement `AdapterCircuitBreaker` (extract or new minimal); decide via slice-3 prep grep whether the existing breaker can share core.
- [x] Wrap `embedding/generator.py:99` only (auto-labeler intentionally not wrapped).
- [x] Remove blanket `except Exception` from `generator.py` (let typed errors propagate).
- [x] Add unit tests for timeout, breaker state transitions, and half-open behavior.
- [x] Add `embedding_timeout_s` + `AdapterBreakerConfig` settings to `recognition/application/settings/adapters.py`, validated at load time.

### Checklist for Slice 4: Canonicalize phase split + ADR

- [x] Decide between (a) deprecate `ScanService.process_scan_job`/`analyze_media` or (b) inline as pass-throughs to a shared `run_scan_three_phase` helper. Record decision.
- [x] Implement the chosen shape; preserve existing `_persist_identities` Identity-ID-Recycling + `unique_media_identity` constraint as the idempotency seam (no new `ON CONFLICT` clause, no schema change).
- [x] Add `test_scan_service_phase_split.py` proving no open tx at adapter-call time across both `tasks/scan.py:process_scan_job_inline` and the new shared helper.
- [x] Add a regression test that re-running detection on the same media yields the same `MediaIdentity` rows (validates idempotency via existing constraint).
- [x] Audit other adapter call sites under `recognition/application/` for the same anti-pattern; record findings or follow-up tasks.
- [x] Land ADR-008 documenting the integration-point pattern, including the idempotency rationale.
- [x] Run integration regression suite.

## Review Readiness

- [x] No boundary-touching implementation is left without matching test or ADR evidence.
- [x] Runtime-parity check (`test_clustering_pool_isolation.py`) passes — bulkhead is intact after the orchestrator refactor.
- [x] Handoff decision per slice records the change, the verification commands run, and any contract/ADR implications.
- [ ] `make review-run` lands a `pass` or `pass_with_findings` verdict before merge.
- [x] All open findings on the task ref are `fixed` or explicitly `deferred`/`wontfix` with rationale.
- [ ] `handoff_close_check(enforce=True)` passes against the merge SHA.

## Stretch Goals

- [x] If `AdapterCircuitBreaker` extraction goes cleanly, refactor `clustering_circuit_breaker.py` to reuse the new core. If it requires touching the HTTP admission contract, defer to a follow-up task.
- [ ] If grep finds duplicated breaker-state logic outside the two known sites, fold them into the new helper and note in the slice-complete decision.

## Success Criteria

- [ ] Unit tests prove timeout + breaker behavior for the embedding adapter and the auto-labeler entrypoint.
- [x] Unit test proves `session.in_transaction()` is False at the moment the scan service awaits the adapter.
- [x] Grep gate proves zero bare-string status assignments in clustering + scan paths.
- [x] Orchestration entry takes ≤4 args (3 dataclasses + tenant/job context).
- [x] ADR `docs/adrs/ADR-008-external-adapter-stability-pattern.md` exists, links to this task plan, and codifies the timeout + breaker + phase-split shape.
- [ ] `handoff_close_check(enforce=True)` passes.
- [x] No new infra dependency in `pyproject.toml`.

## Consolidated Triage Checklist (2026-04-30)

**Disposition:** Archive candidate; app implementation is present and only lifecycle evidence needs final confirmation.
**Evaluation basis:** Current `main` app code under `apps/prototype-description-service`.

- [x] Parameter-object refactor exists via `recognition/application/orchestration/clustering/dependencies.py`.
- [x] Adapter timeout and circuit-breaker integration files exist under `recognition/application/integrations/`.
- [x] Scan queue status/correlation/attempt tracking exists in the current job models and repository implementation.
- [x] ADR-008 exists and documents the external-adapter stability pattern.
- [ ] Resolve the remaining checklist mismatch: this doc still asks for auto-labeler timeout coverage, while the task scope later says the auto-labeler is local DB/pure logic and out of scope.
- [ ] Confirm review-run and `handoff_close_check(enforce=True)` evidence for `pds-pipeline-stability-26` before archiving.
- [ ] Move to archive after lifecycle evidence is confirmed or add a short closure note explaining why the remaining unchecked boxes are no longer required.
