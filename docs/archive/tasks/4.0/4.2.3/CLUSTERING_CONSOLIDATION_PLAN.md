# Clustering Pipeline Consolidation Plan

**Date**: November 28, 2025  
**Sprint**: 4.2.3.1  
**Status**: Proposed  
**Author**: Generated from pipeline analysis

---

## Executive Summary

The current clustering codebase has **three parallel clustering paths** that have diverged over time:

1. `cluster_identities_incremental()` - Original per-identity loop (legacy)
2. `cluster_batch_incremental()` - Chunked processing with Chinese Whispers (new)
3. `cluster_identities_hybrid()` - Entry point that routes to sync/async paths

This fragmentation causes:

- **Bugs**: Fixes applied to one path don't propagate to others
- **Confusion**: Different log formats, different behavior for same inputs
- **Degradation**: Each "fix" adds complexity, creating new edge cases

**Goal**: Consolidate to **one canonical path** with clear, testable stages. Replace Chinese Whispers with HDBSCAN for better outlier handling and density adaptation.

---

## Current State Analysis

### The Three Paths (Problem)

```
┌────────────────────────────────────────────────────────────────────────────┐
│  cluster_identities_hybrid() [Entry Point - AMBIGUOUS NAME]                │
│      │                                                                     │
│      ├── Sync path (≤100 identities)                                       │
│      │      └── cluster_batch_incremental() ← NEW (with CW + validation)   │
│      │                                                                     │
│      └── Async path (>100 identities)                                      │
│             └── ClusteringJobService.process_clustering_job()              │
│                    └── cluster_batch_incremental() ← Same as sync          │
│                                                                            │
│  cluster_identities_incremental() [Legacy - STILL CALLED!]                 │
│      └── Per-identity loop, centroid fallback, no CW ← DIFFERENT BEHAVIOR  │
│                                                                            │
│  cluster_identities() [Shim]                                               │
│      └── Calls cluster_identities_incremental() ← BYPASSES NEW PATH        │
└────────────────────────────────────────────────────────────────────────────┘
```

### Ordinal-Dependent Names (Problem)

Current function names use stage numbers that create coupling:

- `stage2_batch_clustering()` - What if we insert a stage before it?

**Current → Proposed Renames:**

| Current Name                       | Proposed Name                      | Rationale                    |
| ---------------------------------- | ---------------------------------- | ---------------------------- |
| `cluster_identities_hybrid()`      | `cluster_unclustered_identities()` | Describes what it does       |
| `stage2_batch_clustering()`        | `cluster_via_graph()`              | Describes the algorithm type |
| `cluster_batch_incremental()`      | `process_clustering_batch()`       | Action-oriented              |
| `cluster_identities_incremental()` | **DELETE**                         | Dead code                    |
| `cluster_identities()`             | **DELETE**                         | Dead shim                    |

### Dead Code to Remove

| File/Function                      | Status                       | Action     |
| ---------------------------------- | ---------------------------- | ---------- |
| `cluster_identities()`             | Shim bypassing new path      | **DELETE** |
| `cluster_identities_incremental()` | Legacy, no CW                | **DELETE** |
| `convert_threshold_to_euclidean()` | Only for Ward                | **DELETE** |
| `ward_clustering.py`               | Never existed (only in docs) | N/A        |

---

## HDBSCAN Integration

### Why Replace Chinese Whispers with HDBSCAN

From [clustering-algorithm-comprehensive-analysis.md](./clustering-algorithm-comprehensive-analysis.md):

| Aspect            | Chinese Whispers        | HDBSCAN               |
| ----------------- | ----------------------- | --------------------- |
| Density Handling  | Single global threshold | Automatic adaptation  |
| Outlier Detection | None (all assigned)     | Explicit (label=-1)   |
| Determinism       | Non-deterministic       | Deterministic         |
| Implementation    | Custom (error-prone)    | Library (well-tested) |

**Key insight**: HDBSCAN handles varying cluster densities automatically and explicitly identifies outliers, which aligns with our suggestion-based approach for borderline cases.

### HDBSCAN Settings (Already in Schema)

The database and settings already have HDBSCAN support:

```python
# clustering_settings.py (existing but unused)
use_hdbscan_for_outliers: bool = False
hdbscan_min_cluster_size: int = 2
hdbscan_min_samples: int = 1
```

### Implementation

**New file**: `recognition/application/clustering/hdbscan_clustering.py`

