# Task Plan

> **Metadata**
>
> - **Date**: 2026-06-13
> - **Author**: Claude Opus 4.8 (claude-opus-4-8)
> - **Owning Epic**: [docs/epics/v0.5.0/context-aware-image-description-epic.md](../../epics/v0.5.0/context-aware-image-description-epic.md)
> - **Epic Short ID**: E19
> - **Target Branch**: `feature/e19-1`
> - **Review Coverage Target**: 2

---

## E19-1. Headless Description Foundation

## Objective

Deliver the smallest end-to-end image-description loop: a synchronous backend route that returns deterministic, provenance-bearing visual facts for one uploaded image; a WordPress path that roundtrips one existing attachment through it; and a local-CPU VLM adapter (Florence-2) behind isolated optional deps, benchmarked on the OCI A1 host. Seeded-first — the contract and seeded adapter are provable before any model code lands.

## Intake

- **Scope one-pager / roadmap**: [docs/roadmaps/context-aware-image-description-roadmap-2026-06-13.md](../../roadmaps/context-aware-image-description-roadmap-2026-06-13.md) (Phase 1 + Phase 2; candidate epics D1, D2, D3).
- **Source assessment**: [docs/assessments/current/privacy-trust-and-vlm-fit-investigation-2026-06-13.md](../../assessments/current/privacy-trust-and-vlm-fit-investigation-2026-06-13.md) (Florence-2 on OCI A1 CPU recommendation).
- **Scope intake decision**: `MAINT-public-demo-vlm-scope` (handoff).
- **Not-Doing (this task)**: no admin UI; no bulk generation; no alt-text write to `_wp_attachment_image_alt` (Phase 2 / E19-2); no BYOK or hosted-provider adapter; no context-aware *scoring* (WP context is inert transport only); no `force`/cache-bypass field in the Phase-1 wire.

## Problem Statement

The product promise is better image descriptions, but no description contract exists. The backend has recognition scan/cluster/storage/retention but no visual-facts route; the `scene/` package is an empty placeholder (one health stub, a stale orphan `.pyc`). The plugin can proxy recognition and upload bytes but cannot request descriptions. Description must reuse recognition's transport/auth/retention without coupling to the wire-locked `/recognition/analyze` envelope (PDS-26), and any model runtime must stay off the request path and out of the recognition-only default build so the live OCI deployment is unaffected.

## Constraints

- **Greenfield**: schema changes go directly into the single baseline migration `db/migrations/versions/001_identity_schema.py`. No follow-on migration, no backward-compat shim.
- **No `/recognition/analyze` extension**: description is a new `scene` router mounted at `/scene`; the recognition analyze response shape is never given caption/visual-facts fields (roadmap line 60; PDS-26 wire lock).
- **Seeded-first ordering**: the `DescriptionAdapter` protocol + seeded adapter + full contract land and pass (S1–S5) before any VLM code (S8–S10). VLM is a swap behind the protocol, never a contract change.
- **No inline model inference on the HTTP request path**: seeded runs synchronously (instant, deterministic); `local_cpu` runs only in a one-worker async path. `async_inline=False` default.
- **VLM dependency isolation**: a new `[vlm]` optional-dependency group only. `uv sync --extra dev` (the default `make install`) and the default Docker `runtime` stage (`.[face]`) must pull zero `torch`/`transformers`. Do **not** reference the dangling `[local]` extra that the InsightFace error string mentions but pyproject does not define.
- **rg-015 boundary fidelity**: the WP describe proxy must trace every envelope field to the backend payload or a documented local authority; a malformed upstream shape returns an explicit `502 invalid_description_envelope` — never fabricated `cached`/`data_source`/provenance. No list-pagination fields on a single-object response.
- **rg-016 PHP autoload parity**: new `class-*.php` / `interface-*.php` are not PSR-4 autoloadable; wire them through explicit `require_once` from the controller's header block and from `class-api.php`, verified with a runtime `class_exists` check.
- **Provenance is unavoidable**: the response JSON schema declares all 15 fields (including model/provider provenance and `retention_class`) as required up front; the seeded adapter fills expansion fields with typed placeholders so future adapters never change the wire.

