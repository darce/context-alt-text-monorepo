# Face Cluster Load Optimization

**Status**: [PLANNED]  
**Epic**: Workbench Performance & Scalability  
**Priority**: HIGH  
**Complexity**: Medium (3-5 day vertical slice)

## Executive Summary

Current implementation loads all face data (thumbnails, embeddings, bounding boxes) for every request to `/cat/v1/clusters`, causing 60+ MB payloads and multi-second response times when users have hundreds of detected faces. This optimization introduces lightweight cluster summaries with lazy-loaded detail pages, reducing initial payload to <100 KB and enabling smooth drag-and-drop editing even with thousands of faces.

## Key Issues

- ClusterController::listClusters re-runs full clustering and fetches every unresolved face (payload incl. thumbnails/embeddings) for each request, so a 10 k limit still loads >60 MB of JSON before pagination kicks in (apps/wp-context-alt-text/src/Recognition/ClusterController.php (line 63) → apps/wp-context-alt-text/src/Recognition/ClusterController.php (line 88)).

- ClusteringService::clusterUnknownFaces always materialises the whole face list and serialises it, even when we only need a count and a preview (apps/wp-context-alt-text/src/Domain/Clustering/ClusteringService.php (line 60) → apps/wp-context-alt-text/src/Domain/Clustering/ClusteringService.php (line 88)).

- UnknownFaceRepository::findUnresolvedFaces pulls the complete row (bbox JSON, 512-dim embedding JSON, base64 thumbnail) for each face, which is unnecessary for list view summaries (apps/wp-context-alt-text/src/Infrastructure/Repositories/UnknownFaceRepository.php (line 93) → apps/wp-context-alt-text/src/Infrastructure/Repositories/UnknownFaceRepository.php (line 114)).

- Base64 thumbnails are embedded back into every list response via CachedFaceThumbnailProvider, so the browser downloads thousands of inline JPEGs even though only a handful are visible (apps/wp-context-alt-text/src/Recognition/CachedFaceThumbnailProvider.php (line 12) → apps/wp-context-alt-text/src/Recognition/CachedFaceThumbnailProvider.php (line 35)).

## Recommended Flow

- Add a lightweight read model in the repository (e.g., findClusterSummaries(int $limit, int $offset)) that returns cluster id, face count, created/updated timestamps, and a GROUP_CONCAT of up to four preview face IDs; reuse findFacesByIds to hydrate just those previews.

- Change ClusterController::listClusters to call the new summary method instead of clusterUnknownFaces, returning { id, face_count, preview_faces[], sample_face, created_at, updated_at }; keep previews at four faces to match the card UI.
  Keep ClusteringService::clusterUnknownFaces available for background jobs/manual refresh, but restrict it to fetching only faces with cluster_id IS NULL so we re-cluster incrementally rather than on every page load.

- Extend GET /cat/v1/clusters/{id} to paginate faces (page, per_page) so the detail drawer can lazily fetch the remainder (needed for Scenario B drag‑and‑drop); return total count plus a page of faces with thumbnails and bounding boxes.

- Wire the drag-and-drop move endpoint to request additional pages on demand (TanStack Query infinite scroll fits the plan in docs/tasks/face-cluster-editing-plan.md), so operators can drag any face after it has been fetched into the detail grid.

- Cache cluster summaries for a short TTL (e.g., 30 s WordPress transient keyed by query params) so repeated navigation in the workbench doesn’t thrash MySQL; invalidate the cache on move/delete/confirm mutations.

## Thumbnails & Persistence

- Continue storing raw base64 in wp_cat_unknown_faces.thumbnail; during list fetch only transfer thumbnails for the four preview faces and for whatever page is being viewed in the detail drawer, converting to data URIs in CachedFaceThumbnailProvider.

- When drag-and-drop moves a face, don’t regenerate thumbnails; the file is keyed by face id, so the preview remains valid as the face changes clusters.

## Lazy-Loading Variants

Option A (above) - do not implement this option; it's here for archival purposes. keeps cards static and loads the full cluster on detail open; optimistic updates plus mutation invalidation handle move/delete flows cleanly.

Option B that must be implemented: streams faces with server-driven pagination (Link headers) so the UI can prefetch subsequent pages while the operator reviews the first page—useful when clusters hold hundreds of faces.

