"""Slice 1: merge core — normalize_bbox, containment_match, merge_identities skeleton.

Pure unit tests, no DB and no VLM. Phrase boxes use the VLM-2C seed frame:
coords normalized [0,1] as fractions of the original W×H, origin top-left.
"""

import pytest

from scene.application.identity_merge import (
    ConfirmedFace,
    MergeResult,
    NamingMode,
    NamingPolicy,
    NamingSkipReason,
    NamingStatus,
    NormalizedBox,
    PhraseBox,
    containment_match,
    merge_identities,
    normalize_bbox,
)
from scene.tests.identity_merge_helpers import make_face


def _face(label: str, box: NormalizedBox, *, confidence: float = 0.95) -> ConfirmedFace:
    return make_face(label, box=box, roster_id=f"roster-{label}", confidence=confidence)


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
        cx, cy = box.center
        assert cx == pytest.approx(0.4)
        assert cy == pytest.approx(0.3)
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


def _enabled_policy(*, suppressed_roster_ids: frozenset = frozenset()) -> NamingPolicy:
    return NamingPolicy(agreement_enabled=True, suppressed_roster_ids=suppressed_roster_ids)


class TestNamingSkipStatusDistinctFromNoFaces:
    """C4: skip reasons keep their own status wire values; they do not collapse to no_faces."""

    def test_no_confirmed_identities_status_is_the_reason_not_no_faces(self):
        caption = "A man stands by the window."
        result = merge_identities(
            caption=caption,
            phrase_boxes=[],
            confirmed_faces=[],
            policy=_enabled_policy(),
        )
        assert result.named_draft == caption
        assert result.provenance.reason is NamingSkipReason.NO_CONFIRMED_IDENTITIES
        assert result.provenance.status is NamingStatus.NO_CONFIRMED_IDENTITIES
        assert type(result.provenance.status) is NamingStatus
        assert result.provenance.status is not NamingStatus.NO_FACES

    def test_no_eligible_identities_status_is_the_reason_not_no_faces(self):
        caption = "A man stands by the window."
        face = _face("Daniel", NormalizedBox(x=0.4, y=0.2, width=0.05, height=0.08))
        person = _person_phrase("A man", NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.7))
        result = merge_identities(
            caption=caption,
            phrase_boxes=[person],
            confirmed_faces=[face],
            policy=_enabled_policy(suppressed_roster_ids=frozenset({face.roster_id})),
        )
        assert result.named_draft == caption
        assert result.provenance.reason is NamingSkipReason.NO_ELIGIBLE_IDENTITIES
        assert result.provenance.status is NamingStatus.NO_ELIGIBLE_IDENTITIES
        assert type(result.provenance.status) is NamingStatus
        assert result.provenance.status is not NamingStatus.NO_FACES

    def test_ambiguous_grounding_status_is_the_reason_not_no_faces(self):
        caption = "A man stands by the window."
        person = _person_phrase("A man", NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.8))
        result = merge_identities(
            caption=caption,
            phrase_boxes=[person],
            confirmed_faces=[
                _face("Daniel", NormalizedBox(x=0.35, y=0.2, width=0.04, height=0.06)),
                _face("Sarah", NormalizedBox(x=0.5, y=0.2, width=0.04, height=0.06)),
            ],
            policy=_enabled_policy(),
        )
        assert result.named_draft == caption
        assert result.provenance.reason is NamingSkipReason.AMBIGUOUS_GROUNDING
        assert result.provenance.status is NamingStatus.AMBIGUOUS_GROUNDING
        assert type(result.provenance.status) is NamingStatus
        assert result.provenance.status is not NamingStatus.NO_FACES

    def test_agreement_disabled_status_stays_disabled(self):
        caption = "A man stands by the window."
        face = _face("Daniel", NormalizedBox(x=0.4, y=0.2, width=0.05, height=0.08))
        person = _person_phrase("A man", NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.7))
        result = merge_identities(
            caption=caption,
            phrase_boxes=[person],
            confirmed_faces=[face],
            policy=NamingPolicy(agreement_enabled=False, suppressed_roster_ids=frozenset()),
        )
        assert result.provenance.reason is NamingSkipReason.AGREEMENT_DISABLED
        assert result.provenance.status is NamingStatus.DISABLED

    def test_applied_status_unchanged_when_a_name_is_woven(self):
        caption = "A man stands by the window."
        face = _face("Daniel", NormalizedBox(x=0.4, y=0.2, width=0.05, height=0.08))
        person = _person_phrase("A man", NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.7))
        result = merge_identities(
            caption=caption,
            phrase_boxes=[person],
            confirmed_faces=[face],
            policy=_enabled_policy(),
        )
        assert result.named_draft != caption
        assert result.provenance.reason is None
        assert result.provenance.status is NamingStatus.APPLIED

    def test_http_schema_round_trips_new_skip_statuses(self):
        from scene.interface_adapters.http.schemas.responses import (
            NamingProvenance as HttpNamingProvenance,
        )

        for status in (
            NamingStatus.NO_CONFIRMED_IDENTITIES,
            NamingStatus.NO_ELIGIBLE_IDENTITIES,
            NamingStatus.AMBIGUOUS_GROUNDING,
        ):
            model = HttpNamingProvenance(status=status)
            dumped = model.model_dump()
            restored = HttpNamingProvenance.model_validate(dumped)
            assert restored.status is status
            assert type(restored.status) is NamingStatus
            assert model.model_dump(mode="json")["status"] == status.value


