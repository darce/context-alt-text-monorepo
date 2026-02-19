# Thumbnail Deprecation: Remove Dead `thumbnail_url` Plumbing (v4.13.1)

## Problem Statement

The `thumbnail_url` field on `MediaIdentity` was designed for server-generated face crop thumbnails. This feature was never completed -- the column is always `NULL` in production. Despite this, `thumbnail_url` plumbing spans ~35 code sites across backend, plugin, and frontend: domain models, response schemas, repository reads, API mappers, TS types, and a dead `IdentityThumbnail` fast-path. The frontend already uses client-side canvas cropping via bbox coordinates, making the server-side thumbnail path fully redundant. Removing this dead code reduces surface area, eliminates confusing dual `thumb_url`/`thumbnail_url` fields, and unblocks cleaner response contracts.

## Workflow Principles

- **Backend-first**: Drop the column and remove backend fields first. Once the backend no longer emits `thumbnail_url`, downstream consumers can be simplified without backward-compat shims.
- **Preserve `acx://` indirection**: The `acx://cluster/{uuid}/media/{id}` URI scheme used by snapshot sync is _not_ part of this deprecation. It resolves to `wp_get_attachment_url()` and is actively used. Evaluate simplifying it in a separate task.
- **Preserve WP attachment thumbnails**: `WorkbenchMediaItem.thumbnailUrl` (WP media library `thumbnail` size) is unrelated to face crop thumbnails and must not be touched.
- **Migration safety**: The Alembic migration to drop the column must be backward-compatible (the column is nullable and never read by application code after the backend changes land).

## Terminology

- **`thumbnail_url`**: The never-populated `String(500)` column on `media_identities` and its propagation through domain objects, schemas, and API responses. **This is what we're removing.**
- **`thumb_url`**: The actively-used thumbnail URL resolved from `acx://` → `wp_get_attachment_url()`. **This stays.**
- **`thumbnailUrl`**: The WP attachment thumbnail size URL on `WorkbenchMediaItem`. **This stays.**
- **`acx://` URI**: Internal URI scheme (`acx://cluster/{uuid}/media/{id}`) stored in `representative_thumb_path` column. Resolved client-side by the PHP mapper. **Not in scope.**

## Current State Analysis

What exists:

- `MediaIdentity.thumbnail_url` column in PostgreSQL -- always `NULL` (no code writes to it).
- `ThumbnailSettings` config class with `base_url` / `storage_dir` -- used only to mount a `StaticFiles` directory that is always empty.
- `_fetch_cluster_thumbnails()` in `suggestion_repository.py` -- window function query over the always-NULL column, always returns `{}`.
- 7 `thumbnail_url` fields across Pydantic response schemas -- always serialize as `null`.
- 6 `thumbnail_url` fields across domain dataclasses (`ClusterRepresentative`, `SuggestionDetails`, `MergeSuggestionDetails`).
- Plugin `resolve_thumb_url()` has a dead `is_http_url()` fast-path (thumb_path is always `acx://`, never HTTP).
- Plugin `ClustersController` proxy-response fallback reads `thumbnail_url` from backend JSON as a fallback for `thumb_url`.
- Frontend `IdentityThumbnail` component has a dead fast-path: `if (identity.thumbnail_url) { setCroppedSrc(null); return; }`.
- Frontend types carry `thumbnail_url` on 5+ interfaces, plus suggestion thumbnail fields that are always `null`/`[]`.
- Dual `thumb_url` + `thumbnail_url` emission in `clusterApiQueries.ts` normalizer and PHP mapper `map_top_unlabeled_representative()`.

What's actively used (must NOT be removed):

- `acx://` URI resolution path (`resolve_representative_thumb_path`, `normalize_thumb_path`, `extract_media_id_from_thumb_path`).
- `WorkbenchMediaItem.thumbnailUrl` (WP attachment thumbnail).
- `wp_get_attachment_url()` fallback in `resolve_thumb_url()` (the non-HTTP branch).
- Canvas-crop thumbnail rendering in `IdentityThumbnail` component (the `croppedSrc` path).

## Proposed Solution

### Phase 1: Backend -- Remove `thumbnail_url` from Application Layer

Strip `thumbnail_url` from domain models, response schemas, repository reads, router mappings, and config. This makes the backend stop emitting `thumbnail_url` in API responses.

### Phase 2: Backend -- Drop Column via Migration

