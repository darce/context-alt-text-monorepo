# Scope: Commercial Face Identity Replacement (FIR)

**Intake**: 2026-07-15 · task FIR-1 · answers recorded in handoff MCP
**Assessment**: [docs/assessments/current/commercial-face-pipeline-replacement-assessment-2026-07-15.md](../assessments/current/commercial-face-pipeline-replacement-assessment-2026-07-15.md)

## Problem

InsightFace buffalo model weights are non-commercial; ACX is a commercial product. Production face identity (detection → embedding → clustering) must move to commercially licensed weights. InsightFace remains **internal-benchmark-only**, hard-separated from production paths (deps, images, DB).

## Intake decisions (recorded)

| Question | Decision |
| --- | --- |
| Accuracy release gate | **No fixed gate yet** — bake-off produces numbers first; gate is then decided and recorded in MCP before switch-over |
| Bench/prod embedding separation | Prod DB stays single-model (128D SFace) + per-row `embedding_model` provenance column; buffalo embeddings live only in eval-harness run artifacts / dedicated eval deployment (pgvector fixed-dim makes a shared column infeasible anyway; zero prod perf cost) |
| GPU scope | **CPU first** (prod is ARM CPU); A10 ONNX-Runtime-CUDA serves the bake-off, production GPU path is a follow-on |
| age/gender metadata | **Dropped** (was inaccurate, never product); possible follow-up after recognition is stable. Pose becomes landmark-derived proxies; quality gains AdaFace/MagFace-style embedding-magnitude signal |

## MVP scope

An ACX-owned face pipeline — YuNet 2026may (MIT) detection + 5 landmarks → five-point affine alignment (OpenCV `FaceRecognizerSF.alignCrop` semantics) → SFace 2021dec (Apache-2.0) 128D embedding → L2 normalize → existing clustering/representative machinery → pgvector cosine retrieval — running on the ARM CPU production path behind the existing `FaceDetectorProtocol`/`EmbeddingGeneratorProtocol` seams, with pinned model hashes + license files shipped in the artifact, buffalo weights removed from production images, and thresholds calibrated from an ACX-domain bake-off.

## Success criteria

1. Production images contain no InsightFace weights; `insightface` dependency only in a `[bench]` extra.
2. Scan → cluster → curate flow works end-to-end on YuNet+SFace with recalibrated thresholds; unknown-first failure mode (no silent false assignments) until calibration lands.
3. Bake-off report exists comparing YuNet+SFace vs buffalo_l reference (eval env only) on the extended golden corpus with identification P/R, false-merge/false-split, unknown-rejection, and per-slice metrics — **occlusion (real + synthetic-paired), profile, low-res, blur, similar-people, demographic** — the release gate is decided from it and recorded as an MCP decision.
4. Golden parity tests for landmark order, alignment affine, and embedding normalization pass on CPU in CI (`make check-remote` green).
5. Every production embedding row carries `embedding_model` provenance.

## Assumptions

- Greenfield: no data migration; `PGVECTOR_DIM` 512→128 edited directly in `001_identity_schema.py`; tenants re-scan.
- Clustering algorithms are dimension-agnostic (cosine on unit vectors) and need calibration only.
- Golden corpus grows via VLM-6 Golden-100 curation; eval tenant pattern from `scripts/eval_harness/` is reused.

## Task decomposition

| Task | Title | Depends on | Core deliverables |
| --- | --- | --- | --- |
| **FIR-2** | Pipeline seam hardening + provenance | — | Model-neutral detection/embedding dataclasses (strip `embedding_512`, age/gender, native pose); centralize embedding-dim in settings; `embedding_model` column + typed model manifest (DOM-05); drop age/gender columns/exports/API projections; schema edit + verify/sync scripts |
| **FIR-3** | YuNet+SFace adapters | FIR-2 | OpenCV CPU reference impl (semantic golden); ORT CPU adapters with identical preprocessing; model files pinned by sha256 + license files in artifact; OpenCV 4.12-vs-5 pin decision; golden tests (landmark order, affine, normalization) |
| **FIR-4** | Runtime integration + license isolation | FIR-3 | scan_worker/inline wiring; `FacePipelineSettings`; health-probe model-cache checks; Docker/deps rework; insightface → `[bench]` extra; prod-image weight audit; mac install script replacement |
| **FIR-5** | Bake-off harness extension | FIR-2 | Offline candidate leg (in-process detector+embedder over golden corpus) or env-selected eval-instance profile; false-merge/false-split + cluster-purity + unknown-rejection metrics; `slice_tags` manifest field + per-slice rollups with **occlusion first-class** (real occluders + deterministic synthetic-occlusion paired protocol); demographic slices (Fair-SA); buffalo_l reference leg confined to eval env + run artifacts; corpus hard-slice extension |
| **FIR-6** | Calibration + quality rework + hard-case recovery + gate decision | FIR-4, FIR-5 | Quality signals: landmark pose proxies, sharpness, embedding magnitude (AdaFace/MagFace), **occlusion-severity proxy** (landmark confidence + eye-region patch stats); occlusion-adaptive threshold adjustment via existing `compute_identity_quality().threshold_adjustment` (OACT pattern, 2607.03581 concept); **Hungarian within-photo one-to-one assignment** over face×candidate cosine matrix (2606.23230 pattern, `linear_sum_assignment`); representative/medoid aggregation tuning; similarity/unknown/ambiguity-margin calibration on ACX data; bake-off report; **release-gate decision recorded in MCP**; switch-over slice |
| FIR-7 (follow-on) | A10 GPU production path | FIR-6 | ORT-CUDA providers, FP16 + threshold recheck, engine caching |
| FIR-8 (contingent) | Escalation ladder | failed FIR-6 gate | SFIQA-class learned quality model (2602.07403) → SeetaFace6 audit → licensed InsightFace quote → commercial SDK comparison → (last) occlusion-aware embedder training (synthetic-data SFace / LaCoVL / OccFace as references); YuNet retrain with depth-aware occlusion compositing (2512.11683) only if bake-off attributes occlusion losses to *detection misses* |

## Not-Doing

- Video/track pipeline (companion doc exists; separate future epic).
- age/gender attribute model (follow-up only after recognition is stable).
- Custom model training, dataset licensing, or fine-tuning.
- HNSW indexes (exact ivfflat/cosine is fine at current roster sizes; add only on measured latency need).
- Commercial SDK or managed-API integration (bake-off comparator at most, behind FIR-8).
- Model-registry service or multi-dimension vector query layer (provenance column only — REF-12).
- GPU-class hard-case models in the live path: diffusion super-resolution (2607.05702), GAN-inversion/SAM occlusion segmentation (2602.00635), CLIP-based fusion (2605.19821), LRM 3D reconstruction (2601.12736). S3POT-class segmentation at most as offline GPU curation labeling.
- Detector or embedder retraining in the MVP (Depth-Copy-Paste augmentation and occlusion-aware embedder training live behind the FIR-8 gate).
- TensorRT / native engine work (post-FIR-7 at earliest).
- Migration/shadow-mode tooling in production (greenfield; shadow comparison lives in the eval harness).
