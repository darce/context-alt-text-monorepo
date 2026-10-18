# MVP State Assessment (4.13.2)

> **Date**: 2026-02-18
> **Branch**: `refactor/4.13.1-wp-sovereign-phase-3` (1 commit ahead of `main`, 35 modified + 17 untracked files uncommitted)
> **Assessment scope**: v0.1.0 Sovereign Cluster epic progress vs roadmap-v3 vision and roadmap-v4 placeholder

---

## Epic Progress: v0.1.0 Sovereign Cluster Architecture

Source: `docs/epics/v0.1.0/wp-sovereign-cluster-epic.md`

| Phase | Title | Epic Status | Git Evidence | Verdict |
|---|---|---|---|---|
| **1** | Scaffolding & Local Projection | COMPLETED | Commits `db9e072`..`b5ed911` on `main`; packaging audit + phase1 audit both resolved | **Done** |
| **2** | Read-Path Flip (Offline First) | COMPLETED | Commits `29e9c5e`..`ec9f5ca` on `main`; controllers read local-first, sync status in UI | **Done** |
| **3** | Local-First Writes & Pull Sync | NOT STARTED (per epic) | Branch `refactor/4.13.1-wp-sovereign-phase-3` has 1 committed + 35 modified files; task plan + audit exist; all checklist items checked except manual smokes and success criteria sign-off | **~90% code-complete, uncommitted** |
| **4** | Hard Dependency Removal | NOT STARTED | No code; task plan references thumbnail deprecation plan | **Not started** |

### Phase 3 Detail (uncommitted work)

The uncommitted diff (+1182/−1101 lines across 35 files) contains:

**Plugin (PHP) — completed in working tree:**
- `ClusterMutationsController` dual-write: `update_label`, `dismiss`, `undismiss` persist locally before proxying
- `ClustersRepository` mutation methods (`update_label`, `dismiss`, `undismiss`) with `is_user_confirmed = 1`
- `SyncPullJob` + `SyncPullJobInterface` (on-demand, fail-fast — cron removed)
- Stale-check gate in `ClustersController` read path triggers `SyncPullJob::perform()` 
- Integration tests: `ClusterMutationsControllerDualWriteTest`, `ClustersRepositoryMutationTest`, `SyncPullJobTest`, `SovereignProjectionIntegrationTest`
- Null repository stubs extracted to `tests/stubs/`
- 141 tests, 452 assertions, 0 failures; PHPStan 0 errors

**Backend (Python) — completed in working tree:**
- `GET /tenants/{tenant_uuid}/clusters/snapshot` endpoint implemented
- `ClusterSnapshotResponse` + `ClusterSnapshotMemberResponse` Pydantic models
- Snapshot query service in `cluster_repository.py`
- 476 pytest tests passing

**Remaining Phase 3 items:**
- [ ] Manual smoke: label cluster with backend stopped, restart, confirm sync + label persistence
- [ ] Manual smoke: full cycle — proxy load → analysis → stop backend → clusters render locally
- [ ] Commit and merge uncommitted work to `main`
- [ ] Sign off success criteria in task plan

### Phase 4 Detail (not started)

Full scope defined in `thumbnail-deprecation-task-plan.md` + epic Phase 4:
- Backend: remove `thumbnail_url` from domain/schemas/repos/routers (~28 code sites), drop DB column
- Plugin: remove proxy-response fallback, dead `is_http_url()` branch, duplicate `thumbnail_url` keys
- Frontend: remove `thumbnail_url` from TS types (~10 interfaces), dead `IdentityThumbnail` fast-path, suggestion thumbnail fields
- Replace proxy reads with local service facade (beyond thumbnail cleanup)

---

## Roadmap v3 (Core Vision) — Epic Coverage

Source: `docs/roadmaps/roadmap-v3.hybrid.md`

| Epic | Title | Status | Notes |
|---|---|---|---|
| **A** | Foundations & Safety | Partial | Plugin bootstrap, lifecycle, API client done. Feature gates not implemented (greenfield policy — not needed). |
| **B** | Data Model | **Done** | Plugin-owned tables via `dbDelta`, sovereign local projection — completed in v0.1.0 Phase 1. |
| **C** | Recognition Pipeline (WP ↔ FastAPI) | Partial | Backend detection/clustering/suggestions pipeline exists. Snapshot sync implemented. Round-trip flow functional but proxy-dependent for writes. |
| **D** | Dashboard & Alt Text Generation | **Not started** | No React admin dashboard. No LLM alt-text generation. No draft review/approval workflow. |
| **E** | Propagation & Sync | **In progress** | Snapshot pull sync done. Dual-write done (uncommitted). Outbox pattern + Action Scheduler deferred to v0.2+. |
| **F** | Observability & Security | Partial | API key auth with tenant scoping done. Structured logging partial. Metrics/audit logs not implemented. |
| **G** | Backend Architecture (PG + pgvector) | **Done** | PostgreSQL 17, pgvector, Alembic, RLS multitenancy, materialized views, centroid clustering all operational. |

