# E15-11. Image Upload Transport (Slice A — multipart-direct + filesystem ObjectStore)

> **Metadata**
>
> - **Date**: 2026-04-25
> - **Author**: Claude Opus 4.7
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-11
> - **Target Branch**: `feature/e15-11-image-upload-transport`
> - **Type**: Implementation task plan (Slice A only; Slice B/OCI gets a separate task plan)
> - **Review Coverage Target**: 2

---

## Objective

Replace the URL-fetch image transport between the WordPress plugin and the description service with a multipart-direct transport, sitting on a backend `ObjectStore` seam whose first implementation writes blobs to a per-job filesystem path. After this slice, a default WordPress install (LocalWP, intranet, or behind a WAF) can submit scans to the hosted Alt Context API without making its media library publicly fetchable.

## Intake

- **Scope one-pager**: [docs/scopes/e15-11-image-upload-transport-scope.md](../../scopes/e15-11-image-upload-transport-scope.md)
- **Key Q&A decisions**: `#2335` (storage seam), `#2336` (OCI is the follow-on target), `#2337` (small predictable batches), `#2338` (URL mode behind `acx_recognition_transport` filter)
- **Planning review**: decision `#2340` `claude_planning_review_e15_11_scope_conditional_pass` — verdict `conditional_pass`; PLAN-01/02/03 fixed before this plan was drafted
- **Not-Doing**: presigned/direct-to-bucket uploads, resumable transfer, client-side resizing, removal of URL transport (kept behind opt-in filter), OCI-backed implementation (Slice B / separate task plan)

## Problem Statement

The recognition service's detector pulls image bytes by HTTP `GET` against `media_url` strings the plugin passes through `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py::analyze_media`. The plugin builds those `media_url` strings from `wp_get_attachment_url()` in `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php::analyze_media` and ships them as JSON via `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php::proxy_request`. If the WordPress site is not publicly resolvable from the hosted API (LocalWP, intranet, behind a WAF), every scan dies before detection because `InsightFaceFaceDetector._fetch_image` cannot reach the URL. This breaks the default install path the public demo depends on (E15 epic, v0.4.0).

## Constraints

- **Greenfield policy applies.** Schema additions go in `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`; no migration chain. No backward-compatibility shim for the request envelope.
- **Plugin boundary.** Only files under `apps/prototype-wp-alt-context/`, `apps/prototype-description-service/`, `docs/`, and `scripts/` may change.
- **Tenant isolation must hold for blob bytes.** A blob written by tenant A under one `job_id`/`media_id` must never be readable by tenant B via id collision or path traversal.
- **No new long-running services or queues.** Slice A reuses the existing `ScanWorker` lifecycle (`apps/prototype-description-service/recognition/worker/scan_worker.py::ScanWorker`).
- **Body-size and concurrency budget.** Per intake `#2337`, a single multipart POST stays under ~25 MB and ~5 image parts; FastAPI/ASGI must reject requests over the cap before fully buffering them.

## Workflow Principles

- **One contract owner per boundary.** The `/recognition/analyze` route owns the transport contract; the plugin proxy adapts to it, not the other way around.
- **No partial implementations.** A slice that adds a multipart endpoint without cleanup or hardening is rejected — both ship in the same slice as the endpoint.
- **Behavior plus proof every slice.** Each slice below produces an executable test artifact (pytest for backend, PHPUnit for plugin, integration smoke for end-to-end).
- **URL transport is opt-in, not deleted.** The URL-fetch path stays in the codebase behind `acx_recognition_transport=url`; the default flips to `multipart`.

## Terminology

- **ObjectStore**: backend protocol with `put(job_id, media_id, bytes) -> uri`, `open(uri) -> BinaryIO`, and `cleanup(job_id) -> None`. Filesystem impl lands in Slice A; OCI impl is the Slice B follow-on task plan.
- **Blob URI**: opaque string returned by `ObjectStore.put(...)`. The detector resolves it via `ObjectStore.open(...)` instead of HTTP `GET`. Format is impl-private (filesystem impl uses `file://` paths under a per-job tempdir).
- **Transport mode**: value of the `acx_recognition_transport` WordPress filter. `multipart` (default) ships bytes inline; `url` keeps the legacy `wp_get_attachment_url()` path for managed-host installs that expose media publicly.
- **Per-blob tenant binding**: invariant that an `ObjectStore` URI written under tenant T's job is only resolvable by detector code running on behalf of tenant T's job. Enforced by namespacing the per-job path under the tenant.

