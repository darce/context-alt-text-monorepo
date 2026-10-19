# APP-1 portal account and billing contract

> **Status:** proposed planning contract. Not implementation. Not a Stripe production cutover.
> **Date:** 2026-09-22 UTC.
> **Task:** APP-1. Lane: `billing-contract`.
> **Owner of this file:** P / billing-contract. Downstream owners are named per surface below.
> **Supersedes:** the missing-spec placeholder in [Plan 0001](../plans/0001-app-altcontext-beta-clerk-stripe-task-plan.md) and the contract gaps listed in [Plan 0002](../plans/0002-app-altcontext-launch-continuation-task-plan.md) node P/C/H/R.

This document freezes the portable hosted-checkout, tenant-identity, durable-attempt, webhook, and recovery contracts that C (schema/provider), H (portal HTTP), and R (reconciliation processing) must implement. Standard Stripe direct is the selected integration behind the existing `BillingProvider` boundary; adapter implementation and sandbox qualification remain separate work. Paid live traffic stays behind the separate paid gate.

## Provenance

**PLANNED CONTRACT, not deployed implementation.** [ADR-014](../adrs/ADR-014-payment-processor-merchant-of-record-selection.md) is the accepted authority: standard Stripe direct on AltContext's own account, Clerk authentication, and AltContext-owned manual tax calculation and seller obligations. Stripe Managed Payments and merchant-of-record arrangements are excluded.

Portable tenant, attempt and admission contracts remain in force. Earlier vendor-specific SDK, signature, pagination and environment behavior has been removed; historical adapter receipts do not qualify Stripe. Implementation must pin the Stripe API/SDK and genuine sandbox fixtures. No provider cutover is claimed.

