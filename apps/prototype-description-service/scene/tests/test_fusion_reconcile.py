"""E20-FUSION S2: Stage-2 reconciliation — object / caption / dropped decisions.

Uses real producer shapes: ContextPack (requests.py), VisualFactsPrior
(visual_facts_pass.py), ConfirmedFace/PhraseBox/MergeResult (merge.py).
"""

from __future__ import annotations

from scene.application.fusion import (
    AttachmentAltitude,
    AttachmentDecision,
    BrandDetection,
    BrandFact,
    FactSource,
    ReviewReason,
    reconcile_context_facts,
)
from scene.application.identity_merge import NamingPolicy, NormalizedBox
from scene.application.visual_facts_pass import VisualFactsPrior, VisualFactsPriorSource
from scene.interface_adapters.http.schemas.requests import (
    AttachmentContext,
    ContextPack,
    IdentityContext,
    IdentityContextItem,
    IdentityPolicyContext,
    PostContext,
    ProductContext,
    TaxonomyTermContext,
)
from scene.tests.identity_merge_helpers import make_face, make_phrase_box

CAPTION = "A person standing outdoors near greenery."
PERSON_BOX = NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.7)
FACE_BOX = NormalizedBox(x=0.4, y=0.2, width=0.05, height=0.08)


def _prior(caption: str = CAPTION, *, objects: list[str] | None = None) -> VisualFactsPrior:
    return VisualFactsPrior(
        caption=caption,
        objects=objects if objects is not None else ["person", "plant"],
        text=None,
        source=VisualFactsPriorSource.ISOLATION_PASS,
    )


def _identity_item(
    name: str = "Slate Willow",
    *,
    cluster_id: str | None = "cluster-maria",
    identity_id: str | None = "identity-maria",
) -> IdentityContextItem:
    return IdentityContextItem(
        name=name,
        identity_id=identity_id,
        cluster_id=cluster_id,
        source="roster",
    )


def _pack_with_identity(
    *items: IdentityContextItem,
    person_naming: str = "allowed",
    review_reasons: list[str] | None = None,
    **kwargs,
) -> ContextPack:
    return ContextPack(
        identity=IdentityContext(
            policy=IdentityPolicyContext(person_naming=person_naming),
            identities=list(items),
            review_reasons=review_reasons or [],
        ),
        **kwargs,
    )


def test_object_attach_identity_via_merge_containment():
    """Identity with face center inside person phrase box → object attach."""
    item = _identity_item()
    pack = _pack_with_identity(item)
    face = make_face(
        item.name,
        box=FACE_BOX,
        cluster_id=item.cluster_id,
        identity_id=item.identity_id,
        roster_id="roster-maria",
    )
    phrase = make_phrase_box("person", CAPTION, box=PERSON_BOX)

    results = reconcile_context_facts(
        context_pack=pack,
        visual_prior=_prior(),
        confirmed_faces=[face],
        phrase_boxes=[phrase],
        naming_policy=NamingPolicy(agreement_enabled=True),
    )

    identity_atts = [a for a in results if a.fact_source is FactSource.IDENTITY]
    assert len(identity_atts) == 1
    att = identity_atts[0]
    assert att.decision is AttachmentDecision.OBJECT
    assert att.altitude is AttachmentAltitude.OBJECT
    assert att.visible is True
    assert att.fact_label == "Slate Willow"
    assert att.target_evidence == "person"
    assert att.review_reason is None
    assert att.fact_id == "identity:cluster:cluster-maria"


def test_ineligible_colocated_face_blocks_object_attach():
    """EH-01: a policy-ineligible face sharing the smallest phrase box must
    still trip the same-region ambiguity guard for an eligible identity.

    merge_identities filters ineligible faces before its 1:1 containment guard,
    so without the full-set geometry re-check the eligible identity would
    object-attach over a region actually shared by a second (un-nameable) face.
    """
    item = _identity_item(name="Alice", cluster_id="cluster-a", identity_id="id-a")
    pack = _pack_with_identity(item)
    eligible = make_face(
        "Alice",
        box=NormalizedBox(x=0.40, y=0.20, width=0.05, height=0.08),
        cluster_id="cluster-a",
        identity_id="id-a",
        roster_id="roster-a",
    )
    # Different person, no roster_id => policy-ineligible; center inside the
    # SAME (only) phrase box as the eligible face.
    ineligible = make_face(
        "Unknown",
        box=NormalizedBox(x=0.50, y=0.50, width=0.05, height=0.08),
        cluster_id="cluster-b",
        identity_id="id-b",
        roster_id=None,
    )
    phrase = make_phrase_box("person", CAPTION, box=PERSON_BOX)

    results = reconcile_context_facts(
        context_pack=pack,
        visual_prior=_prior(),
        confirmed_faces=[eligible, ineligible],
        phrase_boxes=[phrase],
        naming_policy=NamingPolicy(agreement_enabled=True),
    )

    identity_atts = [a for a in results if a.fact_source is FactSource.IDENTITY]
    assert len(identity_atts) == 1
    att = identity_atts[0]
    assert att.decision is AttachmentDecision.DROPPED
    assert att.visible is False
    assert att.review_reason is ReviewReason.AMBIGUOUS_GROUNDING


