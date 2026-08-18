# Branch Audit — `feature/4.12.0-suggestion-panel`

> **Date:** 2026-02-07
> **Scope:** 101 files changed, +5888 / −1987 lines vs `main`
> **Categories:** ANTIPATTERN · DEAD_CODE · COMPLEXITY · GAP
> **Method:** Full branch-review-guide.md checklist (automated gate + manual sections 3.1–3.9)

---

## Summary

| Severity | Count |
|----------|-------|
| **HIGH** | 3 |
| **MEDIUM** | 6 |
| **LOW** | 5 |
| **Total** | **14** |

> **Resolution update (2026-02-07):** All 14 findings listed in this document have been addressed in code. The sections below keep the original finding descriptions for traceability.

---

## Automated Check Results

| Check | Result |
|-------|--------|
| `make check` (ruff + mypy + pytest) | :white_check_mark: 473 passed, 1 skipped |
| `npm run typecheck` | :white_check_mark: |
| `npm run test -- --run` | :white_check_mark: 132 passed, 3 todo |
| `npm run lint` | :white_check_mark: (after fix — removed spurious `async` in ClusterReviewPanel.test.tsx:144) |
| `npm run build` | :white_check_mark: |
| `composer test` (PHPUnit) | :white_check_mark: 41 tests, 102 assertions (after fix — removed deprecated `setAccessible()` in AdminTest.php:108) |
| `check-architecture-compliance.js` | :white_check_mark: 0 errors |
| `composer phpstan` | N/A (not installed) |
| Cyclomatic complexity (radon, grade C+) | 5 functions at grade D+ in diff files |

### Architecture compliance errors

| File | Violation |
|------|-----------|
| `clusterApi.ts` | 210/175 lines (API module limit) |
| `identityApi.ts` | 197/175 lines (API module limit) |
| `useJobProgressStream.ts` | 205/200 lines (hook limit) |
| `SuggestionReviewPanel.tsx` | 549/400 lines (route/page limit) |
| `WorkbenchPage.tsx` | 6/5 `useState` hooks |

### Radon grade D+ in diff files

| File | Function | Grade | Score |
|------|----------|-------|-------|
| `label_inference.py` | `infer_suggested_label` | E | 40 |
| `refresh_service.py` | `surface_for_newly_labeled_cluster` | E | 36 |
| `cluster_repository.py` | `_to_domain` | D | 30 |
| `refresh_service.py` | `refresh_for_identity` | D | 23 |
| `tasks/clustering.py` | `run_background_surface_suggestions` | D | 22 |

### Fixes applied during review

| Fix | File | Description |
|-----|------|-------------|
| F-1 | `tests/Unit/AdminTest.php:108` | Removed deprecated `setAccessible(true)` (PHP 8.5) |
| F-2 | `ClusterReviewPanel.test.tsx:144` | Removed unnecessary `async` (ESLint `require-await`) |

---

## HIGH Severity

### H-1 · Domain layer imports presentation DTOs

| | |
|---|---|
| **Files** | `recognition/domain/repositories.py` L22–25 |
| **Category** | ANTIPATTERN |

`recognition/domain/repositories.py` imports `SuggestionDetails` and `MergeSuggestionDetails` from `recognition/interface_adapters/schemas/suggestion_details`. This inverts the dependency direction — the domain layer must not depend on presentation schemas. Repository protocol methods (`list_pending_with_details`, etc.) should return domain types; the interface_adapters layer maps to DTOs at the boundary.

### H-2 · Architecture compliance: file size and hook violations

| | |
|---|---|
| **Files** | `SuggestionReviewPanel.tsx` (549 lines), `clusterApi.ts` (210), `identityApi.ts` (197), `useJobProgressStream.ts` (205), `WorkbenchPage.tsx` (6 useState) |
| **Category** | COMPLEXITY |

5 errors from `check-architecture-compliance.js`. `SuggestionReviewPanel.tsx` at 549/400 significant lines is the largest overshoot — needs extract-to-hooks or split into sub-components. `WorkbenchPage.tsx` needs `useReducer` to consolidate state.

### H-3 · TopClustersSection bypasses API module layer

| | |
|---|---|
| **Files** | `TopClustersSection.tsx` L13, L258–265 |
| **Category** | ANTIPATTERN |

Component directly imports `fetchApi` from `utils/http` and constructs a raw inline `queryFn` with string-interpolated URL params (`\`${base}/top-unlabeled?limit=${...}&tenant_id=${...}\``). Should be extracted to an API module function using `URLSearchParams`, consistent with `clusterApi.ts` which already has this pattern.

