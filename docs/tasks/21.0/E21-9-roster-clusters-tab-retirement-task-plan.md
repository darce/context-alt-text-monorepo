# E21-9. Roster Clusters-tab retirement + person-first roster

**Epic**: [E21 Public-MVP UX polish](../../epics/v0.4.1/public-mvp-ux-polish-epic.md) · Phase 4 (Person-first roster & link contract)
**Date**: 2026-07-22 · **Author**: Claude (Fable 5) · **Revised**: 2026-07-22 per adversarial planning review (findings E219-PR-01..15 in handoff)
**Target Branch**: `feature/e21-9` · **Worktree**: `context-alt-text-monorepo-e21-9`
**Review Coverage Target**: 2
**Depends on**: E21-5 (unified review queue + person-commit — landed on `main`), E15-17 s3–4 (face scrubber + cluster evidence, under the [E15-17 plan](../15.0/E15-17-roster-person-review-scrub-workspace-task-plan.md))
**Blocks**: E21-10 (cross-surface link contract)
**UXP amendments folded at authoring time** ([uxp-ux-pass-decomposition.md](../../scopes/uxp-ux-pass-decomposition.md) §Amendments, E21-9 row; epic Re-baseline table E21-9 row): label-curation ⇒ person-projection write-through; server-side same-label grouping so duplicate person rows cannot render; Entries never empty after naming (UXA-09); every drag ships a click/keyboard alternative ([A11Y-15]); hover-only affordances become always-visible ([A11Y-14]); progressive bulk merge gets live-region progress + a designed mid-sequence-failure state ([A11Y-21]/[A11Y-24]).

## Objective

Retire the Roster page's Clusters tab and make the person-first surface the only roster. The workbench review queue (E21-5) is the canonical cluster-triage surface; Roster curates people. Close the two data-honesty gaps that make person-first impossible today: (1) naming a cluster through the workbench label path produces a label but no person, so the Entries surface can stay empty after naming; (2) person-name uniqueness is an accident of DB collation rather than an explicit product policy, and where the lookup and the unique index disagree the commit path errors instead of rebinding. Ship the amended a11y obligations on the surviving cluster-manipulation seams that this task owns (keyboard member-fix, always-visible affordances, announced progressive bulk merge).

## Problem Statement

`RosterPage.tsx` renders two tabs (`RosterPage.tsx:255-288`) from the `ROSTER_TABS` enum (`js/admin/pages/roster/rosterRoute.ts:4-7`). The Clusters tab (`RosterClustersTab.tsx`) is a full parallel review surface — grid, multi-select, bulk merge/dismiss, drag-drop face reassignment — duplicating the workbench review queue E21-5 shipped. Cross-surface links hardcode the duplicate: `adminUrls.ts:4` falls back to `…&tab=clusters`, consumed by `Panels.tsx:218` ("Open clusters in roster") and `ConfirmTabContent.tsx:31`.

Data honesty — grounded against the real schema (`src/support/class-life-cycle-manager.php:503-516`, greenfield wipe-on-deploy CREATE TABLE): the workbench label path (`ClusterLabelingPanel.tsx` → `update_cluster_label`, `class-cluster-mutations-controller.php:236` → `ClusterLabelService`) writes only the cluster label — `src/api/services/class-cluster-label-service.php` (121 lines) never touches `acx_persons` — so "Name this person" via labeling leaves the person-first surface empty (UXA-09). On the person path (`class-api.php:398` `commit_roster_cluster`), `acx_persons` **already** carries `UNIQUE KEY idx_name (name)` under `$wpdb->get_charset_collate()` — a `utf8mb4_*_ci` collation (case-insensitive, accent-insensitive, PAD SPACE folds trailing spaces). So "Ada" and "ada " *cannot* coexist as rows today, and the lookup `WHERE name = %s` (`class-api.php:421`) is collation-folded, not byte-exact. The actual defects are:

1. **Uniqueness policy is a collation accident, not a product decision.** The DB today treats "José" = "Jose" (accent-insensitive under `*_ci`), and PAD behavior varies by MySQL version (`utf8mb4_0900_*` on MySQL 8 is NO PAD — trailing-space semantics flip). No explicit normalization exists in code.
2. **Error-instead-of-rebind.** Where the lookup misses but the unique index still considers the name equal (or vice versa under collation variance), `wpdb->insert` fails on `idx_name` and the request 500s ("Could not create person") instead of rebinding the cluster to the existing person.
3. The read path (`RosterEntryProjectionRepository::list_entries`, `src/sovereign/repositories/class-roster-entry-projection-repository.php:23-86`) is `SELECT * FROM acx_persons ORDER BY name ASC` with no grouping. Given `idx_name`, same-name duplicate rows cannot exist today; render-time grouping's protective scope is exactly the uniqueness gap that survives the Slice-1 collation decision (see Open Questions Q3/Q4) — its tests must target that gap, not states the DB forbids ([TEST-15]).

