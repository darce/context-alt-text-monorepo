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

---

# Lane R7-gsplit — FIR-12-BR-65 / FIR-12-BR-66

## Finding: both target defects were already fixed in base b2ad134a

Scope was `apps/prototype-description-service/scripts/eval_harness/gallery_split.py`
and its tests (`apps/prototype-description-service/scene/tests/test_eval_harness_gallery_split.py`).
Before writing anything, I read the current file and found the guard tests the
brief said don't exist already present at test file lines 650-754:

- `test_gallery_map_key_subject_mismatch_raises[g1|g2]` (BR-65, map-level check,
  `gallery_split.py` `_normalise_gallery_map` ~L183-192)
- `test_builder_roster_key_subject_mismatch_raises` (BR-65, `_as_template` roster-key
  check, ~L234-241)
- `test_withheld_probe_templates_are_sorted_and_stripped_independent_of_insertion`
  (BR-66, constructor-site `withheld_probe_templates` normalisation, ~L104-110)

`git log --oneline -- <test file>` traces these to commit
`a829e663d9b3bf94440730afac24c07daf80a2dd` ("fix(eval): FIR-12 BR-65/BR-66 pin key
mismatch and withheld normalisation", lane F40), which is an ancestor of this lane's
base `b2ad134a` (merged into `int/round4` via `lane-f42`'s merge chain before this
lane started). No code or test edit was needed or made in this lane — writing a
second, near-duplicate set of tests over the same guards would not add coverage.

Per TEST-15 / "independent review beats self-triage" I did not take lane F40's own
report (`docs/tasks/fir/lane-reports/F40.md`) on faith. I re-ran all three control
mutants myself on the remote gate, independently, from a clean b2ad134a tree, one
throwaway commit per mutant, reverted with `git reset --hard HEAD~1` after each RED
confirmation. Working tree is clean at `b2ad134a` again; no fix commits exist for
Fix 1 / Fix 2 because there was nothing left to fix.

## Mutant A — BR-65, `_normalise_gallery_map` raise arm (gallery_split.py ~L186-189)

Deleted:
```python
if template_key != key:
    raise GallerySplitError(
        f"{gallery} key {key!r} holds template for {template.subject_id!r}"
    )
```
Gate (`gate-lane.sh r7-gsplit -k gallery_split`), commit `48babf2cd` (reverted):
```
FAILED scene/tests/test_eval_harness_gallery_split.py::test_gallery_map_key_subject_mismatch_raises[g1]
FAILED scene/tests/test_eval_harness_gallery_split.py::test_gallery_map_key_subject_mismatch_raises[g2]
2 failed, 33 passed, 1638 deselected in 12.18s
```
RED confirmed independently.

## Mutant B — BR-65, `_as_template` roster-key raise (gallery_split.py ~L238-241)

Deleted:
```python
if template_subject != canonical_subject:
    raise GallerySplitError(
        f"template {value.template_id!r} subject_id {value.subject_id!r} "
        f"does not match roster key {subject_id!r}"
    )
```
Gate, commit `5d4a417f3` (reverted):
```
FAILED scene/tests/test_eval_harness_gallery_split.py::test_builder_roster_key_subject_mismatch_raises
1 failed, 34 passed, 1638 deselected in 5.19s
```
RED confirmed independently. (The map-level test stays green here, as expected —
it exercises the other check.)

## Mutant C — BR-66, constructor-site withheld normalisation (gallery_split.py ~L104-110)

Replaced:
```python
_normalise_template_tuple(
    self.withheld_probe_templates, gallery="withheld_probe_templates"
),
```
with a bare `tuple(self.withheld_probe_templates),`.
Gate, commit `4a55c1106` (reverted):
```
FAILED scene/tests/test_eval_harness_gallery_split.py::test_withheld_probe_templates_are_sorted_and_stripped_independent_of_insertion
AssertionError: assert [('Zoe ', 'z1'), ('Ann ', 'n1')] == [('Ann', 'n1'), ('Zoe', 'z1')]
1 failed, 34 passed, 1638 deselected in 5.02s
```
RED confirmed independently.

All three throwaway mutant commits were reset out (`git reset --hard HEAD~1`);
`git status` and `git diff --stat b2ad134a` are both clean. No full-suite gate
re-run was needed post-change since no production or test line differs from the
given baseline (`1668 passed, 4 skipped, 1 deselected, 14 warnings`, per the
operator-supplied baseline — not re-measured, per instructions).

## Dead-invariant sweep (optional item)

`_assert_invariants` (gallery_split.py L340-395) is called only from
`build_disjoint_galleries`, before the `GallerySplit(...)` constructor runs.
One check shares the exact rewrite-blindness shape the brief already named for
`GallerySplit.__post_init__`:

- **L369-375** (dead):
  ```python
  for gallery_name, gallery in (("g1", g1), ("g2", g2)):
      for subject_id, template in gallery.items():
          if template.subject_id != subject_id:
              raise GallerySplitError(...)
  ```
  By the time `build_disjoint_galleries` populates `g1`/`g2`, every `Template` in
  them has already passed through `_as_template`, which calls
  `_with_subject(value, canonical_subject)` **unconditionally after** its own
  roster-key check — including under mutant B, where the check that should have
  raised is gone but the rewrite still runs. So `template.subject_id` is always
  already forced equal to the dict key by the time this loop inspects it; it is
  a sensor reading a value the actuator already normalised, canon OBS-12 ("sensors
  must touch the controlled stock" — this one touches the stock only after
  something else already wrote to it). Confirmed live-dead by mutant B above: the
  builder test still went RED, but via the earlier `_as_template` path being the
  *only* thing that could catch it — this copy fired for neither mutant A nor B in
  either of my runs.

No other check in `_assert_invariants` shares this failure mode:
- **L347-359** (`g1_ids & g2_ids`, `g1_ids/g2_ids & probe_ids`) key off
  `template_id`, a field `_with_subject` never touches — dead only if
  `build_disjoint_galleries`'s own `seen_ids` duplicate-id check (elsewhere in
  the function, upstream of `_assert_invariants`) is also live; not the same
  rewrite mechanism, not investigated further here (out of scope for this lane).
