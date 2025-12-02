# Clustering Algorithm Evaluation

**Date**: December 1st 2025  
**Context**: Recognition Service V2 Rewrite  
**Purpose**: Evaluate clustering algorithms for face identity grouping

---

## 🚨 CRITICAL BUG DISCOVERED: Metadata Dilution

**Status**: FIXED in `centroid_utils.py` (December 1, 2025)

Before evaluating algorithms, we discovered a **fundamental bug** in similarity computation that invalidated all previous clustering results:

### The Bug

Our 1024D extended embeddings contain:
- **Dims 0-511**: Face identity embedding (what we SHOULD compare)
- **Dims 512-1023**: Metadata (pose, age, gender, detection score, etc.)

The `compute_similarity()` function was normalizing and comparing the **full 1024D vector**. Due to metadata having larger values:

| Component | Norm (Energy) | % of Total |
|-----------|---------------|------------|
| Face (0-511) | ~2.2 | ~13% |
| Metadata (512-1023) | ~15.2 | ~87% |

**Result**: Similarity was computed primarily on metadata, not faces. Two completely different people with similar pose/age/detection scores matched at 97%+ similarity!

### The Fix

```python
# centroid_utils.py - compute_similarity() now extracts face only
face_a = _to_face_embedding(vec_a)  # First 512D
face_b = _to_face_embedding(vec_b)  # First 512D
similarity = np.dot(normalize(face_a), normalize(face_b))
```

### Impact on This Evaluation

With the bug fixed:
1. **All algorithms will now work correctly** — They were never broken, the input similarities were wrong
2. **Thresholds may need recalibration** — 0.88 threshold on face-only similarity may behave differently
3. **Guards will be effective** — Complete-link and maturity checks now validate actual face similarity

---

## Problem Statement

We need to cluster face embeddings (512-dimensional normalized vectors) into identity groups. The ideal algorithm must:

1. Handle varying cluster densities (some people have many photos, others few)
2. Work with incremental data (new identities added over time)
3. Produce stable, reproducible results
4. Handle outliers gracefully (don't force wrong assignments)
5. Scale to thousands of identities

---

## Algorithms Evaluated

### 1. Chinese Whispers (CW)

**Source**: Biemann (2006) - "Chinese Whispers - an Efficient Graph Clustering Algorithm"

**How it works**:
- Time-linear graph clustering: O(E) where E = number of edges
- Each node starts with unique class label
- Iteratively: each node adopts the most frequent class in its neighborhood
- Converges when classes stabilize (typically 20-50 iterations)

**Pros**:
- Very fast for large graphs
- No predefined cluster count needed
- Handles varying cluster sizes well
- Parameter-free (threshold defines edges, not algorithm)

**Cons**:
- **Non-deterministic** - Different runs can produce different results
- Cannot cross component boundaries (disconnected subgraphs stay separate)
- No explicit outlier handling (all nodes get assigned)
- Small graphs can oscillate between states

**Best for**: Large batches (>500 identities) where speed matters more than perfect determinism.

**Current usage**: Fallback when HDBSCAN unavailable or batch too large.

---

### 2. HDBSCAN (Hierarchical Density-Based Clustering)

**Source**: Campello et al. (2013) - "Density-Based Clustering Based on Hierarchical Density Estimates"

**How it works**:
- Builds minimum spanning tree of mutual reachability distances
- Constructs cluster hierarchy based on density
- Extracts flat clusters using stability-based selection
- Points not fitting any cluster labeled as noise (-1)

**Pros**:
- **Explicit outlier detection** - Noise points not forced into clusters
- Handles varying density automatically
- **Deterministic** (given same input)
- Well-tested library implementation (hdbscan package)
- `cluster_selection_epsilon` parameter respects our similarity threshold

**Cons**:
- O(n²) complexity for distance matrix computation
- Slower than CW for large batches
- Requires tuning `min_cluster_size` and `min_samples`

**Best for**: Smaller batches (≤500 identities) where precision matters.

**Recommended settings**:
```python
min_cluster_size = 2  # Minimum faces to form a person
min_samples = 1       # Allow edge cases
cluster_selection_epsilon = 1.0 - similarity_threshold  # e.g., 0.12 for 0.88 threshold
```

---

### 3. Agglomerative Hierarchical Clustering (AHC)

**Variants**: Single-link, Complete-link, Average-link, Ward

**How it works**:
- Bottom-up: Start with each point as its own cluster
- Iteratively merge closest clusters based on linkage criterion
- Stop when desired number of clusters or distance threshold reached

**Linkage methods**:

| Method | Distance between clusters | Behavior |
|--------|--------------------------|----------|
| Single-link | Min distance between any pair | Chaining effect (bad for faces) |
| Complete-link | Max distance between any pair | Compact, spherical clusters |
| Average-link | Average of all pairwise distances | Balance |
| Ward | Minimize within-cluster variance | Tends to equal-size clusters |

**Pros**:
- Deterministic
- Complete-link produces compact clusters (good for faces)
- Well-understood theory

**Cons**:
- **O(n³) for Ward**, O(n² log n) for others
- No natural outlier handling
- Number of clusters or threshold must be specified
- Single-link has catastrophic "chaining" for face embeddings

**Best for**: Small datasets or offline analysis. **Not recommended** for real-time.

---

### 4. K-Means

**How it works**:
- Requires predefined number of clusters K
- Iteratively assigns points to nearest centroid, recomputes centroids
- Converges to local optimum

**Pros**:
- Very fast: O(nkt) where k=clusters, t=iterations
- Simple to implement
- Works well for roughly spherical clusters

**Cons**:
- **Requires K upfront** - We don't know how many people are in the dataset
- Assumes equal-size clusters (violates our reality)
- Sensitive to initialization
- No outlier handling (every point assigned)

**Not recommended** for our use case. Fundamental mismatch with variable number of identities.

---

### 5. Representative-Based Matching

**How it works** (our current primary method):
- Each cluster maintains representative embeddings (diverse samples)
- New identity matched against representatives using cosine similarity
- Match if similarity to any representative ≥ threshold

**Pros**:
- O(n × r) where r = total representatives (typically small)
- Incremental: handles streaming data naturally
- Deterministic
- Easy to understand and debug

**Cons**:
- Requires existing clusters (cold start problem)
- Single representative match can be misleading (lookalike problem)
- No automatic cluster discovery

**Best for**: Incremental matching to existing clusters. Must be combined with graph clustering for new cluster discovery.

---

## Recommendation: Hybrid Pipeline

Based on the analysis, we recommend a **two-phase hybrid approach**:

### Phase 1: Representative Discovery
```
New identities → RepresentativeDiscovery → Candidates to existing clusters
                                         → Remaining go to Phase 2
```

- Fast: O(n × r)
- Uses proven representative matching
- Handles incremental data well

### Phase 2: Graph Clustering for Remaining

```
Remaining identities → HDBSCAN (if ≤500) → New clusters + outliers
                    → Chinese Whispers (if >500) → New clusters (all assigned)
```

**Why HDBSCAN over CW for smaller batches**:
1. Explicit outlier detection → feeds into suggestion system
2. Deterministic → easier testing and debugging
3. Respects our similarity threshold via `cluster_selection_epsilon`

**Why CW for larger batches**:
1. O(E) vs O(n²) complexity
2. Acceptable for bulk processing where some non-determinism is tolerable

---

## Threshold Recommendations

From ArcFace and Chinese Whispers literature:

| Scenario | Similarity Threshold | Rationale |
|----------|---------------------|-----------|
| High confidence auto-assign | 0.92+ | Very unlikely false positive |
| Standard auto-assign | 0.88 | Good balance precision/recall |
| Suggestion tier | 0.80-0.88 | Human review needed |
| Reject | <0.80 | Too risky to suggest |

**Complete-Link Guard settings**:
```python
complete_link_min_floor = 0.80    # Worst rep match must be decent
complete_link_avg_threshold = 0.85 # Average across all reps
```

---

## Integration with AssignmentGate

The key insight from this evaluation is that **clustering algorithms should discover candidates, not assign them**. The `AssignmentGate` handles the final decision:

```python
# GraphDiscovery output
candidates = hdbscan_discover(identities, anchors)
outliers = [i for i in identities if i not in candidates]

# ALL candidates go through the gate
for candidate in candidates:
    decision = gate.evaluate(candidate)
    if decision.outcome == ACCEPT:
        writer.assign(candidate)
    elif decision.outcome == SUGGEST:
        suggestions.create(candidate)
    # REJECT: stays unclustered

# Outliers get their own clusters or become singletons
for outlier in outliers:
    writer.create_singleton_cluster(outlier)
```

This ensures that even HDBSCAN's anchor matching (which currently bypasses guards) flows through the unified validation.

---

## Complexity Comparison

| Algorithm | Time Complexity | Space | Deterministic | Outliers |
|-----------|----------------|-------|---------------|----------|
| Representative | O(n × r) | O(r) | Yes | N/A |
| Chinese Whispers | O(E) | O(n) | No | No |
| HDBSCAN | O(n²) | O(n²) | Yes | Yes |
| AHC (Ward) | O(n³) | O(n²) | Yes | No |
| K-Means | O(nkt) | O(nk) | Mostly | No |

**Where**:
- n = number of identities
- r = total representatives
- E = number of edges (n × k where k = average connections per node)
- k = number of clusters (K-Means)
- t = iterations

---

## Conclusion

### 🚨 Priority 1: Validate the Bug Fix

Before any algorithm changes, verify that the metadata dilution fix resolves the "Cam Grant domination" problem:

1. **Reset the corrupted cluster** — The cluster with 16+ different people must be dissolved
2. **Re-run clustering** — With face-only similarity, clusters should form correctly
3. **Verify thresholds** — 0.88 on face similarity may be too strict or too lenient

### Priority 2: Evaluate Algorithm Needs

With correct similarity computation, many proposed architectural changes may be **unnecessary**:

| Original Problem | Root Cause | Status After Fix |
|-----------------|------------|------------------|
| 20+ people match one cluster | Metadata similarity, not face | ✅ Should be fixed |
| Guards ineffective | Guards checked metadata similarity | ✅ Should work now |
| Complete-link bypassed | Was working, but on wrong data | ✅ Should work now |

### Algorithm Recommendations (Post-Fix)

**Primary algorithm**: HDBSCAN for batches ≤500, with `cluster_selection_epsilon = 1.0 - threshold`

**Fallback**: Chinese Whispers for batches >500

**Discovery-only constraint**: All algorithms output candidates that flow through `AssignmentGate`. No algorithm has the power to directly assign identities to clusters.

**Cold start**: RepresentativeOnlyClustering (deterministic, conservative) for first batch with no existing clusters.

### Deferred: Full Rewrite

The unified `AssignmentGate` architecture is still valuable for **code quality** but may not be **urgent** if the bug fix resolves the clustering issues. Re-evaluate after validation.