def test_caption_fallback_for_product_and_attachment():
    """Non-detector facts (product, attachment) stay caption-level / non-visible."""
    pack = ContextPack(
        product=ProductContext(name="Trail Jacket"),
        attachment=AttachmentContext(title="Summer sale hero", caption="Red jacket on trail."),
        post=PostContext(title="Trail jackets for spring", post_type="product", status="publish"),
    )

    results = reconcile_context_facts(context_pack=pack, visual_prior=_prior())

    assert results
    assert all(a.decision is AttachmentDecision.CAPTION for a in results)
    assert all(a.altitude is AttachmentAltitude.CAPTION for a in results)
    assert all(a.visible is False for a in results)
    sources = {a.fact_source for a in results}
    assert FactSource.PRODUCT in sources
    assert FactSource.ATTACHMENT in sources
    assert FactSource.POST in sources
    labels = {a.fact_label for a in results}
    assert "Trail Jacket" in labels
    assert "Summer sale hero" in labels


def test_dropped_brand_without_detector_match():
    """Brand in pack but no logo detection → dropped with review_reason."""
    pack = ContextPack()
    results = reconcile_context_facts(
        context_pack=pack,
        visual_prior=_prior(),
        brands=[BrandFact(name="Acme", template_id="tmpl-acme")],
        brand_detections=[],
    )

    assert len(results) == 1
    att = results[0]
    assert att.decision is AttachmentDecision.DROPPED
    assert att.altitude is AttachmentAltitude.NONE
    assert att.visible is False
    assert att.fact_source is FactSource.BRAND
    assert att.review_reason == ReviewReason.BRAND_NOT_DETECTED


def test_object_attach_brand_when_detected():
    """Brand with matched logo detection → object attach."""
    pack = ContextPack()
    results = reconcile_context_facts(
        context_pack=pack,
        visual_prior=_prior(),
        brands=[BrandFact(name="Acme", template_id="tmpl-acme")],
        brand_detections=[BrandDetection(name="Acme", template_id="tmpl-acme", confidence=0.91, matched=True)],
    )

    att = results[0]
    assert att.decision is AttachmentDecision.OBJECT
    assert att.altitude is AttachmentAltitude.OBJECT
    assert att.visible is True
    assert att.target_evidence == "tmpl-acme"
    assert att.review_reason is None


def test_detector_backed_conflict_drop_face_not_detected():
    """Name in pack whose face is not among confirmed detections → dropped + reason."""
    item = _identity_item("Slate Willow")
    pack = _pack_with_identity(item)
    # Different person detected — Maria's face is not present.
    other = make_face(
        "Hollow Pennant",
        box=FACE_BOX,
        cluster_id="cluster-bea",
        identity_id="identity-bea",
    )
    phrase = make_phrase_box("person", CAPTION, box=PERSON_BOX)

    results = reconcile_context_facts(
        context_pack=pack,
        visual_prior=_prior(),
        confirmed_faces=[other],
        phrase_boxes=[phrase],
        naming_policy=NamingPolicy(agreement_enabled=True),
    )

    att = next(a for a in results if a.fact_source is FactSource.IDENTITY)
    assert att.decision is AttachmentDecision.DROPPED
    assert att.altitude is AttachmentAltitude.NONE
    assert att.visible is False
    assert att.review_reason == ReviewReason.FACE_NOT_DETECTED
    assert att.target_evidence is None


