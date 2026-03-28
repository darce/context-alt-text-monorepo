# ADR-004: Sync Completion and Retention Hardening Rationale

## Status

Accepted

## Date

2025-07-18

## Context

The v0.2.0 release cycle delivered the core sync pipeline (snapshot projector, outbox drain, conflict resolution), retention controls (policy, export, purge, audit), and the full suggestion/proposal lifecycle. However, a full audit of the five v0.2.0 epics revealed seven genuinely open hardening items spread across three separate epics. These items share a common theme: they close the gap between "functional sync and retention" and "contractually hardened sync and retention."

This ADR documents why the work described in the [sync-completion-and-retention-hardening-epic.md](../epics/v0.3.0/sync-completion-and-retention-hardening-epic.md) is necessary and traces each phase to the roadmap items it fulfills.

### Why This Work is Needed

**1. Delta sync exists but lacks contractual safety.** The backend and WordPress delta ingest path both work today, but there is no shared contract in `packages/shared-contracts/`, no explicit deletion/tombstone semantics, and no documented fallback behavior when a delta chain breaks. Without these, any future consumer of the delta surface must reverse-engineer behavior from implementation rather than relying on a stable contract. This is a reliability and maintainability risk, not a feature gap.

**2. No mechanism exists to detect or repair state divergence.** If a WordPress site misses an outbox drain, loses a partial sync, or encounters a transient backend failure, the local projected state silently diverges from the recognition service. There is no detection, no operator visibility, and no repair path short of a manual full re-sync. The system cannot make any trustworthiness guarantee about local state accuracy.

**3. Export versioning is implicit, not contracted.** Retention exports already emit an integer `schema_version`, but this field is not treated as a first-class shared boundary. It is not propagated consistently through the HTTP response envelope or the WordPress proxy layer. Future export consumers (import tools, migration scripts, compliance auditors) cannot rely on a stable version contract.

**4. Embedding disposal has no audit granularity.** Purge operations delete embeddings in bulk alongside their parent clusters and record only cluster-level disposal events. Privacy officers reviewing the audit timeline cannot trace individual embedding lifecycle events. This limits the strength of any compliance claim about biometric data handling.

**5. Scattered open items across three epics create coordination risk.** Seven related items were distributed across `remaining-sync-workbench-and-retention-epic.md`, `sovereign-sync-and-workbench-ux-epic.md`, and `recognition-ux-and-ergonomics-epic.md`. Leaving them scattered creates duplicate tracking, unclear ownership, and the risk that a future planning pass marks them as complete because the parent epics are otherwise finished.

## Decision

Consolidate all seven open sync and retention hardening items into a single v0.3.0 epic with four phases, each mapping to a distinct hardening concern. The epic is scoped strictly to hardening existing surfaces; it does not introduce new product features.

## Roadmap Traceability

### Phase 1: Delta Ingest Hardening

Implements the following roadmap items:

| Roadmap                                                         | Item                                                                    | Reference                                                                    |
| --------------------------------------------------------------- | ----------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| [roadmap-v4.md](../roadmaps/roadmap-v4.md) Epic D checklist     | "Delta ingest with snapshot fallback"                                   | Unchecked item in the Epic D consolidated checklist                          |
| [roadmap-v4.md](../roadmaps/roadmap-v4.md) Current Gaps         | "Sync is full-snapshot only; no outbox, delta, or drift reconciliation" | Listed as a current gap; delta ingest closes the "delta" portion             |
| [roadmap-v3.hybrid.md](../roadmaps/roadmap-v3.hybrid.md) Epic E | "Outbox pattern with Action Scheduler (v0.2+)"                          | Delta ingest is the consumer-side complement of outbox-driven sync evolution |

v0.2.0 source items consolidated:

- `remaining-sync-workbench-and-retention-epic.md` Phase 1: "Delta ingest path with snapshot fallback"
- `sovereign-sync-and-workbench-ux-epic.md` Track A: "Delta ingest" (duplicate; consolidated)
- `recognition-ux-and-ergonomics-epic.md` Deferred: "Delta ingest and drift reconciliation" (duplicate; consolidated)

### Phase 2: Drift Reconciliation

Implements the following roadmap items:

| Roadmap                                                                           | Item                                                                                                    | Reference                                                                                                                                                    |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [roadmap-v4.md](../roadmaps/roadmap-v4.md) Epic D checklist                       | "Drift reconciliation with curation-safe conflict policy"                                               | Unchecked item in the Epic D consolidated checklist                                                                                                          |
| [roadmap-v4.md](../roadmaps/roadmap-v4.md) Current Gaps                           | "Sync is full-snapshot only; no outbox, delta, or drift reconciliation"                                 | Listed as a current gap; drift reconciliation closes the "drift reconciliation" portion                                                                      |
| [roadmap-v4.md](../roadmaps/roadmap-v4.md) Sync scope additions                   | "Drift reconciliation surfaces conflicting person assignments instead of silently overwriting curation" | Explicit requirement that drift reconciliation must respect curation-first precedence                                                                        |
| [roadmap-v3.hybrid.md](../roadmaps/roadmap-v3.hybrid.md) Architectural Principles | "Sovereign local state"                                                                                 | Drift reconciliation is a direct consequence of the sovereign model: if WordPress owns the projection, it must be able to verify that projection is accurate |

v0.2.0 source items consolidated:

- `remaining-sync-workbench-and-retention-epic.md` Phase 1: "Drift reconciliation"
- `sovereign-sync-and-workbench-ux-epic.md` Track A: "Drift reconciliation" (duplicate; consolidated)
- `recognition-ux-and-ergonomics-epic.md` Deferred: "Delta ingest and drift reconciliation" (duplicate; consolidated)

