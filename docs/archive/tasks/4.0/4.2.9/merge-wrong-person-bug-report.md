# Critical Bug Report: Merge & Wrong Person Failures

**Date:** 2025-12-22  
**Severity:** P0 - Blocking curation workflow  
**Branch:** fix/4.2.8.1-connection-pool-leak

---

## Bug 1: Merge Cluster Returns 404

### Symptoms

**Error:** `404: Cluster not found` when merging clusters  
**Affected Operation:** `POST /clusters/{id}/merge`  
**Example:** Merging cluster `4aa8c252-9b5f-46d7-afc0-26d69f6e4d6c` for media 6513

**Log Evidence:**
```
2025-12-22 12:51:15,210 ERROR recognition.interface_adapters.http.dependencies - get_optional_session: exception during yield/commit: 404: Cluster not found
2025-12-22 12:52:21,385 ERROR recognition.interface_adapters.http.dependencies - get_optional_session: exception during yield/commit: 404: Cluster not found
2025-12-22 12:52:22,883 ERROR recognition.interface_adapters.http.dependencies - get_optional_session: exception during yield/commit: 404: Cluster not found
```

### Root Cause

**File:** `recognition/application/orchestration/cluster_merge.py` line 299

The merge operation **deletes the source cluster** before the session commits:

```python
# Line 292: Move members
moved = await member_repo.move_members(source_cluster_id, target_cluster_id)

# Line 293-297: Update target cluster
target.identity_count = (target.identity_count or 0) + moved
target.label = target_label or target.label
target.is_labeled = bool(target.label)
target.user_confirmed = True
updated: IdentityCluster = await cluster_repo.update(target)

# Line 299: DELETE SOURCE - THIS CAUSES 404
await cluster_repo.delete(source_cluster_id)  # ❌ PROBLEM

# Lines 301-310: Recompute representatives/centroid for TARGET cluster
# ... this works ...

# Session commits in dependencies.py::get_session() finally block
# But source cluster is already marked for deletion!
# SQLAlchemy tries to flush DELETE but target cluster update references it
# → 404: Cluster not found
```

**Why It Fails:**

1. `cluster_repo.delete()` marks source cluster for deletion in SQLAlchemy session
2. Subsequent operations (recompute reps, log events) try to reference deleted cluster
3. When session commits, SQLAlchemy flushes DELETE first
4. Foreign key constraints or ORM relationships fail
5. **HTTPException with 404 raised during commit phase**
6. Error caught in `dependencies.py` line 251 but surfaces as generic 404

### Impact

- **All merge operations fail** with 404
- User cannot consolidate clusters
- Workflow completely blocked
- Database left in inconsistent state (members moved but source not deleted)

---

## Bug 2: Wrong Person Removal Not Working

### Symptoms

**Error:** Cannot remove media items 6705, 6703, 6702 from cluster assignment  
**Ground Truth:** Laura Dresser not in any of these images (false positive)  
**Affected Operation:** "Wrong person" button / remove from cluster

### Database Investigation Results

**Query Results (Admin Mode):**
```
                  id                  | media_id |              cluster_id              |      label       
--------------------------------------+----------+--------------------------------------+------------------
 8afaacee-c1dd-4bbf-b76d-b72079053847 |     6702 | 25e1d8a4-90ca-4a45-b285-977d4ca103ef | Laura Dresser
 00583ee2-3f87-4283-999e-aeb89e25ced3 |     6702 | 8f5c73f7-f371-442c-968c-9d928d097f9e | Slate Willow
 29e6a293-aa66-42e2-b1fd-e6f90a069025 |     6703 | 25e1d8a4-90ca-4a45-b285-977d4ca103ef | Sable Dresser
 0c7ae9ef-31d1-4678-8f22-687123f0d423 |     6703 | 8f5c73f7-f371-442c-968c-9d928d097f9e | Slate Willow
 f16da274-fec9-42b5-950c-241f09ebb5c0 |     6705 | c8d17a77-5e2c-4f28-9955-54d5fd218773 | (unlabeled)
 6084a67f-1e0f-42e4-b92a-ce9d4a198eda |     6705 | 06e29c3d-cbb5-411c-950c-20c33d1f3c1e | (unlabeled)
 d550f092-ddfd-4216-8a7e-4c7902f143c3 |     6705 | 25e1d8a4-90ca-4a45-b285-977d4ca103ef | Laura Dresser
 913bc4d4-4a10-4491-983b-09b65b940808 |     6705 | 8f5c73f7-f371-442c-968c-9d928d097f9e | Slate Willow
(8 rows)
```

**Key Finding:** Each media item has **MULTIPLE FACES** (2-4 faces detected per image):
- Media 6702: 2 faces (Sable Dresser + Slate Willow)
- Media 6703: 2 faces (Sable Dresser + Slate Willow)
- Media 6705: 4 faces (2 unlabeled + Sable Dresser + Slate Willow)

### Root Cause Analysis

**Problem:** UI doesn't handle multi-face media items correctly in "Wrong Person" workflow.

**Frontend Code Path:**
1. User clicks "Wrong person" button (`IdentityClusterItem.tsx:167`)
2. Calls `handleWrongPerson()` which calls `mutations.reassign(cluster.members.map(m => m.identity_id))` (line 176)
3. `reassign()` loops through ALL identity IDs and calls `reassignClusterIdentity()` for each (line 83-113 in `clusterApi.ts`)
4. Backend `/clusters/reassign` endpoint removes identities from their clusters

