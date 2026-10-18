# Clustering Batch Size Regression — Debug Analysis

## Problem Statement

Clustering behavior is **inconsistent and dependent on batch size**:

- **10 images** (fresh DB): Clustering works correctly — three separate identities assigned to three different clusters
- **20 images** (fresh DB): Clustering fails — three separate identities incorrectly grouped into the same cluster

**Ground truth**: The three identities correspond to three distinct people and should always be in separate clusters.

**Critical context**: Both tests were run with a freshly reset database, eliminating state accumulation as a factor.

---

## Observed Behavior

### Correct Behavior (10 images, fresh DB)

```
Found 3 media identities:
- media_id=2871 identity=17f84264 cluster_id=df3b21c4 emb_norm=1.4142 centroid_norm=1.0000
- media_id=2872 identity=176d8262 cluster_id=b1b650a8 emb_norm=1.4142 centroid_norm=1.0000
- media_id=2872 identity=fb5bb209 cluster_id=c80bafb8 emb_norm=1.4142 centroid_norm=1.0000

Pairwise similarities: 0.5367, 0.5363, 0.4924 (all below 0.6 threshold)
Identity-to-centroid: 0.9386, 1.0000, 0.9262 (high — singleton clusters)
```

### Incorrect Behavior (20 images, fresh DB)

```
Found 3 media identities (ALL IN SAME CLUSTER):
- media_id=2871 identity=3cbb44b1 cluster_id=7cc1ac7a emb_norm=1.4142 centroid_norm=1.0000
- media_id=2872 identity=650fe5b0 cluster_id=7cc1ac7a emb_norm=1.4142 centroid_norm=1.0000
- media_id=2872 identity=4135b055 cluster_id=7cc1ac7a emb_norm=1.4142 centroid_norm=1.0000

Pairwise similarities: 0.5367, 0.5363, 0.4924 (identical to 10-image case)
Identity-to-centroid: 0.7353, 0.6726, 0.8691 (lower, more variance)
```

**Key observation**: Pairwise similarities are **identical** (0.49-0.54) in both scenarios, but cluster assignments differ dramatically.

---

## Root Cause Analysis

### Issue: Incremental Clustering with Centroid Drift

The clustering algorithm processes identities **incrementally in creation order**, comparing each new identity against all existing cluster centroids. When a larger batch (20 images) creates more intermediate clusters, the incremental centroid updates can cause "centroid drift" that attracts dissimilar identities.

#### How It Happens (20 images)

1. **Images 1-17**: Detect various faces, creating clusters A, B, C, etc. Some of these clusters may have centroids that drift during updates.

2. **Image 18 (Person X from media_id=2871)**:

   - Compare against existing centroids (A, B, C, ...)
   - If similarity to any centroid ≥ 0.6, assign to that cluster
   - Otherwise, create new cluster

3. **Image 19 (Person Y from media_id=2872)**:

   - Compare against all centroids (including clusters modified by Person X)
   - Gets assigned to an existing cluster due to centroid drift

4. **Image 20 (Person Z from media_id=2872)**:
   - Compare against centroids that now average dissimilar faces
   - The averaged centroid may be closer to Person Z than the original members were
   - Gets incorrectly assigned to the same cluster

#### The Centroid Update Formula

```python
def update_centroid_incremental(old_centroid, old_count, new_embedding):
    old_vector = np.array(old_centroid, dtype=np.float32)  # Already normalized (norm=1.0)
    new_vector = _normalize_vector(np.array(new_embedding, dtype=np.float32))

    weighted_old = old_vector * float(old_count)  # Denormalize by scaling
    updated = (weighted_old + new_vector) / float(old_count + 1)
    return _normalize_vector(updated)  # Re-normalize
```

This formula computes: `normalize((old_centroid × N + new_vec) / (N + 1))`

**The formula is mathematically correct** for computing the average of N+1 unit vectors when given:

- A normalized average of N unit vectors (old_centroid)
- One new unit vector (new_embedding)

However, in practice, this creates a **bias toward early members**: when you average many unit vectors, the resulting centroid can drift significantly from any individual member, potentially reaching similarities ≥ 0.6 with dissimilar faces.

#### Why 10 Images Succeed

With fewer images, there are fewer intermediate clusters and less opportunity for centroid drift. The three target identities (media 2871 and 2872) arrive when the cluster landscape is simpler, so they each create their own clusters.

#### Why 20 Images Fail

