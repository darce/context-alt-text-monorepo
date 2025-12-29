---
title: Workbench Recognition REST API
status: draft
owners:
  - plugin-platform
  - recognition-service
description: WordPress REST endpoints used by the Workbench UI. These proxy to /recognition on the FastAPI service.
---

# Workbench Recognition REST API

These endpoints are provided by the WordPress plugin (`apps/prototype-wp-alt-context`).
They require a valid WP REST nonce header (`X-WP-Nonce`) and `manage_options`
capability. The plugin injects `tenant_id` (md5 of the site URL) and forwards
requests to the recognition service (`/recognition/*`).

Base path: `/wp-json/acx/v1/workbench/recognition`

## POST /workbench/recognition/analyze

Queue a recognition job for attachment IDs.

Request body:

```json
{
  "media_ids": [101, 102, 103]
}
```

Response (proxied from `/recognition/analyze`):

```json
{
  "id": "2f2d7b69-7c42-4c4a-9dbd-5fbc0e4b24a2",
  "type": "analyze",
  "status": "pending",
  "progress": { "completed": 0, "total": 3 },
  "started_at": "2025-02-14T18:21:00Z",
  "finished_at": null,
  "message": "Queueing 0/3 items"
}
```

Notes:
- The plugin resolves `media_ids` to `{media_id, media_url}` before forwarding.
- Batch limits are tier-based (default max 50 for free tier).

## GET /workbench/recognition/jobs/{job_id}

Poll job status (proxy to `/recognition/jobs/{job_id}`).

## POST /workbench/recognition/jobs/{job_id}/cancel

Cancel a running scan job (proxy to `/recognition/jobs/{job_id}/cancel`).

## POST /workbench/recognition/cluster

Trigger clustering for unclustered identities (proxy to `/recognition/clustering/jobs`).

Response (sync mode):

```json
{
  "id": "e7c0d8b5-0f06-4b44-b3eb-2b2c3386a284",
  "type": "clustering",
  "status": "completed",
  "progress": { "completed": 12, "total": 12 },
  "started_at": "2025-02-14T18:30:00Z",
  "finished_at": "2025-02-14T18:30:03Z",
  "clusters_created": 4,
  "total_identities_clustered": 12
}
```

## GET /workbench/recognition/clusters

List clusters.

Query params:
- `limit` (default 50, max 500)
- `offset` (default 0)
- `labeled_only` (`true` or omitted)
- `search` (optional substring filter for labels)

Response (array of clusters):

```json
[
  {
    "id": "b43c2ab2-8d4f-42a8-9b2d-7f1d2e5a9b7a",
    "tenant_id": "a9c2c2c0f6ef4a1f8d6d7a3f6c9b8e12",
    "label": "Alice",
    "is_labeled": true,
    "is_auto_label": false,
    "identity_count": 5,
    "representatives": [
      {
        "id": "8f91f4e7-3ad9-4c31-9a12-9c86e8790e6a",
        "media_id": "101",
        "thumb_url": "https://example.test/uploads/101-thumb.jpg",
        "is_pinned": false
      }
    ]
  }
]
```

## GET /workbench/recognition/media-identities

Return identities grouped by `media_id`.

Query params:
- `media_ids[]` (1-100 attachment IDs)
- `include_debug` (optional)

Response:

```json
{
  "identities_by_media": {
    "101": [
      {
        "identity_id": "0a7b8331-bb7f-40c1-8f24-8c7e2b2d7c4f",
        "media_id": 101,
        "cluster_id": "b43c2ab2-8d4f-42a8-9b2d-7f1d2e5a9b7a",
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
  }
}
```

## POST /workbench/recognition/clusters/reassign

Reassign an identity to a different cluster, or remove it from its cluster.

Request body:

```json
{
  "identity_id": "0a7b8331-bb7f-40c1-8f24-8c7e2b2d7c4f",
  "target_cluster_id": "b43c2ab2-8d4f-42a8-9b2d-7f1d2e5a9b7a",
  "block_from_cluster": true
}
```

Response (proxy to `/recognition/clusters/reassign`):

```json
{
  "identity_id": "0a7b8331-bb7f-40c1-8f24-8c7e2b2d7c4f",
  "source_cluster_id": "8d1f7e1c-3fd3-4b78-9c6e-53c8b8f3c1b2",
  "target_cluster_id": "b43c2ab2-8d4f-42a8-9b2d-7f1d2e5a9b7a",
  "success": true
}
```

## PATCH /workbench/recognition/clusters/{cluster_id}

Update cluster label.

Request body:

```json
{ "label": "Alice" }
```

Response: `ClusterResponse`.

## POST /workbench/recognition/clusters/{source_id}/merge

Merge a source cluster into a target.

Request body:

```json
{ "target_cluster_id": "...", "target_label": "Alice" }
```

Response: `ClusterResponse` for the target cluster.

## POST /workbench/recognition/clusters/{cluster_id}/split

Split a cluster using hierarchical clustering.

Request body (sync mode):

```json
{
  "n_clusters": 0,
  "anchor_identity_id": "...",
  "split_mode": "anchor",
  "mode": "sync"
}
```

Response (sync):

```json
{
  "new_cluster_ids": ["...", "..."],
  "moved_counts": [3, 2],
  "new_cluster_id": "...",
  "moved_count": 3
}
```

Response (async):

```json
{
  "job_id": "...",
  "status": "pending",
  "message": "Split operation queued for cluster ..."
}
```

## POST /workbench/recognition/clusters/create-for-identity

Create a new labeled cluster for a single identity.

Request body:

```json
{ "identity_id": "...", "label": "Alice" }
```

Response:

```json
{
  "cluster_id": "...",
  "label": "Alice",
  "identity_id": "...",
  "message": "Cluster created"
}
```

## GET /workbench/recognition/identities/{identity_id}/suggestions

List suggested clusters for an identity.

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

## GET /workbench/recognition/suggestions

List pending suggestions.

Query params:
- `limit` (default 10)
- `offset` (default 0)

Response:

```json
[
  {
    "id": "...",
    "identity_id": "...",
    "cluster_id": "...",
    "rep_similarity": 0.92,
    "member_similarity": 0.92,
    "status": "pending"
  }
]
```

## POST /workbench/recognition/suggestions/{suggestion_id}/accept
## POST /workbench/recognition/suggestions/{suggestion_id}/reject

Accept or reject a suggestion. Response mirrors `SuggestionResponse`.

## Known proxy gaps

The following proxy routes exist in WordPress but the backend endpoints are not
implemented in the recognition service yet (expect 404 until wired):

- `GET /workbench/recognition/clusters/labels`
- `GET /workbench/recognition/training-stage`
- `POST /workbench/recognition/clusters/revert-merge`

The recognition service does support representative pinning, but the WordPress
proxy does not currently expose it.
