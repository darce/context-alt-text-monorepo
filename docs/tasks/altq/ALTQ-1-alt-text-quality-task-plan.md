# ALTQ-1. Alt-Text Quality Upgrades (research-backed)

Task: ALTQ-1 · Branch: `feature/altq-1` · Status: in_progress
Date: 2026-07-14 (revised 2026-07-16) · Author: coordinator (claude-code) · Review Coverage Target: planning verdict `pass` + branch-complete `/review-parallel`
Evidence base: [ALTQ-1-alt-text-quality-research-findings.md](ALTQ-1-alt-text-quality-research-findings.md)

> **ALTQ task family**: project-local id family for alt-text output-quality work
> (no owning epic; registered here per planning-review-guide naming rules;
> plans live under `docs/tasks/altq/`).

## Objective

Raise Qwen3-VL-30B alt-text quality using the 2026-07-14 research synthesis:
eval-harness rubric expansion first (measurement before change), then
prompt/pipeline upgrades (dual-length output, two-pass describe-then-ground,
face-gated naming), benched A/B on `golden.json` (37 images) — **comparator is
the fresh v1-baseline config measured in the same window** (the historical 7b
benchmark exists only on the 10-image legacy subset and is background context,
not the A/B comparator).

## Problem Statement

Single-surface, single-pass captions saturate the existing rubric while still
exhibiting meta-framing, context duplication, and unverifiable-name risk. The
product needs a short alt surface plus a long description surface, generated
under the never-guess contract, with measurable quality/cost trade-offs.

## Current State Analysis

- Slices 1, 2, 4 are landed on `feature/altq-1` (commits `0ddf1d99`/`79bbf48c`
  Slices 1–2, `c34aaa94`/`9e8c7439`/`ff8b6af7` Slice 4); the scoped harness
  suite is green at HEAD (416 passed) and 66 py + 79 php Slice-4 tests pass.
- Slice 3 (measurement) is the only unstarted work.
- `alt_text_long` is plumbing-complete service-side but always null until an
  adapter populates it (dual-length generation lives in the eval harness; the
  async describe worker is the future service conduit). Bulk/async run
  surfaces deliberately do not carry it.
- `golden.json` currently has **0/37 entries with `face_boxes`** — the
  face-gate bench cell has an enrichment prerequisite (see Slice 3).

## Target Outcome

A measured, cost-aware decision on which pipeline config (v1, v2, two-pass,
two-pass+face-gate, dual-length) becomes the detailed-tier default, with both
output surfaces shipped end-to-end and the never-guess contract provably
tightened.

## Constraints

- Black-box llama.cpp endpoint (greedy; no logits/attention). No model training.
- All scoring stays pure/deterministic (bit-identical re-score preserved).
- `alt_text_long` is an additive, optional schema extension — old run-records
  score unchanged.
- Never-guess contract is inviolable: upgrades may only tighten it.

## Terminology

- **Golden manifest (A/B corpus)** = `apps/prototype-description-service/scene/tests/seed/golden.json`
  (37 entries). Distinct from `bakeoff_golden.json` (10 entries, VLM-2B legacy;
  also the harness default — Slice 3 must pass `--manifest` explicitly).
- **Two-pass** = pass-1 objective structured JSON (image only, no context/names),
  pass-2 identity/context weave. **Dual-length** = long-first generation +
  text-only compression to the short alt surface. **Weave-bench** = replaying
  recorded pass-1 facts through pass-2 only (no image) — the CPU synthesis cell.

## Context Loading

Read before implementing Slice 3:
[`docs/runbooks/oci-vlm-batch-compute-learnings.md`](../../runbooks/oci-vlm-batch-compute-learnings.md)
(GPU acquisition + on-box pattern; committed on this branch),
[`docs/assessments/current/cpu-tiered-serving-plan-2026-07-16.md`](../../assessments/current/cpu-tiered-serving-plan-2026-07-16.md)
(CPU-tier obligations; committed on this branch),
[`infra/oci/GPU-BURST-PROVISIONING.md`](../../../infra/oci/GPU-BURST-PROVISIONING.md)
(existing A10 provisioning surface), and the research findings doc (§3 style
rules, §2.4 mismatch few-shot).

