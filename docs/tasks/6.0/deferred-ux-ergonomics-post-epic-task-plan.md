# Deferred: UX Ergonomics Post-Epic Backlog

## Problem Statement

The Recognition UX and Plugin Ergonomics epic (v0.2.0) is complete. Two items were deferred during delivery because they depend on infrastructure that belongs to the reconciliation epic rather than the UX epic. This document tracks their origin and forward routing so they are not lost.

## Workflow Principles

- These items are **not blocked** -- they are intentionally sequenced after the UX epic because they require broader reconciliation architecture.
- Delta ingest and drift reconciliation are prerequisites for bidirectional conflict resolution.
- Both items are scoped under the [Recognition State Reconciliation + Offline Continuity](../../epics/v0.2.0/recognition-state-reconciliation-and-offline-continuity-epic.md) epic.

## Terminology

- **Delta ingest**: incremental import of backend clustering changes instead of full snapshot replacement.
- **Drift reconciliation**: detection and resolution of divergence between local projection and backend state that accumulated during offline periods.
- **Bidirectional conflict resolution**: operator-mediated merge when both local curation and backend compute changed the same entity.

## Current State Analysis

- The UX epic delivered durable outbox replay, conflict recording, and sync-status infrastructure.
- Snapshot-based sync is operational but does not yet support incremental deltas.
- Conflict records are stored but have no operator-facing resolution UI.
- Person name edits are local-only; backend person records accept the local name via curation sync but do not propose name changes back.

## Proposed Solution

Route both deferred items to the reconciliation epic where they fit naturally:

1. **Delta ingest and drift reconciliation** maps to Reconciliation Epic Phase 2 (Curation-First Merge Contract) and Phase 3 (Minimal Durable Sync Replay).
2. **Bidirectional conflict resolution for person name edits** maps to Reconciliation Epic Phase 4 (Offline and Conflict UX).

No implementation work is needed in this document. It exists only to close the UX epic cleanly.

## Functions to Change

_None -- this is a routing document._

## Related Files

| File | Note |
| --- | --- |
| `docs/epics/v0.2.0/recognition-ux-and-ergonomics-epic.md` | Source epic (closed) |
| `docs/epics/v0.2.0/recognition-state-reconciliation-and-offline-continuity-epic.md` | Target epic for deferred work |
| `docs/tasks/5.0/phase-5-sovereign-sync-person-push-task-plan.md` | Phase 5 task plan that delivered the sync primitives these items build on |

---

# Consolidated Checklist

## Completed (Delivered in Phase 5)

- [x] Action Scheduler integration (upgrade from WP cron drain) -- delivered as part of outbox drain.

## Routed to Reconciliation Epic

- [ ] Delta ingest and drift reconciliation -- Reconciliation Epic Phases 2-3.
- [ ] Bidirectional conflict resolution for person name edits -- Reconciliation Epic Phase 4.
