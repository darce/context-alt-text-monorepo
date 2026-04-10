# E16. SaaS Foundation (Epic)

> **Epic Short ID**: E16
> **Status**: planning -- no implementation started
> **Parent**: [roadmap-saas-operations.md](../../roadmaps/roadmap-saas-operations.md) Phase 1
> **Prerequisites**: E14 (self-hosting baseline deployed), E15-3 (plugin settings page — **not yet implemented**, must land before E16 success criteria can be verified)

Build the business infrastructure layer — a separate business database, vendor-managed auth, API key self-service, usage metering, and observability — so that WordPress site owners can sign up, get an API key, and start using Alt Context without manual operator provisioning.

---

## Problem Statement

The recognition service is deployed (E14) and the plugin can be configured (E15-3), but every new customer requires manual work: generate an API key in the database, email it, track usage informally. There is no self-serve sign-up, no billing, no usage visibility, and no operational observability.

The `altcontext-marketing-monorepo` has proven patterns for API key management, usage rollups, and GDPR compliance, but runs on Fly.io with 256MB RAM and crashes under load. The patterns are valuable; the infrastructure is not.

## Scope

**In scope (Phase 1 — this epic):**
- Business Postgres database on OCI (accounts, API keys, usage, CRM — separate from recognition DB)
- Business API service (FastAPI on OCI) for tenant/key/usage CRUD
- Auth vendor integration (WorkOS or Clerk) for user sign-up, login, webhooks
- Customer dashboard at `app.altcontext.com` (account, API keys, usage)
- Sentry integration (recognition backend + plugin frontend)
- PostHog integration (recognition API usage events)
- Recognition auth middleware updated to validate keys from business DB
- DNS: `app.altcontext.com`, `mail.altcontext.com` SPF/DKIM prep

**Out of scope (Phase 2+):**
- Payment processing (Polar -- Phase 2)
- Plan enforcement and usage limits (Phase 2)
- Transactional email (Resend -- Phase 3)
- Full marketing backend port from Fly.io (Phase 4)

## Constraints

- **Vendor-managed auth.** Use WorkOS or Clerk. Do not build auth in-house, regardless of existing marketing backend auth code. Auth is security-critical.
- **Separate databases.** Business data and recognition data live in separate Postgres instances on the same OCI VM. No cross-database joins. Coordination through shared tenant UUIDs.
- **Business DB is the authority for tenant lifecycle.** The business DB owns `tenants`, `api_keys`, and `usage_daily`. Recognition DB trusts the tenant_id set by auth middleware after key validation.
- **Port patterns, not code.** The marketing backend's Node.js API key service, rollup architecture, and GDPR consent patterns are design inputs. Reimplement in Python/FastAPI for deployment consistency.
- **New key management service, not existing repo expansion.** The recognition service's `SqlAlchemyApiKeyRepository` only supports `get_by_hash()` and `touch()` for read-path bookkeeping. API key lifecycle (create, list, rotate, revoke) is owned by a new `business/services/api_key_service.py` in the business API, writing to the business DB. The recognition repo stays read-only.
- **OCI consolidation.** Business API runs on the same OCI VM as the recognition service. No Fly.io dependency for business-critical paths.

## Data Architecture

### Two Postgres instances, shared tenant UUID

```
OCI VM
├── Business Postgres (acx_business) — NEW
│   ├── tenants
│   │   ├── id           UUID PRIMARY KEY (canonical tenant identifier)
│   │   ├── name         TEXT
│   │   ├── slug         TEXT UNIQUE
│   │   ├── plan         TEXT DEFAULT 'free' (free/pro/business)
│   │   ├── billing_id   TEXT (Polar customer ID, Phase 2)
│   │   ├── created_at   TIMESTAMPTZ
│   │   └── updated_at   TIMESTAMPTZ
│   │
│   ├── api_keys
│   │   ├── id           UUID PRIMARY KEY
│   │   ├── tenant_id    UUID FK → tenants
│   │   ├── key_hash     TEXT UNIQUE (SHA-256)
│   │   ├── key_prefix   TEXT (first 12 chars, for lookup)
│   │   ├── scope        TEXT (recognition/admin)
│   │   ├── label        TEXT
│   │   ├── expires_at   TIMESTAMPTZ
│   │   ├── revoked_at   TIMESTAMPTZ
│   │   ├── last_used_at TIMESTAMPTZ
│   │   └── created_at   TIMESTAMPTZ
│   │
│   ├── usage_daily
│   │   ├── tenant_id    UUID FK → tenants
│   │   ├── date         DATE
│   │   ├── api_calls    INTEGER
│   │   ├── images_processed INTEGER
│   │   └── PRIMARY KEY (tenant_id, date)
│   │
│   ├── leads (CRM — ported from marketing backend pattern)
│   │   ├── id           UUID PRIMARY KEY
│   │   ├── tenant_id    UUID FK → tenants (for multi-tenant CRM, or NULL for pre-signup leads)
│   │   ├── email        TEXT
│   │   ├── name         TEXT
│   │   ├── source       TEXT (signup/marketing/referral)
│   │   ├── consent_status TEXT (pending/express/withdrawn)
│   │   └── created_at   TIMESTAMPTZ
│   │
│   └── billing_events (Polar webhook audit log — Phase 2)
│       ├── id           UUID PRIMARY KEY
│       ├── tenant_id    UUID FK → tenants
│       ├── event_type   TEXT
│       ├── payload      JSONB
│       └── received_at  TIMESTAMPTZ
│
└── Recognition Postgres (context_alt_text_service) — existing
    ├── tenant_id on all tables (same UUID as business.tenants.id)
    ├── RLS policies enforce tenant isolation
    └── No FK to business DB — trusts middleware-set session context
```

