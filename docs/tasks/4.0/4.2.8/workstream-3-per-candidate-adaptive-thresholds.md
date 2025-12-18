# Workstream 3: Per-candidate Maturity & Adaptive Thresholds

**Version:** 4.2.8  
**Date:** 2025-12-17  
**Status:** Draft  
**Scope:** Backend (prototype-description-service)

---

## Executive Summary

Enhance the existing `AssignmentGate` check pipeline to use **per-candidate** adaptive thresholds based on cluster maturity and identity quality. The current system already has adaptive thresholds based on global "labeled cluster count" via `ConfidenceCheck`. This workstream extends that to also consider:

1. **Per-Cluster Maturity** — The target cluster's member count, diversity, and confirmation state
2. **Per-Identity Quality** — The candidate identity's pose, confidence, and bounding box size

This prevents "singleton snowballing" while allowing mature, user-verified clusters to absorb new members more reliably.

---

## Current State Analysis

### What Already Exists ✅

| Component | File | Current Behavior |
|-----------|------|------------------|
| `MaturityCheck` | [checks/maturity.py](apps/prototype-description-service/recognition/application/assignment/checks/maturity.py) | Checks `min_representatives_for_maturity` setting; bypasses for anchor-linked to labeled clusters |
| `ConfidenceCheck` | [checks/confidence.py](apps/prototype-description-service/recognition/application/assignment/checks/confidence.py) | Uses `compute_adaptive_threshold()` based on **global** labeled cluster count |
| `user_confirmed` | [db/models.py](apps/prototype-description-service/db/models.py#L140) | Column exists on `identity_clusters` |
| `diversity_score` | [db/models.py](apps/prototype-description-service/db/models.py#L214) | Column exists on `identity_cluster_representatives` |
| `quality_score` | [db/models.py](apps/prototype-description-service/db/models.py#L213) | Column exists on `identity_cluster_representatives` (NOT on `media_identities`) |
| Pose metadata | [db/models.py](apps/prototype-description-service/db/models.py) | `pose_pitch`, `pose_yaw`, `pose_roll` exist on `media_identities` |
| `ClusteringSettings` | [settings/clustering.py](apps/prototype-description-service/recognition/application/settings/clustering.py) | All threshold settings in one place |

### False Assumptions in Original Plan ❌

| Original Claim | Reality |
|----------------|---------|
| "`MIN_CLUSTER_SIZE >= 2` global heuristic" | `MaturityCheck` uses `min_representatives_for_maturity` setting (default=0, disabled). The check is already per-cluster, not global. |
| "`diversity_score` from `identity_cluster_representatives.diversity_score` (avg)" | This field exists but is **not yet populated** — it's nullable and unused. |
| "Add `quality_score` to `media_identities`" | `quality_score` exists on `IdentityClusterRepresentative`, not `MediaIdentity`. Adding to `MediaIdentity` requires schema change. |
| "Global adaptive threshold removed" | The current `ConfidenceCheck` uses labeled_cluster_count (global), which is correct for "system maturity". Per-cluster maturity is a **separate concern**. |

---

## 1. Maturity Metrics

Maturity defines how "stable" and "well-defined" a cluster is.

| Metric | Source | Current Status | Impact on Threshold |
|--------|--------|----------------|---------------------|
| **Member Count** | `identity_clusters.identity_count` | ✅ Exists | Small clusters (< 3) require stricter similarity to prevent false merges |
| **Representative Count** | `COUNT(identity_cluster_representatives)` | ✅ Used by `MaturityCheck` | Used for diversity proxy |
| **Diversity Score** | `AVG(identity_cluster_representatives.diversity_score)` | ⚠️ Column exists but not populated | High diversity allows slightly more inclusive matching |
| **Confirmation State** | `identity_clusters.user_confirmed` | ✅ Exists | User-confirmed clusters can be trusted more |

### 1.1 Maturity Level Classification

| Level | Criteria | Description |
|-------|----------|-------------|
| **Cold (L0)** | `identity_count` = 1, `user_confirmed` = false | Highly volatile. Only exact or near-exact matches allowed. |
| **Nascent (L1)** | `identity_count` 2-5, `user_confirmed` = false | Building evidence. High similarity required. |
| **Confirmed (L2)** | `user_confirmed` = true | User has validated. High reliability. |
| **Mature (L3)** | `identity_count` > 10 AND `representative_count` >= 3 | Highly stable. Can absorb candidates with lower similarity if they match reps well. |

---

## 2. Identity Quality Metrics

Quality defines how "reliable" a single identity's embedding is.

| Metric | Source | Status | Ideal Value |
|--------|--------|--------|-------------|
| **Confidence** | `media_identities.confidence` | ✅ Exists | > 0.9 |
| **Frontal Pose** | `pose_pitch`, `pose_yaw`, `pose_roll` | ✅ Exists | All < 15° |
| **Area** | `bbox_width * bbox_height` | ✅ Computable | > 4096px (64×64) |

### 2.1 Identity Quality Score ($Q_i$)

$$Q_i = \text{confidence} \times \text{PosePenalty}(\theta) \times \text{SizeFactor}(A)$$

Where:
- $\text{PosePenalty}(\theta) = 1 - 0.5 \times \min(1, \frac{\max(|\text{pitch}|, |\text{yaw}|)}{45})$
- $\text{SizeFactor}(A) = \min(1, \frac{A}{10000})$ for area $A = \text{width} \times \text{height}$

---

## 3. Adaptive Threshold Function

The final decision to assign identity $i$ to cluster $C$ uses an adaptive threshold:

$$\text{Required Threshold} = T_{base} + \Delta_{cluster\_maturity}(C) + \Delta_{identity\_quality}(i)$$

### 3.1 Threshold Adjustments ($\Delta$)

**Cluster Maturity Adjustments:**

| Maturity Level | $\Delta_{cluster\_maturity}$ | Rationale |
|----------------|------------------------------|-----------|
| Cold (L0) | +0.05 | Protect singletons from false merges |
| Nascent (L1) | +0.02 | Still building evidence |
| Confirmed (L2) | -0.02 | User trust established |
| Mature (L3) | -0.03 | High confidence in cluster definition |

**Identity Quality Adjustments:**

| Quality Range | $\Delta_{identity\_quality}$ | Rationale |
|---------------|------------------------------|-----------|
| $Q_i < 0.5$ (poor) | +0.05 | Require more similarity for unreliable embeddings |
| $0.5 \le Q_i < 0.8$ | +0.02 | Moderate penalty |
| $Q_i \ge 0.8$ (good) | 0.00 | Trust the embedding |
| $Q_i \ge 0.95$ (excellent) | -0.02 | Allow slightly more lenient matching |

### 3.2 Relationship to Existing Checks

| Existing Check | Proposed Change |
|----------------|-----------------|
| `MaturityCheck` | **Enhance:** Compute maturity level (L0-L3) and pass to downstream checks |
| `ConfidenceCheck` | **Enhance:** Add `$\Delta_{cluster\_maturity}$` and `$\Delta_{identity\_quality}$` to threshold |
| `CompleteLinkCheck` | **No change** — already uses per-cluster representative similarities |
| `MemberDistributionCheck` | **No change** — already uses per-cluster member similarities |

---

## 4. Implementation Steps (TDD)

> **Follows `instructions.md`:** Scaffolding first → failing tests → minimal implementation → refactor

### Phase 0: Scaffolding (Interfaces & Types)

**Task 0.1:** Add `ClusterMaturityLevel` enum and `compute_maturity_level()` function signature

**File:** `recognition/application/assignment/maturity.py` (NEW)

```python
"""Cluster maturity level computation."""
from __future__ import annotations

from enum import IntEnum
from dataclasses import dataclass


class ClusterMaturityLevel(IntEnum):
    """Maturity level affecting adaptive threshold adjustments."""
    COLD = 0       # identity_count=1, not confirmed
    NASCENT = 1    # identity_count 2-5, not confirmed
    CONFIRMED = 2  # user_confirmed=True
    MATURE = 3     # identity_count>10 AND representative_count>=3


@dataclass(frozen=True, slots=True)
class ClusterMaturityInfo:
    """Maturity information for a cluster."""
    level: ClusterMaturityLevel
    identity_count: int
    representative_count: int
    user_confirmed: bool
    threshold_adjustment: float  # Delta to apply


def compute_maturity_level(
    *,
    identity_count: int,
    representative_count: int,
    user_confirmed: bool,
) -> ClusterMaturityLevel:
    """Compute maturity level from cluster metrics.
    
    Args:
        identity_count: Number of members in the cluster.
        representative_count: Number of representatives.
        user_confirmed: Whether user has confirmed the cluster.
        
    Returns:
        ClusterMaturityLevel enum value.
    """
    raise NotImplementedError("TODO: implement maturity level logic")


def compute_maturity_adjustment(level: ClusterMaturityLevel) -> float:
    """Return threshold adjustment for a maturity level.
    
    Args:
        level: Cluster maturity level.
        
    Returns:
        Float adjustment (positive = stricter, negative = more lenient).
    """
    raise NotImplementedError("TODO: implement adjustment lookup")
```

**Task 0.2:** Add `compute_identity_quality()` function signature

**File:** `recognition/application/assignment/quality.py` (NEW)

```python
"""Identity quality score computation."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IdentityQualityInfo:
    """Quality information for an identity."""
    score: float  # 0.0 to 1.0
    confidence: float
    pose_penalty: float
    size_factor: float
    threshold_adjustment: float  # Delta to apply


def compute_identity_quality(
    *,
    confidence: float,
    pose_pitch: float | None,
    pose_yaw: float | None,
    pose_roll: float | None,
    bbox_width: int,
    bbox_height: int,
) -> IdentityQualityInfo:
    """Compute identity quality score from detection metrics.
    
    Args:
        confidence: Detection confidence (0-1).
        pose_pitch: Head pitch angle in degrees.
        pose_yaw: Head yaw angle in degrees.
        pose_roll: Head roll angle in degrees.
        bbox_width: Bounding box width in pixels.
        bbox_height: Bounding box height in pixels.
        
    Returns:
        IdentityQualityInfo with computed score and adjustment.
    """
    raise NotImplementedError("TODO: implement quality computation")


def compute_quality_adjustment(quality_score: float) -> float:
    """Return threshold adjustment for a quality score.
    
    Args:
        quality_score: Identity quality (0-1).
        
    Returns:
        Float adjustment (positive = stricter, negative = more lenient).
    """
    raise NotImplementedError("TODO: implement adjustment lookup")
```

**Task 0.3:** Add `ClusterRepository.get_maturity_info()` signature

**File:** `recognition/domain/repositories.py`

```python
# Add to ClusterRepository protocol:
async def get_maturity_info(self, cluster_id: UUID) -> ClusterMaturityInfo | None:
    """Fetch maturity information for a cluster.
    
    Args:
        cluster_id: Cluster to query.
        
    Returns:
        ClusterMaturityInfo or None if cluster not found.
    """
    ...
```

### Phase 1: Unit Tests (Failing)

**Task 1.1:** Test `compute_maturity_level()` classification

**File:** `recognition/tests/unit/test_maturity_level.py`

```python
"""Tests for cluster maturity level computation."""
import pytest
from recognition.application.assignment.maturity import (
    ClusterMaturityLevel,
    compute_maturity_level,
    compute_maturity_adjustment,
)


class TestComputeMaturityLevel:
    def test_cold_singleton_not_confirmed(self) -> None:
        level = compute_maturity_level(
            identity_count=1, representative_count=1, user_confirmed=False
        )
        assert level == ClusterMaturityLevel.COLD

    def test_nascent_small_cluster(self) -> None:
        level = compute_maturity_level(
            identity_count=3, representative_count=2, user_confirmed=False
        )
        assert level == ClusterMaturityLevel.NASCENT

    def test_confirmed_overrides_size(self) -> None:
        # Even a singleton becomes CONFIRMED when user confirms
        level = compute_maturity_level(
            identity_count=1, representative_count=1, user_confirmed=True
        )
        assert level == ClusterMaturityLevel.CONFIRMED

    def test_mature_large_diverse_cluster(self) -> None:
        level = compute_maturity_level(
            identity_count=15, representative_count=5, user_confirmed=False
        )
        assert level == ClusterMaturityLevel.MATURE


class TestComputeMaturityAdjustment:
    @pytest.mark.parametrize("level,expected", [
        (ClusterMaturityLevel.COLD, 0.05),
        (ClusterMaturityLevel.NASCENT, 0.02),
        (ClusterMaturityLevel.CONFIRMED, -0.02),
        (ClusterMaturityLevel.MATURE, -0.03),
    ])
    def test_adjustment_values(self, level: ClusterMaturityLevel, expected: float) -> None:
        assert compute_maturity_adjustment(level) == pytest.approx(expected)
```

**Task 1.2:** Test `compute_identity_quality()` scoring

**File:** `recognition/tests/unit/test_identity_quality.py`

```python
"""Tests for identity quality score computation."""
import pytest
from recognition.application.assignment.quality import (
    compute_identity_quality,
    compute_quality_adjustment,
)


class TestComputeIdentityQuality:
    def test_high_confidence_frontal_large_face(self) -> None:
        info = compute_identity_quality(
            confidence=0.95,
            pose_pitch=0.0, pose_yaw=0.0, pose_roll=0.0,
            bbox_width=200, bbox_height=200,
        )
        assert info.score >= 0.9
        assert info.threshold_adjustment <= 0.0  # Lenient

    def test_low_confidence_penalized(self) -> None:
        info = compute_identity_quality(
            confidence=0.5,
            pose_pitch=0.0, pose_yaw=0.0, pose_roll=0.0,
            bbox_width=100, bbox_height=100,
        )
        assert info.score < 0.6
        assert info.threshold_adjustment > 0.0  # Stricter

    def test_extreme_pose_penalized(self) -> None:
        info = compute_identity_quality(
            confidence=0.9,
            pose_pitch=45.0, pose_yaw=0.0, pose_roll=0.0,
            bbox_width=100, bbox_height=100,
        )
        assert info.pose_penalty < 1.0
        assert info.score < 0.9

    def test_small_face_penalized(self) -> None:
        info = compute_identity_quality(
            confidence=0.9,
            pose_pitch=0.0, pose_yaw=0.0, pose_roll=0.0,
            bbox_width=32, bbox_height=32,
        )
        assert info.size_factor < 0.5


class TestComputeQualityAdjustment:
    @pytest.mark.parametrize("quality,expected_sign", [
        (0.3, 1),    # Positive (stricter)
        (0.6, 1),    # Positive (stricter)
        (0.85, 0),   # Zero (neutral)
        (0.98, -1),  # Negative (lenient)
    ])
    def test_adjustment_direction(self, quality: float, expected_sign: int) -> None:
        adjustment = compute_quality_adjustment(quality)
        if expected_sign == 1:
            assert adjustment > 0
        elif expected_sign == -1:
            assert adjustment < 0
        else:
            assert adjustment == pytest.approx(0.0, abs=0.001)
```

### Phase 2: Implementation

**Task 2.1:** Implement `compute_maturity_level()` and `compute_maturity_adjustment()`

**Task 2.2:** Implement `compute_identity_quality()` and `compute_quality_adjustment()`

**Task 2.3:** Implement `SqlAlchemyClusterRepository.get_maturity_info()`

### Phase 3: Integration

**Task 3.1:** Enhance `ConfidenceCheck` to use per-cluster and per-identity adjustments

**File:** `recognition/application/assignment/checks/confidence.py`

Modify `evaluate()` to:
1. Fetch `ClusterMaturityInfo` via repository
2. Compute `IdentityQualityInfo` from candidate identity
3. Apply both adjustments to adaptive threshold

**Task 3.2:** Add events for observability

Log `maturity_level`, `quality_score`, and `applied_threshold` in `recognition_events` for regression analysis.

### Phase 4: Monitoring & Validation

**Task 4.1:** Add integration tests with real database

**Task 4.2:** Add regression test capturing threshold behavior with known fixtures

---

## 5. Files Changed Summary

### New Files

| File | Purpose |
|------|---------|
| `recognition/application/assignment/maturity.py` | Maturity level computation |
| `recognition/application/assignment/quality.py` | Identity quality computation |
| `recognition/tests/unit/test_maturity_level.py` | Unit tests for maturity |
| `recognition/tests/unit/test_identity_quality.py` | Unit tests for quality |

### Modified Files

| File | Change |
|------|--------|
| `recognition/domain/repositories.py` | Add `get_maturity_info()` to protocol |
| `recognition/infrastructure/repositories/cluster_repository.py` | Implement `get_maturity_info()` |
| `recognition/application/assignment/checks/confidence.py` | Add maturity/quality adjustments |
| `recognition/application/assignment/candidate.py` | Optionally carry quality info |

### Schema (No Changes)

All required columns already exist:
- `identity_clusters.user_confirmed`, `identity_count`
- `media_identities.confidence`, `pose_pitch`, `pose_yaw`, `pose_roll`, `bbox_width`, `bbox_height`
- `identity_cluster_representatives.diversity_score` (exists but needs population)

---

## 6. Acceptance Criteria

- [ ] `compute_maturity_level()` correctly classifies clusters into L0-L3
- [ ] `compute_identity_quality()` produces scores 0-1 with pose/size penalties
- [ ] `ConfidenceCheck.evaluate()` applies both cluster and identity adjustments
- [ ] Unit tests pass for all maturity level transitions
- [ ] Unit tests pass for all quality score edge cases
- [ ] Integration test verifies that a singleton cluster requires higher similarity than a mature cluster
- [ ] Integration test verifies that a low-quality identity (side profile) requires higher similarity
- [ ] Regression test with known fixtures produces consistent threshold values
- [ ] Events logged with `maturity_level`, `quality_score`, `applied_threshold`

---

## 7. Future Enhancements

1. **Populate `diversity_score`** — Currently nullable and unused. Could enhance maturity calculation.
2. **Add `quality_score` to `media_identities`** — Pre-compute at scan time for faster gate evaluation.
3. **Configurable adjustment tables** — Move threshold deltas to `ClusteringSettings` for tuning.
4. **ML-based thresholds** — Train adjustment model on user curation feedback.
