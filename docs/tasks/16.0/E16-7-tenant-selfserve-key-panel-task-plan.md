# E16-7. Tenant self-serve API key panel

- **Date**: 2026-09-16
- **Author**: gpt-5.6-luna
- **Owning Epic**: `docs/epics/v0.3.1/saas-foundation-epic.md`
- **Epic Short ID**: `E16`
- **Task ID**: `E16-7`
- **Target Branch**: `feature/e16-7`
- **Review Coverage Target**: 2

> **Status**: Draft. The E16 epic lists phases E16-1..E16-6 only, and E16-7 is not yet allocated there; this plan is a scoped draft for review and carry-forward, not an implementation-ready `/incremental-implementation` input.

## Objective

Give an operator-provisioned tenant a bounded, server-rendered portal at `/portal` where an eligible Clerk-authenticated contact can inspect its own recognition-key metadata, rotate a named key exactly once per idempotency key, and revoke a key irreversibly. Preserve the existing Tailscale-only `/admin` boundary and recognition API behavior while adding durable tenant isolation, pre-tenant auth-event evidence, and an operator runbook for provisioning and Clerk configuration.

## Intake

- **Scope one-pager**: `docs/scopes/e16-7-tenant-selfserve-key-panel-scope.md` (rev3, 2026-09-16)
- **Eval specification**: `docs/scopes/e16-7-tenant-selfserve-key-panel-evals.json` (SC-1 through SC-20)
- **Key Q&A decisions**: `decision #11708`, `decision #11709`, and triage decision `#11713`
- **Not-Doing**: signup, billing, tenant creation, usage/quota display, plugin auto-adopt, demo-host self-heal mint, ADR-012 key metadata, `/admin` tenant-email updates, and changes to the existing API-key contract section.

## Problem Statement

After a production database reset, operators must ferry raw recognition keys back to WordPress manually. Tenants have no self-serve way to inspect, rotate, or revoke their own keys, while the existing operator console is Tailscale-only and must not become the tenant trust boundary. A client-supplied tenant identifier or an unverified Clerk claim must never select a tenant, and pre-tenant rejection evidence needs a separate RLS-exempt audit surface.

## Constraints

- Use Clerk only for identity purchase: verify session JWTs server-side in FastAPI, accept only RS256 with configured issuer and authorized parties, require `email` plus `email_verified == true` (or the spike-confirmed Clerk primary-verified equivalent), and do not ship Clerk JS on the panel [SEC-01][CARD-06].
- Resolve the tenant from lowercase-and-trimmed verified email through `apps/prototype-description-service/recognition/infrastructure/repositories/tenant_repository.py::SqlAlchemyTenantRepository.find_by_primary_contact_email (new)`; ignore `X-Tenant-ID`, query tenant ids, and body tenant ids [SEC-01][CARD-10][SECD-02].
- Require the exact operator prerequisite `make provision-customer EMAIL=<e> ENV=prod [PLAN=pro] [LABEL="Name"]`; there is no portal signup or tenant creation [CARD-10].
- Portal dependencies must not call `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py::get_session (existing)`, `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py::get_optional_session (existing)`, or `apps/prototype-description-service/recognition/interface_adapters/http/deps/tenant_common.py::get_tenant_id_optional (existing)`. Those paths consume `X-Tenant-ID`; portal sessions are new and server-resolved.
- Keep the recognition database as the source of truth for this greenfield portal; `api_keys` and `tenants` remain RLS-exempt, while `portal_rotations` is tenant-scoped and `portal_auth_events` is pre-tenant and RLS-exempt [DOM-01][SECD-02][PG-02][DATA-13].
- Preserve SHA-256 hashing for the existing 43-character random token, do not widen `audit_events.actor` beyond `varchar(100)`, and never put a raw key in logs, audit payloads, or URLs [PHP-09][SECD-04].
- Cookie-authenticated rotate/revoke requests require an HMAC of the verified Clerk `sid` with the per-session CSRF token and matching `Origin`/`Referer`; bearer-authenticated requests skip CSRF because bearer credentials are not ambient. Service-set cookies are `Secure; HttpOnly; SameSite=Lax` [WEB-08][SEC-01].
- Required-at-boot configuration must fail fast [rg-008]: `ACX_CLERK_ISSUER`, `ACX_CLERK_JWKS_URL`, `ACX_CLERK_AUTHORIZED_PARTIES`, and `ACX_PORTAL_CSRF_SECRET`. JWKS requests use bounded timeouts and cached keys; an unavailable verifier returns a distinct 503 without affecting `/analyze` [CARD-07][RES-13].
- The `ACX_PORTAL_TESTS_REQUIRE_PG=1` test mode must fail, not skip, when PostgreSQL is unreachable. The eval command must pass with zero skips, and every `/admin*` path on the new app host must remain 404 [CARD-10].
- This plan-draft lane creates only `docs/tasks/16.0/E16-7-tenant-selfserve-key-panel-task-plan.md`; scope note, epic, ADR, and implementation surfaces belong to their declared downstream lanes.

## Workflow Principles

- Authenticate and validate claims before deriving tenant context; authorization is based on the resolved tenant, never on request input.
- Keep untrusted-token failures (401), trusted-but-ineligible contacts (403), CSRF failures (403), and verifier outages (503) distinct and observable without leaking tenant existence [SEC-01][DATA-13].
- Reserve a rotation idempotency key first, perform mint/revoke/audit in one transaction, and make replay metadata deterministic without ever replaying the raw secret [API-02][DATA-13].
- Keep each slice independently reviewable as behavior plus proof; the RED lane names one test for each SC-1 through SC-20 case.
- Preserve the existing `/admin` response mapping and auth contract while putting tenant behavior in a separate portal router; do not import the admin router into portal code [SECD-02].
- Prefer narrow repository methods with structural tenant predicates over caller-provided tenant arguments [ARCH-13][WEB-08].

## Terminology

