# Implementation Plan: Representative Recomputation

Fixes for merge representative updates and cold-start fragmentation.

## Problem Summary

1. **Merge doesn't update representatives**: `merge_cluster()` calls `recompute_representatives()` but the method doesn't exist
2. **Cold start fragmentation**: Large batches fragment because graph algorithms can't leverage incremental representative building

---

## Why FPS, Not FAISS?

**FPS (Farthest-Point Sampling)** and **FAISS** solve different problems:

| Algorithm | Purpose | Use Case |
|-----------|---------|----------|
| **FAISS** | Fast nearest-neighbor **search** | "Find top-k similar vectors" |
| **FPS** | Diversity **selection** | "Pick k vectors covering the space" |

### FPS for Representative Selection

For representatives, we need **coverage**, not similarity:

```
Cluster has 100 faces with varying poses:
- 50 frontal faces (similar embeddings)
- 30 left-profile faces
- 20 right-profile faces
```

| Method | Result |
|--------|--------|
| Top-k by confidence | Picks 10 frontal faces (redundant) |
| FAISS k-means | Clusters, but loses outlier bridges |
| **FPS** | Picks 3 frontal + 3 left + 3 right + 1 bridge |

FPS guarantees geometric spread by iteratively picking the point farthest from all selected points.

---

## Proposed Changes

### 1. Add `recompute_representatives()` to AssignmentWriter

#### [MODIFY] [assignment_writer.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/persistence/assignment_writer.py)

```python
async def recompute_representatives(self, cluster_id: str) -> None:
    """Recompute cluster representatives using FPS for diversity."""
    members = await self._members.get_by_cluster(cluster_id)
    identities = await self._get_identities_for_members(members)
    await self._clusters.clear_representatives(cluster_id)
    
    selected = _select_diverse_representatives(
        identities, self._settings.max_representatives_per_cluster
    )
    for identity in selected:
        await self._clusters.add_representative(ClusterRepresentative(...))
```

---

### 2. Add `clear_representatives()` to ClusterRepository

#### [MODIFY] [repositories.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/domain/repositories.py)

---

### 3. Maturity-Based Chunked Processing

#### [MODIFY] [cluster_service.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/orchestration/cluster_service.py)

| Stage | Processed | Chunk Size |
|-------|-----------|------------|
| Cold start | 0-20 | 5 |
| Early | 20-50 | 10 |
| Maturing | 50-200 | 25 |
| Mature | 200+ | 50 |

```python
def _get_chunk_size(total_processed: int) -> int:
    if total_processed < 20: return 5
    if total_processed < 50: return 10
    if total_processed < 200: return 25
    return 50
```

---

## Test Coverage

### Unit Tests

#### [NEW] `test_recompute_representatives.py`

```python
# test_recompute_representatives_clears_and_rebuilds
# - Create cluster with 1 rep
# - Add 10 members with diverse embeddings
# - Call recompute_representatives()
# - Assert: old rep removed, 10 new reps added (max_reps=10)

# test_recompute_uses_fps_diversity
# - Create cluster with 100 members (50 frontal, 30 left, 20 right)
# - Call recompute_representatives() with max_reps=6
# - Assert: reps cover all 3 pose groups, not just highest confidence

# test_recompute_on_empty_cluster
# - Call recompute_representatives() on cluster with 0 members
# - Assert: no error, no reps added
```

#### [NEW] `test_clear_representatives.py`

```python
# test_clear_removes_all_reps
# - Create cluster with 5 reps
# - Call clear_representatives()
# - Assert: get_representative_count() == 0
```

#### [MODIFY] `test_cluster_service_merge.py`

```python
# test_merge_triggers_recompute_representatives
# - Merge cluster A (1 rep, 5 members) into B (1 rep, 10 members)
# - Assert: recompute_representatives called for target cluster
# - Assert: target cluster now has >1 rep covering merged diversity
```

#### [NEW] `test_adaptive_chunk_size.py`

```python
# test_chunk_size_cold_start -> 5
# test_chunk_size_early -> 10
# test_chunk_size_maturing -> 25
# test_chunk_size_mature -> 50
```

---

### Integration Tests

#### [MODIFY] `test_cluster_operations.py`

```python
# test_merge_actually_updates_representatives_in_db
# - Create real clusters with real embeddings
# - Merge via ClusterService
# - Query DB: SELECT COUNT(*) FROM identity_cluster_representatives
# - Assert: count increased to cover merged diversity
```

#### [NEW] `test_cold_start_chunked.py`

```python
# test_200_image_cold_start_no_fragmentation
# - Process 200 identities with known 5 people
# - Assert: creates ~5 clusters, not 100+ singletons
# - Assert: each cluster has diverse representatives

# test_chunk_boundaries_trigger_rep_refresh
# - Process 25 identities in cold start
# - Assert: recompute called at indices 5, 10, 15, 20
```

---

## Verification Commands

```bash
# Run affected tests
pytest recognition/tests/unit/test_recompute_representatives.py -v
pytest recognition/tests/unit/test_cluster_service_merge.py -v
pytest recognition/tests/integration/test_cluster_operations.py -v

# Database verification after merge
./scripts/db_shell.sh --admin -c "
  SELECT c.label, COUNT(r.*) as rep_count
  FROM identity_clusters c
  LEFT JOIN identity_cluster_representatives r ON r.cluster_id = c.id
  GROUP BY c.id, c.label
  ORDER BY rep_count DESC;
"
```