```python
"""HDBSCAN-based clustering for unmatched identities.

HDBSCAN (Hierarchical DBSCAN) provides:
- Automatic density adaptation (no eps parameter)
- Explicit outlier detection (label=-1)
- Deterministic results
- Cluster persistence scores for confidence

Reference: clustering-algorithm-comprehensive-analysis.md Q8-Q9
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

import hdbscan
import numpy as np

from db.models import IdentityCluster, MediaIdentity
from recognition.application.clustering.clustering_settings import ClusteringSettings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class HDBSCANClustering:
    """Cluster identities using HDBSCAN algorithm."""

    def __init__(self, settings: ClusteringSettings) -> None:
        self.settings = settings
        self.min_cluster_size = settings.hdbscan_min_cluster_size
        self.min_samples = settings.hdbscan_min_samples

    async def cluster(
        self,
        identities: list[MediaIdentity],
        create_cluster: Callable[[Sequence[MediaIdentity]], Awaitable[tuple[IdentityCluster, object]]],
        anchor_embeddings: dict[UUID, list[np.ndarray]] | None = None,
        add_to_cluster: Callable[[UUID, Sequence[MediaIdentity]], Awaitable[None]] | None = None,
    ) -> list[IdentityCluster]:
        """
        Cluster identities using HDBSCAN.

        Args:
            identities: Unclustered identities to process
            create_cluster: Callback to persist new cluster
            anchor_embeddings: Existing cluster representatives for anchor matching
            add_to_cluster: Callback to add members to existing cluster

        Returns:
            List of newly created clusters (outliers become singletons)
        """
        if not identities:
            return []

        # Build embedding matrix
        embeddings = np.array(
            [np.array(ident.embedding, dtype=np.float32) for ident in identities],
            dtype=np.float32,
        )

        # Convert to distance matrix (HDBSCAN uses distances, not similarities)
        # For normalized embeddings: distance = 1 - cosine_similarity = 1 - dot_product
        similarity_matrix = np.dot(embeddings, embeddings.T)
        distance_matrix = 1.0 - similarity_matrix

        # Run HDBSCAN
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=self.min_cluster_size,
            min_samples=self.min_samples,
            metric="precomputed",
            cluster_selection_method="eom",  # Excess of Mass - better for varying densities
        )
        labels = clusterer.fit_predict(distance_matrix)

        # Log results
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        n_outliers = sum(1 for label in labels if label == -1)
        logger.info(
            "HDBSCAN: %d identities → %d clusters, %d outliers",
            len(identities),
            n_clusters,
            n_outliers,
        )

        # Group by label
        clusters_by_label: dict[int, list[MediaIdentity]] = {}
        outliers: list[MediaIdentity] = []

        for identity, label in zip(identities, labels, strict=True):
            if label == -1:
                outliers.append(identity)
            else:
                clusters_by_label.setdefault(label, []).append(identity)

        # Try to match clusters to anchors first
        created_clusters: list[IdentityCluster] = []

        if anchor_embeddings and add_to_cluster:
            for label, members in list(clusters_by_label.items()):
                # Compute cluster centroid
                member_embeddings = np.array(
                    [np.array(m.embedding, dtype=np.float32) for m in members]
                )
                centroid = member_embeddings.mean(axis=0)
                centroid = centroid / np.linalg.norm(centroid)

                # Find best anchor match
                best_anchor_id: UUID | None = None
                best_similarity = 0.0

                for cluster_id, reps in anchor_embeddings.items():
                    for rep in reps:
                        sim = float(np.dot(centroid, rep))
                        if sim > best_similarity:
                            best_similarity = sim
                            best_anchor_id = cluster_id

                # If good match, add to existing cluster
                if best_anchor_id and best_similarity >= self.settings.similarity_threshold:
                    logger.info(
                        "HDBSCAN cluster (label=%d, %d members) → anchor %s (sim=%.4f)",
                        label,
                        len(members),
                        best_anchor_id,
                        best_similarity,
                    )
                    await add_to_cluster(best_anchor_id, members)
                    del clusters_by_label[label]

        # Create new clusters for remaining groups
        for label, members in clusters_by_label.items():
            cluster, _ = await create_cluster(members)
            created_clusters.append(cluster)
            logger.info(
                "HDBSCAN created cluster %s from label=%d (%d members)",
                cluster.id,
                label,
                len(members),
            )

        # Outliers become singleton clusters
        for outlier in outliers:
            cluster, _ = await create_cluster([outlier])
            created_clusters.append(cluster)
            logger.debug("HDBSCAN outlier → singleton cluster %s", cluster.id)

        return created_clusters
```

