# Lane gx1 — restore integrity gates under `--freeze-certification`

Branch: `fix/gx1` · fork: `feature/vlm-6` @ `8ae228aa`  
Heuristics: `TEST-15`, `EVAL-04`, `EVAL-13`, `EVAL-23`, `AUDIT-07`, `rg-005`, `rg-006`, `rg-009`, `sr-001`.

## 1. What changed

| File | Reason |
| --- | --- |
| `apps/prototype-description-service/scripts/eval_harness/cli.py` | Move freeze-cert `return` below measurement-integrity gates (caption + face); hoist `schema_exit`; refuse freeze when post-cert fold re-serialises (`degraded`); scope OBS-04 comment for freeze vs live. |
| `apps/prototype-description-service/scene/tests/test_eval_harness_cli.py` | Six new TEST-15 proofs: five integrity-under-freeze (aborted/zero/trunc/manifest/schema) + score-face freeze green path. |
| `apps/prototype-description-service/scripts/eval_harness/README.md` | Document that freeze-cert softens adoption only; integrity still exit-determining. |
| `.s2a/vlm6-gx1-report.md` | This report. |

## 2. Per-finding resolution

### S1-01 [high] — integrity gates skipped under freeze-cert

**Fixed.** Freeze-cert `return` now sits **after** integrity gates and **before** adoption-quality gates.

Caption integrity (always exit-determining):
- `schema_exit`
- `relabel_exit` / manifest-relabel (`non_comparable`)
- aborted-record
- failed-items
- zero-scored
- truncation
- manifest-mismatch (missing fetch-time sha)

Caption adoption (soft under freeze only):
- empty-rubric, must-right failures
- wrong-name floor vacuity + floor
- category-vacuity (`not_ready`)

Face: all three gates (aborted / zero-scored / failed-items) run **before** freeze-cert return. Face has no adoption gates today.

**Evidence:** RED five integrity tests greened freeze exit 0; GREEN they raise non-zero with class tokens. Committed freezes still `ANCHOR_EXIT=0`.

### S1-02 [high] — `schema_exit` computed then discarded

**Fixed.** `if schema_exit is not None: _score_gate_fail(schema_exit)` is the first integrity gate, above freeze-cert return (`rg-005`).

**Evidence:** `test_score_freeze_certification_schema_invalid_exits_nonzero` RED (DID NOT RAISE) → GREEN (schema error).

### S1-03 [high] — certified bytes ≠ written bytes under freeze

**Chosen fix: refuse freeze-cert return when `degraded` is true.**

Justification: post-cert folds (schema / evidence / relabel) re-serialise the document after `_check_expect_report` compared `base_json`. Certifying those pre-fold bytes while persisting post-fold bytes is not a frozen scoring path. Integrity gates usually already fire for those folds (aborted/zero/schema/relabel); the `degraded` refuse is the explicit boundary when a fold re-serialised without a matching gate.

Alternative rejected: “certify written bytes” would either re-compare after fold (double-cert surface) or write pre-fold pass verdicts for integrity failures (OBS-04 regression on disk).

**Evidence:** aborted under freeze no longer prints `freeze-certification passed` (integrity gate fires first with `aborted-record`).

### S1-04 [medium] — OBS-04 comment honesty

**Fixed.** Comment now scopes:
- **Live path:** process exit must match artifact (category-vacuity etc.).
- **Freeze path:** integrity still non-zero; adoption fail/`not_ready` may green-exit by design when bytes match (fx8 intent). Integrity half of OBS-04 restored; adoption half intentionally diverges under the flag.

## 3. TEST-15 proofs

### RED (before production fix)

```text
FFFFF.                                                                   [100%]
=================================== FAILURES ===================================
E   Failed: DID NOT RAISE SystemExit
… freeze-certification passed [score]: scoring-path is byte-stable …
FAILED …::test_score_freeze_certification_aborted_exits_nonzero - Failed: DID NOT RAISE SystemExit
FAILED …::test_score_freeze_certification_zero_scored_exits_nonzero - Failed: DID NOT RAISE SystemExit
FAILED …::test_score_freeze_certification_truncated_exits_nonzero - Failed: DID NOT RAISE SystemExit
FAILED …::test_score_freeze_certification_manifest_mismatch_exits_nonzero - Failed: DID NOT RAISE SystemExit
FAILED …::test_score_freeze_certification_schema_invalid_exits_nonzero - Failed: DID NOT RAISE SystemExit
5 failed, 1 passed, 124 deselected, 3 warnings in 22.51s
```

(Face green-path test already passed at RED time — integrity-clean fixture; proves green path exists independent of the integrity reorder.)

### GREEN (after production fix)

```text
...........                                                              [100%]
11 passed, 119 deselected, 4 warnings in 46.23s
```

Scoped integrity + face green (verbose):

```text
scene/tests/test_eval_harness_cli.py::test_score_freeze_certification_aborted_exits_nonzero PASSED
scene/tests/test_eval_harness_cli.py::test_score_freeze_certification_zero_scored_exits_nonzero PASSED
scene/tests/test_eval_harness_cli.py::test_score_freeze_certification_truncated_exits_nonzero PASSED
scene/tests/test_eval_harness_cli.py::test_score_freeze_certification_manifest_mismatch_exits_nonzero PASSED
scene/tests/test_eval_harness_cli.py::test_score_freeze_certification_schema_invalid_exits_nonzero PASSED
scene/tests/test_eval_harness_cli.py::test_score_face_freeze_certification_exits_zero_when_bytes_match PASSED
```

### Existing fx8 regression suite (still green)

- green path despite wrong names under freeze → exit 0, adoption visible
- byte mismatch (tmp copy) → non-zero `ANCHOR_MISMATCH`
- live wrong-name without freeze → non-zero (`sr-001`)
- freeze requires `--expect-report` (score + score-face)

### `make eval-anchor-check`

```text
determinism check passed [score]: … matches --expect-report …/S2A-determinism-anchor-run-20260811-report.json
… scored=37/37 … wrong_names=4 verdict=fail wrong_name_rate=0.1081 …
freeze-certification passed [score]: … (artifact verdict=fail; integrity gates enforced above; adoption gates computed below, not exit-determining)
determinism check passed [score-face]: … matches --expect-report …/S2A-face-determinism-anchor-run-20260811-face-report.json
freeze-certification passed [score-face]: … (integrity gates enforced above; not an adoption softener)
ANCHOR_EXIT=0
```

## 4. Suite result

```text
1243 passed, 4 skipped, 32 warnings in 213.63s (0:03:33)
```

Baseline fork: 1237 passed + 4 skipped. Delta: +6 new tests, 0 failed.

## 5. Cross-lane requests

None. All fixes fit within owned files (`cli.py`, `test_eval_harness_cli.py`, README, this report). No changes needed to generators, anchors, or metrics modules.

## 6. What you could not verify

- Did not re-run a hand-crafted adversarial probe outside pytest for the four original repro cases after the fix (pytest integrity suite covers the same surfaces).
- Did not verify MCP handoff / `make context` (not available / not in scope for this lane).
- Face path has no schema fold today — schema-under-freeze coverage is caption-only.
- `degraded` refuse path is defense-in-depth; primary red paths fire the class-unique integrity gates first (not the generic refuse message).
- Did not mutate `eval-anchor-check` Makefile (forbidden; exit not swallowed — `ANCHOR_EXIT=0` is real pass).
