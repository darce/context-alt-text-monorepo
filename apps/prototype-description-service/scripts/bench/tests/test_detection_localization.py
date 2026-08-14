"""[TEST-15] IoU localization: GREEN match + translation RED + containment RED."""

from __future__ import annotations

from scripts.bench.export_map import match_detection_boxes
from scripts.eval_harness.face_assignment import IOU_MATCH_THRESHOLD
from scripts.eval_harness.face_metrics import ImageDetection, detection_pr
from scripts.eval_harness.manifest import FaceBox

GT = [FaceBox(x=0.5, y=0.5, w=0.2, h=0.2, name="Alice Q", source="iptc")]
W = H = 1000


def test_green_exact_overlap_matches() -> None:
    result = match_detection_boxes(
        GT,
        [{"x": 400, "y": 400, "width": 200, "height": 200}],
        image_width=W,
        image_height=H,
    )
    assert result.matched_faces == 1
    assert result.iou_values[0] == 1.0
    scored = detection_pr(
        [ImageDetection("img", pred_faces=1, labeled_faces=1, matched_faces=result.matched_faces)]
    )
    assert scored.true_positives == 1
    assert scored.false_positives == 0
    assert scored.false_negatives == 0


def test_red_translation_unmatched_count_only_perfect() -> None:
    result = match_detection_boxes(
        GT,
        [{"x": 700, "y": 400, "width": 200, "height": 200}],
        image_width=W,
        image_height=H,
    )
    assert result.matched_faces == 0
    matched = detection_pr(
        [ImageDetection("img", pred_faces=1, labeled_faces=1, matched_faces=0)]
    )
    assert matched.false_positives == 1
    assert matched.false_negatives == 1
    count_only = detection_pr([ImageDetection("img", pred_faces=1, labeled_faces=1)])
    assert count_only.true_positives == 1
    assert count_only.precision == 1.0
    assert count_only.recall == 1.0


def test_red_containment_iou_below_threshold() -> None:
    result = match_detection_boxes(
        GT,
        [{"x": 100, "y": 100, "width": 800, "height": 800}],
        image_width=W,
        image_height=H,
    )
    assert result.matched_faces == 0
    assert abs(result.iou_values[0] - 0.0625) < 1e-9
    assert result.iou_values[0] < IOU_MATCH_THRESHOLD
