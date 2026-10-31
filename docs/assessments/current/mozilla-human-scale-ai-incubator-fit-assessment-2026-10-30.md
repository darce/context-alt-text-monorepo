# Mozilla Human-Scale AI Incubator Fit — Assessment

> **Metadata**
>
> - **Date**: 2026-10-30
> - **Scope**: fit of ACX (this monorepo) and `~/Development/semantic-image-search` (Visual Search Workbench) for the Mozilla Foundation Human-Scale AI Incubator call; gaps to close before applying
> - **Status**: Draft for operator review
> - **Task**: HSAIFIT-1
> - **Method**: adversarial review (inversion) against Canon v0.26.2 rows, read through the pinned copy, plus passages from the original distilled corpus (`~/Development/heuristics-canon-research/distilled/`); repo claims checked against code and docs on `main` at `44b476e649`
> - **Evidence limits**: Mozilla's pages sit behind a Cloudflare challenge. Call facts come from the official application form (read directly) and search-engine quotes of Mozilla's pages, so they are secondhand. Confirm the wording on the live page before relying on it.

## Verdict

Neither project qualifies today. ACX is the one to apply with, but only if a real pilot with course authors and blind or low-vision (BLV) readers is running before the deadline: **Fri 2026-11-20, 11:59 PM PST** (Sat 2026-11-21, 2:59 AM Toronto).

## 1. The call

- **Money:** $300k plus 12 months of support from April 2027. Strong projects can get up to $200k more and two more years. Non-dilutive. Seven seats: 3 anchors, 4 open.
- **Gate:** working technology "already deployed with the people they're designed to serve, even at a small scale or through an early pilot", with early product-community fit and significant work still ahead.
- **What "successful" means:** follow-on money depends on core-tech progress, product-community-fit evidence, public benefit and the roadmap.
- **Principles:** Small (efficient models and compute), Intentional (user agency and data control), Tailored (shaped by a specific community).
- **The form screens early.** It asks for:
  - stage: Concept, Working prototype, Deployed <100, Deployed 100+
  - early signals and user count
  - how central accessibility is
  - frontier-API dependence
  - parameter bucket, from ≤10B to >40B
  - charitable purpose

  Answers outside the focus end in a newsletter offer. Mozilla doesn't say which answers trigger it.
- **Who can apply:** applicant types include Individual, Nonprofit/NGO, Fiscal sponsorship and For-profit. The region served is a hard stop, so check that Canada is in the dropdown.
- **Impact section:** success at 12 and 36 months and how it's measured, sustainability, what $300k unlocks, and how code, data and learnings are shared. A 2-minute video is optional.
- **AI use:** limited to supportive functions; heavily AI-generated applications may get extra review.
- **Anchors:**
  - Tiles: small local models plus an open private AI commons for education.
  - Family Intelligence (garden3d): household AI memory that outside servers can't read.
  - DAIR: tools for organizations to run their own compute.
- **Date conflict:** daily.dev claims submissions run Oct 30–Dec 4 and that projects started before Oct 30 are ineligible. Nothing else confirms it, and it contradicts the deployment gate.

## 2. Scorecard

| Criterion | ACX | semantic-image-search (Workbench) |
|---|---|---|
| Deployed with intended users (gate) | **Fail**: CLAUDE.md says "NO production users"; honest answers are "Working prototype" and "None of these yet" | **Fail**: no users; unsigned, un-notarized debug build |
| Small | **Weak**: Qwen3-VL-30B-A3B, a 30B mixture-of-experts model (~3B active), on a rented A10 GPU; 30–40B bucket; cold start takes minutes | **Pass**: models under 1B (OpenCLIP ViT-B/32, MobileSAM, LibreYOLOXn) on an 8 GB M1 |
| Intentional | **Weak**: face recognition is off by default today, and the operator has directed it back to on by default ([ADR-020](../../adrs/ADR-020-recognition-on-by-default-tenant-controlled.md), Proposed 2026-10-31); face templates live on the server in pgvector, demo/prod use non-commercial InsightFace buffalo_l weights, and images leave the site | **Pass**: local-only, App Sandbox, `verify-no-egress.sh`, model licences gated by ADR 0005 |
| Tailored | **Fail**: the professor segment is untested; the people the output serves aren't part of the design | **Fail**: general photo search, no community |
| Accessibility central | **Pass** | **Fail** |
| No frontier API | **Pass** | **Pass** |
| Open / public benefit | **Pass**: MIT licence, public repo, ADA Title II timing; the Stripe SaaS needs to be kept separate | **Fail**: no LICENSE file |

