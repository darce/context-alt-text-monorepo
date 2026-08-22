# L4-surf EVALSURF-1 merge-blocker report

## IMPORT PROVENANCE check output

Command (from `/home/ubuntu/w/L4-surf/apps/prototype-description-service`):

```text
PYTHONPATH=$PWD /home/ubuntu/vlm6-fix/apps/prototype-description-service/.venv/bin/python -c "import scripts.eval_harness.strata as m; print(m.__file__)"
```

Output:

```text
/home/ubuntu/w/L4-surf/apps/prototype-description-service/scripts/eval_harness/strata.py
```

The imported module is inside the assigned worktree.

## RED output (B.1)

This was the first run after adding the two failing contract tests and before changing production files.

```text
FF                                                                       [100%]
=================================== FAILURES ===================================
_______________ test_test_scripts_collects_eval_target_contract ________________

    def test_test_scripts_collects_eval_target_contract() -> None:
        result = subprocess.run(
            ["make", "-n", "-C", str(REPO_ROOT), "test-scripts"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
>       assert "scripts/test_make_eval_targets.py" in result.stdout, (
            "test-scripts does not collect scripts/test_make_eval_targets.py"
        )
E       AssertionError: test-scripts does not collect scripts/test_make_eval_targets.py
E       assert 'scripts/test_make_eval_targets.py' in "make: Entering directory '/home/ubuntu/w/L4-surf'\npython3 -m pytest \\\n\tscripts/hooks .github/hooks scripts/test_p...short --durations=25\nbash scripts/deploy/tests/test-smoke-gate.sh\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n"
E        +  where "make: Entering directory '/home/ubuntu/w/L4-surf'\npython3 -m pytest \\\n\tscripts/hooks .github/hooks scripts/test_p...short --durations=25\nbash scripts/deploy/tests/test-smoke-gate.sh\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" = CompletedProcess(args=['make', '-n', '-C', '/home/ubuntu/w/L4-surf', 'test-scripts'], returncode=0, stdout="make: Ente...tions=25\nbash scripts/deploy/tests/test-smoke-gate.sh\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n", stderr='').stdout

../../scripts/test_make_eval_targets.py:163: AssertionError
__________________ test_eval_report_requires_and_forwards_run __________________

    def test_eval_report_requires_and_forwards_run() -> None:
        missing_run = subprocess.run(
            [
                "make",
                "-C",
                str(REPO_ROOT),
                "eval-report",
                "MANIFEST=golden.json",
                "OUT=report.html",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert missing_run.returncode != 0, "eval-report ran without required RUN"
>       assert "RUN is required" in missing_run.stdout + missing_run.stderr
E       assert 'RUN is required' in ("make: Entering directory '/home/ubuntu/w/L4-surf'\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" + 'error: Could not acquire lock\n  Caused by: Could not create temporary file\n  Caused by: Read-only file system (os e... at path "/home/ubuntu/.cache/uv/.tmpV6zJMl"\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:90: eval-report] Error 2\n')
E        +  where "make: Entering directory '/home/ubuntu/w/L4-surf'\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-report', 'MANIFEST=golden.json', 'OUT=report.html...at path "/home/ubuntu/.cache/uv/.tmpV6zJMl"\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:90: eval-report] Error 2\n').stdout
E        +  and   'error: Could not acquire lock\n  Caused by: Could not create temporary file\n  Caused by: Read-only file system (os e... at path "/home/ubuntu/.cache/uv/.tmpV6zJMl"\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:90: eval-report] Error 2\n' = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-report', 'MANIFEST=golden.json', 'OUT=report.html...at path "/home/ubuntu/.cache/uv/.tmpV6zJMl"\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:90: eval-report] Error 2\n').stderr

../../scripts/test_make_eval_targets.py:183: AssertionError
=========================== short test summary info ============================
FAILED ../../scripts/test_make_eval_targets.py::test_test_scripts_collects_eval_target_contract
FAILED ../../scripts/test_make_eval_targets.py::test_eval_report_requires_and_forwards_run
2 failed in 0.55s
```

## GREEN output (B.3)

Final focused run after restoring the production fixes:

```text
..                                                                       [100%]
2 passed in 0.58s
```

