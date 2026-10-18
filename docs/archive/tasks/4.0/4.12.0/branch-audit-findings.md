# Branch Audit — `feature/4.12.0-suggestion-panel`

> **Date:** 2025-06-07
> **Scope:** 66 files changed, +4169 / −830 lines vs `main`
> **Categories:** ANTIPATTERN · DEAD_CODE · COMPLEXITY · GAP

---

## Summary

| Severity   | Count  |
| ---------- | ------ |
| **HIGH**   | 9      |
| **MEDIUM** | 24     |
| **LOW**    | 19     |
| **Total**  | **52** |

---

## HIGH Severity

### H-1 · Migration ↔ Model Constraint Mismatch

|              |                                                                                                |
| ------------ | ---------------------------------------------------------------------------------------------- |
| **Files**    | `db/migrations/versions/001_identity_schema.py` L102, L162 / `db/models/identity.py` L75, L141 |
| **Category** | GAP                                                                                            |

Two unique constraints diverge between the migration and the ORM model:

- `unique_media_identity`: migration includes `identity_type` column — model omits it ⇒ 4-col vs 5-col.
- `unique_tenant_identity_label`: migration includes `identity_type` — model has only `(tenant_id, label)`.

Alembic autogenerate will detect schema drift. The model definition controls what SQLAlchemy validates at application level, while the migration controls what the database actually enforces.

---

### H-2 · SQL LIKE Injection in Cluster Search

|              |                                                                 |
| ------------ | --------------------------------------------------------------- |
| **File**     | `recognition/infrastructure/repositories/cluster_repository.py` |
| **Category** | ANTIPATTERN                                                     |

`search` parameter is interpolated into a LIKE pattern without escaping `%` and `_` wildcards. A user searching for `100%` would match all rows. Apply `search.replace('%', '\\%').replace('_', '\\_')` before `ilike(f"%{search}%")`.

---

### H-3 · `contextlib.suppress(Exception)` Silently Swallows Errors

|              |                                                                                  |
| ------------ | -------------------------------------------------------------------------------- |
| **Files**    | `cluster_repository.py` (materialized view refresh), `cluster_merge.py` L283–292 |
| **Category** | ANTIPATTERN                                                                      |

Two sites use bare `contextlib.suppress(Exception)`:

1. Materialized view refresh — if the view fails to refresh, stale data is served silently.
2. Post-merge suggestion resolution — if suggestion resolution has a real bug (DB constraint violation), it will be invisible.

At minimum log the suppressed exception.

---

### H-4 · `_coerce_uuid` / `_ensure_media_identity` Copy-Pasted Across Repositories

|              |                                                                         |
| ------------ | ----------------------------------------------------------------------- |
| **Files**    | `cluster_repository.py`, `suggestion_repository.py`, and 1+ other repos |
| **Category** | COMPLEXITY                                                              |

Identical UUID coercion and media-identity bootstrap logic is duplicated across 3+ repository files. Extract to a shared utility in `infrastructure/repositories/_helpers.py`.

---

### H-5 · Missing Pose Fields in Merge-Path `MediaIdentity` Construction

|              |                                                                   |
| ------------ | ----------------------------------------------------------------- |
| **File**     | `recognition/application/orchestration/cluster_merge.py` L103–114 |
| **Category** | GAP                                                               |

`MediaIdentity` is constructed without `pose_pitch`, `pose_yaw`, `pose_roll`, or `image_phash` (all defaulting to `None`). `ConfidenceCheck` then computes quality using these None values. Compare with `refresh_service.py` L89–101 which correctly populates all pose fields — the merge path applies different quality thresholds for the same identity.

---

### H-6 · Duplicate `representative_thumbnail_url` Field in `SuggestionResponse`

|              |                                                                     |
| ------------ | ------------------------------------------------------------------- |
| **File**     | `recognition/interface_adapters/http/schemas/responses.py` L174–175 |
| **Category** | DEAD_CODE                                                           |

Field declared twice on consecutive lines. Pydantic silently uses the last declaration. Likely a copy-paste error — one may have been intended as a different field.

---

### H-7 · Skipped / Empty Tests Masking Coverage Gaps

