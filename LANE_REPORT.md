# FIR-12 R7 Bake-off Lane Report

Worktree: `context-alt-text-monorepo-r7-bakeoff`, branch `feature/fir12-r7-bakeoff`, base `b2ad134a7`.
Owned files: `scripts/eval_harness/fir_bakeoff_run.py`, `scripts/eval_harness/strata_join.py`,
`scene/tests/test_eval_harness_fir_bakeoff_run.py`.

## Final gate result (all four fixes applied, HEAD `4a2a031b9`)

```
1674 passed, 4 skipped, 1 deselected, 14 warnings in 62.29s (0:01:02)
```

Zero failures. Baseline was `1668 passed, 4 skipped, 1 deselected, 14 warnings` — net +6 passing
(4 new BR-75 tests, 1 new BR-73 test, 1 new BR-68 test; BR-74 extended an existing test's fixture,
no net-new test).

## Fix 1 — FIR-12-BR-75 (normalise identities at ingest) — commit `c3dc1c047`

**Contract decision**: a blank-after-strip or non-string `present_identities` item is a manifest
defect and is rejected at parse (`FirBakeoffRunError` / `StratumJoinError`), not skipped. Rationale:
sr-006 — fail closed at the boundary rather than let a malformed item crash downstream at point of
use (membership lookup) or silently vanish from the census. `_identities()` in `fir_bakeoff_run.py`
and `_entry_identities()` in `strata_join.py` both now delegate to strip-and-validate helpers using
the same alphabet as the existing `_normalise_subject_id` (strip, reject blank/non-string).

Control mutant (reverted `_entry_identities` to bare `str(item) for item in value if item`):
```
4 failed, 1674 deselected in 5.06s
```
(all 4 new BR-75 tests failed, e.g. `AssertionError: assert 5 == 4` on the census test). Restored via
`git reset --hard 91ff20212`, confirmed clean.

## Fix 2 — FIR-12-BR-73 (dedup mated search units) — commit `91ff20212`

**Contract decision**: `mated_identities_for` dedups by normalised key, preserving first-seen order,
rather than raising on a repeat. Rationale: by the time an identity reaches this function it has
already passed BR-75 ingest validation, so a repeated mention reads as "this subject is present"
stated twice, not as corrupt data — treating it as an error would be punitive for a manifest
authoring mistake that costs nothing to absorb here.

Control mutant (reverted the `seen: set[str]` dedup guard, restoring the append-without-guard loop):
```
1 failed, 1677 deselected in 4.93s
```
(`AssertionError: assert ('Bob', 'Bob') == ('Bob',)`). Restored via `git reset --hard 91ff20212`,
confirmed clean.

## Fix 3 — FIR-12-BR-68 (overall.incomplete rolls up over declared strata) — commit `7673e44d2`

**Contract decision**: `overall.incomplete` now rolls up over the declared `PROBE_STRATA` set, not
the observed `points` keys. A declared stratum absent from `points` (zero join rows) counts as
incomplete unless the manifest explicitly marks it via `declared_empty_cells`. The new
`RunReport.never_measured_probe_strata` field carries the "never measured" reason distinctly from
"measured and short" (`points[name].incomplete`), so callers/reports can tell the two failure modes
apart instead of collapsing them into one boolean.

Full-suite gate with the new test in place: `1674 passed, ...` (see above), zero failures.

Control mutant (dropped the `never_measured` term from `overall_incomplete`, restoring the buggy
`any(points[name].incomplete for name in PROBE_STRATA if name in points)`):
```
1 failed, 1678 deselected in 5.03s
AssertionError: assert False is True
 +  where False = BakeoffIETPoint(... incomplete=False).incomplete
```
Restored via `git reset --hard 7673e44d2`, confirmed clean (`grep -c MUTANT` → 0).

## Fix 4 — FIR-12-BR-74 (Unicode alphabet for twin-normaliser test) — commit `4a2a031b9`

**Contract decision**: replaced the ASCII-only `_IDENTITY_KEY_SAMPLES` literal with a generated
alphabet covering NBSP, em space, line separator, CR/LF/CRLF padding, and an NFC/NFD pair, since
`gallery_split.py` (the twin implementation this test pins against) is owned by another agent and
out of scope to edit here. Both twins strip via bare `str.strip()`, which treats all of the added
whitespace code points as strippable, so the old ASCII-only denylist could not have caught a future
divergence (e.g. one twin narrowing to an ASCII-only strip) on any of them.

This fix modified an existing test's fixture rather than adding a new test, so the MANDATORY EVIDENCE
PROTOCOL's "for every new test" clause doesn't strictly apply — but to prove the fixture change adds
real value, the mutant below shows the new samples catching a divergence the old ASCII-only set would
have missed:

Control mutant (narrowed the local `_normalise_subject_id` to `value.strip(" \t\r\n")`, an ASCII-only
strip that diverges from the untouched `gallery_split` twin on the new NBSP/em-space/line-separator
samples):
```
1 failed, 1678 deselected in 4.86s
AssertionError: assert '\xa0Bob' == 'Bob'
```
Restored via `git reset --hard 4a2a031b9`, confirmed clean (`grep -c MUTANT` → 0).

## Unfinished work

None. All four fixes (BR-75, BR-73, BR-68, BR-74) are implemented, committed separately, gate-verified
green together (`1674 passed`, zero failures), and each has a confirmed-RED control mutant that was
restored before landing.

---

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
