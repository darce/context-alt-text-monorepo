# Face Cluster Editing Plan

## Summary

Deliver an assisted clustering workflow inside the Workbench "Unknown People" panel that lets editors consolidate mis-clustered faces by dragging individual thumbnails between clusters. **The primary goal is to improve augmented embeddings by manually curating unrecognized faces into identified facial clusters (roster entries)**, enabling progressive learning to deliver better facial recognition over time.

This change spans WordPress (frontend + PHP backend) and the recognition service so that manually curated cluster assignments update the canonical augmented embeddings store, thereby improving future face matching accuracy.

## Goals

1. **Primary: Improve Augmented Embeddings** – Allow users to manually assign mis-clustered unknown faces to correct roster entries (identified people), storing these corrections as augmented embeddings that enhance the recognition model.
2. **Enable Cluster Consolidation** – Support dragging thumbnails between unknown clusters to fix clustering errors before confirmation.
3. **Delete Irrelevant Faces** – Allow users to dismiss faces with no archival value (random people, false detections) to keep clusters clean.
4. **Navigate to Source Media** – Provide quick access to the original WordPress media item from any face thumbnail for context and verification.
5. **Maintain Accessibility** – Keep the UX accessible (keyboard support, ARIA) and performant even with dozens of clusters.
6. **Preserve Auditability** – Log which thumbnails were moved, deleted, by whom, to which roster entry, and when.
7. **Backward Compatibility** – Maintain compatibility with existing clustering and confirmation flows.

## In Scope

- Workbench UI changes inside the element:
  ```
  <section class="cat-unknown-people-panel" aria-labelledby="cat-unknown-people-heading">
    <header class="cat-unknown-people-panel__header">…</header>
    <div class="cat-unknown-people-panel__grid">…</div>
  </section>
  ```
- Drag & drop for buttons rendered as:
  ```
  <button type="button" class="cat-cluster-card" … data-testid="cluster-card-…">
    <div class="cat-cluster-card__media"><img src="data:image/jpeg;base64,…">
  ```
- Recognition service API updates to accept cluster edits and persist them.
- Progressive-learning refresh logic so the new cluster membership updates search results.

## Out of Scope

- Automated reclustering or re-running DBSCAN/Hierarchical algorithms on the fly.
- Editing roster entries or confirmed faces (only unknown clusters).
- Bulk thumbnail regeneration (handled by recognition service when needed).

## User Flow

### Scenario A: Assign Unknown Faces to Identified Person (Primary Use Case)

1. Operator opens Unknown People panel in Workbench.
2. Unknown face clusters load from WordPress (`GET /cat/v1/clusters`).
3. User identifies a cluster that appears to be "Jane Doe" (an existing roster entry).
4. User clicks cluster to open ClusterDetailView, which shows roster suggestions.
5. User confirms cluster assignment to "Jane Doe" roster entry.
6. System:
   - Marks faces as resolved (`resolved_at`, `roster_id` set in `wp_cat_unknown_faces`).
   - Sends augmented embeddings to recognition service (`POST /api/v0/roster/{roster_id}/augment`).
   - Recognition service stores embeddings in `augmented_embeddings` table linked to Jane's roster entry.
   - Aggregate embedding for Jane is recomputed (weighted average of reference + augmented).
   - Future face detection will better match Jane's face due to enriched embeddings.

### Scenario B: Consolidate Mis-Clustered Unknown Faces (Secondary Use Case)

1. User notices two clusters that appear to be the same unknown person.
2. User drags thumbnails from source cluster and drops onto target cluster card.
3. UI updates immediately (optimistic) to reflect the new grouping.
4. Background request updates cluster membership in WordPress (`POST /cat/v1/unknown-clusters/move`).
5. Success toast with optional "Undo" link appears.
6. When eventually confirmed to a roster entry, all consolidated faces contribute augmented embeddings.

### Scenario C: Delete Irrelevant Faces

1. User opens cluster detail view and sees random people/false detections with no archival value.
2. User hovers over face thumbnail, sees contextual menu with "Delete" and "View Original" options.
3. User clicks "Delete" → confirmation dialog appears: "Remove this face? The original image will not be affected."
4. User confirms → face removed from database, thumbnail deleted, cluster count decremented.
5. System logs deletion action with user ID and timestamp for audit trail.

### Scenario D: Navigate to Original Media

1. User sees interesting/ambiguous face in cluster, needs context.
2. User clicks "View Original" button on face thumbnail (or double-clicks thumbnail).
3. WordPress Media Library opens in new tab/modal, focused on the source attachment.
4. User reviews full image, reads alt text, checks upload date for context.
5. User returns to Workbench to continue clustering workflow.

### Scenario E: Clear All Unknown Faces (Bulk Cleanup)

1. User has processed all valuable clusters (confirmed known people, deleted obvious false detections).
2. Remaining clusters contain random people/strangers with no archival value (e.g., 20 clusters of event attendees).
3. User clicks "Clear All Remaining" button in Unknown People panel header.
4. Confirmation dialog: "Dismiss all 127 remaining unknown faces? This will mark them as reviewed but not identified. You can still find them via database queries if needed. This action cannot be undone."
5. User confirms → all unresolved faces marked as `roster_id='__cleared__'`, `resolved_at=NOW()`.
6. Success notification: "Cleared 127 unknown faces from 20 clusters."
7. Unknown People panel now shows empty state: "All unknown faces have been reviewed! New faces will appear here as you scan more images."

## Technical Approach

### Frontend (WordPress Workbench SPA)

**Status:** Drag-and-drop infrastructure already implemented. See:

- `js/components/workbench/ClusterCard.tsx` – Drop target with `onDropFaces` callback
- `js/components/workbench/UnknownPeoplePanel.tsx` – Manages drop state via `onMoveFaces` prop
- `js/components/workbench/dragTypes.ts` – `FaceDragPayload` type with `clusterId` and `faceIds`
- Tests in `ClusterCard.test.tsx` and `UnknownPeoplePanel.test.tsx`

**Implementation Path:**

1. **Cluster Detail Face Selection:**

   - Extend `ClusterDetailView` to support multi-select of face thumbnails.
   - Add checkbox or toggle selection mode.
   - Track selected `faceIds` in local state.
   - Implement drag initiation from selected thumbnails (set `FaceDragPayload` on drag start).

2. **Drag-and-Drop Between Clusters:**

   - `ClusterCard` already handles `onDragEnter`, `onDragOver`, `onDrop` events.
   - `UnknownPeoplePanel.handleDropFaces` receives `{ targetClusterId, sourceClusterId, faceIds }`.
   - Wire to new mutation hook: `useMoveFaces` (TanStack Query mutation).

3. **Backend Mutation:**

   - `useMoveFaces` calls `POST /cat/v1/unknown-clusters/move`:
     ```typescript
     {
       face_ids: number[],        // WordPress database IDs from wp_cat_unknown_faces
       source_cluster_id: string,
       target_cluster_id: string
     }
     ```
   - On success: invalidate cluster queries, show toast.
   - On error: show error toast, revert optimistic update.

4. **Optimistic UI Updates:**

   - Mutation uses TanStack Query's `onMutate` to optimistically update cached cluster data.
   - Remove faces from source cluster `face_count`.
   - Add faces to target cluster `face_count`.
   - Revert on error using snapshot stored in `onMutate`.

5. **Undo Support (Optional Enhancement):**

   - Store undo payload in React state (limited time window, e.g., 30 seconds).
   - Expose "Undo" button in toast notification.
   - Call reverse mutation: `POST /cat/v1/unknown-clusters/move` with swapped source/target.

6. **Face Deletion:**

   - Add `useDeleteFace` mutation hook: `DELETE /cat/v1/unknown-faces/:id`.
   - Show confirmation dialog before deletion (avoid accidental clicks).
   - Optimistically remove from cluster cache, revert on error.
   - Toast notification: "Face removed. Undo?" (15-second window).

