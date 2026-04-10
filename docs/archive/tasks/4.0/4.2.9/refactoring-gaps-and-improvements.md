# Recognition Module Refactoring: Gaps & Improvements

**Date**: 2025-12-23  
**Related Branch**: Current working branch (post-large-refactor)

---

## Overview

This document outlines outstanding refactoring gaps and improvement opportunities identified after evaluating the unstaged changes in the current branch. The refactor successfully simplified the recognition pipeline (removed 1024D embeddings, consolidated protocols, externalized settings), but several areas warrant further attention.

---

## Part 1: Gaps Identified from Git Diff Review

### Gap 1: Docstring Duplication in InsightFaceAdapter

| **Severity** | Low |
|--------------|-----|
| **File**     | [infrastructure/embeddings/__init__.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/infrastructure/embeddings/__init__.py#L43-L48) |
| **Lines**    | 46-47 |

**Description**: Duplicate docstring line:
```python
"""Adapter for InsightFace detection and embedding generation.

Wraps InsightFace's FaceAnalysis for face detection and generates
Wraps InsightFace's FaceAnalysis for face detection and generates  # DUPLICATE
512D face embeddings.
```

**Action**: Remove duplicate line.

---

### Gap 2: Missing Unit Tests for New Shared Utilities

| **Severity** | Medium |
|--------------|--------|
| **File**     | [shared/similarity.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/shared/similarity.py) |

**Description**: New functions `normalize_vector` and `normalize_face_embedding` were added but lack dedicated unit tests.

**Action**: Add test cases to `test_similarity.py`:
- `test_normalize_vector_unit_length`
- `test_normalize_vector_zero_vector`
- `test_normalize_face_embedding_512d`

---

### Gap 3: HDBSCAN Adapter Inline Defaults

| **Severity** | Low |
|--------------|-----|
| **File**     | [infrastructure/clustering/hdbscan_adapter.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/infrastructure/clustering/hdbscan_adapter.py#L23-L30) |

**Description**: Default values for HDBSCAN parameters are declared inline rather than derived from `ClusteringSettings`. This creates a maintenance burden if defaults change.

**Current Code**:
```python
# Default fallback values if no settings provided
_default_min_cluster_size = 2
_default_min_samples = 1
_default_epsilon = 0.55
```

**Action**: Use `ClusteringSettings()` defaults as the authoritative source:
```python
_defaults = ClusteringSettings()
self.min_cluster_size = min_cluster_size if min_cluster_size is not None else (
    settings.hdbscan_min_cluster_size if settings else _defaults.hdbscan_min_cluster_size
)
```

---

### Gap 4: parse_optional_uuid Inconsistent Export

| **Severity** | Low |
|--------------|-----|
| **File**     | [shared/__init__.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/shared/__init__.py) |

**Description**: The new `parse_optional_uuid` function in `shared/ids.py` is not exported from `shared/__init__.py`.

**Action**: Add to `__all__` in `shared/__init__.py`:
```python
from recognition.shared.ids import generate_id, parse_id, parse_optional_uuid

__all__ = [
    # ...existing...
    "parse_optional_uuid",
]
```

---

### Gap 5: Outdated Comment in HDBSCAN Adapter

| **Severity** | Low |
|--------------|-----|
| **File**     | [infrastructure/clustering/hdbscan_adapter.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/infrastructure/clustering/hdbscan_adapter.py) |

**Description**: Comment `# sqrt(2*(1-0.85))` describing epsilon calculation is outdated now that epsilon is configurable via settings.

**Action**: Remove or update comment.

---

## Part 2: Type Annotation Improvements

### Files Affected

| File | Method | Current Type | Recommended Type |
|------|--------|--------------|------------------|
| [centroid.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/discovery/centroid.py#L33) | `discover` | `centroids_by_cluster: object` | `dict[str, np.ndarray]` |
| [representative.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/discovery/representative.py#L36) | `discover` | `representatives_by_cluster: object` | `dict[str, list[np.ndarray]]` |
| [graph.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/discovery/graph.py#L122) | `discover` | `anchor_embeddings: object` | `dict[str, list[np.ndarray]]` |

**Rationale**: Using `object` defeats the purpose of type hints. These should be specific dictionary types.

---

## Part 3: File Complexity Analysis

### Summary Table

| File | Lines | Functions | Max Nesting | Complexity Score |
|------|-------|-----------|-------------|-----------------|
| `incremental_clustering.py` | **598** | 2 | 5 levels | 🔴 High |
| `assignment_writer.py` | **556** | 17 | 3 levels | 🟡 Medium |
| `cluster_split.py` | **441** | 2 | 4 levels | 🟡 Medium |
| `cluster_merge.py` | **354** | 2 | 4 levels | 🟢 Acceptable |
| `scan/service.py` | **256** | 7 | 3 levels | 🟢 Acceptable |
| `infrastructure/embeddings/__init__.py` | **207** | 10 | 2 levels | 🟢 Acceptable |

---

### 3.1 incremental_clustering.py — Critical Complexity

| **Severity** | High |
|--------------|------|
| **Lines**    | 598 (target: <150 per module for core logic) |
| **Issue**    | Single function `cluster_unclustered_identities()` spans 530+ lines |

**Deep Nesting Locations**:
- Lines 317-423: Gate decision handling with nested `if/elif/else` (4 levels)
- Lines 477-524: HAC refinement block (4 levels)
- Lines 327-386: Locator/metadata construction (3 levels)

**Recommended Decomposition**:

1. **Extract `_process_discovery_chunk()`** (~80 lines)
   - Lines 270-308: Run representative/centroid/graph discovery
   - Returns: `all_candidates`, `new_cluster_proposals`

2. **Extract `_evaluate_and_persist_candidates()`** (~120 lines)
   - Lines 317-423: Gate evaluation + persistence
   - Returns: `accepted_ids`, `suggested_ids`, `rejected_ids`, counts

3. **Extract `_run_hac_refinement()`** (~50 lines)
   - Lines 477-524: HAC noise-pool clustering
   - Returns: `clusters_created` delta

4. **Extract `_build_decision_metadata()`** (~40 lines)
   - Lines 327-386: Locator payload and metadata construction
   - Returns: `dict[str, Any]`

5. **Extract `_collect_cluster_data()`** (~50 lines)
   - Lines 237-265: Gather representatives, centroids, anchors
   - Returns: `representatives_by_cluster`, `centroids_by_cluster`, `labeled_cluster_ids`

---

### 3.2 assignment_writer.py — Duplication

| **Severity** | Medium |
|--------------|--------|
| **Lines**    | 556 |

**Duplicate Patterns**:

1. **Representative Creation** (appears 4 times):
   - Lines 264-280: In `persist_assignment()`
   - Lines 366-382: In `recompute_representatives()`
   - Lines 429-446: In `persist_new_cluster()`
   - Lines 509-527: In `assign_to_existing_cluster()`

**Recommended Refactoring**:

Extract `_create_and_add_representative()`:
```python
async def _create_and_add_representative(
    self,
    cluster_id: str,
    identity: MediaIdentity,
    reason: str,
) -> ClusterRepresentative:
    """Create and persist a representative, emitting events."""
    quality = _compute_identity_quality(identity, self._settings)
    rep = ClusterRepresentative(
        id=str(uuid.uuid4()),
        cluster_id=cluster_id,
        identity_id=identity.id,
        embedding=identity.embedding,
        created_at=datetime.now(tz=UTC),
        tenant_id=identity.tenant_id,
        quality_score=quality,
        image_phash=identity.image_phash,
    )
    await self._clusters.add_representative(rep)
    self._emit_representative_selected_event(
        cluster_id=cluster_id,
        identity=identity,
        reason=reason,
        quality_score=rep.quality_score,
        diversity_score=rep.diversity_score,
    )
    return rep
```

---

### 3.3 cluster_split.py — Deep Conditional Nesting

| **Severity** | Medium |
|--------------|--------|
| **Lines**    | 441 |

**Deeply Nested Section** (Lines 183-229):
```python
if user_label and label_owner is None and original_cluster.representative_identity_id:
    rep_id = original_cluster.representative_identity_id.lower()
    label_owner = identity_to_label.get(rep_id)

if user_label and label_owner is None:
    reference_vec = original_cluster.centroid
    if reference_vec is None:
        reference_vec = np.mean(...)
    else:
        reference_vec = np.asarray(...)
    reference_norm = float(np.linalg.norm(reference_vec))
    if reference_norm > 0:
        reference_vec = reference_vec / reference_norm
    # ... more nesting ...
```

**Recommended Refactoring**:

Extract `_determine_label_owner()`:
```python
def _determine_label_owner(
    identity_to_label: dict[str, int],
    clusters_by_label: dict[int, list],
    anchor_key: str | None,
    original_cluster: IdentityCluster,
    identities: list[MediaIdentityModel],
) -> int | None:
    """Determine which cluster group should inherit the original label."""
    # 1. Anchor override
    if anchor_key:
        anchor_label = identity_to_label.get(anchor_key)
        if anchor_label is not None:
            return anchor_label

    # 2. Representative match
    if original_cluster.representative_identity_id:
        rep_id = original_cluster.representative_identity_id.lower()
        rep_label = identity_to_label.get(rep_id)
        if rep_label is not None:
            return rep_label

    # 3. Centroid similarity match
    return _find_closest_group_to_centroid(
        original_cluster.centroid or _compute_mean(identities),
        clusters_by_label,
    )
```

---

### 3.4 cluster_merge.py — Acceptable Complexity

| **Severity** | Low |
|--------------|-----|
| **Lines**    | 354 |

The file is reasonably well-structured. Minor improvement:

**Suggestion**: Extract `_build_media_identity_from_model()` helper (~15 lines) since the same pattern appears twice (lines 100-110, 175-185).

---

### 3.5 scan/service.py — Acceptable

| **Severity** | Low |
|--------------|-----|
| **Lines**    | 256 |

No critical issues. File is well within the 300-line guideline.

---

### 3.6 infrastructure/embeddings/__init__.py — Acceptable

| **Severity** | Low |
|--------------|-----|
| **Lines**    | 207 |

No critical complexity issues beyond the duplicate docstring (Gap 1).

---

## Part 4: Logging Verbosity

### RepresentativeDiscovery Logging

| **File** | [representative.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/discovery/representative.py#L86-L91) |
|----------|---------------|

**Current**: INFO level for every match:
```python
logger.info(
    "[RepresentativeDiscovery] MATCHED identity %s -> cluster %s with similarity %.4f",
    ...
)
```

**Recommendation**: Change to DEBUG level. Keep summary logs at INFO.

---

## Part 5: Consolidation Opportunity

### Face Vector Normalization Pattern

The following pattern appears in **3 discovery classes** plus `cluster_merge.py`:
```python
face_vec = normalize_face_embedding(np.asarray(identity.embedding, dtype=np.float32))
```

**Recommendation**: Add a computed property to `MediaIdentity`:
```python
# In domain/identity.py
@property
def face_vector(self) -> np.ndarray:
    """Return normalized 512D face embedding for similarity calculations."""
    from recognition.shared.similarity import normalize_face_embedding
    return normalize_face_embedding(np.asarray(self.embedding, dtype=np.float32))
```

**Benefits**:
- Single point of truth for normalization
- Cleaner code in discovery classes
- Memoization opportunity (cache the normalized vector)

---

## Implementation Checklist

### Quick Fixes (5 min each)
- [x] Remove duplicate docstring line in `infrastructure/embeddings/__init__.py:46-47`
- [x] Remove/update obsolete epsilon comment in `hdbscan_adapter.py`
- [x] Export `parse_optional_uuid` from `shared/__init__.py`

### Medium Effort (30-60 min each)
- [x] Add unit tests for `normalize_vector`, `normalize_face_embedding` in `test_similarity.py`
- [x] Strengthen type annotations in discovery class `discover()` methods
- [x] Extract `_create_and_add_representative()` in `assignment_writer.py`
- [x] Extract `_determine_label_owner()` in `cluster_split.py`
- [ ] Extract `_build_media_identity_from_model()` in `cluster_merge.py`
- [x] Change RepresentativeDiscovery match logging to DEBUG level

### High Effort (2-4 hours)
- [x] Decompose `cluster_unclustered_identities()` into 5 smaller functions
- [x] Add `face_vector` property to `MediaIdentity` domain object
- [x] Extract inline HDBSCAN defaults to use `ClusteringSettings` defaults

---

## Verification

All refactoring changes should be verified by:

1. **Unit Tests**: Run `pytest recognition/tests/unit/ -v`
2. **Integration Tests**: Run `pytest recognition/tests/integration/ -v`
3. **Type Checking**: Run `mypy recognition/`
4. **Linting**: Run `ruff check recognition/`
