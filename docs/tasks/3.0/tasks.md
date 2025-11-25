# Frontend ↔ Backend Integration Tasks (Next Sprint)

**Shared context**
- `apps/wp-context-alt-text/` → WordPress plugin + MCP adapter (frontend)
- `apps/recognition-service/` → HF Spaces recognition/roster API (backend)
- `docs/architecture/` → planning rules, roadmap, UML (source of truth for coordination docs)

This sprint plan ensures both services land the same contracts, feature flags, and ops playbooks ahead of the combined plugin release.

## Repository Structure Improvements

- [ ] Draft monorepo layout RFC aligning with current JS/PHP best practices (apps/, services/, packages/)
  - Command reference: `git checkout -b chore/structure-monorepo`
- [ ] Prototype directory move into staging branch to validate tooling paths
  - Command reference: `git mv context-alt-text apps/context-alt-text`
  - Command reference: `git mv __hugging-face/entity-identifier-api services/entity-identifier-api`
- [ ] Update Composer, npm, and CI workflows to target new locations before merge
  - Command reference: `rg --files -g'*composer.json' -0 | xargs -0 sed -i '' 's#context-alt-text#apps/context-alt-text#g'`
- [x] Document resulting structure in `docs/architecture/rules/instructions.md` and root index
- [ ] Verify `git status` is clean and run full test suites post-move (`composer test`, `npx vitest run`, `pytest`)

## Critical Tech Debt Remediation (Do Immediately)

- [x] **Consolidate REST API namespaces to `cat/v1`** — eliminate dual namespace technical debt ✅ **COMPLETED**
  - **Context**: Previously using both `context-alt-text/v1` (legacy workbench, roster GET, settings) and `cat/v1` (newer observations, roster mutations, retry). This created confusion, inconsistent endpoint discovery, and maintenance overhead.
  - **Migration completed**:
    - [x] Audited all REST endpoints in `apps/wp-context-alt-text/src/Api/Api.php` and categorized by namespace
    - [x] Created migration branch `refactor/consolidate-rest-namespace`
    - [x] Registered all endpoints under `cat/v1` namespace while maintaining `context-alt-text/v1` aliases for backward compatibility (deprecation period)
    - [x] Updated Admin.php endpoint configuration to use `cat/v1` URLs (lines 230-270)
    - [x] Updated all frontend hooks (`useRoster`, `useRecognitionObservations`, `useWorkbenchMedia`, etc.) to target `cat/v1`
    - [x] Added deprecation notices to `context-alt-text/v1` endpoints that log warnings when called
    - [x] Updated all integration tests to reflect consolidated namespace
    - [x] Ran full test suite: **113 Vitest tests passed**, **105 PHPUnit tests passed** (12 skipped)
    - [ ] After deprecation period (2 releases), remove `context-alt-text/v1` aliases and update CHANGELOG
  - **Files modified**:
    - `apps/wp-context-alt-text/src/Api/Api.php` - Added `register_endpoint_with_deprecated_alias()` helper
    - `apps/wp-context-alt-text/src/Admin/Admin.php` - Updated all endpoint URLs to `cat/v1`
    - `apps/wp-context-alt-text/js/admin/hooks/*.ts` - Updated test fixtures
    - `apps/wp-context-alt-text/tests/**/*Test.php` - Updated endpoint assertions
    - `apps/wp-context-alt-text/js/components/**/*.test.tsx` - Updated MSW handlers
  - **Success criteria**: ✅ All REST endpoints accessible via `cat/v1`; ✅ frontend makes zero calls to `context-alt-text/v1`; ✅ all tests green; ⏳ documentation pending

## Cross-Service Integration Sync

- [ ] Weekly handshake (15 min) to review contract diffs (`api/openapi.yaml` vs PHP DTOs) and backlog rollovers
- [ ] Mirror test fixtures: share golden responses under `context-alt-text/tests/fixtures/hf/` sourced from backend `tests/fixtures/`
- [ ] Update `docs/architecture/backend-uml/unified_architecture.mermaid` after any API shape change (frontend consumes this diagram)
- [ ] Shared env file template (`.env.template`) describing recognition base URL, API key, and timeouts for both services
- [ ] Publish run-book for local dev tunnel (ngrok/Cloudflared) so WP ↔ HF calls work during pairing sessions

