# VLM-4. Anti-Hallucination Caption Generation (Ensemble Decoding + Visual-Prior)

> **Metadata**
>
> - **Date**: 2026-07-07 EST
> - **Author**: claude-opus-4-8
> - **Project**: `apps/prototype-description-service`
> - **Task ID**: `VLM-4`
> - **Target Branch**: `feature/vlm-4`
> - **Review Coverage Target**: 2

---

## VLM-4. Anti-Hallucination Caption Generation

## Objective

Reduce caption **hallucination at generation time** by two measure-gated, inference-time techniques on the VLM-3 GPU tier: **ensemble decoding** (multi-view attention-weighted synthesis of one VLM) and a **visual-prior-first** pass (EVENTA Stage 1). Adopt whichever measurably cuts `Easy-Wrong` hits without lowering `Must-Right`/insertion rate, behind the existing `DescriptionAdapter` seam.

## Intake (new feature)

- **Scope one-pager**: `docs/scopes/anti-hallucination-caption-generation-scope.md`
- **Key Q&A decisions**: `decision #1584` (scope), `#1585` (EVENTA Stage-1 added); plan-analyze findings `VLM4-PA-01..03` (fixed).
- **Not-Doing**: model training/fine-tuning; cross-model ensemble in MVP; external-document/news RAG (that is E20-FUSION); depth/event-camera input; fast-tier (Florence) ensemble; running before VLM-3 lands.

## Problem Statement

