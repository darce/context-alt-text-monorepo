---
title: Tenant Cluster Snapshot API
status: draft
owners:
  - plugin-platform
  - recognition-service
description: Contract for backend snapshot export consumed by sovereign local projection in the WordPress plugin.
---

# Tenant Cluster Snapshot API

## Scope

This contract defines the v0.1.0 snapshot payload required for plugin-side sovereign projection.

- Route owner: recognition service (`apps/prototype-description-service`)
- Consumer: WordPress plugin sovereign projector (`apps/prototype-wp-alt-context`)
- Delivery mode: pull-first (`GET`) snapshot, no event replay requirement in v0.1.0

## Endpoint

- `GET /tenants/{tenant_id}/clusters/snapshot`

Path params:

- `tenant_id`: stable tenant key (`md5(get_site_url())` from plugin)

Required headers:

- `X-API-Key` or `Authorization: Bearer <token>` (service deployment dependent)
- `X-Tenant-ID` may be sent by plugin proxy, but path param is canonical for this route

## Response (200)

```json
{
  "tenant_id": "a9c2c2c0f6ef4a1f8d6d7a3f6c9b8e12",
  "snapshot_version": 1042,
  "generated_at": "2026-02-10T17:00:00Z",
  "clusters": [
    {
      "cluster_uuid": "b43c2ab2-8d4f-42a8-9b2d-7f1d2e5a9b7a",
      "label": "Daniel",
      "curation_state": "confirmed",
      "is_user_confirmed": true,
      "identity_count": 5,
      "representative_thumb_path": "acx://cluster/b43c2ab2-8d4f-42a8-9b2d-7f1d2e5a9b7a/media/101"
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
      "image_width": 1024,
      "image_height": 768,
      "thumb_path": "acx://identity/0a7b8331-bb7f-40c1-8f24-8c7e2b2d7c4f/attachment/101",
      "similarity": 0.98
    }
  ]
}
```

## Projection Semantics

- `snapshot_version` must be monotonic per tenant.
- Plugin projector writes all rows inside one DB transaction.
- Curation-first guard:
  - existing `wp_acx_clusters.is_user_confirmed = 1` rows are authoritative for `label`, `curation_state`, `is_user_confirmed`
  - non-authoritative fields (`identity_count`, `representative_thumb_path`, `snapshot_version`, `last_synced_at`) may refresh
- Plugin stale-row cleanup deletes only non-curated rows absent from incoming snapshot.

## `bbox_json` Storage Contract (Plugin)

Plugin persists members `bbox` payload into `wp_acx_identity_members.bbox_json`:

```json
{
  "pixels": { "x": 45, "y": 60, "width": 120, "height": 120 },
  "normalized": { "x": 0.043945, "y": 0.078125, "width": 0.117188, "height": 0.15625 },
  "coordinate_space": "original_image"
}
```

Normalization source:

- `x / image_width`
- `y / image_height`
- `width / image_width`
- `height / image_height`

## Error Responses

- `400`: malformed tenant id
- `401` or `403`: auth failure
- `404`: tenant snapshot stream not found
- `5xx`: backend snapshot generation failure

When backend returns non-2xx, plugin sync should preserve existing local rows and retry later.