## Interfaces to Implement/Verify

- Recognition Service (HF Space)
  - POST /api/v0/analyze-scene → AnalyzeSceneRequest ⇒ SceneAnalysisResult
  - POST /api/v0/embeddings → EmbeddingsRequest ⇒ EmbeddingsResponse
  - GET /api/v0/health, GET /api/v0/service/info, POST /api/v0/service/reload-embeddings
- Roster Sync (HF Space)
  - GET /api/v0/roster[?since=<rfc3339>]&page&per_page → list remote roster entries (paginated)
  - POST /api/v0/roster → create remote roster entry with embeddings (from reference image)
  - PATCH /api/v0/roster/{id} → update label/type/metadata, add new reference image(s) and recompute embeddings
  - DELETE /api/v0/roster/{id} → soft-delete or archive remote roster entry
- Frontend Abilities (MCP Adapter in WP)
  - cat/generate_alt_text
  - cat/regenerate_alt_texts
  - cat/create_roster_entry
  - cat/propagate

## Work Breakdown

1. Backend Service Readiness (`__hugging-face/entity-identifier-api/`)

- [x] Define/lock DTO schemas (AnalyzeSceneRequest, SceneAnalysisResult, EmbeddingsRequest, EmbeddingsResponse)
- [x] Add OpenAPI examples for new endpoints and publish base URL
- [ ] CORS and rate limits configured for WP origin(s)
- [ ] Health/Info endpoints return model versions, thresholds, and uptime
- [ ] Smoke tests for /analyze-scene and /embeddings with public demo images

1. WordPress Plugin Settings & Clients (`context-alt-text/`)

- [ ] Add settings: recognitionBaseUrl, timeoutMs, model/profile selection
  - Settings page wires to `context-alt-text/src/admin/settings/RecognitionSettingsPanel.tsx` with REST-backed save actions.
  - Persist options under `cat_settings` array (keys: recognitionBaseUrl, timeoutMs, modelProfile, featureFlags.recognitionEnabled).
  - Expose values to JS via `wp_localize_script` and to PHP services via `SettingsRepository` helper.
- [x] Implement PHP RecognitionClient:
  - [x] analyzeScene(AnalyzeSceneRequest): SceneAnalysisResult
  - [x] embeddings(EmbeddingsRequest): EmbeddingsResponse
  - [x] health(): ServiceHealth
  - [x] serviceInfo(): array { modelVersions, thresholds, uptime }
  - [x] reloadEmbeddings(): { status }
- [ ] Handle retries, circuit breaker, and structured error mapping
  - Wrap `RecognitionClient` requests with `HttpClient::withCircuitBreaker` policy (timeout default 10s, maxRetries 2, jittered backoff).
  - Normalize backend error payloads into `WP_Error` codes (`cat_recognition_timeout`, `cat_recognition_validation`, `cat_recognition_unavailable`).
  - Emit structured logs (`cat_recognition_http`) with requestId, endpoint, latency, attempt count.
- [ ] Add WP-CLI commands for pinging health and analyzing a sample attachment
  - Register `cat-recognition health` invoking `/api/v0/health`; print status + model versions table.
  - Register `cat-recognition analyze <attachment_id>`; fetch attachment file/path, call analyze-scene, pretty-print caption + faces table.
  - Provide `--timeout` override and bubble up HTTP diagnostics on failure.
- [ ] Establish TDD scaffolding: phpunit suites cover admin enqueue + metrics wiring; Vitest exercises dashboard data hooks/components (see roadmap-v3.md testing requirements)
  - PHPUnit: add `tests/phpunit/RecognitionSettingsTest.php` verifying option persistence, defaults, validation.
  - Vitest: create `src/js/hooks/__tests__/useRecognitionSettings.test.ts` mocking REST endpoints, ensuring caching/resubmission flows.
  - Configure GitHub Actions job `wp-plugin-tests` to run phpunit + vitest in CI.
- [x] Frontend code authored in TypeScript (`.ts/.tsx`) with strict compiler options; no new plain `.js/.jsx` files without architectural approval
  - [x] Enforce `"strict": true`, `"noUncheckedIndexedAccess": true`, and `"moduleResolution": "bundler"` in `tsconfig.json`.
  - [x] Add lint rule via ESLint config rejecting new `.js/.jsx` files in `src/js/` (allowlist legacy paths only).
  - [x] Update contributor docs with TS-first coding standards and migration guidance for existing JS modules.
