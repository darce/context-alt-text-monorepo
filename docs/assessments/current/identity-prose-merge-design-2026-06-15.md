# Merging Curated Identities into Description Prose — Design Assessment

> **Status:** Design assessment / decision input. Not an epic or task plan.
> **Date:** 2026-06-15
> **Task:** `MAINT-identity-prose-merge-20260615`
> **Question evaluated:** How to merge curated/confirmed clustered identities (roster names + face boxes) into the written prose of a generated image description, seamlessly for the user, on the OCI A1 VM.
> **Source inputs:** Code (`apps/prototype-description-service` recognition + roster + db models), [segmentation-vlm-pipeline-feasibility-2026-06-15.md](./segmentation-vlm-pipeline-feasibility-2026-06-15.md), [privacy-trust-and-vlm-fit-investigation-2026-06-13.md](./privacy-trust-and-vlm-fit-investigation-2026-06-13.md), [context-aware-image-description-roadmap-2026-06-13.md](../../roadmaps/context-aware-image-description-roadmap-2026-06-13.md) (Phase 5).
> **Revision (2026-06-15):** consent model resolved by operator decision (admin-only plugin + blanket operator naming-agreement); reflow approach expanded (grammar-aware NLG vs. small on-box LLM vs. instruction-VLM) and the "small LLM on the VM?" question answered.

---

## Verdict (TL;DR)

**The merge is the cheapest part of the whole system, and the OCI A1 hardware is not the bottleneck.** Naming a confirmed person in prose is a spatial-join + string-substitution — pure Python/SQL, sub-millisecond, ~0 RAM. The hardware cost is entirely the VLM pass(es) already budgeted in the feasibility doc; the merge adds **at most +1 Florence pass** (phrase grounding), or **zero** with the positional fallback.

The real constraints are **not** compute. They are:
1. **Correctness of face↔phrase association** (calling the *wrong* person by name is a worse failure than not naming at all). With consent resolved (below), this is now the **top** risk.
2. **Consent posture** — resolved by product decision (admin-only plugin + blanket operator naming-agreement). This *simplifies* the engineering (naming on-by-default behind one operator flag, no per-person opt-in) but is **mitigation + liability-shift, not full elimination** of the privacy concern. See the Consent model section below.

**Recommended (A1-viable now):** post-hoc **deterministic merge** — VLM emits caption + grounded person-phrase boxes; match against `user_confirmed` face boxes by normalized containment; **reflow** names into the prose (grammar-aware NLG, not naive substitution — see §2 below); gate behind the operator naming-agreement; fall back to generic phrasing on any ambiguity. Seamless because it reuses the curation the user *already did* and runs server-side in the describe worker — no new per-image action.

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

### 2. Name injection — reflow, not naive replacement

Florence-2 `<CAPTION_TO_PHRASE_GROUNDING>` returns, for the model's own caption, a box per noun phrase (e.g. "a man", "a woman", "a person") with its character span. Once a phrase is associated with confirmed name *N*, the prose must be **reflowed** so the name reads naturally — a naive head-swap ("A man in a red jacket" → "Daniel, in a red jacket") is brittle: article elision, subject vs. object/possessive position, pronoun coreference on later mentions, and list aggregation ("Daniel and Sarah"). Three reflow tiers, increasing cost:

1. **Grammar-aware NLG (deterministic, no model) — start here.** A small data-to-text realizer that, given `(generic_caption, [(span→name)], face_order)`, fixes articles/case, chooses subject vs. possessive form, aggregates multiple names, and resolves repeated mentions. Zero added RAM/CPU/latency and **zero hallucination risk**. For accessibility alt text — short, literal, factual — this covers the large majority of cases; the patterns are few and enumerable.
2. **Small on-box LLM rewriter (constrained) — feasible on A1, but a deliberate upgrade.** Analysis below. Use only if tier 1 reads robotically on real data.
3. **Instruction-VLM single pass (names in prompt) — best reflow, off-A1.** The model produces named prose natively; reflow disappears as a separate step. Needs a heavier instruction-following VLM → GPU/provider tier (Approach C).

> **Florence-2 cannot be prompted with names.** It is **task-token driven, not instruction-following** — no free-text channel to say "call the left person Daniel." With Florence, naming is necessarily **post-hoc** (tier 1 or 2). Only an instruction-following VLM (Phi-3.5-vision, SmolVLM2, Qwen2.5-VL) supports name-in-prompt (tier 3 / Approach C).

#### Should a small LLM run on the OCI VM for reflow?

