"""Offline C76 health/worker wiring contracts with inert provider seams.

G1 ABI-07 supplies loaded_runtime_record and observe_api_face_adapters.
These checks execute real health/worker functions, never endpoint/E2E flows.
"""
from __future__ import annotations

import ast
import asyncio
import dataclasses
import importlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
WORKER = ROOT / "recognition/worker/scan_worker.py"
HEALTH = ROOT / "recognition/application/health.py"


def tree(path):
    return ast.parse(path.read_text(), filename=str(path))


def function(node, name):
    result = [n for n in ast.walk(node) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    assert len(result) == 1, f"fixture: expected one existing {name}"
    return result[0]


def called_names(node):
    return {n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id
            for n in ast.walk(node) if isinstance(n, ast.Call)
            and isinstance(n.func, (ast.Name, ast.Attribute))}


def plain(value):
    if dataclasses.is_dataclass(value):
        return plain(dataclasses.asdict(value))
    if isinstance(value, SimpleNamespace):
        return plain(vars(value))
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if hasattr(value, "model_dump"):
        return plain(value.model_dump())
    return value


def mappings(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from mappings(item)
    elif isinstance(value, list):
        for item in value:
            yield from mappings(item)


def face_settings(tmp_path):
    return SimpleNamespace(runtime_mode="production", face_pipeline=SimpleNamespace(
        profile="auraface", resolved_models_dir=tmp_path / "detector",
        resolved_embedder_models_dir=tmp_path / "embedder", models_dir=tmp_path / "detector",
        embedder_models_dir=tmp_path / "embedder", score_threshold=0.9,
        nms_threshold=0.3, top_k=5000, embedding_dimension=512),
        pgvector_dim=512, identity_detection=SimpleNamespace(embedding_dimension=512))


@dataclasses.dataclass(frozen=True)
class RuntimeObservation:
    runtime_generation_id: str
    state: str = "loaded_unexercised"


@dataclasses.dataclass(frozen=True)
class AdapterObservation:
    adapter_instance_id: str
    usage_origin: str
    runtime_record: RuntimeObservation
    last_execution_at: datetime | None = None
    active: bool = True


@pytest.fixture
def health_diagnostics(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT))
    health = importlib.import_module("recognition.application.health")
    adapter = importlib.import_module("recognition.infrastructure.embeddings.face_pipeline_adapter")
    config = importlib.import_module("recognition.config")
    settings = face_settings(tmp_path)
    singleton = SimpleNamespace(runtime_generation_id="health-new", state="loaded_unexercised")
    singleton.loaded_runtime_record = lambda **kwargs: RuntimeObservation("health-new")
    observations = (AdapterObservation("api-adapter", "serving", RuntimeObservation("api-old")),)
    calls = []

    def observe(*, expected_config, captured_at):
        assert expected_config is not None
        assert isinstance(captured_at, datetime) and captured_at.utcoffset() == UTC.utcoffset(captured_at)
        calls.append("api")
        return observations

    def get_runtime(**kwargs):
        calls.append("health")
        return singleton

    monkeypatch.setattr(health, "assert_space_activatable", lambda space: None)
    monkeypatch.setattr(health, "_cached_verify_outcome", lambda *a, **k: SimpleNamespace(ok=True))
    monkeypatch.setattr(health, "_with_numeric_runtime_fingerprint", lambda result: result)
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setattr(adapter, "assert_three_way_embedding_dimensions", lambda manifest: None)
    monkeypatch.setattr(adapter, "auraface_embedding_model_manifest", lambda: object())
    monkeypatch.setattr(adapter, "get_shared_face_pipeline_runtime", get_runtime)
    # G1 symbols are provider seams, not test-built health diagnostics.
    monkeypatch.setattr(adapter, "observe_api_face_adapters", observe, raising=False)
    if hasattr(health, "observe_api_face_adapters"):
        monkeypatch.setattr(health, "observe_api_face_adapters", observe)
    if hasattr(health, "get_shared_face_pipeline_runtime"):
        monkeypatch.setattr(health, "get_shared_face_pipeline_runtime", get_runtime)
    result = health.check_model_space(health.ModelSpace.AURAFACE, tmp_path / "embedder")
    assert result.status is health.HealthStatus.OK, "fixture: inert readiness setup must be healthy"
    return plain(result), calls, observations


def test_health_labels_probe_only_generation_in_executable_code(health_diagnostics):
    result, calls, _ = health_diagnostics
    assert "health" in calls
    rows = [row for row in mappings(result) if row.get("usage_origin") == "health_probe_only"]
    assert rows, "CAUSAL_RED: emitted singleton diagnostics lack health_probe_only origin"
    assert any(child.get("runtime_generation_id") == "health-new"
               for row in rows for child in mappings(row))


def test_health_observes_api_registry_without_relabeling_singleton(health_diagnostics):
    # F04: execution also accepts getattr-bound observers; AST spelling is not evidence.
    result, executed, original = health_diagnostics
    assert "api" in executed, "CAUSAL_RED: registry observer was not executed"
    serving = [row for row in mappings(result) if row.get("usage_origin") == "serving"]
    assert serving, "CAUSAL_RED: actual API serving observation was not emitted"
    # F03: renamed/missing generation keys must not hide an extra singleton row.
    assert sorted(row.get("adapter_instance_id", "") for row in serving) == sorted(
        row.adapter_instance_id for row in original
    ), "CAUSAL_RED: serving rows must equal the observed adapter ids exactly"
    assert any(child.get("runtime_generation_id") == "api-old"
               for row in serving for child in mappings(row))
    assert not any(child.get("runtime_generation_id") == "health-new"
                   for row in serving for child in mappings(row)), "health generation relabeled as API serving"
    assert original[0].usage_origin == "serving"
    assert original[0].runtime_record.runtime_generation_id == "api-old"


def recording_heartbeat(monkeypatch, worker):
    """Execute real heartbeat/publish methods with in-memory session boundaries."""
    worker_module = importlib.import_module("recognition.worker.scan_worker")
    dialect = importlib.import_module("recognition.shared.db.dialect")
    events, publications = [], []

    class Session:
        async def __aenter__(self):
            events.append("enter")
            return self

        async def __aexit__(self, *args):
            events.append("exit")

        async def commit(self):
            events.append("commit")

    session = Session()

    async def bypass(actual):
        assert actual is session
        events.append("bypass")

    async def publish(actual, **kwargs):
        assert actual is session
        events.append("publish")
        publications.append(plain(kwargs))

    worker._session_factory = lambda: session
    worker._scan_counters = worker_module.ScanWorkerCounters()
    monkeypatch.setattr(dialect, "is_postgres", lambda actual: actual is session)
    monkeypatch.setattr(worker_module, "enable_rls_bypass", bypass)
    monkeypatch.setattr(worker_module, "publish_embedding_runtime_capability", publish)
    return events, publications


@pytest.mark.parametrize("state", ["loaded_unexercised", "drifted"])
def test_worker_heartbeat_observes_its_retained_detector(monkeypatch, tmp_path, state):
    # F01: dead/no-arg calls cannot satisfy an executed ABI-07 observation.
    worker, observations = retained_worker(monkeypatch, tmp_path, "worker-old", state)
    events, publications = recording_heartbeat(monkeypatch, worker)
    for index in range(2):
        asyncio.run(worker._heartbeat_embedding_runtime_capability())
        assert len(observations) == index + 1, "CAUSAL_RED: one ABI-07 observation per heartbeat required"
        assert len(publications) == index + 1, "CAUSAL_RED: heartbeat must publish its observation"
        publication = publications[-1]
        assert publication["available"] is (state != "drifted"), "CAUSAL_RED: published availability ignores retained state"
        assert "worker-old" in repr(publication), "CAUSAL_RED: published capability lacks observed generation"
        assert events == ["enter", "bypass", "publish", "commit", "exit"] * (index + 1)


def retained_worker(monkeypatch, tmp_path, generation, state, *, allow_rebuild=False):
    monkeypatch.syspath_prepend(str(ROOT))
    worker_module = importlib.import_module("recognition.worker.scan_worker")
    observations = []
    records = []
    rebuilds = []

    class RetainedDetector:
        def __init__(self, generation, state, session_id):
            self.generation, self.state = generation, state
            self.record = SimpleNamespace(
                runtime_generation_id=generation, state=state,
                reason_code="artifact_changed" if state == "drifted" else None,
                sessions=(SimpleNamespace(session_id=session_id),),
                execution_receipt={"runtime_generation_id": generation, "session_id": session_id},
            )

        # ABI-07 is keyword-only: a no-argument call must fail this double.
        def loaded_runtime_record(self, *, expected_config, active_generation_id, captured_at):
            # F06: object() must not impersonate the frozen G1 runtime config.
            assert dataclasses.is_dataclass(expected_config), "CAUSAL_RED: expected_config must be FrozenFaceRuntimeConfig"
            assert type(expected_config).__name__ == "FrozenFaceRuntimeConfig"
            assert expected_config.__dataclass_params__.frozen, "CAUSAL_RED: expected_config must be frozen"
            assert active_generation_id in (None, self.generation), "health singleton is not role-local policy"
            assert isinstance(captured_at, datetime)
            assert captured_at.utcoffset() == UTC.utcoffset(captured_at)
            observations.append((self.generation, expected_config, active_generation_id, captured_at))
            records.append(self.record)
            return self.record

    def forbidden(*args, **kwargs):
        raise AssertionError("singleton/factory/DB/client must not replace retained evidence")

    monkeypatch.setattr(worker_module, "get_recognition_settings", lambda: face_settings(tmp_path))

    async def rebuild(**kwargs):
        rebuilds.append(kwargs)
        return RetainedDetector("worker-new", "loaded_unexercised", "session-new"), SimpleNamespace()

    monkeypatch.setattr(worker_module, "build_embedding_runtime", rebuild if allow_rebuild else forbidden)
    monkeypatch.setattr(worker_module, "get_shared_face_pipeline_runtime", forbidden, raising=False)
    worker = object.__new__(worker_module.ScanWorker)
    worker._runtime_mode = "production"
    worker._detector = RetainedDetector(generation, state, "session-old")
    worker._embedding_runtime_ready = True
    worker._embedding_retry_after = None
    worker._face_pipeline_metrics = None
    worker._session_factory = forbidden
    worker._http_client = SimpleNamespace()  # inert, already allocated; no client construction
    worker._config = SimpleNamespace(max_attempts=1, max_concurrency=1)
    worker._object_store_factory = None
    worker._scan_counters = worker_module.ScanWorkerCounters()
    worker._hlt_records = records
    worker._hlt_rebuilds = rebuilds
    worker._hlt_original_record = worker._detector.record
    monkeypatch.setattr(worker_module, "ScanItemHandler", lambda **kwargs: SimpleNamespace())
    return worker, observations


@pytest.mark.parametrize("generation", ["worker-old", "worker-restarted"])
def test_sticky_ready_still_observes_worker_generation_before_return(monkeypatch, tmp_path, generation):
    worker, observations = retained_worker(monkeypatch, tmp_path, generation, "loaded_unexercised")
    asyncio.run(worker._ensure_embedding_runtime())
    assert [row[0] for row in observations] == [generation], "CAUSAL_RED: sticky ready bypasses retained-generation evidence"
    assert worker._embedding_runtime_ready is True


def test_sticky_ready_drift_requires_new_generation_and_session_on_rebuild(monkeypatch, tmp_path):
    # F07 / ABI-08: a same-pass rebuild is permitted with fresh identities only.
    worker, observations = retained_worker(
        monkeypatch, tmp_path, "worker-old", "drifted", allow_rebuild=True
    )
    original = worker._hlt_original_record
    before = plain(original)
    _, publications = recording_heartbeat(monkeypatch, worker)
    asyncio.run(worker._ensure_embedding_runtime())
    assert observations and observations[0][0] == "worker-old", "CAUSAL_RED: retained drift not observed"
    assert plain(original) == before, "CAUSAL_RED: earlier receipt was mutated or overwritten"
    if worker._hlt_rebuilds:
        assert len(worker._hlt_rebuilds) == 1
        assert len(worker._hlt_records) >= 2, "CAUSAL_RED: replacement must be observed"
        assert worker._hlt_records[-1] is not original, "CAUSAL_RED: rebuild overwrote earlier receipt"
        replacement = plain(worker._hlt_records[-1])
        assert replacement["runtime_generation_id"] != before["runtime_generation_id"], "CAUSAL_RED: rebuild reused generation"
        old_sessions = {row["session_id"] for row in before["sessions"]}
        new_sessions = {row["session_id"] for row in replacement["sessions"]}
        assert new_sessions and new_sessions.isdisjoint(old_sessions), "CAUSAL_RED: rebuild reused session"
        assert publications, "CAUSAL_RED: replacement generation must be published"
        assert replacement["runtime_generation_id"] in repr(publications[-1])
        assert all(session_id in repr(publications[-1]) for session_id in new_sessions)
        assert worker._embedding_runtime_ready is True
    else:
        assert worker._embedding_runtime_ready is False, "CAUSAL_RED: drift must demote sticky readiness"
        assert worker._can_claim_scan_items() is False


def test_existing_readiness_fixture_is_real_worker_method():
    method = function(tree(WORKER), "_ensure_embedding_runtime")
    assert isinstance(method, ast.AsyncFunctionDef)
    assert "build_embedding_runtime" in called_names(method)