|              |                                                                               |
| ------------ | ----------------------------------------------------------------------------- |
| **Files**    | `test_api_suggestions.py` L24–72, `test_label_inference.py` L16–163, L166–185 |
| **Category** | DEAD_CODE                                                                     |

Three tests are permanently `@pytest.mark.skip` and one is `pass`-only:

- `test_suggestion_response_has_suggested_label_fields` — skipped "scaffold", tests critical API contract.
- `test_infer_suggested_label_from_similar_cluster` / `test_infer_suggested_label_no_match_low_similarity` — skipped for SQLite vector limitation, covering a primary feature path.
- `test_infer_suggested_label_from_identity_match_deprecated` — empty body, runs as a false-positive green.

These create false confidence in test coverage.

---

### H-8 · `clusterAdapter.ts` Missing `clusteringPending` Property

|              |                                                              |
| ------------ | ------------------------------------------------------------ |
| **File**     | `js/admin/api/recognition/adapters/clusterAdapter.ts` L26–31 |
| **Category** | GAP                                                          |

`toClusterGroup` returns an object missing the required `clusteringPending` property from the `ClusterGroup` type. Causes `TS2741` at build time. Pre-existing but in the diff scope.

---

### H-9 · ~600 Lines of Copy-Pasted Repository Stubs in Tests

|              |                                                                                                                                             |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **Files**    | `test_suggestion_refresh.py` L311–580, `test_assignment_gate.py`, `test_assignment_gate_defaults.py`, `test_assignment_writer_interface.py` |
| **Category** | COMPLEXITY                                                                                                                                  |

Four test methods in `TestRefreshForIdentity` define identical `ClusterRepoStub` / `SessionStub` inline classes (~30 lines each), plus three additional files define full ~100-line `ClusterRepository` stub implementations independently. A shared `NullClusterRepository` test utility would eliminate ~600+ lines.

---

## MEDIUM Severity

### M-1 · `ClusterNotFoundError` Defined in Two Locations

|              |                                                    |
| ------------ | -------------------------------------------------- |
| **Files**    | `recognition/domain/` + `recognition/application/` |
| **Category** | ANTIPATTERN                                        |

Same exception class defined in both domain and application layers. Consolidate to one canonical location (domain).

---

### M-2 · `IdentityClusterBlockRepository` Has Duplicate Methods

|              |                                      |
| ------------ | ------------------------------------ |
| **File**     | `recognition/domain/repositories.py` |
| **Category** | DEAD_CODE                            |

Both `block()` and `add_block()` exist with near-identical signatures. One is likely a leftover from a rename.

---

### M-3 · `get_member_identities_with_similarity` Not Declared in Protocol

|              |                                      |
| ------------ | ------------------------------------ |
| **File**     | `recognition/domain/repositories.py` |
| **Category** | GAP                                  |

Method used by suggestion service but missing from the `ClusterRepository` Protocol, forcing `getattr()` duck-typing at call sites.

---

### M-4 · `create()` and `upsert_by_identity_cluster()` Near-Identical Logic

|              |                            |
| ------------ | -------------------------- |
| **File**     | `suggestion_repository.py` |
| **Category** | COMPLEXITY                 |

Two large methods share most of their logic. Refactor to one internal builder with a conditional upsert/insert path.

---

### M-5 · Untyped `object` Parameter in `eligibility.py`

|              |                                                          |
| ------------ | -------------------------------------------------------- |
| **File**     | `recognition/application/suggestions/eligibility.py` L11 |
| **Category** | ANTIPATTERN                                              |

`is_eligible_cluster(cluster: object, ...)` accesses `tenant_id`, `user_confirmed`, `label`, `id` via `getattr()`. Erases type safety entirely. Should accept a Protocol or `IdentityCluster`.

---

### M-6 · `ClusteringSettings()` Default Instantiation in `label_inference.py`

|              |                                                              |
| ------------ | ------------------------------------------------------------ |
| **File**     | `recognition/application/suggestions/label_inference.py` L43 |
| **Category** | ANTIPATTERN                                                  |

Creates a brand-new default instance per call, bypassing environment-configured overrides. Should receive settings via dependency injection.

