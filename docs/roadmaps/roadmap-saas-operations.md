# SaaS Operations Roadmap -- Business Infrastructure for Alt Context

> **Status:** Planning -- no implementation started.
> **Predecessor:** [roadmap-v4.md](roadmap-v4.md) (product UX), [self-hosting-epic.md](../epics/v0.3.1/self-hosting-epic.md) (deployment baseline)
> **Scope:** Everything required to operate Alt Context as a paid SaaS product: user accounts, billing, API key distribution, usage metering, observability, email, feedback, and compliance.
> **Key input:** The `altcontext-marketing-monorepo` has proven patterns for API key management, analytics rollups, and GDPR compliance that can be ported to the OCI infrastructure. Auth is vendor-managed (not in-house).

---

## Objective

Transform Alt Context from a self-hosted developer tool into an operational SaaS product where WordPress site owners can sign up, get an API key, manage their usage, pay for the service, and receive support -- without any manual provisioning by the operator.

## Problem Statement

The recognition service (E14) is deployed on OCI with multi-tenant Postgres, API key auth, and rate limiting. The marketing platform (`altcontext-marketing-monorepo`) has proven patterns for API key lifecycle, analytics, and lead management but runs on Fly.io with limited capacity (256MB, frequent crashes under load). Neither system has billing, transactional email, or vendor-managed auth.

Every new customer requires manual provisioning: generate an API key, email it, track usage by hand. This doesn't scale past the first 5 users.

## Design Principles

1. **Vendor-managed auth.** Authentication is security-critical infrastructure. Use WorkOS or Clerk for user management, session handling, and future OAuth/SSO. Do not roll in-house auth regardless of existing code.
2. **Separate business and recognition data.** Two Postgres databases on the same OCI VM: one for business (accounts, API keys, billing, CRM, usage) and one for recognition (embeddings, clusters, scans). Shared tenant UUIDs provide the RLS bridge.
3. **Consolidate on OCI.** Port the viable services from the Fly.io marketing backend to the OCI VM. One infrastructure provider, one deployment target, more capacity (24GB RAM vs. 256MB).
4. **Reuse proven patterns, not code.** The marketing backend's API key management, rollup architecture, and GDPR compliance patterns are valuable design inputs. Port the patterns into the Python/FastAPI stack on OCI rather than running a separate Node.js service.
5. **Buy commodity infrastructure.** Auth (WorkOS/Clerk), billing (Polar), email (Resend), error tracking (Sentry), analytics (PostHog).
6. **Self-serve from day one.** Sign up → get key → install plugin → working.

## Data Architecture

### Two databases, one tenant UUID

```
OCI VM (129.213.40.111)
├── Business Postgres (acx_business)
│   ├── tenants          ← canonical tenant registry (UUID, plan, billing_id)
│   ├── api_keys         ← all API keys (recognition + future services)
│   ├── usage_daily      ← metered API calls per tenant per day
│   ├── leads            ← CRM / marketing leads
│   └── billing_events   ← Polar webhook audit log
│
├── Recognition Postgres (alt_context_service) — existing
│   ├── tenant_id column on all tables (FK concept, not enforced cross-DB)
│   ├── RLS policies check tenant_id from session context
│   └── Validates API keys by calling business DB or cached lookup
│
└── Shared contract: tenant UUID
    - Business DB is the authority for tenant lifecycle and API key validity
    - Recognition DB trusts tenant_id set in session context after auth middleware validates
    - API key validation flow: request → auth middleware checks key against business DB → sets tenant context → recognition queries scoped by RLS
```

### Why separate databases

- **Different lifecycles.** Business data (users, billing, CRM) changes when the product evolves. Recognition data (embeddings, clusters) changes when the ML pipeline evolves. Coupling them creates deployment friction.
- **Different backup/retention needs.** Business data has legal retention requirements (billing records). Recognition data is disposable under the greenfield policy.
- **Different access patterns.** Business queries are simple key lookups and aggregations. Recognition queries involve vector similarity search with pgvector.
- **Clean blast radius.** A recognition schema migration cannot break user login or billing.

## Vendor Stack

| Function | Vendor | Rationale |
|----------|--------|-----------|
| **Auth & user management** | WorkOS or Clerk | API-first, webhook events, OAuth/SSO ready, free tier. Security-critical — don't roll in-house. |
| **Billing** | Polar | Merchant of record. Handles VAT/tax/compliance. Developer-focused. Webhook events for subscription lifecycle. |
| **Error tracking** | Sentry | Python + JS SDKs. Free 5K errors/mo. |
| **Product analytics** | PostHog | Usage events, session replay, feature flags. Free 1M events/mo. |
| **Transactional email** | Resend | React Email or HTML templates. Branded `mail.altcontext.com`. |

## What to Build In-House

| Component | Stack | Rationale |
|-----------|-------|-----------|
| Business API service | Python/FastAPI on OCI | Tenant CRUD, API key lifecycle, usage metering, billing webhooks. Same stack as recognition for deployment simplicity. |
| Customer dashboard | SvelteKit or Next.js at `app.altcontext.com` | Account info, API keys, usage, billing portal link. Auth via WorkOS/Clerk SDK. Can deploy on OCI or Vercel. |
| API key lifecycle | Port pattern from marketing backend | Create, hash (SHA-256), scope, rotate, revoke, timing-safe validation. Proven pattern, rewrite in Python. |
| Usage metering | Port rollup pattern from marketing backend | Daily counters per tenant, aggregation jobs. Same architecture, Python implementation. |
| Auth middleware (recognition) | Extend existing FastAPI middleware | Validate keys against business DB (or cache), set tenant context for RLS. |