## Contract and Boundary Impact

| Boundary | Change | Status |
| --- | --- | --- |
| `describe` response (service ⇄ WP) | additive optional `alt_text_long` — [`image-description-api.md`](../../workbay/contracts/image-description-api.md) + `packages/shared-contracts/schemas/image-description-response.schema.json` (never in `required`) | landed (Slice 4) |
| WP settings (`acx/v1`) | `acx_alt_style` (`alt_only` default \| `alt_plus_description`; invalid → `alt_only`) | landed (Slice 4) |
| Bulk/async run surfaces | **unchanged** — do not carry `alt_text_long` (deferred, recorded in handoff decision) | n/a |
| Face-service wiring | **not in this task** — deferred to the commercial face pipeline (E22 / FIR-2/FIR-3) | deferred |

## Proposed Solution

Measurement-first pipeline upgrades behind explicit bakeoff flags (landed in
Slices 1–2), then a single A/B window (Slice 3) whose GPU leg follows the
batch-compute runbook and whose CPU cells are capacity-safe, feeding an
evidence-based adoption decision.

## Files and Surfaces to Change (Slice 3 — remaining work)

- `apps/prototype-description-service/scripts/eval_harness/bakeoff.py` —
  `--weave-bench` flag **(new)**: replay `describe["passes"][0].raw` facts from
  an input GPU run record through pass-2 messages **without `image_part`**
  against a CPU endpoint; `_weave_bench_messages()` **(new)**.
- `apps/prototype-description-service/scripts/eval_harness/report.py` —
  `_latency_summary()` **(new)**: per-config p50/p95 wall-clock per image +
  model-call count aggregated from `describe["passes"]`/`latency_s`.
- `apps/prototype-description-service/scene/tests/seed/golden.json` — enriched
  `face_boxes` via `scripts/eval_harness/export_identities.py:enrich_entry`
  (fills `face_boxes` from curated ground truth; landed on main via VLM-6).
- `docs/tasks/altq/ALTQ-1-alt-text-quality-research-findings.md` — results
  appendix.

## Verification Strategy

- New tooling (weave-bench, latency summary): transport-stubbed unit tests in
  `scene/tests/test_eval_harness_pipeline.py` / `test_eval_harness_report.py`;
  scoped command `pytest scene/tests/ -k eval_harness -q` green at HEAD.
- Bench runs: run-records + reports committed to
  `docs/tasks/altq/bakeoff-results/`; determinism check bit-identical on
  re-score; `test_result` events with commit SHAs.
- Full-suite regression stays on the remote gate (`make check-remote`) before
  merge.

## Consolidated Checklist

### Context and Ownership

- Owner surface: `apps/prototype-description-service/scripts/eval_harness/`
  (bakeoff pipeline + scoring) for Slices 1–3; `scene` describe contract + WP
  plugin for Slice 4.
- Key symbols (landed): `bakeoff.py` — `PROMPT_VARIANTS` registry
  (`PromptVariant` dataclass), `--prompt-variant` / `--two-pass` /
  `--dual-length` / `--face-gate` flags, `PassOneJSONError`,
  `_parse_pass1_json`, `_stamp_pipeline_provenance`; scoring additions in
  `report.py` (`caption.short_failed_images`, provenance banner); tests in
  `scene/tests/test_eval_harness_pipeline.py`.
- **CPU weave cell ownership**: ALTQ-1 Slice 3 **executes** the cell (it owns
  the weave code path); the cpu-tiered-serving plan §4 and VLM-6 S4/S5
  **consume** its numbers for the T1d tier decision. Single owner: ALTQ-1.
