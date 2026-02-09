# Prototype WP Alt Context Web Deployment Cleanup Plan (v4.13.0)

## Problem Statement

`prototype-wp-alt-context` is approaching web deployment and needs a focused cleanup pass to remove dead paths, reduce maintenance risk, and harden verification gates. Current checks are mostly green, but several deployment-relevant gaps remain (including a non-runnable PHP code-style gate and candidate orphaned runtime surfaces).

This document defines a whole-app cleanup plan using the `branch-review-guide.md` taxonomy and severity model, seeds initial findings, and specifies phased remediation and validation criteria.

## Scope

This plan covers the full application at:

- `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context`

Scope policy:

1. Whole-app audit for deployment hardening (not diff-only).
2. Findings classified using `ANTIPATTERN`, `DEAD_CODE`, `COMPLEXITY`, and `GAP`.
3. Severity classified as `HIGH`, `MEDIUM`, and `LOW` per `/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/rules/branch-review-guide.md`.
4. This document is planning-only; implementation happens in follow-up execution work.

## Audit Method (Branch Review Guide Alignment)

Audit workflow:

1. Run automated gates first and capture exact outcomes.
2. Apply manual branch-review checklist concepts to `prototype-wp-alt-context` with deployment focus:
   1. dead routes/endpoints and config keys;
   2. unused placeholders and compatibility shims;
   3. non-runnable or misleading quality gates;
   4. tracked debug artifacts that should not ship.
3. Classify each finding with:
   1. severity (`HIGH`, `MEDIUM`, `LOW`);
   2. category (`ANTIPATTERN`, `DEAD_CODE`, `COMPLEXITY`, `GAP`);
   3. file-level evidence with line references when available.
4. Define phased remediation order:
   1. reliability first;
   2. dead-path reduction second;
   3. low-risk cleanup third;
   4. test debt closure fourth;
   5. full re-audit fifth.

## Automated Baseline (2026-02-09)

| Check                                                                                                          | Result                                          |
| -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| `npm run typecheck` (from `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context`) | pass                                            |
| `npm run lint`                                                                                                 | pass                                            |
| `npm run arch`                                                                                                 | pass                                            |
| `npm run test -- --run`                                                                                        | pass (`29` files, `138` tests passed, `3` todo) |
| `composer test`                                                                                                | pass (`41` tests, `102` assertions)             |
| `npx tsc --noEmit --project tsconfig.type-check.json --noUnusedLocals --noUnusedParameters`                    | pass (no unused TS locals/params reported)      |
| `composer cs-check`                                                                                            | fail (script misconfigured: no target paths)    |

## Seeded Findings (ANTIPATTERN / DEAD_CODE / COMPLEXITY / GAP)

| ID  | Severity | Category    | Finding                                                              | Evidence                                                                                                                                                                                                                                                                                                                                                                                |
| --- | -------- | ----------- | -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| H-1 | HIGH     | GAP         | PHP code-style gate is non-runnable via composer script              | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/composer.json:32` (`cs-check` missing file targets)                                                                                                                                                                                                                                                  |
| M-1 | MEDIUM   | DEAD_CODE   | Frontend service path appears unused/placeholder                     | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/class-alt-context.php:16`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/class-alt-context.php:35`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/frontend/class-frontend.php:7`                               |
| M-2 | MEDIUM   | DEAD_CODE   | Training-stage endpoint/key/style surface has no runtime consumer    | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-admin.php:203`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:787`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/styles/components/_workbench.scss:392` |
| M-3 | MEDIUM   | DEAD_CODE   | Recover-orphans route appears orphaned (no frontend caller)          | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:253`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:641`                                                                                                                      |
| M-4 | MEDIUM   | DEAD_CODE   | Deprecated compatibility re-export appears unused outside tests      | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/workbench/IdentityClusterList.tsx:1`                                                                                                                                                                                                                                                  |
| M-5 | MEDIUM   | DEAD_CODE   | Tracked debug artifacts should not ship in deployment-focused branch | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/test_output.txt`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/test_output_debug.txt`                                                                                                                                                                          |
| L-1 | LOW      | DEAD_CODE   | Unused parameter in batch-limits trait (explicitly marked unused)    | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/support/trait-batch-limits.php:36`                                                                                                                                                                                                                                                               |
| L-2 | LOW      | ANTIPATTERN | Redundant boolean condition in workbench render path                 | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx:290`                                                                                                                                                                                                                                                                |
| L-3 | LOW      | GAP         | Test placeholders remain for key user flows                          | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterPage.test.tsx:150`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/__tests__/WorkbenchPage.test.tsx:77`                                                                                                            |

