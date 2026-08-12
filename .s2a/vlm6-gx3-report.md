# Lane gx3 — S3 face observation units (ordering, unknown-rejection, named-only FN)

Branch: `fix/gx3` (forked from `feature/vlm-6` @ `8ae228aa`)

Heuristics cited: `TEST-15`, `EVAL-04`, `EVAL-16`, `EVAL-19`, `EVAL-23`, `AUDIT-07`, `rg-005`, `rg-015`, `sr-001`, `sr-007`.

## What changed

- `scripts/eval_harness/face_metrics.py` — single `normalized_centre_order_key(cx, cy, name)` shared by predicted L→R, row sort, and labeled L→R; degenerate `w/h<=0` unpositionable; `missed_stranger_gt` required on unknown-rejection; `face_identification_pr` docs pin named-only `missed_gt`.
- `scripts/eval_harness/face_assignment.py` — `missed_gt` = named unmatched GT only; new `missed_stranger_gt` on `AssignmentResult` / `collect_matched_faces` / `score_face_assignment`.
- `scripts/eval_harness/placement_metrics.py` — module docstring: image/viewer-left, not anatomical left.
- `scene/tests/test_eval_harness_face_metrics.py` — hard-import `predicted_names_for_positional`; TEST-15 pins for S3-01/02/03/04/06/07; existing unknown-rejection callers pass `missed_stranger_gt=0`.
- `scene/tests/test_eval_harness_placement_metrics.py` — docstring convention pin (S3-08).
- `.s2a/vlm6-gx3-report.md` — this report.

## Per-finding resolution

| ID | Resolution |
|----|------------|
| **S3-01** | Fixed. One pure key `normalized_centre_order_key`; both `predicted_left_to_right` and `sort_identity_rows_by_normalized_centre` sort with it before any name dedup. No third definition. |
| **S3-02** | Fixed. `labeled_left_to_right` sorts with the same key `(x, y, name)` (y defaults `0.0` when absent). Input array order no longer decides pure-x ties. |
| **S3-03** | Fixed (signature). `missed_stranger_gt: int` is **required** (no default). Production-shaped calls without attribution raise `TypeError` — cannot publish rate=1.0 by omission. Report wiring is a cross-lane request (below). |
| **S3-04** | Fixed (assignment semantics). `collect_matched_faces` / `AssignmentResult.missed_gt` count named unmatched GT only; strangers go to `missed_stranger_gt`. `face_identification_pr` docstring states `mg` is named-only. Full-corpus report path already passes `assignment.missed_gt` — once assignment is fixed that path is correct for ID FN; unknown-rejection still needs the report patch. |
| **S3-06** | Fixed. Hard import of `predicted_names_for_positional`; assert shared implementation with `predicted_left_to_right`; dropped soft `getattr`/`if is not None` skip. |
| **S3-07** | Fixed. `wire_bbox_normalized_centre` returns `None` when `w<=0` or `h<=0`. |
| **S3-08** | Fixed. One-sentence viewer-left convention in `placement_metrics` module docstring + pin test. |

## TEST-15 proofs

RED proofs: baseline modules at `8ae228aa` exercised with the new assertion bodies (import-time symbols on the fixed tree cannot load against unfixed modules, so RED is against the baseline file content loaded as `baseline_face_metrics` / `baseline_face_assignment` / `baseline_placement_metrics`). GREEN: pytest on the fixed tree.

### 1. S3-01 — centre-x tie, both APIs same order

**RED (baseline):**
```
=== RED: test_centre_x_tie_both_apis_share_one_order_key ===
AssertionError: predicted=['Alice', 'Bob'] rows=['Bob', 'Alice']
```

**GREEN:**
```
scene/tests/test_eval_harness_face_metrics.py::test_centre_x_tie_both_apis_share_one_order_key PASSED
```

### 2. S3-02 — labeled order input-order independence

**RED (baseline):**
```
=== RED: test_labeled_left_to_right_tie_stable_across_input_order ===
AssertionError
```
(baseline: `labeled_left_to_right([Bob,Alice]@x=0.5) → ['Bob','Alice']` vs reverse input → `['Alice','Bob']`)

**GREEN:**
```
scene/tests/test_eval_harness_face_metrics.py::test_labeled_left_to_right_tie_stable_across_input_order PASSED
```

### 3. S3-03 — unknown-rejection refuses unattributed misses

**RED (baseline):**
```
=== RED: test_face_unknown_rejection_requires_missed_stranger_gt ===
AssertionError: baseline accepted call without missed_stranger_gt: rate=1.0 n=3
```

**GREEN:**
```
scene/tests/test_eval_harness_face_metrics.py::test_face_unknown_rejection_requires_missed_stranger_gt PASSED
```
(`TypeError: face_unknown_rejection() missing 1 required keyword-only argument: 'missed_stranger_gt'`)

### 4. S3-04 — stranger miss is not identification FN

**RED (baseline):**
```
=== RED: test_missed_gt_named_only_stranger_not_id_fn ===
AssertionError: baseline missed_gt=2 (counts strangers too)
```