A11y: face reassignment is drag-only (`ClusterDrawerPanel.tsx:212` `draggable`; `useClusterDragDrop.ts` has no keyboard path) — an [A11Y-15] violation; bulk merge progress lives in `useClusterActions.ts:30` (`bulkMergeProgress`) with no live region and no designed mid-sequence-failure state.

## Constraints

- **Sequencing (conditional)**: **No concurrent edits to `js/admin/pages/workbench/identity-clusters/**` while an E15-37-FE lane is active.** If E15-37-FE merges before Slice 3 lands, rebase on it first. E15-37 closed with its frontend slices deferred and no active lane exists, so this constraint must **not** block Slices 3–6 indefinitely — it binds only while such a lane is live. The known findings on `resolveMergeSurvivor.ts` / `useLiveReviewTarget.ts` are GROK-01, S5-02, and S5-03 on the archived `MAINT-e21-5-postmerge-review-20260718` ref — they belong to that lane, do not fix them here.
- **Epic waiver (gate before Slice 1)**: the epic's Hard Constraints state "No backend contract changes" (public-mvp-ux-polish-epic.md:19). Slices 1–2 change local plugin surfaces: `acx_persons` schema, grouped read cardinality on `GET /acx/v1/roster/entries`, and PATCH-label side effects — zero recognition-service contract changes. Before Slice-1 funding, amend the epic Hard Constraints / E21-9 re-baseline row to authorize this additive local-projection scope; the operator confirms at intake. Do not start Slice 1 without the recorded amendment.
- **Two hats ([REF-05])**: server contract changes (Slices 1–2, PHP) never mix with the TS surface restructuring (Slices 3–6). Slice 5a is a structural move with zero behavior change beyond mounting; Slice 5b (Needs-assignment rail) is a behavior slice and is labeled as such; behavior amendments land in Slices 3–4 first.
- **rg-002 (atomic writes)**: keyboard member-fix drives the existing single `reassignClusterIdentity` call; write-through binds label→person in one server transaction — never split into label-then-commit frontend mutations.
- **rg-003 (zero-state reachability)**: the retired tab must not orphan triage — unassigned-cluster work stays reachable from the person-first surface at zero state (disabled-with-reason, never hidden). E21-12's always-visible person list is the baseline; keep `RosterZeroStateReachability.test.tsx` green.
- **rg-005 (schema parity)**: the normalized-name column/index is validated against the real `acx_persons` CREATE TABLE in `src/support/class-life-cycle-manager.php:503` (greenfield: schema change lands directly in that table definition — no migration shim; delete-over-flag).
- **rg-015 (no invented metadata)**: grouped entries' `cluster_count`, `queue_memberships`, projection fields derive from the grouped source rows or documented fallbacks — never fabricated during aggregation.
- **sr-004**: all touched styles consume `--acx-*` tokens; `workbench-tokenization.test.ts` stays green.
- **sr-007**: `ROSTER_TABS` shrinks/retires as an enum edit in `rosterRoute.ts` — no scattered `'clusters'` string comparisons survive; route params and queue ids keep their `as const` unions.
- **Banned vocabulary**: surviving copy passes `banned-vocabulary.test.tsx`; people-first terms per UXP-4's `syncVocabulary.ts` map ("Clusters" as user-facing tab vocabulary disappears with the tab).
- **Findings discipline**: review findings live in workbay-handoff MCP by ID only; no finding status in this plan.

## Current State Analysis (ground truth, verified 2026-07-22 on `feature/e21-9` @ branch point from `main` 4b326c54; re-verified against worktree at planning review)

