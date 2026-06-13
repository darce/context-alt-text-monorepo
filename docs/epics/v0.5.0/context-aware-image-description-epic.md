# E19. Context-Aware Image Description (v0.5.0)

> **Epic Short ID**: E19
> **Status**: active — planning (E19-1 plan authored; analyze + review pending)
> **Source roadmap**: [context-aware-image-description-roadmap-2026-06-13.md](../../roadmaps/context-aware-image-description-roadmap-2026-06-13.md)
> **Source assessment**: [privacy-trust-and-vlm-fit-investigation-2026-06-13.md](../../assessments/current/privacy-trust-and-vlm-fit-investigation-2026-06-13.md)
> **Scope intake**: `MAINT-public-demo-vlm-scope` (scope intake 2026-06-13)
> **Predecessor**: [v0.4.0/public-demo-launch-readiness-epic.md](../v0.4.0/public-demo-launch-readiness-epic.md) (E15 — recognition-only demo; VLM/description explicitly deferred out of E15)

## Objective

Turn Alt Context from a recognition/curation prototype into a context-aware image-description service that produces accessibility-ready visual facts and alt-text drafts from WordPress media — using site-owned context, roster-confirmed identities, and auditable privacy controls. The first phase proves the smallest useful loop end to end (read one attachment → multipart to backend → deterministic visual facts → cache + provenance), then probes whether a local-CPU VLM is viable on the OCI A1 host.

## Product Positioning

Alt Context is not a generic "AI writes alt text" wrapper. It generates **inspectable visual facts** and alt-text drafts for site-owned media, enriched by WordPress and roster context, with explicit retention/purge/export and provider-disclosure controls. The three defensible traits — Context, Auditability, Trust — carry through every phase: model/provider provenance and retention state are first-class response fields, not afterthoughts.

## Epic-to-Task Decomposition

This epic owns destination and sequencing only; each task plan owns its slices. Roadmap phases (1–6) and candidate epics (D1–D7) map onto E19 phases as follows:

| E19 phase | Scope | Roadmap source | Task |
| --- | --- | --- | --- |
| **Phase 1 — Headless Description Foundation** | Backend visual-facts contract + seeded adapter + cache/provenance (D1); WordPress one-attachment roundtrip + LocalWP smoke (D2); local-CPU VLM probe on OCI A1 behind isolated `[vlm]` extras + benchmark/decision memo (D3) | Roadmap Phase 1 + Phase 2 | **E19-1** (this epic's first plan) |
| **Phase 2 — Minimal Alt-Text Write Path** | `write_alt`/preview/force semantics, non-overwrite-by-default guard, attachment-meta provenance, missing-alt integration (D4) | Roadmap Phase 3 | E19-2 |
| **Phase 3 — Table-Stakes Workflow Beta** | WP-CLI surface, bounded bulk generation, review/history UI, post/page refresh, error/status logs, usage controls (D5) | Roadmap Phase 4 | E19-3 |
| **Phase 4 — Context-Aware Differentiation** | Context pack (WP + roster), output modes, context-diff demo evidence (D6) | Roadmap Phase 5 | E19-4 |
| **Phase 5 — Hosted Provider Quality Tier** | Server-side provider adapter behind operator keys, benchmark harness, opt-in + disclosure, BYOK decision memo (D7) | Roadmap Phase 6 | E19-5 |

**Why E19-1 spans roadmap Phase 1 and Phase 2.** The roadmap mandates *seeded-first*: the visual-facts contract and seeded adapter (Phase 1) must ship and be provable before any model runtime (Phase 2). E19-1 keeps that discipline as ordered slices — the seeded contract and WordPress roundtrip land first; the local-CPU VLM is added last, behind an isolated `[vlm]` optional-dependency group that leaves the recognition-only default runtime and the live OCIR image untouched. Both roadmap phases sit inside this single **epic** phase ("Headless Description Foundation") because they share one contract and one transport seam; the VLM is a swap behind the same `DescriptionAdapter` protocol, not a second product surface.

## Strict Dependency Order

1. **D1 backend seeded contract** (route, schema, seeded adapter, cache/provenance) — no upstream dependency.
2. **D2 WordPress roundtrip** — depends on the D1 backend describe route existing.
3. **D3 local-CPU VLM adapter** — depends on the D1 `DescriptionAdapter` protocol; must not redefine it.

Later phases (E19-2…E19-5) depend on E19-1's contract. The alt-text-overwrite risk is owned by Phase 2 (E19-2): E19-1 deliberately never touches `_wp_attachment_image_alt`.

## Success Metrics (epic-level, from roadmap)

- One existing WordPress attachment roundtrips to backend description and returns stable visual facts.
- A repeated seeded call returns `cached=true`.
- Generated output always includes adapter/model/provider provenance and retention state.
- The optional write path (Phase 2+) never overwrites non-empty alt text unless forced.
- Context-aware output (Phase 4+) is visibly better than a generic caption on seeded demo images.
- Provider mode (Phase 5), if shipped, reports per-image cost, latency, model/provider id, and retention disclosure.

## Key Risks

- **Model work swallows product proof** → seeded adapter + schema ship first; local CPU is the last slice of E19-1, gated behind a benchmark go/no-go.
- **VLM deps fatten the recognition-only runtime** → `[vlm]` extras only; default install and the live OCIR image stay torch-free.
- **CPU inference blocks the API** → no inline model on the request path; one-worker async path with downsample/timeout caps.
- **Description couples to face recognition** → separate `scene` router, separate contract; the `/recognition/analyze` envelope is never extended.

## Out of Scope (this epic, until the mapped phase)

- No admin UI, bulk generation, or BYOK in Phase 1.
- No alt-text write in Phase 1 (Phase 2 owns the overwrite guard).
- No claim that local CPU inference beats hosted APIs on quality or latency.
- No automatic naming of people in alt text without human-reviewed roster context (Phase 4 + policy guardrails).

## External Dependencies

| Dependency | Owner | Status | Blocks |
| --- | --- | --- | --- |
| Description output contract review | Product + Engineering | Lands in E19-1 S1; human sign-off gate before WP slice (S6) | E19-1 S6 |
| OCI A1 local-CPU benchmark | Engineering | E19-1 S10 | Live local-model decision |
| Public recognition/description data policy | Product + Legal | Draft needed | Public beta + provider mode (Phase 5) |
| Provider/subprocessor terms | Product + Legal | Not started | Phase 5 (E19-5) |
