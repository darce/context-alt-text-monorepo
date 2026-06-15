# Context-Aware Image Description Roadmap

> **Status:** Roadmap seed for later epic/task decomposition.
> **Date:** 2026-06-13
> **Source inputs:** [privacy-trust-and-vlm-fit-investigation-2026-06-13.md](../assessments/current/privacy-trust-and-vlm-fit-investigation-2026-06-13.md), [recognition-privacy-hybrid-roadmap-2026-03-06.md](recognition-privacy-hybrid-roadmap-2026-03-06.md), [roadmap-v4.md](roadmap-v4.md), [e15-11-image-upload-transport-scope.md](../scopes/e15-11-image-upload-transport-scope.md), AltText.ai WordPress feature review.
> **Decomposition target:** future release epic(s) under `docs/epics/`, then executable task plans under `docs/tasks/`.

---

## Objective

Turn Alt Context from a recognition/curation prototype into a context-aware image description service that can produce accessibility-ready visual facts and alt-text drafts from WordPress media, using site-owned context, roster-confirmed identities, and auditable privacy controls.

The first implementation should prove the smallest useful loop:

1. read an existing image attachment from the current WordPress install,
2. send image bytes to the hosted/backend service through the existing authenticated proxy shape,
3. return deterministic seeded visual facts for the demo path,
4. cache and record provenance for the generated result,
5. optionally write or preview the result without introducing a new UI.

## Problem Statement

Alt Context has strong recognition and curation foundations, but the product promise is still incomplete. The user-visible value is not face clustering by itself; it is better image descriptions because the system knows site context, media context, and human-reviewed identity context.

The current app state shows the gap:

- The Python backend has recognition scan, clustering, object storage, retention, metrics, and health surfaces, but no dedicated image-description or visual-facts contract.
- The WordPress plugin can list media by missing alt text, proxy recognition requests, upload image bytes through multipart transport, and run LocalWP batch smokes, but it does not request or persist generated image descriptions.
- The `scene` package exists as a placeholder, which is a natural home for visual description use cases, but it is not yet wired into HTTP routes or workers.
- Existing roadmap language already warns that the MVP is hosted privacy-minimized processing, not self-hosted recognition. Description generation must preserve that positioning.
- Public benchmarks such as AltText.ai set user expectations around "install plugin, paste API key, alt text appears"; Alt Context must meet the workflow basics while differentiating on context, visual facts, and auditable privacy.

## Product Positioning

Alt Context should not compete as a generic "AI writes alt text" wrapper. The positioning should be:

> Alt Context generates inspectable visual facts and alt-text drafts for site-owned media, enriched by WordPress context and human-reviewed roster context, with explicit retention, purge, export, and provider-disclosure controls.

This keeps the product anchored in three defensible traits:

- **Context:** use WordPress attachment/post/product data and roster-confirmed names, not only pixels.
- **Auditability:** return visual facts, model/provider metadata, cache keys, and retention state, not just a final prose string.
- **Trust:** keep provider mode opt-in and disclose when image bytes leave the Alt Context service boundary.

## Current State Assessment

### Backend

The backend app at `apps/prototype-description-service/` is a FastAPI service with:

- `api/main.py` mounting recognition and roster routers, health, readiness, metrics, upload-size middleware, CORS, version, and auth-gated diagnostics.
- `recognition/interface_adapters/http/router.py` mounting analyze, multipart analyze, blobs, clusters, events, suggestions, diagnostics, media, retention, and tenant routes.
- `recognition/interface_adapters/http/routers/analyze_multipart.py` accepting multipart `image_<media_id>` parts, storing bytes through an `ObjectStore`, creating scan jobs, and scheduling background work.
- `recognition/application/storage/` containing the object-store seam needed for private/local WordPress images.
- `recognition/interface_adapters/http/routers/retention.py` and related domain services for export, purge, and audit-oriented retention behavior.
- `scene/` package scaffolding only: `application/health.py` and HTTP adapter package init exist, but no description model, route, adapter, worker, or persistence contract yet.
- `pyproject.toml` with Pillow/OpenCV/ONNX/InsightFace dependencies, but no VLM dependencies such as Transformers, Optimum, Florence, or model-specific runtime extras.

Implication: the first description route should reuse backend auth, tenant context, multipart/object-store lessons, metrics, retention language, and job/circuit-breaker patterns. It should not extend the face-recognition `analyze` response with unrelated caption fields.

