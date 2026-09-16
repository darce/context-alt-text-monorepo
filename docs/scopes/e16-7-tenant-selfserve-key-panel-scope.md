# E16-7. Tenant self-serve API key panel

Status: scoped 2026-09-15, rev2 2026-09-16 — awaiting plan-draft
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
- Require an operator-provisioned tenant with a non-NULL primary contact email before portal access; the prerequisite is exactly `make provision-customer EMAIL=<e> ENV=prod [PLAN=pro] [LABEL="Name"]` (ENV=prod is required by the service Makefile). No signup, billing, or tenant creation in this MVP. [CARD-10]
- If no tenant matches the normalized email, or the tenant row has NULL email, return `403 tenant_not_eligible` (a distinct code), create no tenant, and write one row to the new pre-tenant `portal_auth_events` table: `id uuid pk`, `clerk_sub text not null`, `email_hash text not null` (sha256 of the normalized email, never the raw email), `outcome text not null` in {`tenant_not_eligible`, `email_unverified`, `claim_missing`}, and `created_at timestamptz`. Persist nothing about the Clerk subject beyond that row in this MVP. The table is not tenant-scoped, is RLS-exempt like `api_keys` because it is needed before tenant resolution, is registered in `EXPECTED_SCHEMA_TABLES`, and its rows are kept (negligible volume). [SEC-01][DATA-13]
- A missing email claim returns `403 claim_missing`, and an unverified email claim returns `403 email_unverified`; each writes one `portal_auth_events` row with the corresponding outcome.
- Ship the keys panel only: authenticated tenants can see their own key metadata (`id`, `created_at`, `last_used_at`, `expires_at`, `revoked_at`), rotate, and revoke. [PG-02][ARCH-13]
- Keep the existing hashed `api_keys` store and `api_key_admin_service`; `api_keys` and `tenants` are intentionally outside `TENANT_TABLES` (RLS-exempt) because recognition auth must look a key up before any tenant is known; the portal therefore uses the same DB role and enforces isolation structurally in the repository layer — every portal query is issued through a `TenantScopedApiKeyRepository(tenant_id)` wrapper whose methods take no tenant argument and always add `WHERE tenant_id = :tenant_id` [ARCH-13], plus a per-object ownership check before every mutation [WEB-08]. [PG-02]
- Make rotation immediate and atomic for a named key: `POST /portal/keys/{id}/rotate` mints one new `secrets.token_urlsafe(32)` key with the old row's `rate_limit_tier` and `expires_at` policy, shows its raw value once, hashes it for storage, and sets `revoked_at = now()` on exactly that key id in one transaction. The handler INSERTs the `portal_rotations` reservation row FIRST inside that transaction, before mint/revoke. On `UniqueViolation` for `(tenant_id, idempotency_key)`, roll back, re-read the winner row, compare `request_fingerprint`, and return replay metadata with `raw_key: null, replayed: true` when equal; return 422 when different. Catch ONLY the unique-violation error class; every other error propagates. Authorize `key.tenant_id == resolved tenant`; return 404 otherwise (never 403 that leaks existence); rotating an already-revoked key returns 409; multiple active keys per tenant remain allowed. A repeated request with the same `Idempotency-Key` and fingerprint replays the existing rotation metadata without another mint; the raw secret is not replayed. The operator accepts the WP-side outage until the new key is pasted into wp-admin Settings and Test Connection passes. [API-02][DATA-13][WEB-08][WEB-16]
- Make revoke irreversible (`revoked_at = now()`), check that the addressed key belongs to the resolved tenant before the write, and record an audit event with the Clerk subject and email. Dual control is judged excessive for self-serve; the audit trail is the compensating evidence. [WEB-08][SECD-04]
- Preserve the existing SHA-256 hash behavior for the 43-character random token as a known, accepted risk; changing the hashing scheme is out of scope. [PHP-09]
- Separate the portal router from the Tailscale-only operator router and its shared `X-Admin-Token`; the portal uses the same DB role with repository-level isolation and never reuses the admin dependency or token. [SECD-02][CARD-10]
- Treat identity as a generic subdomain to buy (Clerk) and key issuance as supporting/core functionality to build (the thin tenant-scoped router). [DOM-01]
- Read the recognition DB directly instead of the planned business DB from E16-1. This is an explicit greenfield deviation: there are no production users, so the existing hashed key store is the narrowest source of truth for this MVP. [DOM-01][SECD-02]
- On Clerk JWKS failure, fail the portal loudly with a distinct 503 while keeping the recognition API path independent of Clerk; use bounded JWKS timeouts and cached verification keys. [CARD-07][RES-13]

## Architecture sketch

