# Cluster curation recompute implementation

## Goals

- Recompute representatives and centroid for affected clusters after split and wrong-person removal.
- Kick incremental clustering for unclustered identities after curation.
- Preserve user intent with explicit anchor selection and durable negative constraints.
- Avoid UI timeouts by moving heavy work to async jobs.

## Constraints

- Greenfield: update only the baseline migration at `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`.
- No feature flags.
- Keep contracts aligned with `docs/architecture/contracts/clustering-api.md` and `docs/architecture/contracts/workbench/recognition-identify.json`.

---

## Evaluation: How Well This Solves the Findings

### Findings Document Issues

| Issue                                          | Root Cause                                         | Implementation Coverage                           | Rating  |
| ---------------------------------------------- | -------------------------------------------------- | ------------------------------------------------- | ------- |
| **Split times out via WP proxy (60s)**         | Synchronous operation with no async path           | Phase 4 adds job-based async, Phase 2 returns 202 | ✅ Full |
| **Reps/centroid not recomputed after split**   | `split_cluster()` never calls recompute methods    | Phase 3 adds explicit recompute calls             | ✅ Full |
| **Reps/centroid not recomputed after removal** | `remove_identity_from_cluster()` doesn't recompute | Phase 3 adds recompute                            | ✅ Full |
| **Unclustered identities not re-clustered**    | No trigger after curation                          | Phase 3 schedules incremental clustering          | ✅ Full |
| **Label goes to wrong group on split**         | Uses centroid/rep heuristic, not user intent       | Phase 2/3 adds `anchor_identity_id`               | ✅ Full |
| **Wrong-person immediately re-merged**         | No negative constraint                             | Phase 1 adds `identity_cluster_blocks` table      | ✅ Full |

### Gaps in Current Spec

1. **No code snippets** — Spec describes what to do but not how, risking interpretation drift
2. **No test patterns** — Phase 6 mentions tests but doesn't show expected behavior
3. **No scaffolding examples** — Phase 0 is vague about what scaffolds to create
4. **Missing recompute method signatures** — AssignmentWriter already has these, but spec doesn't reference them

---

## Contract alignment notes

- `docs/architecture/contracts/clustering-api.md` defines WP endpoints under `/wp-json/cat/v1/...`.
- Recognition service endpoints are under `/recognition/...` (WP proxy uses `/wp-json/acx/v1/...`).
- Implementation should update the WP proxy and TypeScript types to reflect any new fields, and update the contract docs after code changes.

Proposed additions (must be reflected in docs):

- Split request: add `anchor_identity_id` (or `anchor_face_id` if WP layer uses face IDs).
- Reassign request: add `block_from_cluster: boolean` (default true when target is null).
- Responses: return job payloads when operations run async (reuse `JobStatusResponse`).

---

## Phase 0: Scaffolding (MANDATORY per instructions.md)

### 0.1 Domain Model: ClusterBlock

```python
# recognition/domain/block.py (NEW FILE)
"""Negative constraint: identity blocked from cluster."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ClusterBlock:
    """Represents a user-initiated block preventing an identity from joining a cluster.

    This is a durable negative constraint created when a user removes an identity
    from a cluster, preventing automatic re-assignment by clustering algorithms.

    Attributes:
        id: Unique block identifier (UUID string).
        tenant_id: Tenant that owns this block.
        identity_id: Identity that is blocked.
        blocked_cluster_id: Cluster the identity cannot join.
        reason: Why the block was created (e.g., "manual_removal").
        created_at: When the block was created.
        created_by_user_id: WP user who created the block (optional).
        expires_at: Optional expiration (None = never expires).
    """

    id: str
    tenant_id: str
    identity_id: str
    blocked_cluster_id: str
    reason: str
    created_at: datetime
    created_by_user_id: int | None = None
    expires_at: datetime | None = None
```

### 0.2 Repository Protocol: BlockRepository

