# Auto-Labeling Implementation Plan

> **Date**: 2026-01-20  
> **Status**: ✅ COMPLETE  
> **Parent**: [implementation-gap-analysis-2026-01-20.md](implementation-gap-analysis-2026-01-20.md)  
> **Goal**: Bootstrap first-run experience by auto-labeling high-confidence clusters

---

## Open Questions — Answered

### Q1: Should auto-labeled clusters be suggestion targets immediately?

**Answer: Yes**

Rationale:

- The entire purpose is to bootstrap the suggestion workflow for first-run users
- Without this, users still need to manually label before seeing suggestions (defeating the purpose)
- UI already distinguishes auto-labels via `is_auto_label` property
- Users can rename or confirm auto-labels; suggestions will update accordingly

### Q2: Should auto-labels keep `user_confirmed=false`?

**Answer: Yes, keep `user_confirmed=false`**

Rationale:

- Preserves `is_auto_label = bool(label) and not user_confirmed` signal in UI
- Clear semantic distinction: "system guessed" vs "user verified"
- Eligibility logic change is cleaner (check for label presence, not confirmation)
- When user renames/confirms, `user_confirmed` becomes `true` and `is_auto_label` becomes `false`

**Data state transitions:**

| Event                   | label      | user_confirmed | is_auto_label | Suggestion Eligible |
| ----------------------- | ---------- | -------------- | ------------- | ------------------- |
| HDBSCAN creates cluster | NULL       | false          | false         | ❌ No               |
| Auto-label applied      | "Person 1" | false          | **true**      | ✅ Yes              |
| User renames to "John"  | "John"     | true           | false         | ✅ Yes              |

### Q3: What thresholds define "high confidence"?

**Answer:**

| Setting                       | Value       | Rationale                                       |
| ----------------------------- | ----------- | ----------------------------------------------- |
| `auto_label_min_members`      | 3           | HDBSCAN min is 2; require 3 for more confidence |
| `auto_label_similarity_floor` | 0.85        | Matches `suggestion_ceiling` (accept threshold) |
| Similarity metric             | **Average** | More stable than min (outlier-resistant)        |

**Why average similarity?**

- `persist_new_cluster` receives list of member similarities
- Min can be skewed by one poor match
- Average represents overall cluster cohesion

---

## Implementation Steps

### Phase 0: Scaffolding (TDD)

#### 0.1 Settings class

```python
# recognition/application/settings/clustering.py

class AutoLabelSettings(BaseModel):
    """Settings for automatic cluster labeling."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=True,
        description="Enable auto-labeling of high-confidence clusters.",
    )
    min_members: int = Field(
        default=3,
        description="Minimum cluster size to trigger auto-labeling.",
    )
    similarity_floor: float = Field(
        default=0.85,
        description="Minimum average similarity for auto-labeling.",
    )
    prefix: str = Field(
        default="Person",
        description="Prefix for auto-generated labels (e.g., 'Person 1').",
    )
```

#### 0.2 Label allocator interface

```python
# recognition/application/labeling/auto_labeler.py

async def allocate_person_label(
    tenant_id: str,
    session: AsyncSession,
    prefix: str = "Person",
) -> str:
    """Atomically allocate next 'Person N' label for tenant.

    Uses UPDATE...RETURNING for concurrency safety.

    Args:
        tenant_id: Tenant UUID string.
        session: Active database session.
        prefix: Label prefix (default "Person").

    Returns:
        Label string like "Person 1", "Person 2", etc.

    Raises:
        NoResultFound: If tenant doesn't exist.
    """
    raise NotImplementedError("TODO: implement atomic counter")
```

#### 0.3 Schema addition

```python
# db/models/tenant.py - Add column
next_person_number: Mapped[int] = mapped_column(
    Integer, nullable=False, server_default=text("1")
)

# db/migrations/versions/001_identity_schema.py - Add to tenants table
sa.Column("next_person_number", sa.Integer(), nullable=False, server_default=sa.text("1")),
```

---

### Phase 1: Auto-labeler Implementation

#### 1.1 Atomic label allocation