Every tier does **single-pass, whole-image** captioning whose classic failure is hallucination (Florence's "dining table" on a flower; a guessed name). The VLM-2A/2B gated rubric catches hallucinations at **eval** time (`Easy-Wrong`) but nothing reduces them at **generation** time. The papers survey identifies a **training-free, inference-time** family — ensemble decoding (arXiv 2505.17529, SOTA POPE/CHAIR) + visual-prior-first (arXiv 2606.18553) — with measured reduction on off-the-shelf VLMs. Neither exists in the service.

## Constraints

- **GPU-tier only, after VLM-3.** Ensemble decoding is **N× passes → N× latency/GPU cost** (heuristic: *tail-latency amplification* + *capacity multiplier*) — affordable only on VLM-3's async, minutes-tolerant tier; never the fast Florence tier. Hard dependency on VLM-3's `GpuRemoteDescriptionAdapter` + async describe path.
- **Behind the adapter seam** — the technique wraps `DescriptionAdapter` (`scene/application/description_adapter.py:35`) and returns `AdapterResult`; **no bespoke describe route** (ports & adapters).
- **Attention-guided variant needs attention exposure** (heuristic: *functional coupling*) — vLLM logprobs, a raw `transformers` path, or **OpenCV-5's native-VLM engine** (exposes attention+KV-cache); a **logit-only vote fallback is mandatory** where attention is unavailable.
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

## Current State Analysis

- **Works**: describe route (`describe.py:192`) → `get_description_adapter` (`deps.py:15`) → `VisualFactsService` → `VisualFactsResponse` (`responses.py:75`); the VLM-2A/2B eval harness (`scripts/eval_harness/`).
- **Depends on (VLM-3, not yet landed)**: `GpuRemoteDescriptionAdapter` (`scene/infrastructure/vlm/gpu_remote_adapter.py`), `ACX_GPU_ENDPOINT_URL`, the async describe path.
- **Missing**: any multi-pass/ensemble decode; any visual-facts-in-isolation component; attention exposure from the serving stack (confirmed by spike).

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

Five slices: (1) the **shared visual-facts (Stage-1) component** (reused by E20-FUSION); (2) the **ensemble-decode core** behind the GPU adapter (attention-weighted + logit-only fallback, bounded N, caption-only vote); (3) a **bake-off** (baseline vs ensemble vs visual-prior vs composed) on the VLM-2B corpus; (4) a **decision memo**; (5) stretch region proposals + optional Whitened-CLIP re-ranker. Sequenced strictly after VLM-3.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `scene/application/visual_facts_pass.py` (new) | Shared Stage-1: one VLM pass → structured visual facts (objects/attributes/spatial/text), no `ContextPack`; reused by E20-FUSION |
| backend | `scene/infrastructure/vlm/ensemble_decode.py` (new) | N-view decode: build views, per-view passes, attention-weighted logit ensemble + logit-only fallback, adaptive plausibility, bounded N |
| backend | `scene/infrastructure/vlm/gpu_remote_adapter.py` (VLM-3) | Extend to expose per-token logprobs/attention (or the logit-only path) for the ensemble |
| backend | `scene/config/profiles.py` / `deps.py` | Opt-in flag/profile routing a request through the ensemble/visual-prior decode |
| docs | `docs/tasks/vlm/VLM-4-decision-memo.md` (new) | Bake-off winner + measured hallucination/latency deltas |
| tests | `scene/tests/test_ensemble_decode.py`, `test_visual_facts_pass.py` (new) | Vote logic (attention + logit-only), view construction, caption-only scope, AdapterResult intact |

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

### Slice 1: Shared visual-facts (Stage-1) component

**Goal**: One VLM pass → structured visual facts in isolation, reusable by E20-FUSION.

Changes: `visual_facts_pass.py` — call the adapter with a facts-extraction prompt (no `ContextPack`), return a typed structured-facts object.

Proof: `pytest test_visual_facts_pass.py` (structured output from a stubbed adapter); E20-FUSION can import it.

### Slice 2: Ensemble-decode core

**Goal**: N-view attention-weighted (or logit-only) caption synthesis behind the GPU adapter.

Changes: `ensemble_decode.py` — view construction (grid/attention-seeded, **pinned here**), per-view passes, logit ensemble weighted by attention with logit-only fallback, adaptive plausibility, bounded N; caption-only vote, objects/phrase_boxes from the full-image pass; opt-in flag in `profiles.py`/`deps.py`.

Proof: `pytest test_ensemble_decode.py` (attention + logit-only vote math on stubbed logits; N bound; AdapterResult intact); `isinstance(..., DescriptionAdapter)`.

### Slice 3: Bake-off

**Goal**: Measure the techniques on the VLM-2B corpus.

Changes: run baseline vs ensemble vs visual-prior vs composed via `report.build_reports`; emit REPORTs + a latency-multiplier table.

Proof: committed acx-eval/v1 REPORTs; deterministic re-score bit-identical.

### Slice 4: Decision memo

**Goal**: Adopt / reject with evidence.

Changes: `VLM-4-decision-memo.md` — which technique(s) to adopt, `Easy-Wrong`/`Must-Right`/insertion deltas + the cost each buys.

Proof: memo names the verdict, cites the Slice-3 REPORTs.

### Slice 5 (stretch): region proposals + Whitened-CLIP re-ranker

**Goal**: Better views + a cheap filter.

Changes: SAM-class masks as views (re-run bake-off); Whitened-CLIP candidate re-ranker.

Proof: region views beat grid on the rubric (or the memo records they don't); re-ranker flags an over-specific caption in a test.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the scope, VLM-3 plan, and the three papers before editing.
- [ ] Confirmed the shared Stage-1 ownership vs E20-FUSION (first-to-land owns `visual_facts_pass.py`).

### Checklist for Slice 1: Shared visual-facts component

- [ ] `visual_facts_pass.py` returns structured facts from an isolation pass (no ContextPack); test green; importable by E20-FUSION.

### Checklist for Slice 2: Ensemble-decode core

- [ ] N-view decode (attention-weighted + logit-only fallback), bounded N, adaptive plausibility; view-selection strategy pinned.
- [ ] Caption-only vote; objects/phrase_boxes from the full-image pass; `AdapterResult` preserved; opt-in flag wired.
- [ ] Vote/fallback tests green; `isinstance(..., DescriptionAdapter)`.

### Checklist for Slice 3: Bake-off

- [ ] Baseline vs ensemble vs visual-prior vs composed REPORTs committed; deterministic re-score; latency multiplier recorded.

### Checklist for Slice 4: Decision memo

- [ ] Memo names the adopted technique(s) with measured deltas + cost.

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
- [ ] A memo adopts a technique **iff** it cuts `Easy-Wrong` without lowering `Must-Right`/insertion, at an accepted latency multiplier.
- [ ] The technique runs behind `DescriptionAdapter` (no bespoke route), GPU-tier-gated, with a working logit-only fallback proven by test.
- [ ] `visual_facts_pass.py` is a single shared component with E20-FUSION.
