---
title: Recognition REST API (WordPress Proxy)
status: draft
boundary_owner: wp-proxy
description: WordPress REST endpoints used by the admin UI. These proxy to /recognition on the FastAPI service.
---

# Recognition REST API (WordPress Proxy)

These endpoints are provided by the WordPress plugin (`apps/prototype-wp-alt-context`).
They require a valid WP REST nonce header (`X-WP-Nonce`) and `manage_options`
capability. The plugin injects the canonical tenant UUID derived by
`TenantIdentity::derive_from_site_url()` and forwards requests to the
recognition service (`/recognition/*`).

Tenant identity note:

- The plugin's canonical tenant identifier is the deterministic UUID emitted by `TenantIdentity::derive_from_site_url()`, not the legacy md5(site_url) hash.
- Maintenance slice `MAINT-scan-api-lint-20260427` updated boundary-touching tests and static-analysis fixes without changing any request or response payload shape on this REST surface.

Blob auth note:

- The blob proxy continues to use the same `/wp-json/acx/v1/recognition/blobs/...` route and response surface.
- Hotfix slice `HOTFIX-blob-nonce-bypass-20260427` only tightened the nonce-bypass path check so query-string values that mention the blob route no longer bypass auth; no request or response payload changed.

Maintenance note:

- Maintenance slice `MAINT-architecture-compliance-20260511` refactored the React admin recognition/dashboard/roster/settings surfaces and split oversized client helpers without changing any request payload, response envelope, status vocabulary, query parameter contract, or permission behavior on this WordPress REST surface.

Maintenance tooling note:

- Maintenance slice `MAINT-FORMAT-BOOTSTRAP-20260511` updated the root and plugin `Makefile` formatter/bootstrap flow so fresh linked worktrees install missing local Node tool binaries before running WordPress plugin formatting and review gates.
- No `acx/v1/recognition` route, request payload, response payload, status code, or nonce/capability requirement changed in this slice.

Maintenance note:

- Slice `BUG-WORKBENCH-SCAN-COUNT-20260512` adjusted frontend scan-progress derivation and focused hook tests so completed scan totals stay stable while clustering begins.
- No `acx/v1/recognition` route, request payload, response payload, batch-run envelope, or status vocabulary changed in this slice; the runtime REST contract remains byte-identical.

Face thumbnail crop contract:

- Backend-emitted `/recognition/face-thumbs/<job>/<media>?x=...&y=...&width=...&height=...` URLs use a shared max crop component of `32768`.
- `x` and `y` must be integers in `0..32768`; `width` and `height` must be integers in `1..32768`.
- This bound is enforced across the backend emitter in `apps/prototype-description-service/recognition/interface_adapters/http/blob_url.py`, the backend reader in `apps/prototype-description-service/recognition/interface_adapters/http/routers/blobs.py`, and the WordPress proxy signer in `apps/prototype-wp-alt-context/src/api/class-blob-url-rewriter.php`.
- If the crop bound changes, update all three surfaces in the same slice so WordPress never signs a face-thumb URL the backend will reject.

Base path: `/wp-json/acx/v1/recognition`

## POST /recognition/analyze

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

## GET /recognition/jobs/{job_id}

Poll job status (proxy to `/recognition/jobs/{job_id}`).

Notes:

- The upstream backend may return `503` with `{ "error": "database_unavailable", "trace_id": "...", "path": "..." }` and `Retry-After: 5` when the recognition service cannot acquire a database connection.
- The WordPress proxy preserves that overload state as HTTP `503` with `{ "error": "backend_overloaded", "retry_after": 5 }` and a matching `Retry-After` header instead of degrading it to an empty success payload.
- The proxied backend no longer leaks raw exception class names or messages in generic `500` responses.
- Tenant-context setup occurs in the backend session dependency; the job-status handler does not repeat tenant setup after the session has already been prepared.
- Completed clustering responses may include `snapshot_version`, `source_job_id`, `projection_acknowledged_at`, and an optional `projection_payload`.
- `projection_payload` mirrors the backend cluster-delta shape for `since_version=0`. When present and `projection_acknowledged_at` is null, the plugin may project local state directly from this job-status response instead of issuing a second snapshot or delta fetch.
- The plugin still falls back to `POST /recognition/sync/trigger` semantics when `projection_payload` is absent or version-mismatched.

## GET /recognition/jobs/{job_id}/stream

Stream job progress via SSE. Emits `progress` events with `{ completed, total, status }`
and a terminal `done` event with `{ status }`. The WordPress proxy polls job status
and forwards events to the client.

