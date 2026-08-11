# Local AI + Managed-Default Product Roadmap

> **Status:** Active product direction (2026-07-31). Supersedes remote-only permanence in [ADR-011](../adrs/ADR-011-retire-on-device-recognition-remote-only.md) for *customer-facing* compute placement; does not reopen URL-derived tenanting or dual-mode probe defects that ADR-011 fixed.
> **Source brief:** [AltContext Local AI Strategy Session Brief](../assessments/current/AltContext_Local_AI_Strategy_Session_Brief.docx) (31 Jul 2026).
> **Canon validation:** `~/Development/heuristics-canon-research/` — rule IDs cited as `[RULE-ID]` (business-marketing, ml-systems, engineering, security).
> **Audience:** operator (Daniel) for sequencing; agents for what to stop, keep, and reframe.
> **Related active surfaces:** [E15](../epics/v0.4.0/public-demo-launch-readiness-epic.md) · [GTM productization plan](../gtm/altcontext-productization-launch-plan.md) · [FIR commercial face](../epics/v0.5.0/commercial-face-identity-replacement-epic.md) · [context-aware description](context-aware-image-description-roadmap-2026-06-13.md) · [portfolio MVP assessment](../assessments/current/portfolio-quadrant-mvp-strategy-assessment-2026-06-11.md)

---

## 0. Decision in one sentence

**Keep the managed service as the easiest default, add a private local worker as an option, and build the business around the WordPress workflow and trusted records — not around owning a remote GPU.**

Local inference removes model access as a credible moat. It does not remove AltContext. The product remains valuable when it reliably turns replaceable AI outputs into named people, reviewed descriptions, correction history, privacy controls, and reusable WordPress metadata.

---

## 1. Why this roadmap exists

### Market force (what changed)

Capable local machines make private image description, face recognition, and grouping practical for privacy-sensitive and high-volume customers (photographers, agencies, universities, archives, health). Captioning and face models are becoming interchangeable commodities.

### Product force (what did not change)

Most WordPress users still want install, updates, recovery, and support handled for them. Reliable review, saved decisions, provenance, quality testing, and WP-native batch workflows remain hard. Cloud remains useful for zero-install onboarding, shared teams, elastic bursts, uptime, and recovery.

### Explicit non-dependency

Apple M7 Ultra / multi-TB rumour is a **directional signal, not a planning dependency**. Face recognition and grouping already run on far smaller machines. Design for local execution now; do not fund a polished multi-platform desktop app on unconfirmed 2028 hardware.

---

## 2. Target product shape

### One product, several places to run inference

| Mode | Who operates compute | Customer experience | When |
| --- | --- | --- | --- |
| **Managed (default)** | AltContext | Install plugin → connect account → work. Zero extra machine. | Always |
| **Private Worker** | Customer (signed Mac app or managed server package) | Pair worker to WP; images/face data can stay under customer control | After narrow pilot proves paid demand |
| **Hosted burst** | AltContext (metered) | Large libraries, hard images, deadlines, offline local machine | After metering exists |
| **Private server / VPC** | Customer or AltContext enterprise | Enterprise isolation | Only after repeated qualified demand + positive support margins |

**Do not create separate cloud and local products.** One versioned job contract; every worker reports model version, settings, result, confidence where meaningful, and processing history the same way. WordPress remains the main record of people, names, corrections, and editorial decisions.

### Positioning (do not imitate full DAM)

> **DAM-grade identity and alt-text governance for WordPress — without moving the media library into a DAM.**

PhotoShelter/Brandfolder sell shared storage, rights, portals, and collaboration. AltContext sells reviewable identity + alt-text governance *inside* the library the customer already owns.

### Pricing direction

- **Primary charge:** sites, teams, workflow, privacy controls, updates, support (maintained product).
- **Secondary charge:** hosted processing when it creates real variable cost (metered or allowance).
- **Local-compute plan is still paid software** — customer buys workflow/governance/support, not GPU time.

---

## 3. Moat (revised)

Ordered by durability after a clone has the same public models and can copy GPL plugin code:

