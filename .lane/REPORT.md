# L5-msgs — three eval guard messages satisfy `"is required"`

## IMPORT PROVENANCE check output

Command (from `/home/ubuntu/w/L4-surf/apps/prototype-description-service`):

```text
PYTHONPATH=$PWD /home/ubuntu/vlm6-fix/apps/prototype-description-service/.venv/bin/python -c "import scripts.eval_harness.strata as m; print(m.__file__)"
```

Output:

```text
/home/ubuntu/w/L4-surf/apps/prototype-description-service/scripts/eval_harness/strata.py
```

The printed path starts with `LANE_PATH` (`/home/ubuntu/w/L4-surf`). Import provenance is this worktree, not the shared-venv `.pth` pin.

## RED output (B.1)

First run of the three parametrised cases, before any production edit:

```text
FFF                                                                      [100%]
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
E       assert 'is required' in ("make: Entering directory '/home/ubuntu/w/L4-surf'\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" + 'error: IMAGES and OUT are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:112: eval-corpus-inventory] Error 2\n')
E        +  where "make: Entering directory '/home/ubuntu/w/L4-surf'\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-corpus-inventory'], returncode=2, stdout="make: E...IMAGES and OUT are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:112: eval-corpus-inventory] Error 2\n').stdout
E        +  and   'error: IMAGES and OUT are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:112: eval-corpus-inventory] Error 2\n' = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-corpus-inventory'], returncode=2, stdout="make: E...IMAGES and OUT are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:112: eval-corpus-inventory] Error 2\n').stderr

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
E       assert 'is required' in ("make: Entering directory '/home/ubuntu/w/L4-surf'\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" + 'error: REPORT and MANIFEST are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:80: eval-face-calibrate] Error 2\n')
E        +  where "make: Entering directory '/home/ubuntu/w/L4-surf'\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-face-calibrate'], returncode=2, stdout="make: Ent...PORT and MANIFEST are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:80: eval-face-calibrate] Error 2\n').stdout
E        +  and   'error: REPORT and MANIFEST are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:80: eval-face-calibrate] Error 2\n' = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-face-calibrate'], returncode=2, stdout="make: Ent...PORT and MANIFEST are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:80: eval-face-calibrate] Error 2\n').stderr

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
E       assert 'is required' in ("make: Entering directory '/home/ubuntu/w/L4-surf'\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" + 'error: INVENTORY (SOURCE=PATH) and OUT are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:123: eval-strata] Error 2\n')
E        +  where "make: Entering directory '/home/ubuntu/w/L4-surf'\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-strata'], returncode=2, stdout="make: Entering di...RY (SOURCE=PATH) and OUT are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:123: eval-strata] Error 2\n').stdout
E        +  and   'error: INVENTORY (SOURCE=PATH) and OUT are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:123: eval-strata] Error 2\n' = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-strata'], returncode=2, stdout="make: Entering di...RY (SOURCE=PATH) and OUT are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:123: eval-strata] Error 2\n').stderr

../../scripts/test_make_eval_targets.py:123: AssertionError
=========================== short test summary info ============================
FAILED ../../scripts/test_make_eval_targets.py::test_required_arguments_are_guarded[eval-corpus-inventory]
FAILED ../../scripts/test_make_eval_targets.py::test_required_arguments_are_guarded[eval-face-calibrate]
FAILED ../../scripts/test_make_eval_targets.py::test_required_arguments_are_guarded[eval-strata]
3 failed in 7.19s
```

## GREEN output (B.3)

After rewriting only the three production error strings in `mk/evals.mk`:

```text
...                                                                      [100%]
3 passed in 7.25s
```

## REVERT-RED proof (B.4 / TEST-15)

`git stash push -- mk/evals.mk` restored the three `"are both required"` strings. Same three cases, unchanged assertion:

```text
FFF                                                                      [100%]
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
E       assert 'is required' in ("make: Entering directory '/home/ubuntu/w/L4-surf'\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" + 'error: IMAGES and OUT are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:112: eval-corpus-inventory] Error 2\n')
E        +  where "make: Entering directory '/home/ubuntu/w/L4-surf'\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-corpus-inventory'], returncode=2, stdout="make: E...IMAGES and OUT are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:112: eval-corpus-inventory] Error 2\n').stdout
E        +  and   'error: IMAGES and OUT are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:112: eval-corpus-inventory] Error 2\n' = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-corpus-inventory'], returncode=2, stdout="make: E...IMAGES and OUT are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:112: eval-corpus-inventory] Error 2\n').stderr

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
E       assert 'is required' in ("make: Entering directory '/home/ubuntu/w/L4-surf'\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" + 'error: REPORT and MANIFEST are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:80: eval-face-calibrate] Error 2\n')
E        +  where "make: Entering directory '/home/ubuntu/w/L4-surf'\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-face-calibrate'], returncode=2, stdout="make: Ent...PORT and MANIFEST are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:80: eval-face-calibrate] Error 2\n').stdout
E        +  and   'error: REPORT and MANIFEST are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:80: eval-face-calibrate] Error 2\n' = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-face-calibrate'], returncode=2, stdout="make: Ent...PORT and MANIFEST are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:80: eval-face-calibrate] Error 2\n').stderr

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
E       assert 'is required' in ("make: Entering directory '/home/ubuntu/w/L4-surf'\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" + 'error: INVENTORY (SOURCE=PATH) and OUT are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:123: eval-strata] Error 2\n')
E        +  where "make: Entering directory '/home/ubuntu/w/L4-surf'\nmake: Leaving directory '/home/ubuntu/w/L4-surf'\n" = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-strata'], returncode=2, stdout="make: Entering di...RY (SOURCE=PATH) and OUT are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:123: eval-strata] Error 2\n').stdout
E        +  and   'error: INVENTORY (SOURCE=PATH) and OUT are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:123: eval-strata] Error 2\n' = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L4-surf', 'eval-strata'], returncode=2, stdout="make: Entering di...RY (SOURCE=PATH) and OUT are both required\nmake: *** [/home/ubuntu/w/L4-surf/mk/evals.mk:123: eval-strata] Error 2\n').stderr

../../scripts/test_make_eval_targets.py:123: AssertionError
=========================== short test summary info ============================
FAILED ../../scripts/test_make_eval_targets.py::test_required_arguments_are_guarded[eval-corpus-inventory]
FAILED ../../scripts/test_make_eval_targets.py::test_required_arguments_are_guarded[eval-face-calibrate]
FAILED ../../scripts/test_make_eval_targets.py::test_required_arguments_are_guarded[eval-strata]
3 failed in 7.21s
```

