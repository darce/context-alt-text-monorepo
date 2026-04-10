# Structural Clustering Guard: Solution Evaluation

**Date**: 2024-11-30  
**Branch**: `subfeature/4.2.3.1-suggestion-guard`  
**Status**: Evaluation & Selection

## Problem Statement

**Core Issue**: Faces with 0.85-0.92 embedding similarity are being incorrectly assigned to the "Cam Grant" cluster. These are genuine lookalikes (young females with similar features), not noise. The current approach fails because:

1. **Threshold tweaking doesn't work**: Raising the threshold just moves the problem—you can't find a magic number that separates all lookalikes from real matches
2. **Member validation is poisoned**: Once wrong faces enter the cluster, new faces validate against the corrupted pool (snowball effect)
3. **Single-distance decisions are insufficient**: A new face being 0.90 similar to one Cam photo doesn't mean it's Cam—it might be 0.75 to other Cam photos

**Key Insight**: "Don't decide 'this is Cam' from a single distance; decide from how this vector sits relative to ALL known Cam embeddings and the local density structure."

## Solution Evaluation

### ✅ SELECTED: Complete-Link "Everyone Must Agree" Guard

**Why this is best for our architecture**:
1. **Already have representatives**: We store multiple representative embeddings per cluster—perfect for complete-link validation
2. **Simple to implement**: Just check max distance to ALL representatives, not just the nearest one
3. **No new dependencies**: Uses existing infrastructure (representatives table, cosine similarity)
4. **Directly addresses the problem**: A lookalike might be 0.92 to one Cam photo but 0.80 to another angle—complete-link catches this

**How it works**:
```python
# Instead of: max_sim(new_face, any_rep) >= threshold
# Do: min_sim(new_face, all_reps) >= threshold_floor AND avg_sim >= threshold

cluster_reps = get_representatives(cluster_id)  # 5-10 stored embeddings
similarities = [cosine_sim(new_face, rep) for rep in cluster_reps]

min_similarity = min(similarities)
avg_similarity = mean(similarities)

# Must agree with ALL representatives, not just one
accept = (min_similarity >= 0.80) and (avg_similarity >= 0.88)
```

**Implementation in existing code**:
- Modify `representative_matcher.py::match()` to check against ALL representatives
- Add `complete_link_min_threshold` setting (e.g., 0.80)
- Keep existing flow but add this as a structural guard before auto-assignment

---

### ⏳ DEFERRED: Density-based HDBSCAN "Trust Region"

**Concept**: Run HDBSCAN over Cam's confirmed embeddings + candidates. Only auto-accept if the new face falls into the same dense cluster as Cam's core.

**Pros**:
- Catches lookalikes that form their own dense cluster
- Threshold becomes two-dimensional (density + similarity)

**Cons**:
- Needs enough points (5-10 confirmed Cams minimum)
- Heavier compute than complete-link
- We already tried HDBSCAN—it has installation/stability issues

**Defer Reason**: Complete-link is simpler and addresses the same problem. Revisit if complete-link proves insufficient.

---

### ⏳ DEFERRED: Multi-Prototype K-Means Sub-Centers

**Concept**: Represent each identity by k sub-centers (e.g., "profile view", "3/4 view", "different ages"). Check both distance to nearest sub-center AND that sub-center's radius.

**Pros**:
- Handles intra-class variation naturally
- Early sub-centers are tight, preventing false positives

**Cons**:
- More complex to implement and maintain
- Need to tune k and manage sub-center lifecycle
- Overlaps with what representatives already provide

**Defer Reason**: Representatives + complete-link achieves similar benefits more simply.

---

### ⏳ DEFERRED: Graph/k-NN Community Detection

**Concept**: Build k-NN graph over batch, run community detection. Only assign if candidate is in same component as Cam's references AND has high internal edge density.

**Pros**:
- Naturally separates lookalikes into their own communities
- Candidates become "Unknown-A", "Unknown-B" clusters instead of false positives