- [ ] Refactor existing frontend modules to use arrow function expressions; enforce arrow functions for new React components/hooks/utilities
  - Run codemod over `src/js/**/*.{ts,tsx}` converting `function Component()` to `const Component = () =>` (skip WordPress interop that requires named functions).
  - Add ESLint rule `func-style: ["error", "expression", {"allowArrowFunctions": true}]` scoped to frontend package.
  - Document exception list for filters/actions that demand named callbacks.

- [x] Add PHP RosterSyncClient (or extend RecognitionClient) for remote roster operations:
  - [x] listRoster({ since?, page?, per_page? }): { entries: RosterEntryDTO[], nextPageToken? }
  - [x] upsertRosterEntry(dto: { remoteId?, label, type, avatarUrl?, references: AttachmentRef[] }): { remoteId }
  - [x] deleteRosterEntry(remoteId: string): { status }
 - [x] addReferenceImage(remoteId: string, attachmentId: number): { updated: true, embeddingId }

1. Admin SPA Surfaces (`context-alt-text/js/`)

- [ ] Bootstrap React SPA shell (RouterProvider + ApplicationLayout) mounting inside dashboard PHP entrypoint
- [ ] Dashboard Overview route — surface missing-alt counts, queued jobs, latest recognition insights
- [ ] Dashboard Overview widgets (HeroStats, RecentActivity, QueuedJobsSummary, RecognitionStatus)
- [ ] Automation Queue route — list/manage bulk jobs (generation, propagation, sync) with status filters and retry controls
- [ ] Roster Manager route — CRUD UI, roster match insights, guidance on entity creation during alt-text runs (finalize flow); lives at `/roster` inside the Context Alt Text admin SPA alongside Workbench/Automation/Settings
- [ ] Alt-Text Workbench route — grid/list of images missing alt text with selection tools, recognition triggers, bulk actions
- [ ] Alt-Text Workbench modules (MediaList, SelectionToolbar, RecognitionActions, BulkAltTextPanel)
- [ ] Settings route — plugin configuration forms (base URL, timeouts, feature toggles)
- [ ] Account Center route — API keys, billing/entitlements, account-specific notices
- [ ] Shared components: toast/notices, async data hooks, suspense states
- [ ] REST integration layer with nonce handling + error normalization for SPA consumption
- [ ] Storybook/Playground or dedicated mock state harness for rapid SPA iteration
- [ ] Global keyboard accessibility system covering all SPA surfaces
  - [ ] Define shortcut map aligned with Apple/Adobe conventions while avoiding existing WordPress bindings
  - [ ] Implement a togglable in-app shortcut helper/overlay that announces commands (including key combos) to assistive tech
  - [ ] Publish and maintain a dedicated keyboard bindings documentation page kept in sync with product changes
- [ ] Audit SPA components for hard-coded strings and replace with internationalized resources

1. Recognition Service Integration (Frontend)

- [ ] Harden RecognitionClient timeouts, retries, and circuit breaker defaults
  - Centralize HTTP config in `src/php/Infrastructure/Http/RecognitionHttpConfig.php`; expose tunables (timeouts, retries, fallback URL).
  - Integrate with the circuit breaker above; record metrics via `cat_observability` logger.
  - Add integration test hitting mock server to ensure fallback triggers after threshold.
- [ ] Map HF Space error payloads to WP_Error with actionable admin notices
  - Parse `error.code`, `error.detail`, `trace_id` from backend; surface inline admin notice with resolution hints.
  - Store recent failures in transient `cat_recognition_errors` for diagnostics page.
  - Localize user-facing copy for common failure shapes (rate limit, auth, validation).
- [ ] Add WP-CLI commands: `cat-recognition health` and `cat-recognition analyze <attachment_id>`
- [ ] ObservationRepository persists backend matches/confidence for UI badges
  - Extend schema with `confidenceScore` decimal + `sourceRemoteId` to map back to roster entries.
  - Sync repository updates when RecognitionClient returns matches; ensure migrations seeded.
  - Surface data to dashboard via REST `/wp-json/cat/v1/observations`.
