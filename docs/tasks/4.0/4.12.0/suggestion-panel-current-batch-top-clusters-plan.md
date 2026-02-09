# 4.12.0 Implementation Plan: Suggestion Panel Current-Batch Top Clusters

## Problem Statement

The Workbench suggestion panel (`acx-suggestion-panel`) does not provide a clear, unified curation flow. Users need two
high-value queues at the top of the page:

1. Suggestions that match identities to user-confirmed clusters.
2. Clusters to name from the latest batch.
   Today the naming queue never populates, and suggestions are not constrained to confirmed clusters, so the workflow feels
   inconsistent and hard to trust.

## Workflow Principles

- Suggestion candidates: identities matched against user-confirmed clusters only.
- Naming queue: top non-singleton unlabeled clusters from the latest run.
- Merge queue: separate, lower-priority, collapsible section below naming; collapsed by default but always visible with
  a suggestion count.
- Tenant-wide confirmed gallery for suggestions.
- Run-scoped unlabeled clusters for naming.

## Terminology

- Confirmed cluster: `user_confirmed = true` and `label` is a human label (not `cluster-*`).
- Unlabeled cluster: `user_confirmed = false` and `label` is null or auto-generated.
- RLS note: All DB access must remain tenant-scoped. The WP REST proxy injects `tenant_id` server-side; the frontend
  still passes `tenant_id` to keep query keys stable and avoid tenantless requests.

## Current State Analysis

- `SuggestionReviewPanel` only renders `TopClustersSection` when `getConfig().tenant_id` exists. `AltContextAdmin` does
  not currently include `tenant_id`, so the naming queue is skipped.
- The frontend calls `/recognition/clusters/top-unlabeled`, but `get_top_unlabeled()` filters for
  `label is not null` and `label startswith "cluster-"`. New clusters are created with `label = None`, so the query
  returns zero rows.
- The endpoint returns all unlabeled clusters for the tenant, not those created in the most recent clustering run.
  "Current batch" data already exists in `recognition_runs` and `recognition_events` (event_type `cluster_created`),
  but the endpoint does not use it.
- The UI filters out singletons (`identity_count > 1`) in `TopClustersSection`. If the API only returns singletons,
  the panel renders nothing even when data exists.
- Suggestion eligibility currently allows any cluster, including unlabeled clusters, which conflicts with the
  confirmed-only requirement.
- Merge suggestions are interleaved with assignment suggestions, which hides priority and adds cognitive load.

## Proposed Solution

- Enforce confirmed-only eligibility for suggestions in the backend.
- Filter pending suggestions at query time in `GET /suggestions` (via `SuggestionService.list_pending` ->
  `SuggestionRepository.list_pending_with_details`) so legacy rows targeting unconfirmed clusters stay hidden.
- Add run-scoped selection for top unlabeled clusters; fall back to tenant-wide when no run data exists.
- Include representative thumbnails in the top-unlabeled response.
- Always render both suggestions and naming queues in the suggestion panel.
- Move merge suggestions into a separate, lower-priority collapsible queue below naming; keep it visible with a count
  badge, default collapsed, and persist user expand/collapse preference.
- Keep the API deterministic: prefer `run_id` (or latest run) for naming, tenant-wide for suggestions.
- Fallback is intentional: when the latest run has zero `cluster_created` events (or no runs exist), fall back to
  tenant-wide unlabeled clusters. This keeps the naming queue populated so users feel the system is working across
  batches, not just the latest run.
- Retire `CurateTopClustersPrompt` so the naming queue in the suggestion panel is the single source of truth.
- Filter legacy pending suggestions that target unconfirmed clusters at query time (do not delete).
- Provide `tenant_id` in `AltContextAdmin` to keep tenant-scoped query keys and avoid tenantless frontend requests.
  The WP REST proxy still injects `tenant_id` server-side for recognition endpoints, so RLS remains enforced.

## Open Questions Resolved

### Representative thumbnails in `top-unlabeled`

