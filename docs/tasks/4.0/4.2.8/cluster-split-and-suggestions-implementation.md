# Cluster split and suggestions implementation plan

## Goals

- Treat user-initiated split as ground truth: always create at least two clusters.
- Prevent immediate re-merge after split via durable negative constraints.
- Recompute representatives and centroids for affected clusters after curation.
- Recompute suggestions after every user curation on the affected identities.
- Auto confirm or auto reject suggestions as the user curates identities.

## Non-goals

- No feature flags.
- No migrations beyond the baseline file.
- No changes outside the monorepo boundaries.

---

## Log Analysis Insights (2024-12-20)

**Source:** [log-analysis-curation-patterns.md](log-analysis-curation-patterns.md)

### Key Findings

| Metric                   | Value          | Implication                                               |
| ------------------------ | -------------- | --------------------------------------------------------- |
| Singleton merges         | 74% (14/19)    | Users manually hunting for false negatives                |
| Auto-rejections          | 25             | Creating orphan identities that need manual correction    |
| Complete-link rejections | 76% of rejects | Marginal similarity failures, prime suggestion candidates |

### Priority Adjustment

Based on production data, implementation priority should be:

1. **Phase 3 (Highest):** Suggestion refresh - addresses 74% singleton merge pattern
2. **Phase 2 (Medium):** Forced split - only 1 split in logs but critical for correctness
3. **Phase 4 (Lower):** UI components - depends on Phase 3 backend

### Threshold Recommendations

- `suggestion_floor: 0.70` - captures marginal rejects currently becoming orphans
- `suggestion_ceiling: 0.85` - existing accept threshold
- `anchor_split_similarity_floor: 0.85` - keep similar faces with anchor

### Expected UX Improvements

- **86% reduction** in singleton merge time (30s manual to 3s suggestion review)
- **Auto-surface** related faces after cluster labeling
- **Eliminate manual hunting** for related identities

---

## Constraints

- Greenfield policy: update only `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`.
- TDD required: tests before implementation.
- Scaffolding required before tests or implementation.
- ASCII-only documentation.

---

## Architecture Overview

```
User Action (Split / Reassign / Remove)
          |
          v
+-------------------+     +----------------------+
| Curation Endpoint | --> | split_cluster()      |
| (clusters.py)     |     | force_two_way_split()|
+-------------------+     +----------------------+
          |                         |
          v                         v
+-------------------+     +------------------------+
| BlockRepository   |     | AssignmentWriter       |
| (persist blocks)  |     | (recompute reps/cent)  |
+-------------------+     +------------------------+
          |                         |
          v                         v
+-------------------+     +------------------------+
| SuggestionService |     | AssignmentGate         |
| refresh_for_*()   |     | BlockCheck (is_fatal)  |
| resolve_*()       |     +------------------------+
+-------------------+
```

## Strategy overview

### Split strategy (user-initiated)

- Require an explicit `anchor_identity_id` for split requests.
- Use the anchor to force a two-way split, even when embeddings are similar.
- Persist negative constraints so the two groups cannot merge automatically.
- Recompute representatives and centroids for all affected clusters.

### Suggestions strategy (marginal rejects)

- Convert marginal rejects into pending suggestions rather than hard rejects.
- Recompute suggestions for the affected identity on each curation event.
- Resolve suggestions automatically based on user actions (accept/reject).
- Keep suggestion scores up to date as clusters change.

**Log-validated patterns to address:**

- 74% of merges are singleton corrections (1 identity moved)
- 76% of rejections are pure similarity threshold failures
- Users immediately merge after labeling (suggestion refresh trigger)
- Batch merges indicate related unlabeled clusters exist

---

## Phase 0: Scaffolding (MANDATORY)

### 0.1 Split intent and strategy types

**File:** `recognition/application/orchestration/cluster_split.py`

```python
from enum import Enum
from dataclasses import dataclass


class SplitStrategy(Enum):
    """Strategy for determining how to split a cluster."""

    AUTO = "auto"           # Hierarchical clustering decides group count
    FORCED_BINARY = "forced_binary"  # Always split into exactly 2 groups


class SplitScope(Enum):
    """Scope limiting which identities participate in a split."""

    ALL_MEMBERS = "all_members"  # Split considers all cluster members
    MEDIA_SCOPED = "media_scoped"  # Future: limit to identities from specific media


@dataclass
class SplitPlan:
    """Validated plan for executing a cluster split.

    Args:
        cluster_id: Target cluster to split.
        strategy: How to determine groups.
        anchor_identity_id: Identity that must end up with original label.
        scope: Which members participate in the split.
        n_clusters: Requested cluster count (0 = auto-detect).

    Raises:
        ValueError: If anchor_identity_id is required but missing for FORCED_BINARY.
    """

    cluster_id: str
    strategy: SplitStrategy
    anchor_identity_id: str | None
    scope: SplitScope = SplitScope.ALL_MEMBERS
    n_clusters: int = 0

    def __post_init__(self) -> None:
        if self.strategy == SplitStrategy.FORCED_BINARY and not self.anchor_identity_id:
            raise ValueError("FORCED_BINARY strategy requires anchor_identity_id")
```

**File:** `recognition/interface_adapters/http/schemas/requests.py`

Update `SplitClusterRequest` to include `split_mode`:

```python
class SplitClusterRequest(BaseModel):
    """Request to split a cluster using hierarchical clustering.

    Args:
        tenant_id: The tenant that owns the cluster.
        n_clusters: Number of clusters to split into.
                    0 = auto-detect based on similarity (default).
                    2+ = force exactly this many clusters.
        anchor_identity_id: Identity ID used to keep labels with the selected person.
                            Required when split_mode is 'forced'.
        split_mode: 'auto' uses hierarchical clustering, 'forced' guarantees
                    at least two clusters even when faces are similar.
    """

    tenant_id: str
    n_clusters: int = Field(default=0, ge=0, description="0=auto-detect, 2+=fixed count")
    anchor_identity_id: str | None = None
    split_mode: Literal["auto", "forced"] = "auto"

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
```

