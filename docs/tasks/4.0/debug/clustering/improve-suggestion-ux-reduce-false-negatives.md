# Improve Suggestion UX: Reduce False Negatives in Clustering

## Executive Summary

**Problem**: Media items go unclustered even when there is an identity with a high-percentage match. The current clustering pipeline is too conservative, rejecting valid matches and creating excessive singleton clusters. This makes the manual review process tedious for users.

**Design Principle**: It is preferable to suggest a high probability identity than to assume a false positive or false negative.

**Root Cause**: The `member_validation_threshold` (0.68) is too strict. When a new identity matches a representative at ~0.60-0.66, but the average similarity to existing cluster members falls below 0.68, the match is rejected.

**Proposed Solution**: Introduce a "suggested match" tier for borderline cases (0.55-0.68 member similarity) that surfaces high-probability matches to the user for confirmation, rather than silently rejecting them.

---

## Problem Analysis

### Observed Behavior from Logs (Nov 24-25, 2025)

From `recognition.log`:

```
MEMBER VALIDATION FAILED: identity=3666dac5-29f1-4d28-aac6-2804a6c78de3,
  rep=0.6426, avg_member=0.5691 < threshold=0.6800.
  Preventing false positive (cluster drift detected).
```

**Pattern**: Identities with representative similarity of 0.60-0.68 are being rejected because the average similarity to existing cluster members falls below the 0.6800 threshold.

### Current Thresholds (from `clustering_settings.py`)

| Threshold                         | Value    | Purpose                                      |
| --------------------------------- | -------- | -------------------------------------------- |
| `similarity_threshold`            | 0.65     | Minimum similarity to match a representative |
| `borderline_upper_threshold`      | 0.70     | Matches below this trigger validation        |
| `borderline_validation_threshold` | 0.60     | Centroid must be at least this similar       |
| `member_validation_threshold`     | **0.68** | Avg member similarity must be at least this  |
| `member_validation_sample_size`   | 3        | Number of random members to check            |

### Why Member Validation Fails for Valid Matches

1. **Cluster diversity accumulates over time**: As more faces are added to a cluster, the members become more diverse (different poses, lighting, expressions)

2. **New faces match representatives but not all members**: A new photo of "Maya" might match her representative photo (0.64 similarity) but have lower similarity to other members taken in different conditions

3. **Member validation penalizes legitimate diversity**: The 0.68 avg_member threshold assumes cluster members are homogeneous, which is often false

4. **Result**: Valid matches get rejected → create singleton clusters → user must manually merge later

### Evidence from Logs

```
--- Processing identity 89/212: media_id=2185, identity_id=3666dac5 ---
Rep matching: best_cluster=..., best_similarity=0.6426 (threshold=0.6000)
Member validation: rep=0.6426, avg_member=0.5691, min_member=0.5414, threshold=0.6800 (checked 3 members)
MEMBER VALIDATION FAILED: identity=3666dac5, rep=0.6426, avg_member=0.5691 < threshold=0.6800
✗ Creating NEW cluster: best_rep=0.6426, best_centroid=0.0000, threshold=0.6000
```

**Interpretation**:

- Representative match: **0.6426** (passes 0.60 threshold ✓)
- Average member similarity: **0.5691** (fails 0.68 threshold ✗)
- Result: New singleton cluster created instead of suggesting the match

---

## Proposed Solution: Suggested Matches Tier

### Concept

Instead of a binary accept/reject decision, introduce three outcomes:

| Decision    | Criteria                         | Action                                      |
| ----------- | -------------------------------- | ------------------------------------------- |
| **Accept**  | rep ≥ 0.65 AND avg_member ≥ 0.68 | Auto-assign to cluster                      |
| **Suggest** | rep ≥ 0.60 AND avg_member ≥ 0.55 | Surface as suggestion for user confirmation |
| **Reject**  | rep < 0.60 OR avg_member < 0.55  | Create new cluster                          |

