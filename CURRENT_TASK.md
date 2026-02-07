# Current Task: 4.12.0 Suggestion Panel Current-Batch Top Clusters

**Started**: 2026-02-05
**Task Doc**: `docs/tasks/4.0/4.12.0/suggestion-panel-current-batch-top-clusters-plan.md`
**Status**: IN_PROGRESS (stabilization + final validation)

## Objective

Implement unified curation flow with confirmed-only suggestions, run-scoped naming queue, and separated merge queue.

## Context

The Workbench suggestion panel needs two high-value queues: suggestions matching identities to confirmed clusters, and clusters to name from the latest batch. Currently the naming queue never populates (wrong filter logic) and suggestions aren't constrained to confirmed clusters.
Current blocker: some top-cluster cards still render `Name this person` when they should render `Is this <Known Name>?` (example: Maria Correonero), indicating missing/late `suggested_label` enrichment in top-unlabeled responses.
Current blocker: UI/DB state divergence for cluster suggestions. Identity-level suggestions can transition to `accepted` during refresh while source clusters remain unlabeled and continue to render in top-unlabeled as `Name this person` (example source clusters: `922d985a-4010-4d75-bc6a-66bf0be8940b`, `e86537dd-66a6-4bdf-8486-752430512746`; media set: `6716, 6706, 6698, 6704, 6700, 6711`).
Mitigation landed in current batch: refresh no longer auto-resolves suggestions to `accepted/rejected`, stale accepted-but-unmoved suggestions are re-listed as pending review, and low-confidence suggestions are surfaced with explicit UI treatment.

## Progress

### Completed

- [x] Plan clarification: merge queue as collapsible section, `thumbnail_url` on domain dataclass, `tenant_id` from `md5(get_site_url())`
- [x] Phase 0: Scaffolding complete across backend/frontend API shape updates
- [x] Phase 1: Backend implementation complete for confirmed-only suggestion eligibility + run-scoped top-unlabeled query
- [x] Phase 2: Frontend implementation complete for unified review panel, merge queue integration, and naming queue rendering
- [x] Regression fix: `FaceThumbnail` no longer sticks in loading state when image is already browser-cached
- [x] Regression fix: removed per-row `EventSource` subscription from `IdentityClusterList` to stop workbench hangs / request starvation
- [x] Regression fix: `ClusterReviewPanel` CSS no longer overrides `FaceThumbnail` internals (thumbnails render correctly)
- [x] Top cluster card grid now uses representative observation crop (`media_url + bbox`) with `thumb_url` fallback
- [x] Suggestion refresh now updates scores without auto-transitioning rows to `accepted/rejected` (keeps user review in loop)
- [x] `list_pending_with_details()` now re-surfaces stale `accepted` rows (where identity was not moved) as pending review items
- [x] Low-confidence suggestion surfacing added (`low_confidence_suggestion_floor`) with visual badge/background treatment in `acx-suggestion-card`
- [x] Suggestion panel fetch size increased from 10 to 25 for higher-leverage curation sessions
- [x] Accepting a single suggestion card no longer triggers cluster-wide refresh side effects (no auto-accept fanout)
- [x] Suggestion surfacing path hardened for idempotency: dedupe candidate clusters and identities within a run

### In Progress

- [ ] Dynamic top-cluster CTA enrichment: convert `Name this person` to `Is this <label>?` when matching previously/recently labeled clusters is available ← **ACTIVE**
- [ ] Reconcile suggestion resolution semantics with cluster state: backend mitigation shipped, pending manual browser validation against Maria/Tory examples ← **ACTIVE**

### Completed (Session 5)

- [x] Hybrid run-scoped + tenant-wide top-unlabeled query (surfaces large older clusters)
- [x] Dismiss cluster from naming queue (`dismissed_at` column + Skip button + POST/DELETE endpoints)

### Remaining

- [ ] Manual browser verification and end-to-end smoke pass for naming/review flows
- [ ] Full backend/frontend suite pass (beyond targeted tests)
- [ ] Final contract/doc consistency sweep (`docs/agentic/contracts/recognition-clustering.md`)
- [ ] Ensure top-unlabeled cards refresh immediately after label/merge (no stale 60s window)
- [ ] Add robust label-inference fallback for clusters missing `representative_identity_id`
- [ ] Validate accepted-suggestion UX end-to-end in browser:
      stale `accepted` rows should now appear in Review Suggestions and no longer disappear from user perspective
