# Clustering Pipeline Analysis & Simplification

**Date**: November 25, 2025  
**Related**: [improve-suggestion-ux-reduce-false-negatives.md](./improve-suggestion-ux-reduce-false-negatives.md)

## Table of Contents

1. [What Does the Match % Represent?](#what-does-the-match--represent)
2. [Dead Code Analysis](#dead-code-analysis)
3. [Confidence-Weighted Thresholds (Option C)](#confidence-weighted-thresholds-option-c)
4. [Industry Clustering Algorithms](#industry-clustering-algorithms)
5. [Is Chinese Whispers the Best Solution?](#is-chinese-whispers-the-best-solution)
6. [Pipeline Simplification Recommendations](#pipeline-simplification-recommendations)

---

## What Does the Match % Represent?

The match percentage shown to users in the cluster merge UI represents **centroid-to-embedding similarity**, not representative similarity.

### Current Implementation

**Frontend** (`IdentityClusterList.tsx` line 379):
```tsx
{Math.round(similarity * 100)}%
```

**Backend** (`suggestion_router.py`):
```python
distance_expr = ClusterCentroid.centroid.cosine_distance(embedding)
# ...
similarity = 1.0 - float(distance)
```

### The Similarity Types in the Pipeline

| Similarity Type | What It Measures | Where Used | Current Threshold |
|-----------------|------------------|------------|-------------------|
| **Representative similarity** | New face vs. best representative face | Clustering decision (Stage 1) | 0.65 |
| **Centroid similarity** | New face vs. cluster centroid (average) | Suggestion API, borderline validation | 0.60 |
| **Member similarity** | New face vs. random existing members | Member validation | 0.68 |
| **Pairwise similarity** | Any two faces within a cluster | Quality validation | N/A |

### The Problem

The user sees **centroid similarity** (suggestion API), but clustering decisions are made using **representative + member similarity**. These can differ significantly:

- Representative similarity: 0.64 → would match
- Centroid similarity: 0.58 → user sees "58% match"
- Member similarity: 0.56 → validation fails

**Result**: User sees a 58% match suggestion, but the system silently rejected it due to member validation (0.56 < 0.68).

### Recommendation

The UI should show **representative similarity** (the score used for the initial match decision), not centroid similarity. Additionally, consider showing both scores with labels:
- "Best match: 64%"
- "Average similarity: 58%"

---

## Dead Code Analysis

### 1. Centroids (Partially Dead)

**Status**: ⚠️ Used for suggestions API, but NOT for clustering decisions

**Evidence from logs**:
```
best_centroid=0.0000
```

**Why it's always 0.0000**:

```python
# identity_clustering_service.py line 462-464
centroid_candidates = [
    entry for entry in existing_clusters if entry.cluster.id not in representatives_by_cluster
]
```

Since **all clusters have representatives** (they're created with representatives), `centroid_candidates` is always empty. The centroid fallback path is never executed.

**Current uses**:
1. ✅ Suggestion API (`/identities/{id}/suggestions`) - uses centroid for quick matching
2. ✅ Borderline validation - checks centroid as secondary validation
3. ❌ Primary clustering - never used (all clusters have representatives)

**Recommendation**: 
- Keep centroids for the suggestion API (fast pgvector index search)
- Remove centroid fallback from clustering logic (dead path)
- Consider replacing centroid-based suggestions with representative-based suggestions for consistency

### 2. Ward Clustering (Dead Code)

**Status**: ❌ Dead code - never invoked

**Evidence**:

```python
# ward_clustering.py exists but is never called
# identity_clustering_service.py line 684-686
from recognition.application.chinese_whispers import ChineseWhispersClustering
cw = ChineseWhispersClustering(self.settings)
return await cw.cluster(...)
```

The method `_stage2_batch_clustering` is documented as "Ward linkage" but actually uses Chinese Whispers:

```python
async def _stage2_batch_clustering(
    self,
    identities: list[MediaIdentity],
    ...
) -> list[IdentityCluster]:
    """Cluster identities using Ward linkage on normalized embeddings."""  # LIES!
    # ...
    from recognition.application.chinese_whispers import ChineseWhispersClustering
    cw = ChineseWhispersClustering(self.settings)  # Actually uses Chinese Whispers
```

**Files to remove/archive**:
- `recognition/application/ward_clustering.py` - Never called
- `recognition/application/clustering_utils.py::convert_threshold_to_euclidean()` - Only used by Ward
- Settings: `ward_sync_batch_limit`, `ward_async_max_identities` - Never used

### 3. Centroid Match Threshold (Likely Dead)

**Status**: ⚠️ Configured but never hit in practice

```python
# clustering_settings.py
centroid_match_threshold: float = 0.73  # For centroid-based matching fallback
```

This threshold is used in `_match_via_centroids()`, but since all clusters have representatives, the centroid matching fallback is never triggered.

---

## Confidence-Weighted Thresholds (Option C)

### Current Problem

The pipeline uses **fixed thresholds** that don't account for face detection quality:

```python
similarity_threshold: float = 0.65
member_validation_threshold: float = 0.68
```

A 0.68 member threshold applied to:
- **High-confidence detection** (det_score=0.99, large bbox) → probably correct
- **Low-confidence detection** (det_score=0.75, small bbox) → might be wrong

### Confidence-Weighted Approach

Weight similarity by detection confidence:

```python
def confidence_adjusted_similarity(
    raw_similarity: float,
    source_confidence: float,
    target_confidence: float,
) -> float:
    """
    Adjust similarity based on detection confidence.
    
    High-confidence pairs get their similarity preserved.
    Low-confidence pairs get their similarity dampened.
    """
    confidence_factor = (source_confidence * target_confidence) ** 0.5
    
    # Interpolate between raw similarity and a lower "uncertain" value
    uncertain_baseline = 0.3
    return uncertain_baseline + (raw_similarity - uncertain_baseline) * confidence_factor
```

### Adaptive Thresholds

Instead of fixed thresholds, use confidence-based thresholds:

```python
def adaptive_threshold(base_threshold: float, confidence: float) -> float:
    """
    Lower threshold for high-confidence detections.
    Higher threshold for low-confidence detections.
    """
    # High confidence (0.95+) → threshold reduced by up to 10%
    # Low confidence (0.75) → threshold increased by up to 15%
    adjustment = 0.1 * (confidence - 0.85) / 0.15  # Scale around 0.85
    return base_threshold - adjustment
```

### Why This Helps

| Scenario | Current Behavior | With Adaptive Thresholds |
|----------|------------------|--------------------------|
| High-quality face, 0.62 similarity | Rejected (< 0.65) | Accepted (threshold lowered to 0.60) |
| Low-quality face, 0.66 similarity | Accepted | Rejected (threshold raised to 0.70) |
| Blurry face, 0.60 similarity | Rejected | Rejected (requires higher threshold) |

---

## Industry Clustering Algorithms

### Face Clustering Landscape

| Algorithm | Type | Pros | Cons | Used By |
|-----------|------|------|------|---------|
| **DBSCAN** | Density-based | No predefined clusters, handles noise | Sensitive to eps parameter | Facebook, Google Photos |
| **Chinese Whispers** | Graph-based | Linear time, non-parametric | Can merge distinct people via bridging | dlib, OpenFace |
| **Agglomerative (Ward)** | Hierarchical | Deterministic, good quality | O(n²) space, O(n³) time | Academic |
| **Approximate Rank-Order** | Nearest-neighbor | Scalable, handles hard cases | Complex implementation | Microsoft Face API |
| **HDBSCAN** | Density-based | Handles varying densities | Slower than DBSCAN | Some research systems |

### Industry Best Practices

**Google Photos** (2015 paper):
- Uses DBSCAN with cosine distance
- Threshold: ~0.4 (more permissive)
- Relies heavily on user corrections
- Prioritizes recall over precision

**Facebook**:
- Deep learning face verification model
- Threshold chosen for 99.63% accuracy on LFW
- Uses approximate nearest neighbor for scale

**Apple Photos**:
- On-device clustering
- Conservative thresholds (privacy-first)
- Heavy use of temporal/spatial context

### Key Insight

**Industry prefers recall over precision for face clustering**:
- It's easier to split a merged cluster than to find unmatched singletons
- User corrections are expected and designed for
- The goal is to surface potential matches, not make perfect decisions

---

## Is Chinese Whispers the Best Solution?

### Chinese Whispers Overview

**Algorithm**:
1. Build similarity graph (edges where similarity > threshold)
2. Initialize each node with unique label
3. Iterate: each node adopts the label of its most-connected neighbors
4. Converges to clusters

### Pros

- **Linear time**: O(V + E) per iteration
- **Non-parametric**: No need to specify cluster count
- **Natural**: Clusters form via consensus

### Cons

- **Threshold sensitivity**: The edge threshold (0.75 in current config) is critical
- **Bridging problem**: Weak links can merge distinct clusters
- **Non-deterministic**: Random iteration order affects results
- **No outlier handling**: All nodes must belong to some cluster

### Current Configuration Issues

```python
# clustering_settings.py
cw_threshold: float = 0.75  # Very strict - drops many valid edges
```

With a 0.75 threshold:
- Edges between 0.65-0.75 are dropped
- These might be valid same-person matches in different lighting
- Creates more singletons than necessary

### Recommendation: HDBSCAN

**HDBSCAN** (Hierarchical DBSCAN) addresses Chinese Whispers' weaknesses:

```python
import hdbscan

clusterer = hdbscan.HDBSCAN(
    min_cluster_size=2,
    min_samples=1,
    metric='precomputed',  # Use 1 - similarity as distance
    cluster_selection_epsilon=0.0,
    cluster_selection_method='eom',
)

# Convert similarity matrix to distance matrix
distances = 1.0 - similarity_matrix
labels = clusterer.fit_predict(distances)
```

**Advantages**:
- Handles varying cluster densities
- Explicit outlier detection (label = -1)
- Cluster persistence (confidence scores)
- More robust to bridging

**Trade-off**: O(n²) space for distance matrix, but manageable for typical batch sizes (<1000).

---

## Pipeline Simplification Recommendations

### Current Pipeline Complexity

```
Stage 1: Representative Matching
    ├── If similarity >= 0.65 and < 0.70: borderline validation
    │   ├── Check centroid similarity >= 0.60
    │   └── Check avg member similarity >= 0.68
    ├── If similarity >= 0.70: accept (but still check member validation!)
    └── If similarity < 0.65: reject, go to Stage 2

Stage 2: Chinese Whispers (for remaining)
    ├── Build graph with edge threshold 0.75
    ├── Run label propagation
    └── Create new clusters
```

**Problems**:
1. Too many thresholds (0.65, 0.68, 0.70, 0.73, 0.75)
2. Overlapping validation layers
3. Dead code paths (centroid fallback, Ward)
4. Overfitted to specific failure cases

### Simplified Pipeline Proposal

```
Stage 1: Representative Matching (unchanged)
    └── If similarity >= SINGLE_THRESHOLD (0.62): accept
        └── No secondary validation needed

Stage 2: User-Assisted Matching (NEW)
    └── If 0.50 <= similarity < 0.62: create suggestion for user review
        └── Store suggestion with confidence score
        └── User accepts or rejects

Stage 3: Batch Clustering (for remaining)
    └── Use HDBSCAN instead of Chinese Whispers
        └── More robust to threshold selection
        └── Explicit outlier handling
```

### Threshold Simplification

| Current | Proposed | Rationale |
|---------|----------|-----------|
| 5 thresholds | 2 thresholds | Reduce cognitive load |
| 0.65 (match) | 0.62 (match) | Increase recall |
| 0.68 (member validation) | Remove | Overfitted check |
| 0.70 (borderline upper) | Remove | Unnecessary complexity |
| 0.73 (centroid match) | Remove | Dead code |
| 0.75 (Chinese Whispers) | 0.50 (suggestion) | User-assisted for borderline |

### Dead Code Removal Checklist

- [ ] Delete `ward_clustering.py`
- [ ] Remove Ward-related settings from `clustering_settings.py`
- [ ] Remove `convert_threshold_to_euclidean()` from `clustering_utils.py`
- [ ] Remove centroid fallback from `cluster_identities_incremental()`
- [ ] Update docstrings that reference "Ward linkage"
- [ ] Archive or remove `centroid_match_threshold` setting

### Validation Layer Simplification

**Current** (3 validation layers):
1. Borderline validation (centroid check)
2. Member validation (random member check)
3. Quality validation (cluster health check)

**Proposed** (1 validation + user review):
1. Single similarity threshold
2. Borderline cases → user review
3. Remove automated secondary validation

**Philosophy**: Let the user make judgment calls on borderline cases rather than building increasingly complex automated heuristics that get overfitted.

---

## Summary

### Key Findings

1. **Match % in UI** = centroid similarity, but decisions use representative + member similarity → user confusion

2. **Dead code**:
   - Ward clustering (`ward_clustering.py`) - never called
   - Centroid fallback path - all clusters have representatives
   - Associated settings and utilities

3. **Pipeline is overfitted**:
   - `member_validation_threshold` raised to 0.68 to fix one issue
   - Created new issue (too many false negatives)
   - Pattern: fix one bug → introduce another

4. **Industry approach**: More permissive thresholds + user corrections, not stricter automated validation

5. **Chinese Whispers limitations**: Threshold sensitivity, bridging problem, no outlier handling

### Recommended Actions

1. **Immediate**: Remove dead code (Ward, centroid fallback)
2. **Short-term**: Implement suggestion tier for borderline cases
3. **Medium-term**: Replace Chinese Whispers with HDBSCAN
4. **Long-term**: Simplify to single threshold + user-assisted matching