**Feasible: yes. First choice: no.** Findings:
- **Latency is fine.** A 1.5B-class instruct model, Q4 via llama.cpp on the A1's Ampere cores, generating the ~50–80 tokens of an alt-text rewrite, lands in roughly **1–3 s** (server-grade ARM far exceeds SBC benchmarks of ~5–8 t/s for 4B models). Tolerable inside the async describe worker.
- **License is fine.** Permissive small picks: **Qwen2.5-1.5B-Instruct** (Apache-2.0) and **SmolLM2-1.7B-Instruct** (Apache-2.0); **Phi-3.5-mini** (MIT, but 3.8B); **Gemma-4** (now Apache-2.0). Avoid **Qwen2.5-3B** (Qwen-Research, non-commercial); treat **Llama-3.2** (custom community license) as review-required. Qwen2.5-1.5B is the strongest instruction-follower of the permissive small set.
- **The real cost is stacking, not speed.** It puts a *second* generative model into the ~5–8 GB headroom already shared by Florence (~1–2 GB), Postgres, and InsightFace — Q4 1.5B adds ~1–1.5 GB and competes for the same 4 cores (passes serialize). Manage via lazy load/unload.
- **The real risk is hallucination.** A free-text rewriter can invent attributes absent from the grounded caption — a correctness/trust regression for accessibility text and a breach of the product's "inspectable visual facts" positioning. **Mitigation is mandatory:** feed the LLM *structured grounded facts + names* (not the raw image), constrain hard (low temperature; "use only these facts and names, add nothing"), and **validate output against the source caption**, rejecting any new content nouns.
- **It may be a stopgap.** The cleanest long-term reflow is tier 3 (instruction-VLM, single pass) on a GPU/provider tier; heavy investment in an on-box reflow LLM is partly throwaway if the roadmap heads there.

**Recommendation:** ship tier 1 (grammar-aware NLG). Add the small on-box LLM (tier 2: **Qwen2.5-1.5B-Instruct**, Q4 llama.cpp, constrained + validated) only if deterministic reflow reads robotically on real data — and treat it as a **data-to-text realizer of grounded facts, never open generation**. Prefer tier 3 once off the A1.

### 3. Seamlessness

"Seamless" = the curation the user already performed in WordPress (confirming clusters, assigning names) **automatically** appears in generated prose with **no extra per-image step**. The merge runs **server-side in the describe worker**, joined by `media_id`. The user sees a named draft; they never invoke the merge.

---

## Approaches (the merge mechanism)

| # | Approach | Extra VLM passes | A1 CPU fit | Fluency / seamlessness | License |
| --- | --- | --- | --- | --- | --- |
| **A** | **Deterministic post-hoc** (ground phrases → containment-match → template substitution) | +1 (grounding) | ✅ excellent (merge ≈ 0 cost) | good; integrated into prose | MIT (Florence only) |
| **B** | **Positional fallback** (order confirmed faces left→right, prepend/append: "Left to right: Daniel, Sarah.") | 0 | ✅ best | adequate; less woven in | MIT |
| **C** | **Prompt-injection** (names → instruction VLM prompt, single pass) | 0 extra (replaces Florence) | ⚠️ poor on A1 (heavier VLM) | best; native prose | model-dependent (Phi/SmolVLM permissive; Qwen review) |
| **D** | **A + small on-box LLM rewriter** (grounded facts → constrained realize) | +1 grounding +1 text | ✅ feasible (~1–3 s, +~1–1.5 GB; stacks on Florence) | high; constrained to grounded facts | Apache (Qwen2.5-1.5B / SmolLM2-1.7B) |

**Recommendation:** ship **A** (with grammar-aware reflow) plus **B** as the zero-pass fallback when grounding is absent/low-confidence. Add **D** only if deterministic reflow is insufficient on real data — as a *constrained, validated* realizer, not open generation. Defer **C** to a GPU/provider tier.

---

## Consent model (resolved 2026-06-15)

**Product decision:** the WordPress plugin is **admin-operator-only**, and operators give a **blanket agreement** to person-naming. This resolves the engineering gate and removes the worst fact patterns — but, to be honest about scope, it is **mitigation + liability-shift, not full elimination** of the privacy concern. (Risk analysis, not legal advice; get counsel before any "BIPA/GDPR compliant" claim.)

**What admin-only + operator agreement genuinely solves:**
- No public/end-user uploads, no public face lookup, no cross-tenant or surveillance use — the high-severity patterns the privacy assessment flags simply don't exist.
- The operator becomes the accountable **controller**; Alt Context is the **processor**. Engineering can treat naming as **on-by-default behind a single operator-level agreement flag** — no per-person opt-in needed for v1.

