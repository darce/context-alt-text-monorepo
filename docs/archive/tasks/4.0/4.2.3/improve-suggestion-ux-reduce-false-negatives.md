# Improve Suggestion UX: Reduce False Negatives in Clustering

## Executive Summary

**Problem**: Media items go unclustered even when there is an identity with a high-percentage match. The current clustering pipeline is too conservative, rejecting valid matches and creating excessive singleton clusters. This makes the manual review process tedious for users.

**Design Principle**: It is preferable to suggest a high probability identity than to assume a false positive or false negative.

**Root Cause**: The `member_validation_threshold` (0.68) is too strict. When a new identity matches a representative at ~0.60-0.66, but the average similarity to existing cluster members falls below 0.68, the match is rejected.

**Proposed Solution**: Introduce a "suggested match" tier for borderline cases (0.55-0.68 member similarity) that surfaces high-probability matches to the user for confirmation, rather than silently rejecting them.

---

## Related Work: Clustering Improvements (Sprint 4.2.3)

> **Status**: The backend clustering infrastructure has been significantly improved.
> This document focuses on the **frontend UX** for surfacing suggestions to users.

### Completed Backend Work

The following improvements have been implemented (see `clustering-improvements-dev-plan.md`):

| Feature                       | Status  | Relevance to Suggestions           |
| ----------------------------- | ------- | ---------------------------------- |
| **1024D Extended Embeddings** | ✅ Done | Provides metadata for UI display   |
| **Confidence Weighting**      | ✅ Done | Improves match quality             |
| **Configurable Thresholds**   | ✅ Done | Per-tenant tuning via API          |
| **Metrics & Logging**         | ✅ Done | Tracks suggestion acceptance rates |

### New Embedding Metadata Available

The extended 1024D embedding now includes human-readable metadata that can be exposed in the suggestion UI:

```python
# From recognition/domain/embeddings/layout.py
| Index     | Field               | Description                    | UI Display Hint           |
|-----------|---------------------|--------------------------------|---------------------------|
| 512-514   | Head Pose           | [pitch, yaw, roll] in degrees  | "Facing: Left/Right/Up"   |
| 515       | Age                 | Estimated age                  | "~35 years old"           |
| 516       | Gender              | 0=female, 1=male              | "Female" / "Male"         |
| 517       | Detection Score     | Confidence [0-1]               | "High/Medium/Low quality" |
| 518       | Bbox Area           | Face size in pixels²           | "Large face" / "Small"    |
| 519       | Landmark Quality    | Std deviation of landmarks     | Quality indicator         |
```

### Extracting Metadata for Suggestions

Add a utility to decode metadata from stored embeddings:

```python
# recognition/application/suggestion_metadata.py
from recognition.domain.embeddings.layout import (
    AGE_IDX, GENDER_IDX, DET_SCORE_IDX, BBOX_AREA_IDX,
    LANDMARK_QUALITY_IDX, POSE_START, AGE_SCALE, POSE_SCALE,
    BBOX_AREA_SCALE, LANDMARK_STD_SCALE,
)

@dataclass
class SuggestionMetadata:
    """Human-readable metadata extracted from 1024D embedding."""
    pose_pitch: float  # degrees
    pose_yaw: float    # degrees
    pose_roll: float   # degrees
    age: int | None
    gender: str | None  # "female", "male", None
    detection_score: float
    face_size_quality: str  # "large", "medium", "small"
    landmark_quality: str   # "excellent", "good", "fair", "poor"

    @property
    def pose_description(self) -> str:
        """Human-readable pose description."""
        if abs(self.pose_yaw) > 30:
            return "Profile view" if self.pose_yaw > 0 else "Profile view (left)"
        if abs(self.pose_pitch) > 20:
            return "Looking up" if self.pose_pitch > 0 else "Looking down"
        return "Frontal view"

    @property
    def quality_score(self) -> float:
        """Combined quality score 0-1 for ranking suggestions."""
        return (self.detection_score * 0.5 +
                self._face_size_score() * 0.3 +
                self._landmark_score() * 0.2)


def extract_suggestion_metadata(embedding: np.ndarray) -> SuggestionMetadata:
    """Extract human-readable metadata from 1024D embedding."""
    return SuggestionMetadata(
        pose_pitch=embedding[POSE_START] * POSE_SCALE,
        pose_yaw=embedding[POSE_START + 1] * POSE_SCALE,
        pose_roll=embedding[POSE_START + 2] * POSE_SCALE,
        age=int(embedding[AGE_IDX] * AGE_SCALE) if embedding[AGE_IDX] > 0 else None,
        gender="female" if embedding[GENDER_IDX] == 0 else ("male" if embedding[GENDER_IDX] == 1 else None),
        detection_score=embedding[DET_SCORE_IDX],
        face_size_quality=_classify_face_size(embedding[BBOX_AREA_IDX] * BBOX_AREA_SCALE),
        landmark_quality=_classify_landmark_quality(embedding[LANDMARK_QUALITY_IDX] * LANDMARK_STD_SCALE),
    )
```

