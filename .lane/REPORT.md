# L8-anchor report

Repair of the confirmed false-green in `test_eval_anchor_check_fails_when_any_single_verifier_fails` (FIR-ORCH-BR-24).

## IMPORT PROVENANCE

Command run before the first pytest invocation:

```text
$ cd /home/ubuntu/w/L1-gate/apps/prototype-description-service && PYTHONPATH=$PWD /home/ubuntu/vlm6-fix/apps/prototype-description-service/.venv/bin/python -c "import scripts.eval_harness.strata as m; print(m.__file__)"
/home/ubuntu/w/L1-gate/apps/prototype-description-service/scripts/eval_harness/strata.py
```

The imported module is under `/home/ubuntu/w/L1-gate`. Evidence below is from this worktree, not the shared venv `.pth` pin.

## RED, GREEN, AND REVERT-RED EVIDENCE

Predicted first failure (TEST-06): current `eval-anchor-check` is three separate Make recipes, so an injected failure of `S2A-determinism-anchor-run` stops after `score`. The new assertion must report `got ['score']` rather than the three-command list.

### B.1 RED — strengthened production test, before the Makefile fix

```text
F                                                                        [100%]
=================================== FAILURES ===================================
_________ test_eval_anchor_check_fails_when_any_single_verifier_fails __________

tmp_path = PosixPath('/tmp/pytest-of-ubuntu/pytest-1951/test_eval_anchor_check_fails_w0')

    def test_eval_anchor_check_fails_when_any_single_verifier_fails(tmp_path: Path) -> None:
        for fail_token in _FAIL_TOKENS:
            leg_path = tmp_path / fail_token
            leg_path.mkdir()
            proc, calls = _run_eval_anchor_check(leg_path, fail_token=fail_token)
>           _assert_injected_failure_was_honored(proc, calls, fail_token)

scripts/eval_harness/tests/test_eval_anchor_check.py:178: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

proc = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L1-gate', 'eval-anchor-check'], returncode=2, stdout="make: Enter.../home/ubuntu/w/L1-gate'\n", stderr='S2A-determinism-anchor-run\nmake: *** [Makefile:668: eval-anchor-check] Error 1\n')
calls = [['run', '--extra', 'dev', 'python', '-m', 'scripts.eval_harness.cli', ...]]
fail_token = 'S2A-determinism-anchor-run'

    def _assert_injected_failure_was_honored(
        proc: subprocess.CompletedProcess[str],
        calls: list[list[str]],
        fail_token: str,
    ) -> None:
        combined = proc.stdout + proc.stderr
>       assert _verifier_commands(calls) == list(_VERIFIER_COMMANDS), (
            f"{fail_token}: expected all three verifiers invoked, got {_verifier_commands(calls)!r}:\n{combined}"
        )
E       AssertionError: S2A-determinism-anchor-run: expected all three verifiers invoked, got ['score']:
E         make: Entering directory '/home/ubuntu/w/L1-gate'
E         make: Leaving directory '/home/ubuntu/w/L1-gate'
E         S2A-determinism-anchor-run
E         make: *** [Makefile:668: eval-anchor-check] Error 1
E         
E       assert ['score'] == ['score', 'sc...w-eval-split']
E         
E         Right contains 2 more items, first extra item: 'score-face'
E         Use -v to get more diff

scripts/eval_harness/tests/test_eval_anchor_check.py:92: AssertionError
=========================== short test summary info ============================
FAILED scripts/eval_harness/tests/test_eval_anchor_check.py::test_eval_anchor_check_fails_when_any_single_verifier_fails
1 failed in 2.46s
```

### Scratch-copy mutation RED (each run separately)

These apply the same `_assert_injected_failure_was_honored` contract to a scratch Makefile. They are not the production target.

**Mutation 1 — `eval-anchor-check` absent entirely** (the case that fooled the original: make exits 2 with zero verifiers):