Create an Alembic migration to `DROP COLUMN thumbnail_url` from `media_identities`. This is safe because:
- The column is nullable and always NULL.
- After Phase 1, no application code reads it.

### Phase 3: Plugin -- Remove Backward-Compat Shims

With the backend no longer emitting `thumbnail_url`:
- Remove the `thumbnail_url` proxy-response fallback in `ClustersController`.
- Remove the dead `is_http_url()` branch in `resolve_thumb_url()`.
- Collapse dual `thumb_url`/`thumbnail_url` emission to `thumb_url` only.

### Phase 4: Frontend -- Remove Dead Types and Fast-Paths

- Remove `thumbnail_url` from all TS type interfaces.
- Remove the `IdentityThumbnail` fast-path.
- Collapse the `clusterApiQueries.ts` normalizer.
- Remove suggestion thumbnail fields (`cluster_thumbnails`, `identity_thumbnail_url`, etc.).

## Patterns to Follow

### Pattern: Remove Field from Pydantic Schema

```python
# Before
class ClusterMemberResponse(BaseModel):
    identity_uuid: str
    thumbnail_url: str | None = None  # ← remove
    media_id: int

# After
class ClusterMemberResponse(BaseModel):
    identity_uuid: str
    media_id: int
```

### Pattern: Remove Dead Repository Method

```python
# Before (suggestion_repository.py)
def _fetch_cluster_thumbnails(self, session, cluster_ids, per_cluster_limit=4):
    # 30-line window function query over always-NULL column
    ...
    return {}  # always empty

# After
# Method deleted entirely. Callers updated to remove thumbnail attachment.
```

### Pattern: Simplify PHP Mapper (Collapse Dual Fields)

```php
// Before (map_top_unlabeled_representative)
return array(
    'thumb_url'     => $this->resolve_thumb_url( $member_row, $media_id ),
    'thumbnail_url' => $this->resolve_thumb_url( $member_row, $media_id ), // ← remove
    'media_url'     => $this->resolve_media_url( $media_id ),
);

// After
return array(
    'thumb_url' => $this->resolve_thumb_url( $member_row, $media_id ),
    'media_url' => $this->resolve_media_url( $media_id ),
);
```

### Pattern: Remove IdentityThumbnail Fast-Path

```tsx
// Before
useEffect(() => {
  if (identity.thumbnail_url) {   // ← dead branch
    setCroppedSrc(null);
    return;
  }
  // canvas crop logic...
}, [identity.thumbnail_url, ...deps]);

// After
useEffect(() => {
  // canvas crop logic (always runs)
}, [...deps]);  // thumbnail_url removed from deps
```

## Functions to Change

### Backend

