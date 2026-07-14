# Task Plan — VLM-6 GPU VLM Bake-off

> **Metadata**
>
> - **Date**: 2026-07-14 14:15 EST
> - **Author**: claude-fable-5
> - **Project**: apps/prototype-description-service
> - **Task ID**: `VLM-6`
> - **Target Branch**: `feature/vlm-6`
> - **Review Coverage Target**: 2

---

## VLM-6. GPU VLM Bake-off — benchmark, decide, adopt

## Objective

Benchmark every A10-fittable open-weight VLM candidate (12 models incl. requested DeepSeek/Kimi/GLM/Ovis coverage) against the incumbents over an expanded 100-image difficulty-stratified golden corpus, pick winners hallucination-first per tier (GPU async + CPU inline), and adopt them: new `profiles.py` entries, `gpu_phi4` stub deleted, regression eval gate green before any adapter flip.

## Intake

- **Key Q&A decisions**: handoff decision `#2282` (`claude_scope_intake_vlm6_gpu_bakeoff`, 2026-07-14) — candidate breadth, hallucination-first winner rule, both tiers, adoption in-task.
- **Research basis**: deep-research run `wf_4ab72866-400` (2026-07-14, 21/25 claims adversarially verified) · `docs/tasks/19.0/E19-1-mimo-vl-vs-phi4-and-sub7b-a1-eval-20260616.md` · `docs/tasks/19.0/E19-1-local-cpu-vlm-benchmark-decision-memo.md`.
- **Not-Doing**: hosted providers (E20-11 disposition `reject` stands); >10B-active dense models; fine-tuning; multi-GPU serving; the `florence_large` async worker (obsoleted by this task); WordPress plugin changes; changes to face-recognition scoring.

## Problem Statement

The scene tier runs Florence-2-base-ft on CPU (picked for CPU viability, quality ceiling long since passed) and Qwen3-VL-30B-A3B Q4 on the GPU path. The `gpu_phi4` profile is a dead stub: research verdict (3-0 verified) says Phi-4-multimodal loses to every 2025-class candidate on the metric that matters most for alt-text (HallusionBench 40.5 vs 49–63.8). Now that the A10 burst host exists (VLM-3), the model choice has never been validated against the current field, and the 38-image golden manifest is too small and too easy to discriminate hallucination behavior between strong candidates.

## Constraints

- **Burst-host economics**: the A10 host bills while provisioned; all GPU runs happen in one scripted window; nothing gets debugged live on the meter — unscripted candidates are cut, recorded as `serving-gate-failed` [AGT-06, AGT-12].
- **Teardown is in-slice**: capture instance OCID at boot; terminate and verify at window end [RES-07] (per VLM-3B incident).
- **LocalWP uploads are read-only source material** (plugin-boundary rule): copy into `GOLDEN_IMAGES_DIR`; never write to `~/Development/wp-context-alt-text/`.
- **Determinism**: greedy decode, pinned model revisions, pinned prompts; the offline re-score path must stay bit-identical [TEST-08].
- **Eval isolation**: live eval runs use the dedicated eval tenant, never demo/prod tenants (eval-harness README contract).
- **A1 memory ceiling** for the CPU-tier run: ~18 GB free, no swap; abort any model exceeding 12 GB RSS (E19-1 measured envelope).

## Workflow Principles

- Hallucination/factuality is the primary ranking axis; caption quality secondary; latency is a tier *gate* (fits budget or not), never a ranking axis.
- Unverified-evidence candidates (DeepSeek, Kimi, GLM, Ovis) are benchmarked, not trusted from leaderboards — absence of verified evidence is not confirmed inferiority [AGT-06].
- Every model run produces raw generations + metrics on disk and a `test_result` handoff event [OBS-01, AGT-04]; every latency figure is a percentile, never an average [PERF-01], from open-loop per-image timing [PERF-03].
- No adapter flip without the regression gate meeting-or-beating the incumbent's same-corpus scores [AGT-03].

