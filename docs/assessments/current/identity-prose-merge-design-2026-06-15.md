# Merging Curated Identities into Description Prose — Design Assessment

> **Status:** Design assessment / decision input. Not an epic or task plan.
> **Date:** 2026-06-15
> **Task:** `MAINT-identity-prose-merge-20260615`
> **Question evaluated:** How to merge curated/confirmed clustered identities (roster names + face boxes) into the written prose of a generated image description, seamlessly for the user, on the OCI A1 VM.
> **Source inputs:** Code (`apps/prototype-description-service` recognition + roster + db models), [segmentation-vlm-pipeline-feasibility-2026-06-15.md](./segmentation-vlm-pipeline-feasibility-2026-06-15.md), [privacy-trust-and-vlm-fit-investigation-2026-06-13.md](./privacy-trust-and-vlm-fit-investigation-2026-06-13.md), [context-aware-image-description-roadmap-2026-06-13.md](../../roadmaps/context-aware-image-description-roadmap-2026-06-13.md) (Phase 5).

---

## Verdict (TL;DR)

**The merge is the cheapest part of the whole system, and the OCI A1 hardware is not the bottleneck.** Naming a confirmed person in prose is a spatial-join + string-substitution — pure Python/SQL, sub-millisecond, ~0 RAM. The hardware cost is entirely the VLM pass(es) already budgeted in the feasibility doc; the merge adds **at most +1 Florence pass** (phrase grounding), or **zero** with the positional fallback.

The real constraints are **not** compute. They are:
1. **Correctness of face↔phrase association** (calling the *wrong* person by name is a worse failure than not naming at all).
2. **A missing consent/opt-in layer** — the backend has **zero** naming-policy fields today, yet the privacy posture (Meta-2021 / BIPA / GDPR) requires identity naming to be opt-in, human-in-the-loop, and roster-bound. This is a prerequisite, not an afterthought.

**Recommended (A1-viable now):** post-hoc **deterministic merge** — VLM emits caption + grounded person-phrase boxes; match against `user_confirmed` face boxes by normalized containment; substitute names via a small template; gate behind an opt-in flag; fall back to generic phrasing on any ambiguity. Seamless because it reuses the curation the user *already did* and runs server-side in the describe worker — no new per-image action.

**Upgrade (off-A1 / later):** single-pass **prompt-injection** — feed roster names into an instruction-following VLM's prompt so it weaves names in natively. Most fluent, but needs Phi-3.5-vision / SmolVLM / Qwen-class models (heavier, borderline on A1 CPU, some license caveats) → GPU/provider tier.

> **Decoupling insight:** the identity-merge layer is **model-independent**. It is a pure function `(caption, phrase_boxes, confirmed_faces, policy) → named_prose`. It can be built and tested **now** against the seeded adapter (roadmap Phase 1) and the **already-implemented** recognition data — *before* Florence-2 exists. Do not couple this to the VLM build.

---

## What we can join on (confirmed data model)

The recognition + roster system is **already implemented** and persists everything the merge needs. For any `media_id` (= WordPress attachment ID), a confirmed identity is retrievable with its face box:

| Layer | Entity | Key fields | Source |
| --- | --- | --- | --- |
| Detected face (1 row/face) | `MediaIdentity` | `media_id`, `bbox_x/y/width/height`, `confidence`, `embedding` | `db/models/identity.py:41-101` |
| Face→cluster join | `IdentityMember` | `identity_id`→face, `cluster_id`, `similarity` | `db/models/identity.py:279-307` |
| Curated identity | `IdentityCluster` | `label` (human name), `user_confirmed` (bool), `roster_id` (WP person UUID), `curation_state` | `db/models/identity.py:104-176` |

Join (confirmed people + boxes for one image):
```sql
SELECT mi.bbox_x, mi.bbox_y, mi.bbox_width, mi.bbox_height, mi.confidence,
       ic.label, ic.roster_id
FROM media_identities mi
JOIN identity_members  im ON mi.id = im.identity_id
JOIN identity_clusters ic ON im.cluster_id = ic.id
WHERE mi.media_id = :media_id
  AND ic.user_confirmed = TRUE
  AND ic.label IS NOT NULL
  AND ic.curation_state <> 'dismissed';
```
- **Names are WordPress-authoritative** (ADR-003); the backend cluster carries the synced `label` + `roster_id` (`roster/.../curation_sync_service.py`, op `cluster_person_bound` / `cluster_label_updated`). Person rows themselves live in WordPress only.
- A versioned **projection** (`ClusterDeltaResponse`, `/recognition/clusters/snapshot`) already exposes `label`, `is_user_confirmed`, per-face `bbox`, and `attachment_id` per tenant — so the same data is reachable read-side without new queries.
- **Same key, both systems:** `MediaIdentity.media_id` == the attachment id a description will be generated for. The join is direct.