| File | Line | Change |
| --- | --- | --- |
| `recognition/config/settings.py` | 19–24 | **Remove** `ThumbnailSettings` class. |
| `recognition/config/settings.py` | 62 | **Remove** `thumbnail: ThumbnailSettings` field from `RecognitionSettings`. |
| `api/main.py` | 7 | **Remove** `from fastapi.staticfiles import StaticFiles` import. |
| `api/main.py` | 79–92 | **Remove** entire `StaticFiles` thumbnail mount block. |
| `api/logging_config.py` | 55–59 | **Remove** dead `RecognitionFilter` branch for `recognition.infrastructure.thumbnail`. |
| `db/models/identity.py` | 63 | **Remove** `thumbnail_url` column from `MediaIdentity` model. |
| `recognition/domain/representative.py` | 36 | **Remove** `thumbnail_url` field from `ClusterRepresentative`. |
| `recognition/domain/suggestion_details.py` | 33, 37, 42 | **Remove** `identity_thumbnail_url`, `representative_thumbnail_url`, `cluster_thumbnails` from `SuggestionDetails`. |
| `recognition/domain/suggestion_details.py` | 61, 65 | **Remove** `cluster_a_representative_thumbnail_url`, `cluster_b_representative_thumbnail_url` from `MergeSuggestionDetails`. |
| `recognition/infrastructure/repositories/suggestion_repository.py` | 134, 140 | **Remove** `thumbnail_url` assignments in `_to_details()`. |
| `recognition/infrastructure/repositories/suggestion_repository.py` | 191–220 | **Delete** `_fetch_cluster_thumbnails()` method entirely. |
| `recognition/infrastructure/repositories/suggestion_repository.py` | 269–280 | **Remove** `_fetch_cluster_thumbnails()` call and thumbnail attachment in `list_pending_with_details()`. |
| `recognition/infrastructure/repositories/suggestion_repository.py` | 204, 211, 214 | **Remove** `MediaIdentity.thumbnail_url` from SELECT and WHERE clauses in representative subquery. |
| `recognition/infrastructure/repositories/cluster_repository.py` | 214 | **Remove** `MediaIdentity.thumbnail_url` from SELECT in `_build_fallback_representatives()`. |
| `recognition/infrastructure/repositories/cluster_repository.py` | 248 | **Remove** `thumbnail_url=row.thumbnail_url` assignment. |
| `recognition/infrastructure/repositories/cluster_repository.py` | 736–737 | **Update** docstring to remove `thumbnail_url` mention. |
| `recognition/infrastructure/repositories/cluster_repository.py` | 970 | **Remove** `thumbnail_url=identity.thumbnail_url` in `_to_domain()`. |
| `recognition/infrastructure/repositories/merge_suggestion_repository.py` | 217–221 | **Remove** `thumbnail_url` reads in `_to_details_model()`. |
| `recognition/infrastructure/repositories/merge_suggestion_repository.py` | 237 | **Remove** `"representative_thumbnail_url"` from dict in `_build_cluster_details()`. |
| `recognition/interface_adapters/http/schemas/responses.py` | 46 | **Remove** `thumbnail_url` from `ClusterMemberResponse`. |
| `recognition/interface_adapters/http/schemas/responses.py` | 58 | **Remove** `thumbnail_url` from `IdentityResponse`. |
| `recognition/interface_adapters/http/schemas/responses.py` | 170, 174, 179 | **Remove** `identity_thumbnail_url`, `representative_thumbnail_url`, `cluster_thumbnails` from `SuggestionResponse`. |
| `recognition/interface_adapters/http/schemas/responses.py` | 201, 205 | **Remove** `cluster_a/b_representative_thumbnail_url` from `MergeSuggestionResponse`. |
| `recognition/interface_adapters/http/routers/clusters.py` | 338 | **Remove** `thumb_url=rep.thumbnail_url` in top-unlabeled response builder. |
| `recognition/interface_adapters/http/routers/clusters.py` | 427 | **Remove** `thumbnail_url=identity.thumbnail_url` in `list_cluster_members`. |
| `recognition/interface_adapters/http/routers/suggestions.py` | 293–302 | **Remove** `identity_thumbnail_url`, `representative_thumbnail_url`, `cluster_thumbnails` mappings. |
| `recognition/interface_adapters/http/routers/suggestions.py` | 348–359 | **Remove** `cluster_a/b_representative_thumbnail_url` mappings. |
| `recognition/interface_adapters/http/deps/stores.py` | 234 | **Remove** `"thumbnail_url"` from identity listing payload dict. |
| `recognition/application/regression_harness/report_builder.py` | 448–449 | **Remove** conditional `thumbnail_url` block. |

### Plugin

| File | Line | Change |
| --- | --- | --- |
| `src/api/class-clusters-controller.php` | 206–210 | **Remove** `thumbnail_url` proxy-response fallback block in `list_top_unlabeled_clusters`. |
| `src/sovereign/mappers/trait-maps-response-fields.php` | 26–40 | **Simplify** `resolve_thumb_url()` — remove dead `is_http_url()` fast-path branch. |
| `src/sovereign/mappers/class-cluster-response-mapper.php` | 178 | **Remove** duplicate `'thumbnail_url'` key from `map_top_unlabeled_representative()`. |
| `src/sovereign/mappers/class-cluster-response-mapper.php` | 163 | **Rename** `'thumbnail_url'` → `'thumb_url'` in `map_cluster_identity()` (align with `thumb_url` convention). |
| `src/sovereign/mappers/class-member-response-mapper.php` | 68 | **Rename** `'thumbnail_url'` → `'thumb_url'` in member mapper output. |
| `src/sovereign/repositories/class-clusters-repository.php` | 511 | **Simplify** `resolve_representative_thumb_path()` — remove `thumbnail_path` fallback, keep `thumb_path` only. |
| `src/sovereign/repositories/class-identity-members-repository.php` | 436 | **Simplify** `normalize_thumb_path()` — remove `thumbnail_path` fallback, keep `thumb_path` only. |

### Frontend

