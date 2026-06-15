# E19-1 — VLM Model Candidates for the A1-CPU Description Adapter (exploration)

> **Date**: 2026-06-15 · **Status**: exploration (no decision committed) · companion to the [S10 benchmark/decision memo](E19-1-local-cpu-vlm-benchmark-decision-memo.md)
> **Target**: OCI Ampere A1 — aarch64 (Neoverse-N1), 4 OCPU, 23 GB, **no GPU**. Baseline: `microsoft/Florence-2-base-ft` = **~14 s/image** mean (beams=3, `MORE_DETAILED_CAPTION`+`OD`, 1024px). Goal: ≤~20 s/image (async worker OK), permissive license, accessibility-caption quality.
> Researched + adversarially verified across 10 model families (15 agents). **Latency figures for non-Florence models are extrapolations — they MUST be benchmarked on A1 before trusting.**

## Swap effort (why this is cheap)

The hexagonal seam (`DescriptionAdapter` Protocol → `AdapterResult`) means each model below is **one adapter class (~50–90 lines) + one wiring branch + a settings field**. Route, service, cache key, wire contract, DB, and UI are untouched; the cache key auto-isolates per `model_id`/`model_version`. **Bonus:** GIT and BLIP are native `transformers` (no `trust_remote_code`, no flash-attn) and would let us **drop the `transformers <4.49` pin** that Florence-2 forces.

## ⏱ MEASURED on the A1 (2026-06-15) — supersedes the extrapolations below

Ran all 4 shortlist models + the incumbent on the real A1 host (same china/flower images, fp32 CPU, 4 threads). **The optimistic latency extrapolations were wrong — `num_beams=3` is brutal on CPU.** `/health` stayed `ok` throughout; scratch torn down.

| Model | china | flower | budget (≤20s) | OD | Caption character |
| --- | --- | --- | --- | --- | --- |
| **Florence-2-base-ft** (incumbent, beams=3, detail+OD) | **11.1s** | **16.6s** | ✅ | boat✓ / **dining-table✗** | RICH: *"tall **red** building, **pointed roof**… water with boats"* / *"large **orange** flower, round petals, red center, blurry bg, sun"* |
| **BLIP-large** (beams=3) | **12.1s** | **13.6s** | ✅ | — | TIGHT: *"a tall tower with many windows on top of a hill"* / *"**two** orange flowers with green leaves"* |
| **SmolVLM-500M-Instruct** (greedy) | 37.2s | 39.4s | ❌ | — | GENERIC: *"In this image we can see a building, trees, boats…"* / *"…flowers… leaves"* (missed colour) |
| **GIT-large-coco** (beams=3) | 59.1s | 57.6s | ❌ | — | TERSE: *"the **pagoda** at the top of the hill"* / *"close up of a bright orange flower"* |
| **Florence-2-large-ft** (beams=3, detail+OD) | 39.8s | 38.9s | ❌ (2×) | boat✓ / **flower✓** | BEST: *"a **dahlia**… peach… petals in a circular pattern… yellow center… green leaves blurred… **another flower at the bottom**"* |

Cold load 17–28 s (incl. download); peak RSS 2.8–5.7 GB. SmolVLM-500M loaded on transformers 4.48.3 (idefics3 — no ≥4.50 bump needed).

### Sweet-spot verdict (three lenses: accuracy / WCAG-alt-text / pragmatist)

- **Florence-2-base-ft (the incumbent) is the quality×latency sweet spot** — the only model that is both **under budget** and **rich** (colour, composition, objects) at ~14 s. No swap beats it on richness-under-budget.
- **BLIP-large (~13 s)** is the strong lean alternative and the **accessibility lens actually prefers it**: tight one-sentence captions are better alt-text than Florence's verbose 8-sentence paragraphs, it's **native transformers (un-pins `<4.49`)**, BSD-3, and has **no hallucinated OD**. Loses colour/composition richness.
- **Florence-2-large-ft is the quality ceiling** (it alone ID'd the *dahlia* + the second flower, and its OD didn't hallucinate) but **~39 s → async-worker + progress UI only**.
- **GIT-large-coco & SmolVLM-500M are dominated** — over budget *and* not richer than Florence-base. (GIT was the only model to say "pagoda", though.)
- **The dominant lever is decode config, not the model:** `num_beams=3` is what blew GIT to 58 s. Greedy (`beams=1`) + **dropping the `<OD>` pass** would cut Florence-base to ~7–9 s (and kill the dining-table hallucination), and could bring Florence-large into ~15–20 s. **Tune Florence before swapping models.**

**Recommendation:** keep Florence-2-base-ft as the real-description model; drop `<OD>` + try `beams=1` for headroom + fewer hallucinations; offer Florence-2-large-ft as an async "high-quality" tier; BLIP-large is the fallback if you want to drop `trust_remote_code` and un-pin transformers. Strip filler ("There is…", "In this image we can see…") in post for alt-text norms.

---

## Ranked shortlist (pre-benchmark extrapolations — kept for the reasoning trail)

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