- Decision: add `thumbnail_url` to the domain `ClusterRepresentative` dataclass and populate it from
  `MediaIdentity.thumbnail_url` in cluster repository mapping.
- Why: `GET /clusters/top-unlabeled` currently maps from domain representatives returned by
  `ClusterRepository.get_top_unlabeled`. `RepresentativeResponse` already supports `thumb_url`, so keeping
  `thumbnail_url` on the domain object is the cleanest typed path from repository -> router -> API response.
- API mapping: keep domain field name `thumbnail_url`, map it to response field `thumb_url`.

### `tenant_id` source for `AltContextAdmin`

- Decision: derive `tenant_id` from site URL hash, matching current recognition proxy behavior:
  `md5( (string) get_site_url() )`.
- Current source of truth: `apps/prototype-wp-alt-context/src/api/class-recognition-controller.php` in
  `RecognitionController::get_tenant_id()`.
- Not used today: no `acx_tenant_id` plugin option, no user-ID-derived tenant, and no initialization fetch from the
  recognition service.
- Implementation note: include the same derived value in `AltContextAdmin` payload from `class-admin.php` so frontend
  query keys and requests stay tenant-scoped.

### Merge queue priority UX

- Decision: render merge suggestions as a collapsible section directly below the naming queue.
- Visibility: always show the section header with count (for example, `Merge suggestions (4)`), even when collapsed.
- Default state: collapsed by default to de-emphasize merge actions versus assignment + naming.
- State behavior: remember expanded/collapsed state per user session (or local storage) so repeated reviewers keep their
  preferred view.
- Rejected alternatives:
  - Hidden behind a non-visible expander: lower discoverability.
  - Separate tab/view: unnecessary context switching for a secondary workflow.

## Existing Suggestions Policy

- Pending suggestions that target unconfirmed clusters remain in the database.
- Suggestion list endpoints must filter them out at query time.
- When a cluster becomes confirmed, pending suggestions targeting it become eligible again and should surface.
- Cleanup is not required for MVP; suggestions stay alive until resolved by the user.

## Patterns to Follow

### Eligibility: confirmed clusters only

```python
def is_eligible_cluster(cluster: object, tenant_id: str) -> bool:
    if tenant_id and getattr(cluster, "tenant_id", "").lower() != tenant_id.lower():
        return False
    label = getattr(cluster, "label", None)
    if not getattr(cluster, "user_confirmed", False):
        return False
    if not label:
        return False
    if str(label).startswith("cluster-"):
        return False
    return True
```

### Write endpoints: commit before response

```python
result = await service.update_cluster(...)
await session.commit()
return result
```

### Pending suggestions: filter at query time

```python
stmt = (
    select(SuggestionModel)
    .join(SuggestionModel.suggested_cluster)
    .where(SuggestionModel.tenant_id == _coerce_uuid(tenant_id))
    .where(SuggestionModel.resolution == SuggestionStatus.PENDING.value)
    .where(IdentityCluster.user_confirmed.is_(True))
    .where(IdentityCluster.label.is_not(None))
    .where(~IdentityCluster.label.startswith("cluster-"))
    .order_by(SuggestionModel.created_at.desc())
    .offset(offset)
    .limit(limit)
)
```

### Run-scoped top unlabeled query with fallback

```python
run_id_stmt = (
    select(RecognitionRun.id)
    .where(RecognitionRun.tenant_id == tenant_uuid)
    .where(RecognitionRun.source == "cluster_unclustered_identities")
    .order_by(RecognitionRun.created_at.desc())
    .limit(1)
)
run_id = (await session.execute(run_id_stmt)).scalar_one_or_none()

cluster_ids = []
if run_id:
    event_stmt = (
        select(RecognitionEvent.cluster_id)
        .where(RecognitionEvent.run_id == run_id)
        .where(RecognitionEvent.event_type == "cluster_created")
        .where(RecognitionEvent.cluster_id.is_not(None))
        .distinct()
    )
    cluster_ids = [str(row[0]) for row in (await session.execute(event_stmt)).all()]

stmt = (
    select(ClusterModel)
    .where(ClusterModel.tenant_id == tenant_uuid)
    .where(ClusterModel.user_confirmed.is_(False))
    .where(or_(ClusterModel.label.is_(None), ClusterModel.label.startswith("cluster-")))
    .where(ClusterModel.identity_count >= 2)
    .order_by(ClusterModel.identity_count.desc())
    .limit(limit)
)
if cluster_ids:
    stmt = stmt.where(ClusterModel.id.in_(cluster_ids))
```

