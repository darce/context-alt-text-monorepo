# Batch Consistency Fix — Implementation Specification

**Date:** 2025-12-13  
**Version:** 4.2.6  
**Status:** In Progress  
**Parent Document:** [batch_consistency_analysis.md](./batch_consistency_analysis.md)

---

## 1. Solution Overview

The root cause of batch inconsistency is **broken transitivity** across batches.
- **Single Batch:** Graph algorithms see all faces (A, B, C) and connect them: `A (frontal) ↔ B (side) ↔ C (profile)`.
- **Split Batch:**
    1. Batch 1 processes `A` and `B`. Cluster created.
    2. Batch 2 processes `C`.
    3. `C` fails to match `A` or `B` directly via `RepresentativeDiscovery` (threshold 0.85 is too high for A↔C).
    4. `GraphDiscovery` runs on `C` *in isolation*. It never sees `A` or `B`, so it cannot form the transitive link.

**Fix: Anchor Injection**. Inject representatives from existing clusters into the `GraphDiscovery` process as "anchor nodes". This restores the A↔B↔C link within the graph algorithm.

| Phase | Feature | Status |
|-------|---------|--------|
| **Phase A** | **FPS Diversity Selection** | ✅ **Completed** |
| **Phase B** | **Anchor Injection** | 🚧 **Primary Focus** |

---

## 2. Phase A — Diversity-Aware Representative Selection (Completed)

*Implemented Farthest-Point Sampling (FPS) to ensure representatives cover the geometric hull of the cluster. This is now live in `assignment_writer.py`.*

---

## 3. Phase B — Anchor Injection (Graph Retrospection)

### 3.1 Design

Modify `GraphDiscovery` to include existing cluster representatives (anchors) in the graph clustering process.

1. **Input**: `identities` (new faces) + `anchor_embeddings` (existing reps).
2. **Flatten**: Convert `anchor_embeddings` into a list of synthetic `AnchorIdentity` objects.
3. **Cluster**: Run CW/HDBSCAN on the combined list (`identities` + `anchors`).
4. **Resolve**:
    - Iterate through resulting groups.
    - If a group contains **Anchor(ClusterX)**, assign all new faces in that group to **ClusterX**.
    - If a group contains multiple anchors, resolve (prioritize majority or best fit).
    - If a group contains no anchors, it becomes a **New Cluster**.

### 3.2 Code Changes

#### [MODIFY] [graph.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/discovery/graph.py)

Update `discover` method:

```python
@dataclass
class AnchorIdentity:
    """Lightweight wrapper for anchor nodes."""
    id: str
    cluster_id: str
    confidence: float = 1.0  # Anchors have high authority
```

Logic flow:
```python
async def discover(self, identities, anchor_embeddings):
    # 1. Flatten anchors
    anchors: list[AnchorIdentity] = []
    anchor_vecs: list[np.ndarray] = []
    for cluster_id, reps in anchor_embeddings.items():
        for rep in reps:
            anchors.append(AnchorIdentity(id=f"anchor-{uuid4()}", cluster_id=cluster_id))
            anchor_vecs.append(self._normalize(rep))
    
    # 2. Combine inputs
    combined_identities = list(identities) + anchors
    combined_vectors = face_vectors + anchor_vecs
    
    # 3. Cluster
    labels = algorithm.cluster(combined_vectors, combined_identities)
    
    # 4. Group & Resolve
    grouped = self._group_by_label(combined_identities, combined_vectors, labels)
    
    for label, items in grouped.items():
        # Check for anchors in this group
        group_anchors = [item for item, _ in items if isinstance(item, AnchorIdentity)]
        new_members = [item for item, vec in items if isinstance(item, MediaIdentity)]
        
        if not new_members:
            continue
            
        if group_anchors:
            # Matched to existing cluster via anchor transitivity!
            # Pick best anchor cluster (majority vote or first)
            target_cluster = self._resolve_anchor_conflict(group_anchors)
            sim = self._compute_avg_similarity(new_members, group_anchors)
            
            for member in new_members:
                candidates.append(AssignmentCandidate(..., cluster_id=target_cluster, ...))
        else:
            # No anchors found -> New Cluster Proposal
            new_clusters.append((new_members, ...))
```

#### [MODIFY] [cluster_service.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/orchestration/cluster_service.py)

Ensure `GraphDiscovery` receives the anchors. (Existing code already passes `anchor_embeddings=representatives_by_cluster`, so minimal changes needed here, just verify it's passing *all* relevant representatives).

> [!NOTE] 
> No changes required for `chinese_whispers.py` or `hdbscan_adapter.py`. They operate on the generic sequence and will naturally process the injected anchors.

---

## 4. Verification Plan

### 4.1 New Unit Test

Add `test_graph_discovery_matches_via_anchor_injection` to `test_graph_discovery.py`.

```python
@pytest.mark.asyncio
async def test_graph_discovery_matches_via_anchor_injection() -> None:
    """Should match new identity to anchor cluster if they end up in same graph component."""
    # Setup: Anchor and Identity are far apart directly, but linked via a bridge (if we had one)
    # OR simpler: FakeAlgorithm returns same label for Identity and Anchor
    
    cluster_id = "existing-cluster-1"
    identity = make_identity(...)
    anchor_vec = ...
    
    # Fake algo forces them into label "0"
    discovery = GraphDiscovery(..., algorithm=FakeGraphAlgorithm([0, 0])) 
    
    result = await discovery.discover([identity], {cluster_id: [anchor_vec]})
    
    # Expect: Candidate pointing to "existing-cluster-1"
    assert len(result.candidates) == 1
    assert result.candidates[0].cluster_id == cluster_id
```

### 4.2 Integration Scenario (Manual)

1. **Reset DB**: Start fresh.
2. **Batch 1 (50 images)**: Process and verify clusters.
   - Example: `Muted Yarrow` -> Cluster A (frontal reps).
3. **Batch 2 (60 images)**: Process remaining 106 images (including difficult angles).
   - Without Fix: `RepresentativeDiscovery` fails (sim < 0.85). `GraphDiscovery` creates new Cluster B.
   - With Fix: `GraphDiscovery` includes Cluster A reps. CW links `Profile Face` <-> `Frontal Rep`.
   - **Result**: `Profile Face` is assigned to Cluster A.

### 4.3 Automated Integration Test

Create `tests/integration/test_batch_consistency.py`:
- Split a known dataset (e.g. LFW subset) into 2 batches.
- Run Batch 1. Count clusters.
- Run Batch 2. Count *new* clusters.
- Assert Total Clusters == Expected Unique Identities.

---

## 5. Rollback Plan

If Anchor Injection causes excessive false positives (merging distinct people due to weak links):
1. Revert `graph.py` changes.
2. Fallback to **Phase C (Two-Tier Threshold)** which is safer but less effective at handling transitivity.
