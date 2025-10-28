---
title: WordPress Clustering REST Contracts
status: draft
owners:
  - frontend-team
  - plugin-platform
description: REST endpoints powering assisted face identification workflows within the Context Alt Text WordPress plugin.
---

# Context Alt Text – Clustering REST API

The following endpoints enable assisted face identification inside the WordPress admin. All routes require an authenticated user with the `edit_posts` capability and a valid REST nonce. Responses are JSON (`application/json; charset=utf-8`). Unless specified, timestamps follow ISO 8601.

## `POST /wp-json/cat/v1/recognition/scan`

Trigger face detection and embedding extraction for a curated list of attachments. This endpoint enqueues asynchronous jobs rather than processing synchronously.

### Request

```http
POST /wp-json/cat/v1/recognition/scan HTTP/1.1
Content-Type: application/json
X-WP-Nonce: <nonce>
```

```json
{
  "attachment_ids": [123, 456, 789],
  "priority": "normal"
}
```

- `attachment_ids`: required, array of numeric WordPress attachment IDs (max 50 per request).
- `priority`: optional, `"high"` or `"normal"` (defaults to `"normal"`).

### Response

```json
{
  "job_id": "scan-2024-11-01T07:18:22Z",
  "queued_count": 3,
  "estimated_start_at": "2024-11-01T07:19:00Z"
}
```

### Error Codes

| Status | Code                     | Meaning                                                      |
|--------|--------------------------|--------------------------------------------------------------|
| 400    | `invalid_request`        | Missing/invalid payload or batch exceeds 50 attachments.     |
| 401    | `rest_not_logged_in`     | Non-authenticated request.                                   |
| 403    | `rest_forbidden`         | Lacking capability / nonce invalid.                          |

## `GET /wp-json/cat/v1/clusters`

List unresolved face clusters available for review. Supports pagination and filtering.

### Query Parameters

- `page` (default `1`)
- `per_page` (default `20`, max `50`)
- `status` (`"unresolved"`, `"review_later"`, `"resolved"`)
- `min_confidence` (float between `0` and `1`)

### Response

```json
{
  "page": 1,
  "per_page": 20,
  "total": 5,
  "clusters": [
    {
      "id": "cluster-abc123",
      "face_ids": ["face-1", "face-2"],
      "sample_face_id": "face-1",
      "suggested_roster_id": null,
      "confidence": null,
      "created_at": "2024-10-31T11:20:00Z",
      "updated_at": "2024-10-31T11:20:00Z"
    }
  ]
}
```

## `GET /wp-json/cat/v1/clusters/{id}`

Retrieve detailed information for a single cluster, including face metadata and suggestions.

### Response

```json
{
  "cluster": {
    "id": "cluster-abc123",
    "face_ids": ["face-1", "face-2"],
    "sample_face_id": "face-1",
    "suggested_roster_id": "person-42",
    "confidence": 0.96,
    "created_at": "2024-10-31T11:20:00Z",
    "updated_at": "2024-10-31T12:05:00Z"
  },
  "faces": [
    {
      "id": "face-1",
      "attachment_id": 123,
      "bbox": { "x": 45, "y": 60, "width": 120, "height": 120 },
      "embedding_id": "emb-1",
      "detected_at": "2024-10-31T11:20:00Z",
      "cluster_id": "cluster-abc123"
    }
  ],
  "suggestions": [
    {
      "cluster_id": "cluster-abc123",
      "roster_id": "person-42",
      "display_name": "Ellyn",
      "confidence": 0.96,
      "reason": "FAISS similarity 0.96"
    }
  ]
}
```

## `POST /wp-json/cat/v1/clusters/{id}/confirm`

Confirm a cluster’s identity and mark constituent faces as resolved.

### Request

```json
{
  "roster_id": "person-42",
  "face_ids": ["face-1", "face-2"],
  "notes": "Confirmed during November sweep"
}
```

### Response

```json
{
  "cluster_id": "cluster-abc123",
  "resolved_count": 2,
  "roster_id": "person-42",
  "sync_status": "queued"
}
```

### Post-Conditions

- Faces are marked resolved with `roster_id`.
- Observation + roster embedding sync job enqueued (see recognition contract).

## `POST /wp-json/cat/v1/clusters/{id}/split`

Move one or more faces into a new or existing cluster to correct grouping errors.

### Request

```json
{
  "target_cluster_id": "cluster-def456",
  "face_ids": ["face-2"]
}
```

- `target_cluster_id`: optional; when omitted, the backend creates a new cluster.

### Response

```json
{
  "source_cluster_id": "cluster-abc123",
  "target_cluster_id": "cluster-def456",
  "moved_face_ids": ["face-2"]
}
```

---

## Error Handling

All endpoints return standard REST error objects:

```json
{
  "code": "rest_forbidden",
  "message": "You are not allowed to confirm this cluster.",
  "data": {
    "status": 403
  }
}
```

Ensure front-end handlers gracefully surface error messages and provide retry guidance.
