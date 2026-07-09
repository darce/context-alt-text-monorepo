# ADR-012: Customer & Tenant Management Data Model — CRM-Ready Admin Key Surface

## Status

Proposed

## Date

2026-07-09

## Context

The operator admin surface at `/admin/ui/keys` (and the `/admin/ui/tenants` companion) manages tenants and API keys, but it is **anonymous and metadata-poor**. During this session's tenant-procurement debugging it became clear that:

- A **tenant** is a pure technical scoping row keyed by `site_url` — there is no customer name, contact, account status, plan, notes, or provenance of who onboarded it.
- An **API key** is a bare credential — there is no human label ("prod WP" vs "staging"), no record of *who* minted it, *why*, or *for whom*, and no revocation reason.
- The procurement flow is therefore untraceable: an operator mints a key in the console and hands it to a customer, and the system retains nothing linking that credential to a human, an organization, or a support contact. When a client hits an error (as happened repeatedly this session), there is no clean identifier for them to quote and no record on the operator side of who they are.

As the project onboards real customers for the public demo launch (E15), operators need genuine **customer-management mechanics** — and the data model should be **future-proof for migration to a proper CRM** (HubSpot, Salesforce, etc.) without schema surgery or a data migration when that day comes.

This ADR is a companion to [ADR-011](./ADR-011-retire-on-device-recognition-remote-only.md): ADR-011 makes the **key ↔ tenant** binding the source of truth (key-driven tenanting); this ADR enriches the tenant and key **around** that binding with customer identity, credential provenance, and CRM-ready seams.

### Improvements distilled from this session

> Concrete gaps observed while debugging tenant procurement/admin this session.

- Keys are anonymous — no way to know which customer/site a key belongs to from the admin surface.
- No support identifier is captured or surfaced — a client cannot easily say "I am tenant/key X" (ADR-011 adds the plugin-side display; this ADR adds the operator-side record).
- No mint-time provenance — who created the key, when, for what environment, is not recorded.
- Tenant vs environment ambiguity — local vs OCI, prod vs staging vs demo vs eval all look alike; no environment/label field disambiguates.
- No customer contact — when a key must be rotated or a tenant contacted, there is no email/name on file.

### Constraints from prior review

- **Greenfield.** No production data to preserve; schema changes go directly in `001_identity_schema.py`; delete-over-flag (no back-compat shims).
- **Single shared, RLS-isolated backend** (ADR-011). Customer isolation is per-tenant Postgres RLS; there are no per-customer servers.
- **PII discipline.** Contact information is associated with the account/tenant, never with a credential (`api_keys`) and never written to logs.
- **Operator-only, audited surface** (E15-31). `/admin` is tailnet-gated; every mutation writes an `audit_events` row on the same request session.

## Current State Inventory

> Grounded in the live schema (`db/migrations/versions/001_identity_schema.py`, commit `9551d929`).

- **`tenants`** (`001_identity_schema.py:162-181`): `id` (UUID PK), `site_url` (unique), `next_person_number`, `naming_agreement_enabled`, `retention_mode`, `last_export_at`, `last_purge_at`, `retention_updated_at`, `created_at`, `updated_at`. **No customer identity fields.**
- **`api_keys`** (`001_identity_schema.py:183-199`): `id` (UUID PK), `tenant_id` (FK → tenants, CASCADE), `api_key_hash` (unique), `rate_limit_tier`, `created_at`, `last_used_at`, `expires_at`, `revoked_at`. **No label, no created-by provenance, no revocation reason, no environment.**
- **Admin surface** (`recognition/interface_adapters/http/routers/admin.py`): `POST /admin/ui/tenants` (site_url only), `POST /admin/ui/keys` (tenant only), `POST /admin/ui/keys/{key_id}/revoke`, JSON list/get routes. CLI mirror: `scripts/manage_api_keys.py` (`tenant-create --site-url`, `create --tenant`). Every mutation writes `audit_events` on the same session.
- **Account concept:** none. `tenant` is `account` 1:1, keyed by `site_url`. A customer with multiple sites/environments has multiple unrelated tenants.