- [ ] Settings page: base URL, API key, timeout, model profile, recognition enable toggle
  - Build React form using `@wordpress/data` store; include live validation + test connection button invoking health endpoint.
  - Save to options API; show unsaved changes banner, revert button.
  - Write Percy/Storybook stories to lock in layout.
- [x] Persist initial media scan results on activation and prime counts when missing
- [x] Provide Media Library panel view for attachments missing alt text

1. Propagation & Roster Sync (Shared)

- [ ] Implement propagation job queue (`cat/propagate`) with polling endpoint `/wp-json/cat/v1/propagate/{jobId}`
  - Queue skeleton: register `cat_propagation_jobs` table (jobId UUID, payload JSON, status, createdAt, updatedAt, errorLog).
  - Worker pathway: WP-Cron every minute hydrates pending jobs, dispatches batches to recognition service, records retries with exponential backoff.
  - API contract: POST `/wp-json/cat/v1/propagate` enqueues jobs, GET `/wp-json/cat/v1/propagate/{jobId}` streams status plus processed counts.
- [ ] Update admin roster table with sync badges (LOCAL, SYNCED, CONFLICT) and avatar thumbnails
  - Extend REST payload with `syncStatus` computed from remote_id + `cat_roster_sync_state` metrics.
  - Render badges via shared `<StatusPill>` component; ensure color contrast AA compliant and tooltips narrate state for screen readers.
  - Avatar column pulls WordPress attachment thumb; fall back to initials when missing.
- [ ] Conflict policy: remote embeddings win, labels/types resolved via `updated_at`; log overrides for manual review
  - Detection: compare `remote.updated_at` vs local `modified_gmt`; mark conflict when local wins but remote differs.
  - Resolution: persist remote record, retain local label in `cat_roster_conflicts` audit trail with resolver, timestamps.
  - Surface: admin notice + conflict filter in roster table for follow-up.
- [ ] Persist sync metrics in `cat_roster_sync_state` (lastSyncAt, pulled, created, updated, deleted, conflicts)
  - Schema: JSON column storing per-run aggregates and last successful sync timestamp.
  - Update flow: `RosterService::syncFromRemote` writes metrics each batch, resets counters on success, increments `failedRuns` on errors.
  - Diagnostics: expose metrics on admin diagnostics page and include in telemetry heartbeat.
- [ ] Bulk “Sync Recognition” action invokes `/wp-json/cat/v1/recognition/sync` and surfaces progress/errors in admin notices
  - List action: register bulk op in Media Library + Roster list tables; prompts confirmation dialog with expected duration and quota warning.
  - Execution: issue POST to sync endpoint, poll job queue for completion, emit dismissible notices on success/failure.
  - UX polish: disable action while another sync job is running; show progress bar fed by job queue metrics.

1. Alt Text Generation (Shared)

- [ ] cat/generate_alt_text optionally calls analyze-scene when recognition is required
- [ ] AltTextService composes prompt using SceneAnalysisResult (faces, objects, context)
- [ ] Provider-agnostic AIClient for captioning; enforce length and style policy
- [ ] cat/regenerate_alt_texts supports policy.requires_scene_analysis flag

1. Roster Management Flow (Shared)

- [x] Schema updates/migrations
  - [x] Add column cat_roster.remote_id (VARCHAR(64) or UUID) with unique index (nullable until synced)
  - [x] Persist avatar attachment ID (either cat_roster.avatar_id INT or within meta JSON under meta.avatarId)
  - [x] Migration backfills indexes for remote_id and label-type uniqueness

- [ ] Create/Update Flow (WP → Remote)
  - [ ] On create, compute embeddings via POST /api/v0/embeddings for selected reference image(s)
  - [ ] POST /api/v0/roster to create remote entry; persist returned remote_id into cat_roster.remote_id
  - [ ] On update (label/type/notes), PATCH /api/v0/roster/{remote_id}
  - [ ] When adding a new reference image, call embeddings then PATCH /roster/{remote_id} to append vectors