## Terminology

- **Golden-100**: the expanded 100-image evaluation corpus (supersedes the 38-image golden manifest for this task; face-recognition P/R rows keep their original 38-image basis).
- **Serving gate**: 60-minute timebox to stand up a candidate's serving stack on the bake host; failure is recorded, not debugged.
- **Tier gate (latency)**: GPU async tier ≤ 170 s p95/image — derived from the adapter timeout chain (`ACX_GPU_CONNECT_TIMEOUT_SECONDS=5` + `ACX_GPU_READ_TIMEOUT_SECONDS=175` in `scene/config/settings.py`; a model whose p95 approaches the read timeout will fail live traffic). CPU inline tier ≤ 20 s p95/image (established inline bar, E19-1). *Intake assumption*: the 170 s async bar is a ceiling, not a target — operator may tighten it in S5 when ranking.
- **Anchor**: a model run for reference, not competing for adoption (both incumbents + Phi-4).

## Current State Analysis

- `scene/infrastructure/vlm/florence_local_adapter.py:33` defaults to `microsoft/Florence-2-base-ft`; `florence_large` is a 503 stub (`scene/config/profiles.py:79`); `gpu_phi4` is a 503 stub (`profiles.py:89`).
- `gpu_qwen30b` / `gpu_qwen30b_ensemble` profiles (`profiles.py:101-119`) serve Qwen3-VL-30B-A3B Q4_K_M via `gpu_remote_adapter.py` against the llama.cpp endpoint on the burst host.
- Eval harness (`scripts/eval_harness/`: `cli.py`, `manifest.py`, `caption_metrics.py`, `draft_labels.py`, `report.py`) scores captions + face P/R against the 38-image golden manifest v2 (populated by VLM-2C, incl. phrase boxes); deterministic offline re-score exists (`score --check-determinism`).
- `scripts/benchmark_local_vlm.py` exists for ad-hoc local model timing (E19-1 era); it is not corpus-scoring.
- A10 burst infra: `infra/oci/GPU-BURST-PROVISIONING.md`, `oci_core_instance.acx_gpu_burst` in `infra/oci/main.tf` (shape `VM.GPU.A10.1`).
- Phi-4 has one CPU anchor datapoint (924 s/image, E19-1 memo); never run on GPU.

## Target Outcome

A decision memo ranks 12 candidates + 3 anchors on identical Golden-100 evidence; the GPU async profile and (if it wins) the CPU inline profile point at the new models; `gpu_phi4` is gone; the eval harness permanently gains the Golden-100 corpus and a hallucination metric, making future model swaps a re-run instead of a research project.

## Context Loading

- Rules: `docs/workbay/rules/testing-python.md`, `docs/workbay/rules/development-workflow.md`
- Contracts: `apps/prototype-description-service/scripts/eval_harness/README.md` (eval tenant + fixtures contract), `infra/oci/GPU-BURST-PROVISIONING.md`
- Handoff/MCP state: task `VLM-6`, decision `#2282`; VLM-3/VLM-3B decisions for burst-host operational history

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| -------- | ----- | ---------------- | --------------- | --------------------- | ------------ |
| Golden manifest schema (v2) | eval harness | `scripts/eval_harness/manifest.py` | additive: difficulty/domain tags, reference-facts field, and a frozen `face_eval` membership flag (original 38 ids) so face P/R keeps its basis regardless of people appearing in new images | yes — 38-image face P/R rows must still score identically; a test pins the face-metric input count to 38 | `score --check-determinism` on the pre-expansion run record + face-input-count test |
| `ACX_DESCRIPTION_ADAPTER` profile enum | scene config | `scene/config/profiles.py` | add winner profile(s); delete `GPU_PHI4` | no (greenfield policy; stub was never servable) | `scene/tests/test_description_profiles.py` updated in same slice |
| GPU serving endpoint | bake host (llama.cpp / vLLM) | `gpu_remote_adapter.py` request shape | none for GGUF winners; new vLLM-OpenAI variant only if a non-GGUF model wins | yes — adapter contract tests | `scene/tests/test_gpu_remote_adapter.py` |

