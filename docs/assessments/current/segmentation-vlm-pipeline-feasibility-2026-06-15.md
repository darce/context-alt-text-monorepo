# Segmentation + Per-Entity VLM Pipeline — Feasibility Assessment

> **Status:** Feasibility assessment / decision input. Not an epic or task plan.
> **Date:** 2026-06-15
> **Task:** `MAINT-seg-vlm-feasibility-20260615`
> **Question evaluated:** Add a segmentation/detection front-end (e.g. YOLO) that iterates detected entities to produce better per-object descriptions, then synthesizes the scene with the Florence VLM in `apps/prototype-description-service`. Is the juice worth the squeeze on current OCI hardware, within licensing constraints?
> **Source inputs:** Codebase (`apps/prototype-description-service`, `infra/oci`), [context-aware-image-description-roadmap-2026-06-13.md](../../roadmaps/context-aware-image-description-roadmap-2026-06-13.md), [privacy-trust-and-vlm-fit-investigation-2026-06-13.md](./privacy-trust-and-vlm-fit-investigation-2026-06-13.md).

---

## Verdict (TL;DR)

**Not worth the squeeze on the current OCI Always-Free A1 hardware as a real-time multi-model pipeline.** Three independent reasons, any one sufficient:

1. **Redundancy.** Florence-2 (MIT) is *itself* a detector + region-grounding + dense-region-captioning model. The proposed YOLO→per-entity→synthesize loop largely re-implements tasks Florence-2 exposes natively in a single model (`<OD>`, `<DENSE_REGION_CAPTION>`, `<REGION_PROPOSAL>`, `<CAPTION_TO_PHRASE_GROUNDING>`, referring segmentation). Most of the "juice" is reachable with **one** model, not a pipeline.
2. **Cost multiplier vs. hardware.** The box is 4 OCPU / 24 GB **ARM, CPU-only, no GPU** (`infra/oci/main.tf:118-123`; Dockerfile: `# No VLM/torch`). A detect→N-region-VLM→synthesize chain multiplies VLM forward passes linearly in object count. At even a conservative per-pass cost, a busy scene (6–8 entities) blows the roadmap's 20s demo target and the 30s adapter timeout, on a box with only ~5–8 GB RAM headroom already shared by Postgres + InsightFace + worker.
3. **Wrong granularity for the product.** The output is **text** (visual facts / alt-text). Pixel-accurate segmentation masks are never consumed downstream. Bounding-box region grounding — which Florence-2 already produces — is the relevant granularity. Dedicated segmentation (SAM-class) adds large CPU cost for masks the product throws away.

**Do instead:** prove single-model Florence-2-base on CPU first (roadmap Phase 2), using its built-in region/grounding task prompts to emit structured, grounded visual facts. Treat detect-and-crop as an *optional, conditional* enhancement reserved for a future GPU/provider tier — not the A1 baseline.

> **Premise correction:** the Florence VLM is **not yet implemented** in this checkout. `scene/` is a health-check stub (`scene/application/health.py`), `pyproject.toml` has **zero** VLM deps (no Transformers/Optimum/Florence), and the prod Dockerfile explicitly excludes torch/VLM. The roadmap correctly lists Florence-2 as an *unstarted* Phase 2 candidate. This assessment therefore designs Phase 2 sequencing, not an extension of existing VLM code.

---

## Hardware envelope (the binding constraint)

| Dimension | Value | Source |
| --- | --- | --- |
| Compute shape | `VM.Standard.A1.Flex`, Always Free | `infra/oci/main.tf:118-123` |
| CPU | 4 OCPU, **ARM/Ampere aarch64** | `infra/oci/main.tf`, `terraform.tfvars:10-11` |
| RAM | 24 GB total | `infra/oci/main.tf` |
| GPU | **None.** CPU-only onnxruntime | `Dockerfile:5` (`# No VLM/torch — InsightFace + onnxruntime CPU only`) |
| Container platform | `linux/arm64` | `Dockerfile:1-3` |
| Disk | 200 GB boot, ~155–170 GB free for weights | `infra/oci/main.tf:128`, `README.md` |
| RAM already in use | ~16–18 GB baseline (Postgres ~2–4 GB, InsightFace buffalo_l ~1.5–2 GB, API/worker ~0.3 GB, OS/Docker ~1 GB) | `self-hosting-epic.md:95-98` |
| **Free RAM headroom** | **~5–8 GB** | derived |
| Worker model | single worker process, `max_concurrency=5`, 30s adapter timeout, 25 MB upload cap | `recognition/worker/scan_worker.py`, `.../middleware/upload_size.py` |

Implication: weights fit on disk easily; **RAM headroom and CPU latency are the limits**, not storage. ARM CPU has no flash-attention path and is materially slower than x86 server CPU for transformer decode.

## Integration seams (if a model is added)

