# 🧭 Context Alt Text Roadmap v3.0 — MVP, Abilities + MCP Adapter

## 🎯 Core Objective

Ship a WordPress plugin that lets admins batch-generate semantically rich, identity-aware alt text and confirm known people/brands by invoking:

- a **self-hostable remote recognition service** (faces/brands; side profiles & partial occlusions) that performs detection, recognition, and roster synchronization, and
- a provider-agnostic LLM (captioning via PHP AI Client SDK).

### Active surfaces

| Area                   | Directory                               | Notes                                                                    |
| ---------------------- | --------------------------------------- | ------------------------------------------------------------------------ |
| Frontend plugin        | `context-alt-text/`                     | WordPress plugin, MCP adapter, shared PHP DTOs                           |
| Backend service        | `__hugging-face/entity-identifier-api/` | FastAPI/HF Spaces microservice, OpenAPI source                           |
| Systems knowledge base | `docs/architecture/`                    | Roadmaps, rules, UML (`backend-uml/`, `frontend-uml/`), research prompts |

Agent integrations (VS Code Copilot, Claude, etc.) go through MCP (post‑MVP); WordPress admin UX continues to use internal REST for screens. Face identification happens exclusively in the backend recognition service; the WordPress UI no longer hosts a standalone face-tagging page in MVP.

---

## 🧱 Dashboard (Comprehensive Overview)

The Dashboard provides a at-a-glance status of the plugin's recognition, alt-text generation, and automation workflows through five card-based widgets and a hero status banner.

### Dashboard Components

#### 1. Hero Status Banner

**Purpose**: Primary accessibility signal with immediate action path

- Displays current system state (e.g., "We found N images missing alt text")
- CTA button directing to filtered Media Library or Workbench
- Shows last updated timestamp
- State-driven styling (info, warning, success)

#### 2. Coverage Card

**Purpose**: Visual progress tracking for alt-text coverage

- Percentage coverage with donut chart visualization
- Breakdown: Total images, With alt text, Missing alt text
- Optional trend visualization (feature-flagged: `coverageTrend`)
- React Query-powered with loading/error states
- Retry action on fetch failures
- Intersection Observer for analytics (card visibility tracking)

#### 3. Activity Card

**Purpose**: Recent operation timestamps

- Last recognition run
- Last alt-text generation
- Last roster sync
- Human-readable relative timestamps with tooltips showing absolute values

#### 4. Recognition Insights Card

**Purpose**: Triage surface for pending recognition work

- Faces awaiting review (count with warning styling if > 0)
- Brands awaiting review (count with warning styling if > 0)
- Unresolved matches requiring manual intervention

#### 5. Automation Pipeline Card

**Purpose**: Background job status at a glance

- Queued jobs count
- Currently running jobs
- Completed jobs (24-hour window)
- Next scheduled action timestamp (if applicable)

#### 6. Action Footer

**Purpose**: Persistent quick-action bar

- Primary workflows accessible from any dashboard view
- Links to Workbench, Settings, Documentation

### Implementation Notes

- First-run scan MUST populate missing alt text count within 30s of activation
- When count not ready, render "Calculating…" with spinner (no blocking errors)
- Counting logic treats BOTH (a) absence of `_wp_attachment_image_alt` meta AND (b) empty-string values as "missing"
- Coverage Card uses React Query with 60s stale time, manual refetch available
- All cards implement proper ARIA labels, live regions, and screen reader announcements
- Cards emit analytics events on visibility (IntersectionObserver) and interactions
- Feature flags control optional enhancements (trend visualization, advanced metrics)

> Gating note (MVP): Abilities and MCP integration are scaffolded but disabled by default. They are behind feature flags and will be delivered post‑MVP. See "Feature flags and gating" below.

- Declare plugin capabilities as Abilities and expose them as MCP tools via MCP Adapter (Deferred: post‑MVP):