| # | Moat | Customer-owned? | Notes |
| --- | --- | --- | --- |
| 1 | **Saved human decisions** | Yes | People, accepts/rejects, merges/splits, conflicts, undo — survive model changes |
| 2 | **WordPress-native workflow** | Shared | Media selection, batch review, metadata write, retry, multi-site agency work |
| 3 | **Trust and governance** | Shared | Unknown is valid; export/delete; clear data-flow per mode; no confidence theater |
| 4 | **Reliable operations** | AltContext | Queues, cancel, batch, signed updates, recovery, model routing, health |
| 5 | **Quality system** | AltContext | Maintained test set, hard-case eval, threshold calibration, release gates |
| 6 | **Distribution and reputation** | AltContext | WP.org, agencies, a11y credibility, docs, support |

### Critical correction to prior GTM language

**Customer corrections are mostly not an AltContext-wide network-effect moat.** They are **customer-owned value and switching cost**. Do not build the company moat by quietly appropriating identity labels. Company-wide learning uses licensed evaluation data or explicit privacy-safe opt-in telemetry. Instrument accept/edit for product improvement and support `[AIPX-03]`, but treat the identity graph as the customer's system of record, exportable and deletable `[BOOT-01][CLM-03]`.

What survives cloning is still true: code is not the moat `[STRAT-02]`. What changes is *which* durable assets we claim.

---

## 4. Delta from current active planning — avoid traps

This section is the operational heart of the doc. Each row names **what to change** relative to active/adjacent plans so agents do not waste cycles.

### 4.1 STOP or reverse (traps if continued)

| Current surface | Trap | Required change |
| --- | --- | --- |
| **[ADR-011](../adrs/ADR-011-retire-on-device-recognition-remote-only.md)** "no local recognition models" / "customers do not run their own recognition hardware" as permanent product law | Locks product into remote-GPU identity; conflicts with private-worker demand and privacy positioning | **Supersede customer-facing remote-only.** Keep ADR-011 wins: key-driven tenanting, offline *display* sovereignty, kill URL-derived tenant + dual-mode probe bugs. Replace "remote-only forever" with **managed default + optional private compute**. Write a follow-on ADR when implementing the worker contract. |
| **E14 diagram "GPU Inference Server" as product center** | Makes owning remote GPU the story; invites cost shock and wrong GTM | GPU is **optional burst capacity**, not the product definition. Keep A1 CPU as managed baseline; meter GPU when used. |
| **GTM launch thesis: "curated-accuracy data flywheel" as *the only compounding moat* with proprietary labels** | Quietly re-homing face/caption corrections as AltContext IP; fights privacy promise and export story | **Reframe:** flywheel telemetry = product ops + optional opt-in learning. Identity/corrections = customer-owned. Marketing claim = "improves with *your* corrections," not "our training set grows from your faces." |
| **"All data stays local" marketing before Private Worker ships** | Claim/implementation mismatch `[CLM-03][CLM-04]` | Claim only: reviewable workflow + clear deployment choices. Publish per-mode data-flow page before privacy slogans. |
| **Browser-based production inference** | Hardware drift, version drift, fragile sessions | Out of production path. Worker is signed, versioned, updatable. |
| **Building polished multi-platform desktop worker before paid intent** | Update/signing/support surface before demand `[PROD-03][PROD-05][GTM-01]` | Narrow Mac (or single-platform) proof first; 3–5 orgs; paid pilot gate. |
| **Full self-hosted mandatory stack as only mode** | Excludes non-technical WP audience | Managed remains default; private is opt-in. |
| **Imitating full DAM** | Dilutes WP-native position | Stay governance-of-the-library, not re-host the library. |

### 4.2 DEFER (unnecessary work *now*)

| Work item | Why defer | Resume when |
| --- | --- | --- |
| Multi-OS polished Private Worker (Windows/Linux parity, App Store polish) | Demand unproven; support multiplies | ≥2 paid private pilots + support time within rate card |
| Local captioning / VLM in the worker | Lifecycle + face path first; caption support burden is higher | Worker install/update/recovery proven |
| Customer VPC / private server productization | Support economics unknown | Repeated enterprise RFPs + margin model |
| Opportunistic GPU fleet as roadmap center (see assessments under `docs/assessments/current/*gpu*`) | Useful later as cost/latency tool; not identity | After metering + job routing exist |
| Epic D sovereign sync evolution as near-term priority | Snapshot sync works; zero users; B&B crowding Pearl delivery | After demo + first paid conversion path |
| PG18 upgrade, heavy SaaS ops beyond free-tier minimum | Infra for empty funnel | After Phase 0–1 GTM gates (demo funnel measured) |
| Video / scene-description product epic | Still Oyster research | After still-image context caption proof |
| InsightFace buffalo in production after FIR | License risk | FIR gate: never re-introduce to prod |