With more images (1-17 before the target faces), more clusters exist with more chances for:

1. Centroid drift toward "average face" representations
2. One of the three target identities getting assigned to a drifted cluster
3. The centroid shifting further, attracting the remaining two target identities

---

## Secondary Issue: Non-Normalized Embedding Storage

Embeddings are stored with `norm=1.4142` (√2) instead of 1.0, indicating they're not normalized at storage time. While this doesn't cause the clustering bug (Python code normalizes before comparison), it indicates architectural inconsistency:

```python
# identity_scan_service.py:_save_identities()
identity = MediaIdentity(
    # ...
    embedding=embedding_entity.embedding,  # ❌ Stored unnormalized
)
```

The materialized view compensates by normalizing:

```sql
normalize_vector(mi.embedding::public.vector)::vector(1024) AS unit_embedding
```

---

## Diagnostic Steps

### Step 1: Add Clustering Decision Logging

Instrument `cluster_identities_incremental()` to log all similarity comparisons:

```python
for identity in unclustered:
    identity_vector = _normalize_vector(np.array(identity.embedding, dtype=np.float32))
    best_entry, best_similarity = self._find_best_cluster_match(identity_vector, existing_clusters)

    logger.info(
        f"Identity {identity.id} (media {identity.media_id}): "
        f"best_cluster={best_entry.cluster.id if best_entry else None}, "
        f"similarity={best_similarity:.4f}, threshold={self.threshold:.4f}"
    )

    if best_entry and best_similarity >= self.threshold:
        logger.info(f"→ Assigning to existing cluster {best_entry.cluster.label}")
    else:
        logger.info(f"→ Creating new cluster (similarity {best_similarity:.4f} < {self.threshold:.4f})")
```

**Expected output with 20 images**: You'll see one of the three target identities assigned to an existing cluster with similarity just above 0.6, then subsequent identities following due to centroid drift.

### Step 2: Test with Synthetic Data

Create three orthogonal embeddings (guaranteed dissimilar) and verify they cluster correctly:

```python
import numpy as np
from recognition.application.identity_clustering_service import IdentityClusteringService

# Three orthogonal 1024-dim vectors (cosine similarity = 0)
emb1 = np.zeros(1024, dtype=np.float32); emb1[0] = 1.0
emb2 = np.zeros(1024, dtype=np.float32); emb2[1] = 1.0
emb3 = np.zeros(1024, dtype=np.float32); emb3[2] = 1.0

# Create identities with these embeddings and cluster
# Expected: 3 separate clusters regardless of how many other faces are in the batch
```

### Step 3: Measure Centroid Drift

Track how centroids change as members are added:

```python
# In _assign_to_cluster()
old_centroid_copy = entry.centroid.copy()
# ... perform update ...
drift = 1.0 - compute_similarity(old_centroid_copy, entry.centroid)
logger.info(f"Centroid drift for cluster {entry.cluster.id}: {drift:.4f}")
```

---

## Research Insights

### ML Literature (Introduction to Machine Learning with Python)

Chapter 3 "Unsupervised Learning" provides validation for our approach:

**Agglomerative Clustering with Ward Linkage**:

- Minimizes variance increase when merging clusters
- Produces relatively equally sized clusters (26-623 in 2,063-face dataset)
- More robust to processing order than incremental methods
- Successfully identified semantic groups in face clustering

**Evaluation Metrics**:

- **ARI (Adjusted Rand Index)**: Proper metric for clustering (handles label permutation)
- **Silhouette score**: Measures cluster compactness
- Manual inspection still necessary for semantic validation

**Preprocessing Importance**:

- Distance-based algorithms highly sensitive to data scaling
- Consistent normalization critical for cosine similarity

### WordPress Plugin Experience (Hybrid Face Matching)

The archived WordPress plugin solved a similar incremental face matching problem using **representative embeddings** instead of centroids:

**Key Finding**: Store actual face embeddings (up to 10 per person) rather than computed centroids

- Avoids centroid drift entirely
- WordPress implementation proved this works at scale (50+ person roster)
- Used 0.65 similarity threshold successfully

**Why Representative Embeddings Work**:

```php
// Compare against actual faces, not averaged centroids
foreach ($observations as $obs) {
    $similarity = cosineSimilarity($newFace, $obs->embedding);
    if ($similarity >= 0.65) {
        return $obs->rosterId;  // Direct match to real face
    }
}
```

**The Insight**: Centroids are mathematical averages that drift toward "generic face" representations. Representative embeddings preserve actual face characteristics.