- [ ] Final success-criteria check and task closeout

## Key Files

| File                                                                                                  | Purpose                                                                    |
| ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `apps/prototype-description-service/recognition/application/suggestions/eligibility.py`               | Confirmed-only eligibility enforcement                                     |
| `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py`    | Run-scoped `get_top_unlabeled()` + representative crop fields              |
| `apps/prototype-description-service/recognition/application/suggestions/label_inference.py`           | Dynamic cluster->label suggestion inference (`suggested_label`)            |
| `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py`           | Suggestion refresh behavior (no auto-resolution, low-confidence surfacing) |
| `apps/prototype-description-service/recognition/infrastructure/repositories/suggestion_repository.py` | Pending suggestion query + stale accepted relisting logic                  |
| `apps/prototype-description-service/recognition/application/settings/clustering.py`                   | Low-confidence suggestion floor setting                                    |
| `apps/prototype-description-service/recognition/domain/representative.py`                             | Representative payload fields (`thumbnail_url`, `media_url`, `bbox_*`)     |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py`          | `/clusters/top-unlabeled` response mapping                                 |
| `apps/prototype-description-service/recognition/interface_adapters/http/schemas/responses.py`         | HTTP response schema for representative crop fields                        |
| `apps/prototype-description-service/recognition/tests/api/test_top_unlabeled.py`                      | API regression coverage for representative crop serialization              |
| `apps/prototype-wp-alt-context/src/admin/class-admin.php`                                             | `tenant_id` + events endpoint in `AltContextAdmin` config                  |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/SuggestionReviewPanel.tsx`  | Unified review panel + merge queue                                         |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/TopClustersSection.tsx`     | Top cluster thumbnail rendering (face crop + fallback)                     |
| `apps/prototype-wp-alt-context/js/admin/styles/components/_workbench.scss`                            | Low-confidence suggestion visual treatment                                 |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterLabelingPanel.tsx`   | Label/merge flow and query invalidation after curation                     |
| `apps/prototype-wp-alt-context/js/components/ui/FaceThumbnail.tsx`                                    | Cached-image load handling fix                                             |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterReviewPanel.tsx`     | Review panel thumbnail rendering path                                      |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/IdentityClusterList.tsx`    | Removed per-row SSE subscription                                           |
| `docs/tasks/4.0/4.12.0/suggestion-panel-current-batch-top-clusters-plan.md`                           | Plan + consolidated checklist                                              |

## Verification Commands

```bash
# Backend
cd apps/prototype-description-service
PYENV_VERSION=description-service mypy .
PYENV_VERSION=description-service ruff check .
PYENV_VERSION=description-service pytest recognition/tests/unit/test_eligibility.py -v
PYENV_VERSION=description-service pytest recognition/tests/api/test_top_unlabeled.py -v
PYENV_VERSION=description-service pytest recognition/tests/service/test_suggestion_refresh.py -v
PYENV_VERSION=description-service pytest recognition/tests/integration/test_proactive_suggestions.py -v
PYENV_VERSION=description-service pytest recognition/tests/api/test_api_suggestions.py -v

# Frontend
cd apps/prototype-wp-alt-context
npm run test -- js/admin/pages/workbench/identity-clusters/__tests__/SuggestionReviewPanel.test.tsx
npm run test -- js/admin/pages/workbench/identity-clusters/__tests__/ClusterReviewPanel.test.tsx
npm run test -- js/components/ui/__tests__/FaceThumbnail.test.tsx
npm run test -- js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx
npm run typecheck
```

## Next Agent Instructions

1. Manually verify on `http://localhost:10010/wp-admin/admin.php?page=alt-context-workbench#/workbench` that Maria/Tory duplicate cases now appear in Review Suggestions (including low-confidence styling) instead of disappearing.
2. Validate stale-accepted reconciliation against media `6716, 6711, 6706, 6704, 6702, 6700, 6698`:
   rows previously `accepted` without membership move should be reviewable in pending suggestion panel.
