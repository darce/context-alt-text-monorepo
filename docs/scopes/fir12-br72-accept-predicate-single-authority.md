# Scope — FIR-12-BR-72: accept-predicate single authority and the serialized merge

**Status:** scope (intake complete, no artifact drafted downstream yet)
**Task ref:** FIR-12 (finding FIR-12-BR-72; blocks DESCQUAL-2 merge too)
**Graded against:** heuristics-canon @ `a5f47c6` (`lexicons/engineering.md`)
**Intake mode:** canon-answered. Operator standing instruction is to resolve scoping
questions from canon rather than ask; questions and their canon answers are recorded
below in place of an `AskUserQuestion` pass.

---

## 1. The finding, restated from measured state

BR-72 was recorded as "the two integration branches ship opposite specs for the same
function." Verification on the local tree shows the real shape is larger.

Predicate census on `feature/fir-12` @ `bbfb8239` (pre-F41), `apps/prototype-description-service/scripts/eval_harness/`:

| Copy | Role | Predicate today |
| --- | --- | --- |
| `calibrate_face_thresholds.py:645` | threshold **selection** (FMR accounting) | `s >= tau` |
| `calibrate_face_thresholds.py:771` | threshold **selection** (sweep) | `s >= tau` |
| `face_assignment.py:383` | **apply** | `s_max >= tau` |
| `face_assignment.py:672` | **apply** | `s_max >= tau` |
| `face_assignment.py:841` | **apply** | `s >= tau` |
| `synthetic_occlusion.py:552` | occlusion recovery | `s_max >= float(tau)` |
| `open_set_identification.py:124` | open-set top-1 | **`top1_score > tau`** |

Plus two prose copies of the same decision: `synthetic_occlusion.py:9` and `:84` both
assert `s_max >= tau` in docstrings, and the pinned goldens
(`tests/test_calibrate_face_thresholds.py:52`, `GOLDEN_GLOBAL_TAU = 0.66`) encode the
predicate's *consequence* as a third representation.

Two facts follow, and both matter more than the merge order:

1. **The tree is already inconsistent before F41.** `open_set_identification.py:124` is
   strict `>`; the other six are `>=`. F41 (`78f2fd85`, VM branch `fir12-int` @ `b2ad134a`)
   moves two more copies to `>` and drags `GOLDEN_GLOBAL_TAU` 0.66 → 0.58. It leaves four
   copies on the other side of the boundary.
2. **The half-migrated state is not cosmetic.** Fixture
   `tests/fixtures/face_bakeoff_report.v1.json:449` holds a genuine Alice→Bob impostor at
   `s_max = 0.58`, exactly the `tau_proposed` F41 publishes. With selection on `>` and
   apply on `>=`, the calibrator certifies a threshold whose own FMR accounting excludes a
   case the apply path admits. That is a published-FMR understatement at the boundary, not
   a rounding artifact.

**Canon:** [REF-19] a design decision (representation) appearing in >1 module is
information leakage. [REF-26] DRY is knowledge, not text — the trigger is precisely "a
single facet of intent must change in multiple places *and formats* (code + docs,
duplicated config keys)", which is the code / docstring / golden-constant triple above.
[REF-27] don't program by coincidence — a fixture whose score is bit-exactly the proposed
tau is a boundary the code currently resolves by accident of which module you are in.

## 2. Why the branches can no longer merge independently

`feature/fir-12` @ `bbfb8239` and `feature/descqual-2` @ `dca7bdd3` both edit
`calibrate_face_thresholds.py` and both pin `GOLDEN_GLOBAL_TAU`. Each is green on its own
gate. Neither gate evaluates the other's tree.

**Canon:** [REF-13] coupling-type triage — a plan may not claim two modules are independent
while they share a type contract; here they share a *predicate* contract and a duplicated
constant. [REF-14] the independent-deployability test fails. [RLSE-12] pipeline scope =
deployable unit: "if green does not mean no more work, the evaluation scope is wrong" —
the per-branch gate is the wrong scope, so widen it. [OBS-08] silence is not success: two
greens over a combination neither ran is dead instrumentation reading as health.

