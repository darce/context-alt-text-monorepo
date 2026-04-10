# 4.13.3 Phase 2 -- Plugin Thumbnail Deprecation + Proxy-to-Facade

## Problem Statement

The WordPress plugin still retains a backward-compat fallback in `ClustersController` that reads `thumbnail_url` from the (now-removed) backend field, and calls PHP helpers (`resolve_thumb_url`, `resolve_representative_thumb_path`, `normalize_thumb_path`) that chain through a dead `is_http_url()` fast-path and a `thumbnail_path` fallback key that no longer exists in any upstream response. Additionally, while `ClustersController` already serves local projection reads when sync state is present, it maintains a fallback path that proxies read requests for top-unlabeled clusters to the backend HTTP API; replacing this with a `ClusterFacade` that reads sovereign local tables makes the plugin fully offline-first for reads.

## Workflow Principles

- **Plugin-boundary only**: All changes are inside `apps/prototype-wp-alt-context/`. No backend changes.
- **Greenfield remove-over-flag**: Delete shims outright. No feature flags.
- **acx:// URI is in scope to simplify, not remove**: `resolve_thumb_url()` resolves `acx://` URIs via `wp_get_attachment_url()`. Keep that; remove only the dead `is_http_url()` fast-path above it.
- **Defer mapper emissions to Phase 3**: The frontend still reads `thumbnail_url` directly in cluster member UIs and identity types. Do not rename or remove `thumbnail_url` keys from `map_cluster_identity` or `map_cluster_member` until Phase 3. Only remove the dead double-emission from `map_top_unlabeled_representative`.
- **ClusterFacade reads sovereign tables only**: The facade must never make backend HTTP calls. `SyncPullJob` remains the sole component that calls the backend.

## Terminology

- **`thumbnail_url`**: Dead field removed from backend in Phase 1. Plugin mappers still emit it for the frontend, but we will defer removing it until Phase 3 to avoid cross-phase contract breakage.
- **`thumb_url`**: Live canonical field. Resolved from `acx://` URI via `wp_get_attachment_url()`. **Preserve.**
- **`thumbnail_path` key**: Dead fallback key read from upstream responses (replaced by `thumb_path`). **Remove from helper methods.**
- **`is_http_url()` fast-path**: Dead branch in `resolve_thumb_url()` -- backend stopped emitting HTTP URLs for thumbs. **Remove.**
- **Proxy-to-facade**: Replace `ClustersController::list_top_unlabeled_clusters` HTTP proxy fallback call with a `ClusterFacade` read from sovereign tables.
- **ClusterFacade**: New PHP service class to encapsulate sovereign-table cluster reads. Introduced by this task.

## Current State Analysis

- `ClustersController::list_top_unlabeled_clusters` (L222--226): reads `$rep['thumbnail_url']` as a legacy fallback when `thumb_url` is absent -- backend no longer emits this field.
- `class-cluster-response-mapper.php` (L163): `map_cluster_identity()` outputs `'thumbnail_url'` key -- defer removal to Phase 3 (frontend dependency).
- `class-cluster-response-mapper.php` (L177--178): `map_top_unlabeled_representative()` emits both `'thumb_url'` and `'thumbnail_url'` with the same value -- removing the duplicate `thumbnail_url` is safe as frontend top-unlabeled types rely on `thumb_url`.
- `class-member-response-mapper.php` (L68): `map_cluster_member()` emits `'thumbnail_url'` key -- defer removal to Phase 3 (frontend dependency).
- `trait-maps-response-fields.php` (L28, L61): `resolve_thumb_url()` passes through an `is_http_url()` branch that will never be true (thumb paths are always `acx://` URIs now).
- `class-clusters-repository.php` (L535): `resolve_representative_thumb_path()` reads `$representative['thumbnail_path']` as a fallback -- `thumbnail_path` is not present in sovereign table rows.
- `class-identity-members-repository.php` (L436): `normalize_thumb_path()` reads `$member['thumbnail_path']` as a fallback -- same issue.
- `ClustersController::list_top_unlabeled_clusters`: still proxies the cluster list request to the backend when falling back, creating a hard dependency on backend availability for every workbench page load.