### 0.2 Suggestion refresh interfaces

**File:** `recognition/application/suggestions/service.py`

Add new method signatures to `SuggestionService`:

```python
class SuggestionRefreshReason(Enum):
    """Reason triggering a suggestion refresh."""

    MANUAL_SPLIT = "manual_split"
    WRONG_PERSON = "wrong_person"
    MANUAL_ASSIGN = "manual_assign"
    MANUAL_MERGE = "manual_merge"
    CLUSTER_RECOMPUTE = "cluster_recompute"


class SuggestionService:
    # ... existing methods ...

    async def refresh_for_identity(
        self,
        identity_id: str,
        reason: SuggestionRefreshReason,
        *,
        exclude_cluster_ids: list[str] | None = None,
    ) -> list[AssignmentSuggestion]:
        """Recompute suggestions for an identity after curation.

        Re-runs representative + centroid matching for the identity,
        generates suggestions for candidates in the suggestion band,
        and upserts pending suggestions with updated similarity/confidence.
        Skips blocked clusters and clusters in exclude_cluster_ids.

        Args:
            identity_id: Identity to refresh suggestions for.
            reason: What triggered the refresh (for logging/observability).
            exclude_cluster_ids: Clusters to skip during refresh.

        Returns:
            List of created/updated suggestions.

        Raises:
            NotImplementedError: Until implemented.
        """
        raise NotImplementedError("TODO: refresh_for_identity")

    async def resolve_for_identity_exclusive(
        self,
        identity_id: str,
        accepted_cluster_id: str,
    ) -> int:
        """Accept one suggestion and reject all others for an identity.

        Used when user confirms assignment via curation action.
        Accepts the suggestion matching accepted_cluster_id and
        rejects all other pending suggestions for the same identity.

        Args:
            identity_id: Identity whose suggestions to resolve.
            accepted_cluster_id: Cluster whose suggestion should be accepted.

        Returns:
            Total number of suggestions resolved.

        Raises:
            NotImplementedError: Until implemented.
        """
        raise NotImplementedError("TODO: resolve_for_identity_exclusive")
```

### 0.3 New repo helpers (scaffold only)

**File:** `recognition/domain/repositories.py`

Add to `SuggestionRepository` protocol:

```python
class SuggestionRepository(Protocol):
    # ... existing methods ...

    async def bulk_update_status(
        self,
        tenant_id: str,
        suggestion_ids: list[str],
        status: SuggestionStatus,
    ) -> int:
        """Update status for multiple suggestions in a single operation.

        Args:
            tenant_id: Tenant scope for the operation.
            suggestion_ids: Suggestions to update.
            status: New status to apply.

        Returns:
            Number of suggestions updated.
        """
        ...

    async def upsert_by_identity_cluster(
        self,
        tenant_id: str,
        identity_id: str,
        cluster_id: str,
        *,
        representative_similarity: float,
        member_similarity: float,
        confidence_score: float,
    ) -> AssignmentSuggestion:
        """Create or update suggestion for identity-cluster pair.

        Idempotent: if a pending suggestion exists, update its scores.
        If no pending suggestion exists, create one.
        Does not modify accepted/rejected suggestions.

        Args:
            tenant_id: Tenant scope.
            identity_id: Identity for the suggestion.
            cluster_id: Target cluster for the suggestion.
            representative_similarity: Similarity to best representative.
            member_similarity: Average similarity to cluster members.
            confidence_score: Combined confidence score.

        Returns:
            Created or updated suggestion.
        """
        ...
```

---

## Phase 1: Contract and data model updates

### 1.1 HTTP request contracts

**File:** `recognition/interface_adapters/http/schemas/requests.py`

Already scaffolded in Phase 0. Ensure validation:

```python
@field_validator("anchor_identity_id", "split_mode")
@classmethod
def validate_forced_mode_anchor(cls, v: str | None, info) -> str | None:
    """Ensure anchor_identity_id is provided when split_mode is 'forced'."""
    # Note: Cross-field validation handled in model_validator if needed
    return v
```

**File:** `apps/prototype-wp-alt-context/src/REST/RecognitionProxyController.php`

Ensure WP proxy forwards new fields:

```php
// In handle_split_cluster_request()
$body = [
    'tenant_id' => $this->get_tenant_id(),
    'n_clusters' => $request->get_param('nClusters') ?? 0,
    'anchor_identity_id' => $request->get_param('anchorIdentityId'),
    'split_mode' => $request->get_param('splitMode') ?? 'auto',
];
```

**File:** `apps/prototype-wp-alt-context/js/admin/api/recognition/types/cluster.ts`

```typescript
export interface SplitClusterRequest {
  nClusters?: number;
  anchorIdentityId?: string;
  splitMode?: "auto" | "forced";
}
```

### 1.2 Baseline migration updates (if needed)

**File:** `db/migrations/versions/001_identity_schema.py`

Add `source` and `refreshed_at` columns to `identity_suggestions` if not present:

```python
# In identity_suggestions table definition
sa.Column("source", sa.String(50), nullable=True, comment="Reason for suggestion creation"),
sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True, comment="Last refresh timestamp"),
```

The `identity_cluster_blocks` table should already exist from previous work.
If not present, add:

```python
identity_cluster_blocks = sa.Table(
    "identity_cluster_blocks",
    metadata,
    sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id"), nullable=False),
    sa.Column("identity_id", sa.UUID(), nullable=False),
    sa.Column("blocked_cluster_id", sa.UUID(), nullable=False),
    sa.Column("reason", sa.String(255), nullable=True),
    sa.Column("created_by_user_id", sa.Integer(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.UniqueConstraint("tenant_id", "identity_id", "blocked_cluster_id", name="uq_identity_cluster_block"),
)
sa.Index("ix_identity_cluster_blocks_lookup", identity_cluster_blocks.c.tenant_id, identity_cluster_blocks.c.identity_id)
```