**GREEN:**
```
scene/tests/test_eval_harness_face_metrics.py::test_missed_gt_named_only_stranger_not_id_fn PASSED
```
(post-fix: `missed_named=1`, `missed_stranger=1`, `face_identification_pr` FN=1)

### 5. S3-07 — degenerate boxes unpositioned

**RED (baseline):**
```
=== RED: test_wire_bbox_normalized_centre_rejects_degenerate_box_size ===
AssertionError
```
(baseline: `width=0` → centre `(0.0, …)`; `width=-40,x=100` → fabricated centre)

**GREEN:**
```
scene/tests/test_eval_harness_face_metrics.py::test_wire_bbox_normalized_centre_rejects_degenerate_box_size PASSED
```

### 6. S3-06 / S3-08 (cheap)

**RED:** soft-skip hid missing alias; baseline placement docstring lacked viewer-left sentence.

**GREEN:**
```
scene/tests/test_eval_harness_face_metrics.py::test_predicted_left_to_right_matches_centre_not_corner_order PASSED
scene/tests/test_eval_harness_placement_metrics.py::test_module_docstring_states_viewer_left_convention PASSED
```

## Suite result

**Owned scoped suites (face_metrics + placement_metrics + face_assignment):**
```
102 passed in 4.24s
```

**Full `scene/tests/` (post-fix):**
```
26 failed, 1217 passed, 4 skipped, 26 warnings in 164.09s (0:02:44)
```

**Explained reds (expected / out of ownership):**

1. **25 failures** — `TypeError: face_unknown_rejection() missing 1 required keyword-only argument: 'missed_stranger_gt'` at `report.py:2598`. Intentional contract break for the report follow-up lane (`sr-001`: do not fail-open). Modules: `test_eval_harness_report.py` (10), `test_eval_harness_face_determinism_anchor.py` (10), `test_eval_harness_cli.py` score-face paths (5).
2. **1 failure** — `test_cli_score_determinism_guard_pins_import_root_against_cwd_decoy` (`ModuleNotFoundError: recognition` under decoy probe). **Pre-existing at fork** — reproduces on clean `8ae228aa` tree without gx3 edits; not introduced by this lane.

Baseline claim at fork: 1237 passed / 4 skipped / 0 failed. Env here also fails the decoy probe on clean baseline, so the claimed 0-failed may reflect a different PYTHONPATH. No metric assertion was loosened.

## Cross-lane requests

### Report lane — wire `missed_stranger_gt` (S3-03) + confirm named-only ID path (S3-04)

**File:** `apps/prototype-description-service/scripts/eval_harness/report.py`  
**Do not soften the required kwarg.** Apply:

```python
# Full-corpus identification + unknown-rejection (includes private strangers).
id_pr = face_identification_pr(
    assignment.decisions,
    missed_gt=assignment.missed_gt,  # now named-only (S3-04); already correct call shape
    unmatched_detections=assignment.false_detections,
    sampling_frame=FACE_BAKEOFF_SAMPLING_FRAMES["full_corpus_identification"],
)
unknown = face_unknown_rejection(
    assignment.decisions,
    missed_stranger_gt=assignment.missed_stranger_gt,  # S3-03 — required
)
```

Replace the bare call at ~line 2598:
```python
# BEFORE (illegal under new signature):
unknown = face_unknown_rejection(assignment.decisions)

# AFTER:
unknown = face_unknown_rejection(
    assignment.decisions,
    missed_stranger_gt=assignment.missed_stranger_gt,
)
```

If any other call site exists outside this file, same shape: always pass an attributed int (`0` only when the frame truly has zero unmatched stranger GT).

**S3-04 note:** `assignment.missed_gt` is already named-only after gx3; the full-corpus `face_identification_pr(..., missed_gt=assignment.missed_gt)` call does **not** need a filter rewrite. Headline path via `_association_counts_for_media` was already named-only.

**Optional disclosure:** surface `assignment.missed_stranger_gt` next to unknown-rejection in the JSON/MD rollup so AUDIT-07 readers can see the observation unit.

**After the report patch:** re-run the 25 TypeError failures above; they should go green without touching metric assertions. Freeze/anchor modules may still need a regenerate if published rates change when stranger misses enter the unknown-rejection denominator (out of gx3 ownership; generators/anchors are forbidden here).

## What you could not verify

- End-to-end `build_face_reports` / freeze byte-stability after report wiring (blocked until report lane applies the patch).
- Whether regenerating face determinism anchors is required once stranger misses affect published unknown-rejection rates.
- CLI extraction path (`cli.py`) already delegates to `sort_identity_rows_by_normalized_centre`; not re-run as a live CLI byte freeze (ownership forbid on `cli.py`).
- Production LocalWP face_pass against real wire bboxes for the new cy secondary key (unit coverage only).
- The cwd-decoy CLI test’s `recognition` import under this env (fails on clean baseline; not gx3).
