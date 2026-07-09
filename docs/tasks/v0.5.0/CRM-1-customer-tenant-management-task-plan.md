# Task Plan — CRM-1

> - **Date**: 2026-07-09
> - **Author**: Claude Opus 4.8 (operator session)
> - **Project**: context-alt-text-monorepo (description-service admin)
> - **Task ID**: `CRM-1`
> - **Target Branch**: `feature/crm-1`
> - **Review Coverage Target**: 2
> - **Derived from**: [ADR-012](../../adrs/ADR-012-customer-tenant-management-crm-ready-admin.md)

---

## CRM-1. Customer & Tenant Management — CRM-Ready Admin Key Surface

## Objective

Enrich `tenants` and `api_keys` with customer identity and credential provenance, surface them in the `/admin` console, and add the future-proofing seams (JSONB `metadata`, `crm_account_id`, `account_ref`) plus a CRM-shaped read/export and lifecycle events. When complete, every tenant is a named, contactable account and every key has a label + minter + reason-on-revoke, migratable to an external CRM without schema surgery.

## Problem Statement

`tenants` is a technical scoping row (`site_url`, retention, counters — no customer identity) and `api_keys` is a bare credential (`rate_limit_tier`, timestamps — no label, no `created_by`, no revoke reason) (`db/migrations/versions/001_identity_schema.py:162-199`). Procurement is untraceable: keys are anonymous, no contact is on file, and there is no external-CRM linkage. ADR-012 accepted a CRM-ready metadata layer.

## Constraints

- **Greenfield**: schema changes go directly in `001_identity_schema.py`; no data migration; delete-over-flag.
- **PII discipline**: contact fields on `tenants` only — never on `api_keys`, never logged; retention/export must cover them.
- **Operator-only, audited**: `/admin` is tailnet-gated (E15-31); every mutation writes an `audit_events` row on the **same** request session (existing invariant; `audit_events` table exists — `001_identity_schema.py:35`, indexed on `tenant_id,event_type`).
- **Enums centralized** (sr-007): `account_status`, `environment` as Python `StrEnum`.
- **Boundary adapters must not fabricate metadata** (rg-015): export/read envelopes derive fields from stored rows, not guesses.
- **Plugin Boundary Rule**: modify only `apps/prototype-description-service/**` (+ optional whoami surfacing).

## Workflow Principles

- Typed columns for known fields; JSONB `metadata` for the un-formalized tail only; promote-not-duplicate.
- External linkage via `crm_account_id`; rollup via `account_ref`; never overload the UUID PK.
- A CRM is a consumer of export + events, never a dependency on the mint path.

## Terminology

- **Account**: the customer/organization behind one or more tenants (today 1:1 with tenant via `account_ref` = self id).
- **Subscription (informal)**: an `api_key` row viewed as a customer's credential in the CRM-shaped read.

## Current State Analysis

- `tenants` columns: `id`, `site_url` (unique), `next_person_number`, `naming_agreement_enabled`, `retention_mode`, `last_export_at`, `last_purge_at`, `retention_updated_at`, `created_at`, `updated_at` (`001_identity_schema.py:162-181`). No customer identity.
- `api_keys` columns: `id`, `tenant_id` (FK CASCADE), `api_key_hash` (unique), `rate_limit_tier`, `created_at`, `last_used_at`, `expires_at`, `revoked_at` (`001_identity_schema.py:183-199`). No label/provenance/reason.
- Admin routes: `POST /admin/ui/tenants` (site_url), `POST /admin/ui/keys` (tenant), `POST /admin/ui/keys/{key_id}/revoke` (`recognition/interface_adapters/http/routers/admin.py`); service logic `recognition/application/services/api_key_admin_service.py`; CLI mirror `scripts/manage_api_keys.py`.
- `audit_events` exists with `tenant_id`, `event_type`, `created_at` (`001_identity_schema.py:35,1231-1232`).

## Target Outcome

Operators create a customer (tenant + contact + first labeled key) in one atomic step, edit account fields, see who minted each key and why it was revoked, and export the customer roster; lifecycle events land in `audit_events` for a future CRM to consume.

## Context Loading

