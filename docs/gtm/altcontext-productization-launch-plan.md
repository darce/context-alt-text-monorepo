# AltContext Productization & Launch Plan

> **Status:** Planning (durable, decomposable). **Authored:** 2026-07-09. **Merged + canon-reviewed:** 2026-07-09.
> **Supersedes:** the split `00`–`05` GTM docs (merged into this single file after a heuristics-canon review pass).
> **Scope:** Take AltContext from "deployed backend + prototype plugin" to "self-serve SaaS with paying WordPress customers." Connects the already-planned *technical* launch (E15 demo, E16 SaaS-ops) to the *commercial* launch (demo funnel, user management, CRM, payments, marketing, moat, GTM, WP.org).
> **Audience:** operator (Daniel) for decisions; junior/offload agents for the Implementation Slices (§14).
> **Citations:** `[GTM-01]` = [business-marketing lexicon](https://github.com/darce/heuristics-canon/blob/main/lexicons/business-marketing.md); `[DATA-14]` = [engineering lexicon](https://github.com/darce/heuristics-canon/blob/main/lexicons/engineering.md); `[COL-10]` = [design-aesthetics lexicon](https://github.com/darce/heuristics-canon/blob/main/lexicons/design-aesthetics.md). IDs are stable.

---

## 0. What the canon review changed (changelog)

This revision was reviewed against all three heuristics-canon lexicons. Material changes vs. the first draft:

| # | Finding | Canon | Fix |
|---|---|---|---|
| C1 | Leaned on WP.org as *the* channel; ignored platform-landlord risk across WP.org, Clerk, Polar, OCI-free | `[BOOT-07]` hostile-landlord | Added §11 multi-homing/portability posture; WP.org is *a* node, not the only one |
| C2 | Customer contact path (email list) implicitly left inside vendors | `[BOOT-01]` own before polish | §6 makes the owned email list an in-house system of record |
| C3 | Free tier had no stated conversion trigger | `[BOOT-06]` freemium kill switch | §3/§7 free tier now carries an explicit conversion hypothesis |
| C4 | Pricing lacked a floor concept; KPI risked reach-vanity | `[BOOT-04]` rate floor, `[BOOT-08]` payers-per-1k | §7 pricing floor; §13 north-star is paying conversions |
| C5 | CRM + data-ownership split was undocumented (operator asked) | `[DATA-14][DOM-04][RES-11][ARCH-02][API-10]` | New §6 field-by-field ownership table + integration rules |
| C6 | Facial-recognition accuracy across skin tones unaddressed | `[COL-10]` inclusive grade test (doubly binding for accessibility) | §5/§10 add skin-tone accuracy as a trust + moat requirement |
| C7 | "conviction vs falsification" / "novelty vs precision" stated loosely | canon §8 cross-source tensions | §2/§10 cite the canon's explicit resolutions |

All rule IDs cited in this doc were verified present in the canon.

---

## 1. What already exists (do not re-plan)

| Layer | State | Source of truth |
|---|---|---|
| Recognition backend | Deployed, HTTPS, authenticated, tenant-isolated, rate-limited (in progress) | E15 epic; `api.altcontext.com` |
| Infra | OCI A1.Flex free tier (4 ARM cores / 24GB), Caddy TLS, Postgres/pgvector, systemd compose | `infra/oci/` |
| API-key minter | `/admin` JSON router (`routers/admin.py`) + HTML console (`admin_console.py`) — primitive, operator-only | recognition service HTTP layer |
| Demo topology | `demo.altcontext.com` = WP+MariaDB containers on the OCI VM behind Caddy, as one real tenant | E15-28 |
| Identity model | Explicit tenant + key minted via `manage_api_keys`; **never URL-derived/JIT** | E15-24 |
| Build-vs-buy stack | Decided (buy): auth = WorkOS/Clerk · billing = Polar · errors = Sentry · analytics = PostHog · email = Resend | `roadmap-saas-operations.md` (E16) |
| WP plugin | Prototype: facial recognition + roster/curation, sovereign local-read | `apps/prototype-wp-alt-context/` |
| Marketing site | Brittle Fly.io Node/Prisma stack (256MB, crashes under load) | `altcontext-marketing-monorepo/` |
| Business DB plan | Two-DB model, shared `tenant_id`; `leads` table already envisioned | `roadmap-saas-operations.md` |

**Consequence:** "build or buy" for user management is *already answered — buy* — and it's the right call (§6). This plan adds the commercial layer and the data-ownership detail, not a vendor re-litigation `[STRAT-05]`.

---

## 2. Launch thesis & moat

**Thesis:** Ship a self-serve **free tier** (with a stated conversion trigger `[BOOT-06]`) behind a **frictionless per-prospect demo**; convert on **trust in caption accuracy** and **founder credibility**; defend with a **curated-accuracy data flywheel** a coding-agent clone cannot copy on day one.

**The code is not the moat — assume you are already cloned** `[STRAT-02]`. Four things survive cloning, by durability:

1. **Curated-accuracy data flywheel (the only compounding moat).** Every human accept/edit of a caption or face-name is a proprietary label; a clone starts at zero `[AIPX-03][PROD-11]`. Make "improves with your corrections" a *demonstrable* claim. This is why the flywheel telemetry ships first (§9).
2. **Trust in the outcome.** Accessibility captions carry legal/reputational stakes; a wrong caption costs more than silence `[AIPX-07]`. Winning posture = calibrated honesty: say "not sure," one-click correction, no confidence theater `[AIPX-10][AIPX-14]`. This includes **accuracy parity across skin tones** — for a face product this is both an ethics floor and a trust differentiator `[COL-10]`.
3. **Founder-led credibility.** The persona's leverage isn't astrology — it's "product engineer with a visible thesis / accessibility-as-architecture." That thesis, published repeatedly, *is* distribution `[STRAT-05][GTM-08]`. A clone-farm cannot hold the thesis in public.
4. **Channel position (WP.org) + community** — earned review-by-review; a moat that compounds but is landlord-dependent (§11) `[GTM-05]`.

**Canon tension resolutions (explicit):** run *positioning/values on conviction*, *features/funnels on falsification* — canon §8 (`[STRAT-07]`↔`[PROD-04]`). First exposure may be *novel*; the *output* is never sloppy in a trust product — canon §8 (`[GTM-08]`↔`[AIPX-07]`).

> **Synthesis:** community + trust are *outputs*; the *engine* is flywheel + honest-accuracy + public thesis, distributed through WP but not captive to it. Build the engine; community is the exhaust.

---

## 3. Launch phases (sequenced, gated)

Persona timing = planning cadence, not prophecy: don't force a grand launch while overheated (Jul–Aug 2026); **Sep–Oct 2026 is the strongest publish-case-studies / ship-demos / reactivate-network window.** Quiet plumbing in summer; loud launch in fall.

- **Phase 0 — Demo funnel + measurement (Jul–Aug, quiet).** Public `demo.altcontext.com` (E15-28) with Before/After + face proof; per-prospect demos + short-slug URLs (§5); PostHog + Sentry wired (§9 — *no funnel, no launch* `[PROD-01]`); landing reskin (§8, 1 week max). **Gate:** a non-Daniel human completes the demo unaided; events land in PostHog.
- **Phase 1 — Self-serve free tier + accounts (Aug–Sep, quiet).** Clerk live; `app.altcontext.com` dashboard; business API + `acx_business` DB; `/admin` minter consolidated behind it (§6). Free tier soft-metered with a stated conversion trigger `[BOOT-06]`. **Gate:** 3–5 hand-recruited betas self-onboard and generate real captions `[PROD-06]`.
- **Phase 2 — Payments + paid conversion (Sep, start loud).** Polar checkout + webhooks → plan enforcement. Validate price with paid intent before scaling `[GTM-01][GTM-02]`. **Gate:** ≥1 *unsolicited* paid conversion at target price — the real PMF falsifier `[PROD-04]`.
- **Phase 3 — Launch motions + WP.org (Sep–Nov, loud).** WP.org submission + freemium split (§11); founder build-in-public + network activation (§10); community surface feeding the flywheel. **Gate:** WP.org approved; first *inbound* signups.
- **Phase 4 — Compounding (Nov+).** Retention, onboarding funnels, OAuth, referrals, case studies. Persona caution: stabilize, don't rebrand under stress `[STRAT-08]`.

---

## 4. Minimal-friction path to first paying clients

Two shapes, run in **parallel**:

| Shape | Friction | For | When |
|---|---|---|---|
| **Concierge** (do-it-for-them) | A DM + manual `/admin` provision + a Polar payment link | The 5–15 warm contacts with image-heavy WP sites *today* | **Now** `[GTM-03][GTM-01]` |
| **Self-serve** | Card → key → plugin, no human | Long-tail WP owners via WP.org + content | Phase 2+ |

**The fastest dollar is concierge to a warm contact.** Self-serve machinery makes the *second hundred* cheap; concierge makes the *first five* real and teaches pitch/price/objections `[PROD-03]`. **Do not gate the first sale on the billing system.**

---

## 5. Demo provisioning — per-prospect demos with short-slug URLs

**Reconcile the operator's "abbreviated UUID in URL" with E15-24 ("never URL-derived identity"):** the short ID is a **public lookup slug for a demo instance — never a tenant identity, never a credential.** Server-side it maps to an explicitly-minted `(tenant_id, api_key)`; the browser never sees the key.

```
https://demo.altcontext.com/x/7fQ2ab   ← slug: opaque, ~7 base58 chars, random (NOT base62(tenant_uuid))
   Caddy → demo router → demo_instances lookup → {tenant_id, api_key ref, seed, branding}
```

- Slug is **capability-free** (view a sandbox, nothing else), **random** (no identity enumeration), **rate-limited**, **auto-expiring** (~30d), **quota-capped**, **revocable** `[AIPX-09]`. 58⁷ ≈ 2×10¹² space → un-enumerable under rate limits, still short enough to paste in a DM.

**Two modes, shared plumbing:** (a) evergreen public demo at the root (E15-28); (b) per-prospect demo at `/x/<slug>` seeded with the prospect's own images — the concierge weapon `[GTM-09]`: "I built you a private sandbox with your gallery's photos."

**Do NOT spin one WP container per prospect** (breaks the OCI free tier + bulkhead SLO). **One demo WP instance, tenant-switched by slug**; per-prospect state (seed, tenant) lives in the backend + a small `demo_instances` registry.

```sql
create table demo_instances (
  slug text primary key,            -- ~7 char base58, random, NOT derived from tenant uuid
  tenant_id uuid not null,          -- explicitly minted, E15-24 compliant
  api_key_ref text not null,        -- reference/hash, NOT the raw key
  label text, seed_bundle text not null default 'default',
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,  -- default +30d
  recognition_quota int not null default 200, recognition_used int not null default 0,
  branding_json jsonb, revoked boolean not null default false
);
```

**Operator ergonomics:** `make provision-demo LABEL="Acme Gallery" SEED=acme` → mints tenant+key via the existing `/admin` minter, seeds media, inserts the slug row, prints the URL. `make expire-demo SLUG=…` + a daily expiry/quota job.

**The demo must demonstrate the moat, not just work:** Before/After caption; face-recognition + roster naming; **accept/edit affordance** (the flywheel interaction `[AIPX-08][AIPX-11]`); honest low-confidence state `[AIPX-07][AIPX-10]`; and visibly correct results **across skin tones** `[COL-10]`.

**Security checklist (before public exposure):** random slug (no identity leak) · view-only capability · demo key rate-limited/quota-capped (E15-1) · demo origin in CORS allowlist · WP containers CPU/mem-limited (bulkhead, E15-28) · expired slug → "demo ended, sign up" CTA · raw key never reaches browser or slug table.

---

## 6. User-management infrastructure, CRM, and data ownership

This is the section the operator asked to expand. **Two questions: (a) what to build vs buy, (b) which DB fields stay in-house vs outsourced, and how to integrate a CRM.**

### 6.1 Build vs buy — the line

Buy identity, billing, email, telemetry (commodity, security-critical, zero differentiation `[STRAT-02]`). Build the tenant/plan/key/usage/flywheel logic (it encodes your product rules and the moat). **Keep the `/admin` key-minter in-house** — API-key lifecycle *is* product-specific.

- **Auth vendor: Clerk (recommended) over WorkOS.** Clerk = drop-in self-serve B2B UI, lowest time-to-first-login — right for chasing long-tail WP owners. WorkOS = SSO/SAML-first; adopt only if a real enterprise lead demands it (don't pre-pay for a market you don't have `[STRAT-03][STRAT-08]`). Clerk→WorkOS later is a bounded migration.

### 6.2 The ownership principle (canon-grounded)

Your **business DB is the hub; `tenant_id` (UUID) is the universal join key.** The governing rules:

- **Name one system of record per datum; never dual-write** — derive the second copy from the first's change log `[DATA-14]`.
- **Reference external aggregates by ID only** (`clerk_user_id`, `polar_customer_id`, `crm_contact_id`) — don't copy their whole record into yours `[DOM-04]`.
- **Never reach into a vendor's DB, and never let a vendor read yours** — integrate via API + webhooks; single writer owns each table `[RES-11][ARCH-02]`.
- **Translate at the boundary** — your schema/API shapes are yours; don't leak Clerk/Polar field names into your model `[API-10]`.
- **All inbound webhooks idempotent** — dedupe on event id; keep an audit log `[API-02][RES-01]`.
- **Own a direct contact path** — the customer email list (with consent) is an in-house SoR, so no landlord can sever your reach `[BOOT-01][BOOT-07]`.
- **Record the ownership map as an ADR** `[ARCH-07]`.

### 6.3 Field-by-field: in-house vs outsourced

| Datum | System of record | Your DB stores | Rationale |
|---|---|---|---|
| `tenant_id` (UUID) | **You (business DB)** | canonical key | universal join across every vendor `[DOM-04]` |
| Plan / entitlements / quota | **You** | plan, limits, enforcement flags | product logic; vendors *notify*, you *decide* |
| API keys (hashed) + scopes + rotation | **You** (the `/admin` minter) | hash, scope, tenant_id | product-specific security; keep in-house |
| Usage / metering | **You** | daily counters per tenant | billing-truth SoR |
| **Flywheel labels** (accept/edit, corrections, face confirmations) | **You** | all of it | **the moat — never outsource** `[BOOT-01][PROD-11]` |
| GDPR consent records | **You** | consent state + scope + timestamp | legal SoR |
| **Customer email + contact consent** | **You** (cached from Clerk, with consent) | email, consent flag | owned direct contact path `[BOOT-01][BOOT-07]` |
| Password / session / MFA / OAuth tokens | **Clerk** | *nothing* (only `clerk_user_id`) | never store credentials `[STRAT-02]` |
| Name / avatar / profile PII | **Clerk** (opt. CRM) | optional cached projection | not product-critical; by-ID `[API-10]` |
| Card / payment method / invoice / tax | **Polar (MoR)** | *nothing sensitive*; `polar_customer_id` | never store PAN; MoR owns VAT/tax |
| Subscription status | **Polar** → projected to you | cached status + `current_period_end` | drives entitlement; derived from Polar's webhook stream `[DATA-14]` |
| Product/behavioral events, funnels, replay | **PostHog** | `posthog_distinct_id` link only | analytics store, not SoR |
| Errors / traces | **Sentry** | *nothing* (correlation_id links) | diagnostics store |
| Sales pipeline: notes, stage, deal history, email threads | **CRM (if adopted)** | `crm_contact_id` link | relationship data, not product SoR |
| Transactional email send/deliverability | **Resend** | optional send-status via webhook | deliverability infra |

**One-directional derivation, never dual-write** `[DATA-14]`: identity flows Clerk→you; billing flows Polar→you; you never write auth/payment *truth* back. Recognition data trusts `tenant_id` set by the auth middleware after it validates the key against the business DB (the two-DB / shared-UUID model already in `roadmap-saas-operations.md`).

### 6.4 CRM — what makes sense here, and when

**Now (Phase 0, <~20 leads): do NOT buy a CRM.** The `leads` table already planned in the business DB + a Notion/Airtable board is the correct CRM at this volume. Buying one now is automating a mess / swinging at a non-fat-pitch `[OPS-05][STRAT-04]`.

**When concierge follow-ups exceed memory (~Phase 2–3): adopt a lightweight *relationship* CRM** (the motion is founder-led/network selling, not enterprise pipeline):

| CRM | Fit | Note |
|---|---|---|
| **Attio** (recommended) | API-first, flexible data model, clean webhooks, free tier | integrates with the business DB via `tenant_id`; best for a technical founder who wants product↔CRM sync |
| **Folk** | relationship/network-oriented, lightweight | good for warm-network selling; shallower API |
| **HubSpot free** | powerful free CRM + email/marketing bundled | heavier, upsell-pressured; pick if you want marketing automation too |
| *Avoid* Salesforce / Pipedrive | enterprise pipeline heft you don't need | over-tooling `[OPS-05]` |

**Integration direction (canon-safe):** business DB is SoR for tenant/plan/usage; push a *projection* (`tenant_id`, plan, signup date, usage tier, lifecycle stage) into the CRM via its API on lifecycle events. Relationship notes/threads stay CRM-only. Product facts flow **DB→CRM one-way**; relationship facts are **CRM-only**. **No field is written in both** `[DATA-14]`. The CRM never reads your DB directly; it receives events from your business API `[RES-11]`.

---

## 7. Payments & the money pipeline

The vendor pieces were chosen (Clerk, Polar); the *connected flow from stranger to provisioned paying tenant* was missing. Here it is:

```
Stranger → "Start free" (site / WP.org)
   → Clerk signup ──webhook user.created──► Business API: create tenant (plan=free)
        → Dashboard (app.altcontext.com): API key + install steps + usage
             → install WP plugin, paste key → first caption → PostHog "activated"
                  → hits free cap / wants faces-at-scale  [BOOT-06 conversion trigger]
                       → Polar checkout ──webhook subscription.active──► Business API:
                            plan=pro, raise quota + rate tier, Resend receipt
```

**Business API is the single authority** for tenant lifecycle; auth + billing vendors notify via idempotent webhooks `[API-02]`; recognition trusts tenant context post-validation. **Consolidate the two key surfaces** (OCI `/admin` + local `/admin`) to one authority: business API owns key *policy*, the recognition minter is the *mechanism* `[OPS-01][ARCH-02]`.

**Free-tier conversion hypothesis (required)** `[BOOT-06]`: *Free = 100 images/mo + 1 key + community support; the forcing function to Pro is (a) the monthly image cap on an active site, or (b) wanting roster-scale face recognition across many photos.* If, in practice, neither pushes upgrades, the free tier is miscalibrated — treat that as a falsifier, not a mystery.

**Pricing:** hold `$0 / $19 / $49` as a *hypothesis*, not a validated price.
- Charge the real number before scaling tiers `[GTM-01]`; measure checkout reach `[GTM-02]`.
- Respect a **rate floor** — don't price where you'd resent the work after fees; below the floor the asset burns out `[BOOT-04]`.
- Test an **agency/multi-site tier** anchored on compliance value before assuming $49 is the ceiling; **repackage, don't discount** `[STRAT-11]`.

**Minimal-friction launch options (ranked by time-to-first-dollar):** (A) concierge + Polar payment link — *days*, works today, do first; (B) public Polar link + manual provision — ~1 week bridge; (C) full self-serve — the scale motion. Don't gate the first sale on C `[PROD-03]`.

**Onboarding = activation.** Optimize signup → key → install → **first accepted caption**. Show the API key *and* copy-paste WP install steps on one screen (highest-drop step); Resend welcome email with 3-step setup + demo link; fire `activated` on first caption, nudge at 24h `[PROD-01][AIPX-02]`.

---

## 8. Marketing site direction (time-boxed: 1 week, reskin only)

**D6:** reskin `altcontext.com`; **kill the brittle Fly.io Node/Prisma analytics backend** (it crashes at 256MB); serve **static/edge-hosted** + PostHog. The moat is not the website.

**Message hierarchy:** outcome not mechanism → Before/After hero → Us-vs-Them → face-recognition novelty → trust `[GTM-07][GTM-08]`.

```
┌───────────────────────────────────────────────────────────────────────┐
│ AltContext         Features  Pricing  Docs            [ Start free ]   │
├───────────────────────────────────────────────────────────────────────┤
│  ALT TEXT THAT KNOWS WHO'S IN THE PHOTO.                               │ ← H1: outcome + novelty
│  Accurate, accessible, audit-ready image descriptions for WordPress.  │
│  [ Try the live demo → ]   [ Start free ]                             │ ← demo = primary CTA
│  ┌──────────── BEFORE / AFTER (hero proof) ─────────────────────────┐ │
│  │ BEFORE     alt=""                        ← inaccessible          │ │
│  │ GENERIC AI "a group of people standing"  ← vague, no names       │ │
│  │ ALTCONTEXT "Maria Chen and Devon Ross    ← named, roster-aware,  │ │
│  │             at the 2026 Gala"               audit-ready          │ │
│  └──────────────────────────────────────────────────────────────────┘ │
├───────────────────────────────────────────────────────────────────────┤
│ US vs THEM                                                             │
│  Generic captioners           │ AltContext                            │
│  ─ "a group of people"        │ ✓ Names people from YOUR roster       │
│  ─ never says "not sure"      │ ✓ Says "not sure" instead of bluffing │
│  ─ generic, per-image         │ ✓ WCAG / audit-ready output           │
│  ─ no WP workflow             │ ✓ Learns your accept/edit corrections │
│                               │ ✓ Native WP media-library workflow    │
├───────────────────────────────────────────────────────────────────────┤
│ FACE RECOGNITION + ROSTER (shown, not told)                           │
│  [photo] → [faces boxed] → [matched to roster names]                  │
│  Build a roster once. Every future photo names the right people —     │
│  accurately across every skin tone. Sovereign local-read: you curate. │ ← COL-10 + privacy
├───────────────────────────────────────────────────────────────────────┤
│ HOW IT WORKS  1 Install → 2 Paste key → 3 Captions appear             │
│ TRUST  accuracy you can audit · accessibility-as-architecture · founder│
│ PRICING  Free / Pro $19 / Business $49  (hypothesis, §7)              │
│ FINAL CTA  [ Try the live demo → ]   [ Start free ]                   │
└───────────────────────────────────────────────────────────────────────┘
```

**Content rules (non-negotiable):** never bluff confidence — the "says 'not sure'" line is a trust feature `[AIPX-07][AIPX-14]`; disclose AI early `[AIPX-13]`; **"Try demo" outranks "Start free"** above the fold (the demo is the argument, needs no signup). Every CTA/section is a PostHog event `[PROD-01]`.

**Build notes:** static host; reuse brand assets, retire the Fly.io backend (§9). When building, consult the **design lexicon**: line measure 45–75 cpl `[TYPE-01]`, one modular type scale `[TYPE-05]`, value hierarchy before hue `[COL-04]`, and — for the Before/After sample imagery and the recognition demo — **test across skin tones** `[COL-10]`.

---

## 9. Analytics & observability

**Two jobs, don't conflate:** PostHog = product analytics (funnels, replay, flags); **Sentry** = error/issue tracking (the operator's "sentinel" = Sentry); existing JSON logs + `/health`/`/ready` stay. **Retire the hand-rolled Fly.io analytics backend** — PostHog's free tier (1M events/mo) replaces it `[OPS-05]`.