### 4.3 REFRAME (keep the work, change the framing)

| Surface | Old frame | New frame |
| --- | --- | --- |
| **E15 public demo** | Prove remote recognition works | Prove **WP workflow + review + identity**; managed mode is the demo default. Do not demo claims that data never leaves the site. |
| **E14 self-hosting** | "Customers self-host recognition" vs "we host everything" confusion | **Operator-hosted managed backend** is internal infra. **Customer private compute** = Private Worker product track (separate). |
| **FIR (YuNet/SFace commercial stack)** | "Replace buffalo for commercial SaaS only" | **Dual purpose:** commercial license for managed **and** packageable CPU-first stack for Private Worker proof. Accelerate FIR relative to GPU detours. |
| **Context-aware description roadmap** | Hosted-only description loop | Description ships first on **managed**; local description is a later worker capability after face worker lifecycle is stable. Contract stays provider-neutral. |
| **Privacy-hybrid / deferred sovereignty** | Post-MVP "embeddings maybe in WP" | Private Worker is the **practical sovereignty path** for privacy-sensitive buyers without rewriting WP into a vector DB. Embedding authority can still minimize remote retention. |
| **SaaS ops / Polar / Clerk** | Meter GPU minutes as the product | Meter **hosted processing** as variable add-on; **plan price** = sites/teams/workflow/support. Free tier still needs conversion hypothesis `[BOOT-06]`. |
| **Plugin GPL / open source** | Fear of clone → cripple plugin | Assume plugin is copyable. Compete on pace, support, eval, integrations, trust. Keep records portable. |

### 4.4 KEEP / accelerate (aligned work — do not cancel)

| Work | Why it still matters under this direction |
| --- | --- |
| **E15 demo URL + unaided human completion** | Managed default must be real; distribution starts here |
| **Roster, workbench, review UX (v0.4.x polish)** | Workflow *is* the product |
| **Export, purge, audit, retention honesty** | Trust moat + CLM compliance of claims |
| **Key-driven tenanting, RLS, offline display** (ADR-011 keepers) | Correct multi-tenant ops without URL-tenant bugs |
| **FIR commercial face pipeline** | License + worker packaging |
| **Golden / bake-off eval harness (VLM + FIR)** | Quality system moat `[EVAL-01][PROV-01]` |
| **GTM Phase 0 measurement (PostHog funnel, Sentry)** | No funnel, no launch `[PROD-01]` — but events must not carry embeddings/PII |
| **Production alt-text workflow & governance epic (v0.5.0)** | Review, approval trail, writeback — center of value |
| **Paid intent interviews (agencies, privacy-sensitive orgs)** | Gate Private Worker investment `[GTM-01][PROD-06]` |

---

## 5. Phased delivery (gated)

Persona timing from GTM plan still holds: quiet plumbing → loud fall window. This roadmap inserts **compute-placement** work without displacing demo/conversion gates.

### Phase A — Contract correction (now)

**Outcomes**

1. Product language: *managed by default, private compute optional*.
2. Inventory docs that assert remote-only forever; mark superseded (this file + ADR-011 note).
3. Define **provider-neutral worker/job contract** (request, result, cancel, retry, model version, provenance, error, health). Schema-first `[SERVE-01][PROV-01][PROV-06]`.
4. Per-mode data-flow draft (what leaves WP in managed vs private vs burst).

**Exit**

- One written contract draft reviewed by operator.
- Public/marketing claims do not overstate locality.

**Do not build** desktop packaging in this phase.

### Phase B — Managed value path (parallel, primary commercial path)

Unchanged critical path from E15 + GTM Phase 0–2, with moat language fixed:

1. Public demo (E15) with Before/After, face+roster, accept/edit, honest low confidence `[AIPX-07][AIPX-10][AIPX-14]`.
2. Skin-tone / hard-case honesty in demos `[AIPX-04][FAIR-02]`.
3. Free tier + accounts + metering for *hosted processing*.
4. Payments; ≥1 unsolicited paid conversion at target price `[PROD-04]`.

**Exit gates:** unaided demo completion; funnel events land; paid conversion falsifier.

### Phase C — Narrow Private Worker proof (next, demand-gated)

