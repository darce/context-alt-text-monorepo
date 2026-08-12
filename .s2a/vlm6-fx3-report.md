# VLM-6 lane `fx3` — face metrics and placement matching

**Branch:** `feature/vlm-6-fx3` (this lane's branch)  
**Base:** `e2575b5ef09ed75de7f792546439d53624c9d344`  
**Owned files:** `face_metrics.py`, `placement_metrics.py`, `test_eval_harness_face_metrics.py`, `test_eval_harness_placement*.py`, this report.

Targeted gate (68 tests):
```
cd apps/prototype-description-service && .venv/bin/python -m pytest \
  scene/tests/test_eval_harness_face_metrics.py \
  scene/tests/test_eval_harness_placement_metrics.py -q
```
**GREEN:** `68 passed in 0.78s`

---

## VLM6-B-01 (high) — fold `missed_gt` into identification FN

- **Files:** `face_metrics.py` (`SAMPLING_FRAME_FACE_ID`, `face_identification_pr`)
- **Behaviour change:** Attributed `missed_gt` is added to `false_negatives` (EVAL-16). Sampling-frame string no longer claims misses are excluded. Coupling flag retained as disclosure.
- **RED** (`test_face_id_detection_recall_coupling_flag_computed` vs unfixed production):
  ```
  assert coupled.false_negatives == 2  # EVAL-16: missed_gt folded into FN
  E   assert 0 == 2
  E    +  where 0 = FaceLevelIdPr(..., false_negatives=0, ..., missed_gt=2, ...).false_negatives
  ```
- **GREEN:** same test; FN=2, recall≈1/3, recall_denominator=3.

## VLM6-B-02 (medium) — EVAL-16 test asserts FN/recall, not only the flag

- **Files:** `test_eval_harness_face_metrics.py` (`test_face_id_detection_recall_coupling_flag_computed`)
- **Behaviour change:** Test asserts `false_negatives`, `recall`, `recall_denominator` before flag/frame checks so a flag-only scorer goes red (TEST-15). RED evidence is the B-01 run above.

## VLM6-B-03 (high) — centre-based predicted L→R is the production path in this module

- **Files:** `face_metrics.py` (`predicted_left_to_right` docs, `predicted_names_for_positional`, `ImageIdentities.predicted_rows`/`image_width`/`image_height`, `_leftmost_unique_names`, `positional_identification`); tests.
- **Behaviour change:**
  1. `positional_identification` uses `predicted_left_to_right` when `predicted_rows` + dims are set (centre-x order).
  2. Without rows, leftmost-wins name dedup still runs so `[Alice, Alice, Bob]` vs labeled `[Alice, Bob]` is exact (not 1/3).
  3. `predicted_names_for_positional` is the only approved predicted-order API exported for report wiring.
- **RED (dedupe path):**
  ```
  assert result.exact_order_images == 1
  E   assert 0 == 1
  +  where 0 = PositionalIdResult(position_hits=1, position_total=3, exact_order_images=0, ...).exact_order_images
  ```
- **RED (rows path vs unfixed):**
  ```
  TypeError: ImageIdentities.__init__() got an unexpected keyword argument 'predicted_rows'
  ```
- **GREEN:** both tests pass; centre-order fixture exact_order=1 / accuracy=1.0.
- **Cross-lane:** report.py must wire rows (see below).

## VLM6-B-06 (high) — bare left/right not placement mid-terms

- **Files:** `placement_metrics.py` (`_PAIR_DIR_TERMS`, `_mid_pattern`); placement tests.
- **Behaviour change:** Pair-order mids are `to the left of` / `left of` (and right analogues), not bare `left`/`right`. Departure verb no longer scores as perfect placement.
- **RED:**
  ```
  assert s.correct == []
  E   AssertionError: assert ['Alice left_of Bob'] == []
  ```
  (caption `"Alice left Bob at the station."` scored accuracy=1.0)
- **GREEN:** departure → abstention (`accuracy is None`); `"Alice to the left of Bob"` / `"Alice is left of Bob"` / `"Bob to the right of Alice"` still correct.

## VLM6-B-08 (medium) — missed stranger GT counts against unknown-rejection

- **Files:** `face_metrics.py` (`SAMPLING_FRAME_UNKNOWN_REJECTION`, `UnknownRejectionResult.missed_stranger_gt`, `face_unknown_rejection`)
- **Choice:** Count missed stranger GT against the rate (EVAL-16), not only rewrite the frame string. Rationale: a detector that skips hard strangers must not keep rate=1.0 by exclusion; AUDIT-07 requires naming the true observation unit and including units with non-zero sampling probability.
- **Behaviour change:** `missed_stranger_gt` enters `n` and rate denominator as failures; frame string names matched+missed, not `full_corpus_including_unpublishable`.
- **RED:**
  ```
  TypeError: face_unknown_rejection() got an unexpected keyword argument 'missed_stranger_gt'
  ```
  (pre-fix matched-only path: 3 rejects → rate=1.0, n=3 with 50 misses invisible)
- **GREEN:** `face_unknown_rejection(matched, missed_stranger_gt=50)` → n=53, rate=3/53.
- **Cross-lane:** report must pass frame-scoped missed stranger count.

## VLM6-B-09 (medium) — determinism self-comparison without `--expect-report`

- **Not fixable in owned files.** No determinism checker lives in `face_metrics.py` / `placement_metrics.py`. Root cause is CLI/check path (`score-face --check-determinism` without `--expect-report` re-scores the same corrupted bytes and agrees). See Cross-lane.
- **Verified by reading** `test_corrupt_face_run_record_without_expect_report_passes_silently` (not owned; documents the hole). No executable assertion available inside this lane’s modules (TEST-15 N/A for production code here).

## VLM6-B-10 (low) — positional vacuity signal when π=0

- **Files:** `face_metrics.py` (`SAMPLING_FRAME_POSITIONAL`, `POSITIONAL_EVAL_*`, `POSITIONAL_VACUITY_SIGNAL`, `PositionalIdResult` fields, `positional_identification`); golden-corpus test.
- **Behaviour change:** When `compared_images==0`, result emits `evaluable=False`, `status=not_evaluable`, `vacuity_signal="positional identification not evaluable on this corpus, π=0 for box-grounded identity claims"` (EVAL-23 / AUDIT-07). Proven on real `golden.json` (0/37 face_boxes).
- **RED:**
  ```
  assert getattr(result, "evaluable", None) is False
  E   AssertionError: assert None is False
  ```
  (`compared_images=0`, `position_accuracy=None`, no machine-readable block signal)
- **GREEN:** same golden corpus run; status/signal set; 37 excluded.
- **Cross-lane:** verdict layer must fail closed on `status=not_evaluable`.

---

## Cross-lane requests

### report.py (lane `fx2`) — B-03 wiring

In `score_run_record` (where `predicted_names = identity_names(item.get("identities", []))` feeds `positional_items`):

```python
from scripts.eval_harness.face_metrics import predicted_names_for_positional

# Prefer centre-ordered + leftmost-wins names for positional metric.
identities = item.get("identities") or []
image_w = item.get("image_width")  # or dims from run record / provenance
image_h = item.get("image_height")
pos_predicted = predicted_names_for_positional(
    identities, image_width=image_w, image_height=image_h
)
# Fallback only if rows unusable:
if pos_predicted is None:
    pos_predicted = identity_names(identities)

positional_items.append(
    ImageIdentities(
        image=path,
        predicted=pos_predicted,
        labeled=list(ordered_labeled) if order_known else [],
        recognition_enabled=recognition_enabled,
        stranger_faces=stranger_faces,
        labeled_order_known=order_known,
        predicted_rows=identities if order_known else None,
        image_width=image_w,
        image_height=image_h,
    )
)
```

Also surface positional vacuity in the report JSON (B-10):

```python
"positional": {
    ...
    "evaluable": positional.evaluable,
    "status": positional.status,
    "vacuity_signal": positional.vacuity_signal,
    "sampling_frame": positional.sampling_frame,
}
```

### report.py (lane `fx2`) — B-01 already wired counts

`face_identification_pr(..., missed_gt=assignment.missed_gt, ...)` already passes counts; after this lane’s fix those counts lower FN/recall automatically. Ensure any freeze re-score or gate that expected FN-excluding-misses is updated. Do not re-introduce “misses excluded from FN” language in report copy.

### report.py (lane `fx2`) — B-08 missed stranger GT

```python
# Count unmatched GT boxes with true_name is None (stranger), frame-scoped.
missed_stranger_gt = ...  # mirror _association_counts_for_media but name is None
unknown = face_unknown_rejection(
    assignment.decisions,
    missed_stranger_gt=missed_stranger_gt,
)
# Emit unknown["missed_stranger_gt"] in the slice payload.
```

### report.py / verdict (lane `fx2`) — B-10 gate

When `identification.positional.status == "not_evaluable"` (or `evaluable is False`), block adoption pass for the identity/positional category (EVAL-23: readiness is the weakest category). Do not treat `position_accuracy is None` alone as a soft skip.

### cli.py (lane `fx1`) — B-03 residual

`_extract_identities` still sorts by corner-x. Either accept image dims and sort via `sort_identity_rows_by_normalized_centre` / centre-x, or rely on report re-ordering via `predicted_names_for_positional`. Prefer fixing extract so stored rows are already centre-ordered.

### cli.py / face determinism (lane `fx1`) — B-09

`score-face --check-determinism` without `--expect-report` must not print a bare “determinism check passed” for self-comparison of the same bytes. Either:
1. Require `--expect-report` for the red path, or
2. Change the success message to state it only proves seed-stability of the supplied run-record bytes (not integrity vs a pinned freeze).

TEST-15: the red path must be reachable without an opt-in that operators routinely omit.

---

## Deferred

Nothing deferred for lack of Golden-100 among owned fixes. Vacuity is made loud today (B-10) without populating `face_boxes`. Full positional gate adoption still needs Golden-100 face_boxes (corpus work outside this lane) **and** the report/verdict wiring above.

---

## Heuristics cited

TEST-15, EVAL-16, EVAL-23, AUDIT-07, sr-001, sr-007.
