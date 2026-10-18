# Dynamic Suggestion Refresh During Curation

**Date:** 2026-01-26  
**Status:** In Progress  
**Goal:** Update similarity % dynamically and eliminate stale candidates as user provides ground truth

---

## Problem Statement

During user curation sessions, suggestions should:

1. Update similarity percentages as cluster centroids change
2. Eliminate candidates already confirmed to a cluster
3. Propagate curriculum adjustments to existing suggestions
4. Reflect cluster membership changes immediately

---

## Clarifications (2026-01-26)

1. /suggestions/{id}/accept behavior

- Already correct. The endpoint assigns the identity to the target cluster, marks the suggestion accepted, and then refreshes.
- No change to assignment behavior is needed.

2. Merge suggestion invalidation strategy

- Use hard delete (Option B).
- Rationale: Greenfield policy favors clean rewrites; no need for INVALIDATED status or audit in DB.
- FK constraints already cascade; explicit deletion keeps UI consistent immediately.

3. Enum changes

- Skip any enum changes (no INVALIDATED status).

4. Invalidation points

- Confirmed: curation_job.py, cluster_merge.py, discovery_pipeline.py, accept_merge_suggestion.
- Verify no manual cluster delete endpoint exists; if it does, add deletion there too.

5. Tests

- Both unit and integration tests.

6. Performance

- Synchronous deletes are acceptable; volume is low and users expect immediate consistency.

---

## Current State Analysis

### ✅ What IS Working

| Trigger                                    | Backend Action                                     | Frontend Refresh                          |
| ------------------------------------------ | -------------------------------------------------- | ----------------------------------------- |
| Reassign identity                          | `refresh_for_identity()` + `refresh_for_cluster()` | ✅ Query invalidation                     |
| Remove from cluster                        | `refresh_for_identity()` + `refresh_for_cluster()` | ✅ Query invalidation                     |
| Split cluster                              | `refresh_for_cluster()` for all splits             | ✅ Query invalidation                     |
| Assign outlier via `/clusters/{id}/assign` | `refresh_for_cluster()`                            | ✅ Query invalidation                     |
| Label new cluster                          | `surface_for_newly_labeled_cluster()`              | ✅ Query invalidation                     |
| Merge clusters                             | `refresh_for_cluster()` via curation job           | ✅ Query invalidation                     |
| SSE Events                                 | Server pushes updates                              | ✅ `useClusterEvents` invalidates queries |

**Key mechanisms:**

- `refresh_for_cluster(cluster_id)` — recalculates similarity for ALL pending suggestions targeting that cluster
- `refresh_for_identity(identity_id)` — finds new cluster matches for an identity
- `resolve_for_identity_exclusive()` — accepts one suggestion, rejects all others for that identity

### ❌ Gaps Identified

| Gap                                                              | Impact                                             | Status       |
| ---------------------------------------------------------------- | -------------------------------------------------- | ------------ |
| Accept suggestion via `/suggestions/{id}/accept` missing refresh | Similarity % stale after accept                    | **FIXED**    |
| Merge suggestions not invalidated on cluster changes             | Stale cluster-to-cluster suggestions               | TODO         |
| Curriculum adjustments don't cascade                             | Thresholds change but suggestions not re-evaluated | Low priority |

---

## Changes Made

### 1. Added `refresh_for_cluster()` to Suggestion Accept Endpoint

**File:** `recognition/interface_adapters/http/routers/suggestions.py`

**Before:**

```python
resolve_exclusive = getattr(suggestion_service, "resolve_for_identity_exclusive", None)
if callable(resolve_exclusive):
    await resolve_exclusive(
        identity_id=suggestion.identity_id,
        accepted_cluster_id=suggestion.cluster_id,
        reason="manual_accept",
    )
return _to_response(suggestion)
```

**After:**

```python
resolve_exclusive = getattr(suggestion_service, "resolve_for_identity_exclusive", None)
if callable(resolve_exclusive):
    await resolve_exclusive(
        identity_id=suggestion.identity_id,
        accepted_cluster_id=suggestion.cluster_id,
        reason="manual_accept",
    )

# Refresh suggestions for the target cluster (centroid changed)
suggestion_refresh_service = await get_suggestion_refresh_service(session=session, tenant_id=request.tenant_id)
await suggestion_refresh_service.refresh_for_cluster(suggestion.cluster_id)

return _to_response(suggestion)
```

