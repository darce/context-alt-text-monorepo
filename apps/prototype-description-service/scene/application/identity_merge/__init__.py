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

__all__ = [
    "ConfirmedFace",
    "IdentityAssociation",
    "MergeResult",
    "NormalizedBox",
    "PhraseBox",
    "containment_match",
    "load_confirmed_faces",
    "merge_identities",
    "normalize_bbox",
]