## Workflow Principles

- Each slice is one vertical path with behavior + proof; no scaffold-only slices.
- The cache key is exactly `(tenant_id, image_hash, adapter, model_version, prompt_or_task_version, context_hash)` as a `UniqueConstraint`; `context_hash` is canonical-JSON of the normalized context so key reordering never fragments the cache.
- WordPress `wp_context` (title/caption/description/filename) is sent as **inert transport** in Phase 1; the seeded adapter is not gated or scored on consuming it (context-aware differentiation is E19-4).
- Description audit events reuse the existing `AuditEvent` sink with namespaced `description.*` event types (`description.generated`, `description.cache_hit`) so the feed stays filterable.

## Terminology

- **Visual facts**: structured, inspectable observations about an image (caption, region/object labels, optional OCR) returned before final prose.
- **Seeded adapter**: deterministic, model-free `DescriptionAdapter` whose output is a stable function of `sha256(image_bytes + versions + context_hash)` over checked-in fixtures.
- **`context_used`** (response): typed echo of the context the adapter actually consumed — pinned shape `ContextUsed {sources: list[str], applied: bool}`; the seeded adapter returns `sources=[], applied=false` (empty-but-typed) in Phase 1. Distinct from `wp_context` (request input).
- **`context_hash`**: cache-key dimension AND response field (included so the cache key is auditable on the wire → 15 response fields).
- **`retention_class`**: reuses the recognition retention `StrEnum` so export/purge machinery stays uniform; S1 **imports** that existing enum into the `scene` domain rather than defining parallel tokens.

## Current State Analysis

- Works: recognition multipart transport (`analyze_multipart.py`), per-tenant `ObjectStore` seam, `require_write_access` auth, optional-session DB degradation, `MetricsMiddleware`, `UploadSizeLimitMiddleware` (path-scoped to `/recognition/analyze/multipart`), baseline migration with RLS table lists, `AuditEvent` sink. Plugin has `AbstractRecognitionProxyController` (JSON/multipart proxy, tenant headers, retry/circuit, body-size cap), `AnalyzeMediaService` (attachment byte-read + multipart dispatch), and `localwp-batch-run-smoke`.
- Missing/drifting: `scene/` is empty (health stub + orphan `.pyc` only — do not import the dead `health_router`); no description schema/route/adapter/cache; no plugin describe controller/service/smoke; no `[vlm]` extra (and an InsightFace error string references a non-existent `[local]` extra — do not propagate it); no benchmark fixture (`infra/oci/demo/seed/media/` holds only `.gitkeep`).

## Target Outcome

`POST /scene/describe/multipart` accepts one `image_<media_id>` part + a JSON `request` envelope, returns a typed `VisualFactsResponse` (15 fields) synchronously for the seeded adapter, caching by the six-tuple and writing a `description.generated`/`description.cache_hit` audit event. WordPress `POST /acx/v1/recognition/describe` resolves one attachment, reads bytes, attaches inert `wp_context`, dispatches multipart to the backend route, and returns the visual facts unchanged. `make localwp-describe-run-smoke` proves first-call `cached=false` then repeat `cached=true` against a real LocalWP attachment, emitting evidence JSON. A `local_cpu` Florence-2 adapter exists behind the same protocol, isolated in `[vlm]`, run only by a one-worker async describe worker, with an OCI A1 benchmark + decision memo.

## Context Loading

