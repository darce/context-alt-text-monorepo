# E21-9. Roster Clusters-tab retirement + person-first roster

**Epic**: [E21 Public-MVP UX polish](../../epics/v0.4.1/public-mvp-ux-polish-epic.md) · Phase 4 (Person-first roster & link contract)
**Date**: 2026-07-22 · **Author**: Claude (Fable 5)
**Target Branch**: `feature/e21-9` · **Worktree**: `context-alt-text-monorepo-e21-9`
**Review Coverage Target**: 2
**Depends on**: E21-5 (unified review queue + person-commit — landed on `main`), E15-17 s3–4 (face scrubber + cluster evidence, under the [E15-17 plan](../15.0/E15-17-roster-person-review-scrub-workspace-task-plan.md))
**Blocks**: E21-10 (cross-surface link contract)
**UXP amendments folded at authoring time** ([uxp-ux-pass-decomposition.md](../../scopes/uxp-ux-pass-decomposition.md) §Amendments, E21-9 row; epic Re-baseline table E21-9 row): label-curation ⇒ person-projection write-through; server-side same-label grouping so duplicate person rows cannot render; Entries never empty after naming (UXA-09); every drag ships a click/keyboard alternative ([A11Y-15]); hover-only affordances become always-visible ([A11Y-14]); progressive bulk merge gets live-region progress + a designed mid-sequence-failure state ([A11Y-21]/[A11Y-24]).

## Objective

Retire the Roster page's Clusters tab and make the person-first surface the only roster. The workbench review queue (E21-5) is the canonical cluster-triage surface; Roster curates people. Close the two data-honesty gaps that make person-first impossible today: (1) naming a cluster through the workbench label path produces a label but no person, so the Entries surface can stay empty after naming; (2) the entries read path renders one row per `acx_persons` row with no same-label grouping, so duplicate person rows can render. Ship the amended a11y obligations on the surviving cluster-manipulation seams (keyboard member-fix, always-visible affordances, announced progressive bulk merge).

## Problem Statement

`RosterPage.tsx` renders two tabs (`RosterPage.tsx:255-288`) from the `ROSTER_TABS` enum (`js/admin/pages/roster/rosterRoute.ts:4-7`). The Clusters tab (`RosterClustersTab.tsx`) is a full parallel review surface — grid, multi-select, bulk merge/dismiss, drag-drop face reassignment — duplicating the workbench review queue E21-5 shipped. Cross-surface links hardcode the duplicate: `adminUrls.ts:4` falls back to `…&tab=clusters`, consumed by `Panels.tsx:218` ("Open clusters in roster") and `ConfirmTabContent.tsx:31`.

Data honesty: the workbench label path (`ClusterLabelingPanel.tsx` → `update_cluster_label`, `class-cluster-mutations-controller.php:236` → `ClusterLabelService`) writes only the cluster label — `src/api/services/class-cluster-label-service.php` (121 lines) never touches `acx_persons` — so "Name this person" via labeling leaves the person-first surface empty (UXA-09). The person path (`class-api.php:398` `commit_roster_cluster`) dedupes only by byte-exact name (`WHERE name = %s`, `class-api.php:421`), and the read path (`RosterEntryProjectionRepository::list_entries`, `src/sovereign/repositories/class-roster-entry-projection-repository.php:33`) is `SELECT * FROM acx_persons ORDER BY name ASC` with no grouping — "Ada" and "ada " render as two people.

A11y: face reassignment is drag-only (`ClusterDrawerPanel.tsx:212` `draggable`; `useClusterDragDrop.ts` has no keyboard path) — an [A11Y-15] violation; bulk merge progress lives in `useClusterActions.ts:30` (`bulkMergeProgress`) with no live region and no designed mid-sequence-failure state.

## Constraints