## Proposed Solution

Perform the work in three sequential sub-phases:

1. **Shim removal**: Strip the dead `thumbnail_url` fallback block from the controller, remove dead fallback branches from repository helpers, and remove the duplicate key from the top-unlabeled mapper. Defer member/identity mapper key removals to Phase 3.
2. **ClusterFacade scaffold**: Introduce a `ClusterFacade` class with an interface/stub and tests first (scaffolding-first rule), then implement the sovereign-table read path.
3. **Wire ClusterFacade into ClustersController**: Replace the proxy call with a `ClusterFacade::list_top_unlabeled()` call. Remove the now-dead `thumbnail_url` fallback block.

## Patterns to Follow

### Pattern: Remove Dead Output Key from Mapper

```php
// Before (class-cluster-response-mapper.php)
return array(
    'thumb_url'     => $this->resolve_thumb_url( $member_row, $media_id ),
    'thumbnail_url' => $this->resolve_thumb_url( $member_row, $media_id ), // dead -- remove
    'media_url'     => $this->resolve_media_url( $media_id ),
);

// After
return array(
    'thumb_url' => $this->resolve_thumb_url( $member_row, $media_id ),
    'media_url' => $this->resolve_media_url( $media_id ),
);
```

### Pattern: Simplify resolve_thumb_url (Remove is_http_url Branch)

```php
// Before (trait-maps-response-fields.php)
private function resolve_thumb_url( array $member_row, int $media_id ): ?string {
    $thumb_path = trim( (string) ( $member_row['thumb_path'] ?? '' ) );
    if ( '' !== $thumb_path && $this->is_http_url( $thumb_path ) ) {
        return $thumb_path;  // dead: thumb_path is always acx://, never HTTP
    }
    // acx:// resolution via wp_get_attachment_url() ...
}

// After
private function resolve_thumb_url( array $member_row, int $media_id ): ?string {
    $thumb_path = trim( (string) ( $member_row['thumb_path'] ?? '' ) );
    // acx:// resolution via wp_get_attachment_url() -- only path now
    ...
}
// is_http_url() method deleted entirely
```

### Pattern: Simplify thumbnail_path Fallback Keys

```php
// Before (class-clusters-repository.php resolve_representative_thumb_path)
$thumb_path = trim( (string) ( $representative['thumb_path'] ?? $representative['thumbnail_path'] ?? '' ) );

// After
$thumb_path = trim( (string) ( $representative['thumb_path'] ?? '' ) );
```

### Pattern: ClusterFacade Service (Scaffolding-First)

```php
// src/sovereign/class-cluster-facade.php
namespace AltContext\Sovereign;

class ClusterFacade {
    public function __construct( private \wpdb $wpdb ) {}

    /**
     * Returns top unlabeled clusters from sovereign tables.
     *
     * @param string $tenant_id  Tenant UUID.
     * @param int    $limit      Maximum clusters to return.
     * @return array<int, array<string, mixed>>
     * @throws \RuntimeException If the query fails.
     */
    public function list_top_unlabeled( string $tenant_id, int $limit ): array {
        // Orchestrate reads through ClustersRepository and IdentityMembersRepository instead of raw $wpdb
        throw new \RuntimeException( 'TODO: implement sovereign read via repositories' );
    }
}
```

## Functions to Change

### Shim Removal (Plugin)

| File | Line | Change |
| --- | --- | --- |
| `src/api/class-clusters-controller.php` | 222--226 | **Remove** `thumbnail_url` legacy fallback block in `list_top_unlabeled_clusters`. |
| `src/sovereign/mappers/class-cluster-response-mapper.php` | 178 | **Remove** duplicate `'thumbnail_url'` key from `map_top_unlabeled_representative()`. |
| `src/sovereign/mappers/trait-maps-response-fields.php` | 28 | **Remove** `is_http_url()` fast-path branch in `resolve_thumb_url()`. |
| `src/sovereign/mappers/trait-maps-response-fields.php` | 61--65 | **Delete** `is_http_url()` private method entirely. |
| `src/sovereign/repositories/class-clusters-repository.php` | 535 | **Remove** `$representative['thumbnail_path'] ??` fallback in `resolve_representative_thumb_path()`. |
| `src/sovereign/repositories/class-identity-members-repository.php` | 436 | **Remove** `$member['thumbnail_path'] ??` fallback in `normalize_thumb_path()`. |

