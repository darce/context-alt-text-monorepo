# VLM-6 Slice 2A — `vlm6-s2a-verdict` lane report

**Lane:** `vlm6-s2a-verdict`  
**Task:** `VLM-6`  
**Scope:** Emit scored verdict + fail `score` on wrong-name floor  
**Out of scope (per runtime guidance):** `--check-determinism` cross-process, corruption guards

## Verdict

**merge_ready** — lane-owned code + tests + this report committed.

## What changed

### 1. Machine-readable scored verdict (`report.py`)

- Added `ScoreVerdict` StrEnum (`pass` | `fail`) — no magic strings (sr-007).
- Added module constant `WRONG_NAME_RATE_FLOOR = 0.0` with WHY comment:
  attaching a hallucinated human name to a photograph is worse than placeholder
  text; zero tolerance.
- Added `face_wrong_name_rate()` and `build_score_verdict()`.
- Rate formula: `len(faces.identification.wrong_names) / counts.scored`
  (scored-image denominator; empty scored → 0.0).
- `score_run_record` / `build_reports` emit:

```json
{
  "verdict": "pass|fail",
  "reasons": ["..."],
  "wrong_name_rate": 1.0,
  "wrong_name_rate_floor": 0.0,
  "insertion_rate": ...,
  "mean_gated_score": ...,
  "must_right_failed_images": ...
}
```

Non-gating metrics are **reported only** (no exit thresholds this slice).

### 2. `score` CLI gate (`cli.py` `_cmd_score`)

- Prints `verdict=… wrong_name_rate=… wrong_name_rate_floor=…`.
- Keeps failed-items gate; renames message to `score failed-items gate: …`.
- Adds additive gate: `score wrong-name floor gate: wrong_name_rate=X exceeds floor=Y (see <report>)`.
- Gates name themselves distinctly.

## RED evidence (before fix)

Catastrophic run: wrong human name on **100%** of scored images (2/2).

```
scored=2/2 insertion_rate=0.0 wrong_names=2
RED_FALSE_GREEN: score exited 0 with wrong names on 100% of images
has_verdict False
wrong_names [['mock_images/alice.jpg', 'Bob Builder'], ['mock_images/bob.jpg', 'Alice Example']]
```

Pytest RED (imports / missing field):

```
FAILED test_cmd_score_exits_nonzero_when_wrong_name_rate_breaches_floor
  ImportError: cannot import name 'WRONG_NAME_RATE_FLOOR'
FAILED test_cmd_score_exits_zero_when_no_wrong_names_and_no_failures
  KeyError: 'verdict'
ERROR test_eval_harness_report.py collection
  ImportError: cannot import name 'WRONG_NAME_RATE_FLOOR'
```

## GREEN evidence (after fix)

Same catastrophic record:

```
scored=2/2 … wrong_names=2 verdict=fail wrong_name_rate=1.0 wrong_name_rate_floor=0.0
POST_FIX_RED: code='score wrong-name floor gate: wrong_name_rate=1.0 exceeds floor=0.0 (see …/run-wrong-report.json)'
verdict={
  'verdict': 'fail',
  'wrong_name_rate': 1.0,
  'wrong_name_rate_floor': 0.0,
  'reasons': ['wrong_name_rate=1.0000 exceeds floor=0.0 (wrong_names=2, scored=2)'],
  ...
}
```

## Tests

| Suite | Baseline (before) | After |
| --- | --- | --- |
| `test_eval_harness_cli.py` + `test_eval_harness_report.py` | **116 passed** | **121 passed** |

New tests (each can go red — TEST-15):

- `test_cmd_score_exits_nonzero_when_wrong_name_rate_breaches_floor`
- `test_cmd_score_exits_zero_when_no_wrong_names_and_no_failures`
- `test_score_run_record_emits_verdict_fail_when_wrong_names_present`
- `test_score_run_record_emits_verdict_pass_when_no_wrong_names`
- `test_build_reports_json_includes_verdict_block`

Audience CLI tests updated to expect wrong-name `SystemExit` after artifacts write
(fixture still uses Wrong Celebrity for redaction coverage — not a weakened gate).

## Verification command

```bash
cd apps/prototype-description-service && \
  uv run --extra dev pytest \
    scene/tests/test_eval_harness_cli.py \
    scene/tests/test_eval_harness_report.py -q
# 121 passed
```

## Explicit non-work

- Did **not** touch `--check-determinism` / `_check_face_determinism_cross_process`
  (separate serialized lane).
- Did **not** add exit thresholds for insertion_rate / mean_gated_score /
  must_right_failed_images.
- Did **not** relax report validators or touch fusion_runner / golden corpus.