### Downstream surfaces that must migrate together

- `db/migrations/versions/001_identity_schema.py` — `tenants` + `api_keys` table definitions.
- `recognition/interface_adapters/http/routers/admin.py` — create/mint/revoke routes, request/response models, console HTML.
- `recognition/application/services/api_key_admin_service.py` — mint/revoke service logic.
- `scripts/manage_api_keys.py` — CLI create/list/revoke + tenant-create.
- `recognition/.../routers/tenant.py` (`/tenant/whoami`) — may surface account display fields to the plugin.
- Retention/export surfaces — must extend to cover the new PII.

## Decision

Add a **CRM-ready customer-metadata layer** to `tenants` and `api_keys`: typed columns for the fields we know we need now, a JSONB `metadata` escape hatch for the un-formalized tail, and a stable external reference plus an account-rollup seam — then shape the admin read/export surface as **account + contacts + subscriptions** so a future CRM can sync without schema surgery.

### Chosen design rules

1. **Enrich `tenants` with account/customer fields.** `display_name`, `primary_contact_name`, `primary_contact_email`, `account_status` (StrEnum: `trial` | `active` | `suspended` | `churned`, default `active`), `notes` (operator free text), `onboarded_at`. `site_url` stays. These describe the customer/organization behind the tenant.
2. **Enrich `api_keys` with credential provenance + labeling.** `label` (human name, e.g. "prod WP", "staging"), `description`, `created_by` (operator identity that minted it), `environment` (optional: `prod` | `staging` | `dev` | `demo` | `eval`), `revoked_reason`, `revoked_by`. Never PII.
3. **JSONB `metadata` escape hatch on both tables.** Add experimental/soft fields (acquisition source, company size, plan add-ons) with no migration; promote hot fields to typed columns later. Typed columns for known needs, JSONB for the tail only — never duplicate a typed field into JSONB.
4. **Stable external CRM reference.** `crm_account_id` (nullable, indexed) on the tenant/account — the bidirectional link to an external CRM. Never overload the UUID primary key for external identity.
5. **Account-rollup seam.** Nullable `account_ref` (UUID) grouping on `tenants` so multiple tenants (prod/staging, multiple sites) can later roll up to one CRM account. Today `account_ref` may equal the tenant's own id (1:1); the column's existence makes N:1 a config change, not a data migration.
6. **CRM-shaped admin read + export + events.** Admin API returns account + contacts + keys (subscriptions) in one read; add a roster **export** endpoint (JSON/CSV). Emit lifecycle events (`tenant_created`, `key_minted`, `tenant_suspended`, `key_revoked`, `contact_updated`) to `audit_events` so a CRM can be fed by webhook/CDC, not only polling.
7. **PII discipline.** Contact fields live on `tenants` only — never on `api_keys`, never logged. Retention/export coverage extends to the new contact PII. Admin mutations keep writing `audit_events` on the same session (existing atomic invariant).
8. **Idempotent provisioning.** A "provision customer" admin flow creates tenant + contact + first labeled key in one atomic step; upsert-by-`crm_account_id` so a future CRM-driven provisioning integration is idempotent.

### Target outcome

- Every tenant is a named, contactable account with a status; every key has a label, a minter, and a reason-on-revoke.
- Adding a new customer field never requires a migration (JSONB) and promoting one is a single typed-column edit to `001`.
- A CRM integration is a *consumer* of the export/events surface, not a rewrite.

## Why This Decision

### Turns anonymous tenants into managed accounts

Operators can answer "who is this, how do I reach them, what did they buy, why was this key issued" — none of which is possible today. This directly closes the procurement/support gaps seen this session.

### Migration-free evolution + clean CRM handoff

`metadata` JSONB (soft fields), `crm_account_id` (external link), and `account_ref` (rollup seam) are three additive seams that let the model grow and hand off to a real CRM without schema surgery or data migration — the explicit "future-proof" requirement.

### Local-first metadata, optional CRM sync

The recognition service needs tenant/account metadata locally for RLS, support, and the admin console regardless of any CRM. Keeping metadata local and exposing an export/events surface layers a CRM as an optional consumer instead of a hard dependency on the mint path.

