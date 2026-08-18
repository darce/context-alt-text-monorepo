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

Benchmark every A10-fittable open-weight VLM candidate (13 models incl. Florence-2-large-ft and requested DeepSeek/Kimi/GLM/Ovis coverage) against the incumbents over an expanded 100-image difficulty-stratified golden corpus, pick winners hallucination-first per tier (GPU async + CPU inline), and adopt them: new `profiles.py` entries, `gpu_phi4` stub deleted, regression eval gate green before any adapter flip.

## Intake

- **Key Q&A decisions**: handoff decision `#2282` (`claude_scope_intake_vlm6_gpu_bakeoff`, 2026-07-14) — candidate breadth, hallucination-first winner rule, both tiers, adoption in-task.
- **Research basis**: deep-research run `wf_4ab72866-400` (2026-07-14, 21/25 claims adversarially verified) · `docs/tasks/19.0/E19-1-mimo-vl-vs-phi4-and-sub7b-a1-eval-20260616.md` · `docs/tasks/19.0/E19-1-local-cpu-vlm-benchmark-decision-memo.md`.
- **Not-Doing**: hosted providers (E20-11 disposition `reject` stands); >10B-active dense models; fine-tuning; multi-GPU serving; the `florence_large` async worker (obsoleted by this task — the model itself IS benchmarked, candidate #13); WordPress plugin changes; OpenCV upgrade (**as of VLM-6 writing** the pipeline pinned `opencv-python` 4.13 for decode/preprocess only; **superseded by CVUP-1** — service now pins `opencv-python==5.0.0.93` / `opencv-python-headless==5.0.0.93`; animal recognition remains a VLM concern covered by the animals/pets stratum, not an OpenCV task); **the `rd.altcontext.com` research hub** (consolidated home for galleries, benchmarks, and test retrospectives — spun out as follow-up task `RND-1`: Caddy block + DNS + static hub serving; VLM-6 artifacts are built rd-publishable but hosting is not on this task's critical path).

## Problem Statement

The scene tier runs Florence-2-base-ft on CPU (picked for CPU viability, quality ceiling long since passed) and Qwen3-VL-30B-A3B Q4 on the GPU path. The `gpu_phi4` profile is a dead stub: research verdict (3-0 verified) says Phi-4-multimodal loses to every 2025-class candidate on the metric that matters most for alt-text (HallusionBench 40.5 vs 49–63.8). Now that the A10 burst host exists (VLM-3), the model choice has never been validated against the current field, and the 37-image golden manifest (media_ids 1–38 with media_id 22 absent) is too small and too easy to discriminate hallucination behavior between strong candidates.

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

- **Golden-100**: the expanded 100-image evaluation corpus (supersedes the 37-image golden manifest). Face identity ground truth is curated for all 100 images; the original golden-37 subset (media_ids 1–38 with media_id 22 absent — max id is not the count) is additionally scored on its own for historical comparability.
  - **Corpus status on this branch (VLM6-R2-03)**: Golden-100 is Slice 1 work and has **not** landed. What S2A ships is the *harness* against the 37-entry `scene/tests/seed/golden.json`, whose `face_boxes`, `spatial_facts` and `reference_facts` are empty on 0/37 entries. Consequence: positional identification never runs (set-based identity scoring cannot catch right-names-on-wrong-faces), placement accuracy is vacuous, and fabricated-fact scoring has no denominator. A green S2A gate is evidence the scoring path is deterministic and that corruption goes red — **not** that a model cleared the adoption bar. The adoption gate in S5 requires the Slice 1 corpus. Full inventory: `apps/prototype-description-service/scripts/eval_harness/README.md` § Corpus coverage boundary; the determinism anchor carries the same list in `provenance.coverage_gaps`.
- **Serving gate**: 60-minute timebox to stand up a candidate's serving stack on the bake host; failure is recorded, not debugged.
- **Tier gate (latency)**: GPU async tier ≤ 170 s p95/image — derived from the adapter timeout chain (`ACX_GPU_CONNECT_TIMEOUT_SECONDS=5` + `ACX_GPU_READ_TIMEOUT_SECONDS=175` in `scene/config/settings.py`; a model whose p95 approaches the read timeout will fail live traffic). CPU inline tier ≤ 20 s p95/image (established inline bar, E19-1). *Intake assumption*: the 170 s async bar is a ceiling, not a target — operator may tighten it in S5 when ranking.
- **Anchor**: a model run for reference, not competing for adoption (both incumbents + Phi-4).

## Current State Analysis

- `scene/infrastructure/vlm/florence_local_adapter.py:33` defaults to `microsoft/Florence-2-base-ft`; `florence_large` is a 503 stub (`scene/config/profiles.py:79`); `gpu_phi4` is a 503 stub (`profiles.py:89`).
- `gpu_qwen30b` / `gpu_qwen30b_ensemble` profiles (`profiles.py:101-119`) serve Qwen3-VL-30B-A3B Q4_K_M via `gpu_remote_adapter.py` against the llama.cpp endpoint on the burst host.
- Eval harness (`scripts/eval_harness/`: `cli.py`, `manifest.py`, `caption_metrics.py`, `draft_labels.py`, `report.py`) scores captions + face P/R against the 37-image golden manifest v2 (populated by VLM-2C, incl. phrase boxes; media_ids 1–38 with media_id 22 absent); offline seed-stability exists (`score --check-determinism`) and the freeze compare is `score --check-determinism --expect-report <report>` / monorepo-root `make eval-anchor-check`.
- `scripts/benchmark_local_vlm.py` exists for ad-hoc local model timing (E19-1 era); it is not corpus-scoring.
- A10 burst infra: `infra/oci/GPU-BURST-PROVISIONING.md`, `oci_core_instance.acx_gpu_burst` in `infra/oci/main.tf` (shape `VM.GPU.A10.1`).
- Phi-4 has one CPU anchor datapoint (924 s/image, E19-1 memo); never run on GPU.

## Target Outcome

A decision memo ranks 14 candidates + 2 incumbent anchors on identical Golden-100 evidence; the GPU async profile and (if it wins) the CPU inline profile point at the new models; `gpu_phi4` is gone; the eval harness permanently gains the Golden-100 corpus and a hallucination metric, making future model swaps a re-run instead of a research project.

## Context Loading

- Rules: `docs/workbay/rules/testing-python.md`, `docs/workbay/rules/development-workflow.md`
- Contracts: `apps/prototype-description-service/scripts/eval_harness/README.md` (eval tenant + fixtures contract), `infra/oci/GPU-BURST-PROVISIONING.md`
- Handoff/MCP state: task `VLM-6`, decision `#2282`; VLM-3/VLM-3B decisions for burst-host operational history

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| -------- | ----- | ---------------- | --------------- | --------------------- | ------------ |
| Golden manifest schema (v2) | eval harness | `scripts/eval_harness/manifest.py` | additive: difficulty/domain tags, reference-facts field; **face identity ground truth curated for all 100 images** (present-identity labels + `face_count` incl. strangers, roster-validated — the existing manifest fields, extended to the new 63) | yes — the original golden-37 subset is still scored and reported separately for historical comparability; a test pins the golden-37 subset membership | `score --check-determinism --expect-report <S0 freeze report>` (or `make eval-anchor-check`) on the pre-expansion run record + golden-37 subset-pin test |
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
| 13 | Florence-2-large-ft | Microsoft (US) | 0.77B | bf16 ~2 GB | HF Transformers | never production-served (`florence_large` is a 503 stub); quality ceiling of the incumbent family — closes the E19-1 async-worker question |

## Files and Surfaces to Change

| Surface | File | Change |
| ------- | ---- | ------ |
| eval corpus | `scripts/eval_harness/manifest.py` | additive schema: `difficulty`, `domain`, `reference_facts` fields |
| eval scoring | `scripts/eval_harness/caption_metrics.py` | hallucination metric: fabricated-fact count vs `reference_facts` |
| eval labeling | `scripts/eval_harness/draft_labels.py` | draft reference-facts generation for the 63 new images |
| eval labeling | `scripts/eval_harness/export_identities.py` (new) | pull curated identities from `/media/identities`, match by sha256/filename, write labels into golden.json |
| bench driver | `scripts/eval_harness/bakeoff_runner.py` (new) | registry-driven serve→warm→run→collect loop; per-image open-loop timing |
| candidate registry | `scripts/eval_harness/bakeoff_candidates.yaml` (new) | model id, revision pin, quant artifact, serving recipe, prompt template, tier |
| bake-host prep | `infra/oci/scripts/` (new script) | weight pre-pull for all candidates into the golden image / block volume |
| scene profiles | `scene/config/profiles.py` | add winner profile(s); delete `GPU_PHI4` enum + spec |
| scene tests | `scene/tests/test_description_profiles.py`, `scene/tests/test_gpu_remote_adapter.py` | update for adopted profiles; remove phi4 expectations |
| env docs | `.env.prod.example` | adapter switch documentation for new profiles |
| docs | `docs/tasks/vlm/VLM-6-bakeoff-decision-memo.md` (new) | ranked results + adoption decision |
| eval reporting | `scripts/eval_harness/report.py` | self-contained HTML caption-gallery generator (`caption-gallery.html`, data-URI thumbnails) |
| eval scoring | `scripts/eval_harness/caption_metrics.py` | spatial-relation placement-correctness metric (multi-face images) |

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
  - `uv run python -m scripts.eval_harness.cli score --run-record <pre-expansion record> --check-determinism --expect-report <S0 freeze report>` (or monorepo-root `make eval-anchor-check`) — seed-stability alone is not a freeze compare; the expect-report leg is what proves a schema change did not perturb old scores
  - Copy a committed record out of tree (`WORK=$(mktemp -d) && cp ../../docs/tasks/vlm/bakeoff-results/S0-determinism-anchor-run-20260714.json "$WORK/run.json"`), then `.venv/bin/python -m scripts.eval_harness.cli score --run-record "$WORK/run.json" --manifest scene/tests/seed/golden.json --check-determinism` — caption re-score is bit-identical. **Expected exit 3**: detection/identification REFUSED on the current golden (`roster_only` / unboxed claims). A refused face block is not a perturbed caption score.
- Runtime-parity / environment checks:
  - S3: incumbent anchor (`gpu_qwen30b`) scored first in-window — this run *establishes* the GPU incumbent baseline (no separate S0 GPU baseline exists) and validates the harness end-to-end on live GPU serving; a repeated-image determinism spot-check must be bit-identical before candidate runs proceed
  - S6: full eval-harness run on the adopted profile via the live service path (eval tenant)
- Contract/fixture verification:
  - `scene/tests/test_gpu_remote_adapter.py` green against the winner's serving recipe
- Manual verification:
  - Spot-read 10 highest-difficulty images' descriptions for the top-2 candidates before the memo is finalized

## Slice Delivery

### Slice 0: Determinism anchor

**Goal**: Freeze a pre-expansion 37-image run record **and report** on the current manifest (media_ids 1–38 with media_id 22 absent). Two distinct gates, do not conflate them: (1) `score --check-determinism` / default `make eval-captions` certifies **seed-stability** — cross-process re-score of the record in hand is bit-identical under varied `PYTHONHASHSEED`; it does **not** read a freeze and will still pass if a manifest/schema edit changes scores as long as the scorer agrees with itself. (2) S1's proof that an additive schema change did not perturb scoring is `score --check-determinism --expect-report <committed freeze report>` (or monorepo-root `make eval-anchor-check`), which fails closed on `ANCHOR_MISMATCH` when the re-score diverges from the freeze. This is a harness/determinism anchor, **not** an incumbent quality baseline. Neither incumbent is quality-baselined here: prod ships the model-free `seeded` adapter (the recognition image is torch-free by design — `.env.prod.example`; florence is not deployed anywhere), and standalone incumbent runs on hastily-provisioned hosts would be cross-condition confounds ([TEST-08] determinism, [PERF-03] coordinated omission). Both incumbent quality baselines are captured in-tier, anchor-first, on the same corpus/harness as their candidates: `florence_small` → S4 CPU pass; `gpu_qwen30b` → S3 GPU window. No florence deploy and no A10 boot in S0.

Changes:

- None (measurement only): full 37-image `make eval-captions` (passes `--check-determinism` by default) against the current prod `seeded` profile — served live on `acx-backend` (= `api.altcontext.com`, the single running backend VM; "prod" and the dev VM are the same host, distinguished only by the `--env` DSN label). Eval tenant + key minted via the remote `/admin` console (`RECOGNITION_ADMIN_TOKEN`; `POST /admin/tenants` → `POST /admin/tenants/{id}/keys` — the JSON path sidesteps the browser form's same-origin CSRF guard that a tunnel trips). The `seeded` record re-scores bit-identical under seed-stability. Caption metrics on this path are model-free stub numbers by construction (not a caption-model quality baseline).
- **S0 face numbers — sampling frame (AUDIT-07), not a genuine detector baseline:** target = "face detection/ID quality on the 37-image golden"; frame = `scene/tests/seed/golden.json` (37 entries); sampling unit = image/entry; observation unit = detection/ID assertion. Claim units with **π=0** on this corpus: positional identification (`face_boxes` empty on 0/37 — never runs), placement accuracy (`spatial_facts` empty on 0/37), fabricated-fact scoring (`reference_facts` empty on 0/37). Identity scoring that *does* run is set-based (right-names-on-wrong-faces still scores clean). Worse, the determinism-anchor generator stamps predicted `face_count` and identity rows **from the ground-truth entry**, so 1.000 P/R on the freeze is a self-comparison, not a detector result. What S0 **did** deliver: a harness/determinism freeze that proves seed-stability and that corruption gates go red — **not** an adoption-grade face quality baseline. Adoption-grade face evidence requires Slice 1 (Golden-100 + curated boxes) and a non-self-sourced prediction path.
- Follow-up (tech debt, deferred): `make eval-tenant ENV=…` helper that wraps the two `/admin` calls and emits `ACX_EVAL_*` exports, consolidating the tenant/key path onto the remote console as the canonical surface (the 3 CLI façades already share one minter). Tracked in handoff, not built in this slice.

Proof:

- Run record + report promoted to `docs/tasks/vlm/bakeoff-results/` (out/ is gitignored); seed-stability via `score --check-determinism` (or default `make eval-captions`); freeze compare via `score --check-determinism --expect-report <promoted report>` / `make eval-anchor-check`; `test_result` handoff events.

### Slice 1: Golden-100 corpus

**Goal**: 100-image difficulty/domain-stratified corpus with reference-fact annotations, deterministically scorable.

Changes:

- **Procurement of the 63 new images** (100 − 37 current; three sources, in priority order; every image gets a `provenance` manifest entry — source, URL/path, license — plus `sha256` and the next stable synthetic `media_id` continuing golden.json v2's scheme, which currently ends at `media_id` 38 with 37 entries — media_id 22 is absent):
  1. **Existing fixture pool** (`GOLDEN_IMAGES_DIR` extras, `mock_entities` face crops) — roster-identity images come ONLY from here or other consented/mock-entity material, because identification ground truth requires known people.
  2. **LocalWP uploads** (`~/Development/wp-context-alt-text/app/public/wp-content/uploads`, copy-only, PII/license screen) — product-realistic scenes; expected to cover people/dense-scene/product strata.
  3. **Gap-fill for hard strata** (occlusion, mirrors, crowds, abstract, art, B&W, animals — mostly absent from 1–2): CC0/public-domain sources only (Wikimedia Commons, Openverse CC0 filter, operator's own photos), source URL + license recorded per image. Faces in gap-fill images are strangers by definition: they contribute to `face_count`/true-rejection only, never to identity labels.
> **BLOCKING, added 2026-07-28 (QA v8 re-gate) — draw and freeze the sealed eval split BEFORE any curation selection runs.** [EVAL-07] [MLDATA-09] [EVAL-10]. This slice currently stratifies, curates, and only then evaluates; nothing here draws a split. Curating first and splitting after is precisely the failure the sealed-split step exists to prevent: once a human has looked at every image to assign strata and confirm identities, the "held-out" half is held out from the *model* but not from the *selection process*, and the resulting numbers are selection-contaminated in a direction nobody can bound afterwards. The order is **freeze the split → curate → evaluate**, and the split must be committed by hash before the first curation decision.
>
> This obligation is shared with FIR-11, which owns the split artifact for the face corpus. Use a distinct term — **"sealed eval split"** — because FIR-11 already uses "sealed" in an unrelated proposal-reveal sense. If the split has not been drawn and the curation tenant is live, **stop curating and draw it first**; work already curated without a frozen split is usable as *training/development* material but not as an evaluation half.

- [x] Sealed eval split drawn + committed by hash — `bakeoff-results/S1-sealed-eval-split-20260818.json`, `draw-eval-split` CLI, `scene/tests/test_eval_harness_eval_split.py`

- Stratify across people/faces, **crowds, occlusion, mirrors/reflections, animals/pets, art (paintings/illustration), abstract imagery, black-and-white**, dense scenes, text-in-image, charts/screenshots, products, low-light/blur. Every stratum gets ≥5 images; per-domain counts reported in the slice decision.
- License/PII screen every new image; record provenance per image in the manifest.
- `manifest.py`: additive `difficulty`/`domain`/`reference_facts` fields. **Face identity ground truth for all 100 images**: present-identity labels + `face_count` (incl. non-roster strangers) curated per image using the existing manifest v2 fields; roster extended if new recurring people are added; golden-37 subset membership pinned by test so historical face P/R stays comparable.
- Reference facts: `draft_labels.py` drafts all 100; **operator confirms a 20% stratified sample plus every people/faces and text-in-image entry**; agent drafts are accepted for the remainder. Sample disagreement >10% escalates to a full operator pass (owner: operator; est. 1–2 h at sample scope).
- **Dogfooded face curation (shipped naming flow)**: provision a dedicated eval tenant on the existing dev/staging stack (`scripts/provision_demo.py` flow). Point the **existing** LocalWP install (`~/Development/wp-context-alt-text`, no new instance) at that tenant via `ACX_RECOGNITION_URL` / the `acx_recognition_base_url` filter + eval-tenant API key (**operator-performed** — agents never modify LocalWP config, per plugin-boundary rule; revert the setting after curation). Upload Golden-100 through the plugin so the recognition service's HDBSCAN clustering (`recognition/infrastructure/clustering/hdbscan_adapter.py`) proposes entity clusters, and **curate them in the plugin's shipped naming flow** (the E21-13 walkthrough surface) — this dogfoods the exact product curation path. Then a new export step (`scripts/eval_harness/` addition) reads curated identities back via the `/media/identities` endpoint (already consumed by `cli.py:231`), matches service media rows to golden.json entries by `sha256`/filename, and writes confirmed identity labels into the manifest. Corpus separation is manifest + tenant-scoped — no WP media-library "gallery" grouping is needed; WP is the curation UI, not the corpus organizer. The bench runner (S2/S3) still reads local files + manifest and never touches WP. **Anti-circularity rule**: service clustering output is a *draft only* — human confirmation is what makes it ground truth; recognition metrics are always scored against the curated truth, never against the service's own uncurated output. This doubles as an end-to-end exercise of the ingest→embed→cluster pipeline on hard strata.
- **Spatial-relation facts**: for multi-face images, derive relative-placement facts (left-of / right-of / between, foreground/background) from the curated face boxes; captions claiming placements are scored for placement correctness alongside fabricated-fact rate.
- `caption_metrics.py`: fabricated-fact hallucination metric.
- **FIR-1 bake-off coordination — reuse this harness, don't fork it** (see `docs/scopes/commercial-face-identity-replacement.md` §Coordination, `feature/fir-1` @ `d3e21098`; decision `claude_fir1_vlm6_harness_coordination`). This curation pass is the cheapest place to capture FIR's face-recognition ground truth — operator labor is the locked binding constraint, so a second tagging pass would double it:
  - **Keep the S1 curation eval tenant — do NOT dispose it.** The curation tenant (`4ddf8f36…`, LocalWP `localhost:10018`) is RETAINED after curation for the FIR bake-off; it holds the curated clusters/identities FIR-5 reuses. The earlier "disposable / orphan at teardown" framing is superseded for this tenant. The synthetic **face-pass tenant `8b8e2005…`** (site_url `https://vlm6-facepass.altcontext.com`) is ALSO retained — a reusable scratch tenant for VLM face tests — and kept SEPARATE from the curation tenant so the same faces are never clustered twice (synthetic media_ids via the analyze API vs the plugin's real WP media_ids). Its face-pass JSONL now lives in `scripts/eval_harness/out/` **and is committed to `bakeoff-results/`** (it was lost once to the ephemeral session scratchpad — 403 remote calls; never leave it only in `/tmp`).
  - **Per-entry stratum tags in golden.json.** Write stratum membership (occlusion, low-light/blur, crowds, profile) into each entry's `domain`/`difficulty` manifest fields, not only into the strata sidecar/browse set — FIR-5 reads per-entry `domain` (occlusion is already a ≥5-image stratum) and drops its own `slice_tags`.
  - **Persist ALL curated face boxes** (named + anonymous strangers, `name=None`) per entry — box-level detection ground truth for FIR's detector leg (YuNet vs SCRFD reference), not just `face_count`. XMP/MWG regions already carry the coords; the export step persists every box.
  - **Anti-blind-spot: operator tags faces the detector missed.** Cluster drafts come from the buffalo-backed service, so faces its detector misses never appear as drafts; the operator must add missed faces (naming flow / XMP region tagging), or FIR inherits buffalo's blind spots as the truth ceiling — biasing the bake-off toward the incumbent.
  - **Retain the full-res originals** — FIR needs them for synthetic-occlusion pairs (beyond the resolution floor already enforced).

Proof:

- `score --check-determinism --expect-report <S0 freeze report>` (or `make eval-anchor-check`) bit-identical on the S0 run record against the committed freeze — not seed-stability alone; new-manifest validation test green; corpus stats table (per-domain counts) in the slice decision.

### Slice 2: Bench harness + registry (offload candidate)

**Goal**: Fully scripted bake-off: registry in, metrics + raw generations out; zero live debugging left for the GPU window.

Changes:

- `bakeoff_candidates.yaml` (all 14 candidates + 2 incumbent anchors, revision-pinned) and `bakeoff_runner.py` (serve → warm-up → 100 images at concurrency 1, open-loop per-image timing [PERF-03], p50/p95/p99 [PERF-01], cold-load, peak VRAM via `nvidia-smi` sampling, image-edge cap reusing `ACX_VLM_MAX_IMAGE_EDGE_PX` semantics with downscales recorded).
- **Execution locus**: `bakeoff_runner.py` executes **on the bake host** (invoked over Tailscale SSH from the laptop, same access path as `acx-backend`); Golden-100 images are rsynced to the host once before the window; per-model metrics + raw generations are pulled back to the laptop after each model completes (so a window abort loses at most one model's outputs).
- Weight pre-pull script; dry-run mode validated locally against a stub server.
- **Per-stack smoke gate**: one real inference per serving stack before the window — llama.cpp via MiniCPM-V 4.6 GGUF locally (laptop/A1); vLLM and HF Transformers via their smallest candidate on a short throwaway GPU boot (≤1 h) or CPU-mode where the stack supports it. No stack enters S3 unsmoked.
- **Modality-agnostic registry/run-record (FIR-1 reuse)**: the candidate registry schema and the run-record's face sections stay generic — the "face legs vacuous by design" stance (VLM-2B) was a scope choice, not a schema invariant. FIR-5 registers detector+embedder candidates in-process and reuses this same `fetch_run_record` walker (per-item isolation, rg-007 bounded stall), determinism re-score, and report machinery; the S2 freeze either includes FIR's face legs or FIR runs its own driver against the same corpus + manifest.

Proof:

- Dry-run transcript; per-stack smoke evidence; registry lints (every candidate has pin + recipe + tier); `/offload` pass results merged.

### Slice 3: A10 burst window — GPU bake-off

**Goal**: All GPU candidates + anchors measured on Golden-100 in one provisioning window.

Changes:

- None to repo code during the window (runner is frozen at S2); outputs only.
- Order: incumbent anchor first (validates harness in-window), then verified-evidence candidates, unverified labs last, Phi-4 anchor last.
- Serving gate: 60 min/candidate; failures recorded as `serving-gate-failed` with the blocking error [AGT-06].
- MiMo-VL: `/no_think` output-shape check + MMMU-anomaly probe.
- **FIR-1 GPU co-scheduling**: FIR's ORT-CUDA detector/embedder legs ride this single S3 A10 window or explicitly book a second one — GPU hosts stay off otherwise [RES-07].
- Teardown: terminate instance, verify OCID gone [RES-07].

Proof:

- Bulky raw generations + run records land in `scripts/eval_harness/out/` (gitignored working set); durable evidence — per-model summary JSON + score tables — is committed to `docs/tasks/vlm/bakeoff-results/`; per-model `test_result` events [AGT-04]; termination evidence in the slice decision.

### Slice 4: CPU inline tier run

**Goal**: MiniCPM-V 4.6 (GGUF Q4, llama.cpp) vs Florence-2-base-ft on the A1, same corpus and metrics. `florence_small` (Florence-2-base-ft) is the CPU incumbent anchor — scored **first** in this pass (anchor-first, mirroring `gpu_qwen30b` in S3) to establish the CPU incumbent baseline in-condition; no separate S0 florence baseline exists (prod ships the torch-free `seeded` image, so serving florence requires a torch-enabled deploy done here).

Changes:

- None to repo code; A1 runs with 12 GB RSS abort threshold.

Proof:

- Run records + `test_result` events; RSS high-water line in the slice decision.

### Slice 5: Scoring + decision memo

**Goal**: Ranked, trade-off-explicit adoption decision.

Changes:

- `VLM-6-bakeoff-decision-memo.md`: hallucination-first ranking; per-candidate scores/latency/VRAM/serving friction/license/lab; explicit downside for each winner [ARCH-06]; disposition for every non-winner; tier gates applied (GPU ≤170 s p95 per the timeout-chain derivation, CPU ≤20 s p95).
- **Caption gallery (durable artifact, browser-rendered)**: `docs/tasks/vlm/bakeoff-results/caption-gallery.html` — self-contained HTML (thumbnails embedded as data URIs, no external assets) that opens directly in a browser: one section per image (reference thumbnail + ground-truth facts + curated face identities) with every model's caption side by side and its per-image scores. Generated by a `report.py` extension so it regenerates from run records. This is the retrospective surface: any scored result traces back to its image, model, prompt, and raw generation — and it is the first artifact to publish on the research hub (RND-1).
- **Metrics reported**: fabricated-fact rate (hallucination, primary); caption metrics; face detection precision/recall; face identification **precision/recall/accuracy** (micro + per-identity macro, full-100 and golden-37 subset); **spatial-relation placement correctness** for multi-face images; per-domain accuracy breakdowns.

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

### Checklist for Slice 0: Determinism anchor

- [x] Full 37-image `make eval-captions` run on the current manifest (prod `seeded`, eval tenant `7e1bea2f…`; target now defaults `--check-determinism`)
- [x] Seed-stability: `score --check-determinism` bit-identical on the run record (cross-process re-score only — not a freeze compare)
- [x] Freeze compare path documented for S1: `score --check-determinism --expect-report <promoted report>` / `make eval-anchor-check`
- [x] Run record + report promoted to `docs/tasks/vlm/bakeoff-results/`; `test_result` events captured
- [x] Both incumbent quality baselines confirmed deferred in-tier (florence_small → S4, gpu_qwen30b → S3); no florence deploy / no S0 GPU boot

### Checklist for Slice 1: Golden-100 corpus

- [ ] 63 new images selected, stratified (incl. occlusion/mirrors/crowds/abstract/art/B&W/animals ≥5 each), license/PII-screened, provenance recorded
- [ ] Manifest schema extended (additive) + reference facts confirmed for all 100
- [ ] Eval tenant provisioned; LocalWP pointed at it; Golden-100 uploaded via plugin; clusters curated in the shipped naming flow
- [ ] FIR-1 capture (during this pass): per-entry `domain` tags in golden.json; ALL face boxes persisted (named + strangers); operator tagged detector-missed faces; curation tenant `4ddf8f36…` RETAINED (not disposed); full-res originals kept
- [ ] Identity-export step implemented (/media/identities → golden.json by sha256 match); ground truth confirmed for all 100
- [ ] Spatial-relation facts derived from curated face boxes for multi-face images
- [ ] Hallucination + placement-correctness metrics implemented with unit tests
- [ ] Freeze compare (`--check-determinism --expect-report` / `make eval-anchor-check`) bit-identical on pre-expansion record; golden-37 subset-pin test green

### Checklist for Slice 2: Bench harness + registry

- [ ] Registry complete: 14 candidates + 2 incumbent anchors, revision-pinned, recipes + tiers
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
- [ ] Browser-rendered `caption-gallery.html` generated from run records and committed
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
