"""Identity→prose merge layer: deterministic, model-independent named drafts."""

from scene.application.identity_merge.join import (
    load_confirmed_faces,
    load_suppressed_roster_ids,
)
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
    NamingPolicy,
    NamingProvenance,
    NamingSkipReason,
    resolve_naming_allowed,
)
from scene.application.identity_merge.realizer import (
    DeterministicNlgRealizer,
    PositionalFallbackRealizer,
    ReflowRealizer,
)

__all__ = [
    "ConfirmedFace",
    "DeterministicNlgRealizer",
    "IdentityAssociation",
    "InjectedName",
    "MergeResult",
    "NamingPolicy",
    "NamingProvenance",
    "NamingSkipReason",
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