- Rules: [docs/workstate/rules/backend-python-guidelines.md](../../workstate/rules/backend-python-guidelines.md), [docs/workstate/rules/backend-php-guidelines.md](../../workstate/rules/backend-php-guidelines.md), [docs/workstate/rules/testing-python.md](../../workstate/rules/testing-python.md)
- Contracts: [docs/workstate/contracts/recognition-clustering.md](../../workstate/contracts/recognition-clustering.md) (PDS-26 wire lock; do not extend), [docs/workstate/contracts/clustering-api.md](../../workstate/contracts/clustering-api.md) (`data_source`/`502 invalid_*_envelope` precedent)
- Code anchors: `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze_multipart.py`, `.../application/storage/object_store.py`, `.../deps/{auth,object_store,session}.py`, `db/models/jobs.py`, `db/migrations/versions/001_identity_schema.py`, `apps/prototype-wp-alt-context/src/api/{class-abstract-recognition-proxy-controller.php,services/class-analyze-media-service.php,class-api.php}`, `scripts/localwp/batch-run-smoke.php`
- Handoff/MCP: task `E19-1`; planning findings under `plan-analyze-*`/planning-review sessions.
- External via `ctx7`: only for Florence-2 / `transformers` `trust_remote_code` load semantics during S9.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `/scene/describe/multipart` | backend | none (new) | new `docs/workstate/contracts/image-description-api.md` + `packages/shared-contracts/schemas/image-description-response.schema.json` | no (greenfield) | route tests; JSON-schema validation; OpenAPI shows route |
| `/recognition/analyze` envelope | backend | `recognition-clustering.md` (PDS-26 wire-locked) | **none** (must not extend) | n/a | test asserts analyze response shape unchanged |
| `/acx/v1/recognition/describe` | wp-proxy | none (new) | new proxy surface section in the description contract; rg-015 provenance | no | PHPUnit fake-host body shape; `502 invalid_description_envelope` on bad upstream |
| multipart / `ObjectStore` transport | backend | `analyze_multipart.py` + `ObjectStore` Protocol | reuse unchanged | no | route happy/negative tests |
| `image_descriptions` table + RLS | backend | `001_identity_schema.py` baseline | add table to baseline + RLS lists (greenfield) | no (no new migration) | migration applies on fresh DB; `EXPECTED_SCHEMA_TABLES` self-check; schema-parity grep |
| `[vlm]` optional deps | backend | pyproject extras (`dev`/`face`/`gpu`) | add `vlm` extra (out of default) | no (isolated) | default install/Docker pull zero `torch` |

## Proposed Solution