```text
F                                                                        [100%]
=================================== FAILURES ===================================
__________ test_eval_anchor_check_fail_contract_rejects_absent_target __________

tmp_path = PosixPath('/tmp/pytest-of-ubuntu/pytest-1954/test_eval_anchor_check_fail_co0')

    def test_eval_anchor_check_fail_contract_rejects_absent_target(tmp_path: Path) -> None:
        makefile = _write_scratch_makefile(tmp_path, mode="absent")
        fail_token = _FAIL_TOKENS[0]
        leg = tmp_path / "absent-leg"
        leg.mkdir()
        proc, calls = _run_eval_anchor_check(leg, fail_token=fail_token, makefile=makefile)
>       _assert_injected_failure_was_honored(proc, calls, fail_token)

scripts/eval_harness/tests/test_eval_anchor_check.py:262: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

proc = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L1-gate', '-f', '/tmp/pytest-of-ubuntu/pytest-1954/test_eval_anch...Leaving directory '/home/ubuntu/w/L1-gate'\n", stderr="make: *** No rule to make target 'eval-anchor-check'.  Stop.\n")
calls = [], fail_token = 'S2A-determinism-anchor-run'

    def _assert_injected_failure_was_honored(
        proc: subprocess.CompletedProcess[str],
        calls: list[list[str]],
        fail_token: str,
    ) -> None:
        combined = proc.stdout + proc.stderr
>       assert _verifier_commands(calls) == list(_VERIFIER_COMMANDS), (
            f"{fail_token}: expected all three verifiers invoked, got {_verifier_commands(calls)!r}:\n{combined}"
        )
E       AssertionError: S2A-determinism-anchor-run: expected all three verifiers invoked, got []:
E         make: Entering directory '/home/ubuntu/w/L1-gate'
E         make: Leaving directory '/home/ubuntu/w/L1-gate'
E         make: *** No rule to make target 'eval-anchor-check'.  Stop.
E         
E       assert [] == ['score', 'sc...w-eval-split']
E         
E         Right contains 3 more items, first extra item: 'score'
E         Use -v to get more diff

scripts/eval_harness/tests/test_eval_anchor_check.py:92: AssertionError
=========================== short test summary info ============================
FAILED scripts/eval_harness/tests/test_eval_anchor_check.py::test_eval_anchor_check_fail_contract_rejects_absent_target
1 failed in 0.13s
```

**Mutation 2 — target exists but stops at the first verifier:**

```text
F                                                                        [100%]
=================================== FAILURES ===================================
__________ test_eval_anchor_check_fail_contract_rejects_stop_at_first __________

tmp_path = PosixPath('/tmp/pytest-of-ubuntu/pytest-1952/test_eval_anchor_check_fail_co0')

    def test_eval_anchor_check_fail_contract_rejects_stop_at_first(tmp_path: Path) -> None:
        makefile = _write_scratch_makefile(tmp_path, mode="stop_at_first")
        fail_token = _FAIL_TOKENS[0]
        leg = tmp_path / "stop-leg"
        leg.mkdir()
        proc, calls = _run_eval_anchor_check(leg, fail_token=fail_token, makefile=makefile)
>       _assert_injected_failure_was_honored(proc, calls, fail_token)

scripts/eval_harness/tests/test_eval_anchor_check.py:271: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

proc = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L1-gate', '-f', '/tmp/pytest-of-ubuntu/pytest-1952/test_eval_anch...* [/tmp/pytest-of-ubuntu/pytest-1952/test_eval_anchor_check_fail_co0/stop_at_first.mk:3: eval-anchor-check] Error 1\n')
calls = [['run', '--extra', 'dev', 'python', '-m', 'scripts.eval_harness.cli', ...]]
fail_token = 'S2A-determinism-anchor-run'

    def _assert_injected_failure_was_honored(
        proc: subprocess.CompletedProcess[str],
        calls: list[list[str]],
        fail_token: str,
    ) -> None:
        combined = proc.stdout + proc.stderr
>       assert _verifier_commands(calls) == list(_VERIFIER_COMMANDS), (
            f"{fail_token}: expected all three verifiers invoked, got {_verifier_commands(calls)!r}:\n{combined}"
        )
E       AssertionError: S2A-determinism-anchor-run: expected all three verifiers invoked, got ['score']:
E         make: Entering directory '/home/ubuntu/w/L1-gate'
E         make: Leaving directory '/home/ubuntu/w/L1-gate'
E         S2A-determinism-anchor-run
E         make: *** [/tmp/pytest-of-ubuntu/pytest-1952/test_eval_anchor_check_fail_co0/stop_at_first.mk:3: eval-anchor-check] Error 1
E         
E       assert ['score'] == ['score', 'sc...w-eval-split']
E         
E         Right contains 2 more items, first extra item: 'score-face'
E         Use -v to get more diff

scripts/eval_harness/tests/test_eval_anchor_check.py:92: AssertionError
=========================== short test summary info ============================
FAILED scripts/eval_harness/tests/test_eval_anchor_check.py::test_eval_anchor_check_fail_contract_rejects_stop_at_first
1 failed in 0.25s
```

