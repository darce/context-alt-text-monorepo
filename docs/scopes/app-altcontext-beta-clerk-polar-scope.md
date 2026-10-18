# APP-1 scope: free beta with a ready paid path

Date: 2026-09-19. Status: proposed; intake partly answered, assumptions explicit.
Handoff decision: `APP-1` #12633. [Plan 0001](../plans/0001-app-altcontext-beta-clerk-polar-task-plan.md). [Research and vendor refresh](../assessments/current/app-portal-prior-art-and-vendors-2026-09-19.md).

Current recommendation: [Clerk identity + retained local API keys + Polar Starter](../assessments/current/app-portal-launch-recommendation-2026-09-19.md), with source-book corpus and execution sequence. The earlier vendor comparison remains evidence; mandatory comparative spikes are replaced by proof of the chosen path and explicit fallback triggers.

## Intent and recommendation

The user requests app.altcontext.com with Clerk, tenant API-key self-service/rotation and Polar payments, with a refreshed payment comparison grounded in the heuristics canon. The user further requires a **free testing phase**, with paid conversion implemented or close to completion, and asks which launch choice best balances flow learning and initial cost.

Recommend the first option's complete journey as a **controlled free self-service beta**. Recruit a small cohort, let them sign up and connect WordPress themselves, observe friction, and expand only after the limiting step improves. Implement and prove the selected provider's checkout/webhooks/portal/cancellation/recovery in sandbox before beta. Turning on live payment later requires explicit customer checkout; beta expiry never charges a customer.

## Intake record

| Question asked | Answer or working assumption |
| --- | --- |
| Paid beta / public launch / private manual pilot? | User explicitly wants free beta plus ready paid conversion. Controlled self-service enrollment is our recommendation, not yet accepted |
| Clerk/Polar preferred or fixed? | User explicitly asks to reopen both choices. Recommend Clerk identity, retained local keys and Polar Starter after comparison. User asked whether keys also retire: recommendation explicitly says no. No implementation approval claimed |
| Organization / single-owner / agency tenant? | No new answer. Preserve E16-7 single-owner `(issuer, subject)` binding initially; tenant UUID is independent of user. Team roles/invites are deferred, not accidentally implied by "workspace" |
| Date, budget, prices, rotation, outages? | Low initial costs confirmed; exact ceiling/date unconfirmed. Propose seven-day maximum overlap, bounded usage, local outage containment and measured rollout gates below |

The earlier September 15 keys-only intake excluded signup and billing; this user's new request expands that scope. Its immediate-revocation rotation was subsequently amended in the September 16 assessment. Retain a separate emergency revoke rather than conflate the two behaviors.

## MVP scope and completion signals

- Clerk signup/login/logout/recovery, invitation redemption, deterministic tenant creation or safe existing-tenant claim.
- One owner per tenant; key create/list/rotate/revoke; one-time secret display; WordPress install and Test Connection guidance.
- Beta entitlement with no payment instrument or charge; real limits, visible allowance/end date, recoverable cap/expiry states.
- Usage and activation evidence; privacy-safe feedback; observed first-run sessions with consent.
- Polar sandbox checkout, signed durable webhooks, local subscription/entitlement projection, hosted billing portal, cancellation/failed-payment recovery and reconciliation.
- Live paid activation implemented behind a server gate; explicit checkout at launch, no silent beta-to-paid conversion or arrears.
- Isolation, concurrency, provider-failure, restore and full user-journey evidence. Every APP-SC criterion maps to an eval case in [the eval data](app-altcontext-beta-clerk-polar-evals.json).

## Proposed non-functional envelope

Start with 10-20 invited tenants, one owner each, and a 30-day beta grant. A provisional 200 successful image jobs per tenant caps the first cohort at 2,000-4,000 jobs; validate this allowance against actual cold-start/GPU costs before invitations. Also enforce daily/global admission limits, max job cost/size, bounded queues and an operator stop control. A usage cap alone is not a dollar cap.

Propose a US$50 **incremental** 30-day beta spending ceiling, excluding already-committed hosting; approval and an actual worst-case cost envelope are release inputs, not assumptions to charge against. Prefer Clerk Hobby and Polar Starter if required security features fit; buy additional features only when justified. No new analytics warehouse or separate dashboard runtime by default.

Local portal operations target p95 <=500 ms / p99 <=1 s under the defined staging load; vendor redirects <=3 s timeout, durable webhook ack <=2 s. These are test targets, not existing measured SLOs. The plan defines retries, bounded stale entitlements, read-after-write behavior and outage recovery. No calendar launch promise until readiness evidence exists.

## Not doing

Public unlimited enrollment; automatic charging at beta expiry; live charges in this planning session; usage overage billing; agency subtenants/team roles/SSO; custom payment forms/invoices; migration to Clerk-managed API keys or a generic API gateway; a second tenant/key source of truth; local-worker implementation; CRM rebuild; plugin silent key replacement; storing media, face identity or credentials in analytics.

## Review decisions

Confirm controlled enrollment, single-owner tenancy, exact cohort/allowance/budget/date, price/currency/catalog, failed-payment grace, entitlement staleness, and vendor-account eligibility. The draft is reviewable with these labelled proposals; it is not an accepted implementation baseline. Scope questions were asked, but the unanswered ones are not reported as approved decisions.