```python
# Add to recognition/domain/repositories.py

class BlockRepository(Protocol):
    """Abstract interface for identity-cluster block persistence."""

    async def create(
        self,
        *,
        tenant_id: str,
        identity_id: str,
        blocked_cluster_id: str,
        reason: str,
        created_by_user_id: int | None = None,
    ) -> ClusterBlock:
        """Create a block preventing identity from joining cluster.

        Args:
            tenant_id: Tenant UUID string.
            identity_id: Identity UUID string to block.
            blocked_cluster_id: Cluster UUID string to block from.
            reason: Human-readable reason (e.g., "manual_removal").
            created_by_user_id: Optional WP user ID.

        Returns:
            The created ClusterBlock.

        Raises:
            ValueError: If block already exists (idempotent: return existing).
        """
        raise NotImplementedError("TODO: implement create")

    async def get_blocks_for_identity(
        self,
        tenant_id: str,
        identity_id: str,
    ) -> list[ClusterBlock]:
        """List all clusters blocked for an identity.

        Args:
            tenant_id: Tenant UUID string.
            identity_id: Identity UUID string.

        Returns:
            List of active blocks (excludes expired).
        """
        raise NotImplementedError("TODO: implement get_blocks_for_identity")

    async def is_blocked(
        self,
        *,
        tenant_id: str,
        identity_id: str,
        cluster_id: str,
    ) -> bool:
        """Check if identity is blocked from cluster.

        Args:
            tenant_id: Tenant UUID string.
            identity_id: Identity UUID string.
            cluster_id: Cluster UUID string to check.

        Returns:
            True if a non-expired block exists.
        """
        raise NotImplementedError("TODO: implement is_blocked")

    async def remove_block(
        self,
        *,
        tenant_id: str,
        identity_id: str,
        blocked_cluster_id: str,
    ) -> bool:
        """Remove a block (e.g., when user explicitly reassigns).

        Args:
            tenant_id: Tenant UUID string.
            identity_id: Identity UUID string.
            blocked_cluster_id: Cluster UUID string.

        Returns:
            True if a block was removed, False if none existed.
        """
        raise NotImplementedError("TODO: implement remove_block")
```

### 0.3 Request Schema Updates

```python
# Update recognition/interface_adapters/http/schemas/requests.py

class SplitClusterRequest(BaseModel):
    """Request to split a cluster using hierarchical clustering.

    Args:
        tenant_id: The tenant that owns the cluster.
        n_clusters: Number of clusters to split into.
                   0 = auto-detect based on similarity (default).
                   2+ = force exactly this many clusters.
        anchor_identity_id: Identity that should keep the original label.
                           If provided, the group containing this identity
                           retains the cluster's current label.
    """

    tenant_id: str
    n_clusters: int = Field(default=0, ge=0, description="0=auto-detect, 2+=fixed count")
    anchor_identity_id: str | None = Field(
        default=None,
        description="Identity ID to anchor label assignment. Group containing this ID keeps the label.",
    )

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, v: str) -> str:
        return _validate_uuid(v)

    @field_validator("anchor_identity_id")
    @classmethod
    def validate_anchor_identity_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_uuid(v)


class ReassignIdentityRequest(BaseModel):
    """Request to reassign an identity to a different cluster.

    Used for:
    - Accepting inline suggestions (moving singleton to labeled cluster)
    - Moving identity between clusters (correction)
    - Removing from cluster (set target_cluster_id to null)

    When removing (target_cluster_id=null), block_from_cluster controls whether
    to prevent automatic re-assignment to the source cluster.
    """

    tenant_id: str
    identity_id: str
    target_cluster_id: str | None = None
    block_from_cluster: bool = Field(
        default=True,
        description="When removing, create a block preventing re-assignment to source cluster.",
    )

    # ... existing validators ...
```

---

## Phase 1: Data model

### 1.1 Baseline Migration Addition

Add to `db/migrations/versions/001_identity_schema.py` after the `identity_suggestions` table:

```python
# Add to TENANT_TABLES list at top of file:
# "identity_cluster_blocks",

op.create_table(
    "identity_cluster_blocks",
    sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "tenant_id",
        sa.dialects.postgresql.UUID(as_uuid=True),
        sa.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "identity_id",
        sa.dialects.postgresql.UUID(as_uuid=True),
        sa.ForeignKey("media_identities.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "blocked_cluster_id",
        sa.dialects.postgresql.UUID(as_uuid=True),
        sa.ForeignKey("identity_clusters.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("reason", sa.Text(), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    sa.Column("created_by_user_id", sa.Integer(), nullable=True),
    sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.UniqueConstraint(
        "tenant_id", "identity_id", "blocked_cluster_id",
        name="unique_identity_cluster_block",
    ),
)

# Add indexes
op.create_index(
    "idx_identity_cluster_blocks_identity",
    "identity_cluster_blocks",
    ["tenant_id", "identity_id"],
)
op.create_index(
    "idx_identity_cluster_blocks_cluster",
    "identity_cluster_blocks",
    ["tenant_id", "blocked_cluster_id"],
)
```