### Coverage summary
- **3 of 7 epics substantially done** (B, E, G)
- **2 partially done** (A, C)
- **1 in progress** (E — sync/propagation)
- **1 not started** (D — dashboard & alt text)
- **1 partially done** (F — security yes, observability no)

---

## Roadmap v4 — Status

Source: `docs/roadmaps/roadmap-v4.md`

**Placeholder only.** Awaits v0.1.0 completion and retrospective. Open questions:
- Which v3 epics (B–G) carry forward vs get redesigned?
- What new capabilities or integrations?
- How does on-device vs backend split evolve?

---

## Outstanding Items from 4.13.1 Task Folder

### Carrying forward (incomplete)

| Item | Source | Status | Blocking |
|---|---|---|---|
| Manual smoke tests (2) | `wp-sovereign-phase3-dual-write-task-plan.md` | Not done | Phase 3 sign-off |
| Commit + merge Phase 3 branch | Git state (35 modified, 17 untracked) | Uncommitted | Phase 3 completion |
| Success criteria sign-off | `wp-sovereign-phase3-dual-write-task-plan.md` | Not done (all code items checked) | Epic Phase 3 closure |
| Phase 3 audit M-2 remnants | `wp-sovereign-phase3-branch-audit-findings.md` | Code done (stubs extracted) — needs audit re-verification | Clean merge |
| Thumbnail deprecation (full plan) | `thumbnail-deprecation-task-plan.md` | Not started (0/~50 checklist items) | Epic Phase 4 |
| Backend snapshot endpoint live integration | `wp-sovereign-phase3-dual-write-task-plan.md` | Code done — not tested end-to-end with live WP plugin | Full-stack validation |
| XMP face metrics | `wp-image-xmp-face-metrics-task-plan.md` | Partial (staged fixes in git history) | Not blocking epic |

### Completed (for archival reference)

| Item | Source |
|---|---|
| Portable packaging plan | `wp-plugin-portable-packaging-plan.md` — audit passed |
| Sovereign Phase 1 local projection | `wp-sovereign-phase1-local-projection-task-plan.md` — audit passed |
| Phase 1 branch audit | `sovereign-phase1-branch-audit-findings.md` — all findings resolved |
| Packaging audit | `packaging-plan-implementation-audit.md` — all findings resolved |
| Phase 2 read-path flip | `wp-sovereign-phase2-read-path-flip-task-plan.md` — merged to main |
| Phase 2 branch audit | `wp-sovereign-phase2-branch-audit-findings.md` |
| Phase 2b branch audit | `wp-sovereign-phase2b-branch-audit-findings.md` |
| Phase 3 branch audit | `wp-sovereign-phase3-branch-audit-findings.md` — H-1 resolved, M-1 resolved, M-2 resolved, L-1 resolved, L-2 resolved |
| Phase 3 dual-write (code) | `wp-sovereign-phase3-dual-write-task-plan.md` — all automated checklist items complete |

---

## Gap Analysis: What Remains for v0.1.0 Epic Completion

### Must-do (blocks epic exit criteria)

1. **Merge Phase 3** — commit uncommitted work, manual smokes, merge to `main`
2. **Phase 4: Thumbnail deprecation** — ~50 items across backend/plugin/frontend per task plan
3. **Phase 4: Proxy→facade replacement** — replace runtime proxy dependency with local service facade for cluster reads
4. **Phase 4: Architecture diagram update** — contracts and diagrams to reflect sovereign model

### Should-do (stated in epic but not strictly blocking)

5. **Backend parallel: snapshot endpoint polish** — error handling, pagination for large tenants
6. **Frontend: sync status refinement** — "Sync Now" manual trigger button (listed as optional in Phase 3 plan)

### Won't-do in v0.1.0 (explicitly deferred)

- Outbox table (`wp_acx_cluster_operations`)
- Action Scheduler migration
- Delta/event endpoint
- Drift reconciliation and conflict review queue
