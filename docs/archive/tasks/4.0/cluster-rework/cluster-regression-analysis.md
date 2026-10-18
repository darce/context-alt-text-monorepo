# Cluster Regression Analysis — Workbench 4.0

> Author: Codex  
> Date: 2025‑11‑18  
> Status: Investigation log & remediation plan

## 1. Context

- **Archived implementation** (`apps/archived-recognition-service/recognition_core`):
  - Stored **every detection embedding** and clustered them offline via cosine similarity.
  - `cluster_unknowns.py` pulled *all* unassigned faces per tenant, ran hierarchical / incremental clustering, and persisted the cluster assignments so a single label applied across the media library.
  - `suggest.py` provided “people you might know” semantics by comparing new embeddings to existing cluster centroids; this is what powered cross‑media propagation.

- **Prototype 4.0 implementation** (`apps/prototype-description-service`):
  - `IdentityScanService` saves raw embeddings per media item but never reuses them for future scans.
  - `IdentityClusteringService` only clusters **within the last scan batch** (whatever `cluster_identities()` sees in `identity_scan_jobs.media_ids`). We do not fetch the full unclustered corpus nor do we compute similarities against prior clusters.
  - The SPA shows cluster IDs, but each scan ends up creating disjoint “cluster-xxxxxxx” groups instead of reusing the same label (Muted Yarrow being split across 7 clusters is a symptom).

## 2. Root Cause

1. **No persistent centroid / similarity search**  
   - The new service never queries existing clusters when deciding where to put a fresh embedding. `_find_similar_identities()` only compares the detections *within the current unclustered set*. That means scan A clusters Muted’s first photo, but scan B has zero knowledge of scan A’s embeddings.

2. **Clustering scope limited to current batch**  
   - `cluster_identities()` filters on `~membership_exists` for the current tenant, but we only call it immediately after `scan_identities()` with the latest job’s IDs. Prior jobs already have a membership, so no clustering rerun will ever add new faces to earlier clusters.

3. **Missing “suggest/merge” pathway**  
   - Archived service used `face_utils.find_similar_faces()` to return nearest neighbors and automatically merge or suggest merges. The prototype lacks any merge-by-similarity logic; manual merging simply renames whichever auto label was produced that scan.

4. **No background job**  
   - Previously, cron / task queues reran clustering periodically. Now everything rides on the inline call from `/recognition/analyze`, so once RLS rejects a cluster insert (like earlier errors), scanning halts and the UI never gets a cluster ID.

## 3. Required Capabilities

- **Global embedding index per tenant** for all media identities (pgvector works; we already store embeddings).
- **Incremental clustering** that:
  - For each new embedding, searches existing clusters and attaches to the closest one above a similarity threshold.
  - Only creates a new cluster when no existing centroid matches.
- **Merge suggestions / auto-merge** based on centroid drift so operators can keep clusters clean across time.
- **Background process** so clustering runs even if a scan fails mid-way, avoiding UI-blocking errors.

## 4. Remediation Plan

1. **Restore archived clustering semantics**
   - Port `recognition_core/domain/entities.py` logic (especially centroid updates and similarity scoring) into the new `IdentityClusteringService`.
   - Replace `_get_unclustered_identities()` + `_find_similar_identities()` with:
     ```python
     SELECT id, embedding FROM media_identities WHERE tenant_id=:tenant
     ```
     compute cosine similarity vs existing cluster centroids, and assign accordingly.

2. **Add centroid table / fields**
   - Extend `identity_clusters` with `centroid vector` + `member_embeddings_count`.
   - Update centroid incrementally: `new_centroid = normalize((old_centroid * count + new_embedding) / (count + 1))`.

3. **Reintroduce suggestion endpoint**
   - `/recognition/clusters/suggest` similar to archived `suggest.py` so the roster drawer can fetch “likely matches”.

4. **Background worker**
   - Run `cluster_identities()` via a Celery/Arq task or cron triggered by `/recognition/analyze` but decoupled from the HTTP response, preventing 500s from RLS hiccups.

5. **Testing**
   - Unit tests for “add embedding, cluster attaches to existing centroid”.
   - Integration test that scans multiple batches and verifies the same person yields a single cluster ID.

## 5. Next Steps

1. Design the new schema changes (centroid column, index maintenance) → author migration under `apps/prototype-description-service/db/migrations/`.
2. Port the archived clustering utilities (face utils, similarity thresholds) into the prototype service.
3. Implement background job trigger (FastAPI → task queue).
4. Update Workbench + Roster UI to consume the improved suggestion/merge data.
5. Write regression tests (Python + Playwright/Cypress) proving cross-media clustering works.

_Document created per request to capture the failures and plan a rewrite for 4.0._