---

## Landmark Quality: Is It Useful for Suggestions?

### What InsightFace Returns

InsightFace's `face.kps` provides 5 facial landmarks:

- Left eye center
- Right eye center
- Nose tip
- Left mouth corner
- Right mouth corner

The **landmark quality** we store is the **standard deviation** of these landmark positions. This measures how "spread out" or "compressed" the landmarks are.

### Interpretation

| Landmark Std Dev | Quality   | Interpretation                                    |
| ---------------- | --------- | ------------------------------------------------- |
| 20-40            | Excellent | Well-spaced landmarks, frontal face               |
| 40-60            | Good      | Slight compression, minor pose                    |
| 60-80            | Fair      | Compressed landmarks, profile view or small face  |
| 80+              | Poor      | Very compressed, likely extreme pose or occlusion |

### Is It Useful for Suggestions?

**Partially useful, but with caveats:**

1. **✅ Helps identify low-quality detections**: High std dev often correlates with extreme poses or partially occluded faces that may match poorly.

2. **✅ Can explain match failures**: "This face is in profile view (landmark std=75), which may explain the lower match score."

3. **⚠️ Not directly comparable across faces**: Two frontal faces at different scales will have different landmark std devs, so absolute values aren't meaningful for comparison.

4. **❌ Not a direct quality indicator**: A perfectly frontal small face might have low std dev simply due to scale.

### Recommendation

Use landmark quality as a **secondary signal** in the suggestion UI:

```tsx
// Example UI hint in SuggestionReviewPanel
{
  metadata.landmark_quality === "poor" && (
    <Badge variant="warning">
      ⚠️ Profile view detected - lower match confidence expected
    </Badge>
  );
}
```

**Better quality signals for suggestions:**

1. **Detection score** (primary) - InsightFace's confidence
2. **Face size** (secondary) - Larger faces = more pixels = more reliable embedding
3. **Pose yaw** (tertiary) - Profile faces match less reliably

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

### Enhanced Suggestion API Response

Expose the new embedding metadata in the suggestion API for richer UI:

```python
# recognition/interface_adapters/http/suggestion_router.py
class SuggestionDetailResponse(BaseModel):
    """Detailed suggestion with metadata for UI display."""

    id: str
    identity_id: str
    suggested_cluster_id: str
    cluster_label: str | None

    # Similarity scores
    representative_similarity: float
    avg_member_similarity: float
    confidence_score: float

    # Identity metadata (from 1024D embedding)
    identity_metadata: IdentityMetadata

    # Comparison data
    cluster_representative_metadata: IdentityMetadata | None
    cluster_member_count: int

    created_at: datetime


class IdentityMetadata(BaseModel):
    """Human-readable metadata extracted from embedding."""

    thumbnail_url: str | None
    pose_description: str  # "Frontal view", "Profile view", etc.
    age: int | None
    gender: str | None  # "female", "male"
    detection_quality: str  # "high", "medium", "low"
    face_size: str  # "large", "medium", "small"

    # Raw values for advanced users
    detection_score: float
    pose_yaw: float  # degrees


@router.get("/suggestions", response_model=list[SuggestionDetailResponse])
async def list_suggestions(
    tenant_id: UUID = Query(...),
    status: str = Query("pending", regex="^(pending|all)$"),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[SuggestionDetailResponse]:
    """
    List pending suggestions with full metadata for UI display.

    Returns suggestions ordered by confidence score (highest first).
    """
    # Implementation
```

