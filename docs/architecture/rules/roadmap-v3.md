# 🧭 Context Alt Text Roadmap v3.0 — MVP, Abilities + MCP Adapter

## 🎯 Core Objective

Ship a WordPress plugin that lets admins batch-generate semantically rich, identity-aware alt text and confirm known people/brands by invoking:

* a **self-hostable remote recognition service** (faces/brands; side profiles & partial occlusions) that performs detection, recognition, and roster synchronization, and
* a provider-agnostic LLM (captioning via PHP AI Client SDK).

### Active surfaces

| Area | Directory | Notes |
| --- | --- | --- |
| Frontend plugin | `context-alt-text/` | WordPress plugin, MCP adapter, shared PHP DTOs |
| Backend service | `__hugging-face/entity-identifier-api/` | FastAPI/HF Spaces microservice, OpenAPI source |
| Systems knowledge base | `docs/architecture/` | Roadmaps, rules, UML (`backend-uml/`, `frontend-uml/`), research prompts |

Agent integrations (VS Code Copilot, Claude, etc.) go through MCP (post‑MVP); WordPress admin UX continues to use internal REST for screens. Face identification happens exclusively in the backend recognition service; the WordPress UI no longer hosts a standalone face-tagging page in MVP.

---

## 🧱 Dashboard (Current Narrow MVP Scope)

The Dashboard UI has been intentionally reduced to ONLY surface the core accessibility signal:

1. “We found N images missing alt text” (primary status line – KEEP EXACT WORDING)
2. “Review in Panel” action (opens Media Library filtered to missing alt text)

All former First Run Scan (formerly "Magic Import") related panels, banners, demo draft sections, and experimental counts have been QUARANTINED (code retained but not executed). No additional widgets (jobs, drafts, banners) are required for this phase.

Notes:

* The historical typo / merged text after item 2 has been corrected. Only the two bullets above are in scope.
* A first-run scan MUST populate the missing alt text count within 30s of activation (or plugin install) so the dashboard line is meaningful immediately.
* When the count is not yet ready, the UI should still render the line with a spinner or a temporary “calculating…” state (future enhancement; not blocking this edit).
* Total image count debug output currently shown in development (e.g., `DEBUG: Total Images = 0 | With Alt = 0 | Missing = 0`) is temporary and will be removed once the corrected query & tests land.
* First Run Scan service / UI code (formerly Magic Import): quarantined; do NOT delete yet (scheduled for later cleanup milestone).
* Ensure counting logic treats BOTH (a) absence of the `_wp_attachment_image_alt` meta row AND (b) empty-string values as “missing”.
* Future (optional) enhancement: surface compliance percentage once counts are verified.

> Gating note (MVP): Abilities and MCP integration are scaffolded but disabled by default. They are behind feature flags and will be delivered post‑MVP. See "Feature flags and gating" below.

* Declare plugin capabilities as Abilities and expose them as MCP tools via MCP Adapter (Deferred: post‑MVP):

* cat/generate_alt_text
* cat/regenerate_alt_texts (batch)
* cat/create_roster_entry (delegates embeddings/recognition to backend service)
* cat/propagate (applies backend-provided matches to local media)

* LLM access is model-agnostic through the PHP AI Client SDK (GPT/Claude/Gemini, etc.).

* Recognition remains a self-hostable microservice (HF Space or your GPU box). No embeddings on the frontend.

Implementation guardrails for the admin UI:

* Keep the PHP-rendered dashboard entry screen for capability checks and menu wiring, then mount the SPA within it.
* Build the React admin app with the standard WordPress stack (`@wordpress/scripts` or Vite) and source REST endpoints + nonces via PHP.
* Default to SPA routes for new UI slices (dashboard widgets, media panel, roster, settings), migrating legacy fragments incrementally.
* Reserve server-rendered PHP fallbacks for scenarios that demand them (activation notices, hard failures).

Planned SPA navigation surfaces:

* **Dashboard Overview** – single-glance status of the recognition + alt-text workflow (missing counts, recent recognitions, queued jobs).
* **Automation Queue** – bulk job manager (naming replacement for "Jobs") tracking generation, propagation, and sync runs.
* **Roster Manager** – CRUD for roster entities plus touchpoints for how matches are captured during alt-text generation (decision pending on when new entities are created vs. linked).
* **Alt-Text Workbench** – dedicated list of media missing alt text (new name to avoid clashing with the native Media Library) with workflow tooling, recognition triggers, and selection helpers.
* **Settings** – plugin configuration (base URLs, feature toggles, timeouts).
* **Account Center** – account-scoped details such as API keys, billing, entitlements; lives separately to keep operational controls distinct from general settings.

## 🔧 Feature flags and gating (MVP)

* CAT_ENABLE_ABILITIES: default false. When true (or filtered via `cat_enable_abilities`), Abilities registrar boots and tools are registered.
* CAT_ENABLE_MCP: default false. Reserved for MCP server wiring. MCP UI is removed for MVP.
 
---

* Admin UI for MCP tools: removed (no menu). Abilities/MCP are not part of MVP acceptance criteria.
* Post‑MVP: turn flags on in wp-config.php or programmatically via filters.

Diagram note: the legacy phase diagrams are deprecated; use the canonical `docs/architecture/backend-uml/unified_architecture.mermaid` alongside the flow-specific diagrams in `docs/architecture/frontend-uml/`. Recognition and embeddings are remote-only.

## ✅ Phase 1: MVP Release (Target)

### 🔐 Architecture Goals

* Fully open-source local plugin logic.
* Remote visual recognition engine **self-hosted on Hugging Face Spaces or similar infrastructure**.
* Remote engine supports **non-frontal, partially obscured recognition** (e.g., side profiles, masks, cropped logos).
* Avoid usage-based billing and centralized rate limits.
* MCP for agent access; internal REST for WP admin UI.