`git stash pop` restored the production fix. The assertion was never edited.

## Full file after restore

From `apps/prototype-description-service` with `PYTHONPATH=$PWD`:

```text
..............s.......                                                   [100%]
21 passed, 1 skipped in 53.68s
```

0 failed.

`make test-scripts` was not run. The root recipe still names `scripts/hooks` and `.github/hooks`, which are absent from this worktree overlay. That is the known materialisation gap named in the invariants — out of scope; not chased.

## Canon rules and satisfaction

### TEST-15 (verbatim from `~/lane-canon/ENGCANON.md`)

> | TEST-15<a name="test-15"></a> | Reviewing a passing test that guards an invariant, single-source count, or state property | **Prove the green can go red**: a passing test that cannot fail certifies nothing; before trusting it, mutate the production path (break the invariant, inject a second/zero case, corrupt an input) and confirm the assertion catches it; for invariant/count tests, ship the mutation as a permanent discrimination guard (e.g. mis-wire → asserts 2, drop → asserts 0). Watch for assertions on the code's own output rather than observed behavior, and DOM/count checks that never query the real surface (see [[TEST-11]](engineering.md#test-11), [[DBG-01]](engineering.md#dbg-01)) | If production regressed here, would this exact assertion turn red; have I seen it? | S·r | [modern-software-engineering ch-8](../SOURCES.md#src-modern-software-engineering) + [pragmatic-programmer ch-9](../SOURCES.md#src-pragmatic-programmer) |

Satisfaction: the three cases were observed RED on the old `"are both required"` strings, GREEN after the production rewrite, then RED again after `git stash` of `mk/evals.mk` only. The existing assertion (`"is required" in stdout+stderr`) is the discrimination guard; it was not weakened.

### sr-001

`grep -nE 'sr-001|relax compliance|offending code' ~/lane-canon/RULES.md ~/lane-canon/EVALCANON.md ~/lane-canon/ENGCANON.md` returned no matches. The named rule is genuinely absent from the three supplied lane-canon files.

Project-local derived copy in `docs/workbay/constitution.md` (not invented; not a lane-canon row):

> [sr-001] helpful=2 harmful=0 :: Do not relax compliance/lint scripts to silence violations. Fix the offending code.

Satisfaction: `scripts/test_make_eval_targets.py` was not edited. The three production echo strings in `mk/evals.mk` were changed so each missing variable is named and the substring `"is required"` appears, with a usable example.

### Other named EVAL/TEST IDs in the brief

The brief names TEST-15 and sr-001. No other EVAL/MLDATA/FAIR/AUDIT/PROV IDs are assigned to this message-only slice.

## Exact files changed (`git diff --stat HEAD~1`)

Recorded after this commit (production file + this report). Pre-commit production-only stat:

```text
 mk/evals.mk | 6 +++---
 1 file changed, 3 insertions(+), 3 deletions(-)
```

Touched production strings only:

- `eval-face-calibrate`: `REPORT is required (e.g. REPORT=report.json) and MANIFEST is required (e.g. MANIFEST=golden.json)`
- `eval-corpus-inventory`: `IMAGES is required (e.g. IMAGES=corpus/) and OUT is required (e.g. OUT=inventory.json)`
- `eval-strata`: `INVENTORY is required (e.g. INVENTORY=celebs01=inv.jsonl) and OUT is required (e.g. OUT=shortlists.json)`

## HONEST STATUS: COMPLETE

The three assigned production messages now satisfy the existing `"is required"` contract. The assertion file and the root `test-scripts` recipe were not modified.

Out of scope, unchanged, not remaining work for this lane: the overlay gap where `make test-scripts` names missing `scripts/hooks` and `.github/hooks`; `eval-report`'s secondary `MANIFEST and OUT are required` string (the no-args parametrised case still hits the `RUN is required` guard first and is green).