| Surface | Anchor | Fact |
| --- | --- | --- |
| Tab shell | `js/admin/pages/RosterPage.tsx:255-288` | `Tabs` over `ROSTER_TABS` (entries, clusters); entries tab mounts `PersonWorkspacePanel` + `RosterEntriesSection`; clusters tab mounts `RosterClustersTab`; page already fetches `useRecognitionClusters({ limit: 20 })` at `:41` |
| Route model | `js/admin/pages/roster/rosterRoute.ts:4-11, 96-120` | `ROSTER_TABS` enum; `ROSTER_ROUTE_PARAM_KEYS = ['person','queue','face','cluster']`; `cluster=` param forces clusters tab; `tab=clusters` legacy param |
| Cluster tab | `js/admin/pages/roster/RosterClustersTab.tsx` (151), `ClusterGrid.tsx` (243), `BulkActionBar.tsx` (62), `js/admin/pages/roster/useRosterBulkConfirmation.ts` (page dir, not `hooks/`) | duplicate triage surface: grid, selection, bulk merge/dismiss with confirm dialog |
| Drawer | `js/admin/pages/roster/ClusterDrawerPanel.tsx` (320) | page-level panel; face thumbnails `draggable` (:212); commit/rescan/reassign; opens from `cluster=` param or grid |
| Drag seam | `js/admin/pages/roster/hooks/useClusterDragDrop.ts` | drag payload/drop-target state; no keyboard path anywhere |
| Actions | `js/admin/pages/roster/hooks/useClusterActions.ts` | `reassignMutation` (single atomic call), `commitMutation` → `commitClusterToRosterEntry`, `bulkMergeProgress` state (:30) — progress not announced; toast-only outcomes |
| Person workspace | `js/admin/pages/roster/PersonWorkspacePanel.tsx` (237) | per-person cluster evidence + curriculum queue links (E15-17 s1–2 shell); banned-strings "Source version" (:90), "projected instances" (:137), "Curriculum" (:196) are E21-1's banned-vocabulary scope, not owned here |
| Persons schema | `src/support/class-life-cycle-manager.php:503-516` | greenfield CREATE TABLE (wipe-on-deploy authority per comment at :548); columns `id, person_uuid, name, tags, local_revision, reference_thumb_path, cluster_count, created_at, updated_at`; `UNIQUE KEY idx_name (name)`, `UNIQUE KEY idx_person_uuid`; **no `tenant_id` column** (single-tenant local table); collation from `$wpdb->get_charset_collate()` |
| Label write path | `js/admin/pages/workbench/identity-clusters/ClusterLabelingPanel.tsx` → `src/api/class-cluster-mutations-controller.php:236` → `src/api/services/class-cluster-label-service.php` | label-only; zero `acx_persons` writes; wraps in `run_transactional` (:80); loaded via explicit `require_once` from controllers (`class-cluster-mutations-controller.php:9`); person∪cluster typeahead with blocking duplicate guard (UXP-3) exists client-side only |
| Person write path | `src/api/class-api.php:398-470` `commit_roster_cluster` | transactional via inline `begin_database_transaction` (:895, pre-sr-009); collation-folded name lookup (`WHERE name = %s`, :421); inserts `acx_persons` + enqueues `person_created` curation op; insert colliding with `idx_name` → 500, no rebind |
| Entries read path | `class-api.php:393` → `src/sovereign/repositories/class-roster-entry-projection-repository.php:23-86` `list_entries` | `SELECT * FROM acx_persons ORDER BY name ASC`; per-row projection join; no grouping |
| Transaction trait | `src/support/trait-runs-transactional.php` | `run_transactional` forbids nesting — nested START TRANSACTION would implicitly commit the outer transaction; wrapper returns `acx_db_error` instead |
| Cross-surface links | `js/admin/utils/adminUrls.ts:4,26` `rosterClustersUrl()`; consumers `workbench/Panels.tsx:8,218`, `workbench/ConfirmTabContent.tsx:31` | hardcode `&tab=clusters` |
| Tests | `tests/Unit/RosterEntryProjectionRepositoryTest.php`; `js/admin/pages/roster/__tests__/` (incl. `rosterRoute.test.ts`, `RosterZeroStateReachability.test.tsx`); `tests/e2e/a11y/roster-keyboard-walk.spec.ts`, `roster-axe.spec.ts` | existing harnesses to extend; PHP unit suite stubs `wpdb` — it cannot exercise MySQL collation semantics |

Landed context: E21-5 shipped person-commit + multi-select bulk on the workbench review queue (canonical triage). E21-12 shipped the always-visible person list + Add Person + designed empty state. E15-17 s1–2 shipped the workspace shell; s3–4 (face scrubber, evidence migration) execute under the E15-17 plan and are consumed, not built, here.

## Proposed Solution

**Server first, surface last.** Slices 1–2 make the person projection honest (explicit normalization + rebind + write-through) so the person-first surface has true data. Slices 3–4 discharge the a11y amendments on the seams that survive retirement. Slice 5a retires the tab as a pure structural move; Slice 5b adds the Needs-assignment rail as an explicit behavior slice. Slice 6 sweeps links, copy, and e2e.