<!--
* cat/generate_alt_text
* cat/regenerate_alt_texts (batch)
* cat/create_roster_entry (delegates embeddings/recognition to backend service)
* cat/propagate (applies backend-provided matches to local media)
-->

- LLM access is model-agnostic through the PHP AI Client SDK (GPT/Claude/Gemini, etc.).

- Recognition remains a self-hostable microservice (HF Space or your GPU box). No embeddings on the frontend.

Implementation guardrails for the admin UI:

- Keep the PHP-rendered dashboard entry screen for capability checks and menu wiring, then mount the SPA within it.
- Build the React admin app with the standard WordPress stack (`@wordpress/scripts` or Vite) and source REST endpoints + nonces via PHP.
- Default to SPA routes for new UI slices (dashboard widgets, media panel, roster, settings), migrating legacy fragments incrementally.
- Reserve server-rendered PHP fallbacks for scenarios that demand them (activation notices, hard failures).
- Treat keyboard accessibility as a first-class contract: every interactive surface must be operable end-to-end via the keyboard, include shortcut bindings that mirror familiar Apple/Adobe conventions (while avoiding collisions with existing WordPress shortcuts), expose those bindings through a togglable/audible in-app helper, and maintain a dedicated key-command reference page. New features cannot ship without meeting this bar.

Planned SPA navigation surfaces:

- **Dashboard Overview** – single-glance status of the recognition + alt-text workflow (missing counts, recent recognitions, queued jobs).
- **Automation Queue** – bulk job manager (naming replacement for "Jobs") tracking generation, propagation, and sync runs.
- **Roster Manager** – CRUD for roster entities plus touchpoints for how matches are captured during alt-text generation (decision pending on when new entities are created vs. linked).
- **Alt-Text Workbench** – dedicated list of media missing alt text (new name to avoid clashing with the native Media Library) with workflow tooling, recognition triggers, and selection helpers.
- **Settings** – plugin configuration (base URLs, feature toggles, timeouts).
- **Account Center** – account-scoped details such as API keys, billing, entitlements; lives separately to keep operational controls distinct from general settings.

## 🔧 Feature flags and gating (MVP)

- CAT_ENABLE_ABILITIES: default false. When true (or filtered via `cat_enable_abilities`), Abilities registrar boots and tools are registered.
- CAT_ENABLE_MCP: default false. Reserved for MCP server wiring. MCP UI is removed for MVP.

**User Consent for Remote Operations:**

All operations that use remote recognition services or modify remote FAISS indexes require explicit user confirmation:

- Recognition job submission requires user-initiated action (button click, bulk action confirmation)
- Roster sync to FAISS only occurs after user confirms face identity (create new person, confirm suggestion, correct misidentification)
- Background processing must provide immediate feedback (toast notification, progress indicator, error state)
- No automatic roster sync on plugin activation, image upload, or scheduled tasks without user opt-in

---

- Admin UI for MCP tools: removed (no menu). Abilities/MCP are not part of MVP acceptance criteria.
- Post‑MVP: turn flags on in wp-config.php or programmatically via filters.

Diagram note: the legacy phase diagrams are deprecated; use the canonical `docs/architecture/backend-uml/unified_architecture.mermaid` alongside the flow-specific diagrams in `docs/architecture/frontend-uml/`. Recognition and embeddings are remote-only.

## ✅ Phase 1: MVP Release (Target)

### 🔐 Architecture Goals

- Fully open-source local plugin logic.
- Remote visual recognition engine **self-hosted on Hugging Face Spaces or similar infrastructure**.
- Remote engine supports **non-frontal, partially obscured recognition** (e.g., side profiles, masks, cropped logos).
- Avoid usage-based billing and centralized rate limits.
- MCP for agent access; internal REST for WP admin UI.

### Glossary