- Add a FastAPI `portal` router under `/portal`. The portal router MUST NOT depend on `get_session`/`get_optional_session`. Define `get_portal_session` in a new `deps/portal_session.py`; it takes NO request tenant input (no header, no query), verifies the Clerk session JWT, requires the verified `email` claim and `email_verified == true` (or Clerk's equivalent primary-verified flag — [the spike confirms the exact claim name]), lowercases + trims it, and resolves the tenant server-side from the verified Clerk claims via `TenantRepository.find_by_primary_contact_email(email)`. Before yielding, it sets `app.current_tenant` to the RESOLVED tenant id on the session so `audit_events` and `portal_rotations` writes pass FORCE RLS. There is no tenant-id trust from request headers or bodies.
- Endpoints:

  | Endpoint | Behavior |
  | --- | --- |
  | `GET /portal/me` | Return the verified Clerk subject/email and resolved tenant summary. |
  | `GET /portal/keys` | Return only the resolved tenant's key metadata: `id`, `created_at`, `last_used_at`, `expires_at`, and `revoked_at`. |
  | `POST /portal/keys/{id}/rotate` | Require `Idempotency-Key`; authorize the named key for the resolved tenant (404 otherwise, 409 if already revoked), mint with the old row's `rate_limit_tier` and `expires_at` policy, revoke exactly that key in one transaction, and return the raw value only in the first successful response. |
  | `POST /portal/keys/{id}/revoke` | Authorize the key's `tenant_id` before the irreversible revoke and audit write. |

- `api_key_admin_service.mint_api_key` only mints, hashes, and persists (it does not commit or audit). `revoke_key_atomic`, `RevokeOutcome`, `UnknownKeyError`, and the `audit_events` writes currently live in `recognition/interface_adapters/http/routers/admin.py` (`revoke_key_atomic` at ~L267); Slice 0 moves them into `api_key_admin_service.py` behind transactional `rotate_api_key(session, *, key_id, tenant_id, actor)` and `revoke_api_key(session, *, key_id, tenant_id, actor)` functions that write the `audit_events` row (actor = Clerk `sub` + email, or admin token id) in the same transaction and roll back the key mutation if the audit insert fails. Successful portal rotate/revoke actions write `audit_events` with the resolved `tenant_id`; pre-tenant auth failures write `portal_auth_events` because `audit_events.tenant_id` is non-null. Reuse `SqlAlchemyApiKeyRepository.list_for_tenant` and the existing auth outcome vocabulary (`invalid_key`, `expired`, `revoked`, `tenant_mismatch`) where the recognition API validates keys. The portal's Clerk dependency is separate from `_require_auth_impl`, and the portal router never imports the admin router module [SECD-02].
- Every portal query goes through `TenantScopedApiKeyRepository(tenant_id)`, whose methods take no tenant argument and always add `WHERE tenant_id = :tenant_id`; per-object ownership is checked before every mutation. All `portal_rotations` access goes through a new `TenantScopedRotationRepository(tenant_id)`, a sibling of `TenantScopedApiKeyRepository`; its methods take no tenant argument and always add `WHERE tenant_id = :tenant_id`. `api_keys` and `tenants` remain outside `TENANT_TABLES` (RLS-exempt) because recognition auth must look a key up before any tenant is known, so the portal uses the same DB role and relies on repository-layer structural isolation. [ARCH-13][WEB-08]
- Add durable idempotency table `portal_rotations` directly in `001_identity_schema.py` per greenfield policy. Columns: `id uuid pk`, `tenant_id uuid fk tenants`, `idempotency_key text`, `request_fingerprint text` (sha256 of method+path+key id), `old_key_id uuid fk api_keys`, `new_key_id uuid fk api_keys`, and `created_at timestamptz`; enforce `UNIQUE (tenant_id, idempotency_key)`. Register `portal_rotations` in BOTH `TENANT_TABLES` and `EXPECTED_SCHEMA_TABLES`; `TENANT_TABLES` gives it FORCE RLS, with the `tenant_isolation_portal_rotations` policy created via `ensure_rls`. The reservation INSERT happens FIRST inside the rotate transaction, before mint/revoke. Same key + same fingerprint replays metadata (`new_key_id`, `created_at`, and `revoked_at` of old) with `raw_key: null` and `replayed: true`; same key + different fingerprint returns 422. On a concurrent `UniqueViolation` for `(tenant_id, idempotency_key)`, roll back, re-read the winner row, compare `request_fingerprint`, and return the replay or 422 response; catch only that unique-violation error class and propagate every other error. Keep rows for tens of tenants; retention is negligible. Reuse `scene/domain/describe_run.py::normalize_idempotency_key` and `scene/application/describe_run_repository.py::DescribeRunRepository.get_run_by_idempotency_key`. [API-02][DATA-13]
- Add `portal_auth_events` directly in `001_identity_schema.py` with `id uuid pk`, `clerk_sub text not null`, `email_hash text not null` (sha256 of the normalized email, never the raw email), `outcome text not null` in {`tenant_not_eligible`, `email_unverified`, `claim_missing`}, and `created_at timestamptz`. It is pre-tenant, not tenant-scoped, and RLS-exempt like `api_keys`; register it in `EXPECTED_SCHEMA_TABLES` and keep rows indefinitely because volume is negligible.
- Serve a minimal server-rendered HTML page that reuses the escaped f-string pattern of `admin_console.py::render_console` — extract the shared HTML-escaping helpers into `recognition/interface_adapters/http/html_render.py` (Slice 0 refactor item) and build `portal_console.py::render_portal(...)` on them. No Jinja2, no StaticFiles, no htmx, no npm build; the existing `test_admin_mount.py` module ban stays in force and a twin assertion is added for the portal mount. The new page is served on the new `app.altcontext.com` Caddy vhost. The vhost needs an operator-created DNS A record, proxies portal requests to the service, and keeps `respond 404` for every `/admin*` path. Existing API vhosts retain their `/admin*` 404 behavior. [WEB-16][CARD-10]
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
8. **SC-8** — Two concurrent rotate requests with the same Idempotency-Key and fingerprint produce exactly one new key and one revoked key; the loser receives the replay response (PostgreSQL-backed concurrent test). [API-02][RES-13]
9. **SC-9** — Cross-tenant test: tenant B cannot read or replay tenant A's `portal_rotations` row, at both repository and RLS level. [ARCH-13][SECD-04]
10. **SC-10** — A portal request carrying `X-Tenant-ID` for another tenant is served strictly as the Clerk-resolved tenant; the header is ignored (test asserts no cross-tenant rows returned). [SECD-02][WEB-08]
11. **SC-11** — Direct `POST /portal/keys/{id}/revoke` (200 → `revoked_at` set + `audit_events` row; 404 for a foreign key id; 409 if already revoked).
12. **SC-12** — `GET /portal/me` returns `{tenant_id, email, key_count}` for an eligible user and 403 `tenant_not_eligible` for an unmatched one, with a `portal_auth_events` row.
13. **SC-13** — Missing `email` claim → 403 `claim_missing`, `email_verified=false` → 403 `email_unverified`, each with a `portal_auth_events` row.
14. **SC-14** — The server-rendered page (`GET /portal/`) returns 200 HTML listing the tenant's keys with no `jinja2` in `sys.modules`.
15. **SC-15** — If the `audit_events` insert fails inside rotate, the key mutation rolls back and no `portal_rotations` row survives.

Each criterion maps one-to-one to the `SC-1` through `SC-15` cases in the adjacent eval spec.

## Not-doing

- Demo-host self-heal mint on 401 (decision 6437, track 2); operators paste the new key into wp-admin Settings and use Test Connection.
- ADR-012 key metadata columns `label` and `created_by`; those are owned by CRM-1.
- Plugin auto-adopt of a rotated key; keep paste plus Test Connection.
- Usage or quota display.
- Signup, billing, and any grace window; rotation is immediate and the old key is revoked in the same transaction.
- Any schema change beyond what rotation and pre-tenant auth-event capture needs; schema change limited to the `portal_rotations` AND `portal_auth_events` tables, added directly in `001_identity_schema.py` per greenfield policy.
- No `/admin` tenant-email update route in this MVP; `/admin` has no tenant-email field or email-update route.

## Assumptions + open questions

- Clerk plan and cost are acceptable, and the final identity shape (Clerk user versus organization) is still open; the spike must settle the org/email claim mapping. [CARD-06]
- Every tenant already exists; `primary_contact_email` is nullable with a unique index, and portal access requires the normalized Clerk email to match it. A tenant with no match or NULL email is `tenant_not_eligible` (403), with no tenant creation and one `portal_auth_events` row. Operator provisioning remains outside the portal.
- The DNS A record for `app.altcontext.com` is an operator action.
- The 500 ms p95 target is an intake assumption, not an existing SLO.
- RLS extension to `api_keys` is explicitly deferred; revisit if the portal ever gets its own DB role.

## Dispatch decomposition

0. **Slice 0 refactor:** move `revoke_key_atomic`, `RevokeOutcome`, `UnknownKeyError`, and the `audit_events` writes from `recognition/interface_adapters/http/routers/admin.py` into `api_key_admin_service.py` behind transactional `rotate_api_key(session, *, key_id, tenant_id, actor)` and `revoke_api_key(session, *, key_id, tenant_id, actor)`; the audit insert and key mutation share a transaction, and an audit failure rolls back the key mutation. Extract the shared HTML-escaping helpers into `recognition/interface_adapters/http/html_render.py` for `portal_console.py::render_portal(...)`; add `portal_rotations` to both `TENANT_TABLES` and `EXPECTED_SCHEMA_TABLES`, and add `portal_auth_events` to `EXPECTED_SCHEMA_TABLES`. The portal router never imports the admin router module [SECD-02].
1. **SPIKE lane:** throwaway verification of a Clerk JWT against JWKS in FastAPI; record claim shape and JWKS-outage behavior as a handoff decision, gated per [CARD-06]. Exit criterion: decision recorded and code discarded.
2. **RED lane:** tests only: `recognition/tests/api/test_portal_auth.py`, `recognition/tests/api/test_portal_keys.py`, `recognition/tests/api/test_portal_ui.py`, and `recognition/tests/infra/test_caddyfile_admin_404.py`; done when they collect and fail.
3. **IMPLEMENTATION lane:** build the Clerk dependency, tenant-scoped portal router, app vhost, durable rotation idempotency, and key-panel behavior until the RED tests pass; preserve the existing `/admin*` 404 boundary.

## Canon gaps

- no rule for shown-once/unrecoverable secret display semantics; no rule for JWT-to-internal-identity re-derivation beyond SEC-01.
