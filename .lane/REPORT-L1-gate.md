# L1-gate report

## IMPORT PROVENANCE

Command run before the first pytest invocation:

```text
$ cd /home/ubuntu/w/L1-gate/apps/prototype-description-service && PYTHONPATH=$PWD /home/ubuntu/vlm6-fix/apps/prototype-description-service/.venv/bin/python -c "import scripts.eval_harness.strata as m; print(m.__file__)"
/home/ubuntu/w/L1-gate/apps/prototype-description-service/scripts/eval_harness/strata.py
```

The imported module is under `/home/ubuntu/w/L1-gate`, so the test evidence below comes from this worktree rather than the shared venv's `.pth` target.

## RED, GREEN, AND REVERT-RED EVIDENCE

### T1 — root `eval-anchor-check`

RED, after adding the target contract test and before adding the Make target:

```text
F.                                                                       [100%]
=================================== FAILURES ===================================
__________ test_eval_anchor_check_invokes_the_three_literal_verifiers __________

tmp_path = PosixPath('/tmp/pytest-of-ubuntu/pytest-1920/test_eval_anchor_check_invokes0')

    def test_eval_anchor_check_invokes_the_three_literal_verifiers(tmp_path: Path) -> None:
        proc, calls = _run_eval_anchor_check(tmp_path)
        combined = proc.stdout + proc.stderr
>       assert proc.returncode == 0, combined
E       AssertionError: make: Entering directory '/home/ubuntu/w/L1-gate'
E         make: Leaving directory '/home/ubuntu/w/L1-gate'
E         make: *** No rule to make target 'eval-anchor-check'.  Stop.
E
E       assert 2 == 0
E        +  where 2 = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L1-gate', 'eval-anchor-check'], returncode=2, stdout="make: Enter...Leaving directory '/home/ubuntu/w/L1-gate'\n", stderr="make: *** No rule to make target 'eval-anchor-check'.  Stop.\n").returncode

scripts/eval_harness/tests/test_eval_anchor_check.py:59: AssertionError
=========================== short test summary info ============================
FAILED scripts/eval_harness/tests/test_eval_anchor_check.py::test_eval_anchor_check_invokes_the_three_literal_verifiers
1 failed, 1 passed in 0.93s
```

GREEN, after adding the three literal verifier recipes:

```text
..                                                                       [100%]
2 passed in 1.19s
```

REVERT-RED, after temporarily removing only the new Make target:

```text
F.                                                                       [100%]
=================================== FAILURES ===================================
__________ test_eval_anchor_check_invokes_the_three_literal_verifiers __________

tmp_path = PosixPath('/tmp/pytest-of-ubuntu/pytest-1924/test_eval_anchor_check_invokes0')

    def test_eval_anchor_check_invokes_the_three_literal_verifiers(tmp_path: Path) -> None:
        proc, calls = _run_eval_anchor_check(tmp_path)
        combined = proc.stdout + proc.stderr
>       assert proc.returncode == 0, combined
E       AssertionError: make: Entering directory '/home/ubuntu/w/L1-gate'
E         make: Leaving directory '/home/ubuntu/w/L1-gate'
E         make: *** No rule to make target 'eval-anchor-check'.  Stop.
E
E       assert 2 == 0
E        +  where 2 = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L1-gate', 'eval-anchor-check'], returncode=2, stdout="make: Enter...Leaving directory '/home/ubuntu/w/L1-gate'\n", stderr="make: *** No rule to make target 'eval-anchor-check'.  Stop.\n").returncode

scripts/eval_harness/tests/test_eval_anchor_check.py:59: AssertionError
=========================== short test summary info ============================
FAILED scripts/eval_harness/tests/test_eval_anchor_check.py::test_eval_anchor_check_invokes_the_three_literal_verifiers
1 failed, 1 passed in 0.88s
```

The target was restored immediately afterward.

### T2 — any failed bake-off leg exits nonzero

RED, with one failed fetch leg out of two:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
________ test_emit_shell_exits_nonzero_when_one_of_two_fetch_legs_fails ________

