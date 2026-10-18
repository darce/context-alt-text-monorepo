# Implementation Plan: Representative Lifecycle Management (4.9.11)

**Related Task**: `dynamic_suggestion_updates_implementation_plan.md` §10 (Deferred Items)
**Date**: 2025-12-24
**Status**: PLANNING

---

## 1. Overview

This plan addresses three interconnected representative lifecycle features deferred from 4.9.10:

1. **Quality-Based Upgrade**: Replace lower-quality representatives with better ones in the same pose bucket
2. **Batch-Scoped Deferral**: Avoid representative churn during batch processing
3. **User-Confirmed Protection**: Prevent auto-replacement of user-selected representatives

These features require coordinated schema, domain, and logic changes.

---

## 2. Current State Analysis

### 2.1 What Already Exists

| Component                                             | Location                       | Status                           |
| ----------------------------------------------------- | ------------------------------ | -------------------------------- |
| `_find_upgradeable_representative()`                  | `assignment_writer.py:175-193` | ✅ Implemented                   |
| Quality scoring (`_compute_identity_quality`)         | `assignment_writer.py:63-91`   | ✅ Implemented                   |
| Pose bucketing (`_get_pose_bucket`, `_is_novel_pose`) | `assignment_writer.py:143-169` | ✅ Implemented                   |
| Upgrade integration in `_should_add_representative`   | `assignment_writer.py:373-381` | ✅ Implemented                   |
| `ClusterRepresentative` domain object                 | `representative.py`            | ✅ Has `quality_score`, `pose_*` |
| `IdentityClusterRepresentative` model                 | `db/models.py:203-228`         | ✅ Has `quality_score`           |

### 2.2 What's Missing

| Component                 | Gap                                                       | Impact                       |
| ------------------------- | --------------------------------------------------------- | ---------------------------- |
| `is_user_selected` column | Not in schema or domain                                   | Cannot protect user picks    |
| Batch context awareness   | `_should_add_representative` has no batch flag            | Upgrades thrash mid-batch    |
| Recompute preservation    | `recompute_representatives()` clears all, ignores quality | Loses good reps on recompute |

---

## 3. Design Decisions

### 3.1 ADR: Representative Lifecycle

**Decision 1: Recompute Behavior**

| Option                                          | Pros         | Cons         |
| ----------------------------------------------- | ------------ | ------------ |
| C. Preserve pinned + high-quality, rebuild rest | Best of both | Most complex |

**Selected**: ✅ **Option C** (preserve pinned + best-per-pose-bucket)

**Rationale**: Option C yields more accurate results long-term because:

1. **Quality upgrades are intentional improvements**: The `_find_upgradeable_representative` logic replaces reps in the same pose bucket only when a significantly better face arrives (quality > old + 0.1 margin). These are curated improvements, not noise.

2. **FPS prioritizes diversity, not quality**: Standard FPS maximizes embedding distance, but doesn't consider which face in a pose bucket has the best detection confidence or size. Preserving high-quality reps ensures the "best face per angle" persists.

3. **Monotonic improvement**: With Option B, quality oscillates as recomputes reset upgrades. With Option C, clusters improve monotonically over time as better faces are discovered.

**Simplified implementation**: Preserve the **top-quality rep per pose bucket** during recompute (not an arbitrary threshold). This naturally aligns with the upgrade logic and avoids defining a magic "high-quality" cutoff.

```python
# Preservation logic:
# 1. Group existing reps by pose bucket
# 2. For each bucket, keep the highest quality_score rep
# 3. Also keep all is_user_selected=True reps
# 4. FPS fills remaining slots with diversity relative to preserved set
```

---

**Decision 2: Batch Deferral Mechanism**

| Option                                   | Pros                | Cons              |
| ---------------------------------------- | ------------------- | ----------------- |
| B. `is_provisional` column on reps table | Durable, crash-safe | Schema complexity |

**Selected**: ✅ **Option B** (`is_provisional` column)

**Rationale**: Durability matters for batch processing that can take hours. If the process crashes mid-batch, in-memory state is lost. A `provisional` flag allows:

