"""YuNet + SFace face pipeline (FIR-3).

S1 exposes model provenance only. Detectors/embedders land in S2/S3.
Import surface is stdlib-only at this package root (no cv2/onnxruntime).
"""

from recognition.infrastructure.face_pipeline.provenance import (
    MODEL_MANIFEST,
    ModelIntegrityError,
    ModelProvenance,
    load_verified_model,
)

__all__ = [
    "MODEL_MANIFEST",
    "ModelIntegrityError",
    "ModelProvenance",
    "load_verified_model",
]