- Face-service wiring deferred to E22 / FIR-2/FIR-3 (commercial face pipeline).

### Checklist for Slice 1: Eval + test harness upgrades

- [x] `caption_metrics.py`: activate easy_wrong wrong-name trap (hard gate);
      meta-framing detector; context-duplication ratio; sentence-count band;
      name-front-loaded check — pure, additive `CaptionScores` fields.
- [x] Corpus metrics: name precision, hallucinated-name rate (closed-roster
      string match) alongside existing insertion_rate/recall.
- [x] Dual-surface scoring: optional `describe.alt_text_long` scored on the long
      rubric; `alt_text_draft` scores as the short surface; absent long ⇒ null.
- [x] `bakeoff.py` eval modes: `--eval-mode standard|context_distractor|name_ablation`
      (fetch-time context transform + provenance stamp; score-time assertions
      keyed off the stamp).
- [x] Report/markdown: new `quality` section + long-surface section + eval-mode
      banner; determinism check still bit-identical.
- [x] Tests for every new check + mode transform + report integration
      (`scene/tests/test_eval_harness_*`), full harness test suite green.

### Checklist for Slice 2: Prompt v2 + dual-length + two-pass generation

- [x] Prompt v2 (style rules §3 of findings) as a named variant in the
      `PROMPT_VARIANTS` registry (`bakeoff.py`); `--prompt-variant` flag; v1
      stays the byte-frozen baseline; chosen variant stamped into run-record
      provenance and the report banner.
- [x] Two-pass describe-then-ground `--two-pass` (pass-1 structured objective
      JSON via `_parse_pass1_json`, typed `PassOneJSONError` per-item failure;
      pass-2 weave); mismatch few-shot in the weave prompt; per-pass raw +
      latency recorded in `describe["passes"]`.
- [x] Long-first generation + text-only compression to short (`--dual-length`);
      run-record carries both surfaces; compression failure keeps the long and
      marks `short_error` (scored long-only).
- [x] Face-gated naming `--face-gate`: eligible names = context ∩ manifest
      `face_boxes` matches with positional binding; ineligible names ablated
      from the prompt (fail-closed) — harness-side simulation only; **service
      wiring deferred to E22 / FIR-2/FIR-3** (not Slice 4).

### Checklist for Slice 3: A/B bench (GPU window + CPU cells)

**Goal**: every config measured on the same 37 images with quality AND
cost/latency axes; CPU cells never blocked by GPU capacity.
**Proof**: run-records + reports in `docs/tasks/altq/bakeoff-results/`,
`test_result` events per cell, decision-rule table filled in the findings doc.

- [ ] **Prerequisite — face_boxes enrichment**: populate `face_boxes` for
      `golden.json` entries from curated ground truth via
      `export_identities.py:enrich_entry` (0/37 today; the face-gate cell is
      vacuous without it — fail-closed gate ablates every name). If curated
      boxes cover < 30/37 entries, run the face-gate cell on the covered
      subset and say so in the report.
- [x] **New tooling (test-first, before any bench)**: `--weave-bench` replay
      mode (pass-2 text-only from a recorded pass-1; no `image_part`) and
      `report.py:_latency_summary` (p50/p95 per image + model-call count per
      config). Transport-stubbed tests green.
- [ ] **GPU acquisition** per the batch-compute runbook: fresh `VM.GPU.A10.1`
      launch from the custom image (runbook §Working solution;
      `acx-gpu-vlm-multiad-20260716` — supersedes the research-findings'
      `acx-gpu-qwen3vl30b-golden`, which predates the multi-AD image), rotating
      AD-1/2/3, public-subnet + on-box; bounded acquisition window (≤24 h
      spaced retries). **Capacity-miss contingency**: no host in the window ⇒
      record a blocker, run CPU cells, re-attempt next window [RES-13].
