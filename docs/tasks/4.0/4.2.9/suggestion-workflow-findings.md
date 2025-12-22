# Suggestion Workflow Findings (v4.2.9)

**Date:** 2025-12-21  
**Branch Evaluated:** fix/4.2.8-cluster-split  
**Issue:** Suggestions not appearing or updating after user curation actions

---

## Problem Statement

After implementing the async-split functionality (v4.2.8), users report:

1. **No suggestions presented** after curation actions (splits, merges, removals)
2. **Similarity % not shown** in UI for suggested identities
3. **Unclear if suggestions are recomputing** behind the scenes

Users expect that **ground truth events** (labeling, merging, splitting, wrong-person removals) should  trigger immediate suggestion recomputation since these actions provide training signals about which faces belong together.

---

## Investigation Summary

### What IS Working

✅ **Backend suggestion refresh IS implemented** for most curation events:

| Event | Trigger Location | Refresh Call |
|-------|------------------|--------------|
| **Split** | `cluster_split.py:379` | `refresh_for_identity()` for all moved & remaining identities |
| **Reassign (assign)** | `clusters.py:342-347` | `refresh_for_identity()` after assignment |
| **Reassign (remove)** | `clusters.py:378-383` | `refresh_for_identity()` after removal |
| **Merge** | Background task via `run_background_retry()` | Retry matching after merge (indirect) |

✅ **Endpoints exist** and return data:
- `GET /identities/{id}/suggestions` → Returns `IdentitySuggestionsResponse` with similarity %
- Backend computes similarity correctly (lines 66-72 in `suggestions.py`)

✅ **Frontend fetches suggestions**:
- `useClusterSuggestions.ts` hook queries `/identities/{id}/suggestions`
- `InlineSuggestionPrompt.tsx` displays top suggestion with similarity %
- `ClusterEditForm.tsx` shows suggestions in dropdown

### What IS NOT Working

❌ **Merge doesn't trigger immediate suggestion refresh**
- Merges queue background job (`queue_curation_followup` line 263-266)
- Background worker runs `retry_matching` (line 59) but this re-evaluates orphans, not existing suggestions
- **Gap:** Merged cluster identities don't get new suggestions immediately

❌ **Query invalidation may not refetch immediately**
- `useClusterMutations.ts:89-90` invalidates `['identity-suggestions']` after mutations  
- But React Query may not refetch if component is unmounted or query is stale
- **Gap:** User may not see updated suggestions until manual refresh

❌ **Similarity % computed but not prominently displayed**
- Backend returns `similarity` in `ClusterSuggestionMatch` (line 69 `suggestions.py`)
- Frontend `InlineSuggestionPrompt` shows it (line 62 `InlineSuggestionPrompt.tsx`)
- **Gap:** Only shows for TOP suggestion in inline prompt, not in dropdown or cluster list

❌ **No visual feedback when suggestions update**
- After split/merge, UI doesn't show "Suggestions updated" toast or indicator
- User doesn't know if suggestions were recomputed
- **Gap:** No UX feedback loop

---

## Root Cause Analysis

### Issue 1: Merge Doesn't Refresh Suggestions Directly

**File:** `recognition/application/orchestration/cluster_merge.py`

**Expected:** After merging cluster A → B, all identities in cluster B should get fresh suggestions (their representatives/centroid changed)

**Actual:** Merge queues `retry_matching` background job which:
1. Fetches unclustered identities
2. Tries to match them to clusters
3. **Does NOT refresh suggestions for clustered identities**

**Why:** The `merge_cluster_op` function (imported in `cluster_service.py:42`) likely doesn't call `suggestion_service.refresh_for_identity()` for affected identities.

**Evidence:**
```python
# clusters.py:196-208 (merge endpoint)
cluster = await cluster_service.merge_cluster(...)
background_tasks.add_task(run_background_retry, request.tenant_id, request.target_cluster_id)
# ^ Only queues retry_matching, doesn't refresh suggestions
```

###Issue 2: Frontend Query Invalidation Timing