---

## Alternative Approaches Considered

### Option A: Lower member_validation_threshold to 0.55

**Pros**: Simplest change, just update one constant
**Cons**: Increases false positives, doesn't give user control
**Status**: ✅ Now configurable per-tenant via `/config` API

### Option B: Disable member_validation entirely

**Pros**: Maximum recall, no rejected matches
**Cons**: Cluster drift becomes a real problem, Maya/Alicia issue returns
**Status**: ❌ Not recommended

### Option C: Use confidence-weighted thresholds

**Pros**: Smarter decisions based on detection quality
**Cons**: More complex, may not solve the core UX issue
**Status**: ✅ Implemented in Sprint 4.2.3 (Slice A)

### Option D: Suggested Matches (Recommended)

**Pros**:

- User gets final say on borderline cases
- No silent rejections of valid matches
- Preserves protection against obvious false positives
- Better UX than manual merging
- Can display rich metadata (pose, age, quality) for informed decisions

**Cons**:

- Requires new database table
- Requires new UI component
- More user clicks (but for good reason)

**Status**: 🚧 This document - ready for implementation

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

> **Note**: Backend infrastructure (thresholds, metrics, embeddings) is complete.
> Frontend already has basic suggestion UI in `IdentityClusterList` (similarity-based suggestions in Combobox dropdown).
> The remaining work focuses on **persistent suggestion storage** and **dedicated review UX**.

### Backend Tasks (Suggestion Flow)

- [x] **Task 1**: Add `identity_suggestions` table and SQLAlchemy model
  - _Done: Added to `001_identity_schema.py` migration and `db/models.py` with `IdentitySuggestion` model_
- [x] **Task 2**: Add `suggestion_threshold` setting — _Done: `ClusteringSettings` has `suggestion_enabled` and `suggestion_threshold` (0.55)_
- [x] **Task 3**: Modify `_validate_member_similarity()` to return suggestion flag
  - _Done: Added `MemberValidationResult` dataclass and `validate_member_similarity_with_suggestion()` method in `cluster_validation.py`. Returns `(should_accept, should_suggest)` based on thresholds._
- [x] **Task 4**: Add `_create_suggestion()` method to persist suggestions during clustering
  - _Done: Created `SuggestionService` class in `recognition/application/clustering/suggestion_service.py` with `create_suggestion()`, `accept_suggestion()`, `reject_suggestion()`, and `expire_suggestions()` methods._
- [x] **Task 5**: Integrate suggestion creation into clustering flow
  - _Done: Added `suggestion_callback` parameter to `RepresentativeMatcher.assign_to_cluster()`. `IdentityClusteringService` instantiates `SuggestionService` and wires the callback._
- [x] **Task 6**: Add API endpoints for suggestion management
  - [x] `GET /identities/{id}/suggestions` - Fetch suggestions for an identity ✅
  - [x] `GET /suggestions` - List all pending suggestions with metadata ✅
  - [x] `GET /suggestions/{id}` - Get a specific suggestion ✅
  - [x] `POST /suggestions/{id}/accept` - Confirm and assign to cluster ✅
  - [x] `POST /suggestions/{id}/reject` - Mark as rejected ✅
  - _Done: Added to `suggestion_router.py` with `PersistedSuggestion` response model, pagination, and cluster/identity detail enrichment._
- [x] **Task 7**: Add `extract_suggestion_metadata()` utility (pose, age, quality from embedding)
  - _Done: Created `recognition/application/suggestion_metadata.py` with `SuggestionMetadata` dataclass, `extract_suggestion_metadata()`, and `extract_metadata_for_comparison()`. Includes 33 tests in `test_suggestion_metadata.py`._
- [x] **Task 8**: Add tests for suggestion persistence flow
  - _Done: Created `recognition/tests/test_suggestion_service.py` with 26 tests covering create, accept, reject, expire, query operations, and confidence score computation._