- **Resolved tenant**: the tenant selected from the normalized, verified Clerk email; it is the only tenant identity accepted by portal handlers.
- **Portal auth event**: a committed pre-tenant row for `tenant_not_eligible`, `email_unverified`, or `claim_missing`; invalid JWTs do not create one [DATA-13].
- **Rotation reservation**: a `portal_rotations` row inserted before mint/revoke to own `(tenant_id, idempotency_key)` and make concurrent retries deterministic.
- **Replay envelope**: a successful retry response containing prior rotation metadata with `raw_key: null` and `replayed: true`.
- **Ambient cookie**: the Clerk `__session` credential sent by a browser; unlike a bearer token, it requires CSRF and same-origin checks for mutations.

## Current State Analysis

- `apps/prototype-description-service/recognition/infrastructure/repositories/tenant_repository.py::SqlAlchemyTenantRepository (existing)` currently exposes `get`, `get_naming_agreement_enabled`, and `update_naming_agreement_enabled`, but not `find_by_primary_contact_email`. The normalized lookup pattern is inline at `apps/prototype-description-service/recognition/application/services/customer_provision_service.py::inline select(Tenant) lookup at L111 (existing)`, against the unique `tenants.primary_contact_email` column; Slice 0 adds the repository method.
- The rev3 scope note names `TenantScopedApiKeyRepository` and `TenantRepository.find_by_primary_contact_email` as if they already exist. They do not. The plan uses `apps/prototype-description-service/recognition/infrastructure/repositories/api_key_repository.py::SqlAlchemyApiKeyRepository.list_for_tenant (existing)` with the Clerk-resolved tenant id for key reads, and adds only `apps/prototype-description-service/recognition/infrastructure/repositories/portal_rotation_repository.py::TenantScopedRotationRepository (new)` for rotation rows. No `TenantScopedApiKeyRepository` is introduced.
- `apps/prototype-description-service/recognition/application/services/api_key_admin_service.py::mint_api_key (existing)` mints, hashes, and persists without committing or auditing. `apps/prototype-description-service/recognition/interface_adapters/http/routers/admin.py::revoke_key_atomic (existing)`, `apps/prototype-description-service/recognition/interface_adapters/http/routers/admin.py::UnknownKeyError (existing)`, and `apps/prototype-description-service/recognition/interface_adapters/http/routers/admin.py::RevokeOutcome (existing)` currently own revoke and audit behavior; Slice 0 moves the transactional domain operations behind new service functions while retaining admin response mapping.
- `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py::_apply_postgres_session_safety_settings (existing)`, `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py::get_session (existing)`, and `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py::get_optional_session (existing)` use `SET LOCAL` and `X-Tenant-ID` through `apps/prototype-description-service/recognition/interface_adapters/http/deps/tenant_common.py::get_tenant_id_optional (existing)`. A portal request cannot reuse those dependencies; new portal sessions must establish context only after Clerk verification and tenant lookup.
- `apps/prototype-description-service/recognition/interface_adapters/http/admin_console.py::render_console (existing)` emits escaped f-string HTML. `apps/prototype-description-service/recognition/tests/api/test_admin_mount.py::module-ban assertion at L183-L188 (existing)` protects the no-Jinja2/no-StaticFiles/no-htmx boundary; Slice 0 extracts reusable escaping helpers and Slice 2 adds the portal twin assertion.
- `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::TENANT_TABLES (existing)`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::RAW_SQL_TABLES (existing)`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::EXPECTED_SCHEMA_TABLES (existing)`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::_ensure_table_constraints (existing)`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::_ensure_table (existing)`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::ensure_rls (existing)`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::heal (existing)`, and `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::downgrade (existing)` do not yet cover `portal_rotations` or `portal_auth_events`. The new raw-SQL tables must be reflected in the four schema-truth surfaces, with `audit_events.actor` kept at `varchar(100)` and `payload` kept as `jsonb`.
- `apps/prototype-description-service/recognition/tests/conftest.py::PostgreSQL reachability skip at L407 (existing)` currently allows database-backed tests to skip. The RED lane adds `apps/prototype-description-service/recognition/tests/conftest.py::require_postgres (new)` and four named portal test files; `apps/prototype-description-service/recognition/tests/infra/` does not yet exist and is created by that lane.
- `apps/prototype-description-service/Caddyfile::@admin matcher and respond 404 directives on public vhosts (existing)` already protect `/admin` paths. The `app.altcontext.com` vhost is new and must proxy portal traffic while preserving 404 for every `/admin*` path.
- `docs/workbay/contracts/security.md::API-key and X-Admin-Token sections (existing)` describe the current auth contract only. Slice 2 adds a portal section without modifying the API-key section.

## Target Outcome

An eligible Clerk contact reaches a minimal HTML key panel at `GET /portal/` through the Clerk-hosted sign-in flow. The server verifies `__session` first or `Authorization: Bearer <jwt>` second, rejects requests carrying both, normalizes the verified email, resolves one provisioned tenant, and exposes only that tenant's key metadata. The portal has no Clerk JS and never trusts a tenant id from a header, query, or body [SEC-01][WEB-16].

The API surface is:

- `GET /portal/`: authenticated HTML panel; unauthenticated browser requests return 302 to Clerk sign-in with `redirect_url=/portal/`.
- `GET /portal/me`: `{tenant_id, email, key_count}` for an eligible user.
- `GET /portal/keys`: only `id`, `created_at`, `last_used_at`, `expires_at`, and `revoked_at` for the resolved tenant.
- `POST /portal/keys/{id}/rotate`: requires `Idempotency-Key`; 404 for a foreign key, 409 for an already-revoked key, and 422 for a fingerprint conflict. The first success returns one raw key; an equal-fingerprint replay returns metadata with `raw_key: null, replayed: true` [API-02][WEB-08].
- `POST /portal/keys/{id}/revoke`: checks ownership before the irreversible write, returns 404 for a foreign key and 409 when already revoked, and writes a same-transaction audit event.

Invalid or missing verification returns API JSON 401 `invalid_session`; missing, unverified, or unmatched verified email returns 403 `claim_missing`, `email_unverified`, or `tenant_not_eligible` and commits exactly one corresponding `portal_auth_events` row from a separate short-lived session. A JWKS outage returns 503, logs only structured failure information, and leaves the valid-key `/analyze` path independent [DATA-13][CARD-07][RES-13]. Cookie mutations additionally require HMAC CSRF and same-origin evidence; bearer mutations do not.

## Context Loading