The service already has the right shape to host inference (`recognition/` patterns are directly reusable for `scene/`):
- Singleton model load + `loop.run_in_executor()` threadpool (`recognition/infrastructure/embeddings/__init__.py:208-217`).
- Background job queue with `SELECT … SKIP LOCKED`, retry, stale detection (`recognition/worker/scan_worker.py`).
- `ObjectStore` file:// seam for image bytes (`recognition/application/storage/`).
- `AdapterCircuitBreaker` + `wait_for_adapter(timeout_s=...)` guard pattern.
- `scene/` package has empty DDD scaffolding ready for a `description_router` mounted under `/scene` in `api/main.py:172-173`.

So integration cost is **not** the blocker. Inference economics are.

---

## Does the pipeline add value? (the juice)

Evidence that cropping detected regions and re-describing them improves VLM output — **real, but bounded**:
- Visual cropping improves MLLM accuracy on **small/medium** objects specifically; large objects benefit little ([2502.17422](https://arxiv.org/html/2502.17422), [2306.00228](https://arxiv.org/pdf/2306.00228)).
- High-resolution captioning pipelines crop newly-detected objects to recover detail missed in the global pass ([2510.27164](https://arxiv.org/pdf/2510.27164)).
- **Trade-off:** zooming in loses surrounding context, which *degrades* recognition of what the object is. Detail vs. context is a genuine tension, not a free win.
- Purpose-built region-captioning models exist (RegionGPT, "Describe Anything" ICCV 2025) — i.e. the field's answer to this need is usually *one region-aware model*, not a bolted-on detector + generic VLM.

**Key point:** Florence-2 already internalizes this. Its `<DENSE_REGION_CAPTION>` and grounding tasks emit region-localized captions in a single forward pass — capturing most of the small-object juice without N extra crops.

## What it costs (the squeeze)

**Latency (CPU, ARM, estimate — must be benchmarked).** No published A1-class ARM benchmark for Florence-2 was found; community reports note CPU lacks flash-attention and is slow. Reasonable planning estimates:
- Florence-2-**base** (~0.23B), one detailed-caption pass: single-digit to low-tens of seconds on this box (autoregressive decode dominates).
- Florence-2-**large** (~0.77B): ~3–4× worse — likely exceeds the 30s timeout even for a single pass.
- Permissive ONNX detector pass: cheap (~0.3–1s).
- **Pipeline total ≈ detect + (N × region-VLM) + 1 synthesis.** For N=6 at even 5s/pass that is ~35s+ of VLM time alone — over the 20s demo target and 30s timeout, before synthesis.

**Memory.** Florence-2-base weights ~0.5 GB disk / ~1–2 GB RAM resident; large ~1.5 GB / ~3–4 GB RAM. A *second* model (detector/SAM) loaded concurrently eats further into the ~5–8 GB headroom shared with Postgres + InsightFace. SAM ViT-H (~2.4 GB) is impractical here.

**Concurrency.** Single worker, `max_concurrency=5`. Long multi-pass jobs starve the queue; multiplying passes per image makes throughput collapse under any backlog.

---

## Licensing matrix (hard product requirement)

The plugin is a **closed-source commercial product**, so **AGPL-3.0 is disqualifying** unless a paid commercial license is purchased. This is the single most important external constraint and it eliminates the "obvious" YOLO choice.

### Detectors

| Model | License | Verdict for closed-source SaaS |
| --- | --- | --- |
| **Ultralytics YOLO** (v5/v8/v11/v12, `ultralytics` pip pkg) | **AGPL-3.0** or paid Enterprise | ❌ unless Enterprise license purchased. AGPL forces open-sourcing connected code. |
| **YOLOX** | Apache-2.0 | ✅ permissive |
| **RT-DETR** (PaddleDetection / HF `transformers`) | Apache-2.0 | ✅ permissive |
| **RF-DETR** (Roboflow, ICLR 2026) | Apache-2.0 | ✅ permissive; SOTA-COCO, clean ONNX→CPU export. Best permissive accuracy option. |
| **DETR / OWLv2** (HF `transformers`) | Apache-2.0 | ✅ permissive; OWLv2 = open-vocabulary |

### Segmentation

| Model | License | Verdict |
| --- | --- | --- |
| **SAM / SAM2** (facebookresearch standalone) | Apache-2.0 (SAM2 also BSD-3) | ✅ license-OK but **heavy for CPU** |
| **MobileSAM** (standalone repo) | Apache-2.0 | ✅ lightweight encoder; CPU-viable |
| **FastSAM** | repo Apache-2.0 **but depends on `ultralytics`** | ⚠️ inherits **AGPL** via dependency — avoid |
| **EdgeSAM** | NTU S-Lab License 1.0 | ❌ non-permissive / research-only |
| **Florence-2 referring segmentation** | MIT | ✅ already in-model |

### VLM

| Model | License | Note |
| --- | --- | --- |
| **Florence-2** (base / large) | **MIT** | ✅ fully permissive; detection + dense-region-caption + grounding + referring-seg in one model |

> **AGPL trap to flag explicitly:** the `ultralytics` pip package is AGPL-3.0 and also re-distributes SAM/SAM2/MobileSAM/RT-DETR/YOLOX *integration wrappers*. Using a permissively-licensed model *through* `ultralytics` still pulls AGPL into the runtime. **Rule:** consume permissive models via their standalone repos or HF `transformers` only — never via the `ultralytics` package.

---

## Options (ranked)

### Option A — Single-model Florence-2, region-aware prompting (RECOMMENDED)
One Florence-2-base load. Use built-in task prompts (`<MORE_DETAILED_CAPTION>` + `<DENSE_REGION_CAPTION>` + `<OD>`/`<CAPTION_TO_PHRASE_GROUNDING>`) to emit grounded, structured visual facts in 1–2 passes. No second model.
- **Hardware fit:** best (one model, ~1–2 GB, 1–2 passes). **License:** MIT only. **Juice:** captures most small-object/region benefit. **Squeeze:** lowest. **Risk:** base-model quality; large may exceed timeout — benchmark decides.

### Option B — Florence-2 + permissive detector, *conditional* crop loop (FUTURE / GPU tier)
Run global Florence-2 first; invoke an Apache detector (RF-DETR or YOLOX) + selective region re-description **only** when global confidence is low or small objects are suspected. Cap crops (e.g. ≤2). Synthesis pass merges.
- **Hardware fit:** poor on A1 (multi-pass); fine on GPU/provider tier. **License:** Florence MIT + detector Apache (✅). **Juice:** highest detail. **Squeeze:** high CPU cost; only justified off-A1.

### Option C — Detector-first, unconditional per-entity VLM (the literal proposal)
Detect all → crop each → describe each → synthesize. **Not recommended on any tier**: cost scales with object count, duplicates Florence-2's native grounding, and the detail-vs-context trade-off hurts recognition. Reconsider only with a region-native model and GPU.

### Option D — Provider VLM tier (opt-in, server-side)
Skip local pipeline; send bytes to a hosted multimodal API for the quality tier (already the roadmap's Phase 6). Best quality/latency, but adds a subprocessor and trust-disclosure obligations — keep opt-in, not the A1 default.

---

## Recommendation & sequencing

1. **Ship roadmap Phase 1 (seeded contract) first** — unchanged. Pipeline questions are premature until the visual-facts schema + cache + WP roundtrip exist.
2. **Phase 2 = benchmark single-model Florence-2-base on the A1** (Option A). Measure: latency for `<MORE_DETAILED_CAPTION>` and `<DENSE_REGION_CAPTION>`, RAM resident, quality vs. seeded, behavior under worker concurrency. **This benchmark is the gate** for everything else.
3. **Only if** Option A is quality-insufficient *and* a GPU/provider tier exists, evaluate Option B (conditional crop with an **Apache** detector — RF-DETR or YOLOX, never `ultralytics`).
4. **Drop dedicated segmentation (SAM-class) for alt-text** — wrong granularity; revisit only if a future feature consumes masks.

## What would flip the verdict

- A measured single-model Florence-2-base pass ≤ ~8s on the A1 **and** clear evidence that conditional cropping adds material alt-text quality → Option B becomes worth piloting (still off the critical request path).
- Hardware change to a GPU shape or adoption of the provider tier → the cost multiplier mostly disappears; Option B/D viable.
- A permissive **region-native** captioning model small enough for CPU → could collapse the pipeline back into one model.

## Open questions / required evidence

- Actual Florence-2-base vs -large CPU/ARM latency and RAM on the A1 (no public benchmark found — must measure in Phase 2).
- Quality delta: Florence-2 `<DENSE_REGION_CAPTION>` alone vs. detector+crop, on representative WordPress media.
- Confirm RF-DETR / YOLOX ONNX export runs clean on `linux/arm64` onnxruntime (Apache path, no `ultralytics`).

## References

- [Ultralytics License](https://www.ultralytics.com/license) (AGPL-3.0 / Enterprise) · [pricing](https://www.ultralytics.com/pricing)
- [Florence-2 (Roboflow overview)](https://blog.roboflow.com/florence-2/) · [arXiv 2311.06242](https://arxiv.org/pdf/2311.06242) · [Florence-2-large CPU inference notes](https://huggingface.co/microsoft/Florence-2-large/discussions/22)
- [RF-DETR (Apache-2.0, ICLR 2026)](https://github.com/roboflow/rf-detr) · [Apache-2.0 detection models](https://roboflow.com/models-by-license/apache-2-0-licensed-object-detection)
- [SAM2](https://github.com/facebookresearch/segment-anything-2) · [MobileSAM (Kornia)](https://kornia.readthedocs.io/en/latest/models/mobile_sam.html) · [EdgeSAM (NTU S-Lab License)](https://github.com/chongzhou96/EdgeSAM)
- Cropping/region benefit: [2502.17422](https://arxiv.org/html/2502.17422) · [2306.00228](https://arxiv.org/pdf/2306.00228) · [2510.27164](https://arxiv.org/pdf/2510.27164) · [Describe Anything (ICCV 2025)](https://openaccess.thecvf.com/content/ICCV2025/papers/Lian_Describe_Anything_Detailed_Localized_Image_and_Video_Captioning_ICCV_2025_paper.pdf)