## POST /recognition/jobs/{job_id}/cancel

Cancel a running scan job (proxy to `/recognition/jobs/{job_id}/cancel`).

## GET /recognition/batch-runs

List recent durable batch runs for the current tenant. Reads tenant-scoped rows from `acx_batch_runs` via `BatchRunRepository::list_recent_runs`; does not proxy to the recognition service.

Query params:

- `limit` (optional): integer 1–10, default `5`. Out-of-range values clamp to the bounds.

Permission callback: `can_manage_recognition`.

Response:

```json
{
  "items": [
    {
      "run_id": "run-1",
      "latest_job_id": "job-1",
      "latest_job_status": "completed",
      "child_job_ids": ["job-1"],
      "submitted_total": 1,
      "accepted_total": 1,
      "completed_total": 1,
      "failed_total": 0,
      "cancelled_total": 0,
      "terminal_state": true,
      "failed_batches": [],
      "created_at": "2025-01-01 00:00:00",
      "updated_at": "2025-01-01 00:00:01"
    }
  ]
}
```

Notes:

- Backs the dashboard "Recent Activity" panel with durable, tenant-scoped provenance (`provenance: 'durable_batch_run'`); falls back to browser-local job ids only when this route is unavailable or empty (`provenance: 'browser_local_fallback'` / `'unavailable'`).
- TypeScript shape mirrored at `apps/prototype-wp-alt-context/js/admin/api/recognition/types/scan.ts` (`RecentBatchRunsResponse`, `RecentBatchRunActivity`). No shared-contracts schema yet; lift to `packages/shared-contracts/schemas/` if a second consumer needs codegen parity.

## POST /recognition/cluster

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

## POST /recognition/clusters/recover-orphans

> **Backend-only** -- no WordPress proxy route exists for this endpoint.

Re-cluster orphaned identities (direct call to `/recognition/clusters/recover-orphans`).

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

## GET /recognition/clusters

List clusters (local-first via sovereign projection).

Machine-readable schema: [recognition-cluster-list-response.schema.json](../../../packages/shared-contracts/schemas/recognition-cluster-list-response.schema.json)

Query params:

- `limit` (default 50, max 500)
- `offset` (default 0)
- `labeled_only` (`true` or omitted)
- `search` (optional substring filter for labels)

Response (envelope):

```json
{
  "clusters": [
    {
      "id": "b43c2ab2-8d4f-42a8-9b2d-7f1d2e5a9b7a",
      "label": "Alice",
      "label_state": "person",
      "is_auto_label": false,
      "identity_count": 5,
      "member_ids": [
        "0a7b8331-bb7f-40c1-8f24-8c7e2b2d7c4f",
        "0db4d66d-2d7b-4454-8ad4-954e469c0a33"
      ],
      "representative_identity": {
        "media_id": 101,
        "bbox": { "x": 45, "y": 60, "width": 120, "height": 120 }
      },
      "sample_identities": [
        {
          "identity_id": "0a7b8331-bb7f-40c1-8f24-8c7e2b2d7c4f",
          "media_id": 101,
          "similarity": 0.98,
          "confidence": 0.98,
          "clustering_pending": false,
          "bbox": { "x": 45, "y": 60, "width": 120, "height": 120 },
          "thumb_url": "https://example.test/uploads/101-thumb.jpg",
          "media_url": "https://example.test/uploads/101.jpg"
        }
      ]
    }
  ],
  "limit": 50,
  "total": 123,
  "truncated": true
}
```

Notes:

- The WordPress proxy always returns the envelope `{ clusters, limit, total, truncated }` on this route. The only compatibility carve-out is a legacy bare-array upstream response; in that case the plugin normalizes `limit` from the effective request limit, `total` from the returned row count, and `truncated=false`.
- A partial envelope such as `{ "clusters": [...] }` without `limit`, `total`, or `truncated` is a contract violation. The proxy surfaces that upstream failure as a `502 invalid_cluster_list_envelope` response rather than inventing the missing metadata.
- For unlabeled clusters, `label_state` is `"unlabeled"`. `label` may still be a reserved auto label (`cluster-*` / `cluster_*`) with `is_auto_label: true`; the FE must not synthesize `cluster-<hex>` from a null label.
- `label_state` is the three-valued authority `person | unlabeled | unbound`. `is_auto_label` / `is_labeled` cannot express `unbound`. Cluster detail uses the same summary shape as list items.
- `suggested_label*` fields may be populated for unlabeled clusters.
- `user_confirmed` distinguishes user-curated labels from auto-generated ones.

