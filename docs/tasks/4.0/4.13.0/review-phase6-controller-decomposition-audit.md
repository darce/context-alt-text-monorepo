# Phase 6 Controller Decomposition Audit (v4.13.0)

> **Date:** 2026-02-10
> **Scope:** Recognition controller decomposition (`AFS-M4`) and carry-forward item verification from commit `cafa041`
> **Baseline:** `web-deployment-cleanup-plan.md` Phase 6 checklist + carry-forward table
> **Categories:** ANTIPATTERN · DEAD_CODE · COMPLEXITY · GAP

---

## Gate Re-Run Results

All gates re-run from `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context`.

| Check | Result |
| --- | --- |
| `npm run typecheck` | pass |
| `npm run lint` | pass |
| `npm run arch` | pass (`98` files checked, no violations) |
| `npm run test -- --run` | pass (`30` files, `153` tests passed) |
| `composer test` | pass (`48` tests, `129` assertions) |
| `composer cs-check` | pass (exit `0`) |

---

## Phase 6 Checklist Verification

### Phase 6.0: Scaffolding

| Item | Status | Evidence |
| --- | --- | --- |
| Controller interface + base abstractions | **Done** | `src/api/interface-recognition-route-controller.php` (9 lines) — `RecognitionRouteControllerInterface` with `register_routes()`. `src/api/class-abstract-recognition-proxy-controller.php` (97 lines) — shared `proxy_request()`, `get_tenant_id()`, `can_manage_recognition()`, retry logic. |
| New controller class shells + route boundaries | **Done** | `class-analysis-jobs-controller.php` (375 lines), `class-clusters-controller.php` (541 lines), `class-suggestions-controller.php` (234 lines) |
| Test files adjusted | **Done** | Tests exercise decomposed controllers through `RecognitionController` composition facade via `__call()` |

### Phase 6.1: Extraction

| Item | Status | Evidence |
| --- | --- | --- |
| Analysis/job routes → `AnalysisJobsController` | **Done** | `analyze`, `jobs/{id}`, `jobs/{id}/stream`, `jobs/{id}/cancel` — 4 routes with full SSE streaming |
| Cluster/media-identity routes → `ClustersController` | **Done** | 14 route registrations covering cluster CRUD, merge/split/reassign, dismiss, media-identities, revert-merge |
| Suggestion routes → `SuggestionsController` | **Done** | 7 route registrations covering suggestion read, accept/reject, merge suggestions |

### Phase 6.2: Wiring and Compatibility

| Item | Status | Evidence |
| --- | --- | --- |
| API bootstrap registers sub-controllers | **Done** | `class-recognition-controller.php` (68 lines) — composition root delegates `register_routes()` to all three sub-controllers |
| Route paths/shapes/permissions unchanged | **Done** | All routes use same `acx/v1` namespace, HTTP methods, `can_manage_recognition` permission. `testRegisterRoutesDoesNotExposeRemovedSurfaces` asserts removed routes stay absent. |
| Dead code removed from legacy controller | **Done** | Legacy controller: 1,288 → 68 lines |

### Phase 6.3: Verification

| Item | Status | Evidence |
| --- | --- | --- |
| `composer test` passes | **Done** | 48 tests, 129 assertions — all pass |
| Frontend contract tests pass | **Done** | 30 files, 153 tests — all pass |
| Manual smoke checks | **Not done** | Checklist item correctly left unchecked — requires live WP environment |

### Size Breakdown (Post-Decomposition)

| File | Lines |
| --- | --- |
| `class-recognition-controller.php` (composition root) | 68 |
| `class-analysis-jobs-controller.php` | 375 |
| `class-clusters-controller.php` | 541 |
| `class-suggestions-controller.php` | 234 |
| `class-abstract-recognition-proxy-controller.php` | 97 |
| `interface-recognition-route-controller.php` | 9 |
| **Total** | **1,324** |

---

## Phase 6 New Findings

