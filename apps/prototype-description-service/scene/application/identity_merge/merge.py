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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scene.application.identity_merge.policy import NamingPolicy
    from scene.application.identity_merge.realizer import ReflowRealizer

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


def span_replaceable(caption: str, phrase_box: PhraseBox) -> bool:
    """A span may be replaced only when it verifiably matches the caption."""
    start, end = phrase_box.span_start, phrase_box.span_end
    return (
        0 <= start < end <= len(caption) and bool(phrase_box.phrase.strip()) and caption[start:end] == phrase_box.phrase
    )


def _box_key(box: NormalizedBox) -> tuple[float, float, float, float]:
    return (box.x, box.y, box.width, box.height)


def containment_match(
    confirmed_faces: list[ConfirmedFace],
    phrase_boxes: list[PhraseBox],
    *,
    max_face_to_phrase_area_ratio: float = DEFAULT_MAX_FACE_TO_PHRASE_AREA_RATIO,
) -> list[IdentityAssociation]:
    """Match each face to the smallest phrase box containing its center, 1:1 only.

    Any ambiguity yields no match for the faces involved — never guess:
    no containing box; an equal-area tie for smallest; the area-ratio guard
    failing against the smallest box (a looser enclosing box must NOT be
    promoted); or two faces resolving to the same region (by box value, so
    duplicate phrase-box objects cannot defeat the 1:1 rule).
    """
    usable = [pb for pb in phrase_boxes if pb.box.area > 0]
    candidates: list[IdentityAssociation] = []
    for face in confirmed_faces:
        if face.box.area <= 0:
            continue  # degenerate detection box carries no containment signal
        cx, cy = face.box.center
        containing = [pb for pb in usable if pb.box.contains_point(cx, cy)]
        if not containing:
            continue
        smallest = min(containing, key=lambda pb: pb.box.area)
        if sum(1 for pb in containing if pb.box.area == smallest.box.area) > 1:
            continue  # equal-area tie: no deterministic "smallest" exists
        if face.box.area > max_face_to_phrase_area_ratio * smallest.box.area:
            continue  # guard failed against the best box: do not promote to a looser one
        candidates.append(IdentityAssociation(face=face, phrase_box=smallest))

    matched_counts: dict[tuple[float, float, float, float], int] = {}
    for assoc in candidates:
        key = _box_key(assoc.phrase_box.box)
        matched_counts[key] = matched_counts.get(key, 0) + 1
    return [assoc for assoc in candidates if matched_counts[_box_key(assoc.phrase_box.box)] == 1]


def _person_key(face: ConfirmedFace) -> tuple[str, str]:
    """Identify a person without collapsing distinct people sharing a label."""
    if face.cluster_id is not None:
        return "cluster", str(face.cluster_id)
    return "identity", str(face.identity_id)


def _distinct_faces_by_person(faces: list[ConfirmedFace]) -> list[ConfirmedFace]:
    """Keep one face per cluster while preserving the first visual occurrence."""
    seen: set[tuple[str, str]] = set()
    distinct: list[ConfirmedFace] = []
    for face in faces:
        key = _person_key(face)
        if key in seen:
            continue
        seen.add(key)
        distinct.append(face)
    return distinct


def merge_identities(
    *,
    caption: str,
    phrase_boxes: list[PhraseBox],
    confirmed_faces: list[ConfirmedFace],
    realizer: ReflowRealizer | None = None,
    policy: NamingPolicy | None = None,
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
        NamingMode,
        NamingProvenance,
        NamingRealizer,
        NamingSkipReason,
        NamingStatus,
        resolve_naming_allowed,
    )
    from scene.application.identity_merge.realizer import (
        DeterministicNlgRealizer,
        PositionalFallbackRealizer,
    )

    def _generic(reason: Any) -> MergeResult:
        if policy is None:
            provenance = None
        else:
            status = NamingStatus.DISABLED if reason is NamingSkipReason.AGREEMENT_DISABLED else NamingStatus.NO_FACES
            provenance = NamingProvenance(
                naming_allowed=False,
                reason=reason,
                status=status,
                realizer=None,
                names_applied=(),
            )
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

    # Only verifiable spans can produce insertions; unverifiable boxes must
    # not participate in containment (they could steal a face's match).
    groundable = [pb for pb in phrase_boxes if span_replaceable(caption, pb)]
    associations = containment_match(faces, groundable)
    mode: Any = None
    named_faces: list[ConfirmedFace]
    if associations:
        # Provenance counts only faces whose span the realizer will actually
        # replace; duplicate mentions of one person collapse to one entry.
        # Keyed by cluster_id (the person), not label, so provenance stays
        # correct even if label uniqueness were ever relaxed.
        dedup: dict[tuple[str, str], ConfirmedFace] = {}
        for a in sorted(associations, key=lambda association: association.phrase_box.span_start):
            dedup.setdefault(_person_key(a.face), a.face)
        named_faces = list(dedup.values())
        mode = NamingMode.GROUNDED
    elif not phrase_boxes and faces:
        named_faces = _distinct_faces_by_person(sorted(faces, key=lambda f: f.box.center[0]))
        mode = NamingMode.POSITIONAL
    else:
        named_faces = []

    if realizer is None:
        if associations:
            realizer = DeterministicNlgRealizer()
        elif not phrase_boxes and faces:
            realizer = PositionalFallbackRealizer()
    realizer_faces = named_faces if not associations and not phrase_boxes else faces
    named_draft = (
        realizer.realize(caption=caption, associations=associations, confirmed_faces=realizer_faces)
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
                        detection_confidence=f.detection_confidence,
                    )
                    for f in named_faces
                ),
                naming_allowed=True,
                reason=None,
                mode=mode,
                status=NamingStatus.APPLIED,
                realizer=(
                    NamingRealizer.GROUNDED
                    if mode is NamingMode.GROUNDED
                    else NamingRealizer.POSITIONAL_FALLBACK
                ),
                names_applied=tuple(f.label for f in named_faces),
            )
        else:
            provenance = NamingProvenance(
                naming_allowed=False,
                reason=NamingSkipReason.AMBIGUOUS_GROUNDING,
                status=NamingStatus.NO_FACES,
                realizer=None,
                names_applied=(),
            )
    return MergeResult(
        generic_draft=caption,
        named_draft=named_draft,
        associations=tuple(associations),
        provenance=provenance,
    )
