# Lane vlm6-s2-runner / r10 — VLM6-S7-02 follow-up

**Item:** `#734` remove false `assert result.recall is None` from `test_matched_faces_bounds_table`
**Not in scope:** `test_worker_cancellation_marks_failed_then_re_raises` (aarch64 flake); anything under `scripts/eval_harness/` (TEST-15 mutation was uncommitted and restored)

## Verdict

Done. The carry-over `assert result.recall is None` is deleted, not rewritten. `test_matched_faces_bounds_table` still collects 5 cases. No function in the file is defined twice. Surviving FP/FN assertions bite: count-only FN mutation went red, restore went green.

## Exact diff hunk

```diff
diff --git a/apps/prototype-description-service/scene/tests/test_eval_harness_face_metrics.py b/apps/prototype-description-service/scene/tests/test_eval_harness_face_metrics.py
--- a/apps/prototype-description-service/scene/tests/test_eval_harness_face_metrics.py
+++ b/apps/prototype-description-service/scene/tests/test_eval_harness_face_metrics.py
@@ -1443,6 +1443,9 @@ def test_matched_faces_is_optional_last_field():
     assert row.matched_faces is None
 
 
+# VLM6-S7-02: this test was defined twice; the shadowed copy's extra
+# `assert result.recall is None` was dropped, not merged — recall is None only
+# when tp+fn == 0, which no row here produces (labeled_faces=2 throughout).
 @pytest.mark.parametrize(
     ("matched", "expect_ok", "fp", "fn"),
     [
@@ -1467,9 +1470,3 @@ def test_matched_faces_bounds_table(matched, expect_ok, fp, fn):
     assert result.false_negatives == fn
     assert result.false_positives >= 0
     assert result.false_negatives >= 0
-    if matched is None:
-        # VLM6-S7-02: carried over from a duplicate definition of this test that
-        # main shadowed (defined twice, so only the second was ever collected).
-        # Scoped to the count-only path on purpose — with matched_faces supplied
-        # recall IS computable, so the shadowed copy's unqualified form was wrong.
-        assert result.recall is None
```

## 1. Pytest counts

Command: `cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/test_eval_harness_face_metrics.py -q -p no:randomly`

```
..................................................................       [100%]
66 passed in 2.57s
```

Exact passed count: **66 passed**.

## 2. Duplicate-definition check

Method: `grep '^def test_' scene/tests/test_eval_harness_face_metrics.py | sort | uniq -d`

Output: empty (no duplicate function names).

Collected cases (`pytest --collect-only -q -p no:randomly -k test_matched_faces_bounds_table`):

```
scene/tests/test_eval_harness_face_metrics.py::test_matched_faces_bounds_table[0-True-3-2]
scene/tests/test_eval_harness_face_metrics.py::test_matched_faces_bounds_table[2-True-1-0]
scene/tests/test_eval_harness_face_metrics.py::test_matched_faces_bounds_table[3-False-None-None]
scene/tests/test_eval_harness_face_metrics.py::test_matched_faces_bounds_table[-1-False-None-None]
scene/tests/test_eval_harness_face_metrics.py::test_matched_faces_bounds_table[None-True-1-0]

5/66 tests collected (61 deselected)
```

`test_matched_faces_bounds_table` is defined once, at line 1459. Collects exactly 5 cases.

`uniq -c` of `^def test_` names with count > 1: empty.

## 3. TEST-15 transcripts

Mutation (uncommitted, then restored): in `detection_pr` count-only branch, `fn += max(item.labeled_faces - item.pred_faces, 0)` became `fn += max(item.labeled_faces - item.pred_faces, 0) + 1`. Production file restored before commit.

### test_matched_faces_bounds_table — RED

Command: `uv run --extra dev pytest scene/tests/test_eval_harness_face_metrics.py::test_matched_faces_bounds_table -q -p no:randomly`

```
....F                                                                    [100%]
=================================== FAILURES ===================================
________________ test_matched_faces_bounds_table[None-True-1-0] ________________

matched = None, expect_ok = True, fp = 1, fn = 0

    @pytest.mark.parametrize(
        ("matched", "expect_ok", "fp", "fn"),
        [
            (0, True, 3, 2),   # (i) accepted; neither FP nor FN negative
            (2, True, 1, 0),   # (ii) upper bound matched == min(pred, labeled) — load-bearing for <= vs <
            (3, False, None, None),  # (iii) exceeds labeled
            (-1, False, None, None),  # (iv) below 0
            (None, True, 1, 0),  # (v) omitted → count-only legacy
        ],
    )
    def test_matched_faces_bounds_table(matched, expect_ok, fp, fn):
        if matched is None:
            item = ImageDetection(image="x.jpg", pred_faces=3, labeled_faces=2)
        else:
            item = ImageDetection(image="x.jpg", pred_faces=3, labeled_faces=2, matched_faces=matched)
        if not expect_ok:
            with pytest.raises(ValueError, match="matched_faces_out_of_bounds"):
                detection_pr([item])
            return
        result = detection_pr([item])
        assert result.false_positives == fp
>       assert result.false_negatives == fn
E       assert 1 == 0
E        +  where 1 = PrResult(true_positives=2, false_positives=1, false_negatives=1, true_rejections=0, wrong_names=[], per_identity={}, excluded_images=[]).false_negatives

scene/tests/test_eval_harness_face_metrics.py:1470: AssertionError
=========================== short test summary info ============================
FAILED scene/tests/test_eval_harness_face_metrics.py::test_matched_faces_bounds_table[None-True-1-0] - assert 1 == 0
 +  where 1 = PrResult(true_positives=2, false_positives=1, false_negatives=1, true_rejections=0, wrong_names=[], per_identity={}, excluded_images=[]).false_negatives
1 failed, 4 passed in 0.83s
```

### Restored green

`face_metrics.py` restored to committed count-only FN formula (`+ 1` removed). `git diff -- scripts/eval_harness/face_metrics.py` empty.

```
.....                                                                    [100%]
5 passed in 0.66s
```

## Out of scope left untouched

- `scene/tests/test_describe_async_worker.py`
- committed contents of `scripts/eval_harness/`