**Mutation 3 — target runs all three but swallows a non-zero exit:**

```text
F                                                                        [100%]
=================================== FAILURES ===================================
_________ test_eval_anchor_check_fail_contract_rejects_swallowed_exit __________

tmp_path = PosixPath('/tmp/pytest-of-ubuntu/pytest-1953/test_eval_anchor_check_fail_co0')

    def test_eval_anchor_check_fail_contract_rejects_swallowed_exit(tmp_path: Path) -> None:
        makefile = _write_scratch_makefile(tmp_path, mode="swallow")
        fail_token = _FAIL_TOKENS[0]
        leg = tmp_path / "swallow-leg"
        leg.mkdir()
        proc, calls = _run_eval_anchor_check(leg, fail_token=fail_token, makefile=makefile)
>       _assert_injected_failure_was_honored(proc, calls, fail_token)

scripts/eval_harness/tests/test_eval_anchor_check.py:280: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

proc = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L1-gate', '-f', '/tmp/pytest-of-ubuntu/pytest-1953/test_eval_anch...y '/home/ubuntu/w/L1-gate'\nmake: Leaving directory '/home/ubuntu/w/L1-gate'\n", stderr='S2A-determinism-anchor-run\n')
calls = [['run', '--extra', 'dev', 'python', '-m', 'scripts.eval_harness.cli', ...], ['run', '--extra', 'dev', 'python', '-m', 'scripts.eval_harness.cli', ...], ['run', '--extra', 'dev', 'python', '-m', 'scripts.eval_harness.cli', ...]]
fail_token = 'S2A-determinism-anchor-run'

    def _assert_injected_failure_was_honored(
        proc: subprocess.CompletedProcess[str],
        calls: list[list[str]],
        fail_token: str,
    ) -> None:
        combined = proc.stdout + proc.stderr
        assert _verifier_commands(calls) == list(_VERIFIER_COMMANDS), (
            f"{fail_token}: expected all three verifiers invoked, got {_verifier_commands(calls)!r}:\n{combined}"
        )
        assert fail_token in combined, (
            f"{fail_token} was not surfaced in verifier output:\n{combined}"
        )
>       assert proc.returncode != 0, f"{fail_token} failure was ignored:\n{combined}"
E       AssertionError: S2A-determinism-anchor-run failure was ignored:
E         make: Entering directory '/home/ubuntu/w/L1-gate'
E         make: Leaving directory '/home/ubuntu/w/L1-gate'
E         S2A-determinism-anchor-run
E         
E       assert 0 != 0
E        +  where 0 = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L1-gate', '-f', '/tmp/pytest-of-ubuntu/pytest-1953/test_eval_anch...y '/home/ubuntu/w/L1-gate'\nmake: Leaving directory '/home/ubuntu/w/L1-gate'\n", stderr='S2A-determinism-anchor-run\n').returncode

scripts/eval_harness/tests/test_eval_anchor_check.py:98: AssertionError
=========================== short test summary info ============================
FAILED scripts/eval_harness/tests/test_eval_anchor_check.py::test_eval_anchor_check_fail_contract_rejects_swallowed_exit
1 failed in 0.28s
```

