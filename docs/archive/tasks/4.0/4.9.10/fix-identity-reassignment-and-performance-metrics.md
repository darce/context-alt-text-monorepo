# Fix Identity Reassignment and Performance Metrics

**Date**: 2025-12-23  
**Related Branch**: Current working branch  
**Issue**: UniqueViolation error when reassigning identity after false positive removal

---

## Overview

When a user corrects a false positive (removes identity from wrong cluster, assigns to correct cluster), the `assign_outlier_to_cluster` function fails with a unique constraint violation. Additionally, the system lacks proper semantic distinction between **false positive** and **false negative** corrections for performance measurement.

---

## Problem Analysis

### Bug: UniqueViolationError on Reassignment

**Trigger**: User removes identity from cluster A, then assigns to cluster B.

**Stack Trace** (from `recognition.log` at `2025-12-23 21:59:57`):
```
IntegrityError: duplicate key value violates unique constraint "unique_identity_membership"
[SQL: INSERT INTO identity_members (...)]
[parameters: (...cluster_id=ccf4b9b4..., identity_id=393a688b...)]
```

**Root Cause**: The `assign_outlier_to_cluster` function only checks if the identity is in the **target** cluster:

```python
# Current (incorrect)
existing_members = await member_repo.get_by_cluster(target_cluster_id)
if any(m.identity_id == str(identity_model.id) for m in existing_members):
    return cluster
```

But the DB constraint is on `(tenant_id, identity_id)` globally—not per-cluster.

**Contrast**: `create_cluster_for_identity` already handles this correctly by checking for any existing membership first.

---

## Semantic Distinction: False Positive vs False Negative

### Definitions

| Type | System Behavior | User Action | Meaning |
|------|-----------------|-------------|---------|
| **False Positive** | Auto-assigned to wrong cluster | Reassign to correct cluster | System wrongly matched |
| **False Negative** | Left as singleton/outlier | Assign to existing cluster | System failed to match |

### Determining Which Type

The determination is based on the **source state**:

| Source State | User Action | Classification |
|--------------|-------------|----------------|
| In multi-member cluster (identity_count > 1) | Move to different cluster | `FALSE_POSITIVE` |
| Singleton/orphan (outlier) | Assign to existing cluster | `FALSE_NEGATIVE` |
| Any | Create new cluster | `NEW_IDENTITY` |

### UI Implications

"Wrong Person" button should be **removed** in favor of implicit detection:

1. **From multi-member cluster → dropdown selection** = False Positive (implicit)
2. **From singleton/outlier → dropdown selection** = False Negative (implicit)
3. **Block from cluster** button = Creates explicit `cannot_link` constraint

### Edit Label Behavior

"Edit Label" should **only update the string value** of the cluster label. No cluster recomputation (centroids, representatives) should occur—this is purely a metadata change.

### Split Behavior

When splitting a cluster: identities moved to the **new cluster** (not keeping the user-defined label) should be treated as **false positives** ("wrong person"). This indicates the system incorrectly grouped them with the labeled person.

---

## Proposed Changes

### File: [cluster_curation.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/orchestration/cluster_curation.py)

#### 1. Add CurationActionType Enum

```python
class CurationActionType(str, Enum):
    FALSE_POSITIVE = "false_positive"   # Moved FROM auto-assigned cluster
    FALSE_NEGATIVE = "false_negative"   # Assigned FROM singleton/outlier
    NEW_IDENTITY = "new_identity"       # Created new cluster
    BLOCK = "cannot_link"               # Explicit wrong person constraint
```

#### 2. Update `assign_outlier_to_cluster`

```diff
+    # Determine source state for metrics
+    source_cluster_id = await get_identity_cluster_id(
+        member_repo=member_repo, identity_id=str(identity_model.id)
+    )
+    is_false_positive = source_cluster_id is not None
+
+    # If identity is in a DIFFERENT cluster, remove it first
+    if source_cluster_id:
+        await remove_identity_from_cluster(
+            identity_id=str(identity_model.id),
+            member_repo=member_repo,
+            cluster_repo=cluster_repo,
+            assignment_writer=assignment_writer,
+            recompute=True,  # Recompute source cluster's centroids
+            tenant_id_for_logging=tenant_id,
+            media_id=int(identity_model.media_id),
+        )
+
     await member_repo.add_member(target_cluster_id, ...)
+
+    # Log with action type for metrics
+    action_type = CurationActionType.FALSE_POSITIVE if is_false_positive else CurationActionType.FALSE_NEGATIVE
     logger.info(
-        "[curation] ASSIGNED identity=%s media_id=%s target_cluster=%s ...",
+        "[curation] ASSIGNED identity=%s media_id=%s target_cluster=%s "
+        "action_type=%s source_cluster=%s ...",
         identity_model.id,
         identity_model.media_id,
         target_cluster_id,
+        action_type.value,
+        source_cluster_id,
         ...
     )
```