### ClusterFacade Introduction

| File | Line | Change |
| --- | --- | --- |
| `src/sovereign/class-cluster-facade.php` | -- | **[NEW]** `ClusterFacade` class with `list_top_unlabeled()` method. |
| `src/api/class-clusters-controller.php` | -- | **Inject** `ClusterFacade` via constructor; replace proxy call with facade in `list_top_unlabeled_clusters`. |
| `src/api/class-api.php` | -- | **Construct** `ClusterFacade` and inject into `RecognitionController`. |
| `src/api/class-recognition-controller.php` | -- | **Wire** `ClusterFacade` from `Api` into `ClustersController`. |

## Related Files

| File | Note |
| --- | --- |
| `src/sovereign/mappers/trait-maps-response-fields.php` | `resolve_thumb_url()` is used by both cluster and member mappers. Simplification affects both. |
| `src/sovereign/repositories/class-clusters-repository.php` | `resolve_representative_thumb_path()` reads from sovereign rows. The `thumbnail_path` key it reads as a fallback no longer exists in synced data. |
| `src/sovereign/sync/class-snapshot-client.php` | Snapshot sync is NOT in scope. It remains the sole HTTP caller. |
| `js/admin/api/recognition/types/cluster.ts` | Frontend types -- Phase 3 will remove `thumbnail_url` here. For this phase, verify the frontend does not break if `thumbnail_url` is absent from PHP responses. |
| `docs/tasks/4.0/4.13.1/thumbnail-deprecation-task-plan.md` | Phase 3 and 4 sections of 4.13.1 plan provide the original line-level detail. |

---

# Consolidated Checklist

## Phase 0: Scaffolding

- [x] Add `ClusterFacade` interface/stub (`src/sovereign/class-cluster-facade.php`) with method signatures, type hints, docstrings, and `throw new \RuntimeException('TODO')` bodies.
- [x] Create `tests/Unit/Sovereign/ClusterFacadeTest.php` with `@group scaffold` stub tests for `list_top_unlabeled()`.
- [x] Verify scaffolds pass PHPCS and PHPStan: `composer cs-check && composer phpstan`.

## Phase 1: Shim Removal

- [x] Remove `thumbnail_url` fallback block (L222--226) from `ClustersController::list_top_unlabeled_clusters`.
- [x] Remove dead `is_http_url()` branch (L28) from `resolve_thumb_url()` in `trait-maps-response-fields.php`.
- [x] Delete `is_http_url()` private method (L61--65) from `trait-maps-response-fields.php`.
- [x] Remove `$representative['thumbnail_path'] ??` (L535) from `resolve_representative_thumb_path()` in `class-clusters-repository.php`.
- [x] Remove `$member['thumbnail_path'] ??` (L436) from `normalize_thumb_path()` in `class-identity-members-repository.php`.
- [x] Remove duplicate `'thumbnail_url'` key (L178) from `map_top_unlabeled_representative()`.
- [x] Update existing plugin tests: remove `thumbnail_url` key assertions in `ClusterResponseMapperTest` for the top-unlabeled representative.
- [x] Verify: `composer test && composer phpstan`.

## Phase 2: ClusterFacade Implementation

- [x] Implement `ClusterFacade::list_top_unlabeled()` by orchestrating reads via `ClustersRepository` and `IdentityMembersRepository` (do not duplicate `$wpdb` SQL).
- [x] Use existing repository methods to assemble cluster data, ensuring `resolve_representative_thumb_path()` is correctly applied by the repository layer.
- [x] Wire `ClusterFacade` into `ClustersController` constructor; replace proxy call in `list_top_unlabeled_clusters`.
- [x] Construct `ClusterFacade` in `Api` and pass it down through `RecognitionController`.
- [x] Remove the backend proxy HTTP fallback call from `list_top_unlabeled_clusters` once facade is wired.
- [x] Fill in `ClusterFacadeTest` with real assertions covering: empty result, single cluster + representative, label/curation_state mapping.
- [x] Verify: `composer test && composer phpstan`.