## REVERT-RED proof (B.4 / TEST-15)

The final production shape was temporarily reverted: the `test-scripts: test-eval-surface` wiring and narrow target were removed, and the `RUN` guard/forwarding were removed. The new tests remained unchanged.

```text
FF                                                                       [100%]
=================================== FAILURES ===================================
_______________ test_test_scripts_collects_eval_target_contract ________________

    def test_test_scripts_collects_eval_target_contract() -> None:
        result = subprocess.run(
            ["make", "-n", "-C", str(REPO_ROOT), "test-scripts"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
>       assert "scripts/test_make_eval_targets.py" in result.stdout, (
            "test-scripts does not collect scripts/test_make_eval_targets.py"
        )
E       AssertionError: test-scripts does not collect scripts/test_make_eval_targets.py
E       assert 'scripts/test_make_eval_targets.py' in "make: Entering directory '/home/ubuntu/w/L4-surf'\npython3 -m pytest \\\n\tscripts/hooks .github/hooks scripts/test_p...short --durations=25\nbash scripts/deploy/tests/test-smoke-gate.sh\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n"
E        +  where "make: Entering directory '/home/ubuntu/w/L4-surf'\npython3 -m pytest \\\n\tscripts/hooks .github/hooks scripts/test_p...short --durations=25\nbash scripts/deploy/tests/test-smoke-gate.sh\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" = CompletedProcess(args=['make', '-n', '-C', '/home/ubuntu/w/L4-surf', 'test-scripts'], returncode=0, stdout="make: Ente...tions=25\nbash scripts/deploy/tests/test-smoke-gate.sh\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n", stderr='').stdout

../../scripts/test_make_eval_targets.py:164: AssertionError
__________________ test_eval_report_requires_and_forwards_run __________________

    def test_eval_report_requires_and_forwards_run() -> None:
        missing_run = subprocess.run(
            [
                "make",
                "-C",
                str(REPO_ROOT),
                "eval-report",
                "MANIFEST=golden.json",
                "OUT=report.html",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert missing_run.returncode != 0, "eval-report ran without required RUN"
>       assert "RUN is required" in missing_run.stdout + missing_run.stderr
E       assert 'RUN is required' in ("make: Entering directory '/home/ubuntu/w/L4-surf'\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" + 'error: Could not acquire lock\n  Caused by: Could not create temporary file\n  Caused by: Read-only file system (os e... at path "/home/ubuntu/.cache/uv/.tmpJUds4v"\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:90: eval-report] Error 2\n')
E        +  where "make: Entering directory '/home/ubuntu/w/L4-surf'\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-report', 'MANIFEST=golden.json', 'OUT=report.html...at path "/home/ubuntu/.cache/uv/.tmpJUds4v"\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:90: eval-report] Error 2\n').stdout
E        +  and   'error: Could not acquire lock\n  Caused by: Could not create temporary file\n  Caused by: Read-only file system (os e... at path "/home/ubuntu/.cache/uv/.tmpJUds4v"\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:90: eval-report] Error 2\n' = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-report', 'MANIFEST=golden.json', 'OUT=report.html...at path "/home/ubuntu/.cache/uv/.tmpJUds4v"\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:90: eval-report] Error 2\n').stderr

../../scripts/test_make_eval_targets.py:184: AssertionError
=========================== short test summary info ============================
FAILED ../../scripts/test_make_eval_targets.py::test_test_scripts_collects_eval_target_contract
FAILED ../../scripts/test_make_eval_targets.py::test_eval_report_requires_and_forwards_run
2 failed in 0.45s
```

The production changes were then restored, and the focused suite returned to the GREEN output above.

## BR-01 deliberate Make wiring proof

Before this change, `rg -n "scripts/test_make_eval_targets.py|test_make_eval_targets" Makefile mk/*.mk scripts/*.sh` found only the descriptive comment in `mk/evals.mk`; no target collected the file. The implemented `test-eval-surface` target runs the file from the service directory with local `PYTHONPATH`, and `test-scripts` depends on it.

