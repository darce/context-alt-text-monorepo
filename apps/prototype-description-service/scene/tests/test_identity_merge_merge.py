"""Slice 1: merge core — normalize_bbox, containment_match, merge_identities skeleton.

Pure unit tests, no DB and no VLM. Phrase boxes use the VLM-2C seed frame:
coords normalized [0,1] as fractions of the original W×H, origin top-left.
"""

import pytest

from scene.application.identity_merge import (
    ConfirmedFace,
    MergeResult,
    NormalizedBox,
    PhraseBox,
    containment_match,
    merge_identities,
    normalize_bbox,
)


def _face(label: str, box: NormalizedBox, *, confidence: float = 0.95) -> ConfirmedFace:
    return ConfirmedFace(
        identity_id=f"identity-{label}",
        cluster_id=f"cluster-id-{label}",
        roster_id=f"roster-{label}",
        label=label,
        detection_confidence=confidence,
        box=box,
    )


def _person_phrase(phrase: str, box: NormalizedBox, start: int = 0) -> PhraseBox:
    return PhraseBox(phrase=phrase, span_start=start, span_end=start + len(phrase), box=box)


class TestNormalizeBbox:
    def test_pixels_to_unit_fractions_top_left(self):
        box = normalize_bbox(x=100, y=50, width=200, height=100, image_width=1000, image_height=500)
        assert box == NormalizedBox(x=0.1, y=0.1, width=0.2, height=0.2)

    def test_resolution_independence(self):
        full = normalize_bbox(x=400, y=200, width=800, height=400, image_width=4000, image_height=2000)
        down = normalize_bbox(x=100, y=50, width=200, height=100, image_width=1000, image_height=500)
        assert full == down

    def test_rejects_nonpositive_image_dims(self):
        with pytest.raises(ValueError):
            normalize_bbox(x=0, y=0, width=1, height=1, image_width=0, image_height=100)

    def test_center_and_area(self):
        box = NormalizedBox(x=0.2, y=0.2, width=0.4, height=0.2)
        assert box.center == (pytest.approx(0.4), pytest.approx(0.3))
        assert box.area == pytest.approx(0.08)


class TestContainmentMatch:
    def test_face_center_in_person_box_matches(self):
        face = _face("Daniel", NormalizedBox(x=0.4, y=0.2, width=0.05, height=0.08))
        person = _person_phrase("a man", NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.7))
        matches = containment_match([face], [person])
        assert len(matches) == 1
        assert matches[0].face is face
        assert matches[0].phrase_box is person

    def test_picks_smallest_containing_box(self):
        face = _face("Daniel", NormalizedBox(x=0.45, y=0.25, width=0.04, height=0.06))
        whole_scene = _person_phrase("two people at a table", NormalizedBox(x=0.0, y=0.0, width=1.0, height=1.0))
        person = _person_phrase("a man", NormalizedBox(x=0.35, y=0.1, width=0.25, height=0.8), start=30)
        matches = containment_match([face], [whole_scene, person])
        assert len(matches) == 1
        assert matches[0].phrase_box is person

    def test_two_faces_in_one_box_is_ambiguous_no_match(self):
        face_a = _face("Daniel", NormalizedBox(x=0.35, y=0.2, width=0.04, height=0.06))
        face_b = _face("Sarah", NormalizedBox(x=0.5, y=0.2, width=0.04, height=0.06))
        person = _person_phrase("a person", NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.8))
        assert containment_match([face_a, face_b], [person]) == []

    def test_face_center_outside_all_boxes_no_match(self):
        face = _face("Daniel", NormalizedBox(x=0.8, y=0.8, width=0.05, height=0.05))
        person = _person_phrase("a man", NormalizedBox(x=0.1, y=0.1, width=0.3, height=0.5))
        assert containment_match([face], [person]) == []

    def test_area_ratio_guard_rejects_face_as_big_as_phrase(self):
        # Face box nearly the size of the phrase box: containment is meaningless.
        face = _face("Daniel", NormalizedBox(x=0.32, y=0.12, width=0.26, height=0.56))
        person = _person_phrase("a man", NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.6))
        assert containment_match([face], [person]) == []


class TestMergeIdentitiesSkeleton:
    def test_returns_associations_and_untouched_generic_draft(self):
        caption = "A man stands by the window."
        face = _face("Daniel", NormalizedBox(x=0.4, y=0.2, width=0.05, height=0.08))
        person = _person_phrase("A man", NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.7))
        result = merge_identities(caption=caption, phrase_boxes=[person], confirmed_faces=[face])
        assert isinstance(result, MergeResult)
        assert result.generic_draft == caption
        assert len(result.associations) == 1
        assert result.associations[0].face.label == "Daniel"

    def test_no_faces_yields_no_associations_and_generic_named_draft(self):
        caption = "A dog on a beach."
        result = merge_identities(caption=caption, phrase_boxes=[], confirmed_faces=[])
        assert result.associations == ()
        assert result.named_draft == caption
        assert result.generic_draft == caption