---

### M-7 · Raw SQL in Application Layer (`label_inference.py`)

|              |                                                                   |
| ------------ | ----------------------------------------------------------------- |
| **File**     | `recognition/application/suggestions/label_inference.py` L109–111 |
| **Category** | ANTIPATTERN                                                       |

`text("SELECT name FROM roster_entries WHERE id = :rid")` violates clean architecture boundaries. Wrapped in bare `except Exception: pass` that silently swallows errors.

---

### M-8 · Inconsistent Check `name` Conventions

|              |                                                     |
| ------------ | --------------------------------------------------- |
| **Files**    | `checks/block.py`, `confidence.py`, `constraint.py` |
| **Category** | GAP                                                 |

Three conventions: `"block_check"` (snake), `"confidence"` (bare), `"ConstraintCheck"` (Pascal). These are matched by string in `refresh_service.py`; if names are ever refactored, the fallback silently breaks.

---

### M-9 · Duplicate Gate Fallback Logic

|              |                                                                             |
| ------------ | --------------------------------------------------------------------------- |
| **File**     | `recognition/application/suggestions/refresh_service.py` L274–296, L568–575 |
| **Category** | COMPLEXITY                                                                  |

When `self._gate is None`, both `refresh_for_identity` and `surface_for_newly_labeled_cluster` manually inline block/constraint checks. The second path doesn't check constraints at all — only blocks — creating an inconsistency.

---

### M-10 · `getattr`-Based Dynamic Dispatch Defeats Type Checking

|              |                                                                      |
| ------------ | -------------------------------------------------------------------- |
| **Files**    | `cluster_merge.py` L90/133/143, `tasks/clustering.py` L80–87/148–153 |
| **Category** | ANTIPATTERN                                                          |

Multiple `getattr(service, "method_name", None)` + `callable()` guards. Suggests protocol types are incomplete — methods should be declared on the protocol interfaces.

---

### M-11 · Unreachable Dead Code in `reassign_identity` Endpoint

|              |                                |
| ------------ | ------------------------------ |
| **File**     | `routers/clusters.py` L686–687 |
| **Category** | DEAD_CODE                      |

Inside the `else` branch (where `target_cluster_id` is None), code checks `if request.target_cluster_id:` — unreachable.

---

### M-12 · Re-exporting Non-Check Symbols from `checks/__init__.py`

|              |                                                                       |
| ------------ | --------------------------------------------------------------------- |
| **File**     | `recognition/application/assignment/checks/__init__.py` L9–11, L17–19 |
| **Category** | ANTIPATTERN                                                           |

`ClusterRepository`, `IdentityClusterBlockRepository`, `ClusteringSettings` exported from the `checks` package `__all__` but never imported from there. Misleading coupling.

---

### M-13 · Broad Exception Suppression in Merge Path

|              |                             |
| ------------ | --------------------------- |
| **File**     | `cluster_merge.py` L283–292 |
| **Category** | GAP                         |

Covered by H-3. `contextlib.suppress(Exception)` hides bugs in post-merge suggestion resolution.

---

### M-14 · Non-Null Assertions (`!`) in SuggestionReviewPanel

|              |                                           |
| ------------ | ----------------------------------------- |
| **File**     | `SuggestionReviewPanel.tsx` L98–102, L134 |
| **Category** | ANTIPATTERN                               |

`suggestion.identity_media_url!` and `suggestion.representative_bbox!` suppress nullable types instead of narrowing properly. The `representative_bbox` path doesn't even guard truthiness before using `!`.

---

### M-15 · `undefined as T` Unsafe Cast in `http.ts`

|              |                                   |
| ------------ | --------------------------------- |
| **File**     | `js/admin/utils/http.ts` L44, L49 |
| **Category** | ANTIPATTERN                       |

`return undefined as T` for empty/204 responses. Callers doing `fetchApi<SomeInterface>(...)` get `undefined` typed as the interface, causing runtime errors on property access. Return type should be `Promise<T | undefined>`.

---

### M-16 · Ad-Hoc Query Keys Outside `queryKeys` Factory