## What to Port from Marketing Backend

The `altcontext-marketing-monorepo` has production-proven patterns worth porting to the OCI/Python stack:

| Pattern | Source (Node.js/Prisma) | Target (Python/SQLAlchemy) |
|---------|------------------------|---------------------------|
| API key generation + hashing | `backend/src/services/api-keys.ts` | New `business/services/api_key_service.py` |
| Timing-safe key validation | `backend/src/services/api-keys.ts` | Extend recognition auth middleware |
| Daily metric rollups | `backend/src/services/metrics.ts` | New `business/services/usage_rollup.py` |
| GDPR consent tracking | `backend/src/services/consent.ts` | New `business/models/consent.py` |
| Tenant resolution middleware | `backend/src/lib/tenant-resolution.ts` | Extend existing FastAPI tenant middleware |

### What stays on Fly.io (for now)

- Marketing analytics dashboard (lead tracking, traffic sources, geo visualization)
- Marketing-specific event ingestion
- These can migrate to OCI later or remain as a separate marketing tool

## Phase 1 Free Tier Contract

Before billing exists (Phase 2), Phase 1 operates as an implicit free tier:

- All tenants are `plan = 'free'` in the business DB (the column exists; no enforcement logic yet)
- No image quota enforcement — all authenticated requests are served
- API key creation is unrestricted (no per-plan key limits)
- Usage metering records calls for visibility but does not enforce limits

Phase 2 adds Polar integration, plan enforcement, and the billing model below.

## Billing Model (Phase 2 — not enforced until Polar integration)

| Plan | Price | Includes |
|------|-------|----------|
| **Free** | $0/mo | 100 images/mo, 1 API key, community support |
| **Pro** | $19/mo | 5,000 images/mo, 3 API keys, email support |
| **Business** | $49/mo | 25,000 images/mo, 10 API keys, priority support |

Concrete quotas and enforcement logic are deferred to the Phase 2 billing epic. The table above is a planning target, not a Phase 1 deliverable.

## Architecture

```
User Browser
  │
  ├─ app.altcontext.com (Customer Dashboard)
  │    ├─ Auth: WorkOS/Clerk SDK (login, signup, session)
  │    ├─ API Keys: CRUD via business API
  │    ├─ Usage: charts via business API
  │    └─ Billing: Polar checkout/portal link
  │
  ├─ WordPress Admin (Plugin Settings, E15-3)
  │    └─ Enter API URL + key from dashboard
  │
  └─ OCI VM (129.213.40.111)
       ├─ api.altcontext.com → Recognition Service (existing FastAPI)
       │    ├─ Auth middleware validates key against business DB
       │    ├─ Tenant-scoped RLS (existing)
       │    └─ Errors → Sentry, events → PostHog
       │
       ├─ Business API Service (NEW FastAPI)
       │    ├─ /admin/tenants — tenant lifecycle
       │    ├─ /admin/api-keys — key CRUD
       │    ├─ /admin/usage — metered usage
       │    ├─ /webhooks/auth — WorkOS/Clerk account events
       │    ├─ /webhooks/billing — Polar subscription events
       │    └─ Postgres: acx_business
       │
       └─ Two Postgres instances
            ├─ acx_business (accounts, keys, usage, CRM)
            └─ alt_context_service (recognition data)
```

## Implementation Phases

### Phase 1: Foundation (Epic E16)

- Business Postgres setup on OCI VM
- Business API service (tenant CRUD, API key lifecycle, usage metering)
- Auth vendor integration (WorkOS or Clerk)
- Customer dashboard scaffold
- Sentry + PostHog integration
- Recognition auth middleware updated to validate against business DB

### Phase 2: Billing

- Polar integration (products, checkout, webhooks)
- Plan enforcement (key limits, rate tier based on plan)
- Usage dashboard with plan comparison
- Billing portal link in dashboard

### Phase 3: Email & Lifecycle

- Resend integration with `mail.altcontext.com`
- Welcome email with setup instructions
- Usage alerts, key rotation reminders
- Billing receipts (via Polar webhooks)

### Phase 4: Growth & Support

- In-plugin feedback form
- Public changelog
- PostHog onboarding funnels
- OAuth providers (Google, GitHub) via auth vendor

---

## Decisions to Make Before Implementation

1. **Auth vendor**: WorkOS vs. Clerk — evaluate free tiers, B2B features, webhook flexibility
2. **Dashboard hosting**: OCI VM (co-located) vs. Vercel/Netlify (edge, simpler deploys)
3. **Business API deployment**: Separate compose service on OCI or separate process in existing stack?
4. **Tenant UUID coordination**: business DB generates UUID, recognition service trusts it? Or recognition service creates tenant on first authenticated request?
5. **Pricing validation**: survey potential users before committing to plan structure
6. **Marketing backend migration**: port to OCI now (Phase 1) or keep on Fly.io until Phase 4?