**Why:** When user accepts a suggestion:

1. Identity joins the cluster → centroid shifts
2. Other identities similar to the new member now have HIGHER similarity to the cluster
3. Without refresh, their displayed similarity % would be stale

---

## Apple's Approach (Reference)

From Apple's "Recognizing People in Photos Through Private On-Device Machine Learning":

1. **Two-pass clustering** — First pass is conservative (high precision), second pass uses HAC to increase recall
2. **Filtering unclear faces** — Detections that are false positives or out-of-distribution are filtered before clustering
3. **Curriculum learning** — CurricularFace loss underweights easy examples, focuses on hard negatives
4. **Multi-modal cues** — Face + upper body embeddings for same-session matching

### Current System Safeguards

| Defense                    | Against FP                       | Against FN                   | Implementation             |
| -------------------------- | -------------------------------- | ---------------------------- | -------------------------- |
| `curriculum_t` adjustment  | ✅ `-0.05` on remove             | ✅ `+0.01` on merge          | Per-cluster bias           |
| Complete-link verification | ✅ All members must meet floor   |                              | `complete_link_min_floor`  |
| Quality-based threshold    | ✅ Poor quality → stricter       | ✅ High quality → lenient    | `QualitySettings`          |
| Maturity-based adjustment  |                                  | ✅ Mature clusters → lenient | `MaturitySettings`         |
| Suggestion band routing    | ✅ Low-confidence → human review |                              | `suggestion_floor/ceiling` |
| Fatal floors               | ✅ Reject bad detections         |                              | `fatal_confidence_floor`   |

---

## Remaining Work

### High Priority

1. **Test suggestion accept refresh** — Verify similarity % updates after accepting suggestion
2. **Merge suggestion invalidation** — When cluster is merged/deleted, remove stale merge suggestions

### Medium Priority

3. **Cross-cluster refresh optimization** — Consider batch refresh for efficiency
4. **Add merge suggestion `invalidate_by_cluster()` method**

### Low Priority

5. **Curriculum cascade** — Re-evaluate suggestions when `curriculum_t` changes
6. **Per-pair curriculum** — Store adjustments at pairwise level, not just per-cluster

---

## Evaluation: Merge Suggestion Invalidation

### Problem

When a cluster is merged or deleted, existing `ClusterMergeSuggestion` records referencing that cluster become stale:

- The UI may show suggestions for clusters that no longer exist
- Foreign key constraints may cause query errors if cluster is hard-deleted
- Similarity scores become meaningless after cluster centroid changes

### Current State

**Repository methods available:**

- `upsert_pending()` — Create/update suggestion
- `list_pending_with_details()` — List pending with cluster details
- `update_status()` — Mark as accepted/rejected
- `get_by_id()` — Fetch by ID

**Missing:**

- `invalidate_by_cluster(cluster_id)` — Mark/delete suggestions involving a cluster

### Where Invalidation Is Needed

| Trigger                  | Location                                                               | Why                          |
| ------------------------ | ---------------------------------------------------------------------- | ---------------------------- |
| Merge clusters           | `curation_job.py:119` → `cluster_repo.delete(source_cluster_id)`       | Source cluster deleted       |
| Merge clusters           | `cluster_merge.py:302` → `cluster_repo.delete(source_cluster_id)`      | Source cluster deleted       |
| Discovery pipeline merge | `discovery_pipeline.py:257` → `cluster_repo.delete(source_cluster_id)` | Auto-merge during clustering |
| Accept merge suggestion  | `suggestions.py:accept_merge_suggestion`                               | Both clusters affected       |

### Implementation Options

**Option A: Soft Invalidation (Recommended)**

```python
async def invalidate_by_cluster(self, tenant_id: str, cluster_id: str) -> int:
    """Mark all pending suggestions involving cluster_id as INVALIDATED."""
    tenant_uuid = _coerce_uuid(tenant_id)
    cluster_uuid = _coerce_uuid(cluster_id)
    stmt = (
        update(MergeSuggestionModel)
        .where(MergeSuggestionModel.tenant_id == tenant_uuid)
        .where(MergeSuggestionModel.resolution == SuggestionStatus.PENDING.value)
        .where(
            or_(
                MergeSuggestionModel.cluster_a_id == cluster_uuid,
                MergeSuggestionModel.cluster_b_id == cluster_uuid,
            )
        )
        .values(resolution=SuggestionStatus.INVALIDATED.value, resolved_at=datetime.now(tz=UTC))
    )
    result = await self._session.execute(stmt)
    return result.rowcount
```