- Rules and structure: `docs/workbay/templates/TASK_PLAN.template.md`
- Scope: `docs/scopes/e16-7-tenant-selfserve-key-panel-scope.md`
- Eval mapping: `docs/scopes/e16-7-tenant-selfserve-key-panel-evals.json`
- House style: `docs/tasks/16.0/E16-1-bounded-iteration-caps-task-plan.md::metadata and Draft status note (existing)`
- Contracts: `docs/workbay/contracts/security.md::API-key auth section (existing)`
- Handoff/MCP state: task ref `E16-7`; open E16-7 findings in handoff (query `review_findings list status=open task_ref=E16-7`) are inputs to the RED lane; resolve by id.
- Refactor anchors: `apps/prototype-description-service/recognition/application/services/api_key_admin_service.py::mint_api_key (existing)`, `apps/prototype-description-service/recognition/interface_adapters/http/routers/admin.py::revoke_key_atomic (existing)`, `apps/prototype-description-service/recognition/interface_adapters/http/routers/admin.py::UnknownKeyError (existing)`, `apps/prototype-description-service/recognition/interface_adapters/http/routers/admin.py::RevokeOutcome (existing)`, `apps/prototype-description-service/recognition/interface_adapters/http/admin_console.py::render_console (existing)`, and `apps/prototype-description-service/recognition/infrastructure/repositories/tenant_repository.py::SqlAlchemyTenantRepository (existing)`.
- Session and schema anchors: `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py::_apply_postgres_session_safety_settings (existing)`, `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py::get_session (existing)`, `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py::get_optional_session (existing)`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::TENANT_TABLES (existing)`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::RAW_SQL_TABLES (existing)`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::EXPECTED_SCHEMA_TABLES (existing)`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::_ensure_table (existing)`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::_ensure_table_constraints (existing)`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::ensure_rls (existing)`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::heal (existing)`, and `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::downgrade (existing)`.
- Verification surfaces: `apps/prototype-description-service/recognition/tests/api/test_admin_router.py::module-level regression suite (existing)`, `apps/prototype-description-service/recognition/tests/api/test_admin_auth.py::module-level regression suite (existing)`, `apps/prototype-description-service/recognition/tests/api/test_key_rotation.py::module-level regression suite (existing)`, `apps/prototype-description-service/recognition/tests/api/test_auth_audit.py::module-level regression suite (existing)`, `apps/prototype-description-service/recognition/tests/schema/test_schema_truth_consistency.py::module-level schema-truth checks (existing)`, `apps/prototype-description-service/recognition/tests/schema/test_identity_schema_heal_pg.py::module-level PostgreSQL heal checks (existing)`, `apps/prototype-description-service/recognition/tests/test_identity_schema_migration.py::module-level migration checks (existing)`, and `scripts/verify_identity_schema.py::identity-schema verifier (existing)`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Clerk-hosted sign-in and `/portal/*` FastAPI requests | Clerk + recognition service | `docs/workbay/contracts/security.md::API-key auth section (existing)`; no portal transport | Add `__session` cookie-first or bearer-second JWT verification, portal errors, and CSRF/idempotency headers in `docs/workbay/contracts/security.md::portal section (new)` | No for the greenfield portal; preserve `/admin` and API-key sections | `apps/prototype-description-service/recognition/tests/api/test_portal_auth.py::test_browser_cookie_and_bearer_auth_transport (new)` and `apps/prototype-description-service/recognition/tests/api/test_portal_keys.py::test_rotate_idempotency_key_mints_once (new)` |
| Verified identity to tenant/key repository | recognition service | Existing sessions use `X-Tenant-ID` through `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py::get_session (existing)` and `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py::get_optional_session (existing)` | Resolve normalized verified email, ignore request tenant ids, and constrain key/rotation queries to the resolved tenant | No; the portal must not reuse the existing tenant-input dependency | `apps/prototype-description-service/recognition/tests/api/test_portal_auth.py::test_portal_ignores_request_tenant_header (new)` and `apps/prototype-description-service/recognition/tests/api/test_portal_keys.py::test_cross_tenant_key_is_not_visible (new)` |
| `app.altcontext.com` to service | Caddy + recognition service | `apps/prototype-description-service/Caddyfile::@admin matcher (existing)` returns 404 on public vhosts | Add a portal proxy vhost while returning 404 for every `/admin*` path on that host and existing hosts | Yes, preserve the existing 404 boundary | `apps/prototype-description-service/recognition/tests/infra/test_caddyfile_admin_404.py::test_app_vhost_admin_paths_return_404 (new)` |
| Recognition identity schema and RLS | migration + schema verification surfaces | `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::TENANT_TABLES (existing)`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::RAW_SQL_TABLES (existing)`, and `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::EXPECTED_SCHEMA_TABLES (existing)` omit both portal tables | Add raw-SQL `portal_rotations` and pre-tenant `portal_auth_events`, constraints, RLS policy/heal/downgrade behavior, and truth-surface coverage | No; existing `api_keys`, `tenants`, and API-key auth remain unchanged | `apps/prototype-description-service/recognition/tests/schema/test_schema_truth_consistency.py::module-level schema-truth checks (existing)` plus Slice 0 admin regression tests |
| Operator provisioning and Clerk deployment setup | service Make target + operator documentation | `make provision-customer EMAIL=<e> ENV=prod [PLAN=pro] [LABEL="Name"]`; no portal runbook | Document production provisioning, allowed origin `https://app.altcontext.com`, hosted sign-in redirect `/portal/`, and DNS A-record action | Additive documentation only | Slice 3 runbook proof and eligible-user SC-12 path |

## Proposed Solution

Implement a separate `/portal` router and dependency stack around a server-side Clerk JWT verifier. The verifier reads only the cookie-first/bearer-second transport, validates RS256, issuer, authorized parties, `exp`, `nbf`, and cached JWKS, then `apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_session.py::get_portal_session (new)` normalizes verified email and resolves the tenant through `apps/prototype-description-service/recognition/infrastructure/repositories/tenant_repository.py::SqlAlchemyTenantRepository.find_by_primary_contact_email (new)`. `apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_session.py::get_portal_auth_event_session (new)` writes only the three trusted-claim rejection outcomes without tenant context.

Keep key access narrow: portal reads call `apps/prototype-description-service/recognition/infrastructure/repositories/api_key_repository.py::SqlAlchemyApiKeyRepository.list_for_tenant (existing)` with the resolved tenant id, while `apps/prototype-description-service/recognition/infrastructure/repositories/portal_rotation_repository.py::TenantScopedRotationRepository (new)` exposes rotation-row operations with the tenant predicate internal to the repository. Add raw-SQL `portal_rotations` and `portal_auth_events` in `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::portal table definitions (new)`; give only `portal_rotations` FORCE RLS and tenant policy coverage. Move transactional admin revoke/audit behavior into `apps/prototype-description-service/recognition/application/services/api_key_admin_service.py::rotate_api_key (new)` and `apps/prototype-description-service/recognition/application/services/api_key_admin_service.py::revoke_api_key (new)` and reuse it for portal mutations. Extract the escaped f-string helpers from `apps/prototype-description-service/recognition/interface_adapters/http/admin_console.py::render_console (existing)` into `apps/prototype-description-service/recognition/interface_adapters/http/html_render.py::shared HTML-escaping helpers (new)` so `apps/prototype-description-service/recognition/interface_adapters/http/portal_console.py::render_portal (new)` remains dependency-light.

Rotation inserts the reservation before mint/revoke, updates its `new_key_id` before commit, preserves the old key's `rate_limit_tier` and `expires_at` policy, and writes audit evidence in the same transaction. A unique violation rolls back and is the only conflict caught; the retry opens a new transaction, reapplies tenant context, reads only committed winner data, compares the fingerprint, and returns either replay metadata or 422. A failed audit insert rolls back the mutation and reservation. Revoke performs the ownership check first, records `clerk:<sub>` (truncate-with-hash if needed for `varchar(100)`) plus `{clerk_sub, email, sid}` in existing JSONB payload, and never exposes a foreign key's existence [API-02][DATA-13][WEB-08][SECD-04].

The rotation table is raw SQL with `id uuid` primary key, non-null tenant/old-key foreign keys, `idempotency_key`, `request_fingerprint` (SHA-256 of method + path + key id), nullable `new_key_id`, `created_at`, and `UNIQUE (tenant_id, idempotency_key)`. The auth-event table is raw SQL with `id uuid` primary key, non-null `clerk_sub`, nullable SHA-256 `email_hash`, constrained outcomes `tenant_not_eligible`, `email_unverified`, and `claim_missing`, and `created_at`; enforce `(outcome = 'claim_missing') = (email_hash IS NULL)`, retain rows, and never store the raw email [DATA-13].

## Files and Surfaces to Change

| Surface | File and symbol | Change |
| --- | --- | --- |
| service | `apps/prototype-description-service/recognition/application/services/api_key_admin_service.py::rotate_api_key (new)`; `apps/prototype-description-service/recognition/application/services/api_key_admin_service.py::revoke_api_key (new)`; shared outcomes `apps/prototype-description-service/recognition/application/services/api_key_admin_service.py::UnknownKeyError (new)` and `apps/prototype-description-service/recognition/application/services/api_key_admin_service.py::RevokeOutcome (new)` | Own transactional rotate/revoke, audit insertion, ownership/unknown/already-revoked outcomes; keep `apps/prototype-description-service/recognition/application/services/api_key_admin_service.py::mint_api_key (existing)` focused on mint/hash/persist. |
| admin router | `apps/prototype-description-service/recognition/interface_adapters/http/routers/admin.py::revoke_key_atomic (existing)`; `apps/prototype-description-service/recognition/interface_adapters/http/routers/admin.py::UnknownKeyError (existing)`; `apps/prototype-description-service/recognition/interface_adapters/http/routers/admin.py::RevokeOutcome (existing)` | Move implementation ownership to the service and preserve `/admin` response mapping, including 200 `already_revoked`. |
| HTML rendering | `apps/prototype-description-service/recognition/interface_adapters/http/html_render.py::shared HTML-escaping helpers (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/admin_console.py::render_console (existing)` | Extract and reuse escaped f-string rendering without Jinja2, StaticFiles, htmx, or npm. |
| tenant repository | `apps/prototype-description-service/recognition/infrastructure/repositories/tenant_repository.py::SqlAlchemyTenantRepository.find_by_primary_contact_email (new)` | Add normalized primary-contact lookup using the existing unique column. |
| API-key repository use | `apps/prototype-description-service/recognition/infrastructure/repositories/api_key_repository.py::SqlAlchemyApiKeyRepository.list_for_tenant (existing)` | Use the Clerk-resolved tenant id for portal key metadata; do not add a `TenantScopedApiKeyRepository`. |
| rotation repository | `apps/prototype-description-service/recognition/infrastructure/repositories/portal_rotation_repository.py::TenantScopedRotationRepository (new)` | Add tenant-internal reads, reservation insert, fingerprint comparison, and committed replay lookup. |
| identity schema | `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::TENANT_TABLES (existing)`; `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::RAW_SQL_TABLES (existing)`; `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::EXPECTED_SCHEMA_TABLES (existing)`; `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::_ensure_table (existing)`; `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::_ensure_table_constraints (existing)`; `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::ensure_rls (existing)`; `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::heal (existing)`; `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::downgrade (existing)`; `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::portal_rotations SQL table (new)`; `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::portal_auth_events SQL table (new)` | Register and create both raw-SQL tables; add unique/FK/CHECK constraints, rotation RLS policy, downgrade, heal, and truth-registry parity. `portal_auth_events` stays RLS-exempt and outside `TENANT_TABLES`. |
| schema truth | `apps/prototype-description-service/recognition/tests/schema/test_schema_truth_consistency.py::module-level schema-truth checks (existing)`; `apps/prototype-description-service/recognition/tests/schema/test_identity_schema_heal_pg.py::module-level heal checks (existing)`; `apps/prototype-description-service/recognition/tests/test_identity_schema_migration.py::module-level migration checks (existing)`; `apps/prototype-description-service/scripts/verify_identity_schema.py::identity-schema verifier (existing)` | Extend all four surfaces for both tables and their intended RLS classification. |
| RED tests | `apps/prototype-description-service/recognition/tests/api/test_portal_auth.py::test_clerk_jwks_outage_is_503_without_affecting_analyze (new)`; `apps/prototype-description-service/recognition/tests/api/test_portal_keys.py::test_cross_tenant_key_is_not_visible (new)`; `apps/prototype-description-service/recognition/tests/api/test_portal_ui.py::test_portal_page_renders_without_jinja2 (new)`; `apps/prototype-description-service/recognition/tests/infra/test_caddyfile_admin_404.py::test_app_vhost_admin_paths_return_404 (new)`; `apps/prototype-description-service/recognition/tests/conftest.py::require_postgres (new)` | Add only the four eval files and fail-fast PostgreSQL fixture; map SC-1 through SC-20 one-to-one to named tests in the eval JSON. |
| portal auth | `apps/prototype-description-service/recognition/interface_adapters/http/deps/clerk_jwt.py::verify_clerk_session_jwt (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/deps/clerk_jwt.py::load_clerk_settings (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_session.py::get_portal_session (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_session.py::get_portal_auth_event_session (new)` | Add server-side Clerk verification, cookie/bearer transport, normalized tenant resolution, CSRF support, and committed pre-tenant event writes. |
| portal HTTP/UI | `apps/prototype-description-service/recognition/interface_adapters/http/routers/portal.py::get_portal (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/routers/portal.py::get_portal_me (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/routers/portal.py::list_portal_keys (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/routers/portal.py::rotate_portal_key (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/routers/portal.py::revoke_portal_key (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/portal_console.py::render_portal (new)` | Add the five portal endpoints and server-rendered key panel with no Clerk JS. |
| proxy/contract | `apps/prototype-description-service/Caddyfile::app.altcontext.com vhost (new)`; `docs/workbay/contracts/security.md::portal auth and key-panel section (new)` | Proxy the new portal host, retain `/admin*` 404, and document portal transports, schemas, CSRF, replay envelope, errors, and headers without changing the API-key section. |
| operator docs | `operator runbook::production provisioning and Clerk dashboard setup (new)` | Document the required `make provision-customer ... ENV=prod` command, Clerk allowed origin/redirect, and DNS action. The ops lane selects the repository's canonical runbook path. |

## Related Files

| File and symbol | Note |
| --- | --- |
| `docs/scopes/e16-7-tenant-selfserve-key-panel-scope.md::rev3 MVP scope and dispatch decomposition (existing)` | Behavioral source of truth; this plan corrects its nonexistent repository names as stated above. |
| `docs/scopes/e16-7-tenant-selfserve-key-panel-evals.json::SC-1 through SC-20 cases (existing)` | Adjacent eval gate; each case maps to one named RED test and the command fails on skips. |
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py::_apply_postgres_session_safety_settings (existing)` | Existing `SET LOCAL` safety behavior to preserve and reapply after a rotation-conflict rollback through the portal session context. |
| `apps/prototype-description-service/recognition/tests/api/test_admin_mount.py::module-ban assertion at L183-L188 (existing)` | Existing no-template/no-static-assets boundary; portal gets a twin assertion. |
| `apps/prototype-description-service/recognition/tests/conftest.py::PostgreSQL reachability skip at L407 (existing)` | Existing skip behavior that the RED fixture must override only for portal DB tests under the required-PG flag. |
| `apps/prototype-description-service/Caddyfile::@admin matcher (existing)` | Existing public-vhost 404 boundary that must remain intact. |
| `docs/workbay/contracts/security.md::API-key auth section (existing)` | Must remain unchanged; only the portal section is additive. |

## Verification Strategy

> Define the evidence bundle before implementation. The portal eval command is the authoritative acceptance gate and must produce zero skips.

- Deterministic tests:
  - `make -C apps/prototype-description-service test`
  - `cd apps/prototype-description-service && ACX_PORTAL_TESTS_REQUIRE_PG=1 python3 -m pytest recognition/tests/api/test_portal_auth.py recognition/tests/api/test_portal_keys.py recognition/tests/api/test_portal_ui.py recognition/tests/infra/test_caddyfile_admin_404.py -q -rs --junitxml=.task-state/evals/e16-7-portal.xml`
  - `python3 -m pytest scripts/test_check_lane_manifest_overlaps.py -q`
- Runtime-parity / environment checks:
  - `make postgres-start`
  - `make provision-customer EMAIL=<e> ENV=prod [PLAN=pro] [LABEL="Name"]`
  - Verify configured Clerk JWKS outage returns portal 503 while `/analyze` with a valid API key remains available.
- Contract/fixture verification:
  - Confirm SC-1 through SC-20 each map one-to-one to the named test in `docs/scopes/e16-7-tenant-selfserve-key-panel-evals.json`.
  - Confirm `ACX_PORTAL_TESTS_REQUIRE_PG=1` produces a failure rather than a skip when PostgreSQL is unreachable.
  - Confirm `apps/prototype-description-service/recognition/tests/api/test_admin_mount.py::module-ban assertion at L183-L188 (existing)` and `apps/prototype-description-service/recognition/tests/infra/test_caddyfile_admin_404.py::test_app_vhost_admin_paths_return_404 (new)` both preserve the no-template and `/admin*` boundaries.
- Manual verification:
  - Configure Clerk's allowed origin as `https://app.altcontext.com`, hosted sign-in redirect to `/portal/`, and the operator-created DNS A record; sign in through Clerk's hosted page and verify the panel contains no Clerk JS.
  - Rotate once, paste the raw key into wp-admin Settings, and run Test Connection; verify a replay does not show the raw value again.

## Slice Delivery

### Slice 0: Refactor with no behavior change

**Goal**: Move shared admin mutation/rendering/schema primitives into reusable surfaces while keeping existing admin responses and recognition behavior green.

Changes:

- Move `apps/prototype-description-service/recognition/interface_adapters/http/routers/admin.py::revoke_key_atomic (existing)`, `apps/prototype-description-service/recognition/interface_adapters/http/routers/admin.py::UnknownKeyError (existing)`, `apps/prototype-description-service/recognition/interface_adapters/http/routers/admin.py::RevokeOutcome (existing)`, and its audit insert into `apps/prototype-description-service/recognition/application/services/api_key_admin_service.py::rotate_api_key(session, *, key_id, tenant_id, actor) (new)` and `apps/prototype-description-service/recognition/application/services/api_key_admin_service.py::revoke_api_key(session, *, key_id, tenant_id, actor) (new)`; share domain outcomes while `/admin` continues mapping `already_revoked` to HTTP 200.
- Extract escaped f-string helpers from `apps/prototype-description-service/recognition/interface_adapters/http/admin_console.py::render_console (existing)` into `apps/prototype-description-service/recognition/interface_adapters/http/html_render.py::shared HTML-escaping helpers (new)`.
- Add `apps/prototype-description-service/recognition/infrastructure/repositories/tenant_repository.py::SqlAlchemyTenantRepository.find_by_primary_contact_email (new)` using the normalized unique primary-contact email lookup.
- Add raw-SQL `portal_rotations` and `portal_auth_events` to the appropriate `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::TENANT_TABLES (existing)`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::RAW_SQL_TABLES (existing)`, and `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::EXPECTED_SCHEMA_TABLES (existing)` registries; create constraints and RLS through `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::_ensure_table (existing)`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::_ensure_table_constraints (existing)`, and `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::ensure_rls (existing)`, and cover `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::downgrade (existing)`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::heal (existing)`, and all four schema-truth surfaces. `portal_rotations` is tenant-scoped; `portal_auth_events` is RLS-exempt.
- Define `portal_rotations` with UUID id, non-null tenant and old-key foreign keys, idempotency key, SHA-256 request fingerprint, nullable new-key foreign key, creation time, and unique `(tenant_id, idempotency_key)`; define `portal_auth_events` with UUID id, non-null Clerk subject, nullable SHA-256 email hash, constrained outcome, and creation time. Enforce that `email_hash` is NULL exactly for `claim_missing`, and keep auth-event rows indefinitely because volume is negligible [DATA-13].

Proof:

- Existing `apps/prototype-description-service/recognition/tests/api/test_admin_router.py::module-level regression suite (existing)`, `apps/prototype-description-service/recognition/tests/api/test_admin_auth.py::module-level regression suite (existing)`, `apps/prototype-description-service/recognition/tests/api/test_key_rotation.py::module-level regression suite (existing)`, and `apps/prototype-description-service/recognition/tests/api/test_auth_audit.py::module-level regression suite (existing)` remain green.
- `apps/prototype-description-service/recognition/tests/schema/test_schema_truth_consistency.py::module-level schema-truth checks (existing)`, `apps/prototype-description-service/recognition/tests/schema/test_identity_schema_heal_pg.py::module-level heal checks (existing)`, `apps/prototype-description-service/recognition/tests/test_identity_schema_migration.py::module-level migration checks (existing)`, and `scripts/verify_identity_schema.py::identity-schema verifier (existing)` accept both tables and their RLS classification.
- `make -C apps/prototype-description-service test` passes with no portal behavior introduced in this slice.

### Slice 1: RED portal contract

**Goal**: Add executable failing tests for all portal behavior and a fail-fast PostgreSQL fixture before implementation begins.

Changes:

- Add only `apps/prototype-description-service/recognition/tests/api/test_portal_auth.py::test_clerk_jwks_outage_is_503_without_affecting_analyze (new)`, `apps/prototype-description-service/recognition/tests/api/test_portal_keys.py::test_cross_tenant_key_is_not_visible (new)`, `apps/prototype-description-service/recognition/tests/api/test_portal_ui.py::test_portal_page_renders_without_jinja2 (new)`, and `apps/prototype-description-service/recognition/tests/infra/test_caddyfile_admin_404.py::test_app_vhost_admin_paths_return_404 (new)`; add the remaining named test symbols from the adjacent eval JSON in those files.
- Add `apps/prototype-description-service/recognition/tests/conftest.py::require_postgres (new)`, applied to every DB-backed portal test; with `ACX_PORTAL_TESTS_REQUIRE_PG=1` and unreachable PostgreSQL, it must fail rather than skip.
- Keep the tests red against the pre-implementation state, while mapping every SC-1 through SC-20 case one-to-one to its eval test path.

Proof:

- All four files collect successfully.
- The eval command runs with `ACX_PORTAL_TESTS_REQUIRE_PG=1`; portal tests fail for missing implementation, and PostgreSQL-unreachable mode fails rather than skips.
- The mapping table in `docs/scopes/e16-7-tenant-selfserve-key-panel-evals.json::SC-1 through SC-20 cases (existing)` remains the single named-test mapping.

### Slice 2: Tenant portal implementation

**Goal**: Make the RED contract pass with a separate Clerk-authenticated, tenant-isolated portal and preserved admin boundary.

Changes:

- Add `apps/prototype-description-service/recognition/interface_adapters/http/deps/clerk_jwt.py::verify_clerk_session_jwt (new)` and `apps/prototype-description-service/recognition/interface_adapters/http/deps/clerk_jwt.py::load_clerk_settings (new)` for server-side RS256 verification, issuer/authorized-party checks, expiration/not-before checks, cached JWKS refresh on unknown `kid`, bounded outage handling, and required-at-boot environment validation.
- Add `apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_session.py::get_portal_session (new)` and `apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_session.py::get_portal_auth_event_session (new)`; read `__session` before bearer, reject both credentials, derive tenant only from verified normalized email, ignore `X-Tenant-ID`, commit trusted 403 events through the short-lived no-tenant session (but still return 403 and log at ERROR if that write fails), and apply the HMAC-of-`sid` CSRF/same-origin checks for cookie mutations.
- Add `apps/prototype-description-service/recognition/interface_adapters/http/routers/portal.py::get_portal (new)`, `apps/prototype-description-service/recognition/interface_adapters/http/routers/portal.py::get_portal_me (new)`, `apps/prototype-description-service/recognition/interface_adapters/http/routers/portal.py::list_portal_keys (new)`, `apps/prototype-description-service/recognition/interface_adapters/http/routers/portal.py::rotate_portal_key (new)`, and `apps/prototype-description-service/recognition/interface_adapters/http/routers/portal.py::revoke_portal_key (new)` with the documented 302/401/403/404/409/422/503 semantics.
- Add `apps/prototype-description-service/recognition/infrastructure/repositories/portal_rotation_repository.py::TenantScopedRotationRepository (new)` and use `apps/prototype-description-service/recognition/infrastructure/repositories/api_key_repository.py::SqlAlchemyApiKeyRepository.list_for_tenant (existing)` for keys; methods on the new wrapper take no tenant argument, reservation INSERT is first, the winner row is reread only after a unique-violation rollback in a new transaction with tenant context reapplied, and only the unique-violation class is caught.
- Add `apps/prototype-description-service/recognition/interface_adapters/http/portal_console.py::render_portal (new)` on the extracted helpers; render only key metadata and never the raw key except in the first successful rotate response.
- Add the `app.altcontext.com` proxy in `apps/prototype-description-service/Caddyfile::app.altcontext.com vhost (new)`, preserving `apps/prototype-description-service/Caddyfile::@admin matcher (existing)` 404 behavior, and add the portal section to `docs/workbay/contracts/security.md::portal auth and key-panel section (new)` without changing `docs/workbay/contracts/security.md::API-key auth section (existing)`.

Proof:

- The exact eval command from `docs/scopes/e16-7-tenant-selfserve-key-panel-evals.json::command (existing)` passes with zero failures and zero skips.
- SC-1 through SC-20 each pass their named test; concurrent same-key rotation produces one mint and a replay under re-applied tenant context, and failed audit insertion rolls back the mutation and reservation.
- Existing admin regression tests and `apps/prototype-description-service/recognition/tests/infra/test_caddyfile_admin_404.py::test_app_vhost_admin_paths_return_404 (new)` remain green.

### Slice 3: Provisioning and operator documentation

**Goal**: Make the eligible-user path operationally reproducible without adding signup or tenant-management behavior to the portal.

Changes:

- Add the production operator command `make provision-customer EMAIL=<e> ENV=prod [PLAN=pro] [LABEL="Name"]` to `operator runbook::production provisioning procedure (new)`.
- Document Clerk dashboard setup in `operator runbook::Clerk dashboard configuration (new)`: allowed origin `https://app.altcontext.com`, hosted sign-in redirect to `/portal/`, required environment variables, JWKS outage expectation, and operator-created DNS A record.
- Document the post-rotation handoff: paste the one-time raw key into wp-admin Settings and confirm Test Connection; do not add plugin auto-adopt or grace-window behavior [CARD-10].

Proof:

- The canonical operator runbook contains the production provisioning and Clerk setup steps.
- An operator-provisioned tenant exercises the eligible-user SC-12 path and observes `{tenant_id, email, key_count}` from `GET /portal/me`.

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `e16-7-refactor` | `apps/prototype-description-service/recognition/application/services/api_key_admin_service.py::rotate_api_key (new)`; `apps/prototype-description-service/recognition/application/services/api_key_admin_service.py::revoke_api_key (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/routers/admin.py::revoke_key_atomic (existing)`; `apps/prototype-description-service/recognition/interface_adapters/http/html_render.py::shared HTML-escaping helpers (new)`; `apps/prototype-description-service/recognition/infrastructure/repositories/tenant_repository.py::SqlAlchemyTenantRepository.find_by_primary_contact_email (new)`; `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::TENANT_TABLES (existing)`; `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::RAW_SQL_TABLES (existing)`; `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::EXPECTED_SCHEMA_TABLES (existing)`; `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::_ensure_table (existing)`; `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::_ensure_table_constraints (existing)`; `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::ensure_rls (existing)`; `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::heal (existing)`; `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py::downgrade (existing)`; the four schema-truth surfaces | None | Existing admin tests, schema-truth tests, and `make -C apps/prototype-description-service test` |
| `e16-7-red` | Only `apps/prototype-description-service/recognition/tests/api/test_portal_auth.py::test_clerk_jwks_outage_is_503_without_affecting_analyze (new)`, `apps/prototype-description-service/recognition/tests/api/test_portal_keys.py::test_cross_tenant_key_is_not_visible (new)`, `apps/prototype-description-service/recognition/tests/api/test_portal_ui.py::test_portal_page_renders_without_jinja2 (new)`, `apps/prototype-description-service/recognition/tests/infra/test_caddyfile_admin_404.py::test_app_vhost_admin_paths_return_404 (new)`, and `apps/prototype-description-service/recognition/tests/conftest.py::require_postgres (new)` | None | Eval files collect and remain intentionally red; required-PG mode fails rather than skips |
| `e16-7-impl` | `apps/prototype-description-service/recognition/interface_adapters/http/deps/clerk_jwt.py::verify_clerk_session_jwt (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_session.py::get_portal_session (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_session.py::get_portal_auth_event_session (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/routers/portal.py::get_portal (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/routers/portal.py::get_portal_me (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/routers/portal.py::list_portal_keys (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/routers/portal.py::rotate_portal_key (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/routers/portal.py::revoke_portal_key (new)`; `apps/prototype-description-service/recognition/infrastructure/repositories/portal_rotation_repository.py::TenantScopedRotationRepository (new)`; `apps/prototype-description-service/recognition/interface_adapters/http/portal_console.py::render_portal (new)`; `apps/prototype-description-service/Caddyfile::app.altcontext.com vhost (new)`; `docs/workbay/contracts/security.md::portal section (new)` | `e16-7-refactor`, `e16-7-red` | Exact eval command with zero skips; admin regressions; Caddy `/admin*` 404 |
| `e16-7-ops` | `operator runbook::production provisioning and Clerk dashboard setup (new)` | `e16-7-impl` | Runbook exists; provisioned eligible-user SC-12 path is exercised |

### Merge Order

`e16-7-refactor` → `e16-7-red` → `e16-7-impl` → `e16-7-ops`

### Manifest

```bash
make lane-manifest-init TASK=E16-7 LANE_IDS='e16-7-refactor e16-7-red e16-7-impl e16-7-ops' TASK_PLAN=docs/tasks/16.0/E16-7-tenant-selfserve-key-panel-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools with the declared lane ownership and verification boundaries.
- **Shell fallback**: Use repo lane helpers or manual worktrees while preserving the same ownership and evidence requirements.

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Open E16-7 findings in handoff (query `review_findings list status=open task_ref=E16-7`) are inputs to the RED lane; resolve by id. Do not paste finding bodies or mutable finding counts into this plan.

## Context and Ownership

- [ ] Load the rev3 scope, adjacent eval specification, security contract, and current handoff state before implementation.
- [ ] Keep each lane within its declared paths; the plan-draft lane changes only this task-plan file.
- [ ] Record boundary ownership and compatibility expectations before touching the portal contract, Caddy vhost, or migration registries.
- [ ] Keep `TenantScopedApiKeyRepository` out of implementation; use `SqlAlchemyApiKeyRepository.list_for_tenant (existing)` and the new rotation repository as specified.

### Checklist for Slice 0: Refactor with no behavior change

- [ ] Add service-owned `rotate_api_key (new)` and `revoke_api_key (new)` with shared outcomes and same-transaction audit behavior.
- [ ] Extract HTML escaping, add the normalized tenant-email repository lookup, and preserve admin response mappings.
- [ ] Register both raw-SQL tables with the correct RLS classification and extend create/constraint/heal/downgrade/schema-truth surfaces.
- [ ] Capture existing admin, schema-truth, and service test evidence.

### Checklist for Slice 1: RED portal contract

- [ ] Add only the four eval test files and `require_postgres (new)`; do not add implementation code.
- [ ] Apply the fixture to every DB-backed portal test and prove required-PG mode fails rather than skips.
- [ ] Confirm SC-1 through SC-20 each have the adjacent eval's named test path.

### Checklist for Slice 2: Tenant portal implementation

- [ ] Add server-side Clerk verification, required-at-boot settings, cookie-first/bearer-second auth, claim outcomes, and fresh-session event commits.
- [ ] Add portal sessions, router endpoints, CSRF, tenant-isolated key/rotation repositories, transactional idempotency, audit rollback, and one-time raw-key response.
- [ ] Add server-rendered portal HTML, the app vhost, and additive portal security contract while retaining no-Jinja2 and `/admin*` 404 boundaries.
- [ ] Run the exact eval command with zero failures and zero skips, plus admin and Caddy regression evidence.

### Checklist for Slice 3: Provisioning and operator documentation

- [ ] Document `make provision-customer ... ENV=prod`, Clerk origin/redirect/env setup, and DNS A-record ownership in the canonical operator runbook.
- [ ] Document paste-plus-Test-Connection after rotation and the absence of auto-adopt/grace-window behavior.
- [ ] Exercise the provisioned eligible-user `GET /portal/me` path and capture SC-12 evidence.

## Review Readiness

- [ ] No boundary-touching implementation is left without matching contract, Caddy, migration, test, or operator evidence.
- [ ] The plan explicitly corrects the nonexistent tenant lookup and `TenantScopedApiKeyRepository` names without introducing either as an implementation target.
- [ ] Runtime-parity checks cover Clerk-hosted sign-in, JWKS outage behavior, PostgreSQL-required mode, and the app-host `/admin*` 404 boundary.
- [ ] Handoff records the changed task-plan path, verification commands, and contract implications; live finding status remains in the handoff DB.
- [ ] Any later review cycle uses finding ids `E167PL-01..` and never reuses `E167SC-*` ids.

## Stretch Goals

- [ ] Revisit a dedicated DB role and RLS extension for `api_keys` only if future tenant scale or threat modeling makes the MVP's shared-role repository isolation insufficient [ARCH-13].

## Success Criteria

| Criterion | Observable outcome |
| --- | --- |
| **SC-1** | Cross-tenant portal key access returns 404 or 403 and never exposes the other tenant's key. |
| **SC-2** | An authenticated tenant sees exactly its own key metadata, and client tenant input cannot change the resolved tenant. |
| **SC-3** | Equal-key/fingerprint rotation mints once, preserves policy, and replays metadata; a different fingerprint returns 422. |
| **SC-4** | Rotation authorizes ownership, returns 404 for foreign keys, 409 for revoked keys, revokes immediately, and recognition rejects the old key as revoked. |
| **SC-5** | The raw key appears only in the first successful response, never in replay, logs, audit rows, or URLs. |
| **SC-6** | Every `/admin*` request on `app.altcontext.com` returns 404. |
| **SC-7** | A Clerk JWKS outage returns portal 503 while `/analyze` with a valid key still succeeds. |
| **SC-8** | Concurrent equal rotation requests produce one new key, one revoked old key, and a replay from a re-contextualized loser transaction [API-02][RES-13]. |
| **SC-9** | Tenant B cannot read or replay tenant A's `portal_rotations` row at repository or RLS level [ARCH-13][SECD-04]. |
| **SC-10** | A conflicting `X-Tenant-ID` is ignored and the request serves only the Clerk-resolved tenant [SECD-02][WEB-08]. |
| **SC-11** | Direct revoke returns 200 with `revoked_at` and an audit row, 404 for a foreign key, and 409 when already revoked. |
| **SC-12** | Eligible `GET /portal/me` returns `{tenant_id, email, key_count}`; unmatched email returns 403 `tenant_not_eligible` plus an auth-event row. |
| **SC-13** | Missing email returns 403 `claim_missing` with NULL `email_hash`; unverified email returns 403 `email_unverified` with a hashed email. |
| **SC-14** | `GET /portal/` returns 200 HTML listing tenant keys without `jinja2` in `sys.modules`. |
| **SC-15** | Audit insertion failure rolls back the rotate mutation and leaves no `portal_rotations` row. |
| **SC-16** | Browser `/portal/` redirects unauthenticated users, API `/portal/keys` returns 401 `invalid_session`, and valid cookie/bearer transports authenticate equivalently [SEC-01][WEB-16]. |
| **SC-17** | Cookie rotate/revoke without valid CSRF and same-origin evidence returns 403 `csrf_failed` with no key changes [WEB-08][SEC-01]. |
| **SC-18** | Bad signature, issuer, authorized party, algorithm, expiration, or not-before claims return 401 `invalid_session` and create no auth event [SEC-01]. |
| **SC-19** | Each trusted 403 outcome leaves exactly one committed `portal_auth_events` row visible from a fresh connection [DATA-13]. |
| **SC-20** | With `ACX_PORTAL_TESTS_REQUIRE_PG=1` and PostgreSQL stopped, portal DB tests fail rather than skip. |