3. Confirm whether top-unlabeled exclusion by accepted-member-suggestion still creates UX gaps; if needed, adjust `get_top_unlabeled()` filter strategy.
4. Keep dynamic CTA enrichment work active for unlabeled top-cluster cards where `suggested_label` inference is still missing.
5. Run full validation sweeps (`mypy`, `ruff`, broader `pytest`, frontend `typecheck` and targeted vitest suites), then reconcile remaining checklist items.

---

## Session Log

### 2026-02-05 - Session 1

- Ingested `instructions.md`, `BOOTSTRAP.md`, and task plan.
- Verified `source="cluster_unclustered_identities"` is set in orchestrator.
- Confirmed `RecognitionRun` and `RecognitionEvent` schema matches plan expectations.
- Asked clarifying questions; received answers in updated plan.
- Created `task.md` and `implementation_plan.md` artifacts.

**Backend Changes:**

- Added `thumbnail_url` field to `ClusterRepresentative` domain dataclass.
- Implemented confirmed-only eligibility in `is_eligible_cluster()` (6 unit tests passing).
- Updated `list_pending_with_details` to filter confirmed clusters only.
- Rewrote `get_top_unlabeled()` with run-scoped query and tenant-wide fallback.
- Added `thumbnail_url` mapping from `MediaIdentity.thumbnail_url` in representative conversion.
- Updated integration test `test_unlabeled_clusters_are_filtered_from_suggestions`.
- All backend tests passing (437 passed, 4 skipped).

**Frontend Changes:**

- Added `tenant_id` to `AltContextAdmin` PHP config from `md5(get_site_url())`.
- Deleted `CurateTopClustersPrompt.tsx` (naming queue now in SuggestionReviewPanel).
- Removed `CurateTopClustersPrompt` import and usage from `IdentityClusterList.tsx`.

**Remaining:**

- SuggestionReviewPanel updates (collapsible merge queue, always show both queues).
- TopClustersSection updates (use tenant_id from config).
- API contract documentation update.

### 2026-02-06 - Session 2

- Fixed lint issue in `cluster.ts`: converted `Array<T>` to `T[]` for `TopUnlabeledCluster.representatives`.
- Fixed shared thumbnail loading regression in `FaceThumbnail`:
  added cached/complete-image detection to avoid permanent `opacity: 0` loading state.
- Added regression test for cached-image load path in `FaceThumbnail.test.tsx`.

### 2026-02-06 - Session 3

- Resolved workbench hang root cause by removing per-row SSE hookup from `IdentityClusterList`.
  This prevented excessive `EventSource` connections that could starve API calls and leave panel requests pending.
- Added regression assertion in `IdentityClusterList.test.tsx` to ensure no `EventSource` is created there.
- Fixed `ClusterReviewPanel` thumbnail rendering:
  narrowed CSS selector so panel-specific image sizing does not override `FaceThumbnail` internals.

### 2026-02-06 - Session 4

- Implemented representative observation-crop support for top unlabeled cluster cards:
  backend now returns representative `media_url + bbox` (plus `thumb_url` fallback),
  and frontend uses those fields to render actual face crops in `acx-top-cluster-card__grid`.
- Added frontend regression test for crop rendering and backend API test for representative crop field serialization.
- Targeted checks run and passing:
  - `PYENV_VERSION=description-service pytest recognition/tests/api/test_top_unlabeled.py -q` (2 passed)
  - `npm run test -- js/admin/pages/workbench/identity-clusters/__tests__/SuggestionReviewPanel.test.tsx`
  - `npm run test -- js/admin/pages/workbench/identity-clusters/__tests__/ClusterReviewPanel.test.tsx`
  - `npm run test -- js/components/ui/__tests__/FaceThumbnail.test.tsx`
  - `npm run test -- js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx`

### 2026-02-06 - Session 5

- Implemented hybrid run-scoped + tenant-wide `get_top_unlabeled()`:
  queries run-scoped clusters first, then backfills remaining slots with tenant-wide unlabeled clusters,
  so large clusters from older runs surface in the naming queue. Uses `_base_filters()` helper for DRY.