def test_same_label_mismatched_ids_does_not_object_attach():
    """Display-name match is not detector link — only cluster_id/identity_id attach.

    Regression for E20-FUSION-BR-01: pack identity cluster-a/id-a must not
    object-attach a face labeled the same name with cluster-b/id-b even when the
    face center is inside a phrase box.
    """
    item = _identity_item(
        "Slate Willow",
        cluster_id="cluster-a",
        identity_id="id-a",
    )
    pack = _pack_with_identity(item)
    # Same display name, different recognition ids — label fallback would FP.
    wrong_face = make_face(
        "Slate Willow",
        box=FACE_BOX,
        cluster_id="cluster-b",
        identity_id="id-b",
        roster_id="roster-other",
    )
    phrase = make_phrase_box("person", CAPTION, box=PERSON_BOX)

    results = reconcile_context_facts(
        context_pack=pack,
        visual_prior=_prior(),
        confirmed_faces=[wrong_face],
        phrase_boxes=[phrase],
        naming_policy=NamingPolicy(agreement_enabled=True),
    )

    att = next(a for a in results if a.fact_source is FactSource.IDENTITY)
    assert att.decision is AttachmentDecision.DROPPED
    assert att.altitude is AttachmentAltitude.NONE
    assert att.visible is False
    assert att.review_reason == ReviewReason.FACE_NOT_DETECTED
    assert att.target_evidence is None


def test_detector_backed_conflict_ambiguous_grounding():
    """Face present but containment fails (outside phrase box) → ambiguous drop."""
    item = _identity_item()
    pack = _pack_with_identity(item)
    face = make_face(
        item.name,
        box=NormalizedBox(x=0.85, y=0.85, width=0.05, height=0.05),
        cluster_id=item.cluster_id,
        identity_id=item.identity_id,
        roster_id="roster-maria",
    )
    phrase = make_phrase_box("person", CAPTION, box=PERSON_BOX)

    results = reconcile_context_facts(
        context_pack=pack,
        visual_prior=_prior(),
        confirmed_faces=[face],
        phrase_boxes=[phrase],
        naming_policy=NamingPolicy(agreement_enabled=True),
    )

    att = next(a for a in results if a.fact_source is FactSource.IDENTITY)
    assert att.decision is AttachmentDecision.DROPPED
    assert att.review_reason == ReviewReason.AMBIGUOUS_GROUNDING


def test_unsupported_event_place_stays_caption_level_non_visible():
    """Event/place facts are caption-level, not auto-dropped (no semantic judge)."""
    pack = ContextPack(
        taxonomy_terms=[
            TaxonomyTermContext(taxonomy="event", name="Garden picnic", slug="garden-picnic"),
            TaxonomyTermContext(taxonomy="place", name="City park", slug="city-park"),
            TaxonomyTermContext(taxonomy="product_cat", name="Jackets", slug="jackets"),
        ],
    )
    # Visual prior contradicts the picnic story — still not dropped in MVP.
    prior = _prior("A wrecked aircraft on a rocky hillside.", objects=["aircraft", "rock"])

    results = reconcile_context_facts(context_pack=pack, visual_prior=prior)

    event = next(a for a in results if a.fact_source is FactSource.EVENT)
    place = next(a for a in results if a.fact_source is FactSource.PLACE)
    tax = next(a for a in results if a.fact_source is FactSource.TAXONOMY)

    for att in (event, place, tax):
        assert att.decision is AttachmentDecision.CAPTION
        assert att.altitude is AttachmentAltitude.CAPTION
        assert att.visible is False
        assert att.review_reason is None

    assert event.fact_label == "Garden picnic"
    assert place.fact_label == "City park"
    assert tax.fact_label == "Jackets"


def test_policy_veto_first_even_when_face_would_match():
    """person_naming=disabled vetoes before detector attach (policy first)."""
    item = _identity_item()
    pack = _pack_with_identity(
        item,
        person_naming="disabled",
        review_reasons=["person_naming_policy_disabled"],
    )
    face = make_face(
        item.name,
        box=FACE_BOX,
        cluster_id=item.cluster_id,
        identity_id=item.identity_id,
        roster_id="roster-maria",
    )
    phrase = make_phrase_box("person", CAPTION, box=PERSON_BOX)

    results = reconcile_context_facts(
        context_pack=pack,
        visual_prior=_prior(),
        confirmed_faces=[face],
        phrase_boxes=[phrase],
        naming_policy=NamingPolicy(agreement_enabled=True),
    )

    att = next(a for a in results if a.fact_source is FactSource.IDENTITY)
    assert att.decision is AttachmentDecision.DROPPED
    assert att.review_reason == ReviewReason.PERSON_NAMING_POLICY_DISABLED
    assert att.visible is False
    assert att.target_evidence is None


