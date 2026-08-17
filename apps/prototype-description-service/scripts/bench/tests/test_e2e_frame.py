"""Dual-frame cascade: detector-miss → ID FN on e2e; zero-export stays in both denominators."""

from __future__ import annotations

from scripts.bench.export_map import to_face_metric_inputs
from scripts.bench.score_report import SAMPLING_FRAME_CROSSBENCH_NATIVE, SAMPLING_FRAME_E2E
from scripts.eval_harness.face_metrics import detection_pr, identification_pr
from scripts.eval_harness.manifest import (
    AnnotationMode,
    EntryPolicy,
    FaceBox,
    GoldenEntry,
    GoldenManifest,
    LabelConfidence,
    LabelDecision,
    LabelLineage,
    LabelSource,
    SUPPORTED_MANIFEST_VERSION,
)

_BENCH_LINEAGE = LabelLineage(
    labeler_id="bench-test",
    batch_id="fir-11-bench-v3",
    capture_session_id="bench-test-session",
    pass_index=0,
    labeled_at="2026-08-16T00:00:00Z",
    tool_version="bench-test",
    saw_machine_proposals=False,
    label_source=LabelSource.GOLD_REFERENCE,
    decision=LabelDecision.NAMED,
    confidence=LabelConfidence.HIGH,
)


def _named_box(*, x: float, y: float, w: float, h: float, name: str, source: str = "iptc") -> FaceBox:
    return FaceBox(x=x, y=y, w=w, h=h, name=name, source=source, lineage=_BENCH_LINEAGE)


def _v3_manifest(*, roster: list[str], entries: list[GoldenEntry]) -> GoldenManifest:
    return GoldenManifest(
        manifest_version=SUPPORTED_MANIFEST_VERSION,
        annotation_mode=AnnotationMode.EXHAUSTIVE,
        roster=roster,
        entries=entries,
    )