**Instrument the north-star funnel** end-to-end:
```
marketing_page_view → cta_click{demo|start_free} → demo_started → signup_completed
  → api_key_created → plugin_first_caption (ACTIVATION)
     → caption_accepted / caption_edited{edit_distance,confidence,content_type} (FLYWHEEL)
        → upgrade_started → subscription_active (REVENUE)
```

**The flywheel events are the most important logs you will ever write** — they are the moat's telemetry `[AIPX-03]`. Slice accept-rate by content type / tenant / confidence / **skin-tone cohort** to catch what the aggregate hides `[AIPX-04][COL-10]`.

**Sentry:** backend + frontend SDKs; bind the E15 `correlation_id`; release-tag by plugin version; page the operator only on auth/billing webhook failures, 5xx spikes, new-release regressions `[OPS-04]`.

**Privacy (brand-critical):** never send image content, face embeddings, or PII to PostHog/Sentry — events carry ids/counts/plan/cohort only `[SEC-06]`. Respect GDPR consent. Session replay on marketing + dashboard only, never media/roster screens. Prefer EU-hosted PostHog for data residency. A face product that leaks analytics data destroys the trust moat in one incident `[STRAT-02][AIPX-09]`.

**Phase 0 minimum (non-negotiable before launch):** PostHog funnel down to `plugin_first_caption` + the two flywheel events; Sentry on backend + plugin with correlation-id linkage.

