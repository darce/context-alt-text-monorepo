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

Enrich `tenants` and `api_keys` with customer identity and credential provenance, surface them in the `/admin` console, and add the future-proofing seams (JSONB `metadata` + `UNIQUE` `crm_account_id`; the `account_ref` rollup seam is **deferred** per ADR-012 rule 5) plus a paginated CRM-shaped read/export and lifecycle events. When complete, every tenant is a named, contactable account and every key has a label + minter + reason-on-revoke, migratable to an external CRM without schema surgery.

## Problem Statement

`tenants` is a technical scoping row (`site_url`, retention, counters — no customer identity) and `api_keys` is a bare credential (`rate_limit_tier`, timestamps — no label, no `created_by`, no revoke reason) (`db/migrations/versions/001_identity_schema.py:162-199`). Procurement is untraceable: keys are anonymous, no contact is on file, and there is no external-CRM linkage. ADR-012 accepted a CRM-ready metadata layer.

## Constraints

- **Greenfield, but the backend is live**: schema changes go directly in `001_identity_schema.py`; delete-over-flag. `_ensure_table` (`001:136-139`) only creates missing **tables**, not columns, so new columns must be **nullable/defaulted (expand-first)** and reach the live `altcontext.com` DB via an explicit ALTER-add in the sync/heal path (or a documented reset) — never a bare `NOT NULL` add (ADR-012 rule 1 / V2-01).
- **Bounded reads**: CRM-shaped list + roster export are paginated (limit/offset or cursor); no unbounded fetch-all (ADR-012 rule 6 / V2-04).
- **audit_events reclaimer**: this task raises the `audit_events` write rate; state a retention/purge (partition-and-drop or periodic reclaimer) policy or explicitly defer it (ADR-012 rule 6 / V2-05).
- **PII discipline**: contact fields on `tenants` only — never on `api_keys`, never logged; retention/export must cover them.
- **Operator-only, audited**: `/admin` is tailnet-gated (E15-31); every mutation writes an `audit_events` row on the **same** request session (existing invariant; `audit_events` table exists — `001_identity_schema.py:35`, indexed on `tenant_id,event_type`).
- **Enums centralized** (sr-007): `account_status`, `environment` as Python `StrEnum`.
- **Boundary adapters must not fabricate metadata** (rg-015): export/read envelopes derive fields from stored rows, not guesses.
- **Plugin Boundary Rule**: modify only `apps/prototype-description-service/**` (+ optional whoami surfacing).

## Workflow Principles

- Typed columns for known fields; JSONB `metadata` for the un-formalized tail only; promote-not-duplicate.
- External linkage via `UNIQUE` `crm_account_id` (also the provisioning idempotency key); rollup (`account_ref`) deferred until a consumer exists; never overload the UUID PK.
- A CRM is a consumer of export + events, never a dependency on the mint path.

## Terminology

- **Account**: the customer/organization behind a tenant (today 1:1 with the tenant; the multi-tenant `account_ref` rollup is deferred).
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
| DB schema | migration owner | `tenants`/`api_keys` (`001_identity_schema.py`) | New nullable typed columns + JSONB + `UNIQUE` `crm_account_id` (+ indexes); live-DB ALTER-add via sync/heal (no `account_ref`) | no | `scripts/verify_identity_schema.py` + live ALTER applied |
| `manage_api_keys` CLI | ops | create/list/revoke | Mirror new fields | no | CLI test |

## Proposed Solution