### 1.2 SQLAlchemy Model

```python
# Add to db/models.py

class IdentityClusterBlock(Base):
    """Negative constraint preventing identity from joining a cluster."""

    __tablename__ = "identity_cluster_blocks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_identities.id", ondelete="CASCADE"), nullable=False
    )
    blocked_cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_clusters.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    __table_args__ = (
        UniqueConstraint("tenant_id", "identity_id", "blocked_cluster_id", name="unique_identity_cluster_block"),
        Index("idx_identity_cluster_blocks_identity", "tenant_id", "identity_id"),
        Index("idx_identity_cluster_blocks_cluster", "tenant_id", "blocked_cluster_id"),
    )
```

---

## Phase 2: API changes (recognition service)

### 2.1 Split Endpoint Update

```python
# recognition/interface_adapters/http/routers/clusters.py

@router.post("/clusters/{cluster_id}/split", response_model=SplitClusterResponse)
async def split_cluster(
    cluster_id: str,
    request: SplitClusterRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
) -> SplitClusterResponse:
    """Split a cluster using hierarchical clustering.

    If anchor_identity_id is provided, the group containing that identity
    keeps the original cluster label.
    """
    validate_entity_id(cluster_id, field_name="cluster_id")
    if request.anchor_identity_id:
        validate_entity_id(request.anchor_identity_id, field_name="anchor_identity_id")
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    cluster_service = await build_cluster_service(session=session, tenant_id=request.tenant_id)
    new_ids, counts = await cluster_service.split_cluster(
        cluster_id,
        n_clusters=request.n_clusters,
        anchor_identity_id=request.anchor_identity_id,  # NEW
    )

    return SplitClusterResponse(
        new_cluster_ids=new_ids,
        moved_counts=counts,
        new_cluster_id=new_ids[0] if new_ids else None,
        moved_count=counts[0] if counts else 0,
    )
```

### 2.2 Reassign Endpoint Update

```python
# recognition/interface_adapters/http/routers/clusters.py

@router.post("/clusters/reassign", response_model=ReassignIdentityResponse)
async def reassign_identity(
    request: ReassignIdentityRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
) -> ReassignIdentityResponse:
    """Reassign an identity to a different cluster.

    When target_cluster_id is null:
    - Identity is removed from its current cluster
    - If block_from_cluster=True (default), creates a block preventing re-assignment

    When target_cluster_id is set:
    - If a block exists for that cluster, it is removed first
    - Identity is moved to the target cluster
    """
    # ... existing validation ...

    # Get source cluster before removal
    source_cluster_id = await get_identity_cluster_id(
        member_repo=member_repo,
        identity_id=request.identity_id,
    )

    if request.target_cluster_id is None:
        # Removal case
        await remove_identity_from_cluster(...)

        # Create block if requested
        if request.block_from_cluster and source_cluster_id:
            block_repo = get_block_repository(session)
            await block_repo.create(
                tenant_id=request.tenant_id,
                identity_id=request.identity_id,
                blocked_cluster_id=source_cluster_id,
                reason="manual_removal",
            )

        # Recompute source cluster (see Phase 3)
        # Schedule incremental clustering (see Phase 3)
    else:
        # Reassignment case - remove any existing block first
        block_repo = get_block_repository(session)
        await block_repo.remove_block(
            tenant_id=request.tenant_id,
            identity_id=request.identity_id,
            blocked_cluster_id=request.target_cluster_id,
        )
        # ... existing reassignment logic ...
```

---

## Phase 3: Orchestration changes

### 3.1 Split Recompute

Update `recognition/application/orchestration/cluster_split.py`:

```python
async def split_cluster(
    *,
    cluster_id: str,
    n_clusters: int,
    session: AsyncSession | None,
    cluster_repo: ClusterRepository,
    member_repo: MemberRepository,
    assignment_writer: AssignmentWriter | None = None,  # NEW
    anchor_identity_id: str | None = None,  # NEW
    clustering_logger: ClusteringLogger | None = None,
) -> tuple[list[str], list[int]]:
    """Split a mixed cluster using hierarchical clustering.

    Args:
        cluster_id: Cluster to split.
        n_clusters: Target number of clusters (0=auto).
        session: Database session.
        cluster_repo: Cluster repository.
        member_repo: Member repository.
        assignment_writer: Writer for recomputing reps/centroid (optional).
        anchor_identity_id: Identity that should keep the original label.
        clustering_logger: Logger for observability.

    Returns:
        Tuple of (new_cluster_ids, moved_counts).
    """
    # ... existing splitting logic ...

    # NEW: Use anchor_identity_id to determine label owner
    if anchor_identity_id:
        anchor_label = identity_to_label.get(anchor_identity_id.lower())
        if anchor_label is not None:
            label_owner = anchor_label

    # ... existing cluster creation and member movement ...

    # NEW: Recompute representatives and centroid for all affected clusters
    affected_cluster_ids = [cluster_id] + new_cluster_ids
    if assignment_writer:
        for cid in affected_cluster_ids:
            await assignment_writer.recompute_representatives(cid)
            await assignment_writer.recompute_centroid(cid)

        # Refresh centroids view for discovery
        await assignment_writer.refresh_centroids_view()

    return new_cluster_ids, moved_counts
```

### 3.2 Removal Recompute

Update `recognition/application/orchestration/cluster_curation.py`:

```python
async def remove_identity_from_cluster(
    *,
    identity_id: str,
    member_repo: MemberRepository,
    cluster_repo: ClusterRepository,
    assignment_writer: AssignmentWriter | None = None,  # NEW
    tenant_id_for_logging: str | None = None,
    media_id: int | None = None,
) -> bool:
    """Remove an identity from its current cluster (make it an orphan).

    After removal:
    - Source cluster's reps/centroid are recomputed
    - Centroids view is refreshed
    """
    # ... existing removal logic ...

    if removed and assignment_writer:
        # Recompute source cluster
        await assignment_writer.recompute_representatives(cluster_id)
        await assignment_writer.recompute_centroid(cluster_id)
        await assignment_writer.refresh_centroids_view()

    return True
```

### 3.3 Block Check in Assignment Gates

Update assignment checks to respect blocks:

```python
# recognition/application/assignment/checks/block_check.py (NEW FILE)
"""Block check: prevent assignment to blocked clusters."""

from __future__ import annotations

from recognition.application.assignment.candidate import AssignmentCandidate
from recognition.application.assignment.checks.base import AssignmentCheck, CheckResult
from recognition.domain.repositories import BlockRepository


class BlockCheck(AssignmentCheck):
    """Rejects candidates where identity is blocked from the target cluster."""

    name = "block_check"

    def __init__(self, block_repository: BlockRepository) -> None:
        self._block_repo = block_repository

    def is_enabled(self) -> bool:
        return True

    async def evaluate(self, candidate: AssignmentCandidate) -> CheckResult:
        """Check if identity is blocked from target cluster.

        Args:
            candidate: Proposed assignment.

        Returns:
            CheckResult with passed=False if blocked.
        """
        is_blocked = await self._block_repo.is_blocked(
            tenant_id=candidate.identity.tenant_id,
            identity_id=candidate.identity.id,
            cluster_id=candidate.cluster_id,
        )

        if is_blocked:
            return CheckResult(
                passed=False,
                is_fatal=True,
                should_reject=True,
                reason="identity blocked from cluster by user",
                metadata={"block_active": True},
            )

        return CheckResult(passed=True, metadata={"block_active": False})
```

---

## Phase 4: Jobs and worker

### 4.1 Job Type

Add to `recognition/domain/job.py`:

```python
class JobType(str, Enum):
    """Supported job categories."""

    ANALYZE = "analyze"
    CLUSTERING = "clustering"
    CURATION = "curation"  # NEW: Post-curation recompute and re-clustering
```

### 4.2 Curation Job Handler

The curation job should:

1. Recompute reps/centroid for specified cluster IDs
2. Refresh centroids view
3. Run incremental clustering if unclustered identities exist