| ID | Severity | Category | Finding | Evidence | Recommended Action |
| --- | --- | --- | --- | --- | --- |
| P6-M1 | MEDIUM | COMPLEXITY | `ClustersController` at 541 lines is the largest single controller. Combines cluster CRUD, merge/split/reassign, media-identities, and thumbnail hydration. | `src/api/class-clusters-controller.php` — 14 route registrations | Consider further split into `ClusterMutationsController` and `MediaIdentitiesController` when sovereign roadmap Phase 2 begins. |
| P6-M2 | MEDIUM | ANTIPATTERN | `__call()` magic method on `RecognitionController` provides backward compatibility but bypasses static analysis. Test calls like `$this->controller->dismiss_cluster(...)` route through `__call()` — PHPStan/IDE cannot verify these exist. | `src/api/class-recognition-controller.php:50` — iterates controllers with `method_exists()` | Add typed delegation methods (or `@method` PHPDoc annotations) to restore static analysis coverage. Remove `__call()` once all callers reference sub-controllers directly. |
| P6-L1 | LOW | GAP | No dedicated test files for individual sub-controllers. All coverage goes through the composition root (`RecognitionControllerTest.php`), so regressions lack clear ownership signal. | `tests/Unit/` contains only `RecognitionControllerTest.php` and `ProxyRequestTest.php` for recognition API | Add `AnalysisJobsControllerTest.php`, `ClustersControllerTest.php`, `SuggestionsControllerTest.php` targeting isolated controller behavior. |
| P6-L2 | LOW | GAP | `AbstractRecognitionProxyController` reads `get_option()` at construction time, not request time. Options changed after plugin boot (e.g., settings update) use stale values until next page load. | `src/api/class-abstract-recognition-proxy-controller.php:28` | Acceptable for MVP. For sovereign roadmap, consider lazy-loading or request-scoped option reads. |

---

## Carry-Forward Verification (Commit `cafa041`)

Items from the carry-forward table in `web-deployment-cleanup-plan.md`, verified against current codebase state.

| ID | Claimed Status | Verified | Evidence | Notes |
| --- | --- | --- | --- | --- |
| 4.12-M14 | Resolved | **Confirmed** | `rg` for postfix `!` in `SuggestionReviewPanel.tsx` returns no matches | Non-null assertions eliminated |
| 4.12-M15 | Resolved | **Confirmed** | `rg "undefined as"` in `http.ts` returns no matches; return type is `Promise<T \| undefined>` | Cast eliminated |
| 4.12-L13 | Resolved | **Confirmed** | `rg "window.confirm"` in `js/admin/` returns no matches; `ClusterReviewPanel.tsx` and `IdentityClusterItem.tsx` now use `DialogRoot` | `window.confirm` replaced with accessible Radix dialogs |
| 4.12-L15 | Resolved | **Partially** | `_cluster-panels.scss` — no hardcoded hex colors remain. `_identity-cluster-list.scss` still has `#ef4444` at L212 and L283, plus `#fee2e2` at L213, `#0f172a` at L220. | Core claim (cluster panels tokens) is accurate. Sibling SCSS file `_identity-cluster-list.scss` was not in scope of the carry-forward but has the same anti-pattern. See `P6-CF1` below. |
| 4.12-L16 | Resolved | **Confirmed** | `rg "46px"` in `_workbench.scss` returns no matches; `_spacing.scss` defines `--acx-workbench-sticky-top` | Magic number replaced with documented custom property |
| CF-L1 | Resolved | **Partially** | `_workbench.scss` and `_cluster-panels.scss` no longer have divergent `--acx-color-danger` fallbacks. `_identity-cluster-list.scss` still uses raw `#ef4444` (and `!important`) at L212 and L283. | Same file gap as 4.12-L15. See `P6-CF1`. |
| CF-L2 | Resolved | **Confirmed** | `trait-batch-limits.php:16` now uses `TODO(post-mvp-tiers):` structured format | Structured TODO with tracking context |

### New Finding from Carry-Forward Verification

| ID | Severity | Category | Finding | Evidence | Recommended Action |
| --- | --- | --- | --- | --- | --- |
| P6-CF1 | LOW | ANTIPATTERN | `_identity-cluster-list.scss` still contains hardcoded hex colors (`#ef4444`, `#fee2e2`, `#0f172a`) and `!important` declarations that were not covered by the carry-forward token extraction. | `js/admin/styles/components/_identity-cluster-list.scss:212`, `js/admin/styles/components/_identity-cluster-list.scss:213`, `js/admin/styles/components/_identity-cluster-list.scss:220`, `js/admin/styles/components/_identity-cluster-list.scss:283` | Extract these colors to shared tokens (`--acx-color-danger`, `--acx-color-danger-soft`, `--acx-color-text-primary`) and remove `!important` by increasing selector specificity. |

---

## Summary

| Severity | Phase 6 Findings | Carry-Forward Findings | Total New |
| --- | --- | --- | --- |
| HIGH | 0 | 0 | 0 |
| MEDIUM | 2 | 0 | 2 |
| LOW | 2 | 1 | 3 |
| **Total** | **4** | **1** | **5** |

Phase 6 is **correctly completed** per the plan checklist. The monolithic controller (1,288 lines) has been decomposed into three focused domain controllers with a shared proxy base, preserving the REST contract. All automated gates pass. Two MEDIUM findings (further ClustersController split opportunity, `__call()` magic method) are tracked for sovereign roadmap Phase 2. All carry-forward items are confirmed resolved except a pre-existing hex-color anti-pattern in `_identity-cluster-list.scss` that was outside the original carry-forward scope.
