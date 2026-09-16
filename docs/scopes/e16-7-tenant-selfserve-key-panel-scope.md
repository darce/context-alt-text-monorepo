# E16-7. Tenant self-serve API key panel

Status: scoped 2026-09-15, rev1 2026-09-16 — awaiting plan-draft
Task: E16-7
Epic: E16
Source decisions: 11708, 11709
Triage: review run e16-7-plan-draft-triage-20260915-16706136; decision 11713

## Problem

- A production DB reset leaves operators manually ferrying raw keys back to the WordPress site, the failure mode recorded in decision 6437.
- Tenants have no bounded self-serve path to see, rotate, or revoke their own recognition keys; the operator console is the wrong trust boundary for that workflow.
- A portal must not broaden the existing operator `/admin` surface or trust a client-supplied tenant identifier.

## MVP scope

- Buy identity only: use Clerk; verify the Clerk session JWT server-side in FastAPI, require its `email` claim and `email_verified == true` (or Clerk's equivalent primary-verified flag — [the spike confirms the exact claim name]), lowercase + trim the email before lookup via `TenantRepository.find_by_primary_contact_email(email)`. This is a new repository method (none exists today); `tenants.primary_contact_email` is `nullable=True` with a unique index. Ignore any client-supplied tenant id. [SEC-01][CARD-10]
- Require an operator-provisioned tenant with a non-NULL primary contact email before portal access; `/admin` tenant-create leaves email NULL, so the prerequisite is `make provision-customer EMAIL=<e>` (root Makefile) or an operator setting the email via `/admin`. No signup, billing, or tenant creation in this MVP. [CARD-10]
- If no tenant matches the normalized email, or the tenant row has NULL email, return `403 tenant_not_eligible` (a distinct code), create no tenant, and write an audit row. Persist nothing about the Clerk subject beyond that audit row in this MVP.
- Ship the keys panel only: authenticated tenants can see their own key metadata (`id`, `created_at`, `last_used_at`, `expires_at`, `revoked_at`), rotate, and revoke. [PG-02][ARCH-13]
- Keep the existing hashed `api_keys` store and `api_key_admin_service`; `api_keys` and `tenants` are intentionally outside `TENANT_TABLES` (RLS-exempt) because recognition auth must look a key up before any tenant is known; the portal therefore uses the same DB role and enforces isolation structurally in the repository layer — every portal query is issued through a `TenantScopedApiKeyRepository(tenant_id)` wrapper whose methods take no tenant argument and always add `WHERE tenant_id = :tenant_id` [ARCH-13], plus a per-object ownership check before every mutation [WEB-08]. [PG-02]
- Make rotation immediate and atomic for a named key: `POST /portal/keys/{id}/rotate` mints one new `secrets.token_urlsafe(32)` key with the old row's `rate_limit_tier` and `expires_at` policy, shows its raw value once, hashes it for storage, and sets `revoked_at = now()` on exactly that key id in one transaction. Authorize `key.tenant_id == resolved tenant`; return 404 otherwise (never 403 that leaks existence); rotating an already-revoked key returns 409; multiple active keys per tenant remain allowed. A repeated request with the same `Idempotency-Key` and fingerprint replays the existing rotation metadata without another mint; the raw secret is not replayed. The operator accepts the WP-side outage until the new key is pasted into wp-admin Settings and Test Connection passes. [API-02][DATA-13][WEB-08][WEB-16]
- Make revoke irreversible (`revoked_at = now()`), check that the addressed key belongs to the resolved tenant before the write, and record an audit event with the Clerk subject and email. Dual control is judged excessive for self-serve; the audit trail is the compensating evidence. [WEB-08][SECD-04]
- Preserve the existing SHA-256 hash behavior for the 43-character random token as a known, accepted risk; changing the hashing scheme is out of scope. [PHP-09]
- Separate the portal router from the Tailscale-only operator router and its shared `X-Admin-Token`; the portal uses the same DB role with repository-level isolation and never reuses the admin dependency or token. [SECD-02][CARD-10]
- Treat identity as a generic subdomain to buy (Clerk) and key issuance as supporting/core functionality to build (the thin tenant-scoped router). [DOM-01]
- Read the recognition DB directly instead of the planned business DB from E16-1. This is an explicit greenfield deviation: there are no production users, so the existing hashed key store is the narrowest source of truth for this MVP. [DOM-01][SECD-02]
- On Clerk JWKS failure, fail the portal loudly with a distinct 503 while keeping the recognition API path independent of Clerk; use bounded JWKS timeouts and cached verification keys. [CARD-07][RES-13]

## Architecture sketch

- Add a FastAPI `portal` router under `/portal` with a Clerk-JWT dependency that verifies the session JWT, requires the verified `email` claim and `email_verified == true` (or Clerk's equivalent primary-verified flag — [the spike confirms the exact claim name]), lowercases + trims it, and resolves the tenant server-side through `TenantRepository.find_by_primary_contact_email(email)`; there is no tenant-id trust from request headers or bodies.
- Endpoints:

  | Endpoint | Behavior |
  | --- | --- |
  | `GET /portal/me` | Return the verified Clerk subject/email and resolved tenant summary. |
  | `GET /portal/keys` | Return only the resolved tenant's key metadata: `id`, `created_at`, `last_used_at`, `expires_at`, and `revoked_at`. |
  | `POST /portal/keys/{id}/rotate` | Require `Idempotency-Key`; authorize the named key for the resolved tenant (404 otherwise, 409 if already revoked), mint with the old row's `rate_limit_tier` and `expires_at` policy, revoke exactly that key in one transaction, and return the raw value only in the first successful response. |
  | `POST /portal/keys/{id}/revoke` | Authorize the key's `tenant_id` before the irreversible revoke and audit write. |

- `api_key_admin_service.mint_api_key` only mints, hashes, and persists (it does not commit or audit). `revoke_key_atomic`, `RevokeOutcome`, `UnknownKeyError`, and the `audit_events` writes currently live in `recognition/interface_adapters/http/routers/admin.py` (`revoke_key_atomic` at ~L267); Slice 0 moves them into `api_key_admin_service.py` behind transactional `rotate_api_key(session, *, key_id, tenant_id, actor)` and `revoke_api_key(session, *, key_id, tenant_id, actor)` functions that write the audit row (actor = Clerk `sub` + email, or admin token id) in the same transaction and roll back the key mutation if the audit insert fails. Reuse `SqlAlchemyApiKeyRepository.list_for_tenant` and the existing auth outcome vocabulary (`invalid_key`, `expired`, `revoked`, `tenant_mismatch`) where the recognition API validates keys. The portal's Clerk dependency is separate from `_require_auth_impl`, and the portal router never imports the admin router module [SECD-02].
- Every portal query goes through `TenantScopedApiKeyRepository(tenant_id)`, whose methods take no tenant argument and always add `WHERE tenant_id = :tenant_id`; per-object ownership is checked before every mutation. `api_keys` and `tenants` remain outside `TENANT_TABLES` (RLS-exempt) because recognition auth must look a key up before any tenant is known, so the portal uses the same DB role and relies on repository-layer structural isolation. [ARCH-13][WEB-08]
- Add durable idempotency table `portal_rotations` directly in `001_identity_schema.py` per greenfield policy. Columns: `id uuid pk`, `tenant_id uuid fk tenants`, `idempotency_key text`, `request_fingerprint text` (sha256 of method+path+key id), `old_key_id uuid fk api_keys`, `new_key_id uuid fk api_keys`, and `created_at timestamptz`; enforce `UNIQUE (tenant_id, idempotency_key)`. Same key + same fingerprint replays metadata (`new_key_id`, `created_at`, and `revoked_at` of old) with `raw_key: null` and `replayed: true`; same key + different fingerprint returns 422. Keep rows for tens of tenants; retention is negligible. Reuse `scene/domain/describe_run.py::normalize_idempotency_key` and `scene/application/describe_run_repository.py::DescribeRunRepository.get_run_by_idempotency_key`. [API-02][DATA-13]
- Serve a minimal server-rendered HTML page using the Jinja2 templates already used by `/admin/ui/*` on the new `app.altcontext.com` Caddy vhost; no SPA and no npm build. The vhost needs an operator-created DNS A record, proxies portal requests to the service, and keeps `respond 404` for every `/admin*` path. Existing API vhosts retain their `/admin*` 404 behavior.
- Keep operator admin mutations Tailscale-only with the single shared `X-Admin-Token`; a portal principal can touch only its own tenant's keys. [SECD-02][CARD-10]
- Clerk commitment is gated on a spike proving the JWT verification path, organization/email claim shape, and outage behavior before durable purchase or deployment evidence is accepted. [CARD-06]
- Eval registration is not included here: `packages/workbay-system/config/evals/` does not exist in this checkout, so the eval spec lives beside this scope note; registration in the eval runner is a follow-up owned by another lane.

## Non-functional intake

- Latency: propose p95 ≤ 500 ms for `GET /portal/keys` and `POST /portal/keys/{id}/rotate`; this is an assumption for plan-draft validation.
- Idempotency: `POST /portal/keys/{id}/rotate` requires `Idempotency-Key`; a retry must not double-execute and must replay the prior rotation result. [API-02][DATA-13]
- Clerk outage: use a timeout and cached JWKS; return a distinct 503 from portal auth when verification cannot proceed, while `/analyze` with a valid API key does not call Clerk and remains available. [CARD-07][RES-13]
- Staleness: none expected for reads-after-writes; portal reads and writes use the same recognition DB.
- Scale: target tens of tenants; no capacity claim is made for 10× growth in this MVP.

## Success criteria

1. **SC-1** — Cross-tenant key access through the portal returns 404 or 403 and never exposes the other tenant's key.
2. **SC-2** — An authenticated tenant sees its own key metadata—`id`, `created_at`, `last_used_at`, `expires_at`, and `revoked_at`—and a client-supplied tenant id cannot change the server-resolved tenant.
3. **SC-3** — `POST /portal/keys/{id}/rotate` with the same `Idempotency-Key` and request fingerprint mints exactly one new key, preserves the old key's `rate_limit_tier` and `expires_at` policy, and replays rotation metadata without a second mint; a different fingerprint returns 422.
4. **SC-4** — `POST /portal/keys/{id}/rotate` authorizes only a key owned by the resolved tenant (404 otherwise, never 403), returns 409 for an already-revoked key, revokes exactly that key immediately in the same transaction, and the recognition API rejects it with a `revoked` outcome.
5. **SC-5** — The raw key is shown exactly once in the first successful rotate response, is not re-shown on an idempotent replay, and never appears in application logs, audit rows, or URLs.
6. **SC-6** — Every `/admin*` request on the `app.altcontext.com` vhost returns 404.
7. **SC-7** — When Clerk JWKS is unreachable, the portal returns a distinct 503 while `/analyze` with a valid key still succeeds.

Each criterion maps one-to-one to the `SC-1` through `SC-7` cases in the adjacent eval spec.

## Not-doing

- Demo-host self-heal mint on 401 (decision 6437, track 2); operators paste the new key into wp-admin Settings and use Test Connection.
- ADR-012 key metadata columns `label` and `created_by`; those are owned by CRM-1.
- Plugin auto-adopt of a rotated key; keep paste plus Test Connection.
- Usage or quota display.
- Signup, billing, and any grace window; rotation is immediate and the old key is revoked in the same transaction.
- Any schema change beyond what rotation needs; schema change limited to the `portal_rotations` table, added directly in `001_identity_schema.py` per greenfield policy.

## Assumptions + open questions

- Clerk plan and cost are acceptable, and the final identity shape (Clerk user versus organization) is still open; the spike must settle the org/email claim mapping. [CARD-06]
- Every tenant already exists; `primary_contact_email` is nullable with a unique index, and portal access requires the normalized Clerk email to match it. A tenant with no match or NULL email is `tenant_not_eligible` (403), with no tenant creation and an audit row. Operator provisioning remains outside the portal.
- The DNS A record for `app.altcontext.com` is an operator action.
- The 500 ms p95 target is an intake assumption, not an existing SLO.
- RLS extension to `api_keys` is explicitly deferred; revisit if the portal ever gets its own DB role.

## Dispatch decomposition

0. **Slice 0 refactor:** move `revoke_key_atomic`, `RevokeOutcome`, `UnknownKeyError`, and the `audit_events` writes from `recognition/interface_adapters/http/routers/admin.py` into `api_key_admin_service.py` behind transactional `rotate_api_key(session, *, key_id, tenant_id, actor)` and `revoke_api_key(session, *, key_id, tenant_id, actor)`; the audit insert and key mutation share a transaction, and an audit failure rolls back the key mutation. The portal router never imports the admin router module [SECD-02].
1. **SPIKE lane:** throwaway verification of a Clerk JWT against JWKS in FastAPI; record claim shape and JWKS-outage behavior as a handoff decision, gated per [CARD-06]. Exit criterion: decision recorded and code discarded.
2. **RED lane:** tests only: `recognition/tests/api/test_portal_auth.py`, `recognition/tests/api/test_portal_keys.py`, and `recognition/tests/infra/test_caddyfile_admin_404.py`; done when they collect and fail.
3. **IMPLEMENTATION lane:** build the Clerk dependency, tenant-scoped portal router, app vhost, durable rotation idempotency, and key-panel behavior until the RED tests pass; preserve the existing `/admin*` 404 boundary.

## Canon gaps

- no rule for shown-once/unrecoverable secret display semantics; no rule for JWT-to-internal-identity re-derivation beyond SEC-01.
