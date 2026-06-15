# E19-1 — VLM Model Candidates for the A1-CPU Description Adapter (exploration)

> **Date**: 2026-06-15 · **Status**: exploration (no decision committed) · companion to the [S10 benchmark/decision memo](E19-1-local-cpu-vlm-benchmark-decision-memo.md)
> **Target**: OCI Ampere A1 — aarch64 (Neoverse-N1), 4 OCPU, 23 GB, **no GPU**. Baseline: `microsoft/Florence-2-base-ft` = **~14 s/image** mean (beams=3, `MORE_DETAILED_CAPTION`+`OD`, 1024px). Goal: ≤~20 s/image (async worker OK), permissive license, accessibility-caption quality.
> Researched + adversarially verified across 10 model families (15 agents). **Latency figures for non-Florence models are extrapolations — they MUST be benchmarked on A1 before trusting.**

## Swap effort (why this is cheap)

The hexagonal seam (`DescriptionAdapter` Protocol → `AdapterResult`) means each model below is **one adapter class (~50–90 lines) + one wiring branch + a settings field**. Route, service, cache key, wire contract, DB, and UI are untouched; the cache key auto-isolates per `model_id`/`model_version`. **Bonus:** GIT and BLIP are native `transformers` (no `trust_remote_code`, no flash-attn) and would let us **drop the `transformers <4.49` pin** that Florence-2 forces.

## Ranked shortlist (benchmark next)

| Model | Params | License | transformers | Est. A1 latency vs 14 s | Caption quality | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| **GIT** `microsoft/git-large-coco` (or `git-base-coco`) | 0.35B / 0.13B | **MIT** | native, **un-pins** | likely **≤ baseline** (smaller, short output, greedy) | good (large-coco) / fair (base) | ✅ **confirmed** — cleanest, lowest-risk |
| **BLIP** `Salesforce/blip-image-captioning-large` (or `-base`) | 0.47B / 0.25B | **BSD-3** | native, **un-pins** | likely **faster** (384px enc, ~20-tok decode, no OD) | **fair** — short COCO sentence, terse on colour/composition | ✅ confirmed — fast baseline, lower richness |
| **SmolVLM1** `HuggingFaceTB/SmolVLM-500M-Instruct` (or 256M) | 0.5B / 0.25B | **Apache-2.0** | native (`AutoModelForVision2Seq`, idefics3, ~4.46+) | **unproven on CPU** — plausibly ≤20 s, must verify | **good + controllable** (instruction-tuned → prompt for one concise alt-text sentence) | ⚠️ best quality-per-watt of the fast tier; latency unbenchmarked |
| **Florence-2-large-ft** | 0.77B | MIT | trust_remote_code, keeps `<4.49` pin | **~30–48 s** (2–3.5× baseline) → **over budget** | good→excellent (best in family) | ✅ confirmed — quality upgrade, **async-only** |

**Recommended first benchmarks:** `git-large-coco` and `blip-image-captioning-large` (both confirmed, permissive, un-pin transformers, almost certainly under budget) + `SmolVLM-500M-Instruct` (richer/controllable captions if its CPU latency lands under 20 s). Keep `seeded` as the instant default throughout.

## Rejected (verified) — and why

| Model | Why not |
| --- | --- |
| **Moondream2** (1.9B, Apache-2.0, rich quality) | CPU path **not officially supported** (docs: NVIDIA 24GB+ only); open bugs show CPU fp32 crashes (float16-hardcoded ops need patching); needs `transformers>=4.51.1`; real CPU latency ~20–30 s/image. High integration risk + likely over budget. |
| **Qwen2-VL-2B / Qwen2.5-VL-3B** | Excellent quality but ~10–16× params → much slower on 4 CPU cores; Qwen2.5-VL-3B has a non-Apache license caveat (Qwen2-VL-2B is Apache). |
| **PaliGemma / PaliGemma2** (3B) | Excellent DOCCI alt-text, but 3B Gemma decoder → much slower on CPU; **Gemma Terms** (custom, not OSI). |
| **BLIP-2** (2.7–4B) | 2.7B+ decode → slow on CPU; OPT-variant license problems for a public/commercial demo. |
| **Kosmos-2** (1.6B) | ~7× params → much slower; grounding nice but fails the latency constraint. |
| **ViT-GPT2** (0.24B) | Trivial + fast but **weak** caption quality (not useful alt-text). |
| **Florence-2-base** (non-ft) | Same size/speed as the base-ft baseline, lower quality → no reason to swap. |

## Notes / gotchas (from adversarial verification)

- **All new-model latencies are extrapolated**, anchored to the on-host 14 s Florence baseline (same/smaller params, shorter greedy output ⇒ should be faster). aarch64 torch-CPU can be ~2.5× slower than x86 for the same model — plan around the **upper** end and benchmark on A1.
- **Keep `num_beams=1`** for any new model — beam search multiplies CPU decode linearly and is the fastest way to blow the 20 s budget.
- **transformers pin:** GIT/BLIP work on current transformers (drop the pin). SmolVLM1 needs ~4.46+; any **SmolVLM2 / Video-Instruct / 2.2B** id needs **≥4.50** and the 2.2B is too slow for 4 cores — avoid. Moondream2 needs ≥4.51.1. Florence-2 (either size) is hard-capped at `<4.49`.
- **Object detection:** only Florence-2 and Kosmos-2 emit real region/OD labels. GIT/BLIP/SmolVLM are caption-only → set `objects=[]` (or derive labels from a follow-up prompt). Since the baseline's OD already **hallucinates** (`dining table` on a flower), losing it is a minor cost.