tmp_path = PosixPath('/tmp/pytest-of-ubuntu/pytest-1927/test_emit_shell_exits_nonzero_0')

    def test_emit_shell_exits_nonzero_when_one_of_two_fetch_legs_fails(tmp_path: Path) -> None:
        proc, _calls = _run_shell(tmp_path, fail_token="run-bakeoff-bad.json")
        combined = proc.stdout + proc.stderr
>       assert proc.returncode != 0, combined
E       AssertionError: candidate bad fetch FAILED
E
E       assert 0 != 0
E        +  where 0 = CompletedProcess(args=['bash', '/tmp/pytest-of-ubuntu/pytest-1927/test_emit_shell_exits_nonzero_0/planned.sh'], returncode=0, stdout='', stderr='candidate bad fetch FAILED\n').returncode

scripts/eval_harness/tests/test_bakeoff_runner_exit_status.py:136: AssertionError
=========================== short test summary info ============================
FAILED scripts/eval_harness/tests/test_bakeoff_runner_exit_status.py::test_emit_shell_exits_nonzero_when_one_of_two_fetch_legs_fails
1 failed in 0.37s
```

GREEN, after adding the partial-failure exit branch while preserving the existing all-failed branch and exit code 1:

```text
.                                                                        [100%]
1 passed in 0.35s
```

REVERT-RED, after temporarily restoring the original all-failed-only behavior:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
________ test_emit_shell_exits_nonzero_when_one_of_two_fetch_legs_fails ________

tmp_path = PosixPath('/tmp/pytest-of-ubuntu/pytest-1929/test_emit_shell_exits_nonzero_0')

    def test_emit_shell_exits_nonzero_when_one_of_two_fetch_legs_fails(tmp_path: Path) -> None:
        proc, _calls = _run_shell(tmp_path, fail_token="run-bakeoff-bad.json")
        combined = proc.stdout + proc.stderr
>       assert proc.returncode != 0, combined
E       AssertionError: candidate bad fetch FAILED
E
E       assert 0 != 0
E        +  where 0 = CompletedProcess(args=['bash', '/tmp/pytest-of-ubuntu/pytest-1929/test_emit_shell_exits_nonzero_0/planned.sh'], returncode=0, stdout='', stderr='candidate bad fetch FAILED\n').returncode

scripts/eval_harness/tests/test_bakeoff_runner_exit_status.py:136: AssertionError
=========================== short test summary info ============================
FAILED scripts/eval_harness/tests/test_bakeoff_runner_exit_status.py::test_emit_shell_exits_nonzero_when_one_of_two_fetch_legs_fails
1 failed in 0.37s
```

The partial-failure branch was restored immediately afterward.

### T3 — caption scorer gate is load-bearing

The face proposal policy is deliberate: `report.py` says `gate_proposal is never a release artifact`, sets `release_surface` to `proposal_only_not_release`, and records `FIR-6 human operator records gate/deferral; FIR-5 cannot self-promote`. The face proposal was therefore left unchanged. The generated bake-off shell now runs the real caption `score` command after every successful fetch with `--rubric-gate enforce`. Because the bake-off corpus is `roster_only`, the command explicitly consents to refused face detection and identification metrics; those unavailable face metrics therefore cannot mask the caption gate.

RED, after strengthening the scorer-call test to require that caption-only policy and before adding its arguments:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
_______ test_emit_shell_exits_nonzero_when_score_gate_fails_after_fetch ________

tmp_path = PosixPath('/tmp/pytest-of-ubuntu/pytest-1944/test_emit_shell_exits_nonzero_0')

    def test_emit_shell_exits_nonzero_when_score_gate_fails_after_fetch(tmp_path: Path) -> None:
        bad_run = str((tmp_path / "out" / "run-bakeoff-bad.json").resolve())
        proc, calls = _run_shell(tmp_path, fail_token=f"--run-record {bad_run}")
        combined = proc.stdout + proc.stderr
        score_calls = [call for call in calls if call[:3] == ["-m", "scripts.eval_harness.cli", "score"]]
>       assert any(
            call[-6:] == [
                "--rubric-gate",
                "enforce",
                "--allow-refused",
                "detection",
                "--allow-refused",
                "identification",
            ]
            for call in score_calls
        ), score_calls