The three reds are distinct: absent → `got []` and no `fail_token`; stop-at-first → `got ['score']`; swallow → `assert 0 != 0` after all three ran and the token was printed. The original returncode-only assert cannot tell these apart from a real injected failure.

Those three tests were then inverted into permanent TEST-15 guards that lock the mutation symptoms (`[]` / `['score']` / `returncode == 0`).

### B.3 GREEN — after the continue-then-fail Makefile recipe

```text
.....                                                                    [100%]
5 passed in 10.20s
```

### B.4 REVERT-RED — `git stash` of `Makefile` only, then restore

```text
F                                                                        [100%]
=================================== FAILURES ===================================
_________ test_eval_anchor_check_fails_when_any_single_verifier_fails __________

tmp_path = PosixPath('/tmp/pytest-of-ubuntu/pytest-1956/test_eval_anchor_check_fails_w0')

    def test_eval_anchor_check_fails_when_any_single_verifier_fails(tmp_path: Path) -> None:
        for fail_token in _FAIL_TOKENS:
            leg_path = tmp_path / fail_token
            leg_path.mkdir()
            proc, calls = _run_eval_anchor_check(leg_path, fail_token=fail_token)
>           _assert_injected_failure_was_honored(proc, calls, fail_token)

scripts/eval_harness/tests/test_eval_anchor_check.py:178: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

proc = CompletedProcess(args=['make', '-C', '/home/ubuntu/w/L1-gate', 'eval-anchor-check'], returncode=2, stdout="make: Enter.../home/ubuntu/w/L1-gate'\n", stderr='S2A-determinism-anchor-run\nmake: *** [Makefile:668: eval-anchor-check] Error 1\n')
calls = [['run', '--extra', 'dev', 'python', '-m', 'scripts.eval_harness.cli', ...]]
fail_token = 'S2A-determinism-anchor-run'

    def _assert_injected_failure_was_honored(
        proc: subprocess.CompletedProcess[str],
        calls: list[list[str]],
        fail_token: str,
    ) -> None:
        combined = proc.stdout + proc.stderr
>       assert _verifier_commands(calls) == list(_VERIFIER_COMMANDS), (
            f"{fail_token}: expected all three verifiers invoked, got {_verifier_commands(calls)!r}:\n{combined}"
        )
E       AssertionError: S2A-determinism-anchor-run: expected all three verifiers invoked, got ['score']:
E         make: Entering directory '/home/ubuntu/w/L1-gate'
E         make: Leaving directory '/home/ubuntu/w/L1-gate'
E         S2A-determinism-anchor-run
E         make: *** [Makefile:668: eval-anchor-check] Error 1
E         
E       assert ['score'] == ['score', 'sc...w-eval-split']
E         
E         Right contains 2 more items, first extra item: 'score-face'
E         Use -v to get more diff

scripts/eval_harness/tests/test_eval_anchor_check.py:92: AssertionError
=========================== short test summary info ============================
FAILED scripts/eval_harness/tests/test_eval_anchor_check.py::test_eval_anchor_check_fails_when_any_single_verifier_fails
1 failed in 2.58s
```

Makefile restored via `git stash pop`. Post-restore:

```text
.....                                                                    [100%]
5 passed in 10.46s
```

## SIBLING REVIEW

`test_eval_anchor_check_invokes_the_three_literal_verifiers` does **not** have the same weakness.

