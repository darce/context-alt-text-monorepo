# E16-1. Bounded Iteration Caps

- **Date**: 2026-04-27
- **Author**: GPT-5.4
- **Project**: `prototype-wp-alt-context`
- **Task ID**: `E16-1`
- **Target Branch**: `feature/e16-1`
- **Review Coverage Target**: 2

> **Status**: Draft only. The E16 epic allocation has not landed yet, so this plan is a scoped draft for review and carry-forward, not an implementation-ready `/incremental-implementation` input. The previously referenced `docs/tasks/v0.5.0/...` draft was never committed; this file is the canonical replacement.

## Objective

Bound the highest-risk server-side iteration surfaces in the WordPress plugin and expose explicit envelope metadata where the admin SPA needs to distinguish complete lists from truncated partial views. The first implementation pass must stay narrow: pin one canary cluster-list path end to end, add the missing controller-edge caps, and define a reproducible legacy-roster migration fixture before broader rollout.

## Problem Statement

The refactoring assessment identifies bounded iteration as the top leverage reliability fix for the plugin: several controller and repository paths still depend on caller-supplied limits or unbounded `foreach` loops, while the SPA assumes list responses are complete because the current contract returns bare arrays. The earlier E16-1 draft was never persisted and the dashboard findings now point at a nonexistent `docs/tasks/v0.5.0/...` path, so the work has no canonical executable plan, no pinned canary file, and no reproducible proof bundle.

## Constraints

- Keep this plan in `Draft` until the E16 epic lands and assigns the final milestone/owning-epic metadata.
- Follow the assessment's bounded-iteration scope exactly: RX-3, RX-4, DB-1, DB-3, and DB-5 only. Do not expand this task into the unrelated MX-1 or CLI follow-ons.
- Treat the WordPress admin REST surface as greenfield for compatibility purposes: the SPA client, controller response, and tests must move together in the same slice rather than add compatibility shims.
- Do not reference nonexistent helper targets such as `make contracts-check`; every proof command in this plan must match a real repo surface.
- The legacy roster source is stored in WordPress options (`acx_roster_entries`, `acx_roster_assignments`), not in a legacy SQL table. Resume/chunking strategy must not assume a `legacy_updated_at` column that does not exist.

## Workflow Principles

- Put the cap at the boundary that accepts untrusted fan-in, then preserve the same bound in lower layers.
- When a list can be truncated, return the envelope triple `limit`, `total`, and `truncated` instead of relying on implied completeness.
- Canary the full path first: controller, repository, TS client, and RTL/PHP tests in one slice.
- Reuse an existing envelope pattern where the repo already has one instead of inventing a new response shape.

## Terminology

- **Envelope triple**: response metadata fields `limit`, `total`, and `truncated` returned alongside a list payload.
- **Canary list path**: the first end-to-end route used to prove the new bounded-list contract before applying it to other controllers.
- **Legacy roster fixture**: a seeded `acx_roster_entries` and `acx_roster_assignments` payload large enough to exercise chunked migration behavior during plugin activation.

## Current State Analysis

- `docs/assessments/refactoring-opportunities.md` names the in-scope anchors explicitly: RX-3 `class-media-detail-controller.php`, RX-4 `class-clusters-controller.php`, DB-1 `class-clusters-repository.php::merge_snapshot_for_tenant()`, DB-3 `class-identity-members-repository.php::list_for_cluster()`, and DB-5 `class-life-cycle-manager.php::migrate_legacy_roster_data()`.
- `apps/prototype-wp-alt-context/src/api/class-clusters-controller.php::list_clusters()` is the best canary because it already clamps `limit` at the controller edge, but still returns a bare `ClusterSummary[]` array and calls `ClustersRepository::list_for_tenant()` plus `IdentityMembersRepository::list_for_cluster()` with hidden repository defaults.
- `apps/prototype-wp-alt-context/js/admin/api/recognition/clusterApiQueries.ts::listRecognitionClusters()` and `js/admin/hooks/useRecognitionHooks.ts::useRecognitionClusters()` currently model `/recognition/clusters` as `Promise<ClusterSummary[]>`, so the SPA has no way to render a partial-state affordance when server-side truncation is intentional.
- `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx` is the live consumer of the cluster list and its existing RTL coverage sits in `js/admin/pages/__tests__/RosterPage.test.tsx`, making it the correct JS canary surface.
- `apps/prototype-wp-alt-context/src/api/class-media-detail-controller.php::resolve_media_ids()` accepts arbitrarily long `ids`/`ids[]` input with no typed cap and returns a bare `details_by_media` map.
- `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php::merge_snapshot_for_tenant()` loops over the entire incoming cluster snapshot row by row with no chunk/checkpoint boundary.
- `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php::migrate_legacy_roster_data()` reads legacy data from options, iterates the full entry set in one pass, and only guarantees legacy `id` plus `name`. The new `wp_acx_persons` schema has `updated_at`, but the legacy source does not.
- `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php::MULTIPART_MAX_IMAGES` is the canonical owner of the multipart image cap. `class-abstract-recognition-proxy-controller.php` is a breaker/passthrough base class, not the cap owner.
- `apps/prototype-wp-alt-context/js/admin/api/recognition/clusterApiQueries.ts::fetchTopUnlabeledClusters()` already normalizes an envelope payload (`clusters`, `singleton_count`, `data_source`, `projection_status`), so Slice 1 should mirror that style instead of inventing a one-off list contract.

