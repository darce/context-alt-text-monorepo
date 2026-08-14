"""Dual-frame cascade: detector-miss → ID FN on e2e; zero-export stays in both denominators."""

from __future__ import annotations

from scripts.bench.export_map import to_face_metric_inputs
from scripts.bench.score_report import SAMPLING_FRAME_CROSSBENCH_NATIVE, SAMPLING_FRAME_E2E
from scripts.eval_harness.face_metrics import detection_pr, identification_pr
from scripts.eval_harness.manifest import EntryPolicy, FaceBox, GoldenEntry, GoldenManifest


def _manifest() -> GoldenManifest:
    return GoldenManifest(
        manifest_version=2,
        roster=["Alice Q", "Bob Z"],
        entries=[
            GoldenEntry(
                path="partial.jpg",
                sha256="a" * 64,
                media_id=1,
                face_count=2,
                present_identities=["Alice Q", "Bob Z"],
                must_right=[],
                easy_wrong=[],
                policy=EntryPolicy(recognition_enabled=True),
                base_caption="",
                face_boxes=[
                    FaceBox(x=0.3, y=0.3, w=0.2, h=0.2, name="Alice Q", source="iptc"),
                    FaceBox(x=0.7, y=0.3, w=0.2, h=0.2, name="Bob Z", source="iptc"),
                ],
            ),
            GoldenEntry(
                path="zero.jpg",
                sha256="b" * 64,
                media_id=2,
                face_count=1,
                present_identities=["Alice Q"],
                must_right=[],
                easy_wrong=[],
                policy=EntryPolicy(recognition_enabled=True),
                base_caption="",
                face_boxes=[FaceBox(x=0.5, y=0.5, w=0.2, h=0.2, name="Alice Q", source="iptc")],
            ),
        ],
    )


def _export_partial_only() -> dict:
    # media 1: one predicted face (Alice geometry). media 2: zero export rows.
    return {
        "media_identities": [
            {
                "identity_id": "i1",
                "media_id": 10,
                "cluster_id": "c1",
                "cluster_label": "Alice Q",
                "is_auto_label": False,
                "bbox": {"x": 200, "y": 200, "width": 200, "height": 200},
            }
        ],
        "clusters": [{"id": "c1", "label": "Alice Q", "is_auto_label": False}],
        "cluster_members": [{"cluster_id": "c1", "members": [{"media_id": 10}]}],
    }


def _join() -> dict[int, dict]:
    return {
        1: {"stack_media_id": 10, "image_width": 1000, "image_height": 1000},
        2: {"stack_media_id": 20, "image_width": 1000, "image_height": 1000},
    }


def test_partial_miss_e2e_vs_native() -> None:
    manifest = _manifest()
    export = _export_partial_only()
    join = _join()
    det_n, id_n = to_face_metric_inputs(export, manifest, join, "primary", frame="native")
    det_e, id_e = to_face_metric_inputs(export, manifest, join, "primary", frame="e2e")
    # Detection rows identical across frames.
    assert [(d.image, d.pred_faces, d.labeled_faces, d.matched_faces) for d in det_n] == [
        (d.image, d.pred_faces, d.labeled_faces, d.matched_faces) for d in det_e
    ]
    det = detection_pr(det_e)
    assert det.false_negatives >= 1
    e2e = identification_pr(id_e)
    native = identification_pr(id_n)
    assert e2e.false_negatives > native.false_negatives
    # native must not charge the undetected name the same way
    assert native.false_negatives < e2e.false_negatives


def test_native_recall_below_one_when_box_matched_but_unlabeled() -> None:
    """Native ID recall is failable: a proposed box with no mapped name is an FN."""
    manifest = GoldenManifest(
        manifest_version=2,
        roster=["Alice Q"],
        entries=[
            GoldenEntry(
                path="miss_label.jpg",
                sha256="c" * 64,
                media_id=3,
                face_count=1,
                present_identities=["Alice Q"],
                must_right=[],
                easy_wrong=[],
                policy=EntryPolicy(recognition_enabled=True),
                base_caption="",
                face_boxes=[FaceBox(x=0.5, y=0.5, w=0.2, h=0.2, name="Alice Q", source="iptc")],
            )
        ],
    )
    export = {
        "media_identities": [
            {
                "identity_id": "i1",
                "media_id": 30,
                "cluster_id": "c1",
                "cluster_label": "",
                "is_auto_label": True,
                "bbox": {"x": 400, "y": 400, "width": 200, "height": 200},
            }
        ],
        "clusters": [{"id": "c1", "label": "", "is_auto_label": True}],
        "cluster_members": [],
    }
    join = {3: {"stack_media_id": 30, "image_width": 1000, "image_height": 1000}}
    _det, id_n = to_face_metric_inputs(export, manifest, join, "primary", frame="native")
    native = identification_pr(id_n)
    assert native.recall is not None
    assert native.recall < 1.0
    assert native.false_negatives == 1


def test_optimistic_maps_unlabeled_cluster_by_overlap() -> None:
    from scripts.bench.export_map import map_cluster_labels_optimistic

    manifest = _manifest()
    export = {
        "media_identities": [
            {
                "identity_id": "i1",
                "media_id": 10,
                "cluster_id": "c1",
                "cluster_label": "",
                "is_auto_label": True,
                "bbox": {"x": 200, "y": 200, "width": 200, "height": 200},
            }
        ],
        "clusters": [{"id": "c1", "label": "", "is_auto_label": True}],
        "cluster_members": [],
    }
    join = _join()
    mapped = map_cluster_labels_optimistic(export, manifest, join)
    assert "Alice Q" in mapped.get(10, [])
    primary_only = to_face_metric_inputs(export, manifest, join, "primary", frame="e2e")[1]
    optimistic = to_face_metric_inputs(export, manifest, join, "optimistic", frame="e2e")[1]
    assert identification_pr(optimistic).true_positives > identification_pr(primary_only).true_positives


def test_zero_export_stays_in_both_detection_denominators() -> None:
    manifest = _manifest()
    export = _export_partial_only()
    join = _join()
    det_n, _ = to_face_metric_inputs(export, manifest, join, "primary", frame="native")
    det_e, _ = to_face_metric_inputs(export, manifest, join, "primary", frame="e2e")
    zero_n = next(d for d in det_n if d.image.endswith("zero.jpg") or "2" in d.image)
    zero_e = next(d for d in det_e if d.image.endswith("zero.jpg") or "2" in d.image)
    assert zero_n.pred_faces == 0
    assert zero_e.pred_faces == 0
    assert zero_n.labeled_faces == 1
    assert zero_e.labeled_faces == 1
    native = detection_pr(det_n)
    e2e = detection_pr(det_e)
    assert native.false_negatives >= 1
    assert e2e.false_negatives >= 1
    _ = SAMPLING_FRAME_CROSSBENCH_NATIVE, SAMPLING_FRAME_E2E
