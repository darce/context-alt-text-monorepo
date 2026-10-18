# VLM-6 S2A F1c-2 — wrong-name floor defeatable + vacuous (lane `vlm6-s2a-fix-gates`)

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Scope:** F1-5 only (assignment #525) — ignore-list defeat + recognition-disabled vacuity  
**Builds on:** F1a + F1b + F1b-2 + F1c-1 already in tree  
**Sandbox base:** history-stripped lane sandbox (feature content present)

## Verdict

**merge_ready** — both F1-5 defects fixed; real-corpus RED/GREEN against `scene/tests/seed/golden.json` (37 entries); DBG-11 causation by absence proven; pytest **138 passed** (baseline 136 from F1c-1 + 2 new tests).

## Defects

| ID | Defect | Pre-fix (real golden) | Post-fix |
| --- | --- | --- | --- |
| F1-5 (a) | `ignore-list.json` moves all wrong-name pairs to `ignored_wrong_names`; rate uses live only → floor silent | exit **0**, `rate=0.0`, `verdict=pass`, `ignored=37` | exit non-zero, `rate=1.0`, floor gate names `ignored_wrong_names=37` |
| F1-5 (b) | `recognition_enabled=false` corpus-wide → `identification_pr` excludes all; rate `0.0` regardless of wrong identities | exit **0**, `excluded=37`, `wrong_names=0` | exit non-zero, class-unique **wrong-name floor vacuity** token, `evaluated_images=0` |

## What changed

### `report.py`

- `_total_wrong_name_count`: live + ignored (F1-5 / OBS-04).
- `face_wrong_name_rate` / `build_score_verdict` use total count; reasons emit `ignored=N`.
- Presentation split unchanged: `wrong_names` (live) vs `ignored_wrong_names`.
- New field `faces.identification.evaluated_images` = scored images with `recognition_enabled` (identification denominator). Zero ⇒ floor vacuous (EVAL-19).

### `cli.py` — `_cmd_score` gates

After must-right failures, before the rate floor:

1. **`score wrong-name floor vacuity gate`** — `evaluated_images==0` (class-unique vs `empty-rubric`).
2. **`score wrong-name floor gate`** — rate (incl. ignored) exceeds floor; message includes `ignored_wrong_names=N`.

`_load_ignore_list` docstring notes presentation-only semantics.

### Tests

- `test_ignore_list_suppresses_triaged_wrong_names` (report): assert rate still 0.5 and verdict fail when ignore covers the sole wrong pair.
- `test_score_ignore_list_cannot_defeat_wrong_name_floor` (cli, real golden 37): ignore-list covering all wrongs → non-zero floor gate; assert absence of other gate tokens.
- `test_score_recognition_disabled_corpus_fails_wrong_name_floor_vacuity` (cli, real golden 37 with rec-off): vacuity token + `evaluated_images=0`; assert absence of empty-rubric / floor-breach tokens.

No tests weakened, skipped, or xfailed (sr-001).

## Real-corpus evidence (verbatim)

Corpus: `scene/tests/seed/golden.json` (37 entries).  
Invoked via `uv run --extra dev python` calling `scripts.eval_harness.cli.main`.

### RED-before (pre-fix code)

```
=== (a) wrong-name 100% + ignore-list covering all ===
…/run-ignore-defeat-report.md
scored=37/37 insertion_rate=1.0 wrong_names=0 verdict=pass wrong_name_rate=0.0 wrong_name_rate_floor=0.0 rubric_gate=enforce
EXIT 0 (false green)
live_wrong=0 ignored=37 rate=0.0 verdict=pass

=== (b) recognition_enabled=false corpus-wide + wrong identities ===
…/run-rec-off-report.md
scored=37/37 insertion_rate=None wrong_names=0 verdict=pass wrong_name_rate=0.0 wrong_name_rate_floor=0.0 rubric_gate=enforce
EXIT 0 (false green)
excluded=37 live_wrong=0 rate=0.0 verdict=pass must_right_failed=0
```

### GREEN-after (post-fix)

```
=== (a) GREEN: wrong-name 100% + ignore-list covering all ===
…/run-ignore-defeat-report.md
scored=37/37 insertion_rate=1.0 wrong_names=0 verdict=fail wrong_name_rate=1.0 wrong_name_rate_floor=0.0 rubric_gate=enforce
EXIT non-zero: score wrong-name floor gate: wrong_name_rate=1.0 exceeds floor=0.0 (ignored_wrong_names=37; see …/run-ignore-defeat-report.json)
live=0 ignored=37 rate=1.0 verdict=fail

=== (b) GREEN: recognition_enabled=false corpus-wide ===
…/run-rec-off-report.md
scored=37/37 insertion_rate=None wrong_names=0 verdict=pass wrong_name_rate=0.0 wrong_name_rate_floor=0.0 rubric_gate=enforce
EXIT non-zero: score wrong-name floor vacuity gate: identification denominator is empty (evaluated_images=0, excluded_images=37); wrong-name floor is vacuous — no image contributed to identification (recognition_enabled false corpus-wide or none scored; see …/run-rec-off-report.json)
evaluated=0 excluded=37 rate=0.0

=== CLEAN baseline still exit 0 ===
scored=37/37 insertion_rate=1.0 wrong_names=0 verdict=pass wrong_name_rate=0.0 …
EXIT 0
```

### DBG-11 causation by absence

| removal | effect |
| --- | --- |
| `_total_wrong_name_count` → live-only | (a) EXIT **0** false green restored |
| vacuity gate bypassed (`evaluated_images` forced non-zero + rate 0) | (b) EXIT **0** false green restored |

```
=== DBG-11 (a): face_wrong_name_rate live-only restores exit 0? ===
scored=37/37 … wrong_names=0 verdict=pass wrong_name_rate=0.0 …
EXIT 0 (false green restored by removing total-wrong count)

=== DBG-11 (b): skip vacuity gate restores exit 0? ===
scored=37/37 … wrong_names=0 verdict=pass wrong_name_rate=0.0 …
EXIT 0 (false green restored by removing vacuity / zeroing rate)
```

| corruption | RED-before | GREEN-after |
| --- | --- | --- |
| ignore-list covers 37/37 wrong names | **0** | non-zero, floor gate + `ignored_wrong_names=37` |
| recognition_enabled=false × 37 + wrong ids | **0** | non-zero, `wrong-name floor vacuity` + `evaluated_images=0` |

## Suite counts

| Suite | Baseline (F1c-1) | After F1c-2 |
| --- | --- | --- |
| `test_eval_harness_cli.py` + `test_eval_harness_report.py` | **136 passed** | **138 passed** |

(+2 new CLI tests; report ignore-list test extended, not replaced). No skips/xfails.

## Out of scope / not fixed

- Empty-rubric, truncation, schema hard-keys, verdict-vs-exit contradiction, audience tests, describe_baseline — other F1 items / sibling lanes.

## Verification command

```bash
cd apps/prototype-description-service && \
  uv run --extra dev pytest \
    scene/tests/test_eval_harness_cli.py \
    scene/tests/test_eval_harness_report.py -q
```

Result: **138 passed**, 7 warnings (pre-existing RubricEmptyWarning on face-bakeoff fixtures).
