# E19-4a — Identity→Prose Merge — Scope Note

> **Status:** Scope intake (pre-task-plan). Ready for E19-4a task-plan drafting.
> **Date:** 2026-06-15
> **Scope task:** `MAINT-e19-4a-identity-scope-20260615`
> **Parent epic:** E19 Context-Aware Image Description (v0.5.0), Phase 4 / D6 Context-Aware Differentiation.
> **Design source:** [identity-prose-merge-design-2026-06-15.md](../assessments/current/identity-prose-merge-design-2026-06-15.md) (solution detail lives there; this note bounds the work).

## Decision: task plan, not a new epic

E19 already owns this (Phase 4 / D6). Identity→prose merge is **one component** of E19-4; per intake it is carved as a **focused standalone task, `E19-4a`**, leaving the rest of D6 (WordPress post/product/SEO context pack, output modes) for later E19-4b+. No new epic.

**Prerequisites already shipped in E19-1 (done, merged to main):** description contract + 15-field visual-facts schema (`docs/workstate/contracts/image-description-api.md`), `POST /scene/describe/multipart`, Florence-2 `florence_small` adapter (inline off-thread), WordPress `DescribeController` → `/acx/v1/recognition/describe`. E19-4a builds **on top** of these; it does not re-open them.

## MVP scope (in)

Implement the deterministic identity→prose merge as a **model-independent layer** that turns a description + confirmed roster identities into a **named** alt-text draft, server-side, reusing curation the operator already did.

1. **Backend merge service** (`scene/`): pure function `(caption, phrase_boxes, confirmed_faces, policy) → named_prose` + provenance.
   - SQL join by `media_id`: `MediaIdentity`(bbox, confidence) → `IdentityMember` → `IdentityCluster`(`label`, `user_confirmed`, `roster_id`), filtered `user_confirmed=TRUE`, label present, not dismissed.
   - Coordinate normalization to `[0,1]` image fractions; **containment** match (face-center in smallest person-phrase box), 1:1 only.
   - **Grammar-aware NLG reflow** (deterministic): articles/case, subject vs. possessive, list aggregation, repeated-mention coreference. **Positional fallback** when grounding absent/low-confidence.
2. **Reflow seam (LLM-ready):** the reflow step is an interface with the deterministic NLG realizer as the only v1 implementation, shaped so a constrained on-box LLM (Qwen2.5-1.5B, Approach D) can drop in later **without rework**. No LLM shipped in v1.
3. **Consent gate:** single tenant-level operator naming-agreement flag (default per signed agreement) + per-person **suppress** list keyed on `roster_id`. No per-person opt-in.
4. **Provenance:** every result records which names were injected, source `cluster_id`/`roster_id`, and match confidence. Always emit **both** generic and named drafts.
5. **Build order:** merge layer first against **seeded/mock phrase boxes + existing recognition data** (no Florence dependency); Florence `<CAPTION_TO_PHRASE_GROUNDING>` wiring is a **later slice** (avoids collision with active `E19-1-REV-*` adapter work).

## Assumptions

- Recognition + roster data model is stable as found (`db/models/identity.py`); names are WordPress-authoritative (ADR-003).
- Description and recognition key off the same `media_id` (attachment id).
- Operator naming-agreement is a product/legal given (per the resolved consent model); E19-4a only enforces the flag, it does not adjudicate consent.
- Florence-2 `florence_small` (E19-1) is the grounding source when the grounding slice lands.

## Success criteria

- Given a `media_id` with ≥1 `user_confirmed` identity and the agreement flag on, the service returns a named draft where each named region maps 1:1 to a confirmed face; ambiguous/low-confidence → generic, **never** a guessed name.
- Suppress list and agreement-off both correctly suppress naming.
- Provenance present on every named result; generic draft always returned alongside.
- Merge layer has unit/integration tests against seeded + real recognition fixtures, passing with **no VLM dependency**.
- Context-diff evidence captured on LocalWP media: same image, generic vs. identity-named draft.

## Not-Doing (v1)

- No on-box reflow LLM (Approach D) — seam only; ship Qwen2.5-1.5B later if NLG reads robotically on real data.
- No write to `_wp_attachment_image_alt` — preview/draft only; the write path is **E19-2**.
- No prompt-injection / instruction-VLM (Approach C) — GPU/provider tier.
- No per-person opt-in system — suppress-list only.
- No WordPress post/product/SEO context pack or output modes — that's the rest of E19-4 (E19-4b+).
- No changes to the E19-1 description contract, schema, route, or Florence adapter internals.
- No new admin UI surface beyond the naming-agreement flag + suppress control plumbing.

## Slice outline (seeds the task plan — not the plan itself)

- **S1** Merge service: join + coordinate-normalize + containment match (mock/seeded phrase boxes). Tests.
- **S2** Grammar-aware NLG reflow + positional fallback, behind the reflow seam. Tests.
- **S3** Consent gate (agreement flag + `roster_id` suppress) + provenance fields; both-drafts output.
- **S4** Wire Florence `<CAPTION_TO_PHRASE_GROUNDING>` into the adapter → real phrase boxes; coordinate-fidelity check across full-res recognition vs. downsampled description.
- **S5** Context-diff demo evidence on LocalWP.

## Dependencies & coordination

- **Depends on:** E19-1 (done). **Independent of:** E19-2 (write path) by the preview-only boundary.
- **Coordination risk:** active `E19-1-REV-A/B/C/D` tasks may touch the Florence adapter. S1–S3 are model-independent and avoid it; S4 (grounding wiring) must be sequenced after those settle or coordinated with that agent.

## Intake Q&A (recorded)

| Question | Answer |
| --- | --- |
| Epic or task; breadth | Task plan under E19 — **focused identity merge (E19-4a)**, not full E19-4 |
| Reflow approach in v1 | **Grammar-aware NLG now, LLM-ready seam** for later Qwen2.5-1.5B |
| Output | **Preview/draft only** (write path stays E19-2) |
| Build order | **Merge layer first (mocked)**; Florence grounding wired as a later slice |
