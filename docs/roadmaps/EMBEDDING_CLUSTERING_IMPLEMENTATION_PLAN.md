# Implementation Plan: Recognition Embeddings for Facial Clustering

**Created:** October 26, 2025  
**Status:** Implementation Complete - Ready for Testing  
**Priority:** HIGH - Required for clustering feature

## Executive Summary

The assisted face identification workflow currently cannot cluster similar faces because embedding vectors are not persisted. The recognition service generates 512-dimensional InsightFace embeddings during detection, but only the `embedding_id` reference is stored in the WordPress database. The actual embedding vectors are discarded immediately after generation.

**Result:** Remote FAISS clustering cannot work because there's no data to cluster.

## Problem Analysis

### Current Architecture (BROKEN)

```
┌─────────────────────────────────────────────────────────────────┐
│ Face Scan Flow - Current (embeddings LOST)                      │
├─────────────────────────────────────────────────────────────────┤
│ 1. User triggers face scan                                      │
│ 2. FaceDetectionJob calls recognition service                   │
│ 3. Recognition service:                                          │
│    - Detects faces with InsightFace (not YOLO)                 │
│    - Generates 512-dim InsightFace embeddings                   │
│    - Returns: {embedding_id, bbox, confidence}                  │
│    - Embedding vector: [0.123, -0.456, ...] ❌ NOT RETURNED     │
│    - Note: YOLO used separately for object detection (context)  │
│ 4. RecognitionServiceFaceDetectionPipeline extracts embedding_id│
│ 5. FaceDetectionJob saves to wp_cat_unknown_faces:             │
│    - embedding_id: "abc123" ✅                                   │
│    - embedding_vector: NULL ❌                                   │
│ 6. ClusteringService attempts clustering:                       │
│    - Calls buildRemotePayload()                                 │
│    - Calls resolveEmbeddingVector() → returns [] ❌             │
│    - No vectors to send to FAISS → falls back to 1:1 ❌         │
└─────────────────────────────────────────────────────────────────┘
```

### Target Architecture (FIXED)

```
┌─────────────────────────────────────────────────────────────────┐
│ Face Scan Flow - Target (embeddings PERSISTED)                  │
├─────────────────────────────────────────────────────────────────┤
│ 1. User triggers face scan                                      │
│ 2. FaceDetectionJob calls recognition service                   │
│ 3. Recognition service:                                          │
│    - Detects faces with InsightFace (not YOLO)                 │
│    - Generates 512-dim InsightFace embeddings                   │
│    - Returns: {embedding_id, embedding, bbox, confidence}       │
│    - Embedding vector: [0.123, -0.456, ...] ✅ INCLUDED         │
│    - Note: YOLO used separately for object detection (context)  │
│ 4. RecognitionServiceFaceDetectionPipeline extracts both:       │
│    - embedding_id: "abc123"                                     │
│    - embedding_vector: [0.123, ...]                             │
│ 5. FaceDetectionJob saves to wp_cat_unknown_faces:             │
│    - embedding_id: "abc123" ✅                                   │
│    - embedding_vector: JSON array ✅                             │
│ 6. ClusteringService performs clustering:                       │
│    - Calls buildRemotePayload()                                 │
│    - Calls resolveEmbeddingVector() → returns float[] ✅        │
│    - Sends vectors to FAISS clustering service ✅               │
│    - Groups similar faces (reduces 35 to ~5-10 clusters) ✅     │
└─────────────────────────────────────────────────────────────────┘
```

## Implementation Steps

### Phase 1: Database Schema (30 min)

**File:** `src/Infrastructure/Repositories/UnknownFaceRepository.php`

**Task:** Add `embedding_vector` column to store serialized embeddings.

