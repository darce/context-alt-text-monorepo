# APP-1 checkout, provider portability and Stripe Link

Date: 2026-09-22 UTC. Status: accepted planning direction; implementation and real-provider acceptance remain separately verified. Task: APP-1. Handoff decisions: 13229–13235. This assessment preserves the operator discussion; it does not claim a production provider change or completed checkout.

## Recommendation

Build AltContext’s self-service account, API-key and usage experience now. Use hosted checkout behind the existing small billing-provider boundary. Use direct Stripe for sandbox integration, as selected by the processor decision; this supersedes the earlier provisional Polar recommendation. Confirm the legal seller after incorporation when feasible and verify production readiness before paid launch. Existing free-beta users retain their tenant and API keys when paid billing is enabled.

Prefer one real sandbox integration plus a deterministic test adapter. Do not build a general multi-provider billing framework or a second production adapter merely to demonstrate portability. Record the exit design now and verify it before the paid-launch decision. Switching before the first live payment avoids migration of an active billing book.

## Link is a checkout feature, not a merchant-of-record choice

The operator’s Grok comparison referred to Link, Stripe’s accelerated wallet, not the entire xAI billing stack. Link securely reuses payment details across participating businesses and works within hosted Stripe Checkout. A Link button does not establish who is the legal seller, who handles taxes, or which seller contract applies. [Stripe Link](https://docs.stripe.com/payments/link), [Link with Checkout](https://docs.stripe.com/payments/link/checkout-link).

Polar documents Stripe as its underlying processor. That fact alone does not establish availability of every Stripe feature in an individual Polar checkout. Verify Link with the actual seller configuration, currency and supported funding method. A reported Polar issue concerns Link users with saved US bank accounts; this is an unverified external report to turn into a checkout test, not proof that every checkout is broken. [Polar processors](https://polar.sh/legal/payment-processor-partners), [reported issue 13407](https://github.com/polarsource/polar/issues/13407).

xAI’s public subprocessor list identifies both Stripe and PayPal/Braintree for payment processing; it does not establish an exclusive processor, the exact checkout routing, or equivalent negotiated terms for AltContext. [xAI list](https://x.ai/legal/subprocessor-list).

## Ownership and adapter contract

| Owner | Responsibilities |
| --- | --- |
| Clerk | Interactive sign-in and session verification |
| AltContext | Stable tenant UUID, invitation claim, API-key lifecycle, internal plan codes, usage ledger and entitlement projection |
| Billing provider | Payment collection, hosted billing-management UI, authoritative financial/subscription records |
| Link or another wallet | Optional checkout acceleration; never tenant authentication or API-key ownership |

The browser submits an internal plan code to AltContext. The server selects the configured product, price and approved return URL. Persist a checkout attempt before contacting the provider; reuse an attempt only for an equivalent logical operation. An ambiguous timeout stays pending until reconciliation determines the outcome. Do not blindly create another charge.

The minimal boundary creates checkout and billing-management sessions, verifies raw webhook bodies with the full required header set, normalizes verified events, retrieves authoritative state and supports bounded enumeration for recovery. Keep vendor IDs in mappings keyed by provider, environment and seller-account identity. Namespace event deduplication and checkout records the same way. Sandbox and production must never alias.

AltContext grants access from verified server-side state; the return URL alone never grants paid benefits. Refunds, cancellations and out-of-order events update entitlements according to the application contract. Authentication, entitlement and usage exhaustion are distinct states. A billing change must not regenerate or revoke an otherwise valid API key.

The code map confirms `BillingProvider` in `recognition/domain/portal_contracts.py` and separate `TenantKeyService`. Existing checkout/state/webhook methods are a starting point, not proof that durable attempts, full-header verification or provider enumeration are implemented. Indexed main can lag feature branches; verify the lane’s exact source before edits.

## Customer flow and state requirements

```text
Sign in -> Redeem invitation -> Create API key -> Connect WordPress
                                  |
                           Account dashboard
                     API keys | Usage | Billing
                                          |
                                      Upgrade
                                          |
                             Hosted checkout
                         Link / supported fallback
                                          |
                              Confirming payment
                              /        |        \
                           Active    Pending   Cancelled/failed
```

Account UI owns create/list/rotate/revoke and one-time secret display, connection guidance, allowance and renewal/expiry status. Payment UI owns the payment form and invoice/payment-method management. Never persist plaintext keys in browser storage, analytics or logs. Link authentication must not switch the signed-in tenant or overwrite Clerk identity because the payer uses another email.

Design loading, empty, exhausted, stale/unavailable usage, pending payment, duplicate return, cancellation and recoverable error states before implementation. Offer an ordinary payment fallback; do not make a Link account a prerequisite. Verify keyboard/mobile navigation, readable currency and merchant identity. The dedicated portal UX map remains a required planning artifact; existing WordPress/demo maps do not cover this account flow.

## Commercial decision and operator actions

The separate [vendor comparison](app1-payment-vendor-terms-comparison.md) contains the remote source collection. Coordinator conclusion: Paddle has selected friendlier published clauses (amendment notice, retained-fund timing and assignment qualification); this is not a blanket legal endorsement. Polar’s insurance, product approval and cash-retention conditions require explicit consideration. Lemon Squeezy is not demonstrated to be an overall contractual improvement. Ordinary direct Stripe increases control but leaves sales-tax responsibility with the seller. Merchant-of-record and direct-processing arrangements must be compared on total operating burden, not only checkout appearance.

Ask shortlisted providers about the actual publisher-supplied-image, roster/face-matching and editor-reviewed-description workflow; insurance during sandbox and live operation; reserve amount/release criteria; buyer-data use; and individual-to-company migration. Do not infer approval from another AI business’s use. No messages have been sent to vendors.

Clerk account is being provisioned by the operator. Secrets will be supplied through the existing untracked environment mechanism; never print them or include `.env` in remote lane archives. Polar sandbox and production use separate identities and credentials. Sandbox prevents real payment processing, but is not a verified exemption from contractual insurance obligations. Default checkout currency is independent of seller identity and bank payout currency; USD is a development choice, not a guarantee of USD payouts. [Polar sandbox](https://polar.sh/docs/integrate/sandbox).

Migration after paid launch remains operational work: Polar documents coordinated payment-method transfer, catalog/subscription recreation and aligned renewal dates to prevent double charging. An adapter does not waive contractual transfer restrictions or migrate a legal seller automatically. [Migration documentation](https://polar.sh/docs/migrate-away).

## Canon and evidence validation

- `DOM-03`: distinguish wallet, processor, merchant of record and application entitlement; do not use “provider” ambiguously.
- `REF-15`: wrap the external billing API in the existing minimal adapter.
- `CARD-06` / Principle 13: actual sandbox and tenant-isolation evidence precedes paid activation; a hosted checkout screenshot is insufficient.
- `CARD-15` / Principle 3: keep the pre-revenue choice reversible; write rollback before live cutover.
- `CARD-16` / Principle 8: preserve local tenant/key/usage records and a credible external-provider exit. Temporary single-provider use must be revisited before the paid gate.

Canon verified locally in `~/Development/heuristics-canon-research/lexicons/engineering.md`, `PRINCIPLES.md`, and `reasoning/{evidence-before-commitment,reversible-commitments,second-exit-hostile-landlord}.md`; canonical link: https://github.com/darce/heuristics-canon . These are engineering decision rules, not evidence of vendor capabilities or legal enforceability.

Handoff semantic retrieval reported `embeddings_mode=verified`, model `gte-base-en-v1.5`. Prior decision 2023 supports the earlier MoR choice for solo-founder operating burden; retrieval did not prove Link support or a completed integration. Source documents and live tests must supply those facts.

## Verification before paid activation

Test two-tenant isolation, wrong-tenant session access, genuine signatures, webhook replay/order, interrupted checkout, paid return before webhook, refund/cancel, missing vendor state and restart reconciliation. Exercise Link saved-card flow, supported alternative funding and ordinary-card fallback in the selected checkout. Test malformed/expired credentials and mismatched sandbox/live base URLs. Keep real PostgreSQL concurrency and vendor/browser receipts distinct from narrow unit smoke tests.
