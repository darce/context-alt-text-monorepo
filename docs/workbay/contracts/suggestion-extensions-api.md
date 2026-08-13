---
title: Suggestion Extensions API
status: draft
boundary_owner: backend
description: Phase 0 contract for extending the existing suggestion system with name suggestions, confidence filtering, bulk accept, and expiry metadata.
---

# Suggestion Extensions API

## Purpose

This contract extends the existing suggestion surface instead of introducing a parallel machine-proposals subsystem.

- Route owner: recognition service (`apps/prototype-description-service`)
- Consumers:
  - WordPress plugin proxy (`apps/prototype-wp-alt-context/src/api`)
  - React admin suggestion review UI (`apps/prototype-wp-alt-context/js/admin`)

## Scope

This phase defines the request/response shapes for:

- name suggestion listing and resolution
- confidence-aware suggestion filtering
- bulk accept across suggestion types
- expiry metadata on pending suggestions

## Routes

- `GET /recognition/suggestions`
- `GET /recognition/suggestions/merge`
- `GET /recognition/suggestions/name`
- `POST /recognition/suggestions/{suggestion_id}/accept`
- `POST /recognition/suggestions/{suggestion_id}/reject`
- `POST /recognition/suggestions/merge/{suggestion_id}/accept`
- `POST /recognition/suggestions/merge/{suggestion_id}/reject`
- `POST /recognition/suggestions/name/{suggestion_id}/accept`
- `POST /recognition/suggestions/name/{suggestion_id}/reject`
- `POST /recognition/suggestions/bulk-accept`

## Query Parameters

List endpoints may accept:

- `min_confidence` (`0.0` to `1.0`, optional)
- `limit` (optional)
- `offset` (optional)

## Name Suggestion Shape

```json
{
  "id": "4b6d1b27-8c0d-4d3b-b7d0-3f1d17a8e2f9",
  "cluster_id": "b43c2ab2-8d4f-42a8-9b2d-7f1d2e5a9b7a",
  "suggested_name": "Daniel",
  "confidence_score": 0.91,
  "source": "identity",
  "created_at": "2026-03-19T12:00:00Z",
  "expires_at": "2026-03-26T12:00:00Z",
  "representatives": [
    {
      "id": "7c1e9a44-2f0b-4c8d-9a11-5e6f7a8b9c0d",
      "media_id": "101",
      "thumb_url": "/recognition/face-thumbs/job-42/101?x=12&y=8&width=40&height=30",
      "media_url": "/recognition/blobs/job-42/101",
      "bbox": { "x": 12, "y": 8, "width": 40, "height": 30 },
      "is_user_selected": false
    }
  ]
}
```

`representatives` uses the same `RepresentativeResponse` shape as `ClusterResponse.representatives`
(and frontend `TopUnlabeledRepresentative`). Empty list when the cluster has none — never null.
Accept/reject name-suggestion endpoints return the same full shape, including `representatives`.

Representative field notes:

- `media_id` (`string | null`): identity media id when known (stringified int); `null` when the
  joined identity has no media id. Never fabricated to `0`.
- `is_user_selected` (`boolean`): wire name for the user-pinned representative flag (Python field
  `is_pinned` aliases to this). Clients must not expect `is_pinned` on the wire.

## Bulk Accept Request

```json
{
  "suggestion_type": "assignment",
  "min_confidence": 0.85
}
```

Allowed `suggestion_type` values:

- `assignment`
- `merge`
- `name`

## Bulk Accept Response

```json
{
  "accepted_count": 12,
  "skipped_count": 3
}
```

## Extension Rules

- Existing assignment and merge suggestion responses may add:
  - `confidence_score`
  - `expires_at`
  - `source_job_id`
- Clients must tolerate these fields being `null` during rollout.
- Accepting a name suggestion applies the label to the target cluster and marks the suggestion resolved.
- Rejected suggestions remain auditable and should not be silently deleted.

## Error Contract

- `400`: invalid filter values or invalid bulk request payload
- `404`: suggestion not found
- `409`: suggestion is no longer pending
- `422`: suggestion cannot be applied because its target state changed

## Client Expectations

- WordPress proxy exposes matching passthrough routes rather than redefining business logic.
- Frontend types should be added in Phase 0 even before the backend endpoints are fully implemented.
- Expiry and bulk-accept UI should treat unsupported server behavior as a feature-gap, not a fatal client error.
