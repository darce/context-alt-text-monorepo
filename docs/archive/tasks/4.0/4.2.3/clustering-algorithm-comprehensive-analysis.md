# Comprehensive Clustering Algorithm Analysis

**Date**: November 25, 2025  
**Author**: Daniel  
**Related Documents**:

- [clustering-pipeline-analysis.md](./clustering-pipeline-analysis.md)
- [improve-suggestion-ux-reduce-false-negatives.md](./improve-suggestion-ux-reduce-false-negatives.md)
- [Chinese Whispers Paper](../../../literature/extracted/recognition/chinese-whispers.txt)
- [Apple ML Research](https://machinelearning.apple.com/research/recognizing-people-photos)

---

## Table of Contents

1. [Questions & Answers](#questions--answers)
   - [Q1: Does FAISS optimize vector lookup speed only?](#q1-does-faiss-optimize-vector-lookup-speed-only)
   - [Q2: Cosine similarity vs Euclidean distance](#q2-cosine-similarity-vs-euclidean-distance)
   - [Q3: Pipeline that increases accuracy as cluster members increase](#q3-pipeline-that-increases-accuracy-as-cluster-members-increase)
   - [Q4: Recompute borderline matches when user confirms new member](#q4-recompute-borderline-matches-when-user-confirms-new-member)
   - [Q5: Recall vs Precision for this project](#q5-recall-vs-precision-for-this-project)
   - [Q6: Why batch clustering after user validation?](#q6-why-batch-clustering-after-user-validation)
   - [Q7: Apple Photos clustering algorithm](#q7-apple-photos-clustering-algorithm)
   - [Q8: Explain the eps parameter](#q8-explain-the-eps-parameter)
   - [Q9: HDBSCAN vs reworked Chinese Whispers](#q9-hdbscan-vs-reworked-chinese-whispers)
2. [Expanding on Option C: Confidence-Weighted Thresholds](#expanding-on-option-c-confidence-weighted-thresholds)
3. [Synthesis & Recommendations](#synthesis--recommendations)

---

## Questions & Answers

### Q1: Does FAISS optimize vector lookup speed only?

**Short Answer**: Yes, primarily. FAISS is an **indexing and search library**, not a clustering algorithm.

**Detailed Explanation**:

FAISS (Facebook AI Similarity Search) is designed to solve the **approximate nearest neighbor (ANN)** problem efficiently. Its core purpose is:

1. **Index high-dimensional vectors** for fast retrieval
2. **Search for k-nearest neighbors** orders of magnitude faster than brute-force
3. **Scale to billions of vectors** using GPU acceleration and quantization

FAISS does include some clustering capabilities (`faiss.Kmeans`, `faiss.Clustering`), but these are:

- Primarily for building IVF (Inverted File) indexes that partition the vector space
- Standard K-means variants, not specialized face clustering algorithms
- Used to speed up search, not to discover natural groupings

**What FAISS could do for our pipeline**:

| Use Case                           | Benefit                                | Current Alternative                 |
| ---------------------------------- | -------------------------------------- | ----------------------------------- |
| Fast nearest neighbor search       | O(log n) vs O(n) lookup                | Brute-force pgvector `<->` operator |
| Building k-NN graph for clustering | Avoid O(n²) pairwise similarity        | Full similarity matrix (`np.dot`)   |
| Incremental index updates          | Add new embeddings without re-indexing | N/A (recompute each batch)          |

**Recommendation**: Use FAISS (or Annoy) to **build a k-NN graph efficiently**, then run clustering (HDBSCAN or Chinese Whispers) on that graph. This decouples indexing speed from clustering quality.

```python
# Example: Build k-NN graph with FAISS
import faiss

index = faiss.IndexFlatIP(512)  # Inner product = cosine similarity for normalized vectors
index.add(embeddings)

# Get k nearest neighbors for each embedding
k = 50
distances, indices = index.search(embeddings, k)

# Build graph: edge exists if neighbor is mutual and distance > threshold
# Then run clustering on this sparse graph
```

---

### Q2: Cosine similarity vs Euclidean distance

**Short Answer**: **Cosine similarity is preferred for face embeddings** because modern face recognition models (ArcFace, CosFace, etc.) are trained to optimize angular margins on the unit hypersphere.

**Why Cosine Works Better for Faces**:

1. **Training Objective Alignment**:

   - ArcFace loss: `L = -log(exp(s·cos(θ_y + m)) / (exp(s·cos(θ_y + m)) + Σ exp(s·cos(θ_j))))`
   - The loss explicitly optimizes **angular separation** between classes
   - Embeddings lie on the surface of a unit hypersphere

2. **Normalization Invariance**:

   - Face embeddings are L2-normalized to unit length
   - For unit vectors: `cosine_similarity = dot_product`
   - Euclidean distance: `||a - b||² = 2(1 - cos(a,b))` for unit vectors
   - **They're mathematically equivalent for normalized vectors**, but cosine is more interpretable (0-1 scale)

3. **Magnitude Independence**:
   - Cosine similarity measures **direction**, not magnitude
   - Face quality variations affect embedding magnitude, not direction
   - Low-confidence detections may have slightly different magnitudes

**The Relationship**:

For L2-normalized embeddings where `||a|| = ||b|| = 1`:

```
euclidean_distance² = ||a - b||² = ||a||² + ||b||² - 2·a·b = 2 - 2·cos(θ) = 2(1 - similarity)

Therefore: similarity = 1 - euclidean_distance²/2
```

**Our Current Implementation**:

```python
# chinese_whispers.py line 102-105
# Compute similarity matrix: S = E . E^T
sim_matrix = np.dot(embeddings, embeddings.T)  # This IS cosine similarity for normalized vectors
```

**Recommendation**: Continue using cosine similarity (or equivalently, dot product on normalized vectors). The conversion to Euclidean for Ward clustering was problematic—removing Ward means we can stay in cosine space throughout.

---

### Q3: Pipeline that increases accuracy as cluster members increase

**Short Answer**: Yes, Apple Photos does this through **canonical exemplars** and **sparse coding**.

**Apple's Approach** (from their ML research):

> "We represent each cluster with a set of canonical exemplars X₀, X₁, ...Xc instead of just using the centroid."

Their pipeline:

1. Store **K canonical exemplars per cluster** (not just one centroid)
2. When matching a new face, solve a **sparse coding problem**:
   ```
   min_x ||y - D·x||² + λ·||x||₁
   ```
   where D is the dictionary of all exemplars
3. Assign to cluster with maximum "energy" in the sparse code

**Why This Improves with Scale**:

- More members → more diverse exemplars → better coverage of pose/lighting variations
- Centroid averaging can cause **drift toward a generic face**
- Exemplars preserve the **full diversity** of the cluster

**Our Current Representatives System**:

We already have something similar with `identity_cluster_representatives`:

```python
# Current: max_reps_per_media = 2
# Representatives are selected for quality and diversity
```

**How to Improve Our System**:

| Current                   | Proposed                                            | Benefit          |
| ------------------------- | --------------------------------------------------- | ---------------- |
| Fixed rep count per media | Adaptive: more reps as cluster grows                | Better coverage  |
| Representatives only      | Representatives + centroids for different use cases | Speed + accuracy |
| Match to single best rep  | Match to all reps, aggregate scores                 | More robust      |

**Proposed Enhancement**:

```python
def compute_cluster_confidence(
    query_embedding: np.ndarray,
    representatives: list[np.ndarray],
) -> float:
    """
    Aggregate match confidence across all representatives.

    More representatives = more opportunities to match = higher potential confidence.
    """
    similarities = [np.dot(query_embedding, rep) for rep in representatives]

    # Top-k aggregation (not just max)
    top_k = sorted(similarities, reverse=True)[:3]

    # Weighted combination: best match matters most, but consistency helps
    return 0.6 * top_k[0] + 0.3 * np.mean(top_k) + 0.1 * np.min(top_k)
```

---

### Q4: Recompute borderline matches when user confirms new member

**Short Answer**: Yes, this is valuable and can be implemented incrementally.

**Concept**: When a user confirms a borderline match, the new member becomes evidence that can "rescue" other borderline candidates.

**Implementation Sketch**:

```python
async def on_member_confirmed(
    cluster_id: UUID,
    new_member: MediaIdentity,
    borderline_candidates: list[IdentitySuggestion],
) -> list[IdentitySuggestion]:
    """
    After user confirms a borderline match, check if other suggestions are now stronger.
    """
    new_embedding = normalize(new_member.embedding)
    promoted = []

    for suggestion in borderline_candidates:
        if suggestion.suggested_cluster_id != cluster_id:
            continue

        candidate_embedding = normalize(suggestion.identity.embedding)

        # Compute similarity to newly confirmed member
        similarity_to_new = np.dot(candidate_embedding, new_embedding)

        # If the candidate is similar to the new member, boost its confidence
        if similarity_to_new > 0.65:
            # Recompute avg_member_similarity with new member included
            new_avg = recompute_member_similarity(
                suggestion.identity,
                cluster_id,
                include_new_member=new_member,
            )

            if new_avg >= 0.68:  # Now passes member validation
                suggestion.confidence_score = compute_confidence(
                    suggestion.representative_similarity,
                    new_avg,
                )
                promoted.append(suggestion)

    return promoted
```

**UX Considerations**:

- After user confirms a match, show "X more suggestions found for this person"
- Prioritize suggestions that are similar to the just-confirmed face
- This creates a **positive feedback loop**: confirming good matches makes the cluster stronger

**When to Trigger Recomputation**:

| Event                     | Recompute Scope                             |
| ------------------------- | ------------------------------------------- |
| User confirms suggestion  | Borderline candidates for same cluster      |
| User merges clusters      | All borderline candidates for both clusters |
| Batch clustering complete | All unassigned identities                   |

---

### Q5: Recall vs Precision for this project

**Short Answer**: **Prefer recall**, but surface uncertainty to the user.

**Industry Consensus**:

From the existing analysis document:

> "Industry prefers recall over precision for face clustering:
>
> - It's easier to split a merged cluster than to find unmatched singletons
> - User corrections are expected and designed for"

**Our Context**:

| Factor                           | Implication                      |
| -------------------------------- | -------------------------------- |
| Alt-text generation              | Wrong name is worse than no name |
| User reviews all suggestions     | High recall doesn't flood users  |
| Singleton clusters are invisible | Low recall = lost opportunities  |
| Merge UI is easy                 | Splitting is also easy           |

**The Nuance**:

This isn't binary. We want:

- **High recall** for clustering (find all potential matches)
- **Clear confidence signals** so users can prioritize
- **Easy correction mechanisms** for mistakes

**Proposed Tiered Approach**:

```
Confidence Tier       | Recall | Precision | User Action
----------------------|--------|-----------|------------------
Auto-accept (>0.75)   | Lower  | High      | None required
Suggestion (0.55-0.75)| Medium | Medium    | Review recommended
Batch cluster (<0.55) | Higher | Lower     | May need cleanup
```

**Concrete Thresholds**:

| Current                                        | Proposed              | Rationale                          |
| ---------------------------------------------- | --------------------- | ---------------------------------- |
| Auto-accept: 0.65+ with 0.68 member validation | Auto-accept: 0.70+    | Fewer false positives in auto mode |
| No suggestion tier                             | Suggestion: 0.55-0.70 | Capture borderline cases           |
| CW threshold: 0.75                             | CW/HDBSCAN: 0.50      | Higher recall in batch mode        |

---

### Q6: Why batch clustering after user validation?

**Short Answer**: User validation provides **ground truth labels** that can improve subsequent clustering.

**The Problem with Current Flow**:

1. New images arrive
2. Batch clustering runs (unsupervised)
3. User corrects mistakes
4. Corrections are siloed—don't improve future batches

**Why Post-Validation Clustering Helps**:

1. **Semi-Supervised Learning**:

   - User-validated clusters become **anchors** with known labels
   - New faces are clustered relative to these anchors
   - Reduces error propagation

2. **Representative Refresh**:

   - After user confirms/rejects, representatives may need updating
   - A post-validation pass can select better representatives from the corrected cluster

3. **Cross-Cluster Reconciliation**:
   - User might merge two clusters that were incorrectly split
   - Post-validation can check if other singletons should join the merged cluster

**Implementation Pattern**:

```python
async def periodic_reconciliation(tenant_id: UUID) -> None:
    """
    Run after user has made corrections. Uses validated clusters as anchors.
    """
    # 1. Get clusters with recent user edits
    validated_clusters = await get_recently_modified_clusters(tenant_id)

    # 2. Get orphan identities (singletons created in last N days)
    orphans = await get_singleton_identities(tenant_id, days=7)

    # 3. For each orphan, try matching against validated cluster representatives
    for orphan in orphans:
        suggestions = await find_suggestions_with_anchors(
            orphan,
            anchor_clusters=validated_clusters,
        )
        if suggestions:
            await create_suggestion(orphan, suggestions[0])

    # 4. Check for clusters that should merge based on new evidence
    await check_cluster_merge_candidates(validated_clusters)
```

**Apple's Approach**:

> "This clustering algorithm runs periodically, typically overnight during device charging"

They do continuous reconciliation, not one-shot batch clustering.

---

### Q7: Apple Photos clustering algorithm

**Summary from Apple ML Research**:

Apple uses a **two-pass agglomerative clustering** approach:

#### Pass 1: Conservative Clustering (Face + Upper Body)

- **Goal**: High precision, many small clusters
- **Inputs**: Face embedding + upper body embedding (for clothing context)
- **Constraint**: Upper body comparisons only within same "moment" (time+location)
- **Distance formula**:
  ```
  D_ij = min(F_ij, α·F_ij + β·T_ij)
  ```
  where F = face distance, T = upper body (torso) distance
- **Threshold**: Very strict—only merge very close matches

#### Pass 2: HAC with Median Linkage (Face Only)

- **Goal**: Increase recall, grow clusters across moment boundaries
- **Inputs**: Face embeddings only
- **Method**: Hierarchical Agglomerative Clustering (HAC)
- **Linkage**: Median distance between cluster members
- **Optimization**: Random sampling when comparison count gets large

#### Identity Assignment (New Faces)

- **Method**: Sparse coding with dictionary of canonical exemplars
- **Representation**: K exemplars per cluster (not just centroid)
- **Formula**: `min_x ||y - D·x||² + λ·||x||₁`
- **Assignment**: Cluster with maximum total "energy" in sparse code

**Key Insights for Our Project**:

| Apple Feature                  | Our Equivalent                | Gap                       |
| ------------------------------ | ----------------------------- | ------------------------- |
| Face + upper body embeddings   | Face embedding only           | Could add body context    |
| Moment-based constraints       | None (no temporal context)    | Could use EXIF timestamps |
| Two-pass clustering            | Single CW pass                | Could add HAC refinement  |
| K canonical exemplars          | Representatives (max 2/media) | Should increase K         |
| Sparse coding for assignment   | Nearest representative match  | Simpler but less robust   |
| Overnight batch reconciliation | On-demand only                | Should add periodic job   |

---

### Q8: Explain the eps parameter

**Short Answer**: `eps` (epsilon) is the **maximum distance between neighbors** in DBSCAN/HDBSCAN.

**DBSCAN's Core Concept**:

A point P is a **core point** if at least `min_samples` points are within `eps` distance.
Clusters are formed by connecting core points that are within `eps` of each other.

**The Problem with Fixed eps**:

From sklearn documentation:

> "eps is crucial to choose appropriately for the data set and distance function and usually cannot be left at the default value."

**Why eps is Hard to Tune for Faces**:

1. **Variable Density**:

   - Some people have many photos (dense cluster)
   - Others have few photos (sparse)
   - One eps doesn't fit both

2. **Quality Variation**:

   - High-quality photos cluster tightly
   - Low-quality photos (blur, occlusion) are farther from cluster center
   - Fixed eps either includes garbage or excludes valid matches

3. **Identity Diversity**:
   - Young child photos vs. older photos of same person
   - Different hairstyles, glasses, expressions
   - Wide eps merges different people; narrow eps fragments same person

**HDBSCAN's Solution**:

> "HDBSCAN can be seen as an extension of DBSCAN...performs DBSCAN\* clustering across all values of ε"

HDBSCAN:

1. Builds a hierarchy at all possible eps values
2. Extracts stable clusters that persist across a range of eps
3. Identifies outliers as points that don't belong to any stable cluster

**Visual Intuition**:

```
DBSCAN with eps=0.3:     DBSCAN with eps=0.5:     HDBSCAN:
    ●●●   ○   ●●            ●●●●●●●                ●●● noise ●●
    ●●●       ●●            ●●●●●●●                ●●●       ●●

(Too strict:             (Too loose:              (Adapts to local density,
 splits clusters)         merges clusters)         marks outliers)
```

**Our Chinese Whispers Equivalent**:

In CW, `edge_threshold` plays a similar role:

```python
# chinese_whispers.py
self.edge_threshold = getattr(settings, "cw_threshold", settings.similarity_threshold + 0.05)
```

Current setting: `cw_threshold = 0.75`

This is essentially saying: "Only connect nodes with >75% similarity." It's a single global threshold with the same problems as DBSCAN's eps.

**Recommendation**: Switch to HDBSCAN which handles varying density automatically, or implement **adaptive edge threshold** for Chinese Whispers based on local neighborhood density.

---

### Q9: HDBSCAN vs reworked Chinese Whispers

**Comparison Matrix**:

| Aspect                | Chinese Whispers           | HDBSCAN                       | Winner  |
| --------------------- | -------------------------- | ----------------------------- | ------- |
| **Time Complexity**   | O(E) per iteration         | O(n²) distance matrix         | CW      |
| **Space Complexity**  | O(V + E)                   | O(n²)                         | CW      |
| **Density Handling**  | Single global threshold    | Automatic adaptation          | HDBSCAN |
| **Outlier Detection** | None (all assigned)        | Explicit label=-1             | HDBSCAN |
| **Determinism**       | Non-deterministic          | Deterministic                 | HDBSCAN |
| **Parameters**        | edge_threshold, iterations | min_cluster_size, min_samples | Similar |
| **Implementation**    | Custom (50 LOC)            | Library (well-tested)         | HDBSCAN |
| **Incremental**       | Can add anchors            | Requires refit                | CW      |

**When to Choose Each**:

**Choose Chinese Whispers if**:

- You have >5000 faces (O(n²) becomes prohibitive)
- You need incremental clustering with anchors
- You're willing to tune edge threshold carefully
- Non-determinism is acceptable

**Choose HDBSCAN if**:

- Batch sizes are moderate (<2000)
- You have varying cluster densities
- You want explicit outlier handling
- You prefer library support over custom code

**Hybrid Approach** (Recommended):

```python
async def cluster_identities(
    identities: list[MediaIdentity],
    anchors: list[MediaIdentity],
    settings: ClusteringSettings,
) -> list[IdentityCluster]:
    """
    Hybrid clustering: HDBSCAN for quality, CW for scale.
    """
    n = len(identities)

    if n <= settings.hdbscan_max_identities:  # e.g., 2000
        # Use HDBSCAN for better quality on small batches
        return await hdbscan_cluster(identities, anchors, settings)
    else:
        # Use Chinese Whispers for scale on large batches
        return await chinese_whispers_cluster(identities, anchors, settings)
```

**Reworked Chinese Whispers Improvements**:

If staying with CW, implement these enhancements:

1. **Mutual k-NN Edge Construction**:

   ```python
   # Only connect if both nodes are in each other's top-k neighbors
   edges = []
   for i in range(n):
       for j in knn_indices[i]:
           if i in knn_indices[j] and similarity[i, j] > threshold:
               edges.append((i, j, similarity[i, j]))
   ```

2. **Adaptive Edge Threshold**:

   ```python
   def adaptive_threshold(node_i, neighbors, global_threshold):
       """Lower threshold for sparse neighborhoods."""
       density = len([n for n in neighbors if similarity[node_i, n] > 0.5])
       if density < 3:  # Sparse neighborhood
           return global_threshold - 0.05
       return global_threshold
   ```

3. **Outlier Detection Post-Processing**:
   ```python
   def detect_outliers(clusters, min_cluster_size=2):
       """Mark small clusters as potential outliers."""
       outliers = []
       valid_clusters = []
       for cluster in clusters:
           if len(cluster.members) < min_cluster_size:
               outliers.extend(cluster.members)
           else:
               valid_clusters.append(cluster)
       return valid_clusters, outliers
   ```

---

## Expanding on Option C: Confidence-Weighted Thresholds

### The Core Idea

From `clustering-pipeline-analysis.md`:

> "The pipeline uses fixed thresholds that don't account for face detection quality"

A high-confidence detection (det_score=0.99, large bbox) should be treated differently than a low-confidence detection (det_score=0.75, small bbox).

### Detection Quality Signals

We have access to these quality indicators:

| Signal            | Source                     | Current Use         |
| ----------------- | -------------------------- | ------------------- |
| `det_score`       | Face detector confidence   | None                |
| `bbox` size       | Pixel area of face crop    | None                |
| `alignment_score` | Landmark alignment quality | None (if available) |
| `blur_score`      | Estimated blur level       | None (if available) |

### Confidence-Weighted Similarity

```python
def confidence_weighted_similarity(
    raw_similarity: float,
    source_det_score: float,
    target_det_score: float,
    source_bbox_area: int,
    target_bbox_area: int,
    min_bbox_area: int = 10000,  # 100x100 pixels
) -> tuple[float, float]:
    """
    Adjust similarity based on detection confidence.

    Returns:
        (adjusted_similarity, confidence_factor)
    """
    # 1. Detection confidence factor
    det_confidence = (source_det_score * target_det_score) ** 0.5

    # 2. Size confidence factor (penalize very small faces)
    source_size_conf = min(1.0, source_bbox_area / min_bbox_area)
    target_size_conf = min(1.0, target_bbox_area / min_bbox_area)
    size_confidence = (source_size_conf * target_size_conf) ** 0.5

    # 3. Combined confidence
    confidence = det_confidence * size_confidence

    # 4. Adjust similarity: low confidence dampens the similarity
    # This prevents low-quality faces from strongly matching
    uncertain_baseline = 0.3  # Minimum similarity for uncertain matches
    adjusted = uncertain_baseline + (raw_similarity - uncertain_baseline) * confidence

    return adjusted, confidence
```

### Adaptive Thresholds

Instead of fixed thresholds, use confidence-based thresholds:

```python
def adaptive_threshold(
    base_threshold: float,
    confidence: float,
    confidence_midpoint: float = 0.85,
    max_adjustment: float = 0.10,
) -> float:
    """
    Adjust threshold based on detection confidence.

    High confidence (0.95+) → threshold reduced (easier to match)
    Low confidence (0.75) → threshold increased (harder to match)
    """
    # Linear interpolation around midpoint
    adjustment = max_adjustment * (confidence - confidence_midpoint) / (1.0 - confidence_midpoint)
    adjustment = np.clip(adjustment, -max_adjustment, max_adjustment)

    return base_threshold - adjustment
```

### Integration with Suggestion Tier

Combining confidence weighting with the suggestion tier from Option D:

```python
class MatchDecision(Enum):
    ACCEPT = "accept"
    SUGGEST = "suggest"
    REJECT = "reject"

def classify_match(
    raw_similarity: float,
    source_det_score: float,
    target_det_score: float,
    settings: ClusteringSettings,
) -> MatchDecision:
    """
    Classify a match decision using confidence-weighted thresholds.
    """
    # 1. Compute confidence factor
    confidence = (source_det_score * target_det_score) ** 0.5

    # 2. Adjust thresholds
    accept_threshold = adaptive_threshold(settings.accept_threshold, confidence)  # e.g., 0.68
    suggest_threshold = adaptive_threshold(settings.suggest_threshold, confidence)  # e.g., 0.55

    # 3. Classify
    if raw_similarity >= accept_threshold:
        return MatchDecision.ACCEPT
    elif raw_similarity >= suggest_threshold:
        return MatchDecision.SUGGEST
    else:
        return MatchDecision.REJECT
```

### Expected Impact

| Scenario                    | Current           | With Confidence Weighting                    |
| --------------------------- | ----------------- | -------------------------------------------- |
| High-quality face, 0.62 sim | Rejected (< 0.65) | Accepted (threshold lowered to 0.60)         |
| Low-quality face, 0.66 sim  | Accepted          | Suggested (threshold raised to 0.70)         |
| Blurry face, 0.63 sim       | Rejected          | Rejected (high threshold for low confidence) |
| Profile face, 0.58 sim      | Rejected          | Suggested (if detected with confidence)      |

### Data Requirements

To implement confidence weighting, we need to store:

1. `det_score` per `MediaIdentity` (already have this in some form?)
2. `bbox` dimensions per identity
3. Optional: alignment quality, blur score

**Migration**: If `det_score` isn't currently stored, need a migration to add it or compute from stored embeddings.

---

## Synthesis & Recommendations

### Immediate Actions (This Sprint)

1. **Implement Suggestion Tier** (Option D from existing analysis):

   - Add `identity_suggestions` table
   - Modify clustering to create suggestions for borderline cases (0.55-0.68)
   - Build basic review UI

2. **Remove Dead Code**:

   - Delete `ward_clustering.py`
   - Remove Ward-related settings
   - Remove centroid fallback path

3. **Adjust Thresholds**:
   - Lower CW edge threshold: 0.75 → 0.65 (higher recall)
   - Add suggestion threshold: 0.55
   - Keep accept threshold: 0.70 (with member validation)

### Short-Term (Next 2 Sprints)

4. **Implement Confidence Weighting** (Option C expansion):

   - Store det_score and bbox with identities
   - Compute confidence factor for each pair
   - Use adaptive thresholds in matching

5. **Improve Representatives**:

   - Increase max reps per cluster (not per media)
   - Select for diversity: farthest-point sampling
   - Aggregate scores across multiple reps

6. **Add Periodic Reconciliation**:
   - Background job to recheck singletons
   - Use validated clusters as anchors
   - Surface new suggestions after user edits

### Medium-Term (This Quarter)

7. **Evaluate HDBSCAN**:

   - Add as alternative clustering backend
   - A/B test against Chinese Whispers on real data
   - Use for smaller batches, CW for scale

8. **Temporal Context** (Apple-inspired):
   - Group images by EXIF timestamp
   - Boost similarity for same-session photos
   - Allow more aggressive clustering within moments

### Long-Term (Next Quarter)

9. **Two-Pass Clustering** (Apple-inspired):

   - Pass 1: Conservative, face + context
   - Pass 2: HAC to grow clusters
   - Continuous background refinement

10. **User Feedback Loop**:
    - Track suggestion acceptance rates
    - Auto-tune thresholds per tenant
    - Learn from corrections

### Threshold Simplification Summary

| Current (5 thresholds)     | Proposed (3 thresholds)    |
| -------------------------- | -------------------------- |
| similarity_threshold: 0.65 | accept_threshold: 0.70     |
| borderline_upper: 0.70     | suggest_threshold: 0.55    |
| member_validation: 0.68    | clustering_threshold: 0.50 |
| centroid_match: 0.73       | (removed)                  |
| cw_threshold: 0.75         | (absorbed into clustering) |

### Architecture Evolution

```
Current Pipeline:
  New Identity
       │
       ▼
  ┌─────────────┐     ┌──────────────┐     ┌────────────┐
  │ Rep Match   │────▶│ Validation   │────▶│ CW Batch   │
  │ (threshold) │     │ (3 thresholds│     │ Cluster    │
  └─────────────┘     └──────────────┘     └────────────┘
       │                    │                    │
       ▼                    ▼                    ▼
    Accept               Reject              New Cluster


Proposed Pipeline:
  New Identity
       │
       ▼
  ┌─────────────┐
  │ Confidence- │
  │ Weighted    │
  │ Rep Match   │
  └─────────────┘
       │
       ├── High (>0.70): Accept
       │
       ├── Medium (0.55-0.70): Suggest ──▶ User Review
       │
       └── Low (<0.55): ──▶ HDBSCAN/CW Batch Cluster
                                  │
                                  ├── Cluster Found: Suggest
                                  │
                                  └── Outlier: Singleton + Watch
```

---

## Appendix: Algorithm Complexity Comparison

| Algorithm            | Time                          | Space    | Pros                                | Cons                                   |
| -------------------- | ----------------------------- | -------- | ----------------------------------- | -------------------------------------- |
| Chinese Whispers     | O(E × iterations)             | O(V + E) | Fast, scalable                      | Non-deterministic, threshold-sensitive |
| HDBSCAN              | O(n²) or O(n log n) with tree | O(n²)    | Handles density variation, outliers | Slower, memory-heavy                   |
| Agglomerative (Ward) | O(n³) or O(n² log n)          | O(n²)    | Deterministic, hierarchical         | Slow, threshold-sensitive              |
| DBSCAN               | O(n log n) with index         | O(n)     | Fast, outliers                      | eps-sensitive                          |
| K-means              | O(n × k × iterations)         | O(n + k) | Very fast                           | Need to specify k                      |

For our use case (hundreds to low thousands of faces per batch), **HDBSCAN is viable and preferred** for quality. For scale (5000+), **Chinese Whispers with improvements** remains necessary.

---

## Additional Questions & Clarifications

### Q10: What is Sparse Coding?

**Short Answer**: Sparse coding is a signal representation technique where an input is expressed as a **sparse linear combination** of basis vectors (dictionary elements).

**Mathematical Formulation**:

Given:

- Input vector `y` (e.g., a face embedding)
- Dictionary `D` = [d₁, d₂, ..., dₘ] (collection of exemplar embeddings)

Find sparse code `x` that minimizes:

```
min_x ||y - D·x||² + λ·||x||₁
```

Where:

- `||y - D·x||²` = reconstruction error (how well the dictionary reconstructs the input)
- `||x||₁` = L1 norm (encourages sparsity—most coefficients are zero)
- `λ` = regularization weight (controls sparsity vs. reconstruction)

**Why "Sparse"?**

The L1 penalty forces most coefficients in `x` to be exactly zero. Only a few dictionary elements are "active" for any given input.

**Apple's Application to Face Recognition**:

Instead of nearest-neighbor (which uses only 1 exemplar), sparse coding:

1. Represents each face as a weighted combination of K exemplars
2. The "energy" (sum of |x_i|) per cluster determines assignment
3. More robust because it considers multiple exemplars simultaneously

**Simplified Alternative for Our Pipeline**:

We don't need full sparse coding. A simpler approximation:

```python
def soft_assignment_score(query: np.ndarray, exemplars: list[np.ndarray]) -> float:
    """
    Approximate sparse coding with top-k weighted average.
    More robust than single nearest-neighbor.
    """
    similarities = [np.dot(query, e) for e in exemplars]
    top_k = sorted(similarities, reverse=True)[:3]

    # Exponential weighting emphasizes best matches (similar to sparse coding behavior)
    weights = np.exp(np.array(top_k) * 5)  # Temperature scaling
    weights /= weights.sum()

    return float(np.dot(weights, top_k))
```

---

### Q11: Why Are Weights Hard-Coded? Should They Be Configurable?

**The Hard-Coded Values in Question**:

```python
# Aggregate confidence calculation
return 0.6 * top_k[0] + 0.3 * np.mean(top_k) + 0.1 * np.min(top_k)

# Similarity threshold for recomputation
if similarity_to_new > 0.65:
    if new_avg >= 0.68:  # Member validation
```

**Why They're Currently Hard-Coded**:

1. **Lack of empirical data**: No labeled dataset to tune against
2. **Simplicity during development**: Easier to iterate without config overhead
3. **Reasonable defaults**: Values chosen based on industry norms (0.6-0.7 typical for face similarity)

**Benefits of Making Them Configurable**:

| Benefit            | Explanation                                                      |
| ------------------ | ---------------------------------------------------------------- |
| Per-tenant tuning  | Different photo collections have different quality distributions |
| A/B testing        | Compare configurations without code changes                      |
| Runtime adjustment | React to observed acceptance/rejection rates                     |
| Transparency       | Makes assumptions explicit rather than buried in code            |

**Recommended Configuration Structure**:

```python
@dataclass
class ClusteringSettings:
    # Existing thresholds
    similarity_threshold: float = 0.65
    member_validation_threshold: float = 0.68
    cw_threshold: float = 0.75

    # NEW: Aggregation weights (should sum to 1.0)
    agg_weight_best: float = 0.6      # Weight for best match
    agg_weight_mean: float = 0.3      # Weight for mean of top-k
    agg_weight_min: float = 0.1       # Weight for minimum of top-k

    # NEW: Recomputation triggers
    recompute_similarity_threshold: float = 0.65  # Min similarity to trigger recompute

    # NEW: Auto-tuning bounds
    auto_tune_enabled: bool = False
    threshold_min: float = 0.50       # Never go below this
    threshold_max: float = 0.80       # Never go above this
```

**Implementation**:

```python
def compute_cluster_confidence(
    query_embedding: np.ndarray,
    representatives: list[np.ndarray],
    settings: ClusteringSettings,
) -> float:
    similarities = [np.dot(query_embedding, rep) for rep in representatives]
    top_k = sorted(similarities, reverse=True)[:3]

    # Use configurable weights
    return (
        settings.agg_weight_best * top_k[0] +
        settings.agg_weight_mean * np.mean(top_k) +
        settings.agg_weight_min * np.min(top_k)
    )
```

**Recommendation**: Move to config for the next sprint. Hard-coded is acceptable for initial implementation, but config enables data-driven tuning.

---

### Q12: What is "Recall" in This Context?

**Definition**:

**Recall** = (True Positives) / (True Positives + False Negatives)

In clustering terms:

- **True Positive**: Two faces of the same person correctly placed in the same cluster
- **False Negative**: Two faces of the same person incorrectly placed in different clusters

**High Recall** means: "We found most of the matches" (few missed same-person pairs)
**Low Recall** means: "We missed many matches" (many same-person pairs split across clusters)

**Recall vs. Precision Trade-off**:

| Metric        | Definition                          | High means...      | Risk if too high                |
| ------------- | ----------------------------------- | ------------------ | ------------------------------- |
| **Recall**    | Found matches / All true matches    | Few missed matches | False positives (wrong merges)  |
| **Precision** | Found matches / All claimed matches | Few wrong matches  | False negatives (missed merges) |

**Visual Example**:

```
Ground Truth: Person A has 10 photos

High Recall, Low Precision:        High Precision, Low Recall:
┌─────────────────────┐            ┌─────┐ ┌─────┐ ┌─────┐
│  A A A A A A A A A  │            │ A A │ │ A A │ │ A A │
│  A B B              │ (merged B) │     │ │     │ │     │
└─────────────────────┘            └─────┘ └─────┘ └─────┘
Recall: 100% (all A found)          Recall: 60% (4 clusters)
Precision: 77% (2 B's wrong)        Precision: 100% (no wrong merges)
```

**Why We Prefer Higher Recall**:

1. **Splitting is easier than merging**: User can easily split one cluster into two
2. **Singletons are invisible**: Users don't notice missed matches; they do notice wrong merges
3. **User review catches false positives**: Suggestion tier surfaces uncertain matches

---

### Q13: Practical Continuous Reconciliation (Not Overnight Cron)

**The Problem with Overnight Crons**:

- User uploads images → clusters created → waits 24 hours for reconciliation
- Poor UX for interactive workflows
- Doesn't leverage user validation immediately

**In-Session Async Reconciliation**:

Instead of scheduled jobs, trigger reconciliation **reactively** based on events:

```python
class ReconciliationTriggers(Enum):
    USER_CONFIRMS_SUGGESTION = "user_confirms"
    USER_MERGES_CLUSTERS = "user_merges"
    BATCH_CLUSTERING_COMPLETE = "batch_complete"
    IDLE_TIMEOUT = "idle"  # User hasn't interacted for N seconds

async def maybe_reconcile(
    tenant_id: UUID,
    trigger: ReconciliationTriggers,
    context: dict,
) -> None:
    """
    Lightweight reconciliation triggered by events, not cron.
    """
    if trigger == ReconciliationTriggers.USER_CONFIRMS_SUGGESTION:
        # Fast path: only check borderline candidates for affected cluster
        await reconcile_cluster_neighbors(
            tenant_id,
            cluster_id=context["cluster_id"],
            new_member_id=context["new_member_id"],
        )

    elif trigger == ReconciliationTriggers.USER_MERGES_CLUSTERS:
        # Medium path: check singletons against merged cluster
        await reconcile_singletons_against_cluster(
            tenant_id,
            cluster_id=context["merged_cluster_id"],
            max_singletons=50,
        )

    elif trigger == ReconciliationTriggers.BATCH_CLUSTERING_COMPLETE:
        # Enqueue background task (doesn't block)
        await enqueue_background_reconciliation(
            tenant_id,
            scope="recent_singletons",
            priority="low",
        )
```

**Implementation with Async Workers**:

```python
# Using FastAPI BackgroundTasks (runs in same process)
from fastapi import BackgroundTasks

@router.post("/clusters/{cluster_id}/confirm")
async def confirm_suggestion(
    cluster_id: UUID,
    suggestion_id: UUID,
    background_tasks: BackgroundTasks,
):
    # 1. Confirm the suggestion (synchronous)
    await confirm_identity_to_cluster(cluster_id, suggestion_id)

    # 2. Queue reconciliation (runs after response sent)
    background_tasks.add_task(
        reconcile_cluster_neighbors,
        tenant_id=current_tenant_id,
        cluster_id=cluster_id,
    )

    return {"status": "confirmed", "reconciliation": "queued"}
```

**Lightweight Scoped Reconciliation**:

```python
async def reconcile_cluster_neighbors(
    tenant_id: UUID,
    cluster_id: UUID,
    new_member_id: UUID,
) -> int:
    """
    Fast reconciliation: only check suggestions related to this cluster.
    Runs in <1s for typical cases.
    """
    # 1. Get the newly confirmed member's embedding
    new_member = await get_identity(new_member_id)
    new_embedding = normalize(new_member.embedding)

    # 2. Get pending suggestions for this cluster
    pending = await get_pending_suggestions(
        tenant_id,
        suggested_cluster_id=cluster_id,
    )

    promoted_count = 0
    for suggestion in pending:
        candidate_embedding = normalize(suggestion.identity.embedding)

        # Check similarity to new member
        sim_to_new = np.dot(candidate_embedding, new_embedding)

        if sim_to_new > 0.60:  # Worth recomputing
            # Recompute member validation with new member included
            new_avg = await recompute_member_similarity(
                suggestion.identity_id,
                cluster_id,
            )

            if new_avg >= 0.65:  # Now passes
                await promote_suggestion(suggestion.id)
                promoted_count += 1

    logger.info(
        "Reconciled cluster %s: promoted %d suggestions",
        cluster_id, promoted_count
    )
    return promoted_count
```

**Key Principles**:

1. **Event-driven, not scheduled**: React to user actions
2. **Scoped, not global**: Only reconcile affected clusters
3. **Non-blocking**: Use BackgroundTasks or async workers
4. **Bounded**: Limit scope (e.g., max 50 singletons per reconciliation)

---

### Q14: Using the Full 1024D Vector - InsightFace Metrics & Body Embeddings

**Current Situation**:

- Vector size: 1024D
- Face embedding: 512D (from InsightFace)
- Remaining 512D: Currently unused or padding

**What InsightFace Provides**:

InsightFace's `FaceAnalysis` class returns multiple attributes per face:

| Attribute        | Type        | Description                          |
| ---------------- | ----------- | ------------------------------------ |
| `embedding`      | 512D float  | Face identity embedding              |
| `det_score`      | float       | Detection confidence (0-1)           |
| `bbox`           | 4 floats    | Bounding box [x1, y1, x2, y2]        |
| `kps`            | 5×2 floats  | Facial landmarks (eyes, nose, mouth) |
| `landmark_3d_68` | 68×2 floats | 3D facial landmarks (if enabled)     |
| `pose`           | 3 floats    | Head pose [pitch, yaw, roll]         |
| `gender`         | int         | Gender prediction (0/1)              |
| `age`            | int         | Age estimation                       |

**Proposed 1024D Layout**:

```python
def build_extended_embedding(face) -> np.ndarray:
    """
    Build 1024D embedding with face + context features.
    """
    embedding = np.zeros(1024, dtype=np.float32)

    # Bytes 0-511: Face identity (L2 normalized)
    embedding[0:512] = normalize(face.embedding)

    # Bytes 512-514: Head pose (normalized to [-1, 1])
    if hasattr(face, 'pose'):
        embedding[512] = face.pose[0] / 90.0  # pitch
        embedding[513] = face.pose[1] / 90.0  # yaw
        embedding[514] = face.pose[2] / 90.0  # roll

    # Bytes 515-516: Demographics (normalized)
    if hasattr(face, 'age'):
        embedding[515] = face.age / 100.0  # age (0-1)
    if hasattr(face, 'gender'):
        embedding[516] = float(face.gender)  # 0 or 1

    # Bytes 517-520: Detection quality
    embedding[517] = face.det_score
    bbox_area = (face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1])
    embedding[518] = min(1.0, bbox_area / 50000)  # Normalized bbox area

    # Bytes 519-522: Landmark quality (variance indicates alignment)
    if hasattr(face, 'kps'):
        kps_flat = face.kps.flatten()
        embedding[519] = np.std(kps_flat) / 100  # Landmark spread

    # Bytes 523-1023: Reserved for future use (body embedding, etc.)
    # Currently zero-padded

    return embedding
```

**Adding Body Embeddings (Apple-Style)**:

InsightFace doesn't provide body embeddings, but we could add them:

**Option A: Use a Separate Body Detector**

```python
# Using a person re-identification model
from torchreid.utils import FeatureExtractor

body_extractor = FeatureExtractor(
    model_name='osnet_x1_0',
    model_path='path/to/model.pth',
)

def extract_body_embedding(image, face_bbox) -> np.ndarray:
    """
    Extract body embedding for the person associated with a face.
    """
    # Estimate upper body region from face bbox
    face_center_x = (face_bbox[0] + face_bbox[2]) / 2
    face_height = face_bbox[3] - face_bbox[1]

    # Upper body is roughly 3x face height, centered below face
    body_bbox = [
        face_center_x - face_height,      # x1
        face_bbox[1],                      # y1 (top of face)
        face_center_x + face_height,      # x2
        face_bbox[3] + face_height * 2,   # y2 (2x face height below)
    ]

    body_crop = crop_image(image, body_bbox)
    body_embedding = body_extractor(body_crop)  # Returns 512D

    return normalize(body_embedding)
```

**Option B: Clothing Color Histogram (Simpler)**

```python
def extract_clothing_features(image, face_bbox) -> np.ndarray:
    """
    Extract color histogram from estimated clothing region.
    Lightweight alternative to body embedding model.
    """
    # Estimate torso region below face
    face_height = face_bbox[3] - face_bbox[1]
    torso_bbox = [
        face_bbox[0] - face_height * 0.5,
        face_bbox[3],  # Start below face
        face_bbox[2] + face_height * 0.5,
        face_bbox[3] + face_height * 2,
    ]

    torso_crop = crop_image(image, torso_bbox)

    # HSV histogram (more invariant to lighting than RGB)
    hsv = cv2.cvtColor(torso_crop, cv2.COLOR_BGR2HSV)
    hist_h = cv2.calcHist([hsv], [0], None, [32], [0, 180])
    hist_s = cv2.calcHist([hsv], [1], None, [32], [0, 256])
    hist_v = cv2.calcHist([hsv], [2], None, [32], [0, 256])

    # Concatenate and normalize
    features = np.concatenate([hist_h, hist_s, hist_v]).flatten()
    return normalize(features)  # 96D
```

**Recommendation**:

1. **Immediate**: Store det_score, bbox_area, pose in extended vector
2. **Short-term**: Add clothing color histogram (simple, no new model)
3. **Long-term**: Evaluate person re-id model if clothing features prove useful

---

### Q15: Inferring Same-Session from Color Histograms (No EXIF)

**The Problem**:

- No EXIF timestamps available
- Can't use temporal proximity for clustering
- Need alternative "moment" detection

**Color Histogram as Session Proxy**:

Images taken in the same session often share:

- Similar lighting conditions (indoor/outdoor, time of day)
- Similar background colors
- Similar color cast (white balance)

```python
def extract_scene_signature(image: np.ndarray) -> np.ndarray:
    """
    Extract scene-level color features for session detection.
    """
    # Downsample for speed
    small = cv2.resize(image, (64, 64))
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)

    features = []

    # 1. Global color histogram (HSV)
    for channel, bins, range_max in [(0, 16, 180), (1, 8, 256), (2, 8, 256)]:
        hist = cv2.calcHist([hsv], [channel], None, [bins], [0, range_max])
        features.append(hist.flatten())

    # 2. Dominant colors (k-means on pixels)
    pixels = small.reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, labels, centers = cv2.kmeans(pixels, 5, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    features.append(centers.flatten())  # 5 dominant colors × 3 channels = 15D

    # 3. Color temperature proxy (blue-yellow ratio)
    b, g, r = cv2.split(small)
    temp_ratio = np.mean(b) / (np.mean(r) + 1e-6)
    features.append([temp_ratio])

    # 4. Brightness distribution
    features.append([np.mean(hsv[:,:,2]), np.std(hsv[:,:,2])])

    return normalize(np.concatenate(features))


def compute_session_similarity(sig1: np.ndarray, sig2: np.ndarray) -> float:
    """Compare scene signatures."""
    return float(np.dot(sig1, sig2))


def group_by_inferred_session(
    identities: list[MediaIdentity],
    session_threshold: float = 0.85,
) -> list[list[MediaIdentity]]:
    """
    Group identities by inferred photo session using scene similarity.
    """
    if not identities:
        return []

    # Extract scene signatures
    signatures = []
    for identity in identities:
        image = load_image(identity.media_url)
        signatures.append(extract_scene_signature(image))

    # Cluster by scene similarity (simple greedy approach)
    sessions = []
    assigned = set()

    for i, identity in enumerate(identities):
        if i in assigned:
            continue

        session = [identity]
        assigned.add(i)

        for j in range(i + 1, len(identities)):
            if j in assigned:
                continue

            sim = compute_session_similarity(signatures[i], signatures[j])
            if sim >= session_threshold:
                session.append(identities[j])
                assigned.add(j)

        sessions.append(session)

    return sessions
```

**Using Session Info for Clustering**:

```python
async def cluster_with_session_boost(
    identities: list[MediaIdentity],
    settings: ClusteringSettings,
) -> list[IdentityCluster]:
    """
    Boost similarity for faces in same inferred session.
    """
    # 1. Group by session
    sessions = group_by_inferred_session(identities)

    # 2. Build similarity matrix with session boost
    n = len(identities)
    identity_to_session = {}
    for session_idx, session in enumerate(sessions):
        for identity in session:
            identity_to_session[identity.id] = session_idx

    # 3. Compute pairwise similarities with boost
    embeddings = np.array([normalize(i.embedding[:512]) for i in identities])
    base_sim = np.dot(embeddings, embeddings.T)

    # Apply session boost
    SESSION_BOOST = 0.05  # Add 5% to same-session pairs
    for i in range(n):
        for j in range(i + 1, n):
            if identity_to_session[identities[i].id] == identity_to_session[identities[j].id]:
                base_sim[i, j] += SESSION_BOOST
                base_sim[j, i] += SESSION_BOOST

    # 4. Cluster with boosted similarity
    return await chinese_whispers_cluster(identities, base_sim, settings)
```

**Limitations**:

- Same location, different sessions → false positive boost
- Different locations, same lighting → might not detect session
- Computationally heavier than EXIF lookup

**Recommendation**: Implement as optional feature, disabled by default until validated.

---

### Q16: HDBSCAN vs Chinese Whispers - Which Yields Fewer Singletons?

**Short Answer**: **HDBSCAN typically produces fewer singletons** because of its explicit outlier handling and density-based approach.

**Why Chinese Whispers Creates More Singletons**:

1. **Hard threshold**: If no edges above threshold, node becomes singleton
2. **No transitivity exploration**: Doesn't consider indirect connections
3. **Random initialization**: Some nodes may never connect

**Why HDBSCAN Creates Fewer Singletons**:

1. **Density estimation**: Considers local neighborhood density
2. **Hierarchical approach**: Can find clusters at multiple scales
3. **Explicit outlier detection**: Labels true outliers as -1, rest get clustered

**Empirical Comparison** (typical results):

| Scenario             | Chinese Whispers  | HDBSCAN          |
| -------------------- | ----------------- | ---------------- |
| 100 faces, 10 people | 15-25 singletons  | 5-10 singletons  |
| 500 faces, 50 people | 80-120 singletons | 30-50 singletons |
| Varied quality       | More singletons   | Fewer singletons |

**The Trade-off**:

| Metric          | Chinese Whispers        | HDBSCAN                   |
| --------------- | ----------------------- | ------------------------- |
| Singletons      | More (strict threshold) | Fewer (density-adaptive)  |
| False positives | Fewer                   | More (aggressive merging) |
| Speed           | Faster O(E)             | Slower O(n²)              |
| Determinism     | Non-deterministic       | Deterministic             |

**Recommendation for Fewer Singletons**:

Use HDBSCAN with these settings:

```python
import hdbscan

clusterer = hdbscan.HDBSCAN(
    min_cluster_size=2,        # Allow pairs
    min_samples=1,             # Sensitive to small clusters
    cluster_selection_epsilon=0.1,  # Allow slightly looser clusters
    metric='precomputed',
)
```

---

### Q17: Compressed Dev Timeline - Skip Option D if Option C Superior?

**Assessment**:

| Aspect                | Option C (Confidence Weighting)  | Option D (Suggestion Tier) |
| --------------------- | -------------------------------- | -------------------------- |
| Implementation effort | Medium (modify thresholds)       | High (new table, UI, API)  |
| User value            | Implicit (better auto-decisions) | Explicit (user review)     |
| Correctness           | Improves accuracy                | Surfaces uncertainty       |
| Dependency            | None                             | Requires frontend work     |

**Recommendation**: **Skip Option D for now, implement Option C first**.

**Rationale**:

1. Option C improves clustering quality **silently**—no frontend changes needed
2. Option D requires database schema, API endpoints, and frontend UI
3. If Option C sufficiently reduces false negatives, Option D may be unnecessary
4. Option D can be added later if users still report issues

**Compressed Implementation Plan**:

```
Week 1: Option C (Confidence Weighting)
├── Store det_score and bbox with identities
├── Implement adaptive_threshold()
├── Integrate into representative matching
└── Validate: measure singleton reduction

Week 2: Two-Pass Clustering Scaffold
├── Refactor pipeline for pass 1 (conservative) / pass 2 (HAC)
├── Implement basic HAC pass on representatives
└── A/B test against single-pass CW

Week 3: Hybrid CW + HDBSCAN
├── CW for bulk, HDBSCAN for outliers
├── Tune thresholds based on Week 1-2 data
└── Deploy and monitor
```

---

### Q18: Scaffolding Two-Pass Clustering - Is Current Pipeline Already 2-Stage?

**Current Pipeline Analysis**:

Yes, the current pipeline is already 2-stage, but **not in the Apple sense**:

```
Current 2-Stage:
Stage 1: Representative Matching (assign to existing clusters)
Stage 2: Chinese Whispers (cluster remaining)

Apple's 2-Pass:
Pass 1: Conservative clustering (face + body, same moment)
Pass 2: HAC to grow clusters (face only, across moments)
```

**Key Difference**:

- **Our Stage 2**: Creates new clusters from unassigned faces
- **Apple's Pass 2**: Merges existing clusters more aggressively

**Scaffolding Apple-Style Two-Pass**:

```python
async def two_pass_clustering(
    identities: list[MediaIdentity],
    settings: ClusteringSettings,
) -> list[IdentityCluster]:
    """
    Apple-inspired two-pass clustering.

    Pass 1: Conservative (high precision)
    Pass 2: HAC growth (high recall)
    """
    # PASS 1: Conservative clustering
    # Use strict threshold, creates many small clusters
    pass1_settings = replace(settings,
        similarity_threshold=0.75,  # Very strict
        cw_threshold=0.80,
    )

    pass1_clusters = await chinese_whispers_cluster(
        identities,
        settings=pass1_settings,
    )

    logger.info(f"Pass 1: Created {len(pass1_clusters)} clusters")

    # PASS 2: HAC to merge similar clusters
    if len(pass1_clusters) > 1:
        # Compute cluster representatives/centroids
        cluster_reps = []
        for cluster in pass1_clusters:
            members = await get_cluster_members(cluster.id)
            embeddings = [normalize(m.embedding[:512]) for m in members]
            centroid = normalize(np.mean(embeddings, axis=0))
            cluster_reps.append((cluster, centroid))

        # Build similarity matrix between clusters
        n = len(cluster_reps)
        cluster_sim = np.zeros((n, n))
        for i in range(n):
            for j in range(i + 1, n):
                sim = np.dot(cluster_reps[i][1], cluster_reps[j][1])
                cluster_sim[i, j] = sim
                cluster_sim[j, i] = sim

        # HAC on clusters (merge similar ones)
        from scipy.cluster.hierarchy import linkage, fcluster

        # Convert similarity to distance
        distance_matrix = 1 - cluster_sim
        condensed = squareform(distance_matrix)

        Z = linkage(condensed, method='average')  # or 'median' like Apple

        # Cut tree at merge threshold
        merge_threshold = 1 - settings.similarity_threshold  # e.g., 0.35
        final_labels = fcluster(Z, t=merge_threshold, criterion='distance')

        # Merge clusters with same label
        merged_clusters = await merge_clusters_by_labels(
            pass1_clusters,
            final_labels,
        )

        logger.info(
            f"Pass 2: Merged {len(pass1_clusters)} → {len(merged_clusters)} clusters"
        )
        return merged_clusters

    return pass1_clusters
```

**Integration with Current Pipeline**:

```python
async def cluster_identities_hybrid(
    identities: list[MediaIdentity],
    settings: ClusteringSettings,
) -> list[IdentityCluster]:
    """
    Full hybrid pipeline with two-pass clustering.
    """
    # Stage 1: Representative matching (existing clusters)
    existing_clusters = await get_existing_clusters(tenant_id)
    if existing_clusters:
        assigned, remaining = await stage1_representative_matching(
            identities,
            existing_clusters,
            settings,
        )
    else:
        remaining = identities

    # Stage 2: Two-pass clustering (new clusters)
    if remaining:
        new_clusters = await two_pass_clustering(remaining, settings)
    else:
        new_clusters = []

    return new_clusters
```

---

### Q19: Chinese Whispers on Bulk + HDBSCAN on Outliers

**Short Answer**: Yes, this is a valid hybrid approach and won't confuse clusters.

**Why It Works**:

1. CW processes the bulk quickly, creating most clusters
2. HDBSCAN only runs on the "leftover" outliers
3. Outliers are then either: assigned to existing clusters, or form new small clusters

**Implementation**:

```python
async def hybrid_cw_hdbscan_clustering(
    identities: list[MediaIdentity],
    settings: ClusteringSettings,
) -> list[IdentityCluster]:
    """
    Chinese Whispers for bulk, HDBSCAN for outliers.
    """
    # Step 1: Run Chinese Whispers
    cw_clusters = await chinese_whispers_cluster(identities, settings)

    # Identify singletons (outliers from CW)
    all_clusters = []
    outliers = []

    for cluster in cw_clusters:
        members = await get_cluster_members(cluster.id)
        if len(members) == 1:
            outliers.append(members[0])
        else:
            all_clusters.append(cluster)

    logger.info(
        f"CW produced {len(all_clusters)} clusters + {len(outliers)} singletons"
    )

    if len(outliers) < 2:
        # Not enough outliers for HDBSCAN
        return cw_clusters

    # Step 2: Run HDBSCAN on outliers
    outlier_embeddings = np.array([
        normalize(o.embedding[:512]) for o in outliers
    ])

    # Include existing cluster centroids as anchors
    anchor_centroids = []
    for cluster in all_clusters:
        centroid = await get_cluster_centroid(cluster.id)
        anchor_centroids.append(centroid)

    if anchor_centroids:
        # Combine outliers with anchors for context
        all_embeddings = np.vstack([
            outlier_embeddings,
            np.array(anchor_centroids)
        ])
        n_outliers = len(outliers)
    else:
        all_embeddings = outlier_embeddings
        n_outliers = len(outliers)

    # HDBSCAN clustering
    distance_matrix = 1 - np.dot(all_embeddings, all_embeddings.T)

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=2,
        min_samples=1,
        metric='precomputed',
    )
    labels = clusterer.fit_predict(distance_matrix)

    # Process outlier labels (first n_outliers entries)
    outlier_labels = labels[:n_outliers]

    new_clusters_created = 0
    assigned_to_existing = 0
    still_outliers = 0

    # Group outliers by their new labels
    label_groups = {}
    for i, label in enumerate(outlier_labels):
        if label == -1:
            still_outliers += 1
            continue  # Still an outlier

        if label >= n_outliers:
            # Assigned to an anchor cluster
            anchor_idx = label - n_outliers
            if anchor_idx < len(all_clusters):
                await add_to_cluster(all_clusters[anchor_idx].id, [outliers[i]])
                assigned_to_existing += 1
        else:
            # New cluster among outliers
            if label not in label_groups:
                label_groups[label] = []
            label_groups[label].append(outliers[i])

    # Create new clusters from grouped outliers
    for label, members in label_groups.items():
        if len(members) >= 2:
            new_cluster = await create_cluster(members)
            all_clusters.append(new_cluster)
            new_clusters_created += 1

    logger.info(
        f"HDBSCAN on outliers: {new_clusters_created} new clusters, "
        f"{assigned_to_existing} assigned to existing, "
        f"{still_outliers} remain singletons"
    )

    return all_clusters
```

**Expected Benefits**:

- Faster than running HDBSCAN on everything
- HDBSCAN's density handling helps outliers find homes
- Existing clusters provide anchoring context

---

### Q20: Where Does HAC Fit in This Pipeline?

**HAC (Hierarchical Agglomerative Clustering) Roles**:

| Use Case                   | When to Use              | Why                             |
| -------------------------- | ------------------------ | ------------------------------- |
| **Pass 2 cluster merging** | After initial clustering | Merge over-fragmented clusters  |
| **Offline reconciliation** | Periodic cleanup         | Find clusters that should merge |
| **Quality validation**     | After clustering         | Verify cluster cohesion         |

**HAC is NOT suitable for**:

- Primary face clustering (O(n³) too slow)
- Real-time incremental updates

**Integration Points**:

```
Current Pipeline + HAC:

┌─────────────────────────────────────────────────────┐
│  NEW FACES                                          │
│       │                                             │
│       ▼                                             │
│  ┌─────────────┐                                    │
│  │ Stage 1:    │                                    │
│  │ Rep Match   │──────────────────┐                 │
│  └─────────────┘                  │                 │
│       │ (unassigned)              │ (assigned)      │
│       ▼                           ▼                 │
│  ┌─────────────┐           ┌──────────────┐        │
│  │ Stage 2:    │           │ Update       │        │
│  │ CW Cluster  │           │ Representatives│      │
│  └─────────────┘           └──────────────┘        │
│       │                                             │
│       ▼ (new clusters)                              │
│  ┌─────────────┐                                    │
│  │ Pass 2:     │  ◄── HAC fits here                │
│  │ HAC Merge   │      (merge fragmented clusters)  │
│  └─────────────┘                                    │
│       │                                             │
│       ▼                                             │
│  ┌─────────────┐                                    │
│  │ HDBSCAN on  │  (optional outlier rescue)        │
│  │ Singletons  │                                    │
│  └─────────────┘                                    │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**HAC Implementation for Cluster Merging**:

```python
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform

async def hac_merge_pass(
    clusters: list[IdentityCluster],
    merge_threshold: float = 0.65,
) -> list[IdentityCluster]:
    """
    HAC pass to merge similar clusters.
    Uses median linkage (like Apple).
    """
    if len(clusters) <= 1:
        return clusters

    # Compute cluster centroids
    centroids = []
    for cluster in clusters:
        centroid = await get_cluster_centroid(cluster.id)
        centroids.append(centroid)

    centroids = np.array(centroids)

    # Similarity matrix
    sim_matrix = np.dot(centroids, centroids.T)

    # Convert to distance matrix
    dist_matrix = 1 - sim_matrix
    np.fill_diagonal(dist_matrix, 0)  # Self-distance = 0

    # Condensed distance matrix for scipy
    condensed = squareform(dist_matrix)

    # HAC with median linkage
    Z = linkage(condensed, method='median')

    # Cut tree at threshold
    distance_threshold = 1 - merge_threshold
    labels = fcluster(Z, t=distance_threshold, criterion='distance')

    # Merge clusters with same label
    merge_groups = {}
    for i, label in enumerate(labels):
        if label not in merge_groups:
            merge_groups[label] = []
        merge_groups[label].append(clusters[i])

    merged_clusters = []
    for label, group in merge_groups.items():
        if len(group) == 1:
            merged_clusters.append(group[0])
        else:
            # Merge multiple clusters into one
            merged = await merge_cluster_group(group)
            merged_clusters.append(merged)

    return merged_clusters
```

---

### Q21: How Can User Feedback Auto-Tune Thresholds?

**Feedback Signals Available**:

| Action                    | What It Tells Us                                |
| ------------------------- | ----------------------------------------------- |
| User confirms suggestion  | Threshold was appropriate (or too conservative) |
| User rejects suggestion   | Threshold was too permissive                    |
| User merges clusters      | Threshold was too conservative                  |
| User splits cluster       | Threshold was too permissive                    |
| Singleton count increases | Threshold may be too conservative               |

**Simple Auto-Tuning Algorithm**:

```python
@dataclass
class ThresholdMetrics:
    confirmations: int = 0
    rejections: int = 0
    merges: int = 0
    splits: int = 0
    period_start: datetime = field(default_factory=datetime.utcnow)

class AdaptiveThresholdManager:
    def __init__(
        self,
        initial_threshold: float = 0.65,
        min_threshold: float = 0.50,
        max_threshold: float = 0.80,
        adjustment_step: float = 0.02,
        min_samples: int = 20,
    ):
        self.threshold = initial_threshold
        self.min_threshold = min_threshold
        self.max_threshold = max_threshold
        self.step = adjustment_step
        self.min_samples = min_samples
        self.metrics = ThresholdMetrics()

    def record_confirmation(self) -> None:
        """User confirmed a suggestion."""
        self.metrics.confirmations += 1
        self._maybe_adjust()

    def record_rejection(self) -> None:
        """User rejected a suggestion."""
        self.metrics.rejections += 1
        self._maybe_adjust()

    def record_merge(self) -> None:
        """User manually merged clusters."""
        self.metrics.merges += 1
        self._maybe_adjust()

    def record_split(self) -> None:
        """User split a cluster."""
        self.metrics.splits += 1
        self._maybe_adjust()

    def _maybe_adjust(self) -> None:
        """Adjust threshold if we have enough samples."""
        total = (
            self.metrics.confirmations +
            self.metrics.rejections +
            self.metrics.merges +
            self.metrics.splits
        )

        if total < self.min_samples:
            return

        # Calculate adjustment direction
        # Positive signals (threshold OK or too strict): confirmations, merges
        # Negative signals (threshold too loose): rejections, splits

        positive = self.metrics.confirmations + self.metrics.merges
        negative = self.metrics.rejections + self.metrics.splits

        if positive + negative == 0:
            return

        positive_ratio = positive / (positive + negative)

        # Target: 70% positive (mostly correct suggestions)
        target_ratio = 0.70

        if positive_ratio > target_ratio + 0.1:
            # Too conservative, lower threshold
            new_threshold = self.threshold - self.step
            logger.info(
                f"Auto-tune: lowering threshold {self.threshold:.2f} → {new_threshold:.2f} "
                f"(positive_ratio={positive_ratio:.2%})"
            )
            self.threshold = max(self.min_threshold, new_threshold)

        elif positive_ratio < target_ratio - 0.1:
            # Too permissive, raise threshold
            new_threshold = self.threshold + self.step
            logger.info(
                f"Auto-tune: raising threshold {self.threshold:.2f} → {new_threshold:.2f} "
                f"(positive_ratio={positive_ratio:.2%})"
            )
            self.threshold = min(self.max_threshold, new_threshold)

        # Reset metrics for next period
        self.metrics = ThresholdMetrics()

    def get_current_threshold(self) -> float:
        return self.threshold
```

**Integration with API**:

```python
# Global manager (per tenant in production)
threshold_managers: dict[UUID, AdaptiveThresholdManager] = {}

def get_threshold_manager(tenant_id: UUID) -> AdaptiveThresholdManager:
    if tenant_id not in threshold_managers:
        # Load from database or use default
        threshold_managers[tenant_id] = AdaptiveThresholdManager()
    return threshold_managers[tenant_id]

@router.post("/clusters/{cluster_id}/confirm")
async def confirm_suggestion(cluster_id: UUID, suggestion_id: UUID):
    await confirm_identity_to_cluster(cluster_id, suggestion_id)

    # Record feedback
    manager = get_threshold_manager(current_tenant_id)
    manager.record_confirmation()

    return {"status": "confirmed"}

@router.post("/clusters/{cluster_id}/reject")
async def reject_suggestion(cluster_id: UUID, suggestion_id: UUID):
    await reject_suggestion(suggestion_id)

    manager = get_threshold_manager(current_tenant_id)
    manager.record_rejection()

    return {"status": "rejected"}

@router.post("/clusters/merge")
async def merge_clusters(cluster_ids: list[UUID]):
    await merge_clusters_by_ids(cluster_ids)

    manager = get_threshold_manager(current_tenant_id)
    manager.record_merge()

    return {"status": "merged"}
```

**Persistence**:

```python
async def save_threshold_state(tenant_id: UUID, manager: AdaptiveThresholdManager):
    """Persist threshold state to database."""
    await db.execute(
        """
        INSERT INTO tenant_clustering_config (tenant_id, similarity_threshold, updated_at)
        VALUES (:tenant_id, :threshold, NOW())
        ON CONFLICT (tenant_id) DO UPDATE
        SET similarity_threshold = :threshold, updated_at = NOW()
        """,
        {"tenant_id": tenant_id, "threshold": manager.threshold}
    )

async def load_threshold_state(tenant_id: UUID) -> float:
    """Load threshold from database."""
    result = await db.fetch_one(
        "SELECT similarity_threshold FROM tenant_clustering_config WHERE tenant_id = :tenant_id",
        {"tenant_id": tenant_id}
    )
    return result["similarity_threshold"] if result else 0.65
```

---

## Revised Recommendations (Compressed Timeline)

### Week 1: Core Improvements

1. **Option C: Confidence Weighting**

   - Store det_score, bbox with identities
   - Implement adaptive thresholds
   - Integrate into rep matching

2. **Move thresholds to config**

   - All hard-coded values → ClusteringSettings
   - Enables runtime tuning

3. **Extend 1024D vector**
   - Store det_score, pose, bbox_area
   - Reserve space for future body features

### Week 2: Two-Pass + Hybrid Clustering

4. **Scaffold two-pass clustering**

   - Pass 1: Conservative CW (threshold 0.75)
   - Pass 2: HAC merge on cluster centroids

5. **Hybrid CW + HDBSCAN**

   - CW for bulk processing
   - HDBSCAN on singletons/outliers

6. **In-session reconciliation**
   - Event-driven, not cron
   - Trigger on user confirmations

### Week 3: Tuning & Validation

7. **Auto-tuning framework**

   - Record user feedback
   - Adjust thresholds per tenant

8. **Color histogram session inference**

   - Extract scene signatures
   - Boost same-session similarity

9. **Metrics & monitoring**
   - Singleton rate
   - Acceptance rate
   - Threshold adjustments

### Deferred (If Needed Later)

- Option D (Suggestion tier) - only if Option C insufficient
- Full body embedding model - only if clothing histograms insufficient
- Overnight batch reconciliation - replaced by in-session async
