# Recognition Roster Curation Loop Specification

> **Metadata**
>
> - **Date**: 2026-05-05
> - **Author**: Codex
> - **Status**: Draft
> - **Assessment**: [docs/assessments/current/recognition-roster-suggestion-workflow-assessment-2026-05-05.md](../assessments/current/recognition-roster-suggestion-workflow-assessment-2026-05-05.md)
> - **Owning epic**: [E15 Phase 6 - Local Sync Correctness and Audit Closure](../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Package version target**: n/a

This spec defines the curation loop that makes local roster labels train the suggestion workflow, produce reviewable person entries, and surface curriculum-style review queues. It closes the assessment gap where WordPress roster curation, backend curation replay, suggestion refresh, and roster review projections were separate workflows with different contracts.

**Constraints:** Greenfield policy applies. WordPress remains the operator-visible source of truth under ADR-003. Person remains the first-class local curation entity under ADR-002. Backend suggestion refresh, curriculum queues, and roster review entries are derived/projection work. Implementation is blocked until this spec, [ADR-009](../adrs/ADR-009-recognition-curation-refresh-and-person-review-projection.md), and [E15-13](../tasks/15.0/E15-13-roster-curation-loop-task-plan.md) pass planning review with findings resolved.

**Literature anchors:** This spec uses DDIA's system-of-record and derived-data framing for the WordPress person authority and roster projections (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15680`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15696`), Release It! stability patterns for bounded async refresh work (`literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4322`, `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4433`), Latency's queue/concurrency/tail-latency model for refresh SLOs (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:699`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:798`), Fowler's small-step and split-phase refactoring guidance for event/use-case boundaries (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:1648`, `literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:1660`), Modern Software Engineering's feedback/learning frame for curriculum review loops (`literature/extracted/refactoring/modern-software-engineering.txt:799`, `literature/extracted/refactoring/modern-software-engineering.txt:805`), Apple's private people-recognition paper for periodic clustering plus explicit user input (`literature/extracted/recognition/apple/Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt:95`, `literature/extracted/recognition/apple/Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt:212`), and CurricularFace for hard-example curriculum semantics (`literature/extracted/recognition/apple/CurricularFace--Adaptive-Curriculum-Learning-Loss-for-Deep-Face-Recognition.txt:30`, `literature/extracted/recognition/apple/CurricularFace--Adaptive-Curriculum-Learning-Loss-for-Deep-Face-Recognition.txt:136`).

---

## Spec Items

### RCL-001: Normalize all curation paths into one post-curation event contract

**Trace:** F1, F2, F3, F4, R-MISS-3  
**Priority:** P0  
**ADR gate:** Yes - ADR-009 resolves the event/replay semantics across ADR-002 and ADR-003.

Backend direct label edits, WordPress local roster commits, backend curation sync replay, merge cleanup, and batch clustering completion must converge on one domain event shape that can drive suggestion refresh and projection updates. The authoritative label source is ADR-gated; the default decision in ADR-009 is that WordPress local person state is authoritative and backend refresh consumes that curation signal as derived work.

DDIA's distinction between an authoritative record and derived datasets is the planning reason to make this a post-curation event instead of scattered request-path callbacks (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15680`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15700`). Fowler's split-phase guidance also supports using the event as the intermediate product between curation capture and suggestion computation (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:1648`).

**Before** (`apps/prototype-wp-alt-context/src/api/class-api.php::commit_roster_cluster`):

```php
// current shape emits cluster_uuid + person_uuid only
$payload = array(
    'cluster_uuid' => $cluster_uuid,
    'person_uuid'  => $person_uuid,
);
```

**Before** (`apps/prototype-description-service/roster/application/curation_sync_service.py::_resolve_desired_label`):

```python
if operation_type == "cluster_label_updated":
    return payload.get("label")
return current_label
```

**After:**

```python
PostCurationEvent(
    source="wp_outbox|backend_patch|curation_sync|merge_cleanup|batch_job",
    cluster_id=...,
    person_uuid=...,
    authoritative_label=...,
    curation_revision=...,
    affected_cluster_ids=[...],
    refresh_scope="newly_labeled|label_corrected|merge_target|batch_created",
    idempotency_key=...,
)
```

**Done when:**

- Every curation path produces or maps to the same post-curation event contract.
- `cluster_person_bound` provides or resolves the authoritative person label.
- Label correction on an already user-confirmed cluster has an explicit refresh rule.
- Event handling is idempotent under outbox retry.

---

### RCL-002: Durable suggestion refresh creates missing candidates and refreshes existing ones

**Trace:** F2, F3, F4, F8, F10, R-MISS-2, R-MISS-5  
**Priority:** P0  
**ADR gate:** Yes if the durable refresh lifecycle changes ADR-003 replay boundaries or introduces a new queue/outbox contract.

Suggestion refresh must be durable and observable at the per-event level. The current split between `surface_for_newly_labeled_cluster` and `refresh_for_cluster` leaves gaps: one path can create candidates, while the merge follow-up path only updates existing pending suggestions. RCL-002 owns the per-event status record only; RCL-007 owns aggregate metrics and SLOs.

Release It! supports keeping slow or unreliable integration work behind timeouts, circuit breakers, queues, and visible state instead of letting it hide inside the user request path (`literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4322`, `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4560`). DDIA's message-queue and stream-processing framing supports durable delivery of derived refresh work (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:6024`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:6051`).

**Before** (`apps/prototype-description-service/recognition/application/orchestration/curation_job.py::run_curation_job`):

```python
await suggestion_refresh.refresh_for_cluster(target_cluster_id)
```

**Before** (`apps/prototype-description-service/recognition/application/suggestions/refresh_service.py::refresh_for_cluster`):

```python
if not pending:
    return 0
```

**After:**

```python
result = await suggestion_refresh.refresh_after_curation(
    event,
    create_missing=True,
    refresh_existing=True,
)
await suggestion_refresh_status.record(result)
```

**Done when:**

- A post-curation refresh creates missing singleton/cluster suggestions when no pending suggestion exists.
- Existing pending suggestions for the same target are recomputed after curation.
- `SuggestionRefreshStatus` distinguishes queued, running, completed, no candidates, candidates created, candidates refreshed, timed out, and failed for one event.
- Long-running refreshes expose async status instead of blocking the user path.

---

### RCL-003: Reproduce the Tory Guzman singleton regression as an acceptance fixture

**Trace:** F2, F3, F4, F9, R-MISS-1  
**Priority:** P0  
**ADR gate:** No

The reported batch job must become a deterministic acceptance case before implementation proceeds. The repo contains historical Tory Guzman references, but the exact job `4f7236f5-55ed-4b55-8eae-51e5b7d256f4` and singleton `cluster-e22d355c86504443896d9bd73c54b80e` require DB/API reproduction or a faithful synthetic fixture.

**Fixture strategy:**

- Prefer a captured snapshot fixture if DB/API state for the exact job is available.
- If live job state is unavailable, create a synthetic fixture under `apps/prototype-description-service/recognition/tests/fixtures/recognition/` that preserves the observed labels, job ID, singleton ID string, target label, curation sequence, and similarity ordering.
- Keep the reported `cluster-e22d355c86504443896d9bd73c54b80e` string as fixture metadata even if internal repositories store cluster IDs without the `cluster-` prefix.

**After:**

```python
assert_refresh_candidate(
    job_id="4f7236f5-55ed-4b55-8eae-51e5b7d256f4",
    singleton_cluster_id="cluster-e22d355c86504443896d9bd73c54b80e",
    expected_target_label="Tory Guzman",
)
```

**Done when:**

- A fixture or scripted reproduction loads the job, singleton, target cluster, and similarity evidence.
- The failing current behavior is captured before code changes.
- The fixed behavior proves the singleton is suggested into the Tory Guzman person/cluster after curation.
- The fixture verifies similarity context after user curation, not only initial clustering.

---

### RCL-004: Expand roster entries into a person-instance review model

**Trace:** F1, F6, F7  
**Priority:** P0  
**ADR gate:** Yes - ADR-009 resolves the projection shape while preserving ADR-002's Person authority.

Roster entries must become reviewable person surfaces, not a minimal person table. A label/bind action should create or update a roster entry where all clusters, images, identities, face bboxes, thumbnails, and review actions for that person can be inspected.

This is a materialized read-model problem, not a new person write model. DDIA's materialized-view notes require the plan to name update/freshness behavior when underlying curation facts change (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4727`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4733`).

**Before** (`apps/prototype-wp-alt-context/src/api/class-api.php::get_roster_entries`):

```php
// returns persons with cluster_count only
SELECT p.id, p.name, p.tags, COUNT(c.id) AS cluster_count
```

**Before** (`packages/shared-contracts/schemas/roster-entry.schema.json`):

```json
{
  "id": "integer",
  "name": "string",
  "tags": "array",
  "cluster_count": "integer",
  "updated_at": "string"
}
```

**After:**

```json
{
  "id": "integer",
  "person_uuid": "string",
  "name": "string",
  "tags": "array",
  "clusters": [
    {
      "cluster_id": "string",
      "identity_count": "integer",
      "representative_identity": "object",
      "instances": [
        {
          "identity_id": "string",
          "media_id": "integer",
          "bbox": "array",
          "media_url": "string",
          "similarity": "number|null"
        }
      ]
    }
  ]
}
```

**Done when:**

- The shared roster-entry schema exposes person clusters and face instances.
- The WordPress API returns enough data to review all images and instances for a curated person.
- The entries tab is non-empty after a successful cluster label/bind operation.
- Existing person CRUD semantics from ADR-002 remain intact.

---

### RCL-005: Make cluster listing person-aware and topology-aware

**Trace:** F5, F7, F8  
**Priority:** P1  
**ADR gate:** No unless owner review changes the ADR-002 person model.

The cluster tab should not show raw duplicate cluster rows as the primary mental model after curation. It should group or collapse by person where possible, mark unresolved clusters clearly, and identify merged/superseded topology where available.

**Navigation contract:** The cluster drawer links to the RCL-004 person review surface by `person_uuid`. If a cluster has no `person_uuid`, the drawer stays in unresolved/curriculum review mode and must not invent a person review link.

**Done when:**

- Clusters bound to the same person are grouped or clearly shown as one person context.
- The UI distinguishes unresolved machine clusters from curated person clusters.
- Merged or superseded clusters do not appear as independent duplicate identities without explanation.
- The cluster drawer can navigate to the RCL-004 roster entry/person review surface using `person_uuid`.

---

### RCL-006: Make thumbnail and existing-field similarity copy inspectable

**Trace:** F7, F8  
**Priority:** P1  
**ADR gate:** No

Tier 1 UI work is limited to thumbnail policy and clearer copy using fields already available in current cluster/suggestion responses. It must not introduce new score fields such as `type`, `threshold`, `floor`, or `recomputedAt`; those belong to RCL-009 after the post-curation refresh contract lands.

Refactoring UI's hierarchy and label/value guidance is the UI rationale: similarity should be evidence text with source/target context, not a naked percentage competing equally with identity and action (`literature/extracted/refactoring/Refactoring-UI.txt:465`, `literature/extracted/refactoring/Refactoring-UI.txt:617`, `literature/extracted/refactoring/Refactoring-UI.txt:639`).

**Before** (`apps/prototype-wp-alt-context/js/admin/pages/roster/IdentityThumbnail.tsx::IdentityThumbnail`):

```tsx
if (identity.thumb_url) {
  return <img src={identity.thumb_url} ... />;
}
```

**Before** (`apps/prototype-wp-alt-context/js/admin/styles/components/_cluster-grid.scss`):

```scss
aspect-ratio: 1 / 1;
object-fit: cover;
border-radius: 50%;
```

**Done when:**

- Face thumbnails use bbox-aware inspectable crops in review contexts.
- Review contexts avoid forced circular/square distortion where visual inspection matters.
- Similarity copy names the visible comparison using existing fields only.
- No backend or shared schema contract is changed in this item.

---

### RCL-007: Bound description-service orchestration refactors around aggregate metrics

**Trace:** F10, R-MISS-4, R-MISS-5  
**Priority:** P2  
**ADR gate:** No for internal refactors; yes if queue/replay boundaries change.

The description service already has adapter timeouts, circuit breakers, session timeouts, and pool isolation. This item owns only the enabling refactor and aggregate metrics/SLO surface for refresh work. It must preserve existing resilience controls and defer broad description-service simplification.

Fowler's refactoring guidance supports this as a bounded, behavior-preserving extraction, not a broad rewrite (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:332`, `literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:1660`). Latency's queue model requires aggregate metrics to include queue depth, throughput/concurrency, and p95/p99 behavior rather than a single average (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:699`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:728`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:798`).

**Done when:**

- Curation replay, suggestion refresh, clustering topology mutation, and projection are separable use cases.
- Aggregate metrics cover queue depth, p95/p99 latency, timeout count, retry count, failure rate, recovery time, label-to-visible-suggestion lead time, and projection freshness.
- Refactor slices preserve current adapter resilience controls.
- Per-event status remains owned by RCL-002.

---

### RCL-008: Surface curriculum-driven review queues

**Trace:** F9  
**Priority:** P1  
**ADR gate:** No, unless queue membership requires a new backend contract beyond RCL-002/RCL-004.

The UI must expose the Apple-inspired curriculum states named in the assessment rather than leaving curriculum work as invisible clustering internals.

Apple's people-recognition paper describes unsupervised clusters, periodic processing, and explicit user input as part of gallery formation; this spec translates those system states into review queues visible to the operator (`literature/extracted/recognition/apple/Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt:95`, `literature/extracted/recognition/apple/Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt:212`, `literature/extracted/recognition/apple/Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt:216`). CurricularFace motivates the "hard examples" queue by treating hard samples as explicit curriculum material rather than noise (`literature/extracted/recognition/apple/CurricularFace--Adaptive-Curriculum-Learning-Loss-for-Deep-Face-Recognition.txt:30`, `literature/extracted/recognition/apple/CurricularFace--Adaptive-Curriculum-Learning-Loss-for-Deep-Face-Recognition.txt:89`).

**Queues:**

- **Singleton proposals**: singleton clusters that are candidates for a confirmed person after curation.
- **Hard examples**: low-margin or conflicting candidates that require deliberate human confirmation.
- **Needs confirmation after merge**: candidates affected by workbench merge cleanup or post-merge recomputation.

**Done when:**

- The roster/clusters UI shows these three queues with counts.
- Queue rows link to candidate face evidence and the target person/cluster context.
- Accept/dismiss/defer actions are available or explicitly routed to an existing review action.
- Empty states explain that no candidates currently need that curriculum review.

---

### RCL-009: Add enhanced score evidence after refresh contracts land

**Trace:** F8, F9  
**Priority:** P1  
**ADR gate:** No if it only consumes RCL-002/RCL-004 data; yes if it changes shared response schemas.

Enhanced score evidence is separated from Tier 1 UI cleanup. It may use `score.type`, threshold/floor, and recomputation timestamps only after the backend/shared contract supplies those fields.

**Done when:**

- Similarity labels state candidate source, target comparator, and score type.
- Scores expose threshold/floor context and recomputation state when available.
- Existing UI remains useful when enhanced score fields are absent.

---

## Entity / Payload Schemas

### PostCurationEvent

```json
{
  "event_id": "string",
  "source": "backend_patch | wp_outbox | curation_sync | merge_cleanup | batch_job",
  "tenant_id": "string",
  "cluster_id": "string",
  "person_uuid": "string | null",
  "authoritative_label": "string | null",
  "curation_revision": "integer | null",
  "affected_cluster_ids": "string[]",
  "refresh_scope": "newly_labeled | label_corrected | merge_target | batch_created",
  "idempotency_key": "string | null",
  "created_at": "datetime"
}
```

### SuggestionRefreshStatus

```json
{
  "refresh_id": "string",
  "event_id": "string",
  "status": "queued | running | completed | no_candidates | timed_out | failed",
  "created_count": "integer",
  "refreshed_count": "integer",
  "error": "string | null",
  "updated_at": "datetime"
}
```

---

## Implementation Tiers

### Tier 1 - Low-contract work, still implementation-gated

Task plan: [docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md](../tasks/15.0/E15-13-roster-curation-loop-task-plan.md)

```text
RCL-003  Tory Guzman singleton reproduction and acceptance fixture
RCL-006  Existing-field thumbnail/similarity-copy cleanup
```

Tier 1 is the lowest-contract portion of E15-13 because it must not modify outbox,
person, backend suggestion, or shared score contracts. It may be estimated before
ADR-009 is accepted, but implementation remains blocked until this spec, ADR-009,
and the E15-13 task plan complete planning review with findings resolved.

### Tier 2 - Ready after ADR direction

Task plan: [docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md](../tasks/15.0/E15-13-roster-curation-loop-task-plan.md)

```text
RCL-002  Durable suggestion refresh implementation and per-event status
RCL-005  Person-aware cluster list projection and navigation
RCL-007  Enabling orchestration refactor and aggregate metrics
RCL-008  Curriculum review queues
RCL-009  Enhanced score evidence
```

Tier 2 depends on the reproduction fixture and ADR-backed event/read-model decisions from Tier 3.

### Tier 3 - Blocked on ADR

Task plan: [docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md](../tasks/15.0/E15-13-roster-curation-loop-task-plan.md)  
ADR: [docs/adrs/ADR-009-recognition-curation-refresh-and-person-review-projection.md](../adrs/ADR-009-recognition-curation-refresh-and-person-review-projection.md)

```text
RCL-001  Post-curation event contract and outbox/replay semantics
RCL-004  Person-instance roster entry review model
```

ADR-009 must be reviewed before Tier 2 implementation begins. Implementation tasks may be planned, but no code should start until ADR-009 and this spec are reviewed and updated with the chosen direction.

---

## Deferred or Rejected Directions

- Do not solve duplicate cluster display with frontend filtering alone.
- Do not plan resilience as "increase timeouts" or "add more workers."
- Do not treat singleton HAC as a replacement for user-visible suggestion review.
- Do not expand roster entries only with more counts.
- Do not include a broad `prototype-description-service` rewrite in E15-13. Only enabling refactors required by this curation loop are in scope.

---

## Spec-Review Gate

No implementation may start until:

1. This spec has been reviewed with findings recorded in MCP.
2. All spec review findings are resolved.
3. ADR-009 has been reviewed and either accepted or updated with a reviewed replacement decision.
4. E15-13 task plan has been reviewed with findings resolved.
5. Validation snippets have been verified against the current package.

---

## Validation

### Current-state verification

```bash
# RCL-001: current WP payload lacks authoritative label
rg -n "cluster_person_bound|person_uuid|new_entry_name|label" apps/prototype-wp-alt-context/src/api/class-api.php

# RCL-002: merge cleanup only refreshes existing pending suggestions
rg -n "refresh_for_cluster|surface_for_newly_labeled_cluster|backfill_for_new_unlabeled_clusters" apps/prototype-description-service/recognition/application

# RCL-004: current roster entry contract is count-only
rg -n "cluster_count|RosterEntry|roster-entry" packages/shared-contracts apps/prototype-wp-alt-context/js/admin apps/prototype-wp-alt-context/src/api/class-api.php
```

### Tier 1 validation

```bash
pyenv exec pytest apps/prototype-description-service/recognition/tests -k "tory or post_curation or suggestion"
cd apps/prototype-wp-alt-context && npm test -- --run js/admin/pages/roster
```

### Tier 2 validation

```bash
pyenv exec pytest apps/prototype-description-service/recognition/tests
cd apps/prototype-wp-alt-context && npm test -- --run js/admin
```