---

## 10. Launch strategy using your social network

Four moves, in order — do not skip to Move 3.

- **Move 1 — Concierge the warm tribe (NOW).** List 10–30 people who run/serve image-heavy WP sites (galleries, event orgs, publishers, photographers, membership sites). Mint each a per-prospect demo (§5) seeded with *their* images; DM the private link `[GTM-09]`. First message is a **soft CTA, not a Calendly**: "I built you a private AltContext demo with your gallery's photos — worth a look? No signup" `[GTM-10]`. Goal: 5 real conversations, 1–2 paid concierge customers, and the objection list. Paid intent is the only validation `[GTM-01]`.
- **Move 2 — Build in public (ongoing).** Run the persona's ship-publicly formula on channels you already have (`darce.xyz`, X/LinkedIn): Before/After examples; "a caption my tool got *wrong* and how honest-confidence caught it" (lead with fallibility — it's the trust play `[AIPX-07]`); short accessibility-as-architecture essays. Every post drives to the live demo, not a pricing page `[GTM-08]`. Content is promotional labor for the owned funnel — make it sell the owned product `[BOOT-02]`.
- **Move 3 — WordPress-native launch (Phase 3).** WP.org submission (§11); post in WP accessibility spaces + agency contacts; the WP.org listing is the ranking node — resource it `[GTM-05][GTM-06]`.
- **Move 4 — Outbound to reachable niches (Phase 3–4).** Only after Moves 1–3 taught you the pitch: personalized outbound (research × personalization × relevance, soft CTA, rotate format on silence `[GTM-09][GTM-11]`), 2–4× pipeline multiple `[GTM-12]`.