7. **Navigate to Original Media:**

   - Each face thumbnail stores `attachmentId` (WordPress post ID).
   - Add "View Original" button/icon overlay on hover (or double-click handler).
   - Open WordPress Media Library in new tab: `/wp-admin/upload.php?item={attachmentId}`.
   - Alternative: Modal with attachment details (title, caption, alt text, dimensions, upload date).

   **UX Best Practices:**

   - **Double-click:** Fast for power users, but requires tooltip education ("Double-click to view original").
   - **Button on hover:** More discoverable, better for accessibility (keyboard users can Tab to button).
   - **Recommendation:** Hover button + double-click shortcut (both work).

   **Implementation:**

   ```typescript
   const handleViewOriginal = (attachmentId: number) => {
     const url = `/wp-admin/upload.php?item=${attachmentId}`;
     window.open(url, "_blank", "noopener,noreferrer");
   };

   // Double-click handler
   <div
     className="cat-face-thumbnail"
     onDoubleClick={() => handleViewOriginal(face.attachmentId)}
   >
     <img src={face.thumbnailUrl} alt="Face thumbnail" />
     <button
       className="cat-face-thumbnail__view-original"
       onClick={(e) => {
         e.stopPropagation();
         handleViewOriginal(face.attachmentId);
       }}
       aria-label="View original image"
     >
       <ExternalLinkIcon />
     </button>
   </div>;
   ```

8. **Clear All Unknown Faces (Bulk Cleanup):**

   - Add "Clear All Remaining" button in Unknown People panel header.
   - Shows count: "Clear All (127 faces in 20 clusters)".
   - Only enabled when clusters exist.
   - Create `useClearAllFaces` mutation: `POST /cat/v1/unknown-clusters/clear-all`.
   - Confirmation dialog with strong warning (cannot undo bulk operation).
   - Backend bulk update: `UPDATE wp_cat_unknown_faces SET resolved_at=NOW(), roster_id='__cleared__' WHERE resolved_at IS NULL`.
   - Success notification with cleared count.
   - Empty state appears: "All unknown faces reviewed. New faces will appear as you scan more images."

### Backend (WordPress PHP)

**Current Architecture:**

- `UnknownFaceRepository` – Handles CRUD for `wp_cat_unknown_faces` table
- `ClusteringService` – Routes clustering requests, manages local/remote clustering
- `ClusterController` – REST endpoints for cluster operations (`/cat/v1/clusters/*`)
- `ClusterDetailView.php` (domain) – Not yet implemented
- Confirmation flow exists: `confirmCluster()` assigns `roster_id` and calls recognition service

**Implementation Path:**

#### 1. Add Cluster Move Endpoint

Create `POST /cat/v1/unknown-clusters/move` in `ClusterController`:

```php
public function move_faces(WP_REST_Request $request): WP_REST_Response
{
    $face_ids = $request->get_param('face_ids');
    $source_cluster_id = $request->get_param('source_cluster_id');
    $target_cluster_id = $request->get_param('target_cluster_id');

    // Validate capability
    if (!current_user_can('manage_options')) {
        return new WP_REST_Response(
            ['error' => 'Insufficient permissions'],
            403
        );
    }

    // Validate input
    if (!is_array($face_ids) || empty($face_ids)) {
        return new WP_REST_Response(
            ['error' => 'face_ids must be a non-empty array'],
            400
        );
    }

    // Load faces from database
    $faces = $this->repository->findFacesByIds($face_ids);

    // Verify all faces belong to source cluster
    foreach ($faces as $face) {
        if ($face->clusterId() !== $source_cluster_id) {
            return new WP_REST_Response(
                ['error' => "Face {$face->id()} does not belong to source cluster"],
                400
            );
        }

        // Verify face is not already resolved
        if ($face->resolvedAt() !== null) {
            return new WP_REST_Response(
                ['error' => "Face {$face->id()} is already resolved"],
                400
            );
        }
    }

    // Update cluster_id for each face
    $updated_count = $this->repository->updateClusterMembership(
        $face_ids,
        $target_cluster_id,
        get_current_user_id()
    );

    // Return success
    return new WP_REST_Response([
        'success' => true,
        'moved_count' => $updated_count,
        'source_cluster_id' => $source_cluster_id,
        'target_cluster_id' => $target_cluster_id
    ], 200);
}
```

#### 2. Extend UnknownFaceRepository

Add methods to support cluster reassignment:

```php
/**
 * Find faces by database IDs.
 *
 * @param int[] $faceIds
 * @return UnknownFace[]
 */
public function findFacesByIds(array $faceIds): array
{
    if (empty($faceIds)) {
        return [];
    }

    $this->ensureTableExists();
    $table = $this->tableName();

    // Build IN clause with placeholders
    $placeholders = implode(',', array_fill(0, count($faceIds), '%d'));
    $sql = "SELECT * FROM {$table} WHERE id IN ({$placeholders})";

    $rows = $this->wpdb->get_results(
        $this->wpdb->prepare($sql, ...$faceIds),
        ARRAY_A
    );

    return array_map(fn(array $row) => $this->hydrate($row), $rows);
}

/**
 * Update cluster_id for multiple faces atomically.
 *
 * @param int[] $faceIds
 * @param string $targetClusterId
 * @param int $userId WordPress user ID performing the action
 * @return int Number of rows updated
 */
public function updateClusterMembership(
    array $faceIds,
    string $targetClusterId,
    int $userId
): int {
    if (empty($faceIds)) {
        return 0;
    }

    $this->ensureTableExists();
    $table = $this->tableName();

    // Build IN clause
    $placeholders = implode(',', array_fill(0, count($faceIds), '%d'));
    $sql = $this->wpdb->prepare(
        "UPDATE {$table}
         SET cluster_id = %s,
             updated_at = CURRENT_TIMESTAMP
         WHERE id IN ({$placeholders})
         AND resolved_at IS NULL",
        $targetClusterId,
        ...$faceIds
    );

    $this->wpdb->query($sql);
    $updated_count = $this->wpdb->rows_affected;

    // Log the action
    error_log(sprintf(
        '[UnknownFaceRepository] User %d moved %d faces to cluster %s',
        $userId,
        $updated_count,
        $targetClusterId
    ));

    return $updated_count;
}
```

#### 3. Add Face Deletion Endpoint

Create `DELETE /cat/v1/unknown-faces/:id` in `ClusterController`:

```php
public function delete_face(WP_REST_Request $request): WP_REST_Response
{
    $face_id = (int) $request->get_param('id');

    // Validate capability
    if (!current_user_can('manage_options')) {
        return new WP_REST_Response(
            ['error' => 'Insufficient permissions'],
            403
        );
    }

    // Load face to verify it exists and is unresolved
    $face = $this->repository->findFaceById($face_id);

    if ($face === null) {
        return new WP_REST_Response(
            ['error' => 'Face not found'],
            404
        );
    }

    if ($face->resolvedAt() !== null) {
        return new WP_REST_Response(
            ['error' => 'Cannot delete resolved face'],
            400
        );
    }

    // Soft delete: mark as resolved with special roster_id
    $deleted = $this->repository->softDeleteFace(
        $face_id,
        get_current_user_id()
    );

    if (!$deleted) {
        return new WP_REST_Response(
            ['error' => 'Failed to delete face'],
            500
        );
    }

    // Log deletion
    error_log(sprintf(
        '[ClusterController] User %d deleted face %d (attachment %d, cluster %s)',
        get_current_user_id(),
        $face_id,
        $face->attachmentId(),
        $face->clusterId()
    ));

    return new WP_REST_Response([
        'success' => true,
        'face_id' => $face_id,
        'cluster_id' => $face->clusterId()
    ], 200);
}
```

**Soft Delete Strategy:**

Instead of physical deletion, mark faces as resolved with special `roster_id='__deleted__'`:

```php
public function softDeleteFace(int $faceId, int $userId): bool
{
    $this->ensureTableExists();
    $table = $this->tableName();

    $sql = $this->wpdb->prepare(
        "UPDATE {$table}
         SET resolved_at = CURRENT_TIMESTAMP,
             roster_id = '__deleted__',
             updated_at = CURRENT_TIMESTAMP
         WHERE id = %d
         AND resolved_at IS NULL",
        $faceId
    );

    $this->wpdb->query($sql);

    return $this->wpdb->rows_affected > 0;
}
```