### Implementation Strategy

#### Phase 1: Add Suggestion Tracking (Database)

Add a `suggested_cluster_id` field to `MediaIdentity` or a new `IdentitySuggestion` table:

```sql
CREATE TABLE identity_suggestions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    identity_id UUID NOT NULL REFERENCES media_identities(id),
    suggested_cluster_id UUID NOT NULL REFERENCES identity_clusters(id),
    representative_similarity FLOAT NOT NULL,
    avg_member_similarity FLOAT NOT NULL,
    confidence_score FLOAT NOT NULL,  -- Combined score for ranking
    created_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP,
    resolution VARCHAR(20),  -- 'accepted', 'rejected', 'expired'
    UNIQUE (identity_id, suggested_cluster_id)
);
```

#### Phase 2: Modify Clustering Logic

In `identity_clustering_service.py::_validate_member_similarity()`:

```python
async def _validate_member_similarity(
    self,
    identity: MediaIdentity,
    identity_vector: np.ndarray,
    cluster_id: UUID,
    rep_similarity: float,
) -> tuple[bool, bool]:  # Returns (should_accept, should_suggest)
    """
    Validate a representative match by checking similarity with existing members.

    Returns:
        (should_accept, should_suggest) where:
        - should_accept: True if auto-assignment is safe
        - should_suggest: True if should surface as suggestion (only if not accepted)
    """
    # ... existing member similarity calculation ...

    avg_member_similarity = np.mean(similarities)

    # Strong match: auto-accept
    if avg_member_similarity >= self.settings.member_validation_threshold:
        return True, False

    # Borderline match: suggest for user confirmation
    if avg_member_similarity >= self.settings.suggestion_threshold:  # e.g., 0.55
        logger.info(
            "SUGGESTION CANDIDATE: identity=%s, rep=%.4f, avg_member=%.4f "
            "(above suggestion threshold=%.4f but below accept threshold=%.4f)",
            identity.id,
            rep_similarity,
            avg_member_similarity,
            self.settings.suggestion_threshold,
            self.settings.member_validation_threshold,
        )
        return False, True

    # Poor match: reject
    return False, False
```

#### Phase 3: Create Suggestion During Clustering

```python
async def _create_suggestion(
    self,
    identity: MediaIdentity,
    cluster_id: UUID,
    rep_similarity: float,
    avg_member_similarity: float,
) -> None:
    """Create a suggestion record for user review."""
    suggestion = IdentitySuggestion(
        tenant_id=self.tenant_id,
        identity_id=identity.id,
        suggested_cluster_id=cluster_id,
        representative_similarity=rep_similarity,
        avg_member_similarity=avg_member_similarity,
        confidence_score=self._compute_confidence(rep_similarity, avg_member_similarity),
    )
    self.session.add(suggestion)
```

#### Phase 4: Frontend Integration

1. **Add suggestion indicator to IdentityClusterList**: Show a badge or icon for clusters with pending suggestions

2. **Create SuggestionReviewPanel**: Modal or sidebar to review suggestions

   - Show the identity image
   - Show top 3 cluster members for comparison
   - Show similarity scores
   - "Accept" / "Reject" / "Skip" buttons

3. **API endpoints**:
   - `GET /api/recognition/suggestions` - List pending suggestions
   - `POST /api/recognition/suggestions/{id}/accept` - Confirm match
   - `POST /api/recognition/suggestions/{id}/reject` - Reject match

---

## Alternative Approaches Considered

### Option A: Lower member_validation_threshold to 0.55

**Pros**: Simplest change, just update one constant
**Cons**: Increases false positives, doesn't give user control

### Option B: Disable member_validation entirely

**Pros**: Maximum recall, no rejected matches
**Cons**: Cluster drift becomes a real problem, Maya/Alicia issue returns

### Option C: Use confidence-weighted thresholds

