"""Shared fixture factories for the identity_merge test modules.

One canonical ConfirmedFace/PhraseBox/IdentityAssociation builder so gate
parameters are threaded through a single place; test modules keep thin local
aliases only where their call-site signature reads better.
"""

from __future__ import annotations

from scene.application.identity_merge import ConfirmedFace, NormalizedBox, PhraseBox
from scene.application.identity_merge.merge import IdentityAssociation

DEFAULT_FACE_BOX = NormalizedBox(x=0.4, y=0.2, width=0.05, height=0.08)
DEFAULT_PERSON_BOX = NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.7)


def make_face(
    label: str,
    *,
    box: NormalizedBox | None = None,
    x: float | None = None,
    y: float = 0.2,
    w: float = 0.05,
    h: float = 0.08,
    roster_id: object = "roster-1",
    confidence: float = 0.95,
    cluster_id: object | None = None,
    identity_id: object | None = None,
) -> ConfirmedFace:
    if box is None:
        box = NormalizedBox(x=0.4 if x is None else x, y=y, width=w, height=h)
    return ConfirmedFace(
        identity_id=identity_id if identity_id is not None else f"identity-{label}-{box.x}",
        cluster_id=cluster_id if cluster_id is not None else f"cluster-id-{label}",
        roster_id=roster_id,
        label=label,
        detection_confidence=confidence,
        box=box,
    )


def make_phrase_box(
    phrase: str,
    caption: str,
    *,
    box: NormalizedBox | None = None,
    occurrence: int = 0,
) -> PhraseBox:
    start = -1
    for _ in range(occurrence + 1):
        start = caption.index(phrase, start + 1)
    return PhraseBox(
        phrase=phrase,
        span_start=start,
        span_end=start + len(phrase),
        box=box if box is not None else DEFAULT_PERSON_BOX,
    )


def make_association(
    caption: str,
    phrase: str,
    label: str,
    *,
    box: NormalizedBox | None = None,
    occurrence: int = 0,
    face_x: float = 0.4,
) -> IdentityAssociation:
    return IdentityAssociation(
        face=make_face(label, x=face_x),
        phrase_box=make_phrase_box(phrase, caption, box=box, occurrence=occurrence),
    )
