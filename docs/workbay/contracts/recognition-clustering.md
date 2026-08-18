---
title: Recognition Service HTTP API
status: draft
boundary_owner: backend
description: FastAPI endpoints backing recognition analysis, clustering, and suggestions.
---

Base path: `/recognition`

## Authentication and tenant scoping

- Auth header defaults to `Authorization: Bearer <api-key>`.
- Header name can be changed with `RECOGNITION_API_KEY_HEADER` (the WP plugin uses `X-API-Key`).
- Read endpoints require `X-Tenant-ID` header or `tenant_id` query param.
- Write endpoints include `tenant_id` in the JSON payload and are validated
  against the API key tenant claim when auth is enabled.

Tenant identifiers must be UUID-formatted strings (32 hex or hyphenated UUID).

## Stability and wire-compatibility notes

PDS-26 (`pds-pipeline-stability-26`) hardens the recognition pipeline with
application-boundary adapter timeouts, shared circuit-breaker behavior, and an
explicit DB -> adapter -> DB phase split documented in
`docs/adrs/ADR-008-external-adapter-stability-pattern.md`.

Contract impact:

- No HTTP request or response envelope changed for `/recognition/analyze`,
  `/recognition/analyze/multipart`, `/recognition/jobs/{job_id}`, or the
  clustering routes covered by this document.