---

## Phase 2: Forced split implementation

### 2.1 Anchor-first split algorithm

**File:** `recognition/application/orchestration/cluster_split.py`

Add forced split function:

```python
async def force_two_way_split(
    *,
    identities: list[MediaIdentityModel],
    anchor_identity_id: str,
    anchor_split_similarity_floor: float = 0.85,
) -> dict[int, list[MediaIdentityModel]]:
    """Force a binary split when hierarchical clustering yields one group.

    Args:
        identities: All identities in the cluster.
        anchor_identity_id: Identity that defines the "keep" group.
        anchor_split_similarity_floor: Minimum similarity to anchor for group membership.

    Returns:
        Dictionary with label 0 (anchor group) and label 1 (other group).

    Raises:
        ValueError: If anchor not found or only one identity present.
    """
    anchor = next((i for i in identities if str(i.id).lower() == anchor_identity_id.lower()), None)
    if anchor is None:
        raise ValueError(f"Anchor identity {anchor_identity_id} not found in cluster")

    if len(identities) < 2:
        raise ValueError("Cannot split cluster with fewer than 2 identities")

    anchor_vec = _normalize_embedding(np.asarray(anchor.embedding, dtype=np.float32))

    # Compute similarity of each identity to anchor
    similarities: list[tuple[MediaIdentityModel, float]] = []
    for identity in identities:
        if str(identity.id).lower() == anchor_identity_id.lower():
            similarities.append((identity, 1.0))  # Anchor is always in its own group
            continue
        vec = _normalize_embedding(np.asarray(identity.embedding, dtype=np.float32))
        sim = float(np.dot(anchor_vec, vec))
        similarities.append((identity, sim))

    # Sort by similarity descending
    similarities.sort(key=lambda x: x[1], reverse=True)

    # Anchor group: anchor + identities above threshold
    anchor_group: list[MediaIdentityModel] = []
    other_group: list[MediaIdentityModel] = []

    for identity, sim in similarities:
        if str(identity.id).lower() == anchor_identity_id.lower():
            anchor_group.append(identity)
        elif sim >= anchor_split_similarity_floor:
            anchor_group.append(identity)
        else:
            other_group.append(identity)

    # Guarantee at least one identity in the other group
    if not other_group and len(anchor_group) > 1:
        # Move the farthest identity (last in sorted anchor_group) to other
        farthest = anchor_group.pop()
        other_group.append(farthest)

    return {0: anchor_group, 1: other_group}
```

Modify `split_cluster` to use forced split:

```python
async def split_cluster(
    *,
    cluster_id: str,
    n_clusters: int,
    anchor_identity_id: str | None = None,
    split_mode: str = "auto",  # NEW PARAMETER
    session: AsyncSession | None,
    cluster_repo: ClusterRepository,
    member_repo: MemberRepository,
    block_repo: IdentityClusterBlockRepository | None = None,  # NEW PARAMETER
    assignment_writer: AssignmentWriter | None = None,
    recompute: bool = True,
    clustering_logger: ClusteringLogger | None = None,
) -> tuple[list[str], list[int]]:
    """Split a mixed cluster using hierarchical clustering.

    When split_mode='forced' and hierarchical returns one group,
    forces a binary split using the anchor identity.
    """
    # ... existing code to fetch members and embeddings ...

    # 2. Use HierarchicalClustering to split identities
    hierarchical = HierarchicalClustering(distance_threshold=0.30)
    clusters_by_label = hierarchical.split_identities(identities, n_clusters)

    # NEW: Force split when hierarchical fails and forced mode requested
    if len(clusters_by_label) <= 1 and split_mode == "forced" and anchor_identity_id:
        logger.info(
            "Split cluster %s: Hierarchical returned one group, forcing binary split with anchor=%s",
            cluster_id,
            anchor_identity_id,
        )
        clusters_by_label = await force_two_way_split(
            identities=identities,
            anchor_identity_id=anchor_identity_id,
        )

    # Check if we found multiple groups
    if len(clusters_by_label) <= 1:
        logger.info("Split cluster %s: All faces similar enough to stay together, nothing to split", cluster_id)
        return [], []

    # ... rest of existing logic ...
```

### 2.2 Label ownership

**Already implemented in existing `split_cluster`:**

```python
# Keep user labels on the group that best matches the original cluster.
label_owner = None
if anchor_identity_id:
    anchor_label = identity_to_label.get(anchor_identity_id.lower())
    if anchor_label is not None:
        label_owner = anchor_label
```

No additional changes needed. The anchor group keeps the original label.

### 2.3 Persist negative constraints

**File:** `recognition/application/orchestration/cluster_split.py`

Add block creation after split:

```python
# After creating new clusters, persist blocks
if block_repo is not None:
    for label, count in sorted_labels[1:]:  # Non-anchor groups
        identity_ids_for_group = [ids[i] for i, lbl in enumerate(labels) if lbl == label]
        for identity_id in identity_ids_for_group:
            # Block each moved identity from the original cluster
            await block_repo.add_block(
                tenant_id=original_cluster.tenant_id,
                identity_id=identity_id,
                blocked_cluster_id=cluster_id,
                reason="manual_split",
            )
            logger.debug(
                "Created block: identity=%s blocked from cluster=%s reason=manual_split",
                identity_id,
                cluster_id,
            )
```

### 2.4 Recompute outputs

**Already implemented in existing `split_cluster`:**