## Target Outcome

E16-1 leaves the repo with one fully specified canary bounded-list contract and a precise rollout path for the remaining bounded-iteration surfaces. The cluster list path becomes the reference implementation for controller-edge cap constants, envelope metadata, TS client parsing, and SPA partial-state tests; media detail gets an explicit request cap; snapshot merge and legacy roster migration get concrete chunking plans with reproducible proof commands and fixture definitions.

## Context Loading

- Rules: `docs/agentic/rules/planning-review-guide.md`, `docs/agentic/rules/backend-php-guidelines.md`
- Assessment: `docs/assessments/refactoring-opportunities.md`
- Contracts: `docs/agentic/contracts/recognition-clustering.md`
- Code anchors:
  - `apps/prototype-wp-alt-context/src/api/class-clusters-controller.php`
  - `apps/prototype-wp-alt-context/src/api/class-media-detail-controller.php`
  - `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php`
  - `apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php`
  - `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php`
  - `apps/prototype-wp-alt-context/js/admin/api/recognition/clusterApiQueries.ts`
  - `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx`
- Existing proof surfaces:
  - `apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterPage.test.tsx`
  - `apps/prototype-wp-alt-context/js/admin/api/__tests__/snapshotContract.test.ts`
  - `apps/prototype-wp-alt-context/tests/Unit/ContractSnapshotSchemaTest.php`
- Handoff state: review findings `E16-1-PLAN-01` through `E16-1-PLAN-08` under task ref `SCOPE-v05-cross-cutting-20260427`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `GET /acx/v1/recognition/clusters` -> `listRecognitionClusters()` -> `RosterPage` | WP plugin + admin SPA | bare `ClusterSummary[]` array | return `{ clusters, limit, total, truncated }`, update TS query/parser, surface partial-state affordance in roster UI | No; greenfield admin client and controller change together | `npx vitest run js/admin/pages/__tests__/RosterPage.test.tsx` plus targeted PHP controller/unit coverage |
| `GET /acx/v1/recognition/media-details` | WP plugin | caller-controlled `ids` list, no typed ceiling | add explicit controller-edge cap and response metadata proving when a request was reduced | No; route is internal to the plugin UI | targeted PHPUnit for controller parsing and bounds behavior |
| Legacy roster activation path | plugin runtime | reads `acx_roster_entries` / `acx_roster_assignments` options in one pass | define chunk cursor based on legacy entry id or imported-person id, plus seeded fixture + loader workflow | N/A, local upgrade-only runtime path | `vendor/bin/phpunit tests/Unit/LifecycleManagerTest.php` plus LocalWP activation repro with seeded fixture |

## Proposed Solution

Deliver the work in four slices:

1. Establish the canary bounded-list contract on `ClustersController::list_clusters()` and the `RosterPage` consumer.
2. Add the missing controller-edge request cap for media detail reads.
3. Define chunk/checkpoint strategy for snapshot merge ingestion.
4. Define chunk/checkpoint strategy and reproducible fixture loading for legacy roster migration.

This remains intentionally narrower than a repo-wide bounded-iteration campaign. The canary slice proves the controller/repository/client/test pattern once; later E16 tasks can extend the same pattern to the rest of the assessment inventory.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| controller canary | `apps/prototype-wp-alt-context/src/api/class-clusters-controller.php` | pin `list_clusters()` as the first bounded-list endpoint and return envelope metadata instead of a bare array |
| repository canary | `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php` | define the cluster-list cap constant and chunk-aware list/merge behavior for `list_for_tenant()` and `merge_snapshot_for_tenant()` |
| member repository canary | `apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php` | replace the implicit `500` member limit with a named cap surfaced through the canary controller path |
| controller cap | `apps/prototype-wp-alt-context/src/api/class-media-detail-controller.php` | add a typed `MAX_MEDIA_IDS_PER_REQUEST` boundary and reject or truncate oversize requests explicitly |
| migration runtime | `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php` | introduce chunked legacy roster migration semantics that do not assume a legacy timestamp column |
| TS query/parser | `apps/prototype-wp-alt-context/js/admin/api/recognition/clusterApiQueries.ts` | parse the cluster envelope, mirroring the existing `fetchTopUnlabeledClusters()` style |
| TS types/hooks | `apps/prototype-wp-alt-context/js/admin/api/recognition/types/cluster.ts`, `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionHooks.ts` | replace bare-array list typing with a typed envelope and propagate metadata to consumers |
| SPA canary | `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx` | render a partial-state affordance when `truncated` is true |
| JS proof | `apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterPage.test.tsx` | add the canary RTL assertions for complete vs truncated cluster-list states |
| PHP proof | `apps/prototype-wp-alt-context/tests/Unit/LifecycleManagerTest.php` | add deterministic tests for chunked migration and fixture loading semantics |
| fixture tooling | `apps/prototype-wp-alt-context/tests/fixtures/legacy-roster/` and `apps/prototype-wp-alt-context/scripts/localwp/` | define the seeded legacy fixture and the loader command used by Slice 4 manual verification |