- `JobStatusResponse.status` serializes the lowercase `JobStatus` wire
  vocabulary: `pending`, `running`, `completed`, `completed_with_errors`,
  `rejected`, `failed`. `completed_with_errors` (partial failure) and `rejected`
  (capability-unavailable intake rejection) are terminal states; see
  [Scan job terminal states](#scan-job-terminal-states) for the finalize rules.
- `JobStatusResponse.phase` continues to serialize the existing lowercase
  `JobPhase` vocabulary when present; the enum adoption is an internal
  correctness change, not a wire-shape change.
- The checked-in local env template
  `apps/prototype-description-service/.env.example` remains the canonical dev
  fixture for runtime knobs consumed by `db.settings`, including
  `DB_EMBEDDING_TIMEOUT_SECONDS`; tracking hygiene for `.env*.example` files
  does not change environment variable names or defaults.

## Analyze jobs

### Scan job terminal states

`JobStatusResponse.status` for a scan (analyze) job resolves to one of three
terminal states once every queued item reaches a terminal item state:

- `completed` — every item succeeded.
- `completed_with_errors` — at least one item succeeded **and** at least one
  failed (`error_message` is `"one or more items failed"`).
- `failed` — no item succeeded (`error_message` `"no items completed
  successfully"`), the job stalled past its run threshold, or it was explicitly
  canceled. An all-items-failed batch finalizes `failed` rather than
  `completed_with_errors` so a fully-failed batch is never reported as a partial
  success (a consumer reading only `phase=complete` would otherwise mis-read it
  as healthy).

All finalizers are terminal-guarded: once a job is terminal (e.g. `failed` from
a stall), a late progress refresh from a concurrent worker replica never
overwrites the status or its reason.

Downstream side effects fan out only for jobs that produced at least one
successful item (`completed` or `completed_with_errors`): identity clustering is
auto-triggered and the per-job ObjectStore upload directory is cleaned up. A
fully-`failed` job triggers neither — there is nothing to cluster and the
uploads are retained for diagnosis.

### POST /recognition/analyze

Queue a face detection job (legacy URL transport).

Request body:

```json
{
  "tenant_id": "a9c2c2c0f6ef4a1f8d6d7a3f6c9b8e12",
  "media_items": [
    { "media_id": 101, "media_url": "https://example.test/uploads/101.jpg" }
  ]
}
```

Response: `JobStatusResponse`.

Notes:

- `media_items` is preferred. `media_ids` is accepted for tests and stub detectors.
- When `RECOGNITION_ASYNC_ANALYZE_INLINE=0`, Postgres requires a running scan
  worker or the service returns 503.
- Each `media_items[]` carries exactly one of `media_url` (this route) or
  `blob_uri` (multipart route below). Mutual exclusion enforced at the
  schema layer (`MediaItem` validator).

### POST /recognition/analyze/multipart

E15-11. Multipart variant for callers that cannot expose media via public
URL (LocalWP, intranet, behind a WAF). Image bytes ship inline; the
service writes them through a per-tenant `ObjectStore` and queues the
scan against the resulting blob URIs.

Request: `multipart/form-data` with these parts:

- `request` (required): JSON-encoded envelope, currently
  `{ "tenant_id": "<uuid>" }`. Optional `site_url` and `user_id` fields are
  accepted for plugin-side audit.
- `image_<media_id>` (one or more): binary image bytes. Filename arbitrary;
  `content-type` MUST be one of `image/jpeg`, `image/png`, `image/webp`
  (override via `RECOGNITION_ALLOWED_UPLOAD_MIME_TYPES`).

Headers (added by the proxy / required by the route):

- `X-API-Key: <api-key>` (auth)
- `X-Tenant-ID: <uuid>` (must equal `request.tenant_id`)
- `Content-Type: multipart/form-data; boundary=<token>` (set by the client;
  WP plugin builds this manually since `wp_remote_request` does not
  auto-build multipart from an array body)
- `Content-Length: <bytes>` (must be present; chunked-without-CL → 411)

Response: `202 Accepted` with `JobStatusResponse` body.

Status codes:

- `202` — job queued (`status=pending`); blobs persisted under
  `<RECOGNITION_BLOB_ROOT>/<tenant_id>/<job_id>/<media_id>.bin`
- `400` — missing/malformed `request` part, non-integer `image_<id>` suffix
- `403` — `X-Tenant-ID` / `auth.tenant_claim` differs from
  `request.tenant_id`
- `411` — body-bearing request without `Content-Length`
- `413` — `Content-Length > RECOGNITION_MAX_UPLOAD_BYTES` (default 25 MiB)
- `415` — image part with disallowed MIME type
- `422` — no `image_<id>` parts, missing/invalid `tenant_id`, zero-byte part
- `503` — `RECOGNITION_ASYNC_ANALYZE_INLINE=0` with no DB session/worker

Cleanup contract:

- Successful job: worker `ScanItemHandler._refresh_job_progress` calls
  `ObjectStore.cleanup(job_id)` once the last queued item completes; the
  per-job directory is removed.
- Pre-commit failure (`scan_queue.create_scan_job_record` raises): route's
  `try/finally` calls `ObjectStore.cleanup(job_id)` before propagating.
- Inline-processing path (`RECOGNITION_ASYNC_ANALYZE_INLINE=1`):
  `chain_populate_and_process` cleans up after `process_scan_job_inline`
  returns or raises.

Tenant binding:

- Per-tenant `ObjectStore` is constructed from `auth.tenant_claim`.
- `ObjectStore.open()` rejects URIs whose path does not fall under the
  bound tenant prefix (`ObjectStoreError`).

Settings:

| env var | default | meaning |
| --- | --- | --- |
| `RECOGNITION_BLOB_ROOT` | `/tmp/acx-recognition-blobs` | Filesystem root for `FilesystemObjectStore` |
| `RECOGNITION_MAX_UPLOAD_BYTES` | `26214400` (25 MiB) | Body-size cap for the multipart route |
| `RECOGNITION_ALLOWED_UPLOAD_MIME_TYPES` | `image/jpeg,image/png,image/webp` | CSV; whitespace-only falls back to default |

WordPress plugin contract:

- Filter `acx_recognition_transport` (default `'multipart'`, opt-in `'url'`):
  selects which transport `analyze_media` uses. Plugin-side caps:
  ≤ 5 images per request (`MULTIPART_MAX_IMAGES`), ≤ 25 MiB serialized
  body (`MULTIPART_MAX_BYTES`).
- **Canonical owner of the per-request image cap**: the PHP constant
  `AltContext\Api\AnalysisJobsController::MULTIPART_MAX_IMAGES` (currently
  `5`) is the authoritative source. JS clients MUST chunk submissions to
  match this cap rather than rely on the localized `max_media_per_batch`
  knob alone — `max_media_per_batch` is a soft batching hint that may be
  raised for ergonomic reasons, but the multipart cap is hard. The
  workbench client honours this in
  `apps/prototype-wp-alt-context/js/admin/api/recognition/scanApi.ts`
  (`scanFacesBatched`/`getEffectiveBatchSize`), which clamps the
  effective batch to `min(max_media_per_batch, 5)`. When the server cap
  changes, update the constant **and** this contract in the same slice;
  the JS mirror is allowed to lag the contract but never the constant.
- Telemetry: backend logs `analyze_media_multipart_dispatch ...`; plugin
  logs `[acx] acx_recognition_transport=...` and
  `[acx] multipart dispatch failed: ...` via `Telemetry::log_line`.

### GET /recognition/jobs/{job_id}

Query params:

- `tenant_id` (required for Postgres/RLS)

Response: `JobStatusResponse`.

Notes:

- When the service cannot acquire a database connection from the pool, the route returns `503` with `{ "error": "database_unavailable", "trace_id": "...", "path": "..." }` and a `Retry-After: 5` header.
- Generic unhandled `500` responses expose `trace_id` and `path`, but no longer leak raw exception class names or messages.
- The request uses the tenant-aware session provided by `get_optional_session()` and does not repeat tenant-context setup inside `get_job_status()`.
- Completed clustering responses may include `snapshot_version`, `source_job_id`, `projection_acknowledged_at`, and an optional `projection_payload`.
- `projection_payload` mirrors the tenant delta envelope for `since_version=0` and exists to let the WordPress plugin project durable local state from the same successful job-status read that reported `awaiting_projection`.
- When `projection_acknowledged_at` is non-null or the payload version no longer matches `snapshot_version`, `projection_payload` may be omitted.

### POST /recognition/jobs/{job_id}/cancel

Query params:

- `tenant_id` (required for Postgres/RLS)

Response: `JobStatusResponse`.

## Clustering

### POST /recognition/clustering/jobs

Request body:

```json
{ "tenant_id": "...", "mode": "sync" }
```

Response:

- `sync` mode returns `ClusteringJobStatusResponse` with `clusters_created`.
- `async` mode returns a queued job status.

### POST /recognition/clusters/recover-orphans

Re-cluster any orphaned (unclustered) identities for a tenant.

Request body:

```json
{ "tenant_id": "..." }
```

Response:

```json
{
  "orphans_found": 12,
  "recovered": 8,
  "suggested": 2,
  "rejected": 2,
  "clusters_created": 3
}
```

### GET /recognition/clusters

Query params:

- `tenant_id` (header or query)
- `limit` (default 50)
- `offset` (default 0)
- `include_outliers` (default false)
- `labeled_only` (default false)
- `search` (optional substring filter for labels)

Response: `ClusterResponse[]`.

ClusterResponse fields (abridged):

- `id`, `tenant_id`, `label`, `is_labeled`, `is_auto_label`, `identity_count`, `representatives`
- `suggested_label` (nullable; best-effort label inference for unlabeled clusters)
- `suggested_label_source` (`identity` | `roster` | `similar_cluster` | `none` | null)
- `suggested_label_confidence` (nullable float)

### GET /recognition/clusters/{cluster_id}/roster-candidates

Query params:

- `tenant_id` (header or query; same tenant scoping as sibling cluster reads)
- `top_k` (default 10, max 50; rejected with 400 when out of range — never clamped)

Ranks labelled, user-confirmed clusters (the python-side stand-in for roster persons) against the probe cluster's representatives. Comparison is max-cosine over same-`embedding_model` representative sets only (FIR23-01 / EMB-01). Python has no person table: each candidate is keyed by labelled `cluster_id` + `name` (cluster label). The WordPress passthrough maps `cluster_id` → local `roster_entry_id` via `acx_clusters.person_id`.

Response schema: `packages/shared-contracts/schemas/roster-candidates-response.schema.json`.

```json
{
  "model_id": "opencv-sface+cv5@128d/l2/cosine",
  "embedding_model": "opencv-sface+cv5@128d/l2/cosine",
  "computed_at": "2026-08-18T12:00:00+00:00",
  "reference_face_count": 3,
  "thresholds": {
    "suggestion_floor": 0.35,
    "suggestion_ceiling": 0.55,
    "similarity_threshold": 0.55
  },
  "candidates": [
    {
      "cluster_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      "name": "Ada",
      "similarity": 0.81,
      "band": "strong",
      "quality_flag": "ok"
    }
  ]
}
```

Notes:

- `band` is computed server-side from the active profile's live `suggestion_floor` / `suggestion_ceiling` (`strong` ≥ ceiling, `possible` ∈ [floor, ceiling), `none` < floor). Clients must not invent bands (DRIFT-03).
- `similarity` is a ranking cosine, not a calibrated probability (CAL-03 / HAI-08 / MEAS-05). New UI surfaces should show `band`, not a raw percent.
- Empty labelled roster returns `{ candidates: [] }` (200), not an error (CAL-02). Missing cluster is 404.
- `quality_flag` is `low_quality` when a probe representative's `landmark_quality` / `quality_score` is below `fatal_quality_floor` (or `det_score` below `fatal_confidence_floor`). `occluded` is reserved and is never fabricated.
- Order is server rank (similarity descending). Do not re-sort client-side.

### GET /recognition/clusters/top-unlabeled

Query params:

- `tenant_id` (header or query)
- `limit` (default 10)
- `min_identity_count` (default 2, minimum 1; filters out singletons by default)

Response: `ClusterResponse[]`.

Notes:

- Returns clusters using **tenant-wide size-priority selection**: largest unlabeled clusters across the entire tenant, ordered by `identity_count` descending, then `created_at` descending.
- Excluded: clusters with `user_confirmed = true`, `dismissed_at` set, `identity_count < min_identity_count`, or auto-generated `cluster-*` labels that have been confirmed.
- The `min_identity_count` filter defaults to 2, which excludes singletons from the naming queue.
- `representatives` objects include `thumb_url` for UI display.

### PATCH /recognition/clusters/{cluster_id}

Request body:

```json
{ "tenant_id": "...", "label": "Alice" }
```

Response: `ClusterResponse`.

### POST /recognition/clusters/create-for-identity

Request body:

```json
{ "tenant_id": "...", "identity_id": "...", "label": "Alice" }
```

Response: `CreateClusterForIdentityResponse`.

### POST /recognition/clusters/{cluster_id}/merge

Request body:

```json
{ "tenant_id": "...", "target_cluster_id": "...", "target_label": "Alice" }
```

Response: `ClusterResponse` for the target cluster.

### POST /recognition/clusters/{cluster_id}/split

Request body:

```json
{
  "tenant_id": "...",
  "n_clusters": 0,
  "anchor_identity_id": "...",
  "split_mode": "anchor",
  "mode": "sync"
}
```

Response:

- `SplitClusterResponse` for sync
- `AsyncSplitClusterResponse` for async

### POST /recognition/clusters/reassign

Request body:

```json
{
  "tenant_id": "...",
  "identity_id": "...",
  "target_cluster_id": "...",
  "block_from_cluster": true
}
```

Response: `ReassignIdentityResponse`.

### POST /recognition/clusters/{cluster_id}/assign

Assign an outlier identity to a cluster.

Request body:

```json
{ "tenant_id": "...", "identity_id": "...", "similarity": 0.91 }
```

Response: `ClusterResponse`.

### PATCH /recognition/clusters/{cluster_id}/representatives/{representative_id}/pin

Pin/unpin a representative.

Request body:

```json
{ "tenant_id": "...", "is_pinned": true }
```

Response: 204 No Content.

## Suggestions

### GET /recognition/suggestions

Query params:

- `tenant_id` (header or query)
- `limit` (default 50)
- `offset` (default 0)

Response: `SuggestionResponse[]`.

Response example:

```json
[
  {
    "id": "...",
    "identity_id": "...",
    "cluster_id": "...",
    "rep_similarity": 0.92,
    "member_similarity": 0.92,
    "status": "pending",
    "cluster_label": null,
    "cluster_identity_count": 5,
    "suggested_label": "Alice",
    "suggested_label_source": "identity",
    "suggested_label_confidence": 0.91,
    "confidence_score": 0.91,
    "expires_at": null,
    "source_job_id": "...",
    "identity_media_id": 123,
    "identity_media_url": "https://...",
    "identity_bbox": { "x": 10, "y": 20, "width": 120, "height": 120 },
    "representative_media_id": 456,
    "representative_media_url": "https://...",
    "representative_bbox": { "x": 14, "y": 18, "width": 118, "height": 118 }
  }
]
```

Notes:

- `cluster_label` is null when the cluster is unlabeled.
- `suggested_label*` fields are best-effort and may be null when no reliable source exists.

### GET /recognition/suggestions/merge

Query params:

- `tenant_id` (header or query)
- `limit` (default 50)
- `offset` (default 0)

Response: `MergeSuggestionResponse[]`.

Response example:

```json
[
  {
    "id": "...",
    "cluster_a_id": "...",
    "cluster_b_id": "...",
    "similarity": 0.88,
    "status": "pending",
    "cluster_a_label": "Alice",
    "cluster_b_label": null,
    "cluster_a_identity_count": 5,
    "cluster_b_identity_count": 3,
    "cluster_a_representative_media_id": 123,
    "cluster_a_representative_media_url": "https://...",
    "cluster_a_representative_bbox": { "x": 10, "y": 20, "width": 120, "height": 120 },
    "cluster_b_representative_media_id": 456,
    "cluster_b_representative_media_url": "https://...",
    "cluster_b_representative_bbox": { "x": 14, "y": 18, "width": 118, "height": 118 },
    "confidence_score": 0.88,
    "expires_at": null,
    "source_job_id": "..."
  }
]
```

### GET /recognition/suggestions/name

Query params:

- `tenant_id` (header or query)
- `limit` (default 50)
- `offset` (default 0)
- `min_confidence` (optional)

Response: `NameSuggestionResponse[]`.

Response example:

```json
[
  {
    "id": "...",
    "cluster_id": "...",
    "suggested_name": "Alice",
    "source": "roster",
    "status": "pending",
    "confidence_score": 0.88,
    "source_job_id": "...",
    "created_at": "2026-03-25T12:00:00Z",
    "expires_at": null,
    "resolved_at": null
  }
]
```

### GET /recognition/identities/{identity_id}/suggestions

Query params:

- `tenant_id` (header or query)

Response:

```json
{
  "matches": [
    {
      "cluster_id": "...",
      "label": "Alice",
      "similarity": 0.91,
      "identity_count": 5
    }
  ]
}
```

### POST /recognition/suggestions/{suggestion_id}/accept

### POST /recognition/suggestions/{suggestion_id}/reject

Request body:

```json
{ "tenant_id": "..." }
```

Response: `SuggestionResponse`.

### GET /recognition/clusters/{cluster_id}/roster-candidates

Rank labelled clusters against an unlabeled probe. Schema:
`packages/shared-contracts/schemas/roster-candidates-response.schema.json`.

Query: `top_k` (default 10, min 1, max 50; reject-not-clamp).

200 body is PROV-06 typed:

- `model_id` / `embedding_model` — FIR23-01 space of the ranking rows.
- `computed_at` — ranking timestamp; similarity is not a stable person attribute.
- `probe_face_count` — probe representatives (or member-fallback faces) used.
- `reference_face_count` — same-space labelled reference vectors actually compared.
- `quality_flag` — probe-level `ok` | `low_quality` | `occluded` (reserved; never fabricated). Unknown values → treat as `low_quality`. When not `ok`, every candidate `band` is capped at `possible` (frontend must not show Strong for a low-quality probe). `fatal_quality_floor` / `fatal_confidence_floor` gate; missing metrics fail closed to `low_quality`.
- `thresholds` — live `suggestion_floor` / `suggestion_ceiling` / `similarity_threshold`.
- `candidates[]` — labelled clusters, similarity DESC then `cluster_id` ASC. Negative cosine is `band=none` (floor is `-1.0`, not `0.0`). Dimension-mismatched reps are skipped. Same-space guard is the in-process FIR23-01 helper (`embedding_space.same_space_vector`); unlike label inference there is no MediaIdentity SQL fallback because `get_labeled_with_representatives` eager-loads identity — unresolved models are excluded.

PHP passthrough `GET acx/v1/recognition/clusters/{id}/roster-candidates`:

- Proxy class `post_scan_read` (10s, breaker off).
- Maps `cluster_id` → `roster_entry_id` via tenant-scoped `ClustersReadRepository.lookup_person_ids_for_clusters` (`AND tenant_id = %s`).
- Collapses to one row per `roster_entry_id` (max similarity wins, keep that row's band). `name` is `acx_persons.name` when mapped.
- `roster_entry_id: null` rows are kept and flagged uncommittable (no person to commit to).
- Degraded/offline: HTTP 502 (endpoint_error / refused 3xx) or 503 (unreachable / overloaded). Do not return a 200 `{candidates:[], data_source}` envelope — that is not schema-conformant and is indistinguishable from an empty roster.

## Media identities

### GET /recognition/media/identities

Query params:

- `tenant_id` (header or query)
- `media_ids` (accepts `media_ids`, `media_ids[]`, or `media_ids[0]` style)
- `include_debug` (optional)

Response: array of identities with cluster metadata:

```json
[
  {
    "identity_id": "...",
    "media_id": 101,
    "cluster_id": "...",
    "cluster_label": "Alice",
    "is_auto_label": false,
    "bbox": { "x": 45, "y": 60, "width": 120, "height": 120 },
    "confidence": 0.98,
    "thumbnail_url": "https://example.test/uploads/101-thumb.jpg",
    "media_url": "https://example.test/uploads/101.jpg",
    "debug_metrics": {
      "pose": { "pitch": 5.0, "yaw": -2.0, "roll": 1.0 },
      "age": 32,
      "gender": "female",
      "det_score": 0.98,
      "bbox_area": 14400,
      "landmark_quality": 0.9,
      "clustering_method": null,
      "clustering_algorithm": null,
      "similarity_threshold": null,
      "match_similarity": null,
      "representative_count": 3,
      "pose_buckets": { "filled": 3, "total": 13, "current_bucket": [0, -1] }
    }
  }
]
```

## Events and diagnostics

### GET /recognition/clusters/events

Server-Sent Events stream for cluster and suggestion updates.

### GET /recognition/diagnostics/decisions

Admin-only endpoint for decision inspection.

## Health

### GET /recognition/health

Returns database connectivity and service status.

### GET /recognition/health/pool

Returns connection pool statistics (auth required when enabled).

## Related contracts

The recognition service exposes additional endpoint groups outside `/recognition`:

- **Curation sync and topology operations (`/roster/`):** [curation-sync-api.md](curation-sync-api.md)
- **Snapshot projection (`/tenants/{tenant_uuid}/...`):** [cluster-snapshot-api.md](cluster-snapshot-api.md)
- **WordPress proxy layer for these endpoints:** [clustering-api.md](clustering-api.md)
