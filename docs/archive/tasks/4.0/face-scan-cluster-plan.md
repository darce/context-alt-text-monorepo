# Recognition Scan + Clustering Plan (Prototype Description Service → Workbench)

> Goal: Enable `WorkbenchPage.tsx` to trigger a real recognition pipeline that uploads media IDs, extracts embeddings in the prototype description service, clusters them via pgvector-backed PostgreSQL tables, and sends clusters back to WordPress for review.

## 1. Backend Foundation (apps/prototype-description-service)

1. **Project structure parity with archived service**
   - Mirror the `recognition/`, `scene/`, `roster/` layering pattern from `apps/archived-recognition-service`.
   - Add `recognition/application/scan_faces.py`, `recognition/domain/entities.py`, `recognition/interface_adapters/http/recognition_router.py`.
2. **Database & pgvector**
   - Add `db/` module with SQLAlchemy models:
     - `media_faces` (id, media_id, embedding VECTOR(1024), bbox, created_at)
     - `face_clusters` (id, label, created_at)
     - `cluster_members` (cluster_id, face_id)
   - Provide Alembic migrations enabling `CREATE EXTENSION IF NOT EXISTS vector;`.
   - Expose env vars in `pyproject.toml`/`.env` (POSTGRES_DSN, PGVECTOR_DIM).
3. **Embedding pipeline**
   - Port the archived InsightFace adapters (identity + context recognition) into `recognition/infrastructure/embedding_provider.py`.
   - Define `FaceScanService` use case: fetch source image (via signed URL or WP REST), detect faces, compute embeddings, write to `media_faces`.
4. **Clustering**
   - Implement `FaceClusterService` that
     - pulls unclustered embeddings,
     - runs similarity search (pgvector `cosine_distance`),
     - groups into clusters using e.g. HNSW or hierarchical agg.
  - Provide `/recognition/cluster` REST endpoint returning cluster summaries (id, representative thumbnail, member IDs).
5. **API contracts**
   - `POST /recognition/analyze`: `{ mediaId: number, sourceUrl: string }` → returns job id.
   - `POST /recognition/cluster`: triggers clustering run; returns cluster stats.
   - `GET /recognition/clusters`: list clusters for a given WP site.
   - Add JSON schemas to `docs/architecture/contracts/workbench/`.
   - Make every table multi-tenant by adding `tenant_id` (WordPress site/install identifier) and require all queries to scope by tenant.
6. **Queue/async execution**
   - For now use synchronous endpoints (scan immediately) with TODO markers for Celery/RQ integration once the pipeline stabilizes.

## 2. WordPress Integration (apps/prototype-wp-alt-context)

1. **REST client config**
   - Extend `AltContextAdmin` localization to include `recognitionBaseUrl`, API key/nonce for prototype service.
   - Add nonce handshake if prototype service needs WP tokens (e.g., `X-AltContext-Signature` header).
2. **Admin SPA**
   - In `WorkbenchPage.tsx`, when users click “Analyze selected media”:
     - POST to `/recognition/analyze` with WordPress attachment metadata (ID + secure download URL).
     - Show job state (pending/running/done) in the Batch tab.
   - After the recognition job completes, call `/recognition/clusters` to display clusters inside the future Roster “Clusters” tab (drag/drop UI).
   - Store cluster assignments back via WP REST (`POST /acx/v1/roster/clusters`).
3. **WordPress REST endpoints**
   - Add `POST /workbench/recognition/analyze` proxy (server-to-server call to prototype service, handles secrets).
   - Add `GET /workbench/recognition/clusters` returning cached clusters from prototype service.
4. **Security**
   - Use WordPress options to store prototype service credentials (API key, base URL).
   - Ensure requests to prototype service include server-side auth; browser only calls WP endpoints.

## 3. Roster & Cluster UX

1. **RosterPage.tsx enhancements**
   - Entries tab: list known identities (name, tags, linked clusters).
  - Clusters tab: display grid of recognition clusters. Each card shows up to four cropped faces (add ~1% padding around the bbox) pulled directly from the recognition thumbnails so reviewers can compare expressions at a glance.
  - Drag/drop editing of clusters happens inside `RosterPage.tsx`, so reviewers can consolidate stray detections or remove false positives before committing clusters to identities (the UI should reuse Radix DnD or react-beautiful-dnd patterns for this interaction).
  - Provide a deep link/button inside the Workbench flow that opens the Roster → Clusters tab (e.g., `/wp-admin/admin.php?page=alt-context-roster&tab=clusters`) so users can jump directly from a completed recognition job into the editing surface.
   - Selecting a cluster opens a drawer anchored to the right that lists every member face at a normalized thumbnail size (consistent canvas, e.g., 128×128) so scale doesn’t bias review. Each thumbnail links back to the originating media item (attachment edit screen) for deeper context.
   - Drag/drop between clusters (Radix DnD or react-beautiful-dnd) remains a stretch goal.
   - Buttons:
     - “Rescan media with sensitive settings” → calls `/recognition/analyze` with `sensitivity=high`.
     - “Commit cluster to roster entry” → maps cluster → identity.
2. **State flow**
   - Workbench Select tab chooses media → Batch tab triggers scan → Roster Clusters tab reviews output → Confirm tab uses roster identities to enrich alt text.

## 4. Implementation Phases

| Phase | Description | Key PR deliverables |
|-------|-------------|---------------------|
| 1 | Database + models + pgvector setup | Alembic migration, SQLAlchemy models (with `tenant_id`), Docker compose updates |
| 2 | Recognition REST endpoint (one attachment) | `FaceScanService`, `/recognition/analyze`, integration tests |
| 3 | Clustering service + `/recognition/clusters` | vector queries, cluster DTOs, contract docs |
| 4 | WP REST proxy endpoints | `acx/v1/workbench/recognition/analyze`, `acx/v1/workbench/recognition/clusters` |
| 5 | Workbench Batch tab wiring | React Query mutation for scans, polling for status |
| 6 | Roster Clusters UI | Tabs, cluster board, drag/drop placeholders |
| 7 | Apply clusters to alt text | Confirm tab uses roster data when calling scene description |

## 5. Open Questions / Risks

- Do we need media blobs pulled from WP or are CDN URLs sufficient for the prototype service?  
  → Prototype must fetch the exact image bytes that production will see. Use the same signed/CDN URL that WordPress serves in production so the embedding pipeline matches real conditions; no lossy thumbnails or mock blobs.

- How to handle large batches (100+ attachments) — synchronous vs background job?  
  → Industry standard is to offload heavy face-scan jobs to a background worker queue (Celery/RQ/Kafka). Even when implemented later, the UI must show accurate progress: enqueue → job id → polling endpoint (percent complete, errors). For now we can keep synchronous scans for tiny batches, but design the API with job IDs so asynchronous handling is trivial to add.

- Need a migration strategy if pgvector dimension changes (depends on embedding model choice).  
  → We’re standardizing on InsightFace w600k embeddings (the same for prototype and production). Cross-model embeddings aren’t interchangeable, so switching models requires re-scanning every face to get new vectors. Document this clearly and version embeddings by model so we can invalidate older rows when needed.

- Roster permissions: ensure only privileged admins can edit clusters/roster.  
  → Nonces protect against CSRF but not capability checks. Expose the roster/cluster REST endpoints only to `manage_options` admins (server-side `current_user_can`). The SPA should only render the Roster page when the localized payload indicates the user has that capability; otherwise hide the submenu entirely.
