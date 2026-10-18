# Embedding Simplification — 512D Face-Only Vector

**Date:** 2025-12-13  
**Version:** 4.2.6  
**Status:** Proposed  
**Related:** [batch_consistency_implementation.md](./batch_consistency_implementation.md)

---

## 1. Problem Statement

The current codebase uses 1024D "extended embeddings" that pack face identity (512D) + metadata (512D) into a single vector. This causes:

1. **Normalization bugs**: When normalizing 1024D, metadata dimensions dilute face similarity
2. **Index inefficiency**: pgvector indexes 1024D but only 512D matters for matching
3. **Code complexity**: Must call `extract_face_embedding()` everywhere before similarity

## 2. Solution

Switch to 512D face-only embeddings with separate metadata columns.

### Current (1024D packed)
```
embedding VECTOR(1024)  -- face[0:512] + metadata[512:1024]
```

### Proposed (512D + columns)
```sql
embedding VECTOR(512),  -- face only
pose_pitch FLOAT,
pose_yaw FLOAT,
pose_roll FLOAT,
age INT,
gender INT,
```

> [!NOTE]
> The database migration already implements this layout (`EMBEDDING_DIMENSION = 512` with separate columns). This task updates Python code to match.

---

## 3. Proposed Changes

### 3.1 Domain Layer

#### [DELETE] [layout.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/domain/embeddings/layout.py)

Remove the extended embedding layout module entirely. Constants like `EXTENDED_EMBEDDING_DIM`, `POSE_START`, `AGE_IDX` are no longer needed.

#### [DELETE] [builder.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/domain/embeddings/builder.py)

Remove `build_extended_embedding()` and `prepare_embedding()`. Keep only `extract_face_embedding()` moved to `similarity.py`.

#### [MODIFY] [embeddings/__init__.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/domain/embeddings/__init__.py)

Simplify exports to just `FACE_EMBEDDING_DIM = 512`.

---

### 3.2 Infrastructure Layer

#### [MODIFY] [insightface adapter](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/infrastructure/embeddings/__init__.py)

- Return `(DetectedFace, embedding_512d)` instead of `embedding_1024d`
- Remove calls to `build_extended_embedding()`
- Store metadata in `DetectedFace` dataclass

#### [MODIFY] [generator.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/embedding/generator.py)

- Update `InsightFaceEmbeddingGenerator` to output 512D embeddings
- Update variable names from `embedding_1024d` to `face_embedding`

---

### 3.3 Similarity & Clustering

#### [MODIFY] [similarity.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/shared/similarity.py)

- Remove `EXTENDED_EMBEDDING_DIM = 1024`
- Simplify `extract_face_embedding()` to handle only 512D (no slicing needed)
- Keep `compute_face_similarity()` as-is (already works with 512D)

#### [MODIFY] [centroid_utils.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/clustering/centroid_utils.py)

- Remove `_to_face_embedding()` helper (no longer needed)
- All functions operate directly on 512D vectors
- Remove comments about "1024D"

---

### 3.4 Persistence Layer

#### [MODIFY] [assignment_writer.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/persistence/assignment_writer.py)

- Remove docstring references to "512D or 1024D"
- `_normalize_embedding()` works directly on 512D (no extraction)

---

### 3.5 Settings

#### [MODIFY] [settings.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/config/settings.py)

Change:
```python
embedding_dimension: int = Field(default=1024, ...)
```
To:
```python
embedding_dimension: int = Field(default=512, ...)
```

---

### 3.6 Documentation

#### [MODIFY] [db/README.md](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/db/README.md)

Update:
```markdown
- InsightFace embeddings stored as `VECTOR(1024)` rows
+ InsightFace embeddings stored as `VECTOR(512)` with separate metadata columns
```

---

## 4. Files to Delete

| File | Reason |
|------|--------|
| `recognition/domain/embeddings/layout.py` | Extended embedding layout no longer needed |
| `recognition/domain/embeddings/builder.py` | `build_extended_embedding()` no longer needed |
| `recognition/tests/unit/test_embedding_layout.py` | Tests for deleted module |
| `recognition/tests/unit/test_embedding_builder.py` | Tests for deleted module |

---

## 5. Verification Plan

### 5.1 Automated Tests

After changes, run:
```bash
cd apps/prototype-description-service
python -m pytest recognition/tests/ -v
```

Expected: All tests pass (some will be deleted, remaining should work with 512D)

### 5.2 Mypy Type Check
```bash
cd apps/prototype-description-service
python -m mypy recognition/
```

Expected: No errors

### 5.3 Database Reset & Integration
```bash
cd apps/prototype-description-service
./scripts/reset_dev_db.sh
```

Then verify embeddings are stored as 512D vectors in PostgreSQL:
```sql
SELECT array_length(embedding, 1) FROM media_identities LIMIT 1;
-- Expected: 512
```

---

## 6. Migration Risk

> [!IMPORTANT]
> **No production data migration needed** — database will be reset. This is a clean-slate greenfield change.

---

## 7. Summary of 1024D References to Update

Found in these files:
- `recognition/domain/embeddings/layout.py` → DELETE
- `recognition/domain/embeddings/builder.py` → DELETE  
- `recognition/domain/embeddings/__init__.py` → SIMPLIFY
- `recognition/infrastructure/embeddings/__init__.py` → UPDATE
- `recognition/application/embedding/generator.py` → UPDATE
- `recognition/application/clustering/centroid_utils.py` → UPDATE
- `recognition/application/persistence/assignment_writer.py` → UPDATE
- `recognition/shared/similarity.py` → UPDATE
- `recognition/config/settings.py` → UPDATE
- `db/README.md` → UPDATE
- 6+ test files → UPDATE or DELETE
