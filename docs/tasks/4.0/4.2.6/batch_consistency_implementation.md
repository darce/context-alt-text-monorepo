# Batch Consistency Fix — Implementation Specification

**Date:** 2025-12-13  
**Version:** 4.2.6  
**Status:** Proposed  
**Parent Document:** [batch_consistency_analysis.md](./batch_consistency_analysis.md)

---

## 1. Solution Evaluation Summary

The analysis document correctly identifies the **root cause**: when persisting a new cluster, representatives are selected by **image confidence only** (line 154 of `assignment_writer.py`), discarding "bridge" faces that would link to future batches.

| Proposed Approach | Correctness | Complexity | Recommendation |
|-------------------|-------------|------------|----------------|
| **Diversified Representative Selection** | ✅ Correct | Low | 👍 Implement **first** |
| **Sparse Coding for RepresentativeDiscovery** | ✅ Sound | Medium-High | Defer to future phase |
| **Anchor Injection into GraphDiscovery** | ✅ Sound | Medium | Implement after diversity fix |

> [!IMPORTANT]
> **Recommended Phased Approach**
> 1. **Phase A (this task):** Fix representative selection with diversity-aware sampling
> 2. **Phase B:** Add anchor injection to `GraphDiscovery` for cross-batch transitivity
> 3. **Phase C (optional):** Sparse Coding if diversity + anchors prove insufficient

---

## 2. Phase A — Diversity-Aware Representative Selection

### 2.1 Problem Recap

```python
# Current logic (assignment_writer.py:154)
sorted_identities = sorted(identities, key=lambda i: i.confidence, reverse=True)
```

This discards geometrically important bridge faces if they have lower detection confidence. The result:
- Faces from challenging angles (side profiles, occlusions) are systematically excluded
- Future batches cannot find transitive links through saved representatives

### 2.2 Proposed Algorithm: Farthest-Point Sampling (FPS)

Replace pure confidence sort with a hybrid:

1. **Seed**: Select the single highest-confidence face as the first representative
2. **Iterate**: For remaining slots, select the face that **maximizes minimum distance** from all already-chosen representatives
3. **Tie-break**: Among equidistant candidates, prefer higher confidence

This is computationally O(n·k) for k representatives and naturally preserves geometric extremes (bridge candidates).

### 2.3 Code Changes

#### [MODIFY] [assignment_writer.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/persistence/assignment_writer.py)

Add a helper function and update `persist_new_cluster`:

```python
def _select_diverse_representatives(
    identities: list[MediaIdentity],
    max_reps: int,
    extract_embedding: Callable[[MediaIdentity], np.ndarray],
) -> list[MediaIdentity]:
    """Select representatives via Farthest-Point Sampling for diversity.

    Args:
        identities: Pool of candidate identities.
        max_reps: Maximum number of representatives to select.
        extract_embedding: Function to extract normalized face vector.

    Returns:
        Selected representatives in insertion order.
    """
    if not identities:
        return []
    k = min(max_reps, len(identities))

    # Seed with highest-confidence face
    sorted_by_conf = sorted(identities, key=lambda i: i.confidence, reverse=True)
    selected: list[MediaIdentity] = [sorted_by_conf[0]]
    selected_vecs: list[np.ndarray] = [extract_embedding(sorted_by_conf[0])]
    remaining = set(range(1, len(sorted_by_conf)))

    for _ in range(k - 1):
        if not remaining:
            break
        best_idx: int | None = None
        best_min_dist = -1.0
        for idx in remaining:
            vec = extract_embedding(sorted_by_conf[idx])
            min_dist = min(float(1 - np.dot(vec, sv)) for sv in selected_vecs)
            if min_dist > best_min_dist:
                best_min_dist = min_dist
                best_idx = idx
        if best_idx is None:
            break
        selected.append(sorted_by_conf[best_idx])
        selected_vecs.append(extract_embedding(sorted_by_conf[best_idx]))
        remaining.remove(best_idx)

    return selected
```

Then in `persist_new_cluster` (lines 151-166), replace:

```diff
-        # Create initial representative(s) from the highest-confidence identities
-        if identities:
-            # Sort by confidence descending and pick top few as representatives
-            sorted_identities = sorted(identities, key=lambda i: i.confidence, reverse=True)
-            num_reps = min(self._settings.max_representatives_per_cluster, len(sorted_identities))
-            for i in range(num_reps):
-                identity = sorted_identities[i]
+        # Create initial representative(s) using diversity-aware sampling
+        if identities:
+            diverse_reps = _select_diverse_representatives(
+                identities,
+                self._settings.max_representatives_per_cluster,
+                lambda i: self._normalize_face(np.asarray(i.embedding, dtype=np.float32)),
+            )
+            for identity in diverse_reps:
```