## 3. Adversarial review: how this gets rejected (STRAT-02 **Invert, always invert**)

Rows are from Canon v0.26.2; sources are in §7.

1. **Screened out on page one.** With zero users, ACX fails the gate before anyone reads the principles.
   - GTM-14 **Develop reference customers first**: expand "only after reference customers are live, paying, satisfied". Also PROD-06 **Persona three gates** and PROD-12 **Builder–user proximity** ("the worst-day user includes the AT user").
   - The distilled INSPIRED ch. 39 says: recruit 6–8 prospects from one segment, aiming for 6 live references. The pricing plan's 5–10 concierge pilots have that shape but haven't started.
2. **Tailored fails a disability-justice reviewer.** ACX's user is the author; the person its output serves is a screen-reader user. A pattern search of `docs/` found no BLV participant, reviewer or partner.
   - UXR-16 **Stand-in is not inclusion** requires "a named participant, co-designer, or accountable representative". Also UXR-25 **Put the community in the framing**.
   - The distilled *Design Justice* ch. 2 calls personas "objectified assumptions", and input gathered after the problem statement is fixed counts only as "consultative". ACX's problem statement is already fixed, so a partner recruited now needs real authority (for example, an MOU giving them the eval rubric), not just a quote.
   - The distilled Norman ch. 23: bring tools and partnership, not a finished solution.
3. **Small reads as a 30B GPU service, and the 30B isn't proven necessary.**
   - The [2026-10-28 model assessment](description-model-gtm-selection-assessment-2026-10-28.md) keeps the 30B based on 28/45 accepted descriptions, from reviews that weren't blind or sampled.
   - Its decision rule has 0 of 86 cells reviewed, and 29 images can only resolve differences of about ±20 points.
   - The 8B already runs on the same A10 and has no quality review.
   - CARD-19 (`bounded-role-lets-a-small-model-be-safe`): "Whether captioning and evidence fusion benefit from different model tiers remains a hypothesis to test under their contracts." Also EVAL-01 **Require offline baselines**, COST-07 **Quality–cost–coverage trade**, and COST-10 **Graceful degradation under budget** (a simpler model can cover the cold start).
   - This is the most fixable gap: an honest small-model result is fundable either way. Don't claim ≤10B by counting only active parameters (CLM-04 **Adjectives are not evidence**).
4. **Intentional runs into face recognition.**
   - Off-by-default has landed (`apps/prototype-wp-alt-context/src/settings/class-recognition-policy.php:20`, commit `31ef9cbc82`; SECD-12 **Biometric opt-in default**). The [2026-09-18 Google Photos assessment](altcontext-vs-google-photos-assessment-2026-09-18.md) says "default on", which is stale today.
   - **Operator direction 2026-10-31:** recognition goes back to on by default for the tenant's own library ([ADR-020](../../adrs/ADR-020-recognition-on-by-default-tenant-controlled.md), Proposed). It records the SECD-12 deviation and moves the subject's protection to what is stored: unnamed faces expire after 30 days, every template carries a capture basis, held jurisdictions (US-IL, US-TX, US-WA, EU/EEA, UK, CA-QC) stay opt-in, there is one off switch plus an always-visible delete-all, and privacy-policy text is registered. The default doesn't flip before that gate, counsel and E22 pass.
   - For this application, the reviewer will still read "on by default" against Intentional. The defensible answer is the controls above, not the default.
   - The people in the photos never opt in, templates sit on the server, and the [March privacy roadmap](../../roadmaps/recognition-privacy-hybrid-roadmap-2026-03-06.md) calls the posture "closer to 'remote biometric storage'".
   - Rows: MLDATA-13 **Body-derived identifiers are their own data class**, SECD-13 **Necessity-proportionality gate** ("written need, alternatives considered…"), SECD-09 **Treat face-template compromise as exposure, not a password reset**, and CARD-26 (`licence-provenance-is-transitive`) for buffalo_l.
   - The distilled *Compulsory Visibility* ch. 4 §4.3 gives Canada's test: need, effectiveness, proportionality, no other means. Course material fails "no other means" because the author can just type the name. The only exemptions are synthetic or consented lab data and device unlock with local-only templates.
