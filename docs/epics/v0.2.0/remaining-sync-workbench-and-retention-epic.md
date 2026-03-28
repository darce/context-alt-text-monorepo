# Remaining Sync, Workbench, and Retention Work

## Problem Statement

Five v0.2.0 epics have been evaluated against MCP handoff history, git history, and on-disk implementation evidence. Two epics are fully closed (Recognition UX and Ergonomics; Autonomous Lane Orchestration). One epic's core scope is closed with deferred stretch goals (Phase 5 Retention). Two epics have genuinely unimplemented checklist items remaining (Sovereign Sync Expansion; Recognition State Reconciliation deferred items). Additionally, the Deferred UX Ergonomics routing document forwards three items that overlap with the sovereign sync scope.

This epic consolidates all remaining undelivered work into a single plan with clear phasing and dependency order.

## Source Documents and Completion Status

| Document                                                                                                                           | Status                                                                                                                                             | Remaining                                                                               |
| ---------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| [recognition-ux-and-ergonomics-epic.md](recognition-ux-and-ergonomics-epic.md)                                                     | **Closed.** All phases complete.                                                                                                                   | None                                                                                    |
| [autonomous-lane-orchestration-epic.md](autonomous-lane-orchestration-epic.md)                                                     | **Delivered.** Daemon 1-10 all complete per MCP; epic checklist never updated.                                                                     | None (checklist stale; implementation verified via 362 passing tests and MCP dashboard) |
| [recognition-state-reconciliation-and-offline-continuity-epic.md](recognition-state-reconciliation-and-offline-continuity-epic.md) | **Phases 1-4 complete. Phase 5 complete** (epic text stale; task plan has all [x], implementation on disk). **Post-v0.2.0 deferred items remain.** | 6 deferred items                                                                        |
| [sovereign-sync-and-workbench-ux-epic.md](sovereign-sync-and-workbench-ux-epic.md)                                                 | Track A: 2/7 complete. Track B: 4/6 complete.                                                                                                      | 5 sync architecture items; 2 workbench IA items                                         |
| [deferred-ux-ergonomics-post-epic-task-plan.md](../../tasks/6.0/deferred-ux-ergonomics-post-epic-task-plan.md)                     | Routing document only. Routes 3 items to reconciliation epic.                                                                                      | 3 items (absorbed across Phases 1, 3, and 5 below)                                      |

### Stale Checklist Note

The autonomous-lane-orchestration epic and the reconciliation epic Phase 5 section both show unchecked items that are, in fact, delivered. The implementation files exist (`review_runner.py`, `lane_exec.py`, `worker_daemon.py`, `orchestrator_daemon.py`, `retention.py`, `RetentionPage.tsx`, `class-retention-controller.php`), MCP task history confirms completion (daemon-1 through daemon-10; phase-5-retention-export-and-audit-controls), and tests pass. Those checklists should be updated but their stale state does not indicate missing work.

---

## Delivery Phases

### Phase 1: Delta Ingest and Drift Reconciliation

Replace the current snapshot-only sync path with incremental delta ingest and add drift detection for offline periods.

**Prerequisites**: Phases 1-3 of the reconciliation epic (all delivered; outbox, replay, sync state infrastructure exists).

**Scope**:

- Implement a delta ingest path on the WordPress side that accepts incremental clustering changes from the backend and falls back to full snapshot when the delta chain is broken or stale.
- Implement drift reconciliation logic that detects divergence between local projection and backend state accumulated during offline periods, and replays or flags unresolvable drift.
- Add conflict-safe replay policy so that drift reconciliation respects curated local state and does not silently overwrite user decisions.

**Source items**:

- Sovereign Sync Track A: "Implement delta ingest path with snapshot fallback"
- Sovereign Sync Track A: "Implement drift reconciliation flow and conflict-safe replay policy"
- Reconciliation Epic Deferred: "Replace snapshot-heavy sync with richer delta ingest"
- Deferred UX Routing: "Delta ingest and drift reconciliation"

