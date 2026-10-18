# VLM-6 Slice 2A — `vlm6-s2a-verdict` lane report (item 3: cross-process determinism)

**Lane:** `vlm6-s2a-verdict`  
**Task:** `VLM-6`  
**Scope:** Make `score --check-determinism` cross-process (Slice 2A **item 3** only)  
**Out of scope:** Corruption discrimination guards (item 4 / `vlm6-s2a-corruption-guards`); no change to face determinism behaviour

## Verdict

**merge_ready** — lane-owned code + tests + this report committed.

## What changed

### `cli.py` — `_check_score_determinism_cross_process`

Replaced the same-process double `build_reports(...)` call in `_cmd_score` with a helper that mirrors `_check_face_determinism_cross_process`:

1. Compute in-process baseline by reading the **persisted** run-record path.
2. Re-score in a **fresh subprocess** for each `PYTHONHASHSEED` in `("0", "1", "42")`, reloading the record from disk.
3. Diff JSON + MD against the baseline; distinct failure messages for non-zero rc, malformed output, and mismatch.

Pass message:

```
determinism check passed: cross-process re-score is bit-identical under varied PYTHONHASHSEED
```

`_check_face_determinism_cross_process` is **untouched**. No shared-factor refactor (would risk face path regression for little gain).

## RED evidence (before fix)

Baseline suite at start of this session: **121 passed**.

New tests against the old in-process double-call:

```
FAILED test_cli_score_check_determinism_runs_cross_process_guard
  AssertionError: assert 'cross-process' in
  'determinism check passed: re-score is bit-identical\n...run-det-report.md\nscored=1/1 ...'

FAILED test_cli_score_determinism_guard_detects_mutated_persisted_anchor
  AttributeError: module 'scripts.eval_harness.cli' has no attribute
  '_check_score_determinism_cross_process'. Did you mean:
  '_check_face_determinism_cross_process'?
```

The mutation test cannot pass on the old code: subprocess is never called, so a mutated anchor is invisible and the helper does not exist.

## GREEN evidence (after fix)

Mutating the persisted run-record between baseline and subprocess re-score:

```
determinism check FAILED: cross-process re-score differs under PYTHONHASHSEED=0
```

Clean case:

```
determinism check passed: cross-process re-score is bit-identical under varied PYTHONHASHSEED
```

## Tests

| Suite | Baseline (before) | After |
| --- | --- | --- |
| `test_eval_harness_cli.py` + `test_eval_harness_report.py` | **121 passed** | **123 passed** |

New tests (each can go red — TEST-15):

- `test_cli_score_check_determinism_runs_cross_process_guard` — clean path + message names cross-process
- `test_cli_score_determinism_guard_detects_mutated_persisted_anchor` — mutates disk anchor between baseline and subprocess; asserts FAILED

## Verification command

```bash
cd apps/prototype-description-service && \
  uv run --extra dev pytest \
    scene/tests/test_eval_harness_cli.py \
    scene/tests/test_eval_harness_report.py -q
# 123 passed
```

## Explicit non-work

- Did **not** change `_check_face_determinism_cross_process` behaviour.
- Did **not** add corruption discrimination guards (item 4).
- Did **not** touch frozen anchors under `docs/tasks/vlm/bakeoff-results/`.
- Did **not** relax validators or weaken existing assertions (sr-001).