**Pros:**

- Preserves audit trail
- No FK constraint issues
- Fast bulk update

**Cons:**

- Requires new `INVALIDATED` status value
- Old records accumulate

**Option B: Hard Delete**

```python
async def delete_by_cluster(self, tenant_id: str, cluster_id: str) -> int:
    """Delete all pending suggestions involving cluster_id."""
    # Similar but uses DELETE instead of UPDATE
```

**Pros:**

- Clean database
- Simple

**Cons:**

- Loses audit trail
- May cause issues if suggestion is referenced elsewhere

### Recommendation

**Implement Option B (Hard Delete)** per greenfield policy:

> _"Clean Rewrites: Prefer clean rewrites of logic and schema over backward-compatibility shims."_

Hard delete is simpler:

- No new enum value needed
- No accumulating stale records
- FK constraints already use `ON DELETE CASCADE`
- Audit trail exists in logs, not needed in DB

### Complexity Estimate

| Component                       | Effort          |
| ------------------------------- | --------------- |
| Implement `delete_by_cluster()` | 15 min          |
| Wire into curation job          | 10 min          |
| Wire into cluster merge         | 10 min          |
| Wire into accept merge endpoint | 10 min          |
| Tests                           | 30 min          |
| **Total**                       | **~1.25 hours** |

### Impact If Not Implemented

- **Low severity** — Merge suggestions are regenerated during next clustering run
- **UX annoyance** — Stale suggestions may briefly appear after merge
- **No data corruption** — FK constraints use `ON DELETE CASCADE` (verified)

---

## Design Decisions

### 1. `/suggestions/{id}/accept` Behavior

**Confirmed: Already correct.** The endpoint:

1. ✅ Assigns identity to cluster via `assign_outlier_to_cluster()`
2. ✅ Marks suggestion as accepted
3. ✅ Refreshes cluster suggestions (added in this task)

No change needed to assignment behavior.

### 2. Hard Delete vs INVALIDATED Status

**Decision: Hard Delete (Option B)**

| Factor                | Hard Delete        | INVALIDATED Status    |
| --------------------- | ------------------ | --------------------- |
| Simplicity            | ✅ No enum change  | ❌ New enum value     |
| DB cleanliness        | ✅ No accumulation | ❌ Records pile up    |
| Audit trail           | Logs sufficient    | In DB                 |
| FK safety             | ✅ CASCADE handles | ✅ No FK issues       |
| Cross-domain coupling | ✅ None            | ❌ Shared enum change |

### 3. Enum Change

**Decision: Skip entirely.** Hard delete means no `INVALIDATED` status needed. Method name: `delete_by_cluster()` not `invalidate_by_cluster()`.

### 4. Invalidation Points (Confirmed)

| Location                         | Trigger                              | Confirmed |
| -------------------------------- | ------------------------------------ | --------- |
| `curation_job.py:119`            | Merge cleanup deletes source cluster | ✅        |
| `cluster_merge.py:302`           | Direct merge deletes source cluster  | ✅        |
| `discovery_pipeline.py:257`      | Auto-merge during clustering         | ✅        |
| `/suggestions/merge/{id}/accept` | After merge, source cluster deleted  | ✅        |

**Not needed:**

- Manual cluster delete — No `DELETE /clusters/{id}` endpoint exists
- Split cleanup — Splits don't delete clusters, just move members

### 5. Tests

**Decision: Unit + Integration**

| Test Type             | Scope                                             | Effort |
| --------------------- | ------------------------------------------------- | ------ |
| Unit (fake repo)      | `delete_by_cluster()` removes correct suggestions | 15 min |
| Unit (fake repo)      | `delete_by_cluster()` ignores non-PENDING         | 10 min |
| Integration (real DB) | Merge → delete → suggestions gone                 | 20 min |

### 6. Performance

**Decision: Synchronous**

Rationale:

- Merge suggestions typically <100 per tenant
- Single `DELETE WHERE cluster_id = X` is O(1) in PostgreSQL
- User expects immediate consistency after curation
- Background tasks add retry/failure complexity

**Exception:** Revisit if batch merge (50+ clusters) is added later.

---

## Patterns to Follow

### Backend: Repository Method Pattern

```python
# 1. Add method to Protocol (domain/repositories.py)
class MergeSuggestionRepository(Protocol):
    async def delete_by_cluster(self, tenant_id: str, cluster_id: str) -> int:
        """Delete all pending merge suggestions involving cluster_id."""
        ...

# 2. Implement in SqlAlchemy adapter (infrastructure/repositories/)
async def delete_by_cluster(self, tenant_id: str, cluster_id: str) -> int:
    """Delete all pending merge suggestions involving cluster_id."""
    tenant_uuid = _coerce_uuid(tenant_id)
    cluster_uuid = _coerce_uuid(cluster_id)
    if not tenant_uuid or not cluster_uuid:
        return 0
    stmt = (
        delete(MergeSuggestionModel)
        .where(MergeSuggestionModel.tenant_id == tenant_uuid)
        .where(MergeSuggestionModel.resolution == SuggestionStatus.PENDING.value)
        .where(
            or_(
                MergeSuggestionModel.cluster_a_id == cluster_uuid,
                MergeSuggestionModel.cluster_b_id == cluster_uuid,
            )
        )
    )
    result = await self._session.execute(stmt)
    await self._session.flush()
    return result.rowcount

# 3. Add to Fake for tests (tests/conftest.py or tests/fakes.py)
class FakeMergeSuggestionRepository:
    async def delete_by_cluster(self, tenant_id: str, cluster_id: str) -> int:
        to_delete = [
            sid for sid, s in self._suggestions.items()
            if (s.cluster_a_id == cluster_id or s.cluster_b_id == cluster_id)
            and s.status == SuggestionStatus.PENDING
        ]
        for sid in to_delete:
            del self._suggestions[sid]
        return len(to_delete)
```

### Backend: Calling Deletion Before Cluster Delete

```python
# In curation_job.py, cluster_merge.py, discovery_pipeline.py:
# BEFORE: await cluster_repo.delete(source_cluster_id)
# AFTER:
if merge_suggestion_repo is not None:
    await merge_suggestion_repo.delete_by_cluster(tenant_id, source_cluster_id)
await cluster_repo.delete(source_cluster_id)
```

### Frontend: Query Invalidation Pattern

```typescript
// After mutation success, invalidate related queries:
onSuccess: () => {
  queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.pending() });
  queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.mergePending() });
  queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
},
```

---

## Functions to Change

### Phase 1: Implement Repository Method (~15 min)

| File                                                                     | Change                                                            |
| ------------------------------------------------------------------------ | ----------------------------------------------------------------- |
| `recognition/domain/repositories.py`                                     | Add `delete_by_cluster()` to `MergeSuggestionRepository` Protocol |
| `recognition/infrastructure/repositories/merge_suggestion_repository.py` | Implement `delete_by_cluster()`                                   |
| `recognition/tests/conftest.py`                                          | Add `delete_by_cluster()` to `FakeMergeSuggestionRepository`      |

### Phase 2: Wire Into Cluster Deletion Points (~30 min)

| File                                                                     | Line                      | Change                                                   |
| ------------------------------------------------------------------------ | ------------------------- | -------------------------------------------------------- |
| `recognition/application/orchestration/curation_job.py`                  | ~119                      | Add `delete_by_cluster()` before `cluster_repo.delete()` |
| `recognition/application/orchestration/cluster_merge.py`                 | ~302                      | Add `delete_by_cluster()` before `cluster_repo.delete()` |
| `recognition/application/orchestration/clustering/discovery_pipeline.py` | ~257                      | Add `delete_by_cluster()` before `cluster_repo.delete()` |
| `recognition/interface_adapters/http/routers/suggestions.py`             | `accept_merge_suggestion` | Add deletion for source cluster after merge              |

### Phase 3: Dependency Injection (~10 min)

| File                                                    | Change                                           |
| ------------------------------------------------------- | ------------------------------------------------ |
| `recognition/interface_adapters/http/deps/services.py`  | Ensure `MergeSuggestionRepository` is injectable |
| `recognition/application/orchestration/curation_job.py` | Add `merge_suggestion_repo` parameter            |

