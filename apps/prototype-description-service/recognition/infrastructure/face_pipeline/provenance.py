"""Model provenance manifest + fail-closed loader for YuNet + SFace ONNX.

FIR-3 S1: pin model bytes by sha256 with source URL/ref and license hashes.
Adapters (S2/S3) load models only through ``load_verified_model``.

Heuristics: rg-008 (validate at load), AGT-02 (no fabricated hashes).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

# Explicit unresolved-hash sentinel. Never invent sha256 values.
PENDING_OPERATOR_FETCH = "PENDING_OPERATOR_FETCH"

# opencv_zoo commit that ships YuNet 2026may + SFace 2021dec (not a branch tip).
OPENCV_ZOO_COMMIT = "47534e27c9851bb1128ccc0102f1145e27f23f98"
_OPENCV_ZOO_MEDIA = f"https://media.githubusercontent.com/media/opencv/opencv_zoo/{OPENCV_ZOO_COMMIT}"
_OPENCV_ZOO_RAW = f"https://raw.githubusercontent.com/opencv/opencv_zoo/{OPENCV_ZOO_COMMIT}"

# Default on-disk directory next to this module.
DEFAULT_MODELS_DIR = Path(__file__).resolve().parent / "models"


class ModelIntegrityError(Exception):
    """Raised when a model cannot be loaded with verified integrity (fail-closed)."""


@dataclass(frozen=True, slots=True)
class ModelProvenance:
    """Pinned provenance for one ONNX model artifact."""

    file_name: str
    sha256: str
    source_url: str
    source_ref: str
    license_id: str
    license_file: str
    license_sha256: str
    size_bytes: int


# Hashes computed from bytes downloaded in-sandbox at FIR-3 S1 from the
# pinned opencv_zoo commit above (media.githubusercontent.com LFS content).
# Never hand-edit without re-downloading and re-hashing.
MODEL_MANIFEST: dict[str, ModelProvenance] = {
    "yunet": ModelProvenance(
        file_name="face_detection_yunet_2026may.onnx",
        sha256="ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0",
        source_url=(
            f"{_OPENCV_ZOO_MEDIA}/models/face_detection_yunet/"
            "face_detection_yunet_2026may.onnx"
        ),
        source_ref=OPENCV_ZOO_COMMIT,
        license_id="MIT",
        license_file="LICENSE.yunet",
        license_sha256="c83b8120c50ccbd4c4f96edf53141bdd566ebb8f8e9227e415326aa1b1aba958",
        size_bytes=229_738,
    ),
    "sface": ModelProvenance(
        file_name="face_recognition_sface_2021dec.onnx",
        sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        source_url=(
            f"{_OPENCV_ZOO_MEDIA}/models/face_recognition_sface/"
            "face_recognition_sface_2021dec.onnx"
        ),
        source_ref=OPENCV_ZOO_COMMIT,
        license_id="Apache-2.0",
        license_file="LICENSE.sface",
        license_sha256="cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
        size_bytes=38_696_353,
    ),
}

# License source URLs (not part of ModelProvenance; used by the fetch script).
LICENSE_SOURCE_URLS: dict[str, str] = {
    "yunet": f"{_OPENCV_ZOO_RAW}/models/face_detection_yunet/LICENSE",
    "sface": f"{_OPENCV_ZOO_RAW}/models/face_recognition_sface/LICENSE",
}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def load_verified_model(name: str, *, models_dir: Path | None = None) -> Path:
    """Return the path to a model only after sha256 verification succeeds.

    Fail-closed: missing file, pending sentinel, size mismatch, or hash
    mismatch all raise ``ModelIntegrityError``. Never returns an unverified path.
    """
    entry = MODEL_MANIFEST.get(name)
    if entry is None:
        raise ModelIntegrityError(f"unknown model name: {name!r}")

    if entry.sha256 == PENDING_OPERATOR_FETCH:
        raise ModelIntegrityError(
            f"model {name!r} hash is {PENDING_OPERATOR_FETCH}; "
            f"operator must fetch from {entry.source_url} @ {entry.source_ref} "
            "and pin the real sha256 before load"
        )

    root = Path(models_dir) if models_dir is not None else DEFAULT_MODELS_DIR
    path = root / entry.file_name
    if not path.is_file():
        raise ModelIntegrityError(
            f"model file missing for {name!r}: {path} "
            f"(expected {entry.file_name} from {entry.source_url})"
        )

    actual_size = path.stat().st_size
    if entry.size_bytes > 0 and actual_size != entry.size_bytes:
        raise ModelIntegrityError(
            f"size mismatch for {name!r}: expected {entry.size_bytes} bytes, "
            f"got {actual_size} at {path}"
        )

    actual = _file_sha256(path)
    if actual != entry.sha256:
        raise ModelIntegrityError(
            f"sha256 mismatch for {name!r}: expected {entry.sha256}, "
            f"got {actual} at {path}"
        )

    return path


__all__ = [
    "DEFAULT_MODELS_DIR",
    "LICENSE_SOURCE_URLS",
    "MODEL_MANIFEST",
    "ModelIntegrityError",
    "ModelProvenance",
    "OPENCV_ZOO_COMMIT",
    "PENDING_OPERATOR_FETCH",
    "load_verified_model",
]
