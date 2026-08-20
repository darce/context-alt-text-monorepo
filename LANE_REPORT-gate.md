# LANE_REPORT — FIR-12-BR-67 / FIR-12-BR-70

Worktree: `context-alt-text-monorepo-r7-gate`, branch `feature/fir12-r7-gate`, base `b2ad134a7bf1891604804a88d9b94c68c2f13201`.

## Commits

- `13f1baebab3cec97f00ff75d1c686b8a8923eae7` — fix(eval-harness): FIR-12-BR-67 document testpaths as the full gate collection
- `9ffb124c2d82fdf7d9fb3ee55f0279ecafef1592` — fix(eval-harness): FIR-12-BR-70 give env/startup failures their own exit code

## Post-change gate (full declared collection, remote VM)

```
1671 passed, 4 skipped, 1 deselected, 14 warnings in 62.72s (0:01:02)
```

Zero failures. Baseline (measured earlier, not re-measured per coordinator instruction): `1668 passed, 4 skipped, 1 deselected, 14 warnings`. Delta = +3, matching the 3 new BR-70 tests.

## Old vs new collected-test counts

- **OLD** (the actually-broken FIR-12-BR-67 command, `pytest scene/tests --ignore=... --deselect=...`, no `scripts/eval_harness/tests` positional arg): `1367/1368 tests collected (1 deselected)`.
- **Current `gate-lane.sh`** (already includes both `scene/tests` and `scripts/eval_harness/tests` as positional args — this script was already fixed at the infra layer, outside repo/ownership scope): `1671 passed + 4 skipped + 1 deselected = 1676` collected. Recovers ~308 tests vs. OLD, matching the finding's "~300 tests" claim.
- **NEW** (bare `pytest`, testpaths-driven, full `pyproject.toml` declared collection including `recognition/tests`): `3917 tests collected`. This superset is not run by `gate-lane.sh` for this lane — `recognition/tests` likely needs a live Postgres and belongs to a separate gate; `gate-lane.sh` is remote infra outside this task's file-ownership boundary, not edited here.

## Fix 1(b) — real CLI failure vs. missing interpreter

Already satisfied on base commit `b2ad134a` (prior lane F42). Verified by reading code, not taken on faith: `resolve_eval_python()` (`scripts/regen_eval_report.py` lines 99–123) raises `EvalPythonError` on a set-but-invalid `ACX_EVAL_PYTHON` (never silently falls back) and requires the service `.venv/bin/python` when unset (no `sys.executable` fallback). Covered by existing dedicated tests plus `_REAL_CLI_ENV = {"ACX_EVAL_PYTHON": sys.executable}`. No code change made for part (b).

## Fix 1(c) — doc search for the broken gate command

Exhaustive search of `docs/`, `apps/`, `scripts/`, `.github/workflows/`, `.s2a/` for the literal string `pytest scene/tests --ignore=... --deselect=...` (and variants). **Zero tracked files contain it.** The command was ephemeral lane/reviewer/coordinator dispatch instruction, never committed to the repo. No doc files required correction. `docs/workbay/rules/testing-python.md`'s existing Commands section already documents bare `pytest` / `make test` / `make check` with no narrowed invocation — a preventive callout was drafted there and then reverted, since (1) that file is a workbay-bootstrap-managed surface that will drift on the next `workbay update`, and (2) no broken command actually existed there to correct.

## Exit-code table (`scripts/regen_eval_report.py`'s own contract, FIR-12-BR-70)

| Code | Meaning |
|---|---|
| 0 | Clean score, published. CLI exited 0 and wrote a report. |
| 1 | Partial-corpus score gate. CLI exited 1 **and wrote a report**; held, not published. Genuine corpus-quality outcome. |
| 2 | Resolution/environment/usage failure, never a corpus outcome: missing `--run-record`/`--manifest`, unresolvable `ACX_EVAL_PYTHON`, or the CLI produced **no report at all** regardless of its own exit code. |
| 3 | Refused metrics (CLI exited 3); held unless `--allow-refused`. |
| * | Any other CLI exit **with a report on disk**: unrecognized, held not swallowed. |

## Three-way `echo $?` proof (remote VM, real invocations against `_failed_item_record()`/`_roster_only_manifest()`-equivalent fixtures)

- Scenario A — broken-but-real interpreter, inner `sys.exit(1)`, no report written: `EXIT_A=2`
- Scenario B — interpreter exits 0, no report written: `EXIT_B=2`
- Scenario C — genuine partial corpus via the real CLI (real interpreter, failed item, report written and correctly withheld, CLI exited 1): `EXIT_C=1`

All three distinguishable; A and B share code 2 (neither is a corpus outcome) and both differ from C's genuine 1.

## Control-mutant evidence (TEST-15 / OBS-08)

Two mutants applied to `scripts/regen_eval_report.py`'s missing-report branch, each pushed to the remote lane, run, then reverted via `git reset --hard` to the real fix commit (mutants never landed in history):

- **Mutant 1** (`return proc.returncode or 2`, the original bug): `test_broken_real_interpreter_no_report_is_not_partial_corpus` and `test_env_failures_are_distinguishable_from_genuine_partial_corpus` went RED (`assert broken_code == 2` failed, got `1`). `test_interpreter_exits_0_without_report_is_not_clean_score` stayed green here only because `0 or 2 == 2` in Python — mathematically equivalent to the fix for that specific input; not a gap, since Mutant 2 below kills it.
- **Mutant 2** (bare `return proc.returncode`, no dedicated code, no message): all three new tests went RED:
  ```
  FAILED test_broken_real_interpreter_no_report_is_not_partial_corpus
  FAILED test_interpreter_exits_0_without_report_is_not_clean_score
  FAILED test_env_failures_are_distinguishable_from_genuine_partial_corpus
  ```
- Restored to `9ffb124c2`: all three GREEN (`3 passed, 1673 deselected`); full suite re-confirmed `1671 passed, 4 skipped, 1 deselected, 14 warnings`, zero failures.

## Unfinished / out of scope

- `gate-lane.sh` (remote VM infra script) is narrower than the full `pyproject.toml` `testpaths` declaration — it omits `recognition/tests`. This is outside the task's file-ownership boundary (not a tracked repo file) and plausibly intentional (Postgres dependency); not fixed here, flagged for operator awareness.