def test_agreement_disabled_policy_veto():
    """NamingPolicy.agreement_enabled=False vetoes all identity facts."""
    item = _identity_item()
    pack = _pack_with_identity(item)
    face = make_face(
        item.name,
        box=FACE_BOX,
        cluster_id=item.cluster_id,
        identity_id=item.identity_id,
        roster_id="roster-maria",
    )
    phrase = make_phrase_box("person", CAPTION, box=PERSON_BOX)

    results = reconcile_context_facts(
        context_pack=pack,
        visual_prior=_prior(),
        confirmed_faces=[face],
        phrase_boxes=[phrase],
        naming_policy=NamingPolicy(agreement_enabled=False),
    )

    att = next(a for a in results if a.fact_source is FactSource.IDENTITY)
    assert att.decision is AttachmentDecision.DROPPED
    assert att.review_reason == ReviewReason.AGREEMENT_DISABLED


def test_unconfirmed_identity_dropped():
    """Identity without cluster_id and identity_id → unconfirmed drop."""
    item = _identity_item(cluster_id=None, identity_id=None)
    pack = _pack_with_identity(item)

    results = reconcile_context_facts(
        context_pack=pack,
        visual_prior=_prior(),
        confirmed_faces=[],
        phrase_boxes=[],
        naming_policy=NamingPolicy(agreement_enabled=True),
    )

    att = results[0]
    assert att.decision is AttachmentDecision.DROPPED
    assert att.review_reason == ReviewReason.UNCONFIRMED_IDENTITY


def test_empty_context_pack_returns_empty():
    assert reconcile_context_facts(context_pack=None, visual_prior=_prior()) == []
    assert reconcile_context_facts(context_pack=ContextPack(), visual_prior=_prior()) == []


def test_suppressed_roster_identity_not_eligible():
    """NamingPolicy suppress set → no_eligible_identities degrade path."""
    item = _identity_item()
    pack = _pack_with_identity(item)
    face = make_face(
        item.name,
        box=FACE_BOX,
        cluster_id=item.cluster_id,
        identity_id=item.identity_id,
        roster_id="roster-maria",
    )
    phrase = make_phrase_box("person", CAPTION, box=PERSON_BOX)
    policy = NamingPolicy(
        agreement_enabled=True,
        suppressed_roster_ids=frozenset({"roster-maria"}),
    )

    results = reconcile_context_facts(
        context_pack=pack,
        visual_prior=_prior(),
        confirmed_faces=[face],
        phrase_boxes=[phrase],
        naming_policy=policy,
    )

    att = next(a for a in results if a.fact_source is FactSource.IDENTITY)
    assert att.decision is AttachmentDecision.DROPPED
    assert att.review_reason == ReviewReason.NO_ELIGIBLE_IDENTITIES


def test_mixed_pack_identity_object_and_event_caption():
    """End-to-end mixed pack: object-attach identity + caption event coexist."""
    item = _identity_item()
    pack = _pack_with_identity(
        item,
        taxonomy_terms=[
            TaxonomyTermContext(taxonomy="event", name="Garden picnic", slug="garden-picnic"),
        ],
        product=ProductContext(name="Trail Jacket"),
    )
    face = make_face(
        item.name,
        box=FACE_BOX,
        cluster_id=item.cluster_id,
        identity_id=item.identity_id,
        roster_id="roster-maria",
    )
    phrase = make_phrase_box("person", CAPTION, box=PERSON_BOX)

    results = reconcile_context_facts(
        context_pack=pack,
        visual_prior=_prior(),
        confirmed_faces=[face],
        phrase_boxes=[phrase],
        naming_policy=NamingPolicy(agreement_enabled=True),
    )

    by_source = {a.fact_source: a for a in results}
    assert by_source[FactSource.IDENTITY].decision is AttachmentDecision.OBJECT
    assert by_source[FactSource.EVENT].decision is AttachmentDecision.CAPTION
    assert by_source[FactSource.EVENT].visible is False
    assert by_source[FactSource.PRODUCT].decision is AttachmentDecision.CAPTION