5. **The claims hurt when read literally.** The README tagline sells "facial recognition and roster management", and leading with ADA Title II deadlines invites a "this makes you compliant" reading. Rows: CLM-05 **Three hostile readers** ("read literally, not charitably"), CLM-03 **The policy is a contract**, A11Y-22 **Scoped conformance claims**.
6. **Author control has to be visible.** ATAG treats AI-written alt text as auto-generated content.
   - A11Y-63 **Controlled text-alternative repair**: authors accept, modify or reject before insertion, with no generic strings. Also A11Y-34 **Auto-specified content is accessible**, HAI-12 **Output is a proposal, not the answer**, HAI-13 **User is the last error detector** and AIPX-13 **Disclose AI early**.
   - CAL-02 **Unknown is a valid result** and AIPX-07 **Precision-first guidance** ("wrong advice costs more than silence") support a "needs the author's description" result.
   - The 2026-10-28 assessment already recommends a stage label, AI disclosure, presenting output as a draft, and logging accept/edit/flag (PROD-39 **Communicate product stage**).
   - The docs don't confirm that alt text is reviewed before it's inserted; check the UI before claiming it.
7. **Success measures that can't be checked.** The form wants measures at 12 and 36 months, and cost per accepted description has never been computed (2026-10-28 assessment, F7). Rows: FORE-02 **Resolvable forecast contract**, MEAS-11 **Define the observable before measuring**.
8. **The real obstacle isn't named.**
   - STRAT-20 **Face the challenge** says "define the difficulty and its causes before goals or spend". The distilled Rumelt ch. 3: "Underperformance is a result, not a diagnosis."
   - The obstacle: no author has used ACX in a live course, and no screen-reader user has judged its output.
   - BIAS-02 **No unnoticed substitution**: that is the real question; "can it generate alt text" is the easier stand-in.
9. **Overlap with an anchor.** Tiles' education commons sits next to the professor segment. Pitch ACX as an accessibility piece that commons could run, not a competitor.

BIAS-05 **Outsider test**: with zero users and three weeks left on a call that requires deployment, apply only if a real pilot can go live. Otherwise skip this round. A separate Fellows track closes Dec 17; this assessment didn't look into it.

## 4. Does semantic-image-search fit better?

No. It wins Small and Intentional outright and has the stronger privacy engineering of the two, but it fails the same gate plus Tailored, accessibility and licensing. Turning it into local photo description and search for blind users' own libraries would match all three principles, but that's a new product with no users and three weeks to go.

## 5. Gaps to close before applying

| # | Gap | Canon | Where | Doable by Nov 20? |
|---|---|---|---|---|
| 1 | Live pilot in one segment: 1–3 instructors or one campus accessibility office, real course images, real use logged | GTM-14, PROD-06, PROD-66 **Core version first** | people/ops | Only if recruited by ~Nov 6 |
| 2 | BLV partner with an MOU giving them authority over the eval rubric; judges give consent and are paid | UXR-16, UXR-25, UXR-52 **Set ethical boundaries before collection** | people | Same as 1 |
| 3 | 8B vs 30B, model hidden from judges, rated by BLV readers on sampled pilot images; a human-written alt as baseline; private eval set; decision rule written first. If the 8B is within margin, make it the default and use the 30B for escalation | CARD-19, EVAL-01, EVAL-15 **Treat public benchmarks as contaminated**, COST-07, FORE-02 | ACX | Yes; the bake-off already exists |
| 4 | Recognition stays in the product, on by default under ADR-020. Keep it out of the application's lead and the README tagline. If it is mentioned, describe ADR-020's controls (tenant-only, 30-day limit on unnamed faces, held jurisdictions, delete-all) and say plainly that the default is on. Finish E22 so prod drops buffalo_l | MLDATA-13, MLDATA-15, SECD-12, SECD-13, CARD-26, CLM-05 | ACX | Docs yes; E22 no |
| 5 | Visible accept/edit/reject before insertion, a "needs author" state, an AI label, a Beta label | A11Y-63, A11Y-34, HAI-12, HAI-13, AIPX-13, CAL-02, PROD-39 | ACX | Yes |
| 6 | Accept/edit/flag logging → share accepted without edits, BLV-judged major-error rate, cost per accepted description, author minutes per image | MEAS-11, FORE-02 | ACX | Yes |
| 7 | Model card and open eval set, with errors broken down by image type and by attributes of people shown | PROV-02 **Model card at release**, FAIR-01 **Publish disaggregated operating errors** | ACX | Draft yes |
| 8 | Claims pass: no compliance wording; parameter bucket uses total parameters | CLM-03, CLM-04, A11Y-22 | ACX docs | Yes |
| 9 | Separate the grant-funded public goods (eval set, model card, small-model path, free tier for public institutions) from the Stripe SaaS; pick an applicant type | — | non-code | Yes |
| 10 | Write the application yourself and name the obstacle; 2-minute video of a screen-reader user hearing pilot output | STRAT-20, CLM-05 | non-code | Yes, after 1–2 |

