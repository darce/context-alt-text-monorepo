# APP-1: payment and API-key build/buy reassessment

> **Current APP-1 recommendation (2026-09-19):** [launch decision and source-book grounding](app-portal-launch-recommendation-2026-09-19.md) recommends Clerk identity, retained local API-key management and Polar Starter. It supersedes open-ended vendor selection and keys-only/later-billing scope for APP-1. The analysis below is retained as dated prior art; it is not evidence of implementation.

Date: 2026-09-19. Status: proposed; supersedes the earlier APP-1 vendor ranking, not its security or zero-charge requirements. [Plan 0001](../../plans/0001-app-altcontext-beta-clerk-polar-task-plan.md).

## Recommendation and what changed

Keep the controlled free self-service beta, with paid conversion implemented and sandbox-tested before admission. Buy Clerk identity and hosted payment checkout. **Keep Polar Starter as the provisional implementation candidate, but promote Stripe Managed Payments and Paddle to real alternatives before freezing S1.** There is no evidence yet that switching saves delivery time, and no completed Polar integration to protect. Free beta changes the optimization target to remaining engineering/support effort and time to useful observations; transaction fees begin to matter after conversion.

**Retain local API-key authority provisionally, while giving Clerk managed keys a bounded challenge before S2.** Its current free allowance removes price as a persuasive reason to reject it. The decisive questions are how much custom rotation/recovery code remains, verification availability, secret custody, and existing-key compatibility. Do not defend local keys merely because the previous plan chose them. The local repository exists; the customer-safe panel and rotation transaction do not.

No new answer to the optional changed-parameters question was received while preparing this revision. Known changes are free beta, complete self-service flows, and a nearly completed paid path. Working priority is fastest learning with low maintenance. Seller country, existing approved accounts, customer geography, actual prices/volumes and acceptable auth outages remain unknown. Toronto timezone does not establish seller jurisdiction.

## Prior art retrieved through semantic embeddings

Fresh `find_related_prior_work` calls returned `embeddings_mode=verified`, model `gte-base-en-v1.5`, `ok_with_results`:

| Retrieval | Relevant result | How used |
| --- | --- | --- |
| Broad payment/key build-buy anchor, task APP-1 excluded | `INV-NEXTVER-01` decision #2023, similarity 0.5721 | Prior Polar preference: MoR reduces founder tax work; developer experience/open-source fit; provider adapter |
| Narrowed anchor restricted to E16-7, INV-NEXTVER-01 and July consolidation | `E16-7` decision #11726, similarity 0.5023 | Prior local keys + Clerk identity + later Polar; inspect the actual September assessment |
| Same narrowed query | E16-7 findings #14478, #14468, #14475 | RLS/tenant boundary, rotation idempotency and ambiguous old-key selection are real remaining work |

Semantic similarity is retrieval evidence, not authority. Unrelated PaddleDetection model findings in the broad result were discarded. Handoff text lookup corroborated #2023/#11726 and #11754, which records a **docs-only** E16-7 merge. The [previous evidence inventory](app-portal-prior-art-and-vendors-2026-09-19.md) collects GTM plans, roadmaps, epics and the 35 deferred findings; this revision does not resolve those findings.

The graph project `Users-daniel-Development-context-alt-text-monorepo` was already indexed. A fresh `search_graph` and `get_code_snippet(SqlAlchemyApiKeyRepository)` confirm local hashed lookup, expiry/revocation checks, tenant listing and revoke-by-ID. Tenant-safe mutation and rotation still need work. This is an incremental build comparison, not greenfield build versus finished vendor. Source baseline remains `213fad181474e5739a3b4859536f28792638cdeb`.

## Which provider was meant by Linear?

