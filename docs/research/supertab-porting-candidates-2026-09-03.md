# Supertab Connect — Concepts Worth Porting to AltContext

**Date:** 2026-09-03
**Origin:** Vendor evaluation performed in `altcontext-marketing-monorepo`; full evaluation at `altcontext-marketing-monorepo/docs/research/supertab-evaluation-2026-09-03.md`
**Status:** Proposal / request for consideration. Nothing here is implemented.
**Recommendation:** Do **not** buy Supertab or Supertab Connect. Reimplement four of their architectural patterns, three of which land in this repo.

---

## Why this repo is the target

Supertab sells monetization to **content publishers**. AltContext is a B2B API — alt-text and image-description generation for WordPress sites, sold per tenant, authenticated by API key. The *product* is a non-fit and buying it would be wasted spend.

But Supertab Connect's internal architecture maps onto a gap this repo already has in schema form.

**Corrected 2026-09-03** — an earlier draft of this doc claimed *both* `Tenant.plan` and `ApiKey.rate_limit_tier` were dead columns. That is wrong for the second one, and the difference matters:

- `db/models/tenant.py:49` → `Tenant.plan` (`Mapped[str | None]`) — **enforcement-dead.** It is written at provisioning (`scripts/provision_customer.py:162`, `recognition/application/services/customer_provision_service.py:103,124,164`) and read only to echo itself forward (`plan=tenant.plan or resolved_plan`). No code branches on its value.
- `db/models/tenant.py:88` → `ApiKey.rate_limit_tier` — **already live.** It is loaded in `recognition/interface_adapters/http/deps/auth.py:265`, carried on `AuthContext` (`deps/auth.py:230`), and enforced per-request at `deps/rate_limit.py:54` via `tier_rpm(auth.rate_limit_tier, settings)`. It is also surfaced in the admin console and admin router.

So the entitlement hook is not missing — **it exists at the API-key level and is enforced.** What is missing is (a) anything at the *tenant/plan* level, and (b) any metering or aggregation feeding it. There is still no billing, subscription, checkout, or paywall implementation anywhere in `apps/` or `packages/`.

### How this was checked

`grep -rn` across `apps/` and `packages/` for `rate_limit_tier` and for `plan` attribute access, then reading each non-test hit to separate *writers* from *readers that branch on the value*. This is a text search plus manual read, **not** a call-graph or type-aware analysis — a dynamic access (`getattr`, dict round-trip, ORM `.values()`) would not have been caught. Re-verify before building on it.

---

## Candidate 1 — Metering → entitlement pipeline (highest value)

**What Supertab does.** Connect decomposes monetization into four stages, independent of the licensing semantics wrapped around them:

```
meter      — treat machine events as billable records
             (crawls, calls, tokens, document fetches, tool invocations)
  ↓
aggregate  — collapse millions of events into invoiceable units
  ↓
enforce    — machine-readable budgets, rate limits, entitlements
  ↓
settle     — multi-rail (cards, ACH, wire, invoicing)
```

**Why it fits.** AltContext already produces the billable events — description generations, image analyses, recognition calls. What is missing is everything downstream of "meter."

**Where it lands.**
- `db/tenant_context.py` → `require_tenant_record` is the natural chokepoint. Every tenant-scoped request already passes through it; entitlement checks belong there rather than scattered across route handlers.
- `deps/rate_limit.py` already demonstrates the enforcement shape at the API-key level. The work is to add the *tenant/plan* tier above it and the metering/aggregation beneath it — not to build enforcement from nothing.
- `db/models/tenant.py:49` → give `Tenant.plan` a reader, so it stops being a label.

**Design constraint (raised by the context-alt-text session, accepted).** `require_tenant_record` is a per-request hot path on the same service that fronts GPU burst provisioning. Any entitlement check added there must be a cheap read — in-process cache or a column already loaded on the tenant row, not a second round trip or a cross-service call. Recording this now rather than discovering it during implementation.

**Effort:** in-house, no vendor dependency. This is the single highest-value item in the evaluation.

---

## Candidate 2 — Edge-validatable tokens instead of origin key-hash lookup

**What Supertab does.** OLP (Open Licensing Protocol) extends OAuth 2.0 rather than inventing a scheme:

- `grant_type=client_credentials`; client auth via HTTP Basic
- Issued token type is **`License`**, not `Bearer` — presented as `Authorization: License <token>`
- `access_token` is a JWT signed **ES256**
- A **JWKS endpoint** publishes public keys, so validators verify signatures locally with **no per-request call back to the auth server**
- Introspection at `POST /introspect`, RFC 7662-compliant
- 401 for missing/invalid/expired; 403 for a valid token whose scope excludes the resource. Notably, **no HTTP 402 anywhere.**

**Why it fits.** Today every AltContext request reaches the Python description-service to verify an `api_key_hash` against the database. With short-lived ES256 JWTs plus a JWKS endpoint, Caddy or a CDN can reject unauthorized traffic **before** it reaches the origin.

**Why it matters here specifically — and the counter-argument.** The description-service is deployed on OCI with GPU burst provisioning, so the original framing was that keeping unauthorized traffic off the origin has direct cost impact.