For the wiring proof only, the new collection assertion was temporarily inverted. Running `make test-scripts` with pytest selection narrowed to that assertion produced:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
_______________ test_test_scripts_collects_eval_target_contract ________________

    def test_test_scripts_collects_eval_target_contract() -> None:
        result = subprocess.run(
            ["make", "-n", "-C", str(REPO_ROOT), "test-scripts"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
>       assert "scripts/test_make_eval_targets.py" not in result.stdout, (
            "DELIBERATE WIRING PROOF: test-scripts collected scripts/test_make_eval_targets.py"
        )
E       AssertionError: DELIBERATE WIRING PROOF: test-scripts collected scripts/test_make_eval_targets.py
E       assert 'scripts/tes...l_targets.py' not in "make[1]: En...w/L4-surf'\n"
E         
E         'scripts/test_make_eval_targets.py' is contained here:
E            \
E           	../../scripts/test_make_eval_targets.py -q
E           python3 -m pytest \
E           	scripts/hooks .github/hooks scripts/test_php_characterization_gate.py \
E           	scripts/test_e15_31_admin_deploy_contract.py scripts/test_e15_33_deploy_convergence.py scripts/test_e15_33_boot_smoke.py \...
E         
E         ...Full output truncated (15 lines hidden), use '-vv' to show

../../scripts/test_make_eval_targets.py:164: AssertionError
=========================== short test summary info ============================
FAILED ../../scripts/test_make_eval_targets.py::test_test_scripts_collects_eval_target_contract
1 failed, 21 deselected in 0.27s
make: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:35: test-eval-surface] Error 1
```

The assertion was restored immediately. This proves the broad target reaches the previously orphaned file and propagates its failure.

## BR-02 documented command and missing-RUN behavior

Missing operator value:

```text
error: RUN is required (e.g. RUN=baseline=scripts/eval_harness/out/run-20260820.json)
make: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:97: eval-report] Error 2
```

Documented target invocation with concrete `LABEL=PATH`, manifest, and output values (the environment variables select the supplied shared environment and a writable uv cache because sandbox network/cache writes are unavailable):

```text
UV_CACHE_DIR=/tmp/l4-surf-uv-nosync UV_PROJECT_ENVIRONMENT=/home/ubuntu/vlm6-fix/apps/prototype-description-service/.venv UV_NO_SYNC=1 make eval-report RUN=fixture=/tmp/l4-surf-run.json MANIFEST=scene/tests/seed/bakeoff_golden.json OUT=/tmp/l4-surf-eval-report.html
```

Output:

```text
wrote /tmp/l4-surf-eval-report.html (6KB, 2 images, 1 run(s))
```

The target now documents `RUN=<label=path>`, rejects its omission before invoking uv, and forwards it as `--run "$(RUN)"`.

## Full newly-wired target finding

The invariant says not to weaken assertions when wiring exposes an already-failing test. The full target therefore remains RED with the original `"is required"` assertion unchanged:

```text
............FFs..F....                                                   [100%]
=================================== FAILURES ===================================
__________ test_required_arguments_are_guarded[eval-corpus-inventory] __________

target = 'eval-corpus-inventory'

    @pytest.mark.parametrize("target", sorted(TARGET_ARGS))
    def test_required_arguments_are_guarded(target: str) -> None:
        """Omitting a required variable must fail with exit 2, not a broken run."""
        if not TARGET_ARGS[target]:
            pytest.skip(f"{target} has no required arguments")
        result = subprocess.run(
            ["make", "-C", str(REPO_ROOT), target],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0, f"{target} ran with no required arguments"
>       assert "is required" in result.stdout + result.stderr
E       assert 'is required' in ("make[1]: Entering directory '/home/ubuntu/w/L4-surf'\nmake[1]: Leaving directory '/home/ubuntu/w/L4-surf'\n" + 'error: IMAGES and OUT are both required\nmake[1]: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:112: eval-corpus-inventory] Error 2\n')
E        +  where "make[1]: Entering directory '/home/ubuntu/w/L4-surf'\nmake[1]: Leaving directory '/home/ubuntu/w/L4-surf'\n" = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-corpus-inventory'], returncode=2, stdout="make[1]...GES and OUT are both required\nmake[1]: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:112: eval-corpus-inventory] Error 2\n').stdout
E        +  and   'error: IMAGES and OUT are both required\nmake[1]: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:112: eval-corpus-inventory] Error 2\n' = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-corpus-inventory'], returncode=2, stdout="make[1]...GES and OUT are both required\nmake[1]: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:112: eval-corpus-inventory] Error 2\n').stderr