- DetectedFace (FE) → transient boxes.
- FaceObservation (BE) → persisted box row for matching.
- ObservationEmbedding (BE) → vector for an observation.
- AugmentedEmbedding (BE) → canonical roster vector.

### Epic A — Foundations & Safety (supports all participants) [PLANNED]

#### Implementation (A) [PLANNED]

- Composer + PSR-4; namespaces under `src/` (Abilities, Services, Domain, Admin).
- Main bootstrap with headers, constants, lightweight container/wiring.
- Lifecycle hooks: activation, deactivation, uninstall (clean tables/options/caps).
- Abilities layer scaffolded and feature-gated off by default.
- MCP server scaffolding gated off for MVP.
- Scan for missing alt text on plugin activation (fresh install + upgrade path).

- [HYBRID] Create local tables `cat_roster`, `cat_observation`, `cat_sync_queue` (see Appendix A for SQL).
- [HYBRID] Implement DAO layer for each table with prepared statements; version schema via `cat_db_version` option; create on activation.
- [HYBRID] Add Settings → Recognition Service (Base URL, API key, “Test Connection” action).
- [HYBRID] Build PHP client for the Recognition Service with retries/backoff, `ETag`/`If-None-Match`, and idempotency keys.
- [HYBRID] Schedule WP-Cron jobs: (a) roster delta sync (default: every 15 minutes), (b) sync-queue worker with exponential backoff, (c) observation purge (default: 90 days).
- [HYBRID] Implement optimistic UI for confirmations; enqueue `confirm_match` when offline or on 429/5xx.
- [HYBRID] Add avatar generator (128×128 WebP crops) stored under `wp-content/uploads/context-alt-text/avatars/` and persisted in `cat_roster.avatar_url`.
- [HYBRID] Implement uninstall routine to drop CAT tables, delete avatars under plugin path, and remove options/caps.

#### TDD (A) [PLANNED]

- [HYBRID][TDD] Migration tests for all tables; upgrade path preserves data; uninstall drops tables and files.
- [HYBRID][TDD] DAO CRUD + index coverage; JSON field encoding/decoding integrity.
- [HYBRID][TDD] Client retry/backoff and idempotency-key tests; `ETag` delta application tests; conflict resolution (remote-wins).
- [HYBRID][TDD] Sync queue worker: backoff schedule, dead-letter handling after N attempts, admin “Retry Now” action.
- [HYBRID][TDD] Observation purge job deletes >90-day rows; retention configurable and respected.
- [HYBRID][TDD] Avatar generator produces valid WebP; regeneration on label/primary-face change; permissions hardened.
- Unit tests for activation/deactivation/uninstall behavior exist and pass.
- Abilities registrar tests skip correctly when feature-gated.
- Scan tests for missing alt text on activation pass.

#### DoD [PLANNED]

- First-run scan for missing alt text functional; tests green.
- PHPCS, unit tests pass in CI.
- MCP tool stubs remain gated off for MVP.

### Epic B — Data Model & Migrations [PLANNED]

#### Implementation (B) [PLANNED]

- cat_roster: id, label, type(person|brand), meta(json), created_at, updated_at.
- cat_observation (session-scoped): observation_id PK, session_id, attachment_id, bbox(json), confidence(float), assigned_roster_id (nullable), status(enum), created_at.
- Migrations on activation; smooth re-runs on version bump; uninstall cleans up.
- DetectedFace (FE) persists as FaceObservation (BE); ObservationEmbedding and AugmentedEmbedding backend-only.
- Add compliance % complete, progress bar.
- Add “Next Image to Fix” queue.
- Integrate Live Preview slider in Drafts sub-view.

#### TDD (B) [PLANNED]

- Migration tests cover table creation, columns, idempotency, and versioning.
- Pending: coverage for compliance percentage and draft queue.

#### DoD (B)

- cat_roster + cat_observation tables live with migrations/tests.
- Draft queue actionable from admin panel.
- Compliance percentage displayed with tests.