### Comparative Analysis: FAISS vs Representative Embeddings

**FAISS Role**:

- **Not a solution for centroid drift** - FAISS is for performance, not accuracy
- Useful for Stage 1 performance when cluster count > 100 (sub-linear search)
- Requires labeled data (roster entries) before it can help
- Does NOT solve Stage 2 problem (creating new clusters from unknowns)

**Representative Embeddings Role**:

- **Directly solves centroid drift** by avoiding averaged centroids
- Simpler implementation than full agglomerative rewrite
- Proven at scale in production WordPress plugin
- Works immediately without infrastructure dependencies

---

## Solution Summary

After analyzing ML literature and reviewing the WordPress plugin's approach, we've developed a comprehensive fix combining:

1. **Representative Embeddings** (WordPress plugin approach): Store actual face embeddings instead of averaged centroids to eliminate drift
2. **Ward Linkage Clustering** (ML textbook validation): Use batch agglomerative clustering for deterministic new cluster creation
3. **Three-Stage Hybrid**: Combine both approaches for optimal results

**Implementation Details**: See [`clustering-fix-implementation-plan.md`](./clustering-fix-implementation-plan.md) for complete roadmap, code scaffolding, testing strategy, and estimated timeline (2-3 weeks).

**Key Insights**:

- Centroid drift is the root cause - averaging unit vectors creates "generic face" representations
- Representative embeddings (real faces) avoid drift entirely
- Ward linkage provides deterministic batch clustering for new identities
- FAISS is for performance scaling (Phase 4), not accuracy

---

## Implementation Plan

### Strategy: Three-Stage Enhanced Hybrid Clustering

Based on insights from ML literature and WordPress plugin experience, implement a three-stage approach that combines representative embeddings, batch agglomerative clustering, and optional FAISS optimization:

1. **Stage 1**: Match against existing clusters using representative embeddings (no centroid drift)
2. **Stage 2**: Fallback to centroid-based matching for performance (if needed)
3. **Stage 3**: Batch-cluster remaining identities using Ward linkage (deterministic)

This approach:

- Eliminates centroid drift for existing cluster assignment
- Maintains cross-batch identity continuity
- Creates deterministic new clusters
- Scales to large cluster counts

**Full Details**: Complete implementation scaffolding, database schemas, testing strategy, and success metrics are documented in [`clustering-fix-implementation-plan.md`](./clustering-fix-implementation-plan.md).

---

## Recommended Fixes (Prioritized)

### Fix 1: Implement Representative Embeddings (High Priority - Solves Root Cause)

**Estimated effort**: 4-6 hours  
**Impact**: Directly eliminates centroid drift for Stage 1 assignment

Replace centroid-based matching with representative embedding matching (WordPress plugin approach).

