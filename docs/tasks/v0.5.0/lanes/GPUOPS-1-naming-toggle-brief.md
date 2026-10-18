# GPUOPS-1 lane L6 — one authority for "names in descriptions"

Branch `feature/gpuops-1-naming-toggle`, worktree `context-alt-text-monorepo-gpuops-1-naming-toggle`. Owns: service tenant naming routes you add under `apps/prototype-description-service/recognition/interface_adapters/http/routers/` plus the repository method they need and their tests; the service-side gate in the legacy `/recognition/describe` path if missing; `apps/prototype-wp-alt-context/src/api/class-settings-controller.php`; `src/api/services/class-describe-media-service.php`; `tests/Unit/*Settings*Test.php`; `js/admin/api/settingsApi.ts`; `js/admin/pages/settings/SettingsForm.tsx`; `settingsConstants.ts`; `useSettingsPageState.ts`; their tests.

## Goal

Implement contract C6: the tenant flag `naming_agreement_enabled` becomes the only gate for person names in captions, exposed through a settings toggle. The PHP option is deleted, not mirrored (REF-09, DATA-14).

## Current anchors

- `db/models/tenant.py:53` `naming_agreement_enabled` (Boolean, server default true). No setter route exists; `recognition/interface_adapters/http/routers/admin.py` has `/tenants` GET and `/tenants/{id}/keys` only.
- `scene/application/describe_run_worker.py` ~:446 `naming_enabled = tenant.naming_agreement_enabled and run.recognition_enabled` — the gate that already works for describe runs. Do not edit that file (L7 owns it).
- `src/api/class-settings-controller.php`: GET payload keys ~:141 (`recognition_enabled` via `RecognitionPolicy`), POST validation ~:209-219 (`option_matches_intended`). Follow that shape for `allow_person_names`.
- `src/api/services/class-describe-media-service.php` ~:988 `build_identity_context`, ~:1060 `get_option('acx_description_allow_person_names', false)`.
- Legacy path: grep `naming_agreement_enabled` under `recognition/` to see whether `/recognition/describe` gates names; if it does not, add the gate there (service side, tenant flag).

## Deliverables

1. Service: `GET /recognition/tenant/naming-agreement` → `{enabled}` and `PUT /recognition/tenant/naming-agreement {enabled: bool}` → `{enabled}`, scoped to the calling tenant's key (`require_write_access` for PUT). Repository update method with a test. Demo tier → 403.
2. Service: legacy describe path honours the tenant flag (verify first; add gate + test only if missing).
3. PHP: `/settings` GET includes `allow_person_names` read from the service GET (on service failure return `null` for that field and an `allow_person_names_error` string; never a fabricated default). POST validates boolean, calls the service PUT, and reports failure as 502 `allow_person_names_sync_failed` instead of claiming success. Delete `acx_description_allow_person_names` and its read in `build_identity_context`; identity context is always sent and the service decides.
4. SPA: toggle "Include named people in descriptions" in `SettingsForm.tsx` with help text stating that names come from the People roster and are applied only when recognition is enabled; disabled state with the error string when the field is `null`.

## Tests

- Service: `cd apps/prototype-description-service && python -m pytest <your new test files> -q -p no:cacheprovider`.
- PHP: `cd apps/prototype-wp-alt-context && vendor/bin/phpunit --filter Settings`.
- SPA: `cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/settings/__tests__ && npx tsc --noEmit` (the ux-map parity tests are owned by L5; ignore them if red).

## Non-goals

`SettingsPage.tsx`, `GpuControlCard.tsx` (L5); worker naming logic (L7); apply-view UI (L8).