### WordPress Plugin

The plugin at `apps/prototype-wp-alt-context/` already has:

- media library/query plumbing in `src/api/class-api.php`, including missing-alt detection through `_wp_attachment_image_alt`;
- `src/api/class-abstract-recognition-proxy-controller.php`, which handles authenticated proxying, JSON/multipart bodies, retry/circuit behavior, tenant headers, and payload-size checks;
- `src/api/services/class-analyze-media-service.php`, which resolves attachment ids, reads bytes from the current WordPress install, enforces multipart caps, and dispatches to `/recognition/analyze/multipart`;
- LocalWP smoke infrastructure in `scripts/localwp/batch-run-smoke.php` and `Makefile` targets that prove real WP attachment roundtrips without a new install;
- admin pages for Dashboard, Workbench, Roster, Settings, and Retention;
- frontend API and hooks for recognition workflows, but no description-generation API client or alt-text review/update workflow.

Implication: the MVP should add a narrow description-specific controller/service and headless WP-CLI/eval-file smoke before any admin UI. The existing recognition batch machinery is useful evidence, but the first description path should stay one-image and visual-facts-only.

### Existing Planning Fit

- `roadmap-v4.md` treats alt text generation as a long-term backlog item, not active scope.
- `recognition-privacy-hybrid-roadmap-2026-03-06.md` establishes the right privacy promise: hosted privacy-minimized processing first, optional sovereignty later.
- `privacy-trust-and-vlm-fit-investigation-2026-06-13.md` recommends a local Florence-2 CPU probe for a small demo, but says public APIs will likely win on quality/latency and should be opt-in because they add another processor.
- `e15-11-image-upload-transport-scope.md` and current code have already solved a key table-stakes problem: private/local sites can upload image bytes instead of requiring public image URLs.

## Table Stakes from AltText.ai

AltText.ai's WordPress docs imply a centralized hosted API workflow: connect the plugin with an AltText.ai API key, generate automatically on upload, update a single image, bulk-process missing alt text, use WP-CLI for automation, and upload image bytes directly when a site is private instead of requiring public image URLs. Their account docs also show configurable language, style/detail, formatting, image library review/edit, API key credit limits, and optional ChatGPT text-only post-processing.

For this category, table stakes are:

| Capability | Table-stakes behavior | Alt Context posture |
| --- | --- | --- |
| Plugin connection | API key/account connection with usage visibility | Existing recognition API key/settings can be reused, but description usage needs its own capability/status surface later. |
| Private site support | Upload image bytes when WordPress is not publicly reachable | Already available for recognition multipart; reuse pattern for description. |
| Automatic generation | New uploads can be processed without manual work | Post-MVP; first pass remains headless/manual to avoid UI scope creep. |
| Single-image update | Operator can generate or regenerate alt text for one attachment | MVP headless route/smoke should prove this first. |
| Bulk generation | Missing-alt backlog can be processed in batches, with dry-run/force/limits | Beta table stake; not first CPU-only demo. |
| WP-CLI automation | Scriptable `generate`, `status`, `dry-run`, `limit`, `batch-size`, `force` | First pass should add a smoke/eval-file; later convert to proper command. |
| Review/edit | Processed images have a history/review surface and manual edits do not spend credits | Beta UI table stake; should store provenance and not overwrite human edits by default. |
| Post/page refresh | Existing content can be refreshed after Media Library alt text changes | Beta table stake. |
| Context enrichment | SEO keyphrases, product data, language, style/detail, prefix/suffix | Differentiator when combined with roster/context, but should follow core visual-facts proof. |
| Multilingual | WPML/Polylang/language handling | Later beta; important for parity but not MVP. |
| Usage controls | Credits/rate/budget limits per key/site | Required before provider/BYOK or public beta. |
| Error/status logs | Clear operational feedback for failed batches | Required before bulk. |

## Target Architecture

### Core Contract

Add a description-specific contract that returns structured visual facts before final prose:

- `tenant_id`
- `media_id`
- `image_hash`
- `adapter`
- `model_id`
- `model_version`
- `prompt_or_task_version`
- `visual_facts`
- `alt_text_draft`
- `context_used`
- `provider_disclosure`
- `cached`
- `duration_ms`
- `retention_class`

The first demo can use placeholders for expansion fields, but the schema should make future model/provider provenance unavoidable.

### Backend Components

