# ADR-009: Recognition Curation Refresh and Person Review Projection

> **Metadata**
>
> - **Date**: 2026-05-05
> - **Author**: Codex
> - **Status**: Conditional Accepted
> - **Decided on**: 2026-05-06
> - **Accepting decision**: `codex_conditional_accept_adr009_e15_planning_gate_20260506`
>
> **Purpose:** Resolve the design boundary for post-curation suggestion refresh,
> person-instance roster review projections, and curriculum review queues. This
> ADR unblocks the Tier 3 items in the recognition roster curation loop spec.

---

## Status

Conditional Accepted

## Date

2026-05-05

## Decision Date

2026-05-06

## Accepting Decision

`codex_conditional_accept_adr009_e15_planning_gate_20260506`

## Conditions

This ADR is accepted for downstream planning and implementation ordering with
the following conditions called out explicitly in the owning specs before code
work begins:

- `RCL-008` must define queue-membership predicates and the local projection
   authority for each named review queue.
- `DASH-007` must require a recorded durable-activity source decision before
   the dashboard demotes or replaces browser-local recent-job history.

## Conditions Satisfied (2026-05-17)

Both conditions are now met in the owning specs:

- `RCL-008` defines queue-membership predicates and names `RCL-004` as canonical
   projection authority — see `docs/specs/recognition-roster-curation-loop-spec.md`
   L304-310 (`singleton-proposals`, `hard-examples`,
   `needs-confirmation-after-merge`).
- `DASH-007` records the durable-activity source done-when —
   `docs/specs/alt-context-dashboard-operator-triage-spec.md` L183-240 requires
   a recorded handoff decision before any UI change demotes or replaces
   browser-local history.

Status remains `Conditional Accepted` in the metadata header for audit-trail
continuity (the original conditional-acceptance decision is the authoritative
acceptance event). This section is the operator-visible note that the
conditions have since been satisfied. Planning-review verification run:
`MAINT-roster-planning-review-chain-20260517-planning-009002ea` (verdict
decision `3103`).

## Context

The recognition roster assessment and spec identify a broken curation loop:
WordPress can bind a cluster to a local person, but the backend curation replay
path only receives partial binding state and does not reliably trigger the same
suggestion-surfacing path used by backend direct label edits. Roster entries are
also count-only, so the UI cannot provide the expected person review surface.

This ADR resolves the design questions blocking:

- `RCL-001` - post-curation event contract and outbox/replay semantics
- `RCL-004` - person-instance roster entry review model
- `RCL-002` - durable suggestion refresh when it touches replay boundaries
- `RCL-008` - curriculum review queues derived from curation and refresh state

### Constraints from prior review

- WordPress remains the operator-visible source of truth under ADR-003.
- Person remains the first-class local curation entity under ADR-002.
- Backend clustering and suggestion state remain advisory until projected locally.
- Outbox replay must remain idempotent and at-least-once.
- Review entries and curriculum queues are derived projections; they must be rebuildable from authoritative person, cluster, identity, and refresh state.
- Broad description-service refactoring is out of scope for E15-13; only enabling orchestration boundaries may change.

## Current State Inventory

- `apps/prototype-wp-alt-context/src/api/class-api.php::commit_roster_cluster` creates or binds a local person and enqueues `cluster_person_bound`, but the replay payload carries `cluster_uuid` and `person_uuid` without the authoritative person label.
- `apps/prototype-description-service/roster/application/curation_sync_service.py::_resolve_desired_label` updates labels only for `cluster_label_updated`; `cluster_person_bound` leaves the existing cluster label unchanged.
- `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py::refresh_for_cluster` refreshes existing pending suggestions for a cluster but returns when none exist.
- `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py::surface_for_newly_labeled_cluster` can discover missing suggestions, but it is only reached from selected backend paths.
- `apps/prototype-wp-alt-context/src/api/class-api.php::get_roster_entries` returns persons with `cluster_count` only.
- `packages/shared-contracts/schemas/roster-entry.schema.json` mirrors the count-only roster entry contract.
- `docs/adrs/ADR-002-person-as-first-class-local-entity.md` defines `wp_acx_persons` as the canonical local person entity.
- `docs/adrs/ADR-003-wordpress-local-authority-and-durable-outbox-replay.md` defines WordPress local authority, durable outbox replay, and projection acknowledgement.

### Downstream surfaces that must migrate together

- `apps/prototype-wp-alt-context/src/api/class-api.php` - curation commit, roster entry read model, and outbox payload.
- `apps/prototype-wp-alt-context/src/sovereign/sync/` - outbox drain and projection status refresh behavior.
- `apps/prototype-description-service/roster/application/curation_sync_service.py` - backend replay interpretation.
- `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py` - post-curation refresh discovery and per-event status.
- `apps/prototype-wp-alt-context/js/admin/pages/roster/` - person review, curriculum queues, cluster navigation, and face evidence UI.
- `packages/shared-contracts/schemas/roster-entry.schema.json` - shared roster entry projection contract.

## Decision

Use a **local-authority, derived-refresh, derived-projection** model.

