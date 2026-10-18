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
| 93 | gildedcypress…308648490 | multi-person (2 curated) |
| 154 | 11249412…2004 | multi-person (3 curated) |
| 200 | IMG_2957-scaled | multi-person (3 curated) |
| 46 | emma_stone_1 | single identity (curated) |
| 62 | 104450565…3259 | single identity (curated) |
| 98 | gildedcypress…5107970990 | single identity (curated) |
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

| Label | Model | Params | Quant | Weights + mmproj | GGUF repo | License | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `qwen3vl-30b` | Qwen3-VL-30B-A3B-Instruct | 30B / 3B MoE | Q4_K_M | 18.56 + 1.08 = **19.64 GB** | `unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF` | Apache-2.0 | **control** — run-record exists, not re-run |
| `qwen36-27b` | Qwen3.6-27B | 27B dense (DeltaNet+Attn) | UD-Q4_K_XL | 17.61 + 0.93 = **18.54 GB** | `unsloth/Qwen3.6-27B-GGUF` | Apache-2.0 | like-for-like quality challenger to the control |
| `qwen36-35b-a3b` | Qwen3.6-35B-A3B | 35B / 3B MoE | UD-Q3_K_XL | 16.85 + 0.90 = **17.75 GB** | `unsloth/Qwen3.6-35B-A3B-GGUF` | Apache-2.0 | UD-Q4 (22.4 GB) deliberately not used — OOM w/ KV |
| `ornith15-35b-a3b` | Ornith-1.5-35B-A3B | 35B / 3B MoE | Q3_K_XL | 17.80 + 0.90 = **18.70 GB** | `bartowski/Ornith-1.5-35B-A3B-GGUF` | MIT | **added 2026-08-20** — same `qwen3_5_moe` arch + quant tier as the row above; isolates agentic-coding post-training vs vision-instruct. `--no-think` mandatory |
| `qwen3vl-8b` | Qwen3-VL-8B-Instruct | 8B dense | Q5_K_M | 5.85 + 1.16 = **7.01 GB** | `unsloth/Qwen3-VL-8B-Instruct-GGUF` | Apache-2.0 | safest high-quality challenger; top-class 8B OCR |
| `minicpm45` | MiniCPM-V 4.5 | 8B dense | Q5_K_M | 5.85 + 1.10 = **6.95 GB** | `openbmb/MiniCPM-V-4_5-gguf` | Apache-2.0 | best small-model OCR/doc; anti-hallucination (RLAIF-V) |
| `gemma4-12b` | gemma-4-12b-it | 12B dense | Q6_K | 9.79 + 0.18 = **9.97 GB** | `unsloth/gemma-4-12b-it-GGUF` | Apache-2.0 | newest actionable; day-1 GGUF vision |
| `gemma3-27b` | gemma-3-27b-it | 27B dense | Q4_K_M | 16.55 + 0.86 = **17.41 GB** | `bartowski/google_gemma-3-27b-it-GGUF` | Gemma (custom) | mature stable comparator; Q4-only on A10 |
| `joycaption-b1` | llama-joycaption-beta-one | 8B dense (Llama 3.1 + LLaVA) | Q8_0 | 8.54 + 0.88 = **9.42 GB** | `concedo/llama-joycaption-beta-one-hf-llava-mmproj-gguf` | Llama 3.1 Community (see caveat) | **re-added 2026-08-20** — caption-specialized; already benched (VLM-6 round-2 + 646 CPU baseline). Stage 1 = standard v3, no flags |
| `ornith15-9b` | Ornith-1.5-9B | 9B dense | Q8_0 | 9.53 + 0.92 = **10.45 GB** | `ornith-ai/Ornith-1.5-9B-GGUF` | MIT | *optional* cheap leg, commented out in the runner |

All filenames + byte sizes HEAD-verified against the HF APIs 2026-08-20; the runner
carries the exact resolve URLs. A10 = 24 GB, so quants were picked to land
<= ~20 GB, leaving ~3 GB for KV at `--ctx-size 8192 --image-max-tokens 1536`.

**Build split:** `qwen36-*` and `ornith15-35b-a3b` are `qwen3_5` / `qwen3_5_moe`
arch and need llama.cpp **newer than b6887** for vision — they pass or fail the
serving gate together. The other five serve on b6887.

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

Runner script: `benchmarks/runners/a10-multimodel-bakeoff.sh` (serves each
candidate in turn on the caught A10, runs both lexicon arms, collects records).

## Depiction-lexicon A/B arm (VLM6-LEX)

Every candidate runs the 10 images **twice against the same served instance**:
lexicon OFF, then lexicon ON. The pair is the measurement — the delta between a
model's two legs is attributable to the prompt, because weights, quant, serving
flags, decoding, manifest, and GPU window are all held fixed within the pair.

- **OFF leg** is the plain `--prompt-variant v3 --two-pass` call. Its prompt
  string is byte-identical to the historical baseline, so it also stays
  comparable to every run-record already on disk (including the 30B control).
- **ON leg** adds `--depiction-lexicon ~/Development/heuristics-canon`, which
  appends the canon depiction rules — families `ATTRIB` (attribution &
  identity claims) and `BOUND` (descriptive boundaries & the limits of the
  frame), 15 rules at canon v0.21.6 — to the prose-writing system prompt.

The canon is a separate private checkout; its lexicons are read at run time and
never vendored into the monorepo. Each ON run-record carries
`provenance.depiction_lexicon` = canon tag + file sha256 + the exact rule ids
injected, so a leg can be re-derived without the rule text entering git.