|              |                                                              |
| ------------ | ------------------------------------------------------------ |
| **Files**    | `ClusterLabelingPanel.tsx` L52, `ClusterReviewPanel.tsx` L24 |
| **Category** | ANTIPATTERN                                                  |

Raw `['cluster-members', clusterId]` instead of using the centralized `queryKeys` factory. Creates stale-data risk when other components invalidate via `queryKeys`.

---

### M-17 · Duplicate Face-Crop Math in TopClustersSection

|              |                                 |
| ------------ | ------------------------------- |
| **File**     | `TopClustersSection.tsx` L68–80 |
| **Category** | COMPLEXITY                      |

`buildFaceCropStyle` duplicates the crop-and-center algorithm already encapsulated in `FaceThumbnail.tsx`. If the algorithm changes, both must be updated.

---

### M-18 · Sequential Mutation Loop for Bulk Accept

|              |                                      |
| ------------ | ------------------------------------ |
| **File**     | `SuggestionReviewPanel.tsx` L491–497 |
| **Category** | COMPLEXITY                           |

`acceptGroupedSuggestions` sequentially awaits `acceptMutation.mutateAsync()` in a for-loop. For N suggestions = N serial network round-trips. Use `Promise.all` or a batch endpoint.

---

### M-19 · `!important` Overrides in SCSS

|              |                                      |
| ------------ | ------------------------------------ |
| **Files**    | `_workbench.scss` L695–696, L806–807 |
| **Category** | ANTIPATTERN                          |

`!important` on button padding/font-size, fighting WordPress admin styles. Should increase selector specificity instead.

---

### M-20 · `$_GET['page']` Without Sanitization (PHP)

|              |                                 |
| ------------ | ------------------------------- |
| **File**     | `src/admin/class-admin.php` L87 |
| **Category** | ANTIPATTERN                     |

WordPress coding standards require sanitizing all superglobal access (e.g., `sanitize_key()`) even when the value is only compared against an allowlist.

---

### M-21 · Redundant `tenant_id` in Both Body and Query (PHP)

|              |                                                               |
| ------------ | ------------------------------------------------------------- |
| **File**     | `src/api/class-recognition-controller.php` L860–862, L878–880 |
| **Category** | ANTIPATTERN                                                   |

`dismiss_cluster` / `undismiss_cluster` send `tenant_id` in both the POST body AND query params. Pick one per API contract.

---

### M-22 · `FakeSession` Always Returns Null — False Positive Risk

|              |                                            |
| ------------ | ------------------------------------------ |
| **File**     | `recognition/tests/api/conftest.py` L24–67 |
| **Category** | ANTIPATTERN                                |

API tests use a `FakeSession` that always returns `None`/`0`/empty. Routes relying on real lookups may pass for the wrong reason.

---

### M-23 · Dual-Patching in `api_client` Fixture

|              |                                              |
| ------------ | -------------------------------------------- |
| **File**     | `recognition/tests/api/conftest.py` L500–590 |
| **Category** | COMPLEXITY                                   |

Both `app.dependency_overrides[...]` and `monkeypatch.setattr(...)` for the same dependencies. If resolution path changes, half the patching silently becomes dead.

---

### M-24 · Minimal ClusterReviewPanel Test Coverage

|              |                                         |
| ------------ | --------------------------------------- |
| **File**     | `ClusterReviewPanel.test.tsx` (2 tests) |
| **Category** | GAP                                     |

Missing coverage for: loading state, fetch error state, empty member list, confirm dialog cancellation, `onClose` callback.

---

## LOW Severity

### L-1 · `SqlAlchemySuggestionRepository.__init__` Accepts Unused `tenant_id`

|              |                            |
| ------------ | -------------------------- |
| **File**     | `suggestion_repository.py` |
| **Category** | DEAD_CODE                  |

Constructor parameter accepted but never referenced.

---

### L-2 · `_to_model` Ignores `dismissed_at` on Save

|              |                         |
| ------------ | ----------------------- |
| **File**     | `cluster_repository.py` |
| **Category** | GAP                     |

Round-trip fidelity gap: domain → model conversion drops `dismissed_at`.

---

### L-3 · `FaceBox` / `SuggestionDetails` Are Presentation DTOs in Domain Layer

