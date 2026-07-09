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
    lowercase), `media_id` (int > 0, must equal the part suffix), optional
    legacy `context`, optional typed `context_pack`, and optional `tier` hint
    (`cpu|gpu`). `tier=gpu` routes the request to the server-side GPU profile;
    otherwise the configured default adapter is used.
  - `image_<media_id>` — exactly one image part (`image/jpeg|png|webp`).
- **Upload cap**: `/scene/describe/multipart` is registered with the body-size
  middleware (413 on oversize).

### Response — `VisualFactsResponse` (200)

Machine schema: [`image-description-response.schema.json`](../../../packages/shared-contracts/schemas/image-description-response.schema.json).
All **17** core fields are required; model/provider provenance, tier state, and retention are
unavoidable so future adapters never change the wire:

`tenant_id`, `media_id`, `image_hash`, `context_hash`, `adapter`, `model_id`,
`model_version`, `prompt_or_task_version`, `visual_facts`, `alt_text_draft`,
`context_used`, `provider_disclosure`, `cached`, `duration_ms`,
`retention_class`, `tier`, `result_generation`.

- **Cache key**: `(tenant_id, image_hash, adapter, model_version,
  prompt_or_task_version, context_hash)`. A repeated identical call returns
  `cached=true`.
- `retention_class` ∈ `{retain_all, dispose_after_ack, purge_on_demand}` —
  mirrors the recognition retention vocabulary.
- `provider_disclosure.provider` ∈ `{none, local, hosted}`; seeded/local keep
  bytes inside the service boundary.
- GPU endpoints must be private/loopback/in-tenancy (`ACX_GPU_ENDPOINT_URL`);
  public endpoints fail closed before image bytes are sent.
- `tier` ∈ `{provisional_cpu, final_gpu}`. Inline CPU/local/seeded results use
  `provisional_cpu`; GPU profile results use `final_gpu`. The async path may
  supersede provisional rows later with monotonically increasing
  `result_generation`.
- **Term collision (DOM-03):** response field `tier` is the **compute** tier
  (`provisional_cpu` | `final_gpu`). It is unrelated to the WordPress plugin
  billing option `acx_tier` (`free` | `pro` | … in `trait-batch-limits.php`).
  WP proxy consumers must not conflate the two; the describe proxy passes
  response `tier` through as wire provenance only.
- **Hosted providers are opt-in and fail-closed (E20-11).** A hosted profile
  (e.g. `ACX_DESCRIPTION_ADAPTER=hosted_gpt4o`) resolves to a fail-closed
  unavailable adapter (503) unless the server sets
  `ACX_HOSTED_PROVIDER_OPTIN=1` explicitly; there is no client-side or
  per-request enablement. When a hosted adapter does run, image bytes leave the
  Alt Context service boundary to a third-party subprocessor and the response
  discloses it: `provider_disclosure.provider = "hosted"` and
  `provider_disclosure.left_service_boundary = true`. The default profile
  (`seeded`) and the local Florence profiles never set either. Hosted provider
  keys are server-side deployment secrets (`ACX_HOSTED_PROVIDER_API_KEY`);
  BYOK (customer-supplied keys) is not implemented. The E20-11 governance
  disposition is **`reject`**: the product runs only self-hosted CPU models, so
  no deployment sets the opt-in env and the hosted path stays permanently
  fail-closed unless a future epic-level decision supersedes the memo
  (`docs/tasks/20.0/E20-11-hosted-provider-decision-memo.md`).

#### E19-4a additive optional preview fields

Three **optional** fields (never in the schema `required` set; draft-only —
nothing here writes `_wp_attachment_image_alt`, that write path is E19-2):

- `generic_draft` (`string|null`) — the untouched generic draft (equals `alt_text_draft`).
- `named_draft` (`string|null`) — identity-named draft merging confirmed roster
  identities; identical to `generic_draft` whenever naming is not allowed
  (agreement off, suppressed, ambiguous, low confidence, DB absent). Never a
  guessed name.
- `naming_provenance` (`object|null`) — `injected_names[]` (`name`,
  `cluster_id`, `roster_id`, `detection_confidence` — the face detector's
  score for the matched region, not a face↔phrase match strength),
  `naming_allowed` (bool), `mode` ∈ `{grounded, positional, null}` (span
  replacement vs. appended "Pictured from left" sentence), and `reason` ∈
  `{agreement_disabled, db_unavailable, image_unreadable,
  no_confirmed_identities, no_eligible_identities, ambiguous_grounding,
  merge_error, null}` when the draft stayed generic.

Naming is gated tenant-side by `tenants.naming_agreement_enabled`, the
per-`roster_id` `identity_name_suppressions` list, a **roster requirement**
(an identity without a `roster_id` is never nameable — it would otherwise be
unsuppressable), and a minimum face-detection confidence (0.8).

