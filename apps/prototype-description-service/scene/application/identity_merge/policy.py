"""Consent gate + provenance: name only when every condition holds.

The gate composes with the join filters (Slice 1) and containment matching:
a face reaches a named draft only if it is user-confirmed with a human label
(join), the tenant naming agreement is active, the person is not suppressed,
and detection confidence clears the threshold (this module). Any miss →
generic phrasing, never a guessed name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from scene.application.identity_merge.merge import ConfirmedFace

# Below this face-detection confidence, naming evidence is too weak to use.
DEFAULT_MIN_DETECTION_CONFIDENCE = 0.8


class NamingSkipReason(StrEnum):
    """Why a result is generic-only. Wire values are the enum values."""

    AGREEMENT_DISABLED = "agreement_disabled"
    DB_UNAVAILABLE = "db_unavailable"
    IMAGE_UNREADABLE = "image_unreadable"
    NO_CONFIRMED_IDENTITIES = "no_confirmed_identities"
    NO_ELIGIBLE_IDENTITIES = "no_eligible_identities"
    AMBIGUOUS_GROUNDING = "ambiguous_grounding"
    MERGE_ERROR = "merge_error"


class NamingMode(StrEnum):
    """How the named draft was realized. Wire values are the enum values."""

    GROUNDED = "grounded"
    POSITIONAL = "positional"


class NamingStatus(StrEnum):
    """Stable outcome vocabulary for the persisted naming provenance."""

    APPLIED = "applied"
    DISABLED = "disabled"
    SKIPPED_BUDGET = "skipped_budget"
    NO_FACES = "no_faces"


class NamingRealizer(StrEnum):
    """Realizer vocabulary; no realizer is represented by ``None``."""

    GROUNDED = "grounded"
    POSITIONAL_FALLBACK = "positional_fallback"


@dataclass(frozen=True)
class NamingPolicy:
    """Tenant naming-agreement flag + per-roster suppress set + thresholds."""

    agreement_enabled: bool
    suppressed_roster_ids: frozenset[Any] = frozenset()
    min_detection_confidence: float = DEFAULT_MIN_DETECTION_CONFIDENCE


@dataclass(frozen=True)
class InjectedName:
    """One name actually inserted into the named draft, with its source.

    ``detection_confidence`` is the face detector's score for the matched
    region (``MediaIdentity.confidence``) — honest naming: it is not a
    face↔phrase match strength.
    """

    name: str
    cluster_id: Any
    roster_id: Any | None
    detection_confidence: float


@dataclass(frozen=True)
class NamingProvenance:
    """Per-result record of what was named, from where, or why not."""

    injected_names: tuple[InjectedName, ...] = field(default_factory=tuple)
    naming_allowed: bool = False
    reason: NamingSkipReason | None = None
    mode: NamingMode | None = None
    status: NamingStatus | None = None
    realizer: NamingRealizer | None = None
    names_applied: tuple[str, ...] = field(default_factory=tuple)


def resolve_naming_allowed(face: ConfirmedFace, policy: NamingPolicy) -> bool:
    """Per-face consent gate. The join already guarantees confirmed + labeled.

    A face without a ``roster_id`` is never nameable: the per-roster suppress
    list is the only per-person opt-out, so a roster-less identity would be
    unsuppressable — consent must remain revocable for every named person.
    """
    if not policy.agreement_enabled:
        return False
    if face.roster_id is None:
        return False
    if face.roster_id in policy.suppressed_roster_ids:
        return False
    return face.detection_confidence >= policy.min_detection_confidence