1. Package **current production face stack** (YuNet/SFace after FIR gate, or interim commercial-safe stack) as a **signed Mac worker**.
2. Pair to one WP test site.
3. **No local captioning yet.**
4. Same job schema as managed; shared review UI; compatible identity + provenance records.

**Success measures (from brief)**

- Non-technical user installs and pairs without developer help.
- Same test library → compatible records in managed and private modes.
- Interrupted work resumes without lost decisions or duplicate charges.
- **≥2 pilot customers commit money or signed purchase intent** for private processing `[GTM-01]`.
- Support time + hardware requirements fit proposed price `[BOOT-04]`.

**Kill / pivot if:** enthusiasm without paid intent, or support cost > rate floor.

### Phase D — Worker operations hardening

Installation, updates, offline recovery, worker replacement, failed jobs, version drift, consented diagnostics, fallback to hosted burst.

### Phase E — Local description (only after D)

Add local scene-description model; compare quality, speed, energy, support burden vs hosted. Prefer cheapest learning probe before broad platform matrix `[PROD-03]`.

### Phase F — Pricing + enterprise gates

- Price sites/teams/workflow/private deployment/support; hosted processing metered.
- Enterprise VPC only after repeated demand + margin-positive support model.

---

## 6. Architecture principles (binding)

1. **WordPress is the editorial system of record** for people, names, corrections, alt-text decisions, audit history.
2. **Inference is replaceable** behind a stable job API; managed, private, and burst are providers `[SERVE-01]`.
3. **Perceived privacy boundary = enforced boundary** `[CLM-03]` / Principle 10: if UI says private, bytes must not hit AltContext GPU by default.
4. **Unknown is a valid result** for identity and description `[AIPX-07]` / circle of competence `[STRAT-03]`.
5. **Evidence before durable claim:** model version, settings, thresholds travel with every result `[PROV-01][PROV-06]`.
6. **Delete-over-shim for dead dual modes** that recreate tenant-mismatch bugs; do **not** delete the *concept* of customer-local compute when reintroducing it as a first-class Worker.
7. **Greenfield OK for schema**, but export/delete must reach customer identity records and derived artifacts that claim retention `[PROV-10]` when product promises it.

---

## 7. Canon validation (heuristics-canon-research)

Validated against `~/Development/heuristics-canon-research/` (2026-07-31). Material checks:

| Claim in this roadmap | Canon rule | Verdict |
| --- | --- | --- |
| Assume plugin/code is cloneable; moat is not model access | `[STRAT-02]` invert / code not moat | Pass |
| Cheapest learning before polished multi-platform worker | `[PROD-03][PROD-05]` | Pass |
| Paid intent gates Private Worker investment | `[GTM-01][GTM-02]` | Pass |
| Free tier needs conversion hypothesis | `[BOOT-06]` | Pass (inherits GTM) |
| Price workflow/support, not only GPU | `[PROD-11]` second-step test: commodity inference margin flows away | Pass |
| Instrument corrections without stealing identity SoR | `[AIPX-03]` + customer ownership of labels | Pass with reframe vs GTM v1 |
| Provider-neutral job contract | `[SERVE-01][PROV-06]` | Pass |
| Privacy claim must match implementation | `[CLM-03][CLM-04][CLM-05]` | Pass — blocks premature "all local" copy |
| GPU fleet before load numbers | `[ARCH-08][ARCH-09]` boring/single-machine first; quantify load | Pass — defers GPU-as-center |
| Unknown / abstention in face+caption | `[AIPX-07][STRAT-03]` / CAL-02 spirit | Pass |
| Outcome roadmap over feature timeline | `[PROD-07]` | Pass — phases gated on outcomes |
| Do not staff for a one-time hardware spike | `[STRAT-08]` | Pass — M7 Ultra non-dependency |
| Hostile landlord / multi-home (WP.org not sole channel) | `[BOOT-07]` | Pass — inherits GTM §11 |
| Eval before model thrash | `[EVAL-01][AIPX-15]` | Pass — FIR + golden harness kept |

### Explicit tensions resolved (do not re-litigate without new evidence)