1. Representatives added during batch are marked `is_provisional=True`
2. On batch complete, provisional reps are either confirmed or removed based on final cluster state
3. On crash recovery, provisional reps can be cleaned up or re-evaluated

**Schema addition** (see §4):

```python
sa.Column("is_provisional", sa.Boolean(), nullable=False, server_default="false"),
```

---

**Decision 3: User Selection Scope**

| Option                 | Pros                 | Cons          |
| ---------------------- | -------------------- | ------------- |
| A. Pin individual reps | Fine-grained control | UI complexity |

**Selected**: ✅ **Option A** (pin individual representatives)

**Rationale**: Users should be able to pin specific representatives (e.g., a clear frontal shot) while allowing the system to upgrade others (e.g., replace a blurry profile with a clearer one). Cluster-level locking is too coarse.

---

## 4. Schema Changes

### 4.1 Add `is_user_selected` and `is_provisional` Columns

**File**: `db/migrations/versions/001_identity_schema.py` (baseline per greenfield policy)

```python
# In identity_cluster_representatives table definition, add:
sa.Column("is_user_selected", sa.Boolean(), nullable=False, server_default="false"),
sa.Column("is_provisional", sa.Boolean(), nullable=False, server_default="false"),
```

**Indexes**:

```python
# For filtering pinned reps
op.create_index(
    "idx_cluster_reps_user_selected",
    "identity_cluster_representatives",
    ["cluster_id", "is_user_selected"],
    postgresql_where=text("is_user_selected = true"),
)

# For batch cleanup of provisional reps
op.create_index(
    "idx_cluster_reps_provisional",
    "identity_cluster_representatives",
    ["cluster_id", "is_provisional"],
    postgresql_where=text("is_provisional = true"),
)
```

### 4.2 Domain Object Update

**File**: `recognition/domain/representative.py`

```python
@dataclass
class ClusterRepresentative:
    """Represents a curated embedding that stands in for a cluster."""

    id: str
    cluster_id: str
    identity_id: str
    embedding: np.ndarray
    created_at: datetime
    tenant_id: str | None = None
    pose_pitch: float | None = None
    pose_yaw: float | None = None
    pose_roll: float | None = None
    quality_score: float = 1.0
    diversity_score: float | None = None
    media_id: int | None = None
    image_phash: str | None = None
    is_user_selected: bool = False  # User pinned this rep
    is_provisional: bool = False    # Added during batch, pending confirmation
```

---

## 5. Implementation Details

### 5.1 Feature 1: Quality-Based Upgrade (Already Implemented)

**Current behavior** (verified in `assignment_writer.py:373-381`):

```python
# In _should_add_representative:
upgrade_target = _find_upgradeable_representative(
    decision.candidate.identity,
    existing_reps,
    self._settings.pose_bucket_size,
    self._settings,
)
if upgrade_target:
    await self._clusters.remove_representative(upgrade_target.id)
    return True  # Add new one in its place
```

**Enhancement needed**: Skip upgrade if `upgrade_target.is_user_selected`:

```python
if upgrade_target and not upgrade_target.is_user_selected:
    await self._clusters.remove_representative(upgrade_target.id)
    return True
```

### 5.2 Feature 2: Batch-Scoped Deferral (Provisional Representatives)

**Approach**: Mark reps added during batch as `is_provisional=True`. Confirm or remove on batch completion.

**File**: `recognition/application/persistence/assignment_writer.py`

```python
async def _should_add_representative(
    self,
    decision: AssignmentDecision,
    *,
    batch_mode: bool = False,  # NEW: Set True during batch processing
) -> bool:
    """Determine if the assigned identity should become a representative.

    Args:
        decision: The assignment decision containing candidate info.
        batch_mode: If True, mark new reps as provisional and skip upgrades.

    Returns:
        True if identity should be added as representative.
    """
    cluster_id = decision.candidate.cluster_id
    existing_reps = await self._clusters.get_all_representatives(cluster_id)
    current_count = len(existing_reps)

    # 1. Check for upgrade opportunity (skip during batch to avoid churn)
    if not batch_mode:
        upgrade_target = _find_upgradeable_representative(
            decision.candidate.identity,
            existing_reps,
            self._settings.pose_bucket_size,
            self._settings,
        )
        if upgrade_target and not getattr(upgrade_target, "is_user_selected", False):
            await self._clusters.remove_representative(upgrade_target.id)
            return True

    # ... rest unchanged
```

