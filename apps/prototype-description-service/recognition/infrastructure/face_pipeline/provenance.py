"""Model provenance manifest + fail-closed loader for YuNet + SFace ONNX.

FIR-3 S1: pin model bytes by sha256 with source URL/ref and license hashes.
Adapters (S2/S3) load models only through ``load_verified_model``.

Heuristics: rg-008 (config validate-at-load), AGT-02 (no unresolved anchors),
rg-015 (manifest is single source for EmbeddingModelManifest field values).
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
    """Raised when on-disk bytes fail size/hash integrity (tamper / corrupt).

    Sticky-cacheable in the process runtime singleton: a hash/size mismatch is
    not expected to self-heal without operator intervention or process restart.
    """


class ModelMissingError(Exception):
    """Raised when a known model is not provisioned (missing file or pending pin).

    Not a subclass of ``ModelIntegrityError``. Non-sticky: correcting
    ``models_dir`` (fetch + pin) must recover without process restart.
    """


@dataclass(frozen=True, slots=True)
class ModelProvenance:
    """Pinned provenance for one ONNX model artifact.

    Embedding-contract fields (``embedding_dim``, ``normalization``, ``metric``,
    ``framework``) are the single source for ``EmbeddingModelManifest`` values
    consumed by S2/S3 adapters (rg-015). Detector-only entries use ``None`` for
    embedding fields.
    """

    file_name: str
    sha256: str
    source_url: str
    source_ref: str
    license_id: str
    license_file: str
    license_sha256: str
    size_bytes: int
    framework: str
    embedding_dim: int | None = None
    normalization: str | None = None
    metric: str | None = None


# Hashes computed from bytes downloaded in-sandbox at FIR-3 S1 from the
# pinned opencv_zoo commit above (media.githubusercontent.com LFS content).
# Never hand-edit without re-downloading and re-hashing.
MODEL_MANIFEST: dict[str, ModelProvenance] = {
    "yunet": ModelProvenance(
        file_name="face_detection_yunet_2026may.onnx",
        sha256="ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0",
        source_url=(f"{_OPENCV_ZOO_MEDIA}/models/face_detection_yunet/face_detection_yunet_2026may.onnx"),
        source_ref=OPENCV_ZOO_COMMIT,
        license_id="MIT",
        license_file="LICENSE.yunet",
        license_sha256="c83b8120c50ccbd4c4f96edf53141bdd566ebb8f8e9227e415326aa1b1aba958",
        size_bytes=229_738,
        framework="opencv",
        embedding_dim=None,
        normalization=None,
        metric=None,
    ),
    "sface": ModelProvenance(
        file_name="face_recognition_sface_2021dec.onnx",
        sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        source_url=(f"{_OPENCV_ZOO_MEDIA}/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"),
        source_ref=OPENCV_ZOO_COMMIT,
        license_id="Apache-2.0",
        license_file="LICENSE.sface",
        license_sha256="cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
        size_bytes=38_696_353,
        framework="opencv",
        embedding_dim=128,
        normalization="l2",
        metric="cosine",
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
    """Return the path to a model only after model + license integrity checks pass.

    Fail-closed split:
    - ``ModelMissingError``: not provisioned (missing model/license file, or
      ``PENDING_OPERATOR_FETCH`` sentinel still on the pin).
    - ``ModelIntegrityError``: size or sha256 mismatch (tamper / corrupt bytes).
    Unknown logical names also raise ``ModelIntegrityError`` (config error).

    Integrity is checked at call time against the on-disk files. This is a
    verify-then-open TOCTOU window: a concurrent writer could replace the model
    file after the hash check and before the caller opens the returned path.
    Acceptable under the trusted-operator models-dir threat model (operators
    control ``models/``; untrusted multi-writer environments should re-hash at
    open or pass an already-opened fd).
    """
    entry = MODEL_MANIFEST.get(name)
    if entry is None:
        raise ModelIntegrityError(f"unknown model name: {name!r}")

    if entry.sha256 == PENDING_OPERATOR_FETCH:
        raise ModelMissingError(
            f"model {name!r} hash is {PENDING_OPERATOR_FETCH}; "
            f"operator must fetch from {entry.source_url} @ {entry.source_ref} "
            "and pin the real sha256 before load"
        )

    root = Path(models_dir) if models_dir is not None else DEFAULT_MODELS_DIR
    path = root / entry.file_name
    if not path.is_file():
        raise ModelMissingError(
            f"model file missing for {name!r}: {path} (expected {entry.file_name} from {entry.source_url})"
        )

    actual_size = path.stat().st_size
    if entry.size_bytes > 0 and actual_size != entry.size_bytes:
        raise ModelIntegrityError(
            f"size mismatch for {name!r}: expected {entry.size_bytes} bytes, got {actual_size} at {path}"
        )

    actual = _file_sha256(path)
    if actual != entry.sha256:
        raise ModelIntegrityError(f"sha256 mismatch for {name!r}: expected {entry.sha256}, got {actual} at {path}")

    # License is part of the load-time integrity surface (fail-closed).
    if entry.license_sha256 == PENDING_OPERATOR_FETCH:
        raise ModelMissingError(
            f"license hash for {name!r} is {PENDING_OPERATOR_FETCH}; "
            "operator must pin the real license sha256 before load"
        )
    license_path = root / entry.license_file
    if not license_path.is_file():
        raise ModelMissingError(
            f"license file missing for {name!r}: {license_path} (expected {entry.license_file} next to model)"
        )
    actual_license = _file_sha256(license_path)
    if actual_license != entry.license_sha256:
        raise ModelIntegrityError(
            f"license sha256 mismatch for {name!r}: expected {entry.license_sha256}, "
            f"got {actual_license} at {license_path}"
        )

    return path


@dataclass(frozen=True, slots=True)
class ModelVerifyOutcome:
    """One-shot verified-load outcome for eager readiness probes ([EMB-05]).

    Cache identity covers model and license path stamps so license-only drift
    invalidates readiness without requiring model byte changes ([DRIFT-02]).
    """

    name: str
    ok: bool
    reason: str | None
    path: Path
    mtime_ns: int
    size: int
    license_path: Path | None = None
    license_mtime_ns: int = 0
    license_size: int = 0


def _stamp_path(path: Path) -> tuple[int, int]:
    """Return (mtime_ns, size) or (0, 0) when the path is missing/unreadable."""
    try:
        if not path.is_file():
            return (0, 0)
        st = path.stat()
        return (int(st.st_mtime_ns), int(st.st_size))
    except OSError:
        return (0, 0)


def verify_face_pipeline_model(name: str, *, models_dir: Path | None = None) -> ModelVerifyOutcome:
    """Run ``load_verified_model`` and return a cacheable outcome (model+license stamp).

    Used by profile-aware readiness so probes never report OK for bytes that
    have not passed sha256 at least once in this process ([EMB-05], [DRIFT-02]).
    """
    entry = MODEL_MANIFEST.get(name)
    if entry is None:
        root = Path(models_dir) if models_dir is not None else DEFAULT_MODELS_DIR
        return ModelVerifyOutcome(
            name=name,
            ok=False,
            reason=f"unknown model name: {name!r}",
            path=root / name,
            mtime_ns=0,
            size=0,
            license_path=None,
            license_mtime_ns=0,
            license_size=0,
        )
    root = Path(models_dir) if models_dir is not None else DEFAULT_MODELS_DIR
    path = root / entry.file_name
    license_path = root / entry.license_file
    try:
        verified = load_verified_model(name, models_dir=root)
        mtime_ns, size = _stamp_path(verified)
        lic_mtime_ns, lic_size = _stamp_path(license_path)
        # Fail closed if we cannot stamp license after a successful verify (stat race).
        if lic_mtime_ns == 0 and lic_size == 0 and not license_path.is_file():
            return ModelVerifyOutcome(
                name=name,
                ok=False,
                reason=f"license file missing for {name!r} after verify: {license_path}",
                path=verified,
                mtime_ns=mtime_ns,
                size=size,
                license_path=license_path,
                license_mtime_ns=0,
                license_size=0,
            )
        return ModelVerifyOutcome(
            name=name,
            ok=True,
            reason=None,
            path=verified,
            mtime_ns=mtime_ns,
            size=size,
            license_path=license_path.resolve() if license_path.exists() else license_path,
            license_mtime_ns=lic_mtime_ns,
            license_size=lic_size,
        )
    except (ModelIntegrityError, ModelMissingError) as exc:
        mtime_ns, size = _stamp_path(path)
        lic_mtime_ns, lic_size = _stamp_path(license_path)
        return ModelVerifyOutcome(
            name=name,
            ok=False,
            reason=str(exc),
            path=path,
            mtime_ns=mtime_ns,
            size=size,
            license_path=license_path,
            license_mtime_ns=lic_mtime_ns,
            license_size=lic_size,
        )


def verify_face_pipeline_models(*, models_dir: Path | None = None) -> dict[str, ModelVerifyOutcome]:
    """Eagerly verify both YuNet and SFace; returns per-artifact outcomes."""
    return {
        "yunet": verify_face_pipeline_model("yunet", models_dir=models_dir),
        "sface": verify_face_pipeline_model("sface", models_dir=models_dir),
    }


# ---------------------------------------------------------------------------
# Numeric-relevant runtime fingerprint (CVUP-1 findings HARM-01, HARM-02)
#
# Canonical symbol for consumers (fir-7, fir-8, fir-9, fir23-stack):
#   ``numeric_runtime_fingerprint``  →  NumericRuntimeFingerprint
#
# Not named cv_runtime_version: the stamp covers OpenCV + onnxruntime + numpy
# (all three move embedding / clustering comparability on this upgrade).
# OpenCV full version + onnxruntime major.minor are folded into the SFace
# model_id space identity (see ``space_token`` for WHY that granularity).
# ---------------------------------------------------------------------------


def _opencv_version() -> str:
    """Live OpenCV version string (lazy import; never hardcode)."""
    import cv2

    return str(cv2.__version__)


def _onnxruntime_version() -> str:
    """Live onnxruntime version string (lazy import; never hardcode)."""
    import onnxruntime  # type: ignore[import-untyped]

    return str(onnxruntime.__version__)


def _numpy_version() -> str:
    """Live numpy version string (lazy import; never hardcode)."""
    import numpy

    return str(numpy.__version__)


def _version_major_minor(version: str) -> str:
    """Return ``major.minor`` from a dotted version, or the raw string if short."""
    parts = str(version).split(".")
    if len(parts) >= 2 and parts[0] and parts[1]:
        return f"{parts[0]}.{parts[1]}"
    return str(version)


@dataclass(frozen=True, slots=True)
class NumericRuntimeFingerprint:
    """Installed-package fingerprint for numeric-relevant face-pipeline runtimes.

    Field coverage (minimum CVUP-1 findings HARM-01/HARM-02 surface):
    - opencv_version / opencv_major — warpAffine + cv2 surface
    - onnxruntime_version — YuNet + SFace inference runtime
    - numpy_version — array math under both adapters and clustering
    """

    opencv_version: str
    opencv_major: int
    onnxruntime_version: str
    numpy_version: str

    @property
    def space_token(self) -> str:
        """Compact embedding-space token folded into SFace ``model_id``.

        Granularity (WHY — which dependency bumps are space-breaking):
        - OpenCV: **full version**. ``warpAffine`` numerics are not guaranteed
          stable across any OpenCV release (the 4.x→5.0 cut already forced
          golden regeneration). Full version is the space key independent of
          how tightly the current pin is set — coarsening it would silently
          merge two embedding spaces on the next bump that does move aligner
          output.
        - onnxruntime: **major.minor only**. Pin is ``>=1.28.0,<2.0.0``;
          branch parity (1-cos ≤ 5e-12 between ORT and OpenCV embed paths)
          shows the ORT path is numerically interchangeable at this floor,
          so a routine patch bump (1.28.0→1.28.1) must not mint a new
          embedding space and orphan persisted rows. A minor bump
          (1.28→1.29) still partitions.

        Either component alone must change the token (discrimination).
        Numpy is recorded on the fingerprint but not in the space key.
        """
        ort_mm = _version_major_minor(self.onnxruntime_version)
        return f"cv{self.opencv_version}/ort{ort_mm}"

    @property
    def compact(self) -> str:
        """Single-line form for logs / operator surfaces (all fields)."""
        return (
            f"opencv={self.opencv_version};"
            f"opencv_major={self.opencv_major};"
            f"onnxruntime={self.onnxruntime_version};"
            f"numpy={self.numpy_version}"
        )


def numeric_runtime_fingerprint() -> NumericRuntimeFingerprint:
    """Return the live numeric-relevant runtime fingerprint (never hardcoded).

    Canonical accessor for CVUP-1 finding HARM-01 consumers. Read versions
    from the installed packages at call time so monkeypatching
    ``_opencv_version`` / ``_onnxruntime_version`` / ``_numpy_version`` in
    tests is sufficient.
    """
    opencv_version = _opencv_version()
    major_token = opencv_version.split(".", 1)[0]
    try:
        opencv_major = int(major_token)
    except ValueError as exc:
        raise RuntimeError(f"unparseable OpenCV major from version {opencv_version!r}") from exc
    return NumericRuntimeFingerprint(
        opencv_version=opencv_version,
        opencv_major=opencv_major,
        onnxruntime_version=_onnxruntime_version(),
        numpy_version=_numpy_version(),
    )


__all__ = [
    "DEFAULT_MODELS_DIR",
    "LICENSE_SOURCE_URLS",
    "MODEL_MANIFEST",
    "ModelIntegrityError",
    "ModelMissingError",
    "ModelProvenance",
    "ModelVerifyOutcome",
    "NumericRuntimeFingerprint",
    "OPENCV_ZOO_COMMIT",
    "PENDING_OPERATOR_FETCH",
    "load_verified_model",
    "numeric_runtime_fingerprint",
    "verify_face_pipeline_model",
    "verify_face_pipeline_models",
]