Merging second-in silently reverts whichever predicate landed first while leaving the
loser's goldens green against the wrong spec — the failure is invisible, which is the
disqualifying property, not the conflict.

## 3. Two options, and the one canon supports

**Option A — cherry-pick and go.** Land F41 into the DESCQUAL-2 line, merge both, re-gate.
Cheapest. Rejected: it duplicates a behavior commit onto two branches, leaves four
predicate copies unmigrated, and ships the boundary bug in §1.2 to `main`. It also violates
[REF-05] two hats — F41 as authored mixes the behavior flip with golden-constant churn in
one diff.

**Option B — serialize behind a single authority. Recommended.**

- **B1 (refactor hat, zero behavior change).** On `main`, extract one authority:
  `accepts(score, tau) -> bool` in the eval-harness core, defined as `score >= tau`, and
  route all seven call sites through it. `open_set_identification.py:124` changes from `>`
  to the shared `>=` — that *is* a behavior change and must be called out and gated
  separately rather than smuggled in. Delete the docstring restatements; point them at the
  function. [ARCH-13] architecture hoisting: make the violation unrepresentable rather than
  re-checked by reviewers. [REF-05] this commit adds no behavior.
- **B2 (test hat).** Before B3, pin current behavior [TEST-03] and prove the pins can move
  [TEST-15]: a boundary case at `score == tau` asserted explicitly, and a control mutant
  that flips `accepts` and is *expected* to go RED. The existing goldens do not qualify —
  they were never observed failing [TEST-06].
- **B3 (behavior hat).** One-line change inside `accepts`: `>=` → `>`, with
  `GOLDEN_GLOBAL_TAU` moving 0.66 → 0.58 as a *derived* consequence, not a hand-edited
  constant. This is what F41 meant to do; re-author it rather than cherry-picking
  `78f2fd85`, since F41's diff no longer applies to a unified call graph.
- **B4 (integration).** Rebase both `feature/fir-12` and `feature/descqual-2` onto the
  post-B3 `main`, then gate the **combined** tree once. [RLSE-12].

Cost delta over Option A is roughly one extra branch and one extra gate cycle. That buys
the boundary bug being fixed once instead of shipped twice.

## 4. Success criteria

- `grep -rn -- '>= tau\|> tau'` over `scripts/eval_harness/*.py` returns exactly one
  non-test hit: the body of `accepts`.
- The `score == tau` boundary is asserted by name in a test that has been observed RED
  under a control mutant.
- `GOLDEN_GLOBAL_TAU` is defined once; no second module restates it.
- Fixture `media_id=301` is accounted for identically by selection and apply — the same
  published FMR whichever path counts it.
- One gate run on the combined `fir-12` + `descqual-2` tree, green, on the full declared
  collection (not a subset).

## 5. Not doing

- Not cherry-picking `78f2fd85`. It is superseded, not lost — its intent lands as B3.
- Not deciding whether JANUS FPI is *right* (strict `>` vs `>=`). That is a separate
  measurement question; this scope only makes the tree state one answer instead of two.
- Not touching the VLM-6 line, which is parked.
- Not re-baselining any published FIR-12 or DESCQUAL-2 number in this scope; the goldens
  move as a consequence of B3 and are re-reported there.
- No compatibility shim keeping the old predicate reachable behind a flag — greenfield
  policy, delete-over-flag.

## 6. Assumptions

- F41's `>` direction is the intended JANUS 2.3.4 FPI alignment. If a later measurement
  reverses it, B3 is a one-line revert *because* B1 landed first — which is the main
  argument for Option B.
- The VM branch `fir12-int` @ `b2ad134a` is disposable working state, not a merge source.