../../scripts/test_make_eval_targets.py:123: AssertionError
___________ test_required_arguments_are_guarded[eval-face-calibrate] ___________

target = 'eval-face-calibrate'

    @pytest.mark.parametrize("target", sorted(TARGET_ARGS))
    def test_required_arguments_are_guarded(target: str) -> None:
        """Omitting a required variable must fail with exit 2, not a broken run."""
        if not TARGET_ARGS[target]:
            pytest.skip(f"{target} has no required arguments")
        result = subprocess.run(
            ["make", "-C", str(REPO_ROOT), target],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0, f"{target} ran with no required arguments"
>       assert "is required" in result.stdout + result.stderr
E       assert 'is required' in ("make[1]: Entering directory '/home/ubuntu/w/L4-surf'\nmake[1]: Leaving directory '/home/ubuntu/w/L4-surf'\n" + 'error: REPORT and MANIFEST are both required\nmake[1]: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:80: eval-face-calibrate] Error 2\n')
E        +  where "make[1]: Entering directory '/home/ubuntu/w/L4-surf'\nmake[1]: Leaving directory '/home/ubuntu/w/L4-surf'\n" = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-face-calibrate'], returncode=2, stdout="make[1]: ...T and MANIFEST are both required\nmake[1]: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:80: eval-face-calibrate] Error 2\n').stdout
E        +  and   'error: REPORT and MANIFEST are both required\nmake[1]: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:80: eval-face-calibrate] Error 2\n' = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-face-calibrate'], returncode=2, stdout="make[1]: ...T and MANIFEST are both required\nmake[1]: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:80: eval-face-calibrate] Error 2\n').stderr

../../scripts/test_make_eval_targets.py:123: AssertionError
_______________ test_required_arguments_are_guarded[eval-strata] _______________

target = 'eval-strata'

    @pytest.mark.parametrize("target", sorted(TARGET_ARGS))
    def test_required_arguments_are_guarded(target: str) -> None:
        """Omitting a required variable must fail with exit 2, not a broken run."""
        if not TARGET_ARGS[target]:
            pytest.skip(f"{target} has no required arguments")
        result = subprocess.run(
            ["make", "-C", str(REPO_ROOT), target],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0, f"{target} ran with no required arguments"
>       assert "is required" in result.stdout + result.stderr
E       assert 'is required' in ("make[1]: Entering directory '/home/ubuntu/w/L4-surf'\nmake[1]: Leaving directory '/home/ubuntu/w/L4-surf'\n" + 'error: INVENTORY (SOURCE=PATH) and OUT are both required\nmake[1]: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:123: eval-strata] Error 2\n')
E        +  where "make[1]: Entering directory '/home/ubuntu/w/L4-surf'\nmake[1]: Leaving directory '/home/ubuntu/w/L4-surf'\n" = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-strata'], returncode=2, stdout="make[1]: Entering...(SOURCE=PATH) and OUT are both required\nmake[1]: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:123: eval-strata] Error 2\n').stdout
E        +  and   'error: INVENTORY (SOURCE=PATH) and OUT are both required\nmake[1]: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:123: eval-strata] Error 2\n' = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-strata'], returncode=2, stdout="make[1]: Entering...(SOURCE=PATH) and OUT are both required\nmake[1]: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:123: eval-strata] Error 2\n').stderr