- **L360-368** (`dropped`, `both`) key off dict *keys*, which come straight from
  the roster loop's own normalised `subject_id`, never from `template.subject_id`
  — unaffected by the `_with_subject` rewrite.
- **L379-391** (media disjointness) and **L392-396** (empty gallery) operate on
  `media_ids` / dict emptiness, fields `_with_subject` does not rewrite.

Filing as a separate finding per instructions — not fixed in this lane.

## Unfinished work

None within the assigned scope. The L369-375 dead check above is reported, not
fixed, per the brief's explicit "do NOT fix them this lane" instruction.

---

# FIR-12 R7-pred: single authority for accept predicate (BR-63/69/71)

## Summary

Created `apps/prototype-description-service/scripts/eval_harness/accept_predicate.py`
exporting `is_fpi`, `is_fnir_miss`, `accepts`. Routed the seven divergent
literal tie-at-tau comparisons through these helpers, preserving each site's
current inequality bit-for-bit. No behaviour change; gate is green at the
same pass count plus the new test file, zero failures.

## Post-change gate (full suite, r7-pred @ 85e41a20f)

```
1684 passed, 4 skipped, 1 deselected, 14 warnings in 60.76s (0:01:00)
```

Baseline was `1668 passed, 4 skipped, 1 deselected, 14 warnings` (given, not
re-measured). Delta = +16, exactly the 16 new tests in
`test_accept_predicate.py` (3 + 3 + 3 + 1 + 6 parametrized). Zero failures.

## Seven call sites: before -> after

| Module | Site | Role | Before | After |
|---|---|---|---|---|
| `calibrate_face_thresholds.py` | `fmr_at` (~L645) | selection metric | `s > tau` | `is_fpi(s, tau)` |
| `calibrate_face_thresholds.py` | OOF sweep FPI counter (~L789) | selection metric | `s > tau` | `is_fpi(s, tau)` |
| `open_set_identification.py` | `_is_fpi` (~L124) | published metric | `score > tau` | `is_fpi(score, tau)` |
| `open_set_identification.py` | `_is_fnir_miss` (~L101) | published metric | `score < tau` | `is_fnir_miss(score, tau)` |
| `face_assignment.py` | `open_set_counts_at_tau` (~L383) | apply path | `s_max >= tau` | `accepts(s_max, tau)` |
| `face_assignment.py` | k-fold apply site (~L672) | apply path | `s_max >= tau` | `accepts(s_max, tau)` |
| `face_assignment.py` | Hungarian assignment site (~L841) | apply path | `s >= tau` | `accepts(s, tau)` |
| `synthetic_occlusion.py` | occlusion recovery accept (~L552) | apply path | `s_max >= float(tau)` | `accepts(s_max, float(tau))` |