---

## The merge problem, decomposed

1. **Spatial association** — which described person-region is which confirmed face?
2. **Name injection** — rewrite the prose to use the name.
3. **Policy + seamlessness** — when is naming allowed, and how does it stay invisible to the user?

### 1. Coordinate alignment (the correctness crux)

The two box sources live in **different coordinate spaces**:
- **InsightFace / `MediaIdentity`**: integer **pixel** coords of the analyzed image; the box is the **face only** (small).
- **Florence-2**: location tokens `<loc_0>..<loc_999>` quantized on a **1000×1000 grid** (`NUM_BBOX_*_BINS=1000`, floor), format `<X1><Y1><X2><Y2>`; `post_process_generation` rescales to the **pixel size of the image handed to the processor**; the box is the **whole person** (large).

**Contract:** normalize every box to fractional `[0,1]` coordinates of the **original image W×H**, computed once. This is resolution- and downsample-independent — essential because the describe worker may downsample large images before the VLM while recognition analyzed full-res. Carry `(orig_w, orig_h)` on the description input and divide.

**Match rule (containment, not IoU):** a face matches a person-phrase when the **face-box center lies inside the person-phrase box** AND `area(face) ≪ area(person)`. If several person boxes contain the center, pick the **smallest** (most specific). IoU is wrong here — face and body boxes barely overlap by area.

### 2. Name injection

Florence-2 `<CAPTION_TO_PHRASE_GROUNDING>` returns, for the model's own caption, a box per noun phrase (e.g. "a man", "a woman", "a person") with its character span. Once a phrase is associated with confirmed name *N*:
- **Template substitution** (no model): replace the phrase head, preserve modifiers — `"A man in a red jacket"` → `"Daniel, in a red jacket"`. Handle article/case/pronoun minimally; alt text is short and formulaic, so this is usually adequate.
- **Tiny text rewriter** (one cheap pass): hand the caption + `[(phrase→name)]` bindings to a small text LLM for fluency. Adds latency/RAM/license surface; reserve for when templating reads robotically.

> **Florence-2 cannot be prompted with names.** It is **task-token driven, not instruction-following** — there is no free-text channel to say "call the left person Daniel." So with Florence, naming is necessarily **post-hoc**. Only an instruction-following VLM (Phi-3.5-vision, SmolVLM2, Qwen2.5-VL) supports name-in-prompt (Approach C below).

### 3. Seamlessness

"Seamless" = the curation the user already performed in WordPress (confirming clusters, assigning names) **automatically** appears in generated prose with **no extra per-image step**. The merge runs **server-side in the describe worker**, joined by `media_id`. The user sees a named draft; they never invoke the merge.

---

## Approaches (the merge mechanism)

| # | Approach | Extra VLM passes | A1 CPU fit | Fluency / seamlessness | License |
| --- | --- | --- | --- | --- | --- |
| **A** | **Deterministic post-hoc** (ground phrases → containment-match → template substitution) | +1 (grounding) | ✅ excellent (merge ≈ 0 cost) | good; integrated into prose | MIT (Florence only) |
| **B** | **Positional fallback** (order confirmed faces left→right, prepend/append: "Left to right: Daniel, Sarah.") | 0 | ✅ best | adequate; less woven in | MIT |
| **C** | **Prompt-injection** (names → instruction VLM prompt, single pass) | 0 extra (replaces Florence) | ⚠️ poor on A1 (heavier VLM) | best; native prose | model-dependent (Phi/SmolVLM permissive; Qwen review) |
| **D** | **A + tiny text rewriter** (template, then LLM polish) | +1 grounding +1 text | ⚠️ marginal on A1 | best of the post-hoc options | rewriter-dependent |

**Recommendation:** ship **A** with **B** as the zero-pass fallback when grounding is absent/low-confidence. Defer **C/D** to a GPU/provider tier.

---

## Policy prerequisite (must land before any naming)

