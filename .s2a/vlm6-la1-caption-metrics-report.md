# VLM-6 lane la1 — caption scoring must not be vacuous

**Lane:** `vlm6-la1-caption-metrics`  
**Task:** `VLM-6`  
**Finding:** `VLM6-R4-01` (high)  
**Owned paths only:** `caption_metrics.py`, `test_eval_harness_caption_metrics.py`

## Verdict

**merge_ready** — empty identity denominator is now `None` (not-scored), not vacuous `1.0`. Aggregate helper excludes N/A rows and reports `scored`/`excluded`. Permanent Twyman's-law control ships in the suite. Gate: **56 passed**.

## Semantics decision (owned by this lane)

An empty identity set (`len(inserted)+len(missing)==0`) while insertion is otherwise eligible means **the metric does not apply** → `gated_score = None`.

Not a sentinel float. Not `0.0` (that means hard-gate failure). Not `1.0` (that was the bug: a rate with no denominator reported as a win — UXR-07).

Hard-gate failures (must-right / policy / wrong-name) still return `0.0` even when the identity set is empty, so naming violations remain visible.

## Exact diff summary

### `caption_metrics.py`

1. **`CaptionScores.gated_score`**: `total == 0` → `return None` (was `return 1.0`). Docstring updated for VLM6-R4-01 + UXR-07.
2. **`GatedScoreAggregate`** dataclass: `mean: float | None`, `scored: int`, `excluded: int` (UXR-15 components).
3. **`aggregate_gated_scores(scores)`**: mean over non-`None` gated scores; `excluded = len(scores) - scored`. Does not invent denominators from convenience guesses (rg-015).
4. **`mean_gated_score(scores)`**: thin wrapper returning `.mean` for simple callers.

### `test_eval_harness_caption_metrics.py`

1. `test_empty_identity_set_gated_score_is_not_applicable` — EXP-06 control: garbage caption + empty rubric → `gated_score is None`.
2. `test_empty_identity_set_hard_gate_failures_still_zero` — wrong name with empty present set still zeros.
3. `test_aggregate_gated_scores_excludes_not_applicable_and_reports_count` — mean excludes N/A; `scored`/`excluded` honest.

## RED-before (actual output, pre-fix code)

Reproduced defect (reviewer case):

```
gated_score= 1.0
inserted= []
missing= []
insertion_eligible= True
```

Control tests against temporarily restored `return 1.0` (same pre-fix branch):

```
FAILED test_empty_identity_set_gated_score_is_not_applicable
E   assert 1.0 is None
E    +  where 1.0 = CaptionScores(... insertion_eligible=True ...).gated_score

FAILED test_aggregate_gated_scores_excludes_not_applicable_and_reports_count
E   assert 3 == 2
E    +  where 3 = GatedScoreAggregate(mean=0.6666666666666666, scored=3, excluded=1).scored
```

Causation (DBG-11): vacuous `1.0` return present → tests fail and mean inflates (empty-identity row counted as scored success). Restore `None` → failures disappear; all-N/A mean is `None`.

## GREEN-after (actual output)

```
post-fix gated_score= None
aggregate GatedScoreAggregate(mean=None, scored=0, excluded=2)

cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -q
56 passed in 0.55s
```

## Contract change for wiring lane (`report.py` / `cli.py` — NOT edited)

`report.py` already filters `gated_score is None` when building `gated_values` for `mean_gated_score`. After this change, clean empty-identity rows drop out of that mean (correct) instead of injecting `1.0`.

**Recommended follow-up for the wiring lane (do not invent fields):**

- Prefer `aggregate_gated_scores(caption_scores)` from `caption_metrics` instead of ad-hoc list comprehensions.
- Surface components on the report caption block, e.g.:
  - `mean_gated_score` ← `agg.mean`
  - `gated_score_scored` ← `agg.scored` (denominator)
  - `gated_score_excluded` ← `agg.excluded` (N/A count)
- MD summary should show mean **and** excluded count so operators can see how many corpus entries did not contribute (UXR-15).
- Per-image JSON already emits `"gated_score": null` for N/A once this property returns `None` — no shape break beyond value change from `1.0` → `null` on empty-identity rows.

## What this lane did NOT do (and why)

| Not done | Why |
| --- | --- |
| Edit `report.py` / `cli.py` | Explicitly out of scope; sibling wiring wave owns them |
| Edit `placement_metrics.py`, `describe_baseline.py`, `manifest.py`, `golden.json` | Sibling lanes |
| Change hard-gate zero semantics | Failures must still score 0.0 |
| Return a sentinel float for N/A | Honest answer is `None`; signature already `float \| None` |
| Weaken/skip any existing test | sr-001 |

## Gate command

```
cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/test_eval_harness_caption_metrics.py -q
# 56 passed
```
