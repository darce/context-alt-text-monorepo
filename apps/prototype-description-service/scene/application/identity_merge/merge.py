"""Merge core: normalize + containment-match confirmed faces to caption phrase boxes.

Pure application layer — no HTTP/DB/VLM imports. All boxes live in one frame:
[0,1] fractions of the original image W×H, origin top-left, matching the
VLM-2C ``phrase_boxes.json`` seed format (E19-4a consumes that format as-is).

Matching is face-center-in-smallest-person-phrase-box, strictly 1:1, with an
area-ratio guard (a face box nearly as large as the phrase box carries no
containment signal). IoU is deliberately not used: a face is a small region
inside a much larger person phrase box, so overlap ratios are meaningless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# A face box must be at most this fraction of the containing phrase-box area
# for containment to mean "this face belongs to that person phrase".
DEFAULT_MAX_FACE_TO_PHRASE_AREA_RATIO = 0.5


@dataclass(frozen=True)
class NormalizedBox:
    """Axis-aligned box in [0,1] fractions of the original image, top-left origin."""

    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)

    @property
    def area(self) -> float:
        return self.width * self.height

    def contains_point(self, px: float, py: float) -> bool:
        return self.x <= px <= self.x + self.width and self.y <= py <= self.y + self.height


@dataclass(frozen=True)
class PhraseBox:
    """One grounded noun phrase of the caption: text span + its box."""

    phrase: str
    span_start: int
    span_end: int
    box: NormalizedBox


@dataclass(frozen=True)
class ConfirmedFace:
    """A confirmed, human-labeled face region joined from recognition storage."""

    identity_id: Any
    cluster_id: Any
    roster_id: Any | None
    label: str
    detection_confidence: float
    box: NormalizedBox


@dataclass(frozen=True)
class IdentityAssociation:
    """A 1:1 face↔phrase-box association produced by containment matching."""

    face: ConfirmedFace
    phrase_box: PhraseBox


@dataclass(frozen=True)
class MergeResult:
    """Both drafts plus the associations and provenance that justify any naming."""

    generic_draft: str
    named_draft: str
    associations: tuple[IdentityAssociation, ...] = field(default_factory=tuple)
    # NamingProvenance when a NamingPolicy was applied; None on policy-less
    # (pre-Slice-3) calls. Typed Any to keep the package acyclic.
    provenance: Any = None


def normalize_bbox(
    *, x: float, y: float, width: float, height: float, image_width: float, image_height: float
) -> NormalizedBox:
    """Convert a pixel bbox to [0,1] fractions of the original W×H (top-left origin)."""
    if image_width <= 0 or image_height <= 0:
        raise ValueError(f"image dimensions must be positive, got {image_width}x{image_height}")
    return NormalizedBox(
        x=x / image_width,
        y=y / image_height,
        width=width / image_width,
        height=height / image_height,
    )


def containment_match(
    confirmed_faces: list[ConfirmedFace],
    phrase_boxes: list[PhraseBox],
    *,
    max_face_to_phrase_area_ratio: float = DEFAULT_MAX_FACE_TO_PHRASE_AREA_RATIO,
) -> list[IdentityAssociation]:
    """Match each face to the smallest phrase box containing its center, 1:1 only.

    Any ambiguity — no containing box, or two faces resolving to the same
    phrase box — yields no match for the faces involved. Never guess.
    """
    candidates: list[IdentityAssociation] = []
    for face in confirmed_faces:
        cx, cy = face.box.center
        containing = [
            pb
            for pb in phrase_boxes
            if pb.box.contains_point(cx, cy)
            and pb.box.area > 0
            and face.box.area <= max_face_to_phrase_area_ratio * pb.box.area
        ]
        if not containing:
            continue
        smallest = min(containing, key=lambda pb: pb.box.area)
        candidates.append(IdentityAssociation(face=face, phrase_box=smallest))

    matched_counts: dict[int, int] = {}
    for assoc in candidates:
        key = id(assoc.phrase_box)
        matched_counts[key] = matched_counts.get(key, 0) + 1
    return [assoc for assoc in candidates if matched_counts[id(assoc.phrase_box)] == 1]


def merge_identities(
    *,
    caption: str,
    phrase_boxes: list[PhraseBox],
    confirmed_faces: list[ConfirmedFace],
    realizer: Any | None = None,
    policy: Any | None = None,
) -> MergeResult:
    """Produce both drafts plus 1:1 name↔region associations and provenance.

    Realizer selection lives here, behind the ``ReflowRealizer`` seam — no
    inline mode ladder inside realizers. An injected ``realizer`` always wins;
    otherwise: grounded associations → ``DeterministicNlgRealizer``; no phrase
    boxes at all → ``PositionalFallbackRealizer`` (Approach B); phrase boxes
    present but matching ambiguous/empty → generic (never guess).

    When a ``NamingPolicy`` is passed, the consent gate filters faces before
    matching and the result carries ``NamingProvenance`` (generic-only results
    name the skip reason).
    """
    # Function-level imports: realizer.py/policy.py import the dataclasses
    # from this module, so the seam is bound late to keep the package acyclic.
    from scene.application.identity_merge.policy import (
        InjectedName,
        NamingProvenance,
        NamingSkipReason,
        resolve_naming_allowed,
    )
    from scene.application.identity_merge.realizer import (
        DeterministicNlgRealizer,
        PositionalFallbackRealizer,
    )

    def _generic(reason: Any) -> MergeResult:
        provenance = NamingProvenance(naming_allowed=False, reason=reason) if policy is not None else None
        return MergeResult(generic_draft=caption, named_draft=caption, provenance=provenance)

    faces = list(confirmed_faces)
    if policy is not None:
        if not policy.agreement_enabled:
            return _generic(NamingSkipReason.AGREEMENT_DISABLED)
        if not faces:
            return _generic(NamingSkipReason.NO_CONFIRMED_IDENTITIES)
        faces = [f for f in faces if resolve_naming_allowed(f, policy)]
        if not faces:
            return _generic(NamingSkipReason.NO_ELIGIBLE_IDENTITIES)

    associations = containment_match(faces, phrase_boxes)
    named_faces: list[ConfirmedFace]
    if associations:
        named_faces = [a.face for a in associations]
    elif not phrase_boxes and faces:
        named_faces = sorted(faces, key=lambda f: f.box.center[0])  # fallback order
    else:
        named_faces = []

    if realizer is None:
        if associations:
            realizer = DeterministicNlgRealizer()
        elif not phrase_boxes and faces:
            realizer = PositionalFallbackRealizer()
    named_draft = (
        realizer.realize(caption=caption, associations=associations, confirmed_faces=faces)
        if realizer is not None
        else caption
    )

    provenance = None
    if policy is not None:
        if named_faces and named_draft != caption:
            provenance = NamingProvenance(
                injected_names=tuple(
                    InjectedName(
                        name=f.label,
                        cluster_id=f.cluster_id,
                        roster_id=f.roster_id,
                        match_confidence=f.detection_confidence,
                    )
                    for f in named_faces
                ),
                naming_allowed=True,
                reason=None,
            )
        else:
            provenance = NamingProvenance(
                naming_allowed=False,
                reason=NamingSkipReason.AMBIGUOUS_GROUNDING,
            )
    return MergeResult(
        generic_draft=caption,
        named_draft=named_draft,
        associations=tuple(associations),
        provenance=provenance,
    )