## Related Files

| File | Note |
| --- | --- |
| `docs/assessments/refactoring-opportunities.md` | Source of the RX-3 / RX-4 / DB-1 / DB-3 / DB-5 scope tags and the bounded-iteration priority ranking |
| `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php` | Canonical owner of `MULTIPART_MAX_IMAGES`; use this as the cap reference, not the abstract proxy controller |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/clusterApiQueries.ts` | `fetchTopUnlabeledClusters()` already demonstrates the envelope-normalization pattern Slice 1 should follow |
| `apps/prototype-wp-alt-context/js/admin/api/__tests__/snapshotContract.test.ts` | Existing exact Vitest proof surface; cite targeted test commands instead of a nonexistent `make contracts-check` target |
| `apps/prototype-wp-alt-context/tests/Unit/ContractSnapshotSchemaTest.php` | Existing exact PHPUnit proof surface for shared contract fixtures |
| `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php` | Confirms the legacy source is stored in options and that the new `wp_acx_persons` table, not the legacy payload, owns `updated_at` |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/__tests__/RosterPage.test.tsx js/admin/api/__tests__/snapshotContract.test.ts`
  - `cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit/LifecycleManagerTest.php tests/Unit/ContractSnapshotSchemaTest.php tests/Unit/ClustersControllerTest.php`
- Runtime-parity / environment checks:
  - `cd apps/prototype-wp-alt-context && npm run typecheck`
  - `cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit/LifecycleManagerTest.php --filter testLegacyRosterMigration`
- Contract / fixture verification:
  - Use the targeted snapshot tests above; do not reference `make contracts-check`.
  - If Slice 1 introduces a new cluster-list fixture, add it to the same targeted Vitest/PHPUnit command pair rather than inventing a new umbrella target.
- Manual verification:
  - Slice 4 adds `tests/fixtures/legacy-roster/seed-large-roster.json` containing at least `2 x MAX_LEGACY_ROSTER_BATCH_SIZE + 1` entries and a loader script `scripts/localwp/load-legacy-roster-fixture.php`.
  - LocalWP repro command after Slice 4 lands: `cd apps/prototype-wp-alt-context && php scripts/localwp/load-legacy-roster-fixture.php --wp-path "$WP_PATH" --fixture tests/fixtures/legacy-roster/seed-large-roster.json`
  - Then activate the plugin and confirm the migration completes with the expected person and cluster counts.

## Slice Delivery

### Slice 1: Canary Cluster List Envelope

**Goal**: prove the bounded-list contract on one real list route and one real SPA screen.

Changes:

- Pin `apps/prototype-wp-alt-context/src/api/class-clusters-controller.php::list_clusters()` as the canary controller.
- Replace the current bare array response with an envelope that includes `clusters`, `limit`, `total`, and `truncated`.
- Name the member cap used for preview identities in `IdentityMembersRepository::list_for_cluster()` instead of relying on the raw `500` default.
- Update `clusterApiQueries.ts`, cluster list types, `useRecognitionHooks.ts`, and `RosterPage.tsx` to parse and consume the envelope.
- Add a canary RTL test in `js/admin/pages/__tests__/RosterPage.test.tsx` that distinguishes complete from truncated cluster lists.

Proof:

- `cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/__tests__/RosterPage.test.tsx`
- `cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit/ClustersControllerTest.php`

### Slice 2: Media Detail Boundary Cap

**Goal**: eliminate the remaining caller-controlled media-id fan-in path.

Changes:

- Add a typed request ceiling to `MediaDetailController::resolve_media_ids()`.
- Return the canonical envelope triple `limit`, `total`, and `truncated` when the request exceeds the ceiling so the workbench detail path matches Slice 1's bounded-list contract.
- Align any plugin-side caller expectations so the UI can explain partial detail fetches instead of silently dropping ids.

Proof:

- `cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit/MediaDetailControllerTest.php`

### Slice 3: Snapshot Merge Checkpoints

