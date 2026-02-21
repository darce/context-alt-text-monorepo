# Current Task: Thumbnail Deprecation -- Phase 1 (Backend Application Layer + Column Drop)

**Started**: 2026-02-20
**Task Doc**: [thumbnail-deprecation-task-plan.md](../4.13.1/thumbnail-deprecation-task-plan.md)
**Status**: IN_PROGRESS

## Objective

Remove all `thumbnail_url` plumbing from the Python recognition service -- domain models, Pydantic schemas, repository queries, router mappings, config, and the `MediaIdentity` SQLAlchemy column -- and remove the baseline schema column definition per greenfield policy (no forward Alembic migration).

## Context

Phase 3 (Dual-Write + Pull Sync) is merged to `main`. The epic's next gate is removing dead `thumbnail_url` code. The field is always `NULL` in production; no code writes to it. Downstream consumers (plugin, frontend) have backward-compat shims that can only be deleted once the backend stops emitting `thumbnail_url` in API responses.

- Why this matters: ~35 code sites carry dead plumbing. Removing them reduces surface area, eliminates a confusing dual `thumb_url`/`thumbnail_url` emission, and unblocks the plugin/frontend cleanup (Phases 2-3 of the completion plan).
- Full site inventory: `docs/tasks/4.0/4.13.1/thumbnail-deprecation-task-plan.md` -- Functions to Change tables.
- Related epic: `docs/epics/v0.1.0/wp-sovereign-cluster-epic.md`.

## Key Files

| File | Purpose |
|------|---------|
| `apps/prototype-description-service/recognition/config/settings.py` | Remove `ThumbnailSettings` class and `thumbnail` field |
| `apps/prototype-description-service/api/main.py` | Remove `StaticFiles` thumbnail mount |
| `apps/prototype-description-service/db/models/identity.py` | Remove `thumbnail_url` SQLAlchemy column |
| `apps/prototype-description-service/recognition/domain/representative.py` | Remove `thumbnail_url` from `ClusterRepresentative` |
| `apps/prototype-description-service/recognition/domain/suggestion_details.py` | Remove 5 thumbnail fields |
| `apps/prototype-description-service/recognition/infrastructure/repositories/suggestion_repository.py` | Delete `_fetch_cluster_thumbnails()`, remove reads |
| `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py` | Remove `thumbnail_url` from SELECT + `_to_domain()` |
| `apps/prototype-description-service/recognition/infrastructure/repositories/merge_suggestion_repository.py` | Remove `thumbnail_url` reads |
| `apps/prototype-description-service/recognition/interface_adapters/http/schemas/responses.py` | Remove 7 `thumbnail_url` fields from Pydantic schemas |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | Remove `thumbnail_url` mappings |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/suggestions.py` | Remove `thumbnail_url` mappings |
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/stores.py` | Remove `"thumbnail_url"` from identity payload |
| `apps/prototype-description-service/recognition/application/regression_harness/report_builder.py` | Remove conditional `thumbnail_url` block |
| `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` | Remove baseline `thumbnail_url` column definition (greenfield policy) |

## Technical Notes

- **Greenfield project -- no data migration required.** Per the Greenfield Policy in `GEMINI.md`, the database is wiped and rebuilt after every schema change. There is no production data to preserve. The correct approach is to **remove `thumbnail_url` directly from the baseline migration** (`db/migrations/versions/001_identity_schema.py`) and from the SQLAlchemy model -- do NOT create a new forward Alembic migration.
- `acx://` URI resolution (`resolve_representative_thumb_path`, `normalize_thumb_path`) is **not** in scope -- it is actively used and must not be touched.
- `WorkbenchMediaItem.thumbnailUrl` (WP attachment thumbnail) is **not** in scope.
- After removing `_fetch_cluster_thumbnails()`, verify `list_pending_with_details()` no longer passes a thumbnail dict to `_to_details()`.

## Verification Commands

```bash
cd apps/prototype-description-service
pyenv shell description-service
make check   # ruff + mypy + pytest -- must be clean before and after
pytest recognition/tests/ -q   # full suite; baseline is 476 passed
```

## Next Agent Instructions

1. Read `docs/tasks/4.0/4.13.1/thumbnail-deprecation-task-plan.md` (Functions to Change tables for full line-level inventory).
2. Start with `settings.py` and `api/main.py` (config removal -- zero risk).
3. Work down through domain models, then repositories, then schemas, then routers.
4. After all application-layer changes pass `make check`, remove `thumbnail_url` from `db/migrations/versions/001_identity_schema.py` (no new migration).
5. When done, continue with `v0.1.0-completion-task-plan.md` Phase 2 (Plugin cleanup).

---

## Session Log

### 2026-02-20 - Session 1

- Phase 0 (Merge Phase 3 to main) confirmed complete; smoke tests signed off.
- Phase 0.5 (Workbench media decoupling from sync state) confirmed complete; findings resolved.
- This task plan created for Phase 1 execution.

### 2026-02-21 - Session 2 (Handoff Review Corrections)

- Corrected contradictory migration guidance:
  - Removed references to creating a new Alembic migration for `thumbnail_url` drop.
  - Standardized on greenfield policy: edit baseline migration `001_identity_schema.py` directly.
- Corrected invalid verification command:
  - Replaced `make db-reset` with `make reset` (actual Makefile target).

### 2026-02-21 - Session 3 (Review Findings Recorded)

- [MEDIUM][GAP] Cross-doc mismatch remains:
  - `docs/tasks/4.0/4.13.3/v0.1.0-completion-task-plan.md` Phase 1 checklist still includes:
    - "Create Alembic migration: `ALTER TABLE media_identities DROP COLUMN thumbnail_url`"
    - "Test migration up/down on dev database"
  - This conflicts with greenfield baseline-only schema policy now documented in:
    - `docs/tasks/4.0/4.13.3/thumbnail-deprecation-phase1-task-plan.md`
    - `docs/tasks/4.0/4.13.1/thumbnail-deprecation-task-plan.md`
  - Follow-up needed: align completion-plan Phase 1 checklist to baseline-edit + `make reset`.

### 2026-02-21 - Session 4 (Cross-Doc Alignment Closed)

- Follow-up from Session 3 resolved:
  - `v0.1.0-completion-task-plan.md` Phase 1 checklist now aligns to baseline-only schema policy.
  - Baseline migration guidance and `make reset` command are consistent across Phase 1 + completion docs.

---

# Consolidated Checklist

## Phase 1-A: Backend -- Remove Application-Layer `thumbnail_url`

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

## Phase 1-B: Remove Column from Baseline Schema

- [ ] Remove `thumbnail_url` column definition from the baseline migration (`db/migrations/versions/001_identity_schema.py`).
- [ ] Run `make reset` to wipe and rebuild the dev database from the updated baseline.
- [ ] Verify: `make check`.