**Pros**: Smarter decisions based on detection quality
**Cons**: More complex, may not solve the core UX issue

### Option D: Suggested Matches (Recommended)

**Pros**:

- User gets final say on borderline cases
- No silent rejections of valid matches
- Preserves protection against obvious false positives
- Better UX than manual merging

**Cons**:

- Requires new database table
- Requires new UI component
- More user clicks (but for good reason)

---

## Success Metrics

1. **Reduced singleton clusters**: Measure % of identities that end up in clusters of size 1

   - Target: Reduce from current ~40% to <20%

2. **Suggestion acceptance rate**: Track how often users accept suggestions

   - Target: >70% acceptance rate (indicates good suggestion quality)

3. **Manual merge frequency**: Track how often users manually merge clusters

   - Target: Reduce by 50%

4. **User satisfaction**: Survey/feedback on clustering workflow
   - Target: Improved ease-of-use ratings

---

## Implementation Tasks

### Backend Tasks

- [ ] **Task 1**: Add `identity_suggestions` table and SQLAlchemy model
- [ ] **Task 2**: Add `suggestion_threshold` setting (default: 0.55)
- [ ] **Task 3**: Modify `_validate_member_similarity()` to return suggestion flag
- [ ] **Task 4**: Add `_create_suggestion()` method
- [ ] **Task 5**: Integrate suggestion creation into clustering flow
- [ ] **Task 6**: Add API endpoints for suggestion management
- [ ] **Task 7**: Add tests for suggestion flow

### Frontend Tasks

- [ ] **Task 8**: Add suggestion badge to cluster cards
- [ ] **Task 9**: Create SuggestionReviewPanel component
- [ ] **Task 10**: Add suggestion review to workbench workflow
- [ ] **Task 11**: Add keyboard shortcuts for suggestion review (j/k for navigation, a/r for accept/reject)

### Tuning Tasks

- [ ] **Task 12**: A/B test different suggestion thresholds (0.50, 0.55, 0.60)
- [ ] **Task 13**: Monitor suggestion acceptance rates
- [ ] **Task 14**: Adjust thresholds based on real-world data

---

## Appendix: Log Analysis Details

### Sample Rejection Patterns

From `recognition.log` (Nov 24, 2025):

```
# Pattern 1: High rep similarity, low member similarity
Rep matching: best_cluster=..., best_similarity=0.6426 (threshold=0.6000)
Member validation: rep=0.6426, avg_member=0.5691 < threshold=0.6800
MEMBER VALIDATION FAILED

# Pattern 2: Borderline rep similarity, borderline member similarity
Rep matching: best_cluster=..., best_similarity=0.6103 (threshold=0.6000)
Member validation: rep=0.6103, avg_member=0.6234 < threshold=0.6800
MEMBER VALIDATION FAILED

# Pattern 3: Good rep match, passed validation
Rep matching: best_cluster=..., best_similarity=0.7123 (threshold=0.6000)
Member validation: rep=0.7123, avg_member=0.6923 >= threshold=0.6800
Member validation PASSED
```

### Threshold Distribution Analysis

| Avg Member Similarity | Count | Current Decision | Proposed Decision |
| --------------------- | ----- | ---------------- | ----------------- |
| 0.68+                 | ~30%  | Accept           | Accept            |
| 0.55-0.68             | ~25%  | Reject           | **Suggest**       |
| 0.45-0.55             | ~15%  | Reject           | Reject            |
| <0.45                 | ~30%  | Reject           | Reject            |

**Impact**: ~25% of currently rejected matches would become suggestions for user review.

---

## References

- [clustering-fix-implementation-plan.md](./clustering-fix-implementation-plan.md) - Original clustering fix
- [debug-clustering-batch-size-regression.md](./debug-clustering-batch-size-regression.md) - Batch size regression analysis
- Recognition logs: `apps/prototype-description-service/logs/recognition.log`