- Added `dismissed_at` column to `identity_clusters` (baseline migration, SQLAlchemy model, domain dataclass).
- `get_top_unlabeled()` filters `.where(ClusterModel.dismissed_at.is_(None))`.
- Added `dismiss_cluster()` / `undismiss_cluster()` to `ClusterRepository` (abstract interface + SQLAlchemy implementation).
- Added `POST /clusters/{id}/dismiss` (204/404) and `DELETE /clusters/{id}/dismiss` (204/404) endpoints.
- Added `dismissCluster()` / `undismissCluster()` to frontend `clusterApi.ts`.
- Added Skip button on `TopClusterCard` wired to `useMutation` → `dismissCluster` with query invalidation.
- Updated all test stubs (`NullClusterRepo` in 3 unit test files, `FakeClusterRepository` in API conftest).
- Backend: 4 new API tests (6 total in `test_top_unlabeled.py`), mypy clean, ruff clean, 27 affected tests pass.
- Frontend: 12 tests passing in `SuggestionReviewPanel.test.tsx`, 110 total tests passing (24 files), pre-existing TS2741 in `clusterAdapter.ts` only.

### 2026-02-06 - Session 6

- Investigated why top-cluster cards still show `Name this person` instead of inferred CTA (`Is this Maria Correonero?`).
- Confirmed dynamic inference path exists in `GET /clusters/top-unlabeled` via `infer_suggested_label(...)`, but inference can return `None` when cluster representative linkage is missing.
- Confirmed frontend invalidation gap: `ClusterLabelingPanel` refreshes `clusters.all` and `suggestions.pending` but does not explicitly refresh `clusters.topUnlabeled`, causing stale CTA state after recent labeling/merge.
- Added this blocker as active work item and updated next-agent instructions to prioritize dynamic CTA correctness.

### 2026-02-06 - Session 7

- Investigated reported mismatch where cards still show `Name this person` despite suggestion acceptance.
- Clarified relation to Session 6:
  Session 6 covers missing/late `suggested_label` enrichment and top-unlabeled refetch timing;
  Session 7 covers semantic divergence where suggestion resolution does not update source cluster state.
- Corrected reference set for this investigation:
  media IDs are `6716, 6706, 6698, 6704, 6700, 6711` (not `6671`).
- Confirmed DB evidence for mismatch:
  identities in source clusters `922d985a-4010-4d75-bc6a-66bf0be8940b` and `e86537dd-66a6-4bdf-8486-752430512746`
  received `identity_suggestions` rows targeting `Maria Correonero` and these rows were later set to `resolution='accepted'`.
- Confirmed source cluster state remains unchanged:
  both source clusters still have `label=''`, `user_confirmed=false`, and `identity_count=3`,
  so repository filters still return them in `get_top_unlabeled()` and UI renders `Name this person`.
- Tables directly involved in this discrepancy:
  `identity_suggestions` (suggestion lifecycle),
  `identity_clusters` (top-unlabeled source-of-truth),
  `identity_members` (source cluster membership),
  `identity_cluster_representatives` and `media_identities` (similarity/representative basis),
  `recognition_events` (auditing suggestion resolution path).
- Logical path that produces the UI error:
  1. `PATCH /clusters/{id}` label action triggers background `surface_for_newly_labeled_cluster(...)`, which creates `pending` rows in `identity_suggestions`.
  2. `refresh_for_cluster(...)` re-evaluates these rows and can auto-transition `pending -> accepted` based on gate/similarity.
  3. This transition updates suggestion resolution only (`identity_suggestions`), not source cluster label or membership.
  4. Top-unlabeled query is cluster-state-driven (`identity_clusters.user_confirmed=false` and unlabeled), so unchanged clusters remain in naming queue.
  5. Result: review suggestion can be treated as accepted in DB while the same source cluster still appears as `Name this person` in top cards.
- Session output/change made:
  no schema or runtime behavior change was applied in this session; this session produced root-cause validation,
  corrected media references, and converted the mismatch into an explicit active reconciliation task.

**Possible solutions (ranked by recommendation):**

**Option A — Query-level exclusion: filter top-unlabeled by accepted-suggestion state**
Modify `get_top_unlabeled()` to add a `NOT EXISTS (SELECT 1 FROM identity_suggestions WHERE cluster_id IN source-cluster-members AND status='accepted')` filter, or a simpler LEFT JOIN anti-pattern. Clusters whose member identities already have accepted suggestions targeting another cluster are excluded from the naming queue.