```python
if assignment_writer and new_cluster_ids and recompute:
    affected_cluster_ids = [cluster_id, *new_cluster_ids]
    recompute_reps = getattr(assignment_writer, "recompute_representatives", None)
    if callable(recompute_reps):
        for affected_id in affected_cluster_ids:
            await recompute_reps(affected_id)
    recompute_centroid = getattr(assignment_writer, "recompute_centroid", None)
    if callable(recompute_centroid):
        for affected_id in affected_cluster_ids:
            await recompute_centroid(affected_id)
    refresh_view = getattr(assignment_writer, "refresh_centroids_view", None)
    if callable(refresh_view):
        await refresh_view()
```

No additional changes needed.

---

## Phase 3: Suggestions engine improvements

**Priority: HIGHEST** (based on log analysis - addresses 74% singleton merge pattern)

### 3.1 Marginal reject -> suggestion

**File:** `recognition/application/settings/clustering.py`

Add suggestion band settings:

```python
class ClusteringSettings(BaseModel):
    # ... existing fields ...

    suggestion_floor: float = Field(
        default=0.70,
        description="Minimum similarity for suggestion creation. Below this = hard reject.",
    )
    suggestion_ceiling: float = Field(
        default=0.85,
        description="Maximum similarity for suggestion. Above this = auto-accept.",
    )
```

**File:** `recognition/application/assignment/checks/confidence.py`

Modify `ConfidenceCheck` to return `SUGGEST` for marginal cases:

```python
async def evaluate(self, candidate: AssignmentCandidate) -> CheckResult:
    """Evaluate whether a candidate should be accepted based on dynamic thresholds."""
    # ... existing threshold calculation ...

    similarity = candidate.discovery_similarity

    # Fatal checks remain fatal
    if self._is_fatal_failure(candidate):
        return CheckResult(
            passed=False,
            is_fatal=True,
            should_reject=True,
            reason="fatal_quality_failure",
        )

    # Auto-accept: above ceiling
    if similarity >= self.settings.suggestion_ceiling:
        return CheckResult(passed=True, metadata={"confidence_decision": "accept"})

    # Suggestion band: between floor and ceiling
    if similarity >= self.settings.suggestion_floor:
        return CheckResult(
            passed=False,
            is_fatal=True,  # Stops the gate
            should_reject=False,  # Routes to SUGGEST, not REJECT
            reason=f"similarity {similarity:.3f} in suggestion band",
            metadata={"confidence_decision": "suggest", "similarity": similarity},
        )

    # Hard reject: below floor
    return CheckResult(
        passed=False,
        is_fatal=True,
        should_reject=True,
        reason=f"similarity {similarity:.3f} below suggestion floor",
        metadata={"confidence_decision": "reject", "similarity": similarity},
    )
```

**Fatal checks that always reject (never suggest):**

```python
def _is_fatal_failure(self, candidate: AssignmentCandidate) -> bool:
    """Return True for conditions that should always reject, never suggest."""
    # Example: extremely low quality, bad embedding, etc.
    if candidate.identity.confidence < 0.3:
        return True
    return False
```

### 3.2 Suggestion refresh after curation

**Critical trigger:** Refresh suggestions when a cluster is labeled (addresses immediate-merge-after-labeling pattern from logs).

**File:** `recognition/application/suggestions/service.py`

Implement `refresh_for_identity`:

```python
async def refresh_for_identity(
    self,
    identity_id: str,
    reason: SuggestionRefreshReason,
    *,
    exclude_cluster_ids: list[str] | None = None,
    representative_matcher: RepresentativeMatcher | None = None,
    block_repo: IdentityClusterBlockRepository | None = None,
) -> list[AssignmentSuggestion]:
    """Recompute suggestions for an identity after curation.

    Re-runs representative + centroid matching for the identity,
    generates suggestions for candidates in the suggestion band,
    and upserts pending suggestions with updated similarity/confidence.
    Skips blocked clusters and clusters in exclude_cluster_ids.

    Args:
        identity_id: Identity to refresh suggestions for.
        reason: What triggered the refresh (for logging/observability).
        exclude_cluster_ids: Clusters to skip during refresh.
        representative_matcher: Matcher for computing similarity to clusters.
        block_repo: Repository to check for block constraints.

    Returns:
        List of created/updated suggestions.
    """
    exclude_cluster_ids = exclude_cluster_ids or []
    suggestions: list[AssignmentSuggestion] = []

    # Get identity embedding
    identity = await self._get_identity(identity_id)
    if identity is None:
        logger.warning("[suggestions] refresh: identity not found id=%s", identity_id)
        return suggestions

    # Get candidate clusters (labeled clusters only)
    if self._cluster_repository is None:
        logger.warning("[suggestions] refresh: no cluster repository available")
        return suggestions

    clusters = await self._cluster_repository.get_by_tenant(
        self._tenant_id, labeled_only=True
    )

    for cluster in clusters:
        if cluster.id in exclude_cluster_ids:
            continue

        # Check blocks
        if block_repo:
            is_blocked = await block_repo.is_blocked(
                tenant_id=self._tenant_id,
                identity_id=identity_id,
                cluster_id=cluster.id,
            )
            if is_blocked:
                continue

        # Compute similarity
        similarity = await self._compute_similarity(identity, cluster, representative_matcher)

        # Check if in suggestion band
        settings = self._get_settings()
        if settings.suggestion_floor <= similarity < settings.suggestion_ceiling:
            suggestion = await self._repository.upsert_by_identity_cluster(
                self._tenant_id,
                identity_id,
                cluster.id,
                representative_similarity=similarity,
                member_similarity=similarity,
                confidence_score=similarity,
            )
            suggestions.append(suggestion)
            logger.info(
                "[suggestions] REFRESHED identity=%s cluster=%s similarity=%.4f reason=%s",
                identity_id,
                cluster.id,
                similarity,
                reason.value,
            )

    return suggestions
```

**Trigger points:**

