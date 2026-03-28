# Deferred: Retention and Audit Stretch Goals

## Source

Deferred from [sync-completion-and-retention-hardening-epic.md](../epics/v0.3.0/sync-completion-and-retention-hardening-epic.md) (v0.3.0), "Deferred (Post-v0.3.0)" section.

## Why Deferred

The v0.3.0 retention epic delivers the core building blocks: export format versioning and per-embedding disposal tracking. The items below build on those foundations but are not required for the v0.3.0 MVP. They are deferred to avoid scope creep against the four focused v0.3.0 phases.

**Prerequisite state that must exist before revisiting:**
- Export format versioning shipped and stable (v0.3.0 Phase 3).
- Embedding-level disposal audit trail operational (v0.3.0 Phase 4).

## Deferred Items

### Multi-Version Export Import Migration

> **Item**: Read older format versions and upgrade on import (cross-site migration path).

The v0.3.0 export versioning work stamps a `format_version` header on every new export. It does not implement a reader that can parse exports produced with older format versions and upgrade them to the current schema. This is needed for cross-site migration scenarios where an operator exports data from an older plugin version and imports it into a newer one.

This requires:
- A version registry mapping `format_version` values to migration transforms.
- An import endpoint or CLI tool that detects the format version and applies the appropriate migration chain.
- Tests for upgrading from version N-1 to N.

**Dependency**: at least one version increment must exist before this is meaningful to implement. Activate after the first breaking export format change.

**Likely home when activated**: a follow-on phase of `sync-completion-and-retention-hardening-epic.md`, or a dedicated migration tooling task plan.

---

### GDPR-Specific Retention Policy Presets

> **Item**: GDPR mode -- a curated retention policy preset applying a standard right-to-erasure posture beyond the current "purge all" disposal.

The current retention system supports explicit purge operations, but does not model the GDPR Article 17 (right to erasure) lifecycle as a first-class workflow. A "GDPR mode" preset would:
- Define a retention window (e.g., auto-purge biometric state N days after last use).
- Enforce the erasure response flow when a data-subject request arrives (identify which records belong to the subject, purge them, emit a verifiable audit event).
- Produce a compliance certificate export that documents the erasure for regulatory records.

**Dependency**: embedding-level disposal tracking (v0.3.0 Phase 4) is a prerequisite so the erasure certificate can enumerate individual embedding disposals, not just cluster-level purges.

**Likely home when activated**: a compliance or enterprise-readiness epic, or an extended phase of `sync-completion-and-retention-hardening-epic.md`.

---

### Paginated Full Audit Event Log with Advanced Filtering

> **Item**: A dedicated paginated audit log page with filtering by actor, action, date range, and entity type.

The v0.3.0 `AuditTimeline` component shows a timeline of recent audit events. It is sufficient for the MVP but does not support deep pagination, multi-field filtering, export of the audit log itself, or long-term audit history browsing. Operators running compliance reviews need to search across months of audit history and filter by specific actors, actions, or data subjects.

This requires:
- Backend audit query endpoint supporting `actor`, `action`, `entity_type`, `created_before`, `created_after`, `limit`, and `offset` parameters (partial support exists; needs full coverage).
- Frontend audit log page with filter controls, date range picker, and paginated results table.
- Audit log export (CSV or JSON) for offline compliance review.

**Dependency**: the current `AuditTimeline` component and backend `/retention/audit` endpoint provide the foundation. This item extends them rather than replacing them.

**Likely home when activated**: a compliance UX task plan or a Phase 5 of `sync-completion-and-retention-hardening-epic.md`.
