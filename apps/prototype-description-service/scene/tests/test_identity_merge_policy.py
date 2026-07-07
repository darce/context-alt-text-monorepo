"""Slice 3: consent gate + provenance — naming only when every condition holds."""

from scene.application.identity_merge import (
    ConfirmedFace,
    NamingPolicy,
    NamingSkipReason,
    NormalizedBox,
    PhraseBox,
    merge_identities,
    resolve_naming_allowed,
)


def _face(label: str, *, roster_id="roster-1", confidence=0.95, x=0.4) -> ConfirmedFace:
    return ConfirmedFace(
        identity_id=f"identity-{label}",
        cluster_id=f"cluster-id-{label}",
        roster_id=roster_id,
        label=label,
        detection_confidence=confidence,
        box=NormalizedBox(x=x, y=0.2, width=0.05, height=0.08),
    )


def _person_box(caption: str, phrase: str) -> PhraseBox:
    start = caption.index(phrase)
    return PhraseBox(
        phrase=phrase,
        span_start=start,
        span_end=start + len(phrase),
        box=NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.7),
    )


CAPTION = "A man stands by the window."


class TestResolveNamingAllowed:
    def test_allows_eligible_face(self):
        policy = NamingPolicy(agreement_enabled=True, suppressed_roster_ids=frozenset())
        assert resolve_naming_allowed(_face("Daniel"), policy) is True

    def test_agreement_off_blocks(self):
        policy = NamingPolicy(agreement_enabled=False, suppressed_roster_ids=frozenset())
        assert resolve_naming_allowed(_face("Daniel"), policy) is False

    def test_suppressed_roster_blocks(self):
        policy = NamingPolicy(agreement_enabled=True, suppressed_roster_ids=frozenset({"roster-1"}))
        assert resolve_naming_allowed(_face("Daniel"), policy) is False

    def test_low_detection_confidence_blocks(self):
        policy = NamingPolicy(agreement_enabled=True, suppressed_roster_ids=frozenset())
        assert resolve_naming_allowed(_face("Daniel", confidence=0.2), policy) is False


class TestMergeWithPolicy:
    def test_agreement_off_yields_generic_named_draft_with_reason(self):
        policy = NamingPolicy(agreement_enabled=False, suppressed_roster_ids=frozenset())
        result = merge_identities(
            caption=CAPTION,
            phrase_boxes=[_person_box(CAPTION, "A man")],
            confirmed_faces=[_face("Daniel")],
            policy=policy,
        )
        assert result.named_draft == result.generic_draft == CAPTION
        assert result.provenance.naming_allowed is False
        assert result.provenance.reason == NamingSkipReason.AGREEMENT_DISABLED
        assert result.provenance.injected_names == ()

    def test_suppressed_roster_yields_generic(self):
        policy = NamingPolicy(agreement_enabled=True, suppressed_roster_ids=frozenset({"roster-1"}))
        result = merge_identities(
            caption=CAPTION,
            phrase_boxes=[_person_box(CAPTION, "A man")],
            confirmed_faces=[_face("Daniel")],
            policy=policy,
        )
        assert result.named_draft == CAPTION
        assert result.provenance.injected_names == ()
        assert result.provenance.reason == NamingSkipReason.NO_ELIGIBLE_IDENTITIES

    def test_named_result_carries_provenance(self):
        policy = NamingPolicy(agreement_enabled=True, suppressed_roster_ids=frozenset())
        result = merge_identities(
            caption=CAPTION,
            phrase_boxes=[_person_box(CAPTION, "A man")],
            confirmed_faces=[_face("Daniel")],
            policy=policy,
        )
        assert result.named_draft == "Daniel stands by the window."
        assert result.generic_draft == CAPTION
        assert result.provenance.naming_allowed is True
        assert result.provenance.reason is None
        assert len(result.provenance.injected_names) == 1
        injected = result.provenance.injected_names[0]
        assert injected.name == "Daniel"
        assert injected.cluster_id == "cluster-id-Daniel"
        assert injected.roster_id == "roster-1"
        assert injected.match_confidence == 0.95

    def test_no_confirmed_faces_reason(self):
        policy = NamingPolicy(agreement_enabled=True, suppressed_roster_ids=frozenset())
        result = merge_identities(caption=CAPTION, phrase_boxes=[], confirmed_faces=[], policy=policy)
        assert result.named_draft == CAPTION
        assert result.provenance.reason == NamingSkipReason.NO_CONFIRMED_IDENTITIES

    def test_ambiguous_grounding_reason(self):
        policy = NamingPolicy(agreement_enabled=True, suppressed_roster_ids=frozenset())
        result = merge_identities(
            caption=CAPTION,
            phrase_boxes=[_person_box(CAPTION, "A man")],
            confirmed_faces=[_face("Daniel", x=0.35), _face("Sarah", roster_id="roster-2", x=0.5)],
            policy=policy,
        )
        assert result.named_draft == CAPTION
        assert result.provenance.reason == NamingSkipReason.AMBIGUOUS_GROUNDING

    def test_positional_fallback_provenance(self):
        policy = NamingPolicy(agreement_enabled=True, suppressed_roster_ids=frozenset())
        result = merge_identities(
            caption=CAPTION,
            phrase_boxes=[],
            confirmed_faces=[_face("Daniel")],
            policy=policy,
        )
        assert result.named_draft.endswith("Pictured from left: Daniel.")
        assert result.provenance.naming_allowed is True
        assert [n.name for n in result.provenance.injected_names] == ["Daniel"]