## Alternatives Considered

### 1. Build a full accounts / contacts / subscriptions relational model now

Rejected. Over-engineered for pre-launch volume. The `crm_account_id` + `account_ref` + `metadata` seams deliver the same future (multi-tenant accounts, CRM linkage) without the upfront normalization cost. Promote to a normalized model when customer volume and reporting needs justify it — the seams make that promotion additive.

### 2. Integrate a real CRM (HubSpot/Salesforce) directly, no local metadata

Rejected. Couples core auth to a third party: the mint/auth path would gain latency and an availability dependency, and the service still needs local tenant metadata for RLS and the operator console. Local-first metadata with an optional sync surface is the correct layering.

### 3. Store all customer/contact data in JSONB only (no typed columns)

Rejected. The fields we *know* we need — name, contact, account status, key label — deserve typed columns for querying, constraints, indexing, and the admin UI. JSONB is for the un-formalized tail only; using it for everything forfeits validation and makes the admin surface fragile.

### 4. Put contact PII on the key row for convenience

Rejected. PII belongs to the account, not the credential. Keys are rotated and revoked; coupling PII to a short-lived credential is a privacy and lifecycle mistake and would scatter contact data across every key a customer holds.

## Consequences

### Positive

- Managed, contactable customer accounts; support-ready; procurement captures provenance (who/what/why).
- CRM-migratable without a rewrite: export + events + external ref + rollup seam.
- Key labels let operators map credentials to customers/environments at a glance.

### Negative

- The service now stores contact **PII** → privacy/retention obligations; retention and export must be extended to cover it.
- Growth in the admin UI, create/mint/revoke flows, response schemas, and tests.
- A schema edit to `001_identity_schema.py` (acceptable under greenfield).

### Guardrails for the follow-on implementation task

- Contact PII lives on `tenants` only — never on `api_keys`, never in logs; retention/export must cover it.
- `metadata` JSONB, `crm_account_id`, and `account_ref` are the future-proofing seams — do not hardcode any specific CRM's fields into core tables.
- Typed columns for known fields; JSONB for the experimental tail only; promote-not-duplicate.
- Every new admin mutation writes an `audit_events` row on the same request session (existing atomic invariant).
- Emit lifecycle events for CRM consumption; do **not** build a bespoke CRM in-repo.
- StrEnum for `account_status` and `environment` (centralized domain enums per constitution sr-007) — no scattered magic strings.

## Implementation Plan (follow-on task, derived from this ADR)

1. **Schema.** Extend `tenants` (display_name, contact fields, account_status, notes, onboarded_at, crm_account_id, account_ref, metadata JSONB) and `api_keys` (label, description, created_by, environment, revoked_reason, revoked_by, metadata JSONB) in `001_identity_schema.py`.
2. **Admin API + console.** Capture/edit customer fields at tenant-create and key `label` at mint; CRM-shaped read (account + contacts + keys); roster export endpoint; lifecycle events. Mirror in `manage_api_keys.py`.
3. **Provision-customer flow.** Atomic tenant + contact + first labeled key; idempotent upsert-by-`crm_account_id`.
4. **Retention/export coverage** for the new PII.
5. **ADR-011 tie-in.** Plugin surfaces Key ID + Tenant ID; key `label` helps operators map keys to customers during support.

## References

- Related ADR: [ADR-011 Retire On-Device Recognition](./ADR-011-retire-on-device-recognition-remote-only.md).
- Epic: [E15 Public Demo Launch Readiness](../epics/v0.4.0/public-demo-launch-readiness-epic.md); [E14 Self-Hosting](../epics/v0.3.1/self-hosting-epic.md).
- Prior decision: `maint_tenant_admin_scope_20260621` (admin service extraction scope).
- Code: `db/migrations/versions/001_identity_schema.py:162-199` (tenants/api_keys); `recognition/interface_adapters/http/routers/admin.py`; `recognition/application/services/api_key_admin_service.py`; `scripts/manage_api_keys.py`.
- Implementation task plan: _to be created after planning review._