- [ ] Sync From Remote (Remote → WP)
  - [x] Implement RosterService::syncFromRemote(): pull GET /api/v0/roster with since token; merge by remote_id (basic pass)
  - [ ] Conflict policy: remote is source of truth for embeddings; labels/types resolved by latest updated_at (tie-breaker → remote)
  - [ ] Support soft-deletes/archives from remote; reflect status locally
  - [x] Schedule periodic sync via WP-Cron; add manual “Sync from Remote” button in Admin UI (manual wired; cron pending)

- [ ] Admin UI Enhancements
- [ ] Recognition settings REST API wiring to admin SPA
- [ ] Admin settings panel allowing enable/disable and base URL configuration
- [ ] Integration tests for recognition settings routes and repository migration

- [ ] Observation Labeling Workflow
  - **Shipped surface area**
    - [x] Recognition jobs persist observation payloads (status, bbox, roster matches, candidates) via `RecognitionJobService::persistObservations()` and `RecognitionObservationRepository::store()`; matched roster tags sync automatically with `syncAttachmentTags()` (`apps/wp-context-alt-text/src/Recognition/RecognitionJobService.php:407`, `apps/wp-context-alt-text/src/Recognition/RecognitionObservationRepository.php:34`, `apps/wp-context-alt-text/src/Recognition/RecognitionObservationRepository.php:564`).
    - [x] Workbench queue hydrates from `GET /wp-json/context-alt-text/v1/observations` with `status=needs_review` and React Query hook `useRecognitionObservations` (`apps/wp-context-alt-text/src/Api/Api.php:369`, `apps/wp-context-alt-text/js/admin/hooks/useRecognitionObservations.ts:1`).
    - [x] Roster admin route renders unresolved observations, deep-links via query params, and wires CTA for assignment (`apps/wp-context-alt-text/js/components/roster/RosterRoute.tsx:120`).
    - [x] Roster REST endpoints accept `resolveObservation` payloads and update observation records while retrying pending jobs (`apps/wp-context-alt-text/src/Api/Api.php:640`, `apps/wp-context-alt-text/src/Roster/RosterObservationManager.php:66`).
    - [x] Dashboard/resolver flow refreshes counts through React Query refetch + notices (`apps/wp-context-alt-text/js/components/roster/RosterRoute.tsx:280`).
  - **Remaining gaps**
    - [ ] Promote observation storage into dedicated `cat_observation` table (dbDelta migration, repository adapters, PHPUnit coverage); retain meta mirror until migration completes.
      - [ ] Capture explicit `detected_at`, `source_job_id`, `detection_metadata` columns and index `(status, detected_at)` for queue fetches.
      - [ ] Update `RecognitionObservationRepository` to read/write through table while keeping tag sync behaviour.
    - [ ] Observation API hardening: add pagination cursors, `If-None-Match` caching, and richer filters (`attachment`, `entity_type`, `detected_at` range); document contract in `docs/architecture/rules/recognition-configuration.md`.
    - [ ] UI defer / snooze flow: allow operators to triage later with reason codes, bubble metrics into dashboard and telemetry (`cat_workbench_recognition_labelled`).
    - [ ] Generate cropped reference thumbnails from bounding boxes, persist attachment derivatives, and plumb through `referenceImages` to seeding pipeline.
    - [ ] Add aria-live updates + matched roster badges in Workbench row list; surface remote ID chip + candidate confidence hints.
    - [ ] Nightly reconciliation job to compare WP media tags vs observation state, queue repairs, and document manual remediation steps in `local_integration_guide.md#observation-labeling`.
    - [ ] Review queue sorts unresolved observations by highest recognition similarity and surfaces the top roster candidate with the model-provided confidence %, not the raw face-detection score (update UI + payload contract).
  - [ ] Persist roster match similarity separately from detection confidence and update Workbench UI copy to make the distinction clear; hide detection confidence fallback when roster scores are available.
  - [ ] Tweak auto-resolve flow so new embeddings queue for confirmation instead of immediately averaging into roster vectors; store pending references per entry until operator approval.
  - [ ] Add regression test (Python recognition job + WP resolver) that repeatedly labels the same face and asserts returned similarity stays within tolerance once auto-resolve is adjusted.
  - [ ] Register dedicated taxonomy `cat_roster_entity` for attachments and roster storage (REST + UI support, admin filters, CLI access); document capability requirements.
  - [ ] Update recognition tag sync to target `cat_roster_entity` (replace `post_tag` usage), add CLI repair command, adjust Storybook fixtures, and ensure new taxonomy values flow through REST payloads.
  - [ ] Migration path: scan existing `post_tag` terms prefixed `cat_roster_`, create equivalent `cat_roster_entity` terms, reassign attachment relationships, and leave optional flag to keep legacy tags for discoverability.
    - [ ] Persist any automatic or operator-confirmed face match back into recognition embeddings for that roster entry so future detections improve.
    - [ ] Surface matched roster WP tags in media list/detail views so editors can filter by identity without leaving the library.
    - [ ] Roster Entry Media Mapping (Many↔Many)
    - [ ] Track associations between roster entries and media attachments (multiple attachments per roster, multiple roster matches per attachment) in `cat_roster_media` join table with migrations + APIs.
    - [ ] Update roster admin table “Images” column to list linked attachments (count + quick links), and display roster matches inside Workbench media metadata.