- It asserts `proc.returncode == 0`, so a missing target (make exit 2) fails it. That is why the original author's first run and TEST-15 revert-red were red on the sibling, not on the fail-path test.
- It asserts exact equality on the captured `calls` list (all three literal argv vectors). An empty target or a first-only target cannot pass.
- It does not inject a failure, so it cannot certify swallow-vs-propagate. That is the other test's job; the sibling is not false-green for the missing-target trick.

Left unchanged except that it now goes through the shared runner (optional `-f` is unused on this test).

## CANON RULES

Verbatim table rows from `/home/ubuntu/lane-canon/ENGCANON.md`:

### TEST-06

```text
| TEST-06<a name="test-06"></a> | New test about to be run for the first time | **Watch it fail once / predict the failure**: a test never observed failing (with the predicted message) may assert nothing; a tautological assertion (arithmetic on the code's own output, a `const` that cannot change, a proxy that can diverge from the real behavior) certifies zero | What exact failure message do you expect before you run it? | S·w | [modern-software-engineering ch-8](../SOURCES.md#src-modern-software-engineering) |
```

Satisfaction: the predicted message was `expected all three verifiers invoked, got ['score']`. The first run of the strengthened test produced that exact assertion (B.1). A returncode-only assert would have been green on that same Makefile.

### TEST-15

```text
| TEST-15<a name="test-15"></a> | Reviewing a passing test that guards an invariant, single-source count, or state property | **Prove the green can go red**: a passing test that cannot fail certifies nothing; before trusting it, mutate the production path (break the invariant, inject a second/zero case, corrupt an input) and confirm the assertion catches it; for invariant/count tests, ship the mutation as a permanent discrimination guard (e.g. mis-wire → asserts 2, drop → asserts 0). Watch for assertions on the code's own output rather than observed behavior, and DOM/count checks that never query the real surface (see [[TEST-11]](engineering.md#test-11), [[DBG-01]](engineering.md#dbg-01)) | If production regressed here, would this exact assertion turn red; have I seen it? | S·r | [modern-software-engineering ch-8](../SOURCES.md#src-modern-software-engineering) + [pragmatic-programmer ch-9](../SOURCES.md#src-pragmatic-programmer) |
```

Satisfaction:
- The production fail-path test now asserts observed `_calls` (three CLI names) and the injected `fail_token` in combined output, not make's generic nonzero.
- Each named mutation was run in a scratch copy and produced a distinct red.
- Those mutations shipped as permanent tests: absent → asserts `[]` and no token; stop-at-first → asserts `['score']`; swallow → asserts `returncode == 0` after all three ran.
- Production fix was stashed (`Makefile` only); the fail-path test went red again; the fix was restored.

## MAKEFILE CHANGE (allowlist, justified)

The default expectation was tests only. The strengthened contract requires all three verifiers to be **invoked** even when one is injected-fail. GNU make's per-recipe fail-fast cannot do that: an early `score` failure never reaches `score-face` or `draw-eval-split`. That is mutation 2, which must stay red.

The target is now one recipe: run each verifier in a subshell, record `status=1` on any failure, `exit $$status`. uv argv is unchanged, so the sibling's literal call list still holds. No frozen anchor, digest, or verifier body was touched.

## EXACT FILES CHANGED

`git diff --stat` of the commit contents (equals `git diff --stat HEAD~1` once this commit is HEAD):

```text
 .lane/REPORT.md                                    | 440 +++++++++++----------
 Makefile                                           |  14 +-
 .../eval_harness/tests/test_eval_anchor_check.py   | 168 +++++++-
 3 files changed, 408 insertions(+), 214 deletions(-)
```

## HONEST STATUS: COMPLETE

Strengthened fail-path test requires (1) all three verifiers invoked via captured `_calls` and (2) the injected `fail_token` in combined output, plus nonzero exit. Three permanent scratch-makefile guards ship the named mutations. Makefile continue-then-fail is the minimum production change that can satisfy "all three invoked" when an early verifier fails. Sibling reviewed; no same-weakness fix needed.
