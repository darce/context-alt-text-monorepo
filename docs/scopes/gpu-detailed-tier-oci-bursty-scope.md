# Bursty OCI-GPU Detailed-Description Tier — Scope Note

> **Status:** Scope one-pager (decision input). Not an epic or task plan.
> **Date:** 2026-07-07
> **Proposed Task ID:** `VLM-3` (GPU detailed-tier bake-off + serving) · **Feeds:** E19 (detailed-description tier), sequenced after VLM-2B (CPU detailed-tier pick) / VLM-2A (eval harness).
> **Source of truth:** [caption-context-enrichment-assessment-2026-07-05.md](../assessments/current/caption-context-enrichment-assessment-2026-07-05.md) §4 (OpenCV 5 / OWLv2), §5 (brand Tier B), §10 (model landscape / detailed tier), §11 (implementable-now A1). Intake decision `scope_intake_opencv5_and_oci_bursty_gpu_tier` (MCP, `MAINT-opencv5-bursty-gpu-scope-20260707`). Grounded on `literature/extracted/refactoring/distilled/` — Modern SE (incrementalism, YAGNI, DORA), Release-It (bulkhead, circuit breaker), latency (tail / cold-start).

---

## 1. Problem

The detailed-description tier (VLM-2B winner **Qwen3-VL-4B-Instruct**) runs **~207 s/image on the A1 CPU** — a 100-image batch is **~5.75 hours**. Acceptable for a single opt-in image, not for batch/back-fill, and it caps caption quality at what a 4B model on 4 ARM cores can do. A GPU makes bigger, better detailed-caption models viable and collapses batch wall-clock to minutes — **but the product is privacy-first and self-hosted, and an always-on GPU is wasteful for a bursty, opt-in workload.** No measurement exists for (a) which GPU-served VLM gives the best *named-context* descriptions on our imagery, or (b) whether OCI can serve GPU bursts scale-to-zero without shipping image data off-tenancy.

## 2. MVP Scope

A **bursty, scale-to-zero GPU serving path** for the detailed-description tier, on **OCI (same tenancy as the A1 service)**, whose model is chosen by a **bake-off** reusing the VLM-2A/2B gated-rubric harness. Includes **OWLv2 open-vocab brand detection (Tier B)** as a second consumer of the same burst pool.

**A. GPU model bake-off (reuse VLM-2A/2B harness, no new metrics):**
- Candidates: **Qwen3-VL-8B / -32B-Instruct** (a-priori favorite — same family as the CPU winner, strongest instruction-following for name weaving), **InternVL3-8B/-14B**, **Molmo-7B-D** (grounding/phrase-boxes), **Llama-3.2-Vision-11B**.
- Scored on the existing gated rubric: insertion rate, Must-Right name gates, Easy-Wrong hallucination traps, FKRE — over the VLM-2B bake-off corpus with real context packs. Deterministic tier only; LLM-judge stays a stub.
- One decision memo picks **one** GPU detailed-tier model with evidence + measured GPU latency/RSS.