|              |                                    |
| ------------ | ---------------------------------- |
| **File**     | `recognition/domain/suggestion.py` |
| **Category** | ANTIPATTERN                        |

API response shapes defined alongside domain entities. Should be in interface_adapters/schemas.

---

### L-4 · `numpy` Imported at Runtime in Domain `representative.py`

|              |                                        |
| ------------ | -------------------------------------- |
| **File**     | `recognition/domain/representative.py` |
| **Category** | ANTIPATTERN                            |

Could be under `TYPE_CHECKING` guard if only used for type annotations.

---

### L-5 · `_to_domain` Hardcodes Magic Constants for Debug Metrics

|              |                         |
| ------------ | ----------------------- |
| **File**     | `cluster_repository.py` |
| **Category** | COMPLEXITY              |

Tightly couples repository to presentation-layer metric labels.

---

### L-6 · `wp.i18n` Runtime Check is Ineffective

|              |                            |
| ------------ | -------------------------- |
| **File**     | `js/admin/main.tsx` L62–64 |
| **Category** | DEAD_CODE                  |

`@wordpress/i18n` is bundled — the runtime check for `wp.i18n` on the global never fires.

---

### L-7 · Second `import type { DebugMetrics }` at Bottom of File

|              |                         |
| ------------ | ----------------------- |
| **File**     | `types/cluster.ts` L143 |
| **Category** | ANTIPATTERN             |

Stale duplicate import statement far from top of file.

---

### L-8 · Stale Comment: "Assuming This Location or Will Verify"

|              |                          |
| ------------ | ------------------------ |
| **File**     | `label_inference.py` L14 |
| **Category** | DEAD_CODE                |

Implementation note that should be removed. The import path works.

---

### L-9 · Function-Level `import numpy` in `label_inference.py`

|              |                           |
| ------------ | ------------------------- |
| **File**     | `label_inference.py` L185 |
| **Category** | COMPLEXITY                |

Standard library-level dep (`numpy`) buried in a function body. Move to module scope.

---

### L-10 · Empty `Raises:` Docstring Section in `gate.py`

|              |               |
| ------------ | ------------- |
| **File**     | `gate.py` L75 |
| **Category** | DEAD_CODE     |

Either document what it raises or remove the section.

---

### L-11 · `useClusterEvents` Type Assertion on `event.data`

|              |                              |
| ------------ | ---------------------------- |
| **File**     | `useClusterEvents.ts` L49–50 |
| **Category** | ANTIPATTERN                  |

`event.data as string` cast is unnecessary inside an existing try/catch.

---

### L-12 · Overlapping Event-Type Lists in `useClusterEvents`

|              |                              |
| ------------ | ---------------------------- |
| **File**     | `useClusterEvents.ts` L52–66 |
| **Category** | COMPLEXITY                   |

Two `if` blocks listing nearly identical event type arrays. Consolidate into a mapping.

---

### L-13 · `window.confirm()` for Destructive Action

|              |                                 |
| ------------ | ------------------------------- |
| **File**     | `ClusterReviewPanel.tsx` L41–43 |
| **Category** | ANTIPATTERN                     |

Not styleable, not accessible. Use a proper dialog component.

---

### L-14 · Inline Styles Instead of CSS Classes

|              |                                                                                    |
| ------------ | ---------------------------------------------------------------------------------- |
| **Files**    | `SuggestionReviewPanel.tsx` L116–123, L241–254 / `TopClustersSection.tsx` L151–159 |
| **Category** | COMPLEXITY                                                                         |

Grid layout and badge styles defined inline when SCSS classes already exist or should be created.

---

### L-15 · Magic Hex Colors in SCSS Without Design Tokens

|              |                               |
| ------------ | ----------------------------- |
| **File**     | `_cluster-panels.scss` L49–51 |
| **Category** | COMPLEXITY                    |

Hardcoded `#fef2f2`, `#fecaca`, `#991b1b` instead of CSS custom properties.

---

### L-16 · Magic Number `top: 46px` for Sticky Positioning

|              |                        |
| ------------ | ---------------------- |
| **File**     | `_workbench.scss` L486 |
| **Category** | COMPLEXITY             |

