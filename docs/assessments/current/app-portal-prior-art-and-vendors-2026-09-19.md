# APP-1 evidence: customer portal, beta strategy, and vendor refresh

> **Current APP-1 recommendation (2026-09-19):** [launch decision and source-book grounding](app-portal-launch-recommendation-2026-09-19.md) recommends Clerk identity, retained local API-key management and Polar Starter. It supersedes open-ended vendor selection and keys-only/later-billing scope for APP-1. The analysis below is retained as dated prior art; it is not evidence of implementation.

Date: 2026-09-19. Status: research supporting a proposed plan, not a vendor purchase or production readiness claim.
Repository baseline: `213fad181474e5739a3b4859536f28792638cdeb`.
Canon baseline: `aa18707a999affeab4357c9a9d15ae8b502c459f` in `~/Development/heuristics-canon-research`.

**Later same-day reassessment:** [build/buy pipeline](app-portal-build-buy-reassessment-2026-09-19.md) supersedes the vendor ranking below, adds verified Dodo pricing, promotes Stripe Managed Payments/Paddle to finalists, and specifies a Clerk-key challenge. Earlier receipts remain historical evidence.

## Collected prior art and precedence

| Source | Reusable decision or evidence | Treatment in APP-1 |
| --- | --- | --- |
| [Productization launch plan](../../gtm/altcontext-productization-launch-plan.md), AP-3/AP-4/AP-5 | Signup -> key -> plugin -> first caption -> paid conversion; buy identity/billing; own tenant records | Keep journey; pricing and framework suggestions are hypotheses |
| [Accounts/billing decomposition](../../gtm/decomposition-ap3-ap4-ap5-accounts-billing.md) | Signed/deduplicated webhooks, tenant mapping, key panel, bounded usage reads, reconciliation | Reuse contracts; replace unbuilt separate Business API dependency |
| [AP-1/AP-2 decomposition](../../gtm/decomposition-ap1-ap2.md) | Ownership and lifecycle boundaries | Historical design input, not proof those services shipped |
| [SaaS operations roadmap](../../roadmaps/roadmap-saas-operations.md), [E16 epic](../../epics/v0.3.1/saas-foundation-epic.md) | Broad self-service vision; separate `acx_business` tenant/key authority | Conflicts with newer E16-7; propose one existing authority for beta and reconcile docs before implementation |
| [E16-7 assessment](e16-7-keys-and-subscriptions-build-buy-2026-09-16.md), [scope](../../scopes/e16-7-tenant-selfserve-key-panel-scope.md), [plan](../../tasks/16.0/E16-7-tenant-selfserve-key-panel-task-plan.md), [evals](../../scopes/e16-7-tenant-selfserve-key-panel-evals.json) | Clerk identity; local hashed keys; one-time email claim then stable subject; overlap rotation; restore evidence | Strongest key-management input. Documentation landed; implementation is still needed |
| [E15-31 admin API](../../tasks/15.0/E15-31-tenant-admin-api-key-router-task-plan.md), [ADR-012](../../adrs/ADR-012-customer-tenant-management-crm-ready-admin.md), [CRM-1](../../tasks/v0.5.0/CRM-1-customer-tenant-management-task-plan.md) | Operator provisioning and tenant registry; key labels/contact management | Preserve operator contract; avoid duplicate CRM scope |
| [ADR-014](../../adrs/ADR-014-payment-processor-merchant-of-record-selection.md) | Prefer MoR, Polar first, minimal billing adapter | Proposed ADR; refresh facts below before acceptance |
| [July consolidation memo](../../gtm/infra-telemetry-auth-consolidation-memo.md) | Clerk for customers, Tailscale for operators; PostHog/Sentry separate; recognition capacity is the constraint | Preserve responsibility split; old host capacity/prices are not current measurements |
| [Managed-default roadmap](../../roadmaps/local-ai-managed-default-roadmap-2026-07-31.md) | Charge for workflow/governance; hosted compute is an allowance/cost component; human curation belongs to customer | Overrides older blanket network-effect claims and remote-only permanence; no local-worker build in APP-1 |
| [Unit economics forecast](../../gtm/inference-cost-and-unit-economics-forecast.md) | GPU utilization/cold-start cost matters | Historical forecast, not a beta cost guarantee or basis for uncapped free access |
| [AltText.ai comparison](../../gtm/competitive-analysis-alttext-ai-2026-07-14.md), [Google Photos comparison](altcontext-vs-google-photos-assessment-2026-09-18.md) | Publishing workflow, installation, reviewable text, portability | Keep beta focused on WordPress activation and accepted output, not generic image storage |
| [Production workflow epic](../../epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md), [public MVP UX roadmap](../../roadmaps/public-mvp-ux-polish-roadmap-2026-07-04.md) | User workflow dependencies beyond account plumbing | A working account is insufficient if the plugin cannot deliver a real accepted caption |
| [Concierge runbook](../../gtm/runbooks/concierge-sale.md) | Fast manual sale/provisioning path | Recovery/fallback and customer recruitment; do not use manual provisioning as the normal beta journey |
| Marketing repo `backend/src/services/api-keys.ts::createApiKey` | Hash-and-store, return raw key at creation | Graph-inspected prior art. Reuse pattern; do not migrate its Node service or create a second writable key store |