**Goal**: define a bounded ingestion strategy for `merge_snapshot_for_tenant()` before it is extended to larger snapshots.

Changes:

- Introduce a named snapshot-batch size for `ClustersRepository::merge_snapshot_for_tenant()`.
- Record how chunk boundaries interact with `snapshot_version` and stale-row deletion so the merge remains idempotent.
- Keep the cluster-list canary contract as the only public response change in this task; Slice 3 stays repository-local.

Proof:

- `cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit/ContractSnapshotSchemaTest.php`
- Add or extend repository unit coverage for chunked merge semantics in the same suite.

### Slice 4: Legacy Roster Migration Fixture + Chunking

**Goal**: make the legacy migration path reproducible and free of nonexistent schema assumptions.

Changes:

- Replace the abandoned `(legacy_id, legacy_updated_at)` cursor idea with a cursor based on the legacy entry `id` (from the option payload) or the imported `wp_acx_persons.id`.
- Add a named legacy migration batch size to `migrate_legacy_roster_data()`.
- Create `tests/fixtures/legacy-roster/seed-large-roster.json` with at least `2 x MAX_LEGACY_ROSTER_BATCH_SIZE + 1` entries plus matching assignments so chunk rollover is exercised.
- Add `scripts/localwp/load-legacy-roster-fixture.php` to seed the two legacy options exactly as the migration reads them.
- Document the manual LocalWP activation flow using that loader instead of an undefined "seeded legacy fixture" placeholder.

Proof:

- `cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit/LifecycleManagerTest.php`
- `cd apps/prototype-wp-alt-context && php scripts/localwp/load-legacy-roster-fixture.php --wp-path "$WP_PATH" --fixture tests/fixtures/legacy-roster/seed-large-roster.json`
- Activate the plugin and verify the migrated counts match the fixture.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the assessment, PHP rules, clustering contract, and open MCP planning findings before editing.
- [ ] Kept the task in Draft until the E16 epic allocation lands.
- [ ] Confirmed the cluster list is the canary public boundary and the legacy migration remains runtime-local.

### Checklist for Slice 1: Canary Cluster List Envelope

- [ ] `class-clusters-controller.php::list_clusters()` is the pinned canary controller.
- [ ] `class-clusters-repository.php::list_for_tenant()` and `class-identity-members-repository.php::list_for_cluster()` use named bounds rather than hidden numeric defaults.
- [ ] `clusterApiQueries.ts`, cluster types, `useRecognitionHooks.ts`, and `RosterPage.tsx` consume the new envelope in the same slice.
- [ ] `js/admin/pages/__tests__/RosterPage.test.tsx` proves complete vs truncated list rendering.

### Checklist for Slice 2: Media Detail Boundary Cap

- [ ] `class-media-detail-controller.php::resolve_media_ids()` has a typed request ceiling.
- [ ] Oversize requests return explicit behavior rather than silent unbounded iteration.
- [ ] PHPUnit coverage proves the cap.

### Checklist for Slice 3: Snapshot Merge Checkpoints

- [ ] `merge_snapshot_for_tenant()` has a named chunk/checkpoint strategy.
- [ ] Snapshot-version semantics remain idempotent across chunk boundaries.
- [ ] Repository proof runs in the targeted PHP suite.

### Checklist for Slice 4: Legacy Roster Migration Fixture + Chunking

- [ ] The migration cursor does not assume `legacy_updated_at`.
- [ ] The seeded fixture shape, row count, and loader command are defined in-repo.
- [ ] `LifecycleManagerTest.php` and the LocalWP repro both exercise chunk rollover.

## Review Readiness

- [ ] No slice references a nonexistent command or missing fixture.
- [ ] Public response changes name the exact TS and PHP consumers updated in the same slice.
- [ ] The canary JS proof covers the partial-state affordance, not just the happy path.
- [ ] Handoff decisions record the draft-to-ready transition only after the E16 epic allocation lands.

## Stretch Goals

- [ ] Extend the same envelope pattern to `get_cluster_members()` once Slice 1 proves the contract and UI affordance.
- [ ] Add a shared schema or golden fixture for cluster-list envelopes if later E16 tasks need cross-language reuse beyond the WP plugin boundary.

## Success Criteria

- [ ] The repo has a canonical E16-1 draft at `docs/tasks/16.0/E16-1-bounded-iteration-caps-task-plan.md` instead of an orphan dashboard reference to `docs/tasks/v0.5.0/...`.
- [ ] The plan explicitly enumerates RX-3, RX-4, DB-1, DB-3, and DB-5 with pinned file/method anchors.
- [ ] The canary controller, SPA proof file, contract proof commands, and legacy fixture loader are all named concretely.
- [ ] The draft remains honestly blocked on E16 epic allocation while still being implementation-ready in every other respect.