### Hybrid Algorithm Selection

For large batches, keep Chinese Whispers as fallback (O(E) vs O(n²)):

```python
# In process_clustering_batch():
if len(remaining) <= self.settings.hdbscan_max_batch_size:  # e.g., 500
    # Use HDBSCAN for better quality
    from recognition.application.clustering.hdbscan_clustering import HDBSCANClustering
    clusterer = HDBSCANClustering(self.settings)
else:
    # Fall back to Chinese Whispers for scale
    from recognition.application.clustering.chinese_whispers import ChineseWhispersClustering
    clusterer = ChineseWhispersClustering(self.settings)

chunk_clusters = await clusterer.cluster(remaining, ...)
```

---

## Consolidation Plan

### Phase 1: Delete Dead Code (Immediate)

Since this is a greenfield project with no production footprint, directly remove dead code.

#### Task 1.1: Delete legacy clustering methods

```python
# identity_clustering_service.py - DELETE THESE:
# - cluster_identities()
# - cluster_identities_incremental()
```

#### Task 1.2: Delete unused utilities

```python
# clustering_utils.py - DELETE:
# - convert_threshold_to_euclidean()  # Only used by Ward (never existed)
```

#### Task 1.3: Update test files

Any tests calling deleted methods should be updated to use `cluster_unclustered_identities()`.

### Phase 2: Rename Functions

#### Task 2.1: Rename entry point

```python
# identity_clustering_service.py
# OLD: async def cluster_identities_hybrid()
# NEW: async def cluster_unclustered_identities()
```

#### Task 2.2: Rename graph clustering

```python
# batch_clustering.py
# OLD: async def stage2_batch_clustering()
# NEW: async def cluster_via_graph()
```

#### Task 2.3: Rename batch processor

```python
# batch_clustering.py
# OLD: async def cluster_batch_incremental()
# NEW: async def process_clustering_batch()
```

### Phase 3: Implement HDBSCAN

#### Task 3.1: Create HDBSCAN module

Create `recognition/application/clustering/hdbscan_clustering.py` (see implementation above).

#### Task 3.2: Add to requirements

```txt
# requirements_main.txt
hdbscan>=0.8.33
```

#### Task 3.3: Add settings

```python
# clustering_settings.py
hdbscan_max_batch_size: int = 500  # Use HDBSCAN for batches up to this size
```

#### Task 3.4: Update batch processor

```python
# In process_clustering_batch():
# Replace direct Chinese Whispers call with algorithm selection
```

### Phase 4: Simplify Thresholds

Current threshold sprawl (7 thresholds):

- `similarity_threshold` = 0.65
- `borderline_lower_threshold` = 0.65
- `borderline_upper_threshold` = 0.85
- `member_validation_threshold` = 0.85
- `centroid_match_threshold` = 0.73
- `cw_threshold` = 0.78
- `early_stage_high_confidence_threshold` = 0.90

**Proposed consolidation (4 thresholds)**:

```python
@dataclass
class ClusteringSettings:
    # === Core Thresholds ===
    similarity_threshold: float = 0.75       # Rep matching threshold
    high_confidence_threshold: float = 0.90  # Auto-accept any stage

    # === Validation ===
    member_validation_threshold: float = 0.85  # Lookalike rejection

    # === Graph Clustering ===
    graph_edge_threshold: float = 0.78  # CW/HDBSCAN edge creation
```

---

## Proposed Unified Pipeline

### Single Path Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  cluster_unclustered_identities() [Single Entry Point]                      │
│      │                                                                       │
│      ├── Small batch (≤ sync_limit)                                         │
│      │      └── process_clustering_batch(batch_id=uuid4())                  │
│      │                                                                       │
│      └── Large batch (> sync_limit)                                         │
│             └── enqueue_clustering_job()                                    │
│                    └── ClusteringJobService.process_clustering_job()        │
│                           └── process_clustering_batch(batch_id=job.id)     │
│                                                                              │
│  process_clustering_batch() [Single Implementation]                          │
│      │                                                                       │
│      ├── Match to Representatives                                           │
│      │      ├── Match to existing cluster representatives                   │
│      │      ├── Early-stage guard: borderline → suggestion                  │
│      │      └── Validation: member similarity check                         │
│      │                                                                       │
│      ├── Match to Centroids (optional fallback)                             │
│      │      └── For edge cases with missing representatives                 │
│      │                                                                       │
│      └── cluster_via_graph() [HDBSCAN or Chinese Whispers]                  │
│             ├── HDBSCAN: batch ≤ 500 (quality)                              │
│             └── Chinese Whispers: batch > 500 (scale)                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Simplified Decision Flow

