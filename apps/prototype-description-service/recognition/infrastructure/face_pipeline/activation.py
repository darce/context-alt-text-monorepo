"""Fail-closed activation policy for face-pipeline model spaces.

Lives in infrastructure so serve/scan construction can call the same guard as
readiness without an infrastructure → application import cycle.
"""

from __future__ import annotations

from recognition.infrastructure.face_pipeline.model_space import ModelSpace, UnhandledModelSpaceError
from recognition.infrastructure.face_pipeline.provenance import MODEL_MANIFEST, PENDING_OPERATOR_FETCH


def assert_space_activatable(space: ModelSpace) -> None:
    """Refuse activation while a space's provenance or preprocessing is unverified."""
    if space is ModelSpace.INSIGHTFACE:
        return
    if space is ModelSpace.FACE_PIPELINE:
        model_names = ("yunet", "sface")
    elif space is ModelSpace.AURAFACE:
        model_names = ("auraface",)
    else:
        raise UnhandledModelSpaceError(f"Unhandled model space: {space!r}")

    for model_name in model_names:
        entry = MODEL_MANIFEST.get(model_name)
        if entry is None:
            raise ValueError(f"model space {space.value!r} is missing manifest entry {model_name!r}")
        if entry.sha256 == PENDING_OPERATOR_FETCH or entry.license_sha256 == PENDING_OPERATOR_FETCH:
            raise ValueError(f"model {model_name!r} remains {PENDING_OPERATOR_FETCH}")
        if space is ModelSpace.AURAFACE:
            preprocessing = entry.preprocessing
            template_id = preprocessing.alignment_template_id if preprocessing is not None else "missing"
            if preprocessing is None or "unverified" in template_id.lower():
                raise ValueError(f"model {model_name!r} alignment template {template_id!r} is -unverified")


__all__ = ["assert_space_activatable"]