- **Pros**: Pure read-side fix, no write-side coupling. Source cluster remains unmodified (preserving audit trail). Clean separation of concerns.
- **Cons**: Adds a JOIN/subquery to the hot top-unlabeled path. "Accepted" suggestions are an indirect signal — the user may not have explicitly confirmed the merge. Could hide clusters the user still wants to name differently.
- **Complexity**: Low (1 query change, 1–2 tests).
- **Files**: `cluster_repository.py` (`get_top_unlabeled`), `test_top_unlabeled.py`.

**Option B — Side-effect on auto-accept: auto-merge source into target cluster**
When `refresh_for_cluster()` transitions a suggestion to `ACCEPTED` (lines 357-358 of `refresh_service.py`), also trigger `merge_cluster(source_cluster_id → target_cluster_id)`. This moves member identities out of the source cluster and into the already-labeled target, removing the source from top-unlabeled organically.

- **Pros**: Fully consistent — cluster state and suggestion state converge immediately. Source cluster disappears from naming queue because its members now belong to the labeled target.
- **Cons**: Auto-merge is destructive and hard to undo. High-confidence gate threshold needed to avoid merging wrong clusters. Couples suggestion lifecycle to cluster write mutations. `refresh_for_cluster` currently has no access to `ClusterService.merge_cluster()` — would require injecting orchestration dependency.
- **Complexity**: High (cross-layer dependency injection, merge rollback considerations, new tests for cascade).
- **Files**: `refresh_service.py`, `cluster_service.py`, `cluster_merge.py`, new integration tests.

**Option C — Raise gate threshold: suppress auto-acceptance entirely**
Increase `suggestion_ceiling` (or adjust `AssignmentGate`) so that `refresh_for_cluster()` never auto-transitions to `ACCEPTED`. All suggestions stay `PENDING` and appear in the review queue for manual user confirmation. The user's explicit accept action then triggers the merge/label via the existing `PATCH /clusters/{id}` → `resolve_for_identity()` path.

- **Pros**: Clean UX — user always decides. No stale/divergent state because suggestions can't outrun cluster state. Minimal code change (config tweak or gate parameter).
- **Cons**: Loses the auto-curation value for high-confidence matches. More manual work for the user on obvious duplicates.
- **Complexity**: Very low (config/settings change, 0–1 tests).
- **Files**: `recognition/application/settings/clustering.py` or gate configuration.

**Option D — Hybrid: auto-accept marks source cluster as "suggestion-resolved"**
Add a lightweight cluster state marker (e.g., `suggestion_resolved_at` timestamp on `identity_clusters`) that `refresh_for_cluster` sets when it auto-accepts a suggestion for ALL members of a source cluster. `get_top_unlabeled()` then excludes clusters where `suggestion_resolved_at IS NOT NULL`. Unlike Option B, no merge/move happens — the cluster just becomes invisible in the naming queue. An "undo" button could clear this marker.

- **Pros**: Lightweight write (single column update, no member moves). Reversible. Source cluster data preserved for audit. Reuses the `dismissed_at` pattern from Session 5.
- **Cons**: Requires tracking "all members resolved" condition, which is more complex than a single-row update. Source cluster still physically exists with unlabeled state — could confuse roster views. Partially hides state rather than resolving it.
- **Complexity**: Medium (new column, condition check in refresh, query filter, tests).
- **Files**: migration, `identity.py` model, `cluster_repository.py`, `refresh_service.py`, tests.

**Option E — Frontend-only: enrich top-unlabeled response with accepted-suggestion info**
Keep the backend as-is. In the `GET /clusters/top-unlabeled` response enrichment (where `infer_suggested_label` already runs), also check whether the cluster's members have accepted suggestions. If yes, change the card CTA from `Name this person` to `Is this <target_label>?` with Yes (triggers merge) / No (dismisses suggestion). This is the Session 6 fix (dynamic CTA) extended to cover the Session 7 case.