### API key validation flow

```
WordPress Plugin → api.altcontext.com (recognition)
  1. Auth middleware extracts X-API-Key header
  2. Middleware queries business DB: SELECT tenant_id FROM api_keys WHERE key_hash = sha256(key) AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())
  3. Middleware caches result (TTL 60s) to avoid per-request cross-DB calls
  4. Sets tenant_id in PostgreSQL session for RLS: SET app.current_tenant_id = '<uuid>'
  5. Recognition query executes with RLS enforcement
```

### Tenant ownership and auth contract

**Auth provider → tenant mapping:**
- Each auth provider user (WorkOS/Clerk) maps to exactly one tenant in the business DB.
- The `tenants` table stores `auth_provider_user_id TEXT` (the external user ID from WorkOS/Clerk) alongside the tenant UUID.
- On `user.created` webhook from the auth provider, the business API creates a tenant row with a new UUID and links the auth provider user ID.
- Dashboard API calls include the auth provider session token. The business API validates the token against the auth provider, resolves the `auth_provider_user_id` → `tenant_id` mapping, and scopes all responses to that tenant.

**Dashboard authorization scopes:**
- Dashboard users can only manage their own tenant's API keys and view their own usage.
- The business API enforces tenant scoping: every endpoint resolves the caller's tenant from the session, and queries are filtered by `tenant_id`.
- There is no cross-tenant admin surface in Phase 1. Operator admin uses direct DB access or CLI scripts.

**Webhook provisioning vs. existing lazy bootstrap:**
- The recognition service currently auto-creates a tenant record on first authenticated API request (lazy bootstrap). E16 replaces this: tenant creation is now driven by the auth provider `user.created` webhook → business API → business DB.
- The recognition service's lazy tenant bootstrap is **deprecated** once E16 lands. The recognition DB's `tenant` table becomes a read-only projection: the auth middleware sets `tenant_id` from the business DB lookup, and the recognition DB trusts that context. Any missing tenant row in the recognition DB is auto-created on first query (thin shim), but lifecycle ownership (create, update plan, deactivate) is exclusively in the business DB.

**API key ownership:**
- All API keys are created and stored in the business DB. The recognition service never creates keys.
- The business API's key CRUD endpoints are scoped to the caller's tenant. A user can only create/list/rotate/revoke keys for their own tenant.
- The existing `RECOGNITION_ALLOWED_API_KEYS` env var (dev admin bypass) continues to work for operator access but is not exposed through the dashboard.

## Vendor Stack

| Function | Vendor | Integration Point |
|----------|--------|-------------------|
| **Auth** | WorkOS or Clerk | Customer dashboard login/signup. Webhook → business API creates tenant row. |
| **Billing** | Polar (Phase 2) | Checkout link in dashboard. Webhook → business API updates plan field. |
| **Error tracking** | Sentry | Python SDK in recognition + business API. JS SDK in WP plugin. |
| **Product analytics** | PostHog | Backend events (API calls, key lifecycle). Dashboard: DAU, API volume. |
| **Email** | Resend (Phase 3) | Welcome email, usage alerts, receipts. `mail.altcontext.com` domain. |

## OCI VM Service Layout (after E16)