### Epic C — Recognition Pipeline (WP ↔ HF) [PLANNED]

Implementation focus:

- RecognitionClient handles analyzeScene + embeddings with retries, exponential backoff.
- RosterSyncClient wraps remote roster CRUD with idempotency keys.
- WP-CLI commands for health/analyze to unblock ops.
- Backend HF service exposes /analyze-scene, /embeddings, /roster endpoints with schema parity.

TDD:

- Contract tests comparing PHP DTOs vs OpenAPI examples.
- PHPUnit coverage for retries, error mapping.
- FastAPI tests for embeddings/analysis returning golden payloads.

DoD:

- Round trip: roster entry created in WP persists remote_id, visible via backend GET /roster.
- Analyze scene triggered from WP returns labeled detections.
- Admin diagnostics surfaces health and recent errors.

### Epic D — Dashboard & Alt Text Generation [IN PROGRESS]

Implementation:

**Dashboard Surface** (React/TypeScript)

- [x] Hero Status component with state-driven messaging
- [x] Coverage Card with donut chart, trend visualization (feature-flagged)
- [x] Activity Card with relative timestamps and tooltips
- [x] Recognition Insights Card with pending counts
- [x] Automation Pipeline Card with job status
- [x] Action Footer with quick-access links
- [x] React Query integration with proper loading/error states
- [x] Analytics instrumentation (IntersectionObserver, event emission)
- [x] Comprehensive test coverage (Vitest + Testing Library)
- [ ] Storybook stories for all dashboard components
- [ ] REST endpoint for live Coverage Card refresh (`/wp-json/cat/v1/dashboard/coverage`)
- [ ] REST endpoint for Activity Card data (`/wp-json/cat/v1/dashboard/activity`)
- [ ] REST endpoint for Recognition Insights (`/wp-json/cat/v1/dashboard/recognition`)
- [ ] REST endpoint for Automation Pipeline status (`/wp-json/cat/v1/dashboard/automation`)
- [ ] PHP service layer: `DashboardMetricsService` aggregating data from domain services
- [ ] First-run scan integration (<30s after activation)
- [ ] Persistent user preferences (dismissed notices, view settings)

#### Alt-Text Generation Pipeline

- AltTextService composes prompt from SceneAnalysisResult + policy
- AIClient chooses provider, enforces style guardrails
- Admin UI to review/approve drafts (Workbench integration)
- Batch generation queue with progress tracking

TDD:

- [x] CoverageCard unit tests (loading, error, refetch, trend, accessibility)
- [x] ActivityCard unit tests (timestamp formatting, tooltips)
- [x] RecognitionCard unit tests (warning states, zero states)
- [x] AutomationCard unit tests (job counts, next run display)
- [x] HeroStatus unit tests (state variants, CTA rendering)
- [ ] Integration tests for dashboard data hydration
- [ ] Contract tests for REST endpoints vs TypeScript types
- Golden prompt composition tests
- Provider-specific adapters with mock responses
- [ ] E2E tests for dashboard → workbench navigation flow

DoD:

- [x] Dashboard renders all 5 cards with proper accessibility
- [x] Coverage Card live-refreshes via React Query
- [x] Analytics events fire on card visibility and interactions
- [ ] REST endpoints return properly typed, cacheable responses
- [ ] First-run scan completes within 30s, dashboard reflects counts
- Draft alt text generated automatically for missing entries
- Admin can accept/decline drafts with history log
- [ ] Storybook deployed with all dashboard component stories

### Epic E — Propagation & Sync [PLANNED]

Implementation:

- Propagation job queue processes embeddings matches in batches.
- Conflict resolution ensures remote embeddings take precedence.
- Sync metrics persisted with WP-Cron aware scheduling.

TDD:

- Job queue unit tests with fake runners.
- Conflict policy characterization tests.

DoD:

- “Sync Recognition” action updates roster + media badges.
- Metrics page shows processed counts and conflicts.

