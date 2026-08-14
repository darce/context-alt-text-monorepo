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
        [ImageDetection("img", pred_faces=1, labeled_faces=1, matched_faces=result.matched_faces)]
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
    from scripts.bench.score import iou_tl, pred_px_to_norm_tl

    pred = pred_px_to_norm_tl(100, 100, 800, 800, W, H)
    gt = (0.4, 0.4, 0.2, 0.2)
    assert abs(iou_tl(pred, gt) - 0.0625) < 1e-9
    assert iou_tl(pred, gt) < IOU_MATCH_THRESHOLD
    assert result.iou_values == []


def test_iou_threshold_inclusive_at_half() -> None:
    # This geometry yields IoU = 1/3, below the pinned 0.5 match threshold.
    # GT tl (0.4, 0.4, 0.2, 0.2); pred shifted +100px on x.
    result = match_detection_boxes(
        GT,
        [{"x": 500, "y": 400, "width": 200, "height": 200}],
        image_width=W,
        image_height=H,
    )
    from scripts.bench.score import iou_tl, pred_px_to_norm_tl

    pred = pred_px_to_norm_tl(500, 400, 200, 200, W, H)
    gt = (0.4, 0.4, 0.2, 0.2)
    iou = iou_tl(pred, gt)
    assert abs(iou - 1 / 3) < 1e-9
    assert result.matched_faces == 0
    assert result.iou_values == []
    # Inclusive boundary: a constructed pair at exactly the threshold matches.
    from scripts.bench.score import hungarian_iou_matches

    pairs, _ = hungarian_iou_matches([gt], [pred], threshold=iou)
    assert len(pairs) == 1
    pairs_strict, _ = hungarian_iou_matches([gt], [pred], threshold=iou + 1e-9)
    assert pairs_strict == []
    assert IOU_MATCH_THRESHOLD == 0.5


def test_degenerate_leading_gt_indices_stay_on_original_list() -> None:
    from scripts.eval_harness.face_metrics import identification_pr
    from scripts.bench.export_map import to_face_metric_inputs
    from scripts.eval_harness.manifest import EntryPolicy, GoldenEntry, GoldenManifest

    degenerate = FaceBox(x=0.0, y=0.0, w=0.0, h=0.0, name="Ghost", source="iptc")
    real = FaceBox(x=0.5, y=0.5, w=0.2, h=0.2, name="Alice Q", source="iptc")
    result = match_detection_boxes(
        [degenerate, real],
        [{"x": 400, "y": 400, "width": 200, "height": 200}],
        image_width=W,
        image_height=H,
    )
    assert result.matched_faces == 1
    assert result.matched_gt_indices == [1]
    manifest = GoldenManifest(
        manifest_version=2,
        roster=["Ghost", "Alice Q"],
        entries=[
            GoldenEntry(
                path="deg.jpg",
                sha256="d" * 64,
                media_id=1,
                face_count=2,
                present_identities=["Ghost", "Alice Q"],
                must_right=[],
                easy_wrong=[],
                policy=EntryPolicy(recognition_enabled=True),
                base_caption="",
                face_boxes=[degenerate, real],
            )
        ],
    )
    export = {
        "media_identities": [
            {
                "identity_id": "i1",
                "media_id": 10,
                "cluster_id": "c1",
                "cluster_label": "Alice Q",
                "is_auto_label": False,
                "bbox": {"x": 400, "y": 400, "width": 200, "height": 200},
            }
        ],
        "clusters": [{"id": "c1", "label": "Alice Q", "is_auto_label": False}],
        "cluster_members": [],
    }
    join = {1: {"stack_media_id": 10, "image_width": W, "image_height": H}}
    _det, id_n = to_face_metric_inputs(export, manifest, join, "primary", frame="native")
    native = identification_pr(id_n)
    assert id_n[0].labeled == ["Alice Q"]
    assert native.true_positives == 1
