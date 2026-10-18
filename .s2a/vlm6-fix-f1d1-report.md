# VLM-6 S2A F1d-1 — persisted verdict encodes every exit condition (lane `vlm6-s2a-fix-gates`)

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Scope:** F1-6 only (assignment #527) — on-disk verdict must match non-zero exit  
**Builds on:** F1a–F1c-2 already in tree  
**Sandbox base:** history-stripped lane sandbox (feature content present)

## Verdict

**merge_ready** — every exit gate folded into persisted `verdict` before serialisation; `--rubric-gate skip` → `pass_ungated`; real-corpus RED/GREEN against `scene/tests/seed/golden.json` (37 entries); DBG-11 causation by absence proven; pytest **147 passed** (baseline 138 + 9 new tests).

## Defect (OBS-04)

`build_score_verdict` failed only on wrong-name rate, while `_cmd_score` exited non-zero for failed-items, truncation, manifest-mismatch, empty-rubric, must-right, schema-error, and wrong-name-floor-vacuity **after** the report was written. A fully caption-corrupted run persisted `verdict.verdict == "pass"` while the process exited 1. Slice 2 consumers reading the artifact (not the exit code) read a pass.

Addendum: `--rubric-gate skip` persisted bare `pass` alongside `must_right_failed_images > 0`.

## What changed

### `report.py`

- `ScoreVerdict.PASS_UNGATED = "pass_ungated"`.
- `build_score_verdict` now emits fail reasons for every non-schema exit class:
  - `failed-items`, `truncation`, `manifest-mismatch`, `empty-rubric` (must_right / easy_wrong),
  - `must-right failures` (enforce only), `wrong-name floor vacuity` (scored>0 ∧ evaluated=0),
  - existing `wrong_name_rate` floor.
- Clean `rubric_gate=skip` → `pass_ungated` (not bare `pass`).

### `cli.py` — `_cmd_score` order (F1d-1)

1. Score once via `score_run_record` (monkeypatchable for schema-drift tests).
2. Fold schema hard-key errors into `verdict` (`fail` + `score schema error: …` reasons).
3. Write JSON (load-bearing), then markdown (fallback if schema-degraded).
4. Exit with the existing class-unique gate messages (no gate fires against a pass artifact).

### Tests (`test_eval_harness_cli.py` + fixture fix in report tests)

- One on-disk assertion per exit gate against real golden (37) + discrimination control + `pass_ungated`.
- Existing skip test now asserts `pass_ungated`.
- Pass-path report fixture fixed (no failed items; non-empty rubric).

Heuristics: **OBS-04**, **TEST-15**, **DBG-11**.

## Real-corpus evidence

Corpus: `scene/tests/seed/golden.json` (37 entries).  
Probe: `uv run --extra dev python` calling `scripts.eval_harness.cli.main`.  
RED = production files restored to HEAD (pre-fix); GREEN = fixed files restored. Same record shapes both sides.

### Summary table

| case | RED exit | RED on-disk verdict | GREEN exit | GREEN on-disk verdict |
| --- | --- | --- | --- | --- |
| control (clean) | 0 | `pass` reasons=[] | 0 | `pass` reasons=[] |
| failed-items | non-zero | **`pass`** reasons=[] | non-zero | `fail` + `failed-items` |
| truncation (5/37) | non-zero | **`pass`** reasons=[] | non-zero | `fail` + `truncation` |
| manifest-mismatch | non-zero | **`pass`** reasons=[] | non-zero | `fail` + `manifest-mismatch` |
| empty-rubric must_right | non-zero | **`pass`** reasons=[] | non-zero | `fail` + `empty-rubric` |
| must-right failures | non-zero | **`pass`** reasons=[] | non-zero | `fail` + `must-right failures` |
| wrong-name floor | non-zero | `fail` (already) | non-zero | `fail` + `wrong_name_rate` |
| floor vacuity (rec-off) | non-zero | **`pass`** reasons=[] | non-zero | `fail` + `wrong-name floor vacuity` |
| schema error | non-zero | **`pass`** reasons=[] | non-zero | `fail` + `schema error` |
| `--rubric-gate skip` | 0 | **`pass`** (overclaim) | 0 | **`pass_ungated`** |

### RED-before (verbatim)

```
tmpdir=/tmp/vlm6-f1d1-red-2xc061te
corpus_entries=37

=== RED control ===
EXIT 0 (return=None)
verdict='pass' reasons=[] rubric_gate='enforce' must_right_failed=0

=== RED failed-items ===
EXIT non-zero: score failed-items gate: 1 item(s) not scored …
verdict='pass' reasons=[]  # LIE

=== RED truncation ===
EXIT non-zero: score truncation gate: … missing=32, extra=0 …
verdict='pass' reasons=[]  # LIE

=== RED manifest-mismatch ===
EXIT non-zero: score manifest-mismatch gate: … missing fetch-time manifest_sha256 …
verdict='pass' reasons=[]  # LIE

=== RED empty-rubric-mr ===
EXIT non-zero: score empty-rubric gate: must_right is vacuous corpus-wide …
verdict='pass' reasons=[]  # LIE

=== RED must-right ===
EXIT non-zero: score must-right failures gate: 34 image(s) failed Must-Right …
verdict='pass' reasons=[] must_right_failed=34  # LIE

=== RED wrong-name-floor ===
EXIT non-zero: score wrong-name floor gate: wrong_name_rate=1.0 exceeds floor=0.0 …
verdict='fail' reasons=['wrong_name_rate=1.0000 exceeds floor=0.0 (wrong_names=37, ignored=0, scored=37)']

=== RED vacuity ===
EXIT non-zero: score wrong-name floor vacuity gate: … evaluated_images=0 …
verdict='pass' reasons=[]  # LIE

=== RED rubric-skip ===
EXIT 0 (return=None)
verdict='pass' reasons=[] rubric_gate='skip' must_right_failed=34  # bare pass overclaim

=== RED schema ===
EXIT non-zero: score schema error: caption.must_right_failed_images missing or not a number
verdict='pass' reasons=[]  # LIE (pre-fix wrote unpatched build_reports first)
```

### GREEN-after (verbatim)

```
tmpdir=/tmp/vlm6-f1d1-green-jqr5_gz5
corpus_entries=37

=== GREEN control ===
EXIT 0 (return=None)
verdict='pass' reasons=[] rubric_gate='enforce' must_right_failed=0

=== GREEN failed-items ===
EXIT non-zero: score failed-items gate: 1 item(s) not scored …
verdict='fail' reasons=['failed-items: 1 item(s) not scored']

=== GREEN truncation ===
EXIT non-zero: score truncation gate: … missing=32, extra=0 …
verdict='fail' reasons=['truncation: media-id multiset differs (missing=32, extra=0)']

=== GREEN manifest-mismatch ===
EXIT non-zero: score manifest-mismatch gate: …
verdict='fail' reasons=['manifest-mismatch: run-record provenance missing fetch-time manifest_sha256']

=== GREEN empty-rubric-mr ===
EXIT non-zero: score empty-rubric gate: must_right is vacuous corpus-wide …
verdict='fail' reasons=['empty-rubric: must_right is vacuous corpus-wide']

=== GREEN must-right ===
EXIT non-zero: score must-right failures gate: 34 image(s) failed Must-Right …
verdict='fail' reasons=['must-right failures: 34 image(s) failed Must-Right'] must_right_failed=34

=== GREEN wrong-name-floor ===
EXIT non-zero: score wrong-name floor gate: wrong_name_rate=1.0 exceeds floor=0.0 …
verdict='fail' reasons=['wrong_name_rate=1.0000 exceeds floor=0.0 (wrong_names=37, ignored=0, scored=37)']

=== GREEN vacuity ===
EXIT non-zero: score wrong-name floor vacuity gate: … evaluated_images=0 …
verdict='fail' reasons=['wrong-name floor vacuity: evaluated_images=0']

=== GREEN rubric-skip ===
EXIT 0 (return=None)
verdict='pass_ungated' reasons=[] rubric_gate='skip' must_right_failed=34

=== GREEN schema ===
EXIT non-zero: score schema error: caption.must_right_failed_images missing or not a number
verdict='fail' reasons=['score schema error: caption.must_right_failed_images missing or not a number']
```

### DBG-11

Reverting `cli.py` + `report.py` to HEAD restored every false-green on-disk `pass` (RED table). Restoring the fix restored `fail`/`pass_ungated` (GREEN table). Causation by absence proven.

## Tests

```
cd apps/prototype-description-service && uv run --extra dev pytest \
  scene/tests/test_eval_harness_cli.py scene/tests/test_eval_harness_report.py -q
# 147 passed (baseline 138)
```

No tests weakened, skipped, or xfailed (sr-001).

## Out of scope / not touched

- `_check_score_determinism_cross_process`, `_check_face_determinism_cross_process`
- `score-face` path
- `docs/tasks/vlm/bakeoff-results/` anchors
- `scene/tests/seed/golden.json`

## Could not fix

Nothing in this assignment. All gates + control + `pass_ungated` have real-corpus RED/GREEN pairs.