Should be a CSS custom property documenting the 32px admin-bar + 14px breathing room.

---

### L-17 · SSE Endpoint is a Heartbeat-Only Stub

|              |                                         |
| ------------ | --------------------------------------- |
| **File**     | `class-recognition-controller.php` L766 |
| **Category** | GAP                                     |

`stream_cluster_events` only emits heartbeats. Frontend `useClusterEvents` connects to a stream that will never deliver real events.

---

### L-18 · Transient Fields as Bare Attributes on ORM Model

|              |                                  |
| ------------ | -------------------------------- |
| **File**     | `db/models/identity.py` L148–150 |
| **Category** | COMPLEXITY                       |

`suggested_label`, `suggested_label_source`, `suggested_label_confidence` are unmapped class attributes (`__allow_unmapped__ = True`). Mixes persistence and presentation concerns.

---

### L-19 · Test `QueryClient` Uses `retry: 1` Instead of `retry: false`

|              |                                                                 |
| ------------ | --------------------------------------------------------------- |
| **Files**    | `ClusterReviewPanel.test.tsx`, `SuggestionReviewPanel.test.tsx` |
| **Category** | ANTIPATTERN                                                     |

Adds non-deterministic timing. Standard test practice is `retry: false`.

---

## Recommended Fix Order

### Phase 1 — Correctness (before merge)

1. **H-1** — Align migration and model constraints
2. **H-5** — Add pose fields to merge-path `MediaIdentity`
3. **H-6** — Remove duplicate `representative_thumbnail_url` field
4. **H-8** — Add `clusteringPending` to `toClusterGroup` adapter
5. **H-2** — Escape LIKE wildcards
6. **M-11** — Remove unreachable dead code in reassign endpoint
7. **M-14** — Replace non-null assertions with proper narrowing

### Phase 2 — Robustness (soon after merge)

8. **H-3** — Replace bare `suppress(Exception)` with logged catch
9. **M-15** — Fix `undefined as T` return type in `http.ts`
10. **M-22** — Improve `FakeSession` to not always silently succeed
11. **M-7** — Move raw SQL to repository layer
12. **M-5** — Replace `object` with typed parameter in `eligibility.py`
13. **M-6** — Inject `ClusteringSettings` instead of instantiating defaults

### Phase 3 — Maintainability (tech debt backlog)

14. **H-4** — Extract shared `_coerce_uuid` / `_ensure_media_identity`
15. **H-7** — Remove/complete skipped tests; fill coverage gaps
16. **H-9** — Extract shared `NullClusterRepository` test utility
17. **M-10** — Declare missing methods on protocol interfaces
18. **M-16** — Centralize query keys
19. **M-17** — Deduplicate face-crop math
20. **M-18** — Batch accept endpoint or `Promise.all`

---

# Consolidated Checklist

## Phase 1 — Correctness (before merge)

- [x] **H-1** — Align `unique_media_identity` and `unique_tenant_identity_label` constraints between `001_identity_schema.py` and `db/models/identity.py`
- [x] **H-5** — Add `pose_pitch`, `pose_yaw`, `pose_roll`, `image_phash` to `MediaIdentity` construction in `cluster_merge.py`
- [x] **H-6** — Remove duplicate `representative_thumbnail_url` field in `SuggestionResponse`
- [x] **H-8** — Add `clusteringPending` property to `toClusterGroup` in `clusterAdapter.ts`
- [x] **H-2** — Escape `%` and `_` wildcards in LIKE queries in `cluster_repository.py`
- [x] **M-11** — Remove unreachable `if request.target_cluster_id:` branch in `reassign_identity` endpoint
- [x] **M-14** — Replace non-null assertions (`!`) in `SuggestionReviewPanel.tsx` with proper type narrowing

## Phase 2 — Robustness (soon after merge)