1. Observability & Diagnostics (Shared)

- [ ] Structured logs with correlation IDs (sessionId, requestId)
- [ ] Metrics: latency, errors, cache hits, per-endpoint
- [ ] Admin diagnostics page: health checks, config dump (redact secrets), recent recognition errors
- [ ] Roster sync metrics: pulled, created, updated, deleted, conflicts; lastSyncAt persisted in options
  - [x] Persist lastSyncAt and basic counts in cat_roster_sync_state (initial)

1. Security & Limits (Shared)

- [ ] Input validation and size limits on image payloads (or signed URLs)
- [ ] API keys/allowlists for backend (if required)
- [ ] Timeout budgets, exponential backoff, retry-after respect

1. E2E Tests and Fixtures (Shared)

- [ ] Backend: contract tests for endpoints (JSON schemas, golden responses)
- [ ] Frontend: PHPUnit+integration tests for abilities and services
  - [x] Added unit tests for RosterService::syncFromRemote basic create/update merge via injected fake client
- [ ] Seed minimal roster and sample images for local E2E
- [ ] Roster sync round-trip tests: create locally → remote_id set; update remotely → reflected locally; delete remotely → archived locally
- [ ] Dashboard SPA tests: React component unit tests via Vitest + Testing Library; Storybook visual baselines align with Radix/SCSS stack
- [ ] Ensure SPA tests run under TypeScript strict mode; all new React modules authored as `.ts`/`.tsx`

## Acceptance Criteria

- Frontend abilities successfully invoke backend /analyze-scene and /embeddings in dev
- Recognition results surface in WP (badges, propagation summaries) without a standalone face-tagging UI
- Alt text generation leverages SceneAnalysisResult when enabled
- Roster creation persists embeddings from backend and stores remote_id
- “Sync Recognition” / “Sync from Remote” update local roster entries; admin table shows avatar, local ID, remote ID, sync status badges
- Admin diagnostics page reports backend health and recent error summaries
- All diagrams in `docs/architecture/backend-uml` and `docs/architecture/frontend-uml` stay version-aligned with current APIs
- Keyboard-only workflows succeed for every shipped feature; shortcut helper toggle and documentation page surface key combos with audible descriptions, using Apple/Adobe-style patterns that avoid WordPress collisions

## Recognition Service Backlog Prompts (Consolidated)

- **InsightFace-only rewrite**: rebuild the recognition microservice around a single InsightFace pipeline, stripping legacy CVLFace dependencies and quality scorers.
- **Green-field CVLFace rewrite**: re-evaluate the multi-model architecture (AdaFace, InsightFace, ArcFace) under a clean ports-and-adapters design; scoped for future experimentation.
- **Pipeline debugging**: isolate the "no faces recognized" defect within the SceneAnalysis → Recognition hand-off; document root cause and remediation plan.
- **Model benchmarking harness**: deliver a reproducible benchmark suite that runs every supported recognition model against tagged fixtures and emits JSON + Markdown reports—no synthetic scores.
- **Recognition model test run**: execute the benchmark harness with `/scripts/mock_entities` to rank models based on real-world accuracy, capturing environment details.
- **Roster service rewrite**: design a stand-alone roster service responsible for identity records and embedding stores without embedding inference logic (pairs with the recognition rewrite).