### Glossary

* DetectedFace (FE) → transient boxes.
* FaceObservation (BE) → persisted box row for matching.
* ObservationEmbedding (BE) → vector for an observation.
* AugmentedEmbedding (BE) → canonical roster vector.

### Epic A — Foundations & Safety (supports all participants) [PLANNED]

#### Implementation (A) [PLANNED]

* Composer + PSR-4; namespaces under `src/` (Abilities, Services, Domain, Admin).
* Main bootstrap with headers, constants, lightweight container/wiring.
* Lifecycle hooks: activation, deactivation, uninstall (clean tables/options/caps).
* Abilities layer scaffolded and feature-gated off by default.
* MCP server scaffolding gated off for MVP.
* Scan for missing alt text on plugin activation (fresh install + upgrade path).

#### TDD (A) [PLANNED]

* Unit tests for activation/deactivation/uninstall behavior exist and pass.
* Abilities registrar tests skip correctly when feature-gated.
* Scan tests for missing alt text on activation pass.

#### DoD [PLANNED]

* First-run scan for missing alt text functional; tests green.
* PHPCS, unit tests pass in CI.
* MCP tool stubs remain gated off for MVP.

### Epic B — Data Model & Migrations [PLANNED]

#### Implementation (B) [PLANNED]

* cat_roster: id, label, type(person|brand), meta(json), created_at, updated_at.
* cat_observation (session-scoped): observation_id PK, session_id, attachment_id, bbox(json), confidence(float), assigned_roster_id (nullable), status(enum), created_at.
* Migrations on activation; smooth re-runs on version bump; uninstall cleans up.
* DetectedFace (FE) persists as FaceObservation (BE); ObservationEmbedding and AugmentedEmbedding backend-only.
* Add compliance % complete, progress bar.
* Add “Next Image to Fix” queue.
* Integrate Live Preview slider in Drafts sub-view.

#### TDD (B) [PLANNED]

* Migration tests cover table creation, columns, idempotency, and versioning.
* Pending: coverage for compliance percentage and draft queue.

#### DoD (B)

* cat_roster + cat_observation tables live with migrations/tests.
* Draft queue actionable from admin panel.
* Compliance percentage displayed with tests.

### Epic C — Recognition Pipeline (WP ↔ HF) [PLANNED]

Implementation focus:

* RecognitionClient handles analyzeScene + embeddings with retries, exponential backoff.
* RosterSyncClient wraps remote roster CRUD with idempotency keys.
* WP-CLI commands for health/analyze to unblock ops.
* Backend HF service exposes /analyze-scene, /embeddings, /roster endpoints with schema parity.

TDD:

* Contract tests comparing PHP DTOs vs OpenAPI examples.
* PHPUnit coverage for retries, error mapping.
* FastAPI tests for embeddings/analysis returning golden payloads.

DoD:

* Round trip: roster entry created in WP persists remote_id, visible via backend GET /roster.
* Analyze scene triggered from WP returns labeled detections.
* Admin diagnostics surfaces health and recent errors.

### Epic D — Alt Text Generation [PLANNED]

Implementation:

* AltTextService composes prompt from SceneAnalysisResult + policy.
* AIClient chooses provider, enforces style guardrails.
* Admin UI to review/approve drafts.

TDD:

* Golden prompt composition tests.
* Provider-specific adapters with mock responses.

DoD:

* Draft alt text generated automatically for missing entries.
* Admin can accept/decline drafts with history log.

### Epic E — Propagation & Sync [PLANNED]

Implementation:

* Propagation job queue processes embeddings matches in batches.
* Conflict resolution ensures remote embeddings take precedence.
* Sync metrics persisted with WP-Cron aware scheduling.

TDD:

* Job queue unit tests with fake runners.
* Conflict policy characterization tests.

DoD:

* “Sync Recognition” action updates roster + media badges.
* Metrics page shows processed counts and conflicts.

### Epic F — Observability & Security [PLANNED]

Implementation:

* Structured logging with correlation IDs.
* Metrics exported via WP hooks + FastAPI instrumentation.
* API keys and origin allowlists enforced.

TDD:

* Logging assertions on error paths.
* Security tests for nonce/cap checks.

DoD:

* Ops run-book published.
* Alerting configured for error thresholds.

---

## 📦 Deliverables Summary

1. WordPress plugin (Context Alt Text) with MCP abilities ready but gated.
2. HF recognition backend deployable via Spaces or container.
3. Shared contract + UML docs maintained under `docs/architecture`.
4. Test suites (PHPUnit, Vitest, FastAPI pytest) covering pipeline happy paths + failure modes.
5. Ops guides: environment variables, local tunnel, smoke scripts.

## 🧪 Validation Checklist

- [ ] `composer test` (PHPUnit) passes.
- [ ] `npm test` / `npx vitest run` passes or appropriately skipped.
- [ ] FastAPI pytest suite covers analyze + embeddings.
- [ ] Contract tests compare OpenAPI schema with PHP DTOs.
- [ ] Playbook for manual smoke (WP admin + HF backend) published.

## 🗺️ Long-Term Backlog (Post-MVP)

- MCP tool enablement & agent documentation.
- Advanced roster analytics (duplicate detection, tagging suggestions).
- Multi-tenant backend support with per-site API keys.
- Offline processing queue using managed job runner (e.g., Temporal, PydanticWorker).
- Accessibility insights dashboard with trendlines and digests.

## 📚 References

- WordPress Plugin Handbook — https://developer.wordpress.org/plugins/
- FastAPI docs — https://fastapi.tiangolo.com/
- Hugging Face Spaces — https://huggingface.co/spaces