---

## Verification Plan

### Automated Tests

```bash
cd /Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service
pytest recognition/tests/api/test_api_clusters.py::test_assign_outlier_to_cluster_via_api -v
pytest recognition/tests/unit/test_curation_logging.py -v
```

### Manual Verification

1. Create identity in cluster A (auto or manual)
2. Assign same identity to cluster B via API
3. Confirm: No UniqueViolation error
4. Confirm: Source cluster A has decremented identity_count
5. Confirm: Log shows `action_type=false_positive`

---

## Implementation Checklist

- [ ] Add `CurationActionType` enum to `cluster_curation.py`
- [ ] Update `assign_outlier_to_cluster` to handle existing memberships
- [ ] Update logging to include `action_type` and `source_cluster` fields
- [ ] Add unit test for "identity already in another cluster" scenario
- [ ] Update API documentation if endpoints change behavior

---

## Metrics Query Example

To measure false positive/negative rates:

```sql
SELECT 
    action_type,
    COUNT(*) as count,
    DATE(created_at) as date
FROM recognition_events
WHERE event_type = 'curation_assigned'
GROUP BY action_type, DATE(created_at)
ORDER BY date DESC;
```

---

## Issue: Suggestions Not Visible to Users

### Root Cause

Suggestions are **only created for user-labeled clusters** (line 132 of `service.py`):

```python
if not cluster.user_confirmed or not cluster.label or cluster.label.startswith("cluster-"):
    logger.info("[suggestions] Skipping suggestion: cluster not user-labeled ...")
    return False
```

During initial batch (600+ images), **no clusters are user-labeled**, so all suggestions are skipped. Chicken-and-egg problem.

### Recommended Solution

Add a **"Curate Top Clusters"** prompt after initial batch completes, showing clusters with highest identity counts for labeling first.

---

## Real-time Notifications

### Current State

After curation, backend recomputes but **no push notification** to frontend.

### Options

| Approach | Complexity | Notes |
|----------|------------|-------|
| **WebSocket** | Medium | Full duplex, needs connection management |
| **SSE (Server-Sent Events)** | Low | One-way, simpler |
| **Response Header** | Minimal | `X-Suggestions-Updated: true` |

Start with **response header approach**: Return `X-Suggestions-Updated: true` from curation endpoints. Frontend refetches suggestions when header present.

---

## Enhancement: Pose-Aware Representative Selection

### Background

Current implementation uses **Farthest-Point Sampling (FPS)** in embedding space to select up to 10 diverse representatives per cluster. This mimics Apple's approach of using **K exemplars** instead of a centroid average.

However, FPS operates purely on embedding distance—it doesn't explicitly consider **head pose angles** (pitch, yaw, roll) that InsightFace already provides.

### Problem

| Scenario | Issue |
|----------|-------|
| User has mostly selfies (frontal) | Side profiles not represented |
| New candid shot at extreme angle | Match fails despite same person |
| 10 reps all in ±15° yaw range | "Bridge" faces lost |

### Proposed Solution: Pose-Diversity Bonus

Allow **extra representatives** when a novel pose angle is detected, preventing pose coverage gaps.

### Implementation

#### 1. Add Setting

```python
# In ClusteringSettings
pose_diversity_bonus: int = Field(
    default=3,
    description="Extra representatives allowed for novel head poses beyond max_representatives_per_cluster.",
)
pose_bucket_size: float = Field(
    default=30.0,
    description="Degrees per pose bucket for novelty detection.",
)
```

#### 2. Add Helper Function

File: [assignment_writer.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/persistence/assignment_writer.py)