## GET /recognition/clusters/top-unlabeled

List the largest unlabeled clusters for the naming queue.

Machine-readable schema: [recognition-cluster-top-unlabeled-response.schema.json](../../../packages/shared-contracts/schemas/recognition-cluster-top-unlabeled-response.schema.json)

Query params:

- `limit` (default 10, max 500)

Response (envelope):

```json
{
  "clusters": [
    {
      "id": "b43c2ab2-8d4f-42a8-9b2d-7f1d2e5a9b7a",
      "tenant_id": "a9c2c2c0f6ef4a1f8d6d7a3f6c9b8e12",
      "label": "cluster-a1b2c3d4",
      "label_state": "unlabeled",
      "is_labeled": false,
      "is_auto_label": true,
      "identity_count": 8,
      "user_confirmed": false,
      "suggested_label": "Alice",
      "suggested_label_source": "identity",
      "suggested_label_confidence": 0.91,
      "suggested_target_cluster_id": null,
      "representatives": [
        {
          "id": "8f91f4e7-3ad9-4c31-9a12-9c86e8790e6a",
          "media_id": 101,
          "thumb_url": "https://example.test/uploads/101-thumb.jpg",
          "media_url": "https://example.test/uploads/101.jpg",
          "bbox": { "x": 45, "y": 60, "width": 120, "height": 120 },
          "is_pinned": false
        }
      ]
    }
  ],
  "limit": 10,
  "total": 24,
  "truncated": true,
  "singleton_count": 3,
  "data_source": "local_projection",
  "projection_status": "available"
}
```

Notes:

- The WordPress proxy always returns the canonical envelope `{ clusters, limit, total, truncated, data_source }` on this route.
- Returns clusters from **sovereign local projection** when available.
- When projection is still bootstrapping but the backend queue is reachable, the plugin may return a read-only backend envelope. If the upstream backend still emits a legacy bare array, the proxy normalizes `limit` from the effective request limit, `total` from the returned row count, and `truncated=false` before tagging the response with `data_source: "backend_proxy"`. That fallback is best-effort only: without canonical upstream envelope metadata the proxy cannot detect hidden truncation, so bare-array fallback responses never report `truncated=true`.
- A partial envelope such as `{ "clusters": [...], "limit": 10 }` without `total` or `truncated` is a contract violation. The proxy surfaces that upstream failure as `502 invalid_top_unlabeled_envelope` instead of inventing the missing metadata.
- When local projection is missing and the backend queue is also unavailable, the plugin schedules a bootstrap sync and returns an empty envelope with `limit`, `total: 0`, `truncated: false`, `data_source: "unavailable"`, and `projection_status: "bootstrapping"`.
- `singleton_count` reports the number of single-identity clusters excluded from the naming queue, but only on local-projection / unavailable envelopes where the plugin can source that value honestly.
- `projection_status` is `available` when local projection is readable, `bootstrapping` while the controller has scheduled bootstrap sync, and `unavailable` if a future controller path needs to surface a non-bootstrap projection failure. It is omitted on `backend_proxy` envelopes because those responses did not come from the projection.
- WordPress and TypeScript consumers now treat `clusters`, `limit`, `total`, `truncated`, and `data_source` as canonical envelope metadata. Missing or malformed values are contract errors, not fields to infer locally.
- The controller clamps excessive `limit` requests to the canonical `LIST_TOP_UNLABELED_CLUSTERS_MAX_LIMIT=500` before local or proxied reads, and the response `limit` field reports that effective capped value.
- Clusters with `identity_count < 2`, `is_user_confirmed = true`, or `dismissed_at` set are excluded.

## GET /recognition/clusters/labels

List distinct cluster labels for autocomplete / label search.

Machine-readable schema: [recognition-cluster-labels-response.schema.json](../../../packages/shared-contracts/schemas/recognition-cluster-labels-response.schema.json)

Query params:

- `search` (optional substring filter)
- `limit` (default 50)

Response (envelope):

```json
{
  "labels": ["Alice Example", "Alicia Example"],
  "limit": 2,
  "total": 3,
  "truncated": true
}
```

Notes:

- The WordPress proxy always returns the envelope `{ labels, limit, total, truncated }` on this route.
- When local projection is available, the plugin filters labels by the local `search` substring and clamps the response to the effective `limit` before computing `total` and `truncated`.
- A legacy bare-array upstream response is normalized to the same envelope using the effective request limit, the returned row count as `total`, and `truncated=false`.
- A partial envelope such as `{ "labels": ["Alice"] }` without `limit`, `total`, or `truncated` is a contract violation. The proxy surfaces that upstream failure as a `502 invalid_cluster_labels_envelope` response rather than inventing the missing metadata.

## GET /recognition/clusters/{cluster_id}/members

Return cluster members for one cluster.

Path params:

- `cluster_id` (required)

Response (envelope):

```json
{
  "members": [
    {
      "identity_id": "0a7b8331-bb7f-40c1-8f24-8c7e2b2d7c4f",
      "media_id": 101,
      "similarity": 0.98,
      "confidence": 0.98,
      "clustering_pending": false,
      "bbox": { "x": 45, "y": 60, "width": 120, "height": 120 },
      "thumb_url": "https://example.test/uploads/101-thumb.jpg",
      "media_url": "https://example.test/uploads/101.jpg",
      "cluster_id": "b43c2ab2-8d4f-42a8-9b2d-7f1d2e5a9b7a",
      "cluster_label": "Alice",
      "is_auto_label": false,
      "is_pinned": true,
      "detected_at": null,
      "representative_id": "0a7b8331-bb7f-40c1-8f24-8c7e2b2d7c4f",
      "debug_metrics": null
    }
  ],
  "limit": 500,
  "total": 501,
  "truncated": true
}
```

Notes:

- The WordPress proxy owns the response envelope for this route.
- `limit` is fixed at 500 on the WordPress surface; callers do not control it via query params.
- Local projection reads `total` from the `COUNT(*) OVER() AS total_count` metadata returned by `IdentityMembersRepositoryInterface::list_for_cluster()`, and falls back to `count_for_cluster()` only when that metadata is unavailable. `truncated=true` when the cluster has more members than the capped response includes.
- When the backend proxy returns a bare member array, WordPress wraps it into the same envelope with `limit=500`, `total=<array length>`, and `truncated=false`.
- The matching machine-readable schema is [recognition-cluster-members-response.schema.json](../../../packages/shared-contracts/schemas/recognition-cluster-members-response.schema.json).

