# VLM-6 S2A F2a — one determinism substrate + error taxonomy (C-08, C-03)

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Scope:** F2a only (assignment #532) — `scripts/eval_harness/cli.py` + `scene/tests/test_eval_harness_cli.py`  
**Did not touch:** `report.py`, `test_eval_harness_pipeline.py`, `describe_baseline.py`, bakeoff anchors, `golden.json`.

## Verdict

**merge_ready** for F2a (C-08 + C-03). Shared substrate + ERROR/FAILED taxonomy + timeout + mismatch artifacts + three new branch tests. Full `eval_harness` selection: **667 passed, 4 skipped, 0 failed**.

## Defects

### C-08 — caption guard was a verbatim fork of the face guard

`_check_score_determinism_cross_process` and `_check_face_determinism_cross_process` duplicated seed tuple, env handling, subprocess shape (including no-op `cwd=`), `---MD---` framing, and operator strings. Messages carried **no gate identity**; every remaining fix had to be applied twice.

### C-03 — three unrelated causes collapsed into one verdict

Child `rc != 0`, malformed stdout, and genuine byte mismatch all printed `determinism check FAILED`. No timeout; mismatch discarded which document differed, wrote no artifact, dropped stderr.

## Fix

### C-08

Extracted `_run_determinism_children(child_script, argv, *, label, base_json, base_md, artifact_dir)` holding seed tuple `("0","1","42")`, env/`PYTHONHASHSEED`, `subprocess.run` (no-op `cwd=` preserved for later import-root lane), framing, timeout, and error taxonomy. Both guards call it with distinct labels:

- caption → `label="score"`
- face → `label="score-face"`

Label is interpolated into **every** message.

### C-03 (all four parts)

1. **OBS-04 taxonomy:** infra → `determinism check ERROR [label]: ...`; regression → `determinism check FAILED [label]: ...`
2. **`timeout=`** (`_DETERMINISM_CHILD_TIMEOUT_S = 120`); `TimeoutExpired` → ERROR class
3. **Mismatch:** names `document=JSON` / `MD` / `JSON+MD`, writes side-by-side artifact beside the run record (`determinism-mismatch-{label}-seed{N}.diff.txt`), references path + stderr in exit message
4. **Tests:** rc!=0 and malformed-output branches (plus label-identity battery)

## Evidence

### THREE CLASSES + CONTROL on caption gate (TEST-15)

```text
$ cd apps/prototype-description-service && uv run --extra dev python3  # (inline demo)
=== THREE CLASSES + CONTROL (caption gate) ===
determinism check passed [score]: cross-process re-score is bit-identical under varied PYTHONHASHSEED
CONTROL clean: PASS (no SystemExit) — discrimination control
ERROR rc!=0: determinism check ERROR [score]: subprocess seed=0 rc=1: ModuleNotFoundError: No module named 'scripts.eval_harness'
ERROR malformed: determinism check ERROR [score]: malformed subprocess output seed=0; stderr='x'
FAILED mismatch: determinism check FAILED [score]: cross-process re-score differs under PYTHONHASHSEED=0 (document=JSON+MD; artifact=.../determinism-mismatch-score-seed0.diff.txt; stderr='')
```

Distinct operator strings:

| Class | Token | Remedy class |
| --- | --- | --- |
| Control | `determinism check passed [score]` | — |
| Child rc≠0 | `determinism check ERROR [score]: ... rc=` | operator / environment |
| Malformed stdout | `determinism check ERROR [score]: malformed` | operator / framing |
| Byte mismatch | `determinism check FAILED [score]: cross-process ... document=` | build regression |

### Gate identity (C-08)

Same failure forced on both labels:

```text
=== GATE IDENTITY (same failure, different labels) ===
  caption: determinism check ERROR [score]: subprocess seed=0 rc=1: boom
  face:    determinism check ERROR [score-face]: subprocess seed=0 rc=1: boom
```

Messages differ only by label; CI grep can disambiguate.

### Pytest battery (exact)

```text
$ cd apps/prototype-description-service && uv run --extra dev pytest \
  scene/tests/test_eval_harness_cli.py::test_cli_score_check_determinism_runs_cross_process_guard \
  scene/tests/test_eval_harness_cli.py::test_cli_score_determinism_guard_detects_mutated_persisted_anchor \
  scene/tests/test_eval_harness_cli.py::test_cli_score_determinism_guard_errors_on_child_nonzero_rc \
  scene/tests/test_eval_harness_cli.py::test_cli_score_determinism_guard_errors_on_malformed_output \
  scene/tests/test_eval_harness_cli.py::test_cli_determinism_guard_labels_distinguish_score_and_face \
  -v --tb=short

5 passed in 5.79s
```

### Full self-verify gate

```text
$ cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/ -k eval_harness -q
667 passed, 4 skipped, 408 deselected, 9 warnings in 31.55s
```

Baseline at brief `13db33ba`: **665 passed, 3 skipped, 0 failed** (linux host note: 664 passed, 4 skipped).  
Post-fix: **0 failed**, passed **667** (greater than baseline — C-03 adds branch tests: rc≠0, malformed, label identity).

### DBG-11 — causation by absence

Pre-fix all three branches shared one string prefix:

```text
determinism check FAILED: subprocess seed=...
determinism check FAILED: malformed subprocess output seed=...
determinism check FAILED: cross-process re-score differs under PYTHONHASHSEED=...
```

Post-fix: ERROR vs FAILED are disjoint. Reverting `_run_determinism_children` to the inlined pre-fix loops restores the collapsed `FAILED`-only taxonomy (both guards re-diverge).

## Heuristics cited

- **OBS-04** — ERROR vs FAILED selects the remedy (operator env vs build regression)
- **TEST-15** — three red classes + clean control that still passes
- **DBG-11** — pre-fix collapsed strings documented; post-fix strings are class-unique
- **sr-001** — no existing test weakened/skipped/xfailed; mutation + face mismatch tests still assert `FAILED` + `cross-process`

## Explicit non-work

- Did **not** change import-root / `cwd=` (later lane)
- Did **not** touch report.py / pipeline contract tests / describe_baseline / anchors / golden.json
- Did **not** re-open F1d-* (already green in this tree)

## New tests

- `test_cli_score_determinism_guard_errors_on_child_nonzero_rc`
- `test_cli_score_determinism_guard_errors_on_malformed_output`
- `test_cli_determinism_guard_labels_distinguish_score_and_face`

Strengthened (not weakened):

- mutation test now also asserts `[score]`, `document=`, artifact write, absence of ERROR
- face mismatch test now asserts `[score-face]` + `document=`