### Epic F — Observability & Security [PLANNED]

Implementation:

- Structured logging with correlation IDs.
- Metrics exported via WP hooks + FastAPI instrumentation.
- API keys and origin allowlists enforced.

- [HYBRID] Metrics: sync queue depth, last sync timestamp, last error, purge counts, roster delta size, ETag mismatches.
- [HYBRID] Error budgets: 95th/99th latency for `/recognize`, `/roster/*`; 429/5xx rate alarms; queue dead-letter threshold alarms.
- [HYBRID] Audit logs: roster CRUD and confirmations (include `X-Request-Id`, user id, remote_id, payload hash).
- [HYBRID] API key scoping: restrict roster read/write per tenant; origin allowlist for plugin calls.

TDD:

- [HYBRID] Metrics unit tests: counters/gauges emitted for success/error paths; alarms fire on thresholds (mocked).
- [HYBRID] Security tests: capability `manage_context_alt_text` required for roster ops; API key scope enforced server-side.
- [HYBRID] Audit tests: log entries present for roster CRUD/confirmations; redaction of PII in logs.
- Logging assertions on error paths.
- Security tests for nonce/cap checks.

DoD:

- Ops run-book published.
- Alerting configured for error thresholds.

### Epic G — Backend Architecture Alignment & Database Persistence [IN PROGRESS]

**Overview**: Establish PostgreSQL+pgvector as the canonical storage layer for roster entities, reference embeddings, and augmented embeddings (progressive learning). Implement database adapters for both SQLite (local dev) and PostgreSQL (production), integrate Alembic for schema migrations, and configure FAISS as an optional derived in-memory index synchronized from the database.

**Implementation**:

**Database Architecture & Migrations:**

- ✅ Document complete PostgreSQL schema with pgvector extension (tenants, roster_entities, reference_embeddings, augmented_embeddings, materialized aggregate views)
- ✅ Document SQLite schema with JSON blob storage for embeddings (zero-dependency local dev)
- ✅ Implement Alembic baseline migration (0001) with database-specific branching (PostgreSQL vector types vs SQLite JSON)
- ✅ Create database adapter pattern: `StorageAdapter` interface with `PostgresStorageAdapter` and `SQLiteStorageAdapter` implementations
- 🔄 Set up Alembic in `apps/recognition-service/db/migrations/` with environment-based URL configuration
- ⏳ Implement `PostgresStorageAdapter` with pgvector cosine similarity search, RLS tenant isolation, batched embedding insertion
- ⏳ Implement `SQLiteStorageAdapter` with JSON serialization, manual numpy cosine similarity, fallback search
- ⏳ Create environment detection module to auto-select database (SQLite for local, PostgreSQL for production)

**Progressive Learning Pipeline:**

- ✅ Document augmented_embeddings table schema with observation_id (idempotency), quality_tier (high/medium/low), source tracking
- ✅ Document materialized view strategy for weighted aggregate embeddings (reference + augmented by quality)
- ⏳ Implement `/api/v0/roster/{id}/confirm` endpoint to receive WordPress confirmations
- ⏳ Implement materialized view refresh trigger on augmented embedding insertion
- ⏳ Add FAISS hot-reload after materialized view refresh (HybridIndexManager pattern)

**Hybrid FAISS Integration:**

- ✅ Document FAISS as derived index synchronized from database (not canonical storage)
- ✅ Design HybridIndexManager with rebuild_from_database(), search(), load_from_disk(), save_to_disk()
- ⏳ Implement HybridIndexManager in `recognition_core/hybrid_index.py`
- ⏳ Add configuration flags: `USE_FAISS_ACCELERATION`, `FAISS_INDEX_PATH`
- ⏳ Integrate FAISS fallback: database search when FAISS unavailable

**UML & Documentation Updates:**