## Semantic and handoff retrieval receipt

Used `find_related_prior_work` with two anchors: (a) app/Clerk/tenant keys/rotation/billing and (b) merchant-of-record/Polar/Paddle/Stripe/pricing. The provider returned `embeddings_mode=verified`, model `gte-base-en-v1.5`, and `ok_with_results`. Broad similarity also returned unrelated DNS/deployment items; those were not promoted into requirements.

| Task / decision | Evidence recovered | Consequence |
| --- | --- | --- |
| `MAINT-demo-key-remint-20260915` #11708 | Prior build/buy and unbuilt portal diagnosis | Reuse local credential authority |
| Same task #11709 | Actual Sept 15 answers: Clerk, pre-existing single-owner tenant, keys-only, immediate revoke rotation | Historical intake, superseded in scope by this broader ask; do not silently present it as approval of signup/billing |
| `E16-7` #11726 and Sept 16 assessment | Later overlap and stable subject binding | Prefer seven-day maximum overlap; emergency revoke remains immediate |
| `INV-NEXTVER-01` #2023 | MoR/Polar with `BillingProvider` seam | Refresh commercial facts and migration claims |
| `MAINT-gtm-infra-telemetry-consolidation-20260713` #2134 | Customer auth and infra responsibilities | No new operator IdP or analytics warehouse |
| `E16-7` #11754 | Explicit docs-only merge at `b0a477b7a22d47b669a0caa837fc4fe7a0d801c3` | Closed planning task is not shipped portal code |

`load_session(E16-7, read_profile=hot_summary)` showed no open findings. A separate deferred-finding query returned **35 deferred: 8 high, 25 medium, 2 low**. They remain canonical in handoff, not copied as a second findings ledger. Review S0 must disposition their relevance, especially `E167FI-H-04` (CSRF definition), `E167FI-H-05` (HTML mutation transport), `E167FI-H-06` (rotation repository ownership), `E167FI-H-02` / `E167FI-M-09` (rotation restore), and `E167FI-M-07` (reset privileges). No findings were resolved by this research.

Artifact search for Polar/Clerk/GTM under `INV-NEXTVER-01` returned `scope_excluded_all` (0 scoped chunks, 950 corpus chunks). Thus retrieval evidence is semantic handoff decisions plus source documents; it is not a claim that every document was embedded or the corpus was exhaustively collected.

## Code evidence

Graph project: `Users-daniel-Development-context-alt-text-monorepo`; already indexed. Used `search_graph`, `get_code_snippet`, and coverage checks. Checked key-service/repository/admin paths had `metadata_match`; coverage is best effort. HTTP/service scope gaps included excluded `__pycache__` directories. Narrow negative results are qualified by the app mount inspection.

