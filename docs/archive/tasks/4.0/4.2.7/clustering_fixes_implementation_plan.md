# Implementation Plan: Clustering Pipeline Fixes

## Summary

Three critical issues identified:
1. **MaturityCheck blocks all cold-start clustering** (redundant check)
2. **Suggestions show UUID clusters** instead of user-labeled only
3. **`/create-for-identity` endpoint missing** (405 error)

---

## Issue 1: Remove MaturityCheck (Redundant)

### Analysis

The MaturityCheck is **contradictory** with CompleteLinkCheck:

| Check | rep_count < 2 | rep_count >= 2 |
|-------|---------------|----------------|
| **MaturityCheck** | FAIL | PASS |
| **CompleteLinkCheck** | PASS (auto) | Check sims |

CompleteLinkCheck **already handles singleton clusters** correctly:
```python
if rep_count < 2:
    return CheckResult(passed=True, ...)  # Auto-pass for singletons
```

MaturityCheck was designed to prevent "singleton snowballing" but CompleteLinkCheck/ConfidenceCheck already provide this protection via similarity thresholds.

### Fix

#### [DELETE] Disable MaturityCheck

Option A (safest): Set `min_representatives_for_maturity = 0` to disable

#### [MODIFY] [clustering.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/settings/clustering.py)

```python
min_representatives_for_maturity: int = Field(
    default=0,  # Changed from 2 to 0 (disabled)
    description="Minimum reps before auto-assignment. 0 = disabled."
)
```

Option B (cleaner): Remove MaturityCheck from gate entirely

---

## Issue 2: Filter Suggestions to User-Labeled Clusters Only

### Problem

Suggestions currently include clusters with default UUID labels (e.g., `901afe40-...`).
Users see these confusing suggestions instead of meaningful labels.

### Fix

#### [MODIFY] [suggestion_service.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/suggestions/suggestion_service.py)

Before creating suggestion, check if target cluster is user-labeled:

```python
async def create(self, candidate: AssignmentCandidate, confidence: float) -> None:
    # Only suggest for user-labeled clusters
    cluster = await self._cluster_repo.get_by_id(candidate.cluster_id)
    if not cluster or not cluster.user_confirmed:
        return  # Don't create suggestion for unlabeled clusters
    # ... existing logic
```

---

## Issue 3: Add Missing `/create-for-identity` Endpoint

### Problem

Frontend sends `POST /recognition/clusters/create-for-identity`  
Backend returns 405 Method Not Allowed

Endpoint exists in archived code but not current router.

### Fix

#### [MODIFY] [routers/clusters.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py)

Port from archived:

```python
class CreateClusterForIdentityRequest(BaseModel):
    identity_id: str
    label: str

class CreateClusterForIdentityResponse(BaseModel):
    cluster_id: str
    label: str

@router.post("/clusters/create-for-identity", response_model=CreateClusterForIdentityResponse)
async def create_cluster_for_identity(
    request: CreateClusterForIdentityRequest,
    cluster_service: ClusterService = Depends(get_cluster_service),
    tenant_id: str = Depends(get_tenant_id),
) -> CreateClusterForIdentityResponse:
    """Create a new cluster for a specific identity."""
    cluster = await cluster_service.create_cluster_for_identity(
        identity_id=request.identity_id,
        label=request.label,
        tenant_id=tenant_id,
    )
    return CreateClusterForIdentityResponse(
        cluster_id=cluster.id,
        label=cluster.label,
    )
```

#### [MODIFY] [cluster_service.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/orchestration/cluster_service.py)

Add method:

```python
async def create_cluster_for_identity(
    self,
    identity_id: str,
    label: str,
    tenant_id: str,
) -> IdentityCluster:
    """Create a new labeled cluster containing a single identity."""
    # 1. Get identity
    # 2. Create cluster with label
    # 3. Add identity as member
    # 4. Create representative from identity embedding
    # 5. Return cluster
```

---

## Priority Order

1. **Disable MaturityCheck** (1 line change, fixes cold-start)
2. **Filter suggestions** (simple filter)
3. **Add endpoint** (port from archived)

---

## Verification

```bash
# After changes, reset DB and test cold start
./scripts/reset_dev_db.sh
# Process 50 images
# Verify: ACCEPTED count > 0, not all SUGGESTED
```