References: [Checkout Sessions](https://docs.stripe.com/api/checkout/sessions/create), [API keys/modes](https://docs.stripe.com/keys), [webhook verification](https://docs.stripe.com/events/manage-webhook-endpoints#signature-errors), [customer portal](https://docs.stripe.com/customer-management).

## 1. Terminology (`DOM-03`)

| Term | Authority |
| --- | --- |
| Local tenant | Stable AltContext UUID owning keys, usage and entitlement. |
| Clerk identity | Interactive sign-in; does not own allowance or API keys. |
| Stripe direct | Payment processing; AltContext is the seller. |
| Seller account | AltContext's Stripe account identity, namespaced with environment. |
| Hosted checkout / portal | Stripe payment collection / invoice and subscription management. |
| Usage ledger | AltContext's durable units, reservations and audited grants. |
| Site cap | WordPress attempt safety limit, not the tenant's account balance. |
| Tax | AltContext determines and manually calculates tax and handles seller obligations. |

## 2. Inspected gaps (current code is not this contract)

Tenant/key, admission, checkout-attempt and reconciliation seams exist. Historical adapter code and offline receipts must not be described as a qualified Stripe integration. Inspect the exact branch before implementation.

Reuse the existing `BillingProvider` protocol, tenant-scoped repositories, local usage authority and durable inbox/worker pattern. Supply attempt-owned idempotency, financial-state reconciliation, genuine signature verification and mode/seller isolation. Grant shared-file ownership before schema, route or composition edits.

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
| Stripe customer / subscription / checkout ids | mapping + projection | `(provider, environment, seller_account)` |


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

**Atomic transaction (one commit):** redeem invitation → create tenant → link `(issuer, subject, email)` → `grant_beta(...)`. Any audit/outbox/required write failure **rolls back the entire claim** (finding 14472). No webhook, checkout, or Stripe call in this transaction. Beta **must not** create a Stripe customer or subscription (`APP-SC-07`).

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

Server maps `plan_code` → configured Stripe Price ID. Server sets `success_url` and `cancel_url` from allowlisted origin + `return_path` (default `/billing/return` and `/billing/cancel`). Client cannot choose catalog price or Stripe Price ID.

**Durable attempt owns idempotency** (section 5). HTTP layer does not call Stripe until the attempt row is committed.

**Responses**

| Status | When | Body |
| --- | --- | --- |
| 200 | New or replayed in-progress attempt | `{ "attempt_id", "checkout_url", "status": "pending"\|"provider_requested", "replayed": bool }` |
| 200 | Attempt already `succeeded` (replay) | `{ "attempt_id", "checkout_url": null, "status": "succeeded", "replayed": true }` — **does not grant entitlement** |
| 401 | Auth | same as `/me` |
| 403 | Payments disabled (beta) | `{ "code": "payments_disabled" }` |
| 403 | CSRF origin | `csrf_origin_denied` |
| 409 | Open **ambiguous** attempt for this tenant+plan still pending reconcile | `{ "code": "checkout_ambiguous", "attempt_id" }` — do not create another Stripe checkout |
| 409 | Tenant already `paid_active` for this plan | `{ "code": "already_subscribed" }` |
| 422 | Unknown `plan_code` | `unknown_plan_code` |
| 422 | Bad `return_path` / origin | `invalid_return_path` |
| 422 | Idempotency-Key reused with different fingerprint | `idempotency_key_reuse` (parity with keys) |
| 503 | Provider timeout after persist / Stripe 5xx classified ambiguous | `{ "code": "checkout_ambiguous", "attempt_id" }` — HTTP 503 with `Retry-After: 1` |

**Return URL after Stripe redirect never grants paid benefits.** Browser landing on `success_url` may show `pending` until webhook or reconciliation applies `BillingState`. `APP-SC-10`, `APP-SC-18`.

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

Manage sessions cannot create subscriptions or change tenant. Stripe customer portal is the vendor UI; AltContext remains source of entitlement.

### 4.5 Existing seven routes

Unchanged by this spec except: H must **stop** constructing tenant-bound services from `app.state` overrides that drop the principal’s tenant (Plan 0002 H). `/usage` must not fabricate remaining=0 when the projection is missing; unknown stays unknown (`data_source` already distinguishes). Claim + checkout + manage stay in `portal.py`.

---

## 5. Durable checkout attempts (C)

Persist intent **before** any vendor mutation (DDIA: durable transaction then idempotent sink). Stripe’s `Idempotency-Key` header is a vendor hint, not our source of truth.

### 5.1 Attempt row

Table `billing_checkout_attempt`. Follow the verified repository migration authority and provide an upgrade for existing installations; do not assume deployed databases are greenfield.

| Column | Rules |
| --- | --- |
| `id` | UUID PK (`attempt_id` returned to HTTP) |
| `tenant_id` | FK, RLS with other tenant tables |
| `provider` | `stripe` (fake-provider tests use `fake`) |
| `environment` | `sandbox` \| `live` |
| `seller_account` | Stripe account ID (required text) |
| `plan_code` | Internal code |
| `idempotency_key` | **Attempt-owned** opaque key sent to Stripe |
| `client_idempotency_key` | HTTP `Idempotency-Key` |
| `request_fingerprint` | Canonical JSON of tenant, plan, success_url, cancel_url, environment, seller_account |
| `status` | see state machine |
| `provider_checkout_id` | nullable until Stripe returns |
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
  -> provider_requested   # Stripe POST in flight; row already committed
  -> pending              # Stripe returned checkout URL / id
  -> ambiguous            # timeout/5xx after persist; must retrieve_checkout or enumerate
  -> succeeded            # authoritative paid subscription mapped
  -> expired              # Stripe checkout.expired or retrieve shows expired
  -> canceled             # user cancel; no charge
  -> failed               # 4xx / payments disabled / validation
```

Transitions to `succeeded` **only** from webhook/reconcile applying `BillingState.status=active`, never from HTTP return.

Expired or canceled attempts **do not** reuse `idempotency_key`. A new purchase mints a new attempt row and a new Stripe key. This is why the current hash-of-URLs key is insufficient.

### 5.3 Concurrency

Equivalent HTTP retries share the existing open attempt (same client key + fingerprint → replay URL). Different fingerprint + same client key → 422. Timeout after Stripe 2xx that the client never saw stays `pending`/`ambiguous` until `retrieve_checkout` (`GET /v1/checkouts/{id}`).

Do **not** hold a row lock across the Stripe HTTP call (Release It: timeout + bulkhead). Pattern: insert `created` and commit; set `provider_requested`; call Stripe with attempt `idempotency_key`; update `pending` or `ambiguous`. Reconciliation is the second exit (`CARD-15`).

### 5.4 Stripe adapter call (provisional)

Use `POST https://api.stripe.com/v1/checkout/sessions` through the pinned Stripe SDK/API:

- Server-owned `mode=subscription` and `line_items` with the configured recurring Price ID and quantity.
- Tenant-mapped Stripe `customer`, opaque `client_reference_id` and safe attempt/environment/tenant metadata; never choose a tenant from checkout email.
- Allowlisted `success_url` and `cancel_url`.
- Attempt-owned `Idempotency-Key` and mode-correct secret credential.
- Explicit manual tax treatment from AltContext's approved seller policy; no automatic tax or merchant-of-record product by implication.

The service persists attempt state and returns a typed session ID and URL. Browser return does not grant entitlement. Reconcile an ambiguous original attempt before creating another payment.

## 6. Environment and live-safety

Local environment vocabulary may be `sandbox` / `live`, but Stripe test/live requests use the same `https://api.stripe.com` host. Separate API credentials, webhook secrets, object IDs and seller mappings; do not invent a sandbox host or rely on host-only mode checks. Validate Stripe `livemode` against local environment where applicable.

`payments_enabled=false` rejects new checkout/manage mutations. Keep signature processing and reconciliation for existing customers available. CLI-forwarded endpoint secrets and Dashboard endpoint secrets differ. Never print secrets.

Free beta grants remain local and zero-charge. Login, key recovery and billing recovery stay available when expensive work pauses.

## 7. `BillingProvider` protocol (C owns; R/H consume)

Replace the current five-method surface with the following. Fake provider implements the same protocol.

```python
class CheckoutSession(Protocol):
    url: str
    provider_checkout_id: str

class EnumerationPage(Protocol):
    items: tuple[BillingState, ...]
    next_cursor: str | None  # opaque; selected adapter uses a supported opaque cursor
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

### 7.1 Enumeration (vendor-supported Stripe path)

Use the pinned Stripe customer/subscription APIs and supported cursor pagination. Bind opaque cursors to provider/environment/seller. Explicitly bound page size, per-call timeout, whole-run deadline, lease and work cap; do not copy page-number semantics from another API.

Retrieve current subscription, invoice and payment state through tenant-owned customer mappings. Webhooks trigger reconciliation; arrival order does not determine financial truth. Persist resumable cursors and per-item failures. Genuine sandbox evidence is required.

### 7.2 Webhook verification (APP1-HG-45)

Verify the exact unmodified raw body, `Stripe-Signature` and correct endpoint secret with the supported Stripe SDK verifier and timestamp tolerance. Reject invalid/malformed/mode-mismatched events. Accept no alternate vendor headers, body-only HMAC or legacy signing algorithm.

Selected endpoint: `POST /billing/webhooks/stripe`. Persist a deduplicated inbox keyed by provider/environment/seller/event ID before 2xx; duplicates grant nothing twice. Persistence failure is retryable. Reconcile in the bounded durable worker.

Pin genuine fixtures for checkout, invoice payment/failure, subscription updates/deletion and required refund/dispute cases. Offline historical verifier tests are not Stripe delivery proof.

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

Worker: lease (short, e.g. 30s), commit, call Stripe with `request_timeout=8`, persist items individually, advance cursor, heartbeat. Timeouts are failures of that page, not success. Bounded work per run.

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

C owns `BillingProvider`, selected adapter and checkout-attempt schema/service. H owns portal/webhook HTTP. R owns reconciliation. U owns usage/admission composition. Serialize overlapping schema, route and composition edits.

Namespace mappings and dedupe by provider/environment/seller. Tenant, operation and attempt identities stay local. Historical namespaces need a reviewed drained-writer migration before activation; this documentation change performs no migration.

## 10. Portability (do not build a multi-provider framework)

Keep one selected standard Stripe adapter behind the existing protocol. Retain exportable mappings and local keys/usage. An interface does not automatically migrate customers/payment methods or seller tax obligations. No second provider or live cutover is authorized.

## 11. Acceptance matrix

**Bar for C/H/R merge:** fake `BillingProvider` + real PostgreSQL. Stripe sandbox evidence is V, not this spec.

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
| FP-09 | Webhook missing `Stripe-Signature` / bad signature fixture | 401; no inbox row |
| FP-10 | Enumerate page includes subscription with no local row | R creates quarantine or mapped projection from `external_id`; never from request tenant header |
| FP-11 | Enumerate seller-account namespace mismatch | quarantine; no tenant invented |
| FP-12 | `--once` worker leased but 0 pages progressed | non-zero exit; not healthy |
| FP-13 | Sandbox env + live base URL in composition | constructor/composition error; no HTTP |
| FP-14 | Foreign `attempt_id` / billing id on tenant B | 404/403; no scope change (`APP-SC-02`) |
| FP-15 | Manage with no customer mapping | 409 `billing_customer_missing` |
| FP-16 | Billing active does not rotate keys | key ids unchanged (`APP-SC-12`) |

### 11.2 Stripe sandbox (later V; do not implement in this lane)

Require genuine Stripe signatures, checkout → durable inbox → reconciliation → entitlement, renewal, failed payment, cancel, refund/dispute, expired-session recovery and interrupted checkout. Test duplicate/reordered events, mode/seller mismatch and two-tenant isolation. Return before reconciliation stays pending. Offline doubles and historical adapter receipts are separate evidence.

### 11.3 APP-SC mapping

| APP-SC | This contract |
| --- | --- |
| 01 | FP-01 claim atomicity |
| 02 | FP-14 isolation |
| 03 | Bearer/CSRF/unverified email |
| 07 | FP-04 zero Stripe on beta |
| 10 | server catalog + origin + attempt idempotency |
| 11 | FP-08/09 inbox + R cursor |
| 12 | FP-16 keys stable; status table §8.2 |
| 13 | 503 on provider outage; local keys still work |
| 18 | FP-07 return URL; explicit checkout only |

APP-SC-19/20 remain beta observation and paid canary; out of this spec.

---

## 12. Explicit non-goals

- Production payment cutover or secret reads.
- Multi-provider runtime framework or Link-as-auth.
- Implementing `portal.py` / `selected Stripe adapter (planned)` in this planning lane.
- Changing allowance numbers, prices, or grace policy (operator decisions).
- Cookie Clerk sessions.
- Treating protocol unit smoke as launch evidence (`CARD-06`).

---

## 13. Open operator inputs (do not invent)

Catalog `plan_code` → Stripe Price ID, `seller_account` / Stripe account ID, `APP_PUBLIC_ORIGIN`, `APP_ALLOWED_ORIGINS`, failed-payment grace, stale-entitlement timeout, USD as **development** currency only. Clerk/Stripe provisioning remains blocker 821 for rehearsal, not for this contract.