| Existing surface | Observed behavior | Planned use/change |
| --- | --- | --- |
| `apps/prototype-description-service/api/main.py::create_app` | Mounts recognition, roster, scene/GPU, demo, and gated admin; inspected function has no customer portal/billing mount | Add independently gated portal/webhook mounts; preserve API availability when portal disabled |
| `recognition/application/services/api_key_admin_service.py::mint_api_key` | `token_urlsafe(32)`, configured digest, caller-owned transaction | Reuse with explicit SHA-256 policy pin, audited creation and rotation |
| `recognition/infrastructure/repositories/api_key_repository.py::SqlAlchemyApiKeyRepository` | Active/expired/revoked classification, tenant list, revoke and last use | Tenant-bound access, bounded history, atomic concurrency control; existing revoke-by-id is not sufficient portal authorization |
| `recognition/interface_adapters/http/routers/admin.py::revoke_key_atomic` | Revoke + audit + commit; repeated admin revoke returns success without duplicate audit | Extract transactional service, preserve adapter-specific behavior |
| `recognition/interface_adapters/http/deps/demo_quota.py` | Demo-specific bounded quota machinery | Reuse concurrency pattern, not demo semantics as paid accounting |
| Marketing repo `backend/src/services/api-keys.ts::createApiKey` | Writes hash/prefix/scope; returns raw key | Prior art only |

All `recognition/` paths above are relative to `apps/prototype-description-service/`. Portal and payment implementation below is proposed, not inferred from document titles.

## Payment vendors: primary-source refresh

Verified 2026-09-19. Fees are public list prices, not an account quote. Country, currency, tax-inclusive amount, payout method, dispute/refund mix and seller approval can change the effective rate. Confirm the actual selling entity; Toronto workspace timezone is not proof of incorporation or payout eligibility.

