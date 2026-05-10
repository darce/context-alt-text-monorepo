# E15-13. Recognition Roster Curation Loop

> **Metadata**
>
> - **Date**: 2026-05-05 19:30 EST
> - **Revised**: 2026-05-08 (re-anchor + finding closure for E15-13-PR-01..PR-10)
> - **Author**: Codex
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-13
> - **Target Branch**: `feature/e15-13-roster-curation-loop`
> - **HEAD anchor for current-state analysis**: `7340db43` (local `main` at review time; includes the post-E15-21 curation-sync contract wording and curation-job failure-loop fix)
> - **Review Coverage Target**: 2

---

## Objective

Make roster curation visibly train the recognition workflow. When this task is complete, labeling or binding a person cluster creates a reviewable person entry, triggers durable post-curation suggestion refresh, and surfaces curriculum review queues for singleton proposals, hard examples, and post-merge confirmations.

## Problem Statement

The assessment and spec show that WordPress roster curation, backend curation replay, suggestion refresh, cluster display, and roster entries are currently split across different contracts. A user can curate a cluster locally while backend suggestion surfacing never runs, roster entries remain count-only, duplicate clusters remain visible, and curriculum-style clustering work is not exposed as review queues.

## Constraints

- Implementation is blocked until [ADR-009](../../adrs/ADR-009-recognition-curation-refresh-and-person-review-projection.md), [the spec](../../specs/recognition-roster-curation-loop-spec.md), and this task plan pass planning review with findings resolved.
- WordPress remains the operator-visible source of truth under ADR-003.
- Person remains the first-class local entity under ADR-002.
- Backend suggestion refresh and curriculum queues are derived/projection work, not person write models.
- Broad `apps/prototype-description-service` refactoring is out of scope; only enabling refactors required by the curation loop are allowed.
- Tier 1 work must not change outbox, person, backend suggestion, or shared score contracts.
- Extracted-literature references are planning inputs, not optional reading: DDIA governs record/projection boundaries, Release It! and Latency govern bounded refresh work, Fowler/Modern Software Engineering govern refactor scope, Refactoring UI governs roster evidence hierarchy, and the Apple/CurricularFace texts govern curriculum queue semantics.

## Workflow Principles

