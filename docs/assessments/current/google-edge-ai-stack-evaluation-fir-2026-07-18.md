# Google Edge-AI Stack Evaluation vs FIR Face Pipeline

> **Metadata**
>
> - **Date**: 2026-07-18
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Scope**: E22 Commercial Face Identity Replacement (FIR-2 merged, FIR-3 merged @ad67afaa)
> - **Question**: do LiteRT, MediaPipe, litert-lm, LiteRT.js, XNNPACK, or WebNN improve on the chosen YuNet+SFace / OpenCV-reference / ONNX-Runtime-CPU stack?
> - **Handoff**: decision `claude_fir_edge_stack_eval_google_stack_rejected` (#2685)
> - **Method**: 3 parallel web-research subagents + local codebase inventory (grok offload admission-refused: host memory critical)

## Verdict

**None adopted.** The FIR stack (YuNet MIT + SFace Apache-2.0 ONNX, OpenCV `FaceDetectorYN`/`FaceRecognizerSF` reference, ORT CPU production on OCI A1.Flex aarch64) is strictly better on every stated requirement: single ONNX format with sha256 provenance, golden-test parity, 5-landmark SFace alignment, first-class aarch64 wheels, batch APIs, commercial licenses.

| Project | Verdict | Disqualifier |
| --- | --- | --- |
| LiteRT (`google-ai-edge/litert`) | Reject | `.tflite` only, no ONNX loader; conversion breaks golden parity + provenance |
| MediaPipe Face Detector (BlazeFace) | Reject | Wrong keypoints for SFace alignment; no aarch64 wheel; selfie accuracy class |
| MediaPipe (recognition half) | N/A | No identity embedder exists in MediaPipe at all |
| litert-lm | Irrelevant | LLM orchestration; zero vision surface |
| XNNPACK | Already covered | Not in Linux ORT wheels; KleidiAI in ORT ≥1.22 MLAS supersedes |
| LiteRT.js (web) + WebNN | Reject | Browser inference stays retired (architecture decision reaffirmed) |

## Findings

### LiteRT

- Ships aarch64 manylinux wheels (`ai-edge-litert`, Apache-2.0), but consumes only `.tflite` FlatBuffers — no ONNX loader.
- Running YuNet/SFace requires third-party `onnx2tf` conversion: NCHW→NHWC graph rewrite changes float accumulation order. The converted model is a different graph — at best tolerance-comparable, never a provenance-pinned upstream artifact. Breaks FIR-3's lockfile model (sha256 of upstream opencv_zoo ONNX bytes) and the golden gate.
- Google's zoo has no face identity embedder (MediaPipe issue #4556), so LiteRT could at most swap the detector — forking away from the OpenCV reference stack for zero gain.
- ARM CPU performance parity: LiteRT's edge is its XNNPACK delegate; ORT ≥1.22 MLAS ships Arm KleidiAI kernels (28–51% aarch64 uplift vs 1.21), erasing the gap for these tiny models (YuNet ~340 KB, SFace ~37 MB).

### MediaPipe

- **No identity embedder** — face tasks are Detector, Landmarker (geometry mesh), Stylizer. Image Embedder is ImageNet-MobileNet: clusters by scene/lighting, not person. SFace stays regardless.
- **BlazeFace keypoints incompatible with SFace**: 6 points = eyes, nose tip, mouth *center*, two ear tragions. SFace's five-point affine needs the two **mouth corners**; YuNet emits exactly the right set. No lossless remap exists.
- **No linux-aarch64 PyPI wheel** as of mediapipe 0.10.35 (issue #5965 closed, wheels still unshipped) — Bazel source build or third-party wheels vs `pip install onnxruntime`.
- **Accuracy class**: selfie/proximity detector (short-range ≤2 m, full-range ≤5 m), no published WIDER FACE numbers (YuNet paper excluded it for that reason; YuNet: 81.1% AP WIDER-hard at 75,856 params). Group-photo regression risk for a photo-library product.
- On-device streaming design: no batch API (IMAGE mode = one image per call), TFLite runtime, opaque `.task` bundles vs single-file ONNX pinning.

### XNNPACK

- ORT's XNNPACK EP is prebuilt **only into mobile packages** (Android/iOS); Linux wheels expose `CPUExecutionProvider` only — enabling it means a custom `--use_xnnpack` source build for ~12 covered ops with partition-fallback overhead.
- The benefit it would bring (ARM-optimized kernels) already lives in the default CPU EP via KleidiAI (ORT ≥1.22).
- If CPU throughput ever binds, the levers in order (COST-06 — eliminate work before buying/building): ORT ≥1.22, `intra_op_num_threads` tuned to OCPU count, int8 quantization — before any custom EP build.
- Any different-EP path (XNNPACK, FIR-7 CUDA) legitimately differs in float accumulation → provider parity must stay tolerance-based (as FIR-3's merged plan specifies); bit-equality is a same-EP regression check only.

### litert-lm

LLM inference layer (KV-cache, sessions; engine behind Gemini Nano) for Gemma/Llama/Phi on-device. No vision-CNN surface. The VLM lane is already owned by llama.cpp/Qwen3-VL (VLM-3B).

### Browser: LiteRT.js + WebNN + ORT-web

- LiteRT.js launched 2026-07-09 (week-old runtime, `.tflite` format mismatch). WebNN: W3C CR with 100+ changes since 2024, Chromium-only behind a flag, DirectML→Windows ML backend mid-migration, no Safari/Firefox timeline (~2027+ realistic). ORT-web accelerated EPs (WebGPU/WebNN) labeled experimental; only WASM-CPU is stable.
- Deeper than maturity — two structural blockers reaffirm the retired-local-FR decision:
  1. **Embedding consistency**: identity clustering requires one model/version/precision per tenant library (why `embedding_model` provenance exists). Heterogeneous client runtimes (WASM fp32 / WebGPU fp16 / server ORT) drift clusters.
  2. **Trust boundary**: client-computed embeddings are unauthenticated input; the server must recompute to trust them.
- Only defensible narrow use, if server queue cost ever binds: YuNet-only ORT-web-WASM client pre-filter (~0.5 MB) to skip zero-face uploads, or cosmetic provisional preview boxes. Not justified now. Client-side SFace embedding and any "faces never leave the browser" privacy claim: explicitly not plausible.

## Actionable riders and disposition

1. **Raise `onnxruntime>=1.16` → `>=1.22`** (`apps/prototype-description-service/pyproject.toml:32`) for KleidiAI aarch64 MLAS kernels. **Open** — FIR-3 merged without it; recognition had zero direct ORT imports before FIR-3, and the new `face_pipeline/ort_adapters.py` is the first direct surface, so the bump is low-risk. Route: fold into FIR-4 (first FIR task touching `pyproject.toml` on a branch); re-run the FIR-3 parity suite after bumping.
2. **Provider-parity tolerance-based, bit-equality same-EP only.** **Absorbed** — FIR-3 plan rev 5 constraints already state float `atol`/`rtol`, not bit-comparable; applies forward to FIR-7 CUDA EPs unchanged.

## Heuristics applied

rg-015 (adapters must not invent contract semantics — conversion drift), PERF-06 (measured thresholds/tolerances), MLDATA-04 (lineage = sha256 lockfile; LiteRT conversion severs it), FAIR-08 (evaluate deployed model on operational imagery — FIR-3 real-corpus smoke), COST-06 (eliminate work before new runtimes/hardware), REF-16 (second model format = leaky abstraction tax).

## Sources

LiteRT: [ai-edge-litert PyPI](https://pypi.org/project/ai-edge-litert/) · [onnx2tf](https://github.com/PINTO0309/onnx2tf) · MediaPipe: [Face Detector](https://developers.google.com/edge/mediapipe/solutions/vision/face_detector) · [issue #4556 (no face embedding)](https://github.com/google/mediapipe/issues/4556) · [issue #5965 (no aarch64 wheels)](https://github.com/google-ai-edge/mediapipe/issues/5965) · [BlazeFace model card](https://storage.googleapis.com/mediapipe-assets/MediaPipe%20BlazeFace%20Model%20Card%20(Short%20Range).pdf) · [YuNet paper](https://link.springer.com/article/10.1007/s11633-023-1423-y) · ORT: [XNNPACK EP docs](https://onnxruntime.ai/docs/execution-providers/Xnnpack-ExecutionProvider.html) · [v1.25 release notes / KleidiAI](https://github.com/microsoft/onnxruntime/releases/tag/v1.25.0) · [Arm blog: ORT on Neoverse](https://developer.arm.com/community/arm-community-blogs/b/servers-and-cloud-computing-blog/posts/accelerate-llm-inference-with-onnx-runtime-on-arm-neoverse-powered-microsoft-cobalt-100) · Web: [LiteRT.js announcement](https://developers.googleblog.com/litertjs-googles-high-performance-web-ai-inference/) · [WebNN status](https://webstatus.dev/features/webnn) · [ORT-web WebNN EP](https://onnxruntime.ai/docs/tutorials/web/ep-webnn.html) · [litert-lm](https://ai.google.dev/edge/litert-lm/overview)