Four slices: (1) schema — extend both tables with nullable typed fields + `metadata` JSONB + `UNIQUE` `crm_account_id` (+ indexes), applied to the live DB via ALTER-add (no `account_ref`); (2) admin API + console + CLI capture/edit/display + paginated CRM-shaped read + lifecycle events; (3) atomic provision-customer flow with DB-level idempotency (`INSERT ... ON CONFLICT (crm_account_id)`); (4) retention/export coverage for the new PII + `audit_events` retention. Each slice ships behavior + proof.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Schema | `db/migrations/versions/001_identity_schema.py` (+ sync/heal ALTER path) | tenants: `display_name`, `primary_contact_name`, `primary_contact_email`, `account_status`, `notes`, `onboarded_at`, `crm_account_id` (**`UNIQUE`**, indexed), `metadata` JSONB. api_keys: `label`, `description`, `created_by`, `environment`, `revoked_reason`, `revoked_by`, `metadata` JSONB. **All nullable/defaulted; added to the live DB via ALTER (`_ensure_table` won't). No `account_ref` (deferred).** |
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
- Extend `tenants` and `api_keys` in `001_identity_schema.py` (nullable typed columns + `metadata` JSONB + `UNIQUE` `crm_account_id` indexed; no `account_ref`). Add the ALTER-add path in sync/heal so the columns land on the existing live tables.
- Add `AccountStatus`/`KeyEnvironment` StrEnum.

Proof:
- `verify_identity_schema.py` asserts the new columns + `UNIQUE(crm_account_id)` + indexes; sync applies cleanly on a fresh DB AND ALTER-adds the columns on a pre-existing DB.

### Slice 2: Admin API + console + CLI + events

**Goal**: Capture, edit, and display customer/credential metadata; emit lifecycle events.

Changes:
- Admin create/mint/revoke accept `label`, contact fields, `revoked_reason`; console renders them. **`created_by`/`revoked_by` source:** `/admin` auth is a single shared admin token (`deps/admin_auth.py` `require_admin`) with no per-operator identity — so these are populated from an **operator label supplied in the request body** (free-text, e.g. "daniel"), NOT an inferred human identity. True per-operator attribution is deferred until per-operator admin auth exists; note this in the field docs so the value is not mistaken for authenticated identity.
- **Paginated** CRM-shaped read (account + contacts + keys; limit/offset or cursor, bounded keys-per-account); **paginated** roster export endpoint — **must be `require_admin_header`-gated, tailnet-only (E15-31), and write an `export` `audit_events` row** since it emits contact PII (no weaker gate than mutations). Lifecycle events (`tenant_created`, `key_minted`, `tenant_suspended`, `key_revoked`, `contact_updated`) to `audit_events` on the same session. Mirror in `manage_api_keys.py`.

Proof:
- Admin/service tests assert fields persisted, read shape, and one audit row per mutation.

### Slice 3: Atomic provision-customer + DB-level idempotency

**Goal**: One-step customer provisioning; idempotent at the DB level, race-free.

Changes:
- `provision-customer` flow creates tenant + contact + first labeled key atomically. Idempotency via `UNIQUE(crm_account_id)` + `INSERT ... ON CONFLICT (crm_account_id) DO UPDATE` — not an application-level exists-check (avoids the concurrent double-create race).

Proof:
- Test: two concurrent provisions with the same `crm_account_id` produce exactly one account (ON CONFLICT), single transaction, audited.

### Slice 4: Retention/export PII coverage

**Goal**: Contact PII is covered by retention + export.

Changes:
- Extend retention/export to include contact fields (export includes them; purge/erase honors them).
- State/implement the `audit_events` retention/purge policy (partition-and-drop or periodic reclaimer) given the raised event write rate, or explicitly defer with rationale.

Proof:
- Test asserting PII appears in export and is handled by the retention path; `audit_events` retention policy documented (or deferral recorded).

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded ADR-012, backend-python guidelines, and task `CRM-1` handoff state before editing.
- [ ] Recorded `/admin` API + DB schema boundary ownership and greenfield no-compat expectation.

### Checklist for Slice 1: Schema extension

- [ ] tenants + api_keys extended with nullable typed fields + `metadata` JSONB + `UNIQUE` `crm_account_id` (+ indexes) in `001_identity_schema.py`; ALTER-add path lands them on the live DB; no `account_ref`.
- [ ] `AccountStatus`/`KeyEnvironment` StrEnum added.
- [ ] `verify_identity_schema.py` asserts new columns/indexes; evidence captured.

### Checklist for Slice 2: Admin API + console + CLI + events

- [ ] Create/mint/revoke accept + persist new fields; console + CLI mirror them.
- [ ] CRM-shaped read + export endpoint; lifecycle events on same session.
- [ ] Admin/service tests capture field persistence, read shape, one audit row per mutation.

### Checklist for Slice 3: Atomic provision-customer + DB-level idempotency

- [ ] One-step tenant+contact+labeled-key flow; DB-level idempotency via `UNIQUE(crm_account_id)` + `ON CONFLICT`.
- [ ] Test proves concurrent same-`crm_account_id` provisions yield one account + single transaction + audit.

### Checklist for Slice 4: Retention/export PII coverage

- [ ] Retention + export cover contact PII; test captured.

## Review Readiness

- [ ] No schema/admin-API change without matching test + `verify_identity_schema.py` evidence.
- [ ] PII confined to `tenants`; never on `api_keys` or logs; retention/export covers it.
- [ ] Handoff decision records change + verification + contract implications.

## Success Criteria

- [ ] `tenants`/`api_keys` carry customer identity + provenance + JSONB + `UNIQUE` `crm_account_id` (no `account_ref`); `verify_identity_schema.py` green and live-DB columns ALTER-added.
- [ ] `/admin` captures/edits/displays customer + key label; each mutation writes one audit event.
- [ ] Roster export emits account+contacts+keys; provision-customer is atomic and idempotent by `crm_account_id`.
- [ ] Contact PII covered by retention + export.
