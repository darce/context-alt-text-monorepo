# E19-1 — MiMo-VL vs Phi-4, and sub-7B modern VLMs measured on the OCI A1

> **Date**: 2026-06-16 · **Task**: `MAINT-mimo-vl-eval-20260617` · **Skill**: `/investigate` · **Status**: present-for-testing (no adapter implemented)
> **Scope**: (1) benchmark MiMo-VL against the planned Phi-4 GPU tier; (2) since 7B is too large for the OCI VM, find + **live-test** newer modern **sub-7B** VLMs in the MiMo-VL vein on the real A1.
> **Companion to**: [`E19-1-vlm-model-candidates-a1-cpu.md`](E19-1-vlm-model-candidates-a1-cpu.md) · [`E19-1-local-cpu-vlm-benchmark-decision-memo.md`](E19-1-local-cpu-vlm-benchmark-decision-memo.md) · [`E19-1-florence-large-async-worker-impl-notes.md`](E19-1-florence-large-async-worker-impl-notes.md) (Part D = the GPU tier)
> **Measured on** `acx-backend` via Tailscale (aarch64 Neoverse-N1, 4 OCPU, 23 GB, no GPU, no swap). Live `docker ps` healthy throughout; scratch venv under `/tmp`, public deps + scikit-learn sample images only.

## TL;DR

- **MiMo-VL-7B-RL beats Phi-4-multimodal on quality** (MMMU-val **70.6 vs 55.1**, stronger doc/chart/OCR), is **MIT**, and uses the **Qwen2.5-VL** arch → first-class vLLM/SGLang serving. It is the better GPU-tier model — **but it is 7B**.
- **7B does not fit the current A1.** Measured free RAM is ~18 GB with **no swap**; MiMo-VL-7B bf16 ≈ 16 GB would sit on top of the live recognition stack and risk OOM-killing prod. Both MiMo-VL-7B and Phi-4 are **GPU-tier only** — confirmed, not theoretical.
- **MiMo-VL has no official sub-7B variant.** Its nearest deployable-size sibling is **Qwen2.5-VL-3B** (its exact `qwen2_5_vl` base family); the newest in-vein option is **Qwen3-VL-2B/4B** (Oct 2025).
- **Live-measured on the A1 CPU** (the real ask): **Qwen2.5-VL-3B = mean 341.5 s/image** (china 354 / flower 329), **8.4 GB RAM**, **excellent quality** — names "pagoda" *and* "dahlia" (the latter only Florence-*large* got before, at 4× the RAM), concise, **no hallucination**. ~2.7× faster than Phi-4, fits memory, far richer than Florence. **Qwen3-VL-4B** (newest) edges it on quality — mean 408 s, 9.6 GB, matching Florence-*large*'s best captions (the boats; the second dahlia bud) with no hallucination.
- **Recommendation (present for testing):** evaluate **Qwen2.5-VL-3B** and **Qwen3-VL-4B** as the real-description model. Neither is interactive on the A1 CPU (~6–9 min/image → async-worker only), but both are memory-safe and quality is a large step up from Florence. The 7B tier (MiMo-VL / Phi-4) stays GPU-deferred. **No adapter built yet — awaiting your pick.**

## 1. The two questions

The original plan (`E19-1` Part D) parks a `gpu_phi4` profile (Phi-4-multimodal, fail-closed stub) as the eventual quality tier. Two questions:
1. **Is MiMo-VL a better GPU-tier model than Phi-4?** → §2 (yes, on quality/license/serving).
2. **7B is too big for the OCI VM — what newer, smaller (sub-7B) model in the MiMo-VL vein fits, and how does it actually perform on the A1?** → §3–§5 (measured).

## 2. MiMo-VL-7B-RL vs Phi-4-multimodal (the GPU-tier comparison)

