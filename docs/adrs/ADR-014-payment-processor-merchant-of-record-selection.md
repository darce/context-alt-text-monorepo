# ADR-014: Standard Stripe direct payments

- **Status:** ACCEPTED — current billing-provider authority.
- **Confirmed:** 2026-10-19 by the operator; standard Stripe direct was selected in APP-1 on 2026-09-22.
- **Supersedes:** all earlier payment-provider selection and merchant-of-record recommendations in project plans, scopes, assessments, roadmaps and runbooks.
- **Implementation status:** selected design; deployment and release acceptance require their own evidence.
- **Execution:** [launch continuation](../plans/0002-app-altcontext-launch-continuation-task-plan.md), [account/billing contract](../specs/app-portal-account-billing-spec.md).

## Decision

Use **standard Stripe payments on AltContext's own Stripe account**, with Stripe Checkout Sessions and the hosted customer portal. Use Stripe Billing for the selected recurring offer. **Do not use Stripe Managed Payments or any merchant-of-record arrangement.**

AltContext is the seller. Tax determination and manual calculation, registration, collection, reporting and remittance remain AltContext's responsibility. Do not assume Stripe performs those duties automatically or enable an automated tax product by implication.

Clerk supplies interactive authentication. AltContext retains its stable tenant UUID, API keys, usage ledger, audited grants, admission controls and entitlement projection. Stripe owns financial payment, invoice and subscription records. WordPress reads tenant usage and submits work; its local attempt limit is an optional site safety cap, not a refillable account balance.

## Accounting and customer experience

Customer-facing units must match the billable operation contract. Use image-description units or clearly defined credits; model input/output tokens and GPU cost are internal cost measurements unless an explicit token-priced offer is approved.

Reserve tenant allowance atomically before costly dispatch, settle once under the accepted charging policy, and deduplicate retries and verified payment events. API-key rotation must not reset allowance. Reads and polling do not spend image units. Preserve used, reserved, remaining, allowance, period and observation time; unavailable counts remain unknown.

One account area owns **Usage & billing**: allowance, consumption, pending reservations, reset/expiry date, transaction history and hosted billing-management entry. WordPress shows a compact read-only balance and selected-run estimate next to Describe, with a link to that account area. Keep local site caps in Settings.

The initial recurring offer and its allowance are the existing launch baseline. Purchased top-ups and automatic refills need an explicit product/ledger contract before implementation: unit quantity, currency and tax, expiry/rollover, refunds, credit priority, verified-payment grant idempotency and reconciliation. Auto-refill, if approved later, is opt-in with a threshold and a spending cap. A checkout return URL never credits an account.

## Integration and release boundary

Use the existing small `BillingProvider` boundary; do not add another vendor framework. Pin the Stripe API/SDK and genuine webhook fixtures during implementation. Verify signatures over the unmodified request body using `Stripe-Signature`, persist an inbox event before acknowledgement, and reconcile authoritative Stripe state. Keep provider calls off the recognition/description admission path.

Keep test and live credentials, webhook secrets, object mappings and seller-account namespaces separate. Live payments stay disabled until the paid gate is approved and real sandbox evidence covers checkout, duplicate/reordered events, interruption, cancellation, renewal, refund and recovery. Historical adapter tests are not proof of the selected Stripe integration.

## Documentation precedence

This file owns provider selection and tax responsibility. Plans own sequencing; specs own request/state contracts; runbooks require deployed-version evidence. A superseded document must identify its replacement before its body. Remove contradictory recommendations instead of retaining an active-looking alternative table.

Before editing account or billing documentation, follow this decision. Do not infer the current provider from an old filename, search snippet or historical receipt.

## Research basis

Canon v0.26.2: [DATA-14 — No dual writes](../../../heuristics-canon-v0.26.2/lexicons/engineering.md#data-14), *Designing Data-Intensive Applications*, ch. 11, supports one durable accounting authority with derived UI views; [NAV-05 — MECE categories](../../../heuristics-canon-v0.26.2/lexicons/interaction-ux.md#nav-05), *Designing Interfaces, 3rd ed.*, supports one primary Usage & billing home. These are architecture/UX mechanisms, not vendor or tax advice.

Official implementation references: [Stripe Checkout](https://docs.stripe.com/payments/checkout), [customer portal](https://docs.stripe.com/customer-management), [webhook signatures](https://docs.stripe.com/webhooks/signature).
