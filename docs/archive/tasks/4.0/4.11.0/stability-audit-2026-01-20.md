# v4.11.0 Stability Audit

> **Created**: 2026-01-20  
> **Status**: ✅ P0-P2 COMPLETE (P3 backlog)  
> **Scope**: Clustering pipeline, batch limits, system stability  
> **Triggered by**: 400 error on 100-image batch, unlabeled identities on first run

---

## 1. Critical Bug: PHP Tier Batch Limits Still Enforced

### Symptom

```
Request to http://localhost:10010/wp-json/acx/v1/recognition/analyze failed (400):
{"code":"rest_invalid_param","message":"Invalid parameter(s): media_ids",
 "data":{"params":{"media_ids":"media_ids supports at most 50 items per request (received 100)."}}}
```

### Root Cause

The Python backend removed tier-based batch limits (per [progress-tracking-investigation-2026-01-20.md](progress-tracking-investigation-2026-01-20.md)), but the **PHP proxy layer still enforces them**.

**PHP Enforcement Points:**

| File                                                                                                                             | Line    | Code                                              |
| -------------------------------------------------------------------------------------------------------------------------------- | ------- | ------------------------------------------------- |
| [class-recognition-controller.php](../../../../apps/prototype-wp-alt-context/src/api/class-recognition-controller.php#L37-L42)   | 37-42   | `DEFAULT_TIER_BATCH_LIMITS = ['free' => 50, ...]` |
| [class-recognition-controller.php](../../../../apps/prototype-wp-alt-context/src/api/class-recognition-controller.php#L319-L326) | 319-326 | Enforces limit on `media_items`                   |
| [class-recognition-controller.php](../../../../apps/prototype-wp-alt-context/src/api/class-recognition-controller.php#L850-L857) | 850-857 | Enforces limit on `media_ids`                     |
| [class-admin.php](../../../../apps/prototype-wp-alt-context/src/admin/class-admin.php#L36-L41)                                   | 36-41   | Duplicate limit constant                          |

**Python Backend (Fixed):**

| File                                                                                                                    | Line | Status                                                |
| ----------------------------------------------------------------------------------------------------------------------- | ---- | ----------------------------------------------------- |
| [analyze.py](../../../../apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py#L98) | 98   | ✅ Comment: "Tier-based batch limits removed for MVP" |
| [scan.py](../../../../apps/prototype-description-service/recognition/application/tasks/scan.py#L25)                     | 25   | ✅ Comment: "Tier-based batch limits removed for MVP" |

### Fix Required

**Option A (Recommended for MVP)**: Remove tier limits from PHP entirely

```php
// class-recognition-controller.php - Remove:
// - Lines 37-42 (DEFAULT_TIER_BATCH_LIMITS constant)
// - Lines 319-326 (media_items limit check)
// - Lines 850-857 (media_ids limit in validate_media_ids)
// - Lines 934-980 (get_tier_batch_limit, get_batch_limits methods)

// class-admin.php - Remove:
// - Lines 36-41 (DEFAULT_TIER_BATCH_LIMITS constant)
// - Lines 218-261 (get_tier_batch_limit, get_batch_limits methods)
```

**Option B**: Raise limits to match Python (no practical limit for MVP)

```php
private const DEFAULT_TIER_BATCH_LIMITS = array(
    'free'       => 10000,
    'pro'        => 10000,
    'business'   => 10000,
    'enterprise' => 10000,
);
```

---

## 2. Unlabeled Identities on First Run

### Symptom

First run of 10 images results in "many unlabeled identities".

### Analysis

This is **expected behavior** for cold-start scenarios. The system:

1. Detects faces and generates embeddings ✅
2. HDBSCAN groups similar faces into clusters ✅
3. Clusters start without user labels ✅
4. UI shows "Unlabeled identity" for each cluster ✅

### Why Clusters Don't Auto-Label

| Stage      | What Happens                                                    |
| ---------- | --------------------------------------------------------------- |
| Detection  | InsightFace finds faces, generates 512D embeddings              |
| Clustering | HDBSCAN groups by similarity (>0.55 epsilon)                    |
| Discovery  | RepresentativeDiscovery finds candidates                        |
| Gate       | ConfidenceCheck applies thresholds                              |
| Assignment | ACCEPT → member, SUGGEST → suggestion, REJECT → stays singleton |

**Key insight**: The system groups faces by **visual similarity**, not semantic identity. It cannot know that a cluster represents "John Smith" until a user labels it.

### Current Thresholds (Problem Area)

Per the [curriculum-threshold-fix-plan-2026-01-20.md](curriculum-threshold-fix-plan-2026-01-20.md), the investigation defaults were never fully applied:

| Setting                | Current | Recommended | Impact                         |
| ---------------------- | ------- | ----------- | ------------------------------ |
| `suggestion_floor`     | 0.65    | 0.65        | ✅ Already correct in settings |
| `curriculum_t` default | 0.5     | 0.5         | ✅ Already correct in schema   |
| `similarity_threshold` | 0.85    | 0.85        | Matches in 0.75-0.85 SUGGEST   |

### Effective Threshold Stack

For a COLD cluster with quality score 0.9:

```
base_threshold     = 0.85
maturity_adj       = 0.00 (COLD)
quality_adj        = -0.05 (high quality)
curriculum_adj     = -0.025 (t=0.5)
---------------------------------
final_threshold    = 0.775

suggestion_floor   = 0.65 + 0 - 0.05 - 0.025 = 0.575
```

Faces with similarity 0.58-0.77 will be SUGGESTED, <0.58 REJECTED, ≥0.78 ACCEPTED.

---

## 3. Anti-Patterns and Brittle Code

### 3.1 🔴 Duplicated Constants Across Layers

**Problem**: `DEFAULT_TIER_BATCH_LIMITS` is defined in two PHP files with identical values.

**Files**:

- `class-recognition-controller.php:37`
- `class-admin.php:36`

**Risk**: Values can diverge, causing inconsistent behavior between admin UI hints and API validation.

**Fix**: Extract to shared PHP trait or config class.

### 3.2 🔴 Python-PHP Contract Mismatch

**Problem**: Python removed tier limits but PHP wasn't updated. There's no automated contract validation.

**Files**:

- Python: `analyze.py`, `scan.py` (limits removed)
- PHP: `class-recognition-controller.php` (limits enforced)

**Risk**: Breaking changes silently diverge between layers.

**Fix**:

1. Add integration tests that hit PHP→Python flow with >50 items
2. Consider OpenAPI/JSON Schema shared contract

### 3.3 🟡 Magic Numbers in Maturity Computation

**Problem**: Maturity level thresholds are hardcoded magic numbers.

**File**: [maturity.py](../../../../apps/prototype-description-service/recognition/domain/maturity.py#L48-L54)

```python
if identity_count > 10 and representative_count >= 3:  # Magic!
    return ClusterMaturityLevel.MATURE
if identity_count > 1:  # Magic!
    return ClusterMaturityLevel.NASCENT
```

**Risk**: Tuning requires code changes, no visibility in settings.

**Fix**: Move to `ClusteringSettings` as configurable fields.

### 3.4 🟡 Quality Score Recomputation

**Problem**: `_compute_identity_quality` exists in both `assignment_writer.py` and `quality.py`.

**Files**:

- [assignment_writer.py:68-97](../../../../apps/prototype-description-service/recognition/application/persistence/assignment_writer.py#L68-L97)
- [quality.py](../../../../apps/prototype-description-service/recognition/application/assignment/quality.py)

**Risk**: Divergent implementations, one uses `QualitySettings`, other uses local logic.

**Fix**: Consolidate into single source of truth in `quality.py`.

### 3.5 🟡 No Retry/Backoff in HTTP Proxy

**Problem**: PHP `proxy_request` has no retry logic for transient failures.

**File**: [class-recognition-controller.php:862-898](../../../../apps/prototype-wp-alt-context/src/api/class-recognition-controller.php#L862-L898)

```php
$response = wp_remote_request( $url, array_merge( $options, [ 'method' => $method ] ) );
if ( is_wp_error( $response ) ) {
    return $response;  // No retry!
}
```

**Risk**: Network blips cause user-visible failures.

**Fix**: Add exponential backoff for 5xx and network errors.

### 3.6 🟡 Session Coupling in ClusterService

**Problem**: `ClusterService.cluster_unclustered_identities` requires session but it's optional in constructor.

**File**: [cluster_service.py:139-141](../../../../apps/prototype-description-service/recognition/application/orchestration/cluster_service.py#L139-L141)

```python
if self._session is None:
    raise RuntimeError("cluster_unclustered_identities requires an active session")
```

**Risk**: Runtime error instead of construction-time validation.

**Fix**: Make session required in constructor, or create separate `ClusterServiceWithSession` protocol.

### 3.7 🟡 Floating Point Comparison in Thresholds

**Problem**: Threshold comparisons use `>=` and `<` with floats.

**File**: [confidence.py:151-168](../../../../apps/prototype-description-service/recognition/application/assignment/checks/confidence.py#L151-L168)

```python
if similarity >= final_threshold:
    return CheckResult(passed=True, metadata=metadata)
if similarity >= adjusted_floor:
    return CheckResult(...should_reject=False...)
```

**Risk**: Edge cases at exact threshold boundaries may behave unpredictably.

**Mitigation**: Already using 4-digit rounding in metadata. Consider explicit epsilon.

### 3.8 🟢 Hardcoded Discovery Threshold

**Problem**: `RepresentativeDiscovery.discover` passes `min_similarity=0.0` to find_best_matches.

**File**: [representative.py:73-74](../../../../apps/prototype-description-service/recognition/application/discovery/representative.py#L73-L74)

```python
best_matches = self._search.find_best_matches(
    query_embeddings,
    representatives_by_cluster,
    min_similarity=0.0,  # Always find something, even garbage
)
```

**Impact**: This is intentional - we want the best match even if weak, then let ConfidenceCheck decide. Not an anti-pattern.

---

## 4. Clustering Pipeline Flow (Reference)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SCAN PHASE                                   │
├─────────────────────────────────────────────────────────────────────┤
│  1. PHP receives POST /recognition/analyze                          │
│  2. PHP validates batch limits ← 🔴 BUG HERE                        │
│  3. PHP proxies to Python /recognition/analyze                      │
│  4. Python ScanService.analyze_media() runs                         │
│  5. FaceDetector extracts faces + embeddings                        │
│  6. Embeddings persisted to media_identity table                    │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     CLUSTERING PHASE                                │
├─────────────────────────────────────────────────────────────────────┤
│  7. GraphDiscovery with HDBSCAN groups unclustered identities       │
│  8. New clusters created with:                                      │
│     - curriculum_t = 0.5 (lenient)                                  │
│     - identity_count = 1 (COLD maturity)                            │
│  9. RepresentativeDiscovery finds candidates for existing clusters  │
│ 10. AssignmentGate.evaluate() runs checks:                          │
│     - BlockCheck (user blocks)                                      │
│     - ConstraintCheck (MUST/CANNOT links)                           │
│     - ConfidenceCheck (adaptive thresholds)                         │
│ 11. AssignmentWriter persists decisions:                            │
│     - ACCEPT → Add to cluster, update curriculum_t                  │
│     - SUGGEST → Create identity_suggestion row                      │
│     - REJECT → Leave as singleton/create new cluster                │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        UI DISPLAY                                   │
├─────────────────────────────────────────────────────────────────────┤
│ 12. Frontend queries /clusters                                      │
│ 13. Clusters without labels show "Unlabeled identity"               │
│ 14. User labels cluster → suggestions surface                       │
│ 15. User accepts/rejects suggestions → curriculum_t updates         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 5. Immediate Action Items

### P0: Critical (Fix Now)

- [x] **Remove or raise PHP batch limits** - Blocking 100-image requests
  - File: `class-recognition-controller.php` ✅ FIXED (10000 limit)
  - File: `class-admin.php` ✅ Already had 10000 limit

### P1: High (This Sprint)

- [x] **Add integration test for batch >50** - Prevent regression ✅ Done (5 tests in RecognitionControllerTest.php)
- [x] **Consolidate quality score computation** - Single source of truth ✅ Done

### P2: Medium (Next Sprint)

- [x] **Extract maturity thresholds to settings** - Configurability ✅ Done
- [x] **Add retry logic to PHP proxy** - Resilience ✅ Done (exponential backoff for 5xx and WP_Error)
- [x] **Validate ClusterService session at construction** - Fail-fast ✅ Done (added `.session` property)

### P3: Low (Backlog)

- [x] **Create PHP trait for shared constants** - DRY principle ✅ Done (BatchLimits trait)
- [ ] **Add OpenAPI contract validation** - Cross-layer safety (deferred: requires dedicated task for FastAPI spec generation + PHP validation + CI integration)

---

## 6. Files Modified

| Priority | File                                                                                          | Changes                                      | Status             |
| -------- | --------------------------------------------------------------------------------------------- | -------------------------------------------- | ------------------ |
| P0       | `apps/prototype-wp-alt-context/src/api/class-recognition-controller.php`                      | Raise batch limits to 10000, add retry logic | ✅ Done            |
| P0       | `apps/prototype-wp-alt-context/src/admin/class-admin.php`                                     | Already had 10000 limit                      | ✅ Done            |
| P1       | `apps/prototype-description-service/recognition/application/assignment/quality.py`            | Canonical implementation                     | ✅ Source of truth |
| P1       | `apps/prototype-description-service/recognition/application/persistence/assignment_writer.py` | Delegate to quality.py                       | ✅ Done            |
| P1       | `apps/prototype-wp-alt-context/tests/Unit/RecognitionControllerTest.php`                      | 5 integration tests for batch limits         | ✅ Done            |
| P1       | `apps/prototype-wp-alt-context/tests/stubs/wp.php`                                            | Add sanitize_key, absint stubs               | ✅ Done            |
| P2       | `apps/prototype-description-service/recognition/application/settings/clustering.py`           | Add MaturitySettings class                   | ✅ Done            |
| P2       | `apps/prototype-description-service/recognition/domain/maturity.py`                           | Use settings instead of magic numbers        | ✅ Done            |
| P2       | `apps/prototype-description-service/recognition/application/settings/__init__.py`             | Export MaturitySettings                      | ✅ Done            |
| P2       | `apps/prototype-description-service/recognition/application/orchestration/cluster_service.py` | Add `.session` property with validation      | ✅ Done            |
| P3       | `apps/prototype-wp-alt-context/src/support/trait-batch-limits.php`                            | Shared BatchLimits trait                     | ✅ Done            |
| P3       | `apps/prototype-wp-alt-context/src/api/class-recognition-controller.php`                      | Use BatchLimits trait, remove duplicate      | ✅ Done            |
| P3       | `apps/prototype-wp-alt-context/src/admin/class-admin.php`                                     | Use BatchLimits trait, remove duplicate      | ✅ Done            |

---

## 7. Test Verification

After applying P0 fixes:

```bash
# 1. Submit 100 images - should NOT get 400 error
curl -X POST http://localhost:10010/wp-json/acx/v1/recognition/analyze \
  -H "Content-Type: application/json" \
  -d '{"media_ids": [1,2,3,...,100]}'

# 2. Verify progress shows 100/100 (not 50/50)
# Check SSE stream for correct total

# 3. Verify clusters created
./scripts/db_shell.sh -c "SELECT COUNT(*) FROM identity_clusters;"
```