- ADR: `docs/adrs/ADR-012-customer-tenant-management-crm-ready-admin.md`
- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`
- Handoff: task `CRM-1`; ADR-012 verdict decision `operator_planning_review_verdict_adr011_adr012`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `/admin` JSON API | recognition service | tenant/key create/list/revoke shapes (`routers/admin.py`) | Add customer/provenance fields; CRM-shaped read; export endpoint; lifecycle events | no (greenfield) | `recognition/tests/api/test_admin_router.py` extended |
| `api_key_admin_service` | recognition service | mint/revoke signatures | Accept `label`, `created_by`, `revoked_reason` | no | `test_api_key_admin_service.py` |
| DB schema | migration owner | `tenants`/`api_keys` (`001_identity_schema.py`) | New typed columns + JSONB + `crm_account_id` + `account_ref` (+ indexes) | no | `scripts/verify_identity_schema.py` |
| `manage_api_keys` CLI | ops | create/list/revoke | Mirror new fields | no | CLI test |

## Proposed Solution

Four slices: (1) schema — extend both tables with typed fields + `metadata` JSONB + `crm_account_id` + `account_ref` (+ indexes); (2) admin API + console + CLI capture/edit/display + CRM-shaped read + lifecycle events; (3) atomic provision-customer flow + idempotent upsert-by-`crm_account_id`; (4) retention/export coverage for the new PII. Each slice ships behavior + proof.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Schema | `db/migrations/versions/001_identity_schema.py` | tenants: `display_name`, `primary_contact_name`, `primary_contact_email`, `account_status`, `notes`, `onboarded_at`, `crm_account_id` (indexed), `account_ref` (nullable, indexed, no FK, self-id default), `metadata` JSONB. api_keys: `label`, `description`, `created_by`, `environment`, `revoked_reason`, `revoked_by`, `metadata` JSONB |
| Enums | `recognition/.../` (new/existing enums module) | `AccountStatus`, `KeyEnvironment` StrEnum |
| Admin service | `recognition/application/services/api_key_admin_service.py` | Accept/persist `label`, `created_by`, `revoked_reason`/`revoked_by`; emit lifecycle events |
| Admin router | `recognition/interface_adapters/http/routers/admin.py` | Request/response models + console fields; CRM-shaped read; roster export endpoint |
| CLI | `scripts/manage_api_keys.py` | Mirror new create/revoke fields; tenant-create captures contact |
| Schema verify | `scripts/verify_identity_schema.py` | Assert new columns/indexes |
| whoami (optional) | `recognition/interface_adapters/http/routers/tenant.py` | Optionally return `display_name` for plugin display |

## Related Files

| File | Note |
| --- | --- |
| `recognition/interface_adapters/http/routers/admin.py` docstring | Same-session audit-write invariant to preserve |
| retention router/service | PII must be covered by retention + export (slice 4) |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && uv run pytest recognition/tests/api/test_admin_router.py recognition/tests/service/test_api_key_admin_service.py`
  - `uv run python scripts/verify_identity_schema.py` (columns + indexes present)
- Contract/fixture verification:
  - Admin read returns account + contacts + keys; export endpoint emits the roster shape; each mutation writes one `audit_events` row (same session).
- Manual verification:
  - Provision a customer via `/admin` (tenant + contact + labeled key) over the tailnet; confirm Key ID/label visible and a `key_minted` audit event recorded.

## Slice Delivery

### Slice 1: Schema extension

**Goal**: Both tables carry customer/provenance fields + future-proof seams.

Changes:
- Extend `tenants` and `api_keys` in `001_identity_schema.py` (typed columns + `metadata` JSONB + `crm_account_id` indexed + `account_ref` nullable/indexed/no-FK/self-id default).
- Add `AccountStatus`/`KeyEnvironment` StrEnum.

Proof:
- `verify_identity_schema.py` asserts the new columns + indexes; schema sync applies cleanly on a fresh DB.

### Slice 2: Admin API + console + CLI + events

**Goal**: Capture, edit, and display customer/credential metadata; emit lifecycle events.

Changes:
- Admin create/mint/revoke accept `label`, `created_by`, contact fields, `revoked_reason`/`revoked_by`; console renders them.
- CRM-shaped read (account + contacts + keys); roster export endpoint; lifecycle events (`tenant_created`, `key_minted`, `tenant_suspended`, `key_revoked`, `contact_updated`) to `audit_events` on the same session. Mirror in `manage_api_keys.py`.

Proof:
- Admin/service tests assert fields persisted, read shape, and one audit row per mutation.

### Slice 3: Atomic provision-customer + idempotent upsert

**Goal**: One-step customer provisioning; idempotent by `crm_account_id`.

Changes:
- `provision-customer` flow creates tenant + contact + first labeled key atomically; upsert-by-`crm_account_id`.

Proof:
- Test: repeated provision with same `crm_account_id` is idempotent; single transaction; audited.

### Slice 4: Retention/export PII coverage

**Goal**: Contact PII is covered by retention + export.

Changes:
- Extend retention/export to include contact fields (export includes them; purge/erase honors them).

Proof:
- Test asserting PII appears in export and is handled by the retention path.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded ADR-012, backend-python guidelines, and task `CRM-1` handoff state before editing.
- [ ] Recorded `/admin` API + DB schema boundary ownership and greenfield no-compat expectation.

### Checklist for Slice 1: Schema extension

- [ ] tenants + api_keys extended with typed fields + `metadata` JSONB + `crm_account_id` + `account_ref` (+ indexes) in `001_identity_schema.py`.
- [ ] `AccountStatus`/`KeyEnvironment` StrEnum added.
- [ ] `verify_identity_schema.py` asserts new columns/indexes; evidence captured.

### Checklist for Slice 2: Admin API + console + CLI + events

- [ ] Create/mint/revoke accept + persist new fields; console + CLI mirror them.
- [ ] CRM-shaped read + export endpoint; lifecycle events on same session.
- [ ] Admin/service tests capture field persistence, read shape, one audit row per mutation.

### Checklist for Slice 3: Atomic provision-customer + idempotent upsert

- [ ] One-step tenant+contact+labeled-key flow; idempotent by `crm_account_id`.
- [ ] Test proves idempotency + single transaction + audit.

### Checklist for Slice 4: Retention/export PII coverage

- [ ] Retention + export cover contact PII; test captured.

## Review Readiness

- [ ] No schema/admin-API change without matching test + `verify_identity_schema.py` evidence.
- [ ] PII confined to `tenants`; never on `api_keys` or logs; retention/export covers it.
- [ ] Handoff decision records change + verification + contract implications.

## Success Criteria

- [ ] `tenants`/`api_keys` carry customer identity + provenance + JSONB + `crm_account_id` + `account_ref`; `verify_identity_schema.py` green.
- [ ] `/admin` captures/edits/displays customer + key label; each mutation writes one audit event.
- [ ] Roster export emits account+contacts+keys; provision-customer is atomic and idempotent by `crm_account_id`.
- [ ] Contact PII covered by retention + export.