**New rep creation** (mark provisional when in batch mode):

```python
async def _create_and_add_representative(
    self,
    cluster_id: str,
    identity: MediaIdentity,
    reason: str,
    *,
    is_provisional: bool = False,  # NEW
) -> ClusterRepresentative:
    """Create and persist a new representative."""
    rep = ClusterRepresentative(
        id=generate_id(),
        cluster_id=cluster_id,
        identity_id=identity.id,
        embedding=identity.embedding,
        # ... other fields ...
        is_provisional=is_provisional,
    )
    await self._clusters.add_representative(rep)
    return rep
```

**Batch orchestration** (`incremental_clustering.py`):

```python
# During batch loop:
await assignment_writer.persist_assignment(decision, batch_mode=True)

# After batch completes:
async def finalize_batch(affected_cluster_ids: set[str]) -> None:
    """Confirm provisional reps and recompute for diversity."""
    for cluster_id in affected_cluster_ids:
        # Confirm provisional reps (they survived the batch)
        await cluster_repo.confirm_provisional_representatives(cluster_id)
        # Recompute for diversity with preserved high-quality + pinned
        await assignment_writer.recompute_representatives(cluster_id)
```

**Repository method for confirmation**:

```python
async def confirm_provisional_representatives(self, cluster_id: str) -> int:
    """Mark all provisional representatives in a cluster as confirmed.

    Args:
        cluster_id: Cluster whose provisional reps should be confirmed.

    Returns:
        Number of representatives confirmed.
    """
    raise NotImplementedError("TODO: Implement confirm_provisional_representatives")
```

**Crash recovery** (on startup or batch resume):

```python
async def cleanup_orphaned_provisional_reps(self, tenant_id: str) -> int:
    """Remove provisional reps from clusters with no active batch.

    Called during startup to clean up after crashes.

    Returns:
        Number of provisional reps removed.
    """
    raise NotImplementedError("TODO: Implement cleanup_orphaned_provisional_reps")
```

### 5.3 Feature 3: User-Confirmed Protection

#### 5.3.1 Repository Method

**File**: `recognition/domain/repositories.py` (Protocol addition)

```python
class ClusterRepository(Protocol):
    # ... existing methods ...

    async def mark_representative_user_selected(
        self,
        representative_id: str,
        is_selected: bool = True,
    ) -> None:
        """Mark a representative as user-selected (pinned).

        Args:
            representative_id: UUID of the representative to mark.
            is_selected: True to pin, False to unpin.

        Raises:
            ValueError: If representative not found.
        """
        raise NotImplementedError("TODO: Implement mark_representative_user_selected")

    async def get_user_selected_representatives(
        self,
        cluster_id: str,
    ) -> list[ClusterRepresentative]:
        """Get all user-selected representatives for a cluster.

        Args:
            cluster_id: Cluster UUID.

        Returns:
            List of pinned representatives.
        """
        raise NotImplementedError("TODO: Implement get_user_selected_representatives")
```

#### 5.3.2 Modified Recompute (Option C: Preserve Pinned + Best-Per-Pose-Bucket)

**File**: `recognition/application/persistence/assignment_writer.py`

