"""FIRCOLD-1: producer evidence must survive worker cold start and heartbeats.

External ONNX construction and persistence are recorded. The real runtime
factory, model/license verification, singleton, observation, worker lifecycle,
heartbeat SQL publisher and intake guard run unchanged. Synthetic artifact
bytes are never passed to native ORT and no inference workload is executed.
Invalid-replacement controls replay producer-issued runtime evidence at the
factory seam, independently of how singleton recovery is implemented.

Canon 0.26.2: TEST-03/06/15, DBG-02, OBS-05/08, OPS-75, GRPH-32.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import struct
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from recognition.application.scan.capability import require_scan_dispatch_ready
from recognition.infrastructure.embeddings import face_pipeline_adapter as adapter_module
from recognition.infrastructure.embeddings.runtime_factory import build_embedding_runtime
from recognition.infrastructure.face_pipeline import ort_adapters, provenance
from recognition.worker import scan_worker as worker_module


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tiny_model(name, dimension):
    """Self-contained synthetic ONNX; real acquisition validates its protobuf."""

    def varint(value):
        result = bytearray()
        while value >= 128:
            result.append((value & 127) | 128)
            value >>= 7
        return bytes(result) + bytes([value])

    def integer(field, value):
        return varint(field << 3) + varint(value)

    def blob(field, value):
        return varint((field << 3) | 2) + varint(len(value)) + value

    tensor = integer(1, 1) + integer(1, dimension) + integer(2, 1)
    tensor += blob(8, b"output") + blob(9, struct.pack("<f", 1.0) * dimension)
    shape = blob(1, integer(1, 1)) + blob(1, integer(1, dimension))
    output = blob(1, b"output") + blob(2, blob(1, integer(1, 1) + blob(2, shape)))
    graph = blob(2, ("fircold-synthetic-" + name).encode()) + blob(5, tensor) + blob(12, output)
    return integer(1, 8) + blob(7, graph) + blob(8, integer(2, 13))


class _HeartbeatStore:
    """Record committed production upserts; serve their values back to intake."""

    def __init__(self):
        self.rows = []

    def __call__(self):
        return _Session(self)

    @property
    def latest(self):
        assert self.rows, "worker did not commit a capability heartbeat"
        return self.rows[-1]

    def snapshot(self):
        prefix, marker, payload = self.latest["reason"].partition("; loaded_runtime=")
        fields = dict(part.split("=", 1) for part in prefix.split("; ") if "=" in part)
        return fields, json.loads(payload) if marker else None


class _Session:
    bind = SimpleNamespace(dialect=postgresql.dialect())

    def __init__(self, store):
        self.store = store
        self.pending = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        pass

    async def execute(self, statement, params=None):
        if getattr(getattr(statement, "table", None), "name", None) == "worker_capabilities":
            self.pending.append(statement.compile(dialect=self.bind.dialect).params)
        elif getattr(statement, "is_select", False):
            row = self.store.latest
            return SimpleNamespace(one_or_none=lambda: (row["available"], row["reason"], row["updated_at"]))
        elif params == {"app_name": "scan_worker"}:
            # The external connection witness exists; the runtime gate must
            # still use the independently published capability below.
            return SimpleNamespace(scalar_one_or_none=lambda: 1)

    async def commit(self):
        self.store.rows.extend(self.pending)
        self.pending.clear()


class _RecordingOnnxSession:
    def __init__(self, name, dimension, providers, options):
        self.name, self.dimension = name, dimension
        self.providers, self.options = providers, options

    def get_inputs(self):
        return [SimpleNamespace(name="input", shape=[1, 3, 112, 112], type="tensor(float)")]

    def get_outputs(self):
        names = ort_adapters._YUNET_OUTPUT_NAMES if self.name == "yunet" else ("output",)
        return [SimpleNamespace(name=name, shape=[1, self.dimension], type="tensor(float)") for name in names]

    def get_providers(self):
        return self.providers

    def run(self, *_args, **_kwargs):
        pytest.fail("cold initialization must not execute an inference workload")


class _ColdRuntime:
    def __init__(self, root):
        self.root = root
        self.store = _HeartbeatStore()
        self.constructions = []
        self.workers = []
        self.buffers = {}
        self.now = datetime.now(UTC)
        self.database = SimpleNamespace(pgvector_dimension=128, embedding_timeout_s=1)
        self.settings = SimpleNamespace(
            runtime_mode="prod",
            blob_root=root / "blobs",
            auraface_models_dir=root,
            identity_detection=SimpleNamespace(embedding_dimension=128),
            face_pipeline=SimpleNamespace(
                profile="face_pipeline",
                resolved_models_dir=root,
                resolved_embedder_models_dir=root,
                score_threshold=0.9,
                nms_threshold=0.3,
                top_k=5000,
                timeout_s=1,
                max_workers=1,
            ),
        )

    def select(self, profile):
        self.settings.face_pipeline.profile = profile
        dimension = 512 if profile == "auraface" else 128
        self.settings.identity_detection.embedding_dimension = dimension
        self.database.pgvector_dimension = dimension

    def worker(self):
        worker = worker_module.ScanWorker(worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:"))
        worker._session_factory = self.store
        self.workers.append(worker)
        return worker

    async def factory(self):
        return await build_embedding_runtime(settings=self.settings)


@pytest_asyncio.fixture
async def cold_runtime(monkeypatch, tmp_path):
    fixture = _ColdRuntime(tmp_path)
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "1")
    monkeypatch.delenv(ort_adapters.RETRY_MAX_SIDE_ENV, raising=False)
    # Test-local cache isolation, never a recovery action under test.
    monkeypatch.setattr(adapter_module, "_SHARED", None)
    monkeypatch.setattr(adapter_module, "_SHARED_DETECT_BREAKER", None)
    monkeypatch.setattr(adapter_module, "get_settings", lambda: fixture.settings)
    monkeypatch.setattr(adapter_module, "get_database_settings", lambda: fixture.database)
    monkeypatch.setattr(worker_module, "get_recognition_settings", lambda: fixture.settings)
    database_module = importlib.import_module("db.settings")
    monkeypatch.setattr(database_module, "get_database_settings", lambda: fixture.database)

    class _WorkerTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixture.now if tz is not None else fixture.now.replace(tzinfo=None)

    monkeypatch.setattr(worker_module, "datetime", _WorkerTime)
    for name in ("yunet", "sface", "auraface"):
        # The real verification code checks these explicit synthetic pins.
        model = _tiny_model(name, provenance.MODEL_MANIFEST[name].embedding_dim or 1)
        license_bytes = ("FIRCOLD synthetic license " + name).encode()
        entry = replace(
            provenance.MODEL_MANIFEST[name],
            file_name=name + ".onnx",
            license_file="LICENSE." + name,
            sha256=_sha(model),
            size_bytes=len(model),
            license_sha256=_sha(license_bytes),
        )
        monkeypatch.setitem(provenance.MODEL_MANIFEST, name, entry)
        (tmp_path / entry.file_name).write_bytes(model)
        (tmp_path / entry.license_file).write_bytes(license_bytes)
        fixture.buffers[name] = model

    def construct(source, sess_options=None, providers=None):
        content = source if isinstance(source, bytes) else Path(source).read_bytes()
        names = [name for name, data in fixture.buffers.items() if data == content]
        assert len(names) == 1, "unexpected model reached the external ONNX boundary"
        name = names[0]
        dimension = provenance.MODEL_MANIFEST[name].embedding_dim or 1
        session = _RecordingOnnxSession(name, dimension, providers, sess_options)
        fixture.constructions.append((name, source, session))
        return session

    def forbid_native(*_args, **_kwargs):
        pytest.fail("native ORT construction forbidden in cold-runtime unit lane")

    for module_name in ("onnxruntime.capi._pybind_state", "onnxruntime.capi.onnxruntime_pybind11_state"):
        monkeypatch.setattr(importlib.import_module(module_name), "InferenceSession", forbid_native)
    monkeypatch.setattr(ort_adapters.ort, "InferenceSession", construct)
    try:
        yield fixture
    finally:
        for worker in fixture.workers:
            await worker.__aexit__(None, None, None)


def _assert_loaded(fixture, worker, profile):
    fields, record = fixture.store.snapshot()
    print(
        "FIRCOLD_OBSERVATION",
        json.dumps({"available": fixture.store.latest["available"], "record": record}, sort_keys=True),
    )
    assert fixture.store.latest["available"] is True, (
        f"FIRCOLD_RED: cold {profile} must publish an available loaded producer; observed={record}"
    )
    assert worker._can_claim_scan_items() is True
    assert record["state"] == "loaded_unexercised"
    assert record["reason_code"] is None
    assert record["runtime_generation_id"]
    assert record["effective_profile"] == profile
    assert record["declared_embedding_dimension"] == fixture.database.pgvector_dimension
    assert record["execution_receipt"] is None
    assert record["observed_embedding_dimension"] is None
    embedder = "auraface" if profile == "auraface" else "sface"
    assert set(record["sessions"]) == {"yunet", embedder}
    for name, receipt in record["sessions"].items():
        assert receipt["session_id"]
        assert receipt["runtime_generation_id"] == record["runtime_generation_id"]
        assert receipt["observed_weight_sha256"] == _sha(fixture.buffers[name])
        assert receipt["observed_license_sha256"] == _sha((fixture.root / ("LICENSE." + name)).read_bytes())
        assert receipt["actual_providers"] == ["CPUExecutionProvider"]
        assert receipt["actual_input_metadata"] and receipt["actual_output_metadata"]
    assert len({row["session_id"] for row in record["sessions"].values()}) == 2
    assert record["config_sha256"] and record["compatibility_sha256"]
    assert {
        key: fields[key]
        for key in (
            "media_processed",
            "faces_detected",
            "rows_matched",
            "rows_new",
            "faces_skipped",
            "mixed_model_media",
        )
    } == dict.fromkeys(
        (
            "media_processed",
            "faces_detected",
            "rows_matched",
            "rows_new",
            "faces_skipped",
            "mixed_model_media",
        ),
        "0",
    )
    return record


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["face_pipeline", "auraface"])
async def test_cold_initialization_and_probes_publish_real_loaded_runtime(cold_runtime, profile):
    cold_runtime.select(profile)
    worker = cold_runtime.worker()
    await worker.__aenter__()
    initial = cold_runtime.store.snapshot()[1]
    # Exercise the path used while supported API intake is refusing new jobs.
    await worker._probe_and_publish_embedding_runtime_capability()
    await worker._probe_and_publish_embedding_runtime_capability()
    try:
        await require_scan_dispatch_ready(cold_runtime.store(), inline_processing=False)
    except HTTPException as refusal:
        print("FIRCOLD_INTAKE_REFUSAL", json.dumps({"status": refusal.status_code, "detail": refusal.detail}))
        raise AssertionError(
            f"FIRCOLD_RED: cold {profile} must permit supported scan dispatch; detail={refusal.detail}"
        ) from refusal
    final = _assert_loaded(cold_runtime, worker, profile)
    assert initial["runtime_generation_id"] == final["runtime_generation_id"]
    assert initial["sessions"] == final["sessions"]
    assert len(cold_runtime.constructions) == 2, "healthy probes must retain the loaded session pair"
    await require_scan_dispatch_ready(cold_runtime.store(), inline_processing=False)


@pytest.mark.asyncio
async def test_true_predecessor_replacement_has_new_generation_and_disjoint_sessions(cold_runtime):
    cold_runtime.select("auraface")
    worker = cold_runtime.worker()
    await worker.__aenter__()
    before = _assert_loaded(cold_runtime, worker, "auraface")
    # An actual cache-key/config change makes the retained runtime drifted and
    # requires a real new producer pair; no sticky-ready flag is manipulated.
    cold_runtime.settings.face_pipeline.score_threshold = 0.91
    await worker._probe_and_publish_embedding_runtime_capability()
    after = _assert_loaded(cold_runtime, worker, "auraface")
    assert before["runtime_generation_id"] != after["runtime_generation_id"]
    assert {r["session_id"] for r in before["sessions"].values()}.isdisjoint(
        r["session_id"] for r in after["sessions"].values()
    )
    assert before["config_sha256"] != after["config_sha256"]
    assert len(cold_runtime.constructions) == 4
    await require_scan_dispatch_ready(cold_runtime.store(), inline_processing=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["same_generation", "shared_session", "wrong_config"])
async def test_real_predecessor_rejects_replayed_or_incompatible_factory_pair(cold_runtime, monkeypatch, fault):
    cold_runtime.select("auraface")
    worker = cold_runtime.worker()
    await worker.__aenter__()
    old_detector = worker._detector
    old_runtime = old_detector._runtime
    cold_runtime.settings.face_pipeline.score_threshold = 0.91
    candidate, _ = await cold_runtime.factory()
    runtime = candidate._runtime
    # Fault injection replays identities/receipts issued by actual producers.
    # No ready flags or hand-authored LoadedRuntimeRecord/SessionReceipt exist.
    if fault == "same_generation":
        runtime = replace(runtime, runtime_generation_id=old_runtime.runtime_generation_id)
    elif fault == "shared_session":
        runtime = replace(
            runtime,
            session_receipts={
                **runtime.session_receipts,
                "yunet": old_runtime.session_receipts["yunet"],
            },
        )
    else:
        runtime = old_runtime
    monkeypatch.setattr(adapter_module, "get_shared_face_pipeline_runtime", lambda **_kwargs: runtime)
    await worker._probe_and_publish_embedding_runtime_capability()
    assert worker._detector is old_detector
    assert worker._can_claim_scan_items() is False
    assert cold_runtime.store.latest["available"] is False
    assert worker._embedding_retry_after > cold_runtime.now
    _, record = cold_runtime.store.snapshot()
    assert record["state"] == "drifted"
    assert record["reason_code"] == "effective_config_changed"
    with pytest.raises(HTTPException) as refused:
        await require_scan_dispatch_ready(cold_runtime.store(), inline_processing=False)
    assert refused.value.status_code == 503
    assert refused.value.detail == {
        "reason": "embedding_runtime_unavailable",
        "detail": cold_runtime.store.latest["reason"],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing", "model_hash", "license_hash", "pair_dimension", "manifest_dimension"])
async def test_cold_unavailable_or_wrong_config_stays_closed_with_retry_backoff(cold_runtime, fault):
    entry = provenance.MODEL_MANIFEST["sface"]
    if fault == "missing":
        (cold_runtime.root / entry.file_name).unlink()
    elif fault in {"model_hash", "license_hash"}:
        path = cold_runtime.root / (entry.file_name if fault == "model_hash" else entry.license_file)
        content = path.read_bytes()
        path.write_bytes(bytes([content[0] ^ 1]) + content[1:])
    elif fault == "pair_dimension":
        cold_runtime.database.pgvector_dimension = 512
    else:
        cold_runtime.database.pgvector_dimension = 512
        cold_runtime.settings.identity_detection.embedding_dimension = 512
    worker = cold_runtime.worker()
    await worker.__aenter__()
    constructors = len(cold_runtime.constructions)
    retry_after = worker._embedding_retry_after
    assert retry_after > cold_runtime.now
    for _ in range(2):
        await worker._probe_and_publish_embedding_runtime_capability()
    assert len(cold_runtime.constructions) == constructors
    assert worker._embedding_retry_after == retry_after
    assert worker._can_claim_scan_items() is False
    assert cold_runtime.store.latest["available"] is False
    with pytest.raises(HTTPException) as refused:
        await require_scan_dispatch_ready(cold_runtime.store(), inline_processing=False)
    assert refused.value.status_code == 503
    assert refused.value.detail == {
        "reason": "embedding_runtime_unavailable",
        "detail": cold_runtime.store.latest["reason"],
    }


@pytest.mark.asyncio
async def test_cold_unavailable_runtime_recovers_after_backoff_without_restart(cold_runtime):
    # AuraFace is an existing loaded-receipt producer control on the old tree.
    cold_runtime.select("auraface")
    path = cold_runtime.root / provenance.MODEL_MANIFEST["auraface"].file_name
    content = path.read_bytes()
    path.unlink()
    worker = cold_runtime.worker()
    await worker.__aenter__()
    assert cold_runtime.store.latest["available"] is False
    assert worker._can_claim_scan_items() is False
    path.write_bytes(content)
    constructors = len(cold_runtime.constructions)
    await worker._probe_and_publish_embedding_runtime_capability()
    assert len(cold_runtime.constructions) == constructors
    assert cold_runtime.store.latest["available"] is False
    cold_runtime.now += timedelta(seconds=31)
    await worker._probe_and_publish_embedding_runtime_capability()
    _assert_loaded(cold_runtime, worker, "auraface")
    assert worker._embedding_retry_after is None
    await require_scan_dispatch_ready(cold_runtime.store(), inline_processing=False)