> The linked paper [arxiv 2512.17436v2](https://arxiv.org/html/2512.17436v2) is **MiMo-VL-*Miloco*-7B** — a home-IoT/gesture RL fine-tune, *not* the alt-text model. The deployable general model is **`XiaomiMiMo/MiMo-VL-7B-RL`** ([report 2506.03569](https://arxiv.org/abs/2506.03569)).

| | MiMo-VL-7B-RL | Phi-4-multimodal (incumbent plan) |
| --- | --- | --- |
| Params / arch | ~8B · `Qwen2_5_VLForConditionalGeneration` | 5.6B · Mixture-of-LoRAs on Phi-4-mini |
| License | **MIT** | MIT |
| MMMU-val | **70.6** (RL-2508) | 55.1 |
| DocVQA / ChartQA | **95.2 / 92.0** | 93.2 / ~81 |
| vs Qwen2.5-VL-7B | beats it on **35/40** tasks | — |
| Reasoning | long-CoT (suppress with `/no_think` for alt-text) | concise instruct |
| Serving | **vLLM + SGLang native** | trickier (MoE-LoRA) |
| GPU (bf16) | ~16 GB weights → **~24 GB VRAM** (A10/L4); too tight for a 16 GB T4 → needs AWQ-INT4 | ~11 GB → **fits a 16 GB T4** |

**Verdict:** MiMo-VL-7B-RL is the stronger GPU-tier pick (quality + MIT + easy serving). Cost vs Phi-4: more VRAM (needs a 24 GB GPU or INT4 quant) and you must run `/no_think` so the output is alt-text-shaped. Both are excellent alt-text models; both are GPU-only.

## 3. Why 7B doesn't fit the current A1 (measured)

`acx-backend` snapshot during this work: **23 GB total, ~5 GB used by the live prod/staging/dev stack, ~18 GB available, 0 B swap.** A 7B VLM in bf16 (~16 GB resident, e.g. Phi-4 measured ~10 GB at 5.6B → ~16 GB at ~8B) would leave ~2 GB headroom on a box with no swap, on top of the live recognition service → **OOM-kill risk for prod**. This is exactly why 7B is GPU-tier only here, and why I did **not** load MiMo-VL-7B on the live host. Projected MiMo-VL-7B A1 latency (scaling the measured Qwen-3B below by params, `/no_think`): **~13–14 min/image** — academic, since memory rules it out first.

**MiMo-VL ships only at 7B** (SFT / RL / RL-2508 / Miloco — all 7B). No official 3B/2B. The in-vein smaller options are its base family **Qwen2.5-VL-3B** and the newer **Qwen3-VL-2B/4B**.

## 4. Sub-7B benchmark on the A1 CPU — MEASURED

Config: bf16 (mkldnn bf16 unsupported on Neoverse-N1 → **falls back to BLAS gemm**, same regime as the Phi-tier runs), `attn=eager`, greedy (`num_beams=1`), `max_new_tokens=256`, alt-text prompt, scikit-learn `china`/`flower`. Existing Florence/Phi rows are the anchors from the companion memos.

| Model (A1 CPU) | Params | License | china | flower | cold load | peak RSS | Mem-safe on A1? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Florence-2-base-ft *(incumbent)* | 0.23B | MIT | ~5–11 s | ~5–17 s | ~11 s | 2.5 GB | ✅ |
| **Qwen2.5-VL-3B-Instruct** | 3B | **Apache-2.0** | **353.7 s** | **329.3 s** | 1.6 s¹ | **8.4 GB** | ✅ |
| **Qwen3-VL-4B-Instruct** *(newest)* | 4B | **Apache-2.0** | **443.0 s** | **373.0 s** | 1.7 s | **9.6 GB** | ✅ |
| Phi-4-multimodal *(anchor)* | 5.6B | MIT | 924 s | — | 173 s | ~10 GB | ⚠ tight |
| MiMo-VL-7B-RL *(projected)* | ~8B | MIT | ~13–14 min² | — | — | ~16 GB | ❌ OOM risk |

¹ model pre-cached; first-ever cold load incl. ~7 GB download was a one-time ~minutes. ² projected from the 3B row by params (`/no_think`); not run live (§3).

**Quality — Qwen2.5-VL-3B, china (353.7 s):**
> *"A traditional Chinese **pagoda** with a multi-tiered structure, **red and green** colours and ornate decorations stands on a hill overlooking a serene lake… conical roof with golden elements… lush green trees… in the distance a cityscape with buildings and a bridge… clear sky."*

**Quality — Qwen2.5-VL-3B, flower (329.3 s):**
> *"A close-up of an orange **dahlia** flower with a vibrant, intricate center and petals radiating outward. The background is blurred, highlighting the flower's detailed structure."*

This is **best-tier alt-text from a 3B**: it names "pagoda" *and* "dahlia" — the dahlia ID was previously achievable **only** by Florence-2-**large** (~39 s, ~4× the RAM); Phi-4 itself missed it. Output is concise and **hallucination-free** (no "dining table" like Florence-base's OD pass). The one blemish: mild over-reach on china ("cityscape… bridge", "golden elements") — strip speculative clauses in post. Mean **341.5 s/image**.

**Quality — Qwen3-VL-4B (newest), china (443 s) / flower (373 s):**
> china: *"…multi-tiered pagoda with red pillars, green and orange tiled roofs, ornate eaves… a large body of water with **numerous small boats**… distant landmasses and a hazy horizon."*
> flower: *"A close-up of a **peach-coloured dahlia** with layered, ruffled petals… blurred dark-green foliage. **A second, partially visible dahlia appears below.**"*

Qwen3-VL-4B is the **quality winner**: it gets the **boats** (the 3B missed them) with **no** hallucinated bridge, and on the flower it reproduces **Florence-2-large's** best-in-class caption — "peach… ruffled petals… a second flower below" — where that second bud was previously identified *only* by Florence-large (~39 s, ~4× the RAM). All at 4B / 9.6 GB. Cost vs the 3B: ~20 % more latency (mean **408 s** vs 341.5 s). **Net: Qwen3-VL-4B = best A1-deployable quality; Qwen2.5-VL-3B = slightly faster/leaner at near-equal quality.**

**Net:** a sub-7B modern VLM gives a large quality jump over Florence at ~6 min/image on the A1 CPU — **async-worker only** (≫ the 20 s interactive bar, like Florence-large), but **memory-safe** (unlike 7B). Speed, not memory, is the constraint at 3–4B; memory is the wall at 7B.

## 5. Shortlist — newer modern sub-7B VLMs in the MiMo-VL vein

All are GPU-only for *interactive* latency but fit A1 RAM (async-worker path) and run quantized far faster. Ranked for an alt-text/description tier:

| Model | Params | License | In-vein? | Notes |
| --- | --- | --- | --- | --- |
| **Qwen3-VL-4B-Instruct** | 4B | Apache-2.0 | ✅ newest (Oct 2025), Qwen family | successor to MiMo's base; FP8 + GGUF variants published; top current sub-7B |
| **Qwen2.5-VL-3B-Instruct** | 3B | Apache-2.0 | ✅ MiMo's exact base arch | **measured here**; safest swap, excellent captions/OCR |
| **Qwen3-VL-2B-Instruct** | 2B | Apache-2.0 | ✅ Qwen family | smallest in-vein; fastest on CPU, some quality loss |
| **InternVL3-2B** | 2B | Apache-2.0 | ✅ Qwen2.5 LM backbone | strong reasoning-per-param |
| **Ovis2-2B / Ovis2-4B** | 2–4B | Apache-2.0 | ✅ explicit CoT focus | Int4 (~3–6 GB); reasoning-leaning |
| **Gemma-3-4B-it** | 4B | Gemma terms ⚠ | ~ | multimodal; non-OSI license caveat for a public demo |
| **MiniCPM-V (4.x)** | ~8B | research+ltd-commercial ⚠ | ~ | best edge/GGUF (phone-built); license caveat |
| **LFM2-VL / SmolVLM2** | <2B | Apache-2.0 | efficiency-vein | ultra-light; quality below the 3–4B tier |

**On current hardware specifically:** for a CPU-only A1, a sub-7B model is realistic only **(a)** async-worker (full precision, ~6–9 min/image, memory-safe) or **(b)** **Q4 GGUF via llama.cpp** (~3–5 GB RAM, ~1–3 min/image with ARM NEON) at some quality cost. Qwen3-VL/Qwen2.5-VL/MiniCPM-V all ship GGUF.

## 6. Recommendation — present for testing (no implementation yet)

1. **Test these two as the real-description model:** **Qwen3-VL-4B-Instruct** (newest; measured **best quality** — boats + the second dahlia, no hallucination; 408 s, 9.6 GB) and **Qwen2.5-VL-3B-Instruct** (slightly faster/leaner — 341.5 s, 8.4 GB; near-equal quality). Both Apache-2.0, `qwen3_vl`/`qwen2_5_vl` → trivial transformers + vLLM wiring. **torchvision is a required dep** (Qwen processors build a video sub-processor).
2. **Keep Florence-2-base-ft** as the fast/interactive default (~5–11 s); add the chosen sub-7B as a **high-quality async tier** (mirror the `florence_large` async-worker plan, Part C). The 7B tier (MiMo-VL-7B-RL preferred over Phi-4) stays GPU-deferred (Part D) for when a GPU host exists.
3. **Do not build the adapter until you pick.** When you do: one `DescriptionAdapter` class behind the existing protocol, `/no_think` if a reasoning model, greedy, alt-text prompt, async worker (never inline at ~6 min).

## 7. Reproduce

Access is via **Tailscale** (`ubuntu@acx-backend.tail1a44b8.ts.net`) — the public-IP SSH path is source-IP-allowlisted and was unreachable from this session. On the host: `uv venv` scratch env, `uv pip install torch torchvision "transformers>=4.49" accelerate pillow scikit-learn` (note: **torchvision is required** — Qwen processors build a video sub-processor), then run the standalone harness (`bench.py`, public deps + scikit-learn `china`/`flower` only) per model, emitting the same JSON schema as `E19-1-vlm-benchmark-verification-*.json`. bf16 falls back to BLAS gemm on Neoverse-N1 (no native bf16). Tear down `/tmp` after; watch `docker ps`.

## Sources

- MiMo-VL: report https://arxiv.org/abs/2506.03569 · Miloco (linked) https://arxiv.org/html/2512.17436v2 · card https://huggingface.co/XiaomiMiMo/MiMo-VL-7B-RL
- Phi-4-multimodal: https://huggingface.co/microsoft/Phi-4-multimodal-instruct
- Sub-7B: Qwen2.5-VL-3B https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct · Qwen3-VL-4B https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct · InternVL3-2B https://huggingface.co/OpenGVLab/InternVL3-2B · Ovis2 https://huggingface.co/AIDC-AI/Ovis2-8B
- Measured A1 anchors: companion memo `E19-1-vlm-model-candidates-a1-cpu.md`