**The Issue:**
- UI passes **ALL identity IDs in the cluster** to reassign
- For Laura Dresser cluster, this includes identities from media 6702, 6703, 6705 **AND many other media items**
- When user clicks "Wrong person" on media 6702, intent is to remove **only the Laura Dresser face from 6702**
- BUT the code removes **ALL faces in the Laura Dresser cluster**, including correct matches from other media

**Example Scenario:**
1. User views cluster "Laura Dresser" showing media 6702
2. User recognizes the face in 6702 is NOT Laura Dresser (false positive)
3. User clicks "Wrong person"
4. **Expected:** Remove identity `8afaacee-c1dd-4bbf-b76d-b72079053847` (Laura face in 6702) from Laura cluster
5. **Actual:** Removes ALL 20+ identities in Laura Dresser cluster (breaks entire cluster)

### Why It's Not Working

**UI/UX Gap:** The "Wrong person" button is on the **cluster card**, not on individual faces.

- User sees: "Laura Dresser cluster containing 20 faces"
- User clicks: "Wrong person" thinking "this one face is wrong"
- System interprets: "Remove all faces from this cluster" (cluster-level action, not face-level)

**Fix Required:** Need face-level "Wrong person" action, not cluster-level.


---

## Immediate Workaround

### For Merge:

**DON'T USE** merge until fixed. Alternative:
1. Manually reassign identities from source → target  
2. Delete empty source cluster separately

### For Wrong Person:

**Current workaround:** Open media item detail and remove specific identities
1. Click on media thumbnail to view all faces in that image
2. Identify which face is wrong
3. Use per-face action to remove only that identity

---

## Fix Required

### Priority 1: Fix Merge Delete Timing

**File:** `recognition/application/orchestration/cluster_merge.py`

**Current (BROKEN):**
```python
async def merge_cluster(...) -> IdentityCluster | None:
    # ... move members ...
    updated: IdentityCluster = await cluster_repo.update(target)
    
    await cluster_repo.delete(source_cluster_id)  # ❌ TOO EARLY
    
    # ... recompute reps ...
    # Session commits here via dependency cleanup
```

**Fixed:**
```python
async def merge_cluster(...) -> IdentityCluster | None:
    # ... move members ...
    updated: IdentityCluster = await cluster_repo.update(target)
    
    # ... recompute reps ...
    
    # Delete source cluster LAST, after all operations complete
    await cluster_repo.delete(source_cluster_id)  # ✅ AFTER recompute
    
    return updated
```

### Priority 2: Add Face-Level Wrong Person Action

**Problem:** Wrong person button operates on entire cluster, not individual face.

**Solution Options:**

**Option A: Media Detail View** (Recommended)
- Add "Wrong person" button to each face in media detail modal
- Only removes that specific identity, not entire cluster
- Cleaner UX for multi-face scenarios

**Option B: Context Menu on Cluster Card**
- Right-click on cluster thumbnail shows menu
- "Remove this face only" vs "Remove all faces from cluster"
- More discoverable but more complex UI

**Implementation:**
```typescript
// Add to media detail face card
const handleRemoveFace = (identityId: string) => {
  if (window.confirm('Remove this face from the cluster?')) {
    reassignClusterIdentity({ 
      identityId, 
      targetClusterId: null, 
      blockFromCluster: true 
    });
  }
};
```

---

## Test Scenarios

### Test 1: Verify Merge Fix

```bash
# Setup: Create two labeled clusters
curl -X POST http://localhost:8000/recognition/clusters/create-for-identity \
  -d '{"identity_id": "identity-1", "label": "Alice", "tenant_id": "..."}' 

curl -X POST http://localhost:8000/recognition/clusters/create-for-identity \
  -d '{"identity_id": "identity-2", "label": "Bob", "tenant_id": "..."}'

# Merge Bob → Alice
curl -X POST http://localhost:8000/recognition/clusters/{bob-cluster-id}/merge \
  -d '{"target_cluster_id": "{alice-cluster-id}", "tenant_id": "..."}'

# Expected: 200 OK with updated cluster
# Current: 404 Cluster not found
```

### Test 2: Verify Face-Level Wrong Person

```bash
# Remove specific identity from cluster (media 6702, Laura face)
curl -X POST http://localhost:8000/recognition/clusters/reassign \
  -d '{
    "identity_id": "8afaacee-c1dd-4bbf-b76d-b72079053847",
    "target_cluster_id": null,
    "block_from_cluster": true,
    "tenant_id": "..."
  }'

# Expected: 200 OK, only this identity removed
# Verify: Maria face in same media 6702 remains in cluster
```

---

## Rollback Plan

If fix causes new issues:

1. **Revert to previous commit** before connection pool fixes
2. **Document known issue:** "Merge temporarily disabled"
3. **Use manual workflow:** Reassign + delete separately

---

## Related Issues

- Connection pool leak (fixed in v4.2.8.1)
- Suggestion refresh after merge (documented in v4.2.9 findings)
- Delete operation timing (this bug)

These issues suggest **transaction management needs review** across curation operations.