- [x] **H-3** — Replace `contextlib.suppress(Exception)` with logged exception handling in `cluster_repository.py` and `cluster_merge.py`
- [x] **M-15** — Change `fetchApi` return type to `Promise<T | undefined>` and remove `undefined as T` casts in `http.ts`
- [x] **M-22** — Improve `FakeSession` in `conftest.py` to support configurable return values
- [x] **M-7** — Move raw SQL query from `label_inference.py` to a repository method
- [x] **M-5** — Replace `object` parameter with typed Protocol in `eligibility.py`
- [x] **M-6** — Inject `ClusteringSettings` into `label_inference.py` via parameter instead of instantiating defaults
- [x] **M-9** — Extract gate-absent fallback logic into shared helper; ensure constraint checks are consistent across paths
- [x] **M-8** — Standardize check `name` attributes to a single convention (snake_case)
- [x] **M-1** — Consolidate `ClusterNotFoundError` to a single canonical location in domain layer
- [x] **M-2** — Remove duplicate `block()` / `add_block()` methods in `IdentityClusterBlockRepository`
- [x] **M-3** — Declare `get_member_identities_with_similarity` on `ClusterRepository` Protocol
- [x] **M-10** — Declare missing methods on protocol interfaces; remove `getattr()` + `callable()` guards
- [x] **M-12** — Remove non-check symbols (`ClusterRepository`, `ClusteringSettings`) from `checks/__init__.py` `__all__`
- [x] **M-20** — Sanitize `$_GET['page']` with `sanitize_key()` in `class-admin.php`
- [x] **M-21** — Remove redundant `tenant_id` from either body or query params in dismiss/undismiss PHP endpoints

## Phase 3 — Maintainability (tech debt backlog)

- [x] **H-4** — Extract `_coerce_uuid` / `_ensure_media_identity` to `infrastructure/repositories/_helpers.py`
- [x] **H-7** — Remove or complete skipped tests (`test_api_suggestions.py`, `test_label_inference.py`); delete empty `pass`-only test
- [x] **H-9** — Extract shared `NullClusterRepository` test utility from duplicated stubs across 4+ test files
- [x] **M-4** — Refactor `create()` / `upsert_by_identity_cluster()` in `suggestion_repository.py` to share internal builder
- [x] **M-13** — Add logging to suppressed exception in merge-path suggestion resolution (companion to H-3)
- [x] **M-16** — Move ad-hoc `['cluster-members', clusterId]` query keys to centralized `queryKeys` factory
- [x] **M-17** — Remove duplicate `buildFaceCropStyle` in `TopClustersSection.tsx`; use `FaceThumbnail` component
- [x] **M-18** — Replace sequential `mutateAsync` loop with `Promise.all` or batch endpoint for grouped accepts
- [x] **M-19** — Replace `!important` in SCSS with increased selector specificity
- [x] **M-23** — Consolidate dual-patching in `api_client` fixture to a single injection strategy
- [x] **M-24** — Expand `ClusterReviewPanel.test.tsx` coverage (loading, error, cancel dialog, `onClose`)
- [x] **L-1** — Remove unused `tenant_id` parameter from `SqlAlchemySuggestionRepository.__init__`
- [x] **L-2** — Persist `dismissed_at` in `_to_model` conversion
- [x] **L-3** — Move `FaceBox` / `SuggestionDetails` from domain layer to `interface_adapters/schemas`
- [x] **L-6** — Remove ineffective `wp.i18n` runtime check in `main.tsx`
- [x] **L-7** — Remove duplicate `import type { DebugMetrics }` in `types/cluster.ts`
- [x] **L-8** — Remove stale "Assuming this location" comment in `label_inference.py`
- [x] **L-10** — Remove empty `Raises:` docstring section in `gate.py`
- [x] **L-14** — Replace inline styles with CSS classes in `SuggestionReviewPanel.tsx` and `TopClustersSection.tsx`
- [x] **L-15** — Replace magic hex colors in `_cluster-panels.scss` with CSS custom properties
- [x] **L-19** — Change test `QueryClient` from `retry: 1` to `retry: false`

## Success Criteria

- [x] Zero HIGH findings remaining
- [ ] `PYENV_VERSION=description-service mypy .` passes from `apps/prototype-description-service/`
- [x] `npm run typecheck` passes with zero new errors
- [ ] All existing tests continue to pass (`pytest`, `npm run test`)
- [ ] Branch audit re-run shows no regressions
