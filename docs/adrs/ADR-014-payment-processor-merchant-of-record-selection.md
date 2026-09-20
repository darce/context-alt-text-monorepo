# ADR-014: Payment processor and merchant-of-record selection

- **Status:** Proposed; recommendation updated 2026-09-19, not accepted or implemented.
- **Original date:** 2026-07-12.
- **Decider:** Founder (Daniel).
- **Context:** INV-NEXTVER-01; current implementation proposal APP-1.
- **Evidence:** [vendor comparison](../assessments/current/app-portal-build-buy-reassessment-2026-09-19.md), [launch recommendation with source-book corpus](../assessments/current/app-portal-launch-recommendation-2026-09-19.md).
- **Execution:** [Plan 0001](../plans/0001-app-altcontext-beta-clerk-polar-task-plan.md); [SaaS roadmap](../roadmaps/roadmap-saas-operations.md).

## Context

The immediate objective is a bounded free self-service beta that exposes signup, key installation, usage and recovery behavior. Paid conversion must be implemented and sandbox-tested before beta admission, with live checkout disabled until the paid release gate. The founder's attention and compute exposure are more consequential initially than small processing-rate differences.

The July decision favored a merchant of record (MoR) for a solo global launch. That remains a useful operating assumption, not proof of the actual seller's jurisdiction or tax obligations. Confirm seller/product/payout eligibility. A MoR handles the contracted transaction tax/payment responsibilities; it does not eliminate seller accounting, all fees, product obligations or incident work.

The July decision also overstated Polar's self-hosting exit, Stripe Managed Payments' exclusion and payment portability. This revision removes those claims. The commercial facts and counter-cases are in the linked assessment, refreshed from primary sources on 2026-09-19.

## Recommended decision

**Use Polar Starter as the first and only billing implementation for APP-1. Buy hosted checkout and customer subscription management. Keep a small provider adapter and local entitlement projection.**

This is a reasoned choice under uncertainty, not a measured assertion of best developer experience. Polar's hosted flow, sandbox and customer-state interface fit one subscription offer and the existing planned lifecycle. There is no demonstrated integration advantage that justifies another mandatory vendor bake-off. Prove this path early; reopen only on concrete failure or meaningful new evidence.

- Clerk owns human identity; AltContext retains local API-key issuance/verification and tenant authorization.
- Polar owns subscription/payment facts; AltContext derives access according to explicit entitlement policy. The processor is not merely a notifier whose financial truth we edit locally.
- Use the existing service/customer-state authority for beta, with restricted reset roles and tested restore. No second writable credential database.
- A local beta grant creates no paid subscription, payment instrument requirement, charge or arrears.
- Start with one monthly offer and allowance; defer overages, annual pricing, multiple tiers and bespoke billing UI.
- Verify signatures, persist/dedupe webhooks before acknowledgement, reconcile missed/reordered events and keep billing network calls off the recognition path.

## Alternatives and counter-cases

| Option | Decision for this launch | When it becomes preferable |
| --- | --- | --- |
| Polar Starter | Recommended implementation | Passes actual eligibility and sandbox lifecycle proof |
| Stripe Managed Payments | Eligible contender; do not exclude by old preview status | Existing eligible Stripe setup or required capability materially reduces remaining work; accepts its actual fee schedule |
| Paddle | Credible MoR alternative | Account approval, coverage, operations or measured international economics favor it |
| Stripe direct + Billing | Defer | Explicit seller-owned tax/compliance operating plan and a concrete business benefit justify it |
| Dodo Payments | Reserve | Approval/integration benefit or total effective cost, including payout/recovery fees, wins |
| Lemon Squeezy | Lower priority for new integration | Specific existing account/capability advantage outweighs its announced Stripe Managed Payments direction; no shutdown is presumed |
| Clerk Billing + Stripe | Defer | Accepted merchant/tax/currency requirements fit its actual limitations; it is not a MoR substitute |

## Cost and exit

Polar Starter currently lists 5% + US$0.50, with a non-US card surcharge and payout/dispute costs. Do not assume the old Early Member rate can be captured now. Use actual transaction size/volume before buying a paid rate reduction. [Polar pricing](https://polar.sh/resources/pricing)

Stripe Managed Payments adds 3.5% to Payments fees; optional Billing is separate. Its early-volume cost difference is insufficient by itself to justify rejecting it. [Stripe pricing](https://stripe.com/managed-payments)

Export tenant/provider/customer/catalog mappings and preserve direct customer contact subject to consent. An adapter limits code coupling; it cannot guarantee moving subscriptions or payment methods. A switch may require provider cooperation and customer reauthorization. Polar's open-source code does not reproduce its merchant agreements or payout operation.

## Execution and falsifiers

1. S0 records actual seller/product/payout eligibility and one offer's required lifecycle. S1 performs the chosen integration proof; the proposed two engineer-day timebox is discovery, not complete billing delivery.
2. If Polar fails a required contract or eligibility check, inspect one matching fallback before production integration. Use the current comparison; do not silently add a second provider.
3. S5 completes checkout, signed inbox, reconciliation, cancellation/payment recovery and hosted portal. S6 proves no-charge beta plus recovery and cost containment. S7 enables explicit paid conversion only after the paid-ready gate.
4. Reassess at the first paid-cohort review and material geography/volume changes. Measure support/engineering burden and effective cost, not vendor affinity.

Canon basis: Lean UX ch-3/10/12 (learning/outcomes), Good Strategy Bad Strategy ch-5/8 (bottleneck/coherence), The 4-Hour Workweek ch-8/10/11 (owner attention and demand), Modern Software Engineering ch-11/12 (small adapters), DDIA ch-7/8/11/12 (transaction/projection correctness). The linked recommendation traces these to the local `distilled/` corpus, lexicons, reasoning cards and principles, including disconfirmers.