| Tension | Resolution |
| --- | --- |
| ADR-011 remote-only vs local AI brief | **Remote-only was the right *near-term simplification* for dual-mode bugs.** Permanent *product* remote-only is wrong. Keep simplification for managed path; add Worker as separate product track with same contract. |
| GTM "proprietary flywheel" vs "customer-owned labels" | **Instrument accept/edit for product metrics and opt-in learning.** Do not treat face identity graph as company training corpus without consent. |
| E14 GPU target vs CPU A1 reality | CPU managed path is fine; GPU is burst/premium, not identity. |
| Portfolio Pearl = identity-context | Still true; Private Worker *strengthens* privacy positioning of that Pearl for agencies that cannot send faces off-site. |

### Disconfirmers (kill or pivot criteria) `[STRAT-02][PROD-04]`

1. Privacy-sensitive segments show **no paid intent** for private compute after 3–5 qualified demos → keep managed-only; stop Worker polish.
2. Managed accept-rate / paid conversion **flat vs generic alt-text plugins** → identity-context thesis fails; stop deepening recognition UX before description proof.
3. Support hours per private pilot **exceed rate floor** → raise price, narrow hardware tiers, or kill Worker.
4. Managed and private modes **diverge on identity outcomes** on shared golden set → freeze feature work; fix contract + model pin + shared eval before any sales claim of parity.

---

## 8. Documentation corrections checklist

From the strategy brief §10 — treat as a work queue under Phase A:

- [ ] Feature list: reconcile "hosted detection" vs "Self-hosted FastAPI" — name supported modes explicitly.
- [ ] Rename customer-facing "self-hosted" to **Private Worker** (or equivalent) if desktop pairing is the model; "self-hosted" implies CLI ops.
- [ ] Confirm production face stack names (InsightFace/ArcFace vs YuNet/SFace) before publishing.
- [ ] Separate **shipped / tested / beta / planned** features; stop calling the product "alt-text complete" while recognition is the live milestone.
- [ ] Document exactly which fields leave WordPress in each mode (contradiction: "never leave server" vs "edits flow to hosted service").
- [ ] GDPR/CCPA: keep workflow features; legal claims need review; state customer lawful-use duties for face recognition.
- [ ] Mark ADR-011 customer remote-only permanence as **superseded by this roadmap** for product direction (implementation ADR still required).
- [ ] Update GTM §2 moat language on next GTM edit pass (customer-owned corrections).

---

## 9. Suggested near-term operator sequence (4–6 weeks)

| Order | Action | Owner type |
| --- | --- | --- |
| 1 | Accept this roadmap as active product direction | Operator |
| 2 | Phase A: worker contract draft + data-flow matrix | Planning / backend |
| 3 | Finish E15 demo path (managed) | Implementation |
| 4 | Continue FIR commercial face (feeds managed + worker) | Implementation |
| 5 | GTM Phase 0 funnel + honest demo claims | GTM |
| 6 | Interview 3–5 privacy-sensitive orgs for private-compute paid intent | Operator |
| 7 | Only then: Mac worker thin proof (Phase C) | Implementation |

---

## 10. Out of scope for this document

- Detailed OpenAPI of the worker contract (Phase A deliverable).
- Legal opinion on GPL vs native-worker licensing (brief: obtain counsel before relying on dual licence).
- Task plans / epic IDs for Private Worker (author after Phase B gates and pilot demand).
- Implementation of FIR, E15, or GTM slices (owned by existing epics).

---

## 11. Sources

**Primary**

- `docs/assessments/current/AltContext_Local_AI_Strategy_Session_Brief.docx` (31 Jul 2026)

**Active plans reconciled**

- `docs/adrs/ADR-011-retire-on-device-recognition-remote-only.md`
- `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md`
- `docs/epics/v0.3.1/self-hosting-epic.md`
- `docs/epics/v0.5.0/commercial-face-identity-replacement-epic.md`
- `docs/gtm/altcontext-productization-launch-plan.md`
- `docs/roadmaps/context-aware-image-description-roadmap-2026-06-13.md`
- `docs/roadmaps/recognition-privacy-hybrid-roadmap-2026-03-06.md`
- `docs/roadmaps/roadmap-saas-operations.md`
- `docs/assessments/current/portfolio-quadrant-mvp-strategy-assessment-2026-06-11.md`
- `docs/deferred-features/sovereignty-and-compliance.md`

**Canon**

- `~/Development/heuristics-canon-research/lexicons/business-marketing.md`
- `~/Development/heuristics-canon-research/lexicons/ml-systems.md`
- `~/Development/heuristics-canon-research/lexicons/engineering.md`
- `~/Development/heuristics-canon-research/PRINCIPLES.md`