**Code anchors**:

- `apps/prototype-wp-alt-context/src/sovereign/sync/` (outbox-writer, outbox-drain, outbox-dispatcher already exist)
- `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` (current snapshot endpoint; delta endpoint lives alongside)
- `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php` (current projector; delta path extends this)

### Phase 2: Topology Completion (Representative Parity and Compound Accept)

Complete the topology mutation surface so that representative pin/unpin and compound cluster-merge acceptance work end-to-end through the durable replay contract.

**Prerequisites**: Phases 1-3 of the reconciliation epic (all delivered; snapshot projection and outbox/replay primitives exist). Representative pin/unpin can proceed independently of delta ingest since the current snapshot path already projects cluster state. If a sub-item needs delta-aware replay, call that out narrowly rather than gating all of Phase 2.

**Scope**:

- Extend the backend snapshot/export and WordPress projection schema so representative `id` and `is_pinned` state survive sync.
- Wire the existing manual pin endpoint into the durable replay/outbox contract with round-trip verification.
- Complete the `cluster_merged` accept-machine revert contract: when the operator accepts a merge, the system records moved-member provenance so that future reclustering events do not silently undo a curated merge.

**Source items**:

- Sovereign Sync Track A: "Implement representative projection and pin/unpin replay parity"
- Sovereign Sync Track A: "Complete `cluster_merged` accept-machine revert contract with moved-member provenance"
- Phase 5 Retention "Moved Out": representative pin/unpin parity
- Phase 5 Retention "Moved Out": `cluster_merged` compound accept

**Code anchors**:

- `apps/prototype-description-service/recognition/domain/` (cluster, identity, representative models)
- `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php`
- `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-writer.php`

### Phase 3: Bidirectional Conflict Resolution

Add operator-mediated conflict resolution for person-name edits and other bidirectional curation conflicts where both local and backend state changed the same entity.

**Prerequisites**: Phase 1 (delta ingest surfaces incoming proposals); Phase 2 (topology mutations provide the acceptance/revert contract patterns this phase reuses).

**Scope**:

- Implement bidirectional conflict resolution UI in the existing conflict inbox so operators can review, accept, or reject backend-proposed changes to person names and other curated fields.
- Extend the conflict record schema if needed to capture the backend-proposed value alongside the local curated value.
- Wire resolution actions through the existing outbox/replay contract.

**Source items**:

- Sovereign Sync Track A: "Implement bidirectional conflict resolution for person-name edits"
- Deferred UX Routing: "Operator-facing person-name conflict UX for existing replay conflicts"

**Code anchors**:

- `apps/prototype-wp-alt-context/src/sovereign/sync/class-conflict-resolution-service.php`
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/ConflictInbox.tsx` (existing conflict inbox component)
- `apps/prototype-wp-alt-context/src/api/class-conflict-controller.php`

### Phase 4: Workbench Information Architecture

Migrate Batch functionality from the Workbench to the Dashboard and simplify the Workbench to Scan + Confirm only.

**Prerequisites**: None (UI-only; independent of sync architecture phases).

**Scope**:

- Move Batch tab content and logic from the Workbench page to the Dashboard page, adapting it to the Dashboard's layout and navigation patterns.
- Remove the Batch tab from the Workbench, leaving only Scan and Confirm tabs.
- Verify that existing Batch workflows (bulk alt-text generation, bulk publish) continue to function from their new Dashboard location.

**Source items**:

- Sovereign Sync Track B: "Migrate Batch functionality from Workbench tab to Dashboard"
- Sovereign Sync Track B: "Remove Batch tab from Workbench (reduce to Scan + Confirm)"

**Code anchors**:

- `apps/prototype-wp-alt-context/js/admin/pages/workbench/BatchTabContent.tsx` (source; to be moved)
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx` (target)
- `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx` (simplify; tab orchestration lives here)

