# Portfolio Quadrant & MVP Strategy Assessment — 2026-06-11

**Status:** Active strategy reference
**Task:** MAINT-MVP-PORTFOLIO-ASSESSMENT-20260611
**Framework source:** R.G. Cooper's R&D portfolio quadrants, via Pieraccini, ["Research Is Not Engineering at a Slower Speed"](https://voiceinthemachine.com/2026/06/10/research-is-not-engineering-at-a-slower-speed/) (2026-06-10)

## Purpose

Place the WP plugin (`apps/prototype-wp-alt-context`) and description service (`apps/prototype-description-service`) on the Cooper portfolio quadrants; evaluate whether `docs/roadmaps` tracks toward the stated goal (machine-vision interface for non-technical users → context-grounded alt text → video via scene-change proxies); name the MVP cut list and non-code moat strategies.

The two axes: **probability of success** (inverse of epistemic risk — does the knowledge to solve this even exist?) and **impact if successful** (ROI). Quadrants: **Pearls** (high/high — cultivate), **Oysters** (low P, high impact — pursue selectively via cheap probes), **Bread and Butter** (high P, low impact — contain, don't let it crowd), **White Elephants** (low/low — kill fast).

Pieraccini's core distinction applies directly here: engineering work (low epistemic risk) deserves timelines and milestones; research work (high epistemic risk) deserves cheap probes, not roadmap epics. Mixing the two — scheduling research like engineering, or polishing engineering like it's research — is the failure mode to design against.

## Evidence base

Audited 2026-06-11: plugin source/build/test surface (v0.0.4, 93 PHP unit tests, Playwright e2e, release ZIP script, no readme.txt, hard dependency on external recognition service via `ACX_RECOGNITION_URL`); service source (FastAPI + InsightFace 512D embeddings + HDBSCAN/agglomerative/representative-only clustering, pgvector, 187 test files, prod compose + Caddy + live OCI deploy at `api.altcontext.com`; `scene/` is a health-check skeleton only); all of `docs/roadmaps/`, E15/E14 epics, `docs/deferred-features/`.

**Load-bearing finding: no description generation exists anywhere in the codebase.** No VLM/LLM call in the service or plugin. The system as built is a recognition + clustering + curation pipeline. "Better alt text" — the product's name and impact claim — is currently an unvalidated hypothesis. This is deliberate (MVP step 1 = recognition/clustering interface only) but it concentrates the portfolio's epistemic risk in one untested place. See [Warning 2](#warning-2--the-pearl-hypothesis-is-unvalidated).

## Quadrant placement

| Asset | Quadrant | P(success) | Impact | Reasoning |
|---|---|---|---|---|
| WP plugin chassis (admin SPA, REST proxy, packaging) | **Bread and Butter** | High — built, tested, shipped through Epics A–C | Low standalone | Generic "AI alt text" WP plugins are a commodity; any developer wires a VLM API key in a weekend, and falling dev cost accelerates this. The chassis differentiates nothing by itself. |
| Identity-context layer (clustering + roster curation + person-aware context) | **Pearl** | High — InsightFace + HDBSCAN are proven tech; 1,400+ tests; pipeline works | High | The one thing commodity VLM plugins structurally cannot do: know who is in *your* photos. Hosted providers won't touch private-individual face recognition (policy, BIPA-class liability, EU AI Act climate). Compliance demand (EAA enforcement live since June 2025, WCAG/508) raises the value of *good* alt text, and identity/context is the main quality lever left once generic captioning is free. |
| Video description via scene-change proxies | **Oyster** | Low/unknown — real epistemic risk (see below) | High | Human audio description costs tens of dollars per minute; automation is poor. If keyframe/scene-segmentation reduces video to "describe N stills + identity continuity," cost collapses. Whether that yields *acceptable* descriptions is unknown — that's the research question. |
| Sync/outbox evolution, PG18, SaaS billing impl, CI envelope, Apple-parity recognition | **White Elephant risk** | Mixed | Low *now* (zero users) | Not worthless — mistimed. Infra polish for a user base of zero is the classic Bread-and-Butter-metastasizing-into-White-Elephant pattern. Each is justifiable alone; together they compete with the only milestone that matters. |

### Direct answer: where does the WP plugin sit?

**On the Bread-and-Butter/Pearl boundary, and the next two quarters decide which way it falls.**

- As a *distribution vehicle* for the identity-context layer, it inherits the Pearl's impact: WordPress is ~40%+ of the web, wp.org is free distribution, and the accessibility-compliance wave creates pull.
- As a *standalone artifact*, it is Bread and Butter trending toward **White Elephant**: if it ships as "a face-clustering admin tool that requires self-hosting a Python service, with no description payoff visible," adoption probability drops to near zero and the whole asset strands.
- Treat plugin work with Bread-and-Butter discipline — timeboxed, minimum viable polish, no feature is "done better" past the demo gate — and concentrate all differentiation investment in the identity/context layer and its payoff demonstration.

### Computer-vision market context

The capability frontier moved under this project, favorably. Generic image captioning is solved and nearly free — that *commoditizes competitors'* core feature while leaving this project's core (private identity context + curation workflow) untouched, because the barrier there is data access, trust, and UX, not model quality. Face embedding/clustering is also commodity tech (good: low epistemic risk on the Pearl). What remains scarce: consented, curated, site-specific identity data and a workflow non-technical users will actually complete. The scarce thing is what this repo has been building. The strategy is therefore right; the risk is sequencing and crowding, not direction.

## Moat strategies outside code

As code cost → 0, code is depreciating inventory. Durable assets, in priority order:

1. **Curated-data moat (primary).** Every hour a user spends merging clusters and naming people builds a site-specific identity graph that no competitor can replicate without re-extracting that labor. Switching cost compounds with curation. Actions: make the roster durably exportable (trust enables investment), and make accumulated curation visibly improve every future output — including, eventually, video.
2. **Privacy/trust positioning (structural).** Big platforms exited consumer face recognition (Meta 2021; BIPA litigation; EU AI Act hostility to remote biometric ID). A self-hosted/privacy-minimized recognition service with auditable purge/export occupies ground incumbents *cannot* follow onto. Actions: publish the privacy commitments from `recognition-privacy-hybrid-roadmap-2026-03-06.md` as a public, versioned policy; retention + purge as marketed features, not internals.
3. **Compliance-workflow lock-in.** EAA/508 create demand not just for alt text but for *evidence* of alt text review. The approval trail (who approved which description, when) is sticky in a way generated text never is. The workbench is already shaped for this. Action: frame the workbench as the compliance review surface, not just a generation tool.
4. **Distribution & community standing.** wp.org reviews, installs, and standing in the WP accessibility community compound and cannot be forked. Actions: readme.txt + listing hygiene; show up where WP a11y people are (WP Accessibility Day, a11y team channels); one strong case study with a real media library.
5. **Own the quality benchmark.** Publish a rubric + (consented) evaluation set for *context-aware* alt-text quality. Whoever defines measurement owns the category narrative; this also forces internal honesty about whether context actually improves descriptions.
6. **Vertical depth.** Identity-context value scales with how often the same people recur in a library: newsrooms, universities, museums, congregations, clubs, family archives. Generic stock libraries get ~zero value. Pick one vertical for the first case study rather than marketing horizontally.

## Roadmap evaluation: on track?

**Verdict: directionally on track for MVP step 1, with three structural warnings.**

On track: E15 Phases 1–2 (security, observability) shipped; backend live on OCI; plugin Epics A–C merged; clustering pipeline deeply tested. The E15 MVP definition (public demo URL + manual E2E pass) matches the stated first step — ship the recognition/clustering interface only. The April scope cut (CI envelope demoted to v0.4.1) was the right Cooper move.

### Warning 1 — Bread and Butter is crowding the gate

Epic D sync evolution, E15 Phase 6 audit closure, PG18 roadmap, pgcache refactor assessment, SaaS operations roadmap, an accumulating v0.4.1 backlog — all for zero production users (per the repo's own Greenfield Policy). Cooper's framework says Bread and Butter's danger is precisely that it always looks justified. The only milestone that matters is the public demo URL (E15 Phases 3–4). Everything not on that critical path is crowding it.

### Warning 2 — the Pearl hypothesis is unvalidated

"Granular context + facial clustering ⇒ *better* alt text" has never been demonstrated end-to-end, because no description generation exists. Shipping recognition-only first is a defensible sequencing choice — but a demo visitor will see a face-clustering tool with no visible payoff, and the project will still have zero evidence for its central claim. The fix is cheap now that VLM APIs are commodity: a side-by-side artifact (same image, description with vs. without roster context injected) takes days, not weeks. It belongs in or immediately after the demo gate — not because it's MVP scope creep, but because it is the single cheapest probe of the portfolio's largest epistemic risk.

### Warning 3 — the video Oyster needs a probe, not a plan

Two corrections to the aspiration as stated:

- **Codec keyframes are a noisy proxy.** Encoders place I-frames at fixed GOP intervals (e.g., every 2s for streaming) *plus* at scene cuts; most I-frames are not semantic boundaries. The instinct — use compression-domain structure to collapse the problem space — is sound, but content-aware scene detection (`ffmpeg select='gt(scene,T)'`, PySceneDetect, TransNet-class detectors) is equally cheap and far closer to semantic scene changes. The probe should compare both.
- **The open questions are researchable in a week:** scenes/minute on representative footage (drives cost model), identity persistence across selected frames (does the roster transfer?), and whether per-scene stills + identity continuity read as an acceptable description. One week, five videos, measured numbers. Until that probe runs, video is a belief, not a plan — and per Pieraccini, it must not be scheduled like engineering. `scene/` correctly remains a skeleton; keep it that way until after the demo ships.

### Aspirations mapped to quadrants

| Aspiration | Quadrant | Treatment |
|---|---|---|
| Public demo of recognition + clustering UI | Engineering (Pearl delivery) | Schedule it. Sole v0.4.0 milestone. |
| Context-grounded description generation | R&D (Pearl validation) | Cheapest possible probe immediately at/after demo. |
| Non-technical-user onboarding (no-CLI setup) | Engineering, post-demo | Required before any wp.org listing; not before demo. |
| Video description via scene segmentation | Research (Oyster) | One-week timeboxed probe, post-demo. No epic until probe data exists. |
| Multi-server sync, SaaS billing, PG18, Apple-parity recognition | Bread and Butter / White Elephant risk | Frozen until a user exists. |

## MVP cut list

**Keep (critical path to demo URL):**
- E15 Phase 3 (WP demo provisioning) + Phase 4 (manual E2E) and their named gates (E15-22, E15-3a).
- E15-7 local sync correctness — only to the depth the demo breaks without it.
- Minimal failure UX: a clear "recognition service unreachable / misconfigured" error state. Today misconfiguration fails silently — fatal for non-technical users and demo visitors alike.

**Add (small, high leverage):**
- Context-payoff artifact on the demo landing page: one image, with-context vs. without-context description side by side. Days of work; validates the entire premise (Warning 2).
- Post-demo, timeboxed: the one-week video scene-detection probe (Warning 3).

**Cut / keep frozen (explicit, with re-entry condition):**

| Item | Status today | Re-entry condition |
|---|---|---|
| Epic D sovereign sync / outbox evolution | Deferred | A second real site exists |
| PG18 upgrade (`roadmap-pg18-upgrade.md`) | Phase 0 only | Any production data exists |
| SaaS billing implementation | Planning doc | Paying-user intent demonstrated |
| Apple-pipeline recognition parity (multimodal, exemplar sets) | Insights doc | Clustering quality measurably blocks curation UX |
| CI smoke envelope | Demoted to v0.4.1 | Demo shipped (correct as-is; resist re-promotion) |
| pgcache / DB read-write refactor | Deferred assessment | Measured latency problem with real load |
| Further agentic-workflow tooling (E17-class) | Separate repo | Freeze at current capability until demo ships |

The discipline that matters: nothing leaves the frozen list without its re-entry condition being *observed*, not predicted.

## Relevant books (`/Volumes/Chimay/___Books`)

Mapped to path stage. All under `_graph/books/` unless noted.

**Now — MVP and shipping the interface:**
- `800-Business-and-Strategy/building-machine-learning-powered-applications-going-from-idea-to-product.pdf` (Ameisen) — the single most on-point title in the library: scoping ML MVPs, evaluation loops, when not to build.
- *Accessibility for Everyone* (Kalbag); *Inclusive Design Patterns* (Pickering); *Web Accessibility Cookbook* (Matuzović) — the quality bar for alt text and non-technical-user UX; also where the community/moat lives.
- *WordPress Plugin Development* (Williams); *WordPress Plugin Development Cookbook* (Lefebvre) — wp.org distribution mechanics for the post-demo listing.

**Pearl validation — recognition/clustering quality:**
- *Handbook of Face Recognition — The Deep Neural Network* (Li, Jain, Deng) — clustering quality, threshold/fairness grounding when curation UX hits recognition limits.

**Oyster probe — video:**
- *Video Codec Design* (Richardson) — GOP/I-frame structure; exactly what's needed to evaluate the keyframe-proxy hypothesis honestly.
- *Compression for Great Video and Audio* (Waggoner) — practical encoder behavior (why I-frames land where they do).
- *Machine Learning for Audio, Image and Video Analysis* (Camastra & Vinciarelli) — bridges still-image pipeline to temporal analysis.
- *MPEG Video Compression Standard*; *Image and Video Compression for Multimedia Engineering* (Shi & Sun) — reference depth behind Richardson.

**Gap:** the library has no Cooper (*Winning at New Products* — source of the quadrants), no *Lean Startup* (Ries), no *7 Powers* (Helmer — the moat taxonomy). Worth acquiring; Helmer's "switching costs" and "cornered resource" map directly onto moats #1 and #2 above.

## Decision summary

1. Plugin chassis = Bread and Butter; identity-context layer = the Pearl; ship the demo URL and stop polishing the chassis past it.
2. The portfolio's largest epistemic risk is the unvalidated "context ⇒ better descriptions" claim; buy it down with a days-scale side-by-side artifact at the demo gate.
3. Video is an Oyster: one-week post-demo probe (scene detection vs. codec keyframes, identity persistence, cost/minute). No epic before probe data.
4. Moat = curated identity data + privacy posture + compliance workflow + wp.org standing — not code. Start moat actions that cost ~zero now (privacy policy publication, readme.txt, one vertical case-study target).
5. Frozen list holds until a re-entry condition is observed. Review this assessment when the demo URL is live or 2026-09-01, whichever comes first.
