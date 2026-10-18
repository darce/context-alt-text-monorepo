# Workbench Media API Contract

Canonical owner: `wp-proxy`

## GET /acx/v1/recognition/media-identities

The `identities_by_media` envelope groups identities by media ID. Each identity may additionally carry:

- `person_id?: string | null`: stringified `acx_persons.id` bound to the identity's cluster; null when unbound.
- `representative_face?: { identity_id: string; media_id: number | null; media_url: string | null; attachment_url?: string | null; bbox: { x: number; y: number; width: number; height: number } | null } | null`: the cluster representative member's face, which may belong to another attachment. The URLs and bbox are resolved together in the served image's coordinate space. Null means the representative member could not be resolved.

Both fields are optional; absence means unresolved. Local projection responses emit both fields, while backend proxy responses preserve them only when supplied upstream. Existing identity fields retain their semantics.

This contract documents the WordPress workbench media endpoint consumed by the React admin UI for deferred row enrichment. The runtime owner is the REST surface under `apps/prototype-wp-alt-context/src/api/`.

## GET /acx/v1/workbench/media/detail

Deferred attachment enrichment for the workbench page. The client uses this endpoint after the initial workbench table load to fetch MIME type, dimensions, and XMP persistence details for the current page of media rows.

Query parameters:

- `ids[]` or `ids`: array of attachment IDs.
- Maximum IDs enriched per request: `100`. Additional valid IDs are counted in `total` and omitted from `details_by_media` when `truncated` is `true`.

Response (envelope):

```json
{
  "details_by_media": {
    "11": {
      "id": 11,
      "mimeType": "image/jpeg",
      "updatedAt": "2026-04-29T00:00:00+00:00",
      "dimensions": {
        "width": 1200,
        "height": 800
      },
      "xmpPersistence": {
        "status": "persisted",
        "updated_at": "2026-04-29T00:00:00+00:00"
      }
    }
  },
  "limit": 100,
  "total": 1,
  "truncated": false
}
```

Field semantics:

- `details_by_media`: object keyed by attachment ID string.
- `limit`: the canonical request cap enforced by `MediaDetailController::MAX_MEDIA_IDS_PER_REQUEST`.
- `total`: total count of valid requested attachment IDs before truncation.
- `truncated`: `true` when more than `limit` valid IDs were requested and only the first `limit` were enriched.

Notes:

- Invalid or non-positive IDs are discarded before `total` is computed.
- The React admin consumer treats `details_by_media`, `limit`, `total`, and `truncated` as canonical metadata. Missing or malformed values are contract violations and fail explicitly.
- Machine-readable schemas: `packages/shared-contracts/schemas/workbench-media-detail.schema.json` and `packages/shared-contracts/schemas/workbench-media-detail-response.schema.json`.