## Cleanup Implementation Phases

### Phase 1: Fix audit/tooling reliability

1. Make `composer cs-check` runnable by targeting explicit paths (`src`, `tests`, `alt-context.php`).
2. Confirm updated script fails only on true violations, not invocation errors.
3. Record the command contract in project docs for repeatable branch review.

### Phase 2: Remove or justify dead runtime surfaces

1. Validate whether `/src/frontend/class-frontend.php` should be wired or removed.
2. Audit `recognitionTrainingStage` endpoint key and `/recognition/training-stage` route for active consumers.
3. Audit `/recognition/clusters/recover-orphans` route for active consumers.
4. Remove unused surfaces or mark with explicit deprecation plan and owner.

### Phase 3: Remove deployment-noise artifacts and low-risk anti-patterns

1. Remove or relocate tracked debug outputs (`test_output*.txt`).
2. Resolve low-risk dead/antipattern items (`L-1`, `L-2`) without behavioral changes.
3. Re-run static checks after each cleanup cluster.

### Phase 4: Close test TODOs or convert to tracked issues with references

1. Implement pending test scenarios where feasible.
2. If deferred, replace `todo` placeholders with issue-linked rationale.
3. Prevent silent test debt growth by documenting allowed TODO policy.

### Phase 5: Re-run gates and publish post-cleanup findings delta

1. Re-run full gate set from this plan.
2. Reclassify findings and compare pre/post counts by severity/category.
3. Publish a concise cleanup delta report in `docs/tasks/4.0/4.13.0/`.

## Functions and Files to Change