### Phase 5: Machine Proposals Infrastructure

Add backend-side storage and API support for first-class machine proposals that are separate from committed cluster state, and build operator tooling for reviewing and accepting proposals.

**Prerequisites**: Phase 3 (conflict resolution provides the acceptance UX patterns that proposal review reuses). Machine proposal storage and API endpoints are independent of delta ingest; the transport mechanism can use the existing snapshot/curation-sync path until delta ingest is available.

**Scope**:

- Add backend storage for machine-generated proposals (name suggestions, cluster recommendations) as a first-class entity separate from committed cluster/identity state.
- Add API endpoints for listing, accepting, and rejecting proposals.
- Add operator-facing merge-preview and proposal acceptance workflows in the WordPress admin.

**Source items**:

- Reconciliation Epic Deferred: "Add backend-side storage and API support for first-class machine proposals"
- Reconciliation Epic Deferred: "Add richer operator tooling for merge-preview and proposal acceptance workflows"
- Deferred UX Routing: "Backend-authored machine proposals for person name edits"

**Code anchors**:

- `apps/prototype-description-service/recognition/domain/` (new proposal model)
- `apps/prototype-description-service/recognition/interface_adapters/http/routers/` (new proposal router)
- `apps/prototype-wp-alt-context/js/admin/pages/roster/` (proposal review UI)

### Phase 6: Retention Stretch Goals

Extend the delivered retention, export, and audit surface with capabilities deferred from Phase 5 of the reconciliation epic.

**Prerequisites**: All of Phase 5 retention infrastructure (already delivered).

**Scope**:

- Async/file-based export for large tenants (avoid HTTP timeout on bulk export).
- Paginated full audit event log page with filtering.
- Scheduled disposal worker that auto-purges on a configured interval.
- Export format versioning and import for cross-site migration.
- Embedding-level disposal tracking (per-embedding retain/purge state vs. per-identity).
- Retention policy presets (e.g., "GDPR mode" that applies a standard retention posture).

**Source items**:

- Phase 5 Retention Task Plan: all 6 stretch goals

**Code anchors**:

- `apps/prototype-description-service/recognition/interface_adapters/http/routers/retention.py`
- `apps/prototype-wp-alt-context/src/api/class-retention-controller.php`
- `apps/prototype-wp-alt-context/js/admin/pages/RetentionPage.tsx`

---

## Cross-Cutting: Worktree Lane Lifecycle Management

### Problem

The orchestration pipeline creates worktree lane directories (`context-alt-text-monorepo-<lane>`) and registers them in MCP, but has **no mechanism to clean them up** after a task completes. Completed Phase 5 lanes (`p5-backend-domain`, `p5-backend-http`, `p5-frontend`, `p5-wp-proxy`) and an older `frontend` lane persist as sibling directories of the monorepo root, along with their `codex/*` branches and 6 detached-HEAD Codex sandbox worktrees under `~/.codex/worktrees/`.

### Current State

- `lane-open` / `scripts/worktree-lane create` creates worktrees and registers MCP lane metadata.
- `lane-intake` cherry-picks commits and sets MCP lane status to `merged`, but leaves the worktree directory and branch in place.
- `lane-clean` only removes copied tooling drift within an existing worktree; it does not remove the worktree itself.
- `scripts/worktree-lane` has 4 subcommands (`create`, `brief`, `status`, `report`); none handle removal.
- No MCP tool (`upsert_worktree_lane`, `archive_task_state`, `handoff_close_check`) touches the filesystem.
- The `orchestrator_daemon` dispatches, intakes, and refreshes lanes but never prunes completed ones.
- Lane status has a `merged -> closed` transition in the schema, but nothing triggers it or acts on it.

### Proposed Tooling

Add a `lane-close` lifecycle stage that ties directory cleanup to the `closed` MCP status:

1. **`make lane-close TASK=<task> LANE=<lane>`** (Makefile target):
   - Validates the lane is in `merged` or `closed` status (refuses to close `active`/`blocked`/`review` lanes).
   - Validates no uncommitted changes exist in the worktree (fails with warning if dirty).
   - Runs `git worktree remove <path>` to remove the directory.
   - Runs `git branch -d <branch>` to delete the fully-merged branch (fails safely if not merged; operator can `--force`).
   - Transitions the MCP lane record to `closed` via `upsert_worktree_lane`.
   - Records a decision in MCP noting the cleanup.

2. **`make lane-prune TASK=<task>`** (batch cleanup):
   - Finds all lanes for the task in `merged` or `closed` status.
   - Runs `lane-close` for each.
   - Also prunes orphaned Codex sandbox worktrees (detached HEAD under `~/.codex/worktrees/`) via `git worktree prune`.

3. **`scripts/worktree-lane close`** (new subcommand):
   - The implementation backing `lane-close`; handles the `git worktree remove` + branch deletion + MCP status update atomically (best-effort on each step, reports partial failures).

4. **Orchestrator daemon integration** (optional):
   - After a successful `lane-intake`, the daemon could auto-close the lane if a `AUTO_CLOSE_ON_INTAKE=1` flag is set.
   - Default behavior: leave the lane in `merged` so the operator can inspect before closing.

5. **MCP `close_worktree_lane` tool** (optional; for MCP-native agents):
   - Wraps the same logic as `lane-close` so agents in MCP-capable hosts can trigger cleanup without `run_in_terminal`.

### Immediate Cleanup (Phase 5 lanes)

The following worktrees and branches are safe to remove now that Phase 5 is fully intaked:

| Lane                 | Worktree Path                                         | Branch                    | Status                                      |
| -------------------- | ----------------------------------------------------- | ------------------------- | ------------------------------------------- |
| `p5-backend-domain`  | `../context-alt-text-monorepo-p5-backend-domain`      | `codex/p5-backend-domain` | Has 1 modified file (test); commits intaked |
| `p5-backend-http`    | `../context-alt-text-monorepo-p5-backend-http`        | `codex/p5-backend-http`   | Clean; shares HEAD with wp-proxy            |
| `p5-frontend`        | `../context-alt-text-monorepo-p5-frontend`            | `codex/p5-frontend`       | Clean                                       |
| `p5-wp-proxy`        | `../context-alt-text-monorepo-p5-wp-proxy`            | `codex/p5-wp-proxy`       | Clean; shares HEAD with backend-http        |
| `frontend`           | `../context-alt-text-monorepo-frontend`               | `codex/frontend`          | Older lane; verify before removing          |
| Codex sandboxes (x6) | `~/.codex/worktrees/{09ba,1f62,5f3c,9928,d712,e375}/` | (detached HEAD)           | Stale; safe to prune                        |

Until `lane-close` tooling is built, manual cleanup:

```bash
# From orchestrator root
# 1. Remove Phase 5 worktrees
for lane in p5-backend-domain p5-backend-http p5-frontend p5-wp-proxy; do
  git worktree remove "../context-alt-text-monorepo-$lane" 2>&1
done

# 2. Delete fully-merged branches
for lane in p5-backend-domain p5-backend-http p5-frontend p5-wp-proxy; do
  git branch -d "codex/$lane" 2>&1
done

# 3. Prune stale Codex sandbox worktrees
git worktree prune

# 4. Verify cleanup
git worktree list
git branch | grep codex/
```

**Note**: The `frontend` lane predates Phase 5. Verify its status independently before removing. The `p5-backend-domain` lane has one modified test file; discard or stash it before removal (use `--force` if the change is not needed).

---

## Deferred Beyond This Epic (Post-v0.2.0)

These items from the reconciliation epic are explicitly scoped out. They represent architectural shifts beyond the current plugin-service boundary model:

- Sovereignty tiers where WordPress becomes the authoritative long-term store for embeddings and machine proposals.
- Customer-controlled embedding authority, ephemeral compute APIs, and sovereignty-tier deployment modes.
- Tenant-level encryption, key-management hooks, and region-pinning compliance features.

---

## Consolidated Checklist

### Phase 1: Delta Ingest and Drift Reconciliation -- MOVED TO v0.3.0

- [x] Implement delta ingest path on the WordPress side with snapshot fallback. -- Moved to [sync-completion-and-retention-hardening-epic (v0.3.0)](../v0.3.0/sync-completion-and-retention-hardening-epic.md) Phase 1.
- [x] Implement drift reconciliation logic with conflict-safe replay policy. -- Moved to [sync-completion-and-retention-hardening-epic (v0.3.0)](../v0.3.0/sync-completion-and-retention-hardening-epic.md) Phase 2.
- [x] Add tests for delta chain break and stale-delta fallback scenarios. -- Moved to v0.3.0 Phase 1.

### Phase 2: Topology Completion -- COMPLETED

- [x] Extend projection schema for representative `id` and `is_pinned` state.
- [x] Wire representative pin/unpin through the durable replay/outbox contract.
- [x] Complete `cluster_merged` accept-machine revert with moved-member provenance.
- [x] Add round-trip verification tests for representative and merge mutations.

### Phase 3: Bidirectional Conflict Resolution -- COMPLETED

- [x] Extend conflict record schema for backend-proposed values.
- [x] Implement conflict resolution UI in conflict inbox for person-name edits.
- [x] Wire resolution actions through the outbox/replay contract.
- [x] Add tests for accept, reject, and re-conflict scenarios.

### Phase 4: Workbench Information Architecture -- COMPLETED

- [x] Migrate Batch tab content from Workbench to Dashboard.
- [x] Remove Batch tab from Workbench (Scan + Confirm only).
- [x] Verify Batch workflows function from their Dashboard location.

### Phase 5: Machine Proposals Infrastructure -- COMPLETED

- [x] Add backend proposal storage model separate from committed cluster state. -- Delivered as `identity_suggestions`, `cluster_merge_suggestions`, `name_suggestions` tables.
- [x] Add proposal list, accept, and reject API endpoints. -- Delivered via suggestions router + WP proxy controller.
- [x] Add merge-preview and proposal acceptance UI in WordPress admin. -- Delivered via frontend suggestion hooks and API functions.
- [x] Add tests for proposal lifecycle (create, accept, reject, expire).

### Phase 6: Retention Stretch Goals -- PARTIALLY COMPLETED; REMAINDER MOVED TO v0.3.0

- [x] Async/file-based export for large tenants.
- [x] Paginated full audit event log page with filtering. -- Delivered via AuditTimeline component + audit REST endpoints.
- [x] Scheduled disposal worker (auto-purge on interval).
- [x] Export format versioning and import for cross-site migration. -- Export format versioning moved to [sync-completion-and-retention-hardening-epic (v0.3.0)](../v0.3.0/sync-completion-and-retention-hardening-epic.md) Phase 3.
- [x] Embedding-level disposal tracking. -- Moved to [sync-completion-and-retention-hardening-epic (v0.3.0)](../v0.3.0/sync-completion-and-retention-hardening-epic.md) Phase 4.
- [x] Retention policy presets (e.g., "GDPR mode").

### Cross-Cutting: Worktree Lane Lifecycle Management -- COMPLETED

- [x] Add `scripts/worktree-lane close` subcommand (worktree remove + branch delete + MCP status update).
- [x] Add `make lane-close` Makefile target with status and dirty-state guards.
- [x] Add `make lane-prune` batch cleanup target for all merged/closed lanes + Codex sandbox pruning.
- [x] Clean up Phase 5 worktree directories and branches (manual or via new tooling).
- [x] Optionally add `close_worktree_lane` MCP tool for MCP-native agents.
- [x] Optionally integrate auto-close into orchestrator daemon post-intake.