**Benefits:**

- Maintains audit trail (who deleted, when)
- Can be restored if needed (admin UI: "Show deleted faces")
- Does not orphan embeddings or break foreign key constraints
- Queries exclude deleted and cleared faces via `WHERE roster_id NOT IN ('__deleted__', '__cleared__') OR roster_id IS NULL`

#### 4. Add Bulk Clear Endpoint

Create `POST /cat/v1/unknown-clusters/clear-all` in `ClusterController`:

```php
public function clear_all_faces(WP_REST_Request $request): WP_REST_Response
{
    // Validate capability
    if (!current_user_can('manage_options')) {
        return new WP_REST_Response(
            ['error' => 'Insufficient permissions'],
            403
        );
    }

    // Get count of faces to clear
    $count = $this->repository->countUnresolvedFaces();

    if ($count === 0) {
        return new WP_REST_Response(
            ['message' => 'No unknown faces to clear', 'cleared_count' => 0],
            200
        );
    }

    // Bulk update: mark all as cleared
    $cleared_count = $this->repository->clearAllUnresolvedFaces(
        get_current_user_id()
    );

    // Log the action
    error_log(sprintf(
        '[ClusterController] User %d cleared all %d unknown faces',
        get_current_user_id(),
        $cleared_count
    ));

    return new WP_REST_Response([
        'success' => true,
        'cleared_count' => $cleared_count
    ], 200);
}
```

**Repository Method:**

```php
/**
 * Bulk clear all unresolved faces (mark as reviewed but not identified).
 *
 * @param int $userId WordPress user ID performing the action
 * @return int Number of faces cleared
 */
public function clearAllUnresolvedFaces(int $userId): int
{
    $this->ensureTableExists();
    $table = $this->tableName();

    $sql = "UPDATE {$table}
            SET resolved_at = CURRENT_TIMESTAMP,
                roster_id = '__cleared__',
                updated_at = CURRENT_TIMESTAMP
            WHERE resolved_at IS NULL";

    $this->wpdb->query($sql);
    $cleared_count = $this->wpdb->rows_affected;

    error_log(sprintf(
        '[UnknownFaceRepository] Cleared %d unresolved faces for user %d',
        $cleared_count,
        $userId
    ));

    return $cleared_count;
}

/**
 * Count unresolved faces for "Clear All" button badge.
 *
 * @return int Total unresolved faces
 */
public function countUnresolvedFaces(): int
{
    $this->ensureTableExists();
    $table = $this->tableName();

    $sql = "SELECT COUNT(*) FROM {$table} WHERE resolved_at IS NULL";

    return (int) $this->wpdb->get_var($sql);
}
```

**Use Case: Event Photography Workflow**

After shooting a 200-person event, face detection finds 500+ faces. Workflow:

1. Confirm 20 clusters of known people (staff, speakers) → augmented embeddings
2. Delete 10 obvious false detections (backs of heads, partial faces)
3. **Clear All** remaining 400+ faces of random attendees → UI decluttered for next event

#### 5. Confirmation Flow Updates

The existing `ClusteringService::confirmCluster()` already handles:

1. Marking faces as resolved (`resolved_at`, `roster_id` set)
2. Sending augmented embeddings to recognition service
3. Triggering materialized view refresh

**No changes needed** – cluster consolidation via drag-and-drop is upstream of confirmation. When a consolidated cluster is confirmed, all faces (regardless of original cluster) contribute augmented embeddings to the target roster entry.

### Recognition Service

**Current Architecture:**

- `augmented_embeddings` table stores progressive learning data (512-dim vectors)
- Columns: `roster_entry_id`, `observation_id` (unique), `embedding`, `source`, `attachment_id`, `bbox`, `confidence`, `quality_tier`, `created_at`
- Augmented embeddings are loaded into roster entries via `load_augmented_embeddings()` in `roster_persistence.py`
- Aggregate embeddings computed via weighted average (reference + augmented)
- Materialized view `roster_aggregate_embeddings` provides fast search index

**Implementation Path:**

#### Phase 1: No Recognition Service Changes Required Initially

The existing augmented embeddings workflow handles cluster consolidation transparently:

1. **WordPress Cluster Move:** User drags faces between unknown clusters in WordPress UI.
2. **Local Update Only:** WordPress updates `cluster_id` in `wp_cat_unknown_faces` table.
3. **Confirmation Trigger:** When user confirms consolidated cluster to roster entry:
   - WordPress calls `POST /api/v0/roster/{roster_id}/augment` for each face.
   - Recognition service stores embeddings in `augmented_embeddings` with:
     - `observation_id`: WordPress face ID (ensures idempotency)
     - `source`: "wordpress_confirmation"
     - `embedding`: 512-dim face embedding vector
     - `quality_tier`: "high" (manually confirmed)
4. **Aggregate Recomputation:** Recognition service updates materialized view incrementally (~7ms).

#### Phase 2: Optional Enhanced API (Future)

If real-time cluster sync is needed between WordPress and recognition service:

**New Endpoint:** `POST /api/v0/clusters/reassign`

```python
class ClusterReassignRequest(BaseModel):
    """Request to move faces between unknown clusters."""
    tenant_id: str
    face_ids: List[str]          # WordPress face IDs (e.g., ["wp-face-123", "wp-face-124"])
    source_cluster_id: str       # e.g., "cluster-001"
    target_cluster_id: str       # e.g., "cluster-004"
    user_id: Optional[str]       # WordPress user ID for audit

class ClusterReassignResponse(BaseModel):
    """Response from cluster reassignment."""
    success: bool
    moved_count: int
    source_cluster: ClusterSummary  # Updated cluster stats
    target_cluster: ClusterSummary  # Updated cluster stats

@router.post("/clusters/reassign", response_model=ClusterReassignResponse)
async def reassign_cluster_faces(
    request: ClusterReassignRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> ClusterReassignResponse:
    """
    Move faces from source cluster to target cluster.

    This updates cluster membership metadata but does NOT create augmented
    embeddings. Augmented embeddings are created only when faces are confirmed
    to roster entries (progressive learning).

    **Workflow:**
    1. Validate tenant_id matches request.tenant_id
    2. Load cluster metadata from cache/storage
    3. Update cluster membership (remove from source, add to target)
    4. Recompute cluster statistics (face_count, sample_face)
    5. Return updated cluster summaries

    **Note:** This is metadata-only operation. No embeddings are modified.
    Actual embedding updates happen during confirmation workflow.
    """
    # Validate tenant isolation
    if tenant_id != request.tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Tenant ID mismatch"
        )

    # Load clusters from metadata store (TBD: PostgreSQL table or cache)
    # For now, this is a no-op since WordPress manages cluster state

    logger.info(
        f"[Cluster Reassign] Moving {len(request.face_ids)} faces "
        f"from {request.source_cluster_id} to {request.target_cluster_id} "
        f"(tenant: {tenant_id}, user: {request.user_id})"
    )

    return ClusterReassignResponse(
        success=True,
        moved_count=len(request.face_ids),
        source_cluster=ClusterSummary(...),  # TBD: load from storage
        target_cluster=ClusterSummary(...),  # TBD: load from storage
    )
```

**Storage Considerations:**

If recognition service needs to track unknown cluster state:

1. Add `unknown_face_clusters` table with columns:
   - `id` (UUID, primary key)
   - `tenant_id` (UUID, foreign key)
   - `cluster_id` (string, e.g., "cluster-001")
   - `face_ids` (JSON array of WordPress face IDs)
   - `created_at`, `updated_at`
2. Update on reassignment requests
3. Query during cluster listing

**Recommendation:** Start with Phase 1 (WordPress-only cluster management). Add Phase 2 only if multi-client sync or advanced analytics are needed.

### Data Model Updates

#### WordPress Schema (Already Sufficient)

The existing `wp_cat_unknown_faces` table supports cluster reassignment:

```sql
CREATE TABLE wp_cat_unknown_faces (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    attachment_id BIGINT UNSIGNED NOT NULL,
    bbox_json TEXT NOT NULL,
    embedding_id VARCHAR(255) DEFAULT NULL,
    embedding_vector MEDIUMTEXT DEFAULT NULL,     -- 512-dim embedding as JSON
    thumbnail MEDIUMTEXT DEFAULT NULL,            -- Base64 thumbnail (added recently)
    cluster_id VARCHAR(255) DEFAULT NULL,         -- ✅ Updated during drag-and-drop
    roster_id VARCHAR(255) DEFAULT NULL,          -- Set during confirmation
    detected_at DATETIME NOT NULL,
    resolved_at DATETIME DEFAULT NULL,            -- Set during confirmation
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_attachment (attachment_id),
    INDEX idx_roster (roster_id),
    INDEX idx_cluster (cluster_id),
    INDEX idx_embedding (embedding_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**No schema changes required.** The `cluster_id` column is updated during drag-and-drop operations, and `roster_id`/`resolved_at` are set during confirmation or deletion.

**Special Values:**

- `roster_id = '__deleted__'`: Face manually dismissed by user (soft delete - individual action)
- `roster_id = '__cleared__'`: Face cleared in bulk cleanup (not valuable for identification)
- `roster_id = NULL` AND `resolved_at = NULL`: Unresolved face awaiting clustering/confirmation
- `roster_id = 'person-123'` AND `resolved_at != NULL`: Confirmed to roster entry

**Query Pattern for Unresolved Faces:**

```sql
-- Exclude both deleted and cleared faces
SELECT * FROM wp_cat_unknown_faces
WHERE resolved_at IS NULL
  AND (roster_id IS NULL OR roster_id NOT IN ('__deleted__', '__cleared__'))
```

#### Recognition Service Schema (Already Complete)

The `augmented_embeddings` table stores progressive learning data:

```sql
CREATE TABLE augmented_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    roster_entry_id UUID NOT NULL REFERENCES roster_entries(id) ON DELETE CASCADE,
    observation_id VARCHAR(64) UNIQUE NOT NULL,   -- WordPress face ID (idempotency)
    embedding vector(512) NOT NULL,               -- 512-dim face embedding
    source VARCHAR(64) NOT NULL DEFAULT 'external_confirm',
    attachment_id BIGINT,                         -- WordPress attachment ID
    bbox JSONB,                                   -- Bounding box {x, y, width, height}
    confidence FLOAT,                             -- Detection confidence score
    quality_tier VARCHAR(16) NOT NULL DEFAULT 'medium',  -- high/medium/low
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    INDEX idx_aug_emb_roster (roster_entry_id),
    INDEX idx_aug_emb_quality (quality_tier)
);
```

**Key Design Principles:**

1. **Idempotency:** `observation_id` (WordPress face ID) ensures duplicate augmented embeddings are not created if confirmation is retried.
2. **Quality Tiers:** Manually confirmed faces receive `quality_tier='high'`, giving them higher weight in aggregate embedding computation.
3. **Source Tracking:** `source='wordpress_confirmation'` distinguishes manual curation from algorithmic confirmations.
4. **Cascade Delete:** When a roster entry is deleted, all associated augmented embeddings are removed automatically.

**No schema changes required.** The existing structure fully supports the cluster editing workflow.

### Drag-and-Drop Behaviour

**Current Implementation (Already Complete):**

The drag-and-drop infrastructure is fully implemented and tested:

1. **Draggable Sources:**

   - Face thumbnails within `ClusterDetailView` can be made draggable.
   - Set `FaceDragPayload` via `setFaceDragData(dataTransfer, { clusterId, faceIds })`.

2. **Drop Targets:**

   - `ClusterCard` components handle `onDragEnter`, `onDragOver`, `onDrop` events.
   - Visual feedback via `isDropTarget` prop adds `.cat-cluster-card--drop-target` class.
   - Drop validation: reject if source === target cluster.

3. **Accessibility Features:**

   - Keyboard interaction: Tab to navigate between cluster cards.
   - ARIA attributes: `aria-label` describes cluster ("Review cluster-abc (4 faces)"), `aria-pressed` for selected state.
   - Screen reader announcements: "Dropping 2 faces into cluster-xyz".

4. **Testing Coverage:**
   - `ClusterCard.test.tsx`: Validates drop handling, ignores same-cluster drops.
   - `UnknownPeoplePanel.test.tsx`: Verifies `onMoveFaces` callback with correct payload.
   - Storybook stories: `UnknownPeoplePanel.stories.tsx` demonstrates all states.

**Enhancement: Keyboard-Only Drag-and-Drop**

For users who cannot use a mouse, add keyboard-driven reassignment:

1. **Selection Mode:**

   - Press `Shift+Enter` on a cluster card to enter "Select faces for move" mode.
   - ClusterDetailView renders face thumbnails with checkboxes.
   - Arrow keys navigate, Space toggles selection.

2. **Target Selection:**

   - Press `m` (move) to activate "Choose target cluster" mode.
   - Cluster cards show "Press Enter to move here" hint.
   - Arrow keys navigate between cluster cards.
   - Enter confirms move, Escape cancels.

3. **ARIA Live Announcements:**
   ```javascript
   announcer.announce(
     `Selected 3 faces from cluster ${sourceId}. Press M to choose destination.`
   );
   announcer.announce(`Moving 3 faces to cluster ${targetId}...`);
   announcer.announce(`Successfully moved 3 faces. Press Z to undo.`);
   ```

**Implementation Snippet (React Hook):**

```typescript
const useKeyboardClusterMove = () => {
  const [mode, setMode] = useState<"normal" | "select" | "target">("normal");
  const [selectedFaces, setSelectedFaces] = useState<string[]>([]);
  const [sourceCluster, setSourceCluster] = useState<string | null>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (mode === "select" && e.key === "m") {
        setMode("target");
        announcer.announce(
          "Choose target cluster with arrow keys, Enter to confirm"
        );
      }
      if (mode === "target" && e.key === "Escape") {
        setMode("normal");
        setSelectedFaces([]);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [mode]);

  return {
    mode,
    selectedFaces,
    sourceCluster,
    setSelectedFaces,
    setSourceCluster,
  };
};
```

## API Design

### Existing Endpoints (No Changes)

| Endpoint                                              | Responsibility                                                      |
| ----------------------------------------------------- | ------------------------------------------------------------------- |
| `GET /cat/v1/clusters` (WordPress)                    | List unknown face clusters with counts and sample thumbnails        |
| `GET /cat/v1/clusters/:id` (WordPress)                | Get detailed cluster view with all face thumbnails                  |
| `POST /cat/v1/clusters/:id/confirm` (WordPress)       | Confirm cluster to roster entry, trigger augmented embeddings       |
| `DELETE /cat/v1/unknown-faces/:id` (WordPress)        | Soft delete face (mark as resolved with `roster_id='__deleted__'`)  |
| `POST /cat/v1/unknown-clusters/clear-all` (WordPress) | Bulk clear all unresolved faces (mark as `roster_id='__cleared__'`) |
| `POST /api/v0/roster/:id/augment` (Recognition)       | Add augmented embedding to roster entry (called by WordPress)       |
| `GET /api/v0/roster/:id` (Recognition)                | Retrieve roster entry with reference + augmented embeddings         |

### New Endpoints

#### WordPress REST API

**`POST /cat/v1/unknown-clusters/move`**

Move faces from one cluster to another (before confirmation).

**Request:**

```json
{
  "face_ids": [123, 124, 125],
  "source_cluster_id": "cluster-001",
  "target_cluster_id": "cluster-004"
}
```

**Response (Success):**

```json
{
  "success": true,
  "moved_count": 3,
  "source_cluster_id": "cluster-001",
  "target_cluster_id": "cluster-004"
}
```

**Response (Error - Already Resolved):**

```json
{
  "error": "Face 123 is already resolved",
  "code": "face_already_resolved"
}
```

**Authorization:** Requires `manage_options` capability.

**Side Effects:**

1. Updates `cluster_id` column in `wp_cat_unknown_faces` for specified face IDs.
2. Validates all faces belong to source cluster and are unresolved.
3. Logs action to WordPress debug log with user ID and timestamp.

---

**`DELETE /cat/v1/unknown-faces/:id`**

Soft delete a face (dismiss as irrelevant).

**Request:** (No body, face ID in URL)

**Response (Success):**

```json
{
  "success": true,
  "face_id": 123,
  "cluster_id": "cluster-001"
}
```

**Response (Error - Already Resolved):**

```json
{
  "error": "Cannot delete resolved face",
  "code": "face_already_resolved"
}
```

**Authorization:** Requires `manage_options` capability.

**Side Effects:**

1. Sets `resolved_at = CURRENT_TIMESTAMP` and `roster_id = '__deleted__'` for soft delete.
2. Face no longer appears in cluster listings (filtered out).
3. Maintains audit trail (can query deleted faces for compliance).
4. Logs deletion action to WordPress debug log.

---

**`POST /cat/v1/unknown-clusters/clear-all`**

Bulk clear all remaining unresolved faces (dismiss as not valuable for identification).

**Request:** (No body required)

**Response (Success):**

```json
{
  "success": true,
  "cleared_count": 127
}
```

**Response (No Faces to Clear):**

```json
{
  "message": "No unknown faces to clear",
  "cleared_count": 0
}
```

**Authorization:** Requires `manage_options` capability.

**Side Effects:**

1. Bulk update: Sets `resolved_at = CURRENT_TIMESTAMP` and `roster_id = '__cleared__'` for ALL unresolved faces.
2. All clusters disappear from Unknown People panel.
3. Cannot be undone (strong confirmation required in UI).
4. Logs action with total cleared count.

**Use Case:** After event photography with 500+ unknown attendees, curator confirms known people (staff, speakers), then bulk clears remaining strangers to declutter UI.

---

#### Recognition Service API (Phase 2 - Optional)

**`POST /api/v0/clusters/reassign`**

Synchronize cluster membership changes from WordPress to recognition service. This is metadata-only; no embeddings are modified until confirmation.

**Request:**

```json
{
  "tenant_id": "site-uuid-123",
  "face_ids": ["wp-face-123", "wp-face-124"],
  "source_cluster_id": "cluster-001",
  "target_cluster_id": "cluster-004",
  "user_id": "wp-user-42"
}
```

**Response:**

```json
{
  "success": true,
  "moved_count": 2,
  "source_cluster": {
    "id": "cluster-001",
    "face_count": 3,
    "updated_at": "2025-11-04T10:30:00Z"
  },
  "target_cluster": {
    "id": "cluster-004",
    "face_count": 8,
    "updated_at": "2025-11-04T10:30:00Z"
  }
}
```

**Authorization:** Requires tenant secret key in `X-Tenant-Secret` header.

**Note:** This endpoint is optional and only needed if recognition service maintains cluster state. Start with WordPress-only implementation (Phase 1).

## Observability & Audit

### WordPress Logging

**Location:** WordPress debug log (`wp-content/debug.log` when `WP_DEBUG_LOG` enabled)

**Log Entries:**

```php
// Cluster move initiated
error_log(sprintf(
    '[ClusterController] User %d moving %d faces from %s to %s',
    get_current_user_id(),
    count($face_ids),
    $source_cluster_id,
    $target_cluster_id
));