Build the `scene` package as the description home: domain enums + frozen value objects, pure hashing helpers, a `runtime_checkable` `DescriptionAdapter` Protocol with a `SeededDescriptionAdapter` implementation, an `ImageDescription` cache/provenance model + repository, a DB-optional `VisualFactsService`, and a synchronous `/scene/describe/multipart` route mounted at `/scene` reusing recognition's auth/multipart/object-store deps and registered in the upload-size cap. Add description Prometheus counters (`description.request`/`cache_hit`/`adapter_latency`). On the WordPress side, add a `DescribeController` + `DescribeMediaService` + narrow `DescribeHostInterface` and a headless `describe-run-smoke` + Makefile target. Finally, add the `[vlm]` extra, `VlmSettings` caps, a `LocalCpuDescriptionAdapter` (+ `UnavailableDescriptionAdapter` fail-closed), a one-worker `describe_worker`, an optional `runtime-vlm` Docker stage, and an OCI A1 benchmark CLI + decision memo. The route handles seeded synchronously (S5); the `local_cpu` async-enqueue branch and its `describe.py` edit are owned by S9 (explicit dual ownership of `describe.py`).

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend domain | `apps/prototype-description-service/scene/domain/description.py` | `DescriptionAdapterKind`/`RetentionClass`/`ProviderMode` StrEnums + frozen `VisualFacts` |
| backend app | `scene/application/{hashing,description_adapter,seeded_adapter,visual_facts_service,description_repository}.py` | hashing helpers, Protocol, seeded adapter, DB-optional use case, repository |
| backend http | `scene/interface_adapters/http/{router,deps}.py`, `.../routers/describe.py`, `.../schemas/{requests,responses}.py` | scene router, DI, sync route, request/response schemas (15 fields) |
| backend config | `scene/config/settings.py`, `scene/application/settings/vlm.py` | `DescriptionSettings`, `VlmSettings` caps |
| backend db | `db/models/scene.py`, `db/models/__init__.py`, `db/migrations/versions/001_identity_schema.py` | `ImageDescription` model + baseline table + RLS lists |
| backend main | `api/main.py` | mount `scene_router` at `/scene`; add `/scene/describe/multipart` to upload-size paths; description metrics |
| backend vlm | `scene/infrastructure/vlm/{florence_local_adapter,unavailable_adapter,__init__}.py`, `scene/worker/describe_worker.py` | local-CPU adapter, fail-closed fallback, one-worker async path |
| backend deps | `pyproject.toml`, `Dockerfile`, `Makefile`, `.env.prod.example` | `[vlm]` extra + mypy override; optional `runtime-vlm` stage; `vlm-install`/`vlm-benchmark`; documented env keys |
| backend bench | `scripts/benchmark_local_vlm.py`, `scene/tests/seed/florence_bench_image.jpg` | A1 benchmark CLI + deterministic fixture |
| contracts | `docs/workstate/contracts/image-description-api.md`, `packages/shared-contracts/schemas/image-description-response.schema.json` | new backend + WP-proxy contract + machine schema; cross-ref (not extend) `recognition-clustering.md` |
| plugin api | `apps/prototype-wp-alt-context/src/api/class-describe-controller.php`, `interface-describe-host.php`, `services/class-describe-media-service.php`, `class-api.php` | describe controller/service/interface + explicit require + registration |
| plugin smoke | `apps/prototype-wp-alt-context/scripts/localwp/describe-run-smoke.php`, `Makefile` | headless one-image smoke + `localwp-describe-run-smoke` target |
| memo | `docs/tasks/19.0/E19-1-local-cpu-vlm-benchmark-decision-memo.md` | OCI A1 runbook + fallback decision (S10) |

## Related Files

| File | Note |
| --- | --- |
| `recognition/interface_adapters/http/routers/analyze_multipart.py` | envelope + part parsing + tenant-mismatch guard to reuse |
| `recognition/infrastructure/embeddings/__init__.py` | `Unavailable*` + singleton + `_retry_after` pattern to mirror; source of the dangling `[local]` extra string to avoid |
| `recognition/worker/scan_worker.py` | bulkhead/one-worker pattern the describe worker mirrors |
| `apps/prototype-wp-alt-context/src/api/services/class-analyze-media-service.php` | attachment byte-read + `MULTIPART_MAX_BYTES` (25MB) cap to reuse |
| `apps/prototype-wp-alt-context/Makefile` (`localwp-batch-run-smoke`) | guard block (empty `WP_PATH`, missing `wp-load.php`, non-local refusal) to copy verbatim |

## Verification Strategy

- Deterministic tests:
  - `uv run pytest apps/prototype-description-service/scene/tests -q` (hashing, seeded adapter, repository, service, route, vlm settings; heavy Florence load gated behind a pytest marker so default CI stays torch-free)
  - `composer test` in the plugin (DescribeMediaService body shape against a fake host; `502` on malformed envelope)
- Runtime-parity / environment:
  - `make localwp-describe-run-smoke` against the live LocalWP install (first `cached=false`, repeat `cached=true`); both negative guards (missing `WP_PATH`, missing `wp-load.php`) exit 1
  - `php -r "require 'vendor/autoload.php'; var_export(class_exists('AltContext\\Api\\DescribeController'));"` prints `true` without `composer dump-autoload` (rg-016)
  - migration applies on a fresh DB; `pip list | grep -E 'torch|transformers'` empty after default `make install`
  - `make vlm-benchmark` on the OCI A1 host (latency vs <20s, peak RSS vs cap, CPU%); recognition `/health` + Postgres stay responsive
