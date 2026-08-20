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
