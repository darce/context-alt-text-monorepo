# Roadmap Title: Context Alt Text – Assisted Face Identification UX

## Vision

Deliver an Apple Photos–style assisted labeling flow that groups visually similar, unknown faces, guides the user through confirmation, and cascades new identities across the media library with minimal manual effort. The core batch-identification experience lets the system form “face boxes” (clusters) around similar detections, label the tab of the encompassing box, and apply that roster identity to every cropped face inside it in one motion. Users can refine the cluster by selecting/deselecting thumbnails or dragging misgrouped faces into another person’s box before finalizing.

Maintain compliance with existing architecture guardrails (docs/architecture/rules/instructions.md) by keeping frontend clustering lightweight, offloading heavy workloads to the recognition service where possible, and preserving accessibility/performance guarantees. The recognition service participates early—fueling preliminary suggestions and high-confidence cluster hints—and again post-confirmation to reinforce embeddings for each roster entry so that accuracy improves over time without sacrificing user control or experience.

## Guiding Principles

Accuracy over volume: never sacrifice user trust; surface high-confidence clusters first, let users curate borderline matches.
Explicit user control: no auto-labeling without confirmation; provide clear undo and re-review paths.
Resource awareness: support throttled analysis of selected images/albums before whole-library sweeps.
Progressive disclosure: start with basic grouping and opt-in review; phase in automation (bulk confirmation, autosuggest) only after telemetry shows acceptable precision.

## Phase 0 – Foundations (Pre-work)

Align UX and engineering on target flows (wireframes of cluster grid, confirmation modal, bulk review screen).
Inventory current backend capabilities (FAISS availability, embedding freshness, roster size) and set accuracy metrics (precision/recall targets).
Create working branch feature/assisted-face-identification for implementation artifacts.

## Phase 1 – Unknown Face Discovery & Clustering

Extend media selection tooling to trigger face scanning on a subset (album selection dialog, max batch guardrails).
Implement scheduled/queued jobs (WP + recognition service) to:
Fetch new detections (reuse existing pipelines).
Compute embeddings (frontend fallback, backend preference).
Persist normalized unknown-face records (attachmentId, bbox, embeddingId).
Add clustering service abstraction:
Frontend: light MediaPipe grouping for on-the-fly clusters (<50 faces).
Backend: enqueue FAISS-based clustering for larger sets; store cluster_ids in observation metadata.
Surface “Unknown People” entry point in workbench: cluster cards (count, recency, sample thumbnail).

## Phase 2 – Assisted Identification Workflow

Cluster detail view with grid of cropped faces (lazy-loaded thumbnails, keyboard navigation).
Suggest existing roster matches:
Request recognition/suggest per cluster (batch limit).
Display confidence chips (High/Medium/Low) with explanation tooltip.
Confirmation flow:
Select identity (search roster/create new).
Present pre-selected subset of members (auto-selected based on threshold).
Allow manual deselect/select to correct false positives.
Persist observation/roster updates and mark faces as resolved.
Post-confirmation cascade:
Update all faces sharing embedding/cluster IDs.
Trigger re-scan of remaining clusters to eliminate confirmed faces.

## Phase 3 – Bulk Review & Automation Enhancements

“Review Later” queue: allow deferring ambiguous clusters; store user notes.
Smart ordering: prioritize clusters by confidence, user-specified people, or recency.
Background sync:
Periodic job to auto-draft labels when confidence > configurable threshold (no auto-confirm).
Notification badge + digest email summarizing new suggestions.
Telemetry hooks:
Track suggestion acceptance/rejection rates.
Record processing time, queue depth, error counts.

## Phase 4 – Performance, Quality & Polish

Optimize thumbnail generation and caching (WP image sizes, CDN hints).
Add offline/low-connectivity fallbacks:
When recognition service unavailable, fall back to client embeddings with conservative threshold.
Surface banner warning and disable bulk actions.
Accessibility & i18n validation (keyboard support in grids, screen reader labels, localized copy).
Comprehensive regression suite:
Integration tests for clustering + confirmation flow (MSW-backed API mocks).
Load testing scripts for large libraries (simulate thousands of embeddings).

## Cross-Cutting Tasks

Documentation: update admin guide, troubleshooting, architecture diagrams.
Migration scripts: ensure existing observations integrate with new cluster metadata.
Feature flags: wrap major steps (cluster UI, bulk confirmation) for staged rollout.

## Exit Criteria

≥95% precision on top-tier suggestions in staging.
User testing feedback confirms “assistive, not obstructive” experience.
Monitoring dashboards for clustering jobs, suggestion latency, and error rates in place.