- Contract/fixture verification:
  - sample response validates against `image-description-response.schema.json` with all 15 provenance fields required
  - OpenAPI exposes `/scene/describe/multipart`; a test asserts `/recognition/analyze` response shape is unchanged
- Manual verification:
  - operator runs `make localwp-describe-run-smoke` and inspects the emitted evidence JSON (source attachment title/filename, image_hash, first/second cached, duration_ms, adapter, model_id)

## Slice Delivery

### Slice 1 (S1): Typed visual-facts contract + hashing primitives

**Goal**: Land the 15-field request/response schema + pure key computation, reviewable before any transport/DB/model coupling (satisfies the roadmap "Description output contract review" gate).

Changes:
- `scene/domain/description.py`, `scene/interface_adapters/http/schemas/{requests,responses}.py` (`extra='forbid'`, typed `provider_disclosure`/`context_used` submodels, `retention_class` StrEnum), `scene/application/hashing.py`, `scene/config/settings.py`
- `docs/workstate/contracts/image-description-api.md` + `packages/shared-contracts/schemas/image-description-response.schema.json` (all 15 fields required)

Proof:
- `uv run pytest apps/prototype-description-service/scene/tests/test_hashing.py -q` — identical bytes → identical `image_hash`; context key reordering → identical `context_hash`
- Pydantic round-trip asserts exactly the 15 fields and rejects an extra provenance field; JSON-schema validation of a sample response

### Slice 2 (S2): Seeded `DescriptionAdapter` behind a `runtime_checkable` Protocol

**Goal**: Deterministic, model-free adapter + the canonical Protocol that both seeded and (later) `local_cpu` import — provable product loop with zero VLM risk.

Changes:
- `scene/application/{description_adapter,seeded_adapter}.py`, `scene/tests/fixtures/seeded_visual_facts.json`

Proof:
- `uv run pytest apps/prototype-description-service/scene/tests/test_seeded_adapter.py -q` — same `(bytes, context, versions)` → byte-identical output; bumped `prompt_or_task_version` → different output; `isinstance(SeededDescriptionAdapter(), DescriptionAdapter)`; runs with no DB/network

### Slice 3 (S3): `ImageDescription` model + baseline migration + repository

**Goal**: Persist results keyed by the six-tuple so repeats are cache hits and provenance is auditable.

Changes:
- `db/models/scene.py`, `db/models/__init__.py`, `db/migrations/versions/001_identity_schema.py` (add table + `UniqueConstraint` + tenant index; append to `TENANT_TABLES`/`EXPECTED_SCHEMA_TABLES`/`DOWNGRADE_TABLE_ORDER`), `scene/application/description_repository.py`

Proof:
- `uv run pytest apps/prototype-description-service/scene/tests/test_description_repository.py -q` on aiosqlite — insert then `get_by_cache_key` hit; differing `context_hash` is a miss
- schema-parity cross-check (model cols == migration cols == repository cols) via terminal grep (rg-010); migration applies on fresh DB; `image_descriptions` in `EXPECTED_SCHEMA_TABLES`; RLS policy applies (`tenant_id` like `jobs.py`)

### Slice 4 (S4): `VisualFactsService` orchestration (DB-optional) + description metrics

**Goal**: Wire validate → hash → cache-read → adapter → persist → audit → duration; degrade to adapter-only when the session is `None`; emit Prometheus counters.

Changes:
- `scene/application/visual_facts_service.py`, `scene/interface_adapters/http/deps.py`, description Prometheus counters `acx_description_requests_total` / `acx_description_cache_hits_total` / `acx_description_adapter_duration_seconds` via the existing metrics registry (the surface behind `MetricsMiddleware`)

Proof:
- `uv run pytest apps/prototype-description-service/scene/tests/test_visual_facts_service.py -q` — first call `cached=false` + row persisted + `description.generated` AuditEvent; identical second call `cached=true` with no second adapter invocation (call-count assertion); DB-down path returns adapter result `cached=false, persisted=false`; `duration_ms` ≥ 0 on hit and miss