```python
def _is_novel_pose(
    identity: MediaIdentity,
    existing_reps: list[ClusterRepresentative],
    bucket_size: float = 30.0,
) -> bool:
    """Check if identity's pose is sufficiently different from existing representatives."""
    if identity.pose_pitch is None or identity.pose_yaw is None:
        return False
    
    # Bucket by pitch and yaw (roll less important for matching)
    new_bucket = (
        int(identity.pose_pitch // bucket_size),
        int(identity.pose_yaw // bucket_size),
    )
    
    for rep in existing_reps:
        # Get pose from linked identity if available
        rep_pitch = getattr(rep, "pose_pitch", None)
        rep_yaw = getattr(rep, "pose_yaw", None)
        if rep_pitch is None or rep_yaw is None:
            continue
        existing_bucket = (int(rep_pitch // bucket_size), int(rep_yaw // bucket_size))
        if new_bucket == existing_bucket:
            return False  # Same bucket = not novel
    
    return True
```

#### 3. Update `_should_add_representative`

```diff
 async def _should_add_representative(self, decision: AssignmentDecision) -> bool:
     cluster_id = decision.candidate.cluster_id
     current_count = await self._clusters.get_representative_count(cluster_id)
+    max_base = self._settings.max_representatives_per_cluster
+    max_with_bonus = max_base + self._settings.pose_diversity_bonus

-    if current_count >= self._settings.max_representatives_per_cluster:
+    if current_count >= max_with_bonus:
         return False

+    # Beyond base limit, only add if novel pose
+    if current_count >= max_base:
+        existing_reps = await self._clusters.get_all_representatives(cluster_id)
+        if not _is_novel_pose(decision.candidate.identity, existing_reps, self._settings.pose_bucket_size):
+            return False

     existing_reps = await self._clusters.get_all_representatives(cluster_id)
     # ... rest unchanged
```

### Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Unbounded growth | Hard cap at `max_reps + pose_diversity_bonus` |
| Low-quality extreme poses | Only if `confidence > 0.7` |
| Pose estimation errors | InsightFace reliable for ±60° yaw |

### Why This Avoids "Average Face Problem"

1. Individual embeddings stay intact (no averaging until sparse-code matching)
2. Pose-diverse reps cover the person's "face manifold" better
3. Apple uses **sparse coding** against exemplars, not centroid matching


## Proposed: Representative Quality Upgrade
Instead of just checking "is there room for more reps," check "is this better than an existing rep in the same pose bucket?"

```python
async def _should_upgrade_representative(
    self, 
    identity: MediaIdentity,
    existing_reps: list[ClusterRepresentative],
) -> ClusterRepresentative | None:
    """Check if identity should replace an existing lower-quality representative."""
    if identity.pose_pitch is None or identity.pose_yaw is None:
        return None
    
    new_quality = _compute_identity_quality(identity, self._settings)
    new_bucket = (
        int(identity.pose_pitch // self._settings.pose_bucket_size),
        int(identity.pose_yaw // self._settings.pose_bucket_size),
    )
    
    for rep in existing_reps:
        rep_pitch = getattr(rep, "pose_pitch", None)
        rep_yaw = getattr(rep, "pose_yaw", None)
        if rep_pitch is None or rep_yaw is None:
            continue
            
        rep_bucket = (int(rep_pitch // self._settings.pose_bucket_size), int(rep_yaw // self._settings.pose_bucket_size))
        
        # Same pose bucket - check if new one is better
        if new_bucket == rep_bucket:
            if new_quality > (rep.quality_score or 0) + 0.1:  # Margin to avoid churn
                return rep  # Replace this one
    
    return None  # No upgrade needed
```

### Usage in `_should_add_representative`

```python
# Check for upgrade opportunity
upgrade_target = await self._should_upgrade_representative(identity, existing_reps)
if upgrade_target:
    await self._clusters.remove_representative(upgrade_target.id)
    return True  # Add new one in its place
```

### Key Considerations

| Consideration | Recommendation |
|---------------|----------------|
| Minimum quality gap	| Only replace if new_quality > old_quality + 0.1 (avoid churn) |
| Frequency	| Don't replace on every assignment—only during recompute or explicit upgrade |
| User curation impact	| If user merges clusters, trigger full recompute_representatives() |
| Centroid impact	| After replacement, recompute centroid | 

### When NOT to Update
- User-confirmed representatives: If user explicitly selected a rep, don't auto-replace
- During batch processing: Wait until batch completes to avoid thrashing
- Small quality differences: < 0.1 difference isn't worth the churn