- [ ] **GPU A/B matrix** on `--manifest scene/tests/seed/golden.json`
      (explicit override; harness default is `bakeoff_golden.json`), env
      `ACX_EVAL_LIVE=1` + `GOLDEN_IMAGES_DIR=<originals dir>`; GPU-on ≤1 h,
      terminate after. Five configs, exact flags:
      1. v1 baseline — *(no pipeline flags)*
      2. v2 single-pass — `--prompt-variant v2`
      3. two-pass — `--prompt-variant v2 --two-pass`
      4. two-pass + face-gate — `--prompt-variant v2 --two-pass --face-gate`
      5. dual-length — `--prompt-variant v2 --dual-length`
      × eval modes `standard`, `context_distractor` (all), `name_ablation`
      (configs 1–2 suffice; two-pass ablation optional if window allows).
- [ ] **CPU weave cell** (capacity-safe; runs even if GPU starves): replay
      config-3's pass-1 facts through `--weave-bench` against a CPU llama.cpp
      endpoint (Qwen3-VL-4B-Instruct Q4_K_M text-only — the tiered plan's
      zero-new-weights T1d candidate) on a dedicated CPU box per the runbook;
      report weave latency p50/p95 + the same name-safety metrics.
- [ ] **Cost/latency axis** per config from `_latency_summary` + $/1k images
      (formula: `instance $/hr × wall_hours ÷ images × 1000`; A10 ≈ $2/hr, CPU
      box ≈ $0.45/hr) [PERF-01, PERF-07].
- [ ] Findings + decision-rule table appended to the research doc; winning
      config named.

### Checklist for Slice 4: Service integration + contract change

- [x] `describe` response contract: additive `alt_text_long` in
      [`docs/workbay/contracts/image-description-api.md`](../../workbay/contracts/image-description-api.md)
      + service response model; old clients unaffected (additive-only).
- [x] WP plugin surfaces: short → alt field, long → description field;
      operator setting `acx_alt_style` (naming convention `acx_*`); exposed via
      the existing `acx/v1` settings surface.
- [x] Contract docs/fixtures updated per boundary discipline (fixtures mirror
      the new optional field; contract parity check green) [rg-005, rg-006].

### Review Readiness

- Per-slice: scoped `pytest scene/tests/ -k eval_harness` green at the slice
  HEAD; `test_result` recorded with the commit SHA.
- Branch-complete gate: `/review-parallel` on the full branch diff, findings in
  MCP, zero open findings, `handoff_close_check(enforce=True)` pass, plan
  baseline committed on main (planning verdict first).

## Success Criteria

- [x] New rubric axes catch the known defects (meta-framing, context duplication)
      on the committed 7b winner output — proven by test fixtures derived from it.
- [x] Distractor + ablation modes runnable end-to-end and asserted in tests
      without a live GPU (transport-stubbed).
- [ ] **Decision rule (Slice 3)** — the winning config must, vs the same-window
      v1 baseline on `golden.json`: (a) reduce or hold hallucinated-name rate
      AND wrong-name image rate with zero new Must-Right failures and zero
      policy violations (hard gates); (b) improve at least one of
      name_precision / mean gated score / long-rubric score; (c) keep median
      per-image wall-clock ≤ 2× v1, or the decision memo explicitly accepts the
      trade with the $/1k delta stated. Ties break toward fewer model calls.
- [ ] Both output surfaces measured (dual-length cell) AND landed in WP with
      `acx_alt_style` control — WP landing done (Slice 4); measurement pending
      (Slice 3, config 5).

## Not-Doing

- Model training/LoRA, retrieval modules, CIDEr-length tricks, attention-level
  decoding (findings §6).
- LLM-judge scoring (deterministic axes first; judge tier stays a later epic).
- Bulk/async run surfaces carrying `alt_text_long` (future slice; recorded).
- Face-service wiring (E22 / FIR-2/FIR-3).