- **Pros**: No cluster state mutation needed. Re-uses existing enrichment path. User sees correct CTA and can confirm or reject. Complements Session 6 work.
- **Cons**: Source cluster remains in naming queue even after user confirms (unless frontend also triggers merge on "Yes"). Requires reliable label inference, which Session 6 identified as sometimes failing. Doesn't solve the root semantic divergence.
- **Complexity**: Medium (enrichment logic + frontend CTA branching, tests).
- **Files**: `label_inference.py`, `clusters.py` router, `TopClustersSection.tsx`, tests.

**Recommended approach (updated after Session 8 implementation)**: Option C-style behavior + stale-accepted relisting, with Option E still in progress.
Session 8 shipped the core Option C direction (no auto-accept in refresh path) and added stale-accepted relisting so suggestions remain user-reviewable.
Option E remains active for top-cluster CTA enrichment where `suggested_label` inference is still incomplete.

### 2026-02-06 - Session 8

- Implemented low-confidence suggestion surfacing and stale-accepted reconciliation.
- Backend behavior changes:
  - Added `low_confidence_suggestion_floor` to clustering settings.
  - `SuggestionRefreshService.refresh_for_cluster()` no longer auto-transitions suggestions to `accepted/rejected`; it now refreshes scores while keeping review state pending.
  - Gate rejections from confidence checks can still surface as reviewable suggestions when above low-confidence floor; explicit block/constraint rejections remain hard rejects.
  - `SqlAlchemySuggestionRepository.list_pending_with_details()` now includes stale `accepted` rows where identity is not actually a member of target cluster and normalizes them to pending response status.
  - Pending suggestion ordering updated to `confidence_score DESC`.
- Frontend behavior changes:
  - `SuggestionReviewPanel` now requests 25 suggestions per fetch (up from 10).
  - Added low-confidence visual treatment (`acx-suggestion-card--low-confidence` + `Low confidence` flag).
- DB validation (via `./scripts/db_shell.sh --admin`) confirmed Maria media IDs had stale accepted rows and are now eligible for pending review query path.
- Tests run and passing:
  - `pytest recognition/tests/service/test_suggestion_refresh.py -q` (8 passed)
  - `pytest recognition/tests/integration/test_proactive_suggestions.py -q` (4 passed)
  - `pytest recognition/tests/api/test_api_suggestions.py -q` (3 passed, 1 skipped)
  - `vitest SuggestionReviewPanel` (14 passed)
  - `ruff` and targeted `mypy` on changed backend files passed.
- Known unrelated frontend typecheck issue remains:
  - `apps/prototype-wp-alt-context/js/admin/api/recognition/adapters/clusterAdapter.ts` missing required `clusteringPending` field (pre-existing).

### 2026-02-07 - Session 9

- Investigated report that clicking **Yes** on one low-confidence suggestion appeared to accept other cards.
- Backend fix shipped:
  - `POST /recognition/suggestions/{id}/accept` no longer triggers `refresh_for_cluster(...)` as a side effect.
  - Result: manual accept now resolves only the targeted suggestion/card.
- Added API regression assertion in `test_api_suggestions.py` to ensure no refresh calls are made during single-card accept.
- Investigated duplicate-observation concern (`Maria Correonero`) and validated current state:
  - Log analysis across `recognition.log*`: no repeated `SURFACED identity_id + cluster_id` pairs in current dataset.
  - DB check (`identity_suggestions`): row count equals distinct `(identity_id, suggested_cluster_id)` count; no duplicate suggestion rows.
- Hardening change for idempotency/deduplication in surfacing:
  - `surface_for_newly_labeled_cluster(...)` now dedupes `candidate_cluster_ids`.
  - Tracks `seen_identity_ids` and skips duplicate identity handling within the same surfacing run.
  - Summary logs now include `unique_members` and `duplicate_skipped`.
- Added unit test `test_batch_surfacing_dedupes_same_identity_across_clusters`.
- Targeted verification passed:
  - `ruff check recognition/application/suggestions/refresh_service.py recognition/tests/unit/test_batch_surfacing.py`
  - `pytest recognition/tests/unit/test_batch_surfacing.py -q` (5 passed)
  - `pytest recognition/tests/api/test_api_suggestions.py -q` (3 passed, 1 skipped)