| File | Line | Change |
| --- | --- | --- |
| `js/admin/api/recognition/types/identity.ts` | 24 | **Remove** `thumbnail_url` from `ClusterIdentity`. |
| `js/admin/api/recognition/types/identity.ts` | 70 | **Remove** `thumbnail_url` from `DetectedIdentity`. |
| `js/admin/api/recognition/types/cluster.ts` | 21 | **Remove** `thumbnail_url` from `TopUnlabeledRepresentative`. |
| `js/admin/api/recognition/types/suggestion.ts` | 28–37 | **Remove** `identity_thumbnail_url`, `representative_thumbnail_url`, `cluster_thumbnails` from `PendingSuggestion`. |
| `js/admin/api/recognition/types/suggestion.ts` | 67–71 | **Remove** `cluster_a/b_representative_thumbnail_url` from `PendingMergeSuggestion`. |
| `js/admin/api/recognition/clusterApiQueries.ts` | 24–28 | **Simplify** `normalizeTopUnlabeledRepresentative()` — remove `thumbnail_url` fallback, emit `thumb_url` only. |
| `js/admin/api/recognition/identitySuggestionMappers.ts` | 19–28 | **Remove** `identity_thumbnail_url`, `representative_thumbnail_url`, `cluster_thumbnails` from `PendingSuggestionApiResponse`. |
| `js/admin/api/recognition/identitySuggestionMappers.ts` | 43–47 | **Remove** `cluster_a/b_representative_thumbnail_url` from `PendingMergeSuggestionApiResponse`. |
| `js/admin/api/recognition/identitySuggestionMappers.ts` | 72–81 | **Remove** forwarded thumbnail fields in `mapPendingSuggestions()`. |
| `js/admin/api/recognition/identitySuggestionMappers.ts` | 113–117 | **Remove** forwarded thumbnail fields in `mapPendingMergeSuggestions()`. |
| `js/admin/pages/roster/IdentityThumbnail.tsx` | 25–27 | **Remove** `thumbnail_url` fast-path in `useEffect`. |
| `js/admin/pages/roster/IdentityThumbnail.tsx` | 103 | **Remove** `identity.thumbnail_url` from `useEffect` dependency array. |
| `js/admin/pages/roster/IdentityThumbnail.tsx` | 105 | **Simplify** resolved src: `croppedSrc ?? mediaMeta?.url ?? null`. |
| `js/admin/pages/workbench/identity-clusters/SuggestionCards.tsx` | 62–63 | **Remove** `cluster_thumbnails` grid rendering path. |

## Related Files

| File | Note |
| --- | --- |
| `db/migrations/versions/001_identity_schema.py` | Historical migration defining the column. Do NOT modify -- add a new migration. |
| `recognition/interface_adapters/http/routers/clusters.py` L176–177, L220 | `acx://` URI generation for snapshot sync. Not in scope but related. |
| `src/sovereign/mappers/class-cluster-response-mapper.php` L243 | `extract_media_id_from_thumb_path()` parses `acx://`. Not in scope. |
| `packages/shared-contracts/schemas/workbench-media-item.schema.json` | `thumbnailUrl` is WP attachment thumbnail. Not in scope. |
| `docs/epics/v0.1.0/wp-sovereign-cluster-epic.md` L150–153 | Epic references planned thumbnail cleanup. |
| `docs/agentic/contracts/cluster-snapshot-api.md` L59, L75 | Documents `acx://` URI format. Not in scope. |

---

# Consolidated Checklist

## Phase 1: Backend -- Remove Application-Layer `thumbnail_url`

- [ ] Remove `ThumbnailSettings` class and `thumbnail` field from `RecognitionSettings` (`settings.py`).
- [ ] Remove `StaticFiles` import and thumbnail mount block from `api/main.py`.
- [ ] Remove dead `RecognitionFilter` branch for `recognition.infrastructure.thumbnail` (`logging_config.py`).
- [ ] Remove `thumbnail_url` field from `ClusterRepresentative` domain object (`representative.py`).
- [ ] Remove 5 thumbnail fields from `SuggestionDetails` and `MergeSuggestionDetails` (`suggestion_details.py`).
- [ ] Delete `_fetch_cluster_thumbnails()` method from `suggestion_repository.py`.
- [ ] Remove `thumbnail_url` reads from `_to_details()` in `suggestion_repository.py`.
- [ ] Remove `_fetch_cluster_thumbnails()` call + attachment in `list_pending_with_details()`.
- [ ] Remove `MediaIdentity.thumbnail_url` from SELECT/WHERE in representative subquery (`suggestion_repository.py`).
- [ ] Remove `thumbnail_url` from `_build_fallback_representatives()` and `_to_domain()` in `cluster_repository.py`.
- [ ] Remove `thumbnail_url` reads from `merge_suggestion_repository.py`.
- [ ] Remove `thumbnail_url` from 7 Pydantic response schemas (`responses.py`).
- [ ] Remove `thumbnail_url` mappings from `clusters.py` router (top-unlabeled, list_cluster_members).
- [ ] Remove `thumbnail_url` mappings from `suggestions.py` router (pending, merge).
- [ ] Remove `"thumbnail_url"` from identity listing payload in `stores.py`.
- [ ] Remove conditional `thumbnail_url` block from `report_builder.py`.
- [ ] Remove `thumbnail_url` column from `MediaIdentity` SQLAlchemy model (`identity.py`).
- [ ] Update backend tests: remove `thumbnail_url` from conftest fakes, test fixtures, and assertions.
- [ ] Verify: `make check` (ruff + mypy + pytest).

