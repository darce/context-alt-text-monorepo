# Decomposition — MK-1 (Landing Page) + LS-3 (WP.org Plugin Hardening)

> The two remaining **Epic** slices from the launch plan §14, broken into **atomic** sub-slices with self-contained end-states and scoped `TEST_CMD`s.
> **Engineering heuristics v2** (cite in every slice): [`docs/strategy/engineering-heuristics.md`](../strategy/engineering-heuristics.md). Design: [`docs/strategy/design-aesthetics-heuristics.md`](../strategy/design-aesthetics-heuristics.md). Business: [`docs/strategy/business-marketing-heuristics.md`](../strategy/business-marketing-heuristics.md).
> **Source sections:** MK-1 = launch-plan §8; LS-3 = launch-plan §11. Naming/copy = [`positioning-canon-rules-and-naming.md`](positioning-canon-rules-and-naming.md).

---

## MK-1 — Static landing page (time-boxed: 1 week)

Static/edge-hosted, no backend (the Fly.io Node/Prisma stack crashes at 256MB and gets retired). Design-led, but the engineering rules still bind: no unbounded backend, tokens over literals, accuracy across skin tones.

| Sub-slice | End-state | Scoped `TEST_CMD` / verify | Heuristics | Deps |
|---|---|---|---|---|
| **MK-1a** scaffold + tokens | Static site scaffold; type scale + colour roles defined as **tokens, not literals**; responsive shell; no server runtime. | builds to static assets; body never scrolls horizontally on mobile; no raw hex/px literals in components | `[UI-01]`, design `[TYPE-01][TYPE-05][COL-03][COL-04]` | — |
| **MK-1b** hero + CTAs + analytics | H1 ("Alt text that knows who's in the photo"), sub-head with the "Verified Alt Text" frame, dual CTA with **Try demo** primary; every CTA emits a PostHog event. | CTAs render above the fold; each click fires the mapped event (depends OB-1) | biz `[GTM-07][GTM-08][PROD-01]` | MK-1a, OB-1 |
| **MK-1c** proof blocks | Before/After caption (3 tiers), Us-vs-Them, and face-recognition detect→match block; sample imagery **validated across skin tones**. | blocks match the §8 wireframe; the imagery pipeline preserves detail/dignity across skin tones | design `[COL-10]`, biz `[AIPX-07]` | MK-1a |
| **MK-1d** method + pricing + footer | How-it-works renamed to the Curated-Accuracy Method (Roster → Recognize & Flag → Curate); pricing (hypothesis) with the free-tier conversion trigger noted; final CTA. | content present; method steps match the naming doc; pricing labelled a hypothesis | biz `[GTM-15][BOOT-06]` | MK-1a |
| **MK-1e** deploy + retire Fly.io | Deploy to a static/edge host; DNS cutover; decommission the Fly.io marketing backend and migrate any needed rollups to PostHog. | static host serves `altcontext.com`; old crash-prone backend is off; no analytics gap | `[RES-05]` (no unbounded backend by construction), `[OBS]` | MK-1a..d, OB-6 |

> **Heuristics note:** MK-1 is mostly design-lexicon territory; the engineering v2 rules that genuinely apply are `[UI-01]` (token scales) and the "no unbounded backend" posture that motivates going static. Do **not** force-fit engineering IDs where a design rule is the real driver — cite the design lexicon there.

## LS-3 — WordPress.org plugin hardening (freemium: free GPL plugin + paid API)

The client plugin is copyable; the moat is the service + flywheel. This slice makes the plugin pass WP.org review and behave well when the paid service is unreachable (the sovereign local-read promise). Security and boundary rules dominate.

| Sub-slice | End-state | Scoped `TEST_CMD` / verify | Heuristics | Deps |
|---|---|---|---|---|
| **LS-3a** disclosure + consent | On fresh install, the plugin discloses the external recognition API call and gets consent **before** any request leaves the site; documents what is sent. | fresh install makes **zero** outbound API calls until consent is granted; disclosure text present | `[SEC-01]`, biz `[AIPX-13]` | — |
| **LS-3b** security hygiene | Sanitize/escape/validate **all** I/O at the WP boundary; nonces on every form/action; no arbitrary code exec; capability checks on admin actions. | WPCS/security scan passes; each form carries a nonce; a scripted CSRF/injection attempt is rejected | `[SEC-01]` (validate at every trust boundary, in and out) | — |
| **LS-3c** API client resilience | Plugin→service client has a bounded timeout, bounded backoff retry (5xx-only), and a breaker; on failure it degrades to the cached/local read, never hangs or blanks. | service-down → plugin shows cached data + a clear sync-status indicator; UI never hangs; no retry on 4xx | `[RES-02][API-08][RES-15][API-02]` | — |
| **LS-3d** readme.txt + license | `readme.txt` in WP format (tested-up-to, stable tag, screenshots, FAQ, disclosure); license GPLv2+-compatible; readme copy follows the §8 message hierarchy. | readme validates against the WP readme validator; license header compatible | biz `[PROD-09][GTM-07]` | LS-3a |
| **LS-3e** clean-install smoke | Activates on a clean, current WordPress with no fatal errors or notices; uninstall is clean. | activate → no PHP fatals/notices on a fresh WP; deactivate/uninstall leaves no orphaned state | `[RES-13]` (survive failures at the boundary) | LS-3a..d |

---

## Offload guidance

- **Straight-to-offload (atomic):** all MK-1 sub-slices; LS-3a, LS-3c, LS-3d, LS-3e.
- **Offload with care:** **LS-3b** (security pass across the whole PHP surface — give it the full `[SEC-01]` checklist and a WPCS gate; spot-review the diff, don't merge blind).
- **Ordering:** MK-1a first (unblocks b/c/d in parallel), then MK-1e after OB-6. LS-3a + LS-3b + LS-3c in parallel, then LS-3d, then LS-3e as the gate before WP.org submission (LS-4).
- Each brief = End-state (objective) + `TEST_CMD` + known-red baseline + the cited heuristic IDs.

**Reasoning owner (Claude/operator):** the design-vs-engineering citation boundary (MK-1 note), the consent-before-any-call rule and the degrade-to-local behavior (LS-3a/LS-3c — they carry the trust moat and the sovereign promise). **Junior/offload owner:** the atomic rows.

---

## Status: launch-plan §14 Epics now fully decomposed

| Epic | Decomposition doc |
|---|---|
| AP-1, AP-2 | [`decomposition-ap1-ap2.md`](decomposition-ap1-ap2.md) |
| AP-3, AP-4, AP-5 | [`decomposition-ap3-ap4-ap5-accounts-billing.md`](decomposition-ap3-ap4-ap5-accounts-billing.md) |
| MK-1, LS-3 | this doc |
| OB-8 | [`decomposition-ob8-infra-observability.md`](decomposition-ob8-infra-observability.md) |

All remaining §14 rows are marked **Atomic** and are offload-ready as written (no further decomposition needed): AP-6, AP-7, AP-8, MK-2..5, OB-1..7, DS-1..6, LS-1/2/4/5/6.