### Phase 3: Export Version Metadata Hardening

Implements the following roadmap items:

| Roadmap                                                                                                                           | Item                                                                                | Reference                                                                                            |
| --------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| [recognition-privacy-hybrid-roadmap-2026-03-06.md](../roadmaps/recognition-privacy-hybrid-roadmap-2026-03-06.md) Phase 1          | "Add manual tenant-scoped purge and export endpoints for biometric-derived records" | Export endpoints must carry a stable version contract for downstream consumers to parse and validate |
| [recognition-privacy-hybrid-roadmap-2026-03-06.md](../roadmaps/recognition-privacy-hybrid-roadmap-2026-03-06.md) Design Decisions | "Privacy controls are per-tenant and auditable"                                     | Auditability requires machine-readable export metadata, including a stable version field             |
| [roadmap-v3.hybrid.md](../roadmaps/roadmap-v3.hybrid.md) Epic F                                                                   | "Observability and Security: audit logs"                                            | Export versioning is the retention-specific instance of the broader auditability requirement         |

v0.2.0 source item:

- `remaining-sync-workbench-and-retention-epic.md` Phase 6: "Export format versioning and import"

### Phase 4: Embedding-Level Disposal Tracking

Implements the following roadmap items:

| Roadmap                                                                                                                              | Item                                                                                                                | Reference                                                                                                                |
| ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| [recognition-privacy-hybrid-roadmap-2026-03-06.md](../roadmaps/recognition-privacy-hybrid-roadmap-2026-03-06.md) Target Architecture | "Biometric retention is minimized by default" and "export, purge, and auditability become first-class capabilities" | Per-embedding disposal is the audit granularity required to make the "auditability" claim concrete                       |
| [recognition-privacy-hybrid-roadmap-2026-03-06.md](../roadmaps/recognition-privacy-hybrid-roadmap-2026-03-06.md) Phase 2             | "Add administrative visibility into what biometric state is currently retained per tenant"                          | Embedding-level events enable visibility into exactly which vectors were retained and which were disposed                |
| [recognition-privacy-hybrid-roadmap-2026-03-06.md](../roadmaps/recognition-privacy-hybrid-roadmap-2026-03-06.md) Data Model          | `embedding_purged_at`, `embedding_retained`, audit events for retain/purge actions                                  | The data model already anticipates per-embedding retention metadata and audit events; Phase 4 delivers the disposal side |
| [roadmap-v3.hybrid.md](../roadmaps/roadmap-v3.hybrid.md) Architectural Principles                                                    | "Privacy by design"                                                                                                 | Fine-grained disposal tracking is a direct implementation of privacy-by-design for biometric data                        |

v0.2.0 source item:

- `remaining-sync-workbench-and-retention-epic.md` Phase 6: "Embedding-level disposal tracking"

## Consolidation Summary

The seven open items from three v0.2.0 epics map to the four phases as follows:

| #   | v0.2.0 Epic                                              | Open Item                                | v0.3.0 Phase                         |
| --- | -------------------------------------------------------- | ---------------------------------------- | ------------------------------------ |
| 1   | `remaining-sync-workbench-and-retention-epic.md` Phase 1 | Delta ingest path with snapshot fallback | Phase 1                              |
| 2   | `remaining-sync-workbench-and-retention-epic.md` Phase 1 | Drift reconciliation                     | Phase 2                              |
| 3   | `remaining-sync-workbench-and-retention-epic.md` Phase 6 | Export format versioning and import      | Phase 3                              |
| 4   | `remaining-sync-workbench-and-retention-epic.md` Phase 6 | Embedding-level disposal tracking        | Phase 4                              |
| 5   | `sovereign-sync-and-workbench-ux-epic.md` Track A        | Delta ingest                             | Duplicate of #1; consolidated        |
| 6   | `sovereign-sync-and-workbench-ux-epic.md` Track A        | Drift reconciliation                     | Duplicate of #2; consolidated        |
| 7   | `recognition-ux-and-ergonomics-epic.md` Deferred         | Delta ingest and drift reconciliation    | Duplicate of #1 and #2; consolidated |

All other v0.2.0 checklist items were verified as implemented during the audit and closed in their parent epics.

## Consequences

- A single epic owns all remaining sync and retention hardening work, eliminating the coordination risk of scattered items across closed epics.
- Each phase has clear exit criteria and can be delivered independently.
- The v0.3.0 scope is strictly hardening; no new product features are introduced, which keeps the risk profile low.
- Multi-version export import migration is explicitly deferred to post-v0.3.0, keeping Phase 3 focused on contract propagation rather than backward-compatibility machinery.
- GDPR-specific retention policy presets are also deferred, keeping Phase 4 focused on audit granularity rather than policy configuration.

## References

- Epic: [sync-completion-and-retention-hardening-epic.md](../epics/v0.3.0/sync-completion-and-retention-hardening-epic.md)
- Active roadmap: [roadmap-v4.md](../roadmaps/roadmap-v4.md) (Epic D)
- Vision roadmap: [roadmap-v3.hybrid.md](../roadmaps/roadmap-v3.hybrid.md) (Epic E, Epic F)
- Privacy roadmap: [recognition-privacy-hybrid-roadmap-2026-03-06.md](../roadmaps/recognition-privacy-hybrid-roadmap-2026-03-06.md) (Phases 1-2)
- Related ADRs: [ADR-002: Person as First-Class Local Entity](ADR-002-person-as-first-class-local-entity.md)