## Proposed Solution

Extend the golden corpus to 100 difficulty-stratified images with reference-fact annotations (S1); build a config-driven candidate registry + scripted serve/bench driver offline (S2, offloadable); execute one A10 burst window covering all GPU candidates and anchors (S3) and the CPU-tier comparison on the A1 (S4); score hallucination-first and write the decision memo (S5); adopt winners and delete the Phi-4 stub behind a regression gate (S6).

## Candidate Matrix

Anchors (measured, not competing): **Florence-2-base-ft** (Microsoft, US — 0.23B, CPU incumbent) · **Qwen3-VL-30B-A3B-Instruct Q4_K_M** (Alibaba Qwen, CN — GPU incumbent) · **Phi-4-multimodal-instruct** (Microsoft, US — 5.6B; one GPU anchor run closes the never-tested question; research verdict: obsolete).

| # | Model | Lab | Params (active) | A10 fit | Serving plan | Evidence status |
| - | ----- | --- | --------------- | ------- | ------------ | --------------- |
| 1 | MiniCPM-V 4.5 | OpenBMB (Tsinghua, CN) | 8B | bf16 ~17 GB; official int4/GGUF/AWQ | llama.cpp (official GGUF) | verified 3-0; best-in-class anti-hallucination (RLAIF-V; MMHal 19.4%) |
| 2 | Qwen3-VL-8B-Instruct | Alibaba Qwen (CN) | 8B | bf16 ~17.5 GB; community AWQ | vLLM | verified 3-0; dense sibling of incumbent |
| 3 | Qwen3-VL-4B-Instruct | Alibaba Qwen (CN) | 4B | bf16 ~9 GB | vLLM | family verified; cheap dense option |
| 4 | InternVL3.5-8B | Shanghai AI Lab (CN) | 8B | bf16 ~17 GB | vLLM or lmdeploy | verified 2-1; doc/chart strength; Flash token-halving |
| 5 | MiMo-VL-7B-RL | Xiaomi (CN) | ~8B | bf16 ~16 GB | vLLM, `/no_think` | verified 2-1; top HallusionBench 63.8; check MMMU-anomaly artifact |
| 6 | Kimi-VL-A3B-Instruct | Moonshot AI (CN) | 16.4B total (3B active MoE) | INT4 required (~9–10 GB); bf16 exceeds 24 GB | vLLM | unverified (0-3 leaderboard claims); bench directly |
| 7 | DeepSeek-VL2-Small | DeepSeek (CN) | 16B total (2.8B active MoE) | INT4 required; bf16 exceeds 24 GB | HF Transformers; limited vLLM | unverified; Dec-2024 — oldest candidate; likeliest serving-gate failure |
| 8 | GLM-4.1V-9B-Thinking | Zhipu AI (CN) | 9B | bf16 ~19 GB (tight KV) | vLLM, force non-thinking | unverified |
| 9 | Ovis2.5-9B | Alibaba Int'l / AIDC (CN) | 9B | bf16 ~19 GB (tight KV) | HF Transformers; GPTQModel int4 | unverified; Ovis2-8B leaderboard rows verified strong |
| 10 | Ovis2-8B | Alibaba Int'l / AIDC (CN) | 8B | bf16 ~17 GB | HF Transformers | leaderboard rows verified (HallusionBench 56.3) |
| 11 | MiniCPM-V 4.6 | OpenBMB (CN) | 1.3B | ~2–4 GB GGUF | llama.cpp (official GGUF) | verified 3-0; CPU-inline Florence-successor candidate (+1 GPU run) |
| 12 | Phi-4-multimodal-instruct | Microsoft (US) | 5.6B | bf16 ~11 GB | vLLM | anchor only — research verdict 3-0 obsolete |