### Slice 5 (S5): Synchronous `/scene/describe/multipart` route + mount + body-size cap

**Goal**: Expose the one-image seeded endpoint, separate from `/recognition/analyze`, reusing auth/multipart/object-store transport and registering the upload cap.

Changes:
- `scene/interface_adapters/http/{router,routers/describe}.py`, `api/main.py` (mount at `/scene`; add `/scene/describe/multipart` to `UploadSizeLimitMiddleware` paths)
- `describe.py` is created here for the **seeded synchronous** path only; the `local_cpu` async-enqueue branch is a later edit owned by S9.

Proof:
- `uv run pytest apps/prototype-description-service/scene/tests/test_describe_route.py -q` — happy path 200 returns all 15 fields `cached=false`, immediate repeat `cached=true`; 2 image parts → 422; `media_id` envelope ≠ part suffix → 422; tenant mismatch → 403; no image part → 422; unsupported MIME → 415; oversize → 413
- OpenAPI exposes `/scene/describe/multipart` (401 without key); test asserts `/recognition/analyze` response shape unchanged

### Slice 6 (S6): WordPress describe controller + single-image service + REST route

**Goal**: WordPress resolves one attachment, reads bytes, attaches inert `wp_context`, and dispatches multipart through the existing proxy to the S5 backend route. Depends on S5; gated behind the S1 contract review sign-off.

Changes:
- `src/api/class-describe-controller.php` (extends `AbstractRecognitionProxyController`; `POST acx/v1 /recognition/describe`; permission `can_manage_recognition`/manage_options), `src/api/services/class-describe-media-service.php` (dispatches to **`/scene/describe/multipart`**, `MULTIPART_MAX_BYTES` 25MB), `src/api/interface-describe-host.php`, `src/api/class-api.php` (explicit `require_once` + register)

Proof:
- `composer test` — `DescribeMediaService` with a fake host asserts single-image multipart body (`image_<id>` part + `request` envelope with `tenant_id`/`site_url`/`wp_context`), mime resolution, unreadable/missing-file `WP_Error`, over-cap `WP_Error`; malformed upstream payload → explicit `502 invalid_description_envelope` (rg-015, no fabricated metadata)
- `php -r "require 'vendor/autoload.php'; var_export(class_exists('AltContext\\Api\\DescribeController'));"` → `true` without `composer dump-autoload` (rg-016); `make check-php` passes

### Slice 7 (S7): Headless one-image LocalWP describe smoke + Makefile target

**Goal**: A scriptable headless smoke proves a real LocalWP attachment roundtrips S6→S5 and returns stable visual facts (Phase-1 exit-criteria proof), refusing non-local / missing `WP_PATH`.

Changes:
- `scripts/localwp/describe-run-smoke.php` (selects one image attachment or honors a `MEDIA_ID` arg; asserts first `cached=false` then `cached=true` by natural repeat — no `force` field), `Makefile` `localwp-describe-run-smoke` (guard block copied verbatim from `localwp-batch-run-smoke`)

Proof:
- `make localwp-describe-run-smoke` with no `WP_PATH` exits 1; path lacking `wp-load.php` exits 1; non-local siteurl refused before dispatch
- against the live install: evidence JSON shows `first_cached=false` then `second_cached=true`, `image_hash`/`adapter`/`model_id` populated, **source attachment title/filename** included, exit 0

### Slice 8 (S8): `[vlm]` extras isolation + `VlmSettings` caps (no model, no default-runtime impact)

**Goal**: Add the optional dependency group and runtime caps without touching the recognition-only default build/install — isolation proven up front. Independent of S1–S7 except the `DescriptionAdapter` protocol; can start once S2 lands.

Changes:
- `pyproject.toml` (`vlm = [transformers, torch, einops, timm, accelerate]` out of `dev`/`face`/`gpu`; mypy `ignore_missing_imports` for `transformers.*`/`torch.*`), `scene/application/settings/vlm.py`, `recognition/config/settings.py` (read caps via `get_settings()`, default `adapter_mode='seeded'`), `Makefile` (`vlm-install`), `.env.prod.example`