Rows 1–2 are the gate. If they can't happen in time, rows 3–10 won't save this round.

## 6. ACX or the Workbench?

- **All ten go into ACX.** It's the applicant, and every gap is about its users, model or claims.
- **Carry patterns from the Workbench into ACX, not features:**
  - Port `scripts/qa/verify-no-egress.sh` into ACX's self-host / Private Worker mode ([local-AI roadmap](../../roadmaps/local-ai-managed-default-roadmap-2026-07-31.md)), so Intentional is enforced rather than promised.
  - Port the ADR 0005 Apache/MIT weight gate and `models/LICENSE-NOTICES.md` as an ACX CI check. It would have refused buffalo_l.
  - Treat its on-device Core ML runtime as the 36-month path to drafting alt text on the author's own Mac.
- **Nothing on this list goes into the Workbench itself.** Add a LICENSE before ever calling it open, and don't bolt alt text onto it for this call.

## 7. Canon rows cited

| Row | Tier·phase | Source |
|---|---|---|
| STRAT-02 | B·s | Poor Charlie's Almanack (Munger), § talk-1 |
| STRAT-20 | B·s | Good Strategy Bad Strategy (Rumelt), ch. 3 |
| GTM-14 | J·g | INSPIRED (2nd ed.), ch. 39 |
| PROD-06 | B·p | Lean UX (3rd ed., Gothelf/Seiden), ch. 7 + INSPIRED (2nd ed.), ch. 41 |
| PROD-12 | S·p | The Technological Republic (Karp/Zamiska), ch. 13 |
| PROD-39 | S·g | Escaping the Build Trap, ch. 20 |
| PROD-66 | S·p | Business Analysis Methodology Book (Yayici), ch. 3 |
| UXR-16 | J·r | Design Justice, ch. 2 |
| UXR-25 | S·p | Design for a Better World, ch. 22 + Design for a Better World, ch. 23 |
| UXR-52 | B·p | Just Enough Research, 2nd Edition, ch. 2 |
| EVAL-01 / CAL-02 | S·r / B·p | Designing Machine Learning Systems |
| EVAL-15 | S·p | AI Engineering |
| COST-07 / COST-10 | S·w / B·w | Reliable Machine Learning (Chen, Murphy, Parisa, Sculley et al.) |
| SECD-09 / SECD-12 | B·p / S·r | Face Recognition Technology (Compulsory Visibility), ch. 2 |
| SECD-13 / MLDATA-13 | S·p / B·p | Face Recognition Technology (Compulsory Visibility), ch. 7 |
| CLM-03 / CLM-04 / CLM-05 | S·o / S·o / S·g | bootstrap |
| A11Y-22 | B·g | Web Content Accessibility Guidelines 2.2, § conformance |
| A11Y-34 | B·w | Authoring Tool Accessibility Guidelines (ATAG) 2.0, § B.1.1.2 |
| A11Y-63 | B·w | Authoring Tool Accessibility Guidelines (ATAG) 2.0, § B.2.3.2 |
| HAI-12 | B·w | Designing AI Interfaces (Macfadyen 2026) |
| HAI-13 | B·w | Designing AI Interfaces (Macfadyen 2026), § surfacing-state |
| AIPX-13 | S·g | Designing AI Interfaces (Macfadyen 2026), § this-summary-ai-generated |
| AIPX-07 | S·p | Building Machine Learning Powered Applications (Ameisen), ch. 7 |
| FORE-02 | B·p | Superforecasting, ch. 3 |
| MEAS-11 | S·p | How to Measure Anything in Cybersecurity Risk, ch. 2 |
| BIAS-02 | S·p | Thinking, Fast and Slow, ch. 9 |
| BIAS-05 | S·p | The Scout Mindset, ch. 5 |
| PROV-02 | S·r | Model Cards |
| FAIR-01 | B·r | Gender Shades |

