# Lane `fx8` — separate byte-stability certification from adoption gating

**Branch:** `feature/vlm-6-fx8` (this lane's branch)  
**Base:** `e2575b5ef09ed75de7f792546439d53624c9d344`  
**Prior diagnosis:** `.s2a/vlm6-fx7-report.md` `## Cross-lane requests` #1

Heuristics: `TEST-15`, `EVAL-04`, `EVAL-13`, `EVAL-23`, `AUDIT-07`, `rg-002`, `rg-006`, `rg-009`, `rg-015`, `sr-001`, `sr-007`.

---

## Defect

`make eval-anchor-check` printed `determinism check passed … matches --expect-report …` then exited **1** because caption adoption gates (wrong-name floor from fx4 seeded deviation; category-vacuity from fx6) re-applied after a green byte-stability compare. Two contracts shared one exit code:

| Contract | Question |
| --- | --- |
| **byte-stability** | Did the scoring path reproduce the frozen bytes? |
| **adoption quality** | Is this corpus good enough to certify a model? |

The freeze is deliberately imperfect and non-evidential (`predictions_source: ground_truth_derived_fixture`, `face_metrics_evidential: false`, `wrong_names=4`, `verdict=fail`). Judging it by adoption quality is a category error. README claimed `EXIT_CODE:0` while behaviour disagreed (`rg-006`).

## Fix

Explicit opt-in **`--freeze-certification`** on `score` and `score-face`:

- **Requires** `--expect-report` (and therefore `--check-determinism`). Without it → hard reject (cannot use the flag to skip gating).
- **Exit code sole determinant:** determinism + expect-report comparison. Mismatch still `ANCHOR_MISMATCH` / non-zero.
- Adoption/integrity gates still **computed and printed** (`verdict=fail`, rates, summary) but **do not set exit status**.
- Success line names what is certified and what is not (scoring-path byte-stability only; not model quality / face recognition / adoption — VLM6-E-08 stays closed).
- Does not special-case freeze paths in production scoring (`rg-009`); live `score` without the flag keeps every adoption gate hard (`sr-001`).
- Freeze-tree write protection (VLM6-E-05 / OUT_DIR redirect) unchanged — no clobber regression.
- `make eval-anchor-check` uses the new flag. `--rubric-gate skip` retained on the caption leg **only for freeze stamp parity** (`artifact.rubric_gate=skip`); it is not what makes exit 0 under freeze-certification.

### Files touched

| File | Change |
| --- | --- |
| `scripts/eval_harness/cli.py` | `--freeze-certification` flag + early return after summary under that mode (score + score-face) |
| `scene/tests/test_eval_harness_cli.py` | Five TEST-15 tests (reject / green / mismatch / live regression / face reject) |
| `Makefile` | `eval-anchor-check` → `--freeze-certification` |
| `scripts/eval_harness/README.md` | Exit-code contract + operator table; imperfect freeze documented |
| `.s2a/vlm6-fx8-report.md` | This report |

---

## Per-finding / acceptance (TEST-15)

### 1. Flag cannot skip gating — `--freeze-certification` without `--expect-report`

**Touched:** `cli.py` (`_cmd_score` / `_cmd_score_face` validation + argparse)

**RED (unfixed — flag unknown):**
```
eval_harness: error: unrecognized arguments: --freeze-certification
SystemExit: 2
AssertionError: assert '--freeze-certification requires --expect-report' in '2'
```

**GREEN:**
```
score: --freeze-certification requires --expect-report
FLAG_EXIT:1
```
Test: `test_score_freeze_certification_requires_expect_report` + face twin → passed.

**Behaviour:** Flag alone (or with only `--check-determinism`) is rejected; cannot open adoption gates without an external freeze reference.

---

### 2. Green path exits 0 — unmodified committed freezes under new mode

**Touched:** `cli.py` post-summary early return; `Makefile` `eval-anchor-check`

**RED (pre-fix make target / live score+expect without freeze-cert):**
```
determinism check passed [score]: … matches --expect-report …/S2A-determinism-anchor-run-20260811-report.json
scored=37/37 … wrong_names=4 verdict=fail wrong_name_rate=0.1081 …
score wrong-name floor gate: wrong_name_rate=0.1081 exceeds floor=0.0 …
LIVE_EXIT:1
```

**GREEN (`make eval-anchor-check`):**
```
determinism check passed [score]: … matches --expect-report …/S2A-determinism-anchor-run-20260811-report.json
scored=37/37 insertion_rate=0.0 wrong_names=4 verdict=fail wrong_name_rate=0.1081 … rubric_gate=skip
freeze-certification passed [score]: scoring-path is byte-stable (matches --expect-report); nothing certified about model quality, face recognition, or adoption readiness (artifact verdict=fail; adoption gates computed above, not exit-determining)
determinism check passed [score-face]: … matches --expect-report …/S2A-face-determinism-anchor-run-20260811-face-report.json
freeze-certification passed [score-face]: scoring-path is byte-stable …
MAKE_EXIT:0
```

Adoption verdict remains **visible** (`verdict=fail`, `wrong_names=4`) while exit is 0.

**Behaviour:** Byte-stable re-score of the deliberately imperfect freeze exits 0; adoption outcomes printed, not exit-determining.

---

### 3. Byte mismatch still fails under `--freeze-certification`

**Touched:** unchanged `_check_expect_report` path (still sole exit under freeze-cert)

**RED (tmp-perturbed freeze, not committed):**
```
determinism check ANCHOR_MISMATCH [score]: fresh re-score does not match --expect-report /tmp/fx8-expect-bad.json (…; artifact=…/determinism-anchor-mismatch-score.diff.txt). …
MISMATCH_EXIT:1
```

Test: `test_score_freeze_certification_exits_nonzero_on_anchor_mismatch` → passed.

**Behaviour:** Freeze-certification does **not** swallow ANCHOR_MISMATCH; the thing the target exists to catch still goes red.

---

### 4. Live runs unaffected — adoption gates stay hard without the flag

**Touched:** none for the live path (early return only when flag set)

**RED capability (still fires today — regression guard):**
```
score wrong-name floor gate: wrong_name_rate=0.1081 exceeds floor=0.0 (ignored_wrong_names=0; see …)
LIVE_EXIT:1
```

Same command **with** freeze match but **without** `--freeze-certification` exits 1 after printing `determinism check passed`. Test: `test_score_live_wrong_name_still_exits_nonzero_without_freeze_certification` → passed.

**Behaviour:** Ordinary `score` keeps wrong-name floor / category-vacuity / must-right hard (`sr-001`). Freeze-certification is not a silent soft-open.

---

## Full suite

```
.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
1237 passed, 4 skipped, 28 warnings in 156.78s
SUITE_EXIT:0
```

(+5 freeze-certification tests vs prior 1232).

---

## Cross-lane requests

None. Defect closed inside owned files. Anchors untouched (fx7 final).

---

## Deferred

| Item | Reason |
| --- | --- |
| Real golden `verdict=pass` / adoption-green freeze | Requires Golden-100 population (`face_boxes` / `spatial_facts` / `reference_facts` π>0). Freeze-certification correctly treats today's imperfect freeze as byte-stability-only. |
| Dropping `--rubric-gate skip` from caption `eval-anchor-check` | Would re-stamp `rubric_gate=enforce` and ANCHOR_MISMATCH against the committed freeze. Needs a deliberate anchor regen (out of scope; anchors final per wave). |

---

## Commits (this lane's branch)

1. `fix(vlm-6): separate freeze byte-stability exit from adoption gates (fx8)`
2. `docs(vlm-6): fx8 lane TEST-15 fix report`