```python
# In split_cluster, after creating new clusters:
if suggestion_service is not None:
    all_affected_ids = [*anchor_group_ids, *moved_identity_ids]
    for identity_id in all_affected_ids:
        await suggestion_service.refresh_for_identity(
            identity_id,
            SuggestionRefreshReason.MANUAL_SPLIT,
            exclude_cluster_ids=[cluster_id, *new_cluster_ids],
        )

# In remove_identity_from_cluster:
if suggestion_service is not None:
    await suggestion_service.refresh_for_identity(
        identity_id,
        SuggestionRefreshReason.WRONG_PERSON,
        exclude_cluster_ids=[removed_from_cluster_id],
    )

# In assign_outlier_to_cluster:
if suggestion_service is not None:
    await suggestion_service.resolve_for_identity_exclusive(
        identity_id,
        accepted_cluster_id=target_cluster_id,
    )
```

### 3.3 Auto resolve suggestions

**File:** `recognition/application/suggestions/service.py`

Implement `resolve_for_identity_exclusive`:

```python
async def resolve_for_identity_exclusive(
    self,
    identity_id: str,
    accepted_cluster_id: str,
) -> int:
    """Accept one suggestion and reject all others for an identity.

    Used when user confirms assignment via curation action.
    Accepts the suggestion matching accepted_cluster_id and
    rejects all other pending suggestions for the same identity.

    Args:
        identity_id: Identity whose suggestions to resolve.
        accepted_cluster_id: Cluster whose suggestion should be accepted.

    Returns:
        Total number of suggestions resolved.
    """
    suggestions = await self._repository.get_by_identity(self._tenant_id, identity_id)
    await self._ensure_run_context()

    resolved_count = 0
    accept_ids: list[str] = []
    reject_ids: list[str] = []

    for suggestion in suggestions:
        if suggestion.status != SuggestionStatus.PENDING:
            continue

        if suggestion.cluster_id == accepted_cluster_id:
            accept_ids.append(suggestion.id)
        else:
            reject_ids.append(suggestion.id)

    # Bulk updates
    if accept_ids:
        resolved_count += await self._repository.bulk_update_status(
            self._tenant_id, accept_ids, SuggestionStatus.ACCEPTED
        )
        for sid in accept_ids:
            logger.info(
                "[curation] AUTO_ACCEPTED suggestion_id=%s identity=%s cluster=%s source=exclusive_resolve",
                sid,
                identity_id,
                accepted_cluster_id,
            )
            self._emit_suggestion_resolved_event(
                identity_id=identity_id,
                cluster_id=accepted_cluster_id,
                resolution="accepted",
                suggestion_id=sid,
                source="exclusive_resolve",
            )

    if reject_ids:
        resolved_count += await self._repository.bulk_update_status(
            self._tenant_id, reject_ids, SuggestionStatus.REJECTED
        )
        for sid in reject_ids:
            logger.info(
                "[curation] AUTO_REJECTED suggestion_id=%s identity=%s source=exclusive_resolve",
                sid,
                identity_id,
            )

    return resolved_count
```

**File:** `recognition/infrastructure/repositories/suggestion_repository.py`

Implement `bulk_update_status`:

```python
async def bulk_update_status(
    self,
    tenant_id: str,
    suggestion_ids: list[str],
    status: SuggestionStatus,
) -> int:
    """Update status for multiple suggestions in a single operation."""
    if not suggestion_ids:
        return 0

    tenant_uuid = _coerce_uuid(tenant_id)
    suggestion_uuids = [_coerce_uuid(sid) for sid in suggestion_ids]
    suggestion_uuids = [u for u in suggestion_uuids if u is not None]

    if not suggestion_uuids or tenant_uuid is None:
        return 0

    stmt = (
        update(SuggestionModel)
        .where(SuggestionModel.tenant_id == tenant_uuid)
        .where(SuggestionModel.id.in_(suggestion_uuids))
        .values(resolution=status.value)
    )
    result = await self._session.execute(stmt)
    await self._session.flush()
    return result.rowcount
```

---

## Phase 4: UI and API flow

### 4.1 Frontend anchor selection

**File:** `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx`

Add anchor selection before split:

```typescript
const handleSplitCluster = async (clusterId: string) => {
  // If no anchor selected, prompt user to select one
  if (!selectedAnchorIdentityId) {
    setShowAnchorSelectionModal(true);
    return;
  }

  const request: SplitClusterRequest = {
    anchorIdentityId: selectedAnchorIdentityId,
    splitMode: "forced", // User-initiated splits are always forced
  };

  const result = await splitCluster(clusterId, request);
  if (result.new_cluster_ids.length > 0) {
    // Invalidate queries to refresh UI
    queryClient.invalidateQueries({ queryKey: ["clusters"] });
    queryClient.invalidateQueries({ queryKey: ["suggestions"] });
  }
};
```

### 4.2 Anchor selection modal component

```typescript
interface AnchorSelectionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectAnchor: (identityId: string) => void;
  clusterMembers: ClusterMember[];
}

const AnchorSelectionModal: React.FC<AnchorSelectionModalProps> = ({
  isOpen,
  onClose,
  onSelectAnchor,
  clusterMembers,
}) => {
  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Select the correct person</DialogTitle>
          <DialogDescription>
            Choose the face that should keep this cluster's label. Other faces
            will be moved to a new cluster.
          </DialogDescription>
        </DialogHeader>
        <div className="acx-anchor-grid">
          {clusterMembers.map((member) => (
            <button
              key={member.identity_id}
              className="acx-anchor-option"
              onClick={() => onSelectAnchor(member.identity_id)}
            >
              <img src={member.thumbnail_url} alt="Face thumbnail" />
            </button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
};
```

### 4.3 Update API types

**File:** `apps/prototype-wp-alt-context/js/admin/api/recognition/types/cluster.ts`

```typescript
export interface SplitClusterRequest {
  nClusters?: number;
  anchorIdentityId?: string;
  splitMode?: "auto" | "forced";
}

// Add suggestion refresh status to responses
export interface CurationResponse {
  success: boolean;
  suggestions_refreshed?: number;
  suggestions_resolved?: number;
}
```