---

## MEDIUM Severity

### M-1 · `object` type parameter in protocol

| | |
|---|---|
| **Files** | `recognition/application/orchestration/protocols.py` L82 |
| **Category** | ANTIPATTERN |

`representatives_by_cluster: Mapping[str, Sequence[object] | object]` should use `np.ndarray` or a domain `Embedding` type instead of `object`.

### M-2 · Untyped `decision` parameter with `getattr` guards

| | |
|---|---|
| **Files** | `recognition/application/suggestions/refresh_service.py` L146–158 |
| **Category** | ANTIPATTERN |

`_should_surface_gate_reject(self, decision, ...)` has no type annotation. Uses `getattr(decision, "failure_kinds", [])` and `getattr(decision, "checks_failed", [])`. Should accept the typed `AssignmentDecision` or protocol.

### M-3 · Triplicate `FakeClusterRepository`

| | |
|---|---|
| **Files** | `tests/api/conftest.py` L436, `tests/conftest.py` L127, `tests/fakes.py` L39 |
| **Category** | COMPLEXITY |

Three divergent `FakeClusterRepository` implementations with different stored types and method sets. Protocol changes require updates in three places. Consolidate into one configurable fake.

### M-4 · Missing test files for 3 new UI components

| | |
|---|---|
| **Files** | `CollapsibleMergeQueue.tsx`, `MergeSuggestionCard.tsx`, `TopClustersSection.tsx` |
| **Category** | GAP |

Each new UI component should have tests covering render, loading, and error states per checklist 3.8.

### M-5 · Application layer imports presentation DTO

| | |
|---|---|
| **Files** | `recognition/application/suggestions/service.py` L27 |
| **Category** | ANTIPATTERN |

`SuggestionService` imports `SuggestionDetails` from `interface_adapters/schemas/`. Less severe than H-1 (application is adjacent to interface), but `list_pending()` returns a presentation type rather than a domain type.

### M-6 · Raw hex colors in `_workbench.scss`

| | |
|---|---|
| **Files** | `_workbench.scss` L611–612, L693–694, L812 |
| **Category** | ANTIPATTERN |

`#fff7ed`, `#f59e0b`, `#fef3c7`, `#92400e`, `#e0e0e0` used directly instead of `--acx-*` custom properties. Should define `--acx-color-warning-bg`, `--acx-color-warning-border`, etc.

---

## LOW Severity

### L-1 · PHP tenant_id sent in both POST body and query params

| | |
|---|---|
| **Files** | `class-recognition-controller.php` L1106–1170 |
| **Category** | COMPLEXITY |

`accept_suggestion`, `accept_merge_suggestion`, `reject_suggestion`, `reject_merge_suggestion` all send `tenant_id` in both `$payload` (POST body) and `$query` (4th arg to `proxy_request`). Redundant — pick one transport.

### L-2 · Triplicate inline `StubClusterService` in test file

| | |
|---|---|
| **Files** | `tests/api/test_tenant_isolation.py` L26, L99, L179 |
| **Category** | COMPLEXITY |

Three identical inline class definitions. Extract to a shared fixture.

### L-3 · Duplicate function-level imports in test files

| | |
|---|---|
| **Files** | `test_proactive_suggestions.py` L89+163, `test_label_inference.py` L44+100+184+258+337, `test_curation_logic.py` L234+328 |
| **Category** | ANTIPATTERN |

Same `from ...` imports repeated inside multiple test functions. Hoist to module level.

### L-4 · `NullClusterRepository.get_maturity_info` always returns `None`

| | |
|---|---|
| **Files** | `tests/stubs.py` L94–100 |
| **Category** | GAP |

Not configurable via constructor kwargs unlike other stub methods. Tests using this for confidence checks always hit fallback path.

### L-5 · Function-level `import logging` in test files

| | |
|---|---|
| **Files** | `test_curation_logic.py` L234, L328 |
| **Category** | ANTIPATTERN |

Standard library import repeated inside test functions. Should be at module level.

---

## Recommended Fix Order

### Phase 1 — Correctness (before merge)

1. **H-2** — Split `SuggestionReviewPanel.tsx` (549→<400 lines), consolidate `WorkbenchPage.tsx` state with `useReducer`
2. **H-3** — Extract TopClustersSection inline fetch to `clusterApi.ts` with `URLSearchParams`

### Phase 2 — Robustness (soon after merge)