// Repository update
error_log(sprintf(
    '[UnknownFaceRepository] Updated cluster_id for %d faces to %s',
    $updated_count,
    $target_cluster_id
));

// Confirmation with augmented embeddings
error_log(sprintf(
    '[ClusteringService] Confirming cluster %s to roster %s: %d faces, %d augmented embeddings sent',
    $cluster_id,
    $roster_id,
    count($faces),
    count($augmented_records)
));
```

**Structured Logging (Future Enhancement):**

Consider using Monolog with JSON formatter for easier parsing:

```php
$logger->info('cluster_move_initiated', [
    'user_id' => get_current_user_id(),
    'face_count' => count($face_ids),
    'source_cluster' => $source_cluster_id,
    'target_cluster' => $target_cluster_id,
    'timestamp' => gmdate('c')
]);
```

### Recognition Service Logging

**Location:** Application logs (stdout/stderr in Docker, captured by systemd or Docker logs)

**Log Format:** Structured JSON with `extra` fields for filtering

```python
logger.info(
    "✅ [AUGMENT] Added augmented embedding",
    extra={
        "roster_id": self.unique_id,
        "roster_name": self.name,
        "observation_id": observation_id,
        "source": source,
        "quality_tier": quality_tier,
        "total_augmented": len(augmented_embeddings),
        "action": "embedding_added"
    }
)
```

**Metrics (Prometheus):**

```python
# In shared/metrics.py
AUGMENTED_EMBEDDINGS_TOTAL = Counter(
    'roster_augmented_embeddings_total',
    'Total augmented embeddings added to roster entries',
    ['tenant_id', 'source', 'quality_tier']
)