```
For each identity:
  │
  ├─► Find best representative match
  │      │
  │      ├─► similarity ≥ 0.90 → AUTO-ASSIGN (any stage)
  │      │
  │      ├─► 0.75 ≤ similarity < 0.90 (early stage) → CREATE SUGGESTION
  │      │
  │      ├─► 0.75 ≤ similarity < 0.90 (mature) → VALIDATE & ASSIGN
  │      │      └─► member_avg ≥ 0.85 → assign
  │      │      └─► member_avg < 0.85 → reject, go to graph clustering
  │      │
  │      └─► similarity < 0.75 → REJECT, go to graph clustering
  │
  └─► cluster_via_graph() (for unmatched)
         ├─► HDBSCAN: Creates clusters, marks outliers as singletons
         └─► Optional: Match HDBSCAN clusters to anchors
```

---

## Implementation Checklist

### Phase 1: Delete Dead Code

- [x] Delete `cluster_identities()` from identity_clustering_service.py
- [x] Delete `cluster_identities_incremental()` from identity_clustering_service.py
- [x] Delete `convert_threshold_to_euclidean()` from clustering_utils.py
- [x] Update tests to use new entry point

### Phase 2: Rename Functions

- [x] Rename `cluster_identities_hybrid()` → `cluster_unclustered_identities()`
- [x] Rename `stage2_batch_clustering()` → `cluster_via_graph()`
- [x] Rename `cluster_batch_incremental()` → `process_clustering_batch()`
- [x] Update all call sites
- [x] Update ClusteringJobService to use new names

### Phase 3: Implement HDBSCAN

- [x] Create `hdbscan_clustering.py`
- [x] Add `hdbscan` to requirements (optional dependency in pyproject.toml)
- [x] Add `hdbscan_max_batch_size` setting (default 500)
- [x] Update `cluster_via_graph()` to select algorithm based on batch size
- [ ] Enable `use_hdbscan_for_outliers` by default (optional - for later)

### Phase 4: Simplify Thresholds (DEFERRED)

- [ ] Remove `borderline_lower_threshold` (redundant with similarity_threshold)
- [ ] Remove `borderline_upper_threshold` (use member_validation_threshold)
- [ ] Remove `centroid_match_threshold` (rarely used)
- [ ] Rename `cw_threshold` → `graph_edge_threshold`

---

## Implementation Notes

**Completed 2025-01-28:**

- Consolidated three clustering paths into one: `cluster_unclustered_identities()`
- All clustering now goes through `BatchClusteringProcessor.process_clustering_batch()`
- `cluster_via_graph()` selects HDBSCAN (≤500 identities) or Chinese Whispers (>500)
- HDBSCAN falls back to Chinese Whispers if hdbscan package not installed
- Renamed job_id → batch_id for consistency in log correlation
- Updated tests to use new method names and dict return type

**Algorithm selection logic:**

```python
if len(identities) <= self.settings.hdbscan_max_batch_size:
    # Use HDBSCAN for better quality
    clusterer = HDBSCANClustering(self.settings)
else:
    # Fall back to Chinese Whispers for scale (O(E) vs O(n²))
    clusterer = ChineseWhispersClustering(self.settings)
```

---

## Success Metrics

1. **Single code path**: All clustering goes through `process_clustering_batch()`
2. **Reduced complexity**: ~150 lines deleted (legacy methods, Ward utils)
3. **HDBSCAN enabled**: Better outlier handling, deterministic results
4. **Threshold clarity**: From 7 thresholds to 4
5. **Clear naming**: No ordinal dependencies, descriptive function names

---

## References

- [clustering-pipeline-analysis.md](./clustering-pipeline-analysis.md) - Dead code analysis
- [clustering-algorithm-comprehensive-analysis.md](./clustering-algorithm-comprehensive-analysis.md) - HDBSCAN vs CW comparison (Q8-Q9)
- [early-stage-suggestion-guard.md](./early-stage-suggestion-guard.md) - Suggestion system design
- [Chinese Whispers Paper](../../../literature/extracted/recognition/chinese-whispers.txt) - Algorithm details