## Phase 3: Verification + Quality Gates

- [x] Run `composer test` (PHPUnit full suite).
- [x] Run `composer phpstan`.
- [x] Run `composer cs-check` (PHPCS).
- [x] Confirm top-unlabeled representative responses no longer emit duplicate `thumbnail_url`.
- [x] Confirm workbench loads clusters when backend is stopped (offline-first verified).

## Success Criteria

- [x] DEFERRED TO PHASE 3: `thumbnail_url` emission in cluster identity and member API responses.
- [x] Duplicate `thumbnail_url` key removed from `map_top_unlabeled_representative`.
- [x] `is_http_url()` method deleted; `resolve_thumb_url()` only uses `acx://` resolution path.
- [x] `thumbnail_path` key removed from all `$member`/`$representative` array reads.
- [x] `ClustersController::list_top_unlabeled_clusters` reads from sovereign tables via `ClusterFacade` (no backend HTTP call).
- [x] `SyncPullJob` remains the only component that makes backend HTTP calls.
- [x] `composer test`, `composer phpstan`, and `composer cs-check` all pass.
- [x] Workbench cluster list loads while backend is unreachable (offline-first verified).

## Session Notes

### 2026-02-20 - Session 1 (Plan Authored)

- Phase 2 task plan generated from `TASK_PLAN.template.md`.
- Plugin thumbnail state confirmed by live `grep` before writing.
- Proxy-to-facade scope added per `v0.1.0-completion-task-plan.md Phase 2`.
- Line numbers: `class-clusters-controller.php` L222--226, `class-cluster-response-mapper.php` L163/177-178, `class-member-response-mapper.php` L68, `trait-maps-response-fields.php` L28/61, `class-clusters-repository.php` L535, `class-identity-members-repository.php` L436.

### 2026-02-21 - Session 2 (Correctness Review Findings)

- [HIGH][CONTRACT] `map_cluster_identity()` and `map_cluster_member()` are not safe to rename from `thumbnail_url` to `thumb_url` in Phase 2:
  - Frontend still reads `thumbnail_url` directly in cluster member UIs (`js/admin/pages/workbench/identity-clusters/ClusterLabelingPanel.tsx`, `js/admin/pages/workbench/identity-clusters/ClusterReviewPanel.tsx`) and identity types (`js/admin/api/recognition/types/identity.ts`).
  - Current Phase 2 guidance would break those screens unless frontend changes land in the same phase.
- [MEDIUM][PATH] DI wiring target is incorrect: `src/class-plugin.php` does not exist in this plugin. Composition currently happens via `src/api/class-recognition-controller.php` (constructed by `src/api/class-api.php`).
- [MEDIUM][ARCH] Problem statement overstates current behavior:
  - `ClustersController` does not proxy all reads today; it already serves local projection reads when sync state is present.
  - Phase 2 should explicitly target remaining proxy fallback paths (starting with top-unlabeled), not re-describe already-offline paths as missing.
- [MEDIUM][SCOPE] Phase 2 success criteria currently require zero `thumbnail_url` emission in all cluster/member PHP responses, but Phase 3 is the documented frontend deprecation phase. This cross-phase contract should be corrected (either defer member/list mapper key removal to Phase 3 or include coupled frontend changes in Phase 2).
- [MEDIUM][DESIGN] `ClusterFacade` checklist currently specifies direct `$wpdb` reads for top-unlabeled logic, which duplicates existing repository responsibilities. Prefer facade orchestration over raw-query duplication to avoid divergent SQL and duplicated thumb-path normalization rules.

### 2026-02-21 - Session 3 (Follow-up Corrections Applied)

- Applied follow-up corrections from Session 2:
  - Deferred member/identity mapper `thumbnail_url` removal to Phase 3.
  - Corrected DI wiring paths to `class-api.php` + `class-recognition-controller.php`.
  - Corrected facade implementation guidance to repository orchestration (no duplicated raw SQL).
  - Corrected Phase 3 verification checklist to match deferred scope.