**Anti-pattern:** a Product-Hunt "grand launch" as the *primary* plan — a spike is not a business model `[STRAT-08][STRAT-09]`. Use launch events to *amplify* Moves 1–3.

**Conviction vs falsification** (canon §8): hold positioning/values on conviction through backlash `[STRAT-07]`; let features/funnels be killed by evidence `[PROD-04]`. **Under stress, pivot the tactic, not the identity** — the persona's failure mode is rebranding/abandoning under heat.

---

## 11. WordPress marketplace + platform-landlord posture

**Two "marketplaces" — target the free one:** the **WordPress.org plugin directory** (canonical, bundled into every WP install's "Add New Plugin"; GPL, free, human-reviewed) is the distribution channel. Commercial plugin markets are optional/later.

**Freemium split (D5 — recommended yes):** free **GPL plugin** in the directory that talks to your **paid recognition API**. Plugin (client) is copyable; the *service + data flywheel* is not — this aligns the moat and is the accepted WP model (Yoast/Jetpack) `[PROD-09]`. Every free tier states its conversion hypothesis `[BOOT-06]` (§7).

**Bake WP.org review requirements in NOW, not at submission** `[PROD-09]`:
- GPLv2+ compatible license.
- **Disclose the external API call + get consent + document what's sent** — the #1 rejection reason for SaaS-backed plugins; also satisfies `[AIPX-13]` and §9 privacy.
- Genuinely usable free tier (no crippled-tease patterns).
- Security hygiene: sanitize/escape/validate all I/O, nonces, no code exec (hold your PHP guidelines).
- `readme.txt` in WP format (tested-up-to, stable tag, screenshots, FAQ) — this *is* your directory landing page; treat as marketing copy `[GTM-07]`.
- Clean install, no fatal errors.

**Submission sequence:** harden → write `readme.txt` → submit → resolve the phone-home disclosure thread fast → SVN commit + tag + screenshots → seed initial reviews from Move-1 customers `[GTM-05]`.

**Platform-landlord posture (the fix for C1)** `[BOOT-07]`: WP.org, Clerk, Polar, and the OCI *free* tier are all landlords who can change terms or reclaim capacity. Mitigations, sized to a bootstrap (multi-home the masters, not everything, before you need to):
- **Own the customer email list in-house** (§6) so no listing removal severs your reach `[BOOT-01]`.
- **WP.org is a channel, not the channel** — Moves 1, 2, 4 exist so a delisting doesn't zero the funnel.
- **Keep provisioning reproducible from the repo** (already the E15-28 rule) so the OCI free tier is replaceable, not a snowflake — if Oracle reclaims it, redeploy elsewhere.
- **Vendor exit cost is bounded by the by-ID design** (§6): swapping Clerk or the CRM touches reference IDs, not your SoR.

---

## 12. Risks & falsifiers (invert the plan) `[STRAT-02][PROD-04]`

| Bet | What kills it | Early disconfirmer |
|---|---|---|
| Accuracy-trust is a moat | Users just want *any* fast alt text | Low accept-rate delta vs. generic in demos |
| Flywheel compounds | Corrections don't generalize | Flat per-tenant accept-rate over weeks (§9) |
| Skin-tone parity holds | Recognition worse on some tones | Cohort accept-rate gap `[COL-10]` |
| Founder thesis distributes | Content gets no traction | Move-2 posts → zero demo clicks |
| WP.org channel | Rejected for phone-home; or delisted | Review rejection; or landlord shock `[BOOT-07]` |
| Price holds | No unsolicited pay at $19 | Move-1 interest, no paid intent `[GTM-01]` |
| Free tier converts | Free users never hit the trigger | Upgrades ≈ 0 despite active free sites `[BOOT-06]` |

If a disconfirmer fires, change the falsified assumption and keep shipping; don't rebrand the identity `[STRAT-08]`.

---

## 13. Decision log

| # | Decision | Recommendation | Status |
|---|---|---|---|
| D1 | Auth vendor | **Clerk** (WorkOS only if early enterprise SSO) | operator to confirm |
| D2 | Short demo URL | server-side lookup slug, never the credential | **settled** (§5) |
| D3 | Dashboard hosting | OCI-colocated; Vercel if deploy friction bites | operator |
| D4 | Pricing | hold as hypothesis; validate with paid intent; respect rate floor | operator |
| D5 | WP freemium split | **yes** — free GPL plugin + paid API | **settled** (§11) |
| D6 | Marketing rebuild | reskin landing only; kill Fly.io backend; static + PostHog | operator |
| D7 | Launch timing | quiet plumbing summer; loud launch Sep–Oct | operator |
| D8 | CRM | none now; **Attio** when concierge volume forces it | operator (§6.4) |
| D9 | Data ownership map | in-house SoR = tenant/plan/keys/usage/flywheel/consent/email; ref vendors by ID | **settled** (§6.3), write ADR `[ARCH-07]` |
| D10 | Naming / positioning | category = **"Verified Alt Text"**; method = **"The Curated-Accuracy Method"** (Roster → Recognize & Flag → Curate); method is a supporting asset, **not** the H1 tagline | **settled** — see `positioning-canon-rules-and-naming.md` `[GTM-14..16]` |

> **Companion docs:** `positioning-canon-rules-and-naming.md` (naming + proposed canon rules GTM-14..16) · `decomposition-ap1-ap2.md` (AP-1/AP-2 atomic sub-slices) · `offload-brief-ap7-concierge.md` (first offload lane).

**North-star KPI:** weekly **captions accepted** (value delivered) and **paying conversions** — not signups or follower reach `[GTM-06][BOOT-08]`. Activation = % of signups generating ≥1 caption in 24h.

---

## 14. Implementation Slices (offload-ready)

Each slice has a self-contained objective + a verification. **`Ready?`** column: **Atomic** = one `/offload` lane straight to implementation; **Epic** = decompose into sub-slices first (see §15).

| ID | Objective | Verify | Ready? |
|---|---|---|---|
| DS-1 | `demo_instances` table + migration | migration applies; row round-trips | Atomic |
| DS-2 | `/x/<slug>` router → tenant/key/seed; unknown → 404 | valid slug renders demo tenant | Atomic |
| DS-3 | `make provision-demo` wrapping `/admin` minter + slug insert | command prints working URL; scan succeeds | Atomic |
| DS-4 | `make expire-demo` + daily expiry/quota-revoke job | expired slug → CTA; over-quota → cap msg | Atomic |
| DS-5 | Enumeration/rate-limit hardening on `/x/*` | scripted guessing is blocked | Atomic |
| DS-6 | Seed-bundle mechanism parameterized by `SEED=` | two bundles → two demos | Atomic |
| AP-1 | `acx_business` schema (tenants/api_keys/usage/consent/leads/billing_events/ext-id cols) | migrations apply; ownership map documented | **Epic** |
| AP-2 | Business API service (tenant CRUD, key lifecycle over `/admin`) | create-tenant→key round-trips; recognition validates | **Epic** |
| AP-3 | Clerk integration + `user.*` webhooks (idempotent) → tenant lifecycle; cache email+consent | new signup auto-creates free tenant; email stored | **Epic** |
| AP-4 | `app.altcontext.com` dashboard: key, usage, install steps, upgrade link | signed-in user sees key + usage | **Epic** |
| AP-5 | Polar products + checkout + `subscription.*` webhooks → plan/quota enforcement | test purchase flips tenant to pro | **Epic** |
| AP-6 | Resend welcome + receipt from `mail.altcontext.com` | signup→welcome; purchase→receipt | Atomic |
| AP-7 | Concierge fast-path: `make` recipe + Polar payment link (ship week 1) | operator sells + provisions one customer by hand | Atomic |
| AP-8 | CRM projection sync (DB→Attio via API on lifecycle events, one-way) | tenant lifecycle event appears in CRM by `tenant_id` | Atomic |
| MK-1 | Static landing implementing §8 skeleton + copy | responsive; one primary CTA above fold | **Epic** |
| MK-2 | Before/After hero component (real image, 3 caption tiers) | matches §8; mobile-readable | Atomic |
| MK-3 | Us-vs-Them + face-recognition proof blocks | matches wireframe | Atomic |
| MK-4 | PostHog events on all CTAs/sections | events land per CTA | Atomic |
| MK-5 | Retire Fly.io marketing backend; serve static | old backend off; DNS→static | Atomic |
| OB-1 | PostHog project + snippet; `page_view`+`cta_click` | events live | Atomic |
| OB-2 | Funnel events signup→key→first-caption | funnel renders with drop-off | Atomic |
| OB-3 | `caption_accepted`/`caption_edited{...,skin_tone_cohort}` from plugin | flywheel events land with cohort props | Atomic |
| OB-4 | Sentry backend SDK + correlation-id binding | forced 500 → Sentry, linked to log/tenant | Atomic |
| OB-5 | Sentry frontend SDK, release-tagged | forced JS error → plugin version | Atomic |
| OB-6 | Retire Fly.io analytics; migrate rollups | no funnel gap | Atomic |
| OB-7 | Privacy guard test: no media/embedding/PII in any event | test fails if such a field is added | Atomic |
| LS-1 | Concierge target list (10–30) + per-prospect demo links | ≥5 demo links minted | Atomic |
| LS-2 | Public accuracy changelog + feedback form | wrong-caption report → fix note | Atomic |
| LS-3 | Plugin WP.org hardening (disclosure/consent, license, security, readme.txt) | clean-WP install passes; readme validates | **Epic** |
| LS-4 | WP.org submission package + SVN repo | submitted; review thread open | Atomic |
| LS-5 | Build-in-public kit: 5 Before/After posts + 2 essays (drafts) | drafts ready for Sep–Oct | Atomic |
| LS-6 | Case-study capture flow (consent + template) | one case study drafted | Atomic |

**Suggested first three (this week):** AP-7 + DS-3 (concierge provisioning → sell one warm contact by hand) · LS-1 (target list + demos) · OB-1..OB-3 (funnel + flywheel telemetry before anything goes public).

---

## 15. Offload division of labor — straight-to-implementation vs. decompose-first

**Answering the operator's question directly.** `/offload` dispatches **one self-contained implementation slice** to a junior lane with a scoped `TEST_CMD` and a review gate. So the answer is **it depends on the slice's size**:

- **Atomic slices → straight to implementation.** Anything you can express as *one end-state contract + one scoped test command* fits a single offload pass. In §14 these are marked **Atomic** (e.g. DS-3, AP-7, AP-6, AP-8, OB-1..OB-7, MK-2..MK-5, LS-1/2/4/5/6). Offload each directly.
- **Epic slices → decompose first (a Claude/operator or `Plan`-agent step), then offload the leaves.** Marked **Epic** in §14 (AP-1, AP-2, AP-3, AP-4, AP-5, MK-1, LS-3). A single offload pass has a token budget and one test command — it can't swallow "build the Business API service." Break each into 3–6 atomic sub-slices with their own contracts + tests, *then* offload those.
- **Litmus test:** *if you cannot write ONE falsifiable end-state + ONE `TEST_CMD` for it, it is an Epic — decompose before offloading.*
- **Reasoning stays with Claude/operator:** vendor choices, the slug-vs-identity model, the data-ownership map, pricing stance, moat model, launch sequencing, WP freemium call. `/offload` is the *implementation* vehicle for the leaves, not for strategy authoring.

**Recommended first offloads (all Atomic):** AP-7 (concierge fast-path, unblocks revenue) and DS-3 (`make provision-demo`), then OB-1..OB-3 so nothing launches unmeasured. Kick the two Epics that gate Phase 1 — AP-1 and AP-2 — into a decomposition pass next.
