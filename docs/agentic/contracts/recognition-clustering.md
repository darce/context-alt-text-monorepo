---
title: Recognition Service HTTP API
status: draft
owners:
  - recognition-service
description: FastAPI endpoints backing recognition analysis, clustering, and suggestions.
---

# Recognition Service HTTP API

Base path: `/recognition`

## Authentication and tenant scoping

- Auth header defaults to `Authorization: Bearer <api-key>`.
- Header name can be changed with `RECOGNITION_API_KEY_HEADER` (the WP plugin uses `X-API-Key`).
- Read endpoints require `X-Tenant-ID` header or `tenant_id` query param.
- Write endpoints include `tenant_id` in the JSON payload and are validated
  against the API key tenant claim when auth is enabled.

Tenant identifiers must be UUID-formatted strings (32 hex or hyphenated UUID).

## Analyze jobs

### POST /recognition/analyze

Queue a face detection job.

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

### GET /recognition/jobs/{job_id}

Query params:
- `tenant_id` (required for Postgres/RLS)

Response: `JobStatusResponse`.

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

### GET /recognition/clusters/top-unlabeled

Query params:
- `tenant_id` (header or query)
- `limit` (default 10)

Response: `ClusterResponse[]`.

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
    "cluster_label": "Alice",
    "cluster_identity_count": 5,
    "identity_media_id": 123,
    "identity_media_url": "https://...",
    "identity_thumbnail_url": "https://...",
    "identity_bbox": { "x": 10, "y": 20, "width": 120, "height": 120 },
    "representative_media_id": 456,
    "representative_media_url": "https://...",
    "representative_thumbnail_url": "https://...",
    "representative_bbox": { "x": 14, "y": 18, "width": 118, "height": 118 }
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
