"""Stage-2 reconciliation: attach ContextPack facts at object vs caption altitude.

Deterministic only — no LLM calls, no new grounding model. Object attachment is
detector-backed (identities via ``merge_identities`` containment; brands via
matched logo evidence). Events/places stay caption-level/non-visible in MVP;
semantic conflict detection is the LLM-judge stretch.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from scene.application.identity_merge.merge import (
    ConfirmedFace,
    IdentityAssociation,
    PhraseBox,
    merge_identities,
)
from scene.application.identity_merge.policy import NamingPolicy, resolve_naming_allowed
from scene.application.visual_facts_pass import VisualFactsPrior
from scene.interface_adapters.http.schemas.requests import (
    ContextPack,
    IdentityContextItem,
)


class AttachmentDecision(StrEnum):
    """Per-fact reconciliation outcome (sr-007 — no magic strings)."""

    OBJECT = "object"
    CAPTION = "caption"
    DROPPED = "dropped"


class AttachmentAltitude(StrEnum):
    """Where a fact may be woven into the description."""

    OBJECT = "object"
    CAPTION = "caption"
    NONE = "none"


class FactSource(StrEnum):
    """Origin surface on or beside the ContextPack."""

    IDENTITY = "identity"
    BRAND = "brand"
    PRODUCT = "product"
    EVENT = "event"
    PLACE = "place"
    ATTACHMENT = "attachment"
    POST = "post"
    TAXONOMY = "taxonomy"


class ReviewReason(StrEnum):
    """Machine-readable drop/veto reasons for attachment provenance.

    Conditions shared with ``NamingSkipReason`` (policy.py) must serialize to
    the identical wire string so the two provenance surfaces stay correlatable
    (sr-007 — one canonical vocabulary per condition).
    """

    PERSON_NAMING_POLICY_DISABLED = "person_naming_policy_disabled"
    NAMING_POLICY_UNSET = "naming_policy_unset"
    UNCONFIRMED_IDENTITY = "unconfirmed_identity"
    NO_ELIGIBLE_IDENTITIES = "no_eligible_identities"
    FACE_NOT_DETECTED = "face_not_detected"
    AMBIGUOUS_GROUNDING = "ambiguous_grounding"
    BRAND_NOT_DETECTED = "brand_not_detected"
    AGREEMENT_DISABLED = "agreement_disabled"


# Taxonomy keys that carry event/place altitude (not product/topic tags).
_EVENT_TAXONOMIES = frozenset({"event", "events", "acx_event"})
_PLACE_TAXONOMIES = frozenset({"place", "places", "acx_place", "location"})

# person_naming wire values from WP DescribeMediaService.
_PERSON_NAMING_ALLOWED = frozenset({"allowed"})


@dataclass(frozen=True)
class BrandDetection:
    """Detector-backed brand evidence (E20-BRAND-A instance shape)."""

    name: str
    template_id: str | None = None
    confidence: float = 1.0
    matched: bool = True


@dataclass(frozen=True)
class BrandFact:
    """A supplied brand name eligible for object attachment when detected."""

    name: str
    template_id: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class Attachment:
    """Per-fact Stage-2 decision with altitude, evidence, and review reason."""

    fact_id: str
    fact_source: FactSource
    fact_label: str
    decision: AttachmentDecision
    altitude: AttachmentAltitude
    target_evidence: str | None = None
    review_reason: str | None = None
    visible: bool = False


def reconcile_context_facts(
    *,
    context_pack: ContextPack | None,
    visual_prior: VisualFactsPrior,
    confirmed_faces: Sequence[ConfirmedFace] = (),
    phrase_boxes: Sequence[PhraseBox] = (),
    naming_policy: NamingPolicy | None = None,
    brands: Sequence[BrandFact | Any] | None = None,
    brand_detections: Sequence[BrandDetection] = (),
) -> list[Attachment]:
    """Decide attachment + altitude for each ContextPack fact.

    Order per fact (FUSION Stage-2):
    1. policy veto → dropped
    2. detector-backed object attach (identities via merge containment; brands)
    3. detector-backed conflict drop (identity/brand without match + review_reason)
    4. otherwise caption-level / non-visible (events, places, product, post, …)

    Args:
        context_pack: Typed E20-9 pack (may be None → empty list).
        visual_prior: Stage-1 prior; caption drives merge span verification.
        confirmed_faces: Detector-backed faces for identity attach.
        phrase_boxes: Caption phrase boxes for containment matching.
        naming_policy: E19-4a consent gate (agreement / suppress / conf).
            Fail-closed: when None, identity facts never object-attach
            (dropped with ``naming_policy_unset``).
        brands: Brand facts; defaults to ``context_pack.brands`` when that field
            exists (E20-BRAND-A). Items need a ``name`` attribute or ``name`` key.
        brand_detections: Matched logo instances from the brand detector.

    Returns:
        One ``Attachment`` per extracted fact, stable order: identities, brands,
        product, attachment, post, taxonomy (taxonomy terms in pack input order).
    """
    if context_pack is None:
        return []

    faces = list(confirmed_faces)
    boxes = list(phrase_boxes)
    caption = visual_prior.caption
    attachments: list[Attachment] = []

    attachments.extend(
        _reconcile_identities(
            context_pack=context_pack,
            caption=caption,
            faces=faces,
            phrase_boxes=boxes,
            naming_policy=naming_policy,
        )
    )
    brand_facts = _resolve_brands(context_pack, brands)
    attachments.extend(_reconcile_brands(brand_facts=brand_facts, brand_detections=list(brand_detections)))
    attachments.extend(_reconcile_caption_facts(context_pack))
    return attachments


def _resolve_brands(
    context_pack: ContextPack,
    brands: Sequence[BrandFact | Any] | None,
) -> list[BrandFact]:
    if brands is not None:
        return [_coerce_brand(b) for b in brands]
    # Forward-compatible with E20-BRAND-A ``ContextPack.brands`` without requiring
    # the field on this branch (requests.py is out of Slice-2 scope).
    raw = getattr(context_pack, "brands", None)
    if not raw:
        return []
    return [_coerce_brand(b) for b in raw]


def _coerce_brand(item: BrandFact | Any) -> BrandFact:
    if isinstance(item, BrandFact):
        return item
    if isinstance(item, dict):
        return BrandFact(
            name=str(item["name"]),
            template_id=item.get("template_id"),
            source=item.get("source"),
        )
    return BrandFact(
        name=str(item.name),
        template_id=getattr(item, "template_id", None),
        source=getattr(item, "source", None),
    )


def _reconcile_identities(
    *,
    context_pack: ContextPack,
    caption: str,
    faces: list[ConfirmedFace],
    phrase_boxes: list[PhraseBox],
    naming_policy: NamingPolicy | None,
) -> list[Attachment]:
    identity_ctx = context_pack.identity
    if identity_ctx is None or not identity_ctx.identities:
        return []

    # Policy veto first — applies to every identity fact.
    policy_reason = _identity_policy_veto(identity_ctx.policy.person_naming, naming_policy)

    # Reuse merge containment semantics — never reimplement face↔phrase matching.
    # merge_identities filters policy-ineligible faces BEFORE its 1:1 same-region
    # guard (policy.resolve_naming_allowed runs ahead of containment_match), so a
    # policy-filtered association alone cannot detect an ineligible face sharing
    # the same phrase box. Re-run containment over the FULL face set (policy=None)
    # and require the winning face to survive there too; otherwise a policy-
    # eligible face co-located with an ineligible one object-attaches over a
    # shared region the same-region guard exists to reject (EH-01, refines S2A-01).
    associations: tuple[IdentityAssociation, ...] = ()
    geometric_survivors: frozenset[tuple[str, str]] = frozenset()
    if policy_reason is None and naming_policy is not None:
        associations = merge_identities(
            caption=caption,
            phrase_boxes=phrase_boxes,
            confirmed_faces=faces,
            policy=naming_policy,
        ).associations
        geometric_survivors = frozenset(
            _face_key(assoc.face)
            for assoc in merge_identities(
                caption=caption,
                phrase_boxes=phrase_boxes,
                confirmed_faces=faces,
                policy=None,
            ).associations
        )

    out: list[Attachment] = []
    for index, item in enumerate(identity_ctx.identities):
        fact_id = _identity_fact_id(item, index)
        if policy_reason is not None:
            out.append(
                _dropped(
                    fact_id=fact_id,
                    fact_source=FactSource.IDENTITY,
                    fact_label=item.name,
                    review_reason=policy_reason,
                )
            )
            continue
        assert naming_policy is not None  # veto above guarantees this branch
        out.append(
            _reconcile_one_identity(
                item=item,
                fact_id=fact_id,
                faces=faces,
                associations=associations,
                geometric_survivors=geometric_survivors,
                naming_policy=naming_policy,
            )
        )
    return out


def _identity_policy_veto(
    person_naming: str,
    naming_policy: NamingPolicy | None,
) -> str | None:
    if person_naming not in _PERSON_NAMING_ALLOWED:
        return ReviewReason.PERSON_NAMING_POLICY_DISABLED
    if naming_policy is None:
        # Fail-closed consent gate (S2A-02): without an explicit NamingPolicy
        # the E19-4a eligibility rules (roster binding, suppress list,
        # min_detection_confidence) cannot be enforced — never attach names.
        return ReviewReason.NAMING_POLICY_UNSET
    if not naming_policy.agreement_enabled:
        return ReviewReason.AGREEMENT_DISABLED
    return None


def _reconcile_one_identity(
    *,
    item: IdentityContextItem,
    fact_id: str,
    faces: list[ConfirmedFace],
    associations: tuple[IdentityAssociation, ...],
    geometric_survivors: frozenset[tuple[str, str]],
    naming_policy: NamingPolicy,
) -> Attachment:
    # Unconfirmed / non-roster: pack items without cluster+identity ids are not
    # detector-attachable (E20-10 roster-bound guardrails).
    if not item.cluster_id and not item.identity_id:
        return _dropped(
            fact_id=fact_id,
            fact_source=FactSource.IDENTITY,
            fact_label=item.name,
            review_reason=ReviewReason.UNCONFIRMED_IDENTITY,
        )

    matched_faces = _faces_for_identity(item, faces)
    if not matched_faces:
        return _dropped(
            fact_id=fact_id,
            fact_source=FactSource.IDENTITY,
            fact_label=item.name,
            review_reason=ReviewReason.FACE_NOT_DETECTED,
        )

    if not any(resolve_naming_allowed(f, naming_policy) for f in matched_faces):
        return _dropped(
            fact_id=fact_id,
            fact_source=FactSource.IDENTITY,
            fact_label=item.name,
            review_reason=ReviewReason.NO_ELIGIBLE_IDENTITIES,
        )

    assoc = _association_for_identity(item, associations)
    if assoc is not None and _face_key(assoc.face) in geometric_survivors:
        return Attachment(
            fact_id=fact_id,
            fact_source=FactSource.IDENTITY,
            fact_label=item.name,
            decision=AttachmentDecision.OBJECT,
            altitude=AttachmentAltitude.OBJECT,
            target_evidence=assoc.phrase_box.phrase,
            review_reason=None,
            visible=True,
        )

    # No surviving 1:1 association for this identity's face — either no
    # containing box, the face lost the policy-filtered ambiguity guard, or it
    # lost the full-set geometry guard to a policy-ineligible co-located face.
    return _dropped(
        fact_id=fact_id,
        fact_source=FactSource.IDENTITY,
        fact_label=item.name,
        review_reason=ReviewReason.AMBIGUOUS_GROUNDING,
    )


def _face_key(face: ConfirmedFace) -> tuple[str, str]:
    """Stable identity key for a confirmed face (recognition ids, never label)."""
    return (str(face.cluster_id), str(face.identity_id))


def _association_for_identity(
    item: IdentityContextItem,
    associations: Sequence[IdentityAssociation],
) -> IdentityAssociation | None:
    """Look up the global merge result by recognition ids (never by label)."""
    for assoc in associations:
        face = assoc.face
        if item.cluster_id is not None and str(face.cluster_id) == str(item.cluster_id):
            return assoc
        if item.identity_id is not None and str(face.identity_id) == str(item.identity_id):
            return assoc
    return None


def _faces_for_identity(
    item: IdentityContextItem,
    faces: Sequence[ConfirmedFace],
) -> list[ConfirmedFace]:
    """Match faces by recognition ids only — never by display label.

    ``merge.py`` keys provenance by ``cluster_id``; a shared display name is not
    a detector link and must not object-attach a differently-id'd face.
    """
    out: list[ConfirmedFace] = []
    for face in faces:
        if item.cluster_id is not None and str(face.cluster_id) == str(item.cluster_id):
            out.append(face)
            continue
        if item.identity_id is not None and str(face.identity_id) == str(item.identity_id):
            out.append(face)
    return out


def _identity_fact_id(item: IdentityContextItem, index: int) -> str:
    if item.cluster_id:
        return f"identity:cluster:{item.cluster_id}"
    if item.identity_id:
        return f"identity:id:{item.identity_id}"
    return f"identity:{index}:{item.name}"


def _reconcile_brands(
    *,
    brand_facts: list[BrandFact],
    brand_detections: list[BrandDetection],
) -> list[Attachment]:
    if not brand_facts:
        return []
    usable = [d for d in brand_detections if d.matched and d.name.strip()]
    out: list[Attachment] = []
    for index, brand in enumerate(brand_facts):
        fact_id = f"brand:template:{brand.template_id}" if brand.template_id else f"brand:{index}:{brand.name}"
        detection = _match_brand_detection(brand, usable)
        if detection is not None:
            evidence = detection.template_id or brand.template_id or brand.name
            out.append(
                Attachment(
                    fact_id=fact_id,
                    fact_source=FactSource.BRAND,
                    fact_label=brand.name,
                    decision=AttachmentDecision.OBJECT,
                    altitude=AttachmentAltitude.OBJECT,
                    target_evidence=str(evidence),
                    review_reason=None,
                    visible=True,
                )
            )
        else:
            out.append(
                _dropped(
                    fact_id=fact_id,
                    fact_source=FactSource.BRAND,
                    fact_label=brand.name,
                    review_reason=ReviewReason.BRAND_NOT_DETECTED,
                )
            )
    return out


def _match_brand_detection(
    brand: BrandFact,
    detections: Sequence[BrandDetection],
) -> BrandDetection | None:
    """Prefer template_id equality; fall back to normalized (strip+casefold) name.

    A detection carrying a DIFFERENT template_id than the fact never matches by
    name alone — same-named templates are distinct detector evidence (S2A-03).
    """
    if brand.template_id:
        for d in detections:
            if d.template_id and d.template_id == brand.template_id:
                return d
    key = brand.name.strip().casefold()
    if not key:
        return None
    for d in detections:
        if brand.template_id and d.template_id and d.template_id != brand.template_id:
            continue
        if d.name.strip().casefold() == key:
            return d
    return None


def _reconcile_caption_facts(context_pack: ContextPack) -> list[Attachment]:
    """Product / attachment / post / taxonomy — always caption-level, non-visible.

    Event/place taxonomies stay caption-level (not auto-dropped); semantic
    conflict with the visual prior is the LLM-judge stretch, not MVP.
    """
    out: list[Attachment] = []

    product = context_pack.product
    if product is not None and product.name:
        out.append(
            _caption(
                fact_id=f"product:name:{product.name}",
                fact_source=FactSource.PRODUCT,
                fact_label=product.name,
            )
        )

    attachment = context_pack.attachment
    if attachment is not None:
        if attachment.title:
            out.append(
                _caption(
                    fact_id="attachment:title",
                    fact_source=FactSource.ATTACHMENT,
                    fact_label=attachment.title,
                )
            )
        if attachment.caption:
            out.append(
                _caption(
                    fact_id="attachment:caption",
                    fact_source=FactSource.ATTACHMENT,
                    fact_label=attachment.caption,
                )
            )

    post = context_pack.post
    if post is not None and post.title:
        out.append(
            _caption(
                fact_id="post:title",
                fact_source=FactSource.POST,
                fact_label=post.title,
            )
        )

    for term in context_pack.taxonomy_terms:
        tax = term.taxonomy.casefold()
        if tax in _EVENT_TAXONOMIES:
            source = FactSource.EVENT
            fact_id = f"event:{term.slug or term.name}"
        elif tax in _PLACE_TAXONOMIES:
            source = FactSource.PLACE
            fact_id = f"place:{term.slug or term.name}"
        else:
            source = FactSource.TAXONOMY
            fact_id = f"taxonomy:{term.taxonomy}:{term.slug or term.name}"
        out.append(
            _caption(
                fact_id=fact_id,
                fact_source=source,
                fact_label=term.name,
            )
        )
    return out


def _caption(*, fact_id: str, fact_source: FactSource, fact_label: str) -> Attachment:
    return Attachment(
        fact_id=fact_id,
        fact_source=fact_source,
        fact_label=fact_label,
        decision=AttachmentDecision.CAPTION,
        altitude=AttachmentAltitude.CAPTION,
        target_evidence=None,
        review_reason=None,
        visible=False,
    )


def _dropped(
    *,
    fact_id: str,
    fact_source: FactSource,
    fact_label: str,
    review_reason: str,
) -> Attachment:
    return Attachment(
        fact_id=fact_id,
        fact_source=fact_source,
        fact_label=fact_label,
        decision=AttachmentDecision.DROPPED,
        altitude=AttachmentAltitude.NONE,
        target_evidence=None,
        review_reason=review_reason,
        visible=False,
    )
