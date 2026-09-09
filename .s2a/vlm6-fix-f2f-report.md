# VLM-6 S2A F2f — move `--check-determinism` off `_common` so fetch rejects it (C-06)

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Branch:** `feature/vlm-6` (sandbox: history-stripped `master`)  
**Scope:** `scripts/eval_harness/cli.py` + `scene/tests/test_eval_harness_cli.py` only.  
**Did not touch:** `report.py`, `test_eval_harness_pipeline.py`, `describe_baseline.py`, bakeoff anchors, `golden.json`.  
**B-11 (`describe_baseline` secrets path):** out of scope for this one-item lane — not edited.

## Verdict

**merge_ready** for F2f. `--check-determinism` removed from `_common()`; declared only on `score`, `run`, and (pre-existing) `score-face`. `fetch --check-determinism` is a loud argparse reject (zero cost). `run` keeps the flag with **per-leg certification + pre-spawn cost announcement**.

## Defect

One flag, two opposite wrongs (C-06):

1. **`fetch` silent no-op** — `_common()` applied the flag to `fetch`/`score`/`run`, but only `score` read it. Operators got a paid green that certified nothing (OBS-04).
2. **`run` silent multiplier** — `_cmd_run` loops `_cmd_score` per provider leg with no cost signal; 3 legs × 3 seeds = 9 fresh interpreters, each ~1.65 s import tax, no warning.

## Fix

1. **Remove flag from `_common()`.** Add `_check_determinism_flag()` applied to `score_p` and `run_p` only. `score-face` keeps its existing separate declaration.
2. **`run` semantics — per-leg check + announce cost (chosen).**  
   - **Why per-leg, not once:** each matrix leg produces an independent run-record; a single check would leave other legs uncertified under a flag that claims certification.  
   - **Announcement** prints `legs × seeds` (and `× 2 audiences` when `--audience public`) **before** `_cmd_fetch` / first child spawn.
3. **Import-cost fix not attempted** (out of scope). Recommendation only: child script path currently imports `scripts.eval_harness.cli`, which transitively pulls `face_bakeoff` → `cv2`/`onnxruntime`. A thin child entry (import only `report` + score helpers) would cut the ~1.65 s/child tax without changing guard semantics — separate lane.

Optional audience-default tidy already present on branch (`default=Audience.LOCAL.value`); not reworked.

## Heuristics satisfied

| ID | How |
|---|---|
| **OBS-04** | `fetch` rejection names `--check-determinism`; `run` prints multiplier before wall clock pays |
| **TEST-15** | Discrimination controls: `score` + `score-face` still drive shipped guard; rejection-only battery would be insufficient |
| **DBG-11** | Revert only `cli.py` → new tests red; restore → green |
| **sr-001** | No test weakened/skipped/xfailed; no flag re-added to `_common` to keep a fetch test green |

## Tests (sr-001)

| Test | Intent |
|---|---|
| `test_cli_fetch_rejects_check_determinism` | **new** C-06 / OBS-04 fetch free-reject |
| `test_cli_run_check_determinism_announces_multiplier` | **new** pre-fetch `3 legs × 3 seeds = 9` announcement |
| `test_cli_run_accepts_check_determinism_at_parse` | **new** run still declares the flag (wiring control) |
| `test_cli_score_check_determinism_runs_cross_process_guard` | **existing** TEST-15 score control |
| `test_cli_score_face_check_determinism_runs_shipped_guard` | **existing** TEST-15 score-face control |

## Evidence

### Gate (verbatim)

```text
$ cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/ -k eval_harness -q
686 passed, 4 skipped, 408 deselected, 9 warnings in 65.30s (0:01:05)
```

Baseline (brief): **684 passed, 3 skipped, 0 failed** (linux host: one extra platform skip).  
Post-F2f: **686 passed, 4 skipped, 0 failed** — passed count greater; zero failed.

F2f subset (GREEN):

```text
$ uv run --extra dev pytest scene/tests/test_eval_harness_cli.py \
    -k 'fetch_rejects_check_determinism or run_check_determinism_announces or run_accepts_check_determinism or score_check_determinism_runs_cross_process or score_face_check_determinism_runs_shipped' -q
5 passed, 90 deselected, 2 warnings in 9.25s
```

### Pre-change: `fetch --check-determinism` accepted (silent no-op path)

```text
$ uv run --extra dev python -c "from scripts.eval_harness.cli import main
try:
    main(['fetch', '--check-determinism'])
except SystemExit as e:
    print('EXIT', repr(e.code))
"
EXIT 'live subcommand requires ACX_EVAL_LIVE=1 (safety gate; see README)'
```

Argparse accepted the flag; execution reached `_cmd_fetch` live-env gate. No determinism certification. (With `ACX_EVAL_LIVE=1` this would make paid remote calls and still certify nothing.)

### Post-change: `fetch --check-determinism` rejected (OBS-04)

```text
usage: eval_harness [-h]
                    {fetch,score,run,seed-roster,seed-scenes,face-bakeoff,score-face}
                    ...
eval_harness: error: unrecognized arguments: --check-determinism
EXIT_CODE 2
```

### `run` decision demonstrated

```text
run --check-determinism: per-leg certification — 3 legs × 3 seeds = 9 fresh interpreter(s) before scoring completes
run --check-determinism: per-leg certification — 3 legs × 3 seeds × 2 audiences = 18 fresh interpreter(s) before scoring completes
```

Announcement fires before `_cmd_fetch` (asserted in `test_cli_run_check_determinism_announces_multiplier` by capturing stdout at fetch entry).

### DBG-11 — revert only `cli.py`

```text
$ # reverse F2f cli wiring; tests still post-F2f
$ uv run --extra dev pytest scene/tests/test_eval_harness_cli.py \
    -k 'fetch_rejects_check_determinism or run_check_determinism_announces or run_accepts_check_determinism' -q --tb=line
FAILED test_cli_fetch_rejects_check_determinism
  assert 'live subcommand requires ACX_EVAL_LIVE=1 ...' == 2
FAILED test_cli_run_check_determinism_announces_multiplier
  assert 'run --check-determinism' in ''
1 passed, 2 failed, 92 deselected
```

Restore `cli.py` → 5/5 subset green; full gate 686 passed.

### TEST-15 discrimination controls

- `score --check-determinism` still runs shipped cross-process guard (`test_cli_score_check_determinism_runs_cross_process_guard`).
- `score-face --check-determinism` still runs shipped guard (`test_cli_score_face_check_determinism_runs_shipped_guard`).
- `run --check-determinism` still parses and dispatches (`test_cli_run_accepts_check_determinism_at_parse`).

## Not done / recommendations

- **Child import cost (~1.65 s):** out of scope. Prefer a thin determinism child that does not import full `cli` / `face_bakeoff` / `cv2` / `onnxruntime`.
- **B-11 describe_baseline secrets:** residual finding; not this item’s scope.
- **Audience getattr tidy:** already has `default=Audience.LOCAL.value`; left alone.

## Commits

Lane commits land `cli.py`, `test_eval_harness_cli.py`, and this report under `.s2a/vlm6-fix-f2f-report.md`.
