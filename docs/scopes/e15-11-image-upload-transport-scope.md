# E15-11. Image Upload Transport (multipart-direct + ObjectStore seam)

> **Status**: scope (intake recorded 2026-04-24)
> **Task ref**: `E15-11-image-upload-transport`
> **Parent epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../epics/v0.4.0/public-demo-launch-readiness-epic.md) (E15)
> **Branch**: `feature/e15-11-image-upload-transport`
> **Worktree**: `context-alt-text-monorepo-e15-11-image-upload-transport`
> **MCP intake decisions**: `#2335`, `#2336`, `#2337`, `#2338`

## Problem

The current recognition flow assumes the backend can fetch every image from a public URL. In the description service, the detector still fetches bytes over HTTP from a `media_url`. In the WordPress plugin, scan submission still goes through the shared recognition proxy and the analysis jobs controller by posting URL-based media items to `/recognition/analyze`.

That breaks the default LocalWP and private-site case: if the WordPress `siteurl` is not publicly resolvable from the hosted API, scans fail before detection starts. This conflicts with the product requirement that a normal WordPress install should be able to point at the hosted Alt Context API and work without tunnels, DNS edits, or public media hosting.

## MVP scope

This scope note defines the outcome and boundaries for the next planning stage; it does not lock the implementation contract.

- The plugin must be able to submit image bytes directly to the backend instead of relying on backend reachability to a public `media_url`.
- The backend change must introduce a storage seam so slice A can land with a local implementation and a follow-on slice can swap in OCI object storage without changing the plugin-facing workflow.
- The default transport should favor the out-of-the-box path for LocalWP and other non-public installs; URL transport can remain as an explicit opt-in path if the task plan shows it is still needed.
- The slice-A task plan must specify upload-endpoint hardening: a per-request body-size cap, MIME/extension validation restricted to image content types, and per-blob tenant binding (a blob uploaded by tenant A must not be referenceable by tenant B via media-id collision). Long-term abuse controls — per-tenant rate limits, presigned/signed uploads, virus scanning — remain follow-on work.
- The slice-A task plan must define a deterministic cleanup path for blobs whose owning job fails, errors, or is abandoned mid-batch so a single failed scan does not leave permanent storage residue. Long-term retention policy and bucket lifecycle rules remain follow-on work and ship with Slice B (OCI).
- Batch sizing, endpoint shape, retry policy, telemetry fields, and exact service limits are task-plan concerns and must be validated there instead of being fixed in the scope note.
- Success means removing tunnel, DNS, and public-host requirements for ordinary WordPress installs targeting the hosted Alt Context API.

## Decisions (intake)

Recorded as MCP decisions on `E15-11-image-upload-transport`:

- `#2335` -- **Storage seam from day one.** Introduce an `ObjectStore` boundary in the first implementation slice so the follow-on OCI-backed slice is a backend swap, not a plugin-contract refactor.
- `#2336` -- **OCI Object Storage is the follow-on target.** The immediate implementation can start with a simpler storage backend, but the seam must make OCI the next step.
- `#2337` -- **Uploads should use small, predictable batches.** Keep failure units bounded; confirm the exact batch and body-size limits in the task plan.
- `#2338` -- **Keep URL mode behind `acx_recognition_transport`.** Default the product toward direct upload while preserving an explicit opt-in path for public-URL deployments if the implementation still needs it.

## Success criteria

1. The follow-on task plan can define one concrete implementation slice that lets a LocalWP install submit scans to the hosted API without exposing WordPress uploads over a public URL.
2. The plan keeps the storage boundary explicit so a later OCI-backed implementation is a backend swap rather than a plugin-contract rewrite.
3. The scope stays limited to transport reachability and the minimum observability needed to prove it works; optimizations such as presigned uploads, resumable transfer, or client-side resizing remain follow-on work.

## Not-doing

- No detailed API contract, pseudocode, file-by-file implementation inventory, or test matrix in this scope note; those belong in the task plan.
- No commitment yet to exact batch counts, body-size caps, tempdir layout, bucket names, lifecycle policies, or PHP transport internals.
- No direct-to-bucket presigned uploads, resumable or chunked transfer, client-side resizing, or removal of the URL transport in this scope stage.

## Assumptions

- The blocker is transport reachability, not a recognition-model defect.
- The hosted API remains the service boundary the plugin talks to; this work does not move detection into WordPress.
- Any new upload path must still respect the tenant and auth boundaries already enforced by the existing proxy flow.

## Next step

Draft the slice-A task plan on `feature/e15-11-image-upload-transport`, using the intake decisions above to specify the endpoint contract, storage implementation, plugin submission path, cleanup, telemetry, and verification.