```python
async def recompute_representatives(self, cluster_id: str) -> None:
    """Recompute cluster representatives using FPS for diversity.

    Preserves:
    1. All user-selected (pinned) representatives
    2. The highest quality_score rep per pose bucket (incremental upgrades)

    Remaining slots are filled via seeded FPS for diversity.
    """
    cluster = await self._clusters.get_by_id(cluster_id)
    if not cluster:
        raise ClusterNotFoundError(cluster_id)

    # Get all existing representatives
    all_reps = await self._clusters.get_all_representatives(cluster_id)

    # Step 1: Identify reps to preserve
    preserved_reps = _select_reps_to_preserve(
        all_reps,
        self._settings.pose_bucket_size,
    )
    preserved_ids = {rep.id for rep in preserved_reps}

    # Step 2: Remove only non-preserved representatives
    for rep in all_reps:
        if rep.id not in preserved_ids:
            await self._clusters.remove_representative(rep.id)

    # Step 3: Calculate remaining slots
    preserved_count = len(preserved_reps)
    max_reps = self._settings.max_representatives_per_cluster
    remaining_slots = max_reps - preserved_count

    if remaining_slots <= 0:
        # Cluster is at capacity with preserved reps
        if preserved_reps:
            # Prefer first pinned rep, else highest quality
            primary = next(
                (r for r in preserved_reps if getattr(r, "is_user_selected", False)),
                max(preserved_reps, key=lambda r: r.quality_score),
            )
            cluster.representative_identity_id = primary.identity_id
            await self._clusters.update(cluster)
        return

    # Step 4: Get member identities excluding preserved ones
    preserved_identity_ids = {rep.identity_id for rep in preserved_reps}
    identities = list(await self._clusters.get_member_identities(cluster_id))
    identities = [
        i for i in identities
        if i.embedding is not None and i.id not in preserved_identity_ids
    ]

    if not identities and not preserved_reps:
        return

    # Step 5: Seed FPS with preserved rep embeddings for diversity calculation
    seed_embeddings = [
        _normalize_embedding(np.asarray(rep.embedding, dtype=np.float32))
        for rep in preserved_reps
    ]

    selected = _select_diverse_representatives_seeded(
        identities,
        remaining_slots,
        seed_embeddings,
    )

    # Step 6: Set primary representative
    if preserved_reps:
        primary = next(
            (r for r in preserved_reps if getattr(r, "is_user_selected", False)),
            max(preserved_reps, key=lambda r: r.quality_score),
        )
        cluster.representative_identity_id = primary.identity_id
    elif selected:
        cluster.representative_identity_id = selected[0].id
    await self._clusters.update(cluster)

    # Step 7: Create new representatives from FPS selection
    for identity in selected:
        await self._create_and_add_representative(
            cluster_id=cluster_id,
            identity=identity,
            reason="fps_recompute",
        )


def _select_reps_to_preserve(
    reps: list[ClusterRepresentative],
    pose_bucket_size: int,
) -> list[ClusterRepresentative]:
    """Select representatives to preserve during recompute.

    Preserves:
    1. All user-selected (pinned) reps
    2. The highest quality_score rep per pose bucket

    This preserves incremental quality upgrades while maintaining
    pose diversity.

    Args:
        reps: All current representatives.
        pose_bucket_size: Size of pose angle buckets (e.g., 15 degrees).

    Returns:
        List of representatives to preserve.
    """
    preserved: list[ClusterRepresentative] = []

    # Always preserve pinned reps
    pinned = [r for r in reps if getattr(r, "is_user_selected", False)]
    preserved.extend(pinned)

    # Group non-pinned by pose bucket and keep best per bucket
    non_pinned = [r for r in reps if not getattr(r, "is_user_selected", False)]

    buckets: dict[tuple[int, int], ClusterRepresentative] = {}
    for rep in non_pinned:
        yaw_bucket = int(rep.pose_yaw // pose_bucket_size)
        pitch_bucket = int(rep.pose_pitch // pose_bucket_size)
        key = (yaw_bucket, pitch_bucket)

        if key not in buckets or rep.quality_score > buckets[key].quality_score:
            buckets[key] = rep

    preserved.extend(buckets.values())

    return preserved
```

#### 5.3.3 New FPS Variant (Seeded)

**File**: `recognition/application/persistence/assignment_writer.py`