---

## Related Files

| Category           | File Path                                                                                         | Purpose                      |
| ------------------ | ------------------------------------------------------------------------------------------------- | ---------------------------- |
| **Domain**         | `recognition/domain/suggestion.py`                                                                | `SuggestionStatus` enum      |
| **Domain**         | `recognition/domain/repositories.py`                                                              | Repository protocols         |
| **Infrastructure** | `recognition/infrastructure/repositories/merge_suggestion_repository.py`                          | SQLAlchemy implementation    |
| **Orchestration**  | `recognition/application/orchestration/curation_job.py`                                           | Post-curation cleanup        |
| **Orchestration**  | `recognition/application/orchestration/cluster_merge.py`                                          | Cluster merge logic          |
| **Orchestration**  | `recognition/application/orchestration/clustering/discovery_pipeline.py`                          | Auto-merge during clustering |
| **HTTP**           | `recognition/interface_adapters/http/routers/suggestions.py`                                      | Suggestion endpoints         |
| **HTTP**           | `recognition/interface_adapters/http/routers/clusters.py`                                         | Cluster curation endpoints   |
| **Refresh**        | `recognition/application/suggestions/refresh_service.py`                                          | Identity suggestion refresh  |
| **Frontend**       | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useClusterMutations.ts` | Query invalidation           |

---

## Consolidated Task Checklist

### Completed

- [x] **Analyze current state** — Documented what refresh mechanisms exist
- [x] **Identify gaps** — Found missing refresh in `/suggestions/{id}/accept`
- [x] **Fix suggestion accept refresh** — Added `refresh_for_cluster()` after accepting
- [x] **Evaluate merge suggestion invalidation** — Documented approach and complexity
- [x] **Design decisions** — Confirmed hard delete, synchronous, unit+integration tests

### Phase 1: Implement Repository Method (~15 min) ✅ DONE

- [x] Add `delete_by_cluster()` signature to `MergeSuggestionRepository` Protocol — `repositories.py:496`
- [x] Implement `delete_by_cluster()` in `SqlAlchemyMergeSuggestionRepository` — `merge_suggestion_repository.py:147`
- [x] Add `delete_by_cluster()` to `FakeMergeSuggestionRepository` in tests — `test_merge_suggestions.py:57`

### Phase 2: Wire Into Deletion Points (~30 min) ✅ DONE

- [x] Add deletion to `curation_job.py` before `cluster_repo.delete()` — lines 123-130
- [x] Add deletion to `cluster_merge.py` before `cluster_repo.delete()` — lines 303-307
- [x] Add deletion to `discovery_pipeline.py` before `cluster_repo.delete()` — lines 260-264
- [x] Add deletion to `accept_merge_suggestion` endpoint for source cluster — `suggestions.py:205-206`

### Phase 3: Dependency Injection (~10 min) ✅ DONE

- [x] Ensure `MergeSuggestionRepository` injectable in `deps/services.py`
- [x] Add `merge_suggestion_service` wiring via `getattr()` pattern

### Phase 4: Tests (~30 min) ✅ DONE

- [x] Unit test: `delete_by_cluster()` removes correct suggestions — `test_merge_suggestions.py:223`
- [x] Unit test: `delete_by_cluster()` ignores non-PENDING suggestions — `test_merge_suggestion_repository.py:97`
- [x] Integration test: Merge cluster deletes related merge suggestions — `test_merge_suggestion_repository.py:16`

### Phase 5: Manual Verification — 🔴 BLOCKED

Cannot verify because suggestions don't appear in UI due to label filter (see `proactive-label-suggestions.md`).

- [ ] Accept suggestion via Suggestions panel → other suggestions update similarity
- [ ] Reassign identity → source and target cluster suggestions refresh
- [ ] Label singleton cluster → unlabeled identities get new suggestions
- [ ] Merge clusters → merge suggestions for source cluster deleted
- [ ] Remove identity from cluster → that identity gets new suggestions

### Stretch Goals (Low Priority)

- [ ] Curriculum cascade — Re-evaluate suggestions when `curriculum_t` changes
- [ ] Per-pair curriculum — Store adjustments at pairwise level
- [ ] Batch refresh optimization for cross-cluster updates