### Errors

| Status | When |
| --- | --- |
| 400/422 | malformed envelope, >1 image part, missing image part, `media_id` ≠ part suffix |
| 403 | auth tenant claim ≠ envelope `tenant_id` |
| 413 | body exceeds the upload cap |
| 415 | unsupported image MIME |
| 502 | hosted-provider fault (opted-in hosted profile only: provider 5xx/timeout, missing key, malformed body; fail-closed, no partial result) |
| 503 | description adapter unavailable (deferred/stub profile, hosted profile without `ACX_HOSTED_PROVIDER_OPTIN=1`, missing `[vlm]` extra, `tier=gpu` with unset/non-private `ACX_GPU_ENDPOINT_URL`, or explicit `tier=cpu` when no CPU adapter can be resolved) |
| 504 | description generation exceeded the configured timeout |

Error shapes match the recognition routes: 5xx/503 use the `{error, trace_id, path}` envelope (via the shared exception handlers); 4xx validation errors use FastAPI's default `{detail}` shape.

## Backend async route — `POST /scene/describe/async`

The MVP async surface enqueues a single image, immediately schedules a
background worker in the same process, writes a CPU provisional result first,
then supersedes it with GPU final when the GPU endpoint succeeds.

- `POST /scene/describe/async` returns `DescribeJobResult` with `status=queued`
  and `job_id`.
- `GET /scene/describe/jobs/{job_id}` returns `queued|running|provisional|final|degraded|failed`.
- `degraded` means the CPU provisional result is retained after GPU failure.
- Job reads are tenant-scoped; a valid key for another tenant receives 404.
- The in-memory store is bounded and process-local. Production multi-worker
  deployments must either pin this async surface to one worker or replace the
  store with a shared DB/Redis-backed implementation.

## WordPress proxy surface — `POST /acx/v1/recognition/describe`

| Field | Source / authority |
| --- | --- |
| `media_id` (request param) | operator-supplied attachment id |
| `write_alt` (request param, default `false`) | operator write intent for `_wp_attachment_image_alt` |
| `force` (request param, default `false`) | explicit operator override for non-empty existing alt text when `write_alt=true` |
| `request.tenant_id` | `TenantIdentity::resolve` |
| `request.media_id` | echoes the request param (must equal the `image_<id>` part suffix) |
| `request.context_pack.attachment` | bounded attachment title/caption/description/alt text/filename collected from the attachment post and `_wp_attachment_image_alt` |
| `request.context_pack.post` | bounded parent post title/excerpt/type/status; included only when the parent post is public (`publish`) |
| `request.context_pack.taxonomy_terms` | up to 20 public category/tag/product terms for the public parent post |
| `request.context_pack.product` | bounded Woo-style product name/SKU/price when the public parent post type is `product` |
| every response field | **passed through from the backend payload** |
| `alt_text_write` (response field, WP-only) | local write result added only when `write_alt=true`; never sent by the backend scene route |

### Context-pack bounds and privacy

WordPress owns source collection and privacy filtering. The backend validates
the typed object and owns whether/how an adapter applies it.

- Top-level request keys remain `tenant_id`, `media_id`, and `context_pack` for
  new callers; legacy `context` remains accepted by the backend for older
  clients.
- Parent post body content is not sent. Draft/private/non-public parents are
  omitted entirely.
- Strings are length-bounded before leaving WordPress; taxonomy terms are capped
  at 20.
- Missing context is not an error. Adapters must degrade to generic visual facts
  and report `context_used.applied=false`.

**rg-015 (boundary fidelity)**: the proxy MUST trace every envelope field to the
backend payload or a documented local authority. A malformed upstream shape
returns an explicit `502 invalid_description_envelope` — never a fabricated
`cached`/`data_source`/provenance value. No list-pagination fields
(`limit`/`offset`/`total`) on this single-object response.

- **Permission**: `can_manage_recognition` (`manage_options`).
- **Preview default**: when `write_alt` is absent or false, `_wp_attachment_image_alt` and `_acx_description_provenance` are untouched and the backend `VisualFactsResponse` is returned without `alt_text_write`.
- **Write policy**: when `write_alt=true`, missing alt text is written from `alt_text_draft` and generated provenance is stored in `_acx_description_provenance`. Non-empty existing alt text returns `alt_text_write.status="skipped_existing_alt"` unless `force=true`, which returns `forced_overwrite`.
- **Provenance meta**: `_acx_description_provenance` records `adapter`, `model_id`, `model_version`, `prompt_or_task_version`, `image_hash`, `context_hash`, `generated_at`, and `backend_result_id` when supplied by the backend payload.
- **Idempotence**: repeated writes for the same generated tuple preserve matching existing provenance instead of refreshing `generated_at`.

`alt_text_write.status` ∈ `{written, skipped_existing_alt, forced_overwrite}`.

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