1. **Explicit name normalization + rebind-not-error, server-side, both ends** (Slice 1). One normalization helper (trim + Unicode case-fold; no diacritic folding — decided policy, see Open Questions Q3 answer): a `normalized_name` column with an explicit **`utf8mb4_bin` collation** + **unique index** on `acx_persons` (greenfield, direct edit to `class-life-cycle-manager.php:503`; no `tenant_id` exists on this single-tenant table, so the index is plain-unique like today's `idx_name`). The legacy `UNIQUE KEY idx_name (name)` is **retired in the same DDL** — keeping both would enforce two contradictory uniqueness regimes (collation-folded vs normalized-binary). Write end: `commit_roster_cluster`'s person resolution looks up by normalized name inside the existing transaction and **rebinds on match instead of 500ing on duplicate key** ([CON-05] — the check-then-insert race is closed by the transaction + unique index, not by the lookup alone; [DATA-17] — the invariant is enforced in the DB, not just checked in PHP). Read end: `list_entries` groups rows by normalized name before mapping with a pinned **survivor policy**: lowest stable `id` is the primary (its `id` and `name` are the entry's identity for `?person=` deep links and bindings); `cluster_count`/`clusters`/`queue_memberships` are the union of member rows (rg-015). Grouping's scope is the residual uniqueness gap after the collation pin (e.g. rows written before the schema edit in a dirty dev DB); if aggregation ever needs a new response field, stop and regenerate `roster-entry.schema.json` first.
2. **Label-curation ⇒ person-projection write-through** (Slice 2). Extract the person-resolution block of `commit_roster_cluster` into a shared `PersonResolutionService` ([ARCH-02] — one writer owns `acx_persons`; two controllers must not carry parallel insert logic). The service is **transaction-agnostic: the caller owns the transaction** — `ClusterLabelService::update_cluster_label` invokes it inside its existing `run_transactional` closure, and nesting is forbidden by `trait-runs-transactional.php` (nested START TRANSACTION implicitly commits). `commit_roster_cluster` keeps its inline transaction helpers for this slice and invokes the resolver inside that existing boundary (migrating it to `run_transactional` per sr-009 is out of scope — note as tech debt). Loading: explicit `require_once` from the owning controllers, matching the existing service convention (`class-cluster-mutations-controller.php:9`), verified with a runtime `class_exists` check (rg-016). Labeling a cluster resolves-or-creates the person (normalized policy from Slice 1), binds cluster→person, and enqueues the same curation ops, all in one transaction ([API-03] — the replayed operation carries the resolved person, not a relative "create if missing"). Result: Entries is never empty after naming, whichever path named it — observable on the next roster read (see refresh contract in Contract Impact).
3. **Keyboard member-fix + always-visible affordances** (Slice 3). Every draggable face in `ClusterDrawerPanel` gains an always-visible "Move to…" control (button semantics, ≥24×24 CSS px [A11Y-14]) opening a target-cluster picker that drives the same single `reassignMutation` call ([A11Y-15], rg-002). Picker data contract: the existing clusters list query already mounted on the page (`useRecognitionClusters`, `RosterPage.tsx:41`) — no new endpoint; the current cluster is excluded from targets; empty target list renders disabled-with-reason, never hidden. Outcome announced via `role="status"` ([A11Y-21]). Drag remains as an enhancement over the same mutation.
4. **Announced progressive bulk merge** (Slice 4). Hook-level, surface-agnostic: `bulkMergeProgress` feeds an inline `role="status"` live region ("Merging N of M…"); first failure stops the run, surfaces a persistent inline `role="alert"` naming the failed cluster with retry, and the un-processed remainder stays selected ([A11Y-24] designed failure state; mirrors the E21-5 Slice-5 stop-on-failure pattern). Stall bound (rg-007 analog): each per-cluster mutation gets a 30 s timeout via `AbortController`; a timed-out step is treated as that step's failure (stop, alert, remainder selected) — the run can never spin. Landing this before retirement keeps the amendment honored through the transition and the hook clean wherever it mounts.
5. **Tab retirement** (Slice 5a — structural) **+ Needs-assignment rail** (Slice 5b — behavior). 5a: `RosterPage` drops `Tabs`; the person-first surface is the page; `ROSTER_TABS` retires (sr-007 enum edit); `RosterClustersTab.tsx` + `ClusterGrid.tsx` deleted; `BulkActionBar`/`useRosterBulkConfirmation`/`ClusterDrawerPanel` survive remounted; route compat — `?tab=clusters` and bare `cluster=<id>` parse to the single surface, `cluster=` opens the drawer in place (deep links keep working; satisfies the epic's deep-link-compatibility constraint until E21-10 migrates the specs), `tab` param dropped on parse. Zero new UI in 5a. 5b (gated on Open Question 1 operator confirmation): a compact **"Needs assignment"** section mounts the (Slice-4-hardened) selection + bulk merge/dismiss over unlabeled clusters and deep-links each cluster to the workbench review queue for card-at-a-time triage — rg-003 kept, duplicate grid retired. Rail data contract: the existing `useRecognitionClusters` list query (already fetched at `RosterPage.tsx:41`), filtered client-side to clusters with an empty/absent `label` (same predicate family as the existing `queryKeys.clusters.topUnlabeled` precedent); no new endpoint; zero state renders the section header with disabled-with-reason controls.
6. **Link + copy sweep** (Slice 6). Symbol/string-level retarget **only**: `rosterClustersUrl()` → `rosterUrl()` (roster root; the PHP-localized `adminUrls.rosterClusters` config key follows); workbench consumers' copy retargets ("Open roster") in `Panels.tsx`/`ConfirmTabContent.tsx` — **no structural workbench refactors**; roster root is the frozen intermediate and E21-10 is the sole later changer of these helpers. Banned-vocabulary/axe/keyboard-walk/tokenization sweeps over every touched surface.

## Contract and Boundary Impact

- **Epic waiver required first**: see Constraints — the epic Hard Constraints row must be amended (operator, before Slice 1) to authorize the additive local-plugin changes below. All changes are WP-plugin-local; zero recognition-service contract changes.
- **Changed (additive, local)**: `acx_persons` gains `normalized_name` (`utf8mb4_bin`) + unique index and **drops** `idx_name` — greenfield direct schema edit in `class-life-cycle-manager.php:503`, no migration. `GET /acx/v1/roster/entries` response rows become grouped-unique by normalized name with the pinned survivor policy; envelope shape per row unchanged (rg-005: column names verified against the real CREATE TABLE in tests). `PATCH` cluster-label mutation gains person-binding side effects; request/response shapes unchanged.
- **Refresh contract (client)**: write-through is server-side; the roster entries query refetches on roster mount, so the honesty guarantee is "person appears on the next roster read". A one-line invalidation of the entries query key in the label mutation's `onSuccess` may land in Slice 6 only if no E15-37-FE lane is active (the mutation hook lives under `identity-clusters/**`); otherwise the mount-refetch behavior is the documented limitation.
- **Unchanged**: `commitClusterToRosterEntry` client contract; `reassignClusterIdentity`; recognition-service endpoints; `packages/shared-contracts/schemas/roster-entry.schema.json` field set (grouping changes row cardinality, not shape — if aggregation needs a new field, stop and regenerate the schema first, not mid-slice).
- **Curation replay**: write-through enqueues the existing `person_created` / bind operation kinds — no new outbox operation types.

## Files and Surfaces to Change

| File | Change | Slice |
| --- | --- | --- |
| `src/support/class-life-cycle-manager.php` (:503 `acx_persons` CREATE TABLE) | `normalized_name` (`utf8mb4_bin`) + unique index; retire `idx_name` | 1 |
| `src/sovereign/repositories/class-roster-entry-projection-repository.php` | normalized-name grouping + survivor policy + aggregation in `list_entries` | 1 |
| `src/api/class-api.php` | normalized person resolution + rebind-on-match in `commit_roster_cluster`; extract shared resolver | 1–2 |
| `src/api/services/class-cluster-label-service.php` | person write-through via shared resolver (inside existing `run_transactional`) | 2 |
| new `src/api/services/class-person-resolution-service.php` (explicit `require_once` from owning controllers — rg-016 `class_exists` verified) | single-writer, transaction-agnostic person resolve-or-create | 2 |
| `tests/Unit/…` (+ one real-DB/collation characterization pin) | per slice | 1–2 |
| `js/admin/pages/roster/ClusterDrawerPanel.tsx`, `hooks/useClusterDragDrop.ts` | "Move to…" keyboard path + always-visible affordances + announce | 3 |
| `js/admin/pages/roster/hooks/useClusterActions.ts`, `BulkActionBar.tsx` | announced progress + stop-on-failure + 30 s stall bound | 4 |
| `js/admin/pages/RosterPage.tsx`, `roster/rosterRoute.ts` | tab shell removal, enum retirement, param compat | 5a |
| `js/admin/pages/roster/RosterClustersTab.tsx`, `ClusterGrid.tsx` | delete | 5a |
| new `js/admin/pages/roster/NeedsAssignmentSection.tsx` (+ scss via tokens) | compact unassigned rail (existing clusters query, unlabeled predicate) | 5b |
| `js/admin/utils/adminUrls.ts`, `workbench/Panels.tsx`, `workbench/ConfirmTabContent.tsx`, PHP admin-URL localization | symbol/string-level link retarget only | 6 |
| `tests/e2e/a11y/roster-keyboard-walk.spec.ts`, `roster-axe.spec.ts`, roster `__tests__/` | extended per slice | 3–6 |

Read-only (likely unchanged): `PersonWorkspacePanel.tsx`, `RosterEntriesSection.tsx`, `RosterEntriesTable.tsx`, `rosterApi.ts`, `ClusterLabelingPanel.tsx` (client), `identity-clusters/**` (locked only while an E15-37-FE lane is active; see Constraints).

## Verification Strategy

Every slice's green must be able to go red ([TEST-15]); every new test observed failing once against pre-change behavior ([TEST-06]); untested PHP paths get characterization pins before change ([TEST-03]). The PHP unit suite stubs `wpdb` and cannot exercise MySQL collation — collation-dependent behavior gets one real-DB characterization pin (LocalWP MySQL) or a documented collation assumption in the test ([DATA-17]).

- **PHP characterization first** ([TEST-03], Slice 1 entry): against a real MySQL, pin today's behavior — inserting a name the `*_ci` index considers equal to an existing row ("Jose" vs "José", or trailing-space variant under the live PAD mode) makes `commit_roster_cluster` return the 500 duplicate-key error, not a duplicate row. This pin is the red baseline the slice flips.
- **PHP unit** (`composer test`): normalization helper property tests (trim + case-fold; "José" ≠ "Jose" preserved — red until the helper exists); commit with `new_entry_name` differing only by case/whitespace from an existing person **rebinds, zero inserts, zero errors** (red today: 500 duplicate-key); write-through — `update_cluster_label` on an unlabeled cluster creates exactly one person + binding + curation op, and re-labeling to an existing name re-binds without insert (red today: zero persons written); end-to-end write-through-to-read: the real label mutation followed by `list_entries` returns the person (names the "Entries never empty after naming" criterion); grouping survivor policy — fixed seed rows that normalize equal return one entry with the lowest `id` as primary and unioned aggregates, deterministic (rg-015 assert: aggregated fields equal the sum/union of member rows, no fabricated counts); transaction rollback leaves no partial person row ([CON-05]); resolver-inside-`run_transactional` issues no nested START TRANSACTION / implicit commit (assert single transaction boundary via the stub's query log).
- **TS unit** (Vitest): keyboard member-fix fires exactly one `reassignClusterIdentity` call with the picked target (rg-002; red before the control exists); picker excludes the current cluster and renders disabled-with-reason when no targets; "Move to…" visible without hover (computed-style/no-hover query — red against today's drag-only DOM); bulk-merge progress announces via `role="status"` per step, first failure renders persistent `role="alert"` + remainder-stays-selected (red against today's silent progress); sequential-order discrimination: mock per-id mutations resolving out of order and assert commit order matches selection order — fails if a parallel fan-out is introduced (replaces an unfalsifiable "no `Promise.all`" claim); stall: a never-resolving mutation aborts at the 30 s fake-timer bound and lands in the failure state; route compat: `?tab=clusters` → single surface, `cluster=<id>` → drawer open (extend `rosterRoute.test.ts`); rail mount discrimination (Slice 5b): unlabeled fixtures render the rail's bulk controls enabled, labeled-only fixtures render disabled-with-reason (guards against the rail never wiring bulk); zero references to the retired `ROSTER_TABS.clusters` symbol compile (enum retirement is type-checked, sr-007).
- **E2E a11y** (Playwright): extend `roster-keyboard-walk.spec.ts` — full member-fix loop keyboard-only (focus face → Move to… → pick target → `role=status` announced), ≥24px bounding boxes on new controls; `roster-axe.spec.ts` green over the single-surface page; `RosterZeroStateReachability.test.tsx` green with the Needs-assignment rail at zero state (disabled-with-reason asserted, not hidden).
- **Sweeps**: `banned-vocabulary.test.tsx`, `workbench-tokenization.test.ts` over touched sheets, `npm run typecheck`/lint gates; full-suite verification via `make check-remote` at slice boundaries (local runs stay scoped).
- **Manual (LocalWP) — non-gating** (automated equivalents above are the gate): name a cluster via the workbench labeling panel → person appears on `#/roster` on next visit without a commit step; name the same person with different casing → still one row, no error; drag a face and keyboard-move a face → identical outcome; kill the recognition service mid-bulk-merge → alert names the failure, remainder selected; open a legacy `…&tab=clusters` bookmark → lands on the roster, no dead tab.

## Slice Delivery

Slices sized for remote grok-4.5 lanes (bounded file set, scoped TEST_CMD, explicit exit); each slice merges through the pre-merge gate (`handoff_close_check(enforce=True)`); adversarial review per slice, coverage target 2. **Slice 1 does not start until the epic waiver is recorded (see Constraints). Slice 5b does not start until Open Question 1 is confirmed.**

### Slice 1: Explicit normalization + rebind + grouped read (PHP contract)
Schema edit in `class-life-cycle-manager.php:503`: `normalized_name` (`utf8mb4_bin`) + unique index, `idx_name` retired (rg-005 parity test against the real CREATE TABLE); one normalization helper; `commit_roster_cluster` resolves by normalized name in-transaction and rebinds on match (today: duplicate-key 500); `list_entries` groups by normalized name with the pinned survivor policy (lowest-id primary, unioned aggregates, rg-015). Real-DB collation characterization pin first ([TEST-03]/[DATA-17]), then flip.
`TEST_CMD="cd apps/prototype-wp-alt-context && composer test -- --filter 'RosterEntryProjectionRepositoryTest|PersonDedupe'"`
**Exit**: characterization pin recorded (was: 500 on collation-equal name); rebind test green (was red); survivor-policy grouping test green and deterministic; rollback test green; `phpstan` + `cs-check` green.

### Slice 2: Label-curation → person write-through (PHP contract)
Extract shared, **transaction-agnostic** `PersonResolutionService` from `commit_roster_cluster` ([ARCH-02] single writer; caller owns the transaction — no nested START TRANSACTION, see `trait-runs-transactional.php`; loaded via explicit `require_once`, rg-016 runtime `class_exists` check); `ClusterLabelService::update_cluster_label` resolves-or-creates + binds + enqueues curation ops inside its existing `run_transactional` boundary ([API-03] replay-safe payloads).
`TEST_CMD="cd apps/prototype-wp-alt-context && composer test -- --filter 'ClusterLabelService|PersonResolution'"`
**Exit**: labeling an unlabeled cluster yields exactly one person + binding (was zero); re-label to existing name re-binds, no insert; write-through-to-read test green (label mutation → `list_entries` shows the person); no-nested-transaction assert green; `commit_roster_cluster` behavior identical through the extraction (characterization pins green); no orchestration duplicated between controllers.

### Slice 3: Keyboard member-fix + always-visible affordances (TS — rebase on E15-37-FE first only if it merged)
"Move to…" per face in `ClusterDrawerPanel` (always visible, ≥24px, button semantics, in tab order) → target picker (existing clusters list query, current cluster excluded, empty ⇒ disabled-with-reason) → single `reassignMutation` call; `role=status` outcome announce; drag path unchanged over the same mutation ([A11Y-15][A11Y-14][A11Y-21], rg-002).
`TEST_CMD="cd apps/prototype-wp-alt-context && npm run test -- ClusterDrawerPanel"`
**Exit**: keyboard-only member fix proven in unit + `roster-keyboard-walk.spec.ts`; one-call assert green; picker exclusion/empty tests green; no hover-gated affordance remains on the drawer (no-hover query green, was red); axe green.

### Slice 4: Announced progressive bulk merge + designed failure state (TS)
`useClusterActions` bulk merge: per-step `role=status` progress; stop-on-first-failure with persistent `role=alert` (failed cluster named, retry reachable), remainder stays selected; bounded — 30 s per-mutation timeout via `AbortController`, timeout = step failure (rg-007 analog).
`TEST_CMD="cd apps/prototype-wp-alt-context && npm run test -- useClusterActions BulkActionBar"`
**Exit**: progress announcements asserted per step; mid-sequence-failure test green (alert + selection retained — was silent toast); sequential-order discrimination test green (fails under parallel fan-out); stall-timeout test green.

### Slice 5a: Clusters-tab retirement (TS structural — [REF-05] no behavior change beyond mounting)
Tab shell removed from `RosterPage`; `ROSTER_TABS` retired (sr-007); `RosterClustersTab`/`ClusterGrid` deleted; `cluster=` param opens the drawer in place; `tab=` param dropped on parse. Zero new UI.
`TEST_CMD="cd apps/prototype-wp-alt-context && npm run test -- RosterPage rosterRoute"`
**Exit**: single surface renders; route-compat tests green (legacy `tab=clusters` bookmark + `cluster=` deep link both land usefully); all Slice-3/4 behavior tests still green unmodified (the structural-move guard); typecheck proves no `clusters`-tab symbol survives.

### Slice 5b: Needs-assignment rail (TS behavior — gated on Open Question 1 confirmation)
`NeedsAssignmentSection` mounts the Slice-4 bulk surface over unlabeled clusters (existing `useRecognitionClusters` list query, empty-`label` predicate, no new endpoint) + per-cluster deep link to the workbench review queue; zero state = section visible, controls disabled-with-reason.
`TEST_CMD="cd apps/prototype-wp-alt-context && npm run test -- NeedsAssignment RosterZeroState"`
**Exit**: rail mount discrimination green (unlabeled fixtures ⇒ enabled bulk controls; labeled-only ⇒ disabled-with-reason); zero-state reachability test green with the rail; deep links resolve to the review queue.

### Slice 6: Link contract + copy + e2e sweep (TS)
Symbol/string-level only: `rosterClustersUrl()` → `rosterUrl()` (+ PHP localization key); `Panels.tsx`/`ConfirmTabContent.tsx` retarget + people-first copy — no structural workbench refactors (E21-10 is the sole later changer of these helpers; roster root is the frozen intermediate); optional entries-query invalidation in the label mutation `onSuccess` if no E15-37-FE lane is active; banned-vocabulary, tokenization, axe, keyboard-walk sweeps over every touched surface; `#/roster?person=` deep-link semantics documented for E21-10 handover (E21-10 owns the vocabulary extension, not built here).
`TEST_CMD="cd apps/prototype-wp-alt-context && npm run test -- adminUrls banned-vocabulary && npm run typecheck"`
**Exit**: no `tab=clusters` producer remains in the codebase (grep-asserted in a test); consumers navigate to the live surface; all sweeps green; `make check-remote` green at HEAD.

## Consolidated Checklist

### Gate
- [ ] Epic Hard Constraints / E21-9 re-baseline amendment recorded authorizing the additive local-plugin contract changes (operator, before Slice 1)

### Slice 1: Normalization + rebind + grouped read
- [ ] `normalized_name` (`utf8mb4_bin`) + unique index landed in `class-life-cycle-manager.php:503`; `idx_name` retired; parity test against real CREATE TABLE (rg-005)
- [ ] One normalization helper (trim + case-fold, no diacritic folding); write-end lookup + read-end grouping both use it
- [ ] Real-DB collation characterization pin recorded; rebind-on-match green (was 500); rollback leaves no partial row
- [ ] Survivor policy pinned (lowest-id primary; unioned aggregates) with deterministic test; aggregated fields derived from member rows only (rg-015)

### Slice 2: Write-through
- [ ] `PersonResolutionService` extracted; transaction-agnostic (caller owns transaction; no-nesting assert); single writer for `acx_persons` inserts; `require_once` + `class_exists` verified (rg-016)
- [ ] `update_cluster_label` creates/binds person + curation ops in one transaction; write-through-to-read test green
- [ ] `commit_roster_cluster` characterization pins green through the extraction

### Slice 3: Keyboard member-fix
- [ ] Always-visible "Move to…" ≥24px, tab-order, single atomic reassign call; picker excludes current cluster, empty ⇒ disabled-with-reason
- [ ] `role=status` announce; keyboard-walk e2e extended; no hover-gated affordance on the drawer

### Slice 4: Bulk merge announce + failure state
- [ ] Per-step `role=status`; stop-on-failure `role=alert` + remainder-selected; sequential-order discrimination test; 30 s stall bound

### Slice 5a: Retirement (structural)
- [ ] Tab shell + `ROSTER_TABS` + `RosterClustersTab`/`ClusterGrid` gone; single person-first surface; legacy `tab=clusters` + `cluster=` params land usefully
- [ ] Slice-3/4 tests pass unmodified across the move

### Slice 5b: Needs-assignment rail (after Q1 confirmation)
- [ ] Rail mounts Slice-4 bulk over unlabeled clusters via existing query; reachable + disabled-with-reason at zero state; rail mount discrimination test green

### Slice 6: Links + sweep
- [ ] `rosterUrl()` retarget incl. PHP localization; workbench consumers updated symbol/string-level only; no `tab=clusters` producer remains
- [ ] banned-vocabulary / tokenization / axe / keyboard-walk green; `make check-remote` green

## Success Criteria

Each criterion names its gating check ([FORE-02] scorability; Manual (LocalWP) steps are illustrative, non-gating).

- [ ] Naming a person through **either** path (workbench label, roster commit) yields exactly one person row on the next `#/roster` read — never zero, never duplicates, never a duplicate-key error — server-enforced. *Gate: write-through-to-read PHP test + rebind test (Slices 1–2).*
- [ ] The Roster page is a single person-first surface; cluster triage happens in the workbench review queue; unassigned work remains reachable from roster zero state (rg-003). *Gate: route-compat + `RosterZeroStateReachability` + rail mount discrimination tests.*
- [ ] Every drag operation on surfaces this task owns has an equivalent click/keyboard path driving the same atomic mutation ([A11Y-15], rg-002); no hover-only affordance ([A11Y-14]). Face-scrubber keyboard parity is owned by E15-17 s3–4 — full epic-amendment discharge requires verifying E15-17 shipped it with a cited test, else the residual is recorded on the epic. *Gate: one-call assert + no-hover query + keyboard-walk e2e.*
- [ ] Progressive bulk merge is announced ([A11Y-21]) and fails legibly mid-sequence ([A11Y-24]): alert + retry + remainder selected, bounded by the stall timeout. *Gate: Slice-4 unit tests.*
- [ ] No dead links: every former `tab=clusters` producer navigates somewhere real. *Gate: grep-asserted producer test + consumer navigation tests (Slice 6).*
- [ ] Automated a11y sweeps are the floor, not the pass ([A11Y-23]): the keyboard-walk e2e covers the member-fix loop end-to-end. *Gate: extended `roster-keyboard-walk.spec.ts`.*

## Open Questions (dispositions as of the 2026-07-22 planning review)

1. **Bulk merge/dismiss final home** — OPEN, operator decides at Slice-5b intake. This plan keeps it on the roster's Needs-assignment rail; alternative is retiring it entirely in favor of the workbench multi-select bulk (E21-5). The rail partially recreates the triage surface Slice 5a retires, so the answer gates Slice 5b funding (5a proceeds regardless).
2. **`rosterClustersUrl` consumer retarget** — OPEN, decided by the E21-10 owner. Roster root is this plan's frozen intermediate; E21-10 is the sole later changer if it prefers deep-linking to the workbench review queue.
3. **Normalization policy** — **ANSWERED in-plan** (operator confirms at Slice-1 intake): trim + Unicode case-fold, no diacritic folding ("José" ≠ "Jose"). Because the existing `idx_name` under `*_ci` collation enforces the *opposite* (accent-insensitive) regime, the policy is implemented jointly: `normalized_name` pins `utf8mb4_bin` and `idx_name` is retired in the same DDL — a PHP helper alone cannot implement the policy against a `*_ci` index.
4. **Legacy duplicate rows** — **ANSWERED**: no one-shot hard merge. The existing `UNIQUE idx_name` plus greenfield wipe-on-deploy means same-name duplicate rows cannot exist today; render-time grouping stays as defense-in-depth scoped to the post-Q3 residual uniqueness gap, and its tests target that gap (not states the DB forbids — [TEST-15]).

## Heuristic IDs cited

Verified present in `~/Development/heuristics-canon/lexicons/` (accessibility.md, engineering.md): A11Y-14, A11Y-15, A11Y-21, A11Y-23, A11Y-24, TEST-03, TEST-06, TEST-15, REF-05, CON-05, ARCH-02, API-03, DATA-17, FORE-02. Repo guards cited: rg-002, rg-003, rg-005, rg-007, rg-015, rg-016; sr-004, sr-007, sr-009.