**B. Bursty OCI-GPU serving (scale-to-zero, data-in-tenancy):**
- On-demand OCI GPU instance (A10 / L40S class), one model at a time, **off the A1 demo path**.
- **Scale-to-zero via stop-not-terminate** (idle = boot-volume storage only, ~$0 GPU compute), **not** an always-on VM.
- **Boot/load reduction (explicit build items):** (a) **custom golden image** with drivers + runtime + model weights baked in; (b) **load-once-per-burst** — the serving process (vLLM/TGI/llama.cpp) stays warm for the whole batch so model load amortizes per-burst not per-image; (c) optional **OKE GPU node-pool scale-to-zero** with a warm-node buffer; (d) quantized weights + local NVMe / mmap load.
- **Async queue + progress**; the GPU burst pool is **bulkheaded** from the always-on recognition/description service (a spike can't starve the A1 box — Release-It).
- **Degrade:** if GPU cold-start exceeds budget or the GPU is unavailable, serve the **CPU tier (Florence/Qwen) as a provisional answer**, upgrade to the GPU result when ready (circuit breaker).

**C. OWLv2 Tier B brand detection (GPU consumer):**
- Image-conditioned open-vocab detection for non-rigid/stylized logos where CPU keypoint matching (Scope A) fails; runs on the same burst pool; confirmed instances flow to `ContextPack.brands` exactly like Tier A.

**Deliverables:**
1. GPU bake-off REPORT artifacts (acx-eval/v1 schema, deterministic re-score) + one decision memo picking the GPU detailed-tier model.
2. A `DescriptionAdapter` (or async worker) for the winning GPU model behind the existing profile protocol, GPU-served.
3. An OCI GPU lifecycle controller (spin-on-queue → warm-per-burst → stop/terminate-on-idle) + golden-image build recipe.
4. A spike artifact (E19-1 JSON format) recording real GPU s/img, OCI A10/L40S $/hr + region quota, and measured cold-boot vs warm-start times.

## 3. Stated Assumptions

1. **GPU per-image time is unmeasured** — the ~5 s/img estimate (207 s CPU ÷ ~40× speedup) is a spike deliverable, not a fact; a candidate that can't hit an interactive-batch ceiling is a fail-per-item, not a run-aborter.
2. **OCI has no first-class serverless/scale-to-zero GPU** at authoring time (Functions/Container Instances were CPU-only); the lifecycle controller is DIY. Confirming current OCI GPU-serverless / Container-Instances-GPU support + region GPU quota is a spike question.
3. **Data stays in the OCI tenancy** — same VCN as the A1 service, private networking, no off-provider egress. This is the reason OCI is primary over serverless (which is ~cents cheaper per batch but sends image bytes off-box).
4. **Cost is not the deciding axis** — 100-img batch ≈ $0.20–0.40 on any GPU option; time (5.75 hr → ~10 min) is the payoff. OCI-vs-serverless delta is cents.
5. **Reuses VLM-2A/2B unchanged** — harness, gated rubric, bake-off corpus, `ContextPack` schema; the GPU bake-off runner mirrors the VLM-2B throwaway-client posture.
6. **Concurrency 1, one model resident at a time**, off the live path; the burst pool never degrades the A1 box.

## 4. Not-Doing (explicit out-of-scope)

- **No hosted-API tier** (GPT-4o / Claude / Gemini) — excluded per intake; stays the separate E20-11 track.
- **No always-on GPU** — scale-to-zero only.
- **No snapshot/CUDA-checkpoint restore infra** (the serverless-parity sub-minute-start-plus-zero-idle trick) — DIY, deferred; stop-not-terminate + golden image is the MVP warm-start.
- **No OpenCV 5 incumbent dependency swap** (replacing onnxruntime/torch) — spike-gated later, YAGNI.
- **No context-fusion caption architecture (arXiv 2606.18553), no PG18/19 work.**
- **No LLM-judge implementation** — deterministic rubric only.
- **No CPU Tier-A brand detection** — that is Scope A (`opencv5-brand-detection-tier-a-scope.md`).
- **No new auth surfaces** — reuse the eval-tenant + dev-key posture from VLM-2A.

## 5. Success Criteria

1. Each GPU candidate produces a scored acx-eval/v1 REPORT over the VLM-2B corpus with real context packs; re-score is bit-identical.
2. A decision memo names **one** GPU detailed-tier winner, cites artifacts, and records measured GPU latency/RSS + the CPU→GPU speedup.
3. The bursty path serves a detailed description end-to-end via an OCI GPU instance that is **stopped (≈$0 GPU compute) between bursts**, with measured warm-start ≤ a stated budget.
4. Cold/unavailable GPU degrades to a CPU provisional answer without failing the request; a GPU burst never degrades the A1 service (bulkhead proven).
5. The spike artifact records real GPU s/img, OCI GPU $/hr + quota, and warm-start times — enough to confirm/deny the intake cost model.

## 6. Slice Outline (detail in the task plan)

1. **OCI GPU spike** — confirm GPU shape/quota + serverless-GPU availability; measure cold-boot, golden-image warm-start, and one candidate's s/img; emit the E19-1-format artifact.
2. **GPU bake-off** — serve each candidate on the GPU; score via VLM-2A harness over the VLM-2B corpus; emit REPORTs.
3. **Decision memo** — pick one GPU model with evidence + license verdict.
4. **Bursty serving path** — golden image + lifecycle controller (spin-on-queue, warm-per-burst, stop-on-idle) + async queue + CPU-provisional degrade + A1 bulkhead.
5. **OWLv2 Tier B** — open-vocab brand detection on the burst pool → `ContextPack.brands` (depends on Scope A's `ContextPack.brands` surface landing first).

## 7. Open Risks

- OCI GPU **capacity/quota** in-region may block on-demand spin-up — spike answers this; serverless (Modal/RunPod/fal) is the documented fallback.
- **Warm-start** without snapshot infra may not beat ~60–90 s — acceptable for the async batch tier, but if real usage turns interactive-single-image, reconsider (that is the CPU Florence tier's job).
- **Bigger models (32B)** may exceed a single A10's 24 GB — L40S (48 GB) or quantization required; the bake-off gates this.
- Larger/quantized models may **regress name-injection** vs the 4B CPU winner — the gated Must-Right rubric is the net.
- OWLv2 Tier B **couples** brand-detection quality to GPU availability — Tier A (CPU) remains the always-available baseline.