E       AssertionError: [['-m', 'scripts.eval_harness.cli', 'score', '--manifest', 'scripts/eval_harness/corpus646-interleave-manifest-2026071....cli', 'score', '--manifest', 'scripts/eval_harness/corpus646-interleave-manifest-20260716.json', '--run-record', ...]]
E       assert False
E        +  where False = any(<generator object test_emit_shell_exits_nonzero_when_score_gate_fails_after_fetch.<locals>.<genexpr> at 0xe084eff5fc60>)

scripts/eval_harness/tests/test_bakeoff_runner_exit_status.py:145: AssertionError
=========================== short test summary info ============================
FAILED scripts/eval_harness/tests/test_bakeoff_runner_exit_status.py::test_emit_shell_exits_nonzero_when_score_gate_fails_after_fetch
1 failed in 0.45s
```

GREEN, after wiring the explicit caption policy:

```text
.                                                                        [100%]
1 passed in 0.40s
```

REVERT-RED, after temporarily removing only the caption-enforce/face-consent arguments while leaving the scorer invocation present:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
_______ test_emit_shell_exits_nonzero_when_score_gate_fails_after_fetch ________

tmp_path = PosixPath('/tmp/pytest-of-ubuntu/pytest-1946/test_emit_shell_exits_nonzero_0')

    def test_emit_shell_exits_nonzero_when_score_gate_fails_after_fetch(tmp_path: Path) -> None:
        bad_run = str((tmp_path / "out" / "run-bakeoff-bad.json").resolve())
        proc, calls = _run_shell(tmp_path, fail_token=f"--run-record {bad_run}")
        combined = proc.stdout + proc.stderr
        score_calls = [call for call in calls if call[:3] == ["-m", "scripts.eval_harness.cli", "score"]]
>       assert any(
            call[-6:] == [
                "--rubric-gate",
                "enforce",
                "--allow-refused",
                "detection",
                "--allow-refused",
                "identification",
            ]
            for call in score_calls
        ), score_calls
E       AssertionError: [['-m', 'scripts.eval_harness.cli', 'score', '--manifest', 'scripts/eval_harness/corpus646-interleave-manifest-2026071....cli', 'score', '--manifest', 'scripts/eval_harness/corpus646-interleave-manifest-20260716.json', '--run-record', ...]]
E       assert False
E        +  where False = any(<generator object test_emit_shell_exits_nonzero_when_score_gate_fails_after_fetch.<locals>.<genexpr> at 0xe6c4d5890380>)

scripts/eval_harness/tests/test_bakeoff_runner_exit_status.py:145: AssertionError
=========================== short test summary info ============================
FAILED scripts/eval_harness/tests/test_bakeoff_runner_exit_status.py::test_emit_shell_exits_nonzero_when_score_gate_fails_after_fetch
1 failed in 0.42s
```

The caption policy arguments were restored immediately afterward.

### Final regression checks and anchor finding

Directly affected suite:

```text
............................................                             [100%]
44 passed in 7.81s
```

Existing non-fusion scorer exit-code contract tests:

```text
............                                                             [100%]
12 passed, 3 deselected, 22 warnings in 1.40s
```

The full `test_cli_exit_gates.py` diagnostic run reached 12 progress dots but its three fusion-runner cases did not finish after roughly five minutes; it was interrupted with exit 130 and is not claimed as green evidence. The 12 directly relevant non-fusion tests were then rerun to a final count as shown above.

`make eval-anchor-check` was also invoked exactly as documented. In this isolated sandbox, `uv --extra dev` could not bootstrap the absent local environment because outbound DNS is disabled:

```text
Using CPython 3.12.7
Creating virtual environment at: .venv
error: Request failed after 3 retries in 4.7s
  Caused by: Failed to fetch: `https://pypi.org/simple/psycopg/`
  Caused by: error sending request for url (https://pypi.org/simple/psycopg/)
  Caused by: client error (Connect)
  Caused by: dns error
  Caused by: failed to lookup address information: Temporary failure in name resolution
make: *** [Makefile:668: eval-anchor-check] Error 2
```

The generated `.venv` was moved recoverably out of the worktree to `/tmp/l1-gate-generated-venv`. To separate bootstrap failure from anchor state, all three underlying commands were then run with the contract-provided Python and verified `PYTHONPATH`:

- Caption determinism anchor: exit 1, `determinism check ANCHOR_MISMATCH [score]`. This is a stale-anchor finding; no frozen file or digest was changed.
- Face determinism anchor: exit 0, `determinism check passed [score-face]` and `freeze-certification passed [score-face]`.
- Sealed eval split: exit 0.

Thus the new combined target is capable of going red and, once dependencies are present, will stop on the currently stale caption anchor before proceeding to the two green checks.

## CANON RULES

### EVAL-23

Verbatim table row from `/home/ubuntu/lane-canon/EVALCANON.md`:

```text
| EVAL-23<a name="eval-23"></a> | Production readiness is reported as one number; a count of tests implemented, an average across categories, or an offline accuracy figure | **Readiness is the weakest category, not the total**: score data, model, infrastructure, and monitoring coverage as four separate subtotals and report the minimum as the readiness number, because the four are not substitutable and a total lets strong monitoring hide zero data tests until the untested contract fails in production (worst-unit gating on cohorts is [[FAIR-01]](ml-systems.md#fair-01); per-slice floors are [[EVAL-04]](ml-systems.md#eval-04)) | What is the lowest of the four category subtotals, and what is missing from it? | J·r | [ml-test-score sec-VI.A](../SOURCES.md#src-ml-test-score) |
```

Satisfaction: no aggregate success can hide a weak leg. The anchor target fails on any stale caption, face, or split anchor; the bake-off shell fails on any failed candidate leg; and each successfully fetched candidate must pass the enforced caption scorer gate.

### TEST-15

No `TEST-15` Markdown-table rule is present in either named canon file (`EVALCANON.md` or `RULES.md`). `EVALCANON.md` contains only a cross-reference to `[[TEST-15]](engineering.md#test-15)` in EVAL-22, not the TEST-15 rule text. I have not invented or paraphrased a missing rule as canon.

Satisfaction of the brief's stated TEST-15 requirement: each new behavior was observed RED before its production fix, GREEN after the fix, and RED again with the relevant production behavior temporarily removed; the production behavior was then restored.

### rg-006

No `rg-006` Markdown-table rule or textual occurrence is present in either named canon file (`EVALCANON.md` or `RULES.md`). I have not invented its text.

Satisfaction of the brief's stated command requirement: the root surface is the literal documented `make eval-anchor-check`; its test executes that exact command and asserts the exact three literal verifier argv lists. `make -n eval-anchor-check` parses without override warnings and prints those commands. The real invocation was attempted as written; its only pre-verifier blocker here was the sandbox's disabled dependency-download network, reported verbatim above.

## EXACT FILES CHANGED

The required `git diff --stat HEAD~1` output is unavailable because the sandbox prevents creation of the commit. The staging attempt failed verbatim:

```text
fatal: Unable to create '/home/ubuntu/l1/r7-int/.git/worktrees/L1-gate/index.lock': Read-only file system
```

The intended commit contains exactly these files:

- `.lane/REPORT.md`
- `Makefile`
- `apps/prototype-description-service/scripts/eval_harness/bakeoff_runner.py`
- `apps/prototype-description-service/scripts/eval_harness/tests/test_bakeoff_runner_exit_status.py`
- `apps/prototype-description-service/scripts/eval_harness/tests/test_eval_anchor_check.py`

No determinism anchor JSON, frozen digest, `strata.py`, caption tag scoring, or readability scoring file was changed.

## HONEST STATUS: PARTIAL

All requested code and test work for T1, T2, and T3 is implemented in the worktree. The only required deliverable that remains is to stage the five files listed above, commit them on `lane/L1-gate`, and replace this blocker section with the resulting `git diff --stat HEAD~1`; that cannot be done until `/home/ubuntu/l1/r7-int/.git/worktrees/L1-gate` is writable. The caption determinism anchor is currently stale and must be investigated by its owning workflow; per the task invariant it was reported, not re-frozen. The sandbox-only `uv` bootstrap could not download dependencies because outbound DNS is disabled, but the underlying checks were executed with the provided environment and their actual states are reported above.