Add the normalize helper if not already present (it exists in discovery classes):

```python
def _normalize_face(self, embedding: np.ndarray) -> np.ndarray:
    """Extract the 512D face embedding and normalize to unit length."""
    from recognition.shared.similarity import extract_face_embedding
    vec = extract_face_embedding(embedding)
    norm = float(np.linalg.norm(vec))
    if norm == 0:
        return vec.astype(np.float32)
    return vec.astype(np.float32) / norm
```

#### [MODIFY] [clustering.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/settings/clustering.py)

Increase default representative count (optional but recommended):

```diff
     max_representatives_per_cluster: int = Field(
-        default=5, description="Maximum number of representatives to maintain per cluster."
+        default=10, description="Maximum number of representatives to maintain per cluster."
     )
```

---

## 3. Phase B — Anchor Injection into GraphDiscovery

### 3.1 Concept

Inject pre-existing cluster representatives as **fixed anchor nodes** into the batch graph so Chinese Whispers can discover transitive links:

```
New_A <--> New_B <--> Anchor_Rep (existing cluster)
```

### 3.2 Code Changes

#### [MODIFY] [graph.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/discovery/graph.py)

1. Add a parameter `inject_anchors: bool = False` to `discover()`
2. When `inject_anchors=True`:
   - Add anchor reps as special nodes (flagged as anchors)
   - Compute edges: `new↔new` and `new↔anchor` only (skip `anchor↔anchor`)
   - During label resolution, if a component contains anchors, assign all new faces to that anchor's cluster

#### [MODIFY] [cluster_service.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/orchestration/cluster_service.py)

In `cluster_unclustered_identities`:
- Before calling `graph_discovery.discover()`, load anchors for clusters with centroids meeting a relaxed threshold (e.g., 0.60)
- Pass `inject_anchors=True`

#### [MODIFY] [chinese_whispers.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/infrastructure/clustering/chinese_whispers.py)

Add anchor-aware mode:
- Anchor nodes keep their original labels during propagation
- Track which component each anchor belongs to for final resolution

---

## 4. Verification Plan

### 4.1 Unit Tests

| Test File | Test Name | Purpose |
|-----------|-----------|---------|
| `test_assignment_writer.py` | `test_persist_new_cluster_selects_diverse_representatives` | Verify FPS selects geometrically diverse faces, not just highest confidence |
| `test_assignment_writer.py` | `test_diverse_selection_preserves_bridge_face` | Create identities where a low-confidence face bridges two sub-clusters; verify it's selected |

**Commands:**
```bash
cd /Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service
make test-unit  # runs pytest recognition/tests/unit/
```

### 4.2 Integration Tests

| Test | Purpose |
|------|---------|
| `test_batch_split_produces_consistent_clusters` | Send 100 images in two batches of 50; verify final cluster count matches single-batch |

**Commands:**
```bash
cd /Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service
make test-integration  # runs pytest recognition/tests/integration/
```

### 4.3 Manual Verification (User)

1. Reset dev database: `./scripts/reset_dev_db.sh`
2. Start service: `make run`
3. Cluster 75 images in first batch (POST `/clustering/jobs`)
4. Add labels to a few clusters via UI
5. Cluster remaining 106 images in second batch
6. **Expected**: Faces from Batch 2 that belong to Batch 1 persons are assigned to the correct clusters, not forming new clusters
7. Verify in logs: `RepresentativeDiscovery MATCHED` entries should appear for cross-batch matches

---

## 5. Appendix: Embedding & Similarity Reference

| Term | Value | Location |
|------|-------|----------|
| `similarity_threshold` | 0.85 | `ClusteringSettings` |
| `complete_link_min_floor` | 0.80 | `ClusteringSettings` |
| `max_representatives_per_cluster` | 5 → 10 | `ClusteringSettings` |
| `representative_diversity_threshold` | 0.90 | `ClusteringSettings` |
| Face embedding dimensions | 512 | First half of 1024D vector |

---

## 6. Related Files

- [assignment_writer.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/persistence/assignment_writer.py)
- [representative.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/discovery/representative.py)
- [graph.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/discovery/graph.py)
- [cluster_service.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/orchestration/cluster_service.py)
- [clustering.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/settings/clustering.py)
- [test_assignment_writer.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/tests/integration/test_assignment_writer.py)