`open_set_identification._is_fnir_miss` was not one of the originally-listed
seven (it was already at the correct inequality) but is explicitly named in
scope ("if present") and is now routed for structural lockstep too.
`synthetic_occlusion.py`'s two prose comments (module docstring, protocol
disclosures tuple) now point at `accept_predicate` instead of restating the
inequality in words.

Out of scope, deliberately untouched: `calibrate_face_thresholds.fnmr_at`
and the OOF sweep's FNIR-miss counter (`s < tau`, ~L785) — these were not
part of the seven-site inventory in the brief and were already internally
consistent with `is_fnir_miss`'s semantics; touching them would be scope
creep beyond the named findings.

## Control mutants (TEST-15: prove the green can go red)

Each helper's inequality was flipped in place, pushed to the gate VM,
re-run filtered to `-k accept_predicate`, confirmed RED, then reverted
(`git revert`) before the next mutant. Working tree after all three mutants
diffs empty against the pre-mutant commit (confirmed via `git diff`), so the
mutant/revert commits were squashed out of history with `git reset --soft`
back to the clean refactor commit — final history is the two substantive
commits only.

1. `is_fpi`: `score > tau` -> `score >= tau`
   ```
   FAILED scripts/eval_harness/tests/test_accept_predicate.py::TestIsFpiBoundary::test_at_tau_is_not_fpi
   FAILED scripts/eval_harness/tests/test_accept_predicate.py::test_fpi_and_fnir_miss_never_both_true_at_a_tie
   FAILED scripts/eval_harness/tests/test_accept_predicate.py::test_selection_and_apply_predicates_agree_off_the_exact_tie[0.0]
   FAILED scripts/eval_harness/tests/test_accept_predicate.py::test_selection_and_apply_predicates_agree_off_the_exact_tie[0.2]
   FAILED scripts/eval_harness/tests/test_accept_predicate.py::test_selection_and_apply_predicates_agree_off_the_exact_tie[0.5]
   FAILED scripts/eval_harness/tests/test_accept_predicate.py::test_selection_and_apply_predicates_agree_off_the_exact_tie[0.6180339887]
   FAILED scripts/eval_harness/tests/test_accept_predicate.py::test_selection_and_apply_predicates_agree_off_the_exact_tie[0.9]
   FAILED scripts/eval_harness/tests/test_accept_predicate.py::test_selection_and_apply_predicates_agree_off_the_exact_tie[1.0]
   8 failed, 8 passed, 1673 deselected in 4.83s
   ```

2. `is_fnir_miss`: `score < tau` -> `score <= tau`
   ```
   FAILED scripts/eval_harness/tests/test_accept_predicate.py::TestIsFnirMissBoundary::test_at_tau_is_not_a_miss
   FAILED scripts/eval_harness/tests/test_accept_predicate.py::test_fpi_and_fnir_miss_never_both_true_at_a_tie
   2 failed, 14 passed, 1673 deselected in 4.90s
   ```

3. `accepts`: `score >= tau` -> `score > tau`
   ```
   FAILED scripts/eval_harness/tests/test_accept_predicate.py::TestAcceptsBoundary::test_at_tau_accepts
   FAILED scripts/eval_harness/tests/test_accept_predicate.py::test_selection_and_apply_predicates_agree_off_the_exact_tie[0.0]
   FAILED scripts/eval_harness/tests/test_accept_predicate.py::test_selection_and_apply_predicates_agree_off_the_exact_tie[0.2]
   FAILED scripts/eval_harness/tests/test_accept_predicate.py::test_selection_and_apply_predicates_agree_off_the_exact_tie[0.5]
   FAILED scripts/eval_harness/tests/test_accept_predicate.py::test_selection_and_apply_predicates_agree_off_the_exact_tie[0.6180339887]
   FAILED scripts/eval_harness/tests/test_accept_predicate.py::test_selection_and_apply_predicates_agree_off_the_exact_tie[0.9]
   FAILED scripts/eval_harness/tests/test_accept_predicate.py::test_selection_and_apply_predicates_agree_off_the_exact_tie[1.0]
   7 failed, 9 passed, 1673 deselected in 4.87s
   ```

