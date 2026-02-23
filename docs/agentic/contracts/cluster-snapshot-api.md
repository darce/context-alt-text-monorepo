---
title: Tenant Cluster Snapshot API
status: finalized
owners:
  - plugin-platform
  - recognition-service
description: Contract for backend snapshot export consumed by sovereign local projection in the WordPress plugin.
---

# Tenant Cluster Snapshot API

## Scope

This contract defines the v0.1.0 snapshot payload required for plugin-side sovereign projection.
The machine-readable schema for this contract is located at [recognition-cluster-snapshot.schema.json](../../../packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json).

- Route owner: recognition service (`apps/prototype-description-service`)
- Consumer: WordPress plugin sovereign projector (`apps/prototype-wp-alt-context`)
- Delivery mode: pull-first (`GET`) snapshot, no event replay requirement in v0.1.0

## Endpoint

- `GET /tenants/{tenant_uuid}/clusters/snapshot`

Path params:

- `tenant_uuid`: stable tenant key (`md5(get_site_url())` from plugin). Named `tenant_uuid` (not `tenant_id`) to avoid a FastAPI path/query parameter collision -- `tenant_id` is reserved as a `Query` parameter in the session dependency chain.

Required headers:

- `X-API-Key` or `Authorization: Bearer <token>` (service deployment dependent)
- `X-Tenant-ID` may be sent by plugin proxy, but path param is canonical for this route
- `Accept: application/json`

Content negotiation:

- Success and error payloads MUST use `Content-Type: application/json; charset=utf-8`
- Non-JSON payloads MUST be treated by plugin clients as transport failures and retried as transient errors

Timeout expectations:

- Client request timeout target: 15 seconds
- Backend target p95 response time: <= 5 seconds for tenants up to 10k identities
- If timeout is exceeded, plugin preserves local projection and retries later (no destructive local deletes on timeout)

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
- `429`: rate limited (retry allowed)
- `5xx`: backend snapshot generation failure

When backend returns non-2xx, plugin sync should preserve existing local rows and retry later.

## Retry and Backoff Semantics

- Retryable responses: `408`, `429`, and any `5xx` status.
- Non-retryable responses: `400`, `401`, `403`, `404`, `422`.
- Backoff policy:
  - Attempt 1: immediate
  - Attempt 2: +30 seconds
  - Attempt 3: +120 seconds
  - Attempt 4+: +300 seconds capped
- If `Retry-After` header is present on `429` or `503`, clients should prefer that delay over default backoff.
- After max retries in a sync cycle, keep last known local projection unchanged and schedule next routine pull.

## Rate Limit Contract

- `429` responses should include:
  - `Retry-After: <seconds>`
  - `X-RateLimit-Limit: <integer>`
  - `X-RateLimit-Remaining: <integer>`
  - `X-RateLimit-Reset: <unix_epoch_seconds>`
- Clients must treat missing rate-limit headers as retryable transient failures using default backoff.

## Pagination Contract (Forward-Compatible)

v0.1.0 permits single-response snapshots for small tenants. To support large tenants without breaking clients, backend implementations should support cursor pagination with stable ordering:

- Request query params:
  - `cursor` (optional opaque token from previous page)
  - `page_size` (optional, default 1000, max 5000)
- Response envelope additions:
  - `next_cursor` (string|null)
  - `has_more` (boolean)
- `snapshot_version` MUST remain constant across all pages for one snapshot pull.
- Plugin client must not project partial pages; it should buffer until `has_more=false`, then project in one transaction.
