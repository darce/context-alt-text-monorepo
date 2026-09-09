# Lane r8d report — FIR-12 BR-80

## Outcome

Implemented an always-on pytest collection-scope receipt and terminal summary in
`apps/prototype-description-service/conftest.py`. The repo-owned
`--require-full-collection` boolean flag rejects narrowed collection. A narrow
run without the flag remains valid and still writes `scope=narrowed`.

The configured machine-readable receipt is:

`/tmp/prototype-description-service-pytest-collection-scope.json`

Its JSON fields are `declared_roots`, `collected_roots`, `collected_count`, and
`scope` (`full` or `narrowed`). An optional
`--collection-scope-receipt=PATH` override makes isolated testing possible.

## Baseline and final counts

Required owned-suite command (used exactly from the service directory):

```text
PYTHONPATH=$PWD /home/ubuntu/vlm6-fix/apps/prototype-description-service/.venv/bin/python -m pytest scripts/eval_harness/tests -q -p no:cacheprovider
```

- Baseline: no completed pass/fail count is available. The run reached 22%
  (82 visible passing progress dots, no visible failure) and then emitted no
  further output for roughly ten minutes; it was interrupted. I do not claim
  this as green.
- Final owned suite: no completed pass/fail count is available. A second run
  again reached 22% (82 visible passing progress dots, no visible failure),
  remained silent for several minutes, and was interrupted. I do not claim
  this as green.
- Final focused owned test file: **3 passed, 0 failed in 1.51s**.
- Real declared collection, collect-only with enforcement: **3943 collected,
  0 guard failures in 22.09s**. Receipt verdict was `full`; collected roots were
  `recognition/tests`, `scene/tests`, and `scripts/eval_harness/tests`.

The two configured `apps/prototype-description-service/...` testpath spellings
do not exist relative to the pytest root on this checkout. They remain visible
in `declared_roots`, but only existing declared roots participate in the full
verdict. Otherwise a bare, declared-scope run could never be full.

## TEST-15 mutant evidence

All mutants were applied to production `conftest.py`, tested with the focused
three-test file using the required pytest invocation, and reverted.

### Mutant 1 — disable hard enforcement

```diff
-    if config.getoption("--require-full-collection") and scope != "full":
+    if config.getoption("--require-full-collection") and False:
```

Result at the time (before the no-flag test was added): **1 failed, 1 passed**.
`test_narrowed_collection_is_rejected_and_receipted` failed because the inner
narrowed run returned 0. The full-scope test passed. This proves the narrowed
hard-assertion guard can go red.

### Mutant 2 — invert the verdict

```diff
-    scope = "full" if expected and collected == expected else "narrowed"
+    scope = "narrowed" if expected and collected == expected else "full"
```

Result with the final three tests: **3 failed, 0 passed**. The no-flag narrowed
receipt incorrectly said `full`, the flagged narrowed run was not rejected,
and the full run was rejected as narrowed. This proves every final test can go
red and proves receipt verdicts in both directions are guarded.

After reverting all mutants, the same focused command produced **3 passed,
0 failed**.

## Judgement calls and evidence

- Enforcement occurs in `pytest_collection_finish`, after item collection and
  receipt writing. Evidence: a flagged narrowed subprocess exits nonzero while
  its receipt is readable and says `scope=narrowed`, count 1.
- `--require-full-collection` is a `store_true` flag. It has no disable value;
  a value-like typo is an unknown pytest argument rather than silently false.
- Collected roots are derived from collected item paths, not command-line text.
  Evidence: the isolated full run uses no positional paths and records both
  roots; the isolated narrowed run selects `tests_a` and records only it.
- The receipt defaults to `/tmp` so routine pytest runs do not dirty the repo;
  the stable path remains available for post-hoc VM inspection.
- There was no restructuring commit: all source changes are new behavior and
  its tests, so REF-05's required refactor-first split does not apply.

## Gate handoff and remaining limitation

This closes only the in-repo half. The VM gate script must run exactly:

```text
cd /home/ubuntu/l1/r8d/apps/prototype-description-service
PYTHONPATH=$PWD /home/ubuntu/vlm6-fix/apps/prototype-description-service/.venv/bin/python -m pytest --require-full-collection -q -p no:cacheprovider
```

It must not append positional test paths, because those paths narrow pytest's
configured `testpaths` and will now fail the guard.

Until that script is changed, scope enforcement still depends on an untracked
caller.

I did not edit VM infrastructure because it is outside this lane.

## Transport and workspace limitations

The implementation commit attempt failed because this execution environment
mounts `.git` read-only:

```text
fatal: Unable to create '/home/ubuntu/l1/r8d/.git/index.lock': Read-only file system
```

Therefore I could not commit either implementation or this report. The repo
also began with an unrelated untracked `codex.log`, outside the owned-file
list; I did not touch it. These environment constraints prevent a literally
clean, fully committed working tree despite the owned changes being complete.
