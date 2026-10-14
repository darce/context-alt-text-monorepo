"""Immutable internal face producer ABI V1; model buffers never serialize.

VerifiedModelBytes fields:
logical_name: manifest lookup name; model_bytes: exact immutable acquired buffer;
model_sha256/model_size_bytes: measured buffer digest/length;
license_sha256/license_size_bytes: measured authorization buffer digest/length;
manifest_snapshot: frozen ModelProvenance used for verification and execution;
manifest_expectation_sha256: canonical manifest digest, separate from observations;
observed_model_file_identity/observed_license_file_identity: descriptor fstat
tuples (size, mtime_ns, inode, ctime_ns), invalidation hints only.

SessionReceiptV1 fields:
session_id: construction identity; runtime_generation_id: owning pair identity;
logical_model_name: manifest lookup name; constructed_at: construction timestamp;
observed_weight_sha256/observed_weight_size_bytes: consumed buffer digest/length;
observed_license_sha256/observed_license_size_bytes: authorization digest/length;
manifest_expectation_sha256: frozen manifest digest;
frozen_preprocessing_sha256: executing recipe digest;
numeric_runtime_fingerprint: captured numeric environment contract;
actual_providers: constructor session providers; actual_input_metadata and
actual_output_metadata: captured session tensor metadata; actual_session_options:
captured constructor options; graph_analysis: None or analysis whose digest is
the observed_weight_sha256, never a manifest claim.

ExecutionReceiptV1 fields:
execution_id: per-call correlation; runtime_generation_id: retained pair identity;
detector_session_id/embedder_session_id: sessions used; captured_at: capture time;
input_lineage: optional independent fixture/reference digests;
detector_input: pre-run tensor digest, shape, dtype, contiguity, padding_geometry;
detections_sha256: actual detections digest; alignment: landmark, executing spec,
template, affine and crop digests; embedder_input: pre-run tensor digest, shape,
dtype, contiguity, channel_samples, mean and scale; raw_output/normalized_output:
actual vector digest, dimension and norm; graph_analysis_sha256: bound analysis
digest or None; completion: partial, failed or executed_unreferenced only.

LoadedRuntimeRecordV1 fields:
producer_abi_version: required exact integer 1; runtime_generation_id: retained
pair identity or None; model_id: retained manifest contract; effective_profile:
retained profile; declared_embedding_dimension: manifest width;
observed_embedding_dimension: executed width or None; preprocessing_id: retained
recipe identity; compatibility_sha256: generation-independent observed contract
digest; config_sha256: frozen nonsecret configuration digest; sessions: immutable
name-to-receipt mapping; frozen_preprocessing_spec: executing spec or None;
execution_receipt: last correlated execution or None; state: not_loaded,
loaded_unexercised, attested, drifted or failed; reason_code: sanitized reason or
None; observed_at: observation timestamp. This slice cannot produce attestation.

FrozenFaceRuntimeConfig fields (exact existing cache inputs, excluding artifacts):
profile: selected profile; models_dir: detector directory; embedder_models_dir:
embedder directory; score_threshold: detection cutoff; nms_threshold: suppression
cutoff; top_k: detector candidate limit; embedding_dimension: configured width;
pgvector_dimension: configured store width. Callers supply resolved directories.

AdapterObservationV1 fields:
adapter_instance_id: serving adapter identity; usage_origin: serving/health
origin; runtime_record: retained immutable observation; last_execution_at: last
serving execution timestamp or None; active: role-local serving activity flag.
Nested mappings/sequences are defensively copied into immutable containers.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .provenance import ModelProvenance, NumericRuntimeFingerprint


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


def _freeze_fields(record: Any) -> None:
    for field in fields(record):
        value = getattr(record, field.name)
        object.__setattr__(record, field.name, _freeze(value))


@dataclass(frozen=True, slots=True)
class VerifiedModelBytes:
    logical_name: str
    model_bytes: bytes
    model_sha256: str
    model_size_bytes: int
    license_sha256: str
    license_size_bytes: int
    manifest_snapshot: ModelProvenance
    manifest_expectation_sha256: str
    observed_model_file_identity: tuple[int, int, int, int]
    observed_license_file_identity: tuple[int, int, int, int]

    def __post_init__(self) -> None:
        if type(self.model_bytes) is not bytes:
            raise TypeError("model_bytes must be immutable bytes")
        _freeze_fields(self)


@dataclass(frozen=True, slots=True)
class SessionReceiptV1:
    session_id: str
    runtime_generation_id: str
    logical_model_name: str
    constructed_at: datetime
    observed_weight_sha256: str
    observed_weight_size_bytes: int
    observed_license_sha256: str
    observed_license_size_bytes: int
    manifest_expectation_sha256: str
    frozen_preprocessing_sha256: str
    numeric_runtime_fingerprint: NumericRuntimeFingerprint | Mapping[str, Any]
    actual_providers: tuple[str, ...]
    actual_input_metadata: tuple[Mapping[str, Any], ...]
    actual_output_metadata: tuple[Mapping[str, Any], ...]
    actual_session_options: Mapping[str, Any]
    graph_analysis: Mapping[str, Any] | None

    def __post_init__(self) -> None:
        _freeze_fields(self)
        if self.graph_analysis is not None and self.graph_analysis.get("digest") != self.observed_weight_sha256:
            raise ValueError("graph analysis must bind the consumed model digest")


@dataclass(frozen=True, slots=True)
class ExecutionReceiptV1:
    execution_id: str
    runtime_generation_id: str
    detector_session_id: str
    embedder_session_id: str
    captured_at: datetime
    input_lineage: Mapping[str, Any]
    detector_input: Mapping[str, Any]
    detections_sha256: str | None
    alignment: Mapping[str, Any]
    embedder_input: Mapping[str, Any]
    raw_output: Mapping[str, Any]
    normalized_output: Mapping[str, Any]
    graph_analysis_sha256: str | None
    completion: Literal["partial", "failed", "executed_unreferenced"]

    def __post_init__(self) -> None:
        if self.completion not in {"partial", "failed", "executed_unreferenced"}:
            raise ValueError("execution requires independent lineage before completion")
        _freeze_fields(self)


@dataclass(frozen=True, slots=True)
class FrozenPreprocessingSpecV1:
    """ABI-04 executing recipe, with recursively immutable JSON values.

    Detector: channel_order/layout/dtype, pad_divisor/pad_value and score/NMS/
    top_k thresholds. Embedding: input_size/channel_order/input_mean/input_scale,
    layout/dtype and declared graph normalization. Alignment: selected estimator,
    template coordinates/dtype/digest, landmark_order, interpolation/border and
    output_size. graph_analysis is observed evidence (None when unavailable);
    pipeline_normalization is the actual post-model rule.
    """

    detector: Mapping[str, Any]
    embedding: Mapping[str, Any]
    alignment: Mapping[str, Any]
    graph_analysis: Mapping[str, Any] | None
    pipeline_normalization: str

    def __post_init__(self) -> None:
        _freeze_fields(self)

    def __getitem__(self, name: str) -> Any:
        # Preserve internal recipe readers while the record itself is typed.
        if name not in {field.name for field in fields(self)}:
            raise KeyError(name)
        return getattr(self, name)

    def digest(self) -> str:
        """Hash every ABI field using canonical JSON, never mapping reprs."""
        def plain(value: Any) -> Any:
            if isinstance(value, Mapping):
                return {key: plain(item) for key, item in value.items()}
            if isinstance(value, tuple):
                return [plain(item) for item in value]
            return value

        payload = {field.name: plain(getattr(self, field.name)) for field in fields(self)}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                         allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class LoadedRuntimeRecordV1:
    producer_abi_version: int
    runtime_generation_id: str | None
    model_id: str | None
    effective_profile: str
    declared_embedding_dimension: int | None
    observed_embedding_dimension: int | None
    preprocessing_id: str | None
    compatibility_sha256: str | None
    config_sha256: str | None
    sessions: Mapping[str, SessionReceiptV1]
    frozen_preprocessing_spec: FrozenPreprocessingSpecV1 | None
    execution_receipt: ExecutionReceiptV1 | None
    state: Literal["not_loaded", "loaded_unexercised", "attested", "drifted", "failed"]
    reason_code: str | None
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.frozen_preprocessing_spec is not None and not isinstance(
            self.frozen_preprocessing_spec, FrozenPreprocessingSpecV1
        ):
            raise TypeError("frozen_preprocessing_spec must be FrozenPreprocessingSpecV1 or None")
        if type(self.producer_abi_version) is not int or self.producer_abi_version != 1:
            raise ValueError("unsupported face producer ABI version")
        if self.state not in {"not_loaded", "loaded_unexercised", "attested", "drifted", "failed"}:
            raise ValueError("unsupported runtime state")
        if self.state == "attested":
            raise ValueError("independent attestation is unavailable in this producer slice")
        _freeze_fields(self)


@dataclass(frozen=True, slots=True)
class FrozenFaceRuntimeConfig:
    profile: str
    models_dir: Path
    embedder_models_dir: Path
    score_threshold: float
    nms_threshold: float
    top_k: int
    embedding_dimension: int
    pgvector_dimension: int


@dataclass(frozen=True, slots=True)
class AdapterObservationV1:
    adapter_instance_id: str
    usage_origin: str
    runtime_record: LoadedRuntimeRecordV1
    last_execution_at: datetime | None
    active: bool


__all__ = [
    "FrozenPreprocessingSpecV1",
    "VerifiedModelBytes",
    "SessionReceiptV1",
    "ExecutionReceiptV1",
    "LoadedRuntimeRecordV1",
    "FrozenFaceRuntimeConfig",
    "AdapterObservationV1",
]