def _stale_phrase(caption: str) -> PhraseBox:
    """Span offsets sit past the caption, so span_replaceable is false."""
    start = len(caption) + 1
    return PhraseBox(
        phrase="a ghost",
        span_start=start,
        span_end=start + 7,
        box=NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.7),
    )


class TestNoBoxFallbackReadsVerifiedList:
    """Unverifiable rows must not keep the no-box fallback from running."""

    def test_only_unverifiable_rows_match_empty_payload(self):
        caption = "A man stands by the window."
        face = _face("Daniel", NormalizedBox(x=0.4, y=0.2, width=0.05, height=0.08))
        policy = _enabled_policy()
        kwargs = {"caption": caption, "confirmed_faces": [face], "policy": policy}
        stale = merge_identities(phrase_boxes=[_stale_phrase(caption)], **kwargs)
        empty = merge_identities(phrase_boxes=[], **kwargs)
        assert stale.named_draft == empty.named_draft
        assert stale.named_draft != caption
        assert stale.provenance.mode == empty.provenance.mode
        assert stale.provenance.mode is NamingMode.SUBSTITUTED
        assert stale.associations == empty.associations == ()

    def test_verifiable_unmatched_plus_unverifiable_does_not_fallback(self):
        caption = "A man stands by the window."
        face = _face("Daniel", NormalizedBox(x=0.4, y=0.2, width=0.05, height=0.08))
        unmatched = _person_phrase("A man", NormalizedBox(x=0.8, y=0.1, width=0.15, height=0.3))
        policy = _enabled_policy()
        mixed = merge_identities(
            caption=caption,
            phrase_boxes=[unmatched, _stale_phrase(caption)],
            confirmed_faces=[face],
            policy=policy,
        )
        verifiable_only = merge_identities(
            caption=caption,
            phrase_boxes=[unmatched],
            confirmed_faces=[face],
            policy=policy,
        )
        assert mixed.named_draft == verifiable_only.named_draft == caption
        assert mixed.associations == verifiable_only.associations == ()
        assert mixed.provenance.reason is NamingSkipReason.AMBIGUOUS_GROUNDING
        assert mixed.provenance.mode is verifiable_only.provenance.mode


class TestUngroundedNGe2PositionalGate:
    """Z11: ungrounded n>=2 abstains until position eval; n==1 substitution stays."""

    def test_two_ungrounded_people_keep_generic_draft(self):
        caption = "Two people sit at a table."
        result = merge_identities(
            caption=caption,
            phrase_boxes=[],
            confirmed_faces=[
                _face("Sarah", NormalizedBox(x=0.7, y=0.2, width=0.05, height=0.08)),
                _face("Daniel", NormalizedBox(x=0.2, y=0.2, width=0.05, height=0.08)),
            ],
        )
        assert result.named_draft == caption
        assert result.generic_draft == caption
        assert result.associations == ()
        assert "Pictured from left" not in result.named_draft
        assert "Daniel" not in result.named_draft
        assert "Sarah" not in result.named_draft

    def test_two_ungrounded_people_with_policy_are_ambiguous_grounding(self):
        caption = "A man stands by the window."
        result = merge_identities(
            caption=caption,
            phrase_boxes=[],
            confirmed_faces=[
                _face("Ada", NormalizedBox(x=0.1, y=0.2, width=0.05, height=0.08)),
                _face("Bob", NormalizedBox(x=0.6, y=0.2, width=0.05, height=0.08)),
            ],
            policy=_enabled_policy(),
        )
        assert result.named_draft == caption
        assert result.provenance.naming_allowed is False
        assert result.provenance.reason is NamingSkipReason.AMBIGUOUS_GROUNDING
        assert result.provenance.status is NamingStatus.AMBIGUOUS_GROUNDING
        assert result.provenance.mode is None
        assert result.provenance.realizer is None
        assert result.provenance.names_applied == ()

    def test_n1_substitution_still_weaves_the_name(self):
        caption = "A man stands by the window."
        result = merge_identities(
            caption=caption,
            phrase_boxes=[],
            confirmed_faces=[_face("Daniel", NormalizedBox(x=0.4, y=0.2, width=0.05, height=0.08))],
            policy=_enabled_policy(),
        )
        assert result.named_draft == "Daniel stands by the window."
        assert result.provenance.mode is NamingMode.SUBSTITUTED
        assert result.provenance.status is NamingStatus.APPLIED

    def test_n1_positional_fallback_still_applies_when_substitution_does_not(self):
        caption = "Two people sit at a table."
        result = merge_identities(
            caption=caption,
            phrase_boxes=[],
            confirmed_faces=[_face("Daniel", NormalizedBox(x=0.4, y=0.2, width=0.05, height=0.08))],
            policy=_enabled_policy(),
        )
        assert result.named_draft == "Two people sit at a table. Pictured from left: Daniel."
        assert result.provenance.mode is NamingMode.POSITIONAL

    def test_two_faces_same_cluster_remain_n1_substitution(self):
        caption = "A man stands by the window."
        left = make_face(
            "Daniel",
            box=NormalizedBox(x=0.2, y=0.2, width=0.05, height=0.08),
            roster_id="roster-Daniel",
            cluster_id="cluster-daniel",
        )
        right = make_face(
            "Daniel",
            box=NormalizedBox(x=0.6, y=0.2, width=0.05, height=0.08),
            roster_id="roster-Daniel",
            cluster_id="cluster-daniel",
        )
        result = merge_identities(
            caption=caption,
            phrase_boxes=[],
            confirmed_faces=[left, right],
            policy=_enabled_policy(),
        )
        assert result.named_draft == "Daniel stands by the window."
        assert result.provenance.mode is NamingMode.SUBSTITUTED
