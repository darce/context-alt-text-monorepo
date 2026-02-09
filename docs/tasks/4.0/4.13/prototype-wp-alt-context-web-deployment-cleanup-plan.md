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

| Check | Result |
| --- | --- |
| `npm run typecheck` (from `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context`) | pass |
| `npm run lint` | pass |
| `npm run arch` | pass |
| `npm run test -- --run` | pass (`29` files, `138` tests passed, `3` todo) |
| `composer test` | pass (`41` tests, `102` assertions) |
| `npx tsc --noEmit --project tsconfig.type-check.json --noUnusedLocals --noUnusedParameters` | pass (no unused TS locals/params reported) |
| `composer cs-check` | fail (script misconfigured: no target paths) |

## Seeded Findings (ANTIPATTERN / DEAD_CODE / COMPLEXITY / GAP)

| ID | Severity | Category | Finding | Evidence |
| --- | --- | --- | --- | --- |
| H-1 | HIGH | GAP | PHP code-style gate is non-runnable via composer script | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/composer.json:32` (`cs-check` missing file targets) |
| M-1 | MEDIUM | DEAD_CODE | Frontend service path appears unused/placeholder | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/class-alt-context.php:16`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/class-alt-context.php:35`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/frontend/class-frontend.php:7` |
| M-2 | MEDIUM | DEAD_CODE | Training-stage endpoint/key/style surface has no runtime consumer | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-admin.php:203`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:787`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/styles/components/_workbench.scss:392` |
| M-3 | MEDIUM | DEAD_CODE | Recover-orphans route appears orphaned (no frontend caller) | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:253`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:641` |
| M-4 | MEDIUM | DEAD_CODE | Deprecated compatibility re-export appears unused outside tests | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/workbench/IdentityClusterList.tsx:1` |
| M-5 | MEDIUM | DEAD_CODE | Tracked debug artifacts should not ship in deployment-focused branch | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/test_output.txt`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/test_output_debug.txt` |
| L-1 | LOW | DEAD_CODE | Unused parameter in batch-limits trait (explicitly marked unused) | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/support/trait-batch-limits.php:36` |
| L-2 | LOW | ANTIPATTERN | Redundant boolean condition in workbench render path | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx:290` |
| L-3 | LOW | GAP | Test placeholders remain for key user flows | `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterPage.test.tsx:150`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/__tests__/WorkbenchPage.test.tsx:77` |

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

| File | Line | Planned Change |
| --- | --- | --- |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/composer.json` | 32 | Fix `cs-check` script to include explicit scan targets. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/class-alt-context.php` | 16, 35 | Decide keep/remove wiring for `Frontend` service path based on consumer audit. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/frontend/class-frontend.php` | 7 | Remove placeholder class or implement real responsibilities and wiring. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/admin/class-admin.php` | 203 | Remove or retain `recognitionTrainingStage` endpoint key based on compatibility decision. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php` | 253, 641, 787 | Mark candidate deprecations (`training-stage`, `recover-orphans`) and remove only after compatibility checks pass. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/workbench/IdentityClusterList.tsx` | 1 | Remove compatibility re-export when import audit proves no consumers. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx` | 290 | Remove redundant duplicated condition in render expression. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterPage.test.tsx` | 150 | Implement TODO test or replace with issue-linked deferral. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/__tests__/WorkbenchPage.test.tsx` | 77 | Implement TODO tests or replace with issue-linked deferral. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/test_output.txt` | n/a | Remove tracked debug artifact from deploy-focused branch. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/test_output_debug.txt` | n/a | Remove tracked debug artifact from deploy-focused branch. |

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

## Phase 3: Remove Deployment-Noise Artifacts and Low-Risk Anti-Patterns

- [ ] Remove tracked debug artifacts (`test_output.txt`, `test_output_debug.txt`) or relocate them outside tracked deploy paths.
- [ ] Resolve redundant render condition in `WorkbenchPage.tsx`.
- [ ] Resolve unused-parameter dead code in `trait-batch-limits.php` without behavior regression.

## Phase 4: Resolve Test Placeholder Debt

- [ ] Implement `it.todo` coverage for roster commit flow.
- [ ] Implement `test.todo` coverage for workbench follow-up flows.
- [ ] If any TODO remains, replace with issue-linked tracked deferral.

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