| Vendor | Current offering and price | APP-1 assessment |
| --- | --- | --- |
| **Polar** | MoR; Starter $0/month, 5% + $0.50; +1.5% non-US cards. Optional Pro $20/month at 3.8% + $0.40; Growth $100 at 3.6% + $0.35; Scale $400 at 3.4% + $0.30. Early Member is restricted to organizations created before May 27, 2026: 4% + $0.40 plus 0.5% subscriptions. [Pricing](https://polar.sh/resources/pricing) | Preferred, conditional on approval and sandbox proof. Begin Starter, not a paid rate-buydown plan during free beta |
| **Paddle** | MoR, published 5% + $0.50 per checkout, tax/compliance and revenue recovery included; under-$10 products or invoicing need a custom discussion. [Pricing](https://www.paddle.com/pricing) | Strong fallback, especially non-US-heavy sales. Get account acceptance and test the same lifecycle before switching |
| **Lemon Squeezy** | MoR, 5% + $0.50 base, +0.5% subscription, +1.5% international and +1.5% PayPal; payout extras may apply. [Pricing](https://www.lemonsqueezy.com/pricing), [fees](https://docs.lemonsqueezy.com/help/getting-started/fees) | Viable product, lower preference because team is building Stripe Managed Payments; do not claim a shutdown or mandatory migration |
| **Stripe Managed Payments** | Stripe MoR, **3.5% in addition to Payments fees**; Billing and optional products separate. Checkout/Payment Links and subscriptions supported. [Product/pricing](https://stripe.com/managed-payments), [integration](https://docs.stripe.com/payments/managed-payments) | Real fallback now, not dismissed using July's preview label. Eligibility review still applies; docs list CA and US. Fully automated digital products qualify; professional-service/consulting offers do not. [Eligibility](https://docs.stripe.com/payments/managed-payments/eligibility) |
| **Stripe direct** | Payments, Billing and Tax as separate services; Canadian Payments list starts at 2.9% + CA$0.30 for domestic cards. Your business is merchant; optional tax tooling is not automatically the MoR service. [Canada pricing](https://stripe.com/en-ca/pricing), [MoR comparison](https://docs.stripe.com/payments/managed-payments) | More commercial control but retains merchant responsibilities. Not the low-operations default for this launch |

The comparison revisits all five ADR-014 options. It is not a market-wide ranking. Dodo initially failed the browser fetch; the later reassessment retrieved and parsed its official English pricing page and now includes it.

**Corrections to ADR-014:** replace vague "Stripe-tier" SMP price; verify account access rather than assume old preview exclusion; remove advice to create an organization now to capture an already-past Polar grandfather date. Lemon Squeezy's [January update](https://www.lemonsqueezy.com/blog/2026-update) describes the team's Stripe direction and slower updates, not a published shutdown deadline. A MoR does not remove every seller cost: Polar documents non-refundable original processing fees, a $15 dispute charge and payout fees. Open-source software does not reproduce a vendor's merchant agreements, compliance operation or payouts when self-hosted. An adapter reduces code changes; it does not guarantee payment-method or subscription portability. [Polar fees](https://polar.sh/docs/merchant-of-record/fees)

Illustrative transaction arithmetic, not a forecast: on a USD $19 subscription before tax/payouts, Polar Starter or Paddle's headline rate is $1.45; Polar with the non-US card surcharge is $1.735; Lemon Squeezy subscription is $1.545 domestic or $1.83 international before any PayPal surcharge. On $49 the corresponding amounts are $2.95, $3.685, $3.195 and $3.93. Actual fees may be charged on the tax-inclusive total. Do not compare CA$ fixed fees against US$ fixed fees without currency conversion.

For Starter -> Polar Pro, the simple monthly savings condition is `0.012 * eligible_volume + 0.10 * transactions > 20`, excluding extras that do not change. At uniform $19 sales it takes 61 transactions; at $49, 30. These are derived examples, not the vendor's general breakeven estimate. During a no-charge beta there is no transaction-fee saving to buy.

## Clerk and Polar integration facts that change the plan

Clerk offers user/org API keys, scopes, expiration, create/list/revoke UI and verification APIs. The public key feature price is $0.001/creation after 1,000/month and $0.00001/verification after 100,000/month; Hobby stops at its included limits. This is a credible alternative, not a missing vendor feature. APP-1 provisionally keeps local keys because WordPress already uses them and the required overlap/restore/outage behavior is local. A vendor-key switch needs a measured verification-dependency and migration experiment. Hide/disable the irrelevant Clerk key UI; hiding alone is not authorization. [Clerk API keys](https://clerk.com/docs/guides/development/machine-auth/api-keys)

Clerk Hobby publishes 50,000 monthly retained users, prebuilt auth UI and custom domain support; Pro adds capabilities including MFA and configurable session lifetime. Start with required features rather than buying branding removal. If the threat review requires a Pro capability, count its subscription as a real launch cost. [Clerk pricing](https://clerk.com/pricing)

Do not assume `email` and `email_verified` are default session claims. Confirm a verified primary-email projection or configured custom claims during the spike. Current organization claims use a compact `o` object; the beta proposal avoids organization switching until required. Clerk's session cookie is managed by its browser SDK; do not impose an incompatible HttpOnly rule on the SDK-owned cookie. App-owned cookies remain Secure/HttpOnly/SameSite as appropriate, with server-side JWT and CSRF verification. [Session claims](https://clerk.com/docs/guides/sessions/session-tokens), [session architecture](https://clerk.com/docs/guides/how-clerk-works/overview)

Polar provides a [sandbox](https://polar.sh/docs/integrate/sandbox) and hosted [customer portal](https://polar.sh/docs/features/customer-portal/introduction). Its [customer state](https://polar.sh/docs/integrate/customer-state) combines active subscriptions/benefits/meters and supports external customer IDs plus `customer.state_changed`. Use it for reconciliation; do not call it on every recognition request.

Webhook details need a fresh fixture: Polar changed signing-secret conventions on **September 8, 2026**; current SDK guidance distinguishes old and new secrets. Delivery docs recommend responding within two seconds and describe retry/endpoint-disable behavior. Pin and test the selected SDK against the actual account secret, persist before acknowledgement, and alert on stopped delivery. [Webhook delivery](https://polar.sh/docs/integrate/webhooks/delivery)

## Canon reasoning: sources to decisions to falsifiers

Local references below resolve from this worktree into the canon checkout. IDs were read from current lexicons; chapter sections were read in `distilled/`, rather than treating an ID as a substitute for the source mechanism.

| Decision | Distillation, lexicon, card and principle | Counter-case / verification |
| --- | --- | --- |
| Controlled free self-service beta, then explicit paid conversion | [Lean UX ch-3/10/12](../../../../heuristics-canon-research/distilled/business/lean-ux.md), [Rumelt ch-5/8](../../../../heuristics-canon-research/distilled/business/good-strategy-bad-strategy.md); PROD-01/03, STRAT-22; [evidence before commitment](../../../../heuristics-canon-research/reasoning/evidence-before-commitment.md) CARD-06; principles 2, 13, 19 | Free usage cannot validate willingness to pay. Measure unassisted activation and repeat use now; measure actual opt-in paid conversion later. Expand recruitment if cohort selection hides problems |
| One tenant/key authority, local entitlement projection | [DDIA ch-7/11/12](../../../../heuristics-canon-research/distilled/engineering/designing-data-intensive-applications.md); DATA-13/14, DOM-06; [contract before components](../../../../heuristics-canon-research/reasoning/contract-before-components.md) CARD-01; principles 1, 12 | Colocation increases reset blast radius. Prove restricted roles and restore; do not claim separation from an architecture diagram |
| Rotation is overlap plus a distinct emergency revoke | DDIA ch-7/8, [Anderson](../../../../heuristics-canon-research/distilled/security/anderson-security-engineering.md); WEB-08, SECD-02; [perceived/enforced boundaries](../../../../heuristics-canon-research/reasoning/perceived-enforced-boundaries.md) CARD-12; principles 3, 10, 14 | Compromised credentials should not get grace; make immediate revoke obvious, accessible and independently tested |
| Billing and identity outages do not halt valid local API calls | [Release It! ch-5](../../../../heuristics-canon-research/distilled/engineering/release-it.md); RES-13, DATA-13; principles 3, 11, 16 | Cached access has a financial/security cost; bound its age, exclude explicit revocation, test at the boundary |
| Polar first, exportable mapping and thin provider adapter | [Modern Software Engineering](../../../../heuristics-canon-research/distilled/engineering/modern-software-engineering.md); REF-15, BOOT-07; [second exit](../../../../heuristics-canon-research/reasoning/second-exit-hostile-landlord.md) CARD-16; principle 8 | Adapter is not a migration plan. Rehearse exporting mappings and document customer reauthorization risk |

Authoritative row homes: [business lexicon](../../../../heuristics-canon-research/lexicons/business-marketing.md), [engineering lexicon](../../../../heuristics-canon-research/lexicons/engineering.md), [security lexicon](../../../../heuristics-canon-research/lexicons/security.md), [principles](../../../../heuristics-canon-research/PRINCIPLES.md).

## Recommendation and limits

Choose the first option's **functional scope**, delivered as a **controlled free beta**. Keep normal onboarding self-service while recruitment is curated. Start with a proposed 10-20 WordPress users across at least three use contexts, observe five first-run sessions, then admit the next cohort after fixing the largest drop-off. Public signup multiplies abuse/support/inference spend before the failure modes are known. Manual provisioning saves initial code but hides the account/key/upgrade friction this beta must measure.

The invitation is admission control, not a requirement for an operator to create each tenant or paste its key. Use no card and no automatically renewing paid trial. Beta allowance, end date and recovery actions must be visible. Test checkout in a clearly labelled isolated sandbox; do not expose production keys or billing sessions there. Paid readiness means the lifecycle code already works, not an unimplemented Upgrade button. Proposed numeric gates and budget limits are in the plan and remain subject to review.