```python
# recognition/application/orchestration/curation_job.py (NEW FILE)
"""Background job for post-curation cleanup."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.repositories import ClusterRepository

logger = logging.getLogger(__name__)


async def run_curation_job(
    *,
    tenant_id: str,
    cluster_ids: Sequence[str],
    assignment_writer: AssignmentWriter,
    cluster_repo: ClusterRepository,
    run_incremental_clustering: bool = True,
) -> dict[str, int]:
    """Execute post-curation cleanup tasks.

    Args:
        tenant_id: Tenant owning the clusters.
        cluster_ids: Clusters to recompute.
        assignment_writer: For recompute operations.
        cluster_repo: For checking unclustered.
        run_incremental_clustering: Whether to re-cluster orphans.

    Returns:
        Dict with counts: {"clusters_recomputed": N, "identities_clustered": M}
    """
    logger.info(
        "[curation_job] START tenant_id=%s cluster_ids=%s",
        tenant_id,
        cluster_ids,
    )

    # 1. Recompute reps/centroid for each cluster
    for cid in cluster_ids:
        await assignment_writer.recompute_representatives(cid)
        await assignment_writer.recompute_centroid(cid)

    # 2. Refresh centroids view
    await assignment_writer.refresh_centroids_view()

    # 3. Run incremental clustering if needed
    identities_clustered = 0
    if run_incremental_clustering:
        unclustered = await cluster_repo.get_unclustered(tenant_id)
        if unclustered:
            from recognition.application.orchestration.incremental_clustering import (
                cluster_unclustered_identities,
            )
            # ... call incremental clustering ...

    logger.info(
        "[curation_job] COMPLETE tenant_id=%s clusters_recomputed=%d identities_clustered=%d",
        tenant_id,
        len(cluster_ids),
        identities_clustered,
    )

    return {
        "clusters_recomputed": len(cluster_ids),
        "identities_clustered": identities_clustered,
    }
```

---

## Phase 5: WP proxy and frontend

### 5.1 WP Proxy Updates

```php
// apps/prototype-wp-alt-context/src/api/class-recognition-proxy-controller.php

// Split endpoint - forward anchor_identity_id
$body = [
    'tenant_id'          => $tenant_id,
    'n_clusters'         => $request->get_param('n_clusters') ?? 0,
    'anchor_identity_id' => $request->get_param('anchor_identity_id'),
];

// Reassign endpoint - forward block_from_cluster
$body = [
    'tenant_id'          => $tenant_id,
    'identity_id'        => $request->get_param('identity_id'),
    'target_cluster_id'  => $request->get_param('target_cluster_id'),
    'block_from_cluster' => $request->get_param('block_from_cluster') ?? true,
];
```

### 5.2 TypeScript Types

```typescript
// apps/prototype-wp-alt-context/js/admin/api/recognition/types/clusters.ts

export interface SplitClusterRequest {
  n_clusters?: number;
  anchor_identity_id?: string; // NEW
}

export interface ReassignIdentityRequest {
  identity_id: string;
  target_cluster_id: string | null;
  block_from_cluster?: boolean; // NEW: default true
}
```

---

## Phase 6: Tests

### 6.1 Unit Tests: Block Repository

```python
# recognition/tests/unit/test_block_repository.py

@pytest.mark.asyncio
async def test_create_block_prevents_reassignment():
    """Creating a block should prevent is_blocked from returning True."""
    repo = FakeBlockRepository()

    await repo.create(
        tenant_id="t1",
        identity_id="i1",
        blocked_cluster_id="c1",
        reason="manual_removal",
    )

    assert await repo.is_blocked(tenant_id="t1", identity_id="i1", cluster_id="c1")
    assert not await repo.is_blocked(tenant_id="t1", identity_id="i1", cluster_id="c2")


@pytest.mark.asyncio
async def test_remove_block_allows_reassignment():
    """Removing a block should allow is_blocked to return False."""
    repo = FakeBlockRepository()
    await repo.create(tenant_id="t1", identity_id="i1", blocked_cluster_id="c1", reason="test")

    await repo.remove_block(tenant_id="t1", identity_id="i1", blocked_cluster_id="c1")

    assert not await repo.is_blocked(tenant_id="t1", identity_id="i1", cluster_id="c1")
```

### 6.2 Integration Tests: Split with Anchor