Option C (for very large clusters) - do not implement this option; it's here for archival purposes. adds a GET /cat/v1/clusters/{id}/faces?after= cursor tied to detected_at, enabling virtualised scrolling without repeated OFFSET scans.

## Goals

- Keep the Unknown People workbench responsive even with thousands of faces.
- Support the drag-and-drop flow described in `docs/tasks/face-cluster-editing-plan.md`.
- Avoid storing generated thumbnails on disk; keep them in the `wp_cat_unknown_faces` table.

## Option Review

### Option A – Load four previews, fetch full cluster on expand

- **Pros:** Simplest server changes; matches current REST contract.
- **Cons:** Still transfers the entire cluster payload (including thumbnails) as soon as a drawer is opened. For medium/large clusters the drawer stalls while the bulk response streams in, which makes drag-and-drop awkward and encourages premature prefetching logic in the UI.
- **Scale Fit:** Acceptable for tens of faces per cluster, but becomes clunky beyond ~100 faces.

### Option B – Paged detail endpoint with optimistic prefetch

- **Flow:** `/cat/v1/clusters` returns summaries with up to four preview faces. `GET /cat/v1/clusters/{id}?page=…` delivers `per_page` slices plus total count. The UI requests page 1 on expand, renders immediately, and prefetches page 2 in the background via TanStack Query.
- **Pros:** Smooth UX for small, medium, and large clusters; pagination is transparent to drag-and-drop because faces are fetched before interaction. Keeps payloads <100 KB per request while still returning thumbnails for visible faces.
- **Cons:** Requires controller + repository updates and front-end pagination logic, but the complexity is modest.
- **Scale Fit:** Works well from dozens up to many hundreds of faces; latency stays predictable because queries rely on OFFSET/LIMIT and preview face IDs are resolved through existing repository helpers.

### Option C – Cursor-based streaming (`after` param)

- **Flow:** Detail endpoint returns `next_cursor` keyed to `detected_at` (or database id). UI requests additional slices as the operator scrolls.
- **Pros:** Extremely scalable for multi-thousand-face clusters; avoids deep OFFSET scans.
- **Cons:** More stateful protocol (cursor tracking, cache invalidation, error recovery). Overkill for the near-term data volumes and adds friction to drag-and-drop because faces from earlier pages may need reloading when the user drags them back into view.
- **Scale Fit:** Technically works for small and medium clusters, but the extra round-trips and cursor bookkeeping give no benefit there. Recommend reserving this for a future iteration if OFFSET/LIMIT proves too slow.

## Recommendation

1. Adopt **Option B** as the primary lazy-loading strategy. It keeps the UI fluid, satisfies drag-and-drop requirements, and keeps the server contract straightforward.
2. Retain the database-backed thumbnail column. Return thumbnails only for the preview faces in the summary route and for whatever page is requested from the detail route. No changes to the uploads directory are required.
3. Monitor cluster sizes. If real datasets approach the point where OFFSET/LIMIT causes slow queries, introduce an opt-in cursor parameter (Option C) later without breaking the Option-B contract.

## Next Steps

- Implement repository methods for cluster summaries and paged face retrieval.
- Update `ClusterController` to serve the new summary + paged detail endpoints.
- Adjust the workbench React code to consume the paginated API, prefetch page 2 on expand, and request additional pages during drag-and-drop when needed.
- Add integration tests covering pagination parameters and preview-face limits.

## Follow-up Clean-Up

- **Drop `FETCH_LIMIT` from `ClusteringService::loadFaces()`.** Once the controller stops calling `clusterUnknownFaces()` for UI loads, pulling an arbitrary 10 000 records becomes a liability. Replace this with targeted queries (e.g., streaming unclustered ids in batches when background jobs need them) so reclustering can operate incrementally without hard caps.
- **Retire the `$limit` argument on `UnknownFaceRepository::findUnresolvedFaces()`.** Introduce explicit read-model methods instead (`findClusterSummaries()`, `findFacesPage(clusterId, page, perPage)`, `streamUnclusteredFaces(batchSize, cursor)`). This keeps list views lean while still allowing maintenance jobs to page through the backlog.
- Implement the summary query + controller changes, then update the React workbench to consume preview_faces and new detail pagination.
- Add a background “cluster refresh” task (WP cron or CLI) that calls clusterUnknownFaces() for only unclustered records to keep assignments fresh without blocking UI.
- Keep thumbnails in DB.
