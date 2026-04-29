# ADR-008: External Adapter Stability Pattern

> **Metadata**
>
> - **Date**: 2026-04-28
> - **Author**: GPT-5.4
> - **Status**: Proposed
>
> **Purpose:** Codifies the application-boundary pattern for remote adapter
> calls in the recognition service: commit-bounded DB phases, per-call
> timeouts, application-layer circuit breaking, and explicit idempotency at
> the persistence seam. This ADR closes the architectural question left open
> by `pds-pipeline-stability-26` Slice 4 and gives future adapter work a
> single pattern to follow.

---

## Status

Proposed

## Date

2026-04-28

## Context

The recognition service calls an external InsightFace adapter from inside the
application layer. Prior to `pds-pipeline-stability-26`, those calls had three
stability gaps:

- no shared per-call timeout policy for remote adapter operations
- no application-boundary circuit breaker around the concrete adapter seams
- no explicit, documented phase boundary between short DB transactions and the
  no-DB remote inference step

The task plan at
`docs/tasks/tech-debt/pds-pipeline-stability-26-task-plan.md` decomposed the
fix into bounded slices:

- Slice 3 introduced `wait_for_adapter`, typed timeout failures, and
  `AdapterCircuitBreaker` for the concrete generator and detector seams.
- Slice 4 made the scan pipeline's ordered phase contract explicit through
  `run_scan_three_phase`, then required this ADR plus an idempotency proof.

### Current adapter surface inventory

Inside `apps/prototype-description-service/recognition/application/`, the
remote adapter seams in scope today are:

- `embedding/generator.py` -> `InsightFaceAdapter.analyze(...)`
- `embedding/detector.py` -> `InsightFaceAdapter.detect_faces(...)`

Those seams are reached from the scan-task boundary in
`application/tasks/scan.py`, which now owns the explicit
mark-running -> detect -> persist shape for the inline path. The legacy
`ScanService.process_scan_job` remains a single-session caller, but it now
shares the same ordered phase contract through `run_scan_three_phase`.
`recognition/tests/unit/test_adapter_surface_inventory.py` now serves as an
executable inventory guard so new application-layer adapter seams do not land
silently.

### Constraints from prior review

- Greenfield policy applies: prefer the clean pattern over compatibility shims.
- No schema migration is allowed for this task. Idempotency must rely on the
  existing `unique_media_identity` seam and the current Identity ID recycling
  behavior.
- No new infrastructure dependency is allowed. Timeouts and breaker behavior
  must use stdlib + repo-local code.
- The scan-task boundary remains responsible for job-state mapping when the
  adapter times out or the breaker is open.

## Decision

Use the following application-boundary stability pattern for remote adapters in
the recognition service:

1. **Short DB phase -> remote adapter phase -> short DB phase.**
   A caller that orchestrates remote inference must separate transactional DB
   work from the adapter await point. The canonical ordered contract is now
   expressed by `run_scan_three_phase(...)`.

2. **Every remote adapter await is wrapped in a per-call timeout.**
   Application-layer callers use `wait_for_adapter(...)` and raise typed timeout
   errors (`AdapterTimeoutError`, `DetectionTimeoutError`,
   `EmbeddingTimeoutError`) rather than swallowing hangs behind generic
   exceptions.

3. **Every remote adapter seam is guarded by an application-layer circuit
   breaker.**
   The concrete seams in `generator.py` and `detector.py` use
   `AdapterCircuitBreaker` so repeated remote failures fast-fail before the
   service keeps stacking latency.

4. **Persistence idempotency remains at the identity-write seam.**
   Repeated scans over the same media do not introduce a new uniqueness key or
   `ON CONFLICT` policy. The existing `unique_media_identity` constraint and
   `_persist_identities` recycling/match-update behavior remain the idempotency
   contract.

5. **Job-state mapping stays at the orchestration boundary, not inside the
   adapter wrappers.**
   The generator and detector raise typed failures; `tasks.scan` and related
   orchestration callers decide whether those failures mark the job failed,
   trigger retry behavior, or surface an operator-facing error.

## Why This Decision

### The failure mode belongs at the application boundary

Timeouts and breaker transitions are not repository concerns and not transport
adapter concerns. They are part of how the application chooses to consume a
remote dependency. Keeping them at the application boundary preserves explicit
ownership of degraded behavior.

### Ordered phase boundaries are more reviewable than implicit sequencing

The old scan path relied on readers inferring the transaction shape from a
monolithic wrapper plus helper internals. `run_scan_three_phase` makes the
ordered contract visible and testable without moving DB ownership into a
generic orchestration framework.

### Idempotency already has a durable seam

The system already has a natural replay boundary: the identity locator fields
and the `unique_media_identity` constraint. Reusing that seam is lower risk
than inventing a new schema-level uniqueness key for scan jobs.

## Alternatives Considered

### 1. Keep the remote adapter call inside one long-lived DB phase

Rejected.

That shape makes slow or failing remote inference hold DB resources longer than
necessary and obscures where failure mapping actually lives.

### 2. Put retries and job-state mutation inside the adapter wrappers

Rejected.

The wrappers would then own business semantics rather than adapter semantics.
That couples low-level adapter code to workflow policy and makes reuse harder.

### 3. Add a new scan-job uniqueness key or `ON CONFLICT` path for replay

Rejected.

The task explicitly disallows schema changes, and the service already has a
stable write seam for replay through `_persist_identities` and
`unique_media_identity`.

## Consequences

### Positive

- Remote adapter hangs and repeated failures now fail fast with typed errors.
- The scan pipeline's phase ordering is explicit and unit-testable.
- Future adapter work has a single documented pattern instead of per-call
  improvisation.

### Negative

- The shared helper is intentionally narrow and must stay that way; callers
  still own session scope and error mapping.
- Idempotency proof remains a separate executable requirement. This ADR chooses
  the seam; it does not replace the regression test.

## Follow-on Guardrails

- New remote adapter call sites in `recognition/application/` should follow the
  same timeout + breaker + phase-boundary pattern rather than calling a remote
  adapter directly from inside a long-lived transaction.
- If a future caller needs richer shared behavior than ordered phase execution,
  prefer adding one specific cross-cutting concern to `run_scan_three_phase`
  rather than turning it into a generic workflow abstraction.
- The idempotency regression test for replay on the same media remains required
  before Slice 4 is complete.

## References

- Task plan: `docs/tasks/tech-debt/pds-pipeline-stability-26-task-plan.md`
- Scope: `docs/scopes/pds-pipeline-stability-26.md`
- Assessment: `docs/assessments/clustering-pipeline-postgres-refactor-literature-2026-04-26.md`
- Implementation surfaces:
  - `apps/prototype-description-service/recognition/application/embedding/generator.py`
  - `apps/prototype-description-service/recognition/application/embedding/detector.py`
  - `apps/prototype-description-service/recognition/application/integrations/timeouts.py`
  - `apps/prototype-description-service/recognition/application/integrations/circuit_breaker.py`
  - `apps/prototype-description-service/recognition/application/scan/service.py`
  - `apps/prototype-description-service/recognition/application/tasks/scan.py`