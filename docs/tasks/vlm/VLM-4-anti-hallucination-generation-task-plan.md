# VLM-4. Anti-Hallucination Caption Generation (Ensemble Decoding + Visual-Prior)

> **Metadata**
>
> - **Date**: 2026-07-07 EST
> - **Author**: claude-opus-4-8
> - **Realigned**: 2026-07-12 (VLM-REALIGN-01, Claude Fable 5) — VLM-3's implementation landed (adapter + async path on `main`), so the hard gate narrows to VLM-3 **Slice 7 live activation**; Slice 1's shared Stage-1 component already landed via E20-FUSION (`visual_facts_pass.py` + tests), so Slice 1 becomes adopt-and-verify; serving-stack reality (llama.cpp `server-cuda`) makes the **logit-only vote the mandatory baseline**. Anchor drift cataloged in `VLM-REALIGN-01-anchor-audit-20260712.md`.
> - **Project**: `apps/prototype-description-service`
> - **Task ID**: `VLM-4`
> - **Task Plan Status**: `proposed`
> - **Target Branch**: `feature/vlm-4`
> - **Review Coverage Target**: 2

---

## VLM-4. Anti-Hallucination Caption Generation

## Objective

Reduce caption **hallucination at generation time** by two measure-gated, inference-time techniques on the VLM-3 GPU tier: **ensemble decoding** (multi-view attention-weighted synthesis of one VLM) and a **visual-prior-first** pass (EVENTA Stage 1). Adopt whichever measurably cuts `Easy-Wrong` hits without lowering `Must-Right`/insertion rate, behind the existing `DescriptionAdapter` seam.

## Intake (new feature)

- **Scope one-pager**: `docs/scopes/anti-hallucination-caption-generation-scope.md`
- **Key Q&A decisions**: `decision #1584` (scope), `#1585` (EVENTA Stage-1 added); plan-analyze findings `VLM4-PA-01..03` (fixed).
- **Not-Doing**: model training/fine-tuning; cross-model ensemble in MVP; external-document/news RAG (that is E20-FUSION); depth/event-camera input; fast-tier (Florence) ensemble; running the bake-off (Slices 3–4) before VLM-3 Slice 7 activation produces live baseline REPORTs.

## Problem Statement

