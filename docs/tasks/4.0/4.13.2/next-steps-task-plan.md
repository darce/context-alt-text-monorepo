# 4.13.2 — Next Steps Task Plan

> **Parent epic**: v0.1.0 WordPress Sovereign Cluster Architecture
> **Predecessor**: `4.13.1` — Sovereign Phase 3 (dual-write + pull sync)
> **Scope**: Close Phase 3, execute Phase 4, reach v0.1.0 exit criteria

---

## Priority 1: Close Phase 3 Branch

**Goal**: Get `refactor/4.13.1-wp-sovereign-phase-3` merged to `main`.

### Checklist

- [ ] Run manual smoke test: label a cluster with backend stopped → restart backend → confirm sync reconciles and label persists
- [ ] Run manual smoke test: full cycle — clusters load via proxy → trigger analysis → stop backend → confirm clusters render from local projection
- [ ] Review `git diff --stat HEAD` (35 modified + 17 untracked) for anything that should not ship
- [ ] Stage and commit all Phase 3 work with conventional commit messages
- [ ] Re-run full test suites: `composer test` (141/452/0), `composer phpstan` (0 errors), `pytest` (476 pass)
- [ ] Sign off Phase 3 success criteria in `wp-sovereign-phase3-dual-write-task-plan.md`
- [ ] Merge branch to `main`
- [ ] Update epic checklist: mark Phase 3 COMPLETED

---

## Priority 2: Phase 4 — Thumbnail Deprecation

**Goal**: Remove `thumbnail_url` from all layers. Full plan in `thumbnail-deprecation-task-plan.md`.

### Checklist (summary — see full plan for ~50 items)

#### 2a — Backend Application Layer
- [ ] Remove `thumbnail_url` from domain models, Pydantic schemas, repository queries, and router responses
- [ ] Verify 476+ pytest tests still pass with field removed
- [ ] Verify frontend gracefully handles missing field (no JS errors)

#### 2b — Backend Migration
- [ ] Create Alembic migration to DROP `thumbnail_url` column from `clusters` table
- [ ] Test migration up/down on dev database
- [ ] Verify materialized view refresh still succeeds

#### 2c — Plugin Shim Removal
- [ ] Remove `thumbnail_url` proxy-response fallback in `ClustersController`
- [ ] Remove dead `is_http_url()` branch and duplicate key assignments
- [ ] Update `SnapshotProjector` if it maps `thumbnail_url`
- [ ] Run `composer test` — 0 failures, 0 errors

#### 2d — Frontend Cleanup
- [ ] Remove `thumbnail_url` from TS interface definitions (~10 types)
- [ ] Remove dead `IdentityThumbnail` fast-path component
- [ ] Remove suggestion thumbnail fields
- [ ] Run `vitest` — 0 failures

---

## Priority 3: Phase 4 — Proxy→Facade Replacement

**Goal**: Replace runtime HTTP proxy dependency with local service facade for cluster reads.

### Checklist

- [ ] Create `ClusterFacade` service class that reads from local sovereign tables only
- [ ] Wire `ClustersController` to use `ClusterFacade` instead of proxy for read operations
- [ ] Ensure `SyncPullJob` remains the only component making backend HTTP calls
- [ ] Verify offline-first capability: plugin operates fully with backend unreachable (reads from local)
- [ ] Run `composer test` — 0 failures

---

## Priority 4: Phase 4 — Contracts & Diagrams

**Goal**: Update architecture documentation to reflect the sovereign model.

### Checklist

- [ ] Update `packages/shared-contracts/` to reflect snapshot endpoint schema
- [ ] Create architecture diagram showing sovereign data flow (plugin → local tables → sync job → backend)
- [ ] Update epic: mark Phase 4 COMPLETED
- [ ] Tag release `v0.1.0`

---

## Deferred to v0.2+

These items are explicitly out of scope for v0.1.0:

| ID | Item | Trigger to Revisit |
|---|---|---|
| D1 | Outbox table (`wp_acx_cluster_operations`) | When write volume exceeds sync-on-read capacity |
| D2 | Action Scheduler for background sync | When WP-Cron limitations surface in production |
| D3 | Delta/event endpoint (replace full snapshot with incremental) | When snapshot payload exceeds 500KB |
| D4 | Drift reconciliation & conflict review queue | When multi-device editing is supported |
| D5 | Dashboard & LLM alt-text generation (Epic D) | Post-v0.1.0 roadmap planning |
| D6 | Observability: structured logging, metrics, audit trail | When production deployment begins |

---

## Success Criteria for 4.13.2

- [ ] Phase 3 merged to `main` with all success criteria signed off
- [ ] `thumbnail_url` fully removed from backend, plugin, and frontend
- [ ] Plugin reads clusters exclusively from local sovereign tables (no proxy fallback)
- [ ] Architecture diagrams and contracts updated
- [ ] All automated test suites green across all three layers
- [ ] Epic v0.1.0 marked COMPLETED with release tag
