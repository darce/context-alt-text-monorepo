"""Slice 2: reflow realizers behind the ReflowRealizer seam (PA-03).

One test per enumerated rule R1–R4, the positional fallback, and a seam-swap
test proving merge_identities has no inline mode ladder.
"""

from scene.application.identity_merge import (
    ConfirmedFace,
    DeterministicNlgRealizer,
    NormalizedBox,
    PhraseBox,
    PositionalFallbackRealizer,
    ReflowRealizer,
    merge_identities,
)
from scene.application.identity_merge.merge import IdentityAssociation


def _face(label: str, *, x: float = 0.4) -> ConfirmedFace:
    return ConfirmedFace(
        identity_id=f"identity-{label}",
        cluster_id=f"cluster-id-{label}",
        roster_id=f"roster-{label}",
        label=label,
        detection_confidence=0.95,
        box=NormalizedBox(x=x, y=0.2, width=0.05, height=0.08),
    )


def _assoc(caption: str, phrase: str, label: str, *, occurrence: int = 0, x: float = 0.4) -> IdentityAssociation:
    start = -1
    for _ in range(occurrence + 1):
        start = caption.index(phrase, start + 1)
    return IdentityAssociation(
        face=_face(label, x=x),
        phrase_box=PhraseBox(
            phrase=phrase,
            span_start=start,
            span_end=start + len(phrase),
            box=NormalizedBox(x=x - 0.1, y=0.1, width=0.3, height=0.7),
        ),
    )


class TestDeterministicNlgRealizer:
    def test_r1_article_elision_and_case(self):
        realizer = DeterministicNlgRealizer()
        caption = "A man stands by the window."
        named = realizer.realize(
            caption=caption,
            associations=[_assoc(caption, "A man", "Daniel")],
            confirmed_faces=[],
        )
        assert named == "Daniel stands by the window."

    def test_r1_mid_sentence_article_elision(self):
        realizer = DeterministicNlgRealizer()
        caption = "A dog sits near a woman."
        named = realizer.realize(
            caption=caption,
            associations=[_assoc(caption, "a woman", "Sarah")],
            confirmed_faces=[],
        )
        assert named == "A dog sits near Sarah."

    def test_r2_possessive_form_preserved(self):
        realizer = DeterministicNlgRealizer()
        caption = "A man's hat lies on the table."
        named = realizer.realize(
            caption=caption,
            associations=[_assoc(caption, "A man's hat", "Daniel")],
            confirmed_faces=[],
        )
        assert named == "Daniel's hat lies on the table."

    def test_r3_list_aggregation(self):
        realizer = DeterministicNlgRealizer()
        assert realizer.aggregate_names(["Daniel"]) == "Daniel"
        assert realizer.aggregate_names(["Daniel", "Sarah"]) == "Daniel and Sarah"
        assert realizer.aggregate_names(["Daniel", "Sarah", "Tom"]) == "Daniel, Sarah and Tom"

    def test_r4_repeated_mention_coreference(self):
        realizer = DeterministicNlgRealizer()
        caption = "A man opens the door. A man waves."
        named = realizer.realize(
            caption=caption,
            associations=[
                _assoc(caption, "A man", "Daniel", occurrence=0),
                _assoc(caption, "A man", "Daniel", occurrence=1),
            ],
            confirmed_faces=[],
        )
        assert named == "Daniel opens the door. They wave."


class TestPositionalFallbackRealizer:
    def test_orders_faces_left_to_right_and_appends(self):
        realizer = PositionalFallbackRealizer()
        caption = "Two people sit at a table."
        named = realizer.realize(
            caption=caption,
            associations=[],
            confirmed_faces=[_face("Sarah", x=0.7), _face("Daniel", x=0.2)],
        )
        assert named == "Two people sit at a table. Pictured from left: Daniel and Sarah."


class _UpperCaseFakeRealizer:
    """Seam-swap fake: proves the realizer is injected, not hardcoded."""

    def realize(self, *, caption, associations, confirmed_faces):
        return caption.upper()


class TestSeamSelection:
    def test_merge_uses_injected_realizer(self):
        caption = "A man stands by the window."
        assoc = _assoc(caption, "A man", "Daniel")
        result = merge_identities(
            caption=caption,
            phrase_boxes=[assoc.phrase_box],
            confirmed_faces=[assoc.face],
            realizer=_UpperCaseFakeRealizer(),
        )
        assert result.named_draft == caption.upper()
        assert isinstance(_UpperCaseFakeRealizer(), ReflowRealizer)

    def test_default_realizer_produces_named_draft(self):
        caption = "A man stands by the window."
        assoc = _assoc(caption, "A man", "Daniel")
        result = merge_identities(
            caption=caption,
            phrase_boxes=[assoc.phrase_box],
            confirmed_faces=[assoc.face],
        )
        assert result.named_draft == "Daniel stands by the window."
        assert result.generic_draft == caption

    def test_no_phrase_boxes_selects_positional_fallback(self):
        caption = "Two people sit at a table."
        result = merge_identities(
            caption=caption,
            phrase_boxes=[],
            confirmed_faces=[_face("Sarah", x=0.7), _face("Daniel", x=0.2)],
        )
        assert result.named_draft == "Two people sit at a table. Pictured from left: Daniel and Sarah."

    def test_ambiguous_grounding_stays_generic(self):
        # Phrase boxes exist but two faces land in the same box: no fallback,
        # no names — ambiguity degrades to generic.
        caption = "A person stands by the window."
        box = PhraseBox(
            phrase="A person",
            span_start=0,
            span_end=8,
            box=NormalizedBox(x=0.1, y=0.1, width=0.6, height=0.8),
        )
        result = merge_identities(
            caption=caption,
            phrase_boxes=[box],
            confirmed_faces=[_face("Daniel", x=0.3), _face("Sarah", x=0.5)],
        )
        assert result.named_draft == caption