```python
def _select_diverse_representatives_seeded(
    identities: list[MediaIdentity],
    max_reps: int,
    seed_embeddings: list[np.ndarray],
) -> list[MediaIdentity]:
    """Select representatives via FPS, seeded with existing embeddings.

    The seed embeddings are used for distance calculations but not included
    in the output. This ensures new selections are diverse relative to
    existing (pinned) representatives.

    Args:
        identities: Pool of candidate identities.
        max_reps: Maximum number of representatives to select.
        seed_embeddings: Pre-existing embeddings to consider for diversity.

    Returns:
        Selected representatives (excludes seeds).
    """
    if not identities:
        return []

    k = min(max_reps, len(identities))
    if k <= 0:
        return []

    # Start with seeds as the "already selected" set
    selected_vecs: list[np.ndarray] = list(seed_embeddings)
    selected: list[MediaIdentity] = []

    # Sort candidates by confidence
    sorted_by_conf = sorted(identities, key=lambda i: i.confidence, reverse=True)

    # If no seeds, start with highest confidence
    if not selected_vecs:
        selected.append(sorted_by_conf[0])
        selected_vecs.append(
            _normalize_embedding(np.asarray(sorted_by_conf[0].embedding, dtype=np.float32))
        )
        sorted_by_conf = sorted_by_conf[1:]
        k -= 1

    remaining = set(range(len(sorted_by_conf)))

    for _ in range(k):
        if not remaining:
            break

        best_idx: int | None = None
        best_min_dist = -1.0

        for idx in remaining:
            vec = _normalize_embedding(
                np.asarray(sorted_by_conf[idx].embedding, dtype=np.float32)
            )
            min_dist = min(float(1 - np.dot(vec, sv)) for sv in selected_vecs)
            if min_dist > best_min_dist:
                best_min_dist = min_dist
                best_idx = idx

        if best_idx is None:
            break

        selected.append(sorted_by_conf[best_idx])
        selected_vecs.append(
            _normalize_embedding(
                np.asarray(sorted_by_conf[best_idx].embedding, dtype=np.float32)
            )
        )
        remaining.remove(best_idx)

    return selected
```

---

## 6. API Endpoint

### 6.1 Pin/Unpin Representative

**File**: `recognition/interface_adapters/http/routers/clusters.py`

```python
@router.patch(
    "/clusters/{cluster_id}/representatives/{representative_id}/pin",
    response_model=ClusterResponse,
)
async def pin_representative(
    cluster_id: str,
    representative_id: str,
    pin: bool = Query(default=True, description="True to pin, False to unpin"),
    tenant_id: str = Depends(get_tenant_id),
    session=Depends(get_session),
    auth=Depends(require_write_access),
) -> ClusterResponse:
    """Pin or unpin a cluster representative.

    Pinned representatives are protected from:
    - Quality-based upgrades during assignment
    - Removal during recompute_representatives

    Args:
        cluster_id: Cluster containing the representative.
        representative_id: Representative to pin/unpin.
        pin: True to pin, False to unpin.

    Returns:
        Updated cluster with representative list.
    """
    validate_entity_id(cluster_id, "cluster_id")
    validate_entity_id(representative_id, "representative_id")

    cluster_service = await build_cluster_service(session=session, tenant_id=tenant_id)
    await cluster_service.pin_representative(representative_id, is_pinned=pin)

    return await cluster_service.get_cluster_response(cluster_id)
```

---

## 7. Frontend Integration

### 7.1 Representative Pin Toggle

**File**: `js/admin/pages/workbench/identity-clusters/RepresentativeThumbnail.tsx` (new or extend existing)

```tsx
interface RepresentativeThumbnailProps {
  representative: ClusterRepresentative;
  onPin: (repId: string, pinned: boolean) => void;
  isPinMutating: boolean;
}

export const RepresentativeThumbnail = ({
  representative,
  onPin,
  isPinMutating,
}: RepresentativeThumbnailProps): React.JSX.Element => {
  return (
    <div className="acx-representative-thumbnail">
      <img src={representative.thumbnailUrl} alt="" />
      <button
        type="button"
        className={`acx-representative-pin ${
          representative.isUserSelected ? "pinned" : ""
        }`}
        onClick={() => onPin(representative.id, !representative.isUserSelected)}
        disabled={isPinMutating}
        aria-label={
          representative.isUserSelected
            ? "Unpin representative"
            : "Pin representative"
        }
        aria-pressed={representative.isUserSelected}
      >
        📌
      </button>
      {representative.qualityScore && (
        <span className="acx-representative-quality">
          {Math.round(representative.qualityScore * 100)}%
        </span>
      )}
    </div>
  );
};
```

---

## 8. Test Specifications

### 8.1 Unit Tests

**File**: `recognition/tests/unit/test_representative_pinning.py`

