---
title: Tenant Cluster Snapshot API
status: finalized
boundary_owner: backend
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
  "source_job_id": "b7077447-50cf-4e99-b327-8e60e6e645fd",
  "snapshot_generation_id": "9b2feec0-6b92-44f5-aeb5-2697cd2e4bc8",
  "generated_at": "2026-02-10T17:00:00Z",
  "clusters": [
    {
      "cluster_uuid": "b43c2ab2-8d4f-42a8-9b2d-7f1d2e5a9b7a",
      "label": "Daniel",
      "curation_state": "confirmed",
      "is_user_confirmed": true,
      "identity_count": 5,
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
- `suggested_label` fields are ephemeral backend enrichments computed at read time by `infer_suggested_label`. They are never curation-guarded and are always overwritten by each sync pull. Only unlabeled, unconfirmed clusters (`is_user_confirmed = false`) may receive a non-null `suggested_label`; all other clusters receive null for all four fields.
- `suggested_label_source` values: `"identity"`, `"roster"`, `"similar_cluster"`, `"none"`. Null when no inference was attempted.
- `suggested_label_confidence` is a float in `[0.0, 1.0]`. Null when no inference was attempted.
- Plugin stale-row cleanup deletes only non-curated rows absent from incoming snapshot.
- **Label authority (UXW2-4):** a human cluster label (not NULL, not `''`, and not a reserved shape) MUST have a bound `person_id`. Reserved shape is `DetectsSystemDefinedLabels::is_reserved_label_shape()`: unicode-whitespace trim, then case-insensitive prefix `cluster-` or `cluster_` (`/^cluster[-_]/i`). `Cluster_ab12` is reserved, not a human name. Snapshot merge backfills `acx_persons` + bind for label-only rows in the current batch. `cluster_label` on media-identities is the person name or the auto label.
- **Label tombstone (UXW2-4):** `reset_curation` persists both tombstone fields in one write: `label_cleared_label = label`, `label_cleared_revision = snapshot_version`, and nulls `label` / `person_id`. Snapshot merge loads those fields and computes `$keep_cleared` when `label_cleared_label` is non-empty and the incoming label equals that cleared value. A match stores `label` as NULL and rewrites both tombstone columns unchanged, regardless of `snapshot_version`. Only a genuinely different incoming label releases the tombstone (both `label_cleared_label` and `label_cleared_revision` cleared). A snapshot producer that repeats the cleared name therefore sees a no-op, not a restore.
- Representative metadata semantics:
  - `representative_id` identifies the currently selected backend representative for the cluster.
  - `is_pinned=true` means that representative was explicitly user-selected upstream.
  - Plugin projection should persist both values on the cluster row and reflect them in representative-facing UI and replay paths.

### Projection Conflict Detection

The `SnapshotProjector` detects conflicts when backend state contradicts local operator curation:

| Conflict Code                  | Trigger                                                        | Stored In                    |
| ------------------------------ | -------------------------------------------------------------- | ---------------------------- |
| `curated_cluster_deleted`      | Backend omits a cluster that has `is_user_confirmed = 1`       | `wp_acx_sync_conflicts`      |
| `curated_member_deleted`       | Backend omits a member whose cluster has `is_curated = 1`      | `wp_acx_sync_conflicts`      |
| `member_cluster_reassignment`  | Backend moves a member to a different cluster than local state  | `wp_acx_sync_conflicts`      |

When a conflict is detected:

1. The projector writes a conflict record with `resolution_status = 'open'`, `machine_payload` (backend state), and `local_payload` (curated state).
2. The conflicting local row is NOT deleted or overwritten -- the curated value is preserved.
3. `SyncStateRepository` increments `conflict_count` in `wp_acx_sync_state`.
4. The conflict surfaces in the frontend `ConflictInbox` via `GET /acx/v1/recognition/conflicts`.

Resolution is handled by `ConflictResolutionService` -- see [curation-sync-api.md](curation-sync-api.md) for conflict resolution contracts.

### Projection Acknowledgement

After successful projection:

- Plugin POSTs `POST /recognition/jobs/{job_id}/acknowledge-projection` with `{ "snapshot_version": <projected_version>, "snapshot_generation_id": "<optional-uuid>" }`.
- Backend uses acknowledgement to track tenant synchronization state.
- `source_job_id` is the job identifier the plugin must use in the acknowledgement route.
- `snapshot_generation_id` is optional during rollout, but when present it lets the backend mark the acknowledged snapshot rows as disposal-eligible.

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
