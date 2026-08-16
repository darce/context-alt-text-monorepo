"""YuNet + SFace face pipeline (FIR-3).

S1 exposes model provenance only. Detectors/embedders land in S2/S3.
Import surface is stdlib-only at this package root (no cv2/onnxruntime at
import time). ``numeric_runtime_fingerprint`` lazy-imports those packages
when called.
"""

from recognition.infrastructure.face_pipeline.provenance import (
    MODEL_MANIFEST,
    ModelIntegrityError,
    ModelMissingError,
    ModelProvenance,
    NumericRuntimeFingerprint,
    load_verified_model,
    numeric_runtime_fingerprint,
)

__all__ = [
    "MODEL_MANIFEST",
    "ModelIntegrityError",
    "ModelMissingError",
    "ModelProvenance",
    "NumericRuntimeFingerprint",
    "load_verified_model",
    "numeric_runtime_fingerprint",
]