Proof:
- `make install` (default `uv sync --extra dev`) → `pip list | grep -E 'torch|transformers'` empty
- `uv run pytest apps/prototype-description-service/scene/tests/test_vlm_settings.py -q` — defaults `adapter_mode=='seeded'`, `async_inline False`, `worker_concurrency 1`, `max_image_edge_px 1024`; mypy passes with the override and without vlm deps installed

### Slice 9 (S9): `LocalCpuDescriptionAdapter` behind the S2 protocol + async describe worker

**Goal**: Florence-2-base-ft CPU adapter conforming to the S2 protocol, with downsample/timeout/fail-closed caps, run only in a one-worker async path so the request path never executes the model. Depends on S2 (protocol) + S8 (extras/settings). Owns the `describe.py` `local_cpu` async-enqueue branch.

Changes:
- `scene/infrastructure/vlm/{florence_local_adapter,unavailable_adapter,__init__}.py`, `scene/worker/describe_worker.py`, `scene/interface_adapters/http/routers/describe.py` (add the `adapter_mode==local_cpu` → enqueue branch), `Dockerfile` (optional `runtime-vlm` stage with `.[vlm]`; default `runtime` stays `.[face]`)

Proof:
- `uv run pytest apps/prototype-description-service/scene/tests/test_florence_local_adapter.py -q` — `isinstance(..., DescriptionAdapter)`; missing `[vlm]` raises `RuntimeError` naming `[vlm]`; load failure → `UnavailableDescriptionAdapter`; `runtime_mode=='test'` short-circuit; downsample cap applied (heavy load behind a marker)
- with `ACX_DESCRIPTION_ADAPTER=local_cpu` + `async_inline=False`, the route enqueues and the worker produces the result; request path makes no model call
- default `runtime` Docker stage builds torch-free; `runtime-vlm` stage builds with `.[vlm]`

### Slice 10 (S10): OCI A1 benchmark CLI + fallback decision memo

**Goal**: Measure one seeded 1024px image on the live A1 host and record the keep-seeded / enable-local-CPU / defer-to-hosted-GPU decision. The objective go/no-go gate is latency (<20s) / peak RSS / CPU only; output quality is a qualitative note in the decision memo, not a gate.

Changes:
- `scripts/benchmark_local_vlm.py`, `scene/tests/seed/florence_bench_image.jpg`, `Makefile` (`vlm-benchmark`), `docs/tasks/19.0/E19-1-local-cpu-vlm-benchmark-decision-memo.md`; tick the roadmap Phase-2 checklist items

Proof:
- `make vlm-benchmark` emits JSON with cold-load time, per-image wall latency vs <20s, peak RSS vs cap, CPU% on the A1 host; refuses without `[vlm]`
- decision memo records the chosen fallback with captured latency/memory/CPU/quality numbers; recognition `/health` + Postgres stay responsive during the run

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [ ] Confirmed `ctx7` is needed only for Florence-2 / `transformers` load semantics in S9.
- [ ] Recorded boundary ownership: new `/scene/describe/multipart` + WP `/acx/v1/recognition/describe`; `/recognition/analyze` untouched.

### Checklist for Slice 1 (S1): contract + hashing

- [ ] Domain enums + request/response schemas (15 fields, `extra='forbid'`) in `scene/domain/description.py` + `scene/interface_adapters/http/schemas/`
- [ ] Pure hashing helpers in `scene/application/hashing.py`
- [ ] `docs/workstate/contracts/image-description-api.md` + `packages/shared-contracts/schemas/image-description-response.schema.json` (all 15 required)
- [ ] `uv run pytest scene/tests/test_hashing.py -q` + schema validation green

### Checklist for Slice 2 (S2): seeded adapter + protocol