```php
// In ensureTableExists() method
$sql = "CREATE TABLE IF NOT EXISTS {$tableName} (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    attachment_id BIGINT UNSIGNED NOT NULL,
    bbox TEXT NOT NULL,
    embedding_id VARCHAR(255) DEFAULT NULL,
    embedding_vector MEDIUMTEXT DEFAULT NULL COMMENT '512-dim embedding as JSON array',
    cluster_id VARCHAR(255) DEFAULT NULL,
    roster_id VARCHAR(255) DEFAULT NULL,
    detected_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_attachment (attachment_id),
    INDEX idx_roster (roster_id),
    INDEX idx_cluster (cluster_id),
    INDEX idx_embedding (embedding_id),
    INDEX idx_detected (detected_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci";
```

**Size Considerations:**

- 512 floats × ~10 chars each = ~5 KB per face
- 35 faces × 5 KB = ~175 KB total (negligible)
- MEDIUMTEXT: 16 MB limit (supports ~3,200 faces)

**Migration:** Column will be added automatically on next scan due to `ensureTableExists()`.

---

### Phase 2: Recognition Service Response (1 hour)

**File:** `apps/recognition-service/recognition_core/utils/conversion.py`

**Task:** Include embedding vector in `face_data` field.

**Current code (lines 85-88):**

```python
face_data={
    "embedding_dimension": len(face_embedding.embedding),
    "similarity_score": roster_match.similarity_score if roster_match else 0.0
}
```

**Updated code:**

```python
face_data={
    "embedding_id": f"face-{i}",  # Generate unique ID
    "embedding": face_embedding.embedding.tolist(),  # ✅ ADD THIS
    "embedding_dimension": len(face_embedding.embedding),
    "similarity_score": roster_match.similarity_score if roster_match else 0.0
}
```

**Alternative:** Add top-level field to avoid breaking `face_data` structure:

```python
# In convert_to_analysis_format(), add embeddings to response
return {
    "scene_description": f"Scene with {len(detected_entities)} detected person(s)",
    "processing_time": recognition_result.processing_time_ms,
    "detected_objects": [obj.to_dict() for obj in detected_objects],
    "detected_entities": [entity.to_dict() for entity in detected_entities],
    "embeddings": [face_emb.embedding.tolist() for face_emb in recognition_result.face_embeddings],  # ✅ ADD THIS
    "roster_matches": roster_matches,
    # ...
}
```

---

### Phase 3: PHP Extraction (30 min)

**File:** `src/Recognition/RecognitionServiceFaceDetectionPipeline.php`

**Task:** Extract embedding vector from response.

**Current code (lines 120-139):**

```php
// Extract embedding ID if present
$embeddingId = null;
if (isset($entity['embedding_id']) && is_string($entity['embedding_id']) && trim($entity['embedding_id']) !== '') {
    $embeddingId = trim($entity['embedding_id']);
} elseif (isset($entity['face_id']) && is_string($entity['face_id']) && trim($entity['face_id']) !== '') {
    $embeddingId = trim($entity['face_id']);
}

$results[] = [
    'bbox' => $bbox,
    'embeddingId' => $embeddingId,
    'clusterId' => null,
    'detectedAt' => $this->resolveDetectedAt($entity),
];
```

**Updated code:**

```php
// Extract embedding ID if present
$embeddingId = null;
if (isset($entity['embedding_id']) && is_string($entity['embedding_id']) && trim($entity['embedding_id']) !== '') {
    $embeddingId = trim($entity['embedding_id']);
} elseif (isset($entity['face_id']) && is_string($entity['face_id']) && trim($entity['face_id']) !== '') {
    $embeddingId = trim($entity['face_id']);
}

// ✅ Extract embedding vector if present
$embeddingVector = null;
if (isset($entity['face_data']['embedding']) && is_array($entity['face_data']['embedding'])) {
    $embeddingVector = $entity['face_data']['embedding'];
} elseif (isset($result['embeddings'][$entityIndex]) && is_array($result['embeddings'][$entityIndex])) {
    // Alternative: top-level embeddings array
    $embeddingVector = $result['embeddings'][$entityIndex];
}

$results[] = [
    'bbox' => $bbox,
    'embeddingId' => $embeddingId,
    'embeddingVector' => $embeddingVector,  // ✅ ADD THIS
    'clusterId' => null,
    'detectedAt' => $this->resolveDetectedAt($entity),
];
```

