"""Identity→prose merge layer: deterministic, model-independent named drafts."""

from scene.application.identity_merge.join import load_confirmed_faces
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
from scene.application.identity_merge.realizer import (
    DeterministicNlgRealizer,
    PositionalFallbackRealizer,
    ReflowRealizer,
)

__all__ = [
    "ConfirmedFace",
    "DeterministicNlgRealizer",
    "IdentityAssociation",
    "MergeResult",
    "NormalizedBox",
    "PhraseBox",
    "PositionalFallbackRealizer",
    "ReflowRealizer",
    "containment_match",
    "load_confirmed_faces",
    "merge_identities",
    "normalize_bbox",
]
