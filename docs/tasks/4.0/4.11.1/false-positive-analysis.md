# False Positive Analysis & Recognition Improvement Plan

**Created**: 2026-01-25  
**Context**: Recognition logs show excessive manual corrections required — system clustering is producing too many singletons that users must manually assign.

---

## 1. Log Analysis Summary

### Observations from `recognition.log` (2026-01-25)

| Metric                               | Count | Implication                                           |
| ------------------------------------ | ----- | ----------------------------------------------------- |
| **Manual renames**                   | 23+   | Users naming unlabeled clusters                       |
| **Manual assigns (false negatives)** | 15+   | System failed to match faces that ARE the same person |
| **Manual removes (false positives)** | 1     | System incorrectly grouped different people           |

**Key Insight**: The vast majority of user corrections are **false negatives** (missed matches), NOT false positives. The system is being too conservative — it's leaving faces as singletons when it should be grouping them.

---

## 2. Root Cause Analysis

### 2.1 Threshold Configuration ~~Too Conservative~~ ✅ FIXED

> **Update (2026-01-25)**: Thresholds lowered per P1 implementation. See §4.1 and §6 checklist.

**Previous settings** (before fix):

```python
similarity_threshold: 0.85        # Discovery threshold - WAS VERY HIGH
suggestion_ceiling: 0.85          # Upper bound - WAS TOO STRICT
```

**Current settings** (after P1 fix):

```python
similarity_threshold: 0.80        # Lowered from 0.85 ✅
suggestion_floor: 0.65            # Unchanged
suggestion_ceiling: 0.80          # Lowered from 0.85 ✅
complete_link_threshold: 0.65     # Unchanged - safety net
complete_link_min_floor: 0.80     # Unchanged
```

**Problem** (resolved): A face with 0.82 similarity now auto-assigns instead of becoming a singleton.

### 2.2 Comparison with Apple Photos Approach

From the Apple research paper:

> "We tune the algorithm so that each first-pass cluster only groups together very close matches, providing **high precision but many, smaller clusters**. [...] After the first pass of clustering using the greedy method, we perform a **second pass using hierarchical agglomerative clustering (HAC)** to grow the clusters further, **increasing recall significantly**."

Apple uses a **two-pass strategy**:

1. First pass: Conservative (high precision, low recall) → many small clusters
2. Second pass: Aggressive merging (high recall) → fewer, larger clusters

Our system only has the conservative first pass.

### 2.3 Missing: Curriculum Learning Integration

From the CurricularFace paper:

> "Our CurricularFace adaptively adjusts the relative importance of easy and hard samples during different training stages. [...] easy cases are learned first and then come the hard ones."

Our system has `curriculum_coefficient` but:

- It's set to `-0.05` (very small effect)
- The curriculum learning value (`curriculum_t`) isn't being updated based on user feedback

### 2.4 Pose/Quality Issues

From logs:

- `landmark_quality` always shows 1.0 — not being computed correctly
- `pose_buckets` shows 0 filled — pose diversity not working
- Bucket coordinates like `(0, 0)` or `(-1, 0)` represent pitch/yaw divided by bucket size (30°)

---

## 3. Specific Issues Identified

### Issue 1: Assign vs Merge Terminology