---

### Phase 4: Database Storage (30 min)

**File:** `src/Jobs/FaceDetectionJob.php`

**Task:** Store embedding vector in database.

**Current code (line 80):**

```php
$this->repository->save(
    $face['bbox'],
    $attachmentId,
    $face['embeddingId'] ?? null,
    $face['clusterId'] ?? null,
    $face['detectedAt'] ?? null
);
```

**Updated repository method signature:**

```php
public function save(
    array $bbox,
    int $attachmentId,
    ?string $embeddingId = null,
    ?string $clusterId = null,
    ?DateTimeInterface $detectedAt = null,
    ?array $embeddingVector = null  // ✅ ADD THIS
): ?int
```

**Updated FaceDetectionJob call:**

```php
$this->repository->save(
    $face['bbox'],
    $attachmentId,
    $face['embeddingId'] ?? null,
    $face['clusterId'] ?? null,
    $face['detectedAt'] ?? null,
    $face['embeddingVector'] ?? null  // ✅ ADD THIS
);
```

**In UnknownFaceRepository::save():**

```php
$data = [
    'attachment_id' => $attachmentId,
    'bbox' => wp_json_encode($bbox),
    'embedding_id' => $embeddingId,
    'embedding_vector' => $embeddingVector !== null ? wp_json_encode($embeddingVector) : null,  // ✅ ADD THIS
    'cluster_id' => $clusterId,
    'detected_at' => $detectedAtString,
];
```

---

### Phase 5: Entity Layer (30 min)

**File:** `src/Domain/Entities/UnknownFace.php`

**Task:** Add `embeddingVector` property and getter.

**Add property:**

```php
private ?array $embeddingVector;
```

**Add getter:**

```php
public function embeddingVector(): ?array
{
    return $this->embeddingVector;
}
```

**Update factory method:**

```php
public static function fromRow(array $row): self
{
    // ... existing code ...

    $embeddingVector = null;
    if (isset($row['embedding_vector']) && is_string($row['embedding_vector']) && $row['embedding_vector'] !== '') {
        $decoded = json_decode($row['embedding_vector'], true);
        if (is_array($decoded)) {
            $embeddingVector = $decoded;
        }
    }

    return new self(
        $id,
        $attachmentId,
        $bbox,
        $embeddingId,
        $embeddingVector,  // ✅ ADD THIS
        $clusterId,
        $rosterId,
        $detectedAt
    );
}
```

---

### Phase 6: Clustering Service (15 min)

**File:** `src/Domain/Clustering/ClusteringService.php`

**Task:** Implement `resolveEmbeddingVector()` to return stored vector.

**Current code (lines 1016-1024):**

```php
private function resolveEmbeddingVector(UnknownFace $face): array
{
    $embeddingId = $face->embeddingId();

    if (!is_string($embeddingId) || $embeddingId === '') {
        return [];
    }

    return [];  // ❌ Always returns empty
}
```

**Updated code:**

```php
private function resolveEmbeddingVector(UnknownFace $face): array
{
    $embeddingVector = $face->embeddingVector();

    if ($embeddingVector === null || !is_array($embeddingVector)) {
        return [];
    }

    // Validate vector has correct dimension (512 for InsightFace)
    if (count($embeddingVector) !== 512) {
        error_log(sprintf(
            '[ClusteringService] Invalid embedding dimension for face %d: expected 512, got %d',
            $face->id() ?? 0,
            count($embeddingVector)
        ));
        return [];
    }

    // Vector is already normalized by InsightFace, return as-is
    return $embeddingVector;
}
```

---

### Phase 7: Lower Threshold (5 min)

**File:** `src/Domain/Clustering/ClusteringService.php`

**Task:** Enable clustering with current face count.

**Current code (line 44):**

```php
private const LOCAL_CLUSTER_THRESHOLD = 50;
```

**Updated code:**

```php
private const LOCAL_CLUSTER_THRESHOLD = 10;  // ✅ Changed from 50
```

**Rationale:**