```python
"""Unit tests for representative pinning/protection."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from recognition.application.persistence.assignment_writer import (
    _find_upgradeable_representative,
    _select_diverse_representatives_seeded,
)


class TestUpgradeProtection:
    """Tests for is_user_selected protection during upgrades."""

    def test_find_upgradeable_skips_pinned_rep(self) -> None:
        """Pinned representatives should not be returned as upgrade targets."""
        identity = MagicMock(pose_pitch=15.0, pose_yaw=10.0, confidence=0.95)
        pinned_rep = MagicMock(
            pose_pitch=10.0,
            pose_yaw=5.0,
            quality_score=0.7,
            is_user_selected=True,
        )
        settings = MagicMock(pose_bucket_size=30.0)

        # Same bucket, higher quality, but pinned
        result = _find_upgradeable_representative(
            identity, [pinned_rep], 30.0, settings
        )

        # Should be None because rep is pinned
        # NOTE: Current impl doesn't check is_user_selected - this test will fail until fixed
        assert result is None

    def test_find_upgradeable_returns_unpinned_rep(self) -> None:
        """Unpinned representatives can be upgraded."""
        identity = MagicMock(pose_pitch=15.0, pose_yaw=10.0, confidence=0.95)
        unpinned_rep = MagicMock(
            pose_pitch=10.0,
            pose_yaw=5.0,
            quality_score=0.7,
            is_user_selected=False,
        )
        settings = MagicMock(pose_bucket_size=30.0)

        result = _find_upgradeable_representative(
            identity, [unpinned_rep], 30.0, settings
        )

        assert result == unpinned_rep


class TestSeededFPS:
    """Tests for FPS with seed embeddings."""

    def test_seeded_fps_respects_seed_diversity(self) -> None:
        """New selections should be diverse relative to seeds."""
        # This would need numpy fixtures for proper testing
        pass

    def test_seeded_fps_empty_seeds_falls_back_to_confidence(self) -> None:
        """With no seeds, should start with highest confidence."""
        pass
```

### 8.2 Integration Tests

**File**: `recognition/tests/integration/test_representative_lifecycle.py`

```python
"""Integration tests for representative lifecycle management."""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
class TestRepresentativePinning:
    """Tests for pin/unpin API and recompute preservation."""

    async def test_pin_representative_persists(
        self,
        async_client: AsyncClient,
        authenticated_headers: dict,
        cluster_with_reps: str,
    ) -> None:
        """Pinning a representative persists to database."""
        cluster_id = cluster_with_reps
        # Get first rep
        response = await async_client.get(
            f"/api/v1/clusters/{cluster_id}",
            headers=authenticated_headers,
        )
        rep_id = response.json()["representatives"][0]["id"]

        # Pin it
        response = await async_client.patch(
            f"/api/v1/clusters/{cluster_id}/representatives/{rep_id}/pin?pin=true",
            headers=authenticated_headers,
        )
        assert response.status_code == 200

        # Verify pinned
        response = await async_client.get(
            f"/api/v1/clusters/{cluster_id}",
            headers=authenticated_headers,
        )
        pinned_rep = next(
            r for r in response.json()["representatives"] if r["id"] == rep_id
        )
        assert pinned_rep["isUserSelected"] is True

    async def test_recompute_preserves_pinned_rep(
        self,
        async_client: AsyncClient,
        authenticated_headers: dict,
        cluster_with_reps: str,
    ) -> None:
        """Recompute should not remove pinned representatives."""
        # Pin a rep, trigger recompute, verify it's still there
        pass
```

---

## 9. Phase 0: Scaffolding

### 9.1 Schema Scaffold

```sql
-- Add to baseline migration
ALTER TABLE identity_cluster_representatives
ADD COLUMN is_user_selected BOOLEAN NOT NULL DEFAULT FALSE;
```

### 9.2 Domain Scaffold

```python
# representative.py - add field
is_user_selected: bool = False
```

### 9.3 Repository Scaffold

```python
# In ClusterRepository Protocol
async def mark_representative_user_selected(
    self, representative_id: str, is_selected: bool = True
) -> None:
    raise NotImplementedError("TODO: Implement mark_representative_user_selected")

async def get_user_selected_representatives(
    self, cluster_id: str
) -> list[ClusterRepresentative]:
    raise NotImplementedError("TODO: Implement get_user_selected_representatives")
```