Note: `IdentityCluster` (used in `suggestion_repository.py`) and `ClusterModel` (used in `cluster_repository.py`) refer
to the same underlying SQLAlchemy model. The alias differs by file for readability.

### Representative mapping with thumbnails

```python
RepresentativeResponse(
    id=str(rep.id),
    media_id=rep.media_id or 0,
    thumb_url=rep.thumbnail_url,
    is_pinned=rep.is_user_selected,
)
```

### UI composition: two primary queues plus collapsible merge queue

```tsx
<div className="acx-suggestion-panel">
  <SuggestionQueue items={assignmentSuggestions} />
  <NamingQueue clusters={topUnlabeledClusters} />
  <CollapsibleMergeQueue
    title={`Merge suggestions (${mergeSuggestions.length})`}
    defaultExpanded={false}
    persistedStateKey="acx.mergeQueueExpanded"
    items={mergeSuggestions}
  />
</div>
```

## Functions to Change

| File                                                                                                   | Line | Change                                                                                                                                                     |
| ------------------------------------------------------------------------------------------------------ | ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-description-service/recognition/application/suggestions/eligibility.py`                | 10   | Enforce confirmed-only eligibility for suggestion targets.                                                                                                 |
| `apps/prototype-description-service/recognition/tests/unit/test_eligibility.py`                        | 1    | Update tests for confirmed-only eligibility.                                                                                                               |
| `apps/prototype-description-service/recognition/domain/repositories.py`                                | 185  | Add run-scoped top-unlabeled query or extend `get_top_unlabeled` to accept scope and min count.                                                            |
| `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py`     | 91   | Fix unlabeled filtering, add run-scoped selection, and populate representative thumbnail URLs.                                                             |
| `apps/prototype-description-service/recognition/domain/representative.py`                              | 15   | Add `thumbnail_url` field for API mapping.                                                                                                                 |
| `apps/prototype-description-service/recognition/infrastructure/repositories/suggestion_repository.py`  | 243  | Filter `list_pending_with_details` to confirmed clusters only.                                                                                             |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py`           | 162  | Accept `run_id` or `scope` query param, apply run scope, and map `thumb_url` in representatives.                                                           |
| `apps/prototype-description-service/recognition/tests/api/test_top_unlabeled.py`                       | 1    | Update expectations for run scoping and non-singleton filtering.                                                                                           |
| `apps/prototype-description-service/recognition/tests/integration/test_cluster_repository.py`          | 1    | Add run-scoped repository integration coverage.                                                                                                            |
| `apps/prototype-wp-alt-context/src/api/class-recognition-controller.php`                               | 641  | Forward optional `run_id` or `scope` query param for `/top-unlabeled`.                                                                                     |
| `apps/prototype-wp-alt-context/src/admin/class-admin.php`                                              | 179  | Include `tenant_id` in `AltContextAdmin` config (keep tenant-scoped requests).                                                                             |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/SuggestionReviewPanel.tsx`   | 283  | Always render suggestions and naming queues; render merge queue as a collapsed-by-default collapsible section with count badge and persisted toggle state. |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/TopClustersSection.tsx`      | 117  | Pass run scope query param and handle missing tenant IDs in query keys.                                                                                    |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/CurateTopClustersPrompt.tsx` | 1    | Delete. The naming queue in the suggestion panel replaces this UX.                                                                                         |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/IdentityClusterList.tsx`     | 47   | Remove `CurateTopClustersPrompt` usage/import.                                                                                                             |
| `apps/prototype-wp-alt-context/js/admin/api/queryKeys.ts`                                              | 24   | Keep `topUnlabeled(tenantId)` signature; use `tenant_id` from config.                                                                                      |
| `docs/agentic/contracts/recognition-clustering.md`                                                     | 115  | Document new query params (`run_id` or `scope`) and non-singleton behavior.                                                                                |

