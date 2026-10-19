# APP-1: Standard Stripe direct, Clerk and usage accounting

> **CURRENT DESIGN — confirmed 2026-10-19.** [ADR-014](../../adrs/ADR-014-payment-processor-merchant-of-record-selection.md) owns provider selection and tax responsibility. Design selection is separate from implementation and release evidence.

Use standard Stripe Checkout and the customer portal on AltContext's own Stripe account. Clerk supplies sign-in. AltContext keeps tenant/API-key/usage authority and handles manual tax calculations and seller obligations. Stripe Managed Payments and merchant-of-record arrangements are excluded.

## Accounting UX

Place a compact, read-only tenant balance beside WordPress Describe, separately from the estimate for the selected images. Link it to one account **Usage & billing** area. Show used, reserved, remaining, allowance, period/reset or expiry, and last updated time. Unknown or stale counts must not appear as zero. An optional local site-attempt limit stays in Settings and cannot add account credits.

Use the customer units defined by the accepted offer. Model tokens and GPU spend remain internal cost accounting unless explicit token pricing is approved. Existing portal source exposes allowance fields, but that does not prove the WordPress account-balance integration is complete.

The initial offer is recurring allowance. A purchased top-up needs an explicit quantity, currency/tax, expiry/rollover, refund and credit-priority contract. A verified payment creates at most one audited local grant, with reconciliation. A browser return never increments balance. Auto-refill, if later approved, is opt-in with a threshold and maximum spend.

Use hosted Checkout for payment and the hosted portal for invoices, subscription and payment-method management. Link is optional checkout acceleration; it neither authenticates an AltContext tenant nor changes the seller.

## Canon and original corpus

Canon v0.26.2 [DATA-14 — No dual writes](../../../../heuristics-canon-v0.26.2/lexicons/engineering.md#data-14), *Designing Data-Intensive Applications*, ch. 11: derive account and WordPress displays from one durable accounting authority. The local [DDIA distillate](../../../literature/extracted/refactoring/distilled/designing-data-intensive-applications.md) and original extracted chapter's dual-write race/failure examples support that mechanism.

[NAV-05 — MECE categories](../../../../heuristics-canon-v0.26.2/lexicons/interaction-ux.md#nav-05), *Designing Interfaces, 3rd ed.*: one primary Usage & billing home with contextual links from work. The local [Designing AI Interfaces distillate](../../../literature/extracted/business/distilled/designing-ai-interfaces.md), available Computation/Output material, supports meaningful state and review controls. It does not establish a payment tariff.

[Stripe Billing credits](https://docs.stripe.com/billing/subscriptions/usage-based/billing-credits) apply to supported metered subscription invoice items; they are not a synchronous tenant-admission counter. [Stripe's customer portal](https://docs.stripe.com/customer-management) provides hosted payment/subscription management.

## Remaining acceptance

Confirm the recurring offer, unit/charging policy, manual tax workflow and seller configuration. Prove genuine test-mode checkout, signatures, duplicates/reordering, interruption, return before webhook, refund/cancel and reconciliation. Keep offline schema/worker evidence separate from real-provider/browser proof. Top-up and auto-refill implementation are not claimed complete.

Semantic recall used verified gte-base-en-v1.5 embeddings: APP-1 prior work confirms the small billing-provider boundary and local key/usage authorities. Similarity is a discovery aid, not implementation evidence.
