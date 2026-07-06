# Richer Caption Context — Fusion Architecture, OpenCV 5, Brand Detection, PG18/19

> **Status:** Assessment / decision input. Not an epic or task plan.
> **Date:** 2026-07-05
> **Task:** `VLM-2` (branch `feature/vlm-2`)
> **Question evaluated:** How to raise generated image-description quality by (a) adopting a context-fusion caption architecture (arXiv 2606.18553), (b) using OpenCV 5 for CPU-only scene analysis and dependency reduction, (c) adding user-defined brand/logo detection that auto-tags instances via the clustering engine, and (d) exploiting PostgreSQL 18/19 features.
> **Source inputs:** arXiv [2606.18553v1](https://arxiv.org/html/2606.18553v1) (Hierarchical Multi-Modal Retrieval for Knowledge-Grounded News Image Captioning, EVENTA 2025); [opencv.org/opencv-5](https://opencv.org/opencv-5/); [PostgreSQL 18 announcement](https://www.postgresql.org/about/news/postgresql-18-released-3142/); [PostgreSQL 19.0 release notes](https://www.postgresql.org/docs/release/19.0/) (beta); `literature/extracted/refactoring/distilled/`; code (`apps/prototype-description-service`); [identity-prose-merge-design-2026-06-15.md](./identity-prose-merge-design-2026-06-15.md); [segmentation-vlm-pipeline-feasibility-2026-06-15.md](./segmentation-vlm-pipeline-feasibility-2026-06-15.md); [context-aware-image-description-roadmap-2026-06-13.md](../../roadmaps/context-aware-image-description-roadmap-2026-06-13.md); [roadmap-pg18-upgrade.md](../../roadmaps/roadmap-pg18-upgrade.md); [e19-4a-identity-prose-merge-scope.md](../../scopes/e19-4a-identity-prose-merge-scope.md).

---

## Verdict (TL;DR)

1. **Adopt the paper's fusion pattern, skip its retrieval machinery.** 2606.18553's quality gain (CIDEr 0.039 → 0.123, 3× over vision-only) comes from a three-stage contract: *structured visual description → bounded relevant-context selection → LLM fusion instructed to "anchor in visual evidence, inject names/facts from provided context."* That is exactly our `context_pack → caption` shape. Our context arrives **pre-resolved** (WP context pack + roster-confirmed identities + future brand tags), so the paper's news-corpus retrieval stack (discourse weighting, temporal clustering, citation PageRank) is irrelevant. What transfers: the Stage-1 structured description schema, the Stage-2 *text-embedding* relevance filter for oversize context, and the Stage-3 fusion prompt contract. This **validates** the E19-4a "LLM-ready seam": deterministic merge first, instructed fusion as the upgrade tier.
2. **OpenCV 5 is a credible dependency-reducer — spike-gated, not a commitment.** The rewritten CPU DNN engine (>80% ONNX op coverage, QDQ quantized models, beats onnxruntime by 11–36% on their CPU benchmarks) is a candidate replacement for `onnxruntime` (InsightFace path), and native VLM inference (PaliGemma, Qwen 2.5) is a candidate replacement for torch/transformers (Florence path). Kept SIFT/ORB plus new ALIKED + LightGlueMatcher are the enabling layer for brand detection. Risks: SFace model-weight license history, text-detection zoo models unverified under the new engine, ENGINE_NEW is CPU-only (fine for A1).
3. **Brand detection: template feature-matching first, open-vocab later.** Tenant uploads a logo (or selects a bbox in an existing image) → keypoint template (ORB/ALIKED) + a global crop embedding in pgvector → per-image matching (LightGlue/BF) emits bbox + confidence → instances stored in the existing identity tables under a non-face `identity_type` → confirmed brand names enter the `ContextPack` and flow through the **same fusion stage as identities**. No new clustering algorithm needed; the curation loop (confirm/reject) is reused as-is.
4. **PG18 yes (per existing roadmap), PG19 no (beta).** PG18 is GA and already has an adoption roadmap; nothing here changes it — uuidv7 for the new brand tables, AIO + skip scan help pgvector-filtered reads. PG19 is beta-1: track `INSERT … ON CONFLICT DO SELECT` (one-round-trip caption-cache get-or-insert) and `REPACK CONCURRENTLY` (online bloat reclaim on churny embedding tables) for adoption **after GA**; build nothing against it now.
5. **Quality target needs a measuring stick.** The repo has **no** caption-quality benchmark — the E19-1 harness measures latency/RSS with eyeball quality. Before fusion work lands, freeze a small tenant-representative reference set and score description drafts (deterministic checks + LLM-judge rubric); otherwise "higher quality captions" is unfalsifiable.

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

## 6. Caption-quality evaluation gap

"Higher-quality captions" currently has no measurement. Standard benchmarks (COCO/NoCaps) mis-fit the product (alt-text + named-context, tenant imagery). Minimal viable eval, before fusion work merges:
- Freeze **20–30 reference images** (extend the E19-1 set: people-with-roster-matches, products, logos, text-in-image, no-context scenes) + human-written reference alt text.
- Deterministic assertions: confirmed names present iff policy allows; no unconfirmed names (hallucinated-identity check = the E19-4a top risk, now testable); brand named iff confirmed instance; length/format bounds.
- Rubric score (accuracy/completeness/fluency/context-integration, 1–5) via LLM-judge with the rubric checked in; store both scores per run in the existing benchmark JSON schema so every adapter/fusion change ships a before/after artifact.
- CIDEr/CLIPScore optional later via E20-11's hosted harness; not a gate.

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

## 9. Recommended sequencing

1. **E19-4a identity-prose merge (Tier 0)** — already scoped; unblocked; the paper strengthens its LLM-seam design. Includes structuring `VisualFacts` (paper S1 shape) while the contract is still cheap to change.
2. **Phase-split caching** — key the VLM pass without `context_hash`; recompose prose cheaply on context change. Largest UX win per effort (§3).
3. **Quality eval harness (§6)** — small; must precede 4–6 so wins are measurable.
4. **OpenCV 5 spike** — the three head-to-heads in §4; decision memo in E19-1 format.
5. **Brand detection Tier A (§5)** — template registration + matcher + curation reuse + `ContextPack.brands`; depends on 4 only for the ORB-vs-ALIKED choice, not for viability.
6. **Fusion Tier 1** — instructed fusion behind the E19-4a seam, using whichever model the spike + E20-11 hosted-benchmark work selects.
7. **PG18 upgrade** — per existing roadmap, independently schedulable; PG19 items parked until GA.

**Non-goals (explicit):** paper's retrieval stack; unsupervised logo clustering; any PG19-dependent code; replacing InsightFace before the spike proves parity; caption benchmarks against COCO-style datasets.

## 10. Open risks

- Small-model fusion quality unproven (paper never names its VLM/LLM); Tier-1 quality on A1-class hardware is the open question the spike + eval harness must answer.
- OpenCV 5 is a .0 release (June 2026): pin carefully, keep ORT path behind the port until parity is demonstrated on ARM/A1 specifically.
- Wrong-name/wrong-brand insertion remains the top product risk (per identity-prose-merge assessment); the deterministic checks in §6 are the regression net.
- `IdentityContext` E20 work is in flight on `main` (uncommitted at assessment time); `ContextPack.brands` must be sequenced after it lands to avoid schema churn.