- **Sequencing (hard)**: **E15-37-FE merges first** — it touches `js/admin/hooks/` and `js/admin/pages/workbench/identity-clusters/`. E21-9 rebases on it before Slice 3 lands. **No concurrent edits to `js/admin/pages/workbench/identity-clusters/**` while the E15-37-FE lane is active.** Open findings on `resolveMergeSurvivor.ts` / `useLiveReviewTarget.ts` belong to a separate MAINT lane — do not fix them here.
- **Two hats ([REF-05])**: server contract changes (Slices 1–2, PHP) never mix with the TS surface restructuring (Slices 3–6). Slice 5 is a structural move with zero behavior change beyond mounting; behavior amendments land in Slices 3–4 first.
- **rg-002 (atomic writes)**: keyboard member-fix drives the existing single `reassignClusterIdentity` call; write-through binds label→person in one server transaction — never split into label-then-commit frontend mutations.
- **rg-003 (zero-state reachability)**: the retired tab must not orphan triage — unassigned-cluster work stays reachable from the person-first surface at zero state (disabled-with-reason, never hidden). E21-12's always-visible person list is the baseline; keep `RosterZeroStateReachability.test.tsx` green.
- **rg-005 (schema parity)**: the normalized-name column/index is validated against the real `acx_persons` schema (greenfield: schema change lands directly in the plugin's table definition — no migration shim; delete-over-flag).
- **rg-015 (no invented metadata)**: grouped entries' `cluster_count`, `queue_memberships`, projection fields derive from the grouped source rows or documented fallbacks — never fabricated during aggregation.
- **sr-004**: all touched styles consume `--acx-*` tokens; `workbench-tokenization.test.ts` stays green.
- **sr-007**: `ROSTER_TABS` shrinks/retires as an enum edit in `rosterRoute.ts` — no scattered `'clusters'` string comparisons survive; route params and queue ids keep their `as const` unions.
- **Banned vocabulary**: surviving copy passes `banned-vocabulary.test.tsx`; people-first terms per UXP-4's `syncVocabulary.ts` map ("Clusters" as user-facing tab vocabulary disappears with the tab).
- **Findings discipline**: review findings live in workbay-handoff MCP by ID only; no finding status in this plan.

## Current State Analysis (ground truth, verified 2026-07-22 on `feature/e21-9` @ branch point from `main` 4b326c54)

| Surface | Anchor | Fact |
| --- | --- | --- |
| Tab shell | `js/admin/pages/RosterPage.tsx:255-288` | `Tabs` over `ROSTER_TABS` (entries, clusters); entries tab mounts `PersonWorkspacePanel` + `RosterEntriesSection`; clusters tab mounts `RosterClustersTab` |
| Route model | `js/admin/pages/roster/rosterRoute.ts:4-11, 96-120` | `ROSTER_TABS` enum; `ROSTER_ROUTE_PARAM_KEYS = ['person','queue','face','cluster']`; `cluster=` param forces clusters tab; `tab=clusters` legacy param |
| Cluster tab | `js/admin/pages/roster/RosterClustersTab.tsx` (151), `ClusterGrid.tsx` (243), `BulkActionBar.tsx` (62), `useRosterBulkConfirmation.ts` | duplicate triage surface: grid, selection, bulk merge/dismiss with confirm dialog |
| Drawer | `js/admin/pages/roster/ClusterDrawerPanel.tsx` (320) | page-level panel; face thumbnails `draggable` (:212); commit/rescan/reassign; opens from `cluster=` param or grid |
| Drag seam | `js/admin/pages/roster/hooks/useClusterDragDrop.ts` | drag payload/drop-target state; no keyboard path anywhere |
| Actions | `js/admin/pages/roster/hooks/useClusterActions.ts` | `reassignMutation` (single atomic call), `commitMutation` → `commitClusterToRosterEntry`, `bulkMergeProgress` state (:30) — progress not announced; toast-only outcomes |
| Person workspace | `js/admin/pages/roster/PersonWorkspacePanel.tsx` (237) | per-person cluster evidence + curriculum queue links (E15-17 s1–2 shell); banned-strings "Source version" (:90), "projected instances" (:137), "Curriculum" (:196) are E21-1's banned-vocabulary scope, not owned here |
| Label write path | `js/admin/pages/workbench/identity-clusters/ClusterLabelingPanel.tsx` → `src/api/class-cluster-mutations-controller.php:236` → `src/api/services/class-cluster-label-service.php` | label-only; zero `acx_persons` writes; person∪cluster typeahead with blocking duplicate guard (UXP-3) exists client-side only |
| Person write path | `src/api/class-api.php:398-470` `commit_roster_cluster` | transactional; byte-exact name dedupe (`WHERE name = %s`); inserts `acx_persons` + enqueues `person_created` curation op |
| Entries read path | `class-api.php:393` → `src/sovereign/repositories/class-roster-entry-projection-repository.php:23-86` `list_entries` | `SELECT * FROM acx_persons ORDER BY name ASC`; per-row projection join; **no same-label grouping** |
| Cross-surface links | `js/admin/utils/adminUrls.ts:4,26` `rosterClustersUrl()`; consumers `workbench/Panels.tsx:8,218`, `workbench/ConfirmTabContent.tsx:31` | hardcode `&tab=clusters` |
| Tests | `tests/Unit/RosterEntryProjectionRepositoryTest.php`; `js/admin/pages/roster/__tests__/` (incl. `rosterRoute.test.ts`, `RosterZeroStateReachability.test.tsx`); `tests/e2e/a11y/roster-keyboard-walk.spec.ts`, `roster-axe.spec.ts` | existing harnesses to extend |

Landed context: E21-5 shipped person-commit + multi-select bulk on the workbench review queue (canonical triage). E21-12 shipped the always-visible person list + Add Person + designed empty state. E15-17 s1–2 shipped the workspace shell; s3–4 (face scrubber, evidence migration) execute under the E15-17 plan and are consumed, not built, here.

## Proposed Solution

**Server first, surface last.** Slices 1–2 make the person projection honest (write-through + dedupe) so the person-first surface has true data. Slices 3–4 discharge the a11y amendments on the seams that survive retirement. Slice 5 retires the tab as a pure structural move. Slice 6 sweeps links, copy, and e2e.

1. **Same-label dedupe, server-side, both ends** (Slice 1). One normalization helper (trim + Unicode case-fold; no diacritic folding — pinned policy, see Open Questions): a `normalized_name` column + unique-per-tenant index on `acx_persons` (greenfield, direct schema edit). Write end: `commit_roster_cluster`'s person resolution looks up by normalized name inside the existing transaction ([CON-05] — the check-then-insert race is closed by the transaction + unique index, not by the lookup alone). Read end: `list_entries` groups rows by normalized name before mapping, aggregating `cluster_count`/`clusters`/`queue_memberships` from real member rows (rg-015) — defense-in-depth so pre-existing duplicate rows cannot render regardless of writer.
2. **Label-curation ⇒ person-projection write-through** (Slice 2). Extract the person-resolution block of `commit_roster_cluster` into a shared service ([ARCH-02] — one writer owns `acx_persons`; two controllers must not carry parallel insert logic). `ClusterLabelService::update_cluster_label` calls it: labeling a cluster resolves-or-creates the person (normalized dedupe from Slice 1), binds cluster→person, and enqueues the same curation ops, all in one transaction ([API-03] — the replayed operation carries the resolved person, not a relative "create if missing"). Result: Entries is never empty after naming, whichever path named it.
3. **Keyboard member-fix + always-visible affordances** (Slice 3). Every draggable face in `ClusterDrawerPanel` gains an always-visible "Move to…" control (button semantics, ≥24×24 CSS px [A11Y-14]) opening a target-cluster picker that drives the same single `reassignMutation` call ([A11Y-15], rg-002). Outcome announced via `role="status"` ([A11Y-21]). Drag remains as an enhancement over the same mutation.
4. **Announced progressive bulk merge** (Slice 4). Hook-level, surface-agnostic: `bulkMergeProgress` feeds an inline `role="status"` live region ("Merging N of M…"); first failure stops the run, surfaces a persistent inline `role="alert"` naming the failed cluster with retry, and the un-processed remainder stays selected ([A11Y-24] designed failure state; mirrors the E21-5 Slice-5 stop-on-failure pattern). Landing this before retirement keeps the amendment honored through the transition and the hook clean wherever it mounts.
5. **Tab retirement** (Slice 5). `RosterPage` drops `Tabs`; the person-first surface is the page. `ROSTER_TABS` retires (sr-007 enum edit). Unassigned-cluster triage: a compact **"Needs assignment"** section on the single surface mounts the (Slice-4-hardened) selection + bulk merge/dismiss over unlabeled clusters and deep-links each cluster to the workbench review queue for card-at-a-time triage — rg-003 kept, duplicate grid retired. `RosterClustersTab.tsx` + `ClusterGrid.tsx` deleted; `BulkActionBar`/`useRosterBulkConfirmation`/`ClusterDrawerPanel` survive remounted. Route compat: `?tab=clusters` and bare `cluster=<id>` parse to the single surface — `cluster=` opens the drawer in place (deep links keep working); `tab` param is dropped on parse.
6. **Link + copy sweep** (Slice 6). `rosterClustersUrl()` → `rosterUrl()` (roster root; the PHP-localized `adminUrls.rosterClusters` config key follows); workbench consumers' copy retargets ("Open roster"); banned-vocabulary/axe/keyboard-walk/tokenization sweeps over every touched surface.

## Contract and Boundary Impact

- **Changed (additive)**: `acx_persons` gains `normalized_name` (+ unique index) — greenfield direct schema edit, no migration. `GET /acx/v1/roster/entries` response rows become grouped-unique by normalized name; envelope shape per row unchanged (rg-005: column names verified against real schema in tests). `PATCH` cluster-label mutation gains person-binding side effects; request/response shapes unchanged.
- **Unchanged**: `commitClusterToRosterEntry` client contract; `reassignClusterIdentity`; recognition-service endpoints (zero remote contract changes); `packages/shared-contracts/schemas/roster-entry.schema.json` field set (grouping changes row cardinality, not shape — if aggregation needs a new field, stop and regenerate the schema first, not mid-slice).
- **Curation replay**: write-through enqueues the existing `person_created` / bind operation kinds — no new outbox operation types.

## Files and Surfaces to Change

| File | Change | Slice |
| --- | --- | --- |
| `src/.../class-roster-entry-projection-repository.php` | normalized-name grouping + aggregation in `list_entries` | 1 |
| `src/api/class-api.php` | normalized person resolution in `commit_roster_cluster`; extract shared resolver | 1–2 |
| plugin schema definition for `acx_persons` (+ `tests/Unit/…`) | `normalized_name` column + unique index | 1 |
| `src/api/services/class-cluster-label-service.php` | person write-through via shared resolver | 2 |
| new `src/api/services/class-person-resolution-service.php` (PSR-4-loadable or explicit `require_once` — rg-016) | single-writer person resolve-or-create | 2 |
| `js/admin/pages/roster/ClusterDrawerPanel.tsx`, `hooks/useClusterDragDrop.ts` | "Move to…" keyboard path + always-visible affordances + announce | 3 |
| `js/admin/pages/roster/hooks/useClusterActions.ts`, `BulkActionBar.tsx` | announced progress + stop-on-failure state | 4 |
| `js/admin/pages/RosterPage.tsx`, `roster/rosterRoute.ts` | tab shell removal, enum retirement, param compat | 5 |
| `js/admin/pages/roster/RosterClustersTab.tsx`, `ClusterGrid.tsx` | delete | 5 |
| new `js/admin/pages/roster/NeedsAssignmentSection.tsx` (+ scss via tokens) | compact unassigned rail | 5 |
| `js/admin/utils/adminUrls.ts`, `workbench/Panels.tsx`, `workbench/ConfirmTabContent.tsx`, PHP admin-URL localization | link retarget | 6 |
| `tests/e2e/a11y/roster-keyboard-walk.spec.ts`, `roster-axe.spec.ts`, roster `__tests__/` | extended per slice | 3–6 |

Read-only (likely unchanged): `PersonWorkspacePanel.tsx`, `RosterEntriesSection.tsx`, `RosterEntriesTable.tsx`, `rosterApi.ts`, `ClusterLabelingPanel.tsx` (client), `identity-clusters/**` (locked until E15-37-FE merges).

## Verification Strategy

Every slice's green must be able to go red ([TEST-15]); every new test observed failing once against pre-change behavior ([TEST-06]); untested PHP paths get characterization pins before change ([TEST-03]).

- **PHP unit** (`composer test`): dedupe discrimination pair — seed `"Ada"` + `"ada "` → `list_entries` returns one row with aggregated `cluster_count` (red on today's `SELECT *`); commit with `new_entry_name: "ADA"` binds the existing person, zero inserts (red today: byte-exact miss inserts a duplicate); write-through — `update_cluster_label` on an unlabeled cluster creates exactly one person + binding + curation op, and re-labeling to an existing name re-binds without insert (red today: zero persons written); transaction rollback leaves no partial person row ([CON-05]); rg-015 assert: aggregated fields equal the sum/union of member rows, no fabricated counts.
- **TS unit** (Vitest): keyboard member-fix fires exactly one `reassignClusterIdentity` call with the picked target (rg-002; red before the control exists); "Move to…" visible without hover (computed-style/no-hover query — red against today's drag-only DOM); bulk-merge progress announces via `role="status"` per step, first failure renders persistent `role="alert"` + remainder-stays-selected (red against today's silent progress); route compat: `?tab=clusters` → single surface, `cluster=<id>` → drawer open (extend `rosterRoute.test.ts`); zero references to the retired `ROSTER_TABS.clusters` symbol compile (enum retirement is type-checked, sr-007).
- **E2E a11y** (Playwright): extend `roster-keyboard-walk.spec.ts` — full member-fix loop keyboard-only (focus face → Move to… → pick target → `role=status` announced), ≥24px bounding boxes on new controls; `roster-axe.spec.ts` green over the single-surface page; `RosterZeroStateReachability.test.tsx` green with the Needs-assignment rail at zero state (disabled-with-reason asserted, not hidden).
- **Sweeps**: `banned-vocabulary.test.tsx`, `workbench-tokenization.test.ts` over touched sheets, `npm run typecheck`/lint gates; full-suite verification via `make check-remote` at slice boundaries (local runs stay scoped).
- **Manual (LocalWP)**: name a cluster via the workbench labeling panel → person appears on `#/roster` without a commit step; name the same person with different casing → still one row; drag a face and keyboard-move a face → identical outcome; kill the recognition service mid-bulk-merge → alert names the failure, remainder selected; open a legacy `…&tab=clusters` bookmark → lands on the roster, no dead tab.

## Slice Delivery

Slices sized for remote grok-4.5 lanes (bounded file set, scoped TEST_CMD, explicit exit); each slice merges through the pre-merge gate (`handoff_close_check(enforce=True)`); adversarial review per slice, coverage target 2.

### Slice 1: Server-side same-label dedupe (PHP contract)
`normalized_name` column + unique index (direct schema edit, rg-005 parity test); one normalization helper; `commit_roster_cluster` resolves persons by normalized name in-transaction; `list_entries` groups by normalized name with real-row aggregation (rg-015). Characterize current duplicate behavior first ([TEST-03]), then flip.
`TEST_CMD="cd apps/prototype-wp-alt-context && composer test -- --filter 'RosterEntryProjectionRepositoryTest|PersonDedupe'"`
**Exit**: discrimination pair green (was red); duplicate rows cannot render from either legacy data or new writes; rollback test green; `phpstan` + `cs-check` green.

### Slice 2: Label-curation → person write-through (PHP contract)
Extract shared `PersonResolutionService` from `commit_roster_cluster` ([ARCH-02] single writer; rg-016 autoload verified with a runtime `class_exists` check); `ClusterLabelService::update_cluster_label` resolves-or-creates + binds + enqueues curation ops in one transaction ([API-03] replay-safe payloads).
`TEST_CMD="cd apps/prototype-wp-alt-context && composer test -- --filter 'ClusterLabelService|PersonResolution'"`
**Exit**: labeling an unlabeled cluster yields exactly one person + binding (was zero); re-label to existing name re-binds, no insert; `commit_roster_cluster` behavior byte-identical through the extraction (characterization pins green); no orchestration duplicated between controllers.

### Slice 3: Keyboard member-fix + always-visible affordances (TS — after E15-37-FE merge + rebase)
"Move to…" per face in `ClusterDrawerPanel` (always visible, ≥24px, button semantics, in tab order) → target picker → single `reassignMutation` call; `role=status` outcome announce; drag path unchanged over the same mutation ([A11Y-15][A11Y-14][A11Y-21], rg-002).
`TEST_CMD="cd apps/prototype-wp-alt-context && npm run test -- ClusterDrawerPanel"`
**Exit**: keyboard-only member fix proven in unit + `roster-keyboard-walk.spec.ts`; one-call assert green; no hover-gated affordance remains on the drawer (no-hover query green, was red); axe green.

### Slice 4: Announced progressive bulk merge + designed failure state (TS)
`useClusterActions` bulk merge: per-step `role=status` progress; stop-on-first-failure with persistent `role=alert` (failed cluster named, retry reachable), remainder stays selected; bounded — a stalled step exits the run, never spins (rg-007 analog).
`TEST_CMD="cd apps/prototype-wp-alt-context && npm run test -- useClusterActions BulkActionBar"`
**Exit**: progress announcements asserted per step; mid-sequence-failure test green (alert + selection retained — was silent toast); no `Promise.all` fan-out introduced (sequential per-id, rg-002).

### Slice 5: Clusters-tab retirement (TS structural — [REF-05] no behavior change beyond mounting)
Tab shell removed from `RosterPage`; `ROSTER_TABS` retired (sr-007); `RosterClustersTab`/`ClusterGrid` deleted; `NeedsAssignmentSection` mounts the Slice-4 bulk surface over unlabeled clusters + per-cluster deep link to the workbench review queue; `cluster=` param opens the drawer in place; `tab=` param dropped on parse.
`TEST_CMD="cd apps/prototype-wp-alt-context && npm run test -- RosterPage rosterRoute NeedsAssignment"`
**Exit**: single surface renders; route-compat tests green (legacy `tab=clusters` bookmark + `cluster=` deep link both land usefully); zero-state reachability test green with the rail; all Slice-3/4 behavior tests still green unmodified (the structural-move guard); typecheck proves no `clusters`-tab symbol survives.

### Slice 6: Link contract + copy + e2e sweep (TS)
`rosterClustersUrl()` → `rosterUrl()` (+ PHP localization key); `Panels.tsx`/`ConfirmTabContent.tsx` retarget + people-first copy; banned-vocabulary, tokenization, axe, keyboard-walk sweeps over every touched surface; `#/roster?person=` deep-link semantics documented for E21-10 handover (E21-10 owns the vocabulary extension, not built here).
`TEST_CMD="cd apps/prototype-wp-alt-context && npm run test -- adminUrls banned-vocabulary && npm run typecheck"`
**Exit**: no `tab=clusters` producer remains in the codebase (grep-asserted in a test); consumers navigate to the live surface; all sweeps green; `make check-remote` green at HEAD.

## Consolidated Checklist

### Slice 1: Server-side dedupe
- [ ] `normalized_name` column + unique index landed directly in schema; parity test against real schema (rg-005)
- [ ] One normalization helper (trim + case-fold); write-end lookup + read-end grouping both use it
- [ ] Discrimination pair green (duplicate casing → one row; commit re-binds, no insert); rollback leaves no partial row
- [ ] Aggregated fields derived from member rows only (rg-015)

### Slice 2: Write-through
- [ ] `PersonResolutionService` extracted; single writer for `acx_persons` inserts; autoload verified (rg-016)
- [ ] `update_cluster_label` creates/binds person + curation ops in one transaction; Entries never empty after naming
- [ ] `commit_roster_cluster` characterization pins green through the extraction

### Slice 3: Keyboard member-fix
- [ ] Always-visible "Move to…" ≥24px, tab-order, single atomic reassign call
- [ ] `role=status` announce; keyboard-walk e2e extended; no hover-gated affordance on the drawer

### Slice 4: Bulk merge announce + failure state
- [ ] Per-step `role=status`; stop-on-failure `role=alert` + remainder-selected; sequential per-id commits

### Slice 5: Retirement
- [ ] Tab shell + `ROSTER_TABS` + `RosterClustersTab`/`ClusterGrid` gone; single person-first surface
- [ ] `NeedsAssignmentSection` reachable at zero state; legacy `tab=clusters` + `cluster=` params land usefully
- [ ] Slice-3/4 tests pass unmodified across the move

### Slice 6: Links + sweep
- [ ] `rosterUrl()` retarget incl. PHP localization; workbench consumers updated; no `tab=clusters` producer remains
- [ ] banned-vocabulary / tokenization / axe / keyboard-walk green; `make check-remote` green

## Success Criteria

- [ ] Naming a person through **either** path (workbench label, roster commit) yields exactly one visible person row on `#/roster` — never zero, never duplicates — server-enforced (client cannot render what the server deduped).
- [ ] The Roster page is a single person-first surface; cluster triage happens in the workbench review queue; unassigned work remains reachable from roster zero state (rg-003).
- [ ] Every drag operation on the roster has an equivalent click/keyboard path driving the same atomic mutation ([A11Y-15], rg-002); no hover-only affordance ([A11Y-14]).
- [ ] Progressive bulk merge is announced ([A11Y-21]) and fails legibly mid-sequence ([A11Y-24]): alert + retry + remainder selected.
- [ ] No dead links: every former `tab=clusters` producer navigates somewhere real.
- [ ] Automated a11y sweeps are the floor, not the pass ([A11Y-23]): the keyboard-walk e2e covers the member-fix loop end-to-end.

## Open Questions (resolve at `/planning-review` or operator intake)

1. **Bulk merge/dismiss final home** — this plan keeps it on the roster's Needs-assignment rail (Slice 5). Alternative: retire it entirely in favor of the workbench multi-select bulk (E21-5). Confirm before Slice 5 funding.
2. **`rosterClustersUrl` consumer retarget** — roster root (chosen) vs deep-linking straight to the workbench review queue. E21-10's link contract may prefer the latter; confirm to avoid churn.
3. **Normalization policy** — trim + Unicode case-fold, no diacritic folding ("José" ≠ "Jose") is the pinned proposal. Confirm.
4. **Legacy duplicate rows** — render-time grouping (chosen, non-destructive) vs a one-shot hard merge of existing duplicate `acx_persons` rows (greenfield permits). Grouping is defense-in-depth either way; confirm whether a hard merge should also land in Slice 1.

## Heuristic IDs cited

Verified present in `~/Development/heuristics-canon/lexicons/` (accessibility.md, engineering.md): A11Y-14, A11Y-15, A11Y-21, A11Y-23, A11Y-24, TEST-03, TEST-06, TEST-15, REF-05, CON-05, ARCH-02, API-03. Repo guards cited: rg-002, rg-003, rg-005, rg-007, rg-015, rg-016; sr-004, sr-007.
