# SaaS operations roadmap: bounded free beta to paid self-service

> **Status:** Proposed implementation direction, revised 2026-09-19; no APP-1 implementation is claimed.
> **Execution owner:** [APP-1 Plan 0001](../plans/0001-app-altcontext-beta-clerk-polar-task-plan.md).
> **Decision basis:** [launch recommendation and original source-book distillations](../assessments/current/app-portal-launch-recommendation-2026-09-19.md); [current vendor comparison](../assessments/current/app-portal-build-buy-reassessment-2026-09-19.md).
> **Product direction:** [managed-default workflow/governance roadmap](local-ai-managed-default-roadmap-2026-07-31.md).

## Outcome

A qualified WordPress customer signs up, obtains a tenant key, connects the plugin, produces an accepted caption, returns, and can later explicitly purchase continued service. Normal onboarding requires no operator provisioning. Recruitment may be curated; observed sessions and support remain useful learning channels.

Recommend Clerk for human identity, the existing local API-key backend, and Polar Starter for checkout/subscription operations. Build the smallest portal that connects these responsibilities. In-house API-key management is **retained**, not replaced by Clerk machine authentication in this beta. The plan remains subject to review and actual account eligibility/integration evidence.

## Changes from the earlier roadmap

| Earlier direction | Current recommended contract |
| --- | --- |
| New `acx_business` database and Business API before onboarding | Extend the existing service and credential authority; protect customer state against recognition resets and prove restore |
| Port marketing key services into a new authority | Reuse the local Python repository/minter already present; add tenant-safe lifecycle and a thin panel |
| Uncapped implicit free tier until Phase 2 | Enforce per-tenant allowances and global compute admission budgets before the first beta user |
| Billing is a later build | Complete and test the Polar paid lifecycle in sandbox before beta; live activation is a later operational gate |
| WorkOS versus Clerk remains open | Clerk identity is the recommendation; no new operator IdP |
| Framework/dashboard scaffold is the first milestone | Prove signup -> key -> real WordPress result, using a small FastAPI portal with supported Clerk JS |
| Fixed Free/Pro/Business prices and quotas | One monthly offer/allowance; price and currency require an explicit hypothesis and later paid evidence |
| Marketing backend migration and expanded telemetry | Reuse available instrumentation; no CRM migration or analytics warehouse as a beta dependency |

Historical architecture and rate assumptions are retained in Git history and the linked prior-art inventory. Older E16/AP decomposition is a source of cases, not a parallel project to dispatch unchanged.

## Authority and operating boundaries

- Clerk: login, user recovery, sessions; server verifies actual claims and binds stable issuer/subject to local tenant UUID.
- Local service/database: tenant, keys, beta grants, usage/cost admission, authorization and audit. One writable credential authority.
- Polar: payment/subscription facts and hosted billing UI. Local billing state is a verified, reconcilable projection.
- WordPress: installed key and publishing/review workflow. A portal cannot silently replace `wp-config.php`/filter-managed credentials.
- Operator: current Tailscale/admin boundary, budget stop, account recovery and tested restoration.

Colocation is an initial simplicity choice, not independent availability. Restrict reset roles, bound portal/webhook capacity and prove off-host recovery before beta. Split services/data authority later if isolation cannot be enforced or measured contention justifies the change. No vendor API call is added to normal recognition key verification.

## Ordered delivery and gates

| Stage | APP-1 slices | Exit evidence |
| --- | --- | --- |
| Contract and integration feasibility | S0/S1 | Reviewed scope/roles/state transitions; disposition E16-7 cases/findings and E20-7 usage ownership; actual Clerk session and Polar sandbox proof; key reuse characterized |
| Real account and installation journey | S2/S3 | Tenant-safe create/list/rotate/revoke, stable owner binding, invitation redemption, working WordPress connection and accepted-output observation path |
| Cost and paid lifecycle readiness | S4/S5 | Atomic job allowances/cost reservations, bounded queues, Polar checkout/webhooks/reconciliation/cancel/recovery, local entitlements and hosted portal |
| Free beta release | S6 | APP-SC-01..18 evidence, zero-charge invariant, restore/isolation/alert/privacy/accessibility checks; live checkout disabled |
| Cohort learning | S6 observation | APP-SC-19: proposed first 10 attempts, 5 observed sessions, unassisted activation/repeat use/accepted output/support data; expand up to 20 after fixing largest failure |
| Explicit paid activation | S7 | APP-SC-20: eligibility, catalog, notice, live canary and recovery evidence; actual customer opt-in; no beta arrears |

Proposed discovery timebox for S1: two engineer-days to identify blockers and estimate remaining work, not a promise that complete production billing fits that time. Proof of the chosen stack replaces mandatory multi-vendor implementation. An actual mismatch opens one targeted fallback.

The detailed acceptance contract and 20-case eval data live in Plan 0001. This roadmap summarizes sequencing and does not introduce a second test ledger.

## Free-beta economics and measurement

Proposed starting envelope: 10 invited users, capacity for up to 20 after fixes, 30 days, 200 successful jobs per tenant and one active job per tenant. Proposed incremental 30-day budget: US$50 excluding committed hosting. These are review inputs, not approved spending or a guarantee that the workload fits. Measure and reserve worst-case dispatch costs, including failures/cold starts/idle exposure, before admitting work.

No payment instrument is required; no subscription is silently activated; expiration pauses new processing and offers an honest next action. Account/key/usage access remains available for recovery. Keep beta allowance distinct from vendor billing state.

Report attempt denominators, assistance, time to first successful and accepted caption, repeat-day use, cap encounters and support minutes. Current proposed learning gates: 8/10 unassisted activations and 5 repeat-day users in 14 days. Stop expansion for missed gates and repair the limiting flow; zero customers or a tiny successful sample does not validate demand.

Before paid offers, declare the price/allowance hypothesis and observation window. Count real offers/purchases/cancellations and contribution after compute, vendor fees and support. Free usage and sandbox payments cannot validate willingness to pay. Review effective processing fees after paid evidence makes them consequential.

## Deferred work and reconsideration

Defer private workers, agency/team hierarchy, multi-tier/annual/overage billing, generic key gateways, multiple payment implementations, custom billing forms, rich usage charts, CRM relocation and additional analytics infrastructure. Resume only for observed demand or a demonstrated operating constraint.

Reopen Polar on account/product/payout failure or a required lifecycle mismatch; choose Stripe Managed Payments or Paddle according to the actual failing requirement. Reopen key outsourcing on measured remaining-work/support advantage, including migration and outage/custody tradeoffs. Fix installation UX before treating every key support request as an authority problem.

Keep standard provider exit information and exportable tenant mappings. Privacy, tenant isolation, immediate emergency revoke, no accidental charges and bounded compute remain release requirements.