**File:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useClusterMutations.ts`

**Expected:** After mutation, suggestions immediately refetch

**Actual:**
```typescript
// Line 89-90
void queryClient.invalidateQueries({ queryKey: ['identity-suggestions'] });
void queryClient.invalidateQueries({ queryKey: ['pending-suggestions'] });
```

**Why:** `invalidateQueries` marks queries as stale but doesn't force refetch unless:
- A component is actively using that query
- `refetchOnMount` is enabled
- User navigates to a view that uses the query

**Gap:** If user stays on same view, stale data persists until manual interaction.

### Issue 3: Similarity % Display

**File:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterEditForm.tsx`

**Expected:** Dropdown shows "John Doe (87%)" for each suggestion

**Actual:**
```typescript
// Line 38-40 (SuggestionOption component)
<div className="acx-identity-cluster__suggestion-meta">
  <span className="acx-identity-cluster__suggestion-similarity">
    {Math.round(option.similarity * 100)}%
  </span>
  // ...
</div>
```

**Why:** Similarity IS displayed in dropdown options, but may not be visible due to:
- CSS styling hiding it
- Component not rendering when suggestions are empty
- Frontend filtering logic removing suggestions

**Gap:** Need to verify CSS and rendering logic.

### Issue 4: No Feedback After Curation

**Expected:** After split/merge/removal, user sees toast: "Suggestions updated for 5 identities"

**Actual:** Silent background refresh, no UI feedback

**Why:** Backend emits events (`recognition_events` table) but frontend doesn't poll or subscribe to them

**Gap:** No real-time updates, no toast notifications

---

## Recommendations for v4.2.9

### Priority 1: Add Suggestion Refresh to Merge

**File:** `recognition/application/orchestration/cluster_merge.py`

Add direct suggestion refresh after merge completes:

```python
async def merge_cluster_op(
    source_cluster_id: str,
    target_cluster_id: str,
    ...
    suggestion_service: SuggestionService | None = None,
) -> IdentityCluster | None:
    # ... existing merge logic ...
    
    # Refresh suggestions for all identities in target cluster
    if suggestion_service:
        target_members = await member_repo.get_by_cluster(target_cluster_id)
        for member in target_members:
            with contextlib.suppress(Exception):
                await suggestion_service.refresh_for_identity(
                    identity_id=member.identity_id,
                    reason=SuggestionRefreshReason.MANUAL_MERGE,
                )
    
    return updated_cluster
```

**Impact:** Immediate suggestions after merge (currently delayed until background job)

### Priority 2: Force Refetch After Mutation

**File:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useClusterMutations.ts`

Change invalidation to immediate refetch:

```typescript
// Replace invalidateQueries with refetchQueries
onSuccess: () => {
  void queryClient.refetchQueries({ queryKey: ['identity-suggestions'] });
  void queryClient.refetchQueries({ queryKey: ['pending-suggestions'] });
  void queryClient.invalidateQueries({ queryKey: ['clusters'] });
},
```

**Impact:** Suggestions immediately reload after curation

### Priority 3: Add Visual Feedback

**New File:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useSuggestionToast.ts`

Add toast notification hook:

```typescript
export const useSuggestionToast = () => {
  const queryClient = useQueryClient();
  
  useEffect(() => {
    const unsubscribe = queryClient.getQueryCache().subscribe((event) => {
      if (event.type === 'updated' && 
          event.query.queryKey[0] === 'identity-suggestions') {
        const data = event.query.state.data as IdentitySuggestionsResponse;
        if (data?.matches?.length > 0) {
          toast.success(`${data.matches.length} suggestions updated`);
        }
      }
    });
    return unsubscribe;
  }, [queryClient]);
};
```

**Impact:** User sees confirmation that suggestions were recomputed

### Priority 4: Prominently Display Similarity

