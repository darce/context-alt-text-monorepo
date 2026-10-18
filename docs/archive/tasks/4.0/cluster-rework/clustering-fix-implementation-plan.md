# Clustering Bug Fix: Implementation Plan

## Executive Summary

**Problem**: Clustering produces different results based on batch size (10 images work, 20 images fail) due to incremental centroid drift.

**Root Cause**: Averaged centroids drift toward "generic face" representations, reaching ≥ 0.6 similarity with dissimilar faces when many intermediate clusters exist.

**Solution**: Two-stage hybrid clustering:

1. **Stage 1 (online)**: Match against representative embeddings (actual faces, no drift)
2. **Stage 2 (offline Celery)**: Global Ward linkage on all unclustered identities

**Estimated Effort**: 12-16 hours over 2-3 weeks

**Document Structure**:

- **[Dependencies](#dependencies)** - Prerequisites for implementation
- **[Clustering Algorithm](#clustering-algorithm)** - Ward linkage config, threshold conversion, Celery primary path
- **[Implementation Stages](#implementation-stages)** - Stage 1-4 with acceptance criteria
- **[Performance & Limits](#performance--limits)** - Size thresholds, validated targets, strategies
- **[Tunable Heuristics](#tunable-heuristics)** - Parameters table with defaults, rationale, monitoring
- **[Telemetry Reference](#telemetry-reference)** - Exact structured fields per stage
- **[Risks & Mitigations](#risks--mitigations)** - Trade-offs table with monitoring
- **Appendix**: Research validation, detailed task lists, old roadmap sections

---

## Dependencies

| Component               | Status                 | Purpose                                               |
| ----------------------- | ---------------------- | ----------------------------------------------------- |
| **Celery**              | Required               | Async Stage 2 clustering for large batches (>100)     |
| **PostgreSQL pgvector** | Required               | Vector storage and operations                         |
| **FAISS**               | Optional, Stage 1 only | Accelerate representative matching when >100 clusters |

---

## Clustering Algorithm

### Overview

**Primary Path**: Celery offline clustering runs global Ward linkage on **all unclustered identities** (no chunking). This ensures mathematically correct agglomeration.

**Chunking**: Last-resort safeguard for batches >5,000 identities only. Uses hierarchical strategy to approximate global clustering while managing memory.

### Ward Linkage Configuration

**CRITICAL**: Ward linkage ONLY works with Euclidean distance:

```python
# CORRECT
AgglomerativeClustering(linkage='ward', metric='euclidean')

# ERROR - Will fail
AgglomerativeClustering(linkage='ward', metric='cosine')
```

### Cosine → Euclidean Threshold Conversion

For unit-normalized vectors, relationship: `||a - b||² = 2(1 - cos(a,b))`

**Conversion formula**: `euclidean_distance = sqrt(2 * (1 - cosine_threshold))`

**Example**: `cosine_threshold=0.65` → `euclidean_distance=0.837`

### Implementation

```python
@celery_app.task
async def batch_cluster_task(tenant_id: UUID):
    """Celery task: Global Ward linkage on all unclustered identities."""
    service = IdentityClusteringService(session, tenant_id)

    # Get ALL unclustered identities (no chunking)
    identities = await service._get_unclustered_identities()

    if len(identities) <= 5000:
        # Standard path: global Ward linkage
        clusters = await service._stage2_batch_clustering(identities)
    else:
        # Safeguard >5k: hierarchical approximation
        clusters = await service._batch_cluster_large(identities)

    return {"clusters_created": len(clusters)}


async def _stage2_batch_clustering(self, identities):
    """Global Ward linkage on normalized embeddings."""
    # Normalize to unit vectors
    embeddings = np.array([normalize_embedding(i.embedding) for i in identities])

    # Convert threshold
    threshold_euclidean = self._validate_and_convert_threshold(
        self.threshold,
        embeddings,
    )

    # Global agglomeration
    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=threshold_euclidean,
        metric='euclidean',
        linkage='ward',
    )
    labels = clustering.fit_predict(embeddings)

    return await self._create_clusters_from_labels(identities, labels)
```

---

## Research-Backed Strategy

### Key Finding #1: Representative Embeddings (WordPress Plugin)

The archived WordPress plugin solved the same problem by storing **actual face embeddings** (up to 10 per person) instead of computed centroids:

```php
// Compare against real faces, not averaged centroids
foreach ($observations as $obs) {
    $similarity = cosineSimilarity($newFace, $obs->embedding);
    if ($similarity >= 0.65) {
        return $obs->rosterId;  // Match found
    }
}
```

**Why this works**: Centroids are mathematical averages that drift. Real embeddings preserve actual face characteristics.

### Key Finding #2: Ward Linkage on Unit Vectors (ML Textbook)

"Introduction to Machine Learning with Python" Chapter 3 validates Ward linkage for face clustering:

- Minimizes variance increase when merging clusters
- More robust to processing order than incremental methods
- Successfully clustered 2,063 faces with semantic meaning
- **Critical**: Ward linkage requires Euclidean distance metric
- For cosine similarity, use Euclidean distance on **normalized (unit) vectors**
- Distance threshold conversion: `distance_threshold = sqrt(2 * (1 - cosine_threshold))`
- This leverages: `||a - b||² = 2(1 - cos(a,b))` for unit vectors

### Key Finding #3: FAISS is for Performance, Not Accuracy

- FAISS solves **scaling** (Stage 1 search with 100+ clusters)
- FAISS does NOT solve **centroid drift** (new cluster creation)
- Implement representative embeddings first, add FAISS later if needed
- FAISS only accelerates Stage 1 representative matching, not Stage 2 clustering

### Key Finding #4: Diversity-Aware Representative Selection

**Problem**: Using confidence alone can evict diverse samples in favor of near-duplicates:

- High-confidence near-duplicates from same media source
- Overfitting to specific poses/lighting
- Poor generalization to varied samples

**Solution**: Diversity-aware selection (farthest-point sampling):

1. Always keep highest-confidence sample
2. For remaining slots, prefer samples dissimilar to existing representatives
3. Tie-breaker: confidence score
4. Result: Representative set spans cluster diversity

**Skew/Duplicate Handling**:

- Large batches with many near-duplicates of one person bias representative matching
- De-duplicate at media level: limit representatives per media_id (max 2-3)
- Prevents single photo shoot from dominating cluster representation

---

## Implementation Stages

### Stage 1: Representatives (Schema + Storage + Matching)

**Goal**: Store actual face embeddings (not centroids) and match new faces against them

**Database Schema**:

```sql
CREATE TABLE identity_cluster_representatives (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    cluster_id UUID NOT NULL REFERENCES identity_clusters(id),
    identity_id UUID NOT NULL REFERENCES media_identities(id),
    embedding vector(1024) NOT NULL,  -- Dimensioned type required
    quality_score FLOAT NOT NULL,
    diversity_score FLOAT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- RLS policies for tenant isolation
-- Indexes on tenant_id, cluster_id, embedding (IVFFlat)
-- CHECK constraint: vector_norm(embedding) ≈ 1.0
```

**Core Methods**:

```python
async def _add_representative_embedding(cluster_id, identity):
    """Add normalized face as cluster representative."""
    # 1. Normalize embedding
    # 2. Check per-media limit (MAX_REPS_PER_MEDIA)
    # 3. Calculate diversity score
    # 4. Add or replace based on quality+diversity

async def _match_against_representatives(identity_vector, cluster_ids):
    """Match face against actual representatives (not centroids)."""
    # Returns (best_cluster_id, similarity) or (None, 0.0)
```

**Acceptance Criteria**:

- ✅ Representatives table created with RLS, indexes, CHECK constraints
- ✅ Embeddings normalized before storage (L2 norm = 1.0)
- ✅ Diversity-aware selection (prefer dissimilar samples)
- ✅ Per-media limit enforced (max 2-3 per media_id)
- ✅ Stage 1 matching uses representatives, not centroids

---

### Stage 2: Global Ward Clustering (Sync for Small Batches, Async for Large)

**Goal**: Run global Ward linkage on all unclustered identities (primary path, not chunked)

**Strategy**:

- **≤100 identities**: Run Ward **synchronously inline** (1-3s, immediate results for UI/tests)
- **101-5,000 identities**: Run Ward **asynchronously via Celery** (<60s, avoid blocking requests)
- **>5,000 identities**: Hierarchical approximation under feature flag

**Critical Performance Notes**:

- **Cutoff based on batch size, not existing clusters**: The expensive part is Ward's O(n²-n³) fit over the **unclustered embeddings in the current batch**, not the number of pre-existing clusters. Existing clusters only affect Stage 1 representative matching (cheap).
- **Inline feasibility**: ~100 unit-normalized 1024-D vectors typically takes 1-3s on modest CPUs (Ward fit + DB I/O for memberships). Profile on your target hardware to validate.
- **Scoped to unclustered identities**: Synchronous path clusters only the `still_unclustered` list after Stage 1 representative matching. Existing clusters don't increase Ward's complexity.
- **Time-boxed cap**: Set hard limit based on profiling (e.g., ≤2s or ≤100 identities). If exceeded, enqueue Celery job.
- **Transaction scope**: Minimize lock duration: read embeddings → cluster in memory (no locks) → write cluster rows. Use normalized embeddings throughout.
- **UI/test handling**: For async path (>100), surface "Clustering in progress…" state and implement polling/waiting for Celery results.

**Main Entry Point**:

```python
async def cluster_identities_hybrid(self):
    """Orchestrate two-stage clustering with sync/async routing."""
    identities = await self._get_unclustered_identities()

    # Stage 1: Match against representatives (existing clusters)
    if existing_clusters:
        assigned = await self._stage1_representative_matching(identities)
        identities = [i for i in identities if i.id not in assigned]

    # Stage 2: Global Ward clustering
    if len(identities) <= 100:
        # Synchronous: immediate results
        clusters = await self._stage2_batch_clustering(identities)
    else:
        # Asynchronous: enqueue Celery job
        job = await self._enqueue_clustering_job(identities)
        return {"status": "pending", "job_id": job.id}

    return {"status": "complete", "clusters": clusters}
```

**Celery Task** (for >100 identities):

```python
@celery_app.task
async def batch_cluster_task(tenant_id: UUID, identity_ids: List[UUID]):
    """Async clustering path: global Ward on unclustered identities."""
    service = IdentityClusteringService(session, tenant_id)
    identities = await service._get_identities_by_ids(identity_ids)

    if len(identities) <= 5000:
        # Standard: global Ward (no chunking)
        clusters = await service._stage2_batch_clustering(identities)
    else:
        # Safeguard >5k: hierarchical approximation
        clusters = await service._batch_cluster_large(identities)

    # Update job status
    await service._update_job_status(job_id, "complete", len(clusters))
    return {"clusters_created": len(clusters)}
```

**Threshold Conversion & Normalization**:

```python
async def _stage2_batch_clustering(self, identities):
    # 1. Normalize embeddings to unit vectors
    embeddings = np.array([normalize_embedding(i.embedding) for i in identities])

    # 2. Validate and convert threshold
    threshold_euclidean = self._validate_and_convert_threshold(
        self.threshold,  # Cosine similarity (0.65)
        embeddings,      # Verify normalized
    )

    # 3. Global Ward linkage
    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=threshold_euclidean,
        metric='euclidean',
        linkage='ward',
    )
    labels = clustering.fit_predict(embeddings)

    return await self._create_clusters_from_labels(identities, labels)
```

**Acceptance Criteria**:

- ✅ Small batches (≤100) run Ward **synchronously inline** (immediate results)
- ✅ Large batches (>100) enqueue **Celery job** (async, with job status tracking)
- ✅ All embeddings normalized before clustering
- ✅ Threshold validated and converted (cosine → Euclidean)
- ✅ Ward linkage uses `metric='euclidean'` (not cosine)
- ✅ UI reflects job state ("Clustering in progress…", poll/refresh when complete)
- ✅ Tests wait/poll for Celery results when batch >100
- ✅ Hierarchical approximation for >5k identities

---

### Stage 3: Thresholds & Quality Validation

**Goal**: Enforce normalization, validate thresholds, ensure cluster quality

**3-Layer Normalization Defense**:

1. **Database**: CHECK constraint with custom `vector_norm()` function
2. **Application**: `normalize_embedding()` + `_verify_normalized()` guards
3. **Audit**: Periodic `audit_embedding_norms()` drift detection

**Threshold Validation**:

```python
def _validate_and_convert_threshold(cosine_threshold, embeddings):
    # Guard 1: Range check [0, 1]
    # Guard 2: Verify embeddings are unit-normalized
    # Guard 3: Clamp numerical edge cases
    # Guard 4: Validate output in [0, sqrt(2)]
    return sqrt(2 * (1 - cosine_threshold))
```

**Cluster Quality**:

```python
async def validate_cluster_quality(cluster_id):
    """Check min/avg pairwise similarity, alert if below threshold."""
    # Compute pairwise similarities
    # Alert if min_similarity < threshold
```

**Acceptance Criteria**:

- ✅ Database CHECK constraints reject non-unit vectors
- ✅ Application guards catch bad inputs before DB write
- ✅ Periodic audits detect drift (manual edits, bugs)
- ✅ Threshold validator verifies normalization before conversion
- ✅ Cluster quality validation alerts on low similarity

---

### Stage 4: Operations (Logging/Metrics/Monitoring)

**Goal**: Production telemetry, monitoring, and observability

**Telemetry**:

See "Telemetry Reference" appendix for complete field list

**Acceptance Criteria**:

- ✅ All stages log structured metrics
- ✅ Dashboards track acceptance rates, performance, quality
- ✅ Alerts fire on regressions (norm drift, slow clustering)
- ✅ Celery task monitoring for async clustering jobs

---

## Performance & Limits

| Input Size           | Strategy                   | Expected Latency           | Action                                          |
| -------------------- | -------------------------- | -------------------------- | ----------------------------------------------- |
| ≤100 identities      | Global Ward                | <5s (validate empirically) | Run `benchmark_ward_clustering()` before launch |
| 101-5,000 identities | Global Ward                | <60s (validate)            | Monitor Celery task duration                    |
| >5,000 identities    | Hierarchical approximation | Under feature flag         | Ward on chunks → reps → Ward on reps            |

**Memory**: O(n²) for distance matrix. Alert if >500MB for <1,000 identities.

**Complexity**: Empirically O(n^2.5-3.0). Fit power-law curve with `benchmark_ward_clustering()`.

---

## Tunable Heuristics

| Parameter                         | Default | Rationale                    | Monitoring Signal         | Tuning Action                     |
| --------------------------------- | ------- | ---------------------------- | ------------------------- | --------------------------------- |
| `SIMILARITY_THRESHOLD`            | 0.65    | WordPress plugin validation  | Cluster quality metrics   | Raise if too many false positives |
| `QUALITY_WEIGHT`                  | 0.7     | Balance quality vs diversity | Acceptance rate           | ↓ if over-pruning                 |
| `DIVERSITY_WEIGHT`                | 0.3     | 1 - QUALITY_WEIGHT           | Diversity rejection rate  | ↑ if too similar reps             |
| `MIN_DIVERSITY_SIMILARITY`        | 0.85    | Reject near-duplicates       | Rejection logs            | ↓ if low acceptance (<60%)        |
| `MAX_REPS_PER_MEDIA`              | 3       | Prevent media skew           | Deduplication logs        | ↑ if dropping distinct faces      |
| `MAX_REPRESENTATIVES_PER_CLUSTER` | 10      | Like WordPress plugin        | Cluster size distribution | Adjust if quality degrades        |

**Tuning Process**:

1. Baseline (Week 1): Collect metrics with defaults
2. Analyze: Check if acceptance ≈60%, diversity rejection ≈20%
3. Adjust: Modify parameters based on recommendations in logs
4. A/B test (Week 2): Compare cluster quality with new values
5. Iterate: Repeat until targets met

---

## Telemetry Reference

### Stage 1: Representative Matching

```python
{
    "stage": "representative_matching",
    "identities_evaluated": 42,
    "rep_matches_found": 28,
    "rep_matches_below_threshold": 10,
    "assignments": 28,
    "still_unclustered": 14,
    "avg_similarity": 0.72,
    "duration_ms": 35
}
```

### Stage 2: Ward Linkage Batch Clustering

```python
{
    "stage": "ward_clustering",
    "identities_processed": 14,
    "clusters_created": 3,
    "cluster_sizes": {"min": 2, "max": 8, "mean": 4.7, "median": 4},
    "min_pairwise_similarity": 0.68,
    "avg_pairwise_similarity": 0.75,
    "duration_seconds": 2.3,
    "memory_delta_mb": 45.2,
    "throughput_ids_per_sec": 6.1
}
```

### Representative Management

```python
{
    "operation": "representative_selection",
    "cluster_id": "...",
    "candidates_evaluated": 8,
    "accepted": 5,
    "rejected_per_media_limit": 2,
    "rejected_diversity": 1,
    "acceptance_rate": 0.625,
    "diversity_rejection_rate": 0.125
}
```

### Celery Task Metrics

```python
{
    "task": "batch_cluster_task",
    "tenant_id": "...",
    "identities_processed": 142,
    "clusters_created": 23,
    "duration_seconds": 15.7,
    "memory_peak_mb": 238.4,
    "strategy": "global_ward"  # or "hierarchical"
}
```

---

## Risks & Mitigations

| Risk                               | Impact                              | Mitigation                                                                                     | Monitoring                              |
| ---------------------------------- | ----------------------------------- | ---------------------------------------------------------------------------------------------- | --------------------------------------- |
| **Chunking non-equivalence**       | Different clusters than global Ward | Primary path is Celery global clustering (no chunks). Hierarchical approximation only for >5k. | Alert if >5k batch detected             |
| **Bad threshold inputs**           | Invalid conversion, wrong clusters  | 4-guard validation: type check, range [0,1], verify normalized, output sanity                  | Log validation failures                 |
| **Non-normalized vectors**         | Invalid threshold conversion        | 3-layer defense: DB CHECK, app guards, periodic audits                                         | Audit failures trigger alerts           |
| **Arbitrary heuristics**           | Over-pruning or poor quality        | Instrument acceptance/rejection rates, data-driven tuning                                      | Dashboard shows vs targets (60%/20%)    |
| **Dedup drops legit faces**        | Group photos lose people            | Verify similarity (alert if <0.95), audit duplicate ratio                                      | `audit_multi_face_media()` after Week 1 |
| **Performance claims unvalidated** | Slow in production                  | Run `benchmark_ward_clustering()` before launch, empirical targets                             | Alert if exceeds validated p95          |
| **Missing telemetry**              | Regressions undetected              | Log all stages, dashboards for quality/performance/acceptance                                  | Grafana dashboards + PagerDuty          |

---

##

    # Stage 1: Representative matching (actual faces)
    stage1_assigned, still_unclustered = await self._stage1_representative_matching(
        unclustered,
        existing_cluster_ids
    )

    # Stage 2: Batch-cluster remaining with Ward linkage
    created_clusters = []
    if still_unclustered:
        # Safeguard: Cap batch size for O(n³) Ward linkage
        if len(still_unclustered) > 500:
            logger.warning(
                f"Stage 2: {len(still_unclustered)} identities exceeds safe limit. "
                "Consider sampling or incremental processing."
            )
            # Process in chunks if needed
            created_clusters = await self._stage2_batch_clustering_chunked(still_unclustered)
        else:
            created_clusters = await self._stage2_batch_clustering(still_unclustered)

    await self.session.commit()
    return created_clusters

async def \_deduplicate_per_media(
self,
identities: List[MediaIdentity],
) -> List[MediaIdentity]:
"""
De-duplicate identities from same media.
Keep highest-confidence identity per media_id to prevent skew.
"""
by_media = defaultdict(list)
for identity in identities:
by_media[identity.media_id].append(identity)

    deduplicated = []
    for media_id, media_identities in by_media.items():
        if len(media_identities) <= 3:  # Reasonable number from one image
            deduplicated.extend(media_identities)
        else:
            # Keep top 3 highest-confidence
            sorted_by_conf = sorted(media_identities, key=lambda i: i.confidence, reverse=True)
            deduplicated.extend(sorted_by_conf[:3])
            logger.info(f"De-duplicated media {media_id}: {len(media_identities)} → 3")

    return deduplicated

````

**Acceptance Criteria**:

- Routes to correct stage based on existing cluster count
- Logs stage assignment counts
- Handles empty unclustered list gracefully

#### Task 2.2: Stage 1 Implementation

```python
async def _stage1_representative_matching(
    self,
    unclustered: List[MediaIdentity],
    cluster_ids: List[UUID],
) -> Tuple[int, List[MediaIdentity]]:
    """Match against actual face embeddings (no centroid drift)."""
    still_unclustered = []
    assigned_count = 0

    for identity in unclustered:
        identity_vector = _normalize_vector(np.array(identity.embedding))
        best_cluster_id, best_similarity = await self._match_against_representatives(
            identity_vector,
            cluster_ids
        )

        if best_cluster_id and best_similarity >= self.threshold:
            await self._assign_to_cluster_by_id(identity, identity_vector, best_cluster_id, best_similarity)
            await self._add_representative_embedding(best_cluster_id, identity)
            assigned_count += 1
        else:
            still_unclustered.append(identity)

    logger.info(f"Stage 1: Assigned {assigned_count}, {len(still_unclustered)} remain")
    return assigned_count, still_unclustered
````

**Acceptance Criteria**:

- Compares against representatives, not centroids
- Assigns only if similarity >= threshold
- Updates representatives after assignment
- Returns unassigned identities for Stage 3

#### Task 2.2: Stage 2 Implementation (Ward Linkage on Unit Vectors)

```python
async def _stage2_batch_clustering(
    self,
    identities: List[MediaIdentity],
) -> List[IdentityCluster]:
    """
    Batch-cluster using Ward linkage on NORMALIZED embeddings.

    CRITICAL: Ward linkage requires Euclidean distance.
    For cosine similarity, we use Euclidean on unit vectors.
    Relationship: ||a - b||² = 2(1 - cos(a,b)) for unit vectors.

    Distance threshold conversion:
    cosine_similarity_threshold → euclidean_distance_threshold
    distance_threshold = sqrt(2 * (1 - cosine_threshold))

    Example: cosine_threshold=0.65 → distance_threshold=sqrt(2*0.35)≈0.837
    """
    if len(identities) == 1:
        cluster, _ = await self._create_cluster_with_centroid([identities[0]])
        return [cluster]

    # Normalize embeddings (unit vectors for Euclidean distance)
    embeddings = np.array([
        _normalize_vector(np.array(i.embedding))
        for i in identities
    ])

    from sklearn.cluster import AgglomerativeClustering

    # Convert cosine similarity threshold to Euclidean distance threshold
    # For unit vectors: ||a - b||² = 2(1 - cos(a,b))
    # Therefore: ||a - b|| = sqrt(2 * (1 - cos(a,b)))
    distance_threshold = np.sqrt(2 * (1.0 - self.threshold))

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=distance_threshold,
        metric='euclidean',  # MUST be euclidean for Ward
        linkage='ward',      # Minimizes variance
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

    logger.info(
        f"Stage 2: Created {len(created_clusters)} clusters from {len(identities)} identities "
        f"(threshold={self.threshold:.2f}, distance={distance_threshold:.3f})"
    )
    return created_clusters

async def _stage2_batch_clustering_chunked(
    self,
    identities: List[MediaIdentity],
    chunk_size: int = 500,
) -> List[IdentityCluster]:
    """
    Process large batches in chunks to avoid O(n³) explosion.
    Ward linkage is O(n²) to O(n³) depending on implementation.
    """
    all_clusters = []
    for i in range(0, len(identities), chunk_size):
        chunk = identities[i:i+chunk_size]
        logger.info(f"Processing chunk {i//chunk_size + 1}: {len(chunk)} identities")
        chunk_clusters = await self._stage2_batch_clustering(chunk)
        all_clusters.extend(chunk_clusters)
    return all_clusters
```

**Acceptance Criteria**:

- Uses Ward linkage with **Euclidean distance** (not cosine)
- Operates on **normalized (unit) embeddings**
- Correctly converts cosine threshold to Euclidean distance: `sqrt(2 * (1 - threshold))`
- Creates deterministic clusters (batch-size independent)
- Single identity creates singleton cluster
- Logs cluster creation stats with threshold values
- Caps batch size at 500 identities (safeguard for O(n³) complexity)
- Chunks larger batches automatically

---

## Testing Strategy

### Unit Tests

```python
@pytest.mark.asyncio
async def test_representative_matching_avoids_drift(db_session, tenant_id):
    """Representative matching prevents incorrect assignment."""
    # Create cluster with 10 dissimilar faces (would cause centroid drift)
    # Try to match new dissimilar face
    # Assert: representative matching rejects, centroid would accept

@pytest.mark.asyncio
async def test_deterministic_clustering(db_session, tenant_id):
    """Clustering is batch-size independent."""
    # Cluster 10 images with 3 people → 3 clusters
    # Reset, cluster 20 images with same 3 people → 3 clusters
    # Assert: same cluster count regardless of batch size

@pytest.mark.asyncio
async def test_ward_linkage_clustering(db_session, tenant_id):
    """Ward linkage produces quality clusters."""
    # Create 20 identities representing 5 people
    # Batch-cluster with Ward linkage
    # Assert: 5 clusters created
    # Assert: all clusters pass quality validation
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_incremental_upload_workflow(db_session, tenant_id):
    """Real-world incremental uploads."""
    # Batch 1: 10 images, 3 people → 3 clusters
    # Batch 2: 20 images, same 3 + 1 new → assigns to existing + creates 1 new
    # Batch 3: 5 images, all existing → assigns all to existing
    # Assert: correct cluster assignments, no duplicates
```

### Acceptance Tests

Run original failing test case:

```bash
# Should now produce 3 clusters for both
pytest tests/test_clustering_batch_size.py::test_10_images  # ✅ 3 clusters
pytest tests/test_clustering_batch_size.py::test_20_images  # ✅ 3 clusters (was failing)
```

---

## Success Metrics

### Correctness

- ✅ 10-image test: 3 clusters (baseline)
- ✅ 20-image test: 3 clusters (currently fails)
- ✅ Batch size independence verified
- ✅ Incremental uploads maintain identity continuity

### Quality

- ✅ Min pairwise similarity ≥ threshold (0.65)
- ✅ Representative similarity ≥ threshold
- ✅ Zero centroid drift in Stage 1 assignments

### Performance

- ✅ Stage 1 (online): < 50ms per identity (representative matching)
- ⚠️ Stage 2 (offline Celery): **Claims like "<5s for 100 identities" need empirical validation**
- ⚠️ Ward with 1024-dim data is O(n²) space, O(n³) time - performance degrades with scale
- ✅ Monitor Celery task duration and memory usage with telemetry
- ✅ Cap offline batch at 5,000 identities per task (split larger batches)

**Performance Profiling & Empirical Validation**:

```python
import time
import psutil
import scipy.optimize
from dataclasses import dataclass

@dataclass
class ClusteringPerformanceMetrics:
    """Telemetry for Ward clustering performance."""
    n_identities: int
    n_clusters: int
    duration_seconds: float
    memory_delta_mb: float

    @property
    def throughput(self) -> float:
        """Identities per second."""
        return self.n_identities / self.duration_seconds if self.duration_seconds > 0 else 0


async def _stage2_batch_clustering_profiled(
    self,
    identities: List[MediaIdentity],
) -> tuple[List[IdentityCluster], ClusteringPerformanceMetrics]:
    """Stage 2 with comprehensive performance monitoring."""

    process = psutil.Process()
    mem_before = process.memory_info().rss / 1024 / 1024  # MB
    start_time = time.time()

    clusters = await self._stage2_batch_clustering(identities)

    duration = time.time() - start_time
    mem_after = process.memory_info().rss / 1024 / 1024  # MB
    mem_delta = mem_after - mem_before
    n_clusters = len(clusters)

    metrics = ClusteringPerformanceMetrics(
        n_identities=len(identities),
        n_clusters=n_clusters,
        duration_seconds=duration,
        memory_delta_mb=mem_delta,
    )

    logger.info(
        f"Stage 2 clustering: {len(identities)} identities → {n_clusters} clusters "
        f"in {duration:.2f}s ({metrics.throughput:.1f} ids/s), "
        f"memory +{mem_delta:.1f}MB"
    )

    # Validation: Check against claimed targets
    n = len(identities)
    if n <= 100 and duration > 5.0:
        logger.warning(
            f"⚠️ Clustering slower than claimed target: "
            f"{n} identities took {duration:.2f}s (claimed: <5s for ≤100). "
            f"Update documentation with realistic targets."
        )

    if n > 1000 and duration > 60.0:
        logger.error(
            f"❌ Large batch too slow: {n} identities took {duration:.2f}s. "
            f"Consider splitting into smaller batches (<1000)."
        )

    # Memory warning
    if mem_delta > 500:  # 500MB
        logger.warning(
            f"⚠️ High memory usage: {mem_delta:.1f}MB for {n} identities. "
            f"Ward requires O(n²) space for distance matrix."
        )

    return clusters, metrics


# Benchmark suite for empirical validation
async def benchmark_ward_clustering() -> List[ClusteringPerformanceMetrics]:
    """Empirically validate performance claims with real data."""

    batch_sizes = [10, 50, 100, 200, 500, 1000, 2000]
    results = []

    logger.info("Starting Ward clustering benchmark suite...")

    for n in batch_sizes:
        # Generate synthetic embeddings (or use real data sample)
        embeddings = np.random.randn(n, 512)
        embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

        identities = [
            MediaIdentity(id=uuid4(), embedding=emb.tolist())
            for emb in embeddings
        ]

        # Profile
        _, metrics = await _stage2_batch_clustering_profiled(
            identities,
            threshold=0.7,
        )

        results.append(metrics)

        logger.info(
            f"Benchmark n={n}: {metrics.duration_seconds:.2f}s, "
            f"{metrics.throughput:.1f} identities/s, "
            f"memory={metrics.memory_delta_mb:.1f}MB"
        )

    # Fit complexity curve (O(n²) vs O(n³))
    ns = [r.n_identities for r in results]
    durations = [r.duration_seconds for r in results]

    def power_law(n, a, b):
        return a * (n ** b)

    try:
        (a, b), _ = scipy.optimize.curve_fit(power_law, ns, durations)

        logger.info(
            f"Empirical complexity: O(n^{b:.2f}). "
            f"Coefficient: {a:.6f}."
        )

        # Validate claims
        predicted_100 = power_law(100, a, b)
        predicted_1000 = power_law(1000, a, b)

        if predicted_100 > 5.0:
            logger.warning(
                f"⚠️ Performance claim INVALID: "
                f"Predicted {predicted_100:.2f}s for 100 identities (claimed: <5s). "
                f"Update documentation with realistic targets."
            )
        else:
            logger.info(
                f"✅ Performance claim validated: "
                f"{predicted_100:.2f}s for 100 identities (target: <5s)."
            )

        logger.info(
            f"Predicted performance at 1000: {predicted_1000:.2f}s "
            f"({1000/predicted_1000:.1f} ids/s)"
        )

    except Exception as e:
        logger.error(f"Failed to fit complexity curve: {e}")

    return results


# Dashboard metrics
async def get_clustering_performance_stats(
    session: AsyncSession,
    days: int = 7,
) -> Dict[str, float]:
    """Aggregate performance metrics for monitoring."""

    # Query telemetry logs (implementation depends on logging backend)
    return {
        "avg_duration_100_identities": 3.2,  # seconds
        "p95_duration_100_identities": 4.8,  # seconds
        "max_batch_size": 856,
        "avg_throughput": 45.3,  # identities/second
        "memory_p95_mb": 128.5,
        "outlier_count": 3,  # Batches exceeding 2x expected duration
    }
```

**Action Items**:

1. **Before launch**: Run `benchmark_ward_clustering()` on production hardware
2. **Update docs**: Replace claimed targets with empirical measurements
3. **Production monitoring**: Track metrics via `ClusteringPerformanceMetrics`
4. **Alert on degradation**: If duration exceeds validated targets
5. **Investigate regressions**:
   - Non-normalized embeddings (extra computation)
   - Memory pressure (swapping)
   - Large batch sizes (split into smaller chunks)
   - Hardware differences (dev vs production)

### Heuristic Tuning & Data-Driven Optimization

**⚠️ ARBITRARY KNOBS**: The following constants are starting points requiring tuning with real data:

```python
# Representative selection heuristics (TUNABLE)
QUALITY_WEIGHT = 0.7  # Weight for detection quality (det_score, bbox_area)
DIVERSITY_WEIGHT = 0.3  # Weight for within-cluster diversity
MIN_DIVERSITY_SIMILARITY = 0.85  # Reject candidates too similar to existing reps
MAX_REPS_PER_MEDIA = 3  # Prevent single media from dominating cluster

# Tuning targets (data-driven)
TARGET_ACCEPTANCE_RATE = 0.6  # Aim for 60% of candidates accepted
TARGET_DIVERSITY_REJECTION_RATE = 0.2  # 20% rejected for low diversity
```

**Instrumentation for Tuning**:

```python
from dataclasses import dataclass

@dataclass
class RepresentativeSelectionMetrics:
    """Telemetry for tuning heuristic weights."""
    candidates_evaluated: int = 0
    accepted: int = 0
    rejected_quality: int = 0
    rejected_diversity: int = 0
    rejected_per_media_limit: int = 0

    @property
    def acceptance_rate(self) -> float:
        return self.accepted / self.candidates_evaluated if self.candidates_evaluated else 0

    @property
    def diversity_rejection_rate(self) -> float:
        return self.rejected_diversity / self.candidates_evaluated if self.candidates_evaluated else 0


async def _select_cluster_representatives_instrumented(
    cluster: IdentityCluster,
    max_representatives: int = 10,
) -> tuple[List[MediaIdentity], RepresentativeSelectionMetrics]:
    """Select representatives with full telemetry tracking."""

    metrics = RepresentativeSelectionMetrics()
    identities = cluster.identities
    selected = []
    media_counts = defaultdict(int)

    # Score all candidates
    candidates = []
    for identity in identities:
        quality_score = (
            identity.detection_score * 0.5 +
            (identity.bbox_area / identity.media.image_area) * 0.5
        )

        diversity_score = 1.0
        if selected:
            similarities = [
                cosine_similarity(identity.embedding, rep.embedding)
                for rep in selected
            ]
            diversity_score = 1.0 - np.mean(similarities)

        combined_score = (
            QUALITY_WEIGHT * quality_score +
            DIVERSITY_WEIGHT * diversity_score
        )

        candidates.append({
            "identity": identity,
            "quality_score": quality_score,
            "diversity_score": diversity_score,
            "combined_score": combined_score,
        })

    candidates.sort(key=lambda x: x["combined_score"], reverse=True)

    # Select with rejection tracking
    for candidate in candidates:
        metrics.candidates_evaluated += 1
        identity = candidate["identity"]

        # Reject: per-media limit
        if media_counts[identity.media_id] >= MAX_REPS_PER_MEDIA:
            metrics.rejected_per_media_limit += 1
            logger.debug(
                f"Rejected {identity.id}: per-media limit "
                f"({media_counts[identity.media_id]}/{MAX_REPS_PER_MEDIA})"
            )
            continue

        # Reject: too similar to existing
        if selected:
            max_similarity = max(
                cosine_similarity(identity.embedding, rep.embedding)
                for rep in selected
            )
            if max_similarity > MIN_DIVERSITY_SIMILARITY:
                metrics.rejected_diversity += 1
                logger.debug(
                    f"Rejected {identity.id}: too similar "
                    f"(max_sim={max_similarity:.3f} > {MIN_DIVERSITY_SIMILARITY})"
                )
                continue

        # Accept
        selected.append(identity)
        media_counts[identity.media_id] += 1
        metrics.accepted += 1

        if len(selected) >= max_representatives:
            break

    # Log aggregate metrics
    logger.info(
        f"Representative selection: cluster {cluster.id}, "
        f"evaluated={metrics.candidates_evaluated}, "
        f"accepted={metrics.accepted} ({metrics.acceptance_rate:.1%}), "
        f"diversity_rejections={metrics.rejected_diversity} ({metrics.diversity_rejection_rate:.1%}), "
        f"per_media_rejections={metrics.rejected_per_media_limit}"
    )

    # Tuning recommendations
    if metrics.acceptance_rate < TARGET_ACCEPTANCE_RATE - 0.1:
        logger.warning(
            f"⚠️ Low acceptance rate ({metrics.acceptance_rate:.1%} < {TARGET_ACCEPTANCE_RATE:.1%}). "
            f"Consider: (1) Reduce MIN_DIVERSITY_SIMILARITY (current: {MIN_DIVERSITY_SIMILARITY}), "
            f"(2) Increase MAX_REPS_PER_MEDIA (current: {MAX_REPS_PER_MEDIA}), "
            f"(3) Adjust DIVERSITY_WEIGHT (current: {DIVERSITY_WEIGHT})"
        )

    if metrics.diversity_rejection_rate > TARGET_DIVERSITY_REJECTION_RATE + 0.1:
        logger.warning(
            f"⚠️ High diversity rejection rate ({metrics.diversity_rejection_rate:.1%} > {TARGET_DIVERSITY_REJECTION_RATE:.1%}). "
            f"Increase MIN_DIVERSITY_SIMILARITY to accept more candidates."
        )

    return selected, metrics


# Aggregate tuning dashboard
async def get_representative_selection_stats(
    session: AsyncSession,
    tenant_id: UUID,
    days: int = 7,
) -> Dict[str, Any]:
    """Aggregate metrics for tuning heuristic weights."""

    # Query telemetry logs or database (implementation depends on logging backend)
    # Example output:
    return {
        "avg_acceptance_rate": 0.58,  # 58% (below 60% target)
        "avg_diversity_rejection_rate": 0.25,  # 25% (above 20% target)
        "avg_per_media_rejection_rate": 0.10,
        "total_clusters_evaluated": 142,
        "recommendation": (
            "Reduce MIN_DIVERSITY_SIMILARITY from 0.85 to 0.82 "
            "to improve acceptance rate"
        ),
    }
```

**Tuning Process**:

1. **Baseline** (Week 1): Run with default weights, collect metrics
2. **Analyze**: Check if acceptance rate ≈ 60%, diversity rejection ≈ 20%
3. **Adjust knobs**:
   - Low acceptance → Loosen constraints (↓ MIN_DIVERSITY_SIMILARITY, ↑ MAX_REPS_PER_MEDIA)
   - High diversity rejection → Increase MIN_DIVERSITY_SIMILARITY
   - Cluster quality issues → Increase QUALITY_WEIGHT
4. **A/B test** (Week 2): Run with new weights, compare clustering quality
5. **Iterate**: Repeat until metrics reach targets

---

## Future Enhancements (Phase 4+)

### FAISS Integration

When cluster count > 100, accelerate Stage 1:

```python
async def _stage1_representative_matching_with_faiss(
    self,
    unclustered: List[MediaIdentity],
) -> Tuple[int, List[MediaIdentity]]:
    """Stage 1 with FAISS: sub-linear search O(log n)."""
    # Build FAISS index from all representatives
    # Search for top-3 matches per identity
    # Assign if similarity >= threshold
```

**Trigger**: Cluster count > 100  
**Effort**: 4-6 hours  
**Requires**: Recognition service with FAISS support

### Dendrogram Visualization

```python
from scipy.cluster.hierarchy import dendrogram

def visualize_cluster_hierarchy(embeddings, labels):
    """Generate dendrogram showing hierarchical clustering structure."""
    # Useful for debugging and understanding cluster relationships
```

### Automatic Cluster Splitting

```python
async def split_low_quality_cluster(
    self,
    cluster_id: UUID,
) -> List[IdentityCluster]:
    """Re-cluster members of failed quality validation."""
    members = await self._get_cluster_members(cluster_id)
    await self._delete_cluster(cluster_id)
    return await self._stage3_batch_clustering(members)
```

---

## Algorithm Constraints & Operational Limits

### Ward Linkage Requirements

**CRITICAL**: Ward linkage ONLY works with Euclidean distance metric:

- `AgglomerativeClustering(linkage='ward', metric='cosine')` → **ERROR**
- `AgglomerativeClustering(linkage='ward', metric='euclidean')` → **CORRECT**

**For Cosine Similarity**:

1. Normalize all embeddings to unit vectors (L2 norm = 1.0)
2. Use Euclidean distance on normalized embeddings
3. Relationship: `||a - b||² = 2(1 - cos(a,b))` for unit vectors
4. Threshold conversion: `euclidean_distance = sqrt(2 * (1 - cosine_threshold))`

**⚠️ WARD CHUNKING TRADE-OFF**: Processing chunks of identities (e.g., 500 at a time) will **NOT** produce the same clusters as global agglomeration because:

- Ward minimizes within-cluster variance **globally** at each merge step
- Chunk boundaries prevent cross-chunk merges that would occur in global clustering
- Example: Face A in chunk 1 and Face B in chunk 2 might be merged in global clustering, but chunking forces them into separate clusters

**Solution**: Use Celery offline clustering (see Performance Limits section) to run global Ward on all unclustered identities without chunk limits.

**Threshold Validation** (CRITICAL - Guards Against Bad Inputs):

```python
def _validate_and_convert_threshold(
    self,
    cosine_threshold: float,
    embeddings: np.ndarray,
) -> float:
    """
    Validate cosine threshold and convert to Euclidean distance.

    CRITICAL: This conversion is ONLY valid for unit-normalized vectors.
    Verifies normalization before conversion to catch invalid inputs.

    Args:
        cosine_threshold: Similarity threshold in [0, 1]
        embeddings: Array of embeddings to verify normalization

    Returns:
        Euclidean distance threshold

    Raises:
        ValueError: If threshold out of range or vectors not normalized
    """
    # Guard 1: Type and range validation
    if not isinstance(cosine_threshold, (int, float)):
        raise TypeError(
            f"Threshold must be numeric, got {type(cosine_threshold).__name__}"
        )

    if not 0.0 <= cosine_threshold <= 1.0:
        raise ValueError(
            f"❌ Cosine threshold must be in [0, 1], got {cosine_threshold}. "
            f"Did you accidentally pass a distance instead of similarity?"
        )

    # Guard 2: Verify embeddings are unit-normalized
    norms = np.linalg.norm(embeddings, axis=1)
    non_unit_mask = np.abs(norms - 1.0) > 1e-5

    if non_unit_mask.any():
        non_unit_count = non_unit_mask.sum()
        sample_norms = norms[non_unit_mask][:5]  # Show first 5
        raise ValueError(
            f"❌ Found {non_unit_count} non-unit vectors. "
            f"Threshold conversion requires normalized embeddings. "
            f"Sample norms: {sample_norms}. "
            f"Call normalize() before clustering."
        )

    # Guard 3: Clamp to avoid numerical issues
    clamped = np.clip(cosine_threshold, 0.0, 1.0)
    if clamped != cosine_threshold:
        logger.warning(
            f"Clamped threshold {cosine_threshold} → {clamped}"
        )

    # Convert to Euclidean distance
    distance = np.sqrt(2.0 * (1.0 - clamped))

    # Guard 4: Verify result is in valid range [0, sqrt(2)]
    max_distance = np.sqrt(2.0)
    if not (0.0 <= distance <= max_distance + 1e-6):
        raise ValueError(
            f"❌ Invalid Euclidean distance: {distance}. "
            f"Expected [0, {max_distance:.4f}]. "
            f"This indicates a bug in threshold conversion."
        )

    logger.debug(
        f"Threshold conversion: cosine {clamped:.3f} → "
        f"Euclidean {distance:.3f} "
        f"(verified {len(embeddings)} unit vectors)"
    )

    return distance


# Usage in clustering
async def _stage2_batch_clustering(self, identities, threshold):
    embeddings = np.array([i.embedding for i in identities])

    # REQUIRED: Validate and convert threshold WITH embeddings
    threshold_euclidean = self._validate_and_convert_threshold(
        threshold,
        embeddings,  # Pass for norm verification
    )

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=threshold_euclidean,
        metric='euclidean',
        linkage='ward',
    )
    labels = clustering.fit_predict(embeddings)
    return labels
```

**Alternative** (if you need cosine metric):

- Use `linkage='average'` or `linkage='complete'` with `metric='cosine'`
- Trade-off: Different clustering semantics (linkage criterion)
- Ward minimizes variance; average/complete use different merge criteria

### Performance Limits

**Ward Linkage Complexity**: O(n²) to O(n³)

- **No hard 500-identity limit**: Chunking produces different merges than global agglomeration
- **Chunking breaks cluster structure**: Cross-chunk faces won't be considered for merging
- FAISS does NOT accelerate Stage 2 (only Stage 1 representative matching)

**Hybrid Online/Offline Strategy**:

1. **Online (synchronous)**: Stage 1 representative matching only

   - Fast, < 50ms per identity
   - Handles user-facing requests
   - Assigns to existing clusters with high confidence

2. **Offline (Celery)**: Stage 2 Ward linkage batch clustering
   - Enqueue periodic job after upload batches
   - Re-cluster all unassigned or "dirty" clusters
   - Use global Ward linkage (no chunking limits)
   - Split/merge clusters as needed
   - Refresh materialized views before next batch

**Implementation**:

```python
# Online: Fast representative matching
async def cluster_identities_online(self) -> Dict[str, int]:
    """Synchronous clustering: Stage 1 only."""
    unclustered = await self._get_unclustered_identities()
    if not unclustered:
        return {"assigned": 0, "enqueued_for_batch": 0}

    existing_cluster_ids = await self._get_cluster_ids()
    if not existing_cluster_ids:
        # Enqueue Celery job for batch clustering
        await self._enqueue_batch_clustering(unclustered)
        return {"assigned": 0, "enqueued_for_batch": len(unclustered)}

    # Stage 1: Representative matching
    assigned_count, still_unclustered = await self._stage1_representative_matching(
        unclustered, existing_cluster_ids
    )

    # Enqueue remaining for offline batch clustering
    if still_unclustered:
        await self._enqueue_batch_clustering(still_unclustered)

    return {
        "assigned": assigned_count,
        "enqueued_for_batch": len(still_unclustered)
    }

# Offline: Global Ward linkage (Celery task)
@celery_app.task
async def batch_cluster_task(tenant_id: UUID):
    """Offline batch clustering with global Ward linkage."""
    service = IdentityClusteringService(session, tenant_id)

    # Get all unassigned + dirty cluster members
    identities = await service._get_unclustered_and_dirty_identities()

    if not identities:
        return {"clusters_created": 0}

    # Global Ward linkage (no chunking)
    clusters = await service._stage2_batch_clustering(identities)

    # Refresh materialized views
    await service._refresh_cluster_centroids()

    return {
        "clusters_created": len(clusters),
        "identities_processed": len(identities)
    }
```

**Safeguards**:

1. Monitor Celery task duration and memory usage
2. Cap offline batch at 5,000 identities per task (split if larger)
3. If >5,000 unclustered, use hierarchical strategy (see below)
4. Track "dirty" clusters for incremental re-clustering

**Large-Batch Strategy** (>5,000 identities):

```python
async def batch_cluster_large(
    self,
    identity_ids: List[UUID],
    threshold: float,
) -> int:
    """Handle >5,000 identities with hierarchical clustering."""

    BATCH_SIZE = 5000
    batches = [
        identity_ids[i:i+BATCH_SIZE]
        for i in range(0, len(identity_ids), BATCH_SIZE)
    ]

    logger.info(
        f"Large batch clustering: {len(identity_ids)} identities "
        f"split into {len(batches)} batches of {BATCH_SIZE}"
    )

    # Step 1: Run Ward on each batch independently
    batch_clusters = []
    for i, batch in enumerate(batches):
        logger.info(f"Processing batch {i+1}/{len(batches)}")
        clusters = await self._stage2_batch_clustering_by_ids(batch, threshold)
        batch_clusters.append(clusters)

    # Step 2: Extract representatives from each batch's clusters
    all_reps = []
    rep_to_batch_cluster = {}  # Track which batch cluster each rep came from

    for batch_idx, clusters in enumerate(batch_clusters):
        for cluster in clusters:
            # Select 3 best representatives per cluster
            reps = await self._select_representatives(
                cluster.identities,
                max_count=3,
            )
            all_reps.extend(reps)

            for rep in reps:
                rep_to_batch_cluster[rep.id] = (batch_idx, cluster.id)

    logger.info(
        f"Extracted {len(all_reps)} representatives from "
        f"{sum(len(bc) for bc in batch_clusters)} batch clusters"
    )

    # Step 3: Run Ward on representatives (much smaller dataset)
    rep_embeddings = np.array([r.embedding for r in all_reps])
    threshold_euclidean = self._validate_and_convert_threshold(
        threshold,
        rep_embeddings,
    )

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=threshold_euclidean,
        metric='euclidean',
        linkage='ward',
    )
    final_labels = clustering.fit_predict(rep_embeddings)

    # Step 4: Propagate merged cluster IDs back to original identities
    merged_cluster_map = {}  # batch_cluster_id -> final_cluster_id

    for rep, final_label in zip(all_reps, final_labels):
        batch_idx, batch_cluster_id = rep_to_batch_cluster[rep.id]
        merged_cluster_map[(batch_idx, batch_cluster_id)] = final_label

    # Create final clusters and reassign identities
    final_clusters = defaultdict(list)
    for batch_idx, clusters in enumerate(batch_clusters):
        for cluster in clusters:
            final_label = merged_cluster_map[(batch_idx, cluster.id)]
            final_clusters[final_label].extend(cluster.identities)

    # Persist final clusters
    created_count = 0
    for final_label, identities in final_clusters.items():
        await self._create_cluster_with_representatives(
            identities,
            threshold,
        )
        created_count += 1

    logger.info(
        f"Hierarchical clustering complete: {len(batch_clusters)} batches "
        f"→ {created_count} final clusters"
    )

    return created_count
```

### Normalization Requirements

**MUST normalize at these points**:

1. `_save_identities()`: Normalize before storing in `media_identities.embedding`
2. `_add_representative_embedding()`: Normalize before storing in `identity_cluster_representatives.embedding`
3. Stage 1 matching: Normalize query vector before comparison
4. Stage 2 clustering: Normalize all embeddings before AgglomerativeClustering

**Enforcement Mechanism** (3-layer defense):

**Layer 1: Database CHECK Constraints**

```sql
-- Create vector norm function (add to migration)
CREATE OR REPLACE FUNCTION vector_norm(v vector) RETURNS float AS $$
DECLARE
    arr float[];
    sum_sq float := 0;
    elem float;
BEGIN
    -- Convert vector to array
    arr := v::float[];

    -- Compute sum of squares
    FOREACH elem IN ARRAY arr LOOP
        sum_sq := sum_sq + (elem * elem);
    END LOOP;

    -- Return L2 norm
    RETURN sqrt(sum_sq);
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT;

-- Add CHECK constraints (tolerance: ±0.01 for floating-point arithmetic)
ALTER TABLE media_identities
ADD CONSTRAINT embedding_normalized
CHECK (ABS(vector_norm(embedding) - 1.0) < 0.01);

ALTER TABLE identity_cluster_representatives
ADD CONSTRAINT embedding_normalized
CHECK (ABS(vector_norm(embedding) - 1.0) < 0.01);

-- Test the constraint
INSERT INTO media_identities (embedding) VALUES ('[0.5, 0.5, 0.5]');
-- ERROR: new row violates check constraint "embedding_normalized"
-- DETAIL: Failing row norm: 0.866 (not ≈ 1.0)
```

**Layer 2: Application-Level Normalization**

```python
import numpy as np

def normalize_embedding(embedding: np.ndarray) -> np.ndarray:
    """Normalize embedding to unit length."""
    norm = np.linalg.norm(embedding)

    if norm == 0:
        raise ValueError("Cannot normalize zero vector")

    normalized = embedding / norm

    # Verify normalization succeeded
    new_norm = np.linalg.norm(normalized)
    if abs(new_norm - 1.0) > 1e-6:
        raise ValueError(
            f"Normalization failed: norm={new_norm:.9f} (expected 1.0)"
        )

    return normalized


def _verify_normalized(
    embedding: np.ndarray,
    context: str = "",
) -> None:
    """Assert embedding is unit-normalized before database write.

    Args:
        embedding: Vector to verify
        context: Description for error message

    Raises:
        ValueError: If norm deviates from 1.0 by >1e-5
    """
    norm = np.linalg.norm(embedding)
    tolerance = 1e-5

    if abs(norm - 1.0) > tolerance:
        raise ValueError(
            f"❌ {context or 'Embedding'} not normalized: norm={norm:.9f}. "
            f"Expected 1.0 ± {tolerance}. "
            f"Call normalize_embedding() before storing."
        )


# Usage in face detection
async def create_media_identity(
    session: AsyncSession,
    face_embedding: np.ndarray,
    media_id: UUID,
) -> MediaIdentity:
    """Create identity with normalized embedding."""

    # Normalize at creation
    normalized = normalize_embedding(face_embedding)

    # Verify before insert (defensive check)
    _verify_normalized(normalized, "MediaIdentity.embedding")

    identity = MediaIdentity(
        media_id=media_id,
        embedding=normalized.tolist(),
    )

    session.add(identity)
    await session.flush()  # DB constraint will catch any drift

    return identity
```

**Layer 3: Periodic Drift Detection**

```python
async def audit_embedding_norms(
    session: AsyncSession,
    limit: int = 1000,
) -> Dict[str, Any]:
    """Check stored embeddings for normalization drift.

    Run periodically (e.g., daily) to catch:
    - Manual database edits bypassing constraints
    - Floating-point accumulation errors
    - Migration bugs
    """
    stmt = (
        select(MediaIdentity.id, MediaIdentity.embedding)
        .limit(limit)
    )
    results = (await session.execute(stmt)).all()

    drift_detected = []
    for identity_id, embedding in results:
        norm = np.linalg.norm(np.array(embedding))
        deviation = abs(norm - 1.0)

        if deviation > 1e-5:
            drift_detected.append({
                "identity_id": identity_id,
                "norm": norm,
                "deviation": deviation,
            })

    if drift_detected:
        logger.error(
            f"⚠️ Norm drift detected in {len(drift_detected)} embeddings. "
            f"Sample: {drift_detected[:5]}"
        )
        # Alert monitoring system
        raise ValueError("Embedding normalization drift detected")

    logger.info(f"✅ Audited {len(results)} embeddings, all normalized")

    return {
        "audited_count": len(results),
        "drift_detected_count": len(drift_detected),
        "sample_drift": drift_detected[:5],
    }
```

**Unit Tests**:

```python
import pytest

def test_normalize_embedding():
    """Test normalization produces unit vectors."""
    embedding = np.array([3.0, 4.0])  # Norm = 5.0
    normalized = normalize_embedding(embedding)

    assert np.allclose(normalized, [0.6, 0.8])
    assert np.allclose(np.linalg.norm(normalized), 1.0)


def test_verify_normalized_rejects_non_unit():
    """Test verification catches non-unit vectors."""
    bad_embedding = np.array([3.0, 4.0])  # Norm = 5.0

    with pytest.raises(ValueError, match="not normalized"):
        _verify_normalized(bad_embedding)


async def test_database_constraint_rejects_non_unit(session):
    """Test database CHECK constraint catches drift."""
    bad_embedding = [0.5, 0.5, 0.5]  # Norm ≈ 0.866

    identity = MediaIdentity(
        media_id=uuid4(),
        embedding=bad_embedding,  # Bypass app normalization
    )
    session.add(identity)

    with pytest.raises(IntegrityError, match="embedding_normalized"):
        await session.flush()
```

### Skew & Duplicate Handling

**Risk**: Large batches with many near-duplicates of one person

- Example: 100 faces from one photo shoot
- Result: Representative set dominated by that person
- Impact: Misassignment of other identities

**Mitigation**:

1. Per-media limit: Max 3 representatives per media_id
2. Diversity-aware selection: Prefer dissimilar samples (see Heuristic Tuning section)
3. Pre-clustering deduplication: Top 3 per media in `_deduplicate_per_media()`

**⚠️ DEDUPLICATION TRADE-OFF**: Limiting to 3 faces per media assumes upstream face detection produces **duplicates**, not distinct people. If your face detector does NOT produce duplicates, this cap may drop legitimate multi-face detections (e.g., group photos with 4+ people).

**Verification Strategy**:

```python
MAX_REPS_PER_MEDIA = 3

async def _deduplicate_per_media(
    self,
    identities: List[MediaIdentity],
) -> List[MediaIdentity]:
    """De-duplicate with verification monitoring."""
    by_media = defaultdict(list)
    for identity in identities:
        by_media[identity.media_id].append(identity)

    deduplicated = []
    dropped_count = 0
    multi_face_media = {}  # Track rejected faces for verification

    for media_id, media_identities in by_media.items():
        if len(media_identities) <= MAX_REPS_PER_MEDIA:
            deduplicated.extend(media_identities)
        else:
            # Log potential legitimate multi-face detection
            logger.warning(
                f"⚠️ Media {media_id}: {len(media_identities)} faces detected. "
                f"Keeping top {MAX_REPS_PER_MEDIA} by confidence. "
                f"Verify these are duplicates, not distinct faces."
            )

            sorted_by_conf = sorted(
                media_identities,
                key=lambda i: i.detection_score,
                reverse=True,
            )

            selected = sorted_by_conf[:MAX_REPS_PER_MEDIA]
            rejected = sorted_by_conf[MAX_REPS_PER_MEDIA:]

            deduplicated.extend(selected)
            dropped_count += len(rejected)
            multi_face_media[media_id] = {
                "selected": selected,
                "rejected": rejected,
            }

    # Verify if rejected faces are duplicates or distinct
    for media_id, faces in multi_face_media.items():
        selected_embs = np.array([s.embedding for s in faces["selected"]])
        rejected_embs = np.array([r.embedding for r in faces["rejected"]])

        # Compute pairwise similarities between selected and rejected
        similarities = []
        for rej_emb in rejected_embs:
            for sel_emb in selected_embs:
                sim = cosine_similarity(rej_emb, sel_emb)
                similarities.append(sim)

        avg_sim = np.mean(similarities) if similarities else 0.0

        if avg_sim > 0.95:
            logger.info(
                f"✅ Media {media_id}: Rejected faces are near-duplicates "
                f"(avg_sim={avg_sim:.3f}). Cap is working correctly."
            )
        else:
            logger.warning(
                f"❌ Media {media_id}: Rejected faces may be DISTINCT people "
                f"(avg_sim={avg_sim:.3f} < 0.95). "
                f"Consider increasing MAX_REPS_PER_MEDIA or investigating "
                f"face detection duplicate behavior."
            )

    if dropped_count > 0:
        logger.info(
            f"Deduplication: Dropped {dropped_count}/{len(identities)} faces "
            f"from {len(multi_face_media)} media items. "
            f"Run audit_multi_face_media() to verify duplicates vs distinct."
        )

    return deduplicated


# Data-driven validation (run on sample dataset)
async def audit_multi_face_media(
    session: AsyncSession,
    tenant_id: UUID,
    sample_size: int = 100,
) -> Dict[str, Any]:
    """Check if per-media cap is dropping legitimate faces."""

    # Find media with many detected faces
    stmt = (
        select(
            MediaIdentity.media_id,
            func.count(MediaIdentity.id).label("face_count"),
        )
        .where(MediaIdentity.tenant_id == tenant_id)
        .group_by(MediaIdentity.media_id)
        .having(func.count(MediaIdentity.id) > MAX_REPS_PER_MEDIA)
        .limit(sample_size)
    )
    results = (await session.execute(stmt)).all()

    duplicate_ratio_samples = []

    for media_id, face_count in results:
        # Fetch all faces for this media
        stmt = select(MediaIdentity).where(MediaIdentity.media_id == media_id)
        faces = (await session.execute(stmt)).scalars().all()

        # Compute pairwise similarities
        embeddings = np.array([f.embedding for f in faces])

        # Count duplicates (similarity > 0.95)
        duplicate_count = 0
        for i in range(len(embeddings)):
            for j in range(i+1, len(embeddings)):
                if cosine_similarity(embeddings[i], embeddings[j]) > 0.95:
                    duplicate_count += 1

        total_pairs = face_count * (face_count - 1) // 2
        duplicate_ratio = duplicate_count / total_pairs if total_pairs > 0 else 0
        duplicate_ratio_samples.append(duplicate_ratio)

        if duplicate_ratio < 0.3:
            logger.warning(
                f"Media {media_id}: {face_count} faces, "
                f"only {duplicate_ratio:.1%} are duplicates. "
                f"Per-media cap may be dropping distinct people."
            )

    avg_duplicate_ratio = np.mean(duplicate_ratio_samples) if duplicate_ratio_samples else 0

    report = {
        "media_sampled": len(results),
        "avg_duplicate_ratio": avg_duplicate_ratio,
        "recommendation": None,
    }

    if avg_duplicate_ratio > 0.7:
        report["recommendation"] = (
            f"✅ High duplicate ratio ({avg_duplicate_ratio:.1%}). "
            f"MAX_REPS_PER_MEDIA={MAX_REPS_PER_MEDIA} is appropriate."
        )
    elif avg_duplicate_ratio < 0.3:
        report["recommendation"] = (
            f"❌ Low duplicate ratio ({avg_duplicate_ratio:.1%}). "
            f"Face detection is NOT producing duplicates. "
            f"Increase MAX_REPS_PER_MEDIA to 5-10 or remove cap entirely."
        )
    else:
        report["recommendation"] = (
            f"⚠️ Mixed duplicate ratio ({avg_duplicate_ratio:.1%}). "
            f"Monitor per-media rejections and tune cap as needed."
        )

    logger.info(f"Multi-face media audit: {report}")
    return report
```

**Action Items**:

1. Run `audit_multi_face_media()` on production dataset after 1 week
2. If avg_duplicate_ratio < 30%, increase `MAX_REPS_PER_MEDIA` to 5-10
3. If avg_duplicate_ratio > 70%, current cap (3) is appropriate
4. Monitor rejection logs for media with distinct people being dropped

## Logging & Monitoring

### Context Vector Quality Monitoring

**Decision Point**: Keep 1024-D embeddings (512-D identity + 512-D context) or reduce to 512-D identity-only?

**Monitoring Strategy**:

```python
# Per-batch aggregate metrics (not per-face logs)
async def scan_batch_with_context_metrics(
    self,
    media_items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Scan batch and collect context feature telemetry."""

    batch_telemetry = {
        "total_faces": 0,
        "faces_with_age": 0,
        "faces_with_gender": 0,
        "bbox_areas": [],
        "det_scores": [],
        "context_norms": [],
        "media_with_defaults_only": [],
    }

    for item in media_items:
        image = await self._fetch_image(item["media_url"])
        faces, face_telemetry = self.provider.analyze_with_telemetry(image)

        batch_telemetry["total_faces"] += face_telemetry["face_count"]
        batch_telemetry["faces_with_age"] += face_telemetry["age_present_count"]
        batch_telemetry["faces_with_gender"] += face_telemetry["gender_present_count"]
        batch_telemetry["bbox_areas"].extend(face_telemetry.get("bbox_areas", []))
        batch_telemetry["det_scores"].extend(face_telemetry.get("det_scores", []))
        batch_telemetry["context_norms"].append(face_telemetry["avg_context_norm"])

        # Track media with all defaults
        if (face_telemetry["age_present_ratio"] == 0.0 and
            face_telemetry["gender_present_ratio"] == 0.0 and
            face_telemetry["face_count"] > 0):
            batch_telemetry["media_with_defaults_only"].append(item["media_id"])

    # Aggregate statistics
    total_faces = batch_telemetry["total_faces"]
    if total_faces > 0:
        age_ratio = batch_telemetry["faces_with_age"] / total_faces
        gender_ratio = batch_telemetry["faces_with_gender"] / total_faces

        logger.info(
            f"Context feature quality: {total_faces} faces, "
            f"age_present={age_ratio:.1%}, gender_present={gender_ratio:.1%}, "
            f"avg_bbox_area={np.mean(batch_telemetry['bbox_areas']):.0f}, "
            f"avg_det_score={np.mean(batch_telemetry['det_scores']):.3f}, "
            f"avg_context_norm={np.mean(batch_telemetry['context_norms']):.3f}"
        )

        # Warning if all defaults
        if age_ratio == 0.0 and gender_ratio == 0.0:
            logger.warning(
                f"⚠️ Model not providing age/gender for {total_faces} faces. "
                f"Context vectors are using defaults. "
                f"Consider reducing to 512-D identity-only embeddings."
            )

            # List sample media IDs with defaults
            sample_media = batch_telemetry["media_with_defaults_only"][:5]
            logger.info(f"Sample media with default context: {sample_media}")

    return batch_telemetry
```

**Offline Analysis** (run periodically):

```python
async def audit_context_features(tenant_id: UUID, sample_size: int = 100):
    """Sample embeddings and check context feature quality."""

    # Sample recent identities
    stmt = (
        select(MediaIdentity)
        .where(MediaIdentity.tenant_id == tenant_id)
        .order_by(MediaIdentity.created_at.desc())
        .limit(sample_size)
    )
    identities = (await session.execute(stmt)).scalars().all()

    # Analyze context vectors (last 512 dimensions)
    context_vecs = [np.array(i.embedding)[512:] for i in identities]
    context_norms = [np.linalg.norm(vec) for vec in context_vecs]

    # Check for near-zero context (all defaults)
    near_zero_count = sum(1 for norm in context_norms if norm < 0.01)

    report = {
        "sample_size": len(identities),
        "avg_context_norm": np.mean(context_norms),
        "min_context_norm": np.min(context_norms),
        "max_context_norm": np.max(context_norms),
        "near_zero_ratio": near_zero_count / len(identities),
        "recommendation": None
    }

    # Recommendation
    if report["near_zero_ratio"] > 0.9:
        report["recommendation"] = (
            "REDUCE to 512-D: >90% of context vectors are near-zero. "
            "Model not providing age/gender. Switch to identity-only embeddings."
        )
    elif report["near_zero_ratio"] > 0.5:
        report["recommendation"] = (
            "INVESTIGATE: >50% near-zero context vectors. "
            "Check if model supports age/gender or if defaults are intentional."
        )
    else:
        report["recommendation"] = (
            "KEEP 1024-D: Context features are being populated. "
            "Age/gender data is available from model."
        )

    logger.info(f"Context feature audit: {report}")
    return report
```

**Dashboard Metrics** (if context features are present):

- Histograms: age distribution, gender distribution
- Skew alerts: Check for uniform distributions (indicates defaults)
- Correlation: Does age/gender improve clustering quality?

**Migration Path** (if reducing to 512-D):

```python
# Option 1: Drop context, keep identity portion
async def migrate_to_512d():
    """Extract identity portion (first 512 dims) from existing embeddings."""
    stmt = select(MediaIdentity)
    identities = (await session.execute(stmt)).scalars().all()

    for identity in identities:
        full_embedding = np.array(identity.embedding)
        identity_only = full_embedding[:512]  # First 512 dims
        identity.embedding = identity_only.tolist()

    await session.commit()

    # Update vector column dimension
    await session.execute(text(
        "ALTER TABLE media_identities "
        "ALTER COLUMN embedding TYPE vector(512)"
    ))
```

### Stage 1: Representative Matching

```python
async def _stage1_representative_matching(
    self,
    unclustered: List[MediaIdentity],
    cluster_ids: List[UUID],
) -> Tuple[int, List[MediaIdentity]]:
    """Stage 1 with comprehensive logging."""
    still_unclustered = []
    assigned_count = 0

    # Telemetry counters
    telemetry = {
        "rep_matches_found": 0,
        "rep_matches_below_threshold": 0,
        "rep_assignments": 0,
        "rep_creations": 0,
    }

    for identity in unclustered:
        identity_vector = _normalize_vector(np.array(identity.embedding))
        best_cluster_id, best_similarity = await self._match_against_representatives(
            identity_vector, cluster_ids
        )

        if best_cluster_id:
            telemetry["rep_matches_found"] += 1

            if best_similarity >= self.threshold:
                await self._assign_to_cluster_by_id(
                    identity, identity_vector, best_cluster_id, best_similarity
                )
                await self._add_representative_embedding(best_cluster_id, identity)

                telemetry["rep_assignments"] += 1
                assigned_count += 1

                logger.info(
                    f"Stage 1: Assigned identity {identity.id} (media {identity.media_id}) "
                    f"to cluster {best_cluster_id} (similarity={best_similarity:.3f}, "
                    f"threshold={self.threshold:.3f})"
                )
            else:
                telemetry["rep_matches_below_threshold"] += 1
                still_unclustered.append(identity)

                logger.debug(
                    f"Stage 1: Identity {identity.id} similarity {best_similarity:.3f} "
                    f"below threshold {self.threshold:.3f}"
                )
        else:
            still_unclustered.append(identity)

    logger.info(
        f"Stage 1 complete: {telemetry['rep_assignments']}/{len(unclustered)} assigned, "
        f"{len(still_unclustered)} remain. Telemetry: {telemetry}"
    )

    return assigned_count, still_unclustered
```

### Stage 2: Ward Linkage Batch Clustering

```python
async def _stage2_batch_clustering(
    self,
    identities: List[MediaIdentity],
) -> List[IdentityCluster]:
    """Stage 2 with cluster quality logging."""
    # ... clustering logic ...

    # Log cluster statistics
    cluster_sizes = [len(members) for members in clusters_by_label.values()]

    logger.info(
        f"Stage 2: Created {len(created_clusters)} clusters from {len(identities)} identities. "
        f"Sizes: min={min(cluster_sizes)}, max={max(cluster_sizes)}, "
        f"mean={np.mean(cluster_sizes):.1f}, median={np.median(cluster_sizes):.1f}"
    )

    # Compute and log cluster quality metrics
    for cluster, members in zip(created_clusters, clusters_by_label.values()):
        if len(members) >= 2:
            # Pairwise similarities
            member_embeddings = [
                _normalize_vector(np.array(m.embedding)) for m in members
            ]
            pairwise_sims = [
                cosine_similarity(e1, e2)
                for i, e1 in enumerate(member_embeddings)
                for e2 in member_embeddings[i+1:]
            ]

            min_sim = min(pairwise_sims)
            avg_sim = np.mean(pairwise_sims)

            logger.info(
                f"Cluster {cluster.id}: {len(members)} members, "
                f"min_similarity={min_sim:.3f}, avg_similarity={avg_sim:.3f}"
            )

            # Alert on low-quality clusters
            if min_sim < self.threshold:
                logger.warning(
                    f"⚠️ Low-quality cluster {cluster.id}: min_similarity={min_sim:.3f} "
                    f"below threshold {self.threshold:.3f}"
                )

    return created_clusters
```

### Representative Management Telemetry

```python
class IdentityClusteringService:
    def __init__(self, ...):
        self._telemetry = {
            "rep_candidates_evaluated": 0,
            "rep_added": 0,
            "rep_rejected_per_media_limit": 0,
            "rep_rejected_diversity": 0,
            "rep_evicted": 0,
        }

    async def _add_representative_embedding(
        self,
        cluster_id: UUID,
        identity: MediaIdentity,
    ) -> None:
        """Add representative with telemetry."""
        self._telemetry["rep_candidates_evaluated"] += 1

        # Check per-media limit
        existing_from_media = await self._count_representatives_for_media(
            cluster_id, identity.media_id
        )
        if existing_from_media >= MAX_REPRESENTATIVES_PER_MEDIA:
            self._telemetry["rep_rejected_per_media_limit"] += 1
            logger.info(
                f"Rep rejected (per-media limit): cluster={cluster_id}, "
                f"media={identity.media_id} ({existing_from_media}/{MAX_REPRESENTATIVES_PER_MEDIA})"
            )
            return

        # Check diversity
        existing_reps = await self._get_cluster_representatives(cluster_id)
        if existing_reps:
            normalized_embedding = _normalize_vector(np.array(identity.embedding))
            similarities = [
                cosine_similarity(normalized_embedding, rep) for rep in existing_reps
            ]
            diversity_score = min(similarities)

            if diversity_score > MIN_DIVERSITY_SIMILARITY:
                self._telemetry["rep_rejected_diversity"] += 1
                logger.info(
                    f"Rep rejected (diversity): cluster={cluster_id}, "
                    f"diversity_score={diversity_score:.3f} > {MIN_DIVERSITY_SIMILARITY}"
                )
                return

        # Add/evict logic...
        self._telemetry["rep_added"] += 1
        logger.info(
            f"Rep added: cluster={cluster_id}, identity={identity.id}, "
            f"confidence={identity.confidence:.3f}, diversity={diversity_score:.3f}"
        )

    def get_telemetry(self) -> Dict[str, int]:
        """Return telemetry counters for monitoring."""
        return self._telemetry.copy()
```

### Celery Batch Clustering Metrics

```python
@celery_app.task
async def batch_cluster_task(tenant_id: UUID):
    """Offline batch clustering with metrics."""
    start_time = time.time()

    service = IdentityClusteringService(session, tenant_id)
    identities = await service._get_unclustered_and_dirty_identities()

    if not identities:
        return {"clusters_created": 0, "duration": 0}

    clusters = await service._stage2_batch_clustering(identities)

    # Refresh materialized views
    await service._refresh_cluster_centroids()

    duration = time.time() - start_time

    metrics = {
        "clusters_created": len(clusters),
        "identities_processed": len(identities),
        "duration_seconds": duration,
        "throughput_identities_per_sec": len(identities) / duration if duration > 0 else 0,
    }

    logger.info(f"Batch clustering complete: {metrics}")

    return metrics
```

## Rollback Plan

1. **Feature flag**: `ENABLE_HYBRID_CLUSTERING = False` → reverts to old method
2. **Data safety**: Representatives are additive, don't break existing clusters
3. **Migration**: Can roll back by dropping `identity_cluster_representatives` table
4. **API compatibility**: Maintains same interface, transparent to callers

---

## Key Decisions & Rationale

### Why Representative Embeddings First?

1. **Directly solves root cause** (centroid drift)
2. **Proven in production** (WordPress plugin)
3. **Simpler than full rewrite** (incremental improvement)
4. **No dependencies** (works immediately)

### Why Ward Linkage for Stage 3?

1. **Literature validated** (ML textbook, 2,063 faces)
2. **Deterministic** (same inputs → same outputs)
3. **Minimizes variance** (quality clusters)
4. **Built-in** (scikit-learn, no new dependencies)

### Why Two Stages (Not Three)?

1. **Stage 1**: Representative matching handles existing clusters, no drift
2. **Stage 2**: Ward linkage creates new clusters, deterministic and no drift
3. **No Stage 3**: Centroid fallback REMOVED - reintroduces the drift we're fixing

**Critical**: Any centroid-based decision path reintroduces drift. The fix is complete elimination of averaged centroids from the matching pipeline.

---

## Appendix

### Research Validation

#### References

- **Debug Analysis**: `debug-clustering-batch-size-regression.md`
- **WordPress Plugin**: `hybrid-face-matching-strategy.md`
- **ML Textbook**: "Introduction to Machine Learning with Python" Chapter 3
- **Current Code**: `recognition/application/identity_clustering_service.py`

---

**Created**: 2025-11-20  
**Status**: Ready for implementation  
**Est. Completion**: 2-3 weeks

---

## Task Completion Tracking

### Stage 1: Representatives (Schema + Storage + Matching)

**1.1 Database Schema**:

- [x] 1.1.1 Create `IdentityClusterRepresentative` model in `db/models.py`
- [x] 1.1.2 Update migration with `identity_cluster_representatives` table
- [x] 1.1.3 Add vector(1024) column with normalization CHECK constraint
- [x] 1.1.4 Add indexes: tenant_id, cluster_id, vector index (ivfflat/cosine)
- [x] 1.1.5 Add unique constraint: (cluster_id, identity_id)
- [x] 1.1.6 Add RLS policies (tenant isolation)
- [x] 1.1.7 Test schema with greenfield database

**1.2 Core Methods**:

- [x] 1.2.1 Implement `_add_representative_embedding()` with diversity scoring
- [x] 1.2.2 Implement `_get_cluster_representatives()`
- [x] 1.2.3 Implement `_match_against_representatives()`
- [x] 1.2.4 Update `_create_cluster_with_centroid()` to populate representatives

**1.3 Testing**:

- [x] 1.3.1 Unit tests: representative storage/retrieval/matching
- [x] 1.3.2 Integration test: representative matching avoids centroid drift
- [x] 1.3.3 Verify representatives table populated correctly

### Stage 2: Global Ward Clustering (Sync for Small Batches, Async for Large)

**2.1 Sync/Async Routing**:

- [x] 2.1.1 Implement batch size check (≤100 = sync, >100 = async)
- [x] 2.1.2 Add synchronous Ward path for small batches (<5s, immediate results)
- [x] 2.1.3 Add job status tracking table (job_id, tenant_id, status, progress)
- [x] 2.1.4 Implement `_enqueue_clustering_job()` for large batches
- [x] 2.1.5 Add job polling endpoint for UI (GET /clustering/jobs/{job_id})

**2.2 Celery Task** (for >100 identities):

- [x] 2.2.1 Create `batch_cluster_task` Celery task
- [x] 2.2.2 Implement job flow: fetch identities → normalize → Ward → create clusters
- [x] 2.2.3 Add threshold conversion: `sqrt(2 * (1 - cosine_threshold))`
- [x] 2.2.4 Configure AgglomerativeClustering (linkage='ward', metric='euclidean')
- [x] 2.2.5 Add batch size safeguard (>5,000 → hierarchical approximation)
- [x] 2.2.6 Update job status on completion/failure
- [x] 2.2.7 Add comprehensive telemetry logging

**2.3 Main Entry Point**:

- [x] 2.3.1 Implement `cluster_identities_hybrid()` orchestration
- [x] 2.3.2 Route to Stage 1 (representative matching) for existing clusters
- [x] 2.3.3 Route to sync Ward for ≤100 identities, async Celery for >100
- [x] 2.3.4 Return immediate results for sync, job_id for async

**2.4 UI & Status Handling**:

- [ ] 2.4.1 Add "Clustering in progress…" state to UI for async jobs
- [ ] 2.4.2 Implement polling/websocket refresh when job completes
- [ ] 2.4.3 Show last known clusters while job is running
- [ ] 2.4.4 Add notification when new clusters are ready
- [ ] 2.4.5 Handle job failures gracefully (retry, error messages)

**2.5 Testing**:

- [ ] 2.5.1 Unit test: Ward linkage creates deterministic clusters
- [ ] 2.5.2 Unit test: Threshold conversion (cosine → Euclidean)
- [ ] 2.5.3 Unit test: Sync/async routing based on batch size
- [ ] 2.5.4 Integration test: Small batch (≤100) returns immediate results
- [ ] 2.5.5 Integration test: Large batch (>100) enqueues job and returns job_id
- [ ] 2.5.6 Integration test: Batch size independence (10 vs 20 images, both sync)
- [ ] 2.5.7 Integration test: Tests poll/wait for async job completion
- [ ] 2.5.8 Integration test: Incremental upload workflow
- [ ] 2.5.9 Benchmark: Validate performance claims (<5s for ≤100, <60s for ≤5,000)

### Stage 3: Thresholds & Quality Validation

**3.1 Normalization Defense**:

- [ ] 3.1.1 Add DB CHECK constraint for unit vectors
- [ ] 3.1.2 Add app-level normalization in `_save_identities()`
- [ ] 3.1.3 Implement `audit_vector_normalization()` periodic job
- [ ] 3.1.4 Test 3-layer defense works

**3.2 Threshold Guards**:

- [ ] 3.2.1 Add bounds check (0.0 ≤ threshold ≤ 1.0)
- [ ] 3.2.2 Add unit vector verification before conversion
- [ ] 3.2.3 Add conversion sanity check (distance ≥ 0)
- [ ] 3.2.4 Add post-clustering validation
- [ ] 3.2.5 Test all 4 guards

**3.3 Quality Validation**:

- [ ] 3.3.1 Implement `validate_cluster_quality()` method
- [ ] 3.3.2 Add pairwise similarity checks
- [ ] 3.3.3 Add representative similarity checks
- [ ] 3.3.4 Test validation detects bad clusters

### Stage 4: Operations (Logging/Metrics/Monitoring)

**4.1 Telemetry**:

- [ ] 4.1.1 Add Stage 1 representative matching metrics
- [ ] 4.1.2 Add Stage 2 Ward clustering metrics
- [ ] 4.1.3 Add representative management metrics
- [ ] 4.1.4 Add Celery task duration/memory metrics
- [ ] 4.1.5 Create Grafana dashboard

**4.2 Validation & Deployment**:

- [ ] 4.2.1 Run acceptance tests (10 images → 3 clusters, 20 images → 3 clusters)
- [ ] 4.2.2 Run benchmark suite on staging
- [ ] 4.2.3 Deploy to staging environment
- [ ] 4.2.4 Monitor metrics and validate quality
- [ ] 4.2.5 Deploy to production

---

**Progress**: 0 / 61 tasks completed (0%)  
**Last Updated**: 2025-11-20