**See**: [`clustering-fix-implementation-plan.md#phase-1-representative-embeddings`](./clustering-fix-implementation-plan.md#phase-1-representative-embeddings-week-1) for complete implementation details, database schemas, and code scaffolding.

### Fix 2: Implement Three-Stage Hybrid Clustering (High Priority)

**Estimated effort**: 6-8 hours  
**Impact**: Combines representative matching + Ward linkage for optimal results

**See**: [`clustering-fix-implementation-plan.md#phase-2-three-stage-hybrid-clustering`](./clustering-fix-implementation-plan.md#phase-2-three-stage-hybrid-clustering-week-2) for complete implementation with code examples.

### Fix 3: Raise Similarity Threshold (Quick Win)

**Estimated effort**: 15 minutes  
**Impact**: Immediate reduction in false positives (validated by WordPress plugin at 0.65)

Change from 0.6 to 0.65 in `recognition/config.py` and API routes.

### Fix 4: Normalize Embeddings at Storage (Consistency)

**Estimated effort**: 30 minutes  
**Impact**: Ensures consistency, prevents future issues

Store normalized embeddings in `identity_scan_service.py::_save_identities()`.

### Fix 5: Add Cluster Quality Validation (Safeguard)

**Estimated effort**: 2-3 hours  
**Impact**: Detects bad clusters, enables monitoring

Implement validation with min/avg pairwise similarity and representative similarity metrics.

---

## Next Steps

1. **Review**: Read [`clustering-fix-implementation-plan.md`](./clustering-fix-implementation-plan.md) for complete implementation details
2. **Phase 1** (Week 1): Implement representative embeddings infrastructure
3. **Phase 2** (Week 2): Implement three-stage hybrid clustering
4. **Phase 3** (Week 2-3): Quick wins and validation
5. **Testing**: Run comprehensive test suite (unit, integration, acceptance)
6. **Validation**: Verify 20-image test now produces 3 clusters

---

## OLD CONTENT (For Reference)

The sections below document the original analysis and proposed fixes before developing the comprehensive implementation plan. They are preserved for historical reference.

---

## Recommended Fixes (Original)

### Fix 1: Normalize Embeddings at Storage (Cosmetic)

**Location**: `apps/prototype-description-service/recognition/application/identity_scan_service.py`

```python
from recognition.application.centroid_utils import _normalize_vector

identity = MediaIdentity(
    # ...
    embedding=_normalize_vector(np.array(embedding_entity.embedding, dtype=np.float32)).tolist(),
)
```

**Impact**: Ensures consistency between stored embeddings and centroids (both norm=1.0), but doesn't fix the clustering bug.

### Fix 2: Increase Similarity Threshold (Mitigation)

Raise the default threshold from 0.6 to 0.7 or 0.75 to reduce false positive assignments:

```python
clustering_service = IdentityClusteringService(
    session=session,
    tenant_id=request.tenant_id,
    similarity_threshold=0.7,  # Was 0.6
)
```

**Trade-off**: Reduces false clusters but may create more singleton clusters for the same person.

### Fix 3: Implement Batch Agglomerative Clustering with Ward Linkage (Recommended)

Replace incremental clustering with hierarchical agglomerative clustering on all unclustered identities:

```python
async def cluster_identities_batch(self) -> List[IdentityCluster]:
    """
    Cluster all unclustered identities using agglomerative clustering with Ward linkage.
    More deterministic than incremental approach.

    Literature basis: "Introduction to ML with Python" Ch 3 shows Ward linkage
    produces semantically meaningful face clusters and handles 2,063 faces successfully.
    """
    unclustered = await self._get_unclustered_identities()
    if not unclustered:
        return []

    # Build embeddings matrix
    embeddings = np.array([
        _normalize_vector(np.array(i.embedding, dtype=np.float32))
        for i in unclustered
    ])

    # Agglomerative clustering with Ward linkage
    from sklearn.cluster import AgglomerativeClustering

    # Convert similarity threshold to distance threshold
    # Cosine similarity: 1 = identical, 0 = orthogonal
    # Distance: 0 = identical, 2 = opposite
    distance_threshold = 2 * (1.0 - self.threshold)  # e.g., 0.6 similarity → 0.8 distance

    clustering = AgglomerativeClustering(
        n_clusters=None,  # Auto-determine based on distance_threshold
        distance_threshold=distance_threshold,
        metric='cosine',
        linkage='ward',  # Minimizes variance increase when merging
        compute_full_tree=True  # Enables distance_threshold mode
    )

    labels = clustering.fit_predict(embeddings)

    # Create clusters based on labels
    clusters_by_label = defaultdict(list)
    for identity, label in zip(unclustered, labels):
        clusters_by_label[label].append(identity)

    created_clusters = []
    for members in clusters_by_label.values():
        cluster, _ = await self._create_cluster_with_centroid(members)
        created_clusters.append(cluster)

    await self.session.commit()
    return created_clusters
```

**Advantages**:

- **Deterministic**: same identities always produce same clusters regardless of processing order
- **No centroid drift**: considers all pairwise relationships, not incremental updates
- **Ward linkage**: minimizes variance increase, produces balanced clusters
- **Dendrogram visualization**: can inspect hierarchical structure at different cut points
- **Literature validated**: textbook demonstrates success on 2,063-face dataset

**Disadvantages**:

- More computationally expensive (O(n²) for similarity matrix)
- Requires all unclustered identities in memory

### Fix 4: Add Cluster Quality Validation with ARI and Silhouette Metrics

After clustering, validate that intra-cluster similarities meet threshold:

```python
from sklearn.metrics import adjusted_rand_score, silhouette_score

async def _validate_cluster_quality(self, cluster_id: UUID) -> Tuple[bool, Dict[str, float]]:
    """
    Check if all members in a cluster meet similarity threshold.

    Returns:
        (is_valid, metrics) where metrics includes:
        - min_pairwise_similarity: Minimum similarity between any two members
        - avg_pairwise_similarity: Average similarity across all pairs
        - silhouette_score: Cluster compactness metric (-1 to 1, higher is better)
    """
    members = await self._get_cluster_members(cluster_id)
    embeddings = [_normalize_vector(np.array(m.embedding, dtype=np.float32)) for m in members]

    if len(embeddings) < 2:
        return True, {"min_pairwise_similarity": 1.0, "avg_pairwise_similarity": 1.0}

    # Compute pairwise similarities
    similarities = []
    for i in range(len(embeddings)):
        for j in range(i + 1, len(embeddings)):
            sim = compute_similarity(embeddings[i], embeddings[j])
            similarities.append(sim)

    min_sim = min(similarities)
    avg_sim = sum(similarities) / len(similarities)

    # Compute silhouette score if we have global cluster labels
    # (requires access to other clusters for comparison)
    silhouette = None
    try:
        all_labels = await self._get_all_cluster_labels()
        all_embeddings = await self._get_all_embeddings()
        silhouette = silhouette_score(all_embeddings, all_labels, metric='cosine')
    except Exception as e:
        logger.warning(f"Could not compute silhouette score: {e}")

    is_valid = min_sim >= self.threshold

    if not is_valid:
        logger.warning(
            f"Cluster {cluster_id} quality check FAILED: "
            f"min_similarity={min_sim:.4f} < threshold={self.threshold:.4f}, "
            f"avg_similarity={avg_sim:.4f}"
        )

    metrics = {
        "min_pairwise_similarity": min_sim,
        "avg_pairwise_similarity": avg_sim,
        "silhouette_score": silhouette
    }

    return is_valid, metrics
```

**Literature basis**: Textbook emphasizes:

- ARI (Adjusted Rand Index) for comparing clusterings (handles label permutation)
- Silhouette score for measuring cluster compactness
- "Manual inspection still necessary" — automated metrics complement human review

---

## Architectural Consideration: Batch Clustering with Preexisting Clusters

### The Problem

The proposed batch agglomerative clustering (Fix #3) processes **only unclustered identities** and creates new clusters from scratch. However, this creates a critical issue for **incremental workloads** where:

1. User uploads 10 images → clustering creates clusters A, B, C
2. User uploads 20 more images → clustering should **assign new faces to existing clusters A, B, C** if they match

**With pure batch clustering**, step 2 would:

- Ignore existing clusters A, B, C
- Cluster only the 20 new identities among themselves
- Create duplicate clusters (e.g., new cluster D for a person already in cluster A)

### Solution: Hybrid Approach

Implement a **two-stage hybrid clustering strategy**:

#### Stage 1: Assign to Existing Clusters (Incremental)

```python
async def cluster_identities_hybrid(self) -> List[IdentityCluster]:
    """
    Two-stage clustering:
    1. Try to assign new identities to existing clusters
    2. Batch-cluster remaining identities using agglomerative clustering
    """
    await self._ensure_tenant_context()

    # Stage 1: Load existing clusters
    existing_clusters = await self._get_clusters_with_centroids()
    unclustered = await self._get_unclustered_identities()

    if not unclustered:
        return []

    still_unclustered = []
    assigned_count = 0

    # Try to assign each identity to existing clusters
    for identity in unclustered:
        identity_vector = _normalize_vector(np.array(identity.embedding, dtype=np.float32))
        best_entry, best_similarity = self._find_best_cluster_match(
            identity_vector,
            existing_clusters,
        )

        if best_entry and best_similarity >= self.threshold:
            await self._assign_to_cluster(identity, identity_vector, best_entry, best_similarity)
            assigned_count += 1
        else:
            still_unclustered.append(identity)

    logger.info(
        "Stage 1: Assigned %d identities to existing clusters, %d remain unclustered",
        assigned_count,
        len(still_unclustered),
    )

    # Stage 2: Batch-cluster the remaining identities
    if not still_unclustered:
        await self.session.commit()
        return []

    return await self._cluster_batch_agglomerative(still_unclustered)
```

#### Stage 2: Batch Cluster Remaining (Agglomerative)

```python
async def _cluster_batch_agglomerative(
    self,
    identities: List[MediaIdentity]
) -> List[IdentityCluster]:
    """
    Cluster identities using agglomerative clustering with Ward linkage.
    Only called for identities that don't match any existing cluster.
    """
    if len(identities) == 1:
        # Single identity - just create singleton cluster
        cluster, _ = await self._create_cluster_with_centroid([identities[0]])
        await self.session.commit()
        return [cluster]

    # Build embeddings matrix
    embeddings = np.array([
        _normalize_vector(np.array(i.embedding, dtype=np.float32))
        for i in identities
    ])

    # Agglomerative clustering with Ward linkage
    from sklearn.cluster import AgglomerativeClustering

    distance_threshold = 2 * (1.0 - self.threshold)

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=distance_threshold,
        metric='cosine',
        linkage='ward',
        compute_full_tree=True
    )

    labels = clustering.fit_predict(embeddings)

    # Create clusters based on labels
    clusters_by_label = defaultdict(list)
    for identity, label in zip(identities, labels):
        clusters_by_label[label].append(identity)

    created_clusters = []
    for members in clusters_by_label.values():
        cluster, _ = await self._create_cluster_with_centroid(members)
        created_clusters.append(cluster)

    await self.session.commit()

    logger.info(
        "Stage 2: Created %d new clusters from %d unclustered identities",
        len(created_clusters),
        len(identities),
    )

    return created_clusters
```

### Why This Hybrid Approach Works

1. **Preserves existing clusters**: New faces that match existing people get assigned correctly
2. **Eliminates order dependency for new clusters**: Faces that don't match existing clusters get processed together with deterministic agglomerative clustering
3. **Best of both worlds**:
   - **Incremental assignment** solves the cross-batch identity matching problem
   - **Batch agglomerative** solves the centroid drift problem for new faces

### Impact on Workflow

**Scenario: User uploads images incrementally**

1. **First batch (10 images)**:

   - Stage 1: No existing clusters, skip
   - Stage 2: Batch-cluster all 10 → creates clusters A, B, C deterministically

2. **Second batch (20 images)**:

   - Stage 1: Try to assign to A, B, C
     - 3 images match cluster A → assigned
     - 2 images match cluster B → assigned
     - 15 images don't match (similarity < 0.6)
   - Stage 2: Batch-cluster the 15 remaining → creates clusters D, E, F deterministically

3. **Third batch (5 images)**:
   - Stage 1: Try to assign to A, B, C, D, E, F
     - 5 images all match existing clusters → assigned
   - Stage 2: Nothing left to cluster

**Key insight**: This eliminates the bug because:

- Stage 1 assignment still uses threshold comparison (no centroid drift for assignment)
- Stage 2 uses batch agglomerative (no centroid drift when creating new clusters)

### Tradeoffs

**Pros**:

- Solves the order-dependency bug for new clusters
- Maintains cross-batch identity continuity
- Stage 1 is O(n×k) where k = existing clusters (fast)
- Stage 2 is O(m²) where m = unclustered (only expensive if many new identities don't match)

**Cons**:

- Stage 1 still does incremental assignment (but only for matching existing clusters)
- More complex implementation than pure batch or pure incremental
- Stage 1 centroid updates could still drift (but only affects **existing** clusters, not new ones)

### Alternative: Full Re-clustering

An alternative would be to **re-cluster ALL identities** (existing + new) every time:

```python
async def cluster_identities_full_recompute(self) -> List[IdentityCluster]:
    """
    FULL RE-CLUSTERING: Delete all clusters and re-cluster all identities.
    Computationally expensive but maximally deterministic.
    """
    # Delete all existing clusters
    await self._delete_all_clusters()

    # Get ALL identities
    all_identities = await self._get_all_identities()

    # Batch-cluster everything
    return await self._cluster_batch_agglomerative(all_identities)
```

**When to use full re-clustering**:

- User explicitly requests "rebuild clusters from scratch"
- Changing clustering algorithm or threshold
- Detecting cluster quality issues that require fresh start

**When to use hybrid**:

- Normal incremental uploads (default workflow)
- Preserving user-assigned cluster labels
- Performance-sensitive applications

---

## Action Items

### Immediate (for debugging)

1. ✅ **Add detailed logging** to clustering decisions
2. ✅ **Run 20-image test** with logging enabled to identify which identity gets misassigned first
3. ✅ **Test with synthetic orthogonal embeddings** to isolate the order-dependency

### Short-term (fixes)

4. **Normalize embeddings at storage** (cosmetic fix)
5. **Increase similarity threshold to 0.7** (mitigation)
6. **Implement cluster quality validation** to detect bad clusters

### Long-term (architectural)

7. **Replace incremental clustering with batch clustering** (recommended)
8. **Add integration test** that verifies clustering is deterministic regardless of batch size
9. **Implement cluster splitting** for clusters that fail quality validation
