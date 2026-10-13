"""C76 ABI-09/10/15 producer contracts; only inert transport-record doubles.

Missing proposed symbols are assertion REDs, not collection errors or skips.
The Record double supports attribute and mapping access without a model loader.
PROV-01: https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/ml-systems.md#prov-01
WEB-16: https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/security.md#web-16
"""
from __future__ import annotations

import dataclasses
import importlib.util
import sys
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 1, 1, tzinfo=UTC)


class Record(dict):
    """Structural double, not a claim of a successful model observation."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


@pytest.fixture(autouse=True)
def isolated_import_state(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    for name in ("shared", "shared.source_identity", "shared.face_role_snapshot",
                 "recognition.application.face_acceptance_catalog"):
        # Register absent keys too, so transitive imports are removed on teardown.
        monkeypatch.setitem(sys.modules, name, None)
        monkeypatch.delitem(sys.modules, name)


def producer():
    path = ROOT / "shared/face_role_snapshot.py"
    assert path.is_file(), "CAUSAL_RED: missing shared/face_role_snapshot.py (ABI-09/15)"
    spec = importlib.util.spec_from_file_location("shared.face_role_snapshot", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def plain(value):
    if dataclasses.is_dataclass(value):
        return plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return plain(value.model_dump())
    return value


def observation(generation, adapter):
    return Record(
        adapter_instance_id=adapter, usage_origin="serving", active=True,
        last_execution_at=None,
        runtime_record=Record(
            producer_abi_version=1, runtime_generation_id=generation,
            model_id="auraface+synthetic", effective_profile="auraface",
            declared_embedding_dimension=512, observed_embedding_dimension=None,
            preprocessing_id="synthetic-arcface", compatibility_sha256="a" * 64,
            config_sha256="b" * 64, sessions={}, frozen_preprocessing_spec={},
            execution_receipt=None, state="loaded_unexercised",
            reason_code="execution_missing", observed_at=NOW,
        ),
    )


def inputs(role="worker", process="worker-process", sequence=1, observations=None):
    return dict(
        role=role, process_instance_id=process, observation_sequence=sequence,
        captured_at=NOW,
        adapter_observations=tuple(observations or ()), source_identity=None,
        effective_settings=Record(runtime_mode="face_pipeline", profile="auraface"),
        serving_catalog=None,
    )


def build(**kwargs):
    module = producer()
    fn = getattr(module, "build_face_role_record", None)
    assert callable(fn), "CAUSAL_RED: missing build_face_role_record (ABI-09)"
    return plain(fn(**inputs(**kwargs)))


def test_positive_api_worker_pairs_keep_independent_retained_generations():
    api = build(role="api", process="api-process", observations=[observation("api-old", "api-adapter")])
    worker = build(observations=[observation("worker-old", "worker-adapter")])
    assert api["role"] == "api" and worker["role"] == "worker"
    assert api["process_instance_id"] != worker["process_instance_id"]
    a = api["adapter_observations"][0]["runtime_record"]
    w = worker["adapter_observations"][0]["runtime_record"]
    assert a["runtime_generation_id"] == "api-old"
    assert w["runtime_generation_id"] == "worker-old"
    assert a["compatibility_sha256"] == w["compatibility_sha256"]
    assert a["runtime_generation_id"] != w["runtime_generation_id"]
    assert a["observed_embedding_dimension"] is None
    assert a["state"] == w["state"] == "loaded_unexercised"


def test_multiple_api_generations_are_preserved_without_singleton_substitution():
    rows = [observation("api-old", "a"), observation("api-new", "b")]
    module = producer()
    raw = module.build_face_role_record(**inputs(role="api", process="api-process", observations=rows))
    rows[0]["runtime_record"]["runtime_generation_id"] = "mutated-input"
    result = plain(raw)
    assert {row["runtime_record"]["runtime_generation_id"] for row in result["adapter_observations"]} == {"api-old", "api-new"}
    assert result["adapter_observations"][0]["runtime_record"]["runtime_generation_id"] == "api-old"


def test_health_probe_is_never_a_serving_adapter():
    module = producer()
    options = complete_inputs()
    assert plain(module.build_face_role_record(**options))["collection_status"] == "complete"
    row = options["adapter_observations"][0]
    row["usage_origin"] = "health_probe_only"
    result = plain(module.build_face_role_record(**options))
    assert result["collection_status"] != "complete"
    assert not any(r["usage_origin"] == "serving" for r in result["adapter_observations"])


def test_absent_observations_source_and_catalog_remain_incomplete():
    result = build()
    assert result["source_identity"] is None
    assert result["serving_catalog"] is None
    assert result["adapter_observations"] == []
    assert result["collection_status"] == "incomplete"
    assert result["reason_code"]


@pytest.mark.parametrize("version", [None, 0, 2, True, "1"])
def test_unsupported_runtime_record_version_cannot_be_complete(version):
    module = producer()
    options = complete_inputs()
    baseline = plain(module.build_face_role_record(**options))
    assert baseline["collection_status"] == "complete"
    options["adapter_observations"][0]["runtime_record"]["producer_abi_version"] = version
    result = plain(module.build_face_role_record(**options))
    assert result["collection_status"] == "incomplete"
    assert result["reason_code"] == "incompatible_version"


@pytest.mark.parametrize("sequence", [-1, True, "1"])
def test_invalid_sequence_is_rejected(sequence):
    module = producer()
    with pytest.raises((ValueError, TypeError)):
        module.build_face_role_record(**inputs(sequence=sequence))


def test_repair_cannot_enter_loaded_role_publisher():
    module = producer()
    with pytest.raises((ValueError, TypeError)):
        module.build_face_role_record(**inputs(role="fix-blob-ownership"))


@pytest.mark.parametrize("field", ["connection_string", "authorization", "raw_environment"])
def test_unallowlisted_settings_are_rejected_or_excluded(field):
    module = producer()
    args = inputs()
    args["effective_settings"][field] = "REJECTED_SENTINEL"
    try:
        result = plain(module.build_face_role_record(**args))
    except (ValueError, TypeError):
        return
    serialized = json.dumps(result, sort_keys=True)
    assert "REJECTED_SENTINEL" not in serialized
    assert field not in result["effective_settings"]


def test_atomic_publication_uses_distinct_role_process_paths(tmp_path):
    module = producer()
    fn = getattr(module, "write_face_role_record", None)
    assert callable(fn), "CAUSAL_RED: missing write_face_role_record (ABI-15)"
    for role, process in [("api", "api-one"), ("api", "api-two"), ("worker", "worker-one")]:
        record = module.build_face_role_record(**inputs(role=role, process=process))
        fn(record, evidence_dir=tmp_path, max_record_bytes=16384, deadline_monotonic=time.monotonic() + 2)
    files = [p for p in tmp_path.iterdir() if p.is_file()]
    assert len(files) == 3
    records = [json.loads(p.read_text()) for p in files]
    assert {(r["role"], r["process_instance_id"]) for r in records} == {("api", "api-one"), ("api", "api-two"), ("worker", "worker-one")}
    assert all(p.stat().st_mode & 0o077 == 0 for p in files)
    assert all(r["producer_abi_version"] == 1 for r in records)


@pytest.mark.parametrize("expired,cap", [(True, 16384), (False, 1)])
def test_failed_publication_does_not_replace_previous_record(tmp_path, expired, cap):
    module = producer()
    fn = getattr(module, "write_face_role_record", None)
    assert callable(fn), "CAUSAL_RED: missing write_face_role_record (ABI-15)"
    record = module.build_face_role_record(**inputs())
    fn(record, evidence_dir=tmp_path, max_record_bytes=16384, deadline_monotonic=time.monotonic() + 2)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    next_record = module.build_face_role_record(**inputs(sequence=2))
    try:
        result = plain(fn(next_record, evidence_dir=tmp_path, max_record_bytes=cap,
                          deadline_monotonic=time.monotonic() + (-1 if expired else 2)))
    except (ValueError, TimeoutError):
        pass
    else:
        assert result["status"] != "complete"
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before


def test_drifted_record_preserves_retained_loaded_hash_not_current_disk():
    module = producer()
    options = complete_inputs()
    row = options["adapter_observations"][0]
    runtime = row["runtime_record"]
    runtime["runtime_generation_id"] = "worker-old"
    for model, session_id, weight, license_hash in [
        ("yunet", "old-detector", "a", "c"),
        ("auraface", "old-embedder", "d", "e"),
    ]:
        runtime["sessions"][model].update(
            session_id=session_id, runtime_generation_id="worker-old",
            observed_weight_sha256=weight * 64, observed_license_sha256=license_hash * 64,
        )
    runtime["execution_receipt"].update(
        runtime_generation_id="worker-old", detector_session_id="old-detector",
        embedder_session_id="old-embedder",
    )
    assert plain(module.build_face_role_record(**options))["collection_status"] == "complete"
    row["runtime_record"]["state"] = "drifted"
    row["runtime_record"]["reason_code"] = "artifact_changed"
    result = plain(module.build_face_role_record(**options))
    retained = result["adapter_observations"][0]["runtime_record"]
    assert retained["state"] == "drifted"
    assert retained["sessions"]["auraface"]["observed_weight_sha256"] == "d" * 64
    assert retained["sessions"]["yunet"]["observed_license_sha256"] == "c" * 64
    assert result["collection_status"] != "complete"


def test_process_restart_has_new_transport_identity_and_preserves_old_record(tmp_path):
    module = producer()
    fn = getattr(module, "write_face_role_record", None)
    assert callable(fn), "CAUSAL_RED: missing write_face_role_record (ABI-15)"
    for process, sequence in [("old-worker", 12), ("new-worker", 1)]:
        record = module.build_face_role_record(**inputs(process=process, sequence=sequence))
        fn(record, evidence_dir=tmp_path, max_record_bytes=16384, deadline_monotonic=time.monotonic() + 2)
    records = [json.loads(path.read_text()) for path in tmp_path.iterdir() if path.is_file()]
    assert {(r["process_instance_id"], r["observation_sequence"]) for r in records} == {("old-worker", 12), ("new-worker", 1)}


def test_publisher_does_not_import_live_providers_or_construct_models():
    import ast
    assert (ROOT / "shared/face_role_snapshot.py").is_file(), "CAUSAL_RED: missing shared/face_role_snapshot.py (ABI-09/15)"
    node = ast.parse((ROOT / "shared/face_role_snapshot.py").read_text())
    imports = {alias.name for entry in ast.walk(node) if isinstance(entry, ast.Import)
               for alias in entry.names}
    for entry in ast.walk(node):
        if isinstance(entry, ast.ImportFrom) and entry.module:
            imports.add(entry.module)
            imports.update(entry.module + "." + alias.name for alias in entry.names)
    forbidden = ('onnxruntime', 'cv2', 'recognition.infrastructure.face_pipeline', 'recognition.infrastructure.embeddings', 'recognition.application.embedding.runtime_factory', 'recognition.application.settings', 'config', 'shared.secrets', 'db', 'api', 'requests', 'httpx', 'urllib', 'socket', 'asyncpg', 'psycopg')
    assert not {name for name in imports
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)}
    producer()


def test_email_and_error_like_extra_settings_never_serialize():
    module = producer()
    args = inputs()
    args["effective_settings"]["contact"] = "rejected" + chr(64) + "invalid.example"
    args["effective_settings"]["exception"] = "REJECTED_ERROR_SENTINEL"
    try:
        result = plain(module.build_face_role_record(**args))
    except (ValueError, TypeError):
        return
    text = json.dumps(result)
    assert chr(64) not in text, "email-like input escaped allowlist"
    assert "REJECTED_ERROR_SENTINEL" not in text, "error input escaped allowlist"


def attested_observation(role):
    generation = role + "-generation"
    row = observation(generation, role + "-adapter")
    runtime = row["runtime_record"]
    runtime.update(state="attested", reason_code=None, observed_embedding_dimension=512)
    runtime["sessions"] = {}
    for model in ("yunet", "auraface"):
        runtime["sessions"][model] = Record(
            session_id=role + "-" + model, runtime_generation_id=generation,
            logical_model_name=model, constructed_at=NOW,
            observed_weight_sha256="1" * 64, observed_weight_size_bytes=16,
            observed_license_sha256="2" * 64, observed_license_size_bytes=8,
            manifest_expectation_sha256="3" * 64, frozen_preprocessing_sha256="4" * 64,
            numeric_runtime_fingerprint={}, actual_providers=["CPUExecutionProvider"],
            actual_input_metadata=[], actual_output_metadata=[], actual_session_options={},
            graph_analysis=Record(sha256="5" * 64, synthetic=True),
        )
    runtime["execution_receipt"] = Record(
        execution_id=role + "-execution", runtime_generation_id=generation,
        detector_session_id=role + "-yunet", embedder_session_id=role + "-auraface",
        captured_at=NOW, input_lineage=Record(fixture_id="synthetic",
            fixture_sha256="6" * 64, independent_reference_sha256="7" * 64),
        detector_input=Record(sha256="8" * 64, shape=[1, 3, 8, 8], dtype="float32",
                              contiguous=True, padding_geometry={}),
        detections_sha256="9" * 64,
        alignment=Record(landmarks_sha256="a" * 64, executing_spec_sha256="4" * 64,
                         template_sha256="b" * 64, affine_sha256="c" * 64, crop_sha256="d" * 64),
        embedder_input=Record(sha256="e" * 64, shape=[1, 3, 112, 112], dtype="float32",
                             contiguous=True, channel_samples=[], mean=127.5, scale=0.0078125),
        raw_output=Record(sha256="f" * 64, dimension=512, norm=2.0),
        normalized_output=Record(sha256="0" * 64, dimension=512, norm=1.0),
        graph_analysis_sha256="5" * 64, completion="complete",
    )
    return row


def complete_inputs():
    path = ROOT / "shared/source_identity.py"
    assert path.is_file(), "CAUSAL_RED: missing shared/source_identity.py (ABI-11)"
    source_module = importlib.import_module("shared.source_identity")
    source_type = getattr(source_module, "SourceIdentityV1", None)
    assert callable(source_type), "CAUSAL_RED: missing SourceIdentityV1 (ABI-11)"
    options = inputs(observations=[attested_observation("worker")])
    options["source_identity"] = source_type(
        source_identity_version=1, source_git_sha="1" * 40, source_tree="2" * 40,
        build_context_manifest_sha256="3" * 64, service_lock_sha256="4" * 64,
        image_variant="recognition", build_time="2026-01-01T00:00:00Z",
        identity_document_sha256="5" * 64,
    )
    options["serving_catalog"] = Record(
        producer_abi_version=1, role="worker", process_instance_id="worker-process",
        pool_identity="serving-pool", tenant_context_id="synthetic-tenant",
        captured_at=NOW, deadline_monotonic=time.monotonic() + 2,
        status="complete", reason_code=None,
        instance_binding=Record(instance_id="synthetic-instance", storage_id="synthetic-storage"),
        database=Record(database_name="synthetic_store", database_oid=123,
                        current_user="serving_role", session_user="serving_role"),
        columns=[],
    )
    return options


def test_complete_synthetic_source_catalog_and_attested_observation():
    """Transport control only; all store and receipt evidence is synthetic."""
    module = producer()
    result = plain(module.build_face_role_record(**complete_inputs()))
    assert result["collection_status"] == "complete"
    assert result["reason_code"] is None
    assert result["source_identity"]["source_tree"] == "2" * 40
    assert result["serving_catalog"]["status"] == "complete"
    assert result["adapter_observations"][0]["runtime_record"]["state"] == "attested"


def test_healthy_synthetic_role_pair_keeps_receipt_session_generation_joins():
    """Positive transport control; synthetic receipts do not prove real execution."""
    module = producer()
    records = []
    for role in ("api", "worker"):
        row = attested_observation(role)
        args = inputs(role=role, process=role + "-process", observations=[row])
        args["source_identity"] = Record(
            source_identity_version=1, source_git_sha="1" * 40, source_tree="2" * 40,
            build_context_manifest_sha256="3" * 64, service_lock_sha256="4" * 64,
            image_variant="recognition", build_time="2026-01-01T00:00:00Z",
            identity_document_sha256="5" * 64,
        )
        records.append(plain(module.build_face_role_record(**args)))
    for record in records:
        role = record["role"]
        runtime = record["adapter_observations"][0]["runtime_record"]
        receipt = runtime["execution_receipt"]
        assert runtime["state"] == "attested"
        assert runtime["observed_embedding_dimension"] == 512
        assert receipt["runtime_generation_id"] == runtime["runtime_generation_id"] == role + "-generation"
        assert receipt["detector_session_id"] == runtime["sessions"]["yunet"]["session_id"]
        assert receipt["embedder_session_id"] == runtime["sessions"]["auraface"]["session_id"]
        assert receipt["raw_output"]["norm"] == 2.0
        assert receipt["normalized_output"]["norm"] == 1.0
        # Catalog is deliberately uncaptured: a healthy receipt cannot fill it.
        assert record["serving_catalog"] is None
        assert record["collection_status"] == "incomplete"


@pytest.mark.parametrize("process", ["../escape", "nested/process", "/absolute", "..\\escape"])
def test_process_instance_id_cannot_traverse_publication_directory(tmp_path, process):
    module = producer()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    sentinel = tmp_path / "escape"
    sentinel.write_bytes(b"unchanged")
    before = {path.relative_to(tmp_path): path.read_bytes()
              for path in tmp_path.rglob("*") if path.is_file()}
    try:
        record = module.build_face_role_record(**inputs(process=process))
        result = plain(module.write_face_role_record(
            record, evidence_dir=evidence, max_record_bytes=16384,
            deadline_monotonic=time.monotonic() + 2,
        ))
    except (ValueError, TypeError):
        pass
    else:
        assert result["status"] != "complete"
    after = {path.relative_to(tmp_path): path.read_bytes()
             for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before


def test_record_double_supports_attribute_protocol_and_copy():
    import copy
    row = Record(nested=Record(value=1))
    assert not hasattr(row, "missing")
    assert getattr(row, "missing", None) is None
    with pytest.raises(AttributeError):
        row.missing
    assert copy.deepcopy(row) == row