- ⏳ Update `docs/architecture/backend-uml/database-entities.mmd` to reflect three-table schema (roster_entities, reference_embeddings, augmented_embeddings)
- ⏳ Extend `docs/architecture/backend-uml/roster_service.mermaid` to show database adapters, AugmentedEmbedding domain entities, and persistence ports
- ⏳ Amend `docs/architecture/backend-uml/recognition_service.mermaid` to include database-first architecture with FAISS as derived index
- ⏳ Revise `docs/architecture/backend-uml/recognition-identify-flow.mmd` to show progressive learning loop: WP confirm → backend persist → refresh materialized view → hot-reload FAISS → ACK

**TDD:**

- Render all updated Mermaid diagrams locally to confirm syntax validity and visual accuracy.
- Add contract notes under `docs/architecture/contracts/` describing augmented embedding payloads (observation_id, quality_tier, bbox, confidence) and propagation ACKs
- Unit tests for both PostgresStorageAdapter and SQLiteStorageAdapter (search, insert, update, delete)
- Integration tests: Alembic migrations apply cleanly on both databases; materialized view refreshes correctly; FAISS rebuilds from database
- Peer review revised diagrams and migration scripts with backend stakeholders

**DoD:**

- ✅ `backend-clustering-persitence-tasks.md` created with complete implementation guide (database schemas, adapters, migrations, API catalog, 5-week timeline)
- ✅ `backend-recognition-persistence-plan.md` updated to align with database-first architecture (PostgreSQL primary, FAISS derived)
- ✅ `db-install-and-production-guide.md` updated with SQLite local dev, Docker Compose PostgreSQL, Alembic workflows, production provisioning
- ⏳ Alembic baseline migration (0001) applied successfully on both SQLite and PostgreSQL
- ⏳ Database adapters pass unit tests (CRUD operations, tenant isolation, search accuracy)
- ⏳ HybridIndexManager tests verify database synchronization (rebuild, hot-reload, fallback)
- ⏳ Progressive learning end-to-end: WordPress confirmation → augmented embedding insert → materialized view refresh → FAISS update → improved search results
- ⏳ Updated UML files merged and validated by diagram renderer
- ⏳ Roadmap references to roster propagation match documented database flows
- ⏳ Progressive-learning contract captured in `docs/architecture/contracts/` and shared with WordPress team

**Reference Documents:**

- `docs/tasks/backend-clustering-persitence-tasks.md` — Complete implementation guide with schemas, adapters, migrations, API catalog
- `docs/tasks/backend-recognition-persistence-plan.md` — High-level architecture decisions and patterns
- `docs/tasks/db-install-and-production-guide.md` — Operational guide for local dev and production setup

---

## 📦 Deliverables Summary

1. WordPress plugin (Context Alt Text) with MCP abilities ready but gated.
2. HF recognition backend deployable via Spaces or container.
3. Shared contract + UML docs maintained under `docs/architecture`.
4. Test suites (PHPUnit, Vitest, FastAPI pytest) covering pipeline happy paths + failure modes.
5. Ops guides: environment variables, local tunnel, smoke scripts.
6. Keyboard accessibility system: non-conflicting shortcut map, togglable helper overlay with audible descriptions, and published key-binding documentation.

## 🧪 Validation Checklist

- [ ] `composer test` (PHPUnit) passes.
- [ ] `npm test` / `npx vitest run` passes or appropriately skipped.
- [ ] FastAPI pytest suite covers analyze + embeddings.
- [ ] Contract tests compare OpenAPI schema with PHP DTOs.
- [ ] Playbook for manual smoke (WP admin + HF backend) published.
- [ ] Keyboard navigation verified (no-pointer workflow, shortcut helper toggle, reference page linked) and recorded in Storybook/QA notes.

## 🗺️ Long-Term Backlog (Post-MVP)