Likely **Link**, but the remembered name is unconfirmed. [Link](https://stripe.com/payments/link) is Stripe's checkout wallet, not a separate merchant-of-record competitor. [xAI's privacy addendum](https://x.ai/legal/europe-privacy-policy-addendum) lists Stripe among payment processors; this does not establish which Stripe billing product every Grok channel uses. [Linear's own billing documentation](https://linear.app/docs/ai-credits) says its AI-credit top-ups use Stripe. Neither company's choice establishes AltContext's best tax/operations model. Lemon Squeezy is another plausible remembered name and is included below.

## Refreshed payment shortlist

Public rates checked today; no account-specific quote or live merchant approval. Payment processing, subscription billing and merchant-of-record responsibility are separate buying decisions. A free application beta need not create a payment-provider subscription at all.

| Option | Current offer | Consequence for this beta and paid transition |
| --- | --- | --- |
| **Polar Starter** | MoR; no monthly platform fee; 5% + US$0.50, +1.5% non-US cards. Pro: US$20/month, 3.8% + US$0.40. Payout and dispute fees apply. [Pricing](https://polar.sh/resources/pricing) | Provisional candidate for one paid tier. No paid plan during free beta. Open-source code alone is not an exit from its financial service |
| **Stripe Managed Payments** | MoR; +3.5% on top of Payments, with optional Billing charged separately; no setup fee/monthly minimum. [Pricing](https://stripe.com/managed-payments) | Serious challenger, especially with an approved Stripe account or materially easier integration. Do not exclude using the old preview argument |
| **Stripe direct + Billing** | US domestic card example: 2.9% + US$0.30 Payments plus 0.7% Billing; seller retains merchant duties. Tax tooling is a separate purchase/configuration. [Payments](https://stripe.com/pricing), [Billing/portal](https://support.stripe.com/questions/billing-customer-portal?locale=en-GB) | Choose if seller is deliberately prepared to own the applicable tax/compliance workflow or restrict initial paid markets accordingly. Free beta alone does not establish this |
| **Paddle** | MoR; advertised all-inclusive 5% + US$0.50 per checkout, no monthly fee, tax and recovery included. [Pricing](https://www.paddle.com/pricing) | Equal-finalist status for a broad international launch; compare actual approval, payout and checkout fit instead of automatically ranking behind Polar |
| **Dodo Payments** | MoR; US cards 4% + US$0.40, subscriptions +0.5%, non-US payments +1.5%. US$5 fee for payouts below US$1,000; US$1/refund, US$30/dispute; recovery can add 5% of recovered revenue. [Pricing](https://dodopayments.com/pricing) | Credible lower headline fee, but small-payout/recovery costs can erase savings. Advance if account/payout or integration evidence beats finalists |
| **Lemon Squeezy** | MoR; 5% + US$0.50 base, +0.5% subscription, +1.5% international; payout extras. [Fees](https://docs.lemonsqueezy.com/help/getting-started/fees) | Lower priority for a fresh integration: team describes its move toward Stripe Managed Payments. [Company update](https://www.lemonsqueezy.com/blog/2026-update) gives no shutdown deadline |
| **Clerk Billing + Stripe** | Clerk subscription UI/lifecycle; 0.7% billing fee plus Stripe processing. [Product](https://clerk.com/billing) | Attractive integration hypothesis, but not our global MoR replacement. Clerk documents no MoR service, no current tax/VAT support, USD-only billing, and subscriptions not synced into Stripe Billing. Refunds happen in Stripe. [Contract/limitations](https://clerk.com/docs/guides/billing/overview) |

Stripe Managed Payments has seller/account/product eligibility review, supports CA and US sellers among other locations, and excludes professional services. Confirm that the sold offer is automated software, with customer curation rather than a bundled human service. Account eligibility is not established by a supported-country list. [Eligibility](https://docs.stripe.com/payments/managed-payments/eligibility)

Dodo's English page failed the browser extractor; an unauthenticated curl fetch of the official English HTML succeeded and was parsed to readable pricing text. That page is the source above, superseding the earlier assessment's inability to price Dodo. No promotional credits or negotiated rates are assumed. Clerk's marketing comparison contains older competitor prices; use each vendor's own current pricing page instead.

### Cost sensitivity, not false precision

Illustration only: 20 monthly subscriptions at **US$19**, US domestic cards, US Stripe price schedule, no sales tax, FX, refunds, recovery, payouts or optional products. The seller may not qualify for this schedule. Calculations retain fractional cents; actual rounding differs. MoR fees may apply to tax-inclusive totals.

| Recurring stack | Formula per payment | Per payment | 20 payments/month |
| --- | --- | ---: | ---: |
| Stripe direct + Billing | 3.6% + $0.30 | $0.984 | $19.68 |
| Clerk Billing + Stripe | 3.6% + $0.30 | $0.984 | $19.68 |
| Dodo subscription | 4.5% + $0.40 | $1.255 | $25.10 |
| Polar Starter | 5% + $0.50 | $1.450 | $29.00 |
| Paddle headline | 5% + $0.50 | $1.450 | $29.00 |
| Lemon Squeezy subscription | 5.5% + $0.50 | $1.545 | $30.90 |
| Stripe Managed Payments + Billing | 7.1% + $0.30 | $1.649 | $32.98 |

At this volume, Stripe direct saves $9.32/month versus Polar before tax-operation costs; Managed Payments costs $3.98 more; Dodo saves $3.90 before its small-payout fee. These differences cannot justify days of extra work. No-charge beta has zero payment transactions; it still incurs hosting/compute and possibly identity costs. Use `total cost = remaining build hours * chosen hourly value + maintenance/support + fixed fees + variable fees + migration/recovery exposure`. Do not invent time estimates before a spike.

Re-evaluate at first paid cohort and material volume/geography changes. Polar's published optional plan can reduce fees later; use actual ticket size and count for break-even, not a fixed revenue slogan. Prices $19/$49 remain historical hypotheses, not approved offers.

## Clerk: identity, key management and API management are different scopes

Continue buying human identity. Clerk managed API keys now include user/organization ownership, scopes/claims, expiry and prebuilt management UI. The first 1,000 creations and 100,000 verifications per month are free; overages are $0.001/create and $0.00001/verify, requiring Pro beyond Hobby limits. UI hiding does not disable the Frontend API; server-issued claims/scopes must be enforced if issuance is restricted. [API-key guide](https://clerk.com/docs/guides/development/machine-auth/api-keys)

Illustrative 20 tenants x 200 jobs is 4,000 successful jobs, **not** 4,000 verifications: connection tests, polling, retries and rejected calls also count. At one million verifications, usage overage alone is $9, plus the required plan. Price is unlikely to decide the first cohort. [Identity plans](https://clerk.com/pricing) must be checked against required security capabilities, not just user count.

| Strategy | Work removed | Work still owned / material tradeoff |
| --- | --- | --- |
| Clerk identity + existing local keys | Login, recovery and session UI; reuses current API credential path | Tenant-bound panel, rotation, idempotency, reset protection and restore; no added vendor verification hop |
| Clerk identity + Clerk managed keys | Key generation/storage and standard management UI, vendor revocation APIs | Local tenant authorization, grants, usage/cost caps, custom overlap policy, migration, outages and audit integration remain |
| Clerk identity + dedicated API-key vendor such as Unkey | Specialized key/rate-limit primitives | Another provider and integration; rate limits do not replace successful-job accounting or compute reservations. [Unkey verification migration](https://www.unkey.com/docs/api-reference/v1/migration/keys), [rate limits](https://www.unkey.com/docs/api-reference/v2/ratelimit/set-ratelimit-override) |

Unkey's current [pricing page](https://www.unkey.com/pricing) separates Deploy from API management; the retrieved default showed Deploy pricing. Do not present its active-key deployment fee as a verified standalone API-management quote. It is a reserve candidate if Clerk fails on capability, not an extra platform to build now.

Critical Clerk evidence:

- `verify()` wraps `POST /api_keys/verify`, so the documented path adds a network dependency. Opaque keys do not inherit offline JWT verification. A cache trades availability against revocation freshness; it cannot promise both arbitrary offline use and immediate vendor revocation. [Verification reference](https://clerk.com/docs/reference/backend/api-keys/verify)
- Expiry can be updated, so overlap rotation is plausible; do not claim Clerk lacks expiry shortening. Creating a replacement and updating the predecessor are separate calls, with no atomic two-key operation established here. Our coordinator must recover unknown outcomes and prevent concurrent excess keys. [Update reference](https://clerk.com/docs/reference/backend/api-keys/update)
- The guide says a secret is available once; the reference exposes `getSecret()` / `GET /api_keys/{id}/secret`. These conflict. Do not claim vendor storage is hash-only or that backend compromise cannot retrieve secrets. Resolve against the pinned SDK/live development instance before accepting custody semantics. [Secret reference](https://clerk.com/docs/reference/backend/api-keys/get-secret)
- Import of existing local hashes/raw credentials was not established. Budget an explicit remint/installation step unless proven otherwise; no silent assumption of key portability. A temporary migration verifier must use explicit credential classification and removal criteria, never fallback to local acceptance after a vendor rejection.

The prior plan's seven-day overlap, strict vendor-outage independence and one-time-only secret custody are **design choices inherited from earlier scope**, not newly confirmed beta necessities. Validate them in gate G0 below. If we accept vendor-dependent API availability, vendor-held retrievable secrets and a simpler create-replace-revoke flow, Clerk becomes a stronger buy. If we retain current contracts, local keys remain my recommendation: Clerk does not remove their hardest policy work. Keep one authority; copying Clerk keys into an independently editable local verifier creates a revocation-sync problem.

## Canon-grounded decision pipeline

Canon checkout SHA `aa18707a999affeab4357c9a9d15ae8b502c459f`. These are applied mechanisms and explicit counter-cases, not vendor endorsements.

| Gate | Required decision/evidence | Canon grounding and falsifier |
| --- | --- | --- |
| **G0 - requirements before brand** | Record seller/currency, existing approvals, expected geography/volume, tax-operations owner, key outage tolerance, exact rotation/secret-custody policy. Label assumptions separately from user requirements | [Contract before components](../../../../heuristics-canon-research/reasoning/contract-before-components.md), principle 1. If changing a design preference removes most custom code, reopen buy instead of preserving it by inertia |
| **G1 - eliminate mismatches** | Payment: product/account eligibility and desired MoR responsibility. Keys: tenant binding, issuance controls, revocation, custody and migration. Unknown is pending, not failed or passed | [Principles 11/14](../../../../heuristics-canon-research/PRINCIPLES.md), [SECD-02](../../../../heuristics-canon-research/lexicons/security.md#secd-02). Vendor feature counts cannot compensate for an unmet security boundary |
| **G2 - cheapest decisive experiments** | Proposed total budget: two engineer-days across focused spikes, not two days per vendor. Test Polar and the strongest eligible challenger; test Clerk keys against local remaining-work estimate. No production implementation in this document revision | [Lean UX ch-10/12](../../../../heuristics-canon-research/distilled/business/lean-ux.md), [PROD-03](../../../../heuristics-canon-research/lexicons/business-marketing.md#prod-03), [CARD-06](../../../../heuristics-canon-research/reasoning/evidence-before-commitment.md). Stop when decisive evidence exists; do not build seven integrations |
| **G3 - price remaining work** | Compare observed working journey, remaining custom policy code, failures, founder support burden and 90-day total cost. Use fee table only as sensitivity. Vendor fit can outweigh a few dollars/month | [Lean UX ch-3](../../../../heuristics-canon-research/distilled/business/lean-ux.md), principles 4/15. If a buy path demonstrably saves a day while meeting accepted contracts, prefer it over the incumbent proposal |
| **G4 - choose one and make exit concrete** | Record selection and rejected counter-case; update ADR-014, key contract, S1/S2/S5 and evals together. Export tenant/provider mappings; document payment reauthorization and key remint. Implement one provider | [Modern Software Engineering ch-11/12](../../../../heuristics-canon-research/distilled/engineering/modern-software-engineering.md), [REF-15](../../../../heuristics-canon-research/lexicons/engineering.md#ref-15), [CARD-16](../../../../heuristics-canon-research/reasoning/second-exit-hostile-landlord.md). An adapter without a workable migration is insufficient; multiple live adapters now would add speculative work |
| **G5 - test conversion and learn** | No-card beta, capped usage, real signup/key/plugin flow; sandbox paid lifecycle complete, live disabled. Observe activation/support and later explicit paid conversion | [Lean UX ch-12](../../../../heuristics-canon-research/distilled/business/lean-ux.md), [reversible commitments](../../../../heuristics-canon-research/reasoning/reversible-commitments.md), principles 3/13/19. Free usage is not proof of willingness to pay |

G2 payment receipt: same app-owned tenant goes through checkout, signed webhook, authoritative active state, cancellation, renewal failure/recovery and refund handling; duplicate/reordered/missed events converge; portal cannot cross tenants. Record wall-clock engineering effort, gaps and payout/eligibility questions. Use test environments and fixtures, not real charges.

G2 key receipt: two tenants create/use/rotate/revoke; direct Frontend API issuance cannot bypass admission; existing WordPress header works; wrong-tenant IDs fail; concurrent rotation and lost responses recover; measure verification latency/call count, simulate vendor timeout, and test the secret retrieval contradiction. Compare minimal local work with vendor work under the **same accepted** contracts. [Release It!](../../../../heuristics-canon-research/distilled/engineering/release-it.md) and [RES-13](../../../../heuristics-canon-research/lexicons/engineering.md#res-13) make this a failure-containment experiment, not a happy-path demo.

Selection rule: Polar remains the default if contracts/approval pass and there is no measured delivery advantage elsewhere. Choose Stripe Managed Payments if eligible and its integration/account advantage outweighs its small early fee premium. Choose Paddle if international economics or approval/support evidence wins. Choose direct Stripe only with an explicit merchant-operations plan. Clerk keys win only with accepted custody/outage/migration behavior and lower remaining work; otherwise extend local keys. Do not let the two-day investigation limit waive a failed gate.

This reassessment is a reviewable draft. No vendor account was created, sandbox integration implemented, security policy relaxed, or payment enabled.