**File:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx`

Show similarity badge on cluster cards when viewing suggestions:

```tsx
{cluster.topSuggestion && (
  <span className="acx-cluster__suggestion-badge">
    {cluster.topSuggestion.label} ({Math.round(cluster.topSuggestion.similarity * 100)}%)
  </span>
)}
```

**Impact:** Users always see similarity for suggested matches

---

## Additional Enhancements

### Suggestion Staleness Indicator

Add `refreshed_at` timestamp to UI:

```tsx
<span className="acx-suggestion__freshness">
  Updated {formatDistanceToNow(suggestion.refreshed_at)} ago
</span>
```

Shows users when suggestions were last recomputed.

### Batch Suggestion Refresh

**Current:** Refresh called individually for each identity (N queries)

**Proposed:** Add batch endpoint:

```python
@router.post("/suggestions/refresh-batch")
async def refresh_suggestions_batch(
    request: RefreshSuggestionsBatchRequest,
    ...
) -> RefreshSuggestionsBatchResponse:
    """Refresh suggestions for multiple identities in single request."""
    for identity_id in request.identity_ids:
        await suggestion_service.refresh_for_identity(
            identity_id=identity_id,
            reason=request.reason,
        )
    return RefreshSuggestionsBatchResponse(refreshed_count=len(request.identity_ids))
```

**Impact:** Reduces network overhead after large splits (10+ identities)

### Ground Truth Learning

**Problem:** User corrections (merges, splits) are ground truth labels but not used for model improvement

**Proposed:** Track curation events as training data:

```python
class CurationEvent(BaseModelcolumns:
    id: UUID
    tenant_id: UUID
    event_type: str  # "merge", "split", "remove"
    identity_id: UUID
    from_cluster_id: UUID | None
    to_cluster_id: UUID | None
    user_id: int
    created_at: datetime
```

Use these events to:
1. Fine-tune similarity thresholds per tenant
2. Identify systematic misclassifications
3. Build tenant-specific correction patterns

---

## Implementation Checklist (Proposed for v4.2.9)

- [ ] Add suggestion refresh to `merge_cluster_op()`
- [ ] Change frontend to use `refetchQueries` instead of `invalidateQueries`
- [ ] Add toast notifications for suggestion updates
- [ ] Display similarity % prominently on cluster cards
- [ ] Add `refreshed_at` staleness indicator
- [ ] Create batch refresh endpoint
- [ ] Add documentation for suggestion workflow
- [ ] Write integration test: merge → verify suggestions updated
- [ ] Write E2E test: user merges → sees toast → dropdown shows new suggestions

---

## Test Scenarios

### Manual Test 1: Verify Merge Triggers Suggestions

1. Label cluster A with "Alice" (10 faces)
2. Label cluster B with "Bob" (5 faces)
3. Merge cluster C (unlabeled, 3 faces) → cluster A
4. **Expected:** Cluster C's 3 identities get suggestions for cluster B (if similar)
5. **Current:** Suggestions don't update until background job runs (~10s later)

### Manual Test 2: Verify UI Shows Similarity

1. Create unlabeled singleton with face similar to labeled cluster
2. Open cluster dropdown
3. **Expected:** See "Suggested: Alice (87%)"
4. **Current:** May see "Alice" without percentage, or no suggestion at all

### Manual Test 3: Verify Refetch After Split

1. Split mixed cluster into 2 groups
2. Watch browser network tab
3. **Expected:** `GET /identities/{id}/suggestions` called immediately
4. **Current:** Query invalidated but not refetched until user action

---

## Open Questions for User

1. **Suggestion visibility:** Should suggestions appear in:
   - Inline prompt (current: yes)
   - Cluster dropdown (current: yes)
   - Cluster list view as badges (current: no)?

2. **Refresh timing:** Acceptable latency for suggestion updates?
   - Immediate (< 500ms) via sync refresh?
   - Background (5-10s) via async job?
   - Hybrid (immediate for small ops, async for bulk)?

3. **Similarity threshold:** Should UI filter suggestions below certain %?
   - Current backend band: 75-85%
   - Should frontend hide suggestions < 80%?

4. **Ground truth learning:** Priority for using curation events as training data?
   - High: Build per-tenant models
   - Medium: Track for analytics only
   - Low: Defer to future version
