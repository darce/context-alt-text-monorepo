# Lane r8b report — FIR-12 BR-79

## Outcome

Hoisted probe-stratum exemption into `_is_exempt_probe_stratum(plan, name)` and made both `_never_measured_probe_strata` and `_missing_required_probe_searches` call it. Neither guard retains an exemption literal.

The single exemption rule is: a probe stratum is exempt only when the manifest explicitly lists it in `declared_empty_cells`.

## Baseline

Command (from `apps/prototype-description-service`):

```text
PYTHONPATH=$PWD /home/ubuntu/vlm6-fix/apps/prototype-description-service/.venv/bin/python -m pytest scene/tests/test_eval_harness_fir_bakeoff_run.py scene/tests/test_eval_harness_bakeoff_report.py scripts/eval_harness/tests -q -p no:cacheprovider
```

The run collected 404 tests but did not complete. It reached 162 passing tests with no failures, then produced no output for approximately 14 minutes and was interrupted. A diagnostic rerun with `-vv` identified the stall at 40% in the existing out-of-scope test `scripts/eval_harness/tests/test_cli_exit_gates.py::test_fusion_runner_exits_3_on_roster_only_bakeoff`; it likewise produced no result for several minutes and was interrupted. Therefore no honest complete baseline count is available.

Before the behavior change, the directly owned test module completed with **74 passed, 0 failed** in 2.06s after the neutral predicate extraction.

## REF-05 commit separation

The work was prepared in two independently green stages:

1. Neutral refactor: introduce `_is_exempt_probe_stratum` with the existing never-measured rule and route `_never_measured_probe_strata` through it. Verification: **74 passed, 0 failed**.
2. Behavior: route `_missing_required_probe_searches` through the predicate, remove its implicit-zero exemption, and add/update regression tests. Verification: **78 passed, 0 failed**.

The required commits could not be created because `.git` is mounted read-only in this lane. The first `git commit` attempt failed exactly with:

```text
fatal: Unable to create '/home/ubuntu/l1/r8b/.git/index.lock': Read-only file system
```

Consequently the two stages could not be recorded as separate commits, and this report itself could not be committed. No commit attribution trailers were added.

## Disagreement decision and evidence

The prior guards disagreed for a `PROBE_STRATA` member absent from `strata_counts` and absent from `declared_empty_cells`:

- `_never_measured_probe_strata` did **not** exempt it.
- `_missing_required_probe_searches` did exempt it because `declared_images.get(name, 0) <= 0` treated missing metadata as an implicit empty declaration.

The never-measured side is correct. Absence of a count is not affirmative evidence of an intentionally empty workload; `declared_empty_cells` is the manifest's explicit mechanism for that decision. The existing BR-68 fixture supplies the concrete evidence: `D_capture` absent from the manifest yielded no point. Exempting its missing search lets that never-measured `D_capture` cell pass the earlier completeness guard. The updated regression requires scoring to reject that missing `D_capture` search before publication.

Behavior is unchanged for every case where the guards previously agreed: explicitly declared-empty cells remain exempt, and populated/non-empty declared probe strata remain required.

## TEST-15 mutant proof

Mutant applied to `_missing_required_probe_searches` only:

```diff
 def _missing_required_probe_searches(...):
     missing: list[str] = []
     for name in PROBE_STRATA:
+        if name == "D_capture":  # TEST-15 mutant: divergent one-guard exemption
+            continue
         if _is_exempt_probe_stratum(plan, name):
             continue
```

Command:

```text
PYTHONPATH=$PWD /home/ubuntu/vlm6-fix/apps/prototype-description-service/.venv/bin/python -m pytest scene/tests/test_eval_harness_fir_bakeoff_run.py -q -p no:cacheprovider
```

RED result: **5 failed, 73 passed** in 2.53s.

The new parametrized guard-agreement test failed for `A_true_occluder`, `B_eyewear`, and `C_pose`; the updated absent-`D_capture` BR-68 test also failed, as did the existing populated-probe-strata guard test. This proves the new test can detect a one-guard-only exemption.

The mutant was reverted exactly. GREEN result: **78 passed, 0 failed** in 2.15s.

## Final verification

- Directly owned module: **78 passed, 0 failed** in 2.15s.
- `git diff --check`: passed.
- Complete owned suite: no final count, because the same existing fusion-runner test that blocked baseline did not complete; see Baseline.

## Unresolved environment constraints

- Git metadata is read-only, preventing both required commits and a clean committed handoff.
- A pre-existing untracked `codex.log` was present from the initial status check. It is outside this lane's owned files and was not modified or removed.
- Because the implementation and report are necessarily uncommitted and `codex.log` remains untracked, the requested clean working tree could not be achieved without violating file ownership or filesystem permissions.
