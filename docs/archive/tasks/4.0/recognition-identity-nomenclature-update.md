# Recognition/Identity Nomenclature Update

## Purpose

- Align WordPress admin, REST proxy, and recognition service terminology with the generalized “identity” concept rather than the face-only naming.
- Ensure every API, schema, type definition, migration, and setting can support future entity detectors (logo/brand classifiers, custom taxonomies, etc.) without another naming overhaul.

## Scope

### WordPress Plugin (apps/prototype-wp-alt-context)

1. **PHP Controllers**
   - `src/api/class-recognition-controller.php`: rename payload members (`$face_id` → `$entity_id`, `face_count` → `identity_count`, etc.), endpoint paths, and docblocks.
   - `src/api/class-recognition-proxy-controller.php`: mirror the identity endpoint naming, request parameters, and proxy routes.
2. **Admin bootstrap**
   - `src/admin/class-admin.php`: update localized endpoint handles (`workbenchRecognitionMediaIdentities`, `workbenchRecognitionEntities`, etc.).
3. **Hooks & Types**
   - `js/admin/hooks/useRecognitionHooks.ts`: rename `useScanFaces` → `useScanIdentities`, `useClusterFaces` → `useClusterIdentities`, adjust return types.
   - `js/admin/hooks/useWorkbenchMedia.ts`: rename `faces_detected` → `entities_detected` in `ScanStatus`, `total_faces_clustered` → `total_entities_clustered`, etc.
   - `js/admin/types` or equivalent: `ClusterFace` → `ClusterIdentity`, `sample_faces` → `sample_entities`, etc.
4. **API Calls**
   - `js/admin/api/recognitionApi.ts`: rename functions (e.g., `fetchMediaIdentities`, `reassignClusterIdentity`).
5. **UI Components**
   - Update props, variable names, and copy in components like `MediaSelection`, `ClusterGrid`, `ClusterDrawerPanel` to use “identity” terminology.
   - Roster-specific views (`js/admin/pages/roster/*.tsx`) still refer to `sample_faces`, `face_count`, and `ClusterFace`; rename these props/components plus related SCSS selectors.
   - Any MSW/mock handlers or Storybook stories under `js/admin` referencing `face` payloads must be renamed to the identity forms.

### Recognition Service (apps/prototype-description-service)

1. **Domain & Application**
   - `recognition/application/face_clustering_service.py` → update class/method names (or add aliases) to “identity” where appropriate (`cluster_identities`, `IdentityCluster`).
   - `recognition/application/face_scan_service.py`: rename job fields (`faces_detected` → `entities_detected`), method names, and log copy.
2. **Config**
   - `recognition/config/settings.py` & `config/settings.yaml`: adjust keys to `IDENTITY_*` or `RECOGNITION_IDENTITIES`. Ensure environment variable docs mention the new names.
3. **Domain Entities**
   - `recognition/domain/entities.py`: rename dataclasses/types to `Identity`, `IdentityCluster`.
4. **HTTP Router**
   - `recognition/interface_adapters/http/recognition_router.py`: expose `GET /recognition/media/identities`, rename request/response models (`MediaIdentityDetail`).
5. **Database Layer**
   - SQLAlchemy models already expose identity naming (`MediaIdentity`, `IdentityCluster`, `IdentityMember`, `IdentityScanJob`). Treat them as the contract and replace any lingering `MediaFace` imports in services or repositories.
   - When new fields are required, extend the identity models rather than adding face-prefixed aliases.
6. **Migrations**
   - The identity baseline is already captured in `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`; no additional drop-and-rename migration is necessary.
   - Use `apps/prototype-description-service/scripts/reset_dev_db.sh` (or `alembic downgrade/upgrade`) to rebuild local databases during development.
   - If schema tweaks are needed before release, edit the baseline migration directly per the greenfield policy rather than layering a second revision.
7. **Settings & Env**
   - `config/settings.yaml` / `.env` instructions: rename variables referencing “faces”.

### Tests & Fixtures

- Update unit/integration tests in both codebases to use new terminology (test names, fixtures, sample payloads).
- Confirm MSW mocks or PHP unit test fixtures reference the new fields.

## Deliverables

1. Code changes across both repositories reflecting the “identity” nomenclature.
2. Documented identity baseline + reset procedure (identity tables already defined in `001_identity_schema.py`).
3. Updated documentation (plan + implementation guides).
4. QA checklist ensuring no references to “face” remain where identity semantics are intended (allowing legacy names only where unavoidable, e.g., physical table names if renaming is deferred).

## Rationale & Alternatives

- Alternative was to keep `/media/faces` and introduce new endpoints later; rejected because it leads to confusing mix of “face vs identity” in contracts and hampers adding new entity types.
- Renaming now (before rollout) keeps the API future-proof and reduces technical debt.
