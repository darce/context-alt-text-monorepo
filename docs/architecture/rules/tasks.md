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
- [x] Implement PHP RecognitionClient:
  - [x] analyzeScene(AnalyzeSceneRequest): SceneAnalysisResult
  - [x] embeddings(EmbeddingsRequest): EmbeddingsResponse
  - [x] health(): ServiceHealth
  - [x] serviceInfo(): array { modelVersions, thresholds, uptime }
  - [x] reloadEmbeddings(): { status }
- [ ] Handle retries, circuit breaker, and structured error mapping
- [ ] Add WP-CLI commands for pinging health and analyzing a sample attachment
- [ ] Establish TDD scaffolding: phpunit suites cover admin enqueue + metrics wiring; Vitest exercises dashboard data hooks/components (see roadmap-v3.md testing requirements)
- [ ] Frontend code authored in TypeScript (`.ts/.tsx`) with strict compiler options; no new plain `.js/.jsx` files without architectural approval
- [ ] Refactor existing frontend modules to use arrow function expressions; enforce arrow functions for new React components/hooks/utilities

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
- [ ] Roster Manager route — CRUD UI, roster match insights, guidance on entity creation during alt-text runs (finalize flow)
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

1. Recognition Service Integration (Frontend)

- [ ] Harden RecognitionClient timeouts, retries, and circuit breaker defaults
- [ ] Map HF Space error payloads to WP_Error with actionable admin notices
- [ ] Add WP-CLI commands: `cat-recognition health` and `cat-recognition analyze <attachment_id>`
- [ ] ObservationRepository persists backend matches/confidence for UI badges
- [ ] Settings page: base URL, API key, timeout, model profile, recognition enable toggle
- [x] Persist initial media scan results on activation and prime counts when missing
- [x] Provide Media Library panel view for attachments missing alt text

1. Propagation & Roster Sync (Shared)

- [ ] Implement propagation job queue (`cat/propagate`) with polling endpoint `/wp-json/cat/v1/propagate/{jobId}`
- [ ] Update admin roster table with sync badges (LOCAL, SYNCED, CONFLICT) and avatar thumbnails
- [ ] Conflict policy: remote embeddings win, labels/types resolved via `updated_at`; log overrides for manual review
- [ ] Persist sync metrics in `cat_roster_sync_state` (lastSyncAt, pulled, created, updated, deleted, conflicts)
- [ ] Bulk “Sync Recognition” action invokes `/wp-json/cat/v1/recognition/sync` and surfaces progress/errors in admin notices

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
  - [x] Add columns: Avatar (thumbnail), ID (local id), Remote ID
  - [ ] Modal: select/upload avatar image; store avatarId; show remote sync status badges (SYNCED/LOCAL-ONLY/CONFLICT)
  - [ ] Debounced search across label/type; display count and last synced time

- [ ] Validation & Conflicts
  - [ ] Prevent duplicate label+type; surface friendly errors on 409 from remote
  - [ ] Idempotency keys on create to avoid duplicates on retries

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