## GET /recognition/media-identities

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
        "thumb_url": "https://example.test/uploads/101-thumb.jpg",
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
          "pose_buckets": {
            "filled": 3,
            "total": 13,
            "current_bucket": [0, -1]
          }
        }
      }
    ]
  },
  "data_source": "local_projection"
}
```

Overload response:

```json
{
  "error": "backend_overloaded",
  "retry_after": 5
}
```

Notes:

- When the proxied backend returns `503 database_unavailable`, the WordPress proxy responds with HTTP `503`, `{ "error": "backend_overloaded", "retry_after": <seconds> }`, and forwards `Retry-After`.
- `data_source: "unavailable"` remains the degraded HTTP `200` response only for non-503 upstream failures (for example other `5xx` or transport errors).
- Successful backend-proxy responses must resolve to one canonical envelope: either an upstream `identities_by_media` object or a bare array of identity rows that each include `media_id`. Any other `200` payload shape is rejected with `invalid_media_identities_payload` and HTTP `502`.
- TypeScript consumers now require `data_source` to be present on successful envelopes instead of defaulting missing metadata locally.
- **Label authority (UXW2-4):** human label ⇒ bound person. On the local-projection path, `cluster_label` / `label` is the person name or the auto label. Auto/reserved labels match `DetectsSystemDefinedLabels::is_reserved_label_shape()`: unicode-whitespace trim, then case-insensitive prefix `cluster-` or `cluster_` (`/^cluster[-_]/i`). `Cluster_ab12ef34` is reserved, not a human name. Unbound human labels are not returned as `label` / `cluster_label`.
- **`label_state`:** three-valued authority from `DetectsSystemDefinedLabels::projected_cluster_label_state_sql()` / `resolve_cluster_label_state()` — `person` (bound person name present), `unlabeled` (cluster label empty/null or reserved `/^cluster[-_]/i`), `unbound` (human label with no person bind). Local-projection cluster list, cluster detail, top-unlabeled, identity-members, and media-identities payloads emit it (`ClusterResponseMapper`, `MemberResponseMapper`). Distinct from `is_auto_label` / `is_labeled`, which cannot express `unbound`.

## POST /recognition/clusters/reassign

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

## PATCH /recognition/clusters/{cluster_id}

Update cluster label. The plugin binds a roster person for a human label.

Request body:

```json
{ "label": "Alice" }
```

Local and proxy-success responses include:

```json
{
  "cluster_id": "...",
  "label": "Alice",
  "synced": false,
  "status": "pending",
  "person_id": 12,
  "roster_bound": true
}
```

`person_id` and `roster_bound` are omitted when the mutation is a no-op acknowledgement. A failed backend proxy (non-2xx) does not persist a local person.

`roster_bound` is derived from `ClusterCurationWriter::bind_succeeded()` after the person persist:

- `true` when a local cluster row was updated to that person, or was already bound to that person (`BIND_ALREADY_BOUND`).
- `false` when no local cluster row matched.

On the local path, a genuine bind write failure (`bind_person_to_cluster` returns `false`, including a missing `$wpdb`) is not a `roster_bound: false` flag — it raises HTTP `500` with error code `acx_db_error` before `roster_bound` is written. Do not treat that 500 as a general fail-closed rule for every `roster_bound` writer.

## POST /recognition/clusters/{source_id}/merge

Merge a source cluster into a target.

Request body:

```json
{ "target_cluster_id": "...", "target_label": "Alice" }
```

When `target_label` is a human name, the plugin binds a roster person to the target. A successful local or proxy-success response may include:

```json
{
  "person_id": 12,
  "roster_bound": true
}
```

`roster_bound` is `true` when the target cluster row was updated or already bound to that person (`BIND_ALREADY_BOUND`), and `false` when no local cluster row matched. On the local path, a bind write failure (`false` from `bind_person_to_cluster`) is HTTP `500` `acx_db_error` — it is not reported as `roster_bound: false`. `person_id` is present on the proxy-success path only.

If the target cluster is already bound to a **different** person, the plugin returns HTTP `409` with error code `cluster_already_bound`. Remedy: unbind the target cluster first, then retry the merge.

Response: `ClusterResponse` for the target cluster (plus the `person_id` / `roster_bound` fields above when a label was supplied).

## POST /recognition/clusters/{cluster_id}/split

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

## PATCH /recognition/clusters/{cluster_id}/representatives/{representative_id}/pin

Pin or unpin a representative identity within a cluster.

Request body:

```json
{ "pinned": true }
```

Response: `200` with updated representative object.

Notes:

- Registered in `ClusterMutationsController`.
- Pinned representatives are excluded from automatic representative rotation.

## POST /recognition/clusters/create-for-identity

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

## GET /recognition/identities/{identity_id}/suggestions

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

Overload response:

```json
{
  "error": "backend_overloaded",
  "retry_after": 5
}
```

## GET /recognition/suggestions

List pending assignment suggestions.

Query params:

- `limit` (default 10)
- `offset` (default 0)

Response (envelope):

```json
{
  "suggestions": [
    {
      "id": "...",
      "identity_id": "...",
      "suggested_cluster_id": "...",
      "representative_similarity": 0.92,
      "avg_member_similarity": 0.9,
      "confidence_score": 0.91,
      "resolution": "pending",
      "cluster_label": null,
      "cluster_identity_count": 5,
      "suggested_label": "Alice",
      "suggested_label_source": "identity",
      "suggested_label_confidence": 0.91,
      "identity_media_id": 123,
      "identity_media_url": "https://...",
      "identity_thumb_url": "https://...",
      "identity_bbox": { "x": 10, "y": 20, "width": 120, "height": 120 },
      "representative_media_id": 456,
      "representative_media_url": "https://...",
      "representative_thumb_url": "https://...",
      "representative_bbox": { "x": 14, "y": 18, "width": 118, "height": 118 }
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0,
  "data_source": "backend_proxy"
}
```

Notes:

- `cluster_label` is null for unlabeled clusters; use `suggested_label*` for copy if present.
- `total` reports the number of items in the current page only, derived from the backend array length. The backend does not provide a global total count, so consumers must not treat `total` as server-side pagination metadata.
- When the proxied backend returns `503 database_unavailable`, the WordPress proxy responds with HTTP `503`, `{ "error": "backend_overloaded", "retry_after": <seconds> }`, and forwards `Retry-After`.
- For non-503 upstream failures, the controller still returns `{ "suggestions": [], "total": 0, "limit": <requested>, "offset": <requested>, "data_source": "unavailable" }` with HTTP 200.
- TypeScript type: `PendingSuggestion` in `js/admin/api/recognition/types/suggestion.ts`.
- Field names use `suggested_cluster_id` (not `cluster_id`), `representative_similarity` (not `rep_similarity`), and `*_thumb_url` (not `*_thumbnail_url`).
- TypeScript consumers treat `suggestions`, `total`, `limit`, `offset`, and `data_source` as canonical envelope metadata. Missing or malformed values now fail explicitly instead of falling back to request defaults or list length.

## GET /recognition/suggestions/merge

List pending merge suggestions.

Query params:

- `limit` (default 10)
- `offset` (default 0)

Response (envelope):

```json
{
  "suggestions": [
    {
      "id": "...",
      "cluster_a_id": "...",
      "cluster_b_id": "...",
      "similarity": 0.88,
      "status": "pending",
      "confidence_score": 0.85,
      "cluster_a_label": "Alice",
      "cluster_b_label": null,
      "cluster_a_identity_count": 5,
      "cluster_b_identity_count": 3,
      "cluster_a_representative_thumb_url": "https://...",
      "cluster_b_representative_thumb_url": "https://..."
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0,
  "data_source": "backend_proxy"
}
```

Notes:

- The WordPress proxy wraps the backend's bare-array merge-suggestion response into this envelope.
- `total` reports the number of items in the current page only, derived from the backend array length. The backend does not provide a global total count, so consumers must not treat `total` as server-side pagination metadata.
- When the proxied backend returns `503 database_unavailable`, the WordPress proxy responds with HTTP `503`, `{ "error": "backend_overloaded", "retry_after": <seconds> }`, and forwards `Retry-After`.
- For non-503 upstream failures, the controller still returns `{ "suggestions": [], "total": 0, "limit": <requested>, "offset": <requested>, "data_source": "unavailable" }` with HTTP 200.
- TypeScript consumers treat `suggestions`, `total`, `limit`, `offset`, and `data_source` as canonical envelope metadata. Missing or malformed values now fail explicitly instead of falling back to request defaults or list length.

## GET /recognition/suggestions/name

List pending name suggestions.

Query params:

- `min_confidence` (default 0.0)
- `limit` (default 25)
- `offset` (default 0)

Response (envelope):

```json
{
  "suggestions": [
    {
      "id": "...",
      "cluster_id": "...",
      "suggested_name": "Alice",
      "confidence_score": 0.88,
      "source": "roster",
      "created_at": "2026-03-25T12:00:00Z",
      "expires_at": null,
      "representatives": []
    }
  ],
  "total": 1,
  "limit": 25,
  "offset": 0,
  "data_source": "backend_proxy"
}
```

Notes:

- The WordPress proxy wraps the backend's bare-array name-suggestion response into this envelope.
- `total` reports the number of items in the current page only, derived from the backend array length. The backend does not provide a global total count, so consumers must not treat `total` as server-side pagination metadata.
- `representatives` is optional; current UI types allow it but the proxy may omit it when the backend response does not supply representative context.
- When the proxied backend returns `503 database_unavailable`, the WordPress proxy responds with HTTP `503`, `{ "error": "backend_overloaded", "retry_after": <seconds> }`, and forwards `Retry-After`.
- For non-503 upstream failures, the controller still returns `{ "suggestions": [], "total": 0, "limit": <requested>, "offset": <requested>, "data_source": "unavailable" }` with HTTP 200.
- TypeScript consumers treat `suggestions`, `total`, `limit`, `offset`, and `data_source` as canonical envelope metadata. Missing or malformed values now fail explicitly instead of falling back to request defaults.

## POST /recognition/suggestions/{suggestion_id}/accept

## POST /recognition/suggestions/{suggestion_id}/reject

Accept or reject an assignment suggestion.

## POST /recognition/suggestions/merge/{suggestion_id}/accept

## POST /recognition/suggestions/merge/{suggestion_id}/reject

Accept or reject a merge suggestion.

## POST /recognition/suggestions/name/{suggestion_id}/accept

## POST /recognition/suggestions/name/{suggestion_id}/reject

Accept or reject a name suggestion.

## Known proxy gaps

The following backend endpoints exist but lack WordPress proxy routes:

- `POST /recognition/clusters/recover-orphans` (direct backend call only)

## Related contracts

The WordPress plugin exposes additional REST endpoints outside the `/recognition` proxy path:

- **Sovereign Sync (outbox, conflict, dead-letter, sync health):** [curation-sync-api.md](curation-sync-api.md)
- **Snapshot projection and conflict detection:** [cluster-snapshot-api.md](cluster-snapshot-api.md)
- **Endpoint authorization (capability requirements):** [security.md](security.md)