## Related Files

| File                                                                                                                | Note                                                                                                                                                                                      |
| ------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-description-service/db/models/observability.py`                                                     | Source of `RecognitionRun` (has `created_at`) and `RecognitionEvent` (has `timestamp`, not `created_at`; has `cluster_id`, `run_id`, `event_type`). `source` is on `RecognitionRun` only. |
| `apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py`               | Creates recognition runs for clustering batches.                                                                                                                                          |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/suggestions.py`                     | Current suggestion listing and merge suggestion endpoints.                                                                                                                                |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/identityApi.ts`                                             | Maps pending suggestion responses for the panel.                                                                                                                                          |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/SuggestionReviewPanel.test.tsx` | Add coverage for both queues and merge separation.                                                                                                                                        |

---

# Consolidated Checklist

## Completed

- [x] Align workflow principles with confirmed-only suggestions and run-scoped naming queue.

## Phase 0: Scaffolding

- [x] Verify `RecognitionRun.source` value written by clustering orchestrator matches `"cluster_unclustered_identities"` (used in run-scoped query pattern).
- [x] Add repository interface for run-scoped top-unlabeled clusters and min identity count.
- [x] Add domain representative field for `thumbnail_url`.
- [x] Add test stubs for eligibility and run-scoped top-unlabeled behavior.
- [x] Update API contract with new query params and scope semantics.

## Phase 1: Backend (TDD — tests before implementation)

- [x] Write failing eligibility test: confirmed-only clusters pass, unconfirmed/unlabeled rejected.
- [x] Enforce suggestion eligibility against user-confirmed clusters only (make test green).
- [x] Write failing test for pending suggestions: unconfirmed targets filtered from `list_pending_with_details`.
- [x] Write failing API test: `/clusters/top-unlabeled` returns run-scoped, non-singleton clusters.
- [x] Write failing integration test: run-scoped query uses `RecognitionRun` + `RecognitionEvent` data.
- [x] Resolve latest recognition run for the tenant and collect `cluster_created` IDs (make tests green).
- [x] Query clusters by IDs, filter unlabeled and `identity_count >= 2`, and order by size.
- [x] Include representative thumbnail URLs in the response mapping.
- [x] Fall back to tenant-wide query when no run data exists.
- [x] Ensure any new write endpoints in this slice commit before returning.

## Phase 2: Frontend (TDD — tests before implementation)

- [x] Write failing test: naming queue renders alongside suggestions, merge queue separate.
- [x] Provide `tenant_id` in `AltContextAdmin` (keep tenant-scoped query keys and requests).
- [x] Update `TopClustersSection` to include run scope (or rely on backend default).
- [x] Always show suggestions and naming queues together at the top of the Workbench (make test green).
- [x] Render merge suggestions in a lower-priority collapsible queue below naming (collapsed by default).
- [x] Show merge queue count in header and persist expand/collapse state.
- [x] Delete `CurateTopClustersPrompt.tsx` and remove usage from `IdentityClusterList.tsx`.

## Stretch Goals

- [x] Add optional `min_identity_count` query param (default 2).
- [x] Add observability log line for batch scope selection.

## Success Criteria

- [x] Suggestion candidates only target user-confirmed clusters.
- [x] Naming queue shows top non-singleton unlabeled clusters from the latest batch.
- [x] Merge queue is separate, lower priority, collapsed by default, and still discoverable via visible header + count.
- [x] `/recognition/clusters/top-unlabeled` returns clusters scoped to the latest run when available.
- [x] Workbench always shows both suggestions and naming queues at the top.
