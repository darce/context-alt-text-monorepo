# ALTQ-1. Alt-Text Quality Upgrades (research-backed)

Task: ALTQ-1 · Branch: `feature/altq-1` · Status: in_progress
Evidence base: [ALTQ-1-alt-text-quality-research-findings.md](ALTQ-1-alt-text-quality-research-findings.md)

## Objective

Raise Qwen3-VL-30B alt-text quality beyond the saturated 7b benchmark using the
2026-07-14 research synthesis: eval-harness rubric expansion first (measurement
before change), then prompt/pipeline upgrades (dual-length output, two-pass
describe-then-ground, face-gated naming), benched A/B on the golden manifest
against the 7b baseline.

## Constraints

- Black-box llama.cpp endpoint (greedy; no logits/attention). No model training.
- All scoring stays pure/deterministic (bit-identical re-score preserved).
- `alt_text_long` is an additive, optional schema extension — old run-records
  score unchanged.
- Never-guess contract is inviolable: upgrades may only tighten it.

## Terminology

- **Golden manifest (A/B corpus)** = `apps/prototype-description-service/scene/tests/seed/golden.json`
  (37 entries). Distinct from `bakeoff_golden.json` (10 entries, VLM-2B legacy) —
  Slice 3 uses `golden.json` only.
- **Two-pass** = pass-1 objective structured JSON (image only, no context/names),
  pass-2 identity/context weave. **Dual-length** = long-first generation +
  text-only compression to the short alt surface.

## Consolidated Checklist

### Context and Ownership

- Owner surface: `apps/prototype-description-service/scripts/eval_harness/`
  (bakeoff pipeline + scoring) for Slices 1–3; `scene` describe contract + WP
  plugin for Slice 4.
- Key symbols (landed): `bakeoff.py` — `PROMPT_VARIANTS` registry
  (`PromptVariant` dataclass), `--prompt-variant` / `--two-pass` /
  `--dual-length` / `--face-gate` flags, `PassOneJSONError`,
  `_stamp_pipeline_provenance`; scoring additions in `report.py`
  (`caption.short_failed_images`, per-pass provenance banner); tests in
  `scene/tests/test_eval_harness_pipeline.py`.
- Cross-plan dependencies: GPU compute pattern from
  [`docs/runbooks/oci-vlm-batch-compute-learnings.md`](../../runbooks/oci-vlm-batch-compute-learnings.md);
  CPU-tier measurement obligations from
  [`docs/assessments/current/cpu-tiered-serving-plan-2026-07-16.md`](../../assessments/current/cpu-tiered-serving-plan-2026-07-16.md);
  face-service wiring deferred to the commercial face pipeline (E22 / FIR-2/FIR-3).

### Checklist for Slice 1: Eval + test harness upgrades

- [x] `caption_metrics.py`: activate easy_wrong wrong-name trap (hard gate);
      meta-framing detector; context-duplication ratio; sentence-count band;
      name-front-loaded check — pure, additive `CaptionScores` fields.
- [x] Corpus metrics: name precision, hallucinated-name rate (closed-roster
      string match) alongside existing insertion_rate/recall.
- [x] Dual-surface scoring: optional `describe.alt_text_long` scored on the long
      rubric; `alt_text_draft` scores as the short surface; absent long ⇒ null.
- [x] `bakeoff.py` eval modes: `--eval-mode standard|context-distractor|name-ablation`
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
      from the prompt (fail-closed) — harness-side simulation only; service
      wiring Slice 4.

### Checklist for Slice 3: A/B bench on live A10 (+ CPU cells)

- [ ] GPU acquisition per the batch-compute runbook: fresh `VM.GPU.A10.1`
      launch from custom image `acx-gpu-vlm-multiad-20260716`, rotating
      AD-1/2/3, public-subnet + on-box pattern; bounded acquisition window
      (≤24 h of spaced retries). **Capacity-miss contingency**: if no AD yields
      a host in the window, record a blocker, run the CPU cells below first,
      and re-attempt in the next window — the GPU leg defers, it does not block
      the slice's CPU deliverables [RES-13].
- [ ] GPU A/B on `scene/tests/seed/golden.json` (37 images): configs
      {v1 baseline, v2 single-pass, two-pass, two-pass+face-gate} ×
      {standard, distractor, ablation} modes; GPU-on ≤ 1 h budget; instance
      terminated after (pair every launch with a terminate).
- [ ] **Cost/latency axis** recorded per config: wall-clock p50/p95 per image,
      model-call count per image (1–3 depending on flags), and $/1k images —
      quality deltas are decided against this axis, not in isolation
      [PERF-01, PERF-07].
- [ ] **CPU weave cell** (tiered-serving obligation): pass-2 weave benched
      text-only on a dedicated CPU box against the same manifest, so the T1d
      fallback tier gets a synthesis number
      (see cpu-tiered-serving-plan-2026-07-16.md §4).
- [ ] Findings appended to research doc; winning config named.

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
- [ ] Winning pipeline config beats v1 baseline on the expanded rubric with zero
      wrong-name/hallucination regressions (Slice 3, measured) — judged with the
      cost/latency axis alongside quality.
- [ ] Both output surfaces land in WP with `acx_alt_style` control (Slice 4).

## Not-Doing

- Model training/LoRA, retrieval modules, CIDEr-length tricks, attention-level
  decoding (findings §6).
- LLM-judge scoring (deterministic axes first; judge tier stays a later epic).