**Cons**:
- Requires batch context (less useful for single-image uploads)
- More complex infrastructure
- We already have Chinese Whispers for this purpose

**Defer Reason**: Existing Chinese Whispers flow handles community formation. Focus on preventing incorrect matches first.

---

### 🔜 FUTURE: Hard-Negative Cluster per Identity

**Concept**: Track embeddings that were suggested as Cam but rejected by user. Require new candidates to be closer to positives than hard negatives.

**How it would work**:
```python
sim_pos = max_sim(x, cam_positives)
sim_neg = max_sim(x, cam_negatives)  # Rejected lookalikes

# Margin requirement
accept = (sim_pos >= 0.90) AND (sim_pos - sim_neg >= 0.05)
```

**Pros**:
- Learns from user corrections
- Triplet-style reasoning at inference time
- Prevents recurring false positives

**Cons**:
- Needs UI/UX for "wrong person" to populate negatives
- Cold start—no negatives until user rejects faces
- Need to manage negative set lifecycle

**Future Reason**: Excellent progressive learning mechanism. Implement AFTER complete-link guard is working and we have more user feedback data.

---

### 🔜 FUTURE: Identity-Specific Thresholds

**Concept**: Learn per-identity threshold from that identity's intra-class distances, not a global 0.90.

**How it would work**:
```python
cam_radius = compute_cluster_radius(cam_representatives)
# Cam might have radius 0.08 (tight), someone else might have 0.15 (varied)

threshold_for_cam = base_threshold + (0.5 * cam_radius)
```

**Pros**:
- Adapts to natural variance within each identity
- Tight clusters get stricter thresholds automatically

**Future Reason**: Good optimization once we have stable clusters. Pre-optimization before complete-link works.

---

## Implementation Plan

### Phase 1: Complete-Link Guard (This Sprint)

1. **Add complete-link validation to RepresentativeMatcher**
   - Before auto-assigning, fetch ALL representatives for the target cluster
   - Check `min_similarity >= floor` AND `avg_similarity >= threshold`
   - If fails, route to suggestion tier instead of auto-assign

2. **New settings**:
   ```python
   complete_link_enabled: bool = True
   complete_link_min_floor: float = 0.80  # Every rep must be >= this
   complete_link_avg_threshold: float = 0.88  # Average across all reps
   ```

3. **Logging/Telemetry**:
   ```python
   logger.info(
       "Complete-link check: identity=%s, cluster=%s, min_sim=%.3f, avg_sim=%.3f, passed=%s",
       identity.id, cluster_id, min_sim, avg_sim, passed
   )
   ```

### Phase 2: Early Stage Confirmation Mode (Next Sprint)

During early stage (< 30 labeled clusters), force ALL matches to create suggestions instead of auto-assigning, regardless of similarity.

```python
if self._is_early_stage():
    # Create suggestion for user confirmation, don't auto-assign
    await self._create_suggestion(identity.id, cluster_id, similarity, avg_member_sim)
    return  # Skip auto-assignment
```

### Phase 3: Hard-Negative Tracking (Future)

Add infrastructure to track rejected faces as hard negatives per identity.

---

## Relationship to clustering-fix-implementation-plan.md

**Still relevant?** Yes, but with updates:

1. **Representatives infrastructure** ✅ Already implemented and working
2. **Complete-link guard** ← NEW addition from this evaluation
3. **Ward linkage for batch clustering** ← Still valid for new cluster formation
4. **Celery async clustering** ← Still valid for large batches

The complete-link guard is an ADDITION to the existing plan, not a replacement. It adds structural validation on top of representatives without requiring Ward linkage changes.

---

## Success Metrics

1. **False positive rate**: < 5% of auto-assignments should be "wrong person"
2. **Suggestion quality**: > 80% of suggestions should be correct (user accepts)
3. **Lookalike handling**: Lookalikes should form their OWN clusters, not merge with labeled identities

---

**Next Action**: Implement complete-link guard in `representative_matcher.py`