def _manifest() -> GoldenManifest:
    return _v3_manifest(
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
                    _named_box(x=0.3, y=0.3, w=0.2, h=0.2, name="Alice Q", source="iptc"),
                    _named_box(x=0.7, y=0.3, w=0.2, h=0.2, name="Bob Z", source="iptc"),
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
                face_boxes=[_named_box(x=0.5, y=0.5, w=0.2, h=0.2, name="Alice Q", source="iptc")],
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
    det = detection_pr(det_e, annotation_mode=AnnotationMode.EXHAUSTIVE)
    assert det.false_negatives >= 1
    e2e = identification_pr(id_e)
    native = identification_pr(id_n)
    assert e2e.false_negatives > native.false_negatives
    # native must not charge the undetected name the same way
    assert native.false_negatives < e2e.false_negatives


def test_native_recall_below_one_when_box_matched_but_unlabeled() -> None:
    """Native ID recall is failable: a proposed box with no mapped name is an FN."""
    manifest = _v3_manifest(
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
                face_boxes=[_named_box(x=0.5, y=0.5, w=0.2, h=0.2, name="Alice Q", source="iptc")],
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


def test_optimistic_native_maps_unlabeled_matched_cluster() -> None:
    """native×optimistic must use the optimistic mapper (FIR-8 R3-02)."""
    manifest = _v3_manifest(
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
                face_boxes=[_named_box(x=0.5, y=0.5, w=0.2, h=0.2, name="Alice Q", source="iptc")],
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
    _det, id_n_opt = to_face_metric_inputs(export, manifest, join, "optimistic", frame="native")
    _det, id_n_pri = to_face_metric_inputs(export, manifest, join, "primary", frame="native")
    _det, id_e_opt = to_face_metric_inputs(export, manifest, join, "optimistic", frame="e2e")
    native_opt = identification_pr(id_n_opt)
    native_pri = identification_pr(id_n_pri)
    e2e_opt = identification_pr(id_e_opt)
    assert id_n_opt[0].predicted == ["Alice Q"]
    assert native_opt.true_positives == 1
    assert native_opt.recall == 1.0
    assert native_pri.false_negatives == 1
    assert e2e_opt.true_positives == 1


def _optimistic_labeled_and_unlabeled_fixture() -> tuple:
    """Unlabeled matched cluster + labeled row. bob_on_alice puts Bob on Alice's box."""
    manifest = _v3_manifest(
        roster=["Alice Q", "Bob Z"],
        entries=[
            GoldenEntry(
                path="pair.jpg",
                sha256="d" * 64,
                media_id=4,
                face_count=2,
                present_identities=["Alice Q", "Bob Z"],
                must_right=[],
                easy_wrong=[],
                policy=EntryPolicy(recognition_enabled=True),
                base_caption="",
                face_boxes=[
                    _named_box(x=0.3, y=0.3, w=0.2, h=0.2, name="Alice Q", source="iptc"),
                    _named_box(x=0.7, y=0.3, w=0.2, h=0.2, name="Bob Z", source="iptc"),
                ],
            )
        ],
    )
    export = {
        "media_identities": [
            {
                "identity_id": "unlabeled-alice",
                "media_id": 40,
                "cluster_id": "c-alice",
                "cluster_label": "",
                "is_auto_label": True,
                "bbox": {"x": 200, "y": 200, "width": 200, "height": 200},
            },
            {
                "identity_id": "labeled-bob",
                "media_id": 40,
                "cluster_id": "c-bob",
                "cluster_label": "Bob Z",
                "is_auto_label": False,
                "bbox": {"x": 600, "y": 200, "width": 200, "height": 200},
            },
        ],
        "clusters": [
            {"id": "c-alice", "label": "", "is_auto_label": True},
            {"id": "c-bob", "label": "Bob Z", "is_auto_label": False},
        ],
        "cluster_members": [],
    }
    join = {4: {"stack_media_id": 40, "image_width": 1000, "image_height": 1000}}
    return manifest, export, join


def test_optimistic_native_and_e2e_name_sets_agree() -> None:
    from scripts.bench.export_map import map_cluster_labels_optimistic

    manifest, export, join = _optimistic_labeled_and_unlabeled_fixture()
    _det, id_n = to_face_metric_inputs(export, manifest, join, "optimistic", frame="native")
    _det, id_e = to_face_metric_inputs(export, manifest, join, "optimistic", frame="e2e")
    native_names = set(id_n[0].predicted)
    e2e_names = set(id_e[0].predicted)
    assert native_names == e2e_names == {"Alice Q", "Bob Z"}
    mapped = map_cluster_labels_optimistic(export, manifest, join)
    assert set(mapped.get(40, [])) == {"Alice Q", "Bob Z"}


def test_optimistic_native_does_not_override_labeled_row() -> None:
    """A labeled pred keeps its primary name even when geometry maps to another GT.

    Both mapper paths honor labeled-wins: e2e does not union the Hungarian GT
    name onto an already-labeled pred.
    """
    from scripts.bench.export_map import map_cluster_labels_optimistic

    manifest = _v3_manifest(
        roster=["Alice Q", "Bob Z"],
        entries=[
            GoldenEntry(
                path="override.jpg",
                sha256="e" * 64,
                media_id=5,
                face_count=1,
                present_identities=["Alice Q"],
                must_right=[],
                easy_wrong=[],
                policy=EntryPolicy(recognition_enabled=True),
                base_caption="",
                face_boxes=[_named_box(x=0.3, y=0.3, w=0.2, h=0.2, name="Alice Q", source="iptc")],
            )
        ],
    )
    export = {
        "media_identities": [
            {
                "identity_id": "labeled-bob",
                "media_id": 50,
                "cluster_id": "c-bob",
                "cluster_label": "Bob Z",
                "is_auto_label": False,
                "bbox": {"x": 200, "y": 200, "width": 200, "height": 200},
            }
        ],
        "clusters": [{"id": "c-bob", "label": "Bob Z", "is_auto_label": False}],
        "cluster_members": [],
    }
    join = {5: {"stack_media_id": 50, "image_width": 1000, "image_height": 1000}}
    _det, id_n = to_face_metric_inputs(export, manifest, join, "optimistic", frame="native")
    _det, id_e = to_face_metric_inputs(export, manifest, join, "optimistic", frame="e2e")
    assert id_n[0].predicted == ["Bob Z"]
    assert id_e[0].predicted == ["Bob Z"]
    mapped = map_cluster_labels_optimistic(export, manifest, join)
    assert mapped.get(50, []) == ["Bob Z"]


def _unlabeled_row(media_id: int, identity_id: str, bbox: dict) -> dict:
    return {
        "identity_id": identity_id,
        "media_id": media_id,
        "cluster_id": identity_id,
        "cluster_label": "",
        "is_auto_label": True,
        "bbox": bbox,
    }


def test_optimistic_two_preds_one_gt_single_claim() -> None:
    """Two unlabeled preds, one GT: Hungarian assigns one pred (FIR-8 R5-03)."""
    from scripts.bench.export_map import _optimistic_names_by_pred_index, map_cluster_labels_optimistic

    manifest = _v3_manifest(
        roster=["Alice Q"],
        entries=[
            GoldenEntry(
                path="two-pred.jpg",
                sha256="f" * 64,
                media_id=6,
                face_count=1,
                present_identities=["Alice Q"],
                must_right=[],
                easy_wrong=[],
                policy=EntryPolicy(recognition_enabled=True),
                base_caption="",
                face_boxes=[_named_box(x=0.3, y=0.3, w=0.2, h=0.2, name="Alice Q", source="iptc")],
            )
        ],
    )
    rows = [
        _unlabeled_row(60, "p-exact", {"x": 200, "y": 200, "width": 200, "height": 200}),
        _unlabeled_row(60, "p-shift", {"x": 220, "y": 200, "width": 200, "height": 200}),
    ]
    export = {
        "media_identities": rows,
        "clusters": [{"id": "p-exact", "label": "", "is_auto_label": True}],
        "cluster_members": [],
    }
    join = {6: {"stack_media_id": 60, "image_width": 1000, "image_height": 1000}}
    native_map = _optimistic_names_by_pred_index(manifest.entries[0], rows, 1000, 1000)
    assert len(native_map) == 1
    assert set(native_map.values()) == {"Alice Q"}
    mapped = map_cluster_labels_optimistic(export, manifest, join)
    names = mapped.get(60, [])
    assert names == ["Alice Q"]
    assert len(names) == len(set(names))


def test_optimistic_one_pred_two_gts_single_claim() -> None:
    """One unlabeled pred, two leftover GTs: fallback claims once (FIR-8 R5-03)."""
    from scripts.bench.export_map import _optimistic_names_by_pred_index, map_cluster_labels_optimistic

    manifest = _v3_manifest(
        roster=["Alice Q", "Bob Z"],
        entries=[
            GoldenEntry(
                path="one-pred.jpg",
                sha256="a1" * 32,
                media_id=7,
                face_count=2,
                present_identities=["Alice Q", "Bob Z"],
                must_right=[],
                easy_wrong=[],
                policy=EntryPolicy(recognition_enabled=True),
                base_caption="",
                face_boxes=[
                    _named_box(x=0.3, y=0.3, w=0.2, h=0.2, name="Alice Q", source="iptc"),
                    _named_box(x=0.7, y=0.3, w=0.2, h=0.2, name="Bob Z", source="iptc"),
                ],
            )
        ],
    )
    rows = [_unlabeled_row(70, "p-wide", {"x": 100, "y": 100, "width": 800, "height": 800})]
    export = {
        "media_identities": rows,
        "clusters": [{"id": "p-wide", "label": "", "is_auto_label": True}],
        "cluster_members": [],
    }
    join = {7: {"stack_media_id": 70, "image_width": 1000, "image_height": 1000}}
    native_map = _optimistic_names_by_pred_index(manifest.entries[0], rows, 1000, 1000)
    assert native_map == {0: "Alice Q"}
    mapped = map_cluster_labels_optimistic(export, manifest, join)
    names = mapped.get(70, [])
    assert names == ["Alice Q"]
    assert len(names) == len(set(names))


def test_optimistic_e2e_dedupes_repeated_gt_name() -> None:
    """Two same-name GTs + two preds: e2e list is deduped (FIR-8 R5-03)."""
    from scripts.bench.export_map import _optimistic_names_by_pred_index, map_cluster_labels_optimistic

    manifest = _v3_manifest(
        roster=["Alice Q"],
        entries=[
            GoldenEntry(
                path="dup.jpg",
                sha256="b2" * 32,
                media_id=8,
                face_count=2,
                present_identities=["Alice Q"],
                must_right=[],
                easy_wrong=[],
                policy=EntryPolicy(recognition_enabled=True),
                base_caption="",
                face_boxes=[
                    _named_box(x=0.3, y=0.3, w=0.2, h=0.2, name="Alice Q", source="iptc"),
                    _named_box(x=0.7, y=0.3, w=0.2, h=0.2, name="Alice Q", source="iptc"),
                ],
            )
        ],
    )
    rows = [
        _unlabeled_row(80, "p-a", {"x": 200, "y": 200, "width": 200, "height": 200}),
        _unlabeled_row(80, "p-b", {"x": 600, "y": 200, "width": 200, "height": 200}),
    ]
    export = {
        "media_identities": rows,
        "clusters": [{"id": "p-a", "label": "", "is_auto_label": True}],
        "cluster_members": [],
    }
    join = {8: {"stack_media_id": 80, "image_width": 1000, "image_height": 1000}}
    native_map = _optimistic_names_by_pred_index(manifest.entries[0], rows, 1000, 1000)
    assert set(native_map.values()) == {"Alice Q"}
    assert len(native_map) == 2
    mapped = map_cluster_labels_optimistic(export, manifest, join)
    names = mapped.get(80, [])
    assert names == ["Alice Q"]
    assert len(names) == 1


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
    native = detection_pr(det_n, annotation_mode=AnnotationMode.EXHAUSTIVE)
    e2e = detection_pr(det_e, annotation_mode=AnnotationMode.EXHAUSTIVE)
    assert native.false_negatives >= 1
    assert e2e.false_negatives >= 1
    _ = SAMPLING_FRAME_CROSSBENCH_NATIVE, SAMPLING_FRAME_E2E


def test_native_predictions_restricted_to_matched_faces() -> None:
    """Unmatched-face mapper names must not enter predicted_native."""
    manifest = _v3_manifest(
        roster=["Alice Q", "Bob Z"],
        entries=[
            GoldenEntry(
                path="split.jpg",
                sha256="e" * 64,
                media_id=1,
                face_count=2,
                present_identities=["Alice Q", "Bob Z"],
                must_right=[],
                easy_wrong=[],
                policy=EntryPolicy(recognition_enabled=True),
                base_caption="",
                face_boxes=[
                    _named_box(x=0.3, y=0.3, w=0.2, h=0.2, name="Alice Q", source="iptc"),
                    _named_box(x=0.7, y=0.3, w=0.2, h=0.2, name="Bob Z", source="iptc"),
                ],
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
                "bbox": {"x": 200, "y": 200, "width": 200, "height": 200},
            },
            {
                "identity_id": "i2",
                "media_id": 10,
                "cluster_id": "c2",
                "cluster_label": "Bob Z",
                "is_auto_label": False,
                "bbox": {"x": 0, "y": 0, "width": 10, "height": 10},
            },
        ],
        "clusters": [
            {"id": "c1", "label": "Alice Q", "is_auto_label": False},
            {"id": "c2", "label": "Bob Z", "is_auto_label": False},
        ],
        "cluster_members": [],
    }
    join = {1: {"stack_media_id": 10, "image_width": 1000, "image_height": 1000}}
    _det_e, id_e = to_face_metric_inputs(export, manifest, join, "primary", frame="e2e")
    _det_n, id_n = to_face_metric_inputs(export, manifest, join, "primary", frame="native")
    e2e = identification_pr(id_e)
    native = identification_pr(id_n)
    assert set(id_e[0].predicted) == {"Alice Q", "Bob Z"}
    assert id_n[0].predicted == ["Alice Q"]
    assert id_n[0].labeled == ["Alice Q"]
    assert e2e.precision == 1.0
    assert native.precision == 1.0
    assert native.false_positives == 0
    assert e2e.true_positives == 2
    assert native.true_positives == 1
