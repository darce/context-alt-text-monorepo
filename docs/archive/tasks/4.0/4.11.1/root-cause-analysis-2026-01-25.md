# Root Cause Analysis: Validation Criteria Failure (2026-01-25)

**Date**: 2026-01-25  
**Branch**: `refactor/4.11.1-clustering-persitence-and-false-positives`  
**Dataset**: 100 images analyzed  
**Baseline Comparison**: Previous 2 batches from `logs/archive/logs/`

---

## Executive Summary

After processing 100 images, the system failed ALL validation criteria from `false-positive-analysis.md`:

| Criterion                       | Expected | Actual        | Status    |
| ------------------------------- | -------- | ------------- | --------- |
| Review Suggestions populated    | Any      | 0             | ❌ FAILED |
| Pose Diversity buckets          | >0/13    | 0/13          | ❌ FAILED |
| Landmark Quality variance       | <1.0     | Always 1.0    | ❌ FAILED |
| 50% reduction in manual assigns | <8       | 15+           | ❌ FAILED |
| Singleton reduction             | Lower    | 82 singletons | ❌ FAILED |

---

## Root Causes Identified

### 1. CRITICAL: Centroid Data Not Loaded in `get_by_tenant()` Query

**Location**: [cluster_repository.py#L68](../../../../apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py#L68)

**Problem**: The `get_by_tenant()` query loads `representatives` but does NOT load `centroid_data`:

```python
stmt = (
    select(ClusterModel)
    .where(ClusterModel.tenant_id == _coerce_uuid(tenant_id))
    .options(selectinload(ClusterModel.representatives).selectinload(...))  # ❌ No centroid_data
    ...
)
```

**Impact**: When `MergeSuggestionService.generate_for_tenant()` fetches clusters via `get_by_tenant()`, all clusters have `centroid=None`. The fallback in `_extract_cluster_centroid()` computes centroid from representatives, but:

- Representatives may not cover full embedding diversity
- Falls back to computing on-the-fly, slower and less accurate

**Evidence from DB**:

```
cluster_count:          109
centroid_count (MV):    27
merge_suggestion_count: 0
```

Only 27/109 clusters have centroids in the MV (those with ≥2 members).

**Fix Required**: Add `selectinload(ClusterModel.centroid_data)` to the query options.

---

### 2. CRITICAL: MV Centroid Refresh Not Called After Clustering

**Location**: [orchestrator.py#L545](../../../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L545)

**Problem**: After clustering completes and commits, `refresh_centroids_view()` is NEVER called. The materialized view `mv_identity_cluster_centroids` becomes stale immediately after new clusters are created.

**Impact**:

- Merge suggestion generation happens in `cluster_service.py#L172-179` AFTER commit
- But the MV wasn't refreshed, so centroid data is stale/missing
- `generate_cluster_merge_suggestions()` can't compute similarities

**Evidence**:

```sql
-- Before manual refresh: 27 centroids
-- After manual refresh: 27 centroids (same - MV wasn't stale, just incomplete)
```

**Fix Required**: Call `refresh_centroids_view()` before merge suggestion generation in `cluster_service.py`.

---

### 3. CRITICAL: 82 Singletons Not Eligible for Merge Suggestions

**Location**: MV definition in [001_identity_schema.py#L952-999](../../../../apps/prototype-description-service/db/migrations/versions/001_identity_schema.py#L952)

**Problem**: The materialized view filters `WHERE identity_count >= 2`:

```sql
SELECT ... FROM cluster_embeddings WHERE (identity_count >= 2);
```

**Impact**:

- 109 clusters total, only 27 have ≥2 members
- 82 clusters are singletons (1 member each) → no centroid in MV
- Singleton clusters cannot participate in merge suggestions
- User must manually assign all 82 singletons

**Evidence from DB**:

```sql
-- identity_members: 198 total
-- 198 members across 27 clusters with count ≥2
-- Remaining 82 clusters have 0 members in identity_members table
```

**Design Question**: Should singleton clusters have centroids computed from their single representative? This would enable:

- Singleton-to-singleton merge suggestions
- Singleton-to-cluster merge suggestions

---

### 4. HIGH: Pose Diversity Always 0/13 Buckets

**Location**: [cluster_repository.py#L504-L512](../../../../apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py#L504-L512)

**Problem**: Pose buckets are computed in `_to_domain()` from representatives, but the `filled_buckets` set is only populated when BOTH conditions are true:

1. Representative has `identity` loaded
2. Identity has both `pose_pitch` AND `pose_yaw` non-null

**Evidence from DB**:

```sql
-- pose_pitch and pose_yaw ARE populated:
pose_pitch: 11.02, -27.69, 22.70, ... (all non-null)
pose_yaw: -26.09, 24.82, -25.83, ... (all non-null)
```

**Root Cause**: The pose data is on `media_identities`, but when computing `debug_metrics` for a representative, the code accesses `rep.identity` which must be eagerly loaded. If the identity isn't loaded or the representative has a different identity reference, pose data is lost.

**Investigation Needed**: Check if `rep.identity` is properly joined in the representative query.

---

### 5. HIGH: Landmark Quality Always 1.0

**Location**: [cluster_repository.py#L532](../../../../apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py#L532)

**Problem**:

```python
"landmark_quality": float(identity.quality_score or 1.0),
```

When `identity.quality_score` is `NULL`, it defaults to `1.0`.

**Evidence from DB**:

```sql
quality_score | cnt
--------------+-----
              | 198   -- ALL records have NULL quality_score
```

**Root Cause**: The `quality_score` column is never populated during face detection. The archived code had:

```python
embedding[LANDMARK_QUALITY_IDX] = landmark_std / 100.0
```

But the current codebase doesn't compute `landmark_std` from landmark positions.

**Fix Required**: Compute landmark quality during face detection from landmark point variance.

---

### 6. MEDIUM: HAC Refinement Not Reducing Singletons

**Location**: [orchestrator.py#L469-L479](../../../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L469-L479)

**Problem**: HAC refinement runs but produces no new clusters:

```
hac_created: 0
```

**Possible Causes**:

1. `still_unclustered` is empty after HDBSCAN (all assigned)
2. HAC settings too strict (distance_threshold too low)
3. Embeddings not similar enough for any merges

**Evidence from Logs**:

```
[clustering] batch_complete job_id=... accepted=0 suggested=0 rejected=0 new_clusters=27
```

No identities went through the gate (accepted/suggested/rejected=0), meaning all identities were clustered by HDBSCAN into new clusters immediately.

**Design Issue**: HAC refinement only runs on `still_unclustered` identities that weren't matched by HDBSCAN. If HDBSCAN creates many small clusters (singletons), HAC never sees them.

---

### 7. MEDIUM: Previous Batches Show Same Pattern

**Comparison with `logs/archive/logs/recognition.log.1`**:

```
2026-01-20: RENAMED x3, ASSIGNED x2 (manual corrections)
           identity_suggestions table didn't exist (migration issue)
           No merge suggestions generated
```

The same issues existed in previous batches - this is not a regression from recent changes, but a systemic issue present since before the current sprint.

---

## Database State Analysis

```sql
-- Current state:
identity_clusters:           109
identity_members:            198  (across 27 clusters with ≥2 members)
identity_cluster_representatives: ~73
cluster_merge_suggestions:   0
mv_identity_cluster_centroids: 27

-- Breakdown:
Clusters with ≥2 members:    27  (eligible for centroid in MV)
Singleton clusters:          82  (no centroid, no merge suggestions possible)
```

---

## Required Fixes (Priority Order)

### P0 - Blocking (Must fix before re-test)

#### P0.1: Add centroid_data loading to `get_by_tenant()`

**File**: `recognition/infrastructure/repositories/cluster_repository.py`  
**Function**: `get_by_tenant()` (line ~68)

**Pattern**: SQLAlchemy eager loading with `selectinload`

**Current Code**:

```python
stmt = (
    select(ClusterModel)
    .where(ClusterModel.tenant_id == _coerce_uuid(tenant_id))
    .options(selectinload(ClusterModel.representatives).selectinload(IdentityClusterRepresentative.identity))
    ...
)
```

**Required Change**:

```python
stmt = (
    select(ClusterModel)
    .where(ClusterModel.tenant_id == _coerce_uuid(tenant_id))
    .options(
        selectinload(ClusterModel.representatives).selectinload(IdentityClusterRepresentative.identity),
        selectinload(ClusterModel.centroid_data),  # ADD THIS
    )
    ...
)
```

**Reasoning**: Without eager loading `centroid_data`, the relationship is never populated and `_to_domain()` returns `centroid=None`. The MV has the data, but SQLAlchemy doesn't fetch it.

**Test**: After fix, verify `cluster.centroid is not None` for clusters with ≥2 members.

---

#### P0.2: Refresh centroids MV before merge suggestion generation

**File**: `recognition/application/orchestration/cluster_service.py`  
**Function**: `cluster_unclustered()` (line ~172)

**Pattern**: Call infrastructure method before dependent operation

**Current Code**:

```python
if commit and self.merge_suggestion_service is not None:
    try:
        created = await self.merge_suggestion_service.generate_for_tenant(tenant_id)
```

**Required Change**:

```python
if commit and self.merge_suggestion_service is not None:
    try:
        # Refresh MV so centroids are available for similarity computation
        await self.assignment_writer.refresh_centroids_view()
        created = await self.merge_suggestion_service.generate_for_tenant(tenant_id)
```

**Reasoning**: The MV is stale after clustering creates new clusters. Must refresh before querying centroids for merge suggestion similarity calculations.

**Alternative Location**: Could also add to `_finalize_job()` in orchestrator.py before commit, but cluster_service.py is the better location since it owns merge suggestion orchestration.

---

#### P0.3: Compute singleton centroids dynamically (bypass MV limitation)

**File**: `recognition/application/suggestions/merge_suggestions.py`  
**Function**: `_extract_cluster_centroid()` (line ~149)

**Pattern**: Fallback computation when MV data unavailable

**Current Code**:

```python
def _extract_cluster_centroid(cluster: IdentityCluster) -> np.ndarray | None:
    if cluster.centroid is not None:
        return np.array(cluster.centroid, dtype=np.float32)

    representatives = cluster.representatives or []
    embeddings = [rep.embedding for rep in representatives if rep.embedding is not None]
    if not embeddings:
        return None
    try:
        return compute_centroid(embeddings)
    except ValueError:
        return None
```

**Analysis**: The fallback already exists! The issue is that `representatives` may not be loaded. Check if `get_by_tenant()` is loading representatives properly.

**Additional Fix Needed**: Ensure `_is_eligible_for_merge_suggestion()` doesn't filter out singletons. Current logic (line ~122) should already allow unlabeled/auto-labeled clusters.

**Test**: Add logging to `_extract_cluster_centroid()` to verify:

```python
logger.debug(
    "[merge_suggestions] _extract_cluster_centroid cluster_id=%s has_centroid=%s rep_count=%d",
    cluster.id, cluster.centroid is not None, len(cluster.representatives or [])
)
```

---

### P1 - High Priority

#### P1.1: Fix pose bucket computation

**File**: `recognition/infrastructure/repositories/cluster_repository.py`  
**Function**: `_to_domain()` (line ~504)

**Pattern**: Verify eager loading chain is complete

**Current Code**:

```python
.options(selectinload(ClusterModel.representatives).selectinload(IdentityClusterRepresentative.identity))
```

**Investigation**: The chain `ClusterModel → representatives → identity` should load pose data. Add diagnostic logging:

```python
# In _to_domain(), inside the representative loop
for rep in model_reps:
    identity = rep.identity
    logger.debug(
        "[cluster_repo] rep_id=%s identity_loaded=%s pitch=%s yaw=%s",
        rep.id,
        identity is not None,
        getattr(identity, 'pose_pitch', 'N/A') if identity else 'N/A',
        getattr(identity, 'pose_yaw', 'N/A') if identity else 'N/A',
    )
```

**Possible Root Cause**: The `rep.identity` might be a different identity than the one with pose data if there's a mismatch between `identity_cluster_representatives.identity_id` and the actual media identity.

---

#### P1.2: Compute landmark quality during detection

**File**: `recognition/application/detection/face_detector.py` (or similar)

**Pattern**: Compute derived metric from landmark positions

**Reference Implementation** (from archived code):

```python
# From archived-recognition.4.2.3/domain/embeddings/builder.py
landmark_std = np.std([landmark.x for landmark in landmarks] + [landmark.y for landmark in landmarks])
embedding[LANDMARK_QUALITY_IDX] = landmark_std / LANDMARK_STD_SCALE  # LANDMARK_STD_SCALE = 100.0
```

**Required Change**: During face detection, compute landmark variance and store in `quality_score` column:

```python
def compute_landmark_quality(landmarks: list[tuple[float, float]]) -> float:
    """Compute quality score from landmark position variance."""
    if not landmarks:
        return 1.0
    xs = [p[0] for p in landmarks]
    ys = [p[1] for p in landmarks]
    std = np.std(xs + ys)
    return min(1.0, std / 100.0)  # Normalize to 0-1 range
```

**Note**: This requires finding where face detection creates `MediaIdentity` records and adding the computation there.

---

### P2 - Medium Priority

#### P2.1: Review HAC refinement scope

**File**: `recognition/application/orchestration/clustering/orchestrator.py`  
**Function**: `_process_chunks()` (line ~469)

**Current Behavior**: HAC runs on `still_unclustered` which is:

- Identities with no candidates from discovery
- Identities rejected by gate

**Problem**: HDBSCAN creates singletons BEFORE HAC runs. HAC only sees identities that weren't assigned by HDBSCAN, not existing singleton clusters.

**Potential Fix Options**:

**Option A**: Post-clustering singleton merge pass

```python
# After clustering completes, query singleton clusters and run HAC on them
async def merge_similar_singletons(self, tenant_id: str) -> int:
    singletons = await self._cluster_repo.get_singletons(tenant_id)
    if len(singletons) < 2:
        return 0
    embeddings = [s.centroid for s in singletons if s.centroid is not None]
    # Run HAC on singleton embeddings to find merge candidates
    ...
```

**Option B**: Lower HDBSCAN min_cluster_size to reduce singletons

- Currently uses `min_cluster_size=2`, which creates many singletons
- Could increase to 3 but would create more noise

**Recommendation**: Option A is more targeted. Implement as separate service that runs after merge suggestion generation.

---

## Recommended Test Plan

After P0 fixes:

1. Reset database: `make db-reset`
2. Process 100 images
3. Verify:
   - [ ] `cluster_merge_suggestions` count > 0
   - [ ] Review Suggestions panel shows suggestions
   - [ ] Pose buckets > 0/13
   - [ ] Manual assigns required < 8 (50% reduction from 15)

---

## References

- [false-positive-analysis.md](false-positive-analysis.md) - Original validation criteria
- [cluster_repository.py](../../../../apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py) - Query definitions
- [cluster_service.py](../../../../apps/prototype-description-service/recognition/application/orchestration/cluster_service.py) - Merge suggestion trigger
- [merge_suggestions.py](../../../../apps/prototype-description-service/recognition/application/suggestions/merge_suggestions.py) - Generation logic

---

## Implementation Checklist

### P0 - Blocking (Complete before re-testing)

- [x] **P0.1** Add `selectinload(ClusterModel.centroid_data)` to `get_by_tenant()`
  - File: `recognition/infrastructure/repositories/cluster_repository.py`
  - Function: `get_by_tenant()` (~line 68)
  - Verify: `cluster.centroid is not None` for multi-member clusters

- [x] **P0.2** Call `refresh_centroids_view()` before merge suggestion generation
  - File: `recognition/application/orchestration/cluster_service.py`
  - Function: `cluster_unclustered()` (~line 172)
  - Add before: `await self.merge_suggestion_service.generate_for_tenant(...)`

- [x] **P0.3** Verify representatives are loaded for singleton centroid fallback
  - File: `recognition/application/suggestions/merge_suggestions.py`
  - Function: `_extract_cluster_centroid()` (~line 149)
  - Action: Add debug logging to confirm `cluster.representatives` is populated
  - Fallback already exists - confirm it's reachable

- [x] **P0.4** (Added) MV includes singletons (`WHERE identity_count >= 1`)
  - File: `db/migrations/versions/001_identity_schema.py` (~line 984)
  - Changed from `>= 2` to `>= 1`

### P1 - High Priority

- [x] **P1.1** Diagnose pose bucket computation
  - File: `recognition/infrastructure/repositories/cluster_repository.py`
  - Function: `_to_domain()` (~line 527)
  - Logging added: `rep_id`, `identity_id`, `pose_pitch`, `pose_yaw`

- [x] **P1.2** Compute landmark quality during face detection
  - File: `recognition/application/embedding/detector.py` (~line 32)
  - Function: `_compute_landmark_quality()` - computes `np.std(points) / 100.0`
  - Used in: `service.py` lines 243, 271 - sets `quality_score` from `det.landmark_quality`

### P2 - Future Improvement

- [x] **P2.1** Add post-clustering singleton merge pass
  - Function: `generate_singleton_merge_suggestions(tenant_id, constrained_hac, hac_settings)`
  - File: `recognition/application/suggestions/merge_suggestions.py` (~line 67)
  - Uses HAC to group similar singletons and creates merge suggestions
  - Called from: `cluster_service.py` after regular merge suggestions (~line 178)
  - Test: `test_generate_singleton_merge_suggestions_groups_singletons`

### Validation Criteria (from 4.11.1)

| Metric                    | Before | Target | After |
| ------------------------- | ------ | ------ | ----- |
| Merge suggestions         | 0      | > 0    |       |
| Pose buckets filled       | 0/13   | ≥ 5/13 |       |
| Landmark quality variance | 0      | > 0    |       |
| Manual assigns saved      | 0/15   | ≥ 50%  |       |
| False positives           | N/A    | 0      |       |

### Quick Commands

```bash
# Reset and re-test after P0 fixes
cd apps/prototype-description-service
make db-reset
# Then process 100 images via WordPress admin

# Check merge suggestions
echo "SELECT COUNT(*) FROM cluster_merge_suggestions;" | ./scripts/db_shell.sh --admin

# Check centroid coverage
echo "SELECT COUNT(*) as clusters, (SELECT COUNT(*) FROM mv_identity_cluster_centroids) as centroids FROM identity_clusters;" | ./scripts/db_shell.sh --admin
```