WordPress remains authoritative for person curation. A cluster-person binding
emits a post-curation event with enough authoritative local context for backend
alignment and suggestion refresh. Backend suggestion refresh consumes that event
as derived async work. Roster entries and curriculum queues are local derived
projections over `wp_acx_persons`, projected clusters, identity members, and
suggestion refresh status.

### Chosen design rules

1. **WordPress owns the authoritative person label.** `cluster_person_bound`
   must carry or resolve the `person_uuid` and person name from local state.
   Backend replay must not infer a person label from stale cluster labels.

2. **Post-curation refresh is derived async work.** Suggestion refresh is not
   part of the user's synchronous local commit. It is triggered from a durable
   post-curation event and records per-event status so UI/projection code can
   distinguish queued, running, completed, no candidates, timed out, and failed.

3. **Backend refresh results are proposals.** Backend-created suggestions,
   singleton proposals, hard examples, and post-merge confirmations are advisory
   until projected locally and accepted/dismissed by the operator.

4. **Person review entries are projections, not a second person source of
   truth.** `wp_acx_persons` remains the write model. Roster entry review data
   is derived from person, cluster, identity member, media, bbox, and suggestion
   state.

5. **Curriculum queues are named local review projections.** The UI exposes
   singleton proposals, hard examples, and needs-confirmation-after-merge as
   review queues backed by suggestion/refresh state, not as hidden clustering
   internals.

6. **Aggregate metrics are separate from per-event status.** Per-event
   `CurationRefreshStatus` belongs to the durable replay workflow. Queue depth,
   p95/p99 latency, failure rate, recovery time, and lead-time SLOs belong to
   orchestration metrics.

### Target outcome

A user label/bind operation creates a local person review surface immediately,
then durable async refresh work surfaces related candidates and curriculum
queues. The UI can explain whether candidates are pending, refreshed, absent, or
failed without treating backend compute state as the live UX authority.

## Why This Decision

### It preserves the existing authority model

ADR-002 and ADR-003 already chose local person authority and durable replay.
This ADR extends those decisions to suggestion refresh rather than introducing a
backend-owned person or active-active curation model.

### It makes derived data explicit

Roster entries and curriculum queues need rich review context, but that context
is not new source-of-truth data. Treating it as projection data keeps the person
model stable and lets stale projections be refreshed or rebuilt.

### It makes suggestion failures visible

The old in-process background path could time out or skip candidate discovery
without a durable status surface. Per-event refresh status gives the UI and
operators a concrete state to inspect.

## Alternatives Considered

### 1. Backend owns person labels after replay

Rejected.

That conflicts with ADR-003's local-authority model and makes WordPress curation
dependent on backend label reconciliation.

### 2. Keep suggestion refresh as a best-effort background task

Rejected.

The reported failure is precisely that best-effort surfacing can disappear. The
workflow needs durable status and candidate creation semantics after curation.

### 3. Store roster entry review data as a second write model

Rejected.

That would create a second person/identity source of truth. The review surface
should be a projection over `wp_acx_persons` and recognition state.

### 4. Fold broad description-service refactoring into this ADR

Rejected.

The ADR resolves the event/projection boundary needed for E15-13. Larger service
modularization belongs to a later refactor phase after this workflow is stable.

## Consequences

### Positive

- Local curation remains usable and authoritative while backend refresh catches up.
- Suggestion refresh has durable per-event status instead of hidden timeout logs.
- Roster entries can become reviewable without replacing the Person model.
- Curriculum review queues become visible product surfaces.
- The design keeps broad service refactoring out of the critical launch path.

### Negative

- The outbox payload/replay contract must carry or resolve more curation context.
- The plugin needs richer projections and shared contracts for roster review data.
- Backend refresh status adds a new lifecycle surface to test and monitor.
- Operators may see queued/failed refresh state that was previously invisible.

### Guardrails for the follow-on implementation task

- Do not make backend cluster labels authoritative over `wp_acx_persons.name`.
- Do not update person review entries as independent write-model records.
- Do not hide refresh failures behind generic "no suggestions" UI.
- Do not build curriculum queues as frontend-only filters over raw clusters if the backend/projection state cannot explain membership.
- Preserve existing adapter timeouts, circuit breakers, database session timeouts, and pool bulkheads.
- Keep broad description-service refactoring out of E15-13 unless it is necessary to implement the post-curation refresh boundary.

## References

- Spec: [docs/specs/recognition-roster-curation-loop-spec.md](../specs/recognition-roster-curation-loop-spec.md)
- Assessment: [docs/assessments/current/recognition-roster-suggestion-workflow-assessment-2026-05-05.md](../assessments/current/recognition-roster-suggestion-workflow-assessment-2026-05-05.md)
- Implementation task plan: [docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md](../tasks/15.0/E15-13-roster-curation-loop-task-plan.md)
- Related: [ADR-002: Person as First-Class Local Entity](ADR-002-person-as-first-class-local-entity.md)
- Related: [ADR-003: WordPress Local Authority and Durable Outbox Replay](ADR-003-wordpress-local-authority-and-durable-outbox-replay.md)
- Related: [ADR-008: External Adapter Stability Pattern](ADR-008-external-adapter-stability-pattern.md)