- `DescriptionAdapter` protocol with at least `seeded`, `local_cpu`, and later `hosted_provider` implementations.
- `VisualFactsService` use case that validates inputs, computes hash/context keys, checks cache, calls the adapter, and records provenance.
- `scene` or `description` HTTP router for one-image multipart description, separate from `/recognition/analyze`.
- cache table or durable JSON artifact keyed by tenant, image hash, adapter/model version, and context hash.
- settings for adapter mode, timeout, max image size, worker concurrency, and provider enablement.
- metrics and audit events for request, cache hit, adapter latency, provider used, and purge/export eligibility.

### WordPress Components

- description proxy/controller under `/acx/v1/recognition/describe` (reuse the existing `acx/v1/recognition/*` namespace; do not introduce a parallel top-level `/acx/v1/descriptions` tree in MVP).
- service that resolves a single attachment id, reads bytes, adds WordPress context, and dispatches multipart to backend.
- headless LocalWP smoke/eval-file target that uses the current install and refuses non-local or missing `WP_PATH`.
- optional write mode that updates `_wp_attachment_image_alt` only when explicitly requested and never overwrites non-empty human alt text by default.
- later WP-CLI command surface for `generate`, `status`, `dry-run`, `force`, `limit`, and `batch-size`.

### Provider Adapters

Provider-backed generation is viable, but should be a later adapter, not the MVP default. Candidate adapters for benchmarking:

- OpenAI / Azure OpenAI
- Anthropic Claude
- xAI Grok
- Google Gemini / Vertex AI
- Amazon Bedrock / Nova
- Mistral
- hosted open-model platforms such as Replicate, Modal, Together, Fireworks, or OpenRouter

First provider spike should use operator-owned backend keys only. BYOK can come later only with explicit provider disclosure, encrypted key handling, budget controls, purge/export semantics, and a statement that third-party terms apply.

## Phased Delivery

### Phase 1: Headless Seeded Roundtrip

**Goal:** Prove the product loop without model/runtime risk.

Deliverables:

- Backend description route for exactly one image in multipart form.
- Typed request/response schema for visual facts and alt-text draft.
- Deterministic seeded adapter with fixtures for demo and tests.
- Cache keyed by tenant, image hash, adapter version, and context hash.
- WordPress REST path or eval-file smoke that reads one existing attachment and calls backend.
- Makefile target mirroring `localwp-batch-run-smoke`, but one-image and description-specific.
- Evidence JSON showing first call, cache hit, elapsed time, and source attachment.

Exit criteria:

- Current LocalWP install can roundtrip one existing attachment through backend and receive visual facts JSON.
- Repeated call returns `cached=true`.
- No admin UI is required.
- No new WordPress install or public media URL is required.

### Phase 2: Local CPU Model Probe

**Goal:** Measure whether local CPU inference is good enough for a v1 demo on OCI A1 constraints.

Deliverables:

- Optional local CPU adapter, starting with Florence-2-base-ft or another permissively licensed compact model if benchmark results change.
- Install/runbook that isolates model dependencies from the default recognition-only runtime.
- Downsample, timeout, memory cap, and one-worker default.
- Benchmark output for one seeded image: latency, memory, CPU, output quality, and failure mode.
- Fallback decision: keep seeded-only, enable local CPU for demo, or defer live model inference.

Exit criteria:

- One 1024px image completes inside a tolerable async demo window, target under 20 seconds if feasible.
- Worker does not starve API/Postgres on the OCI A1 host.
- Model dependency does not break existing recognition install/checks.

### Phase 3: Minimal Alt-Text Write Path

**Goal:** Move from visual facts proof to useful WordPress output without opening the full UI surface.

Deliverables:

- Optional `write_alt=true` mode or separate command that updates `_wp_attachment_image_alt`.
- Guardrail: default is preview-only; non-empty alt text is not overwritten without `force`.
- Store description provenance in attachment meta: adapter, model, generated_at, image hash, context hash, and source result id.
- Headless smoke proves preview, write, non-overwrite, and force-regenerate behavior.
- Basic missing-alt query integration reusing existing Media Library status logic.

Exit criteria:

- Operator can generate an alt-text draft for one missing-alt attachment and write it intentionally.
- Human-authored alt text is protected by default.
- Provenance survives after write.

### Phase 4: Table-Stakes Workflow Beta

**Goal:** Reach parity with the workflow basics customers expect from a WordPress alt-text service.

Deliverables:

- Proper WP-CLI command surface: generate, status, dry-run, force, limit, batch-size, output format.
- Bulk missing-alt generation with small bounded batches and retry/status tracking.
- Review/history page for processed images with inline edit and provenance.
- Post/page/WooCommerce refresh path to propagate updated Media Library alt text into existing content.
- Error log/status surface for failed images, unreadable files, provider/model errors, and timeout decisions.
- Usage accounting and per-site budget/rate controls.

Exit criteria:

- A real media library backlog can be dry-run, processed in batches, reviewed, and corrected.
- Existing non-empty alt text is preserved unless an operator forces regeneration.
- Failures are visible and retryable.

### Phase 5: Context-Aware Differentiation

**Goal:** Make Alt Context visibly better than generic hosted alt-text generators.

Deliverables:

- Context pack from WordPress attachment title/caption/description, parent post, nearby content, taxonomy, SEO keyphrases, and WooCommerce product data.
- Roster-confirmed identity context injection from local projection, with policy guardrails around naming people.
- Output modes: visual facts, accessibility alt draft, SEO-aware draft, and "needs human review" reasons.
- Configurable style/detail/length/language without exposing raw prompt plumbing as the primary UX.
- Context diff evidence: generic caption versus context-aware draft.

Exit criteria:

- Seeded demo clearly shows a better draft when WordPress/roster context is available.
- Identity naming remains human-in-the-loop and roster-bound.
- Output explains which context was used.

### Phase 6: Hosted Provider Quality Tier

**Goal:** Decide whether a hosted provider adapter belongs in product or only in benchmarking.

Deliverables:

- Server-side provider adapter behind operator-owned keys.
- Provider benchmark harness across OpenAI, Claude, Grok, Gemini, Bedrock/Nova, Mistral, and selected open-model hosts.
- Per-image cost, latency, retention, provider/model id, prompt version, input dimensions, and token estimates.
- Tenant-level opt-in gate and provider disclosure.
- BYOK decision memo after benchmark, not before.

Exit criteria:

- Product can compare local CPU, seeded, and provider outputs on the same images.
- Provider mode has explicit privacy/subprocessor language.
- BYOK is either deferred or scoped with encrypted storage and budget controls.

## Epic Decomposition Candidates

Future planning can split this roadmap into these epics:

| Candidate epic | Scope | Primary apps |
| --- | --- | --- |
| D1: Backend Visual-Facts Contract | description route, schema, seeded adapter, cache/provenance | `apps/prototype-description-service/scene` (recognition HTTP layer is pattern reference only) |
| D2: Headless WordPress Roundtrip | plugin controller/service, attachment byte upload, smoke target | `apps/prototype-wp-alt-context/src/api`, `scripts/localwp`, `Makefile` |
| D3: Local CPU Description Adapter | Florence/local model install, adapter, benchmark, runtime caps | `apps/prototype-description-service/scene`, `pyproject.toml`, deployment docs |
| D4: Alt-Text Write and Provenance | write/preview/force semantics, attachment meta, non-overwrite protection | WordPress plugin PHP and tests |
| D5: Bulk and Review Workflow | WP-CLI, batch status, review/history, retry, post refresh | WordPress plugin PHP/React |
| D6: Context Enrichment | WordPress/post/product/SEO/roster context pack, output modes | backend + plugin |
| D7: Provider Adapter and Governance | hosted provider benchmark, opt-in, retention disclosure, usage controls | backend + settings/policy docs |

## External Dependencies

| Dependency | Owner | Status | Blocks |
| --- | --- | --- | --- |
| Public recognition/description data policy | Product + Legal | Draft needed | Public beta and provider mode |
| OCI A1 local CPU benchmark | Engineering | Not started | Live local model decision |
| Description output contract review | Product + Engineering | Not started | D1/D2 task planning |
| Current LocalWP attachment fixture | Engineering | Available by assumption | Headless smoke evidence |
| Provider/subprocessor terms | Product + Legal | Not started | D7 |
| Exact release epic owner/version | Planning | Not assigned | Epic decomposition |

## Code Anchors

