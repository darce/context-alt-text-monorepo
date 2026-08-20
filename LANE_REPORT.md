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