```python
# recognition/application/labeling/auto_labeler.py

async def allocate_person_label(
    tenant_id: str,
    session: AsyncSession,
    prefix: str = "Person",
) -> str:
    """Atomically allocate next 'Person N' label for tenant."""
    stmt = (
        update(TenantModel)
        .where(TenantModel.id == uuid.UUID(tenant_id))
        .values(next_person_number=TenantModel.next_person_number + 1)
        .returning(TenantModel.next_person_number)
    )
    result = await session.execute(stmt)
    number = result.scalar_one()
    return f"{prefix} {number - 1}"  # Return pre-increment value
```

#### 1.2 Auto-label decision logic

```python
# recognition/application/labeling/auto_labeler.py

def should_auto_label(
    *,
    member_count: int,
    similarities: list[float],
    algorithm: str,
    settings: AutoLabelSettings,
) -> bool:
    """Determine if a new cluster should be auto-labeled.

    Returns False for:
    - Manual clusters (algorithm="manual")
    - Clusters below member threshold
    - Clusters below similarity threshold
    - When auto-labeling is disabled
    """
    if not settings.enabled:
        return False

    if algorithm == "manual":
        return False

    if member_count < settings.min_members:
        return False

    if not similarities:
        return False

    avg_similarity = sum(similarities) / len(similarities)
    return avg_similarity >= settings.similarity_floor
```

---

### Phase 2: Integration into Cluster Creation

#### 2.1 Hook in `persist_new_cluster`

**File**: `recognition/application/persistence/assignment_writer.py`

**Location**: After cluster is created but before return

```python
async def persist_new_cluster(
    self,
    tenant_id: str,
    identities: list[MediaIdentity],
    similarities: list[float],
    algorithm: str = "hdbscan",
) -> ClusterModel:
    """Create a new cluster with members."""
    cluster = await self._clusters.create(tenant_id=tenant_id, algorithm=algorithm)

    # ... existing member addition logic ...

    # Auto-label if eligible
    if should_auto_label(
        member_count=len(identities),
        similarities=similarities,
        algorithm=algorithm,
        settings=self._settings.auto_label,
    ):
        label = await allocate_person_label(
            tenant_id=tenant_id,
            session=self._session,
            prefix=self._settings.auto_label.prefix,
        )
        await self._clusters.update_label(cluster.id, label)
        cluster.label = label
        logger.info(
            "[auto_label] Applied label=%s cluster_id=%s members=%d avg_sim=%.3f",
            label, cluster.id, len(identities), sum(similarities) / len(similarities),
        )

    return cluster
```

---

### Phase 3: Eligibility Update

#### 3.1 Remove `user_confirmed` requirement

**File**: `recognition/application/suggestions/eligibility.py`

```python
def is_eligible_cluster(cluster: object, tenant_id: str) -> bool:
    """Return True if a cluster can be surfaced as a suggestion target.

    Eligible clusters must have a meaningful label (user OR auto-assigned).
    Auto-labeled clusters ARE eligible to bootstrap the suggestion workflow.
    """
    if tenant_id and getattr(cluster, "tenant_id", "").lower() != tenant_id.lower():
        logger.info("[suggestions] Skipping: tenant mismatch cluster_id=%s", getattr(cluster, "id", None))
        return False

    label = getattr(cluster, "label", None)

    # Require a label, but NOT user_confirmed
    # Auto-labels (user_confirmed=false) are now eligible
    if not label or str(label).startswith("cluster-"):
        logger.info(
            "[suggestions] Skipping: no meaningful label cluster_id=%s",
            getattr(cluster, "id", None),
        )
        return False

    return True
```

---

### Phase 4: Tests (TDD)

#### 4.1 Unit tests for auto-labeler