Every tier does **single-pass, whole-image** captioning whose classic failure is hallucination (Florence's "dining table" on a flower; a guessed name). The VLM-2A/2B gated rubric catches hallucinations at **eval** time (`Easy-Wrong`) but nothing reduces them at **generation** time. The papers survey identifies a **training-free, inference-time** family — ensemble decoding (arXiv 2505.17529, SOTA POPE/CHAIR) + visual-prior-first (arXiv 2606.18553) — with measured reduction on off-the-shelf VLMs. Neither exists in the service.

## Constraints

- **GPU-tier only, after VLM-3.** Ensemble decoding is **N× passes → N× latency/GPU cost** (heuristic: *tail-latency amplification* + *capacity multiplier*) — affordable only on VLM-3's async, minutes-tolerant tier; never the fast Florence tier. Hard dependency on VLM-3's `GpuRemoteDescriptionAdapter` + async describe path.
- **Behind the adapter seam** — the technique wraps `DescriptionAdapter` (`scene/application/description_adapter.py:35`) and returns `AdapterResult`; **no bespoke describe route** (ports & adapters).
- **Attention-guided variant needs attention exposure** (heuristic: *functional coupling*) — and the live stack does not have it: VLM-3's golden image serves llama.cpp `server-cuda`, which exposes token logprobs (`n_probs`) but no cross-attention. The **logit-only vote is therefore the mandatory baseline**, not a fallback; the attention-weighted variant is spike-gated on an alternative serving path (raw `transformers`, vLLM attention hooks, or OpenCV-5's native-VLM engine) and must not block Slices 2–4.
- **Ensemble scope = caption only.** The vote synthesizes `alt_text_draft`; `objects`/`ocr_text`/`phrase_boxes` come from a **designated single pass** (the full-image view) so the `AdapterResult` contract stays intact (VLM4-PA-03).
- **Bounded N** (start N≈4, hard cap); the N views are independent → GPU-batchable but bounded by VRAM (heuristic: *concurrency helps only independent work*).
- **Measure-gated** — nothing ships unless the eval harness shows the win (heuristic: *measure, don't guess*).

## Workflow Principles

- **Falsifiable before adopt** — the deliverable is the *measured decision*, like VLM-2B.
- **Reuse, don't fork** — same eval harness, same corpus, same adapter protocol.
- **Shared Stage 1** — the visual-prior pass is the *same* component as E20-FUSION Stage 1; whoever lands first owns it (VLM4-PA-01).

## Terminology

- **View** — the full image or one sub-region fed to the VLM in one pass.
- **Ensemble decode** — combine per-view token distributions at each step, attention-weighted (or logit-only vote).
- **Visual prior** — structured visual facts from a single isolation pass, before any `ContextPack` text.

## Current State Analysis (realigned 2026-07-12)

- **Works**: describe route (`describe.py:424 /describe/multipart`) → `get_description_adapter` (`scene/interface_adapters/http/deps.py:155` — `http/deps.py`, not `routers/deps.py`) → `VisualFactsService` → `VisualFactsResponse` (`responses.py:103`); the VLM-2A/2B eval harness (`scripts/eval_harness/`).
- **Landed since authoring**:
  - **VLM-3 implementation**: `GpuRemoteDescriptionAdapter` (`gpu_remote_adapter.py:105`), `ACX_GPU_ENDPOINT_URL`, the async describe path (`describe.py:553/:623`). What has NOT happened is a live GPU serving run — VLM-3 Slice 7 (activation on the newly provisioned A10) is this plan's real gate.
  - **Stage-1 component**: `scene/application/visual_facts_pass.py` (`VisualFactsPrior` :31, `VisualFactsPass` :66) + `scene/tests/test_visual_facts_pass.py` landed via **E20-FUSION** (`67056a24`, refined `f0e7d497`). Ownership question VLM4-PA-01 is resolved: E20-FUSION owns it; VLM-4 consumes.
- **Serving-stack reality**: the live GPU stack is llama.cpp `server-cuda` (VLM-3 golden image). Its completion API exposes per-token logprobs (`n_probs`) but **no cross-attention maps** — so the **logit-only vote is the mandatory baseline**, and the attention-weighted variant requires a different serving path (raw `transformers`, vLLM with attention hooks, or OpenCV-5 native-VLM engine), which is a spike-gated add, not an assumption.
- **Missing**: any multi-pass/ensemble decode (`ensemble_decode.py` and its symbols correctly absent); `GpuRemoteTokenTrace` logprob exposure on the adapter; the LLM-judge scoring tier (`cli.py` fail-fast stub — see Measure-gate risk below).

## Target Outcome

A GPU-tier describe request (opted in) runs the winning technique: either a single visual-prior-anchored pass, or an N-view ensemble vote, or both composed — returning an `AdapterResult` with measurably fewer hallucinated units, at a latency multiplier the async tier accepts. If a technique fails the eval gate, it is not shipped.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`.
- Scope: `docs/scopes/anti-hallucination-caption-generation-scope.md`; VLM-3 plan: `docs/tasks/vlm/VLM-3-gpu-detailed-tier-task-plan.md`.
- Papers: arXiv 2505.17529 (ensemble decoding), 2606.18553 (visual-prior), 2505.06934 (Whitened CLIP).
- Code seams: `scene/application/description_adapter.py`, `scene/infrastructure/vlm/gpu_remote_adapter.py` (VLM-3), `scripts/eval_harness/`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Describe adapter (`DescriptionAdapter`, `description_adapter.py:35`) | backend | protocol | New decode wrapper/decorator returning `AdapterResult`; no protocol change | No | `@runtime_checkable` isinstance test |
| GPU serving stack (VLM-3) | infra/backend | `ACX_GPU_ENDPOINT_URL` | Consume logprobs/attention (or logit-only) | No (additive) | adapter unit test w/ MockTransport |
| Describe opt-in | backend/proxy | profile/flag | New flag/profile opts a request into the technique | No | route test |
| Eval harness | backend | `report.build_reports` | Reuse unchanged; new comparison run | No | deterministic re-score |

## Proposed Solution

Five slices: (1) the **shared visual-facts (Stage-1) component** (reused by E20-FUSION); (2) the **ensemble-decode core** behind the GPU adapter (attention-weighted + logit-only fallback, bounded N, caption-only vote); (3) a **bake-off** (baseline vs ensemble vs visual-prior vs composed) on the VLM-2B corpus; (4) a **decision memo**; (5) stretch region proposals + optional Whitened-CLIP re-ranker.

**Slice sequencing vs VLM-3 (VLM4-PR-02, realigned):** **Slice 1 is resolved** — `visual_facts_pass.py` landed via E20-FUSION; Slice 1 shrinks to adopt-and-verify. **Slices 2–5 are gated on VLM-3 Slice 7** (live A10 activation + measured bake-off): the adapter and async path already exist on `main`, but running an N×-pass ensemble bake-off before the single-pass baseline is even measured on the live GPU would gate this plan's evidence on unmeasured infrastructure [RLSE-02]. Start Slice 2's decode core (pure vote math on stubbed logits) any time; run Slices 3–4 only after VLM-3 Slice 7b's baseline REPORTs exist.

**Measure-gate risk (added 2026-07-12):** the eval harness's LLM-judge scoring tier is a fail-fast stub (`scripts/eval_harness/cli.py` `_reject_llm_judge`; tech-debt gaps doc §4) — deterministic metrics catch trap-listed `Easy-Wrong` units but not open-ended semantic hallucination, which is exactly what this task reduces. Either (a) sequence the LLM-judge tier before/with Slice 3 so the gate can see the effect, or (b) record in the Slice-4 memo that the verdict is deterministic-metrics-only and what that misses. Silence here would overstate the gate. Related corpus gap: `bakeoff_golden.json` entries carry no skin-tone/cohort annotation, so the GTM skin-tone-parity falsifier (launch plan §12) cannot be sliced from this bake-off; annotating the 10-entry corpus (or recording an explicit deferral) is a cheap Slice-3 add.

## Files and Surfaces to Change

| Surface | File | Symbol / Function | Change |
| --- | --- | --- | --- |
| backend | `scene/application/visual_facts_pass.py` (**landed** via E20-FUSION) | `VisualFactsPrior` :31, `VisualFactsPass` :66 | Adopt, don't rebuild: verify GPU-profile coverage; extend only on a named gap (Slice 1) |
| backend | `scene/infrastructure/vlm/ensemble_decode.py` (new) | `EnsembleDecodeConfig`, `EnsembleDescriptionAdapter.describe`, `combine_token_distributions` (new) | N-view decode: build views, per-view passes, attention-weighted logit ensemble + logit-only fallback, adaptive plausibility, bounded N |
| backend | `scene/infrastructure/vlm/gpu_remote_adapter.py` (landed, VLM-3) | `GpuRemoteDescriptionAdapter.describe` :139; `GpuRemoteTokenTrace` (**new here, in VLM-4 Slice 2**) | Extend the landed adapter to expose per-token logprobs (llama.cpp `n_probs`); attention exposure only via the spike-gated alternative stack |
| backend | `scene/config/profiles.py` / `scene/interface_adapters/http/deps.py` | `DescriptionProfile`, `ProfileSpec`, `get_description_adapter` | Opt-in flag/profile routing a request through the ensemble/visual-prior decode |
| docs | `docs/tasks/vlm/VLM-4-decision-memo.md` (new) | decision memo (new) | Bake-off winner + measured hallucination/latency deltas |
| tests | `scene/tests/test_ensemble_decode.py`, `scene/tests/test_visual_facts_pass.py` (new) | `test_*` cases (new) | Vote logic (attention + logit-only), view construction, caption-only scope, AdapterResult intact |

## Related Files

| File | Note |
| --- | --- |
| `scene/application/description_adapter.py:20` | `AdapterResult` — the return contract (caption vs objects/phrase_boxes split) |
| `scripts/eval_harness/report.py` | `build_reports` — the bake-off scorer |
| `scene/tests/seed/bakeoff_golden.json` | VLM-2B corpus (Easy-Wrong traps drive the hallucination metric) |

## Verification Strategy

- Deterministic tests: `.venv/bin/python -m pytest scene/tests/test_ensemble_decode.py scene/tests/test_visual_facts_pass.py -q` (vote math with stubbed logits; logit-only fallback; caption-only scope; AdapterResult fields preserved).
- Bake-off: `report.build_reports` over the VLM-2B corpus for baseline vs ensemble vs visual-prior vs composed; deterministic re-score.
- Runtime-parity: confirm the chosen serving stack exposes logprobs/attention on the live GPU tier (else logit-only).
- Manual: opt a media item into the technique on the GPU tier; confirm the `Easy-Wrong` trap image (`nina-machiavelli`/flower-style) loses its hallucinated unit.

## Slice Delivery

### Slice 1: Adopt the shared visual-facts (Stage-1) component (realigned — landed via E20-FUSION)

> **Status (2026-07-12): `visual_facts_pass.py` (`VisualFactsPrior` :31, `VisualFactsPass` :66) + `test_visual_facts_pass.py` are on `main` (`67056a24`, `f0e7d497`). E20-FUSION owns the component (first-to-land rule, VLM4-PA-01 resolved). Do not rebuild it.**

**Goal**: Verify the landed component satisfies VLM-4's visual-prior needs; extend only on a named gap.

Changes: confirm `VisualFactsPass` produces the structured facts (objects/attributes/spatial/text) the visual-prior-first pass needs against the GPU adapter (not just the fusion fast-tier path — the landed component classifies fast-tier profiles via `is_fast_tier_profile`); any gap becomes an explicit extension with its own test, not a fork [NAME-05].

Proof: existing `pytest test_visual_facts_pass.py` green; one added test exercising the pass through a GPU-profile adapter stub; a one-paragraph adoption note in the Slice-4 memo naming any extension made.

### Slice 2: Ensemble-decode core

**Goal**: N-view attention-weighted (or logit-only) caption synthesis behind the GPU adapter.

Files/functions:

- `scene/infrastructure/vlm/ensemble_decode.py:EnsembleDecodeConfig` (new) — bounded N, view strategy, and adaptive-plausibility settings.
- `scene/infrastructure/vlm/ensemble_decode.py:EnsembleDescriptionAdapter.describe` (new) — wraps a GPU `DescriptionAdapter` and returns `AdapterResult`.
- `scene/infrastructure/vlm/ensemble_decode.py:combine_token_distributions` (new) — attention-weighted and logit-only vote math.
- `scene/infrastructure/vlm/gpu_remote_adapter.py:GpuRemoteDescriptionAdapter.describe` (VLM-3) — expose per-token logprobs/attention when available.
- `scene/config/profiles.py:DescriptionProfile` / `ProfileSpec` and `scene/interface_adapters/http/deps.py:get_description_adapter` — add the opt-in profile/flag routing.
- `scene/tests/test_ensemble_decode.py:test_*` (new) — vote/fallback math, N bound, caption-only scope, and `AdapterResult` preservation.

Changes: view construction (grid/attention-seeded, **pinned here**), per-view passes, logit ensemble, adaptive plausibility, bounded N; caption-only vote, objects/phrase_boxes from the full-image pass; opt-in as one named profile — `DescriptionProfile.GPU_QWEN30B_ENSEMBLE` in `profiles.py` resolved by `get_description_adapter` — not a scattered flag string [sr-007].

**Attention-weighting mechanism (VLM4-PR-01), per arXiv 2505.17529:** at each decode step, for each view take the generated token's **cross-attention to that view's image patches**, reduce it to a per-view scalar (mean attention mass on image tokens = "is the model looking at the image, not just prior text"), softmax-normalize across views → weights `w_v`; the ensembled next-token distribution is `softmax(Σ_v w_v · logits_v)`, then the adaptive-plausibility constraint masks low-probability tokens. **Logit-only fallback (no attention):** unweighted mean of per-view `logprobs` (or confidence-weighted by each view's top-token probability) — a strictly weaker vote, quantified in the bake-off.

Proof: `pytest test_ensemble_decode.py` (attention + logit-only vote math on stubbed logits; N bound; AdapterResult intact); `isinstance(..., DescriptionAdapter)`.

### Slice 3: Bake-off

**Goal**: Measure the techniques on the VLM-2B corpus.

Files/functions:

- `scripts/eval_harness/report.py:build_reports` — unchanged scorer for captured run records.
- `scene/tests/seed/bakeoff_golden.json` — VLM-2B corpus input.
- `docs/tasks/vlm/VLM-4-*-report.{json,md}` (new) — curated acx-eval/v1 REPORT artifacts.

Changes: run baseline vs ensemble vs visual-prior vs composed via `report.build_reports`; emit REPORTs + a latency-multiplier table. The latency table must state each technique's measured wall-clock against the async **job timeout** (`asyncio.wait_for` budget in the describe worker, VLMFIX-S1-04) and the **reaper idle/fencing window** — a technique that wins on quality but exceeds the timeout budget fails the gate [RES-02], [PERF-07].

Proof: committed acx-eval/v1 REPORTs; deterministic re-score bit-identical; latency-vs-timeout fit stated per technique.

### Slice 4: Decision memo

**Goal**: Adopt / reject with evidence.

Files/functions:

- `docs/tasks/vlm/VLM-4-decision-memo.md` (new) — evidence-backed adopt/reject memo.

Changes: record which technique(s) to adopt, `Easy-Wrong`/`Must-Right`/insertion deltas + the cost each buys.

Proof: memo names the verdict, cites the Slice-3 REPORTs.

### Slice 5 (stretch): region proposals + Whitened-CLIP re-ranker

**Goal**: Better views + a cheap filter.

Files/functions:

- `scene/infrastructure/vlm/ensemble_decode.py:build_region_proposal_views` (new/stretch) — SAM-class mask views when the spike justifies the dependency.
- `scene/infrastructure/vlm/clip_rerank.py:WhitenedClipReranker` (new/stretch) — optional candidate re-ranker.

Changes: SAM-class masks as views (re-run bake-off); Whitened-CLIP candidate re-ranker. **(VLM4-PR-03) Whitened-CLIP adds a net-new CLIP model dependency** — the service has no CLIP today (recognition uses InsightFace buffalo_l, not CLIP), same new-embedder class as E20-BRAND-A's OpenCLIP question → optional/stretch, spike-gated, not a free guardrail.

Proof: region views beat grid on the rubric (or the memo records they don't); re-ranker flags an over-specific caption in a test.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the scope, VLM-3 plan (incl. Slice 7 status), and the three papers before editing.
- [x] Confirmed the shared Stage-1 ownership vs E20-FUSION — resolved: E20-FUSION landed and owns `visual_facts_pass.py`; VLM-4 consumes.

### Checklist for Slice 1: Adopt the shared visual-facts component

- [ ] Existing `test_visual_facts_pass.py` green; one added GPU-profile-stub test; adoption note (incl. any named extension) drafted for the memo.

### Checklist for Slice 2: Ensemble-decode core

- [ ] N-view decode (attention-weighted + logit-only fallback), bounded N, adaptive plausibility; view-selection strategy pinned.
- [ ] Caption-only vote; objects/phrase_boxes from the full-image pass; `AdapterResult` preserved; opt-in flag wired.
- [ ] Vote/fallback tests green; `isinstance(..., DescriptionAdapter)`.

### Checklist for Slice 3: Bake-off

- [ ] Baseline vs ensemble vs visual-prior vs composed REPORTs committed; deterministic re-score; latency multiplier recorded.
- [ ] Measure-gate scope stated: LLM-judge tier used, or its absence + what deterministic metrics miss recorded in the memo.
- [ ] Skin-tone cohort: corpus entries annotated and accept-rate sliced by cohort, or an explicit deferral recorded (GTM launch plan §12 falsifier; [A11Y-02] — the alt text must serve its purpose for every subject).

### Checklist for Slice 4: Decision memo

- [ ] Memo names the adopted technique(s) with measured deltas + cost; adopt/reject is a gate verdict, not a narrative [RLSE-02].

### Checklist for Slice 5 (stretch)

- [ ] Region-proposal views bake-off; Whitened-CLIP re-ranker (optional).

## Review Readiness

- [ ] No boundary-touching change (adapter wrapper, GPU serving, opt-in) left without contract/doc/test evidence.
- [ ] Runtime-parity: attention/logprob exposure confirmed on the live GPU stack (else logit-only proven).
- [ ] Handoff decision records the change, verification, and the VLM-3 dependency per slice.

## Stretch Goals

- [ ] Cross-model ensemble (different VLMs) — deferred.
- [ ] OpenCV-5 native-VLM engine as the attention-exposing serving path.

## Success Criteria

- [ ] One committed bake-off REPORT compares baseline vs ensemble vs visual-prior vs composed on the VLM-2B corpus, re-score bit-identical.
- [ ] A memo adopts a technique **iff** it cuts `Easy-Wrong` without lowering `Must-Right`/insertion, at an accepted latency multiplier — with the measure-gate's scope (LLM-judge present or absent) stated in the verdict.
- [ ] The technique runs behind `DescriptionAdapter` (no bespoke route), GPU-tier-gated, with the logit-only vote proven by test as the baseline path.
- [x] `visual_facts_pass.py` is a single shared component with E20-FUSION (landed; E20-FUSION owns, VLM-4 consumes).