- MCP tool enablement & agent documentation.
- Advanced roster analytics (duplicate detection, tagging suggestions).
- Multi-tenant backend support with per-site API keys.
- Offline processing queue using managed job runner (e.g., Temporal, PydanticWorker).
- Accessibility insights dashboard with trendlines and digests.

## 📚 References

- WordPress Plugin Handbook — <https://developer.wordpress.org/plugins/>
- FastAPI docs — <https://fastapi.tiangolo.com/>
- Hugging Face Spaces — <https://huggingface.co/spaces>

---

## Appendix A: Hybrid DB Schema (SQL)

Last updated: 2025-10-30T19:13:22Z

**1) `{{prefix}}cat_roster` — Local mirror (remote is authority)**

```sql
CREATE TABLE IF NOT EXISTS {{prefix}}cat_roster (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  remote_id VARCHAR(64) NOT NULL,
  label VARCHAR(191) NOT NULL,
  type ENUM('person','brand','other') NOT NULL DEFAULT 'person',
  avatar_url VARCHAR(255) NULL,
  meta LONGTEXT NULL,
  etag VARCHAR(64) NULL,
  last_sync_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uniq_remote_id (remote_id),
  KEY idx_label (label),
  KEY idx_updated_at (updated_at)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_520_ci;
```

**2) `{{prefix}}cat_observation` — Review artifacts**

```sql
CREATE TABLE IF NOT EXISTS {{prefix}}cat_observation (
  observation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  session_id VARCHAR(64) NULL,
  attachment_id BIGINT UNSIGNED NOT NULL,
  bbox JSON NULL,
  confidence DECIMAL(5,4) NULL,
  assigned_roster_id BIGINT UNSIGNED NULL,
  status ENUM('pending','confirmed','rejected') NOT NULL DEFAULT 'pending',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (observation_id),
  KEY idx_attachment (attachment_id),
  KEY idx_roster (assigned_roster_id),
  KEY idx_created_at (created_at),
  CONSTRAINT fk_obs_roster FOREIGN KEY (assigned_roster_id) REFERENCES {{prefix}}cat_roster(id) ON DELETE SET NULL
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_520_ci;
```

**3) `{{prefix}}cat_sync_queue` — Retry/Offline queue**

```sql
CREATE TABLE IF NOT EXISTS {{prefix}}cat_sync_queue (
  queue_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  kind ENUM('confirm_match','create_roster','update_roster','delete_roster') NOT NULL,
  payload LONGTEXT NOT NULL,
  attempts TINYINT UNSIGNED NOT NULL DEFAULT 0,
  last_error TEXT NULL,
  available_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (queue_id),
  KEY idx_kind (kind),
  KEY idx_available (available_at)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_520_ci;
```

## Appendix B: Remote Contract (v1) — Database-Backed API

**Roster Management:**

- `POST /api/v0/roster` → Create roster entry; returns `{id, remote_id, label, revision, etag}`
  - Request: `{label, type, display_name?, metadata?}`
  - Database: Insert into `roster_entities` with tenant_id from RLS context
- `PUT /api/v0/roster/{id}` → Update roster entry; returns `{etag, revision}`
  - Request: `{label?, display_name?, metadata?}`
  - Database: Update `roster_entities`, increment revision
- `DELETE /api/v0/roster/{id}` → Hard delete roster entry (cascade reference + augmented embeddings)
  - Database: Delete from `roster_entities` (ON DELETE CASCADE)
- `GET /api/v0/roster` → List roster entries with delta sync support
  - Headers: `If-None-Match: W/"etag"` → 304 Not Modified or 200 with delta
  - Query: `?since=revision` for incremental sync
  - Database: `SELECT * FROM roster_entities WHERE tenant_id = :tenant_id AND revision > :since`

**Embeddings & Reference Images:**

- `POST /api/v0/roster/{id}/embeddings` → Add reference embedding(s) from curated images
  - Request: `{embeddings: [embedding_vector], image_paths?: [string], metadata?: object}`
  - Database: Batch insert into `reference_embeddings`
