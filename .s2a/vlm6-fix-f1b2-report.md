# VLM-6 S2A F1b-2 — declare rubric gate mode (lane `vlm6-s2a-fix-gates`)

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Scope:** F1-12 only (assignment #519) — replace F1-11 conjunction with declared run mode  
**Builds on:** F1a (`e7a9028b`) + F1b F1-3 half (`b1fd67df`) — not revisited  
**Sandbox base:** history-stripped lane sandbox (feature content present)

## Verdict

**merge_ready** — simple must-right predicate restored; `--rubric-gate {enforce,skip}` recorded in artifact; real-corpus four-row evidence against `scene/tests/seed/golden.json` (37 entries); pytest **133 passed** (baseline 132 + 1 new flag-recording test; one test rewritten not net-deleted).

## Defect

| ID | Defect | Pre-fix (real golden / anchor) | Post-fix |
| --- | --- | --- | --- |
| F1-12 | F1-11 conjunction (`rate==1.0 ∧ mean_gated==0.0`) false-green on plain garbage and empty captions; mean_gated measures easy_wrong trap avoidance, not caption quality | garbage / empty captions: exit **0**; seeded unmodified: exit **0** | default: any must_right failure → non-zero; `--rubric-gate skip` → 0 (declared exemption) |

## Why content-based discrimination was rejected

Measured on the frozen S0 seeded anchor vs golden entries: seeded captions have **zero content-word overlap with `base_caption` on 36/37 images**. The stub is informationally indistinguishable from corruption. On golden.json both plain garbage and seeded yield `mean_gated_score=0.0811` (3 no-must_right entries score gated 1.0 regardless of caption). Any threshold/overlap/conjunction either admits garbage or rejects the shakedown anchor.

Exemption is therefore **by operator declaration** (`--rubric-gate skip`), never by adapter/model_id inference (rg-009). The seeded report already discloses: *"produced by the model-free `seeded` stub adapter — harness-shakedown numbers, NOT a caption-model baseline."*

## What changed

### `cli.py`

- Deleted `CAPTION_COLLAPSE_MEAN_GATED_SCORE` and the F1-11 conjunction.
- Restored simple gate: `must_right_failed_images > 0` → exit non-zero with the existing class-unique message under `--rubric-gate enforce` (default).
- Added `--rubric-gate {enforce,skip}` on `score` and `run`. Under `skip`, **only** the must-right failures gate is bypassed.
- Printed `rubric_gate=…` on stdout summary line.
- Passed `rubric_gate` into `build_reports` / `score_run_record` so the written artifact is self-describing.

### `report.py`

- `build_score_verdict` / `score_run_record` / `build_reports` accept `rubric_gate` (default `"enforce"`).
- Stamp `verdict.rubric_gate` in the JSON report; surface `rubric_gate: \`…\`` in markdown.

### Tests (`test_eval_harness_cli.py`)

- Corruption-#1 guard: simple predicate; fixture is **not** all-rubric (one empty `must_right` + empty `present_identities` entry, golden 34/37 shape); plain garbage `"xxxxx yyyyy zzzzz qqqqq"` must fail.
- Replaced `test_score_guard_seeded_name_misses_do_not_fire_must_right_gate` with `test_score_guard_rubric_gate_skip_bypasses_must_right_gate` (default non-zero; skip → 0 + artifact records skip).
- Added `test_score_report_records_rubric_gate_flag` (default enforce stamped in report/MD).

Did **not** touch determinism helpers, score-face path, bakeoff anchors, or `golden.json`. F1-3 sha-drift work left intact.

No tests weakened, skipped, or xfailed (sr-001).

## Real-corpus evidence (verbatim)

Corpus: `scene/tests/seed/golden.json` (37 entries; must_right defined 34; easy_wrong 37).  
Probe records built from `docs/tasks/vlm/bakeoff-results/S0-determinism-anchor-run-20260714.json` (probe copy only): bare-string `identities` normalised to `{"name": s}`; committed anchor **not** rewritten.  
Invoked via `uv run --extra dev python` calling `scripts.eval_harness.cli.main`.

| record | flag | required exit | observed |
| --- | --- | --- | --- |
| unmodified seeded anchor | *(default)* | **non-zero**, must-right failures gate | non-zero ✅ |
| unmodified seeded anchor | `--rubric-gate skip` | **0** | 0 ✅ |
| every caption text = plain garbage | *(default)* | **non-zero** | non-zero ✅ |
| every caption text = plain garbage | `--rubric-gate skip` | 0 (documented, expected) | 0 ✅ |

### 1) unmodified seeded anchor — default enforce → non-zero

```
=== unmod-default flag=(default) ===
cmd: score --manifest scene/tests/seed/golden.json --run-record /tmp/vlm6-f1b2-24ifutt7/unmod-default-run.json
/tmp/vlm6-f1b2-24ifutt7/unmod-default-run-report.md
scored=37/37 insertion_rate=0.0 wrong_names=0 verdict=pass wrong_name_rate=0.0 wrong_name_rate_floor=0.0 rubric_gate=enforce
EXIT non-zero: score must-right failures gate: 34 image(s) failed Must-Right caption hard-gate (caption corruption / missing required names; see /tmp/vlm6-f1b2-24ifutt7/unmod-default-run-report.json)
fields: must_right_failed=34 must_right_defined=34 mean_gated=0.0811 rubric_gate=enforce verdict=pass
```

### 2) unmodified seeded anchor — `--rubric-gate skip` → 0

```
=== unmod-skip flag=skip ===
cmd: score --manifest scene/tests/seed/golden.json --run-record /tmp/vlm6-f1b2-xtulpw4g/unmod-skip-run.json --rubric-gate skip
/tmp/vlm6-f1b2-xtulpw4g/unmod-skip-run-report.md
scored=37/37 insertion_rate=0.0 wrong_names=0 verdict=pass wrong_name_rate=0.0 wrong_name_rate_floor=0.0 rubric_gate=skip
EXIT 0 (return=None)
fields: must_right_failed=34 must_right_defined=34 mean_gated=0.0811 rubric_gate=skip verdict=pass
```

### 3) every caption = plain garbage — default enforce → non-zero

Plain garbage: every `alt_text_draft` / `named_draft` / `generic_draft` = `"xxxxx yyyyy zzzzz qqqqq"`.  
Note: `mean_gated_score=0.0811` — **same as seeded** — confirming F1-11's conjunction could not discriminate.

```
=== garbage-default flag=(default) ===
cmd: score --manifest scene/tests/seed/golden.json --run-record /tmp/vlm6-f1b2-50z16dzv/garbage-default-run.json
/tmp/vlm6-f1b2-50z16dzv/garbage-default-run-report.md
scored=37/37 insertion_rate=0.0 wrong_names=0 verdict=pass wrong_name_rate=0.0 wrong_name_rate_floor=0.0 rubric_gate=enforce
EXIT non-zero: score must-right failures gate: 34 image(s) failed Must-Right caption hard-gate (caption corruption / missing required names; see /tmp/vlm6-f1b2-50z16dzv/garbage-default-run-report.json)
fields: must_right_failed=34 must_right_defined=34 mean_gated=0.0811 rubric_gate=enforce verdict=pass
```

### 4) every caption = plain garbage — `--rubric-gate skip` → 0 (expected)

```
=== garbage-skip flag=skip ===
cmd: score --manifest scene/tests/seed/golden.json --run-record /tmp/vlm6-f1b2-50vk30nu/garbage-skip-run.json --rubric-gate skip
/tmp/vlm6-f1b2-50vk30nu/garbage-skip-run-report.md
scored=37/37 insertion_rate=0.0 wrong_names=0 verdict=pass wrong_name_rate=0.0 wrong_name_rate_floor=0.0 rubric_gate=skip
EXIT 0 (return=None)
fields: must_right_failed=34 must_right_defined=34 mean_gated=0.0811 rubric_gate=skip verdict=pass
```

## Suite counts

| Suite | Baseline (F1b) | After F1b-2 |
| --- | --- | --- |
| `test_eval_harness_cli.py` + `test_eval_harness_report.py` | **132 passed** | **133 passed** |

(+1: `test_score_report_records_rubric_gate_flag`; seeded-shape test rewritten to skip-flag test). No skips/xfails.

## Out of scope / not fixed

- **Verdict vs exit-code contradiction:** under enforce, exit is non-zero on must_right failures but `verdict.verdict` remains `pass` (only wrong-name floor flips the machine verdict today). Artifact now carries `rubric_gate` + `must_right_failed_images` so consumers can interpret correctly; full verdict/exit alignment is a separate epic defect, not this assignment.
- F1-3 sha-drift, empty-rubric, truncation, wrong-name floor, audience tests, describe_baseline — not in this slice.

## Verification command

```bash
cd apps/prototype-description-service && \
  uv run --extra dev pytest \
    scene/tests/test_eval_harness_cli.py \
    scene/tests/test_eval_harness_report.py -q
# 133 passed
```