3. **H-1** — Define domain-layer `SuggestionSummary`/`MergeSuggestionSummary` types; move DTO mapping to interface_adapters
4. **M-1** — Type `representatives_by_cluster` as `Mapping[str, Sequence[np.ndarray] | np.ndarray]`
5. **M-2** — Add `AssignmentDecision` type annotation to `_should_surface_gate_reject`
6. **M-4** — Add test files for `CollapsibleMergeQueue`, `MergeSuggestionCard`, `TopClustersSection`
7. **M-6** — Define `--acx-color-warning-*` tokens and replace raw hex in `_workbench.scss`

### Phase 3 — Maintainability (tech debt)

8. **M-3** — Consolidate `FakeClusterRepository` into one configurable implementation
9. **M-5** — Return domain type from `SuggestionService.list_pending()`
10. **L-1 through L-5** — PHP dual-transport cleanup, test stub consolidation, import dedup

---

## Consolidated Checklist

### Phase 1 — Correctness (before merge)

- [x] **H-2** — Split `SuggestionReviewPanel.tsx` below 400 lines; `WorkbenchPage.tsx` → `useReducer`
- [x] **H-3** — Move TopClustersSection fetch to `clusterApi.ts`, use `URLSearchParams`

### Phase 2 — Robustness

- [x] **H-1** — Domain-layer types for suggestion details; remove `interface_adapters` import from `domain/`
- [x] **M-1** — Type `object` → `np.ndarray` in protocols.py embedding param
- [x] **M-2** — Annotate `decision` parameter in refresh_service.py
- [x] **M-4** — Add test files for 3 untested UI components
- [x] **M-6** — Replace raw hex with design tokens in `_workbench.scss`

### Phase 3 — Maintainability

- [x] **M-3** — Single configurable `FakeClusterRepository`
- [x] **M-5** — Domain return type from `SuggestionService.list_pending()`
- [x] **L-1** — Remove duplicate `tenant_id` transport in PHP suggestion endpoints
- [x] **L-2** — Extract shared `StubClusterService` in test_tenant_isolation.py
- [x] **L-3** — Hoist duplicate test imports to module level
- [x] **L-4** — Make `NullClusterRepository.get_maturity_info` configurable
- [x] **L-5** — Move `import logging` to module level in test files

### Success Criteria

- [x] Zero HIGH findings remaining
- [x] `make check` passes
- [x] `npm run typecheck` passes
- [x] `check-architecture-compliance.js` passes with zero errors
- [x] All existing tests continue to pass
- [ ] Branch audit re-run shows no regressions

---

## Manual Checklist Status

| Section | Status | Notes |
|---------|--------|-------|
| 3.1 Correctness | :white_check_mark: CLEAN | Migration ↔ model parity OK, no unreachable code, no duplicate fields, API contracts aligned |
| 3.2 Type Safety | :white_check_mark: CLEAN | M-1 and M-2 addressed (`np.ndarray` protocol typing + typed `AssignmentDecision`) |
| 3.3 Architecture | :white_check_mark: CLEAN | H-1 and M-5 addressed (domain-owned suggestion detail types) |
| 3.4 Code Duplication | :white_check_mark: CLEAN | M-3 addressed (single configurable fake repository) |
| 3.5 Error Handling | :white_check_mark: CLEAN | `ilike` escaping correct, gate fallbacks consistent, `contextlib.suppress(Exception)` instances *removed* in this branch |
| 3.6 Frontend | :white_check_mark: CLEAN | H-2/H-3/M-6 addressed (module split, API boundary, design tokens, architecture check green) |
| 3.7 PHP/WordPress | :white_check_mark:/:information_source: | Sanitization, nonces, capability checks all OK. L-1 dual-transport is minor |
| 3.8 Tests | :white_check_mark: CLEAN | M-4 addressed (tests added for all 3 new UI components) |
| 3.9 Documentation | :white_check_mark:/:information_source: | No stale TODOs, no empty docstrings. L-3/L-5 import cleanup completed |

---

## Backfill Plan Implementation Verification (carried forward)

All 35 backfill plan items verified complete. See previous version of this document for line-by-line evidence. Key success criteria:

| Criterion | Status |
|-----------|--------|
| Newly created unlabeled clusters surface suggestions | :white_check_mark: |
| Clusters with null `representative_identity_id` receive suggestions | :white_check_mark: |
| Previously rejected suggestions never mutated by backend | :white_check_mark: |
| Automated tests cover Laura/Sable/Jen-style scenarios | :white_check_mark: |