```python
# recognition/tests/integration/test_split_anchor.py

@pytest.mark.integration
async def test_split_keeps_label_on_anchor_group(db_session):
    """When anchor_identity_id is provided, that group keeps the original label."""
    # Setup: cluster with 4 identities, 2 similar to each other, 2 different
    cluster = await create_cluster(label="Alice", identities=[i1, i2, i3, i4])

    # i1 and i2 are similar (Alice), i3 and i4 are similar (Not Alice)
    # i2 is the anchor
    new_ids, counts = await split_cluster(
        cluster_id=cluster.id,
        anchor_identity_id=i2.id,
    )

    # The original cluster (containing i2) should keep "Alice" label
    original = await cluster_repo.get_by_id(cluster.id)
    assert original.label == "Alice"

    # The new cluster should have a split label
    new_cluster = await cluster_repo.get_by_id(new_ids[0])
    assert "split" in new_cluster.label.lower() or new_cluster.label != "Alice"
```

---

## Observability

Add structured logging with these fields:

```python
logger.info(
    "[curation] SPLIT original_cluster=%s anchor_identity_id=%s new_clusters=%s "
    "recompute_duration_ms=%d tenant_id=%s user_action=manual_split",
    cluster_id,
    anchor_identity_id,
    new_cluster_ids,
    recompute_duration_ms,
    tenant_id,
)

logger.info(
    "[curation] BLOCK_CREATED identity=%s blocked_cluster=%s reason=%s tenant_id=%s",
    identity_id,
    blocked_cluster_id,
    reason,
    tenant_id,
)
```

---

## Open questions

- Should WP use face IDs or identity IDs when passing `anchor_identity_id`?
- Do we want blocks to expire automatically (time-based) or only by explicit user action?
- Is a separate curation queue needed if scan worker remains unstable?

## Proposed answers

Anchor ID: use identity_id (media identity UUID), not face IDs. Identity IDs are stable, backend-owned, and already used by split/cluster logic. Face IDs are often frontend-only or ephemeral. If the WP UI only has face IDs, update the API to include identity_id in the cluster/identity payload and pass that as anchor_identity_id.

Block expiration: default to no automatic expiry. This is explicit user correction, so keep the block until the user explicitly reassigns/merges. Allow an override path (explicit user action removes the block). If you later add TTL, keep it long and treat it as a safety net, not the default.

Curation queue: start by reusing the existing worker (no separate queue). Add a curation job type, run it at higher priority, keep tasks short. If the worker remains unstable after fixes, then split into a dedicated queue.

---

## Implementation Checklist

Current phase: Complete

### Phase 0: Scaffolding (complete)

- [x] Add `IdentityClusterBlock` dataclass to `recognition/domain/repositories.py`
- [x] Add `IdentityClusterBlockRepository` protocol to `recognition/domain/repositories.py`
- [x] Add scaffold `SqlAlchemyIdentityClusterBlockRepository` in `recognition/infrastructure/repositories/identity_cluster_block_repository.py`
- [x] Update `SplitClusterRequest` with `anchor_identity_id` field
- [x] Update `ReassignIdentityRequest` with `block_from_cluster` field
- [x] Add `JobType.CURATION` to `recognition/domain/job.py`
- [x] Allow `JobStatusResponse.type` to include `curation`

### Phase 1: Data Model (complete)

- [x] Add `identity_cluster_blocks` table to baseline migration
- [x] Add `IdentityClusterBlock` model to `db/models.py`
- [x] Implement `SqlAlchemyIdentityClusterBlockRepository`

### Phase 2: API Changes

- [x] Update split endpoint to accept and forward `anchor_identity_id`
- [x] Update reassign endpoint to handle `block_from_cluster`
- [x] Add block creation on removal
- [x] Add block removal on explicit reassignment

### Phase 3: Orchestration

- [x] Update `split_cluster()` to use anchor for label assignment
- [x] Add recompute calls after split
- [x] Add recompute calls after removal
- [x] Create `BlockCheck` assignment gate
- [x] Wire `BlockCheck` into assignment pipeline

### Phase 4: Jobs

- [x] Create `curation_job.py` with `run_curation_job()`
- [x] Wire curation job into worker

### Phase 5: Frontend

- [x] Update WP proxy to forward new fields
- [x] Update TypeScript types
- [x] Pass `anchor_identity_id` from UI on split

### Phase 6: Tests

- [x] Unit tests for `IdentityClusterBlockRepository`
- [x] Unit tests for `BlockCheck`
- [x] Integration test for split with anchor
- [x] Integration test for removal with block
