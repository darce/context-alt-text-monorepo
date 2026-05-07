# E15-19. Preimplementation Roster Refresh Projection Foundation

> **Metadata**
>
> - **Date**: 2026-05-06 16:10 EST
> - **Author**: Codex
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-19
> - **Target Branch**: `feature/e15-19-preimpl-roster-refresh-projection-foundation`
> - **Review Coverage Target**: 2
> - **Start Command**: `make task-start TASK=E15-19 OBJECTIVE="Implement PREIMPL Tier 0 roster refresh and projection gates"`

---

## Objective

Implement Tier 0 PREIMPL-002, PREIMPL-003, and PREIMPL-004 in Slices 1-4, then land Tier 2 PREIMPL-008 plus the roster-owned portion of PREIMPL-009 in Slice 5 from [docs/specs/e15-app-refactoring-preimplementation-spec.md](../../specs/e15-app-refactoring-preimplementation-spec.md). When complete, local person authority, roster review projections, post-curation refresh, and suggestion scan bounds are contract-safe before person-first UI work expands them, and Tier 2 diagnostics/controller work cannot block Tier 0 close.

## Problem Statement

The current curation loop mixes person writes, count-only roster reads, backend replay, and suggestion refresh across different surfaces. E15-13 already owns much of this behavior, but the PREIMPL spec adds stricter gates: ADR-009 must be accepted, RCL-004 must be canonical, refresh must be durable and bounded, projection freshness must be source-backed, and controller extraction must stay tied to changed behavior.

This plan supersedes [E15-13](E15-13-roster-curation-loop-task-plan.md) as the canonical PREIMPL roster/refresh implementation track. Before Slice 1 code edits, record the superseding handoff decision for E15-19 so reviews have an explicit retirement link. Leave E15-13 on its documented lifecycle while its existing branch/worktree remains active, then retire it through the normal done/archive flow after that branch/worktree is actually closed.

## Constraints

- ADR-009 must be accepted or conditionally accepted before contract-changing event/projection work begins.
- `wp_acx_persons` remains the local person write model.
- RCL-004 enriched roster-entry projection is canonical; RSU TypeScript shapes are UI consumption notes.
- Broad description-service refactoring is out of scope.
- Reset behavior must not expand until projection/read contracts are planning-reviewed.

## Workflow Principles

- Source facts and derived projection fields must be explicit.
- Refresh work can be asynchronous, but it must be durable, idempotent, bounded, and status-backed.
- Queue membership must be projection-backed, not frontend-only filtering.
- Controller extraction happens only where this task changes behavior.

## Terminology

- **RCL-004 enriched roster-entry projection**: Canonical shared roster projection with `person_uuid`, evidence, face instances, queue memberships, freshness/status, and allowed actions.
- **Post-curation event**: Durable event emitted after local/backend curation that drives suggestion refresh.
- **Candidate partition**: Explicit bounded candidate set for refresh work; full tenant scans are reserved for backfill.
- **Projection freshness**: Source version or rebuild timestamp that lets operators distinguish current, refreshing, stale, and failed projections.

## Current State Analysis

- `apps/prototype-wp-alt-context/src/api/class-api.php` mixes curation writes, roster read projection, and outbox enqueueing.
- `packages/shared-contracts/schemas/roster-entry.schema.json` is still count-only.
- `cluster_person_bound` payloads do not carry or resolve the authoritative person label.
- `refresh_for_cluster()` updates existing pending suggestions but can skip missing candidates.
- `surface_for_newly_labeled_cluster()` can fall back to broad cluster scans without product-visible latency/status outcomes.
- Projection freshness and rebuild correctness are not yet acceptance gates for RCL-004.

## Target Outcome

Curation emits a durable post-curation event with enough local person context to refresh suggestions. Refresh creates missing candidates, updates existing candidates, records per-event status, and uses bounded candidate partitions. The WordPress roster API returns the RCL-004 enriched roster-entry projection with source/freshness fields, and controller extraction is limited to named use cases.

## Context Loading

