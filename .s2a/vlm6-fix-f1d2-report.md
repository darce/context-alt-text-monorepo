# VLM-6 S2A F1d-2 — rounding floor + scored-set rubric denominator (lane `vlm6-s2a-fix-gates`)

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Scope:** F1-7 + F1-8 only (assignment #528)  
**Builds on:** F1a–F1d-1 already in tree  
**Sandbox base:** history-stripped lane sandbox (feature content present)

## Verdict

**merge_ready** — F1-7 count-based floor when `floor==0.0` (never gate on `round(rate,4)`); F1-8 `must_right`/`easy_wrong` defined counts over scored set only; real-corpus + scaled RED/GREEN; discrimination control; pytest **152 passed** (baseline 147 + 5 new tests).

## Defects

| ID | Defect | Pre-fix | Post-fix |
| --- | --- | --- | --- |
| F1-7 | Floor compared (or effectively defeated by) `round(rate, 4)`; 1 wrong among ≥20001 → rate serialises as `0.0`, `0.0 > 0.0` is false | scaled: exit **0**, `verdict=pass`, `wrong_name_rate=0.0` | exit non-zero, `verdict=fail`, `wrong_names=1` in reasons (display rate may still be `0.0`) |
| F1-8 | `must_right_defined_images` counted over full score-time manifest, not scored items | 3 non-`must_right` scored vs golden: `defined=34`, no empty-rubric reason | `defined=0`, empty-rubric reason present (EVAL-19) |

Heuristics: **TEST-15**, **DBG-11**, **EVAL-19**.

## What changed

### `report.py`

- **F1-7:** `build_score_verdict` gates wrong-name floor on **count** when `WRONG_NAME_RATE_FLOOR == 0.0`; otherwise on unrounded rate. `wrong_name_rate` remains display-rounded only.
- **F1-8:** `must_right_defined_images` / `easy_wrong_defined_images` count only among successfully scored `per_image` rows (scored ∩ score-time entries), not all `manifest_entries`.

### `cli.py`

- **F1-7:** `_cmd_score` wrong-name floor uses `_total_wrong_name_count` when floor is `0.0`; never compares the rounded serialised rate for the breach decision. Exit message still prints the display rate for operators.

### Tests

- `test_score_one_wrong_name_real_golden_exits_nonzero` — real golden 1/37 (TEST-15 non-scaled).
- `test_score_rounding_cannot_hide_one_wrong_name_scaled` — **synthetic scaled** 1/20001 (explicitly flagged; 20001 real images do not exist).
- `test_score_empty_rubric_keys_on_scored_set_not_manifest` — real golden, score only 3 non-`must_right` media_ids → `defined=0` + empty-rubric in reasons.
- `test_score_f1d2_control_clean_real_golden_still_passes` — discrimination control.
- Report unit: `test_rubric_defined_images_count_scored_set_not_full_manifest`.

No tests weakened, skipped, or xfailed (sr-001).

## Real-corpus / scaled evidence

Corpus: `scene/tests/seed/golden.json` (37 entries, 34 with `must_right`).  
Probe: `uv run --extra dev python` calling `scripts.eval_harness.cli.main`.  
RED = pre-fix gate semantics (manifest-wide rubric count + rounded-rate floor) via targeted monkeypatch; GREEN = current tree. Same records both sides.

### Summary table

| case | RED exit | RED artifact | GREEN exit | GREEN artifact |
| --- | --- | --- | --- | --- |
| control (clean 37) | 0 | `pass` reasons=[] defined=34 | 0 | `pass` reasons=[] defined=34 |
| one-wrong real (1/37) | non-zero | `fail` rate=0.027 wrong_names=1 | non-zero | `fail` rate=0.027 wrong_names=1 |
| scored-no-mr (3/37 non-mr) | non-zero **truncation only** | defined=**34**, reasons=`[truncation]` (no empty-rubric) | non-zero truncation (exit token) | defined=**0**, reasons=`[truncation, empty-rubric: must_right…]` |
| scaled 1/20001 (**synthetic**) | **0** | `pass` rate=0.0 reasons=[] | non-zero floor | `fail` rate=0.0 reasons include `wrong_names=1` |

**F1-8 honesty note:** With the F1-2 truncation gate already in tree, a partial run-record of only the 3 non-`must_right` media_ids against full golden exits non-zero **both** pre and post (truncation). Pre-fix still **silences empty-rubric** (`defined=34`). Post-fix adds the empty-rubric reason and `defined=0`. The F1-8 defect is the wrong denominator / missing vacuity reason, not the truncation exit alone. A pure exit-0 false-green for F1-8 would require truncation to be absent; that co-gate is out of this item’s ownership to remove.

**F1-7 scaled honesty note:** 20001-image fixture is **synthetic** (assignment permits this one scaled case). Real-corpus 1-wrong-name (1/37) exits non-zero both pre and post (rate does not round to 0.0); the scaled case is the only RED exit-0 for rounding.

### GREEN-after (verbatim)

```
corpus_entries=37 must_right=34
tmpdir_green=/tmp/vlm6-f1d2-green-3vyr9642

=== control ===
EXIT 0 (return=None)
verdict='pass' reasons=[] wrong_name_rate=0.0 must_right_defined=34 scored=37

=== one-wrong-real ===
EXIT non-zero: score wrong-name floor gate: wrong_name_rate=0.027 exceeds floor=0.0 (ignored_wrong_names=0; see …/one-wrong-real-report.json)
verdict='fail' reasons=['wrong_name_rate=0.0270 exceeds floor=0.0 (wrong_names=1, ignored=0, scored=37)'] wrong_name_rate=0.027 must_right_defined=34 scored=37

=== scored-no-mr ===
EXIT non-zero: score truncation gate: … missing=34, extra=0 …
verdict='fail' reasons=['truncation: media-id multiset differs (missing=34, extra=0)', 'empty-rubric: must_right is vacuous corpus-wide'] wrong_name_rate=0.0 must_right_defined=0 scored=3

=== scaled-1-of-20001 ===
EXIT non-zero: score wrong-name floor gate: wrong_name_rate=0.0 exceeds floor=0.0 (ignored_wrong_names=0; see …/scaled-1-of-20001-report.json)
verdict='fail' reasons=['wrong_name_rate=0.0000 exceeds floor=0.0 (wrong_names=1, ignored=0, scored=20001)'] wrong_name_rate=0.0 must_right_defined=20001 scored=20001
```

### RED-before (verbatim)

```
tmpdir_red=/tmp/vlm6-f1d2-red-45sv2npz

=== control ===
EXIT 0 (return=None)
verdict='pass' reasons=[] wrong_name_rate=0.0 must_right_defined=34 scored=37

=== one-wrong-real ===
EXIT non-zero: score wrong-name floor gate: wrong_name_rate=0.027 exceeds floor=0.0 …
verdict='fail' reasons=['wrong_name_rate=0.0270 exceeds floor=0.0 (wrong_names=1, ignored=0, scored=37)']

=== scored-no-mr ===
EXIT non-zero: score truncation gate: … missing=34, extra=0 …
verdict='fail' reasons=['truncation: media-id multiset differs (missing=34, extra=0)'] wrong_name_rate=0.0 must_right_defined=34 scored=3
# no empty-rubric reason — F1-8 false quiet on vacuity

=== scaled-1-of-20001 ===
EXIT 0 (return=None)
verdict='pass' reasons=[] wrong_name_rate=0.0 must_right_defined=20001 scored=20001
# F1-7 false green: rounded rate 0.0 cannot exceed floor 0.0
```

### DBG-11

Reverting only the F1-7/F1-8 semantics (manifest-wide defined counts + rounded-rate floor decision) restored:

- scaled → EXIT **0** / `pass`
- scored-no-mr → `defined=34` and empty-rubric absent from reasons  

Restoring the fix restored GREEN. Causation by absence proven.

## Tests

```
cd apps/prototype-description-service && uv run --extra dev pytest \
  scene/tests/test_eval_harness_cli.py scene/tests/test_eval_harness_report.py -q
# 152 passed, 7 warnings (baseline 147)
```

## Out of scope / not touched

- `_check_score_determinism_cross_process`, `_check_face_determinism_cross_process`
- `score-face` path
- `docs/tasks/vlm/bakeoff-results/` anchors
- `scene/tests/seed/golden.json`
- F1d-1 (already merge_ready in `.s2a/vlm6-fix-f1d1-report.md`)

## Could not fix

Nothing blocking merge for F1-7/F1-8. F1-8 pre-fix exit is non-zero due to co-firing truncation (documented above); empty-rubric silence is the F1-8 signal and is fixed.
