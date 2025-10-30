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

#### TDD (A) [PLANNED]

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

TDD:

- Logging assertions on error paths.
- Security tests for nonce/cap checks.

DoD:

- Ops run-book published.
- Alerting configured for error thresholds.

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