- Rules: `docs/agentic/rules/development-workflow.md`
- Rules: `docs/agentic/rules/backend-php-guidelines.md`
- Rules: `docs/agentic/rules/backend-python-guidelines.md`
- Rules: `docs/agentic/rules/testing-php.md`
- Spec: `docs/specs/e15-app-refactoring-preimplementation-spec.md`
- Spec: `docs/specs/recognition-roster-curation-loop-spec.md`
- ADR: `docs/adrs/ADR-009-recognition-curation-refresh-and-person-review-projection.md`
- Related task: `docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md`
- Handoff/MCP state: active task `E15-19`, ADR-009 planning findings, RCL planning findings, PREIMPL findings
- External docs via `ctx7` only if: SQLAlchemy, WordPress REST, or PHPUnit behavior blocks a concrete implementation decision.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| WordPress outbox -> backend curation replay | plugin + backend | `cluster_person_bound` lacks authoritative label context | event carries/resolves person label and idempotency key | replay remains at-least-once | PHP outbox + backend replay tests |
| Shared roster schema | shared contracts + plugin + frontend | count-only roster entry | RCL-004 enriched roster-entry projection | existing callers migrate in same slice | schema/codegen + API tests |
| Suggestion refresh | backend | existing pending-only or broad scan paths | durable create-missing/refresh-existing workflow with bounded candidates | new workflow; old entrypoints wrapped or retired | backend refresh tests |
| Local projection freshness | plugin projection | freshness not part of contract | source version/rebuild timestamp/status exposed | additive to projection | projection rebuild tests |
| PHP controller boundaries | plugin | mixed controller methods | named repository/mapper/use-case helpers | public REST route compatibility | PHPUnit through public API |

## Proposed Solution

Land the work in five slices: accept or conditional-accept ADR-009, introduce the event/status contract, expand and test the RCL-004 projection, bound suggestion refresh scans, and finish with projection integrity plus bounded controller extraction.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| ADR gate | `docs/adrs/ADR-009-recognition-curation-refresh-and-person-review-projection.md` | Move to accepted/conditional accepted with decision id before contract edits |
| shared schema | `packages/shared-contracts/schemas/roster-entry.schema.json` | Add RCL-004 projection fields |
| plugin API | `apps/prototype-wp-alt-context/src/api/class-api.php` | Delegate roster projection and curation outbox operations to named helpers |
| plugin projection | `apps/prototype-wp-alt-context/src/sovereign/` | Project roster review data and freshness/status |
| backend replay | `apps/prototype-description-service/roster/application/curation_sync_service.py` | Map curation replay to post-curation event/status |
| backend refresh | `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py` | Bound candidates and record status outcomes |
| tests | `apps/prototype-description-service/**/tests`, `apps/prototype-wp-alt-context/tests/Unit` | Add replay, refresh, projection, and API tests |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/recognition/application/orchestration/curation_job.py` | Merge cleanup refresh entrypoint |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php` | Projection rebuild/freshness owner |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php` | Cluster projection source |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php` | Sync/freshness source |
| `docs/tasks/15.0/E15-17-roster-person-review-scrub-workspace-task-plan.md` | Consumer of RCL-004 projection |

## Verification Strategy

- Deterministic tests:
  - `pyenv exec pytest apps/prototype-description-service/recognition/tests apps/prototype-description-service/roster`
  - `cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit`
  - shared contract schema/codegen check for `roster-entry`
- Runtime-parity / environment checks:
  - Seed or perform a local curation and verify the roster projection reports person evidence and freshness.
- Contract/fixture verification:
  - Replay/idempotency tests prove repeated outbox delivery does not duplicate refresh work.
  - Refresh tests cover no-candidate, timeout, failure, created, and refreshed outcomes.
- Manual verification:
  - WordPress roster entries show a person with evidence after a cluster bind once projection data exists.

## Slice Delivery

### Slice 1: ADR and Contract Gate

**Goal**: Remove ambiguity before changing cross-service contracts.

Changes:

- Accept or conditionally accept ADR-009 with a recorded decision id.
- Confirm RCL-004 is the canonical projection contract.
- Record any conditional constraints in handoff before code edits.

Proof:

- ADR status and handoff decision exist before event/projection implementation begins.

### Slice 2: Durable Post-Curation Event and Refresh Status

**Goal**: Make curation replay produce durable refresh work.

Changes:

- Carry or resolve authoritative local person labels for `cluster_person_bound`.
- Add or map to one post-curation event contract.
- Persist per-event refresh status and idempotency keys.

Proof:

- Backend replay and refresh tests prove queued/running/completed/no-candidates/timed-out/failed paths.

### Slice 3: RCL-004 Projection Schema and API

**Goal**: Make roster entries a source-backed person review projection.

Changes:

- Expand `roster-entry.schema.json` with source and derived fields.
- Add projection repository/mapper with freshness/source-version data.
- Keep person writes separate from projection reads.

Proof:

- Schema/codegen checks pass; PHPUnit verifies roster API response fields.

### Slice 4: Bounded Suggestion Refresh