```python
# recognition/tests/unit/test_auto_labeler.py

class TestShouldAutoLabel:
    def test_returns_false_when_disabled(self):
        settings = AutoLabelSettings(enabled=False)
        assert not should_auto_label(
            member_count=5, similarities=[0.9, 0.9, 0.9], algorithm="hdbscan", settings=settings
        )

    def test_returns_false_for_manual_algorithm(self):
        settings = AutoLabelSettings()
        assert not should_auto_label(
            member_count=5, similarities=[0.9, 0.9], algorithm="manual", settings=settings
        )

    def test_returns_false_below_member_threshold(self):
        settings = AutoLabelSettings(min_members=3)
        assert not should_auto_label(
            member_count=2, similarities=[0.9, 0.9], algorithm="hdbscan", settings=settings
        )

    def test_returns_false_below_similarity_threshold(self):
        settings = AutoLabelSettings(similarity_floor=0.85)
        assert not should_auto_label(
            member_count=5, similarities=[0.80, 0.82, 0.78], algorithm="hdbscan", settings=settings
        )

    def test_returns_true_when_all_criteria_met(self):
        settings = AutoLabelSettings(min_members=3, similarity_floor=0.85)
        assert should_auto_label(
            member_count=5, similarities=[0.90, 0.88, 0.92], algorithm="hdbscan", settings=settings
        )

    def test_uses_average_not_minimum_similarity(self):
        settings = AutoLabelSettings(similarity_floor=0.85)
        # One low outlier, but average is still above threshold
        similarities = [0.90, 0.90, 0.90, 0.70]  # avg = 0.85
        assert should_auto_label(
            member_count=4, similarities=similarities, algorithm="hdbscan", settings=settings
        )


class TestAllocatePersonLabel:
    @pytest.mark.asyncio
    async def test_returns_sequential_labels(self, db_session, tenant):
        label1 = await allocate_person_label(str(tenant.id), db_session)
        label2 = await allocate_person_label(str(tenant.id), db_session)
        label3 = await allocate_person_label(str(tenant.id), db_session)

        assert label1 == "Person 1"
        assert label2 == "Person 2"
        assert label3 == "Person 3"

    @pytest.mark.asyncio
    async def test_respects_custom_prefix(self, db_session, tenant):
        label = await allocate_person_label(str(tenant.id), db_session, prefix="Identity")
        assert label == "Identity 1"

    @pytest.mark.asyncio
    async def test_concurrent_allocations_are_unique(self, db_session, tenant):
        """Verify no duplicates under concurrent allocation."""
        labels = await asyncio.gather(*[
            allocate_person_label(str(tenant.id), db_session)
            for _ in range(10)
        ])
        assert len(set(labels)) == 10  # All unique
```

#### 4.2 Integration tests for persist_new_cluster

```python
# recognition/tests/integration/test_auto_label_integration.py

@pytest.mark.asyncio
async def test_persist_new_cluster_applies_auto_label_when_criteria_met(
    db_session, tenant, assignment_writer_with_auto_label
):
    """High-confidence cluster gets auto-labeled."""
    identities = [make_identity() for _ in range(5)]
    similarities = [0.90, 0.88, 0.92, 0.89, 0.91]

    cluster = await assignment_writer_with_auto_label.persist_new_cluster(
        tenant_id=str(tenant.id),
        identities=identities,
        similarities=similarities,
        algorithm="hdbscan",
    )

    assert cluster.label == "Person 1"
    assert cluster.user_confirmed is False


@pytest.mark.asyncio
async def test_persist_new_cluster_skips_auto_label_for_manual_clusters(
    db_session, tenant, assignment_writer_with_auto_label
):
    """Manual clusters never get auto-labeled."""
    identities = [make_identity() for _ in range(5)]
    similarities = [0.95, 0.95, 0.95]

    cluster = await assignment_writer_with_auto_label.persist_new_cluster(
        tenant_id=str(tenant.id),
        identities=identities,
        similarities=similarities,
        algorithm="manual",
    )

    assert cluster.label is None


@pytest.mark.asyncio
async def test_persist_new_cluster_skips_auto_label_below_threshold(
    db_session, tenant, assignment_writer_with_auto_label
):
    """Low-confidence cluster stays unlabeled."""
    identities = [make_identity() for _ in range(5)]
    similarities = [0.70, 0.72, 0.68]  # Below 0.85

    cluster = await assignment_writer_with_auto_label.persist_new_cluster(
        tenant_id=str(tenant.id),
        identities=identities,
        similarities=similarities,
        algorithm="hdbscan",
    )

    assert cluster.label is None
```

#### 4.3 Eligibility tests