Reasoning cards: CARD-19 `bounded-role-lets-a-small-model-be-safe`, CARD-26 `licence-provenance-is-transitive`.

Distilled passages are in `~/Development/heuristics-canon-research/distilled/`:
- `interaction/design-justice.md`: stand-ins, "nothing about us without us"
- `design/design-for-a-better-world-norman.md`: ch. 22, 23
- `business/cagan-inspired.md`: ch. 39, 41
- `business/good-strategy-bad-strategy.md`: ch. 3
- `security/face-recognition-compulsory-visibility.md`: opt-in default, necessity-proportionality gate, ch. 4 §4.3

## 8. References

### Mozilla (official)
- [Call for proposals](https://www.mozillafoundation.org/en/what-we-do/grantmaking/incubator/human-scale-ai/call-for-proposals/) (behind Cloudflare; not read directly)
- [Cohort / anchors](https://www.mozillafoundation.org/en/what-we-do/grantmaking/incubator/human-scale-ai/cohort/)
- [Human-Scale AI incubator](https://www.mozillafoundation.org/en/what-we-do/grantmaking/incubator/human-scale-ai/)
- [Application form](https://mozillafoundation.tfaforms.net/w/humanscaleai) (read directly)
- [Join us / newsletter](https://www.mozillafoundation.org/en/join-us/)

### Third-party listings (secondhand)
- [fundsforNGOs](https://www2.fundsforngos.org/innovation/mozilla-foundation-s-human-scale-ai-incubator-2027-call-for-proposals/)
- [DevelopmentAid](https://www.developmentaid.org/grants/view/1735925/request-for-applications-human-scale-ai-incubator-cohort-united-states)
- [daily.dev](https://daily.dev/posts/dev-opportunity-radar-23-500k-mozilla-ai-incubator-100k-kiroween-hackathon-and-wispr-flow-hir-09xhhtcti) (unconfirmed dates)
- [EIN Presswire release](https://www.einpresswire.com/article/951754263/mozilla-foundation-opens-funding-call-for-ai-built-around-communities)
- [MIT Solve: Nabiha Syed](https://solve.mit.edu/articles/tse-nabiha-syed)

### Repo evidence
- [Description model GTM selection assessment (2026-10-28)](description-model-gtm-selection-assessment-2026-10-28.md)
- [AltContext vs Google Photos assessment (2026-09-18)](altcontext-vs-google-photos-assessment-2026-09-18.md) (its "default on" line is stale)
- [Recognition privacy hybrid roadmap (2026-03-06)](../../roadmaps/recognition-privacy-hybrid-roadmap-2026-03-06.md)
- [Local-AI managed-default roadmap (2026-07-31)](../../roadmaps/local-ai-managed-default-roadmap-2026-07-31.md)
- [E22 commercial face identity replacement epic](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
- [E15 public demo launch readiness epic](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
- [Pricing strategy (2026-10-08)](../../gtm/pricing-2026-10-08/strategy.md)
- `apps/prototype-wp-alt-context/src/settings/class-recognition-policy.php:20` (recognition default off)

### semantic-image-search (`~/Development/semantic-image-search`)
- `docs/adr/0005-licenses-and-captions.md` (Apache/MIT weight licence gate)
- `models/LICENSE-NOTICES.md`
- `scripts/qa/verify-no-egress.sh`

### Tooling
- Playwright CLI 1.60.0 and Google Chrome are installed; earlier a11y use is recorded in handoff decision 19650 (UXREC-1).
