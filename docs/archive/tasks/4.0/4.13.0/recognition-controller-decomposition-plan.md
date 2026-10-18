# Recognition Controller Decomposition Plan

## Problem Statement

`apps/prototype-wp-alt-context/src/api/class-recognition-controller.php` has accumulated route registration and callback logic for analysis, clustering, suggestions, and job orchestration in one class. The current size and breadth increase change risk and make review/testing slower.

## Proposed Solution

Split route ownership by domain while preserving current REST contract behavior:

1. Introduce a shared proxy base (`AbstractRecognitionProxyController` or trait) for:
- `proxy_request()`
- `get_tenant_id()`
- common permission and request helpers
2. Extract domain-focused controllers:
- `AnalysisJobsController` (`analyze`, `jobs`, `cancel`, progress stream)
- `ClustersController` (cluster CRUD, merge/split/reassign, media identities)
- `SuggestionsController` (suggestion read/accept/reject, merge suggestions)
3. Keep a thin top-level API wiring class that registers each sub-controller.
4. Port existing PHPUnit route and callback coverage without behavior changes.

## Related Files

- `apps/prototype-wp-alt-context/src/api/class-recognition-controller.php`
- `apps/prototype-wp-alt-context/src/api/class-api.php`
- `apps/prototype-wp-alt-context/tests/Unit/RecognitionControllerTest.php`
- `apps/prototype-wp-alt-context/tests/Unit/ProxyRequestTest.php`

---

# Consolidated Checklist

## Phase 0: Scaffolding

- [x] Add controller interfaces/base abstractions with method signatures only.
- [x] Add new controller class shells and route group boundaries.
- [x] Add/adjust test files with failing scaffolds for each route group.

## Phase 1: Extraction

- [x] Move analysis/job routes and callbacks to `AnalysisJobsController`.
- [x] Move cluster/media identity routes and callbacks to `ClustersController`.
- [x] Move suggestion routes and callbacks to `SuggestionsController`.

## Phase 2: Wiring and Compatibility

- [x] Update API bootstrap to initialize and register sub-controllers.
- [x] Keep route paths, request/response shapes, and permission callbacks unchanged.
- [x] Remove dead code from the legacy monolithic controller.

## Phase 3: Verification

- [x] Ensure `composer test` passes for recognition controller coverage.
- [x] Ensure frontend contract tests that depend on recognition routes still pass.
- [ ] Confirm no REST endpoint regressions in manual smoke checks.

## Success Criteria

- [x] Recognition API responsibilities are split across domain controllers.
- [x] Legacy monolithic controller is either removed or reduced to thin composition.
- [x] Existing route contracts remain backward-compatible for the current branch.