## Current State Analysis

- `analyze_media` (`recognition/interface_adapters/http/routers/analyze.py:260`) accepts `AnalyzeRequest` (JSON only) with `media_items: list[MediaItem]` where each item carries `media_id: int` + `media_url: str`. No multipart variant exists.
- `InsightFaceFaceDetector._fetch_image` (`recognition/application/embedding/detector.py:144`) is the only code path that reads pixel bytes for analysis; it dispatches on whether the source string `startswith("http")`.
- `ScanWorker` (`recognition/worker/scan_worker.py:51`) owns job lifecycle and failure handling; there is no per-job tempdir today (`InsightFaceSettings.cache_dir` is for model weights only).
- `class-analysis-jobs-controller.php::analyze_media` already enforces `get_current_tier_batch_limit()` — an existing batch cap will need to be reconciled with the new ~5-image / ~25 MB multipart unit.
- `class-abstract-recognition-proxy-controller.php::proxy_request` only ever calls `wp_remote_request` with a JSON body; multipart support is greenfield.
- No `acx_recognition_transport` filter exists anywhere in the codebase (verified by `grep`); no name collision.
- `require_auth` (`recognition/interface_adapters/http/deps/auth.py:298`) returns an `AuthContext` with `tenant_claim`; the multipart handler must pass that into the per-job tempdir name to satisfy per-blob tenant binding.

## Target Outcome

A multipart variant of `/recognition/analyze` accepts image parts inline, writes them through an `ObjectStore` protocol whose default impl stores blobs under a per-tenant, per-job filesystem tempdir, and dispatches the existing analysis pipeline using blob URIs instead of public URLs. The plugin's proxy chooses transport via `acx_recognition_transport` (default `multipart`) and submits image bytes from `wp_get_attachment_path()` instead of URLs. Job failure or completion deterministically cleans up the per-job blob directory. The detector's URL fetch path remains in the codebase but is reached only when transport is `url`.

## Context Loading

- Rules: [`docs/agentic/rules/backend-python-guidelines.md`](../../agentic/rules/backend-python-guidelines.md), [`docs/agentic/rules/backend-php-guidelines.md`](../../agentic/rules/backend-php-guidelines.md), [`docs/agentic/rules/development-workflow.md`](../../agentic/rules/development-workflow.md)
- Contracts: [`docs/agentic/contracts/`](../../agentic/contracts/) — confirm whether `/recognition/analyze` has an OpenAPI/JSON-schema fixture that must be updated alongside the route
- Handoff/MCP state: task ref `E15-11-image-upload-transport`; intake decisions `#2335`–`#2338`; planning-review verdict decision `#2340`
- External docs via `ctx7`: not required — FastAPI multipart, Pydantic v2, and `wp_remote_post` multipart usage are stable surfaces in the local toolchain

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|---|---|---|---|---|---|
| `POST /recognition/analyze` | description-service | `AnalyzeRequest` JSON with `media_items[].media_url` | Multipart variant accepting image parts; JSON variant retained for `transport=url` opt-in | No greenfield shim; both content types coexist on the same route via FastAPI content-type dispatch | New pytest under `recognition/tests/api/`; OpenAPI/contract fixture refresh if one exists |
| WP plugin → recognition proxy | plugin (`class-abstract-recognition-proxy-controller.php`) | `wp_remote_request` with JSON | New multipart code path selected by `acx_recognition_transport` filter | No — filter defaults to `multipart`; legacy `url` mode still routes through the existing JSON path | New PHPUnit case for multipart body assembly + filter-driven dispatch |
| `acx_recognition_transport` filter | plugin | (does not exist) | New filter, values `multipart` (default) or `url` | N/A — net-new surface | Filter test asserting both branches |
| `ObjectStore` protocol | description-service | (does not exist) | New protocol + filesystem impl | N/A — net-new surface | Unit tests for `put`/`open`/`cleanup` semantics + tenant-binding invariant |

No DB schema change is anticipated; if blob metadata persistence is needed, the column lands in `001_identity_schema.py` per greenfield policy.

## Proposed Solution