# Increment on augmentation
AUGMENTED_EMBEDDINGS_TOTAL.labels(
    tenant_id=tenant_id,
    source='wordpress_confirmation',
    quality_tier='high'
).inc()
```

**Grafana Dashboard Panels:**

1. **Augmented Embeddings Growth:** Line chart showing `roster_augmented_embeddings_total` over time, grouped by quality_tier.
2. **Cluster Moves Per User:** Bar chart of cluster move operations by WordPress user ID.
3. **Confirmation Rate:** Percentage of unknown faces confirmed to roster entries vs. dismissed.
4. **Progressive Learning Impact:** Compare face recognition accuracy before/after augmented embeddings added.

### Audit Trail

**WordPress Audit Table (Optional):**

For compliance or detailed tracking, create dedicated audit log:

```sql
CREATE TABLE wp_cat_cluster_audit (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    action VARCHAR(50) NOT NULL,          -- 'cluster_move', 'cluster_confirm', 'cluster_undo'
    face_ids JSON NOT NULL,               -- Array of face IDs affected
    source_cluster_id VARCHAR(255),
    target_cluster_id VARCHAR(255),
    roster_id VARCHAR(255),               -- Set during confirmation
    metadata JSON,                        -- Additional context (confidence, suggestion accepted, etc.)
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_user (user_id),
    INDEX idx_action (action),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**Query Examples:**

```sql
-- Find all cluster moves by user in last 7 days
SELECT * FROM wp_cat_cluster_audit
WHERE action = 'cluster_move'
  AND user_id = 42
  AND created_at > DATE_SUB(NOW(), INTERVAL 7 DAY)
ORDER BY created_at DESC;

-- Count confirmations per roster entry
SELECT roster_id, COUNT(*) as confirmation_count
FROM wp_cat_cluster_audit
WHERE action = 'cluster_confirm'
  AND roster_id IS NOT NULL
GROUP BY roster_id
ORDER BY confirmation_count DESC;
```

## Testing Strategy

### Unit Tests

#### WordPress (PHPUnit)

**`tests/Infrastructure/Repositories/UnknownFaceRepositoryTest.php`:**

```php
public function test_find_faces_by_ids_returns_correct_faces(): void
{
    $this->wpdb->mockResults = [
        ['id' => '10', 'cluster_id' => 'cluster-a', ...],
        ['id' => '11', 'cluster_id' => 'cluster-a', ...],
    ];

    $faces = $this->repository->findFacesByIds([10, 11]);

    $this->assertCount(2, $faces);
    $this->assertSame(10, $faces[0]->id());
    $this->assertSame('cluster-a', $faces[0]->clusterId());
}

public function test_update_cluster_membership_changes_cluster_id(): void
{
    $affected = $this->repository->updateClusterMembership(
        [10, 11],
        'cluster-new',
        42  // user_id
    );

    $this->assertSame(2, $affected);
    $this->assertStringContainsString('UPDATE wp_cat_unknown_faces', $this->wpdb->queries[0]);
    $this->assertStringContainsString('cluster-new', $this->wpdb->queries[0]);
    $this->assertStringContainsString('WHERE id IN (10, 11)', $this->wpdb->queries[0]);
}

public function test_update_cluster_membership_ignores_resolved_faces(): void
{
    // Mock: one face resolved, one unresolved
    $this->wpdb->rows_affected = 1;  // Only one updated

    $affected = $this->repository->updateClusterMembership([10, 11], 'cluster-new', 42);

    $this->assertSame(1, $affected);
    $this->assertStringContainsString('AND resolved_at IS NULL', $this->wpdb->queries[0]);
}
```

**`tests/Api/ClusterControllerTest.php`:**

```php
public function test_move_faces_requires_authentication(): void
{
    wp_set_current_user(0);  // Guest user

    $request = new WP_REST_Request('POST', '/cat/v1/unknown-clusters/move');
    $request->set_body_params([
        'face_ids' => [10],
        'source_cluster_id' => 'cluster-a',
        'target_cluster_id' => 'cluster-b',
    ]);

    $response = $this->controller->move_faces($request);

    $this->assertSame(403, $response->get_status());
}

public function test_move_faces_validates_cluster_membership(): void
{
    wp_set_current_user(1);  // Admin

    // Mock: face 10 belongs to cluster-x, not cluster-a
    $this->repository->method('findFacesByIds')->willReturn([
        $this->createFace(10, 'cluster-x'),
    ]);

    $request = new WP_REST_Request('POST', '/cat/v1/unknown-clusters/move');
    $request->set_body_params([
        'face_ids' => [10],
        'source_cluster_id' => 'cluster-a',
        'target_cluster_id' => 'cluster-b',
    ]);

    $response = $this->controller->move_faces($request);

    $this->assertSame(400, $response->get_status());
    $this->assertStringContainsString('does not belong', $response->get_data()['error']);
}
```

#### Recognition Service (pytest)

**`tests/unit/test_roster_augmented_embeddings.py` (Existing):**

Already covers augmented embedding addition, idempotency, and aggregate recomputation. No new tests needed for cluster editing (it's upstream of augmentation).

#### Frontend (Vitest)

**`js/components/workbench/UnknownPeoplePanel.test.tsx` (Existing):**

Already covers drag-and-drop payload handling. Add mutation tests:

```typescript
it("calls move mutation with correct payload", async () => {
  const handleMove = vi.fn();
  renderPanel({ onMoveFaces: handleMove });

  const cards = await screen.findAllByRole("button", {
    name: /review cluster/i,
  });
  const targetCard = cards[1];

  const dataTransfer = createDataTransfer();
  setFaceDragData(dataTransfer, {
    clusterId: "cluster-alpha",
    faceIds: ["face-1", "face-2"],
  });

  fireEvent.drop(targetCard, { dataTransfer });

  await waitFor(() => {
    expect(handleMove).toHaveBeenCalledWith({
      targetClusterId: "cluster-beta",
      sourceClusterId: "cluster-alpha",
      faceIds: ["face-1", "face-2"],
    });
  });
});
```

### Integration Tests

#### WordPress Integration

**`tests/Integration/ClusterWorkflowTest.php`:**

```php
public function test_full_workflow_move_and_confirm(): void
{
    // 1. Create unknown faces in two clusters
    $face1 = $this->createUnknownFace(100, 'cluster-a');
    $face2 = $this->createUnknownFace(101, 'cluster-a');
    $face3 = $this->createUnknownFace(102, 'cluster-b');

    $this->repository->saveUnknownFace($face1);
    $this->repository->saveUnknownFace($face2);
    $this->repository->saveUnknownFace($face3);

    // 2. Move face2 from cluster-a to cluster-b
    $this->repository->updateClusterMembership([2], 'cluster-b', 1);

    // 3. Confirm cluster-b to roster entry
    $result = $this->clusteringService->confirmCluster(
        'cluster-b',
        'person-jane',
        [2, 3]  // face IDs
    );

    // 4. Verify augmented embeddings sent to recognition service
    $this->assertSame(2, $result['augmented_embeddings_sent']);

    // 5. Verify faces marked as resolved
    $face2Resolved = $this->repository->findFaceById(2);
    $this->assertNotNull($face2Resolved->resolvedAt());
    $this->assertSame('person-jane', $face2Resolved->rosterId());
}
```

#### Recognition Service Integration

**`tests/integration/test_progressive_learning.py` (Existing):**

Already covers augmented embedding storage and aggregate recomputation. Cluster editing is transparent to recognition service.

### End-to-End Tests

#### Playwright/Cypress

**`e2e/cluster-editing.spec.ts`:**

```typescript
test("move faces between clusters via drag and drop", async ({ page }) => {
  // 1. Navigate to workbench
  await page.goto("/wp-admin/admin.php?page=context-alt-text-workbench");

  // 2. Wait for clusters to load
  await page.waitForSelector('[data-testid^="cluster-card-"]');

  // 3. Open first cluster detail
  const firstCluster = page.locator('[data-testid="cluster-card-cluster-001"]');
  await firstCluster.click();

  // 4. Select two faces
  const faceCheckboxes = page.locator(
    '.cat-face-thumbnail input[type="checkbox"]'
  );
  await faceCheckboxes.nth(0).check();
  await faceCheckboxes.nth(1).check();

  // 5. Drag to second cluster
  const secondCluster = page.locator(
    '[data-testid="cluster-card-cluster-002"]'
  );
  await page.dragAndDrop(
    '.cat-face-thumbnail[data-selected="true"]',
    '[data-testid="cluster-card-cluster-002"]'
  );

  // 6. Verify success toast
  await expect(page.locator(".cat-toast--success")).toContainText(
    "Moved 2 faces"
  );

  // 7. Verify cluster counts updated
  await expect(firstCluster).toContainText("2 faces"); // Was 4, now 2
  await expect(secondCluster).toContainText("5 faces"); // Was 3, now 5
});

test("confirm consolidated cluster to roster entry", async ({ page }) => {
  await page.goto("/wp-admin/admin.php?page=context-alt-text-workbench");

  // After moving faces, confirm to roster
  const cluster = page.locator('[data-testid="cluster-card-cluster-002"]');
  await cluster.click();

  // Select roster suggestion
  const suggestion = page.locator('[data-testid="suggestion-person-jane"]');
  await suggestion.click();

  // Confirm
  await page.locator('button:has-text("Confirm All")').click();

  // Wait for confirmation
  await expect(page.locator(".cat-toast--success")).toContainText(
    "Confirmed 5 faces"
  );

  // Verify cluster removed from list
  await expect(cluster).not.toBeVisible();
});
```

### Manual Testing Checklist

- [ ] Drag single face between clusters, verify UI updates
- [ ] Drag multiple faces, verify count badges update
- [ ] Drop on same cluster (should be ignored)
- [ ] Drop resolved faces (should show error)
- [ ] Keyboard navigation: Tab through clusters, Shift+Enter to select faces
- [ ] Screen reader: Verify ARIA announcements during drag/drop
- [ ] Undo within 30 seconds, verify revert
- [ ] Confirm consolidated cluster, verify augmented embeddings in recognition service
- [ ] Check WordPress debug.log for audit trail
- [ ] Check recognition service logs for augmentation events
- [ ] Grafana: Verify augmented_embeddings_total metric increases

## Rollout Plan

### Phase 1: WordPress Cluster Editing (MVP)

**Scope:** Enable drag-and-drop cluster consolidation entirely within WordPress, no recognition service changes.

**Deliverables:**

1. **Backend (PHP):**

   - [ ] Add `findFacesByIds()` to `UnknownFaceRepository`
   - [ ] Add `updateClusterMembership()` to `UnknownFaceRepository`
   - [ ] Add `softDeleteFace()` to `UnknownFaceRepository`
   - [ ] Create `POST /cat/v1/unknown-clusters/move` endpoint in `ClusterController`
   - [ ] Create `DELETE /cat/v1/unknown-faces/:id` endpoint in `ClusterController`
   - [ ] Add PHPUnit tests for repository and controller (including deletion)

2. **Frontend (React/TypeScript):**

   - [ ] Extend `ClusterDetailView` to support multi-select of face thumbnails
   - [ ] Implement face thumbnail dragging (set `FaceDragPayload` on drag start)
   - [ ] Add hover overlay with "Delete" and "View Original" buttons on thumbnails
   - [ ] Implement double-click handler to view original media (with tooltip hint)
   - [ ] Create `useMoveFaces` mutation hook (TanStack Query)
   - [ ] Create `useDeleteFace` mutation hook with confirmation dialog
   - [ ] Add optimistic updates to cluster cache (move and delete)
   - [ ] Add success/error toast notifications with undo support
   - [ ] Add Vitest tests for mutation logic (move, delete, view original)

3. **Testing:**

   - [ ] Unit tests: Repository, controller, React hooks
   - [ ] Integration tests: Full workflow (move + confirm)
   - [ ] E2E tests: Playwright scenarios for drag/drop

4. **Documentation:**
   - [ ] Update Workbench user guide with cluster editing instructions
   - [ ] Add troubleshooting section to docs
   - [ ] Document audit logging queries

**Timeline:** 2-3 days

**Success Criteria:**

- Users can drag faces between clusters
- Users can delete irrelevant faces with confirmation
- Users can navigate to original media from thumbnails (hover button + double-click)
- Cluster counts update correctly after moves and deletions
- Confirmation flow works with consolidated clusters
- Augmented embeddings sent to recognition service on confirmation
- Deleted faces do not appear in cluster listings
- Audit log captures all operations (move, delete, confirm)

### Phase 2: Enhanced Observability (Iteration 1)

**Scope:** Add structured logging and metrics for cluster operations.

**Deliverables:**

1. **Metrics:**

   - [ ] Add Prometheus counter for cluster moves: `cat_cluster_moves_total{user_id, action}`
   - [ ] Add Prometheus counter for augmented embeddings: `cat_augmented_embeddings_total{source, quality_tier}`
   - [ ] Create Grafana dashboard: "Face Clustering Operations"

2. **Audit Trail:**

   - [ ] Create `wp_cat_cluster_audit` table
   - [ ] Log all cluster moves with user ID, timestamps, face IDs
   - [ ] Add admin UI to view recent cluster activity

3. **Structured Logging:**
   - [ ] Integrate Monolog with JSON formatter
   - [ ] Add structured context to all cluster operations
   - [ ] Configure log shipping to centralized service (optional)

**Timeline:** 1-2 days

**Success Criteria:**

- Grafana dashboard shows cluster move trends
- Audit table captures all user actions
- Logs are queryable for debugging and compliance

### Phase 3: Recognition Service Sync (Optional - Phase 2 from earlier)

**Scope:** Add `POST /api/v0/clusters/reassign` endpoint for cluster state synchronization.

**Trigger:** Only if:

- Multi-tenant dashboard needs cross-site cluster visibility
- Advanced analytics require centralized cluster state
- WebSocket/real-time sync needed for collaborative editing

**Deliverables:**

1. **Database:**

   - [ ] Create `unknown_face_clusters` table in PostgreSQL
   - [ ] Add indexes on `tenant_id` and `cluster_id`
   - [ ] Add Alembic migration

2. **API:**

   - [ ] Implement `POST /api/v0/clusters/reassign` endpoint
   - [ ] Add authentication via tenant secret
   - [ ] Return updated cluster summaries

3. **WordPress Integration:**

   - [ ] Call recognition service after WordPress cluster move
   - [ ] Handle sync failures gracefully (log, retry)
   - [ ] Add fallback: continue working if recognition service unavailable

4. **Testing:**
   - [ ] Integration tests: WordPress → Recognition sync
   - [ ] Test failure scenarios (network timeout, invalid tenant)

**Timeline:** 2-3 days

**Success Criteria:**

- Recognition service maintains accurate cluster state
- WordPress continues working if sync fails
- Cluster statistics consistent across systems

### Phase 4: Advanced Features (Future)

**Potential Enhancements:**

1. **Bulk Operations:**

   - Select multiple faces across different clusters
   - Batch move to single target cluster
   - Batch delete (select 10 faces, delete all at once)
   - Keyboard shortcut: Ctrl+A to select all in cluster, Del key to delete selected

2. **Cluster Suggestions:**

   - ML model suggests which clusters should be merged
   - Show similarity score between clusters
   - One-click merge suggested clusters

3. **Undo History:**

   - Maintain undo stack (last 10 operations)
   - Persist to `localStorage` for session continuity
   - Admin UI to view and replay undo history

4. **Collaborative Editing:**

   - WebSocket connection for real-time updates
   - Show other users' active cluster edits
   - Conflict resolution for simultaneous moves

5. **Quality Tier Assignment:**
   - Let users mark high-quality faces during move
   - Affects augmented embedding quality_tier
   - Provides stronger signal for progressive learning

**Prioritization:** Based on user feedback and analytics from Phase 1/2.

## Thumbnail Storage Considerations

- **Current approach**: recognition service returns base64 thumbnails in API responses. No persistent storage beyond transient JSON.
- **Pros**:
  - Zero additional DB writes; no cache invalidation.
  - Thumbnails always match latest face crop from insightface detection.
  - WordPress backend doesn’t need to manage files or media entries.
- **Cons**:
  - Slightly heavier payloads (2–5 KB per thumbnail). Acceptable for cluster grids with lazy rendering.
  - Base64 cannot be reused across sessions without re-fetching.

Given the drag/drop workflow still displays the same immediate cluster payload, keeping thumbnails inline via base64 is efficient enough. Persisting in WP DB/filesystem would add complexity (ACL, cleanup, storage costs) without a clear benefit. **Recommendation**: stay with base64 delivery; cache on the front end if needed (e.g., memoize in Redux store) and generate new thumbnails when recognition service confirms cluster edits.

## Risks & Mitigations

- **Concurrent edits**: two admins drag the same face simultaneously. Mitigate by using optimistic UI + backend conflict detection (e.g., check `updated_at`).
- **API latency**: sequential moves may spike load; batch requests if user selects multiple thumbnails.
- **Accessibility**: ensure keyboard users can reassign faces; use proper ARIA roles.
- **Undo complexity**: limit undo window and document behaviour.

## Open Questions

### Architecture & Design

1. **Multi-Select Drag/Drop:** Should users be able to select multiple faces (via checkbox/toggle) and drag them as a batch? Or keep single-face dragging for simplicity?

   - **Recommendation:** Implement multi-select in Phase 1. UX is significantly better for consolidating mis-clustered faces.

2. **Version History:** Do we need to track full history of cluster membership changes per face?

   - **Recommendation:** Phase 1 uses simple audit logging (user ID, timestamp, source/target cluster). Full version history in Phase 4 if compliance requires it.

3. **WebSocket Sync:** Should recognition service emit events to notify WordPress of cluster state changes?

   - **Recommendation:** Not needed for Phase 1. WordPress is source of truth for clusters. Add in Phase 3 only if multi-site dashboards require real-time sync.

4. **Large Cluster Pagination:** How to handle clusters with 500+ faces without slowing UI?
   - **Recommendation:** Implement virtual scrolling (react-window) in ClusterDetailView. Load faces in pages of 50. Show "Load More" button for clusters >100 faces.

### Implementation Details

5. **Optimistic Update Granularity:** Should UI immediately remove face from source cluster, or wait for API success?

   - **Recommendation:** Optimistic update for better UX. Store snapshot in TanStack Query's `onMutate`, revert on error.

6. **Undo Time Window:** How long should users have to undo a cluster move?

   - **Recommendation:** 30 seconds or last 5 operations, whichever comes first. Store in React state (session-only, no persistence).

7. **Batch Move API:** Should `POST /cat/v1/unknown-clusters/move` accept multiple operations in single request?

   - **Recommendation:** Phase 1 supports single move (one source→target). Add batch endpoint in Phase 2 if analytics show users frequently move 10+ faces sequentially.

8. **Quality Tier Assignment:** Should users be able to mark faces as "high quality" during move/confirmation?
   - **Recommendation:** Not in Phase 1. Confirmation workflow defaults to `quality_tier='high'` for all manually confirmed faces. Add UI toggle in Phase 4 if needed.

### User Experience

9. **Face Deletion Confirmation:** Require explicit confirmation dialog, or allow quick delete with undo?

   - **Recommendation:** Confirmation dialog for destructive action. Dialog text: "Remove this face? The original image will not be affected." Buttons: "Cancel" (default focus) | "Remove Face" (danger style). Undo available in toast for 15 seconds after deletion.

10. **View Original Media UX:** Hover button vs. double-click vs. context menu?

    - **Recommendation:** Implement both hover button (accessibility) AND double-click shortcut (power users). Hover button shows external link icon with "View original image" tooltip. Double-click opens same URL. Add educational tooltip on first use: "Tip: Double-click any face to view the original image."

11. **Navigate to Media Library vs. Modal:** Open WordPress Media Library in new tab, or show attachment details in modal?

    - **Recommendation:** New tab for Phase 1 (`/wp-admin/upload.php?item={attachmentId}`). Simpler implementation, leverages existing WP Media Library UI. Phase 4 can add inline modal with attachment preview, metadata, and "Open in Media Library" button for users who prefer staying in Workbench.

12. **Clear All Unknown Faces:** Is bulk clearing a best practice for UX decluttering?
    - **Analysis:**
      - ✅ **Pro:** Essential for event photography (hundreds of strangers), stock photos, crowded scenes. Without it, UI becomes unusable.
      - ✅ **Pro:** Reduces cognitive load—curator can focus on identifying known people, then dismiss rest in one action.
      - ✅ **Pro:** Common pattern in photo management (Google Photos, Apple Photos have "Hide all" / "Not a person").
      - ⚠️ **Con:** Risk of accidental bulk deletion. Mitigate with strong confirmation dialog.
      - ⚠️ **Con:** Cannot undo. Mitigate with soft delete (`__cleared__` status allows admin recovery).
      - ⚠️ **Con:** Might encourage lazy curation. Mitigate with metrics tracking (alert if cleared_count > confirmed_count).
    - **Recommendation:** ✅ **Implement in Phase 1 with safeguards:**
      1. Confirmation dialog: "You are about to dismiss 127 unknown faces. They will not contribute to face recognition learning. Continue?"
      2. Show impact: "20 clusters will be cleared" (not just face count).
      3. Disable button if no clusters (prevent misclicks).
      4. Badge shows count: "Clear All (127)" for transparency.
      5. Success message: "Cleared 127 faces. Admin can recover via database if needed."
      6. Track metric: `clear_all_usage_rate` = cleared ÷ (confirmed + cleared). Alert if >80% (suggests over-aggressive clearing).

### Progressive Learning Strategy

9. **Augmented Embedding Weight:** How much should manually confirmed faces influence aggregate embeddings vs. reference images?

   - **Current:** Equal weight. Aggregate = average(reference + augmented).
   - **Alternative:** Weight by quality_tier (high=2.0, medium=1.0, low=0.5).
   - **Recommendation:** Start with equal weight. Evaluate after 6 months of production data. Adjust if manually confirmed faces show higher variance than references.

10. **Cluster Consolidation vs. Individual Face Confirmation:** Should users confirm entire consolidated clusters, or select individual faces from merged clusters?
    - **Recommendation:** Phase 1 confirms entire clusters (existing workflow). Phase 4 adds individual face selection within cluster confirmation modal.

### Data Management

13. **Cluster ID Stability:** When faces are moved between clusters, should cluster IDs change?

    - **Current:** Cluster IDs are deterministic (hash of first face's embedding or database ID). Moving faces doesn't change cluster ID.
    - **Recommendation:** Keep current approach. Cluster ID represents "original detection group," not "current membership."

14. **Resolved Face Cleanup:** When should resolved faces be deleted from `wp_cat_unknown_faces`?

    - **Recommendation:** Never delete (audit trail). Add `archived_at` column and archive resolved faces >90 days old. Admin UI to trigger cleanup.

15. **Cleared vs. Deleted Distinction:** Should "cleared" faces be treated differently from "deleted" faces in reports?
    - **Recommendation:** Yes. Separate metrics:
      - `__deleted__`: Individual curation decision (bad detection, not a face, obvious error).
      - `__cleared__`: Bulk cleanup decision (not valuable but not necessarily wrong).
      - Reports: "10 faces individually deleted, 127 bulk cleared" gives insight into curation patterns.

### Answers Summary

| Question                 | Phase 1 Answer                        | Future Consideration                        |
| ------------------------ | ------------------------------------- | ------------------------------------------- |
| Multi-select drag/drop   | ✅ Yes, implement                     | -                                           |
| Version history          | ❌ No, simple logging                 | Phase 4: Full audit trail                   |
| WebSocket sync           | ❌ No                                 | Phase 3: If multi-tenant dashboard needs it |
| Large cluster pagination | ✅ Yes, virtual scrolling             | -                                           |
| Optimistic updates       | ✅ Yes, with rollback                 | -                                           |
| Undo time window         | 30 seconds / 5 ops                    | Phase 4: Persist to localStorage            |
| Batch move API           | ❌ No                                 | Phase 2: If analytics show need             |
| Quality tier UI          | ❌ No                                 | Phase 4: Advanced feature                   |
| Embedding weights        | Equal weight                          | Evaluate after 6 months                     |
| Cluster vs. face confirm | Entire clusters                       | Phase 4: Individual face selection          |
| Cluster ID stability     | Keep deterministic                    | -                                           |
| Resolved face cleanup    | Archive after 90 days                 | Admin UI in Phase 2                         |
| **Face deletion UX**     | **✅ Confirmation dialog + 15s undo** | -                                           |
| **View original media**  | **✅ Hover button + double-click**    | Phase 4: Inline modal with preview          |
| **Navigate behavior**    | **✅ New tab to Media Library**       | Phase 4: Optional modal with metadata       |
| **Clear all unknown**    | **✅ Yes, with strong confirmation**  | Track usage metrics to prevent abuse        |

---

## Summary

This plan delivers a **WordPress-first cluster editing workflow** that improves augmented embeddings through manual curation. The implementation prioritizes **simplicity, accessibility, and auditability** while maintaining compatibility with existing face detection and confirmation flows.

**Key Design Decisions:**

1. **WordPress as Source of Truth:** Cluster state managed in `wp_cat_unknown_faces` table. Recognition service stores only augmented embeddings (not cluster metadata).
2. **Progressive Learning First:** The primary goal is improving face recognition accuracy via augmented embeddings, not just UI convenience.
3. **Soft Delete Strategy:** Faces marked with `roster_id='__deleted__'` instead of physical deletion. Maintains audit trail, enables recovery, simplifies queries.
4. **Dual Navigation Pattern:** Hover button (accessibility) + double-click shortcut (power users) to view original media. Opens WordPress Media Library in new tab.
5. **Phased Rollout:** MVP (Phase 1) delivers core drag-and-drop, deletion, and navigation. Advanced features (batch operations, real-time sync, quality tiers) deferred to later phases based on user feedback.
6. **Base64 Thumbnails:** Continue with inline delivery. Simple, portable, and efficient for expected workload (500-1000 faces).
7. **Accessibility:** Keyboard-driven workflow, ARIA announcements, proper focus management, and visible hover buttons ensure all users can curate clusters.

**Success Metrics:**

- **Adoption Rate:** % of unknown face clusters that are consolidated before confirmation
- **Deletion Rate:** % of detected faces dismissed as irrelevant (target: 5-15% indicates good cleanup without over-aggressive filtering)
- **Clear All Usage:** % of sessions that use "Clear All" (target: 10-30% for event photography workflows)
- **Cleared vs. Confirmed Ratio:** cleared_count ÷ (confirmed_count + cleared_count). Alert if >80% (suggests lazy curation).
- **Navigation Usage:** % of users who click "View Original" to verify context (indicates feature discoverability)
- **Augmented Embedding Growth:** Total augmented embeddings added per month
- **Recognition Accuracy:** Precision/recall improvement after 3 months of progressive learning
- **User Satisfaction:** NPS score for face clustering workflow
- **Performance:** P95 latency for cluster move/delete/clear operations <200ms (clear all <2s for 500 faces)

**Next Steps:**

1. Review plan with team (frontend, backend, UX)
2. Break Phase 1 deliverables into Jira tickets
3. Set up metrics dashboard (Grafana) for baseline measurement
4. Schedule kickoff meeting to align on timelines
