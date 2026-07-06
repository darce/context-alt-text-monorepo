"""VLM-2A Slice 2: face metrics — detection + identification P/R, full scope edge ledger."""

import pytest

from scripts.eval_harness.face_metrics import (
    ImageDetection,
    ImageIdentities,
    detection_pr,
    identification_pr,
)

# --- detection level (identity-agnostic) ---


def test_detection_micro_counts():
    items = [
        ImageDetection(image="a.jpg", pred_faces=2, labeled_faces=2),
        ImageDetection(image="b.jpg", pred_faces=3, labeled_faces=2),  # 1 FP
        ImageDetection(image="c.jpg", pred_faces=1, labeled_faces=2),  # 1 FN
    ]
    result = detection_pr(items)
    assert result.true_positives == 5
    assert result.false_positives == 1
    assert result.false_negatives == 1
    assert result.precision == pytest.approx(5 / 6)
    assert result.recall == pytest.approx(5 / 6)


def test_detection_zero_face_corpus_has_null_precision():
    items = [ImageDetection(image="glacier.jpg", pred_faces=0, labeled_faces=0)]
    result = detection_pr(items)
    assert result.precision is None  # undefined, never 1.0
    assert result.recall is None


def test_detection_spurious_faces_on_empty_image():
    items = [ImageDetection(image="glacier.jpg", pred_faces=2, labeled_faces=0)]
    result = detection_pr(items)
    assert result.precision == 0.0
    assert result.recall is None


# --- identification level (named assertions vs labeled identities) ---


def test_identification_micro_and_wrong_names():
    items = [
        ImageIdentities(image="a.jpg", predicted=["Alice"], labeled=["Alice"]),
        ImageIdentities(image="b.jpg", predicted=["Bob"], labeled=["Alice"]),
    ]
    result = identification_pr(items)
    assert result.true_positives == 1
    assert result.false_positives == 1
    assert result.false_negatives == 1
    # wrong-name = top product risk: listed individually
    assert result.wrong_names == [("b.jpg", "Bob")]


def test_identification_duplicate_identity_deduped():
    # same person in multiple crops: dedupe by identity, not by face
    items = [
        ImageIdentities(image="a.jpg", predicted=["Alice", "Alice"], labeled=["Alice"]),
    ]
    result = identification_pr(items)
    assert result.true_positives == 1
    assert result.false_positives == 0
    assert result.precision == 1.0


def test_identification_stranger_true_rejection_not_penalized():
    items = [
        ImageIdentities(image="nina.jpg", predicted=[], labeled=[], stranger_faces=1),
    ]
    result = identification_pr(items)
    assert result.true_rejections == 1
    assert result.false_positives == 0
    assert result.precision is None  # no assertions made: undefined, not 1.0


def test_identification_stranger_true_rejection_in_mixed_image():  # S2-05
    # roster person correctly named AND a stranger present with no wrong name:
    # the stranger is a true rejection even though the image is not all-empty.
    items = [
        ImageIdentities(image="group.jpg", predicted=["Ryann"], labeled=["Ryann"], stranger_faces=2),
    ]
    result = identification_pr(items)
    assert result.true_rejections == 1
    assert result.true_positives == 1


def test_identification_wrong_name_on_stranger_image_is_not_a_true_rejection():  # S2-05
    items = [
        ImageIdentities(image="group.jpg", predicted=["Bob"], labeled=["Ryann"], stranger_faces=1),
    ]
    result = identification_pr(items)
    assert result.true_rejections == 0  # a wrong name was asserted -> not a clean rejection
    assert result.wrong_names == [("group.jpg", "Bob")]


def test_identification_policy_disabled_excluded():
    items = [
        ImageIdentities(
            image="a.jpg",
            predicted=["Alice"],
            labeled=["Alice"],
            recognition_enabled=False,
        ),
        ImageIdentities(image="b.jpg", predicted=["Bob"], labeled=["Bob"]),
    ]
    result = identification_pr(items)
    assert result.true_positives == 1  # only b.jpg counted
    assert result.excluded_images == ["a.jpg"]


def test_identification_macro_diverges_from_micro():
    # Alice: 10 images all correct; Bob: 1 image, missed.
    items = [ImageIdentities(image=f"alice-{i}.jpg", predicted=["Alice"], labeled=["Alice"]) for i in range(10)] + [
        ImageIdentities(image="bob.jpg", predicted=[], labeled=["Bob"])
    ]
    result = identification_pr(items)
    assert result.recall == pytest.approx(10 / 11)  # micro masks Bob
    assert result.per_identity["Alice"].recall == 1.0
    assert result.per_identity["Bob"].recall == 0.0
    assert result.macro_recall == pytest.approx(0.5)  # macro exposes him


def test_identification_per_identity_precision_counts_wrong_name_against_predicted_name():
    items = [
        ImageIdentities(image="b.jpg", predicted=["Bob"], labeled=["Alice"]),
    ]
    result = identification_pr(items)
    assert result.per_identity["Bob"].precision == 0.0
    assert result.per_identity["Alice"].recall == 0.0
