# ADR-014: Payment Processor & Merchant-of-Record Selection

- **Status:** Proposed
- **Date:** 2026-07-12
- **Deciders:** Founder (Daniel)
- **Context task:** INV-NEXTVER-01
- **Supersedes/Refines:** GTM launch plan §7 (which pre-selected Polar without a merchant-of-record rationale)
- **Related:** [ADR-012](ADR-012-customer-tenant-management-crm-ready-admin.md) (tenant/CRM admin), [ADR-010](ADR-010-agentic-plugin-distribution.md), [ADR-011](ADR-011-retire-on-device-recognition-remote-only.md)

## Context

The GTM plan (`docs/gtm/altcontext-productization-launch-plan.md` §7) names Polar as the payments vendor but never justified **merchant-of-record (MoR) vs. direct processor**, and the choice predates two 2026 market shifts. This ADR reviews the decision with current facts.

Project constraints that drive the decision:

- **Solo founder, global sales (EU + US).** A one-person operation cannot absorb VAT/GST/US-sales-tax registration and remittance across dozens of jurisdictions.
- **Two sales motions:** concierge (DM → payment link → manual `/admin` provision) *now*, and self-serve (Clerk → checkout → webhook → tenant) at Phase 2.
- **Architecture:** the Business API is the single tenant-lifecycle authority; billing notifies via **idempotent webhooks** (§7). The processor is a *notifier*, not the source of truth.
- **Founder thesis:** accessibility-as-architecture, sovereign/self-hostable posture, open-source credibility as distribution.
- **Fastest-dollar rule:** do not gate the first sale on billing machinery `[PROD-03]`.

## Decision

**Adopt a merchant-of-record model, keep Polar for launch, and isolate it behind a thin MoR adapter interface** so the concrete vendor is a swappable implementation detail.

1. **MoR over direct (Stripe-direct rejected).** MoR shifts tax registration/remittance and fraud/chargeback liability to the vendor. For a solo global launch this removes an unbounded compliance-ops burden that direct Stripe (even with Stripe Tax) leaves on us.
2. **Polar for launch.** Best developer DX, clean webhook API that fits "Business API owns lifecycle," open-source (self-host optionality + thesis alignment), and payment links that make the concierge fast-path (AP-7) work with zero webhook build.
3. **Adapter isolation (the risk hedge).** Define a `BillingProvider` seam (checkout-link creation + normalized `subscription.*`/`payment.*` webhook events → tenant lifecycle). Polar is the first implementation. This turns a future switch to Paddle or Stripe Managed Payments into a webhook-mapping change, not a rebuild — directly answering Polar's main weakness (depth/longevity).

## Options considered (2026 facts)

| Option | Model | Effective fee (indie, intl) | Fit / DX | Risk |
|---|---|---|---|---|
| **Polar** | MoR, open-source | New orgs (post-2026-05-27) **5% + 50¢**, +1.5% intl, $15 chargeback; grandfathered 4%+40¢ only if org created earlier; paid plans ($20/$100/$400) buy the rate down | **Best DX**, dev-first webhooks, payment links, self-host option | Thinner subscription/jurisdiction depth; newer co.; longevity unproven |
| **Paddle** | MoR | **5% + 50¢ all-in** (no intl/subscription surcharge) → often cheaper for intl-heavy | Enterprise-grade API/webhooks | Slower onboarding + approval gate; assumes payment domain knowledge |
| **Lemon Squeezy** | MoR | ~5%+50¢, intl subs ~7%+50¢ | Digital-goods features (license keys, storefront) | **Acquired by Stripe; being folded into Stripe Managed Payments — do not build new on it** |
| **Stripe Managed Payments (SMP)** | MoR (new) | Stripe-tier | Stripe DX + MoR combined; 35+ countries | **Public preview Feb 2026, GA "soon"** — too early to launch on, strongest medium-term hedge |
| **Stripe (direct)** | Not MoR | 2.9%+30¢ + Stripe Tax ~0.5% | Best ecosystem/control | **We become merchant → we register & remit tax globally** — rejected for solo launch |

## Consequences

**Positive**
- First dollar unblocked now: Polar **payment link** for concierge (AP-7), no self-serve/webhook dependency.
- Tax/compliance liability offloaded from day one.
- Adapter seam caps switching cost; effective fees are ~parity across MoRs in 2026, so the decision rightly rests on DX + switching cost + thesis fit — all favoring Polar today.

**Negative / watch**
- Polar's 2026-05-27 repricing means the "4%" premise in GTM §7 is **stale**. Action: confirm the Polar org's creation date — if grandfathering (4%+40¢) is still capturable, create the org immediately; otherwise plan on 5%+50¢ parity.
- MoR sets the price *to the buyer* including its fee; keep the rate-floor `[BOOT-04]` in pricing.
- If B2B/agency-tier (ADR-012 CRM) needs invoicing/jurisdiction depth Polar lacks, the adapter allows promoting Paddle or SMP for those plans without abandoning Polar for self-serve.

## Falsifiers

- Polar payout unsupported in the founder's country → forces Paddle/SMP; verify before committing.
- Polar webhook `subscription.*` semantics can't cleanly drive idempotent tenant lifecycle → adapter exposes it early; re-evaluate.
- Effective Polar rate (post-hike + intl surcharge) materially exceeds Paddle's all-in 5%+50¢ at real volume → revisit at MRR review.

## Action items

1. Verify Polar payout support + org creation date (grandfather capture) — **blocking gate before AP-5**.
2. Implement `BillingProvider` adapter (Polar impl) in the Business API; normalize webhook events to tenant lifecycle.
3. Ship AP-7 concierge payment link first (no webhook), decoupled from the self-serve checkout (AP-5).

## Sources

- [Polar — Fees](https://polar.sh/docs/merchant-of-record/fees) · [Polar.sh 2026 pricing review](https://dodopayments.com/blogs/polar-sh-review)
- [Stripe vs Paddle vs Lemon Squeezy vs Polar — MoR decision 2026](https://fintechspecs.com/blog/stripe-vs-paddle-vs-lemon-squeezy-vs-polar-merchant-of-record-b2b-saas/)
- [Lemon Squeezy + Stripe Managed Payments (2026 update)](https://www.lemonsqueezy.com/blog/2026-update)
- [Lemon Squeezy vs Polar vs Paddle MoR comparison 2026](https://www.buildmvpfast.com/blog/lemon-squeezy-vs-polar-paddle-merchant-of-record-2026)