## Files and Surfaces to Change

| Surface | File | Change |
| ------- | ---- | ------ |
| eval corpus | `scripts/eval_harness/manifest.py` | additive schema: `difficulty`, `domain`, `reference_facts` fields |
| eval scoring | `scripts/eval_harness/caption_metrics.py` | hallucination metric: fabricated-fact count vs `reference_facts` |
| eval labeling | `scripts/eval_harness/draft_labels.py` | draft reference-facts generation for the 62 new images |
| bench driver | `scripts/eval_harness/bakeoff_runner.py` (new) | registry-driven serve→warm→run→collect loop; per-image open-loop timing |
| candidate registry | `scripts/eval_harness/bakeoff_candidates.yaml` (new) | model id, revision pin, quant artifact, serving recipe, prompt template, tier |
| bake-host prep | `infra/oci/scripts/` (new script) | weight pre-pull for all candidates into the golden image / block volume |
| scene profiles | `scene/config/profiles.py` | add winner profile(s); delete `GPU_PHI4` enum + spec |
| scene tests | `scene/tests/test_description_profiles.py`, `scene/tests/test_gpu_remote_adapter.py` | update for adopted profiles; remove phi4 expectations |
| env docs | `.env.prod.example` | adapter switch documentation for new profiles |
| docs | `docs/tasks/vlm/VLM-6-bakeoff-decision-memo.md` (new) | ranked results + adoption decision |

## Related Files

| File | Note |
| ---- | ---- |
| `scene/infrastructure/vlm/gpu_remote_adapter.py` | winner wiring; contract unchanged for GGUF-served winners |
| `scene/infrastructure/vlm/florence_local_adapter.py` | replaced or retained by S4 verdict |
| `scene/infrastructure/vlm/ensemble_decode.py` | ensemble profile follows the winning base profile |
| `scripts/benchmark_local_vlm.py` | E19-1-era timing script; superseded by `bakeoff_runner.py` for corpus runs |
| `docs/workbay/maps/tech-stack.md` | model references updated at adoption |

## Verification Strategy

- Deterministic tests:
  - `uv run --locked --extra dev pytest scene/tests scripts/eval_harness -q` (from `apps/prototype-description-service`)
  - `uv run python -m scripts.eval_harness.cli score --run-record <pre-expansion record> --check-determinism` (manifest schema change must not perturb old scores)
- Runtime-parity / environment checks:
  - S3: incumbent anchor (`gpu_qwen30b`) scored first in-window; its Golden-38 subset scores must match the S0 baseline within tolerance before candidate runs proceed
  - S6: full eval-harness run on the adopted profile via the live service path (eval tenant)
- Contract/fixture verification:
  - `scene/tests/test_gpu_remote_adapter.py` green against the winner's serving recipe
- Manual verification:
  - Spot-read 10 highest-difficulty images' descriptions for the top-2 candidates before the memo is finalized

## Slice Delivery

### Slice 0: Baseline lock

**Goal**: Fresh incumbent scores on the current 38-image manifest before anything changes.

Changes:

- None (measurement only): `make eval-captions` against current prod profiles (`florence_small`, `gpu_qwen30b`).

Proof:

- Run records in `scripts/eval_harness/out/`; `test_result` handoff events.

### Slice 1: Golden-100 corpus

**Goal**: 100-image difficulty/domain-stratified corpus with reference-fact annotations, deterministically scorable.

Changes:

- Select 62 new images: existing fixture pool + LocalWP uploads (`~/Development/wp-context-alt-text/app/public/wp-content/uploads`, copy-only); stratify across people/faces, dense scenes, text-in-image, charts/screenshots, products, low-light/blur.
- License/PII screen every new image; record provenance per image in the manifest.
- `manifest.py`: additive `difficulty`/`domain`/`reference_facts` fields + frozen `face_eval` membership (original 38 ids) with a test pinning face-metric input count to 38.
- Reference facts: `draft_labels.py` drafts all 100; **operator confirms a 20% stratified sample plus every people/faces and text-in-image entry**; agent drafts are accepted for the remainder. Sample disagreement >10% escalates to a full operator pass (owner: operator; est. 1–2 h at sample scope).
- `caption_metrics.py`: fabricated-fact hallucination metric.

Proof:

- `score --check-determinism` bit-identical on the S0 run record; new-manifest validation test green; corpus stats table (per-domain counts) in the slice decision.

### Slice 2: Bench harness + registry (offload candidate)

**Goal**: Fully scripted bake-off: registry in, metrics + raw generations out; zero live debugging left for the GPU window.

Changes:

- `bakeoff_candidates.yaml` (all 12 + 3 anchors, revision-pinned) and `bakeoff_runner.py` (serve → warm-up → 100 images at concurrency 1, open-loop per-image timing [PERF-03], p50/p95/p99 [PERF-01], cold-load, peak VRAM via `nvidia-smi` sampling, image-edge cap reusing `ACX_VLM_MAX_IMAGE_EDGE_PX` semantics with downscales recorded).
- **Execution locus**: `bakeoff_runner.py` executes **on the bake host** (invoked over Tailscale SSH from the laptop, same access path as `acx-backend`); Golden-100 images are rsynced to the host once before the window; per-model metrics + raw generations are pulled back to the laptop after each model completes (so a window abort loses at most one model's outputs).
- Weight pre-pull script; dry-run mode validated locally against a stub server.
- **Per-stack smoke gate**: one real inference per serving stack before the window — llama.cpp via MiniCPM-V 4.6 GGUF locally (laptop/A1); vLLM and HF Transformers via their smallest candidate on a short throwaway GPU boot (≤1 h) or CPU-mode where the stack supports it. No stack enters S3 unsmoked.

Proof:

- Dry-run transcript; per-stack smoke evidence; registry lints (every candidate has pin + recipe + tier); `/offload` pass results merged.

### Slice 3: A10 burst window — GPU bake-off

**Goal**: All GPU candidates + anchors measured on Golden-100 in one provisioning window.

Changes:

- None to repo code during the window (runner is frozen at S2); outputs only.
- Order: incumbent anchor first (validates harness in-window), then verified-evidence candidates, unverified labs last, Phi-4 anchor last.
- Serving gate: 60 min/candidate; failures recorded as `serving-gate-failed` with the blocking error [AGT-06].
- MiMo-VL: `/no_think` output-shape check + MMMU-anomaly probe.
- Teardown: terminate instance, verify OCID gone [RES-07].

Proof:

- Bulky raw generations + run records land in `scripts/eval_harness/out/` (gitignored working set); durable evidence — per-model summary JSON + score tables — is committed to `docs/tasks/vlm/bakeoff-results/`; per-model `test_result` events [AGT-04]; termination evidence in the slice decision.

### Slice 4: CPU inline tier run

**Goal**: MiniCPM-V 4.6 (GGUF Q4, llama.cpp) vs Florence-2-base-ft on the A1, same corpus and metrics.

Changes:

- None to repo code; A1 runs with 12 GB RSS abort threshold.

Proof:

- Run records + `test_result` events; RSS high-water line in the slice decision.

### Slice 5: Scoring + decision memo

**Goal**: Ranked, trade-off-explicit adoption decision.

Changes:

- `VLM-6-bakeoff-decision-memo.md`: hallucination-first ranking; per-candidate scores/latency/VRAM/serving friction/license/lab; explicit downside for each winner [ARCH-06]; disposition for every non-winner; tier gates applied (GPU ≤170 s p95 per the timeout-chain derivation, CPU ≤20 s p95).

Proof:

- Memo committed; planning-review-visible decision recorded; manual spot-read of top-2 candidates done.

### Slice 6: Adoption

**Goal**: Winners live in config; Phi-4 stub gone; regression gate green.

Changes:

- `profiles.py`: winner profile(s) added, `GPU_PHI4` deleted; `.env.prod.example` updated; `tech-stack.md` updated; adapter wiring (and vLLM-OpenAI adapter variant only if a non-GGUF model won).
- Ensemble profile repointed to the winning base profile.

Proof:

- `pytest scene/tests -q` green; live regression eval on adopted profile meets-or-beats incumbent S3 scores [AGT-03]; `ACX_DESCRIPTION_ADAPTER` flip documented for the operator (deploy is operator-executed).

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded eval-harness README contract, GPU-burst runbook, and VLM-3/3B handoff history before editing.
- [ ] Manifest-schema and profile-enum boundary changes recorded with compatibility notes.

### Checklist for Slice 0: Baseline lock

- [ ] `make eval-captions` run against `florence_small` and `gpu_qwen30b`
- [ ] Run records + `test_result` events captured

### Checklist for Slice 1: Golden-100 corpus

- [ ] 62 new images selected, stratified, license/PII-screened, provenance recorded
- [ ] Manifest schema extended (additive) + reference facts confirmed for all 100
- [ ] Hallucination metric implemented with unit tests
- [ ] Determinism check bit-identical on pre-expansion record

### Checklist for Slice 2: Bench harness + registry

- [ ] Registry complete: 12 candidates + 3 anchors, revision-pinned, recipes + tiers
- [ ] Runner dry-run green against stub server; VRAM/timing capture verified
- [ ] Per-stack smoke gate passed (llama.cpp, vLLM, HF Transformers each ran one real inference)
- [ ] Weight pre-pull script ready; grunt work offloaded via `/offload`

### Checklist for Slice 3: GPU bake-off window

- [ ] Incumbent anchor validates harness in-window (matches S0 within tolerance)
- [ ] All candidates run or `serving-gate-failed` recorded with evidence
- [ ] Per-model run records, raw generations, `test_result` events landed
- [ ] Burst instance terminated; OCID verified gone

### Checklist for Slice 4: CPU tier run

- [ ] MiniCPM-V 4.6 vs Florence base-ft on A1 complete within RSS threshold
- [ ] Run records + events landed

### Checklist for Slice 5: Decision memo

- [ ] Ranking + trade-offs + dispositions complete for all candidates
- [ ] Manual spot-read of top-2 done
- [ ] Memo committed and decision recorded in handoff

### Checklist for Slice 6: Adoption

- [ ] Winner profile(s) in `profiles.py`; `GPU_PHI4` deleted; tests updated
- [ ] `.env.prod.example` + `tech-stack.md` updated
- [ ] Regression eval meets-or-beats incumbent; evidence recorded
- [ ] Operator flip instructions documented

## Review Readiness

- [ ] Manifest-schema change ships with determinism evidence, not just tests.
- [ ] Runtime-parity: incumbent-anchor in-window validation and live regression eval both present (tests alone can't prove serving parity).
- [ ] Handoff decisions record each slice with verification and contract implications.

## Stretch Goals

- [ ] InternVL3.5-Flash variant timed as a latency-optimization datapoint
- [ ] Qwen3-VL-8B AWQ vs bf16 quality-delta measurement (quant-cost datapoint for future swaps)

## Success Criteria

- [ ] Every candidate has Golden-100 hallucination + caption scores, p50/p95/p99 latency, peak VRAM, or an explicit `serving-gate-failed` record — no silent drops [AGT-06].
- [ ] Decision memo names GPU-tier and CPU-tier verdicts with explicit downsides [ARCH-06].
- [ ] `gpu_phi4` no longer exists in the codebase; adopted profile(s) pass the live regression gate before any adapter flip.
- [ ] Golden-100 + hallucination metric are permanent eval-harness capabilities (future swaps are re-runs).
