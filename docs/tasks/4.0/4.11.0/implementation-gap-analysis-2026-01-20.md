# Implementation Gap Analysis

> **Date**: 2026-01-20  
> **Scope**: Review of clustering-regression-investigation.md, progress-tracking-investigation.md, stability-audit-2026-01-20.md  
> **Status**: 🔍 Gaps identified

---

## Executive Summary

Cross-referencing the investigation documents against the actual codebase reveals:

| Category                          | Documented          | Implemented | Gap                            |
| --------------------------------- | ------------------- | ----------- | ------------------------------ |
| UUID fix in constrained_hac.py    | ✅                  | ✅          | None                           |
| PHP batch limits raised           | ✅                  | ✅          | None                           |
| suggestion_floor lowered to 0.65  | ✅                  | ✅          | None                           |
| curriculum_t default 0.5          | ✅                  | ✅          | **Fixed: model synced to 0.5** |
| PHP retry logic                   | ✅                  | ✅          | None                           |
| BatchLimits trait                 | ✅                  | ✅          | None                           |
| MaturitySettings extraction       | ✅                  | ✅          | None                           |
| Quality consolidation             | ✅                  | ✅          | None                           |
| ClusterService session validation | ✅                  | ✅          | None                           |
| Orphan recovery mechanism         | Recommended         | ❌          | **Not implemented**            |
| Suggestions UI for first-run      | Documented as issue | ⚠️          | **Requires labeled clusters**  |

---

## 1. ~~Critical Gap: curriculum_t Default Mismatch~~ ✅ FIXED

### Problem (Resolved)

The migration and model had **conflicting defaults** for `curriculum_t`:

| Location         | Default       | File                                                                                                                             |
| ---------------- | ------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Migration        | `0.5`         | [001_identity_schema.py#L127](../../../../apps/prototype-description-service/db/migrations/versions/001_identity_schema.py#L127) |
| SQLAlchemy Model | ~~`0`~~ `0.5` | [identity.py#L101](../../../../apps/prototype-description-service/db/models/identity.py#L101)                                    |

### Fix Applied

```python
# db/models/identity.py line 101 - UPDATED
curriculum_t: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.5"))
```

---

## 2. Missing Feature: Orphan Identity Recovery

### Status

The [clustering-regression-investigation.md](clustering-regression-investigation.md) recommends:

> **4. Add Job Retry/Recovery**
>
> - Detect orphaned identities
> - Automatically queue them for re-clustering

### Current State

No automated orphan recovery exists. The only path to re-cluster orphans is:

1. Manual re-scan of affected media items
2. Admin-triggered full clustering job

### Impact

- 69% orphan rate was observed during investigation
- Failed jobs leave identities permanently unclustered
- No self-healing mechanism

### Recommended Implementation

```python
# New endpoint: POST /recognition/clusters/recover-orphans
async def recover_orphan_identities(tenant_id: str) -> RecoveryResult:
    """Find and re-cluster orphaned identities."""
    orphans = await get_orphan_identities(tenant_id)
    if not orphans:
        return RecoveryResult(orphans_found=0, recovered=0)

    result = await cluster_service.cluster_unclustered_identities(tenant_id)
    return RecoveryResult(
        orphans_found=len(orphans),
        recovered=result.assignments_made,
    )
```

---

## 3. Architectural Issue: Suggestions Require Labeled Clusters

### Problem

The [clustering-regression-investigation.md](clustering-regression-investigation.md) notes:

> **5. Missing Suggestions UI**: Suggestions are created but no UI surfaces them

Investigation of [eligibility.py](../../../../apps/prototype-description-service/recognition/application/suggestions/eligibility.py) reveals:

```python
def is_eligible_cluster(cluster: object, tenant_id: str) -> bool:
    ...
    if not user_confirmed or not label or str(label).startswith("cluster-"):
        logger.info(
            "[suggestions] Skipping suggestion: cluster not user-labeled cluster_id=%s",
            ...
        )
        return False
```

### Impact on First-Run Experience

1. User scans 100 images → HDBSCAN creates unlabeled clusters
2. System tries to create suggestions → **All skipped** because no clusters are labeled
3. User sees "Unlabeled identity" for everything
4. User must manually label first cluster before suggestions surface

### This Is By Design But UX Is Poor

The eligibility check is correct (suggestions should target labeled clusters), but:

- First-run experience shows no actionable suggestions
- Users don't know they need to label first

### Recommended Improvements

1. **Add onboarding hint**: "Label your first cluster to start seeing suggestions"
2. **Auto-label high-confidence clusters**: If HDBSCAN creates a 5+ member cluster with >0.90 similarity, auto-name it `Person 1`, `Person 2`, etc.
3. **Show "Getting Started" state**: Instead of empty suggestions panel, show guidance

---

## 4. Dead Code: Tier Batch Limits (Python)

### Status: ✅ VERIFIED CLEAN

The investigation claimed tier limits were removed from Python. Searching for `_DEFAULT_TIER_BATCH_LIMITS`, `load_tier_batch_limits`, and `max_batch_for_tier` confirms:

- **No matches in Python codebase** (only in docs referencing the old code)
- Only reference is in [progress-tracking-investigation-2026-01-20.md](progress-tracking-investigation-2026-01-20.md) documenting removal

---

## 5. Antipattern: Test Mocks Don't Match Production Defaults

### Problem

Multiple test files mock `get_curriculum_t` to return `0.0`:

```python
# test_confidence_check.py
repo.get_curriculum_t = AsyncMock(return_value=0.0)

# test_centroid_recomputation.py
repo.get_curriculum_t.return_value = 0.0
```

But the investigation established `0.5` as the correct default. Tests may pass but don't reflect production behavior.

### Files Affected

- [test_confidence_check.py#L70](../../../../apps/prototype-description-service/recognition/tests/unit/test_confidence_check.py#L70)
- [test_centroid_recomputation.py#L25](../../../../apps/prototype-description-service/recognition/tests/unit/test_centroid_recomputation.py#L25)
- [test_representative_lifecycle.py#L26](../../../../apps/prototype-description-service/recognition/tests/unit/test_representative_lifecycle.py#L26)

### Recommended Fix

Update mocks to return `0.5` or use explicit test cases for both values.

---

## 6. Antipattern: Magic Numbers in Tests

### Problem

Several tests hardcode threshold values that should reference settings:

```python
# test_curriculum_thresholds.py
suggestion_floor=0.65,  # New default - should this reference ClusteringSettings?
```

If `ClusteringSettings.suggestion_floor` changes, tests may become stale.

### Recommendation

Import defaults from settings in tests:

```python
from recognition.application.settings import ClusteringSettings

DEFAULT_SETTINGS = ClusteringSettings()

# In test
assert result.metadata["suggestion_floor"] <= DEFAULT_SETTINGS.suggestion_floor + 0.05
```

---

## 7. Unnecessary Complexity: Duplicate Quality Computation Logic

### Status: ✅ VERIFIED FIXED

The audit claimed `_compute_identity_quality` was duplicated. Checking [assignment_writer.py#L69-91](../../../../apps/prototype-description-service/recognition/application/persistence/assignment_writer.py#L69-91):

```python
def _compute_identity_quality(identity: MediaIdentity, settings: ClusteringSettings) -> float:
    """Compute quality score for a media identity.

    Delegates to the canonical compute_identity_quality in quality.py which
    considers detection confidence, pose angles, and face size.
    ...
    """
    info = _compute_quality_info(...)  # Delegates to quality.py
    return info.score
```

The function now **delegates** to the canonical implementation. ✅ Fixed.

---

## 8. Missing Test: Progress Tracking Verification

### Problem

[progress-tracking-investigation-2026-01-20.md](progress-tracking-investigation-2026-01-20.md) has incomplete verification checklist:

```markdown
## Testing Verification

After removing throttling:

- [ ] Submit 100+ images in single request - should succeed
- [ ] Verify progress shows correct total count
- [ ] Confirm no 400 errors from batch limits
```

These are marked as TODO but there's no integration test enforcing them.

### Current Coverage

PHP tests validate batch limit parsing but don't test end-to-end 100+ image flow.

### Recommended Test

```php
/**
 * @test
 * Integration test: 100 images should succeed without 400 error.
 */
public function test_analyze_accepts_100_media_ids(): void {
    // Mock 100 valid media IDs
    $media_ids = range(1, 100);

    // Setup mock to return success
    TestCase::queueHttpResponse([
        'status' => 200,
        'body' => ['job_id' => 'test-job', 'status' => 'queued']
    ]);

    $request = $this->createAnalyzeRequest($media_ids);
    $response = $this->controller->analyze_media($request);

    $this->assertEquals(200, $response->get_status());
}
```

---

## 9. Documentation Stale: Stability Audit Action Items

### Problem

[stability-audit-2026-01-20.md](stability-audit-2026-01-20.md) shows all items as complete, but:

1. **curriculum_t model mismatch** was not caught
2. **Orphan recovery** is marked as not applicable but was a P1 recommendation in the regression investigation
3. **OpenAPI contract validation** is correctly deferred but no tracking issue created

### Recommended Updates

Update stability audit to reflect:

- [ ] curriculum_t model sync (NEW P0)
- [ ] Orphan recovery endpoint (P1 from regression investigation)
- [ ] OpenAPI validation tracking issue

---

## Summary of Required Actions

### ~~P0: Critical (Fix Now)~~ ✅ COMPLETE

| Item                           | File                         | Change                                     |
| ------------------------------ | ---------------------------- | ------------------------------------------ |
| ~~curriculum_t model default~~ | `db/models/identity.py#L101` | ✅ Changed to `server_default=text("0.5")` |

### P1: High (This Sprint)

| Item                         | Files                       | Change                                              |
| ---------------------------- | --------------------------- | --------------------------------------------------- |
| Add orphan recovery endpoint | New router + service method | Detect and re-cluster orphaned identities           |
| Update test mocks            | Multiple test files         | Change `get_curriculum_t` mocks from `0.0` to `0.5` |

### P2: Medium (Next Sprint)

| Item                           | Files     | Change                                       |
| ------------------------------ | --------- | -------------------------------------------- |
| Add 100-image integration test | PHP tests | Verify end-to-end flow                       |
| First-run UX improvements      | Frontend  | Add onboarding hints for suggestion workflow |

### P3: Low (Backlog)

| Item                          | Files        | Change                                  |
| ----------------------------- | ------------ | --------------------------------------- |
| Reference settings in tests   | Python tests | Import defaults instead of hardcoding   |
| Create OpenAPI tracking issue | GitHub       | Track deferred contract validation work |

---

## Consolidated Task Checklist

### Completed ✅

- [x] **P0**: Fix curriculum_t model default mismatch (`db/models/identity.py#L101` → `0.5`)
- [x] **Verified**: UUID fix in `constrained_hac.py` (passes `str(tenant_id)`)
- [x] **Verified**: PHP batch limits raised to 10000
- [x] **Verified**: suggestion_floor lowered to 0.65 in `ClusteringSettings`
- [x] **Verified**: PHP retry logic with exponential backoff
- [x] **Verified**: BatchLimits trait created and used
- [x] **Verified**: MaturitySettings class extracted
- [x] **Verified**: Quality computation consolidated (delegates to `quality.py`)
- [x] **Verified**: ClusterService session validation property added
- [x] **Verified**: Python tier batch limits removed (no dead code)

### P1: This Sprint

- [x] Add orphan recovery endpoint `POST /recognition/clusters/recover-orphans`
- [x] Update test mock: `test_confidence_check.py#L70` → `return_value=0.5`
- [x] Update test mock: `test_centroid_recomputation.py#L25` → `return_value=0.5`
- [x] Update test mock: `test_representative_lifecycle.py#L26` → `return_value=0.5`

### P2: Next Sprint

- [x] Add PHP integration test for 100-image batch (end-to-end)
- [x] Add first-run UX hint: "Label your first cluster to see suggestions"
- [x] Consider auto-labeling high-confidence clusters (`Person 1`, `Person 2`, etc.)

### P3: Backlog

- [x] Refactor tests to import thresholds from `ClusteringSettings` instead of hardcoding
- [ ] Create GitHub issue for OpenAPI contract validation (deferred work; needs repo access)
- [x] Update `progress-tracking-investigation.md` verification checklist to mark items done
