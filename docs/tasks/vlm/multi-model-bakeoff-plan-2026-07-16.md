# Plan: 10-image multi-model description bake-off (2026-07-16)

> Goal: find whether any A10-runnable vision model beats our measured incumbent
> (Qwen3-VL-30B-A3B) at **image descriptions** for the product. A fast 10-image
> comparison against the baseline we already have, rendered image-next-to-output
> in a self-contained report. Companion to
> [`../../assessments/current/cpu-tiered-serving-plan-2026-07-16.md`](../../assessments/current/cpu-tiered-serving-plan-2026-07-16.md)
> and the ALTQ v3 three-surface weave (feature/altq-1). Candidate research is a
> point-in-time web sweep (mid-July 2026) — verify each repo/build hands-on
> before serving (VLM releases are landing weekly).

## The 10 images (locked, reproducible)

WP `media_id`s from the vlm curation tenant, chosen to span the axes models
differ on — identity weaving, spatial (multi-face), celeb recognition, OCR:

| media_id | file | axis |
| --- | --- | --- |
| 93 | ellynheald…308648490 | multi-person (2 curated) |
| 154 | 11249412…2004 | multi-person (3 curated) |
| 200 | IMG_2957-scaled | multi-person (3 curated) |
| 46 | emma_stone_1 | single identity (curated) |
| 62 | 104450565…3259 | single identity (curated) |
| 98 | ellynheald…5107970990 | single identity (curated) |
| 6 | al_pacino_10-scaled | single identity (celeb) |
| 11 | anne_hathaway_13 | uncurated celeb (spontaneous recognition) |
| 400 | hotgirlsgotoheaven-1 | text / OCR heavy |
| 378 | bluestockingdeer…726228 | text / OCR heavy |

Run string: `--media-ids 93,154,200,46,62,98,6,11,400,378`.
Baseline (control) = `run-altq-646-interleave-v3.json` (Qwen3-VL-30B-A3B, v3
three-surface, already committed).

## Candidate matrix — A10 (24 GB), llama.cpp GGUF + mmproj path