Injection is scoped to the pass that makes claims. Pass-1 emits objective JSON
facts and asserts nothing about who is depicted, so it is untouched; the rules
reach the pass-2 weave. At full detail the block is ~1.9k tokens against
`--ctx-size 8192` with 1536 image tokens — `--lexicon-detail brief` and
`--lexicon-tiers B,S` are the levers if a tight-context candidate truncates.

**What the delta should show.** The lexicon is aimed squarely at this
bake-off's primary axis (hallucination / over-claim), not at prose polish:
`ATTRIB-01` (no interior-state or will claims owned by the depicted person),
`ATTRIB-02` (no uncited identity or guilt claims in forensic voice),
`BOUND-01` (no cause, sequence, fate, or completeness from a still),
`BOUND-05` (no "emphasizes/focuses on" unless a pictorial cue licenses it).
Read the pair for: fewer unlicensed inferences, fewer invented specifics, and
whether hedging/attribution language displaces the concrete visible detail the
alt text is for. A quieter, more literal ON leg is a win only if it did not
also lose the facts.

**Confounds to hold.** ~1.9k extra prompt tokens is itself a treatment: a
degraded ON leg on a small model may be context pressure, not rule-following.
Check the ON leg's failure mode before reading it as a lexicon verdict —
truncated pass-2 JSON, dropped names, or collapsed length point at context,
while flattened claims with intact facts point at the rules. And the rules are
tuned for *description*, so a leg that gets quieter on the caption surface may
be right even where the report's caption-quality proxy scores it lower.

## Cost / time

~10 images × 2 calls × ~6 s ≈ 2 min inference per leg. The A/B pairing doubles
inference to ~4 min per model but **not** the dominant cost: the per-model GGUF
download (~5–18 GB) + serve-restart (~3–8 min each) is paid once per model,
since both arms hit the same served instance. 8 models × 2 arms ≈ one ~2–2.5 h
A10 window ≈ ~$4–5. GGUF download tax still dominates — pre-baking a
multi-model image would remove it if this becomes routine (not worth it for one
run).

### JoyCaption — prior art already in the handoff DB (do not re-derive)

VLM-6 action **#18** says absorb this candidate rather than re-research it. What is
already measured:

- **Round-2 interleave, A10, 10 clean images** (decision 2594, 2026-07-17): 10/10 ok,
  ~196 mean words, but wove only **4/10 curated names** and missed *every* multi-person
  group (media 154 → 0/3, media 200 → 0/2, media 98 → 0). Cause: it received a flat name
  list with no face-position grounding. Recorded insight: *"identity-weaving needs the
  structured face-box v3 pipeline; JoyCaption does description, not attribution."*
- **Explicit-register spike** (decision 2592): 4/4, ~225 mean words, **no hedging**, 5.5 s
  — the only candidate that did not euphemize. Logged as *"the register frontrunner."*
- **646-image CPU full-corpus baseline** (decisions 2627/2629, A1.Flex, $2.90 total,
  ~$0.0022/inference): **646/646 clean**. After the positional-grounding fix, pseudonym
  echo was **476/528 vs Qwen3-VL-4B's 524/528** — still the weaker attributor, but no
  longer catastrophic on groups. Run-record: `benchmarks/runs/cpu-baseline-20260717/run-joycaption.json`.
- **The identity fix is already in the shared harness.** Decision 2596's face-box
  positional binding is now `bakeoff.py --face-gate` (action #23's "do it once, consume in
  three places"). No `joycaption_describe.local.py` side-driver is needed anymore.
- **License is unresolved.** Decision 2590 recorded Apache-2.0; that is almost certainly
  wrong — it is a Llama 3.1 8B derivative, so the Llama 3.1 Community License flows
  through (commercial OK under 700 M MAU, but "Built with Llama" attribution required).
  Gate before adoption, not before benching.
- **Style mismatch is the real risk**, not capability: JoyCaption is tuned for dense
  diffusion-training captions; the product wants WCAG alt-text (summary-first, hedged
  uncertainty, no invented facts). ~196–225 words is 4–5× the mainstream legs' 42–55.


## Decision rule

Qualitative first pass (read the 10 side by side): does a challenger produce
clearly better descriptions — richer, more accurate, better OCR, cleaner identity
weaving — than the 30B control, at acceptable latency? Any clear winner graduates
to the **scored** golden-manifest bake-off (VLM-6 S3 protocol, rubric + traps) for
a real quality number before adoption. This 10-image run is a cheap filter, not
the adoption gate. The lexicon arm is scored the same way and answers a separate
question: it ranks *prompts*, not models. If the ON leg wins broadly, the
lexicon (or a distilled subset of it) belongs in the production system prompt
and the scored golden run should carry it; if it wins only on the largest
candidates, that is a capability finding about rule-following under a long
instruction block, not a reason to ship it everywhere. License matters for the self-hosted product: prefer Apache-2.0
(Qwen3-VL, MiniCPM-V, Gemma 4) over custom (Gemma 3).

## Not-doing

- No adoption decision from 10 images (scored golden run is the gate).
- No vLLM track unless a GGUF-path model underperforms and a vLLM-only candidate
  (InternVL3.5 / Ovis2.5 / Molmo2) is worth standing up a second serving stack for.
- No multi-model pre-baked image yet (download tax accepted for a one-off).