```python
# recognition/tests/unit/test_eligibility.py

def test_auto_labeled_cluster_is_eligible():
    """Clusters with labels (even auto) should be eligible."""
    cluster = MockCluster(
        id="abc",
        tenant_id="tenant-1",
        label="Person 1",
        user_confirmed=False,  # Auto-labeled
    )
    assert is_eligible_cluster(cluster, "tenant-1") is True


def test_user_labeled_cluster_is_eligible():
    """User-confirmed clusters should remain eligible."""
    cluster = MockCluster(
        id="abc",
        tenant_id="tenant-1",
        label="John Smith",
        user_confirmed=True,
    )
    assert is_eligible_cluster(cluster, "tenant-1") is True


def test_unlabeled_cluster_is_not_eligible():
    """Clusters without labels should not be eligible."""
    cluster = MockCluster(
        id="abc",
        tenant_id="tenant-1",
        label=None,
        user_confirmed=False,
    )
    assert is_eligible_cluster(cluster, "tenant-1") is False


def test_cluster_prefix_label_is_not_eligible():
    """System-generated 'cluster-XXX' labels are not meaningful."""
    cluster = MockCluster(
        id="abc",
        tenant_id="tenant-1",
        label="cluster-abc123",
        user_confirmed=False,
    )
    assert is_eligible_cluster(cluster, "tenant-1") is False
```

---

## Files to Modify/Create

| File                                                           | Action | Description                                   |
| -------------------------------------------------------------- | ------ | --------------------------------------------- |
| `recognition/application/settings/clustering.py`               | Modify | Add `AutoLabelSettings` class                 |
| `recognition/application/labeling/__init__.py`                 | Create | New module                                    |
| `recognition/application/labeling/auto_labeler.py`             | Create | Label allocation + decision logic             |
| `recognition/application/persistence/assignment_writer.py`     | Modify | Hook auto-labeling into `persist_new_cluster` |
| `recognition/application/suggestions/eligibility.py`           | Modify | Remove `user_confirmed` requirement           |
| `db/models/tenant.py`                                          | Modify | Add `next_person_number` column               |
| `db/migrations/versions/001_identity_schema.py`                | Modify | Add column to tenants table                   |
| `recognition/tests/unit/test_auto_labeler.py`                  | Create | Unit tests                                    |
| `recognition/tests/integration/test_auto_label_integration.py` | Create | Integration tests                             |
| `recognition/tests/unit/test_eligibility.py`                   | Modify | Add auto-label eligibility tests              |

---

## Task Checklist

### Phase 0: Scaffolding

- [x] Add `AutoLabelSettings` to `clustering.py`
- [x] Add `next_person_number` to `TenantModel`
- [x] Add column to migration (greenfield: modify baseline)
- [x] Scaffold `auto_labeler.py` with `NotImplementedError`

### Phase 1: Implementation

- [x] Implement `allocate_person_label()` with atomic UPDATE...RETURNING
- [x] Implement `should_auto_label()` decision logic
- [x] Write unit tests for both functions

### Phase 2: Integration

- [x] Hook into `persist_new_cluster()` in `assignment_writer.py`
- [x] Add `auto_label` settings to `ClusteringSettings`
- [x] Write integration tests

### Phase 3: Eligibility

- [x] Update `is_eligible_cluster()` to accept auto-labels
- [x] Update/add eligibility tests

### Phase 4: Validation

- [x] Run full test suite
- [ ] Manual test: scan 10+ images, verify auto-labels appear
- [ ] Manual test: verify suggestions surface for auto-labeled clusters
- [x] Update `implementation-gap-analysis-2026-01-20.md` checklist

---

## Edge Cases to Handle

1. **Tenant doesn't exist**: `allocate_person_label` should raise clear error
2. **Empty similarities list**: `should_auto_label` returns False
3. **Rollback on failure**: If cluster creation fails after label allocation, counter is incremented but label unused (acceptable gap)
4. **Duplicate label collision**: Unique constraint `(tenant_id, label)` prevents; retry with next number on conflict
5. **Disable mid-run**: Settings are read per-call; disabling takes effect immediately

---

## Success Metrics

| Metric                                | Target                                  |
| ------------------------------------- | --------------------------------------- |
| Auto-labeled clusters on first scan   | ≥1 for 10+ face scan                    |
| Suggestions surfaced after auto-label | >0 within 1 minute                      |
| False positive rate                   | <10% (user renames/deletes auto-labels) |
| Label collision errors                | 0                                       |
