# ALTQ-1. Alt-Text Quality Upgrades (research-backed)

Task: ALTQ-1 · Branch: `feature/altq-1` · Status: in_progress
Evidence base: [ALTQ-1-alt-text-quality-research-findings.md](ALTQ-1-alt-text-quality-research-findings.md)

## Objective

Raise Qwen3-VL-30B alt-text quality beyond the saturated 7b benchmark using the
2026-07-14 research synthesis: eval-harness rubric expansion first (measurement
before change), then prompt/pipeline upgrades (dual-length output, two-pass
describe-then-ground, face-gated naming), benched A/B on the 37-image golden
manifest against the 7b baseline.

## Constraints

- Black-box llama.cpp endpoint (greedy; no logits/attention). No model training.
- All scoring stays pure/deterministic (bit-identical re-score preserved).
- `alt_text_long` is an additive, optional schema extension — old run-records
  score unchanged.
- Never-guess contract is inviolable: upgrades may only tighten it.

## Slices

### Checklist for Slice 1: Eval + test harness upgrades

- [ ] `caption_metrics.py`: activate easy_wrong wrong-name trap (hard gate);
      meta-framing detector; context-duplication ratio; sentence-count band;
      name-front-loaded check — pure, additive `CaptionScores` fields.
- [ ] Corpus metrics: name precision, hallucinated-name rate (closed-roster
      string match) alongside existing insertion_rate/recall.
- [ ] Dual-surface scoring: optional `describe.alt_text_long` scored on the long
      rubric; `alt_text_draft` scores as the short surface; absent long ⇒ null.
- [ ] `bakeoff.py` eval modes: `--eval-mode standard|context-distractor|name-ablation`
      (fetch-time context transform + provenance stamp; score-time assertions
      keyed off the stamp).
- [ ] Report/markdown: new `quality` section + long-surface section + eval-mode
      banner; determinism check still bit-identical.
- [ ] Tests for every new check + mode transform + report integration
      (`scene/tests/test_eval_harness_*`), full harness test suite green.

### Checklist for Slice 2: Prompt v2 + dual-length + two-pass generation

- [ ] Prompt v2 (style rules §3 of findings) as a named variant; variant registry
      + `--prompt-variant` in bakeoff.
- [ ] Two-pass describe-then-ground mode (pass-1 structured objective JSON;
      pass-2 weave); mismatch few-shot in the weave prompt.
- [ ] Long-first generation + text-only compression to short; run-record carries
      both surfaces.
- [ ] Face-gated naming: eligible names = context ∩ face-service matches with
      positional binding (harness-side simulation first; service wiring Slice 4).

### Checklist for Slice 3: A/B bench on live A10

- [ ] Fresh A10 from golden image; 37-image manifest; configs {v1 baseline,
      v2 single-pass, two-pass, two-pass+face-gate} × {standard, distractor,
      ablation} modes; GPU-on ≤ 1 h budget; host terminated after.
- [ ] Findings appended to research doc; winning config named.

### Checklist for Slice 4: Service integration + contract change

- [ ] `describe` response contract: additive `alt_text_long`; WP plugin surfaces
      (short → alt field, long → description) + `alt_style` setting.
- [ ] Contract docs/fixtures updated per boundary discipline.

## Success Criteria

- [ ] New rubric axes catch the known defects (meta-framing, context duplication)
      on the committed 7b winner output — proven by test fixtures derived from it.
- [ ] Distractor + ablation modes runnable end-to-end and asserted in tests
      without a live GPU (transport-stubbed).
- [ ] Winning pipeline config beats v1 baseline on the expanded rubric with zero
      wrong-name/hallucination regressions (Slice 3, measured).
- [ ] Both output surfaces land in WP with `alt_style` control (Slice 4).

## Not-Doing

- Model training/LoRA, retrieval modules, CIDEr-length tricks, attention-level
  decoding (findings §6).
- LLM-judge scoring (deterministic axes first; judge tier stays a later epic).