**What it does NOT solve (the nuance that matters):**
- The parties protected by BIPA/GDPR are the **people in the photos** (the data subjects), not the operator. An operator accepting terms is **not** consent from those people. The privacy assessment is explicit: *"customer contracts do not cure missing subject notice or written release."*
- The durable mechanism is an operator **attestation/warranty** — the operator affirms they hold the rights, notice, and consent for the people in their media and will not use the tool for prohibited biometric purposes. "Blanket agreement" carries weight only when framed this way (operator warranting subject consent), backed by the already-built retention/purge/export controls and the no-training-reuse posture.

**Engineering implications (simplified, not removed):**
- One tenant-level operator naming-agreement flag (its default reflects the signed agreement); **no per-person opt-in** for v1.
- Keep a cheap **per-person suppress** escape hatch keyed on `roster_id` (the operator may still choose not to name someone) — far smaller than an opt-in system.
- Keep **provenance** on every result: which names were injected, from which `cluster_id`/`roster_id`, and match confidence (the roadmap's auditability trait, and the operator's audit trail if a subject objects).
- Always emit the generic draft alongside the named draft.

## Correctness guardrails (mis-naming is the worst outcome)

Name **only** when **all** hold; otherwise degrade to generic:
- `user_confirmed = TRUE` and `label` present (never name a raw cluster).
- A **single** high-confidence containment match between one confirmed face and one person-phrase (1:1). Ambiguous many-to-one → do not name that region.
- Detection `confidence` and grounding presence above thresholds.
- Operator naming-agreement active **and** the person not on the per-person suppress list (`roster_id`).
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
2. **Add the operator naming-agreement flag + per-person suppress + provenance** (small backend + WP curation surface; far lighter than a per-person opt-in system — see Consent model).
3. **When Florence-2 lands** (roadmap Phase 2), wire Approach **A** (caption + `<CAPTION_TO_PHRASE_GROUNDING>`) with **B** fallback.
4. **Defer C/D** to a GPU/provider tier; revisit once a heavier instruction VLM is hosted.

Describe-worker flow: `VLM → (caption, phrase_boxes)` → `join confirmed faces by media_id` → `normalize+containment-match` → `agreement + suppress gate` → `reflow (grammar-aware NLG; optional constrained LLM)` → emit **both** generic and named drafts + provenance.

## Open questions / required evidence

- Florence-2 grounding recall for generic "person/man/woman" phrases on real WordPress media (drives how often A succeeds vs. falls back to B).
- Coordinate fidelity after downsample — verify normalized boxes still align across recognition (full-res) and description (downsampled).
- Reflow quality: how often deterministic grammar-aware NLG reads robotically on real captions — the threshold for adding the constrained on-box LLM (D). If added, measure hallucination rate and validation-rejection rate.
- Operator-agreement UX: exact attestation wording (rights/notice/consent warranty); where the per-person suppress control lives in the curation UI.

## References

- Florence-2 phrase grounding & coordinate format: [Roboflow — phrase grounding](https://blog.roboflow.com/what-is-phrase-grounding/) · [Florence-2 tasks (Analytics Vidhya)](https://www.analyticsvidhya.com/blog/2024/07/how-to-perform-computer-vision-tasks-with-florence-2/) · [Florence-2 deep-dive (TDS)](https://towardsdatascience.com/florence-2-mastering-multiple-vision-tasks-with-a-single-vlm-model-435d251976d0/)
- Naming policy / biometric posture: [Meta — update on face recognition (2021)](https://about.fb.com/news/2021/11/update-on-use-of-face-recognition/) · [740 ILCS 14/15 (BIPA)](https://www.ilga.gov/documents/legislation/ilcs/documents/074000140K15.htm) · [GDPR Art. 9](https://gdpr-info.eu/art-9-gdpr/)
- Instruction-following VLM alternatives (Approach C): [Phi-3.5-vision](https://huggingface.co/microsoft/Phi-3.5-vision-instruct) · [SmolVLM2-2.2B](https://huggingface.co/HuggingFaceTB/SmolVLM2-2.2B-Instruct)
- Small on-box reflow LLM (Approach D): [Qwen2.5-1.5B license (Apache-2.0)](https://huggingface.co/Qwen/Qwen2.5-1.5B/blob/main/LICENSE) · [SmolLM2-1.7B-Instruct (Apache-2.0)](https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct) · [llama.cpp](https://github.com/ggml-org/llama.cpp) · [Llama-3.2 community license](https://www.llama.com/llama3_2/license/)