### 4.4 Suggestions display

**File:** `apps/prototype-wp-alt-context/js/admin/components/SuggestionCard.tsx`

```typescript
interface SuggestionCardProps {
  suggestion: ClusterSuggestionMatch;
  onAccept: () => void;
  onReject: () => void;
}

const SuggestionCard: React.FC<SuggestionCardProps> = ({
  suggestion,
  onAccept,
  onReject,
}) => {
  const confidenceLabel = suggestion.similarity >= 0.8 ? "High" : "Medium";

  return (
    <div className="acx-suggestion-card">
      <div className="acx-suggestion-header">
        <span className="acx-suggestion-label">{suggestion.label}</span>
        <span
          className={`acx-suggestion-confidence acx-confidence-${confidenceLabel.toLowerCase()}`}
        >
          {confidenceLabel} match ({(suggestion.similarity * 100).toFixed(0)}%)
        </span>
      </div>
      <div className="acx-suggestion-actions">
        <Button variant="outline" onClick={onReject}>
          Reject
        </Button>
        <Button onClick={onAccept}>Accept</Button>
      </div>
    </div>
  );
};
```

---

## Phase 5: Tests (TDD)

### 5.1 Split enforcement

**File:** `recognition/tests/unit/test_cluster_split.py`

```python
import pytest
from recognition.application.orchestration.cluster_split import (
    force_two_way_split,
    SplitPlan,
    SplitStrategy,
)


class TestForceTwoWaySplit:
    """Tests for forced binary split algorithm."""

    @pytest.mark.asyncio
    async def test_forced_split_produces_two_clusters_when_hierarchical_returns_one(
        self,
        mock_identities_similar: list,
    ):
        """Forced split always produces two groups even when faces are similar."""
        # Arrange: 5 identities with very high similarity (would be one group)
        anchor_id = str(mock_identities_similar[0].id)

        # Act
        result = await force_two_way_split(
            identities=mock_identities_similar,
            anchor_identity_id=anchor_id,
            anchor_split_similarity_floor=0.85,
        )

        # Assert
        assert len(result) == 2, "Should produce exactly 2 groups"
        assert len(result[0]) >= 1, "Anchor group should have at least anchor"
        assert len(result[1]) >= 1, "Other group should have at least one identity"

    @pytest.mark.asyncio
    async def test_anchor_identity_always_in_anchor_group(
        self,
        mock_identities: list,
    ):
        """Anchor identity is always in group 0."""
        anchor_id = str(mock_identities[2].id)  # Pick middle identity

        result = await force_two_way_split(
            identities=mock_identities,
            anchor_identity_id=anchor_id,
        )

        anchor_group_ids = [str(i.id) for i in result[0]]
        assert anchor_id.lower() in [id.lower() for id in anchor_group_ids]

    @pytest.mark.asyncio
    async def test_farthest_identity_moved_when_all_above_threshold(
        self,
        mock_identities_very_similar: list,
    ):
        """When all identities exceed threshold, farthest is moved to other group."""
        anchor_id = str(mock_identities_very_similar[0].id)

        result = await force_two_way_split(
            identities=mock_identities_very_similar,
            anchor_identity_id=anchor_id,
            anchor_split_similarity_floor=0.50,  # Very low threshold
        )

        # Even with low threshold, we should have two groups
        assert len(result[0]) >= 1
        assert len(result[1]) >= 1

    @pytest.mark.asyncio
    async def test_raises_when_anchor_not_found(self, mock_identities: list):
        """ValueError when anchor identity not in cluster."""
        with pytest.raises(ValueError, match="not found"):
            await force_two_way_split(
                identities=mock_identities,
                anchor_identity_id="nonexistent-id",
            )
```

**File:** `recognition/tests/integration/test_cluster_split_integration.py`

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_anchor_identity_remains_in_labeled_cluster_after_split(
    db_session,
    cluster_with_mixed_identities,
):
    """User label stays with anchor identity's cluster."""
    cluster_id, identities = cluster_with_mixed_identities
    anchor_id = str(identities[0].id)
    original_label = "John Doe"

    # Set label on cluster
    await set_cluster_label(db_session, cluster_id, original_label)

    # Split with anchor
    new_cluster_ids, moved_counts = await split_cluster(
        cluster_id=cluster_id,
        n_clusters=2,
        anchor_identity_id=anchor_id,
        split_mode="forced",
        session=db_session,
        cluster_repo=SqlAlchemyClusterRepository(db_session),
        member_repo=SqlAlchemyMemberRepository(db_session),
    )

    # Verify anchor's cluster kept the label
    anchor_cluster = await get_cluster_for_identity(db_session, anchor_id)
    assert anchor_cluster.label == original_label


@pytest.mark.integration
@pytest.mark.asyncio
async def test_blocks_prevent_immediate_remerge(
    db_session,
    cluster_with_mixed_identities,
):
    """Moved identities cannot be auto-assigned back to original cluster."""
    cluster_id, identities = cluster_with_mixed_identities
    anchor_id = str(identities[0].id)
    moved_id = str(identities[-1].id)

    # Split
    new_cluster_ids, _ = await split_cluster(
        cluster_id=cluster_id,
        n_clusters=2,
        anchor_identity_id=anchor_id,
        split_mode="forced",
        session=db_session,
        cluster_repo=SqlAlchemyClusterRepository(db_session),
        member_repo=SqlAlchemyMemberRepository(db_session),
        block_repo=SqlAlchemyBlockRepository(db_session),
    )

    # Verify block exists
    block_repo = SqlAlchemyBlockRepository(db_session)
    is_blocked = await block_repo.is_blocked(
        tenant_id=identities[0].tenant_id,
        identity_id=moved_id,
        cluster_id=cluster_id,
    )
    assert is_blocked, "Moved identity should be blocked from original cluster"