- Curation is local first: local person state is authoritative and backend refresh follows.
- Suggestions are proposals: backend refresh results must be visible, reviewable, and dismissible, not silently merged.
- Projection data is rebuildable: roster review entries and curriculum queues derive from person, cluster, identity, media, and refresh state.
- Observability has two layers: per-event refresh status and aggregate queue/SLO metrics stay separate.
- Refactor only to reveal and support the curation workflow; defer unrelated simplification.
- Use the literature as guardrails: keep authoritative curation facts separate from derived projections (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15680`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15696`), make slow refresh work durable and observable (`literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4322`, `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4560`), size queue/concurrency/tail latency explicitly (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:699`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:798`), and limit refactors to small behavior-preserving steps with tests (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:332`, `literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:1660`).

## Terminology

- **Post-curation event**: Durable event emitted after a label, person bind, merge cleanup, or batch clustering completion that can drive suggestion refresh.
- **CurationRefreshStatus**: Per-event replay refresh lifecycle state: `not_applicable`, `queued`, `running`, `completed`, `no_candidates`, `timed_out`, or `failed`.
- **Curriculum review queue**: User-visible queue for singleton proposals, hard examples, or needs-confirmation-after-merge candidates.
- **Person review projection**: Derived roster entry surface showing a person with clusters, identity instances, images, bboxes, and review actions.

## Current State Analysis

Anchored to local `main` HEAD `7340db43` (2026-05-08 review-time baseline). Predecessor task plans `E15-19-preimpl-roster-refresh-projection-foundation-task-plan.md` and `E15-21-preimpl-roster-routes-and-evidence-task-plan.md` (both merged) plus the post-merge fix series shipped most of the projection envelope and durable replay scaffolding. This baseline also includes the newer curation-sync contract wording and curation-job failure-loop fix that were not present at `5a3d6ac1`. E15-13 closes the *residual gaps* listed below.

### Already shipped (do NOT re-do)

- **`cluster_person_bound` implementation now carries authoritative person label, but the canonical contract doc still needs co-change in E15-13.** `apps/prototype-wp-alt-context/src/api/class-api.php` resolves `$resolved_person_name` and emits `person_name` in the bind payload (api.php:345, 363-364, 401-402, 472-473). Commit `c8339027 feat(roster): carry person_name in cluster bind replay`. Backend `_resolve_desired_label` reads `payload["person_name"]` for `cluster_person_bound` (`roster/application/curation_sync_service.py:373-377`). `docs/agentic/contracts/curation-sync-api.md` is still the source-of-truth contract surface that Slice 2 must update so the documented payload matches the shipped emitter/reader behavior.
- **Per-event durable refresh lifecycle.** `apps/prototype-description-service/recognition/application/orchestration/curation_job.py:135-222` records `CurationRefreshStatus` transitions (`RUNNING → TIMED_OUT | FAILED | COMPLETED | NO_CANDIDATES`) against the replay session, with fallback to `refresh_for_identity`. Commits `c9cfb532 feat(roster): persist refresh followup lifecycle`, `3e650bc2 feat(refresh): persist no-candidate replay status`, `c9093c33 feat(refresh): persist timeout replay status`, `4420dbd6 feat(refresh): restamp retry replay attempt timestamps`, `65ae2c74 fix(refresh): sync migration replay statuses`.
- **Roster-entry projection envelope.** `packages/shared-contracts/schemas/roster-entry.schema.json` already requires `person_uuid`, `source_version`, `projection_status` (`current | refreshing | stale | failed`), and `projection_refreshed_at`. The generated TS type is at `apps/prototype-wp-alt-context/js/admin/api/generated/roster-entry.ts`. `RosterEntryProjectionRepository` and its PHPUnit test exist (`apps/prototype-wp-alt-context/src/sovereign/repositories/class-roster-entry-projection-repository.php`, `apps/prototype-wp-alt-context/tests/Unit/RosterEntryProjectionRepositoryTest.php`).
- **`cluster_person_unbound` outbox path.** `apps/prototype-wp-alt-context/src/api/class-api.php:466` emits `cluster_person_unbound` when `person_id` is null. Backend `roster/application/curation_sync_service.py:65, 355` registers and resolves the unbind path.

### Residual gaps E15-13 closes

- **Backend `curation_sync_service.py` does not yet branch `cluster_person_bound` into the same newly-labeled-cluster suggestion-surfacing workflow** that backend direct label edits use; replay only updates the cluster label, then `curation_job.run_curation_job` calls `refresh_for_cluster` per cluster. The plan's RCL-001 / RCL-002 work formalises a single `PostCurationEvent` mapping for both bind and unbind (see RCL-001 done-when extensions in Slice 2), updates `docs/agentic/contracts/curation-sync-api.md` so `cluster_person_bound` documents authoritative `person_name` semantics, and routes through a `refresh_after_curation`-style entrypoint that creates *missing* suggestions, not only refreshes existing ones (`refresh_service.py:377` `refresh_for_cluster` returns 0 when no pending suggestions exist).
- **No nested `clusters[].instances[]` review payload on roster entries.** The projection envelope is in place but `clusters`, `representative_identity`, and per-instance `bbox/media_url/similarity` arrays from RCL-004 are still absent from the schema and the WP API response.
- **Cluster cards still list raw cluster rows** and do not collapse by `person_uuid`, mark merged/superseded topology, or distinguish unresolved-machine-cluster from curated-person-cluster (RCL-005). The cluster drawer does not yet navigate to a person review surface by `person_uuid`.
- **Curriculum review queues are not surfaced as product UI** (RCL-008): no `singleton-proposals`, `hard-examples`, or `needs-confirmation-after-merge` queues with counts, evidence, and accept/dismiss/defer wiring.
- **Enhanced score evidence (RCL-009)** depends on RCL-002/RCL-004 fields landing first; no Slice currently consumes `score.type`, threshold/floor, or recomputation timestamps.
- **Refresh-status terminology drift.** Slice 2 standardizes the spec, ADR, contract, and task plan on the implemented `CurationRefreshStatus` name.
- **Aggregate refresh metrics/SLOs are not split out from per-event status (RCL-007).** Existing adapter timeouts, circuit breakers, session timeouts, and pool isolation must be preserved unchanged.

## Target Outcome

A successful cluster label or person bind immediately creates a local person review surface. Durable async refresh then creates or updates suggestions, records per-event status, and projects curriculum queues. Users can review all person instances, inspect candidate evidence, accept/dismiss/defer suggestions, and understand when refresh work is queued, absent, failed, or complete.

## Context Loading

- Rules: `docs/agentic/rules/development-workflow.md`
- Rules: `docs/agentic/rules/planning-review-guide.md`
- Rules: `docs/agentic/rules/backend-php-guidelines.md`
- Rules: `docs/agentic/rules/frontend-guidelines.md`
- Rules: `docs/agentic/rules/backend-python-guidelines.md`
- Spec: `docs/specs/recognition-roster-curation-loop-spec.md`
- ADR: `docs/adrs/ADR-009-recognition-curation-refresh-and-person-review-projection.md`
- Contract: `docs/agentic/contracts/curation-sync-api.md`
- Assessment: `docs/assessments/current/recognition-roster-suggestion-workflow-assessment-2026-05-05.md`
- Epic: `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md`
- Literature: `literature/extracted/recognition/apple/Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt`
- Literature: `literature/extracted/recognition/apple/CurricularFace--Adaptive-Curriculum-Learning-Loss-for-Deep-Face-Recognition.txt`
- Literature: `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt`
- Literature: `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt`
- Literature: `literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt`
- Literature: `literature/extracted/refactoring/Refactoring-UI.txt`
- Literature: `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt`
- Literature: `literature/extracted/refactoring/modern-software-engineering.txt`
- Handoff/MCP state: `MAINT-roster-spec-review-20260505`, `PR-RCL-*`
- External docs via `ctx7` only if: framework/library behavior blocks a concrete implementation decision that cannot be answered from repo code.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| WordPress outbox -> backend curation replay | plugin + backend | ADR-003 plus `docs/agentic/contracts/curation-sync-api.md` | `cluster_person_bound` documents and carries authoritative local `person_name`, both bind/unbind map to the same `PostCurationEvent`, and replay remains idempotent | No compatibility shim required in greenfield, but idempotency semantics must remain | PHP outbox tests + backend curation sync tests + contract/fixture proof that the doc matches emitter/reader payloads |
| Roster entry shared schema | plugin + frontend | `packages/shared-contracts/schemas/roster-entry.schema.json` count-only entry | Person review projection with clusters, identity instances, media, bboxes, and actions | Existing UI callers must migrate in the same slice | schema fixture/codegen + Vitest/PHPUnit |
| Suggestion refresh status | backend + plugin projection | transient logs/background task status | durable per-event refresh status projected locally | New contract; no old consumer dependency expected | backend unit tests + projection/API tests |
| Curriculum review queues | frontend + local projection | no named queues | singleton proposals, hard examples, needs-confirmation-after-merge | Additive UI/API surface | Vitest/PHPUnit queue tests |
| Aggregate refresh metrics | backend ops | existing adapter/session resilience controls | queue depth, p95/p99, failure rate, recovery time, lead-time metrics | Existing metrics remain intact | backend metrics tests or instrumentation assertions |

## Proposed Solution

Deliver the curation loop in five slices. Start with deterministic proof and no contract changes, then land the ADR-backed event/status contract, then expand person review projections and navigation, then surface curriculum queues, and finish with only the enabling refactor needed to keep refresh orchestration observable and bounded.

## Files and Surfaces to Change

State key: **(open)** = E15-13 still needs to land this. **(extend)** = predecessor work landed scaffolding; E15-13 closes residual behavior. **(preserve)** = touched only to keep working.

| Surface | File | Change | State |
| --- | --- | --- | --- |
| backend fixtures/tests | `apps/prototype-description-service/recognition/tests/fixtures/recognition/` | Add replayed-bind singleton regression coverage + curriculum queue fixtures (singleton, hard examples, post-merge confirmations) | **(open)** |
| curation sync contract doc | `docs/agentic/contracts/curation-sync-api.md` | Update `cluster_person_bound` payload semantics to include authoritative `person_name`, clarify bind/unbind `PostCurationEvent` mapping, and keep doc examples aligned with PHP emitter + backend replay reader | **(open)** |
| backend curation replay | `apps/prototype-description-service/roster/application/curation_sync_service.py` | Branch `cluster_person_bound` and `cluster_person_unbound` into the post-curation event mapping; current `_resolve_desired_label` already reads `person_name`, but neither bind nor unbind drives the newly-labeled-cluster surfacing path | **(extend)** |
| backend suggestion refresh | `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py` | Add a `refresh_after_curation` entrypoint that creates missing singleton/cluster suggestions and refreshes existing pending ones; today `refresh_for_cluster` returns when no pending suggestions exist (refresh_service.py:377) | **(extend)** |
| backend orchestration | `apps/prototype-description-service/recognition/application/orchestration/curation_job.py` | Route through the `PostCurationEvent` + `refresh_after_curation` boundary instead of per-cluster `refresh_for_cluster`; preserve existing replay-status persistence (curation_job.py:135-222 already does the status writes) | **(extend)** |
| plugin outbox/API | `apps/prototype-wp-alt-context/src/api/class-api.php` | Expand `get_roster_entries` to return person clusters + identity instances + bboxes for review (projection envelope already exists; nested arrays do not) | **(extend)** |
| plugin projection/repos | `apps/prototype-wp-alt-context/src/sovereign/` | Add curriculum-queue membership projection on top of the existing `RosterEntryProjectionRepository` | **(extend)** |
| shared contracts | `packages/shared-contracts/schemas/roster-entry.schema.json` | Extend with `clusters[]`, `clusters[].instances[]`, and `queue_memberships` in the same RCL-004 projection slice; regenerate TS via `cd apps/prototype-wp-alt-context && npm run generate:contracts` | **(extend)** |
| roster UI | `apps/prototype-wp-alt-context/js/admin/pages/roster/` | Add person review review surface, curriculum queue panels, cluster-drawer navigation by `person_uuid`, thumbnail evidence; `PersonWorkspacePanel.tsx` shell already exists from E15-21 | **(extend)** |
| naming reconciliation | `apps/prototype-description-service/roster/application/curation_sync_service.py` + spec/plan | Keep `CurationRefreshStatus` as the implementation/schema canon and align the spec, ADR-009, contract, and task plan on that name in Slice 2 | **(open)** |
| ADR-009 owners' conditions | `docs/adrs/ADR-009-recognition-curation-refresh-and-person-review-projection.md` and `docs/specs/recognition-roster-curation-loop-spec.md` | Confirm RCL-008 queue-membership predicates remain consistent with this plan's Slice 4 ownership; no new spec edit unless RCL-009 contract widens | **(preserve)** |

## Related Files

| File | Note |
| --- | --- |
| `docs/adrs/ADR-002-person-as-first-class-local-entity.md` | Person authority must not regress |
| `docs/adrs/ADR-003-wordpress-local-authority-and-durable-outbox-replay.md` | Outbox replay/idempotency constraints |
| `docs/adrs/ADR-008-external-adapter-stability-pattern.md` | Existing adapter resilience controls to preserve |
| `apps/prototype-description-service/recognition/application/orchestration/curation_job.py` | Merge cleanup currently calls `refresh_for_cluster` only |
| `apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterDrawerPanel.tsx` | Navigation to person review surface |

## Verification Strategy

- Deterministic tests:
  - `pyenv exec pytest apps/prototype-description-service/recognition/tests -k "replayed_cluster_bind or post_curation or suggestion or curriculum"`
  - `pyenv exec pytest apps/prototype-description-service/roster`
  - `cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit`
  - `cd apps/prototype-wp-alt-context && npm test -- --run js/admin/pages/roster`
- Contract/fixture verification:
  - curation-sync contract/doc parity: update `docs/agentic/contracts/curation-sync-api.md` in the same slice that wires bind/unbind `PostCurationEvent`, then prove the documented payload matches the PHP emitter and backend replay reader.
  - shared contract regen + consumer tests: `cd apps/prototype-wp-alt-context && npm run generate:contracts && vendor/bin/phpunit tests/Unit/RosterEntryProjectionRepositoryTest.php && npm test -- --run js/admin/pages/roster` (replaces the prior docs-only `plan-analyze` proof for contract drift)
  - fixture proof that a replayed cluster bind surfaces singleton suggestions after curation (failing in Slice 1, passing in Slice 2)
  - fixture proof for singleton proposals, hard examples, and needs-confirmation-after-merge queues
- Runtime-parity / environment checks:
  - local WordPress roster clusters tab shows person-aware grouping and curriculum queues after a seeded curation flow
  - entries tab shows person instances after a cluster label/bind
- Manual verification:
  - `http://localhost:10010/wp-admin/admin.php?page=alt-context-roster#/roster?tab=clusters`
  - `http://localhost:10010/wp-admin/admin.php?page=alt-context-roster#/roster?tab=entries`

## Slice Delivery

### Slice 1: Reproduction and Curriculum Fixtures

**Goal**: Capture the failing curation/suggestion behavior before changing contracts.

Literature guardrail: Apple describes gallery formation from clustered face observations plus explicit user input, and CurricularFace frames hard examples as curriculum material; fixtures must therefore cover singleton proposals, hard examples, and post-merge confirmations rather than only one happy-path named identity (`literature/extracted/recognition/apple/Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt:95`, `literature/extracted/recognition/apple/Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt:212`, `literature/extracted/recognition/apple/CurricularFace--Adaptive-Curriculum-Learning-Loss-for-Deep-Face-Recognition.txt:30`).

Changes:

- Add replayed-bind singleton regression coverage or scripted reproduction.
- Add fixture coverage for singleton proposals, hard examples, and post-merge confirmations.
- Limit UI cleanup to thumbnail policy and existing-field similarity copy from RCL-006.

Proof:

- `pyenv exec pytest apps/prototype-description-service/recognition/tests -k "replayed_cluster_bind or curriculum"`
- `cd apps/prototype-wp-alt-context && npm test -- --run js/admin/pages/roster`

### Slice 2: ADR-Backed Event and Refresh Status Contract

**Goal**: Make curation replay produce durable refresh work with per-event status.

Literature guardrail: DDIA's message-queue/event processing model and Release It!'s timeout/circuit-breaker guidance make durable post-curation refresh status a boundary requirement, not a later UI enhancement (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:6024`, `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4322`).

Changes:

- **Confirm ADR-009 conditional accept** (`codex_conditional_accept_adr009_e15_planning_gate_20260506`) before any RCL-001 contract edit; record the confirmation as a `record_event(event_kind="decision", ...)` entry on this task ref.
- Implement post-curation event mapping from backend label edits, WordPress outbox replay (`cluster_person_bound` **and `cluster_person_unbound`**), merge cleanup, and batch job completion. Both bind and unbind must route through the same `PostCurationEvent` envelope; unbind clears person association while keeping the replay row durable and visible as `not_applicable`.
- Update `docs/agentic/contracts/curation-sync-api.md` in the same slice that wires replay behavior so `cluster_person_bound` documents authoritative local `person_name` semantics and the bind/unbind payload examples match the PHP emitter and backend replay reader.
- Carry or resolve authoritative local person label for `cluster_person_bound` (already shipped in `class-api.php`; Slice 2 wires the backend branch into the surfacing path and co-changes the canonical contract doc).
- **Standardize the docs on `CurationRefreshStatus`**: keep the implementation/schema name as canon, update ADR-009 plus the spec/contract/task-plan terminology, and drop the retired name from this slice.
- Persist per-event `CurationRefreshStatus`, including the `not_applicable` branch for unbind events that have no candidate work.
- Ensure refresh creates missing suggestions (new `refresh_after_curation` entrypoint) and refreshes existing pending suggestions (today's `refresh_for_cluster` short-circuits at `refresh_service.py:377`).
- **Flip Slice 1's replayed-bind singleton regression proof from failing to passing** as the slice's green gate; record the passing `record_event(event_kind="test_result", passed=true, ...)` against the implementing commit.

Proof:

- backend curation sync and suggestion refresh tests pass.
- replay/idempotency tests prove repeated outbox delivery does not duplicate refresh work.

### Slice 3: Person Review Projection and Cluster Navigation

**Goal**: Turn roster entries into reviewable person surfaces.

Literature guardrail: DDIA's materialized-view framing requires the person review model to declare source facts and freshness, while Refactoring UI requires the face evidence and primary action to outrank raw IDs and count labels (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4727`, `literature/extracted/refactoring/Refactoring-UI.txt:465`, `literature/extracted/refactoring/Refactoring-UI.txt:617`).

Changes:

- Expand roster entry schema/API to include person UUID, clusters, identity instances, media, bboxes, representative evidence, `queue_memberships`, and review actions.
- Regenerate shared TypeScript types.
- Make cluster drawer navigation link to person review by `person_uuid`.
- Group/collapse cluster list by person where appropriate.

Proof:

- shared contract checks pass.
- PHPUnit covers roster entry response shape.
- Vitest covers entries tab and cluster drawer navigation.

### Slice 4: Curriculum Review Queue UI

**Goal**: Surface Apple curriculum-inspired review queues as product UI.

Literature guardrail: Modern Software Engineering's empirical feedback loop maps here to user curation -> refreshed candidates -> hard examples -> further review; the queue UI is the feedback surface, not decoration (`literature/extracted/refactoring/modern-software-engineering.txt:799`, `literature/extracted/refactoring/modern-software-engineering.txt:805`).

Changes:

- Add singleton proposals, hard examples, and needs-confirmation-after-merge queues by consuming the `queue_memberships` projection landed in Slice 3/RCL-004 (RCL-008 only — enhanced score evidence moves to Slice 5).
- Show queue counts, candidate evidence, target person/cluster context, and empty states.
- Wire accept/dismiss/defer to existing or new review actions.
- Add enhanced score evidence only after backend/shared fields exist.

Proof:

- Vitest covers all three queues with populated and empty states.
- backend/plugin tests prove queue membership is projection-backed, not frontend-only filtering.

### Slice 5: Narrow Enabling Refactor and Aggregate Metrics

**Goal**: Keep refresh orchestration bounded and observable without broad service rewrite.

Literature guardrail: Fowler supports small, tested extractions; Latency requires p95/p99 and queue growth evidence; Modern Software Engineering frames the follow-up metrics as stability and throughput measures (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:332`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:798`, `literature/extracted/refactoring/modern-software-engineering.txt:1938`).

Changes:

- Extract curation refresh use case boundaries only where required by the previous slices.
- Preserve existing adapter timeouts, circuit breakers, session timeouts, and pool bulkheads.
- Add aggregate metrics/SLOs for queue depth, p95/p99 latency, failure rate, recovery time, label-to-visible-suggestion lead time, and projection freshness.
- Document broad description-service refactoring as a follow-on, not part of E15-13.

Proof:

- backend metrics/instrumentation tests pass.
- no direct remote adapter calls are introduced inside long-lived DB transactions.

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `backend-refresh` | `apps/prototype-description-service/**` | Slice 1 fixture decisions, ADR-009 | `pyenv exec pytest apps/prototype-description-service/recognition/tests apps/prototype-description-service/roster` |
| `wp-projection-ui` | `apps/prototype-wp-alt-context/src/**`, `apps/prototype-wp-alt-context/tests/Unit/**`, `apps/prototype-wp-alt-context/js/admin/pages/roster/**`, `apps/prototype-wp-alt-context/js/admin/components/**` | `docs-contracts` schema/codegen handoff, ADR-009, Slice 2 contract shape | `cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit && npm test -- --run js/admin/pages/roster` |
| `docs-contracts` | `docs/**`, `packages/shared-contracts/**`, `apps/prototype-wp-alt-context/js/admin/api/generated/**` | ADR-009 owners' conditions, Slice 2 naming/contract decision | `cd apps/prototype-wp-alt-context && npm run generate:contracts && vendor/bin/phpunit tests/Unit/RosterEntryProjectionRepositoryTest.php && npm test -- --run js/admin/pages/roster && make plan-review DOC=docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md` (regenerate shared TS types from JSON Schema, prove PHP + TS consumers compile/test against the regenerated artifacts, and re-run planning review once the contract/doc surfaces converge) |

### Merge Order

1. `docs-contracts` ADR/spec/task-plan updates
2. `backend-refresh`
3. `wp-projection-ui`
4. final integration and review readiness

### Manifest

```bash
make lane-manifest-init TASK=E15-13 LANE_IDS='backend-refresh wp-projection-ui docs-contracts' TASK_PLAN=docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md
```

### Orchestration Mode

- **Codex subagent**: Use worker lanes only after ADR/spec/task plan review gates pass.
- **Shell fallback**: Use manual worktrees with the same owned paths and proof commands.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded E15 epic, recognition roster spec, ADR-009, ADR-002, ADR-003, and relevant testing guides before editing.
- [ ] Confirmed ADR-009 and this task plan have passed planning review before implementation.
- [ ] Confirmed whether any contract change touches backend replay, shared roster schema, or frontend generated types.
- [ ] Loaded and applied relevant extracted literature anchors before changing event, projection, queue, UI evidence, or refactor scope.

### Checklist for Slice 1: Reproduction and Curriculum Fixtures

- [x] Replayed-bind singleton regression coverage exists.
- [x] Curriculum fixture states cover singleton proposals, hard examples, and needs-confirmation-after-merge.
- [x] Existing-field UI cleanup does not change backend/shared contracts.
- [x] Verification evidence captured.

### Checklist for Slice 2: ADR-Backed Event and Refresh Status Contract

- [x] Post-curation event mapping exists for all curation paths.
- [x] `cluster_person_bound` carries or resolves authoritative local person label.
- [x] Per-event `CurationRefreshStatus` is persisted or otherwise durable.
- [x] Missing suggestions are created and existing suggestions are refreshed.
- [x] Replay/idempotency tests pass.

### Checklist for Slice 3: Person Review Projection and Cluster Navigation

- [x] Roster entry schema/API returns person clusters and identity instances.
- [x] Shared generated TypeScript types are updated.
- [x] Entries tab can review all images/instances for a curated person.
- [x] Cluster drawer navigates by `person_uuid`.
- [x] Person-aware cluster grouping is covered by tests.

### Checklist for Slice 4: Curriculum Review Queue UI

- [x] Singleton proposal queue renders populated and empty states.
- [x] Hard examples queue renders populated and empty states.
- [x] Needs-confirmation-after-merge queue renders populated and empty states.
- [x] Accept/dismiss/defer actions are covered or explicitly marked unavailable pending contract support.
- [x] Queue membership is projection-backed.

### Checklist for Slice 5: Narrow Enabling Refactor and Aggregate Metrics

- [ ] Refresh use case boundaries are extracted only as needed.
- [ ] Existing adapter/session/pool resilience controls remain intact.
- [ ] Aggregate refresh metrics/SLOs are recorded separately from per-event status.
- [ ] Broader description-service refactor is documented as follow-on.
- [ ] Enhanced similarity labels name candidate source, target comparator, and score type when RCL-002/RCL-004 data supplies those fields.
- [ ] Threshold/floor context and recomputation state render when enhanced score fields are present.
- [ ] Existing-field fallback remains useful and tested when enhanced score fields are absent.

## Review Readiness

- [ ] Spec review findings `PR-RCL-*` are fixed or explicitly deferred with rationale.
- [ ] ADR-009 has a planning review run and all findings resolved.
- [ ] This task plan has `plan-analyze` and `plan-review` runs with all findings resolved.
- [ ] No boundary-touching implementation is left without matching contract/schema/test evidence.
- [ ] Handoff decision records implementation proof and any contract implications after each slice.

## Stretch Goals

- [ ] Add a compact operator/debug panel showing refresh queue health if aggregate metrics are already available.

## Success Criteria

- [ ] Labeling or binding a cluster creates a reviewable roster entry with person instances.
- [ ] Post-curation refresh creates or updates suggestions after local curation, merge cleanup, and batch completion.
- [ ] Singleton proposals, hard examples, and needs-confirmation-after-merge queues are visible and actionable.
- [ ] Replayed-bind singleton regression coverage passes.
- [ ] Broad description-service refactor remains deferred outside E15-13.