All three mutants confirmed RED; all three reverted; post-revert diff empty.

## Midpoint-readiness confirmation

`select_threshold`'s known live defect (tau_proposed=0.58 landing exactly on
fixture media_id=301's impostor score) is NOT fixed in this commit, per
instructions — this is a behaviour-hat change for a later lane. The real fix
(making candidate thresholds midpoints between consecutive unique observed
scores, so no chosen tau ever equals an observed score) is a one-line edit
plus golden updates, and `accept_predicate.py` is shaped to make that trivial:
- `is_fpi` / `is_fnir_miss` / `accepts` all take `(score, tau)` as plain
  floats — nothing in their signature or body depends on how `tau` was
  chosen, so `select_threshold` can start emitting midpoint candidates
  without any change to this module.
- Once candidates are midpoints, `score == tau` becomes unreachable by
  construction, so `is_fpi`/`accepts` stop disagreeing at any observed data
  point — no predicate-level change required, only the calibrator's
  candidate-generation step.
- `accepts.__doc__` already documents the gap and why it exists, so the
  follow-up commit only needs to update `select_threshold`'s candidate
  generation and the golden fixtures/pins that shift as a result.

## Unfinished / deferred (by design, not by omission)

- `select_threshold` midpoint-candidate fix: explicitly out of scope (separate
  behaviour-hat commit named in the brief).
- `calibrate_face_thresholds.fnmr_at` and the OOF sweep's FNIR-miss counter:
  not part of the seven-site inventory; left untouched to avoid scope creep.
- No golden/pin files changed; none should have, and none did.

## Follow-up commit (FIR-12-BR-77/78, coordinator-flagged)

Coordinator caught a brief error I followed correctly: the brief said "update
the two prose comments in synthetic_occlusion (lines 9 and 84)". Line 9
(module docstring) is genuinely source prose and the original edit there was
correct. Line ~85 is not a comment — it's an entry in
`SYNTHETIC_OCCLUSION_PROTOCOL_DISCLOSURES`, which `report.py:162` splices
into `FACE_BAKEOFF_PROTOCOL_DISCLOSURES` (published output consumed by
`_entry_is_publishable`). My original edit had replaced the mathematical
statement `(s_max >= tau)` with a bare module pointer
`(accept_predicate.accepts)` in that published string — an external report
reader can evaluate the math, not the module.

**Fix**: restored the inequality and appended the pointer rather than
substituting it: `"... open-set threshold (s_max >= tau; see
accept_predicate.accepts), not closed-set ..."`. Also fixed
`synthetic_occlusion.py`'s `accept_predicate` import from relative
(`from .accept_predicate import accepts`) to the absolute form
(`from scripts.eval_harness.accept_predicate import accepts`) used by the
other three routed sites, for consistency.

**New golden test**: added
`test_threshold_rule_disclosure_is_self_contained_published_text` to
`scene/tests/test_eval_harness_synthetic_occlusion.py`, pinning the exact
disclosure string (verified byte-for-byte against the source AST, not
hand-transcribed) and asserting `"s_max >= tau"` is present in it.

**Post-fix gate** (full suite, r7-pred @ 07ae29670):
```
1685 passed, 4 skipped, 1 deselected, 14 warnings in 63.93s (0:01:03)
```
+1 over the prior 1684, exactly the new golden test. Zero failures.

**Control mutant** — reworded the disclosure back to the bare-pointer form,
pushed, gated filtered to the new test, confirmed RED, reverted (`git
revert`), confirmed post-revert diff empty against `07ae29670`, then
squashed the mutant/revert pair out of history with `git reset --soft`:
```
FAILED scene/tests/test_eval_harness_synthetic_occlusion.py::test_threshold_rule_disclosure_is_self_contained_published_text
1 failed, 1689 deselected in 4.79s
```

Final history: three substantive commits (`f269eefa0`, `1914eb524`,
`07ae29670`), no mutant noise.
