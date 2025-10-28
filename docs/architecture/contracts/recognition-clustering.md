---
title: Recognition Service Clustering Contracts
status: draft
owners:
  - recognition-service
  - plugin-platform
description: HTTP contracts between the Context Alt Text WordPress plugin and the recognition service for clustering and roster suggestion workflows.
---

# Recognition Service – Clustering & Suggestion API

These endpoints are consumed by the WordPress plugin to outsource heavy-duty clustering and roster suggestion tasks when MediaPipe-only matching is insufficient. All requests require the standard recognition service API key header:

```
Authorization: Bearer <api-key>
Content-Type: application/json
```

## `POST /api/v0/cluster`

Perform FAISS-backed clustering on a batch of embeddings. Recommended when the caller collects >50 embeddings or wants server-side consistency.

### Request

```json
{
  "job_id": "cluster-2024-11-01",
  "embeddings": [
    {
      "id": "face-1",
      "vector": [0.01, 0.02, "..."]
    }
  ],
  "min_cluster_size": 2,
  "similarity_threshold": 0.92
}
```

- `job_id`: optional string for idempotency/debugging.
- `embeddings`: array of objects containing a stable identifier and embedding vector (float32 array).
- `min_cluster_size`: optional integer (default `2`).
- `similarity_threshold`: optional float controlling FAISS linkage (default `0.92`).

### Response

```json
{
  "job_id": "cluster-2024-11-01",
  "clusters": [
    {
      "cluster_id": "cluster-abc123",
      "face_ids": ["face-1", "face-2"],
      "centroid": [0.01, 0.02, "..."]
    }
  ],
  "unclustered_face_ids": ["face-99"]
}
```

## `POST /api/v0/suggest`

Return roster suggestions for one or more embeddings. For best results, pass embeddings representing the cluster centroid and representative members.

### Request

```json
{
  "embeddings": [
    {
      "id": "cluster-abc123::centroid",
      "vector": [0.01, 0.02, "..."]
    }
  ],
  "top_k": 3,
  "threshold": 0.92
}
```

### Response

```json
{
  "suggestions": [
    {
      "id": "cluster-abc123::centroid",
      "matches": [
        {
          "roster_id": "person-42",
          "display_name": "Ellyn",
          "confidence": 0.968,
          "reason": "FAISS cosine similarity 0.968"
        }
      ]
    }
  ]
}
```

## `POST /api/v0/roster/add-embedding`

Augment an existing roster entry with confirmed embeddings, ensuring future suggestions improve.

### Request

```json
{
  "roster_id": "person-42",
  "observation_id": "obs-123",
  "embedding": [0.01, 0.02, "..."],
  "metadata": {
    "attachmentId": 123,
    "bbox": { "x": 45, "y": 60, "width": 120, "height": 120 },
    "source": "wordpress-plugin"
  }
}
```

### Response

```json
{
  "status": "queued",
  "sync_id": "sync-456",
  "message": "Embedding scheduled for FAISS index update."
}
```

## Error Handling

All endpoints return standard error objects:

```json
{
  "error": {
    "code": "invalid_payload",
    "message": "Embeddings array cannot be empty.",
    "hint": "Provide at least one embedding vector."
  }
}
```

Client code must treat non-2xx responses as failures and retry or fall back to local processing as appropriate.
