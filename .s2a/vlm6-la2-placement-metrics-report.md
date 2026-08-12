# Lane report: `vlm6-la2-placement-metrics` (VLM-6 / VLM6-R4-03)

**Verdict:** pass — merge-ready for orchestrator review  
**Lane:** `vlm6-la2-placement-metrics`  
**Finding:** VLM6-R4-03 (placement metric must be able to score badly)  
**Owned paths only:**
- `apps/prototype-description-service/scripts/eval_harness/placement_metrics.py`
- `apps/prototype-description-service/scene/tests/test_eval_harness_placement_metrics.py`
- `.s2a/vlm6-la2-placement-metrics-report.md` (this report)

## Summary

`score_placement` no longer drops paraphrased placement claims into a silent
`None`. Structural paraphrase matching (entity-pair + direction order, and
subject-centric absolute cues like "on the right") returns **wrong** or
**correct**. Abstentions are explicit on `PlacementScores.abstained`.
`placement_accuracy` still returns `None` only when no claims were asserted
(distinct from `0.0` = all claims wrong). Module docstring defines claim /
abstention / error observables (MEAS-11).

## Diff summary

### `placement_metrics.py`
- Expanded module docstring with MEAS-11 observables: claim correct, claim
  wrong, abstention, and `None` vs `0.0` for `placement_accuracy`.
- Added `PlacementScores.abstained: list[str]`.
- Kept near-verbatim phrase + inversion + BETWEEN wrong-middle paths.
- Added structural paraphrase path:
  - binary pair order: `subject … dir … reference` and inverse wording
    `reference … opposite_dir … subject`
  - absolute subject cues: "on the left/right", "in the foreground/background", …
  - BETWEEN structure-derived correct phrases as well as wrong
- Facts no longer require authored `phrases` to be applicable (relation +
  entities suffice).
- Scorable fact with no match → `abstained`, not omitted from the result.

### `test_eval_harness_placement_metrics.py`
- Updated no-claim / word-boundary / accuracy micro cases to assert abstentions.
- `test_fact_without_phrases_uses_relation_structure` (strengthened: scores via
  structure).
- New VLM6-R4-03 cases:
  - paraphrased wrong pair order → accuracy `0.0`
  - paraphrased correct pair order → accuracy `1.0`
  - absolute wrong ("the man stands on the right") → accuracy `0.0`
  - absolute correct → `1.0`
  - above/below structural wrong
  - foreground structural wrong (still covered via inversion + structure)
  - abstention vs zero accuracy distinct
  - `PlacementScores.abstained` field present

## RED-before (unfixed code, new tests)

Command:
```
cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/test_eval_harness_placement_metrics.py -q --tb=line
```

Actual output (excerpt):
```
[progress: several FAILED]                                                     [100%]
=================================== FAILURES ===================================
E   AttributeError: 'PlacementScores' object has no attribute 'abstained'
...
E   assert ([])
     +  where [] = PlacementScores(correct=[], wrong=[]).wrong
.../test_eval_harness_placement_metrics.py:131: assert ([])
  # test_paraphrased_wrong_pair_order_scores_wrong
  # caption: "Bob is to the left of Alice." → wrong=[], accuracy=None (defect)
...
E   assert ([])
     +  where [] = PlacementScores(correct=[], wrong=[]).wrong
.../test_eval_harness_placement_metrics.py:158: assert ([])
  # test_paraphrased_absolute_wrong_scores_wrong
  # caption: "the man stands on the right." → claims=0 / accuracy=None (defect)
...
E   assert (None == 0.0)
     +  where None = PlacementScores(correct=[], wrong=[]).accuracy
  # test_above_below_structural_wrong
=========================== short test summary info ============================
FAILED ...::test_no_claim_is_not_scored
FAILED ...::test_fact_without_phrases_uses_relation_structure
FAILED ...::test_placement_accuracy_micro
FAILED ...::test_word_boundary_precision
FAILED ...::test_paraphrased_wrong_pair_order_scores_wrong
FAILED ...::test_paraphrased_correct_pair_order_scores_correct
FAILED ...::test_paraphrased_absolute_wrong_scores_wrong
FAILED ...::test_paraphrased_absolute_correct_scores_correct
FAILED ...::test_above_below_structural_wrong
FAILED ...::test_abstention_vs_zero_accuracy_are_distinct
FAILED ...::test_placement_scores_exposes_abstained_field
11 failed, 9 passed
```

Concrete pre-fix defect (ad-hoc probe on unfixed scorer):
```
caption="the man stands on the right." fact=man LEFT_OF woman phrases=["left of the woman"]
→ PlacementScores(correct=[], wrong=[]) accuracy=None claims=0
```

## GREEN-after (fixed code)

```
cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/test_eval_harness_placement_metrics.py -q
....................                                                     [100%]
20 passed in 0.20s
```

Key fixed case:
```
"Bob is to the left of Alice." + Alice LEFT_OF Bob
→ wrong=[('Alice left_of Bob', 'structural:Bob left Alice')] accuracy=0.0 claims=1

"the man stands on the right." + man LEFT_OF woman
→ wrong=[(..., 'structural-abs:the man on the right')] accuracy=0.0 claims=1
```

## DBG-11 causation by absence

Neutralizing `_structural_verdict` (return `None` always) on the fixed module:

| caption | with structural | without structural | restored |
|---|---|---|---|
| `Bob is to the left of Alice.` | wrong, acc=0.0 | wrong=[], acc=None, abstained | wrong, acc=0.0 |
| `the man stands on the right.` | wrong, acc=0.0 | wrong=[], acc=None, abstained | wrong, acc=0.0 |

Y (wrong score) disappears when X (structural path) is removed and returns when restored.

## Explicitly NOT done (and why)

- **Did not edit `report.py` / `cli.py` / wire `score_placement` into the report.** Out of scope (VLM6-R4-02 / sibling lane). Metric is now worth wiring; wiring is not this lane.
- **Did not edit `caption_metrics.py`, `describe_baseline.py`, `manifest.py`, `golden.json`.** Sibling-lane exclusive ownership.
- **Did not populate corpus `spatial_facts`.** Sibling lane; tests use constructed `SpatialFact` fixtures.
- **Did not run full service test suite.** Gate is the lane-local placement metrics file only.
- **Did not run `make lane-handoff` / `make lane-report`.** Worker contract forbids self-handoff; orchestrator owns that.
- **No LLM-judge / embedding matcher.** Precision-first deterministic matching only, per module policy.
- **Did not treat abstentions as accuracy denominator members.** Accuracy remains correct/claims; abstentions are a separate reported list (coverage is caller-side).

## Gate command

```
cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/test_eval_harness_placement_metrics.py -q
```
Result: **20 passed**.