| Layer | File/Area | Note |
| --- | --- | --- |
| Backend app | `apps/prototype-description-service/api/main.py` | Mount future description/scene router; preserve health/metrics/security shape. |
| Backend router | `apps/prototype-description-service/recognition/interface_adapters/http/router.py` | Current recognition router; use as pattern, not necessarily owner. |
| Backend multipart | `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze_multipart.py` | Multipart/object-store/tenant pattern to reuse. |
| Backend scene package | `apps/prototype-description-service/scene/` | Natural home for visual facts and description use cases. |
| Backend dependencies | `apps/prototype-description-service/pyproject.toml` | Add optional VLM/model extras only after seeded contract lands. |
| Plugin proxy | `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` | Existing JSON/multipart proxy, tenant, API key, retry/circuit behavior. |
| Plugin media read | `apps/prototype-wp-alt-context/src/api/services/class-analyze-media-service.php` | Attachment byte-read and multipart dispatch pattern. |
| Plugin API shell | `apps/prototype-wp-alt-context/src/api/class-api.php` | Current media/missing-alt and route registration surface. |
| LocalWP smoke | `apps/prototype-wp-alt-context/scripts/localwp/batch-run-smoke.php` | Pattern for current-install smoke proof. |
| Plugin Makefile | `apps/prototype-wp-alt-context/Makefile` | Add description-specific LocalWP smoke target. |
| Frontend later | `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx` and dashboard/roster pages | Later review/bulk UI only after headless path works. |

## Risks and Mitigations

- **Risk: model work swallows product proof.**
  Mitigation: seeded adapter and visual-facts schema ship first; local CPU inference is Phase 2.

- **Risk: direct provider APIs weaken trust positioning.**
  Mitigation: provider mode is opt-in, server-side first, with provider disclosure and retention metadata.

- **Risk: alt text overwrites human-authored content.**
  Mitigation: preview-only default, missing-alt-only default, explicit `force` required for overwrite.

- **Risk: CPU inference blocks API requests.**
  Mitigation: async worker, one-worker default, timeout, cache, and no inline model execution on WordPress request path.

- **Risk: visual facts become unverifiable prose.**
  Mitigation: structured facts and context provenance are first-class; final prose is derived and reviewable.

- **Risk: roadmap duplicates existing recognition epics.**
  Mitigation: treat this as a new description layer that reuses recognition transport/auth/retention, not a rewrite of clustering or roster management.

## Success Metrics

- One existing WordPress attachment can roundtrip to backend description and return stable visual facts.
- Repeated seeded call returns a cache hit.
- Generated output includes adapter/model/provider provenance.
- Optional write path never overwrites non-empty alt text unless forced.
- A later beta can process a missing-alt backlog with dry-run, bounded batches, review/edit, and failure visibility.
- Context-aware output is visibly better than a generic image caption on seeded demo images.
- Provider mode, if shipped, reports per-image cost, latency, model/provider id, and retention disclosure.

## Not Doing Yet

- No admin UI in Phase 1.
- No bulk generation in Phase 1.
- No BYOK in Phase 1.
- No promise that local CPU inference beats hosted APIs on quality or latency.
- No self-hosted/sovereign claim for MVP.
- No automatic naming of people in alt text without human-reviewed roster context and policy guardrails.

---

# Consolidated Checklist

## Phase 1: Headless Seeded Roundtrip

- [ ] Backend one-image description multipart route.
- [ ] Visual-facts response schema.
- [ ] Deterministic seeded adapter.
- [ ] Cache/provenance record.
- [ ] WordPress one-attachment proxy path.
- [ ] LocalWP smoke target.
- [ ] Evidence JSON for first call and cache hit.

## Phase 2: Local CPU Model Probe

- [ ] Optional local CPU adapter dependency plan.
- [ ] Florence/local model benchmark.
- [ ] Timeout/memory/concurrency caps.
- [ ] OCI A1 runbook and decision memo.

## Phase 3: Minimal Alt-Text Write Path

- [ ] Preview/write/force semantics.
- [ ] Attachment meta provenance.
- [ ] Non-overwrite tests.
- [ ] Missing-alt integration.

## Phase 4: Table-Stakes Workflow Beta

- [ ] WP-CLI command surface.
- [ ] Bulk missing-alt generation.
- [ ] Review/history page.
- [ ] Post/page refresh.
- [ ] Error/status logs.
- [ ] Usage/budget controls.

## Phase 5: Context-Aware Differentiation

- [ ] Context pack.
- [ ] Roster-confirmed identity context.
- [ ] Output modes.
- [ ] Context diff demo evidence.

## Phase 6: Hosted Provider Quality Tier

- [ ] Provider adapter benchmark harness.
- [ ] Provider disclosure and retention metadata.
- [ ] Cost/latency logging.
- [ ] BYOK decision memo.
