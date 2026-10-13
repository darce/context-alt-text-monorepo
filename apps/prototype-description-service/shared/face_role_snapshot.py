"""Pure role-record construction and bounded local publication."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import time
import uuid

from shared.source_identity import SourceIdentityV1

SETTINGS_FIELDS = frozenset({
    "runtime_mode", "profile", "detector_dimension", "embedding_dimension",
    "detector_embedding_dimension", "embedder_embedding_dimension",
    "detector_directory_identity", "embedder_directory_identity", "detector_threshold",
    "detector_score_threshold", "detector_nms_threshold", "detector_top_k",
    "normalization", "metric", "numeric_runtime_fingerprint", "actual_providers",
    "actual_session_options", "blob_backend", "environment_id",
})
IMAGE_FIELDS = frozenset({"role", "container_id", "repair_invocation_id", "registry_manifest_digest",
                          "digest_type", "platform", "image_config_digest", "identity_document_sha256"})


def _copy(value, depth=0):
    """Structural copy avoids provider hooks and broken mapping __getattr__."""
    if depth > 32:
        raise ValueError("record_too_deep")
    if value is None or type(value) in (bool, int):
        return value
    if isinstance(value, str):
        if len(value) > 16384 or chr(64) in value:
            raise ValueError("unsafe_record_string")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("nonfinite_record")
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("capture_timezone_missing")
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _copy(getattr(value, f.name), depth + 1) for f in fields(value)}
    if isinstance(value, Mapping):
        if len(value) > 1024:
            raise ValueError("record_too_wide")
        result = {}
        for key, item in value.items():
            if not isinstance(key, str) or key.lower() in {
                "authorization", "connection_string", "raw_environment", "password", "secret",
                "auth", "exception", "email", "contact", "credentials", "dsn"}:
                raise ValueError("unsafe_record_field")
            result[_copy(key, depth + 1)] = _copy(item, depth + 1)
        return result
    if isinstance(value, (tuple, list)):
        if len(value) > 1024:
            raise ValueError("record_too_wide")
        return [_copy(item, depth + 1) for item in value]
    raise TypeError("unsupported_record_value")


def _version(value):
    return type(value) is int and value == 1


def _process(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value) is None:
        raise ValueError("invalid_process_identity")


@dataclass(frozen=True, kw_only=True)
class FaceRoleRecordV1:
    producer_abi_version: int
    role: str
    process_instance_id: str
    observation_sequence: int
    captured_at: datetime
    source_identity: object
    effective_settings: dict
    adapter_observations: tuple
    serving_catalog: object
    collection_status: str
    reason_code: str | None


@dataclass(frozen=True, kw_only=True)
class PublicationResultV1:
    status: str
    reason_code: str | None
    path: str | None


@dataclass(frozen=True, kw_only=True)
class RepairIdentityRecordV1:
    producer_abi_version: int
    role: str
    captured_at: datetime
    repair_invocation_id: str
    source_identity: SourceIdentityV1 | None
    image_record: object
    collection_status: str
    reason_code: str | None

    def __post_init__(self):
        if not _version(self.producer_abi_version) or self.role != "fix-blob-ownership":
            raise ValueError("invalid_repair_identity")
        _process(self.repair_invocation_id)
        _copy(self.captured_at)
        if self.source_identity is not None:
            SourceIdentityV1(**_copy(self.source_identity))
        image = _copy(self.image_record)
        if image is not None and (not isinstance(image, dict) or set(image) - IMAGE_FIELDS):
            raise ValueError("invalid_image_fields")
        if image is not None:
            if any(not isinstance(value, str) or not value for value in image.values()):
                raise ValueError("invalid_image_value")
            for name in ("registry_manifest_digest", "image_config_digest"):
                if name in image and (not isinstance(image[name], str) or
                                      re.fullmatch(r"sha256:[0-9a-f]{64}", image[name]) is None):
                    raise ValueError("invalid_image_digest")
            if "identity_document_sha256" in image and re.fullmatch(r"[0-9a-f]{64}", image["identity_document_sha256"]) is None:
                raise ValueError("invalid_image_digest")
            if image.get("role", self.role) != self.role:
                raise ValueError("contradictory_image_role")
        if self.collection_status not in {"complete", "incomplete", "failed", "not_applicable"}:
            raise ValueError("invalid_collection_status")
        if self.collection_status == "complete" and (self.source_identity is None or image is None):
            raise ValueError("repair_binding_missing")
        if self.collection_status == "complete":
            required = {"registry_manifest_digest", "digest_type", "platform",
                        "image_config_digest", "identity_document_sha256"}
            if not required <= image.keys() or image["digest_type"] not in {"manifest", "index"}:
                raise ValueError("repair_binding_missing")
            if image["identity_document_sha256"] != _copy(self.source_identity)["identity_document_sha256"]:
                raise ValueError("contradictory_image_identity")
        object.__setattr__(self, "source_identity", _copy(self.source_identity))
        object.__setattr__(self, "image_record", image)
        _copy(self.reason_code)


def _attested(row):
    runtime = row.get("runtime_record")
    if not isinstance(runtime, dict) or not _version(runtime.get("producer_abi_version")):
        return False
    if row.get("usage_origin") != "serving" or row.get("active") is not True or runtime.get("state") != "attested":
        return False
    receipt = runtime.get("execution_receipt")
    sessions = runtime.get("sessions")
    generation = runtime.get("runtime_generation_id")
    if not generation or not isinstance(receipt, dict) or not isinstance(sessions, dict):
        return False
    if receipt.get("completion") != "complete" or receipt.get("runtime_generation_id") != generation:
        return False
    if set(sessions) != {"yunet", "auraface"}:
        return False
    for model, receipt_key in (("yunet", "detector_session_id"), ("auraface", "embedder_session_id")):
        session = sessions[model]
        if not isinstance(session, dict) or session.get("runtime_generation_id") != generation:
            return False
        if not session.get("session_id") or receipt.get(receipt_key) != session["session_id"]:
            return False
    dimension = runtime.get("observed_embedding_dimension")
    return type(dimension) is int and dimension > 0 and dimension == runtime.get("declared_embedding_dimension")


def build_face_role_record(*, role, process_instance_id, observation_sequence, captured_at,
                           adapter_observations, source_identity, effective_settings, serving_catalog):
    if role not in {"api", "worker"}:
        raise ValueError("invalid_role")
    _process(process_instance_id)
    if type(observation_sequence) is not int or observation_sequence < 0:
        raise ValueError("invalid_sequence")
    _copy(captured_at)
    settings = _copy(effective_settings)
    if not isinstance(settings, dict) or set(settings) - SETTINGS_FIELDS:
        raise ValueError("unallowlisted_settings")
    source = _copy(source_identity)
    if source is not None:
        SourceIdentityV1(**source)
    rows = _copy(adapter_observations)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("invalid_observations")
    for row in rows:
        runtime = row.get("runtime_record")
        if runtime is not None and (not isinstance(runtime, dict) or not _version(runtime.get("producer_abi_version"))):
            raise ValueError("incompatible_version")
    catalog = _copy(serving_catalog)
    complete = (source is not None and bool(rows) and all(_attested(row) for row in rows)
                and isinstance(catalog, dict) and _version(catalog.get("producer_abi_version"))
                and catalog.get("status") == "complete" and catalog.get("role") == role
                and catalog.get("process_instance_id") == process_instance_id)
    return FaceRoleRecordV1(producer_abi_version=1, role=role, process_instance_id=process_instance_id,
                            observation_sequence=observation_sequence, captured_at=captured_at,
                            source_identity=source, effective_settings=settings, adapter_observations=tuple(rows),
                            serving_catalog=catalog, collection_status="complete" if complete else "incomplete",
                            reason_code=None if complete else "evidence_incomplete")


def write_face_role_record(record, *, evidence_dir: Path, max_record_bytes: int, deadline_monotonic: float):
    def check_deadline():
        if not math.isfinite(deadline_monotonic) or time.monotonic() >= deadline_monotonic:
            raise TimeoutError("publication_deadline")
    check_deadline()
    if record.role not in {"api", "worker"} or not _version(record.producer_abi_version):
        raise ValueError("invalid_role_record")
    _process(record.process_instance_id)
    if type(max_record_bytes) is not int or max_record_bytes <= 0:
        raise ValueError("invalid_size_cap")
    payload = json.dumps(_copy(record), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(payload) > max_record_bytes:
        raise ValueError("record_oversized")
    check_deadline()
    directory = Path(evidence_dir)
    target = directory / (record.role + "-" + record.process_instance_id + ".json")
    temporary = directory / ("." + target.name + "." + uuid.uuid4().hex + ".tmp")
    created = False
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        created = True
        with os.fdopen(fd, "wb") as stream:
            check_deadline()
            stream.write(payload)
            stream.flush()
            check_deadline()
            os.fsync(stream.fileno())
        check_deadline()
        os.replace(temporary, target)
    finally:
        if created:
            temporary.unlink(missing_ok=True)
    return PublicationResultV1(status="complete", reason_code=None, path=str(target))
