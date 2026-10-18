# Lane r8a report — FIR-12 BR-63/69/71/72

## Outcome

Implemented the requested midpoint threshold candidates and routed both genuine-miss checks through `accept_predicate.is_fnir_miss`. No fixture changed. The writable source/test changes are complete, but the lane cannot satisfy the commit/clean-tree requirements because `.git` is mounted read-only in this environment. `git commit` failed with `Unable to create '/home/ubuntu/l1/r8a/.git/index.lock': Read-only file system`. The pre-existing untracked, out-of-scope `codex.log` also remains untouched.

The read-only regression test `scene/tests/test_eval_harness_open_set_identification.py::test_calibrated_tau_agrees_with_published_fpi_and_fnir_on_tie` is incompatible with this task: it explicitly asserts `tau in impostor_scores`, while FIR-12 requires the selected interior tau not to equal an observed score. It passed at baseline and is the only final owned-suite failure; that file was not edited.

## Baseline and refactor-only verification

Exact baseline command was the prescribed owned-suite invocation. Result: **53 passed, 0 failed**.

Commit-1 content was restricted to:

```diff
-from scripts.eval_harness.accept_predicate import is_fpi
+from scripts.eval_harness.accept_predicate import is_fnir_miss, is_fpi
-    missed = sum(1 for s in scores if s < tau)
+    missed = sum(1 for s in scores if is_fnir_miss(s, tau))
-                if s < tau:
+                if is_fnir_miss(s, tau):
```

After this refactor-only change, the same suite result was **53 passed, 0 failed**, proving bit-identical behavior. The required refactor commit could not be created due to the read-only `.git` mount; consequently the later behavior change is present in the working tree but not improperly combined in a commit.

## Behavior change and judgement calls

- Candidates are `{0.0, 1.0}` plus `(lower + upper) / 2` for each consecutive pair of sorted unique finite observed scores. Duplicate observations are collapsed before midpoint construction.
- The search remains ascending and returns the first candidate with JANUS FMR `<= fmr_target`.
- Zero impostors and all-non-finite impostors still return `None`.
- If no candidate meets the target, the fallback remains `max(1.0, peak observed finite score)`. The peak is now taken explicitly from `observed`, because observed scores are no longer candidates.
- Bounds remain literal contract candidates. The no-observed-tie guarantee applies to selected interior midpoint candidates; the mandated bounds and fail-closed peak can necessarily coincide with an observation in boundary/fallback cases.
- Public protocol disclosure now states midpoint construction and why it prevents observed-score disagreement.
- No RNG and no fixture edits.

## Golden changes and arithmetic

- Global `tau_proposed`: **0.58 → 0.62**. The old selected impostor score `0.58` is followed by observed score `0.66`; the new candidate is `(0.58 + 0.66) / 2 = 0.62`.
- Global OOF FMR: **1/13 → 0/13 = 0.0**. Moving the operating point off the old tie removes the one accepted OOF impostor while preserving the 13-score denominator.
- Occlusion `tau_proposed`: **0.38 → 0.415** (runtime float `0.41500000000000004`). Consecutive observations are `0.38` and `0.45`; `(0.38 + 0.45) / 2 = 0.415`.
- People OACT tax at coefficient 0.3: **1/3 → 3/7**. The new people base tau is `0.415`, elevated tau is `0.415 + 0.3 = 0.715`; base FNMR is `2/7`, elevated FNMR is `5/7`, hence tax `5/7 - 2/7 = 3/7`.

All other pinned values remained unchanged.

## TEST-15 mutation proofs

All mutants were applied to production, tested using the prescribed `-m pytest` command from the service directory, and reverted.

### Mutant 1 — midpoint construction regresses to observed lower endpoint

```diff
-        (lower + upper) / 2.0 for lower, upper in zip(observed, observed[1:])
+        lower for lower, upper in zip(observed, observed[1:])
```

Tests run: updated golden guard, updated threshold unit guard, all three parameter instances of the new no-observed-score guard, and the new fixture-tie disagreement guard.

Result: **0 passed, 6 failed**. Green after revert for the complete writable calibration test file: **27 passed, 0 failed**.

This mutant proves the golden, midpoint arithmetic, duplicate/adjacent distribution, and published/apply agreement assertions can go red.

### Mutant 2 — fail-closed fallback weakened

```diff
-    return float(max(peak, 1.0))
+    return 1.0
```

Test run: `test_select_threshold_abstain_and_fail_closed_paths`.

Result: **0 passed, 1 failed**. The `[2.0, 3.0]` case returned `1.0` instead of the required peak `3.0`. Green after revert is included in the **27 passed, 0 failed** writable-file run.

### Mutant 3 — zero-impostor abstention fails open

```diff
     if not impostor_scores:
-        return None
+        return 0.0
```

Test run: `test_select_threshold_abstain_and_fail_closed_paths`.

Result: **0 passed, 1 failed**. The zero-impostor assertion received `0.0` instead of `None`. Green after revert is included in the **27 passed, 0 failed** writable-file run.

## Final counts

- Writable calibration test file: **27 passed, 0 failed**.
- Full owned suite: **57 passed, 1 failed**.
- Sole failure: read-only stale tie test described under Outcome. Its assertion is direct evidence of the contract conflict: expected selected tau to be an observed impostor (`tau in impostor_scores`), obtained midpoint `0.575` for consecutive scores `0.55` and `0.60`.
- `git diff --check`: clean.

## Could not do

- Could not create the two implementation commits or commit this report because `.git` is read-only. One commit attempt was made after the independently green refactor and failed before staging/committing anything.
- Could not finish with a clean working tree for the same reason. In addition to the three intended owned modifications, baseline already contained untracked `codex.log`, which is outside lane ownership and was not touched.
- Could not make the full owned suite green without either undoing FIR-12 or editing the explicitly read-only scene regression test.