- Current: 35 faces won't trigger remote clustering (35 < 50)
- Updated: 35 faces WILL trigger remote clustering (35 > 10)
- Remote service supports `REMOTE_MIN_CLUSTER_SIZE = 2` (can group 2+ similar faces)
- Can be adjusted after testing

---

### Phase 8: Testing (1-2 hours)

#### 8.1 Clear Existing Data

```bash
# Option 1: Direct SQL (if wp-cli works)
wp db query "TRUNCATE TABLE wp_cat_unknown_faces"

# Option 2: Create custom WP-CLI command
wp cat-faces clear-unknown

# Option 3: Manual in phpMyAdmin/SequelPro
TRUNCATE TABLE wp_cat_unknown_faces;
```

#### 8.2 Rescan Images

1. Open WordPress admin → Media Library
2. Select images with faces
3. Click "Scan Faces" button
4. Wait for scan to complete

#### 8.3 Verify Database

```sql
SELECT
    id,
    attachment_id,
    embedding_id,
    LENGTH(embedding_vector) as vector_size,
    JSON_LENGTH(embedding_vector) as vector_dimension,
    cluster_id,
    detected_at
FROM wp_cat_unknown_faces
ORDER BY id DESC
LIMIT 10;
```

**Expected results:**

- `embedding_id`: "abc123" or similar
- `vector_size`: ~5000 bytes
- `vector_dimension`: 512
- `cluster_id`: NULL initially (assigned during clustering)

#### 8.4 Test Clustering API

```bash
# Call cluster API
curl -X GET "http://localhost/wp-json/cat/v1/clusters?page=1&per_page=50" \
  -H "X-WP-Nonce: YOUR_NONCE"
```

**Expected response:**

```json
{
  "clusters": [
    {
      "id": "cluster-abc-001",
      "face_count": 5, // ✅ Multiple faces grouped
      "sample_face": {
        /* ... */
      }
    },
    {
      "id": "cluster-abc-002",
      "face_count": 3, // ✅ Multiple faces grouped
      "sample_face": {
        /* ... */
      }
    }
    // ... 5-10 clusters instead of 35
  ],
  "total": 8 // ✅ Much fewer than 35 faces
}
```

**Success criteria:**

- `total` < number of faces (clustering happened)
- Some clusters have `face_count` > 1 (faces grouped)
- Similar-looking faces in same cluster

#### 8.5 Test Cluster Detail View

```bash
# Get faces in a cluster
curl -X GET "http://localhost/wp-json/cat/v1/clusters/cluster-abc-001" \
  -H "X-WP-Nonce: YOUR_NONCE"
```

**Expected:**

- Multiple faces with similar appearances
- All faces have thumbnails
- Can proceed to label cluster

---

## Implementation Order

1. ✅ **Phase 2** (Recognition Service) - Make embeddings available first - COMPLETED
2. ✅ **Phase 1** (Database Schema) - Add column to store them - COMPLETED
3. ✅ **Phase 3** (PHP Extraction) - Extract from response - COMPLETED
4. ✅ **Phase 4** (Database Storage) - Save to database - COMPLETED
5. ✅ **Phase 5** (Entity Layer) - Add to domain model - COMPLETED
6. ✅ **Phase 6** (Clustering Service) - Use stored vectors - COMPLETED
7. ✅ **Phase 7** (Lower Threshold) - LOCAL_CLUSTER_THRESHOLD set to 5 - COMPLETED
8. 🔄 **Phase 8** (Testing) - Verify end-to-end - READY FOR TESTING

**Total estimated time:** 3.5-4.5 hours

---

## Alternative Approaches Considered

### Option A: Store in Separate Table (Rejected)

```sql
CREATE TABLE wp_cat_face_embeddings (
    face_id BIGINT UNSIGNED PRIMARY KEY,
    embedding_vector MEDIUMBLOB NOT NULL,
    FOREIGN KEY (face_id) REFERENCES wp_cat_unknown_faces(id)
);
```

**Pros:**

