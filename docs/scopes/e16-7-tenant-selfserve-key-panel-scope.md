# E16-7. Tenant self-serve API key panel

Status: scoped 2026-09-15 — awaiting plan-draft
Task: E16-7
Epic: E16
Source decisions: 11708, 11709

## Problem

- A production DB reset leaves operators manually ferrying raw keys back to the WordPress site, the failure mode recorded in decision 6437.
- Tenants have no bounded self-serve path to see, rotate, or revoke their own recognition keys; the operator console is the wrong trust boundary for that workflow.
- A portal must not broaden the existing operator `/admin` surface or trust a client-supplied tenant identifier.

## MVP scope

- Buy identity only: use Clerk; verify the Clerk JWT server-side in FastAPI, then re-derive `tenant_id` from the verified identity's email and the unique `tenants.primary_contact_email` index. Ignore any client-supplied tenant id. [SEC-01][CARD-10]
- Require an operator-provisioned tenant (`/admin` or `make provision-customer`) before portal access; no signup, billing, or tenant creation in this MVP. [CARD-10]
- Ship the keys panel only: authenticated tenants can see their own key metadata (`id`, `created_at`, `last_used_at`, `expires_at`, `revoked_at`), rotate, and revoke. [PG-02][ARCH-13]
- Keep the existing hashed `api_keys` store and `api_key_admin_service`; list queries and key mutations carry the resolved `tenant_id`, with a non-owner portal DB role and RLS as the structural isolation boundary. [PG-02][ARCH-13][WEB-08]
- Make rotation immediate and atomic: mint one new `secrets.token_urlsafe(32)` key, show its raw value once, hash it for storage, and set `revoked_at = now()` on the old key in the same transaction. A repeated request with the same `Idempotency-Key` replays the existing rotation result without another mint; the raw secret is not replayed. The operator accepts the WP-side outage until the new key is pasted into wp-admin Settings and Test Connection passes. [API-02][DATA-13][WEB-08][WEB-16]
- Make revoke irreversible (`revoked_at = now()`), check that the addressed key belongs to the resolved tenant before the write, and record an audit event with the Clerk subject and email. Dual control is judged excessive for self-serve; the audit trail is the compensating evidence. [WEB-08][SECD-04]
- Preserve the existing SHA-256 hash behavior for the 43-character random token as a known, accepted risk; changing the hashing scheme is out of scope. [PHP-09]
- Separate the portal router and DB role from the Tailscale-only operator router and its shared `X-Admin-Token`; the portal never reuses the admin dependency or token. [SECD-02][CARD-10]
- Treat identity as a generic subdomain to buy (Clerk) and key issuance as supporting/core functionality to build (the thin tenant-scoped router). [DOM-01]
- Read the recognition DB directly instead of the planned business DB from E16-1. This is an explicit greenfield deviation: there are no production users, so the existing hashed key store is the narrowest source of truth for this MVP. [DOM-01][SECD-02]
- On Clerk JWKS failure, fail the portal loudly with a distinct 503 while keeping the recognition API path independent of Clerk; use bounded JWKS timeouts and cached verification keys. [CARD-07][RES-13]

## Architecture sketch

- Add a FastAPI `portal` router under `/portal` with a Clerk-JWT dependency that resolves the tenant server-side from `primary_contact_email`; there is no tenant-id trust from request headers or bodies.
- Endpoints:

  | Endpoint | Behavior |
  | --- | --- |
  | `GET /portal/me` | Return the verified Clerk subject/email and resolved tenant summary. |
  | `GET /portal/keys` | Return only the resolved tenant's key metadata: `id`, `created_at`, `last_used_at`, `expires_at`, and `revoked_at`. |
  | `POST /portal/keys/rotate` | Require `Idempotency-Key`; mint once, revoke the old key in the same transaction, and return the raw value only in the first successful response. |
  | `POST /portal/keys/{id}/revoke` | Authorize the key's `tenant_id` before the irreversible revoke and audit write. |

- Reuse `api_key_admin_service.mint_api_key`, its existing hash/raw-token behavior and audit-event writes, `SqlAlchemyApiKeyRepository.list_for_tenant`, and the existing auth outcome vocabulary (`invalid_key`, `expired`, `revoked`, `tenant_mismatch`) where the recognition API validates keys. The portal's Clerk dependency is separate from `_require_auth_impl`.
- Serve a minimal static SPA or server-rendered page on the new `app.altcontext.com` Caddy vhost. The vhost needs an operator-created DNS A record, proxies portal requests to the service, and keeps `respond 404` for every `/admin*` path. Existing API vhosts retain their `/admin*` 404 behavior.
- Keep operator admin mutations Tailscale-only with the single shared `X-Admin-Token`; a portal principal can touch only its own tenant's keys. [SECD-02][CARD-10]
- Clerk commitment is gated on a spike proving the JWT verification path, organization/email claim shape, and outage behavior before durable purchase or deployment evidence is accepted. [CARD-06]
- Eval registration is not included here: `packages/workbay-system/config/evals/` does not exist in this checkout, so the eval spec lives beside this scope note; registration in the eval runner is a follow-up owned by another lane.

## Non-functional intake

- Latency: propose p95 ≤ 500 ms for `GET /portal/keys` and `POST /portal/keys/rotate`; this is an assumption for plan-draft validation.
- Idempotency: `POST /portal/keys/rotate` requires `Idempotency-Key`; a retry must not double-execute and must replay the prior rotation result. [API-02][DATA-13]
- Clerk outage: use a timeout and cached JWKS; return a distinct 503 from portal auth when verification cannot proceed, while `/analyze` with a valid API key does not call Clerk and remains available. [CARD-07][RES-13]
- Staleness: none expected for reads-after-writes; portal reads and writes use the same recognition DB.
- Scale: target tens of tenants; no capacity claim is made for 10× growth in this MVP.

## Success criteria

1. **SC-1** — Cross-tenant key access through the portal returns 404 or 403 and never exposes the other tenant's key.
2. **SC-2** — An authenticated tenant sees its own key metadata—`id`, `created_at`, `last_used_at`, `expires_at`, and `revoked_at`—and a client-supplied tenant id cannot change the server-resolved tenant.
3. **SC-3** — Submitting Rotate twice with the same `Idempotency-Key` mints exactly one new key and replays the same result without a second mint.
4. **SC-4** — Immediately after rotation, the old key is rejected by the recognition API with a `revoked` outcome.
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
- Any schema change beyond what rotation needs; none is needed for this panel MVP.

## Assumptions + open questions

- Clerk plan and cost are acceptable, and the final identity shape (Clerk user versus organization) is still open; the spike must settle the org/email claim mapping. [CARD-06]
- Every tenant already exists and has a unique `primary_contact_email`; operator provisioning remains outside the portal.
- The DNS A record for `app.altcontext.com` is an operator action.
- The 500 ms p95 target is an intake assumption, not an existing SLO.
- The portal DB role, RLS policy wiring, and idempotency replay mechanism must be demonstrated in plan-draft without weakening the existing admin isolation boundary.

## Dispatch decomposition

1. **RED lane:** add tests only, forbidden from touching implementation source; done when the tests collect and fail. The test files are `recognition/tests/api/test_portal_auth.py` and `recognition/tests/api/test_portal_keys.py`.
2. **IMPLEMENTATION lane:** build the Clerk dependency, tenant-scoped portal router, app vhost, and key-panel behavior until the RED tests pass; preserve the existing `/admin*` 404 boundary.

## Canon gaps

- no rule for shown-once/unrecoverable secret display semantics; no rule for JWT-to-internal-identity re-derivation beyond SEC-01.