The backend has **no** consent, opt-in, or naming-suppression fields (`grep` for consent/opt_in/allow_naming/name_policy → none; only `user_confirmed` and `confirmation_source`, which mean "a human confirmed this is one person", **not** "naming this person in published alt text is allowed"). The privacy assessment is explicit: naming must be **human-in-the-loop, site-roster-bound, consent/provenance-bound** (Meta shut off automatic people-naming in 2021; BIPA/GDPR treat this as biometric processing).

**Required before shipping identity-in-prose:**
- A naming opt-in gate — minimally **per-tenant**, ideally **per-person (`roster_id`)** — default **off**.
- **Provenance** on the result: which names were injected, from which `cluster_id`/`roster_id`, and the match confidence (matches the roadmap's auditability trait).
- Generic fallback always available (the "generic caption vs. context-aware draft" pair the roadmap/assessment already want).

## Correctness guardrails (mis-naming is the worst outcome)

Name **only** when **all** hold; otherwise degrade to generic:
- `user_confirmed = TRUE` and `label` present (never name a raw cluster).
- A **single** high-confidence containment match between one confirmed face and one person-phrase (1:1). Ambiguous many-to-one → do not name that region.
- Detection `confidence` and grounding presence above thresholds.
- Naming opt-in satisfied for that tenant/person.
- On any miss: fall back to count/generic ("two people", "a person") — **never guess a name**.

---

## Hardware fit conclusion (the asked question)

On the OCI A1 (4 OCPU / 24 GB ARM, CPU-only, ~5–8 GB headroom):
- The **merge itself is free** — SQL join + Python containment test + string substitution. No model, negligible CPU/RAM.
- The **only** hardware cost is VLM inference, already analyzed in the feasibility doc. Approach **A** adds **+1 Florence grounding pass**; **B** adds **0**. Both fit the A1 within the existing single-VLM budget.
- The fluent **single-pass** path (**C**) needs an instruction-following VLM that is heavier/slower than Florence on CPU ARM → **GPU/provider tier**, not A1.

So: **identity→prose merge is achievable on the current hardware** via Approaches A/B. It does not move the hardware needle; the VLM choice (prior doc) does.

## Recommended architecture & sequencing

1. **Build the merge layer model-independently now** (against the seeded adapter + existing recognition data). Pure function + tests; no VLM dependency. Lands inside roadmap Phase 1/Phase 5 work without waiting on Florence.
2. **Add the naming opt-in + provenance** fields/contract (prerequisite; small backend + WP curation surface).
3. **When Florence-2 lands** (roadmap Phase 2), wire Approach **A** (caption + `<CAPTION_TO_PHRASE_GROUNDING>`) with **B** fallback.
4. **Defer C/D** to a GPU/provider tier; revisit once a heavier instruction VLM is hosted.

Describe-worker flow: `VLM → (caption, phrase_boxes)` → `join confirmed faces by media_id` → `normalize+containment-match` → `policy gate` → `template substitution` → emit **both** generic and named drafts + provenance.

## Open questions / required evidence

- Florence-2 grounding recall for generic "person/man/woman" phrases on real WordPress media (drives how often A succeeds vs. falls back to B).
- Coordinate fidelity after downsample — verify normalized boxes still align across recognition (full-res) and description (downsampled).
- Templating quality (article/pronoun/possessive) — decide the threshold at which a rewriter (D) is warranted.
- Consent UX: per-tenant vs. per-person opt-in granularity; default copy.

## References

- Florence-2 phrase grounding & coordinate format: [Roboflow — phrase grounding](https://blog.roboflow.com/what-is-phrase-grounding/) · [Florence-2 tasks (Analytics Vidhya)](https://www.analyticsvidhya.com/blog/2024/07/how-to-perform-computer-vision-tasks-with-florence-2/) · [Florence-2 deep-dive (TDS)](https://towardsdatascience.com/florence-2-mastering-multiple-vision-tasks-with-a-single-vlm-model-435d251976d0/)
- Naming policy / biometric posture: [Meta — update on face recognition (2021)](https://about.fb.com/news/2021/11/update-on-use-of-face-recognition/) · [740 ILCS 14/15 (BIPA)](https://www.ilga.gov/documents/legislation/ilcs/documents/074000140K15.htm) · [GDPR Art. 9](https://gdpr-info.eu/art-9-gdpr/)
- Instruction-following VLM alternatives (Approach C): [Phi-3.5-vision](https://huggingface.co/microsoft/Phi-3.5-vision-instruct) · [SmolVLM2-2.2B](https://huggingface.co/HuggingFaceTB/SmolVLM2-2.2B-Instruct)