## Phase 2: Backend -- Drop Column Migration

- [ ] Create Alembic migration: `ALTER TABLE media_identities DROP COLUMN thumbnail_url`.
- [ ] Test migration up/down locally against development database.
- [ ] Verify: `make check`.

## Phase 3: Plugin -- Remove Backward-Compat Shims

- [ ] Remove `thumbnail_url` proxy-response fallback in `ClustersController::list_top_unlabeled_clusters`.
- [ ] Simplify `resolve_thumb_url()` in trait: remove dead `is_http_url()` fast-path.
- [ ] Remove duplicate `'thumbnail_url'` key from `map_top_unlabeled_representative()`.
- [ ] Rename `'thumbnail_url'` → `'thumb_url'` in `map_cluster_identity()` and member mapper (or remove if frontend doesn't read it).
- [ ] Simplify `resolve_representative_thumb_path()` -- remove `thumbnail_path` fallback.
- [ ] Simplify `normalize_thumb_path()` -- remove `thumbnail_path` fallback.
- [ ] Update plugin tests: `ClustersControllerTest`, `ClusterResponseMapperTest` assertions.
- [ ] Verify: `composer test`, `composer phpstan`.

## Phase 4: Frontend -- Remove Dead Types and Fast-Paths

- [ ] Remove `thumbnail_url` from `ClusterIdentity`, `DetectedIdentity`, `TopUnlabeledRepresentative` types.
- [ ] Remove suggestion thumbnail fields from `PendingSuggestion` and `PendingMergeSuggestion` types.
- [ ] Simplify `normalizeTopUnlabeledRepresentative()` -- collapse to `thumb_url` only.
- [ ] Remove thumbnail fields from `PendingSuggestionApiResponse` and `PendingMergeSuggestionApiResponse`.
- [ ] Remove forwarded thumbnail fields from `mapPendingSuggestions()` and `mapPendingMergeSuggestions()`.
- [ ] Remove `IdentityThumbnail` dead fast-path and `thumbnail_url` from dependency array.
- [ ] Remove `cluster_thumbnails` grid rendering path from `SuggestionCards.tsx`.
- [ ] Update frontend tests: `recognitionApi.test.ts`, `IdentityThumbnail.test.tsx`, `ClusterReviewPanel.test.tsx`, `SuggestionReviewPanel.test.tsx`, `IdentityClusterList.test.tsx`.
- [ ] Verify: `npm run type-check`, `npm test`.

## Stretch Goals

- [ ] Evaluate replacing `acx://` thumb-path indirection with direct `attachment_id` lookup (simplifies mapper trait).
- [ ] Unify response field naming: standardize on `thumb_url` everywhere (currently mixed `thumb_url`/`thumbnail_url`).

## Success Criteria

- [ ] `MediaIdentity.thumbnail_url` column dropped from PostgreSQL.
- [ ] No Python code references `thumbnail_url` (domain, schema, repository, router).
- [ ] `ThumbnailSettings` and `StaticFiles` mount removed.
- [ ] No PHP code emits or reads `thumbnail_url` in API responses.
- [ ] No TypeScript type includes `thumbnail_url` (except `WorkbenchMediaItem.thumbnailUrl` which is WP-native).
- [ ] `IdentityThumbnail` component uses canvas crop exclusively (no `thumbnail_url` fast-path).
- [ ] `make check` passes (ruff + mypy + pytest).
- [ ] `composer test` and `composer phpstan` pass.
- [ ] `npm run type-check` and `npm test` pass.