- Normalized schema
- Can add indexes on embedding dimensions (for future local FAISS)

**Cons:**

- Adds complexity (JOINs required)
- Overkill for current use case
- Harder to clean up orphaned records

**Decision:** Keep in same table for simplicity.

---

### Option B: Binary Format (Rejected)

Store as packed binary instead of JSON:

```php
$packed = pack('f*', ...$embeddingVector);  // 512 floats × 4 bytes = 2 KB
```

**Pros:**

- 60% smaller (2 KB vs 5 KB)
- Slightly faster serialization

**Cons:**

- Not human-readable
- Harder to debug
- PHP `pack()` has platform-specific float format issues

**Decision:** Use JSON for debuggability.

---

### Option C: Local Clustering Only (Rejected)

Implement clustering in PHP using cosine similarity:

```php
private function clusterLocally(array $faces): array
{
    // Calculate pairwise distances
    // Run DBSCAN/agglomerative clustering
    // Return cluster assignments
}
```

**Pros:**

- No external service dependency
- Works offline

**Cons:**

- O(n²) complexity (slow for large datasets)
- No FAISS optimizations (HNSW, IVF)
- Reinventing the wheel

**Decision:** Use remote FAISS service - it's already built and optimized.

---

## Rollback Plan

If implementation causes issues:

1. **Database rollback:**

   ```sql
   ALTER TABLE wp_cat_unknown_faces DROP COLUMN embedding_vector;
   ```

2. **Code rollback:**

   - Revert changes to `RecognitionServiceFaceDetectionPipeline.php`
   - Revert `FaceDetectionJob.php` to ignore `embeddingVector`
   - Keep `resolveEmbeddingVector()` returning empty array

3. **Threshold rollback:**
   ```php
   private const LOCAL_CLUSTER_THRESHOLD = 50;  // Back to original
   ```

System will continue working with 1:1 face-to-cluster mapping.

---

## Success Metrics

- [ ] Database column added successfully
- [ ] Embeddings returned from recognition service
- [ ] Embeddings saved to database (512-dimensional vectors)
- [ ] `resolveEmbeddingVector()` returns non-empty arrays
- [ ] Remote clustering API called (check logs)
- [ ] Cluster count < face count (grouping happened)
- [ ] Similar faces grouped in same cluster (visual verification)
- [ ] Cluster detail view shows grouped faces
- [ ] Can label entire cluster at once (workflow improvement)

---

## Next Steps After Implementation

1. **Performance optimization:**

   - Add caching for frequently accessed embeddings
   - Consider binary format if JSON becomes bottleneck

2. **Feature enhancements:**

   - Add "merge clusters" functionality
   - Add "split cluster" functionality
   - Show similarity scores in cluster view

3. **Data cleanup:**

   - Periodic cleanup of embeddings for deleted attachments
   - Archival of old unknown faces (>90 days)

4. **Monitoring:**
   - Track embedding storage size
   - Monitor clustering success rate
   - Alert if embeddings fail to save

---

## Questions & Decisions

**Q: Should we normalize embeddings before storage?**  
A: No - InsightFace already returns L2-normalized vectors. Store as-is.

**Q: What about privacy concerns with storing biometric data?**  
A: Embeddings are feature vectors, not images. GDPR/privacy implications should be documented. Consider adding opt-out.

**Q: Can we use this for re-identification across different photos?**  
A: Yes! Once labeled, can match against roster embeddings. That's the whole point.

**Q: What about performance with 1000+ faces?**  
A: JSON storage scales to ~3,200 faces (MEDIUMTEXT limit). For larger datasets, consider binary format or separate table.

---

## Related Documentation

- [Face Detection Plan](./architecture/rules/roadmaps/CONSOLIDATED_FACE_DETECTION_PLAN.md)
- [Recognition Service Architecture](./architecture/backend-uml/recognition_service.mermaid)
- [Clustering Service UML](./architecture/backend-uml/clustering_service.mermaid)
- [Recognition Identify Contract](./architecture/contracts/workbench/recognition-identify.json)

---

**End of Implementation Plan**
