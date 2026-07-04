---
title: Image Description API
boundary_owner: backend
status: draft
since: E19-1
machine_schema: ../../../packages/shared-contracts/schemas/image-description-response.schema.json
related:
  - recognition-clustering.md
---

# Image Description API

> **Scope**: one-image visual-facts description. Declared **separately** from the
> recognition `/analyze` surface. The PDS-26 wire-locked recognition response
> (`recognition-clustering.md`) is **never** extended with caption/visual-facts
> fields — this is a new `scene` router, not a recognition change.

## Backend route — `POST /scene/describe/multipart`

Synchronous for the seeded adapter (deterministic, instant). Reuses the
recognition multipart/auth/object-store transport.

- **Auth**: `require_write_access` (admin key or tenant-scoped key), `X-Api-Key`.
- **Body** (`multipart/form-data`):
  - `request` — JSON `DescribeImageEnvelope`: `tenant_id` (UUID, canonicalized
    lowercase), `media_id` (int > 0, must equal the part suffix), optional inert
    `context`. Adapter selection is server-side in Phase 1.
  - `image_<media_id>` — exactly one image part (`image/jpeg|png|webp`).
- **Upload cap**: `/scene/describe/multipart` is registered with the body-size
  middleware (413 on oversize).

### Response — `VisualFactsResponse` (200)

Machine schema: [`image-description-response.schema.json`](../../../packages/shared-contracts/schemas/image-description-response.schema.json).
All **15** fields are required; model/provider provenance and retention are
unavoidable so future adapters never change the wire:

`tenant_id`, `media_id`, `image_hash`, `context_hash`, `adapter`, `model_id`,
`model_version`, `prompt_or_task_version`, `visual_facts`, `alt_text_draft`,
`context_used`, `provider_disclosure`, `cached`, `duration_ms`, `retention_class`.

- **Cache key**: `(tenant_id, image_hash, adapter, model_version,
  prompt_or_task_version, context_hash)`. A repeated identical call returns
  `cached=true`.
- `retention_class` ∈ `{retain_all, dispose_after_ack, purge_on_demand}` —
  mirrors the recognition retention vocabulary.
- `provider_disclosure.provider` ∈ `{none, local, hosted}`; seeded/local keep
  bytes inside the service boundary.

### Errors

| Status | When |
| --- | --- |
| 400/422 | malformed envelope, >1 image part, missing image part, `media_id` ≠ part suffix |
| 403 | auth tenant claim ≠ envelope `tenant_id` |
| 413 | body exceeds the upload cap |
| 415 | unsupported image MIME |

Error shapes match the recognition routes: 5xx/503 use the `{error, trace_id, path}` envelope (via the shared exception handlers); 4xx validation errors use FastAPI's default `{detail}` shape.

## WordPress proxy surface — `POST /acx/v1/recognition/describe`

| Field | Source / authority |
| --- | --- |
| `media_id` (request param) | operator-supplied attachment id |
| `request.tenant_id` | `TenantIdentity::resolve` |
| `request.media_id` | echoes the request param (must equal the `image_<id>` part suffix) |
| `request.context` | WordPress inert bag `{site_url, title, caption, description, filename}` — nested under the single `context` key because the backend `DescribeImageEnvelope` is `extra='forbid'` (no extra top-level keys); inert in Phase 1 |
| every response field | **passed through from the backend payload** |

**rg-015 (boundary fidelity)**: the proxy MUST trace every envelope field to the
backend payload or a documented local authority. A malformed upstream shape
returns an explicit `502 invalid_description_envelope` — never a fabricated
`cached`/`data_source`/provenance value. No list-pagination fields
(`limit`/`offset`/`total`) on this single-object response.

- **Permission**: `can_manage_recognition` (`manage_options`).
- No alt-text write in Phase 1; `_wp_attachment_image_alt` is untouched (Phase 2 / E19-2).

## WordPress dry-run surface — `GET /acx/v1/recognition/describe/candidates`

Read-only selection source for later description generation and write commands.
This route does **not** call `/scene/describe/multipart` and does not mutate
attachment meta.

Query params:

| Field | Default | Meaning |
| --- | --- | --- |
| `limit` | `50` | Candidate page size, clamped by the service maximum. |
| `offset` | `0` | Offset after missing-alt filtering. |

Response fields:

| Field | Meaning |
| --- | --- |
| `candidates` | Page of image attachments with empty `_wp_attachment_image_alt`, sorted by ascending media id. |
| `exclusions` | Attachments skipped by the same selection scan with machine-readable `reason`. |
| `limit`, `offset` | Normalized pagination inputs used for `candidates`. |
| `total_candidates`, `total_exclusions` | Totals before candidate pagination. |

Candidate/exclusion row fields: `media_id`, `filename`, `title`, `mime_type`,
`current_alt_text`, `reason`.

`reason` ∈ `{missing_alt, has_alt_text, unsupported_mime}`.