The context-alt-text session pushed back on this and the pushback holds: because the GPU is provisioned *on demand*, an unauthorized request that reaches origin costs a rejected Python request, not an A10-hour. Origin rejection is already cheap. The lever only becomes real if unauthorized volume is high enough to matter, and **there is no data establishing that it is.**

Treat Candidate 2 as a design note on token shape, not a cost-justified project. If it is ever built, justify it on something measured.

**Where it lands.** The API-key verification path in the description-service, plus the Caddy reverse-proxy config. Adopt the token design; discard the licensing semantics entirely.

---

## Candidate 3 — Test / Live credential pairs

**What Supertab does.** Every registered Website receives **both** a Live Client ID and a Test Client ID. Merchants can build out the full configuration in Test Mode before completing KYC; the deployment snippet auto-switches on the selected environment. Test transactions are visible only with an explicit `?testmode=true` flag.

**Why it fits.** This repo currently handles the same need with `DemoInstance` plus the `infra/oci/demo/tenant-mint-runbook.md` flow — minting a throwaway tenant per prospect. A test/live key pair on the existing `ApiKey` model is a lighter primitive for the same sales-demo purpose. It composes cleanly with the *existing* `rate_limit_tier` enforcement: a test key can simply carry a distinct tier and be throttled by machinery that already runs today. That makes this the lowest-effort of the four — no new enforcement path required.

**Where it lands.** `db/models/tenant.py` (`ApiKey`), and the demo provisioning runbook.

---

## Candidate 4 — WordPress plugin: license gating and distribution

Two separate gaps, both in `apps/prototype-wp-alt-context/`.

### 4a. No license mechanism exists

`alt-context.php` declares `License: GPL v2 or later`. There is **no license-server call, no `license_key` option, no activation gating, no freemium gate**. `src/support/class-life-cycle-manager.php` handles only activation/deactivation/upgrade hooks for table creation.

For comparison, Supertab's WordPress plugin stores a Website URN (`urn:stc:merchant:system:[UUID]`) plus a Merchant API key, treats the latter as sensitive and admin-only, and auto-redirects to its settings page on first activation.

**Where it lands if AltContext becomes paid:**
- `src/support/class-life-cycle-manager.php` — the activation hook is where a license check belongs
- `js/admin/pages/settings/SettingsForm.tsx` and `js/admin/api/settingsApi.ts` — existing admin settings surface where a license-key field would live

### 4b. Distribution — arguably the bigger miss

Supertab Connect ships through wordpress.org: *Plugins → Add Plugin → search "Supertab Connect" → activate*. AltContext ships a standalone `dist/alt-context-<version>.zip` + sha256 via `scripts/release/package-plugin.sh`, per `docs/portable-packaging-runbook.md`.

The standalone ZIP is a deliberate choice with real tradeoffs (no review latency, no wordpress.org policy constraints), so this is a **question, not a defect** — but the reach difference is the reason Supertab's plugin launch post leans on the WordPress market-share stat.

---

## Explicitly not recommended

- **The Tab mechanic** (micro-purchases accumulating to a deferred settlement threshold) — no micro-purchase use case here.
- **Paywalls / the Experiences layer** — nothing to gate.
- **RSL / CAP crawler licensing as a product** — AltContext has no licensable corpus. Note this is about *serving* licensed content; it says nothing about Candidate 2, which borrows only the token mechanics.
- **Supertab as a vendor**, either product line. Pricing starts at $99/mo (Supertab) and $249/mo (Connect), both sales-gated floors with no published fee percentage or revenue share.

### Speculative, flagged as such

AltContext *produces* machine-readable image metadata. RSL is a standard for *declaring* machine-readable terms about content. Emitting licensing/attribution metadata alongside generated alt-text is a conceivable adjacency, but **nothing in the research supports demand for it.** Recorded as a hypothesis, not a recommendation.

---

## Suggested sequencing

1. **Candidate 3** — promoted to first. It rides on `rate_limit_tier` enforcement that already exists, so it is the smallest real change and it improves the demo-minting flow immediately.
2. **Candidate 1** — the metering/aggregation layer plus a tenant-level tier above the existing key-level one. Gives `Tenant.plan` a reader. No external dependency. Subject to the hot-path constraint above.
3. **Candidate 2** — design note only; deferred until there is measured unauthorized volume to justify it.
4. **Candidate 4a/4b** — only once a paid tier is an actual decision.

---

## Provenance and caveats

Research was performed by four parallel agents over ~35 vendor URLs on 2026-09-03. Vendor claims were assessed for credibility; the full table is in the source evaluation. Summary: the Maine Trust case study is credible and specific (2,800+ pass customers → 70 subscription conversions); the "400% uptick in conversions" claim is unanchored and should not be cited; the docs internally contradict themselves on currency support (10 listed vs "134 supported").

The `supertab-integrate/custom-integration` documentation page returned HTTP 404 on every attempt, so **no endpoint names, auth model, or webhook payload schema for their custom-integration path could be confirmed.** Candidate 2 above is reconstructed from the OLP and CAP protocol docs, which were fully retrievable.