```

### 5.2 Suggestions

**File:** `recognition/tests/unit/test_suggestion_service.py`

```python
class TestSuggestionRefresh:
    """Tests for suggestion refresh after curation."""

    @pytest.mark.asyncio
    async def test_marginal_reject_creates_suggestion(
        self,
        suggestion_service: SuggestionService,
        mock_identity,
        mock_cluster,
    ):
        """Similarity in suggestion band creates pending suggestion."""
        # Arrange: similarity between floor (0.70) and ceiling (0.85)
        candidate = AssignmentCandidate(
            identity=mock_identity,
            cluster_id=mock_cluster.id,
            discovery_similarity=0.78,
        )

        # Act
        suggestion = await suggestion_service.create(candidate, confidence=0.78)

        # Assert
        assert suggestion is not None
        assert suggestion.status == SuggestionStatus.PENDING
        assert suggestion.representative_similarity == pytest.approx(0.78, rel=0.01)

    @pytest.mark.asyncio
    async def test_refresh_updates_scores_and_upserts(
        self,
        suggestion_service: SuggestionService,
        mock_identity,
        mock_clusters,
    ):
        """Refresh computes new scores and upserts suggestions."""
        # Arrange: create initial suggestion
        initial = await suggestion_service._repository.create(
            tenant_id=suggestion_service._tenant_id,
            payload=SuggestionCreateData(
                identity_id=mock_identity.id,
                cluster_id=mock_clusters[0].id,
                representative_similarity=0.75,
                member_similarity=0.75,
                confidence_score=0.75,
            ),
        )

        # Act: refresh with updated similarity
        refreshed = await suggestion_service.refresh_for_identity(
            identity_id=mock_identity.id,
            reason=SuggestionRefreshReason.CLUSTER_RECOMPUTE,
        )

        # Assert: scores updated
        assert len(refreshed) >= 1
        # Score may have changed based on new cluster state

    @pytest.mark.asyncio
    async def test_resolve_exclusive_accepts_one_rejects_others(
        self,
        suggestion_service: SuggestionService,
        mock_identity,
        mock_clusters,
    ):
        """Exclusive resolve accepts target and rejects all others."""
        # Arrange: create 3 pending suggestions
        for cluster in mock_clusters[:3]:
            await suggestion_service._repository.create(
                tenant_id=suggestion_service._tenant_id,
                payload=SuggestionCreateData(
                    identity_id=mock_identity.id,
                    cluster_id=cluster.id,
                    representative_similarity=0.78,
                    member_similarity=0.78,
                    confidence_score=0.78,
                ),
            )

        # Act: resolve exclusively for first cluster
        resolved_count = await suggestion_service.resolve_for_identity_exclusive(
            identity_id=mock_identity.id,
            accepted_cluster_id=mock_clusters[0].id,
        )

        # Assert
        assert resolved_count == 3  # 1 accepted + 2 rejected
        suggestions = await suggestion_service.list_for_identity(mock_identity.id)
        accepted = [s for s in suggestions if s.status == SuggestionStatus.ACCEPTED]
        rejected = [s for s in suggestions if s.status == SuggestionStatus.REJECTED]
        assert len(accepted) == 1
        assert len(rejected) == 2
```

**File:** `recognition/tests/integration/test_suggestion_curation.py`

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_suggestions_recompute_after_wrong_person_removal(
    db_session,
    cluster_with_identities,
    suggestion_service,
):
    """Removing identity triggers suggestion refresh."""
    cluster_id, identities = cluster_with_identities
    removed_id = str(identities[0].id)

    # Remove identity (wrong person)
    await remove_identity_from_cluster(
        db_session,
        cluster_id=cluster_id,
        identity_id=removed_id,
        suggestion_service=suggestion_service,
    )

    # Suggestions should be refreshed for removed identity
    suggestions = await suggestion_service.list_for_identity(removed_id)
    # May have new suggestions for other clusters


@pytest.mark.integration
@pytest.mark.asyncio
async def test_accept_resolves_other_pending_suggestions(
    db_session,
    suggestion_service,
    mock_identity,
    mock_clusters,
):
    """Accepting assignment resolves all other pending suggestions."""
    # Create multiple pending suggestions
    for cluster in mock_clusters[:3]:
        await suggestion_service._repository.create(
            tenant_id=suggestion_service._tenant_id,
            payload=SuggestionCreateData(
                identity_id=mock_identity.id,
                cluster_id=cluster.id,
                representative_similarity=0.78,
                member_similarity=0.78,
                confidence_score=0.78,
            ),
        )

    # User accepts assignment to first cluster
    await assign_identity_to_cluster(
        db_session,
        identity_id=mock_identity.id,
        cluster_id=mock_clusters[0].id,
        suggestion_service=suggestion_service,
    )

    # All other suggestions should be rejected
    suggestions = await suggestion_service.list_for_identity(mock_identity.id)
    pending = [s for s in suggestions if s.status == SuggestionStatus.PENDING]
    assert len(pending) == 0, "No pending suggestions should remain"
```

---

## Phase 6: Observability

### 6.1 Split decision logging

**File:** `recognition/application/orchestration/cluster_split.py`

Already implemented with structured logging. Enhance with anchor and strategy info:

```python
logger.info(
    "[curation] SPLIT original_cluster=%s original_label='%s' new_clusters=%s "
    "moved_counts=%s anchor_identity=%s split_mode=%s "
    "anchor_group_size=%d other_group_sizes=%s tenant_id=%s user_action=manual_split",
    cluster_id,
    original_cluster.label,
    new_cluster_ids,
    moved_counts,
    anchor_identity_id,
    split_mode,
    len(anchor_group),
    [len(g) for g in other_groups],
    original_cluster.tenant_id,
)
```

### 6.2 Suggestion refresh logging

**File:** `recognition/application/suggestions/service.py`