| File                                                                                                                                 | Line          | Planned Change                                                                                                     |
| ------------------------------------------------------------------------------------------------------------------------------------ | ------------- | ------------------------------------------------------------------------------------------------------------------ |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/composer.json`                                    | 32            | Fix `cs-check` script to include explicit scan targets.                                                            |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/class-alt-context.php`                        | 16, 35        | Decide keep/remove wiring for `Frontend` service path based on consumer audit.                                     |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/frontend/class-frontend.php`                  | 7             | Remove placeholder class or implement real responsibilities and wiring.                                            |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-admin.php`                        | 203           | Remove or retain `recognitionTrainingStage` endpoint key based on compatibility decision.                          |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php`         | 253, 641, 787 | Mark candidate deprecations (`training-stage`, `recover-orphans`) and remove only after compatibility checks pass. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/workbench/IdentityClusterList.tsx` | 1             | Remove compatibility re-export when import audit proves no consumers.                                              |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx`                 | 290           | Remove redundant duplicated condition in render expression.                                                        |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterPage.test.tsx`     | 150           | Implement TODO test or replace with issue-linked deferral.                                                         |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/__tests__/WorkbenchPage.test.tsx`  | 77            | Implement TODO tests or replace with issue-linked deferral.                                                        |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/test_output.txt`                                  | n/a           | Remove tracked debug artifact from deploy-focused branch.                                                          |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/test_output_debug.txt`                            | n/a           | Remove tracked debug artifact from deploy-focused branch.                                                          |

## Public API and Compatibility Notes

1. `AltContextAdmin.endpoints` contract may change by removing `recognitionTrainingStage` if confirmed unused.
2. REST routes `/acx/v1/recognition/training-stage` and `/acx/v1/recognition/clusters/recover-orphans` are candidate deprecations; do not remove until `rg` + tests + contract review confirm no consumers.
3. Compatibility re-export at `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/workbench/IdentityClusterList.tsx` is a candidate removal after import audit.

## Validation and Exit Criteria

Validation scenarios:

1. Tooling scenario: `composer cs-check` runs successfully and exits `0`.
2. Static scenario: `npm run typecheck`, `npm run lint`, `npm run arch` all pass after cleanup.
3. Runtime scenario: `npm run test -- --run` and `composer test` remain green.
4. Contract scenario: endpoint-key removals do not break `getEndpoint(...)` calls.
5. Dead-code scenario: removed files/surfaces have zero references via `rg`.

Assumptions and defaults:

1. Scope is the full app at `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context` (not diff-only).
2. The document includes both process and seeded findings in this first pass.
3. `branch-review-guide.md` categories and severity model are required.
4. This pass produces the planning artifact only; code cleanup implementation is follow-up.

## Admin Directory Audit Addendum (2026-02-09)

Audit scope for this addendum:

- `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-admin.php`
- `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-menu.php`
- `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-abstract-spa-page.php`
- `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-dashboard-page.php`
- `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-workbench-page.php`
- `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-roster-page.php`

### Findings Summary

| Severity | Count |
| -------- | ----- |
| HIGH     | 1     |
| MEDIUM   | 2     |
| LOW      | 1     |
| Total    | 4     |

### Admin Findings

| ID   | Severity | Category  | Finding                                                                                                                              | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Recommended Action                                                                                                                 |
| ---- | -------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| A-H1 | HIGH     | GAP       | Admin SPA bootstrap can fail silently when production manifest/build assets are missing or unreadable.                               | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-admin.php:73`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-admin.php:125`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-admin.php:155`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-admin.php:161`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-admin.php:76` | Add explicit failure reporting (admin notice + log), and avoid localizing script config when no script handle is enqueued.         |
| A-M1 | MEDIUM   | DEAD_CODE | `alt-context-settings` is allow-listed for asset enqueue but no settings menu/page is registered.                                    | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-admin.php:50`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-menu.php:27`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-menu.php:37`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-menu.php:46`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-menu.php:55`        | Remove the slug from `SUPPORTED_PAGE_SLUGS` or implement/register a real settings page callback and route.                         |
| A-M2 | MEDIUM   | GAP       | Admin asset/menu wiring has limited regression coverage; tests currently exercise tier normalization but not enqueue/menu behaviors. | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/tests/Unit/AdminTest.php:29`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/tests/Unit/AdminTest.php:66`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/tests/Unit/AdminTest.php:91`                                                                                                                                                                                                                                           | Add unit tests for `enqueue_scripts` build/dev flows, manifest-missing behavior, supported-page detection, and menu registrations. |
| A-L1 | LOW      | DEAD_CODE | Unused function imports in `class-admin.php` add noise and drift risk.                                                               | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-admin.php:9`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-admin.php:11`                                                                                                                                                                                                                                                                                                                                                           | Remove unused imports (`absint`, `apply_filters`) during cleanup.                                                                  |

### Phase Mapping Delta

1. Phase 1 should include `A-H1` (fail-fast admin bootstrap diagnostics for missing manifest/assets).
2. Phase 2 should include `A-M1` (settings slug dead-path decision).
3. Phase 3 should include `A-L1` (unused import cleanup in admin code).
4. Phase 4 should include `A-M2` (admin enqueue/menu regression coverage).

## API / Frontend / Support / Core Audit Addendum (2026-02-09)

Audit scope for this addendum:

- `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-api.php`
- `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php`
- `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/frontend/class-frontend.php`
- `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php`
- `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/support/trait-batch-limits.php`
- `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/class-alt-context.php`

### Findings Summary

| Severity | Count |
| -------- | ----- |
| HIGH     | 0     |
| MEDIUM   | 5     |
| LOW      | 2     |
| Total    | 7     |

### API/Frontend/Support/Core Findings

