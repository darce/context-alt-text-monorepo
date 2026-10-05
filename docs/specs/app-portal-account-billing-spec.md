# APP-1 portal account and billing contract

> **Status:** proposed planning contract. Not implementation. Not a Polar production cutover.
> **Date:** 2026-09-22 UTC.
> **Task:** APP-1. Lane: `billing-contract`.
> **Owner of this file:** P / billing-contract. Downstream owners are named per surface below.
> **Supersedes:** the missing-spec placeholder in [Plan 0001](../plans/0001-app-altcontext-beta-clerk-polar-task-plan.md) and the contract gaps listed in [Plan 0002](../plans/0002-app-altcontext-launch-continuation-task-plan.md) node P/C/H/R.

This document freezes the portable hosted-checkout, tenant-identity, durable-attempt, webhook, and recovery contracts that C (schema/provider), H (portal HTTP), and R (reconciliation processing) must implement. Polar remains the provisional sandbox adapter behind the existing `BillingProvider` boundary. Paid live traffic stays behind the separate paid gate.

## Provenance

Inspected this lane checkout at `60fb6dd246238275b243342e0cbad6ffff0b84ce` (sandbox history-stripped). Dispatch brief named feature/app-1 base `581405f99`. Graph index may lag; facts below are from files in this checkout.

**Planning sources**

- [Plan 0002](../plans/0002-app-altcontext-launch-continuation-task-plan.md)
- [Checkout / portability assessment](../assessments/current/app-altcontext-checkout-provider-portability-and-link-2026-09-22.md)
- [Plan 0001 APP-R1..R6 and APP-SC-01..20](../plans/0001-app-altcontext-beta-clerk-polar-task-plan.md)

**Exact source in this checkout**

- `apps/prototype-description-service/recognition/domain/portal_contracts.py` — `BillingProvider`, identity/entitlement protocols
- `apps/prototype-description-service/recognition/infrastructure/billing/polar_provider.py` — `PolarBillingProvider`
- `apps/prototype-description-service/recognition/interface_adapters/http/routers/portal.py` — seven tenant-bound routes
- `apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_auth.py` — `require_portal_principal`
- `apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_composition.py` — sandbox flag with live default URL
- `apps/prototype-description-service/recognition/interface_adapters/http/routers/billing_webhooks.py` — `POST /billing/webhooks/polar`
- `apps/prototype-description-service/db/models/portal_billing.py` — projection + inbox, no checkout-attempt table
- `apps/prototype-description-service/scripts/billing_reconcile.py` — retrieve-known-state worker, no enumeration

**Vendor documentation (pin at use time; not proof of our implementation)**