```python
logger.info(
    "[suggestions] REFRESH identity=%s reason=%s candidates_checked=%d "
    "suggestions_created=%d suggestions_updated=%d excluded_clusters=%s",
    identity_id,
    reason.value,
    candidates_checked,
    created_count,
    updated_count,
    exclude_cluster_ids,
)
```

### 6.3 Auto-resolve event emission

Add to `RecognitionRunContext` for observability:

```python
self._run_context.add_event(
    event_type="suggestions_auto_resolved",
    identity_id=identity_id,
    cluster_id=accepted_cluster_id,
    payload={
        "accepted_count": len(accept_ids),
        "rejected_count": len(reject_ids),
        "source": "exclusive_resolve",
    },
)
```

---

## Implementation Checklist

### Phase 0: Scaffolding

- [x] Add `SplitStrategy` enum to `cluster_split.py`
- [x] Add `SplitScope` enum to `cluster_split.py`
- [x] Add `SplitPlan` dataclass to `cluster_split.py` (includes `anchor_identity_id`)
- [x] Add `split_mode` field to `SplitClusterRequest` (auto vs forced)
- [x] Add `SuggestionRefreshReason` enum to `suggestions/service.py` (manual_split, wrong_person, manual_assign, manual_merge)
- [x] Scaffold `refresh_for_identity()` method signature in `SuggestionService`
- [x] Scaffold `resolve_for_identity_exclusive()` method signature in `SuggestionService`
- [x] Add `bulk_update_status()` to `SuggestionRepository` protocol
- [x] Add `upsert_by_identity_cluster()` to `SuggestionRepository` protocol

### Phase 1: Contract Updates

- [x] Update WP proxy to forward `anchor_identity_id` and `split_mode` parameters
- [x] Update TypeScript `SplitClusterRequest` interface with `anchorIdentityId` and `splitMode`
- [x] Add `source` and `refreshed_at` columns to `identity_suggestions` table in `001_identity_schema.py` (if needed)
- [x] Verify `identity_cluster_blocks` table exists in baseline migration

### Phase 2: Forced Split

- [x] Implement `force_two_way_split()` algorithm (anchor-first, min similarity fallback)
- [x] Add `split_mode`, `anchor_identity_id`, and `block_repo` parameters to `split_cluster()`
- [x] Integrate forced split fallback when hierarchical clustering returns only one group
- [x] Ensure anchor group keeps the original label and user ownership
- [x] Apply split suffix labels to new clusters (e.g., "Label (split N)")
- [x] Persist negative constraints (blocks) for each moved identity against the original cluster
- [x] Persist blocks for anchor-group identities against new clusters where necessary
- [x] Recompute representatives and centroids for all affected clusters
- [x] Refresh centroids view after recompute

### Phase 3: Suggestion Engine

- [x] Add `suggestion_floor` and `suggestion_ceiling` to `ClusteringSettings`
- [x] Modify `ConfidenceCheck` to return `SUGGEST` for marginal cases (within suggestion band)
- [x] Mark fatal check failures explicitly to avoid incorrect suggestions
- [x] Implement `SuggestionService.refresh_for_identity()` (re-run matching, upsert pending suggestions)
- [x] Implement `SuggestionService.resolve_for_identity_exclusive()` (accept target, reject others)
- [x] Implement repository methods in `SqlAlchemySuggestionRepository` (`bulk_update_status`, `upsert_by_identity_cluster`)
- [x] Trigger suggestion refresh on split (anchor + moved identities)
- [x] Trigger suggestion refresh on wrong-person removal
- [x] Trigger suggestion resolve/refresh on manual assign or merge actions
- [x] Reject suggestions for the specific cluster on wrong-person action

### Phase 4: UI

- [x] Update `WorkbenchPage` to require anchor selection for manual splits
- [x] Create `AnchorSelectionModal` component for choosing the face that keeps the label
- [x] Pass `anchorIdentityId` and `splitMode` to API calls
- [x] Invalidate suggestions query on curation completion
- [x] Create `SuggestionCard` component to surface matches as "Needs review" with accept/reject

### Phase 5: Tests

- [x] Unit test: forced split produces two clusters even when faces are similar
- [x] Unit test: anchor identity always ends up in the anchor group
- [x] Unit test: farthest identity fallback when all members are above threshold
- [x] Integration test: anchor identity remains in labeled cluster after split
- [x] Integration test: blocks prevent immediate re-merge after split
- [x] Unit test: marginal reject correctly creates a pending suggestion
- [x] Unit test: refresh updates scores and upserts instead of creating duplicates
- [x] Unit test: exclusive resolve accepts one and rejects all other pending suggestions
- [x] Integration test: suggestions refresh after wrong-person removal
- [x] Integration test: accepting a suggestion resolves other pending suggestions for that identity

### Phase 6: Observability

- [ ] Enhance split logging with anchor ID, final group sizes, and split strategy
- [ ] Add suggestion refresh logging (reason, counts, candidate coverage)
- [ ] Emit `suggestions_auto_resolved` events for observability

---

## Definition of Done

- [ ] User-triggered split always creates two clusters.
- [ ] Split clusters do not immediately re-merge.
- [ ] Suggestions appear for marginal rejects and refresh on curation.
- [ ] Suggestions auto-resolve when user curates identities.
- [ ] All new tests pass.

---

## Validation Metrics (Post-Implementation)

Track these metrics to validate the Suggestions Strategy effectiveness:

| Metric                     | Target                | Measurement                        |
| -------------------------- | --------------------- | ---------------------------------- |
| Suggestion Acceptance Rate | >50%                  | accepted / (accepted + rejected)   |
| Singleton Merge Reduction  | >80% drop             | moved_count=1 merges before/after  |
| Time to Complete Roster    | Significant reduction | Labeling session duration          |
| Orphan Identity Count      | <10% of identities    | Identities not in labeled clusters |

**Baseline from logs:**

- 14 singleton merges in sample period
- 25 auto-rejections creating orphans
- 8 suggestions skipped due to unlabeled clusters