| ID     | Severity | Category    | Finding                                                                                                                                                                                                                                                                                                                                                                                           | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | Recommended Action                                                                                                                                                                                                                                                       |
| ------ | -------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------- | --------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| AFS-M1 | MEDIUM   | DEAD_CODE   | Frontend service remains instantiated/injected but has no runtime behavior or init wiring.                                                                                                                                                                                                                                                                                                        | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/alt-context.php:107`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/class-alt-context.php:16`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/class-alt-context.php:35`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/frontend/class-frontend.php:7`                                                                                                       | Either remove `Frontend` from construction/wiring or implement and initialize explicit frontend responsibilities in `AltContext::init()`.                                                                                                                                |
| AFS-M2 | MEDIUM   | DEAD_CODE   | `recover-orphans` route appears orphaned from the admin runtime surface.                                                                                                                                                                                                                                                                                                                          | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:253`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:641`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:646`; `rg "recover-orphans" /Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin` -> no matches                                    | Keep as candidate deprecation until contract + backend consumer review is complete, then remove route and proxy method if confirmed unused.                                                                                                                              |
| AFS-M3 | MEDIUM   | GAP         | Cluster-events real-time path is incomplete: backend emits heartbeat pings, but frontend subscription hook is not wired into runtime components.                                                                                                                                                                                                                                                  | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:761`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:764`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/useClusterEvents.ts:17`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterList.test.tsx:235` | Decide a single direction: wire `useClusterEvents` in production pages with domain events, or deprecate/remove cluster-events endpoint key + hook.                                                                                                                       |
| AFS-M4 | MEDIUM   | COMPLEXITY  | `RecognitionController` is a monolithic 1,288-line class combining route registration, transport proxying, SSE, and response transformations.                                                                                                                                                                                                                                                     | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:46`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:732`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:964`; `wc -l` shows `1288` lines                                                                                                                                          | Split into focused controllers/services (jobs, clusters, media identities, stream endpoints) with narrower unit-test targets.                                                                                                                                            |
| AFS-M5 | MEDIUM   | GAP         | `LifecycleManager::uninstall()` only deletes two options (`alt_context_version`, `alt_context_installed`) and has no table drop logic. When sovereign cluster tables (`wp_acx_clusters`, `wp_acx_identity_members`, `wp_acx_sync_state`) are added per the v0.1.0 roadmap, uninstall will leave orphaned tables behind. The table cleanup contract must be established before tables are created. | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php:43`; `LifecycleManager::uninstall()` only calls `delete_option()` + `flush_rewrite_rules()` — no `$wpdb->query("DROP TABLE IF EXISTS ...")`                                                                                                                                                                                                                                                                                                  | Add a `drop_tables()` method to `LifecycleManager::uninstall()` (gated behind a confirmation constant or admin action) that drops all plugin-owned tables. Implement alongside `dbDelta()` table creation in sovereign roadmap Phase 1 to keep create/destroy symmetric. |
| AFS-L1 | LOW      | ANTIPATTERN | `include_debug` forwarding relies on truthy string checks, so values like `'false'` are still treated as enabled.                                                                                                                                                                                                                                                                                 | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:275`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:988`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:989`                                                                                                                                                                     | Parse with `rest_sanitize_boolean` and forward only on explicit true.                                                                                                                                                                                                    |
| AFS-L2 | LOW      | GAP         | Route-level tests do not currently cover training-stage, recover-orphans, cluster-events stream, or include-debug parsing behavior.                                                                                                                                                                                                                                                               | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/tests/Unit/RecognitionControllerTest.php:12`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/tests/Unit/ProxyRequestTest.php:13`; `rg "training-stage                                                                                                                                                                                                                                                                                             | recover-orphans                                                                                                                                                                                                                                                          | stream_cluster_events | include_debug" /Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/tests` -> no matches | Add focused unit tests for these route handlers and query-param handling before deployment hardening sign-off. |

### Phase Mapping Delta

1. Phase 2 should include `AFS-M1`, `AFS-M2`, and `AFS-M3` (dead/incomplete runtime surface decisions).
2. Phase 3 should include `AFS-M4` and `AFS-L1` (controller decomposition and low-risk param parsing cleanup). **Sovereign roadmap dependency:** AFS-M4 (controller decomposition) is a prerequisite for sovereign roadmap Phase 2 (read-path flip) and Phase 4 (local service facade replacing proxy). Do not defer AFS-M4 past the start of sovereign cluster work.
3. Phase 1 (sovereign roadmap) should include `AFS-M5` (table cleanup contract in `LifecycleManager::uninstall()`) — implement alongside `dbDelta()` table creation to keep create/destroy symmetric.
4. Phase 4 should include `AFS-L2` (route-level regression coverage for currently untested surfaces).

## Hooks Directory Audit Addendum (2026-02-09)

