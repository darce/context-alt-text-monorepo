"""Identity→prose merge layer: deterministic, model-independent named drafts."""

from typing import TYPE_CHECKING

from scene.application.identity_merge.merge import (
    ConfirmedFace,
    IdentityAssociation,
    MergeResult,
    NormalizedBox,
    PhraseBox,
    containment_match,
    merge_identities,
    normalize_bbox,
)
from scene.application.identity_merge.policy import (
    InjectedName,
    NamingMode,
    NamingPolicy,
    NamingProvenance,
    NamingRealizer,
    NamingSkipReason,
    NamingStatus,
    resolve_naming_allowed,
)
from scene.application.identity_merge.realizer import (
    DeterministicNlgRealizer,
    PositionalFallbackRealizer,
    ReflowRealizer,
)

if TYPE_CHECKING:
    from scene.application.identity_merge.join import (
        load_confirmed_faces,
        load_suppressed_roster_ids,
    )

_JOIN_EXPORTS = ("load_confirmed_faces", "load_suppressed_roster_ids")


def __getattr__(name: str):
    # Lazy: join.py pulls sqlalchemy + db.models, which must not load when
    # the pure merge/realizer seam is imported (e.g. by the VLM adapter).
    if name in _JOIN_EXPORTS:
        from scene.application.identity_merge import join

        return getattr(join, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ConfirmedFace",
    "DeterministicNlgRealizer",
    "IdentityAssociation",
    "InjectedName",
    "MergeResult",
    "NamingMode",
    "NamingPolicy",
    "NamingProvenance",
    "NamingRealizer",
    "NamingSkipReason",
    "NamingStatus",
    "NormalizedBox",
    "PhraseBox",
    "PositionalFallbackRealizer",
    "ReflowRealizer",
    "containment_match",
    "load_confirmed_faces",
    "load_suppressed_roster_ids",
    "merge_identities",
    "normalize_bbox",
    "resolve_naming_allowed",
]