**Goal**: Remove hidden unbounded refresh scans from product paths.

Changes:

- Require candidate partitioning for post-curation refresh where possible.
- Reserve full scans for explicit backfill jobs.
- Add no-candidate, timeout, failure, retry, and idempotency tests.

Proof:

- Backend tests cover bounded and backfill paths with status outcomes.

### Slice 5: Projection Integrity and Bounded Controller Extraction

**Goal**: Keep projection and controller complexity stable after the contract lands, without letting Tier 2 work block Tier 0 close.

Changes:

- Begin this slice only after Slices 1-4 have a recorded `close_slice` decision proving Tier 0 is closed.
- Add projection rebuild correctness tests.
- Keep reset behavior unchanged unless a planning-reviewed projection/read contract requires expansion.
- Extract only roster write/projection/outbox helper seams required by this task.

Proof:

- The Slices 1-4 `close_slice` decision exists before Slice 5 starts, and PHPUnit/API tests pass through public routes with no broad unrelated controller decomposition in the diff.

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `backend-refresh` | `apps/prototype-description-service/**` | Slice 1 ADR gate | `pyenv exec pytest apps/prototype-description-service/recognition/tests apps/prototype-description-service/roster` |
| `wp-projection` | `apps/prototype-wp-alt-context/src/**`, `packages/shared-contracts/**` | Slice 1 ADR gate; backend event shape | `cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit` |
| `docs-contracts` | `docs/adrs/**`, `docs/specs/**`, `docs/tasks/**` | None | `make plan-review DOC=docs/specs/e15-app-refactoring-preimplementation-spec.md` |

### Merge Order

1. `docs-contracts`
2. `backend-refresh`
3. `wp-projection`

### Manifest

```bash
make lane-manifest-init TASK=E15-19 LANE_IDS='docs-contracts backend-refresh wp-projection' TASK_PLAN=docs/tasks/15.0/E15-19-preimpl-roster-refresh-projection-foundation-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools with the declared lane ownership and verification boundaries.
- **Shell fallback**: Use repo lane helpers or manual worktrees while preserving the same ownership and evidence requirements.

## Consolidated Checklist

## Context and Ownership

- [x] Loaded PREIMPL spec, RCL spec, ADR-009, E15-13 related plan, and handoff state before editing.
- [x] Recorded the disposition of E15-13 (superseded by E15-19 with a handoff decision id) before Slice 1 implementation starts.
- [x] Confirmed ADR-009 state before event/projection code changes.
- [x] Recorded boundary ownership and compatibility expectations for every payload/schema change.

### Checklist for Slice 1: ADR and Contract Gate

- [x] ADR-009 status and decision id recorded.
- [x] RCL-004 canonical projection confirmed.
- [x] Conditional ADR constraints copied into task handoff if applicable.

### Checklist for Slice 2: Durable Post-Curation Event and Refresh Status

- [x] `cluster_person_bound` carries or resolves authoritative person label.
- [ ] Refresh status is durable and idempotent.
- [x] Replay/idempotency tests captured.

### Checklist for Slice 3: RCL-004 Projection Schema and API

- [ ] Shared schema exposes source and derived projection fields.
- [ ] Projection freshness/source version is present.
- [ ] API/schema/codegen tests pass.

### Checklist for Slice 4: Bounded Suggestion Refresh

- [ ] Candidate partitioning is required where possible.
- [ ] Full scan is explicit backfill only.
- [ ] No-candidate, timeout, failure, retry, and idempotency tests pass.

### Checklist for Slice 5: Projection Integrity and Bounded Controller Extraction

- [ ] Slices 1-4 are closed with a `close_slice` decision before Tier 2 Slice 5 starts.
- [ ] Projection rebuild correctness tests pass.
- [ ] Reset behavior is not expanded without reviewed contract.
- [ ] Controller extraction is limited to changed roster/projection/outbox use cases.

## Review Readiness

- [ ] No boundary-touching implementation lacks matching contract/doc/fixture evidence.
- [ ] Runtime-parity checks are included where unit tests can mask projection behavior.
- [ ] Handoff decision records the ADR state, refresh/projection changes, and verification.

## Stretch Goals

- [ ] Add a compact debug endpoint for projection freshness only if it reuses named source rows and does not expand dashboard ownership.

## Success Criteria

- [ ] Local curation triggers durable bounded refresh with visible status.
- [ ] RCL-004 roster projection is source-backed, fresh/stale aware, and test-covered.
- [ ] Suggestion refresh no longer depends on hidden unbounded scans for product paths.