- Polar API base URLs: production `https://api.polar.sh`, sandbox `https://sandbox-api.polar.sh` ([API overview](https://polar.sh/docs/api-reference))
- Polar checkout sessions and `external_customer_id` ([Checkout API](https://polar.sh/docs/features/checkout/session))
- Polar list endpoints: `page` (default 1) and `limit` (default 10, max 100) with `pagination.max_page` ([API overview](https://polar.sh/docs/api-reference))
- Polar webhook delivery: pass **headers + raw body** to `validate_event`; secrets generated on or after 2026-09-08 00:00 UTC are Standard Webhooks; older secrets are Polar HMAC over the UTF-8 bytes of the full `whsec_…` string ([Webhook delivery](https://polar.sh/docs/integrate/webhooks/delivery))
- Polar sandbox isolation ([Sandbox](https://polar.sh/docs/integrate/sandbox))
- Polar core subscription list: `GET /v1/subscriptions/` ([List subscriptions](https://polar.sh/docs/api-reference/2026-04/subscriptions/list-subscriptions))
- Standard Webhooks signed content `{webhook-id}.{webhook-timestamp}.{body}` ([spec](https://github.com/standard-webhooks/standard-webhooks/blob/main/spec/standard-webhooks.md))

**Canon** (https://github.com/darce/heuristics-canon): `REF-15`, `DOM-03`, `CARD-06`, `CARD-15`, `CARD-16`, `GRPH-09`, `GRPH-31`, `PERF-11`, `PERF-13`. Engineering rules, not vendor capability evidence.

Protocol pytest smoke is **not** spec-correctness proof. Fake-provider tests are the C/H/R admission bar; Polar sandbox evidence is a later V packet.

---

## 1. Terminology (`DOM-03`)

Do not say “provider” without a qualifier.

| Term | Meaning |
| --- | --- |
| Clerk subject | Verified interactive identity (`iss` + `sub`). Never a tenant id, API key, or billing customer. |
| Local tenant | Stable AltContext UUID. Owns keys, usage, entitlement. Survives vendor change (`CARD-16`). |
| API key | Local credential. Billing events must not rotate, revoke, or re-mint keys. |
| Internal plan code | AltContext catalog key (example: `starter_monthly`). Browser sends only this. |
| Hosted checkout | Vendor-hosted payment UI (Polar Checkout, Stripe Checkout, Paddle overlay). |
| Wallet / Link | Optional checkout acceleration. Not authentication and not merchant-of-record. |
| Processor | Card network acquirer behind the seller (Polar documents Stripe as processor). |
| Merchant of record / seller account | Legal seller. Namespaced as `seller_account`. Polar: organization id bound to the OAT. |
| Billing customer / subscription ids | Vendor ids. Stored only in mappings keyed by `(provider, environment, seller_account)`. |
| Entitlement | Local grant of work (`beta_active` / `paid_active` / closed). Return URLs never grant it. |

---

## 2. Inspected gaps (current code is not this contract)

These are observations from this checkout, not claims that main has shipped them.

1. **`BillingProvider`** (`portal_contracts.py:169-201`) today:
   - `create_checkout_session(tenant_id, plan_code, success_url, cancel_url) -> str`
   - `create_portal_session(tenant_id, return_url) -> str`
   - `retrieve_state(provider_customer_id, provider_subscription_id, request_timeout)`
   - `verify_webhook(raw_body, signature) -> bool`
   - `parse_event(raw_body)`
   Missing: durable-attempt handle, `retrieve_checkout`, **bounded enumeration**, webhook **header set**.
2. **`PolarBillingProvider.create_checkout_session`** computes a **fixed** idempotency key from `(environment, tenant_id, plan_code, success_url, cancel_url)` (`_checkout_idempotency_key`). There is no `checkout_attempt` row. A later purchase after Polar `checkout.expired` with the same URLs reuses the same vendor key. Checkout payload has `metadata.tenant_id` but **does not** set Polar `external_customer_id` (portal sessions do).
3. **`portal.py`** has exactly seven routes: `GET /portal/me`, `GET/POST /portal/keys`, `GET /portal/keys/{id}`, `POST .../rotate`, `POST .../revoke`, `GET /portal/usage`. **No** claim, checkout, or manage route.
4. **`require_portal_principal`** requires a resolved tenant. Claim cannot use it. Unverified email and missing identity both return generic `403 portal access denied`.
5. **`portal_composition.py`**: `billing_environment` defaults to `"sandbox"` while `_DEFAULT_POLAR_BASE_URL = "https://api.polar.sh"` (live). `PolarBillingProvider._DEFAULT_BASE_URL` is the same live host. Polar documents sandbox as `https://sandbox-api.polar.sh`.
6. **`verify_webhook`** HMACs **raw body only** and compares a single signature string. Polar documents Standard Webhooks over `{id}.{timestamp}.{body}` plus a legacy Polar HMAC. Router `billing_webhooks.py` collects `webhook-signature` / Polar aliases and a delivery timestamp, but the protocol still takes `signature: str` only. Inbox unique key is `(provider, provider_event_id)` — no environment or seller account.
7. **`retrieve_state`** requires a **known** customer or subscription id. `billing_reconcile.py` has no list/enumerate path, so a remote orphan subscription cannot be discovered (`GRPH-09` recovery path missing).
8. **Schema** (`portal_billing.py`): `billing_subscription_projection` unique on `(provider, provider_customer_id)`; no `environment`, no `seller_account`, no `checkout_attempt`, no reconciliation cursor/lease.

C must extend the protocol and schema. H must add the three HTTP routes on **`portal.py`** (same owner as `/me` and keys; do not split claim into a second router unless H later extracts it as a whole). R consumes C’s enumeration; R does not invent provider APIs.

---

## 3. Identity and tenancy

Three independent identifiers. Never substitute one for another.

```text
Clerk iss+sub  --claim-->  local tenant UUID  --map-->  billing customer id
                 |                              |
                 +--> local API keys            +--> vendor subscription id
                 +--> local entitlement/usage
```

### 3.1 Pre-tenant verified identity

A **verified portal identity** is a Clerk JWT that passed signature, issuer, audience, expiry, and `email_verified=true` with a non-empty email. It does **not** yet own a tenant.

New dependency (H, in `portal_auth.py`): `require_verified_portal_identity`.

| Condition | Status | `detail.code` |
| --- | --- | --- |
| Missing/malformed `Authorization: Bearer` | 401 | `invalid_portal_authorization` |
| Invalid/expired/wrong-iss JWT | 401 | `invalid_portal_authorization` |
| JWKS unavailable | 503 | `portal_authentication_unavailable` |
| Email missing or not verified | 403 | `email_unverified` |
| `X-Tenant-ID` present on **claim** | 403 | `tenant_header_forbidden` |

Browser `tenant_id` in JSON/query **never** selects the tenant. Prior art: E16-7 finding 14472 (endpoint-specific access, missing/unverified claims, unmatched tenants, audit-failure rollback).

### 3.2 Tenant-bound principal

Existing `require_portal_principal` remains for `/me`, keys, usage, checkout, manage. Optional `X-Tenant-ID` must match the bound tenant or 403 `portal access denied` (keep current fail-closed wording for tenant mismatch). Do not invent a tenant from Clerk email.

### 3.3 Local vs billing ids

| Id | Stored | Namespaced by |
| --- | --- | --- |
| `tenants.id` | local UUID | n/a |
| Clerk `(issuer, subject)` | `portal_identity` unique | issuer |
| Polar customer / subscription / checkout ids | mapping + projection | `(provider, environment, seller_account)` |
| Polar `external_customer_id` | sent to Polar | `"{environment}:{tenant_id}"` (keep current Polar adapter scoping so sandbox/live cannot alias) |

`seller_account` is required in **local** unique keys even when Polar OATs are org-scoped, so a second Polar organization or a later Paddle/Stripe seller cannot collide (`CARD-16`).

---

## 4. HTTP contracts (H owns `portal.py`)

All three new routes are `POST`. All mutating portal responses set `Cache-Control: no-store`. FastAPI `detail` may be a string (401/403 parity with `/me`) or an object with `code` for typed conflicts.

### 4.1 Auth, CSRF, return-origin (all mutating portal POSTs)

Portal auth is **Bearer JWT only**. Cookie-only sessions are rejected (401). Custom `Authorization` is not auto-attached by the browser, which removes classic CSRF; still apply origin checks because cookies must never become sufficient.

| Rule | Enforcement |
| --- | --- |
| `Authorization: Bearer <Clerk JWT>` | Required. 401 otherwise. |
| Cookie session without Bearer | 401. Do not add cookie auth in H. |
| `Origin` header | Required on claim/checkout/manage. Must match `APP_ALLOWED_ORIGINS`. 403 `csrf_origin_denied` if missing or mismatch. `Referer` is not a substitute. |
| `X-Tenant-ID` | Forbidden on claim. On checkout/manage, optional and must match principal. |
| Return URLs | **Server-selected.** Client may send `return_path` only: must match `^/[A-Za-z0-9/_-]*$` (no `//`, no scheme, no `..`). Server prefixes `APP_PUBLIC_ORIGIN` and checks the result against `billing_allowed_return_origins`. Absolute URLs in the body → 422 `invalid_return_path`. |
| Idempotency-Key | Required on checkout (and on key create/rotate as today). 64–128 chars `[A-Za-z0-9._:-]`. |

Admin CSRF (`admin_auth.py` Origin vs Host) is a different surface. Do not reuse admin cookies on app.altcontext.com.

### 4.2 `POST /portal/onboarding/claim`

**Auth:** `require_verified_portal_identity` (no tenant).

**Request**

```json
{ "invitation_token": "inv_..." }
```

`invitation_token` is the single-use secret. Server hashes it (existing invitation row stores only the hash), binds redemption to normalized verified email + expiry + one successful principal.

**Atomic transaction (one commit):** redeem invitation → create tenant → link `(issuer, subject, email)` → `grant_beta(...)`. Any audit/outbox/required write failure **rolls back the entire claim** (finding 14472). No webhook, checkout, or Polar call in this transaction. Beta **must not** create a Polar customer or subscription (`APP-SC-07`).

**Responses**

| Status | When | Body |
| --- | --- | --- |
| 201 | First successful claim | `{ "tenant_id", "issuer", "subject", "email", "replayed": false }` |
| 200 | Same issuer+subject already owns the tenant created by this invitation | `{ ..., "replayed": true }` — no second tenant, no second beta grant |
| 401 | Missing/invalid bearer | `invalid_portal_authorization` |
| 403 | Unverified email | `email_unverified` |
| 403 | Token expired, unknown, email mismatch, or principal not invited | `not_admitted` |
| 403 | `X-Tenant-ID` or body `tenant_id` present | `tenant_header_forbidden` |
| 409 | Invitation already redeemed by a **different** subject | `invitation_consumed` |
| 409 | Subject already bound to a **different** tenant | `identity_already_bound` |
| 422 | Empty/malformed token | `invalid_claim_request` |
| 503 | Identity/DB unavailable | `portal_identity_unavailable` |

Concurrent duplicate claims: one winner via invitation uniqueness. Loser sees 200 replayed or 409 `invitation_consumed`, never two tenants (`APP-SC-01`).

### 4.3 `POST /portal/billing/checkout`

**Auth:** `require_portal_principal`. **Payments:** composition `billing_payments_enabled`. Free beta default is `false`.

**Request**

```http
POST /portal/billing/checkout
Authorization: Bearer …
Origin: https://app.altcontext.com
Idempotency-Key: <client key>
Content-Type: application/json

{ "plan_code": "starter_monthly", "return_path": "/billing/return" }
```

Server maps `plan_code` → configured product id. Server sets `success_url` and `cancel_url` from allowlisted origin + `return_path` (default `/billing/return` and `/billing/cancel`). Client cannot choose catalog price or Polar product id.

**Durable attempt owns idempotency** (section 5). HTTP layer does not call Polar until the attempt row is committed.

**Responses**

| Status | When | Body |
| --- | --- | --- |
| 200 | New or replayed in-progress attempt | `{ "attempt_id", "checkout_url", "status": "pending"\|"provider_requested", "replayed": bool }` |
| 200 | Attempt already `succeeded` (replay) | `{ "attempt_id", "checkout_url": null, "status": "succeeded", "replayed": true }` — **does not grant entitlement** |
| 401 | Auth | same as `/me` |
| 403 | Payments disabled (beta) | `{ "code": "payments_disabled" }` |
| 403 | CSRF origin | `csrf_origin_denied` |
| 409 | Open **ambiguous** attempt for this tenant+plan still pending reconcile | `{ "code": "checkout_ambiguous", "attempt_id" }` — do not create another Polar checkout |
| 409 | Tenant already `paid_active` for this plan | `{ "code": "already_subscribed" }` |
| 422 | Unknown `plan_code` | `unknown_plan_code` |
| 422 | Bad `return_path` / origin | `invalid_return_path` |
| 422 | Idempotency-Key reused with different fingerprint | `idempotency_key_reuse` (parity with keys) |
| 503 | Provider timeout after persist / Polar 5xx classified ambiguous | `{ "code": "checkout_ambiguous", "attempt_id" }` — HTTP 503 with `Retry-After: 1` |

**Return URL after Polar redirect never grants paid benefits.** Browser landing on `success_url` may show `pending` until webhook or reconciliation applies `BillingState`. `APP-SC-10`, `APP-SC-18`.

### 4.4 `POST /portal/billing/manage`

**Auth:** `require_portal_principal`. Hosted customer portal only for the mapped customer (`create_portal_session`).

**Request:** `{ "return_path": "/billing" }` (optional).

| Status | When | Body |
| --- | --- | --- |
| 200 | Mapped customer exists | `{ "portal_url" }` |
| 403 | Payments disabled | `payments_disabled` |
| 403 | CSRF | `csrf_origin_denied` |
| 409 | No billing customer mapping yet | `{ "code": "billing_customer_missing" }` |
| 422 | Bad return path | `invalid_return_path` |
| 503 | Provider failure | `billing_portal_unavailable` |

Manage sessions cannot create subscriptions or change tenant. Polar Customer Portal API is the vendor UI; AltContext remains source of entitlement.

### 4.5 Existing seven routes

Unchanged by this spec except: H must **stop** constructing tenant-bound services from `app.state` overrides that drop the principal’s tenant (Plan 0002 H). `/usage` must not fabricate remaining=0 when the projection is missing; unknown stays unknown (`data_source` already distinguishes). Claim + checkout + manage stay in `portal.py`.

---

## 5. Durable checkout attempts (C)

Persist intent **before** any vendor mutation (DDIA: durable transaction then idempotent sink). Polar’s `Idempotency-Key` header is a vendor hint, not our source of truth.

### 5.1 Attempt row

Table `billing_checkout_attempt`. Follow the verified repository migration authority and provide an upgrade for existing installations; do not assume deployed databases are greenfield.

| Column | Rules |
| --- | --- |
| `id` | UUID PK (`attempt_id` returned to HTTP) |
| `tenant_id` | FK, RLS with other tenant tables |
| `provider` | `polar` (fake-provider tests use `fake`) |
| `environment` | `sandbox` \| `live` |
| `seller_account` | Polar organization id (required text) |
| `plan_code` | Internal code |
| `idempotency_key` | **Attempt-owned** opaque key sent to Polar |
| `client_idempotency_key` | HTTP `Idempotency-Key` |
| `request_fingerprint` | Canonical JSON of tenant, plan, success_url, cancel_url, environment, seller_account |
| `status` | see state machine |
| `provider_checkout_id` | nullable until Polar returns |
| `checkout_url` | nullable |
| `last_error_class` | `none` \| `ambiguous` \| `rejected` \| `expired` |
| `created_at` / `updated_at` | timestamptz |

**Uniques**

- `(tenant_id, provider, environment, seller_account, client_idempotency_key)` where client key is not null
- `(provider, environment, seller_account, idempotency_key)`
- Partial: at most one `status IN ('created','provider_requested','pending','ambiguous')` per `(tenant_id, provider, environment, seller_account)`, regardless of `plan_code`

An active attempt for one plan conflicts with creating an active attempt for another plan in the same namespace. Schema healing refuses to install this index while open cross-plan duplicates exist.

### 5.2 State machine

```text
created
  -> provider_requested   # Polar POST in flight; row already committed
  -> pending              # Polar returned checkout URL / id
  -> ambiguous            # timeout/5xx after persist; must retrieve_checkout or enumerate
  -> succeeded            # authoritative paid subscription mapped
  -> expired              # Polar checkout.expired or retrieve shows expired
  -> canceled             # user cancel; no charge
  -> failed               # 4xx / payments disabled / validation
```

Transitions to `succeeded` **only** from webhook/reconcile applying `BillingState.status=active`, never from HTTP return.

Expired or canceled attempts **do not** reuse `idempotency_key`. A new purchase mints a new attempt row and a new Polar key. This is why the current hash-of-URLs key is insufficient.

### 5.3 Concurrency

Equivalent HTTP retries share the existing open attempt (same client key + fingerprint → replay URL). Different fingerprint + same client key → 422. Timeout after Polar 2xx that the client never saw stays `pending`/`ambiguous` until `retrieve_checkout` (`GET /v1/checkouts/{id}`).

Do **not** hold a row lock across the Polar HTTP call (Release It: timeout + bulkhead). Pattern: insert `created` and commit; set `provider_requested`; call Polar with attempt `idempotency_key`; update `pending` or `ambiguous`. Reconciliation is the second exit (`CARD-15`).

### 5.4 Polar adapter call (provisional)

`POST {base}/v1/checkouts/` with:

- `products: [configured_product_id]` — server catalog only; no ad-hoc prices in v1
- `external_customer_id: "{environment}:{tenant_id}"`
- `metadata: { tenant_id, environment, seller_account, attempt_id }`
- `success_url`, `return_url` (cancel) already origin-checked
- header `Idempotency-Key: <attempt.idempotency_key>`
- header `Authorization: Bearer <OAT>`

Polar documents `external_customer_id` as the reconciliation handle and disables email edit when set. Current adapter omits it on checkout; C must add it.

`create_checkout_session` returns a typed checkout ID + URL result; C’s **service** (`checkout_service.py`) owns attempt lifecycle. Protocol additions in section 7.

---

## 6. Environment and live-safety

| Setting | Sandbox default | Live |
| --- | --- | --- |
| `POLAR_ENVIRONMENT` / `billing_environment` | `sandbox` | `live` (explicit only) |
| `POLAR_BASE_URL` | `https://sandbox-api.polar.sh` | `https://api.polar.sh` |
| `POLAR_PAYMENTS_ENABLED` | `false` until sandbox rehearsal | separately authorized |
| Tokens / webhook secrets / product ids | sandbox org | live org — never mixed |

**Fail closed before any vendor call:** if `environment=sandbox` and base host is `api.polar.sh` (or vice versa), raise at composition **and** at `PolarBillingProvider.__init__`. Current code is incoherent: sandbox flag + live default URL. U owns composition wiring; C owns the adapter constructor check so a miswired test cannot call live (`CARD-06`).

`payments_enabled=false` must reject checkout/manage with 403 `payments_disabled` and must not create Polar customers. Webhook signature verification still runs so sandbox fixtures can be tested with payments off.

---

## 7. `BillingProvider` protocol (C owns; R/H consume)

Replace the current five-method surface with the following. Fake provider implements the same protocol.

```python
class CheckoutSession(Protocol):
    url: str
    provider_checkout_id: str

class EnumerationPage(Protocol):
    items: tuple[BillingState, ...]
    next_cursor: str | None  # opaque; Polar adapter may encode page number
    exhausted: bool

class BillingProvider(Protocol):
    async def create_checkout_session(
        self, *, tenant_id: UUID, plan_code: str, success_url: str, cancel_url: str,
        idempotency_key: str, attempt_id: UUID,
    ) -> CheckoutSession: ...
    async def create_portal_session(self, *, tenant_id: UUID, return_url: str) -> str: ...
    async def retrieve_state(
        self, *, provider_customer_id: str, provider_subscription_id: str | None,
        request_timeout: float,
    ) -> BillingState: ...
    async def retrieve_checkout(
        self, *, provider_checkout_id: str, request_timeout: float,
    ) -> Mapping[str, object]: ...
    async def enumerate_subscriptions(
        self, *, cursor: str | None, limit: int, request_timeout: float,
    ) -> EnumerationPage: ...
    async def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str],
    ) -> bool: ...
    async def parse_event(self, raw_body: bytes) -> Mapping[str, object]: ...
```

`create_checkout_session` **must** take the attempt’s `idempotency_key` (stop hashing URLs inside the adapter) and return `CheckoutSession` containing both `provider_checkout_id` and `url`. The service persists both atomically. Returning only a URL cannot satisfy the stated persistence contract. Update internal fakes/callers within the adapter lane's owned paths; downstream H consumes the typed contract.

Coordinator amendment 2026-09-22: client idempotency uniqueness is tenant-scoped; identical keys used by different tenants must not collide or disclose another attempt. Existing installations need a verified upgrade path, regardless of historical greenfield planning.

### 7.1 Enumeration (vendor-supported Polar path)

Polar core API: `GET /v1/subscriptions/?page=&limit=` with optional `organization_id`. Pagination object has `total_count` and `max_page`. Max `limit` is 100; this contract uses **`limit=50`** (`PERF-13` headroom vs Polar sandbox 100 req/min).

Cursor is opaque to R. Polar adapter encodes `page` as decimal string. Bound: max **20 pages per `--once` run** (1000 subscriptions) then persist cursor and exit. Per-item failure does not abort the page (`rg-007`).

**No network I/O while a DB row lock is held.** Lease the cursor row, commit, then GET, then persist progress.

Reject a remote subscription whose `organization_id` ≠ configured `seller_account`, or whose `customer.external_id` does not parse to this environment’s tenant, or whose tenant mapping is missing — **quarantine**, do not invent a tenant from email.

### 7.2 Webhook verification (APP1-HG-45)

Polar SDK: `validate_event(body, headers, secret)` — **full header map**, not a concatenated signature string.

Required headers to persist with the raw body (audit; do not log secrets):

- `webhook-id` (or Polar/Svix aliases)
- `webhook-timestamp` / `svix-timestamp`
- `webhook-signature` / `x-polar-signature` / `polar-signature`

Verification rules:

1. Body cap 1 MiB (already in router).
2. Delivery timestamp within 300s (already `_DELIVERY_TIMESTAMP_HEADERS`).
3. Standard Webhooks HMAC over `{webhook-id}.{webhook-timestamp}.{raw_body}` when the configured secret is the post-2026-09-08 scheme; **also** try Polar legacy HMAC (UTF-8 bytes of full `whsec_…`) because Polar SDKs try both. Fake provider uses **fixtures**, not guessed production signatures.
4. Constant-time compare. Parse only after verify returns true.
5. This packet does **not** claim the current `PolarBillingProvider.verify_webhook(raw_body, signature)` accepts genuine Polar deliveries.

Router stays `POST /billing/webhooks/polar`, 202 after durable inbox insert, projection bounded (existing 2s persist / 1s projection). Polar times out at 10s and retries up to 10 times; keep handler under 2s.

Inbox unique: `(provider, environment, seller_account, provider_event_id)`. Duplicate delivery → 202 with no second projection (`APP-SC-11`).

Webhook arrival **never** grants entitlement by itself; `apply_billing_state` is the only paid transition.

---

## 8. Recovery and reconciliation (C schema + protocol; R processing)

Two disjoint recovery paths (`GRPH-09`):

1. **Known projections** — existing `retrieve_state` by customer/subscription id.
2. **Remote orphans** — `enumerate_subscriptions` for provider subscriptions with no local projection row.

Also recover **ambiguous checkouts** via `retrieve_checkout` for attempts in `ambiguous`/`provider_requested` older than the provider timeout.

### 8.1 Cursor and lease

Table `billing_reconciliation_cursor`:

| Column | Rules |
| --- | --- |
| `(provider, environment, seller_account, kind)` PK | `kind` in `subscriptions`, `ambiguous_checkouts` |
| `cursor` | opaque text |
| `lease_owner` / `lease_until` | fencing; steal only after expiry (`GRPH-31`) |
| `last_progress_at` | stall detector: `--once` that makes zero progress cannot report healthy success |

Worker: lease (short, e.g. 30s), commit, page Polar with `request_timeout=8`, persist items individually, advance cursor, heartbeat. Timeouts are failures of that page, not success. Bounded work per run.

### 8.2 Entitlement application

`TenantEntitlementService.apply_billing_state` remains the only paid mutation. Mapping:

| Provider / inbox | Local `BillingSubscriptionStatus` | Entitlement |
| --- | --- | --- |
| subscription active/created/renewed/trialing | `active` | `paid_active` |
| past_due / payment_failed / unpaid | `past_due` | `past_due` (keys unchanged) |
| canceled / ended | `canceled` | closed after grace policy (operator-owned; not invented here) |
| refunded | `refund_hold` | closed; no automatic beta restoration of paid leftover |
| none / missing row | `none` | fail-safe expired / existing beta if never paid |

Beta history is never converted to arrears (`APP-SC-07`, `APP-SC-18`). API keys unchanged across all billing transitions (`APP-SC-12`).

Return-from-checkout with `status=pending` is a UI state, not `paid_active`.

---

## 9. Schema and ownership edges

```text
C: 001_identity_schema.py, portal_billing models,
   portal_contracts.BillingProvider, polar_provider.py,
   checkout_attempt_repository.py, checkout_service.py
        │
        ├─► R: scripts/billing_reconcile.py  (processing only)
        ├─► H: routers/portal.py claim/checkout/manage
        │         uses checkout_service; does not call Polar directly
        ├─► K: billing_webhooks.py header pass-through after C protocol change
        └─► U: portal_composition.py factories, env/base coherence, payments_enabled
```

Shared-file rule: C is sole editor of `polar_provider.py` and the protocol. U wires the factory after C lands. H is sole editor of `portal.py` routes. Claim and checkout are **not** split across routers in this contract.

---

## 10. Portability (do not build a multi-provider framework)

`REF-15`: keep one adapter. Polar is provisional. Paddle/Stripe would implement the same protocol. No second production adapter in APP-1. Switching before the first live payment avoids migrating an active book (`CARD-15`, `CARD-16`). Link/wallets are Polar/Stripe checkout features, not seller choice — see the [portability assessment](../assessments/current/app-altcontext-checkout-provider-portability-and-link-2026-09-22.md).

---

## 11. Acceptance matrix

**Bar for C/H/R merge:** fake `BillingProvider` + real PostgreSQL. Polar sandbox evidence is V, not this spec.

### 11.1 Fake-provider (required now)

| ID | Case | Expect |
| --- | --- | --- |
| FP-01 | Concurrent claim same invitation | one tenant; loser 200 replayed or 409; beta granted once |
| FP-02 | Claim without verified email | 403 `email_unverified`; no tenant |
| FP-03 | Claim with `X-Tenant-ID` | 403; no tenant |
| FP-04 | Checkout while `payments_enabled=false` | 403 `payments_disabled`; zero provider calls |
| FP-05 | Checkout persist then provider timeout | attempt `ambiguous`; HTTP 503; retry same Idempotency-Key returns same `attempt_id` |
| FP-06 | Second checkout after `expired` | new attempt, new provider key, not the hash-of-URLs collision |
| FP-07 | Success return URL hit before webhook | usage/entitlement still beta/closed; `GET /usage` not `paid_active` |
| FP-08 | Webhook duplicate same `(provider, env, seller, event_id)` | 202; projection once |
| FP-09 | Webhook missing `webhook-id` / bad signature fixture | 401; no inbox row |
| FP-10 | Enumerate page includes subscription with no local row | R creates quarantine or mapped projection from `external_id`; never from request tenant header |
| FP-11 | Enumerate `organization_id` mismatch | quarantine; no tenant invented |
| FP-12 | `--once` worker leased but 0 pages progressed | non-zero exit; not healthy |
| FP-13 | Sandbox env + live base URL in composition | constructor/composition error; no HTTP |
| FP-14 | Foreign `attempt_id` / billing id on tenant B | 404/403; no scope change (`APP-SC-02`) |
| FP-15 | Manage with no customer mapping | 409 `billing_customer_missing` |
| FP-16 | Billing active does not rotate keys | key ids unchanged (`APP-SC-12`) |

### 11.2 Polar sandbox (later V; do not implement in this lane)

Valid and invalid genuine-format signatures (both Standard Webhooks and legacy Polar HMAC), checkout → webhook → paid, cancel, refund_hold, expired session new purchase, sandbox token against live URL rejected, two-tenant isolation. Record sanitized fixtures. No live charges.

### 11.3 APP-SC mapping

| APP-SC | This contract |
| --- | --- |
| 01 | FP-01 claim atomicity |
| 02 | FP-14 isolation |
| 03 | Bearer/CSRF/unverified email |
| 07 | FP-04 zero Polar on beta |
| 10 | server catalog + origin + attempt idempotency |
| 11 | FP-08/09 inbox + R cursor |
| 12 | FP-16 keys stable; status table §8.2 |
| 13 | 503 on provider outage; local keys still work |
| 18 | FP-07 return URL; explicit checkout only |

APP-SC-19/20 remain beta observation and paid canary; out of this spec.

---

## 12. Explicit non-goals

- Production Polar/Paddle/Stripe cutover or secret reads.
- Multi-provider runtime framework or Link-as-auth.
- Implementing `portal.py` / `polar_provider.py` in this planning lane.
- Changing allowance numbers, prices, or grace policy (operator decisions).
- Cookie Clerk sessions.
- Treating protocol unit smoke as launch evidence (`CARD-06`).

---

## 13. Open operator inputs (do not invent)

Catalog `plan_code` → Polar product id, `seller_account` / organization id, `APP_PUBLIC_ORIGIN`, `APP_ALLOWED_ORIGINS`, failed-payment grace, stale-entitlement timeout, USD as **development** currency only. Clerk/Polar provisioning remains blocker 821 for rehearsal, not for this contract.
