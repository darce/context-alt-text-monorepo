import pytest

from scripts.eval_harness import face_metrics, report
from scripts.eval_harness.face_metrics import ImageDetection
from scripts.eval_harness.manifest import (
    AnnotationMode,
    FaceBox,
    LabelConfidence,
    LabelDecision,
    LabelLineage,
    LabelSource,
    ManifestError,
)


def _lineage(label_source=LabelSource.OPERATOR_BLIND):
    return LabelLineage(
        labeler_id="lane-test",
        batch_id="lane-test",
        capture_session_id="lane-test",
        pass_index=0,
        labeled_at="2026-09-26T00:00:00Z",
        tool_version="lane-test",
        saw_machine_proposals=False,
        label_source=label_source,
        decision=LabelDecision.NAMED,
        confidence=LabelConfidence.HIGH,
    )


def _box(*, width=0.2, lineage=True):
    return FaceBox(
        x=0.5,
        y=0.5,
        w=width,
        h=0.2,
        name="Ada",
        source="operator",
        lineage=_lineage() if lineage else None,
    )


def _row(
    *,
    image="corpus/clean.jpg",
    detections=((640.0, 360.0, 320.0, 180.0),),
    gt_boxes=None,
    image_size=(1600, 900),
    detection_frame_size=(1600, 900),
    labeled_faces=None,
):
    boxes = (_box(),) if gt_boxes is None else gt_boxes
    return ImageDetection(
        image=image,
        pred_faces=len(detections),
        labeled_faces=len(boxes) if labeled_faces is None else labeled_faces,
        detections_bbox_px=detections,
        gt_boxes=boxes,
        image_size=image_size,
        detection_frame_size=detection_frame_size,
    )


def _score(rows):
    return face_metrics.detection_pr_strict(
        rows,
        annotation_mode=AnnotationMode.EXHAUSTIVE,
        run_manifest={"iou_threshold": 0.5},
    )


def _invariant(error):
    return getattr(error.invariant, "value", error.invariant)


def test_score_run_record_refuses_unknown_human_label_source():
    entry = {
        "path": "unknown-source.jpg",
        "media_id": 1,
        "face_count": 1,
        "present_identities": [],
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "annotation_mode": "exhaustive",
        "face_boxes": [
            {
                "x": 0.5,
                "y": 0.5,
                "w": 0.2,
                "h": 0.2,
                "name": None,
                "source": "operator",
                "lineage": {
                    "label_source": "future_importer",
                    "saw_machine_proposals": False,
                    "decision": "named",
                },
            }
        ],
    }
    record = {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "head_sha": "0" * 40,
            "started_at": "t",
        },
        "items": [
            {
                "media_id": 1,
                "path": "unknown-source.jpg",
                "describe": {"alt_text_draft": "A photo.", "visual_facts": {"objects": []}},
                "identities": [],
                "face_count": 1,
                "error": None,
            }
        ],
    }

    with pytest.raises(ManifestError) as exc_info:
        report.score_run_record(
            record,
            [entry],
            annotation_mode=AnnotationMode.EXHAUSTIVE,
            run_manifest={"iou_threshold": 0.5},
        )

    assert _invariant(exc_info.value) == "detection_requires_human_adjudicated_gt_lineage"
    assert exc_info.value.entry_index == 0
    assert exc_info.value.entry_path == "unknown-source.jpg"


@pytest.mark.parametrize(
    "detection",
    [
        (float("nan"), 360.0, 320.0, 180.0),
        (640.0, float("inf"), 320.0, 180.0),
        (640.0, 360.0, float("nan"), 180.0),
        (640.0, 360.0, 320.0, float("inf")),
        (640.0, 360.0, 0.0, 180.0),
        (640.0, 360.0, 320.0, -1.0),
    ],
)
def test_strict_scoring_refuses_nonfinite_or_degenerate_detection_boxes(detection):
    with pytest.raises(ManifestError) as exc_info:
        _score([_row(detections=(detection,))])

    assert _invariant(exc_info.value) == "detection_requires_localization"


@pytest.mark.parametrize(
    "bad_row",
    [
        lambda: _row(image="corpus/73.jpg", gt_boxes=(_box(lineage=False),)),
        lambda: _row(image="corpus/73.jpg", detection_frame_size=None),
        lambda: _row(image="corpus/73.jpg", gt_boxes=(_box(width=0.0),)),
        lambda: _row(image="corpus/73.jpg", detections=((640.0, 360.0, 0.0, 180.0),)),
        lambda: _row(image="corpus/73.jpg", labeled_faces=2),
    ],
    ids=["lineage", "frame", "gt-geometry", "detection-geometry", "coverage"],
)
def test_strict_row_refusals_include_corpus_index_and_image_path(bad_row):
    with pytest.raises(ManifestError) as exc_info:
        _score([_row(image="corpus/1.jpg"), bad_row()])

    assert exc_info.value.entry_index == 1
    assert exc_info.value.entry_path == "corpus/73.jpg"
    assert "entry_index=1" in str(exc_info.value)
    assert "entry_path=corpus/73.jpg" in str(exc_info.value)
