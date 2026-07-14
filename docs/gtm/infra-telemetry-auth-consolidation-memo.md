# GTM Infra, Telemetry & Auth Consolidation Memo

> **Status:** Decision memo (durable). **Authored:** 2026-07-13. **Task:** `MAINT-gtm-infra-telemetry-consolidation-20260713`.
> **Purpose:** Answer the operator's infra/scaling, marketing-monorepo, telemetry-vendor, and auth-consolidation questions, heuristic-grounded, and record the resulting decisions. Companion to [`altcontext-productization-launch-plan.md`](altcontext-productization-launch-plan.md).
> **Citations:** `[GTM-01]`/`[BOOT-07]` = [business-marketing lexicon](https://github.com/darce/heuristics-canon/blob/main/lexicons/business-marketing.md); `[RES-14]`/`[OPS-05]`/`[OBS-05]` = [engineering lexicon](https://github.com/darce/heuristics-canon/blob/main/lexicons/engineering.md). IDs verified present in canon 2026-07-13.

---

## Ground truth (codemap + agent-audited, 2026-07-13)

- **One VM carries everything.** OCI Always-Free **A1.Flex, 4 ARM OCPU / 24 GB** runs **four** isolated environments — `prod` + `staging` + `dev` + `demo` — i.e. 4× Postgres + 3× InsightFace model caches + WordPress + MariaDB + one Caddy (`infra/oci/README.md` § Environments/VM Layout). Free-tier A1 allotment (4 OCPU / 24 GB total) is therefore **fully consumed** by this single box.
- **A10 GPU burst** is a *separate*, private-subnet, **scale-to-zero** instance (idle-reaper STOPs it) — intended relief for heavy description work, currently **blocked on an OCI A10 service-limit increase** (`MAINT-oci-a10-quota-request-20260710`, status blocked).
- **Demo topology is already free-tier-safe:** one shared demo WP instance, **tenant-switched by slug** (plan §5 explicitly forbids one container per prospect); per-prospect state = a `demo_instances` row + seed + `recognition_quota` cap (default 200) + rate limit.
- **Marketing monorepo** (`~/Development/altcontext-marketing-monorepo`, separate repo, ~2 mo stale): static site (face-pose + email signup) + **Fastify/Prisma/Postgres backend that is a hand-rolled analytics warehouse** (`Event`/`Session`/`Visitor`/`Lead`/`DailyMetricRollup` — page views, funnels, UTM, geo, web-vitals) + SvelteKit dashboard. **256 MB Fly OOM is real** (Node+Prisma+SSR in one 256 MB machine). Zero PostHog integration. Bloat = 2 GB `.git` + 0.9 GB committed source images; actual source is small. A **separate ~80%-built OCI free-micro (E2.1.Micro, 1 GB, self-host PG18, $0) Terraform scaffold already exists** in its `backend/infra/oci/` (committed tfstate + retry-apply.log).

---

## Q1 — Self-serve + client demos: infra pressure, can it scale, do it well or scrap?

**Do NOT scrap. The demo design is already sound; the real pressure is self-serve recognition compute, and the scaling path is boxes + GPU burst, not a rewrite.**

| Load | Pressure | Why |
|---|---|---|
| **Client demos** (`/x/<slug>`) | **LOW, by design** | Shared WP, tenant-switched; each prospect = rows + quota-cap + rate-limit, no new container `[RES-09 bulkhead / unbalanced capacities]`. Scales to dozens of prospects on the current box. |
| **Self-serve paying tenants** | **HIGH** | Each real tenant runs ongoing InsightFace recognition (CPU+RAM heavy) on **4 cores already shared by 4 environments**. Bottleneck is recognition compute, not the web tier. |

**Scaling path (reproducible Terraform already exists — provisioning is not a snowflake, plan §11):**
1. **Split `prod` recognition onto its own box the moment the first paying tenants land** — stop co-mingling prod with dev/staging/demo `[RES-11 / ARCH-02 don't reach into / co-locate another system]`. Free tier is exhausted, so this is a **cheap paid A1** (~$30–60/mo), not free — a fine cost against paying revenue `[BOOT-04 rate floor: price above it so this is affordable]`.
2. **Route faces-at-scale to the scale-to-zero A10 burst** (bills only when busy) — this is the plan's Pro conversion trigger. **Unblock the A10 quota** (operator OCI console; `MAINT-oci-a10-quota-request`).
3. **Quota caps + bounded queues BEFORE onboarding, not after** `[RES-14 backpressure]` — partly built already (`deps/demo_quota.py`, DS-2B shared compute budget).

**Do it well = capacity-plan with quotas + backpressure now; do NOT build k8s/autoscaling** — premature for a single-box pre-revenue product `[STRAT-04 swing only at fat pitches; OPS-05 don't automate a mess]`. **Verdict: keep; scale by splitting boxes + GPU burst; instrument load first (ties to Q3).**

---

## Q2 — Marketing monorepo: move to OCI? useful? Fly scaling? cost/benefit

**Do NOT lift-and-shift to OCI. That migrates the exact component you are supposed to delete `[OPS-05 eliminate before automate; plan D6 / OB-6]`. Decompose it instead.**

| Piece | Fate | Rationale |
|---|---|---|
| **Analytics engine** (`Event`/`Session`/rollups) | **RETIRE → PostHog** (OB-6) | It re-implements PostHog (events, funnels, UTM, geo, web-vitals) with zero PostHog. It is the OOM-prone, DB-heavy, stateful part — the entire crash risk and cost `[OPS-05]`. |
| **Static site** (face-pose + signup) | **Edge static host** (Cloudflare Pages free, or an added vhost on the existing OCI Caddy) | ~$0, global CDN, cannot OOM. The moat is not the website (plan §8). |
| **Lead-capture** (`Lead`/`Consent`/`FormSubmission` = owned email SoR) | **Fold into the business API SoR** (§6, AP-1/AP-2) | The owned contact list must be one in-house SoR `[BOOT-01 own before polish]`, not a second marketing DB `[DATA-14 one system of record]`. Interim: keep the slim endpoint until the business API exists. |

**On the pre-built OCI micro scaffold:** it targets a *separate* free 1 GB VM — finishing it would host the retire-target, so **skip it**. Its only defensible use is the interim slim lead-capture endpoint *if* you refuse to wait for the business API.

**Cost/benefit (Fly paid vs OCI vs static+PostHog):**
- Fly paid (bump RAM ~$5–15/mo) = **pay to keep a box you're deleting.**
- OCI free micro ($0) = **same box you're deleting, just cheaper.**
- **Static site + PostHog (~$0, zero-maintenance, no crash) = winner** — it removes the stateful backend entirely `[OPS-05]`.

**Is it useful?** The **site + lead-capture: yes** (keep). The **analytics engine: no** (retire). **Verdict: retire analytics → PostHog, static-host the site, fold lead-capture into the business API. Net marketing infra collapses to ~static-only.** (The site is stale ~2 mo — reskin is the plan's 1-week D6 box, not a rebuild.)

---

## Q3 — Telemetry vendors: add Google Analytics? Datadog? free tiers? redundant with PostHog?

**No to both. The non-redundant stack is exactly the plan's three planes; adding either re-introduces overlap and a new landlord.**

Canon stack (plan §9): **PostHog** (product analytics, EU-hosted) + **Sentry** (errors) + **OCI-native host observability** (OB-8: Cloud Guard, VSS, Notifications topic, symptom alarms). Three planes, deliberately separate — different data, consumer, failure mode `[OBS-05]`.

- **Google Analytics — NO.** Redundant with PostHog (page views/funnels/UTM) `[DATA-14 one SoR]` **and** a trust/privacy regression for a *face* product `[SEC-06; plan §9 "a face product that leaks analytics data destroys the trust moat"]`. It also undercuts the "privacy-first" positioning you must be able to back `[CLM-04 adjectives aren't evidence]`.
- **Datadog — NO (now).** Infra/APM that overlaps **both** Sentry (errors) and OCI-native OB-8 (host). Pricing balloons per-host/per-GB; the free/startup tier is thin (≈5 hosts, 1-day retention). Massive over-tooling for a single VM `[OPS-05; STRAT-03 circle of competence]` and a third observability landlord `[BOOT-07]`. Revisit **only** at multi-host scale — a fat pitch that does not exist yet `[STRAT-04]`.

**Consolidation = PostHog + Sentry + OCI-native. Consolidate *access* through one identity (Q4), not by adding tools.**

---

## Q4 — Add an auth vendor to manage access and users?

**Two distinct surfaces — don't conflate them. Add the customer one (already decided); do NOT add an ops one.**

1. **Customer auth (signups)** → **BUY = Clerk**, already decided (D1 / §6.1). It is the Phase-1 self-serve gate (**AP-3**), not a bolt-on; buying commodity, security-critical identity is correct `[STRAT-02]`. Not built yet.
2. **Operator/ops access** (VM SSH, `/admin`, key minting) → **Tailscale** (already in use) + HTTP-Basic admin token. For a single operator this minimal surface is right; adding an SSO/IdP vendor here is over-tooling `[OPS-05; STRAT-03]`.

**The consolidation lever is NOT a new vendor:**
- Customers → **Clerk** as the single identity across app + dashboard + (eventually) plugin pairing, referenced **by ID** everywhere `[API-10; §6]`.
- Ops → **Tailscale** already consolidates VM SSH + `/admin` serve on one mesh identity.
- **Real identity-model win:** route the plugin's key→tenant through the **business API** and retire URL-derivation (the tenant-pairing bug's root) = **RONLY-1 + AP-3**. That *is* "consolidate auth," and it is already planned.

**Verdict: add Clerk (planned) for customers; do NOT add an ops IdP. Fewer landlords, not more `[BOOT-07]`.**

---

## Which grunt to offload next (heuristic pick) — tenant-pairing durable fix

Telemetry implementation now sits on architecture **just decided here** *and* still needs operator vendor keys → **not clean-offload-ready** `[PROD-02 problem before solution; STRAT-03]`.

**Offload = `MAINT-tenant-pairing-recovery-20260711` durable fix, Slices 1 + 3** — PASS plan, **no vendor dependency**, fixes a **live prod bug** (`whoami` 500 from the documented recurring greenfield schema-drift, `infra/oci/README.md` § "Greenfield schema drift"), and Slice 3's schema-parity probe is **testable against the real Postgres on the remote OCI gate VM** — the operator's stated remote-test opportunity `[RLSE-05 / OBS-08 silence is not success]`. Dispatched to **grok-4.5 high effort**.

---

## Deferred / operator-blocked (unchanged priority order)

1. **OB-\* telemetry impl** — needs PostHog + Sentry accounts + keys (operator); then env-gated code is offloadable. **This is the plan's own skipped Phase-0 gate** (a live public demo with zero telemetry is discarding moat-labels every day `[AIPX-03]`).
2. **Concierge revenue** — Polar payment link + LS-1 target list (operator) turns code-complete AP-7 into the first paid-intent test `[GTM-01]`.
3. **A10 GPU quota** — operator OCI console; gates faces-at-scale self-serve (Q1).
4. **AP-1..AP-5 self-serve + payments** — **defer until concierge validates pitch/price** `[STRAT-08 spike≠business; PROD-03 cheapest learning first]`.