- `POST /api/v0/roster/{id}/confirm` → Record confirmed observation (progressive learning)
  - Request: `{observation_id: UUID, embedding: vector, attachment_id?, bbox?, confidence?, quality_tier: "high"|"medium"|"low"}`
  - Database: Insert into `augmented_embeddings` (idempotent via observation_id UNIQUE)
  - Side Effect: Refresh materialized view `roster_aggregate_embeddings`, trigger FAISS hot-reload
  - Returns: `{etag, revision, aggregate_updated: true}`

**Recognition & Search:**

- `POST /api/v0/recognize` → Detect and identify faces/brands in image
  - Request: `{image_url: string, crops?: [{x,y,w,h}]}`
  - Process: Detect faces → extract embeddings → search aggregate embeddings (pgvector or FAISS)
  - Returns: `{matches: [{roster_entry_id, label, similarity, bbox}], suggestions: [{bbox, embedding}]}`
  - Database: Query `roster_aggregate_embeddings` with pgvector cosine similarity or FAISS search
- `POST /api/v0/search` → Explicit embedding search (bypass detection)
  - Request: `{embedding: vector, top_k?: int}`
  - Database: `SELECT roster_entry_id, aggregate_embedding <=> :embedding AS distance FROM roster_aggregate_embeddings ORDER BY distance LIMIT :top_k`

**Health & Monitoring:**

- `GET /api/v0/health` → Service health check
  - Returns: `{status: "healthy", database: "connected", faiss: "enabled"|"disabled"}`
- `GET /api/v0/stats` → Corpus statistics
  - Returns: `{total_roster_entries, total_reference_embeddings, total_augmented_embeddings, faiss_index_size?}`

**Authentication & Multi-Tenancy:**

- Auth: API key (scoped to tenant) or OAuth2 PAT
- Headers: `X-API-Key: <tenant_api_key>`, `X-Request-Id: <uuid>` (tracing), `Idempotency-Key: <uuid>` (writes)
- RLS: Every request executes `SET LOCAL app.tenant_id = :tenant_id` before queries (PostgreSQL row-level security)
- Versioning: `Accept: application/vnd.cat+json;version=1`

**Database Schema References:**

- Tenants: `tenants(id, name, plan, created_at)`
- Roster: `roster_entities(id, tenant_id, label, type, display_name, meta, revision, created_at, updated_at)`
- Reference Embeddings: `reference_embeddings(id, tenant_id, roster_entry_id, embedding vector(512), image_path, metadata, created_at)`
- Augmented Embeddings: `augmented_embeddings(id, tenant_id, roster_entry_id, observation_id UNIQUE, embedding vector(512), source, attachment_id, bbox, confidence, quality_tier, created_at)`
- Aggregates: `roster_aggregate_embeddings` (materialized view with weighted average by quality tier)

See `docs/tasks/backend-clustering-persitence-tasks.md` Section N2 for complete API catalog with request/response schemas.

## Appendix C: Caching & Retention

- Local roster mirror: persistent; purge on remote delete or uninstall.
- Observations: 90-day rolling purge by default (configurable).
- Avatars: persistent local derived assets; remove on remote delete or uninstall.
- Remote embeddings/roster: retained indefinitely; in-memory roster cache TTL ~5 minutes (for speed only).

## Appendix D: Q&A

Why Hybrid? Single source of truth remotely; fast UX locally; keeps product moat; easier compliance.  
Are embeddings ever stored in WP? No.  
What if service is down? Work continues from cache; new writes queue and replay.  
GDPR/DSAR? “Delete Person” calls remote delete; local mirror and avatars removed immediately.  
How big can the roster get? Tens of thousands per tenant on modest infra; plan tiers cap storage/throughput.  
Do we upload full images? No — only transient crops/URLs for embedding; originals stay in WP.