Audit scope for this addendum:

- `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/`

### Findings Summary

| Severity | Count |
| -------- | ----- |
| HIGH     | 0     |
| MEDIUM   | 5     |
| LOW      | 2     |
| Total    | 7     |

### Hook Findings

| ID    | Severity | Category    | Finding                                                                                                                              | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                | Recommended Action                                                                                                                                   |
| ----- | -------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| HK-M1 | MEDIUM   | DEAD_CODE   | `useClusterEvents` remains effectively orphaned in runtime code paths.                                                               | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/useClusterEvents.ts:17`; `rg "useClusterEvents" /Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin` only returns the hook definition and a test comment (`.../js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx:43`)                                                            | Either wire `useClusterEvents` into the workbench runtime flow or remove/deprecate the hook and related endpoint key.                                |
| HK-M2 | MEDIUM   | DEAD_CODE   | Multi-job status wiring exists but is inert in the state machine call path.                                                          | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachine.ts:93` passes `[]` into `useCombinedScanStatus`; `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionHooks.ts:84`; `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionHooks.ts:89`        | Either pass real `activeJobIds` and consume `multiScanStatus`, or remove the dead multi-status plumbing.                                             |
| HK-M3 | MEDIUM   | GAP         | `useJobCoordination` assumes `crypto.randomUUID` and `BroadcastChannel` are always available, with no runtime fallback.              | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/useJobCoordination.ts:34`; `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/useJobCoordination.ts:51`; tests always provide mocks at `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useJobCoordination.test.ts:19`      | Add capability guards and degrade gracefully to single-tab primary mode when coordination primitives are unavailable.                                |
| HK-M4 | MEDIUM   | ANTIPATTERN | `useWorkbenchMedia` embeds REST transport/parsing instead of routing through a dedicated API module/shared transport helper.         | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/useWorkbenchMedia.ts:42`; `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/useWorkbenchMedia.ts:55`                                                                                                                                                                                  | Extract media-list fetch into `js/admin/api` and use shared request/error handling semantics.                                                        |
| HK-M5 | MEDIUM   | GAP         | Active-job persistence expires entries purely by age (1 hour), which can drop long-running jobs from recovery tracking after reload. | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/useJobPersistence.ts:35`; `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/useJobPersistence.ts:54`                                                                                                                                                                                  | Use terminal job status (or a longer configurable threshold) before purging persisted jobs.                                                          |
| HK-L1 | LOW      | DEAD_CODE   | `clearSelection` is exported by `useMediaSelectionState` but not consumed in the runtime page integration.                           | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/useMediaSelectionState.ts:74`; `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/useMediaSelectionState.ts:85`; `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx:110`                                              | Remove the unused action from the hook contract or explicitly invoke it in selection-reset flows.                                                    |
| HK-L2 | LOW      | GAP         | Hook test coverage does not currently exercise unsupported-browser/storage-failure paths for deployment hardening.                   | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useJobCoordination.test.ts:19`; `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useJobPersistence.test.ts:21`; `rg "useClusterEvents" /Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/__tests__` -> no matches | Add failure-path tests for missing `BroadcastChannel`, missing `crypto.randomUUID`, storage write failures, and cluster-event subscription behavior. |

### Phase Mapping Delta

1. Phase 2 should include `HK-M1`, `HK-M2`, and `HK-L1` (dead hook/runtime surface cleanup).
2. Phase 3 should include `HK-M3`, `HK-M4`, and `HK-M5` (deployment hardening and transport consistency).
3. Phase 4 should include `HK-L2` (hook-level failure-path regression coverage).

## Recognition API Directory Audit Addendum (2026-02-09)

Audit scope for this addendum:

- `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/`

### Findings Summary

| Severity | Count |
| -------- | ----- |
| HIGH     | 0     |
| MEDIUM   | 4     |
| LOW      | 3     |
| Total    | 7     |

### Recognition API Findings

| ID     | Severity | Category  | Finding                                                                                                                                                               | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Recommended Action                                                                                                                                      |
| ------ | -------- | --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RAP-M1 | MEDIUM   | GAP       | Root recognition API barrel is incomplete, forcing deep imports and an inconsistent public API boundary.                                                              | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/index.ts:49`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/TopClustersSection.tsx:15`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/clusterApi.ts:15`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/clusterApi.ts:25`                                            | Export `dismissCluster` and `fetchTopUnlabeledClusters` from `api/recognition/index.ts`, then remove deep `clusterApi` imports from runtime components. |
| RAP-M2 | MEDIUM   | DEAD_CODE | Several exported recognition operations have no consumers outside the module/barrel layer.                                                                            | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/clusterApiMutations.ts:62`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/clusterApiMutations.ts:139`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/clusterApiMembers.ts:6`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/clusterApiQueries.ts:41`; `rg -n "\\b(reassignClusterFace | undismissCluster                                                                                                                                        | pinRepresentative                                                                                               | fetchClusterLabels)\\b" /Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context` returns only recognition API files   | Remove `reassignClusterFace`, `pinRepresentative`, and `fetchClusterLabels`. **Retain `undismissCluster`** with an explicit TODO linked to sovereign roadmap Phase 3 (local-first writes) — the curation-first conflict policy requires a "reverse dismissal" action for user curation state management. |
| RAP-M3 | MEDIUM   | DEAD_CODE | `clusterAdapter` conversion helpers are currently orphaned.                                                                                                           | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/adapters/clusterAdapter.ts:24`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/adapters/clusterAdapter.ts:38`; `rg -n "\\b(toClusterGroup                                                                                                                                                                                                                                                                          | toDetectedIdentity)\\b" /Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context` returns only this adapter file               | Either delete the adapter module or adopt it as the canonical API→UI mapping boundary and add call sites/tests. |
| RAP-M4 | MEDIUM   | GAP       | `TopUnlabeledCluster` representative typing is narrower than runtime payload variants (legacy key + nullable thumb URL), causing cast-based workarounds in consumers. | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/types/cluster.ts:36`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/TopClustersSection.tsx:34`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:705`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:722`                              | Broaden API types to match payload reality (`thumb_url?: string                                                                                         | null`, optional `thumbnail_url?: string                                                                         | null`) and normalize once in API layer instead of casting in UI.                                                                                |
| RAP-L1 | LOW      | DEAD_CODE | Exported constraint/representative interfaces appear unused in current plugin code paths.                                                                             | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/types/constraint.ts:2`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/types/constraint.ts:14`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/types/cluster.ts:145`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/types/cluster.ts:153`; `rg -n "\\b(IdentityConstraint               | CreateConstraintsRequest                                                                                                                                | ClusterRepresentative                                                                                           | PinRepresentativeRequest)\\b" /Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context` returns type declarations only | Remove stale interfaces or move them behind issue-linked TODOs tied to concrete endpoints/features.                                                                                                                                                                                                      |
| RAP-L2 | LOW      | DEAD_CODE | Scan batching utility computes tenant tier metadata that is not consumed by batching logic.                                                                           | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/scanApi.ts:13`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/scanApi.ts:25`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/scanApi.ts:29`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/scanApi.ts:61`                                                                              | Remove unused `tier` plumbing from `TenantLimits` or wire tier into explicit behavior/telemetry.                                                        |
| RAP-L3 | LOW      | GAP       | Direct recognition API unit coverage is narrow relative to the current exported surface.                                                                              | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/__tests__/recognitionApi.test.ts:4`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/__tests__/recognitionApi.test.ts:11`; mappers are only referenced by implementation at `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/recognition/identityQueriesApi.ts:14` and have no direct tests                                                                                                  | Add focused tests for mapper fallback shapes, deep-imported cluster surfaces, and any retained operations after dead-code cleanup.                      |

### Phase Mapping Delta

1. Phase 2 should include `RAP-M2`, `RAP-M3`, `RAP-L1`, and `RAP-L2` (dead API surface reduction).
2. Phase 3 should include `RAP-M1` and `RAP-M4` (API contract hardening and boundary cleanup).
3. Phase 4 should include `RAP-L3` (targeted recognition API regression coverage).

## Pages Directory Audit Addendum (2026-02-09)

Audit scope for this addendum:

- `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/`

### Findings Summary

| Severity | Count |
| -------- | ----- |
| HIGH     | 0     |
| MEDIUM   | 3     |
| LOW      | 2     |
| Total    | 5     |

### Pages Findings

| ID     | Severity | Category    | Finding                                                                                                                                                             | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Recommended Action                                                                                                                                       |
| ------ | -------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PAG-M1 | MEDIUM   | GAP         | Page/workbench links build `wp-admin` URLs from `window.location.origin`, which is brittle for non-root or rewritten admin installs.                                | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx:234`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx:237`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterDrawerPanel.tsx:153`                                                                                                                                                                                                                                            | Localize canonical admin URLs from PHP (or expose a typed config helper) and consume those links in pages instead of reconstructing with browser origin. |
| PAG-M2 | MEDIUM   | ANTIPATTERN | `pages/roster/utils/mediaMeta.ts` performs direct REST transport and custom nonce/base plumbing in the pages layer instead of using shared API transport utilities. | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/roster/utils/mediaMeta.ts:26`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/roster/utils/mediaMeta.ts:53`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/roster/hooks/useClusterMediaMap.ts:4`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/api/rosterApi.ts:1`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/utils/http.ts:29` | Move media metadata fetch into `js/admin/api/` and route calls through shared HTTP helpers to keep request/error/nonce behavior consistent.              |
| PAG-M3 | MEDIUM   | GAP         | Roster route-container behavior is not directly tested; current page tests target re-exported child components instead of rendering `RosterPage`.                   | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterPage.test.tsx:3`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterEntries.test.tsx:3`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:21`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/App.tsx:29`; `rg "render\\(<RosterPage                                                                                                       | <RosterPage\\s\*/>" /Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages` -> no matches                      | Add an integration-style `RosterPage` test that exercises tab selection, query-param tab bootstrapping, and cluster drawer open/close behavior. |
| PAG-L1 | LOW      | DEAD_CODE   | `RosterPage` compatibility re-exports are effectively test-only surface and expand public exports without runtime consumers.                                        | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:228`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:229`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterPage.test.tsx:3`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterEntries.test.tsx:3`                                                                                                                   | Remove these exports after migrating tests to import from canonical component modules (`./roster/*`) or keep behind explicit deprecation notes.          |
| PAG-L2 | LOW      | GAP         | Page-level test TODO placeholders remain unresolved for roster commit and workbench follow-up flows.                                                                | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterPage.test.tsx:150`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/__tests__/WorkbenchPage.test.tsx:77`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/__tests__/WorkbenchPage.test.tsx:78`                                                                                                                                                                                                                      | Implement these tests or replace each placeholder with issue-linked, time-bounded deferrals before deployment sign-off.                                  |

### Phase Mapping Delta

1. Phase 2 should include `PAG-L1` (test-only page export surface cleanup).
2. Phase 3 should include `PAG-M1` and `PAG-M2` (URL/build hardening and API-boundary cleanup in pages).
3. Phase 4 should include `PAG-M3` and `PAG-L2` (route-level page coverage and TODO closure).

---

# Consolidated Checklist

## Phase 1: Fix Audit/Tooling Reliability

- [ ] Update `composer cs-check` to include explicit target paths.
- [ ] Verify `composer cs-check` executes and returns a meaningful result.
- [ ] Document tool invocation contract for repeatable audits.

## Phase 2: Remove or Justify Dead Runtime Surfaces

- [ ] Decide keep/remove strategy for `/src/frontend/class-frontend.php`.
- [ ] Confirm consumer status for `recognitionTrainingStage` and `/recognition/training-stage`.
- [ ] Confirm consumer status for `/recognition/clusters/recover-orphans`.
- [ ] Remove unused surfaces or add explicit deprecation records.
- [ ] Resolve `AFS-M1`: remove unused frontend dependency wiring or implement and initialize it.
- [ ] Resolve `AFS-M2`: deprecate/remove `recover-orphans` route surface if consumer audit stays empty.
- [ ] Resolve `AFS-M3`: either wire live cluster events in production runtime or remove/deprecate cluster-events surface.
- [ ] Resolve `HK-M1`: wire or remove `useClusterEvents` runtime surface.
- [ ] Resolve `HK-M2`: remove inert multi-status path or connect it to real active job IDs.
- [ ] Resolve `HK-L1`: remove unused `clearSelection` export or make it part of runtime selection-reset flow.
- [ ] Resolve `RAP-M2`: remove `reassignClusterFace`, `pinRepresentative`, `fetchClusterLabels`; retain `undismissCluster` with TODO linked to sovereign roadmap Phase 3 (local-first curation reversal).
- [ ] Resolve `RAP-M3`: remove or integrate the orphaned `clusterAdapter` mapping layer.
- [ ] Resolve `RAP-L1`: prune unused recognition type exports in `types/constraint.ts` and `types/cluster.ts`.
- [ ] Resolve `RAP-L2`: remove unused tier metadata in scan batching utility or wire it into real behavior.
- [ ] Resolve `PAG-L1`: remove `RosterPage` test-only compatibility re-exports or keep only with explicit deprecation intent.

## Phase 3: Remove Deployment-Noise Artifacts and Low-Risk Anti-Patterns

- [ ] Remove tracked debug artifacts (`test_output.txt`, `test_output_debug.txt`) or relocate them outside tracked deploy paths.
- [ ] Resolve redundant render condition in `WorkbenchPage.tsx`.
- [ ] Resolve unused-parameter dead code in `trait-batch-limits.php` without behavior regression.
- [ ] Resolve `AFS-M4`: split `RecognitionController` into smaller focused units. **Sovereign roadmap dependency:** this decomposition is a prerequisite for roadmap Phase 2 (read-path flip) and Phase 4 (local service facade). Do not defer past sovereign cluster work start.
- [ ] Resolve `AFS-M5`: add `drop_tables()` to `LifecycleManager::uninstall()` — implement alongside `dbDelta()` table creation in sovereign roadmap Phase 1 to keep create/destroy symmetric.
- [ ] Resolve `AFS-L1`: normalize `include_debug` parsing to strict boolean behavior.
- [ ] Resolve `HK-M3`: add browser-capability fallback in `useJobCoordination`.
- [ ] Resolve `HK-M4`: move workbench media transport into a dedicated API module with shared request semantics.
- [ ] Resolve `HK-M5`: avoid age-only purge for persisted active jobs.
- [ ] Resolve `RAP-M1`: align `api/recognition/index.ts` exports and remove deep `clusterApi` imports from runtime code.
- [ ] Resolve `RAP-M4`: normalize top-unlabeled representative typing/payload mapping (`thumb_url` + legacy `thumbnail_url`).
- [ ] Resolve `PAG-M1`: replace origin-derived `wp-admin` URL construction with localized/admin-configured links.
- [ ] Resolve `PAG-M2`: move roster media metadata REST calls out of `pages/` into `js/admin/api/` shared transport.

## Phase 4: Resolve Test Placeholder Debt

- [ ] Implement `it.todo` coverage for roster commit flow.
- [ ] Implement `test.todo` coverage for workbench follow-up flows.
- [ ] If any TODO remains, replace with issue-linked tracked deferral.
- [ ] Resolve `AFS-L2`: add route tests for training-stage/recover-orphans/cluster-events and include-debug parsing.
- [ ] Resolve `HK-L2`: add hook failure-path tests for coordination/storage and add `useClusterEvents` coverage.
- [ ] Resolve `RAP-L3`: expand direct recognition API tests for mappers and retained cluster operations.
- [ ] Resolve `PAG-M3`: add direct `RosterPage` route-container tests (tab bootstrapping and drawer flows).
- [ ] Resolve `PAG-L2`: close page-level TODO placeholders or convert each to issue-linked deferral.

## Phase 5: Re-Audit and Publish Delta

- [ ] Re-run all baseline checks from this document.
- [ ] Reclassify findings and capture post-cleanup severity/category counts.
- [ ] Publish a post-cleanup findings delta note in `docs/tasks/4.0/4.13.0/`.

## Success Criteria

- [ ] Zero HIGH findings remain.
- [ ] All mandatory quality gates are runnable and reproducible.
- [ ] No confirmed orphaned runtime surfaces remain without explicit deprecation notes.
- [ ] Deployment-focused branch contains no tracked debug artifacts.
- [ ] Post-cleanup audit confirms no regressions from baseline.