../../scripts/test_make_eval_targets.py:123: AssertionError
=========================== short test summary info ============================
FAILED ../../scripts/test_make_eval_targets.py::test_required_arguments_are_guarded[eval-corpus-inventory]
FAILED ../../scripts/test_make_eval_targets.py::test_required_arguments_are_guarded[eval-face-calibrate]
FAILED ../../scripts/test_make_eval_targets.py::test_required_arguments_are_guarded[eval-strata]
3 failed, 18 passed, 1 skipped in 4.31s
make: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:35: test-eval-surface] Error 1
```

The broad legacy `test-scripts` recipe also names nonexistent `scripts/hooks` and `.github/hooks`; once the narrow prerequisite is green, that recipe currently exits at collection with `ERROR: file or directory not found: scripts/hooks`. Neither unrelated issue was changed in this lane.

## Canon rules and satisfaction

### rg-006

`rg -n -i "rg-006|documented commands must run|commands must run as written" /home/ubuntu/lane-canon/RULES.md /home/ubuntu/lane-canon/EVALCANON.md /home/ubuntu/lane-canon/ENGCANON.md` returned no matches. The named rule is genuinely absent from the three supplied canon files, so no verbatim canon text can be quoted without invention.

The brief describes rg-006 as “documented commands must run as written.” The change satisfies that stated requirement by documenting the required `RUN=<label=path>` operand, refusing its omission with a clear example, forwarding it to the real CLI as `--run`, and successfully generating a two-image report with the documented Make invocation.

### TEST-15 (verbatim)

> | TEST-15<a name="test-15"></a> | Reviewing a passing test that guards an invariant, single-source count, or state property | **Prove the green can go red**: a passing test that cannot fail certifies nothing; before trusting it, mutate the production path (break the invariant, inject a second/zero case, corrupt an input) and confirm the assertion catches it; for invariant/count tests, ship the mutation as a permanent discrimination guard (e.g. mis-wire → asserts 2, drop → asserts 0). Watch for assertions on the code's own output rather than observed behavior, and DOM/count checks that never query the real surface (see [[TEST-11]](engineering.md#test-11), [[DBG-01]](engineering.md#dbg-01)) | If production regressed here, would this exact assertion turn red; have I seen it? | S·r | [modern-software-engineering ch-8](../SOURCES.md#src-modern-software-engineering) + [pragmatic-programmer ch-9](../SOURCES.md#src-pragmatic-programmer) |

Satisfaction: both new assertions were first observed RED, then GREEN, then RED again with the final production paths reverted. Separately, the collection assertion was inverted and the real `make test-scripts` path propagated its deliberate failure. The discrimination guards remain permanent in `scripts/test_make_eval_targets.py`.

### EVAL-23 (verbatim)

> | EVAL-23<a name="eval-23"></a> | Production readiness is reported as one number; a count of tests implemented, an average across categories, or an offline accuracy figure | **Readiness is the weakest category, not the total**: score data, model, infrastructure, and monitoring coverage as four separate subtotals and report the minimum as the readiness number, because the four are not substitutable and a total lets strong monitoring hide zero data tests until the untested contract fails in production (worst-unit gating on cohorts is [[FAIR-01]](ml-systems.md#fair-01); per-slice floors are [[EVAL-04]](ml-systems.md#eval-04)) | What is the lowest of the four category subtotals, and what is missing from it? | J·r | [ml-test-score sec-VI.A](../SOURCES.md#src-ml-test-score) |

Satisfaction: this report does not aggregate the focused `2 passed` result into a readiness claim. It reports the weakest integration surface—the full newly-wired target is RED—and therefore marks the lane BLOCKED despite both assigned focused tests passing.

## Exact files changed (`git diff --stat HEAD~1`)

```text
 .lane/REPORT.md                   | 326 ++++++++++++++++++++++++++++++++++++++
 mk/evals.mk                       |  22 ++-
 scripts/test_make_eval_targets.py |  39 ++++-
 3 files changed, 380 insertions(+), 7 deletions(-)
```

## HONEST STATUS: BLOCKED

Both assigned changes are implemented and individually proven: the orphan is now a prerequisite of `test-scripts`, its deliberate failure propagates through Make, and `eval-report` requires/forwards `RUN` and successfully generates a report.

The lane remains BLOCKED because wiring exposes three pre-existing failures in the unchanged `test_required_arguments_are_guarded` assertion:

- `eval-corpus-inventory` says `IMAGES and OUT are both required`.
- `eval-face-calibrate` says `REPORT and MANIFEST are both required`.
- `eval-strata` says `INVENTORY (SOURCE=PATH) and OUT are both required`.

Exactly what remains: a separately authorized change must make those three production error messages satisfy the existing `"is required"` contract without weakening the assertion. After that, the unrelated stale `scripts/hooks` and `.github/hooks` entries in the broad root `test-scripts` recipe must be resolved so the entire target can complete. These were not changed because they are outside the two assigned findings.
