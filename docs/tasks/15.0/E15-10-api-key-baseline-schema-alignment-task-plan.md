# E15-10. API Key Baseline Schema Alignment

> **Status: Superseded by E15-1 Slice 3 / archived 2026-04-11 (commit `ac37af09`).** The `api_keys` table, indexes, README entry, and migration-path regression coverage all landed on main; handoff state is archived. File retained for historical context only.

> **Metadata**
>
> - **Date**: 2026-04-11
> - **Author**: GitHub Copilot
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-10
> - **Target Branch**: `feature/e15-10-api-key-baseline-schema-alignment`
> - **Type**: Reactive bug-fix task plan

---

## Objective

Restore runtime schema parity for API-key authentication so databases bootstrapped from the prototype description service baseline migration include the `api_keys` table required by the merged E15-8 and E15-9 auth path.

## Problem Statement

The merged auth isolation work now correctly treats SQLSTATE `42P01` as a hard auth-store fault and returns `500 {"detail":"api key store unavailable"}`. That exposed a schema/bootstrap drift problem: the runtime service expects the `api_keys` table defined in [apps/prototype-description-service/db/models/tenant.py](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/db/models/tenant.py), but the baseline Alembic migration [apps/prototype-description-service/db/migrations/versions/001_identity_schema.py](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/db/migrations/versions/001_identity_schema.py) does not create it. Service tests currently create `api_keys` directly from ORM metadata, so they do not catch the migration omission.

## Scope

- `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`
- `apps/prototype-description-service/db/README.md`
- Relevant bootstrap/integration tests under `apps/prototype-description-service/recognition/tests/`

## Target Outcome

- The baseline migration creates `api_keys` with the same table shape expected by the runtime model.
- Bootstrap docs name `api_keys` as part of the baseline schema.
- A regression test fails if the migration/bootstrap path omits `api_keys` while runtime auth still expects it.

## Verification Strategy

- `cd apps/prototype-description-service && pyenv exec python -m pytest recognition/tests/api/test_authentication.py -q`
- `cd apps/prototype-description-service && pyenv exec python -m pytest recognition/tests/api/test_retention_api.py -q`

## Slice Delivery

### Slice 1: Baseline Migration Parity

Goal: add `api_keys` to the baseline migration and align docs/tests with runtime expectations.

Changes:

- Add `api_keys` creation and indexes to `001_identity_schema.py`
- Update `db/README.md` baseline table list
- Add a regression test or bootstrap assertion that covers the migration/bootstrap path rather than only ORM metadata `create_all`

Proof:

- `cd apps/prototype-description-service && pyenv exec python -m pytest recognition/tests/api/test_authentication.py -q`
- `cd apps/prototype-description-service && pyenv exec python -m pytest recognition/tests/api/test_retention_api.py -q`

## Success Criteria

- [x] Local runtime no longer fails auth with `relation "api_keys" does not exist` after the baseline schema is applied.
- [x] The migration, model, and bootstrap docs all agree that `api_keys` is part of the baseline auth store.
- [x] Tests cover the drift that allowed E15-8/E15-9 to pass while runtime bootstrap remained broken.