### Frontend Tasks (Suggestion UX)

> **Current State**: `IdentityClusterList.tsx` already shows similarity-based suggestions in a Combobox when editing a cluster label. Users can select a suggested cluster to merge.

- [x] **Task 9**: Basic suggestion display in cluster editing — _Done: Combobox shows suggestions with similarity % and member count_
- [ ] **Task 10**: Create dedicated `SuggestionReviewPanel` component with:
  - Side-by-side comparison view (candidate face vs. cluster representative)
  - Quality metadata display (pose, age, detection score from 1024D embedding)
  - "Accept" / "Reject" / "Skip" buttons with keyboard shortcuts (A/R/→)
  - _Currently: suggestions only appear when editing label, not proactively surfaced_
- [ ] **Task 11**: Add suggestion queue/count badge to workbench page header
  - _Currently: no global view of pending suggestions across all clusters_
- [ ] **Task 12**: Implement suggestion list view with filtering (by cluster, by quality score)
- [ ] **Task 13**: Add keyboard navigation for suggestion review (j/k for list, a/r/s for actions)

### Tuning Tasks

- [x] **Task 14**: Per-tenant threshold configuration — _Done: `/config` API_
- [ ] **Task 15**: Monitor suggestion acceptance rates via metrics endpoint
- [ ] **Task 16**: A/B test different suggestion thresholds (0.50, 0.55, 0.60)

---

## Which Frontend Tasks Are Still Valuable?

### High Value (Recommended)

| Task                                | Why Valuable                                                                                                                                                                     |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Task 10: SuggestionReviewPanel**  | Users currently must manually find and edit clusters to see suggestions. A dedicated review panel surfaces borderline matches proactively, reducing the chance of missed merges. |
| **Task 11: Suggestion queue badge** | Provides visibility into pending work. Without this, users don't know there are suggestions waiting.                                                                             |

### Medium Value (Nice to Have)

| Task                                        | Why Valuable                                                                           |
| ------------------------------------------- | -------------------------------------------------------------------------------------- |
| **Task 12: Suggestion list with filtering** | Useful for power users with many clusters, but basic queue view may suffice initially. |
| **Task 13: Keyboard shortcuts**             | Speeds up review workflow significantly, but only valuable after Tasks 10-11 are done. |

### Already Sufficient (Low Priority)

| Task                                     | Status                                                                                    |
| ---------------------------------------- | ----------------------------------------------------------------------------------------- |
| **Task 9: Basic suggestion in Combobox** | ✅ Already working - shows top 5 suggestions with similarity scores when editing a label. |

### Recommended Next Steps

1. **Backend first**: Implement `identity_suggestions` table (Task 1) so suggestions persist across sessions
2. **Then frontend**: Add `SuggestionReviewPanel` (Task 10) + queue badge (Task 11)
3. **Finally**: Keyboard shortcuts (Task 13) for power users

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

- [clustering-improvements-dev-plan.md](./clustering-improvements-dev-plan.md) - Backend improvements (Slices A-G)
- [clustering-algorithm-comprehensive-analysis.md](./clustering-algorithm-comprehensive-analysis.md) - Algorithm selection analysis
- [clustering-fix-implementation-plan.md](../cluster-rework/clustering-fix-implementation-plan.md) - Original clustering fix
- [debug-clustering-batch-size-regression.md](../cluster-rework/debug-clustering-batch-size-regression.md) - Batch size regression analysis
- Recognition logs: `apps/prototype-description-service/logs/recognition.log`

### Key Source Files

| File                                                        | Description                                      |
| ----------------------------------------------------------- | ------------------------------------------------ |
| `recognition/domain/embeddings/layout.py`                   | 1024D embedding structure with metadata indices  |
| `recognition/domain/embeddings/builder.py`                  | Extended embedding construction from InsightFace |
| `recognition/infrastructure/embedding_provider.py`          | InsightFace integration                          |
| `recognition/application/clustering/clustering_settings.py` | Configurable thresholds                          |
| `recognition/infrastructure/config_repository.py`           | Per-tenant configuration persistence             |