A new ASGI-level multipart handler on the existing `POST /recognition/analyze` route accepts a multipart body with: a JSON `request` part (the existing `AnalyzeRequest` envelope minus `media_url`), and one image part per `media_id`. The handler streams each part through `ObjectStore.put(job_id, media_id, bytes)`, attaches the resulting blob URI to the corresponding `MediaItem`, and dispatches the analysis pipeline unchanged. `InsightFaceFaceDetector._fetch_image` is split into `_fetch_image_url` (legacy) and `_open_image_blob` (uses `ObjectStore.open`); the dispatch on `startswith("http")` becomes a dispatch on whether the source is a blob URI.

The filesystem `ObjectStore` impl writes to `<settings.blob_root>/<tenant_id>/<job_id>/<media_id>.bin` and exposes a `cleanup(job_id)` method that the worker invokes from both the success path (`process_scan_job_inline`) and the failure path (`ScanWorker._scan_handler`'s exception branches). Per-blob tenant binding is enforced by the path layout: a request authenticated as tenant T can only write under `<blob_root>/T/...` and the detector resolves URIs scoped to the active job's tenant only.

The plugin's `proxy_request` learns a `body_kind` parameter (`json` default, `multipart` opt-in). `class-analysis-jobs-controller.php::analyze_media` reads `apply_filters('acx_recognition_transport', 'multipart')`; on `multipart` it switches to `wp_get_attachment_path()` for each `media_id`, builds a multipart body with one part per image plus a JSON request part, and dispatches through `proxy_request(..., body_kind='multipart')`. On `url` it preserves the existing JSON-with-URLs payload.

Hardening (per scope MVP bullet, line 23 of scope note):

- Body-size cap enforced at the ASGI layer (Starlette `MAX_REQUEST_SIZE`-equivalent middleware) before the handler buffers anything; default 25 MB; configurable via `RECOGNITION_MAX_UPLOAD_BYTES`.
- MIME validation: reject any image part whose `Content-Type` is not in `{image/jpeg, image/png, image/webp}` (configurable list); reject zero-byte parts.
- Per-blob tenant binding: enforced by the path-layout invariant above and asserted in a dedicated test.

## Files and Surfaces to Change

| Surface | File | Change |
|---|---|---|
| backend (route) | `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py` | Add multipart variant of `analyze_media`; wire body-size cap and MIME validation |
| backend (schema) | `apps/prototype-description-service/recognition/interface_adapters/http/schemas/requests.py` | Add `blob_uri: str | None` to `MediaItem`; mark `media_url` and `blob_uri` as mutually exclusive |
| backend (storage seam) | `apps/prototype-description-service/recognition/application/storage/__init__.py` (new), `.../storage/object_store.py` (new), `.../storage/filesystem.py` (new) | Define `ObjectStore` Protocol + filesystem impl |
| backend (detector) | `apps/prototype-description-service/recognition/application/embedding/detector.py` | Split `_fetch_image` into URL and blob branches; dispatch on URI scheme |
| backend (worker cleanup) | `apps/prototype-description-service/recognition/worker/scan_worker.py`, `recognition/application/tasks/scan.py` | Invoke `ObjectStore.cleanup(job_id)` on both success and failure paths |
| backend (config) | `apps/prototype-description-service/recognition/config/settings.py` | Add `blob_root: Path`, `max_upload_bytes: int`, `allowed_upload_mime_types: list[str]` settings |
| backend (DI) | `apps/prototype-description-service/recognition/interface_adapters/http/deps/` | Provide `ObjectStore` via FastAPI dependency |
| backend (tests) | `apps/prototype-description-service/recognition/tests/api/test_analyze_multipart.py` (new), `.../tests/application/test_object_store_filesystem.py` (new) | Endpoint hardening + protocol invariant tests |
| plugin (proxy) | `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` | Teach `proxy_request` to accept `body_kind='multipart'`; build multipart body via `wp_remote_post` `body` array |
| plugin (controller) | `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php` | Read `acx_recognition_transport` filter; on `multipart` switch to `wp_get_attachment_path()` and multipart dispatch |
| plugin (tests) | `apps/prototype-wp-alt-context/tests/api/AnalysisJobsControllerTransportTest.php` (new) | Cover filter dispatch + multipart body assembly + URL fallback |
| docs (contract) | `docs/agentic/contracts/` | Add or update the `/recognition/analyze` contract entry to describe both content-type variants |

## Related Files

| File | Note |
|---|---|
| `apps/prototype-description-service/recognition/application/scan/scan_queue_service.py` | Job creation path; may need to pass `tenant_id` into the cleanup call site |
| `apps/prototype-wp-alt-context/src/admin/class-settings-page.php` | Future home of an admin toggle for transport mode (out of scope for this slice; filter-only override for now) |
| `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` | Greenfield landing zone if any blob-metadata column is required; current design needs none |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && pyenv exec python -m pytest recognition/tests/api/test_analyze_multipart.py recognition/tests/application/test_object_store_filesystem.py -q`
  - `cd apps/prototype-wp-alt-context && composer test -- --filter AnalysisJobsControllerTransportTest`
- Runtime-parity / environment checks:
  - `cd apps/prototype-description-service && pyenv exec uvicorn recognition.main:app --port 8001` then `curl -F 'request=@req.json;type=application/json' -F 'image_42=@./fixture.jpg'` against the new multipart endpoint with a known-good auth header
- Contract/fixture verification:
  - If a `/recognition/analyze` fixture exists under `docs/agentic/contracts/`, refresh it in the same slice as the route change
- Manual verification:
  - Submit a scan from a LocalWP install pointed at the dev backend with `acx_recognition_transport=multipart` (default); confirm completion. Toggle filter to `url`; confirm legacy path still works against a publicly-reachable site.

## Slice Delivery

### Slice 1: Backend ObjectStore + multipart endpoint + worker cleanup

**Goal**: Land the backend half end-to-end: the `ObjectStore` protocol, filesystem impl, multipart variant of `/recognition/analyze`, hardening (body-size cap + MIME validation + per-blob tenant binding), and deterministic cleanup wired into both success and failure worker paths.

Changes:

- New `recognition/application/storage/object_store.py` (Protocol) and `filesystem.py` (impl) under `apps/prototype-description-service/`
- Add multipart branch to `analyze.py::analyze_media`; add ASGI body-size middleware + MIME guard
- Split `detector.py::_fetch_image` into URL and blob branches dispatched by URI scheme
- Wire `ObjectStore.cleanup(job_id)` into `scan_worker.py::ScanWorker._scan_handler` (success + exception paths) and `tasks/scan.py::process_scan_job_inline`
- Tests: `test_analyze_multipart.py` (happy path, oversize-body 413, bad-MIME 415, missing-image part 422, tenant-A cannot fetch tenant-B blob), `test_object_store_filesystem.py` (put/open/cleanup contract + tenant-path invariant)
- Update `docs/agentic/contracts/` entry (or add one) for the dual-content-type route

Proof:

- `cd apps/prototype-description-service && pyenv exec python -m pytest recognition/tests/api/test_analyze_multipart.py recognition/tests/application/test_object_store_filesystem.py -q` exits 0 with the multi-part suite green
- Local `curl` multipart submission against a `uvicorn`-launched service returns `202` and the resulting job completes; the per-job tempdir is gone after completion (verified by `ls`)

### Slice 2: Plugin transport switch + `acx_recognition_transport` filter + URL fallback

**Goal**: Land the plugin half: the filter, the multipart body assembly in the proxy, the `wp_get_attachment_path()` switch in the analysis-jobs controller, and the legacy URL path retained behind `acx_recognition_transport=url`.

Changes:

- Add `body_kind` parameter to `class-abstract-recognition-proxy-controller.php::proxy_request`; build multipart `body` array for `wp_remote_post` when `body_kind='multipart'`
- Read `apply_filters('acx_recognition_transport', 'multipart')` in `class-analysis-jobs-controller.php::analyze_media`; on `multipart`, swap `media_url` for `wp_get_attachment_path()` reads and dispatch through the new multipart proxy path
- Reconcile `get_current_tier_batch_limit()` with the ~5-image / ~25 MB multipart cap (smaller of the two wins; document the resolution in code comment)
- New `tests/api/AnalysisJobsControllerTransportTest.php`: filter dispatch (multipart vs url), body-array shape, missing-attachment-path graceful-degrade

Proof:

- `cd apps/prototype-wp-alt-context && composer test -- --filter AnalysisJobsControllerTransportTest` exits 0
- `composer phpcs` and `composer phpstan` (or whichever gates `make check-all` runs) stay green

### Slice 3: End-to-end LocalWP→dev-backend smoke + telemetry

**Goal**: Prove the whole path works against the dev backend from a LocalWP install (the original failure mode), and add the minimum log fields needed to diagnose transport failures.

Changes:

- Structured log fields on the multipart route: `transport=multipart`, `parts_count`, `total_bytes`, `tenant_id`, `job_id` (no PII)
- Plugin-side log entry on transport selection (`acx_recognition_transport=multipart|url`) and on multipart-dispatch failure
- Manual smoke procedure documented in this task plan: exact `curl` and LocalWP steps that must pass before merge
- Optional: `scripts/test_acx_backend_image_contract.py` extension to exercise the multipart endpoint against the dev backend

Proof:

- LocalWP install pointed at dev backend completes a 5-image scan via multipart with default filter setting
- `dev` log stream shows the new structured fields for the run
- Filter set to `url` against a publicly-reachable site still completes (URL fallback honored)

## Consolidated Checklist

> Checklist describes work being delivered, not finding status. Finding status is queried via `review_findings(review={"operation":"list","status":"open","task_ref":"E15-11-image-upload-transport"})`.

## Context and Ownership

- [ ] Loaded backend-python, backend-php, and development-workflow rules before editing
- [ ] Confirmed `/recognition/analyze` contract surface in `docs/agentic/contracts/` (refresh in Slice 1 if a fixture exists)
- [ ] Confirmed no `ctx7` fetch is needed for FastAPI multipart, Pydantic v2, or `wp_remote_post`

### Checklist for Slice 1: Backend ObjectStore + multipart endpoint + worker cleanup

- [ ] `ObjectStore` Protocol defined and filesystem impl lands with `put`/`open`/`cleanup`
- [ ] `analyze.py::analyze_media` accepts multipart with body-size cap + MIME validation
- [ ] `detector.py` resolves blob URIs through `ObjectStore.open` instead of HTTP GET
- [ ] Worker invokes `ObjectStore.cleanup(job_id)` on both success and failure paths
- [ ] New pytest suites cover happy path, 413, 415, 422, and tenant-binding invariant
- [ ] Contract fixture for `/recognition/analyze` updated in the same slice if one exists

### Checklist for Slice 2: Plugin transport switch + `acx_recognition_transport` filter + URL fallback

- [ ] `class-abstract-recognition-proxy-controller.php::proxy_request` supports `body_kind='multipart'`
- [ ] `class-analysis-jobs-controller.php::analyze_media` reads `acx_recognition_transport` and dispatches accordingly
- [ ] Tier batch limit reconciled with the ~5-image / ~25 MB multipart cap (and noted in code)
- [ ] PHPUnit covers both filter branches and the multipart body-array shape
- [ ] `composer phpcs` + `composer phpstan` green

### Checklist for Slice 3: End-to-end smoke + telemetry

- [ ] Structured log fields added on both backend route and plugin transport-select branch
- [ ] LocalWP→dev-backend manual smoke documented and executed
- [ ] URL fallback verified against a publicly-reachable site

## Review Readiness

- [ ] Every slice ships behavior plus proof (no scaffold-only slices)
- [ ] Contract fixture and route change land in the same slice
- [ ] Per-blob tenant binding has a dedicated test (not just an inferred invariant)
- [ ] Cleanup is wired into both success and failure paths, not just one
- [ ] Handoff decision recorded for each slice with rationale, verification, and contract implications

## Stretch Goals

- [ ] Compress `wp_get_attachment_path()` reads through `imagepalette` resize before upload (defer to v0.4.1; not in this slice)
- [ ] Per-tenant rate limit on the multipart endpoint (defer to security follow-on)

## Success Criteria

- [ ] A LocalWP install pointed at the hosted Alt Context API can submit a 5-image scan over multipart with no public-URL exposure of WordPress media, and the scan completes
- [ ] The `acx_recognition_transport=url` opt-in path continues to work against a publicly-reachable site (no regression)
- [ ] Per-job blob directory is empty after every scan completes or fails (no permanent storage residue)
- [ ] No tenant-A request can read or reference a blob written by tenant B, asserted by a dedicated test
- [ ] The `ObjectStore` protocol surface is the only seam Slice B (OCI) needs to swap; no plugin-side change is required for Slice B
