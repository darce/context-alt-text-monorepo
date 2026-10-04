# APP-1 payment vendor terms comparison

Status: official-source collection complete. Research only. No implementation. No provider contact. No secrets or account changes.

Collected: 2026-09-22. Public HTML only. Nine fetches used of a ten-fetch cap.

Planning context: AltContext is a Canadian individual planning incorporation. The product would sell editor-reviewed descriptions of publisher-supplied images, with tenant rosters and face matching, and costly GPU usage. Polar, Paddle, and Lemon Squeezy are evaluated as supplier/MoR documents; Stripe Canada SSA is the direct-processor seller agreement. Buyer checkout terms were not used as the comparison baseline.

Primary contractual text controls. User-supplied Polar/Paddle claims were treated as hypotheses and tested against the pages below ([STRAT-02](https://github.com/darce/heuristics-canon/blob/main/lexicons/business-marketing.md#strat-02)). This note does not rank providers from marketing copy.

Quote budget: at most 25 words quoted from each webpage. Remaining substance is paraphrase. “No clause found” means it was not in the fetched page; it is not a guarantee the obligation is absent from another document, an order form, or a later revision.

## Sources fetched

| # | Document | URL | Date on page | Role |
|---|---|---|---|---|
| 1 | Polar Master Services Terms | https://polar.sh/legal/master-services-terms | Last Updated — March 25, 2026 | Supplier / MoR reseller |
| 2 | Polar Acceptable Use Policy | https://polar.sh/legal/acceptable-use-policy | Effective Date — March 25, 2026 | Supplier product eligibility |
| 3 | Polar Privacy Policy | https://polar.sh/legal/privacy-policy | Effective Date — September 8, 2026 | Privacy role |
| 4 | Paddle Master Services Agreement | https://www.paddle.com/legal/terms | Last updated: 8 October 2025 | Supplier / MoR reseller |
| 5 | Paddle AUP help article | https://paddle.com/support/aup/ | Last Updated 13 April 2026 | Supplier product eligibility |
| 6 | Lemon Squeezy SaaS Service Agreement | https://www.lemonsqueezy.com/terms | No “last updated” clause found; footer ©2026 Sold through Link, LLC f/k/a Lemon Squeezy LLC | Supplier-facing terms (also contains reseller language in §5) |
| 7 | Stripe Services Agreement — General Terms (en-ca) | https://stripe.com/en-ca/legal/ssa | Last modified: November 18, 2025 | Direct seller / PSP (Canada entity Stripe Payments Canada, Ltd.) |
| 8 | Stripe Prohibited and Restricted Businesses (en-ca) | https://stripe.com/en-ca/legal/restricted-businesses | No standalone effective-date line found on page | Eligibility |
| 9 | Stripe SSA Services Terms (Financial Services + Payments) | https://stripe.com/en-ca/legal/ssa-services-terms | Financial Services last modified November 18, 2025; Payments last modified April 24, 2026 | Reserve / payouts |

Not fetched (cap): Polar DPA, Paddle Data Sharing Addendum, Lemon Squeezy DPA/privacy, Stripe DPA, Lemon Squeezy 2026 Managed Payments blog. Those gaps are marked below.

Lemon Squeezy’s terms page also shows a banner about “Lemon Squeezy + Stripe Managed Payments.” The body still describes Lemon Squeezy as a non-exclusive reseller in §5. This comparison uses the contractual body, not the banner.

## User-claim check

| Claim | Result | Where |
|---|---|---|
| Polar hold = 9 months **or** last subscription **or** disputes | **Confirmed as a later-of clock**, not an election. Release after the later of nine months after termination, resolution of known chargebacks/refunds, and expiry of the longest active buyer subscription. | Polar MST 18.4; retention purpose also MST 18.2 |
| Polar insurance = general + professional + cyber, plus 1 year | **Confirmed.** Supplier must keep commercial general liability, professional (E&O), and cyber for the term and one year after. Certificates on request. Amounts/carriers not stated. | Polar MST 20.12 |
| Polar liability cap = six-month fee | **Confirmed as Polar Fee from the supplier’s transactions**, not fees AltContext paid Polar as a subscriber. Cap is Polar’s aggregate liability. Fraud/willful misconduct carved out. | Polar MST 13.3, 13.4 |
| Polar uncapped IP indemnity | **Confirmed only as supplier → Polar.** Supplier IP indemnity for Product/marks/URLs/Product Information is outside the liability cap. No Polar → supplier IP indemnity found on this page. | Polar MST 5.4, 13.3 |
| Polar changes are immediate | **Confirmed.** Changes effective immediately; material changes get site notice or email. Continued use is acceptance. Termination path is MST 17 if the supplier disagrees. | Polar MST intro (Acceptance) |
| Paddle hold = 6 months **or** last subscription | **Confirmed as a later-of clock.** Release on or before the later of six months from termination or expiry of the last Product subscription. Chargebacks/refunds are a retention purpose (17.2) but are **not** a third later-of trigger like Polar 18.4. | Paddle MSA 17.2, 17.4 |
| Paddle has the same defect-free warranty | **Confirmed as the same supplier warranty of the Product**, not a Paddle warranty of Paddle’s services. Paddle disclaims its own service warranties. | Paddle MSA 11.1(vi), 12.1; Polar MST 11.1(vi), 13.1 |

## Six-row comparison

Rows are the six commercially material scoped topics. AI/face-matching eligibility and privacy role follow as the remaining two scoped topics.

| Topic | Polar (MoR) | Paddle (MoR) | Lemon Squeezy (terms page) | Stripe direct (Canada SSA) |
|---|---|---|---|---|
| **1. Insurance obligation** | MST 20.12: supplier maintains CGL, professional (E&O), and cyber for the term **and one year after**. Limits not stated. | **No insurance clause found** in the MSA. Not a guaranteed absence of a later onboarding ask. | **No insurance clause found** in the SaaS agreement. | **No insurance clause found** in SSA General Terms. |
| **2. Liability cap bases** | MST 13.3: Polar’s aggregate liability = Polar Fee from the supplier’s transactions in the **six months** before the event. Carve-outs MST 13.4 (fraud/willful misconduct; death/injury; non-excludable law). | MSA 12.3: Paddle’s aggregate liability = Paddle Discounts on transactions in the **six months** before the event. Carve-outs 12.4 (fraud; death/injury; SGA/SGSA implied title terms; non-excludable law). | §9.4: LS aggregate liability, including indemnification, = amounts **paid by Customer in the prior one-month period** (or the one-time fee for that service). Indirect damages excluded. | SSA 8.4: each party’s aggregate liability = **Fees User paid Stripe in the 12 months** before the first event (excluding Financial Provider pass-through fees). Excluded Claims (gross negligence/fraud/willful misconduct; User §1.2 breach; confidentiality except Data Incident Losses; §9.1 indemnities) sit outside the cap. User payment obligations are not capped. |
| **3. Supplier indemnity (provider → seller)** | **No Polar→supplier IP indemnity found.** Supplier indemnifies Polar for Product IP (5.4, uncapped) and for account/info, breach, law, and Product disputes (12.1). Quote (MST): “Supplier’s obligations under this Section are not subject to any limitation of liability.” | **No Paddle→supplier IP indemnity found.** Supplier indemnifies Paddle for account information, breach, law, and Product disputes (11.2). | §10.1: Lemon Squeezy defends Customer against third-party claims that the **Lemon Squeezy Service** infringes a US patent issued as of the Effective Date, copyright, trademark, or trade secret; exclusive remedy; no liability for third-party software or customer modifications. Customer indemnifies LS for Customer Data and use (§10.2). Indemnity is inside the §9.4 cap. | SSA 9.1(b): **mutual** IP indemnity, with combination exception; exclusive remedy; indemnifier may modify, replace, license, or terminate on 30 days’ notice. User also gives a broad general indemnity for use, gross negligence, willful misconduct, fraud, or material breach (9.1(a)). |
| **4. Reserve / post-termination holds** | MST 7.2: Polar may set, increase, or keep a reserve, delay/suspend payouts, or require prefunding; high-risk/suspended payouts may be delayed **up to 120 days**. MST 18.2–18.4: on termination/suspension Polar may retain Supplier Fees for liabilities, chargebacks, refunds, and remaining subscriptions; release at the **later of nine months, known dispute resolution, and longest remaining subscription**. | MSA 8.3: if funds are insufficient for potential refunds/chargebacks/other liabilities, Paddle may require funding or set-off and may suspend. MSA 17.2–17.4: may retain Supplier Fees for outstanding liabilities and future chargebacks/refunds/remaining subscriptions; release on or before the **later of six months from termination or last Product subscription expiry**. | §7.1.5: LS may “delay payouts for risk assessment”, suspend accounts, and refund payouts without warning if there is evidence of fraud. **No fixed 6- or 9-month post-termination hold found.** After termination LS deletes Customer Data except as required by law (§11.4). | Financial Services Terms 3.3: Stripe may establish a Reserve by Reserve Notice; Stripe controls it; release only when Stripe is satisfied the risk is mitigated; terms may change if risk changes. SSA 7.2(c) lets Stripe collect from a Reserve. **No public fixed calendar hold found** (amount/duration live in the Reserve Notice/Dashboard, not this page). Canada regional term 5.1: safeguarded funds used to fund a Reserve are no longer safeguarded on the user’s behalf. |
| **5. Change notice / assignment** | Changes **effective immediately**; material changes by site notice or email; continued use = acceptance; supplier may terminate under §17 if it disagrees. Polar may assign to an Affiliate or in M&A without consent; supplier may not assign without Polar’s prior written consent (20.3). | New suppliers: immediate. Existing suppliers: **30 days after publication**; material changes emailed on or before publication; supplier may terminate under 16.1; continued use after 30 days = acceptance. Supplier may not assign without Paddle’s prior written consent, not to be unreasonably withheld (18.3). | Main agreement: amendment only by a writing signed by both, except as otherwise set forth (§12.6). End User Terms and Appendix A prohibited list may change; Appendix A says changes take effect immediately. Customer may not assign without LS prior written consent (§12.1). LS assignment of its own rights: **no clause found** granting LS a unilateral assignment right. | SSA 11.8: Stripe may modify by posting on the Legal Page or by notice; effective on posting or as the notice states; continued use = acceptance. User is responsible for checking the Legal Page. SSA 11.10: User needs Stripe’s prior consent to assign (not unreasonably withheld), except a whole-agreement assignment to an M&A successor with notice and assumption; Stripe may assign without User consent. Fee increases: ≥30 days’ notice (7.1(c)). |
| **6. Defect-free warranty** | **Supplier** warrants the Product is free from defects and fit for the agreed or ordinary purpose (11.1(vi)). Polar’s **Services** are as-is; Polar disclaims merchantability, fitness, title, non-infringement, and uninterrupted/error-free operation (13.1). | **Same supplier Product warranty** at 11.1(vi). Paddle’s **Services** are as-is with the same style of disclaimer (12.1). | LS warrants the Service will conform in all material respects with its intended purpose; exclusive remedy is repair/correct or terminate with prepaid refund from termination (§9.2(d)). Broader as-is / no merchantability-fitness disclaimer in §9.3. **No supplier defect-free Product warranty found** on this page. | SSA 8.2: Services and Stripe Technology provided “as is”; Stripe disclaims implied warranties to the maximum extent permitted. Payments Terms §2: User is solely responsible for the nature and quality of its goods and services. **No defect-free Product warranty found.** |

## Scoped topic: AI / face-matching eligibility

Not a ranking. Eligibility is underwriting plus these public lists.

- **Polar AUP** (effective 25 Mar 2026). Acceptable products include software/SaaS and digital goods. Prohibited products include physical goods, human services, marketplaces, and content generation that infringes IP or “enables face swaps or deep fakes.” Restricted (enhanced review, may be refused): AI content-generation tools for text, image, video, or voice. Also prohibited: OSINT platforms that aggregate/search/expose personal data from public or leaked sources. **No clause found that names biometric face-matching SaaS or editor-reviewed alt-text.** Face matching on publisher-supplied tenant images is not the same as selling face-swap/deep-fake generation, but Polar can still refuse under residual sole-discretion / risk-tolerance language (AUP; MST 9.8).
- **Paddle AUP** (updated 13 Apr 2026). Built for software companies; physical goods and unrelated human services are out. Content-generation prohibited list includes face swaps, deep fakes, likeness generation without consent, and “Automated decision-making or categorization of people.” “Human-like faces in realistic, stylized, or animated forms” is marked Restricted. Identity-theft protection / age verification sits in a prohibited financial-services bullet. **No clause found that expressly allows or bans tenant-roster face matching for editor-reviewed descriptions.** Automated categorization of people is the closest named risk for a matching pipeline.
- **Lemon Squeezy Appendix A.** Prohibits unlicensed IP, counterfeit, payment-partner-restricted items, illegal/age-restricted, several regulated products/services, MLM, essay mills, etc. List “may change without notice” and changes “take effect immediately.” **No AI, face-matching, biometric, or deep-fake clause found on this page.**
- **Stripe restricted businesses (en-ca).** Prohibited representative list includes identity-theft protection (monitoring/recovery) and products that infringe or facilitate infringement of IP **or privacy rights**. Restricted list includes several high-risk verticals (content platforms, crypto, firearms, telemedicine, etc.). **No clause found that names face matching, biometrics, embeddings, or AI captioning.** Stripe Identity is a separate Stripe product in the Services Terms index; using Stripe Identity is not the same as selling AltContext’s own matcher. SSA 1.2(a)(ix) still bars Prohibited or Restricted Businesses unless Stripe pre-approves in writing.

GPU metering is a pricing/risk fact, not an eligibility clause. None of the nine pages set a GPU-usage rule.

## Scoped topic: privacy role

- **Polar.** MST 15.1 incorporates the Privacy Policy and DPA. MST 15.5: each party is an independent business (or equivalent) under US state privacy laws for information it independently collects; the parties say they do not intend to create a processor-service provider relationship. Privacy Policy (8 Sep 2026) separately says Polar is Processor for information processed to provide the Services and Controller for other website/customer-facing information, and names Stripe as payment processor. GDPR/UK section is in the Privacy Policy. Polar DPA URL is listed but was **not fetched**.
- **Paddle.** MSA 14.2: each party is an independent Controller and must follow Data Protection Laws **and** the Data Sharing Addendum (https://www.paddle.com/legal/data-sharing-addendum, **not fetched**). MSA 14.3 points at https://paddle.com/privacy for safeguards. This is a controller-to-controller framing on the MSA page, not a processor designation.
- **Lemon Squeezy.** §8.2: LS will not disclose or use Personal Data except as the agreement, the then-current Privacy Policy, law, customer instruction, or as reasonably necessary to provide the Service. **No controller/processor label found on the terms page.** Footer links `/privacy` and `/dpa` (not fetched).
- **Stripe.** SSA 4.1 incorporates the DPA (https://stripe.com/en-ca/legal/dpa) and Data Transfers Addendum. The SSA itself does not restate controller vs processor; that split lives in the unfetched DPA. Canada contracting entity for the SSA table is Stripe Payments Canada, Ltd., with Stripe, LLC as an additional party solely for Personal Data processing under SSA §4.

## Source notes (paraphrase cap)

Each block is well under 180 words.

**Polar MST.** Polar is appointed non-exclusive reseller/MoR: Polar checkouts, tax handling, first-tier transactional support; supplier owns Product support. Polar may reserve, delay, set off, and after termination hold funds on the later-of nine-month / disputes / last-subscription clock. Supplier gives Polar an uncapped Product-IP indemnity. Polar’s own liability is the six-month Polar Fee. Supplier must carry CGL, E&O, and cyber through one year post-term. Terms change immediately; Polar can assign out, supplier cannot without consent. Delaware arbitration; class waiver; 30-day opt-out.

**Polar AUP.** Digital software/SaaS is in-scope; physical goods and human services are not. Long prohibited list; Polar may add to it and refuse any product. Face-swap/deep-fake generation is prohibited. AI content-generation tools need closer review. OSINT personal-data exposure is prohibited.

**Polar Privacy Policy.** Covers Polar Software’s collection of Personal Data. Polar claims Processor status for Services data and Controller status for other site/customer activity. Stripe is named as card processor. US state and GDPR/UK rights sections are included.

**Paddle MSA.** Same MoR-reseller shape as Polar, with a six-month-or-last-subscription release clock rather than Polar’s nine-month later-of-three. No insurance clause found. No Paddle→supplier IP indemnity found. Existing-supplier term changes wait 30 days and are emailed if material. English law/courts. Supplier Product defect-free warranty matches Polar’s.

**Paddle AUP.** Software-company MoR. Content-generation rules expressly list face swaps, deep fakes, non-consensual likeness, and automated categorization of people. Human-like face generation is restricted.

**Lemon Squeezy terms.** Hybrid SaaS subscription + §5 reseller/tax language. One-month lookback liability cap. LS gives a limited US-IP defense of its Service. Payouts may be delayed for risk; no numbered post-termination hold. Signed-writing amendment for the main agreement. Utah law/courts. 2026 Stripe Managed Payments banner is marketing on the same URL, not substitute terms.

**Stripe SSA (en-ca).** Direct PSP agreement, not MoR. 12-month fees-paid cap with listed Excluded Claims. Mutual IP indemnity. Terms changeable by posting. Canada user contracts with Stripe Payments Canada, Ltd. DPA incorporated by reference.

**Stripe restricted businesses.** Representative prohibited/restricted lists. No face-matching category found. Identity-theft protection is prohibited. Privacy-rights infringement is prohibited.

**Stripe Financial Services / Payments terms.** Reserve is a Stripe-controlled collateral account released when Stripe is satisfied risk is mitigated. Payments Terms put goods/services quality on the user. Canada: funds used for a Reserve leave the safeguarding/trust treatment.

## Three concrete provider questions

Ask in writing against the named clause. Do not treat a sales call as an amendment.

1. **Polar and Paddle (eligibility).** MST/AUP and Paddle AUP: does a Canadian SaaS that runs face matching on **publisher-supplied** tenant-roster images, then emits **editor-reviewed** descriptions (not generated faces, not face-swap, not public OSINT), fall under Polar’s prohibited face-swap/deep-fake or restricted AI-content-generation categories, and/or Paddle’s “automated decision-making or categorization of people” / restricted human-like-faces bullets? What enhanced due diligence artifacts are required before the first live checkout?

2. **Polar (hold + entity change).** MST 18.4 and 7.2: for usage-priced GPU subscriptions, is the retained amount gross collections, unpaid overage, or Polar Fees only? If a Canadian individual starts as a sole proprietor and later assigns the account to a new corporation, does Polar treat that as a prohibited assignment (20.3), a new KYB, and a new nine-month hold clock?

3. **Stripe Canada and Paddle (onboarding capacity).** SSA Financial Services 2.1 allows a sole proprietor; Paddle/Polar MSA text assumes a Supplier business. Will a Canadian individual **before incorporation** be onboarded for this product, and which of insurance certificates (Polar 20.12), a Reserve Notice (Stripe FS 3.3), or MoR Product Information / AUP review must exist before paid traffic? If refused, what written basis (AUP category vs KYB vs risk) will be given?

## Method limits

- Public pages only, as of 2026-09-22. Providers can change terms; Polar and Stripe do so by posting.
- Order forms, dashboard policies, Reserve Notices, and KYB questionnaires can add holds, insurance, or refusals not in these pages.
- Lemon Squeezy’s live commercial model may be moving toward Stripe Managed Payments; §5 of the fetched terms still describes reseller/MoR services.
- Stripe DPA, Polar DPA, Paddle Data Sharing Addendum, and Lemon Squeezy DPA were not fetched; privacy-role statements above are only as strong as the fetched pages.
- This is not legal advice and not a vendor selection. Implementation is out of scope for this lane.