Only models with a **working llama.cpp vision path** that fit 24 GB. Pin llama.cpp
**≥ b6887** (Qwen3-VL vision PR #16780) and spot-check the Qwen3-VL OCR-repetition
regression before trusting OCR output.

| Model | Params | Quant on A10 | GGUF repo (verify) | License | Note |
| --- | --- | --- | --- | --- | --- |
| **Qwen3-VL-30B-A3B-Instruct** | 30B/3B MoE | Q4_K_M ~18.6 GB (tight) | `unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF` | Apache-2.0 | **control** — already baked in `acx-gpu-vlm-multiad-20260716` |
| **Qwen3-VL-8B-Instruct** | 8B dense | Q5–Q8, roomy | `unsloth/Qwen3-VL-8B-Instruct-GGUF` | Apache-2.0 | safest high-quality challenger; top-class 8B OCR |
| **MiniCPM-V 4.5** | 8B dense | Q4/Q5 ~5–7 GB | `openbmb/MiniCPM-V-4_5-gguf` | Apache-2.0 | best small-model OCR/doc; needs llama.cpp PR #15575 |
| **Gemma 4 12B Unified** | 12B dense | Q6/Q8 comfortable | `unsloth/gemma-4-12b-it-GGUF` | Apache-2.0 | **newest actionable** (Jun 2026), day-1 GGUF vision; verify specs live |
| **Gemma 3 27B** | 27B dense | Q4_K_M ~16–17 GB | `bartowski/google_gemma-3-27b-it-GGUF` | Gemma (custom) | mature, stable control; Q4-only on A10 |

Apache baselines (optional): **Ministral 3 14B** (`mistralai/Ministral-3-14B-Instruct-2512-GGUF`, unproven vision numbers), **Pixtral 12B** (`bartowski/mistral-community_pixtral-12b-GGUF`, pre-2025-OCR-jump low-risk sanity baseline).

**vLLM-only (no llama.cpp vision today — separate track if pursued):**
InternVL3.5-8B (MMMU ~73, edges Qwen3-VL-8B), Ovis2.5-9B (best open OpenCompass <40B), Molmo2-8B (class-leading grounding; PixMo data terms — check commercial use), Phi-4-multimodal (best tiny OCR). GLM-4.1V-9B llama.cpp vision status is contested — verify before counting it in the GGUF path.

## Procedure (one GPU window, sequential serving)

The custom image serves only the 30B. For each additional candidate, on the A10
box: download its GGUF+mmproj (NAT egress), restart the llama.cpp unit pointed at
it with the VLM-2B serving flags (`--image-max-tokens 1536`, `--mmproj …`), wait
for `/v1/models`, then run the 10-image describe from the laptop through the
Tailscale jump tunnel:

```
ACX_EVAL_LIVE=1 GOLDEN_IMAGES_DIR=/Volumes/Butter/WP/vlm/app/public/wp-content/uploads \
python -m scripts.eval_harness.bakeoff --endpoint http://localhost:8000 \
  --model-id <model> --model-version <quant> \
  --manifest scripts/eval_harness/corpus646-interleave-manifest-20260716.json \
  --prompt-variant v3 --two-pass --limit 0 \
  --out out/run-bakeoff-<model>.json
# (the --media-ids subset is applied at report time, not fetch time; or pre-filter the manifest to the 10)
```

Then one report over all run-records (image-embedded, per-image latency, media_id):

```
python -m scripts.eval_harness.build_bakeoff_report \
  --manifest scripts/eval_harness/corpus646-interleave-manifest-20260716.json \
  --images-dir /Volumes/Butter/WP/vlm/app/public/wp-content/uploads \
  --media-ids 93,154,200,46,62,98,6,11,400,378 --embed-images \
  --run "Qwen3-VL-30B (control)=out/run-altq-646-interleave-v3.json" \
  --run "Qwen3-VL-8B=out/run-bakeoff-qwen8b.json" \
  --run "MiniCPM-V 4.5=out/run-bakeoff-minicpm45.json" \
  --run "Gemma 4 12B=out/run-bakeoff-gemma4-12b.json" \
  --run "Gemma 3 27B=out/run-bakeoff-gemma3-27b.json" \
  --title "10-image multi-model bake-off" --out reports/bakeoff-10img-multimodel.html
```

Runner script: [`infra/oci/incidents/a10-multimodel-bakeoff.sh`](../../../infra/oci/incidents/a10-multimodel-bakeoff.sh)
(serves each candidate in turn on the caught A10, runs the 10, collects records).

## Cost / time

~10 images × 2 calls × ~6 s ≈ 2 min inference per model; the real cost is the
per-model GGUF download (~5–18 GB) + serve-restart (~3–8 min each). 5 models ≈
one ~60–90 min A10 window ≈ ~$2–3. GGUF download tax dominates — pre-baking a
multi-model image would remove it if this becomes routine (not worth it for one
run).

## Decision rule

Qualitative first pass (read the 10 side by side): does a challenger produce
clearly better descriptions — richer, more accurate, better OCR, cleaner identity
weaving — than the 30B control, at acceptable latency? Any clear winner graduates
to the **scored** golden-manifest bake-off (VLM-6 S3 protocol, rubric + traps) for
a real quality number before adoption. This 10-image run is a cheap filter, not
the adoption gate. License matters for the self-hosted product: prefer Apache-2.0
(Qwen3-VL, MiniCPM-V, Gemma 4) over custom (Gemma 3).

## Not-doing

- No adoption decision from 10 images (scored golden run is the gate).
- No vLLM track unless a GGUF-path model underperforms and a vLLM-only candidate
  (InternVL3.5 / Ovis2.5 / Molmo2) is worth standing up a second serving stack for.
- No multi-model pre-baked image yet (download tax accepted for a one-off).