```
docker compose services:

Environment stacks (existing, per-env):
  postgres        — recognition DB (pgvector)
  api             — recognition FastAPI
  worker          — scan worker

Business stack (NEW):
  business-db     — business Postgres (no pgvector needed)
  business-api    — business FastAPI (tenant/key/usage CRUD, webhooks)

Caddy (existing):
  caddy           — routes api.altcontext.com, staging.api.*, dev.api.*
                    NEW: routes app.altcontext.com → dashboard
                    NEW: routes biz.api.altcontext.com → business API (or path-based)
```

## Patterns Ported from Marketing Backend

| Pattern | Source (`altcontext-marketing-monorepo`) | Python Target |
|---------|----------------------------------------|---------------|
| API key generation + SHA-256 hashing | `backend/src/services/api-keys.ts` | `business/services/api_key_service.py` |
| Timing-safe key validation | `backend/src/services/api-keys.ts` | `business/middleware/auth.py` |
| Daily metric rollups | `backend/src/services/metrics.ts` | `business/services/usage_rollup.py` |
| GDPR consent tracking | `backend/src/services/consent.ts` | `business/models/consent.py` |
| Rate-limited login attempts | `backend/src/routes/auth.ts` | Handled by auth vendor (WorkOS/Clerk) |

## Phases

### E16-1: Business Database & API Service

- Set up `acx_business` Postgres on OCI (new container in business compose)
- Implement business FastAPI service with tenant and API key CRUD
- Port API key generation/hashing/validation patterns from marketing backend
- Endpoints: `POST /tenants`, `GET/POST/DELETE /tenants/{id}/api-keys`, `POST /tenants/{id}/api-keys/{id}/rotate`

### E16-2: Auth Vendor Integration

- Evaluate and select WorkOS vs. Clerk
- Implement signup/login flow in customer dashboard
- Webhook handler: auth `user.created` event → create tenant + first API key in business DB
- Dashboard pages: account settings, API key management

### E16-3: Recognition Auth Bridge

- Update recognition service auth middleware to validate keys against business DB
- Add TTL cache for key lookups (avoid per-request cross-DB calls)
- Ensure RLS tenant_id is set from business DB lookup, not from a separate recognition key store
- Backward compatibility: existing recognition API keys continue to work during migration

### E16-4: Usage Metering

- Add `usage_daily` table and middleware counter in recognition service
- Middleware increments counter on each authenticated request
- Daily rollup job aggregates into monthly summaries
- Business API endpoint: `GET /tenants/{id}/usage`
- Dashboard page: usage charts with plan comparison

### E16-5: Sentry + PostHog Integration

- Sentry: Python SDK in recognition + business API, JS SDK in WP plugin admin
- PostHog: track `recognition.analyze`, `key.created`, `key.rotated`, `tenant.created`
- Alert rules: 5xx spike, new error type, high error rate per tenant

### E16-6: Customer Dashboard & DNS

- Customer dashboard at `app.altcontext.com` (SvelteKit or Next.js)
- Auth via WorkOS/Clerk SDK (login, signup, session)
- Pages: dashboard overview, API keys, usage, settings
- DNS: `app.altcontext.com` A record, `mail.altcontext.com` SPF/DKIM prep
- Caddy routing for dashboard + business API

## Success Criteria

- [ ] User can sign up at `app.altcontext.com` via auth vendor (no manual provisioning)
- [ ] Sign-up webhook automatically creates tenant + first API key in business DB
- [ ] User can view, create, rotate, and revoke API keys from the dashboard
- [ ] API key from business DB works in WordPress plugin (verified via `wp-config.php` constant or E15-3 settings page once that task lands)
- [ ] Recognition service validates keys against business DB with RLS correctly scoped
- [ ] Dashboard shows recognition API usage per tenant
- [ ] Business data (accounts, keys, usage) is in separate Postgres from recognition data
- [ ] Sentry captures recognition backend + plugin frontend errors
- [ ] PostHog tracks API usage events per tenant
- [ ] Existing recognition endpoints function unchanged

## Deferred Decisions

- **Auth vendor final selection**: WorkOS vs. Clerk — evaluate during E16-2
- **Dashboard framework**: SvelteKit (team knows it from marketing monorepo) vs. Next.js
- **Dashboard hosting**: OCI VM (static files served by Caddy) vs. Vercel/Netlify (edge CDN)
- **Tenant UUID coordination**: business DB generates on signup, recognition service receives via auth middleware? Or dual-write on tenant creation?
- **Migration from marketing backend**: port marketing analytics/leads to business DB now or keep separate on Fly.io?
- **Second Postgres instance**: run as another container in each env's compose, or a single shared business DB across all three envs?
