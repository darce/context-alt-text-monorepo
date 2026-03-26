---
title: Tenant Cluster Delta API
status: draft
owners:
  - plugin-platform
  - recognition-service
description: Incremental cluster sync contract for version-filtered upserts between the recognition backend and the WordPress projector.
---

# Tenant Cluster Delta API

## Scope

This contract defines the backend-domain slice for incremental cluster sync.
It complements the full snapshot contract in [cluster-snapshot-api.md](./cluster-snapshot-api.md).

- Route owner: recognition service (`apps/prototype-description-service`)
- Primary consumer: WordPress plugin sovereign projector (`apps/prototype-wp-alt-context`)
- Delivery mode: pull-first delta query with `since_version`

## Endpoint

- `GET /tenants/{tenant_uuid}/clusters/delta?since_version=<snapshot_version>`

Path params:

- `tenant_uuid`: stable tenant key (`md5(get_site_url())` from plugin)

Query params:

- `since_version`: previously acknowledged tenant `snapshot_version` as a microsecond-precision Unix timestamp integer

## Response (200)

```json
{
  "tenant_id": "a9c2c2c0f6ef4a1f8d6d7a3f6c9b8e12",
  "snapshot_version": 1773928200000000,
  "generated_at": "2026-03-19T16:30:00Z",
  "clusters": [
    {
      "cluster_uuid": "b43c2ab2-8d4f-42a8-9b2d-7f1d2e5a9b7a",
      "label": "Daniel",
      "curation_state": "confirmed",
      "is_user_confirmed": true,
      "identity_count": 6,
      "representative_thumb_path": "acx://cluster/b43c2ab2-8d4f-42a8-9b2d-7f1d2e5a9b7a/media/101",
      "representative_id": "0a7b8331-bb7f-40c1-8f24-8c7e2b2d7c4f",
      "is_pinned": true,
      "suggested_label": null,
      "suggested_label_source": null,
      "suggested_label_confidence": null,
      "suggested_target_cluster_id": null
    }
  ],
  "members": [
    {
      "identity_uuid": "0a7b8331-bb7f-40c1-8f24-8c7e2b2d7c4f",
      "cluster_uuid": "b43c2ab2-8d4f-42a8-9b2d-7f1d2e5a9b7a",
      "attachment_id": 101,
      "bbox": {
        "x": 45,
        "y": 60,
        "width": 120,
        "height": 120
      },
      "image_width": 0,
      "image_height": 0,
      "thumb_path": "acx://identity/0a7b8331-bb7f-40c1-8f24-8c7e2b2d7c4f/attachment/101",
      "similarity": 0.98
    }
  ]
}
```

## Delta Semantics

- `snapshot_version` remains monotonic per tenant and reflects the backend's latest known version after serving the delta request.
- `snapshot_version` and `since_version` use the same microsecond-precision Unix timestamp encoding as the full snapshot API.
- `clusters` contains only cluster ids whose current `identity_clusters.updated_at` encodes to a value greater than `since_version`.
- `members` contains the full current membership for the returned cluster ids, not just per-member patch rows.
- Clients should treat each returned cluster id as a targeted replacement set:
  - upsert the cluster summary
  - replace the stored member rows for that cluster with the returned member subset
- Representative metadata travels with each changed cluster row:
  - `representative_id` identifies the backend-selected representative
  - `is_pinned` carries explicit user pin state for that representative
- Empty `clusters` and `members` with a newer `snapshot_version` means the backend observed a newer stream version but had no active cluster upserts to emit in this slice, such as when only disposed clusters changed.
- `suggested_label` fields are ephemeral backend enrichments computed at read time by `infer_suggested_label`. They follow the same semantics as the full snapshot: only unlabeled, unconfirmed clusters may receive non-null values; all others carry null for all four fields. These fields are never curation-guarded and are always overwritten by each delta pull.

## Current Limitation

- This backend-domain slice does not yet encode tombstones for fully deleted or disposed clusters.
- HTTP/plugin callers that require destructive reconciliation must fall back to `GET /clusters/snapshot` until a tombstone contract is added.

## Error Handling

- `400`: malformed tenant id or `since_version`
- `401` or `403`: auth failure
- `404`: tenant not found
- `429`: retryable rate limit
- `5xx`: backend delta generation failure

## Fallback Behavior

- The current backend contract does not emit a dedicated `fallback_to_snapshot` response field.
- Callers should fall back to `GET /clusters/snapshot` when the delta request fails at the HTTP layer or when local projection safeguards reject the delta payload.