- [ ] `DescriptionAdapter` Protocol + `SeededDescriptionAdapter` + fixtures in `scene/application/`
- [ ] `uv run pytest scene/tests/test_seeded_adapter.py -q` green (determinism + protocol conformance)

### Checklist for Slice 3 (S3): cache/provenance persistence

- [ ] `ImageDescription` model + baseline-migration table + RLS lists + repository
- [ ] `uv run pytest scene/tests/test_description_repository.py -q` + fresh-DB migration + schema-parity grep green

### Checklist for Slice 4 (S4): service + metrics

- [ ] `VisualFactsService` (DB-optional) + description Prometheus counters
- [ ] `uv run pytest scene/tests/test_visual_facts_service.py -q` green (cache hit, no second adapter call, DB-down degrade)

### Checklist for Slice 5 (S5): backend route

- [ ] Synchronous `/scene/describe/multipart` route + `/scene` mount + upload-size cap entry
- [ ] `uv run pytest scene/tests/test_describe_route.py -q` green; `/recognition/analyze` shape asserted unchanged

### Checklist for Slice 6 (S6): WordPress describe path

- [ ] `DescribeController` + `DescribeMediaService` + `DescribeHostInterface` + explicit `require_once`/registration in `class-api.php`
- [ ] `composer test` + `class_exists` runtime check + `make check-php` green; `502 invalid_description_envelope` on malformed upstream

### Checklist for Slice 7 (S7): LocalWP smoke

- [ ] `scripts/localwp/describe-run-smoke.php` + `localwp-describe-run-smoke` Makefile target (verbatim guard block)
- [ ] `make localwp-describe-run-smoke` evidence JSON shows first `cached=false` then `cached=true` + source attachment; both negative guards exit 1

### Checklist for Slice 8 (S8): vlm extras isolation

- [ ] `[vlm]` extra + mypy override + `VlmSettings` caps + `vlm-install` + documented env keys
- [ ] Default install torch-free (`pip list | grep` empty) + `uv run pytest scene/tests/test_vlm_settings.py -q` green

### Checklist for Slice 9 (S9): local-CPU adapter + worker

- [ ] `LocalCpuDescriptionAdapter` + `UnavailableDescriptionAdapter` + `describe_worker` + `describe.py` enqueue branch + optional `runtime-vlm` Docker stage
- [ ] `uv run pytest scene/tests/test_florence_local_adapter.py -q` green; request path makes no model call; default Docker stage torch-free

### Checklist for Slice 10 (S10): A1 benchmark + decision

- [ ] `scripts/benchmark_local_vlm.py` + seed fixture + `vlm-benchmark` target + decision memo
- [ ] `make vlm-benchmark` JSON captured; decision recorded; recognition health unaffected

## Review Readiness

- [ ] No boundary-touching slice merged without matching contract/doc/fixture evidence; S6 starts only after S1's contract + JSON schema pass review with a recorded decision.
- [ ] Runtime-parity checks present where unit tests can mask behavior: LocalWP smoke (S7), `class_exists` autoload (S6), fresh-DB migration (S3), torch-free default install (S8), A1 benchmark (S10).
- [ ] Handoff decision records each slice's change, verification, and contract implications.

## Stretch Goals

- [ ] `force`/cache-bypass field on the describe envelope (deferred from Phase-1 wire; would re-trigger a miss on demand).
- [ ] Perceptual `image_hash` (pillow/imagehash already present) instead of raw-bytes sha256.

## Success Criteria

- [ ] One existing LocalWP attachment roundtrips through the backend and returns 15-field visual facts JSON (`make localwp-describe-run-smoke`).
- [ ] A repeated seeded call returns `cached=true` (natural repeat, no `force`).
- [ ] Generated output always carries adapter/model/provider provenance + `retention_class`; the JSON schema rejects an untyped provenance field.
- [ ] The recognition-only default install and live OCIR image remain torch-free; the `local_cpu` adapter exists behind the same protocol and never runs on the request path.
- [ ] An OCI A1 benchmark + decision memo records whether local CPU inference is viable for the demo.