def test_two_identities_one_phrase_box_both_dropped_ambiguous():
    """Regression S2A-01: two identities' faces inside ONE person phrase box.

    merge.py's 1:1 same-region guard must see the FULL face set — neither
    identity may object-attach when the region is contested.
    """
    maria = _identity_item("Slate Willow", cluster_id="c-a", identity_id="i-a")
    bea = _identity_item("Hollow Pennant", cluster_id="c-b", identity_id="i-b")
    pack = _pack_with_identity(maria, bea)
    face_a = make_face(
        maria.name,
        box=NormalizedBox(x=0.35, y=0.2, width=0.05, height=0.08),
        cluster_id="c-a",
        identity_id="i-a",
        roster_id="roster-maria",
    )
    face_b = make_face(
        bea.name,
        box=NormalizedBox(x=0.5, y=0.2, width=0.05, height=0.08),
        cluster_id="c-b",
        identity_id="i-b",
        roster_id="roster-bea",
    )
    phrase = make_phrase_box("person", CAPTION, box=PERSON_BOX)

    results = reconcile_context_facts(
        context_pack=pack,
        visual_prior=_prior(),
        confirmed_faces=[face_a, face_b],
        phrase_boxes=[phrase],
        naming_policy=NamingPolicy(agreement_enabled=True),
    )

    identity_atts = [a for a in results if a.fact_source is FactSource.IDENTITY]
    assert len(identity_atts) == 2
    for att in identity_atts:
        assert att.decision is AttachmentDecision.DROPPED
        assert att.altitude is AttachmentAltitude.NONE
        assert att.visible is False
        assert att.review_reason == ReviewReason.AMBIGUOUS_GROUNDING


def test_missing_naming_policy_fails_closed():
    """Regression S2A-02: naming_policy=None must never object-attach a name.

    Roster-less, confidence-0.01 face with no policy supplied → dropped with a
    review_reason, not silently named.
    """
    item = _identity_item()
    pack = _pack_with_identity(item)
    face = make_face(
        item.name,
        box=FACE_BOX,
        cluster_id=item.cluster_id,
        identity_id=item.identity_id,
        roster_id=None,
        confidence=0.01,
    )
    phrase = make_phrase_box("person", CAPTION, box=PERSON_BOX)

    results = reconcile_context_facts(
        context_pack=pack,
        visual_prior=_prior(),
        confirmed_faces=[face],
        phrase_boxes=[phrase],
        naming_policy=None,
    )

    att = next(a for a in results if a.fact_source is FactSource.IDENTITY)
    assert att.decision is AttachmentDecision.DROPPED
    assert att.altitude is AttachmentAltitude.NONE
    assert att.visible is False
    assert att.review_reason == ReviewReason.NAMING_POLICY_UNSET


def test_brand_match_normalizes_whitespace_and_case():
    """Regression S2A-03: detector name with padding/case still matches."""
    results = reconcile_context_facts(
        context_pack=ContextPack(),
        visual_prior=_prior(),
        brands=[BrandFact(name="Acme")],
        brand_detections=[BrandDetection(name=" ACME ", confidence=0.9, matched=True)],
    )

    att = results[0]
    assert att.decision is AttachmentDecision.OBJECT
    assert att.review_reason is None


def test_brand_template_id_mismatch_does_not_attach():
    """Regression S2A-03: same-named detection of a DIFFERENT template ≠ match."""
    results = reconcile_context_facts(
        context_pack=ContextPack(),
        visual_prior=_prior(),
        brands=[BrandFact(name="Acme", template_id="tmpl-a")],
        brand_detections=[BrandDetection(name="Acme", template_id="tmpl-b", confidence=0.9, matched=True)],
    )

    att = results[0]
    assert att.decision is AttachmentDecision.DROPPED
    assert att.review_reason == ReviewReason.BRAND_NOT_DETECTED


def test_brand_template_id_match_preferred_over_name():
    """S2A-03: template_id equality matches even when detector name drifts."""
    results = reconcile_context_facts(
        context_pack=ContextPack(),
        visual_prior=_prior(),
        brands=[BrandFact(name="Acme", template_id="tmpl-a")],
        brand_detections=[BrandDetection(name="Acme Corp.", template_id="tmpl-a", confidence=0.9, matched=True)],
    )

    att = results[0]
    assert att.decision is AttachmentDecision.OBJECT
    assert att.target_evidence == "tmpl-a"


def test_review_reason_parity_with_naming_skip_reason():
    """Regression HARM-05: shared drop conditions serialize identically."""
    from scene.application.identity_merge.policy import NamingSkipReason

    assert ReviewReason.NO_ELIGIBLE_IDENTITIES.value == NamingSkipReason.NO_ELIGIBLE_IDENTITIES.value
    assert ReviewReason.AGREEMENT_DISABLED.value == NamingSkipReason.AGREEMENT_DISABLED.value
    assert ReviewReason.AMBIGUOUS_GROUNDING.value == NamingSkipReason.AMBIGUOUS_GROUNDING.value