**Location**: [IdentityClusterItem.tsx#L237-L239](../../../apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx#L237-L239)

```tsx
return canSearchForMatch
  ? sprintf(__("Assign to %s", "alt-context"), matchedCluster.label)
  : sprintf(__("Merge with %s", "alt-context"), matchedCluster.label);
```

**Explanation**:

- **"Assign to"**: Shown for **singletons** (faces not in any cluster) — the face is being assigned to an existing cluster
- **"Merge with"**: Shown for **clusters** — two clusters are being merged together

### Issue 2: Landmark Quality Always 1.0

**Location**: `recognition/infrastructure/repositories/cluster_repository.py`

The current implementation doesn't compute landmark quality from the actual landmark positions. The archived code had proper computation:

```python
# From archived: landmark_std / LANDMARK_STD_SCALE
embedding[LANDMARK_QUALITY_IDX] = landmark_std / 100.0
```

### Issue 3: Pose Buckets Never Filled

**Location**: [assignment_writer.py#L144-185](../../../apps/prototype-description-service/recognition/application/persistence/assignment_writer.py#L144-L185)

Buckets are computed as:

```python
(int(pitch // bucket_size), int(yaw // bucket_size))
```

With `bucket_size=30.0`:

- `Bucket(0, 0)` = pitch 0-29°, yaw 0-29° (frontal face)
- `Bucket(-1, 0)` = pitch -30 to -1°, yaw 0-29° (looking slightly down)
- `Bucket(1, 2)` = pitch 30-59°, yaw 60-89° (looking up and to the side)

The issue is that pose data (`pose_pitch`, `pose_yaw`) may not be populated on identity records.

### Issue 4: Image Thumbnails Cropping

**Location**: [\_media-selection.scss#L63-69](../../../apps/prototype-wp-alt-context/js/admin/styles/components/_media-selection.scss#L63-L69)

```scss
&__thumb {
  object-fit: cover; // ❌ Crops the image
  width: var(--acx-media-selection-thumb-size);
  height: var(--acx-media-selection-thumb-size);
}
```

Should use `object-fit: contain` to show entire image.

### Issue 5: No Cluster-to-Cluster Merge Suggestions for Unnamed Clusters

**Problem**: The suggestion system only creates suggestions when matching identities to **labeled clusters**. On a fresh database with no user-labeled clusters, the first batch produces:

1. HDBSCAN groups similar faces into clusters (working correctly)
2. All clusters get auto-labels like `cluster-abc123`
3. Suggestion system queries for labeled clusters → finds **zero**
4. Zero suggestions are created
5. "Review Suggestions" box shows "Label a cluster to start seeing suggestions"

**Root cause**: From [cluster_repository.py#L115-L117](../../../apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py#L115-L117):

```python
.where(ClusterModel.user_confirmed.is_(True))
.where(ClusterModel.label.is_not(None))
.where(~ClusterModel.label.startswith("cluster-"))
```

Suggestions only target clusters with `user_confirmed=True` and meaningful labels.

**Expected behavior**: Even with all-unnamed clusters, the system should surface merge suggestions for similar cluster pairs:

> **"Are these the same person?"**  
> [Face A] ↔ [Face B] (82% match)  
> [Yes, merge] [No, different]

**Proposed solution**:

1. **Post-clustering merge suggestions**: After initial HDBSCAN clustering, compare cluster centroids pairwise
2. **Generate cluster-to-cluster suggestions** for pairs above `suggestion_floor` (0.65) but below `similarity_threshold` (0.85)
3. **New suggestion type**: `merge_suggestion` (vs current `assignment_suggestion`)
4. **UI change**: "Review Suggestions" panel shows both types:
   - Identity → Cluster: "Is this Daniel?"
   - Cluster ↔ Cluster: "Are these the same person?"

**Implementation sketch**:

```python
async def generate_cluster_merge_suggestions(
    clusters: list[IdentityCluster],
    settings: ClusteringSettings,
) -> list[MergeSuggestion]:
    """Generate suggestions for similar unnamed cluster pairs."""
    suggestions = []
    for i, cluster_a in enumerate(clusters):
        for cluster_b in clusters[i + 1:]:
            similarity = cosine_similarity(cluster_a.centroid, cluster_b.centroid)
            if settings.suggestion_floor <= similarity < settings.similarity_threshold:
                suggestions.append(MergeSuggestion(
                    cluster_a_id=cluster_a.id,
                    cluster_b_id=cluster_b.id,
                    similarity=similarity,
                ))
    return suggestions
```

---

## 4. Proposed Solutions

### 4.1 Reduce Threshold Conservatism (High Priority)

**Change 1**: Lower `similarity_threshold` from 0.85 to 0.80

```python
similarity_threshold: float = Field(
    default=0.80,  # Was 0.85
    description="Discovery threshold for candidate matching.",
)
```

**Change 2**: Widen the auto-assign band

```python
suggestion_ceiling: float = Field(
    default=0.80,  # Was 0.85 - matches above this auto-assign
    description="Upper bound for suggestion band.",
)
```

**Risk Mitigation**: The `complete_link_threshold` (0.65) still prevents bad merges.

### 4.2 Implement Two-Pass Clustering (Medium Priority)

Following Apple's approach:

1. **Pass 1**: Current conservative clustering (HDBSCAN with current settings)
2. **Pass 2**: HAC merge pass for singleton reduction
   - Only consider singletons
   - Compare against all cluster centroids
   - Merge if distance < 0.75 AND user hasn't rejected

### 4.3 Leverage User Feedback for Curriculum Learning (High Priority)

Update `curriculum_t` based on user actions:

```python
# After manual assign (false negative): system was too strict
curriculum_t = min(1.0, curriculum_t + 0.01)  # Become more lenient

# After manual remove (false positive): system was too loose
curriculum_t = max(0.0, curriculum_t - 0.05)  # Become stricter (5x penalty)
```

This creates an adaptive system that learns from corrections.

### 4.4 Fix Pose/Landmark Metrics (Low Priority)

1. Ensure `pose_pitch` and `pose_yaw` are saved during detection
2. Compute landmark quality from actual landmark positions
3. Add logging to verify pose bucket computation is working

### 4.5 Fix Image Thumbnail CSS (Quick Fix)

```scss
&__thumb {
  object-fit: contain; // ✅ Shows entire image
  width: var(--acx-media-selection-thumb-size);
  height: var(--acx-media-selection-thumb-size);
  background-color: var(--acx-color-panel); // Fill empty space
}
```

---

## 5. Implementation Priority

| Priority | Task                                     | Effort | Impact                                        |
| -------- | ---------------------------------------- | ------ | --------------------------------------------- |
| P0       | Fix image thumbnail CSS                  | 5 min  | UX                                            |
| P1       | Cluster-to-cluster merge suggestions (5) | 4 hrs  | Critical - enables cold-start suggestion flow |
| P1       | Lower thresholds (4.1)                   | 30 min | High - immediate reduction in manual work     |
| P1       | Curriculum learning from feedback (4.3)  | 2 hrs  | High - system learns over time                |
| P2       | Two-pass clustering (4.2)                | 4 hrs  | Medium - reduces singletons                   |
| P3       | Fix pose/landmark metrics (4.4)          | 2 hrs  | Low - diagnostic value                        |

---

## 6. Progress Checklist

### P0 - Immediate (5 min)

- [x] **Fix image thumbnail CSS** (Issue 4) ✅ DONE
  - [x] Change `object-fit: cover` to `object-fit: contain` in `_media-selection.scss`
  - [x] Add `background-color` for letterboxing

### P1 - High Priority (6.5 hrs total)

- [x] **Cluster-to-cluster merge suggestions** (Issue 5) — 4 hrs
  - [x] Create `MergeSuggestion` domain model
  - [x] Implement `generate_cluster_merge_suggestions()` in clustering pipeline
  - [x] Add `merge_suggestion` type to suggestion repository
  - [x] Update `SuggestionReviewPanel` to handle cluster-to-cluster merges
  - [x] Test: Fresh batch produces merge suggestions ✅ Unit tests pass

- [x] **Lower similarity thresholds** (4.1) — 30 min
  - [x] Change `similarity_threshold` from 0.85 to 0.80
  - [x] Change `suggestion_ceiling` from 0.85 to 0.80
  - [x] Verify `complete_link_threshold` (0.65) provides safety net ✅
  - [x] Test: Re-run clustering, verify fewer singletons ✅

- [x] **Curriculum learning from feedback** (4.3) — 2 hrs
  - [x] Track `curriculum_t` in tenant settings or cluster metadata
  - [x] On manual assign: increase `curriculum_t` by 0.01
  - [x] On manual remove: decrease `curriculum_t` by 0.05
  - [x] Apply `curriculum_t` adjustment to thresholds during clustering
  - [x] Test: Repeated corrections shift system behavior ✅

### P2 - Medium Priority (4 hrs total)

- [x] **Two-pass clustering** (4.2) — 4 hrs ✅ COMPLETE
  - [x] Define `ConstrainedHACProtocol` in domain/repositories.py ✅
  - [x] Add `HACSettings` export from settings/**init**.py ✅
  - [x] Implement `run_hac_refinement()` in discovery_pipeline.py ✅
  - [x] Update orchestrator with proper type annotations ✅
  - [x] Add unit tests for HAC refinement path (7 tests) ✅
  - [x] Implement concrete `ConstrainedHAC` service ✅ See `constrained_hac.py`
  - [x] Wire HAC service in dependency injection ✅ See `cluster_service.py#L117-125`
  - [x] Test: Singleton count reduced after second pass ✅ `test_hac_refinement_reduces_singletons_with_real_hac`

### P3 - Low Priority (2 hrs)

- [x] **Fix pose/landmark metrics** (4.4) — 2 hrs
  - [x] Verify `pose_pitch`/`pose_yaw` saved during detection
  - [x] Compute `landmark_quality` from actual landmark positions
  - [x] Add logging for pose bucket computation
  - [x] Test: Logs show non-zero pose buckets

### Validation

- [ ] Reset database and re-run clustering on test dataset
- [ ] Measure: Singleton count before vs after
- [ ] Target: 50% reduction in manual assignments
- [ ] Monitor: False positive rate < 5%

---

## 7. Validation Plan

After implementing P0-P1:

1. Reset database and re-run clustering on test dataset
2. Count singletons before/after
3. Target: 50% reduction in manual assignments needed
4. Monitor false positive rate (should remain <5%)

---

## 8. References

- [Apple: Recognizing People in Photos Through Private On-Device Machine Learning](../../../docs/literature/extracted/recognition/apple/Recognizing%20People%20in%20Photos%20Through%20Private%20On-Device%20Machine%20Learning%20-%20Apple%20Machine%20Learning%20Research.txt)
- [CurricularFace: Adaptive Curriculum Learning Loss for Deep Face Recognition](../../../docs/literature/extracted/recognition/apple/CurricularFace--Adaptive-Curriculum-Learning-Loss-for-Deep-Face-Recognition.txt)
- [Chinese Whispers Graph Clustering](../../../docs/literature/extracted/recognition/chinese-whispers.txt)