---

## 10. Updated Checklist

### Phase 0: Scaffolding

- [x] Add `is_user_selected` to baseline migration <!-- id: 50 -->
- [x] Add `is_user_selected` to `ClusterRepresentative` domain object <!-- id: 51 -->
- [x] Scaffold repository methods <!-- id: 52 -->
- [x] Scaffold `_select_diverse_representatives_seeded` <!-- id: 53 -->

### Phase 1: User Protection

- [x] Implement `mark_representative_user_selected` in SqlAlchemy repo <!-- id: 54 -->
- [x] Implement `get_user_selected_representatives` in SqlAlchemy repo <!-- id: 55 -->
- [x] Update `_find_upgradeable_representative` to check `is_user_selected` <!-- id: 56 -->
- [x] Unit tests for upgrade protection <!-- id: 57 -->

### Phase 2: Recompute Preservation

- [x] Implement `_select_diverse_representatives_seeded` <!-- id: 58 -->
- [x] Modify `recompute_representatives` to preserve pinned <!-- id: 59 -->
- [x] Integration test for recompute preservation <!-- id: 60 -->

### Phase 3: Batch Deferral

- [x] Add `batch_mode` parameter to `_should_add_representative` <!-- id: 61 -->
- [x] Add `batch_mode` parameter to `persist_assignment` <!-- id: 62 -->
- [x] Update `incremental_clustering.py` to pass `batch_mode=True` <!-- id: 63 -->
- [x] Integration test for batch mode <!-- id: 64 -->

### Phase 4: API & Frontend

- [x] Implement `PATCH /clusters/{id}/representatives/{id}/pin` endpoint <!-- id: 65 -->
- [x] Add `RepresentativeThumbnail` component with pin toggle <!-- id: 66 -->
- [x] Add pin mutation hook <!-- id: 67 -->
- [x] Accessibility tests for pin button <!-- id: 68 -->

### Phase 5: Verification

- [x] Manual test: Pin rep, recompute, verify preserved <!-- id: 69 -->
- [x] Manual test: Batch process, verify no mid-batch churn <!-- id: 70 -->
- [x] Manual test: Quality upgrade respects pins <!-- id: 71 -->

---

## 11. Files Modified Summary

| File                                                                     | Change Type | Description                                |
| ------------------------------------------------------------------------ | ----------- | ------------------------------------------ |
| `db/migrations/versions/001_identity_schema.py`                          | Modify      | Add `is_user_selected` column              |
| `recognition/domain/representative.py`                                   | Modify      | Add `is_user_selected` field               |
| `recognition/domain/repositories.py`                                     | Modify      | Add pin methods to Protocol                |
| `recognition/infrastructure/repositories/cluster_repository.py`          | Modify      | Implement pin methods                      |
| `recognition/application/persistence/assignment_writer.py`               | Modify      | Add seeded FPS, batch flag, pin protection |
| `recognition/application/orchestration/incremental_clustering.py`        | Modify      | Pass `skip_upgrades=True`                  |
| `recognition/interface_adapters/http/routers/clusters.py`                | Modify      | Add pin endpoint                           |
| `js/admin/pages/workbench/identity-clusters/RepresentativeThumbnail.tsx` | New         | Pin toggle UI                              |

---

## 12. Dependencies

This plan depends on:

- 4.9.10 SSE infrastructure (for broadcasting pin state changes)
- Existing quality scoring system
- Existing pose bucketing system

No external dependencies required.

---

## 13. Risks & Mitigations

| Risk                                            | Likelihood | Impact | Mitigation                         |
| ----------------------------------------------- | ---------- | ------ | ---------------------------------- |
| Users pin all reps, blocking diversity          | Low        | Medium | UI warning when > 50% pinned       |
| Batch mode misses quality upgrade opportunities | Medium     | Low    | Recompute after batch handles this |
| Schema migration on greenfield                  | N/A        | N/A    | Direct baseline edit per policy    |
| Seeded FPS performance on large clusters        | Low        | Low    | Same O(n²) as current FPS          |
