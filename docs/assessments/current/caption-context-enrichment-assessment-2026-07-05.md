# Richer Caption Context — Fusion Architecture, OpenCV 5, Brand Detection, PG18/19

> **Status:** Assessment / decision input. Not an epic or task plan.
> **Date:** 2026-07-05
> **Task:** `VLM-2` (branch `feature/vlm-2`)
> **Question evaluated:** How to raise generated image-description quality by (a) adopting a context-fusion caption architecture (arXiv 2606.18553), (b) using OpenCV 5 for CPU-only scene analysis and dependency reduction, (c) adding user-defined brand/logo detection that auto-tags instances via the clustering engine, and (d) exploiting PostgreSQL 18/19 features.
> **Source inputs:** arXiv [2606.18553v1](https://arxiv.org/html/2606.18553v1) (Hierarchical Multi-Modal Retrieval for Knowledge-Grounded News Image Captioning, EVENTA 2025); [opencv.org/opencv-5](https://opencv.org/opencv-5/); [PostgreSQL 18 announcement](https://www.postgresql.org/about/news/postgresql-18-released-3142/); [PostgreSQL 19.0 release notes](https://www.postgresql.org/docs/release/19.0/) (beta); `literature/extracted/refactoring/distilled/`; code (`apps/prototype-description-service`); [identity-prose-merge-design-2026-06-15.md](./identity-prose-merge-design-2026-06-15.md); [segmentation-vlm-pipeline-feasibility-2026-06-15.md](./segmentation-vlm-pipeline-feasibility-2026-06-15.md); [context-aware-image-description-roadmap-2026-06-13.md](../../roadmaps/context-aware-image-description-roadmap-2026-06-13.md); [roadmap-pg18-upgrade.md](../../roadmaps/roadmap-pg18-upgrade.md); [e19-4a-identity-prose-merge-scope.md](../../scopes/e19-4a-identity-prose-merge-scope.md).
> **Revision C (2026-07-05):** harness-inventory audit across `/Volumes/Butter/archives/archived-recognition.4.2.3`, `/Volumes/Butter/archives/archived-recognition-service`, the monorepo root, and the description service — **no caption-quality harness was ever started**; §6a records the inventory and the bare-MVP build plan, §6b the golden-set image taxonomy, §6c the metric stack (precision-gated, not recall-first). Ingested the 13 PDFs newly added to `~/Documents/research papers/` — adopts: Williams et al. 0–4 alt-text rubric (W4A'22), Rescribe G1–G8 + coherence/informativeness metrics (UIST'20), Screen Parsing UI-description framing (UIST'21); rest skips (§9 addendum). Length policy revised: summary-first, no hard cap on the detailed tier (Williams: longer scored *higher*).
> **Revision B (2026-07-05):** folded a 12-paper sweep — [BACON 2407.03314](https://arxiv.org/pdf/2407.03314), ["Inserting Faces inside Captions" 2405.02305](https://arxiv.org/pdf/2405.02305), [PerceptionRubrics 2606.28322](https://arxiv.org/html/2606.28322v2), [BLV curator study 2605.31080](https://arxiv.org/html/2605.31080v1), [HBoP 2502.10118](https://arxiv.org/html/2502.10118v2), [VISE 2606.27373](https://arxiv.org/html/2606.27373v1), [MosAIC 2411.11758](https://arxiv.org/html/2411.11758v1), [HyFL-CLIP 2607.00428](https://arxiv.org/html/2607.00428v1), [DataComp-VLM 2606.28551](https://arxiv.org/html/2606.28551v2), [CANVAS 2606.09846](https://arxiv.org/abs/2606.09846), [Accessible-XAI 2603.02486](https://arxiv.org/html/2603.02486v1), [TICR 2410.06314](https://arxiv.org/html/2410.06314v1) — plus the local library (`~/Documents/research papers/`, 14 further papers incl. the deployed Eluvio sports-captioning system, CoTalk, Ensemble Decoding, Whitened CLIP, RE-VLM, CIAN) and a July-2026 small-VLM landscape survey. Adds §§3a, 9–11; rewrites §6; re-sequences §12. BLV framing sharpened: the target is captions that "paint the image" for blind/low-vision users.

---

## Verdict (TL;DR)

1. **Adopt the paper's fusion pattern, skip its retrieval machinery.** 2606.18553's quality gain (CIDEr 0.039 → 0.123, 3× over vision-only) comes from a three-stage contract: *structured visual description → bounded relevant-context selection → LLM fusion instructed to "anchor in visual evidence, inject names/facts from provided context."* That is exactly our `context_pack → caption` shape. Our context arrives **pre-resolved** (WP context pack + roster-confirmed identities + future brand tags), so the paper's news-corpus retrieval stack (discourse weighting, temporal clustering, citation PageRank) is irrelevant. What transfers: the Stage-1 structured description schema, the Stage-2 *text-embedding* relevance filter for oversize context, and the Stage-3 fusion prompt contract. This **validates** the E19-4a "LLM-ready seam": deterministic merge first, instructed fusion as the upgrade tier.
2. **OpenCV 5 is a credible dependency-reducer — spike-gated, not a commitment.** The rewritten CPU DNN engine (>80% ONNX op coverage, QDQ quantized models, beats onnxruntime by 11–36% on their CPU benchmarks) is a candidate replacement for `onnxruntime` (InsightFace path), and native VLM inference (PaliGemma, Qwen 2.5) is a candidate replacement for torch/transformers (Florence path). Kept SIFT/ORB plus new ALIKED + LightGlueMatcher are the enabling layer for brand detection. Risks: SFace model-weight license history, text-detection zoo models unverified under the new engine, ENGINE_NEW is CPU-only (fine for A1).
3. **Brand detection: template feature-matching first, open-vocab later.** Tenant uploads a logo (or selects a bbox in an existing image) → keypoint template (ORB/ALIKED) + a global crop embedding in pgvector → per-image matching (LightGlue/BF) emits bbox + confidence → instances stored in the existing identity tables under a non-face `identity_type` → confirmed brand names enter the `ContextPack` and flow through the **same fusion stage as identities**. No new clustering algorithm needed; the curation loop (confirm/reject) is reused as-is.
4. **PG18 yes (per existing roadmap), PG19 no (beta).** PG18 is GA and already has an adoption roadmap; nothing here changes it — uuidv7 for the new brand tables, AIO + skip scan help pgvector-filtered reads. PG19 is beta-1: track `INSERT … ON CONFLICT DO SELECT` (one-round-trip caption-cache get-or-insert) and `REPACK CONCURRENTLY` (online bloat reclaim on churny embedding tables) for adoption **after GA**; build nothing against it now.
5. **Quality target needs a measuring stick.** The repo has **no** caption-quality benchmark — the E19-1 harness measures latency/RSS with eyeball quality. Before fusion work lands, freeze a small tenant-representative reference set and score description drafts (deterministic checks + LLM-judge rubric); otherwise "higher quality captions" is unfalsifiable. §6 (rev B) specifies the harness: PerceptionRubrics-style gated Must-Right/Easy-Wrong rubrics + insertion-rate KPI + cheap CPU gates.
6. **The deterministic identity merge is production-validated (rev B).** "Inserting Faces inside Captions" (2405.02305) is our E19-4a design implemented: post-hoc name insertion via attention-heatmap ∩ face-bbox overlap hit **93.2% insertion rate** and lifted *every* caption metric on *every* base model — and they *discarded* LLM rewriting for bias. Our Florence-2 phrase-grounding boxes are strictly stronger than their diffuse proxy heatmaps (Θ=0.05). Eluvio's Super Bowl LIX captioner is deployed proof of **constrain-then-map**: the model emits only roster-checkable tokens with HIGH/LOW confidence; names are mapped from the roster, never generated (91.2 vs 81.0 BERTScore). Deterministic-first, LLM-later is no longer a bet; it is the published consensus.
7. **A slow "detailed description" tier is realistic on the A1 now (rev B).** Qwen3-VL-4B-Instruct — E19-1's measured quality winner (408 s/img unquantized, 9.6 GB, no hallucination) — now ships **official GGUF**; Q4 via llama.cpp is estimated 1–3 min/img on ARM (unverified, re-benchmark). Async-worker only, opt-in, with user-facing expectation setting ("detailed description, takes a few minutes"). Bake off against **CapRL-Qwen3VL-4B** (caption-specialized RL tune, Apache-2.0, official GGUF) and MiniCPM-V. No Florence-3 exists; Florence-2 stays the fast interactive tier.

---

## 1. Current state (facts)

- **Pipeline:** `POST /scene/describe/multipart` → `VisualFactsService.describe()` (`scene/application/visual_facts_service.py`): validate → hash → cache-read (6-tuple key incl. `context_hash`) → adapter via `asyncio.to_thread` → persist (`ImageDescription`, JSONB) → audit.
- **Adapters:** `seeded` (deterministic, applies context-pack hints to the draft) and `florence_small` (`LocalCpuDescriptionAdapter`, Florence-2-base-ft CPU, `<MORE_DETAILED_CAPTION>` + `<OD>`). **The real adapter ignores context entirely** (`context_applied=False`) — context currently only affects the cache key and the seeded fixture. `florence_large`/`gpu_phi4` are fail-closed stubs.
- **Context pack:** typed `ContextPack` (`scene/interface_adapters/http/schemas/requests.py`) = attachment/post/taxonomy/product + **`IdentityContext` (in flight on `main`, E20)**: `policy.person_naming`, roster-bound `IdentityContextItem(name, identity_id, cluster_id, source)`, `review_reasons`. WordPress owns collection + privacy filtering; backend normalizes and hashes.
- **Identity→prose merge:** scoped (E19-4a) and design-assessed (2026-06-15) but **unbuilt**. No `named_prose`, no phrase grounding, no merge service in `scene/`.
- **Clustering engine:** InsightFace `buffalo_l` 512-d embeddings (onnxruntime), HDBSCAN + constrained HAC, pgvector (IVFFlat, cosine) in `media_identities`, curation state + `roster_id` + `user_confirmed` in `identity_clusters`, centroid MV with dirty-tracking. **No non-face detection of any kind** (no logo/object detector; Florence `<OD>` labels are hallucination-prone per the E19-1 memo).
- **Benchmarks on hand:** `scripts/benchmark_local_vlm.py` + E19-1 artifacts (`docs/tasks/19.0/E19-1-*`) — latency/RSS on 3 hand-picked images; Florence-2-base-ft binding result 11–17 s/img, 2.48 GB RSS on OCI A1. No COCO/NoCaps/DOCCI/CIDEr/CLAIR anywhere in the repo. E20-11 plans a hosted-provider benchmark harness (not yet executed).

## 2. Paper ingest — what transfers (arXiv 2606.18553)

Pipeline: hierarchical multi-modal **article retrieval** (CLIP-B/32, structure/discourse-aware scoring, temporal + citation refinement) → three-stage captioning: (S1) VLM writes a **structured** description D_visual (objective content incl. legible text / contextual inference / mood / speculative headline); (S2) **text-only** embedder (BGE-M3-class) ranks retrieved-article sentences against D_visual, top-3 + neighbors, restored to source order; (S3) LLM fuses {image, D_visual, selected context} under an explicit *anchor-visual/inject-factual* instruction. Retrieval + S2 are CPU-trivial; VLM/LLM are unspecified (open risk for small-model quality).

| Paper component | Our equivalent | Transfer? |
| --- | --- | --- |
| Article retrieval stack (Phase A) | WP context pack + roster/brand joins — context is already resolved per media item | **No** — dead weight for us |
| S1 structured D_visual (4 fixed dimensions) | `VisualFacts` today is caption + objects | **Yes** — schema-shape the VLM output (objects/setting/legible text; inference; mood) instead of one prose blob; gives the merge + fusion stages typed anchors |
| S2 text-embedding relevance filter | Nothing (context pack is small today) | **Later** — becomes relevant when context packs grow (long post bodies, many taxonomy terms); note the finding that *text* embeddings beat multimodal ones for this matching |
| S3 fusion prompt contract | E19-4a "Approach D" LLM seam (unbuilt) | **Yes** — this is the strongest evidence yet that instructed fusion of (visual facts + named context) is where quality comes from; names enter via provided text, not via the vision model |
| Evidence | CIDEr 0.039 → 0.123 vs vision-only at flat CLIPScore | Grounding in provided context ≈ **3× lexical/factual quality**; visual fidelity unharmed |

Implication: **do not** chase caption quality primarily through a bigger vision model. The paper's gain came from context injection under a disciplined prompt contract — our roster identities and brand tags are *higher-precision* context than their retrieved articles.

## 3. Proposed caption-composition architecture

Three phases, mapped to the refactoring literature (Split Phase; ports & adapters; special-case objects; per-provider circuit breaker/timeout; asyncio fan-out — see §7):

```
Phase 1  VISUAL FACTS (per-image, cacheable, context-free)
         florence/paligemma adapter → structured VisualFacts
         (objects+setting+legible text | inference | mood) + person phrase boxes
Phase 2  CONTEXT ASSEMBLY (per-request, cheap, deterministic)
         providers behind ports, fan-out concurrently, each with timeout + special-case
         "absent" result:
           identity provider  → confirmed faces ⋈ phrase boxes   (E19-4a SQL join)
           brand provider     → confirmed logo instances          (§5)
           wp provider        → attachment/post/taxonomy/product  (already typed)
Phase 3  PROSE COMPOSITION (tiered)
         Tier 0: deterministic merge + grammar-aware reflow       (E19-4a, A1-viable now)
         Tier 1: instructed fusion — small LLM/VLM given {structured facts,
                 assembled context} under the anchor-visual/inject-factual contract
                 (paper S3; hosted or future on-box model)
```

Contract changes implied (all greenfield, no migration): structure `VisualFacts` along S1 dimensions; extend `ContextPack` with a `brands` list mirroring `IdentityContextItem` (`name`, `template_id`, `instance_bbox`, `source`, `confidence`); keep Phase-1 output in the existing cache row (it is context-free ⇒ cache hit rate improves — today `context_hash` needlessly invalidates the expensive VLM pass when only context changes; splitting phases lets the visual-facts row be keyed without `context_hash` and only the cheap composition re-run).

That cache observation is the single biggest latency/quality win available without touching models: **an 11–17 s Florence pass is currently re-run whenever a post title or taxonomy term changes.**

### 3a. Refinements from the paper sweep (rev B)

**Naming discipline — constrain-then-map (Eluvio, deployed):** no stage ever *generates* a person or brand name. Detectors emit only roster-checkable tokens (cluster/template IDs + HIGH/LOW confidence); names are mapped from the roster/brand registry deterministically at merge time. Uncertain identities never enter any prompt — the caption says "a person at the podium" instead. Few-shot exemplars *hurt* entity accuracy in their production system; prefer tight instructions.

**VisualFacts schema conventions (BACON):** number same-category instances (`person 1`, `person 2`) — exactly the slot structure the face-name merge joins on; carry a bbox per object as a first-class field; split foreground/background and style/theme; keep the serialization regex-parseable for models without JSON mode. BACON's ablation (element-wise structured queries beat "describe this image" by +26–50% semantic consistency) is direct evidence for structured facts over one dense caption.

**Prose contract for BLV output (HBoP + curator study 2605.31080 + CANVAS; length policy revised rev C):** tiered composition — scene-level sentence(s) first (orientation/setting; first sentence ≤125 chars gist per Trewin/Williams), then regional groupings, then fine detail; sensory vocabulary (color, texture, mood, atmosphere); concrete quantified detail over evaluative adjectives (tactile-graphics study); jargon ban; **no hard length cap on the detailed tier** — Williams et al. found longer descriptions score *higher* (4-scoring μ=117 words vs 2-scoring μ=34); penalize missing content, not word count (the fast alt-text tier stays bounded for the attribute); don't restate what the surrounding post already says (Rescribe G2 — the context pack tells us what's already said); **hedge uncertain claims** ("appears to be…") and surface provenance in phrasing for roster facts ("identified from your site's people roster"). Region selection is deterministic CPU math (size-ranked NMS + K-means over boxes, ~20 lines); Florence-2's native region captioning replaces HBoP's SAM+BLIP stack. Anti-hallucination instruction (FAST-GOAL, tested): "describe ONLY what is visibly present; do not speculate about events outside the frame."

**Fact merge with source precedence (RE-VLM):** every fact is tagged with its source; on conflict, trust order wins — identity facts *only* from roster, appearance facts from the VLM, contextual facts from the context pack. The fusion stage is **merge-only**: no new semantic units may appear that aren't traceable to an input fact (CoTalk's `units_out ⊆ units_in` contract — machine-checkable).

**Context pre-summarization (CIAN):** never dump raw post bodies into the fusion prompt; summarize/select first (the Stage-2 relevance filter from §2 or a cheap extractive step). Do not adopt CIAN's n-gram refinement (metric cosmetics, hallucination-risky).

**CPU-cheap verification layer (VISE + Ensemble Decoding + Whitened CLIP + 2405.02305):**
- *Crop-and-reinspect:* re-run Florence-2 on face-cluster bbox crops; keep only facts consistent across full-image and crop passes (hallucination drops sharply with fewer irrelevant objects in frame).
- *Ghosting probe:* blur a claimed entity's region and re-query; if the claim survives, it was prior-driven — flag it.
- *Geometric consistency:* flip/transform the image, re-detect, GIoU against the projected roster box as a confidence gate before naming.
- *Name-correction rule:* replace any captioner-guessed name with the roster-confirmed one (kills an entire hallucination class); count-aware syntax rules ("two men" → both names or neither).
- *Whitened CLIP:* near-free (one CLIP pass + a matvec) image-OOD gate (screenshots/renders → conservative template) and name-insertion likelihood-delta sanity check — never standalone, always paired with roster confidence.

## 4. OpenCV 5 evaluation (CPU-only fit)

Confirmed from the release surface (June 2026, Apache-2.0, C++17, Python w/ NumPy 2.x):

| Capability | OpenCV 5 fact | Service relevance |
| --- | --- | --- |
| DNN rewrite | ONNX op coverage ~22%→>80%; QDQ quantized; graph fusion; 4 engines, `ENGINE_NEW` **CPU-only** | Candidate to run buffalo_l / detectors without `onnxruntime`; their CPU benchmarks beat ORT by 11.5% (YOLOv8n) – 36.6% (OWLv2) |
| Native VLM | Built-in tokenizer + KV cache; runs **PaliGemma**, Qwen 2.5, Gemma 3 without external runtimes | Candidate to replace torch/transformers for the caption pass — would collapse the heaviest dependency in the `[vlm]` extra |
| Features module | SIFT/ORB/FAST kept; new **ALIKED**, DISK, **LightGlueMatcher** (confidence-scored attention matcher) | The brand-detection enabling layer (§5); ALIKED+LightGlue is robust at low texture / wide baseline where ORB fails |
| Open-vocab detection | OWLv2 runs on the new engine | Brand-detection quality tier (image-conditioned queries); also a sounder object-facts source than Florence `<OD>` |
| Core | FP16/BF16 Mats, Universal Intrinsics 2.0 (3–4× common ARM ops), KleidiCV HAL (Graviton-validated ARM) | Directly relevant to OCI A1 (Ampere ARM) |

**Caveats:** FaceDetectorYN/FaceRecognizerSF and text-detection (DB/CRNN) zoo models are not mentioned on the release page — assume carried over, verify under ENGINE_NEW before relying on them; SFace weights have historical license questions (opencv/opencv#21192) — irrelevant unless we drop InsightFace; GPU on the new engine is roadmap-only (we don't care on A1).

**Dependency-reduction matrix (spike before commitment):**

| Today | OpenCV 5 candidate | Confidence |
| --- | --- | --- |
| `onnxruntime` (InsightFace) | DNN ENGINE_NEW running the same ONNX models | Medium — op coverage high, but InsightFace's API wraps ORT; needs adapter-level swap behind the existing embedding port |
| `torch` + `transformers` (Florence) | Native VLM path (PaliGemma-class) | Low-medium — quality on our images unproven; Florence task tokens ≠ PaliGemma prompting; benchmark head-to-head |
| (nothing) logo/brand | features (ORB/ALIKED) + LightGlue + DNN | High — this is net-new capability, no incumbent |

Recommendation: one bounded **spike task** producing a benchmark artifact in the E19-1 JSON format: (a) buffalo_l under cv.dnn vs onnxruntime on A1, (b) PaliGemma-via-OpenCV caption quality vs Florence-2 on the frozen eval set (§6), (c) ORB vs ALIKED+LightGlue logo matching precision on a synthetic logo set. Adopt per-component only where the spike wins; ports & adapters (§7) make each swap a one-adapter change.

## 5. User-defined brand detection (design)

**UX contract:** tenant uploads a logo file **or** draws/selects a bbox on an existing media item → names it → system auto-tags future (and back-fills existing) media where the logo appears; instances appear in the same curation workbench flow as faces (confirm/reject), and confirmed brand names become caption context.

**Detection path (Tier A — ship first, CPU-trivial):**
1. Template registration: normalize crop → keypoints + descriptors (ORB baseline, ALIKED upgrade) stored as a blob; plus one global crop embedding (zoo model) stored in **pgvector** for fast candidate shortlisting.
2. Per-image scan (on upload / on backfill): keypoint match template↔image via LightGlue/BF + geometric verification (homography RANSAC, min-inlier threshold) → bbox + inlier-ratio confidence. Rigid printed logos are the favorable case for this classical pipeline; no training, no GPU, milliseconds per template.
3. Persistence: reuse the identity tables — `media_identities.identity_type` already discriminates row types; add a brand value (greenfield: edit `001_identity_schema.py` directly), instance rows carry bbox + confidence + embedding; a `brand_templates` table (tenant-scoped, RLS, uuidv7 PK once on PG18) holds template metadata + descriptor blob. Template-matching is *classification against a known template*, not unsupervised clustering — so no HDBSCAN involvement; what is reused is the **curation loop** (`user_confirmed`, confirmation_source, review workbench) and the WP-authoritative naming pattern (brand name lives in WP like roster persons, ADR-003 symmetry).
4. Context surface: confirmed instances → `ContextPack.brands` (WordPress collects + policy-filters, mirroring `IdentityContext`) → Phase-3 composition names the brand exactly like a person ("…wearing an Acme jacket" / "…in front of the Acme logo").

**Tier B (quality tier, later):** OWLv2 image-conditioned open-vocab detection for non-rigid/stylized brand appearances (products, vehicles) where keypoint matching fails; also candidate replacement for Florence `<OD>` object facts. Heavier; gate on the OpenCV 5 spike numbers.

**Risks:** false positives on lookalike marks (mitigated: confirm-before-context, the same human-in-the-loop stance as person naming); tiny/low-res logos below keypoint density (declare a min-size floor, surface as `review_reasons`); per-template scan cost grows linearly with template count (bound templates per tenant; pgvector shortlist before keypoint match).

## 6. Caption-quality evaluation design (rewritten rev B)

"Higher-quality captions" currently has no measurement. Standard benchmarks (COCO/NoCaps) mis-fit the product (alt-text + named-context, tenant imagery). Design, assembled from the sweep:

**Golden set:** freeze **20–30 reference images** (extend the E19-1 set: people-with-roster-matches, products, logos, text-in-image, no-context scenes) + human-written reference alt text. External anchor: [AstroCaptions](https://huggingface.co/datasets/momentslab/AstroCaptions) (44k NASA images, 13k named persons, public) for name-insertion regression at scale.

**Gated rubric scoring (PerceptionRubrics — adopt):** per golden image, two rubric lists of atomic booleans. *Must-Right* = context-pack facts (roster-confirmed names iff policy allows, confirmed brands, key objects) — **any Must-Right failure zeroes the image's score**. *Easy-Wrong* = hallucination traps **mined from our own failure modes** (run the pipeline over a corpus, collect frequent hallucinations — e.g. Florence's "dining table" on a flower — convert to standing trap rubrics); score = fraction of traps passed. An LLM judge answers each boolean; gated scoring correlates with human ranking at r=0.916 vs ~0.45–0.60 for DOCCI/DetailCaps-style metrics.

**KPIs:**
- **Insertion rate** (% of confirmed identities that land in the caption) — 2405.02305's benchmark is 93.2%; ours should beat it with real phrase-grounding boxes.
- **Semantic-unit traceability** (CoTalk): parse the caption into object/attribute units; richness = unit count, hallucination = units not traceable to a Florence fact, context-pack field, or roster identity. Enforces the merge-only fusion contract.
- **Tag-coverage completeness** (MosAIC) vs Florence's object list; CHAIR/POPE-style object probes as the hallucination regression suite.

**Cheap CPU gates (no LLM):** FKRE readability band ~50–70 (flag below 45); length error vs reference; repetition ratio (1 − unique/total tokens); Div-2/mBLEU-4 diversity + SBERT relevance (all-MiniLM-L6-v2, CPU-fast) for the detailed tier.

**Judge discipline (curator study):** LLM judges align with BLV humans only on visually-grounded traits (composition/colour, ρ≈0.5–0.6) — trust them there; do **not** trust judge scores for vividness/emotional tone without a small human BLV calibration pass. Score coverage of atomic facts, not word count — PerceptionRubrics confirmed verbose ≠ better.

Store all scores per run in the existing E19-1 benchmark JSON schema so every adapter/fusion change ships a before/after artifact. CIDEr/CLIPScore optional later via E20-11's hosted harness; not a gate. MosAIC's warning stands: free-form enrichment raised completeness but *dropped* correctness (60.2% vs 64.6% baseline) — the gated Must-Right design exists precisely to catch that trade.

### 6a. Harness inventory — nothing to revive; build the bare MVP (rev C)

Audited 2026-07-05 across both Butter archives, the monorepo root, and the description service: **no caption-accuracy scoring (BLEU/CIDEr/CLIP-score/judge-vs-reference) was ever started anywhere** — zero content-grep hits. What exists, and what each contributes to the MVP:

| Artifact | State | Reuse |
| --- | --- | --- |
| `scripts/benchmark_local_vlm.py` (E19-1 S10) | working, latency/RSS only; prints prose for eyeball judgment | **The skeleton**: adapter loading, per-image loop, JSON artifact emission — add a scoring step + golden manifest and it *is* the harness |
| `scene/tests/seed/` | empty placeholder (`.gitkeep` + README) | The intended checked-in fixture slot — put the golden set here |
| `archived-recognition-service/scripts/mock_images/` (~42 real photos) + `mock_entities/` (~18 face crops) | image corpus, **no reference captions** | Seed corpus for several golden classes (people, landscapes); references must be authored |
| `recognition/application/regression_harness/` | fully built — for **face clustering** | Structural template: baseline JSON + report builder + regression assertions; copy the pattern, share no code |
| E20-11 task plan | plan only, zero code | Different axis (provider cost/latency/privacy); the golden manifest should be reusable by it later |
| Remote `bench.py` (E19-1 memos) | never committed | ignore |

**Bare-MVP definition (1–2 days, CPU-only, no LLM judge required to be useful):** `scripts/eval_captions.py` + a golden manifest (`scene/tests/seed/golden.json`: per image — path, context_pack fixture, reference facts list, Must-Right rubrics, Easy-Wrong traps, expected identities). Runs any configured adapter(s), computes the deterministic metric tier of §6c (insertion rate, Must-Right string/policy checks, unit-traceability against the fact list, FKRE, length error, repetition ratio, tag coverage), emits E19-1-schema JSON + a markdown report (regression-harness report-builder pattern, with the accessibility-report dedupe/ignore-list ergonomics so triaged judge errors stay suppressed across runs). The LLM-judge tier (0–4 rubric, Easy-Wrong adjudication) is a second pass behind a flag. **Verdict: yes — build it now; it is the cheapest item in the whole program and every subsequent decision (bake-off, merge, fusion) is blind without it.**

### 6b. Golden-set image taxonomy (rev C)

~24–30 images, every class chosen to *discriminate between models/pipeline stages*, not to average them. Roster-dependent classes use our own seeded people; corpus classes can start from the archive `mock_images/`.

**Identity classes (discriminate merge + recognition):**
1. Single roster person, frontal, well-lit — insertion baseline.
2. Roster person in profile / partially occluded / backlit — grounding + detection floor.
3. **Same person young vs old** (two images, one cluster) — embedding drift; does the name survive age gap.
4. Two roster people + strangers in one frame — *association precision*: right name on right person, strangers stay generic.
5. **Crowd** (10+ faces, 1–2 roster-confirmed) — naming restraint; "a crowd outside the arena, including NAME" vs. hallucinated enumeration.
6. Look-alike of a roster person (non-roster) — the false-positive naming trap; canonical Easy-Wrong rubric.
7. Roster person mid-action — verb + gender accuracy (Florence's documented failure mode).
8. Roster person present but `person_naming` policy disabled — must NOT name; policy-compliance gate.

**Scene classes (discriminate visual-facts quality):**
9. **Abstract art / pure texture** — hallucination pressure; models invent objects here.
10. Landscape, no people — spatial layering, general→specific ordering.
11. Busy interior, many small objects — detail *selection* (does it pick the salient 5 or ramble).
12. Low-light / motion blur / low-res — OOD gate + hedging behavior.
13. Color-critical scene (sunset, product colorways) — color fidelity (the trait LLM judges score reliably).
14. Explicit spatial relations (X left of Y, foreground/background) — the orientation information BLV users rank highest.
15. Emotionally salient scene — mood/atmosphere dimension (judge-caution zone; human-calibrate).

**Text / brand / structured classes:**
16. Legible sign or slide text — transcription fidelity, no paraphrase-invention.
17. Logo, large and clean — brand Tier A baseline.
18. Logo, small / skewed / partial — matcher floor + min-size behavior.
19. Stylized brand on product/apparel — the Tier A vs Tier B (OWLv2) discriminator.
20. **UI screenshot** — structured description per Screen Parsing: screen type, major groups, actionable controls, reading order.
21. Chart/graph — summary-first data description (Williams rubric's home turf).

**Context-pack interplay classes (discriminate fusion):**
22. Context adds non-visible facts (event, place) — weaves without contradicting pixels.
23. **Context conflicts with pixels** (post says X, image shows Y) — source precedence: pixels win for appearance, context never overrides what's visible.
24. No context at all — graceful degradation to pure visual description.

### 6c. What the harness measures — precision-gated, recall second (rev C)

Direct answer to "recall vs other metrics": **recall alone is the wrong primary.** For BLV users a false fact (wrong name, invented object) is strictly worse than a missing fact — MosAIC showed richness and correctness trade against each other, and a screen-reader user cannot cheaply detect the lie. Measure in tiers:

| Tier | Metric | Cost | Gate? |
| --- | --- | --- | --- |
| 1. Correctness gates | Must-Right rubric pass (identity/policy/brand facts); Easy-Wrong trap pass; policy compliance (no naming when disabled) | deterministic / cheap judge | **hard gate — any Must-Right miss zeroes the image** |
| 2. Identity recall | **Insertion rate** (% confirmed identities named; benchmark 93.2%); association accuracy (right name ↔ right person) | deterministic | target, not gate |
| 3. Unit precision/recall | Semantic-unit traceability (CoTalk): precision = units traceable to a Florence fact / context field / roster row (1 − hallucination rate); recall = coverage of reference units (= richness) | one judge or parser pass | report as a **pair**; never optimize recall alone |
| 4. Holistic quality | **Williams 0–4 rubric** (validated, κ=0.91) as the headline score; summary-first structure check (first sentence = gist, ≤125 chars) | judge / partly deterministic | trend metric |
| 5. Readability & specificity | FKRE band 50–70; informativeness = corpus-rarity-weighted nouns (Rescribe) — rewards "Breiðamerkurjökull", penalizes "a scenic view"; repetition ratio; length error *vs. missing content, not vs. a cap* | deterministic | CI warning |
| 6. Richness (detailed tier only) | Div-2 / mBLEU-4 diversity; SBERT relevance; tag-coverage vs Florence object list | deterministic, CPU | trend metric |
| 7. Ops | latency, peak RSS, cold load (existing E19-1 harness) | existing | budget gate per tier |
| 8. Human calibration | small BLV pilot pass on a rubric sample — LLM judges align with BLV humans only on visually-grounded traits (ρ≈0.5–0.6 composition/colour), and technical metrics passing while users stay unsatisfied is a documented failure mode (sign-language CHI'25) | periodic, manual | calibrates tiers 3–4 |

Context-complementarity principle (Williams): judge the alt text *jointly with* the surrounding post content — redundancy with visible text is a flaw, complement is a strength; the context pack makes this mechanically checkable (caption units ∩ post units should be small).

## 7. Refactoring-literature crosswalk (why this shape resists rot)

| Concept (source) | Application here |
| --- | --- |
| Split Phase (Fowler/Beck) | §3's three phases with typed intermediates (`VisualFacts`, assembled context) — visual extraction, context assembly, and prose composition change for different reasons |
| Ports & adapters; isolate third-party (Farley) | Each context provider and each model runtime (ORT vs cv.dnn vs transformers) behind its own port — the §4 swaps become one-adapter changes |
| Strategy map over conditionals (Hickey; Fowler "Repeated Switches") | Provider registry: adding the brand provider = one registration entry, zero edits to the composition service |
| Special Case / Null Object (Fowler, Hickey) | Absent/failed provider returns an empty-context object; the composer never null-checks; degraded output still produced (Nygard SLA-inversion: caption without brand context beats no caption) |
| Circuit breaker + timeouts (Nygard) | Recognition already does this for embeddings; replicate per context provider; asyncio fan-out with `to_thread` for CPU-bound passes (Hattingh) |
| YAGNI / Speculative Generality (Fowler) | Identity + brand + WP = three real providers → the provider port is justified *now*; but no plugin frameworks, no speculative Tier-B code, no PG19-dependent paths until GA |
| Divergent Change / Shotgun Surgery (Fowler) | Acceptance test for the refactor: adding provider #4 (e.g. EXIF/geo) must touch only its own module + one registration line |

## 8. PostgreSQL 18 / 19

**PG18 (GA 2025-09-25): adopt per [roadmap-pg18-upgrade.md](../../roadmaps/roadmap-pg18-upgrade.md) — unchanged, mildly strengthened by this work:** uuidv7 PKs for `brand_templates` + new rows; AIO (up to 3× storage reads) benefits pgvector bitmap-heap scans used by filtered similarity queries; skip scan helps `(tenant_id, …)` composite indexes; virtual generated columns for derived cache keys. pgvector 0.8.x provides PG18-compatible builds.

**PG19 (beta-1 2026-06-04): track, do not build.** Two features earmarked for the caption workload at GA: `INSERT … ON CONFLICT DO SELECT … RETURNING` collapses the describe-path cache get-or-insert to one round trip; `REPACK CONCURRENTLY` reclaims bloat on churny `media_identities`/description-cache tables without exclusive locks (today's answer is VACUUM FULL downtime). Also noteworthy at GA: autovacuum parallel workers, lz4 TOAST default (JSONB `visual_facts` blobs), SQL/PGQ property-graph queries (speculative fit for cluster/identity relationship queries). pgvector-on-19 compatibility unverified.

## 9. Paper sweep — verdict table (rev B)

| Paper | Verdict | What we take |
| --- | --- | --- |
| **["Inserting Faces inside Captions" 2405.02305](https://arxiv.org/pdf/2405.02305)** | **Adopt (design)** | E19-4a validated end-to-end; insertion-rate KPI (93.2% benchmark); candidate person-word lexicon + count-aware syntax rules; name-correction rule; ≥90% ID-confidence gate; AstroCaptions eval set; their own ablation justifies deferring LLM fusion. Our phrase-grounding boxes replace their weakest component (proxy attention heatmaps) |
| **[BACON 2407.03314](https://arxiv.org/pdf/2407.03314)** | Steal-ideas | VisualFacts schema conventions: numbered same-category instances, per-object bbox, fg/bg + style/theme split, regex-parseable serialization; description-based CLIP re-ranking to disambiguate same-category instances; structured queries beat dense-caption prompting. Skip its 13B pipeline/dataset |
| **[PerceptionRubrics 2606.28322](https://arxiv.org/html/2606.28322v2)** | **Adopt (methodology)** | Gated Must-Right/Easy-Wrong rubric eval (§6); Easy-Wrong mining recipe from own failure modes; length ≠ quality guardrail |
| **Eluvio Stylized Sports Captioning** (local PDF; deployed Super Bowl LIX) | Steal-ideas (strongly) | Constrain-then-map naming in production; confidence field on identity items; HIGH-only naming gate; no uncertain names in any prompt; instructions over few-shot |
| **[BLV curator study 2605.31080](https://arxiv.org/html/2605.31080v1)** | Steal-ideas | Prototype-as-prompt-contract (orientation-first structure, verbosity spec); 5-trait BLV rubric; judge-calibration protocol; length-error/repetition CI gates |
| **[HBoP 2502.10118](https://arxiv.org/html/2502.10118v2)** | Steal-ideas (borderline adopt) | Global→regional→fine tiered caption schema mapped onto Florence-2 region captioning; NMS+K-means region selection; Div-2/mBLEU-4/SBERT diversity-relevance eval |
| **[VISE 2606.27373](https://arxiv.org/html/2606.27373v1)** | Steal-ideas | Ghosting + GIoU geometric-consistency checks as CPU verification primitives; CHAIR/POPE regression metrics |
| **CoTalk** (local PDF) | Steal-ideas | Semantic-unit traceability metric; merge-only fusion contract (`units_out ⊆ units_in`) |
| **Ensemble Decoding (ICLR 2025)** (local PDF) | Steal-ideas | Crop-and-reinspect: second Florence pass on face crops + cross-pass fact agreement — cheapest strong hallucination lever |
| **Whitened CLIP (ICML 2025)** (local PDF) | Steal-ideas | Near-free image-OOD gate + name-insertion likelihood delta (never standalone) |
| **RE-VLM** (local PDF) | Steal-ideas | Source-tagged fact graph with trust-order arbitration; human correction-rate as a metric |
| **CIAN** (local PDF) | Steal-ideas | Summarize-before-inject for long context; do NOT copy n-gram refinement |
| **[MosAIC 2411.11758](https://arxiv.org/html/2411.11758v1)** | Steal-ideas | Tag-coverage completeness metric; question-slot decomposition as one deterministic checklist; hard evidence free-form enrichment hurts correctness |
| **[CANVAS 2606.09846](https://arxiv.org/abs/2606.09846)** | Skip (mine) | FKRE readability gate; sensory-vocabulary + hedging prompt language. (High-school Zapier demo otherwise) |
| **[Accessible-XAI 2603.02486](https://arxiv.org/html/2603.02486v1)** | Skip (one idea) | Provenance wording in captions ("identified from your site's roster" vs "appears to be") |
| **[HyFL-CLIP 2607.00428](https://arxiv.org/html/2607.00428v1)**, **[DataComp-VLM 2606.28551](https://arxiv.org/html/2606.28551v2)**, **[TICR 2410.06314](https://arxiv.org/html/2410.06314v1)** | Skip | Retrieval embeddings / training-data curation / archival retrieval competition — wrong layer for us. (Bookmark: DCVLM-trained small checkpoints may become the best 1–2B open VLMs) |
| Local PDFs: FAST-GOAL, GRIP, PhaseWin, Sub-Semantic Seg., TC-JEPA, AI-Safety, Beyond Self-Attention, ImageAuditor | Skip | One harvest: FAST-GOAL's tested anti-hallucination prompt clause (§3a). ImageAuditor footnote: tenant rosters are structurally an image-RAG DB; roster-only naming is already the right defensive shape |
| **Williams et al., "Quality Alt Text in Computing Publications" (W4A'22)** *(rev C)* | **Adopt** | Validated 0–4 rubric (κ=0.91) as headline quality score; summary-first structure rule; longer-scores-higher evidence (no length caps); judge caption jointly with surrounding content |
| **Rescribe (UIST'20)** *(rev C)* | Steal-ideas | Codified AD rules G1–G8 (general→specific, no editorializing, don't restate other channels); coherence (LM log-loss) + informativeness (rarity-weighted nouns) as cheap CPU metrics |
| **Screen Parsing (UIST 2021)** *(rev C)* | Steal-ideas | UI screenshots need structured descriptions (screen type, element groups, reading order) — caption template + golden class 20; modern detection via Florence region tasks, not their 2021 stack |
| *(rev C)* Tactile-graphics ASSETS'21; FixAlly; Apple accessibility-reports TOCHI'23; Sign-language CHI'25; V-JEPA 2.1; SD visual-ICL; DiffMAViL; IMU thesis; Rule-22 CA; JPEG spec (Wallace); EVC codec .docx | Skip | Kept: concrete-detail-over-adjectives; verify-loop acceptance (fused caption must beat deterministic baseline without new hallucinations); dedupe/ignore-list report ergonomics; metrics-pass-users-unsatisfied caution; exemplar-retrieval-by-CLIP-similarity for golden exemplars |

## 10. Model landscape (July 2026) and the "slow but detailed" tier

**What actually changed since E19-1 (June 16):** not architectures — **deployment paths**. Official GGUF + llama.cpp support landed for the exact models we measured. E19-1's numbers (Qwen3-VL-4B: 408 s/img, 9.6 GB; Qwen2.5-VL-3B: 341 s, 8.4 GB) were unquantized transformers/BLAS; Q4_K_M GGUF (~3.3 GB) on the A1's 4 cores should be several-fold faster (est. 1–3 min/img — **unverified, re-benchmark**). No Florence-3; no Phi-5-vision (rumor only); MiMo-VL still 7B-only (GPU-deferred per E19-1); SmolVLM3 does not exist.

| Candidate | Params / license | CPU path | Note |
| --- | --- | --- | --- |
| **CapRL-Qwen3VL-4B** | 4B, Apache-2.0 | official GGUF | Caption-*specialized* RL tune of our measured quality winner; claims > Qwen2.5-VL-72B caption quality, reduced hallucination. **Risk: context-injection obedience unverified** — RL for captions may fight instruction-following |
| **Qwen3-VL-4B-Instruct** | 4B, Apache-2.0 | official GGUF | Known quality (E19-1 winner); strongest instruction-following of the group → best bet for weaving injected names |
| **MiniCPM-V 4.5** | 8B, Apache-2.0* | official GGUF/Ollama | Best hallucination story (RLAIF-V; tops ObjectHalBench). Slowest — deep-detail opt-in only |
| **MiniCPM-V 4.6** | 1.3B, Apache-2.0* | llama.cpp day one | **Fast-tier upgrade candidate over Florence-2**: real instruction-following (can take a context block — Florence cannot), 262k ctx, HallusionBench 58.1 |
| **Qwen3.5-4B/9B** (Mar 2026) | Apache-2.0 | GGUF+mmproj (llama.cpp only) | Newest native-multimodal; vision-hallucination data thin — unverified |
| **Gemma 4 E4B** (Apr 2026) | Apache-2.0 (license change from Gemma 3) | llama.cpp at launch | Low-hallucination captioner lineage; detail depth vs Qwen unclear |
| Moondream 3 preview | 9B-A2B MoE, **BSL 1.1** | unverified | License likely blocks a paid alt-text service — excluded |

\* MiniCPM: Apache-2.0 weights with a free-commercial registration questionnaire — verify terms before shipping.

**Two-tier serving design (users informed — the accepted premise):**
- **Fast tier (interactive, ≤20 s):** Florence-2-base-ft today; spike MiniCPM-V 4.6 (1.3B) as successor — it accepts instructions + context blocks, which Florence structurally cannot, making it the first fast-tier model that can do Tier-1 fusion natively.
- **Detailed tier (opt-in, async, minutes):** Qwen3-VL-4B-class via Q4 GGUF/llama.cpp behind the existing async-worker plan (E19-1 Part C shape). UX: explicit expectation setting ("richer description — takes a few minutes"), job status in the workbench, cache-forever once computed (phase-split caching in §3 means context changes don't re-run it). This directly serves the BLV "paint the image" goal: the E19-1 transcripts show the 4B tier catching the boats and the second dahlia bud that Florence-base misses.
- **Bake-off before adapter build (10 golden images, real context packs):** CapRL-4B vs Qwen3-VL-4B-GGUF vs MiniCPM-V 4.5, scored with §6 (insertion rate, Must-Right gates, hallucinated-unit count, FKRE). No public benchmark measures injected-name weaving — we must test it ourselves. One `DescriptionAdapter` behind the existing protocol once picked; greedy decoding; `/no_think` if reasoning-tuned; torchvision is a required dep if the transformers (non-GGUF) path is used.

## 11. What is realistically implementable now (CPU-only A1) — consolidated

Everything below runs on current hardware; items 1–5 need no new model at all:
1. **E19-4a deterministic merge** (SQL join + containment + reflow) with §3a's constrain-then-map, name-correction, and count-aware rules — production-validated pattern, sub-millisecond.
2. **Structured VisualFacts** (BACON conventions + paper-S1 dimensions) emitted by the existing Florence adapter's multi-task passes.
3. **Verification layer** (§3a): crop-and-reinspect, ghosting probe, GIoU consistency, Whitened CLIP gates — each a Florence/CLIP pass or pure math.
4. **Tiered BLV prose contract** (§3a) in the composition stage + provenance/hedging phrasing.
5. **Eval harness** (§6): gated rubrics, insertion rate, unit traceability, FKRE/repetition gates.
6. **Detailed tier** (§10): GGUF 4B async worker — minutes-per-image, opt-in, informed users.
7. **Brand detection Tier A** (§5): keypoint matching is milliseconds on CPU.

GPU procurement changes *which model* fills the detailed/fusion tiers (MiMo-VL-7B-RL per E19-1), not this architecture.

## 12. Recommended sequencing (revised rev B)

1. **Quality eval harness (§6, build plan §6a)** — promoted to first: extend `benchmark_local_vlm.py` into `eval_captions.py` + golden manifest in `scene/tests/seed/`; deterministic metric tier first, judge tier behind a flag; seed images from the archive `mock_images/` corpus + the §6b taxonomy. Everything after must ship before/after artifacts. 1–2 days, no model work.
2. **E19-4a identity-prose merge (Tier 0)** — already scoped; unblocked; now carries §3a's constrain-then-map + name-correction + count rules. Includes structuring `VisualFacts` (BACON conventions) while the contract is cheap to change.
3. **Phase-split caching** — key the VLM pass without `context_hash`; recompose prose cheaply on context change (§3). Prerequisite for an affordable detailed tier.
4. **Detailed-tier bake-off + adapter (§10)** — GGUF re-benchmark on A1, 3-model bake-off scored by the harness, then one adapter + async worker. Delivers the user-visible "richer caption" win.
5. **Verification layer (§3a)** — crop-and-reinspect first (cheapest strong lever), then ghosting/GIoU gates wired into the merge's confidence decision.
6. **OpenCV 5 spike** — the three head-to-heads in §4; decision memo in E19-1 format.
7. **Brand detection Tier A (§5)** — template registration + matcher + curation reuse + `ContextPack.brands`; depends on 6 only for the ORB-vs-ALIKED choice.
8. **Fusion Tier 1** — instructed fusion behind the E19-4a seam (merge-only contract, source precedence), using the bake-off winner; MiniCPM-V 4.6 spike for a fusion-capable fast tier.
9. **PG18 upgrade** — per existing roadmap, independently schedulable; PG19 items parked until GA.

**Non-goals (explicit):** paper retrieval stacks (2606.18553 Phase A, CIAN SigLIP retrieval); multi-agent captioning (MosAIC — compute-prohibitive, hurts correctness); LoRA fine-tuning (curator study — revisit if a GPU lands); unsupervised logo clustering; any PG19-dependent code; replacing InsightFace before the spike proves parity; COCO-style benchmark chasing.

## 13. Open risks

- Small-model fusion quality unproven (2606.18553 never names its VLM/LLM); the bake-off + eval harness answer this before any adapter is built.
- **GGUF quantization quality loss unmeasured on our images** — the 1–3 min/img estimate and Q4 quality parity are both unverified on ARM/A1; re-benchmark before promising the detailed tier.
- **CapRL's instruction obedience unknown** — a caption-RL model may ignore injected context; that's disqualifying regardless of caption quality, and only our own bake-off will show it.
- OpenCV 5 is a .0 release: pin carefully, keep the ORT path behind the port until ARM/A1 parity is demonstrated.
- Wrong-name/wrong-brand insertion remains the top product risk; the §6 gated rubrics + §3a verification layer are the regression net. LLM judges are only trustworthy on visually-grounded traits — budget a small human BLV calibration pass.
- MiniCPM commercial-registration terms and Moondream BSL need license review before either enters a paid tier.
- `IdentityContext` E20 work is in flight on `main` (uncommitted at assessment time); `ContextPack.brands` must be sequenced after it lands to avoid schema churn.
