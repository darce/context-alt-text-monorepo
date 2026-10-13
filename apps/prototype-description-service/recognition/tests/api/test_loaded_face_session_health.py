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
    calls = called_names(tree(HEALTH))
    assert "observe_api_face_adapters" in calls, "CAUSAL_RED: missing actual API adapter registry observation (ABI-07/09)"
    result, executed, original = health_diagnostics
    assert "api" in executed, "CAUSAL_RED: registry observer was not executed"
    serving = [row for row in mappings(result) if row.get("usage_origin") == "serving"]
    assert serving, "CAUSAL_RED: actual API serving observation was not emitted"
    assert any(child.get("runtime_generation_id") == "api-old"
               for row in serving for child in mappings(row))
    assert not any(child.get("runtime_generation_id") == "health-new"
                   for row in serving for child in mappings(row)), "health generation relabeled as API serving"
    assert original[0].usage_origin == "serving"
    assert original[0].runtime_record.runtime_generation_id == "api-old"


def test_worker_heartbeat_observes_its_retained_detector():
    node = tree(WORKER)
    # Allow a worker-owned helper; require its call graph to reach the actual observer.
    methods = {n.name: n for n in ast.walk(node) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    pending = ["_heartbeat_embedding_runtime_capability", "_publish_embedding_runtime_capability"]
    reached = set()
    while pending:
        name = pending.pop()
        if name in reached:
            continue
        reached.add(name)
        pending.extend(called_names(methods[name]) & methods.keys() - reached)
    observers = []
    for name in reached:
        bindings = {}
        for assignment in ast.walk(methods[name]):
            if isinstance(assignment, ast.Assign):
                targets, value = assignment.targets, assignment.value
            elif isinstance(assignment, (ast.AnnAssign, ast.NamedExpr)):
                targets, value = [assignment.target], assignment.value
            else:
                continue
            if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                    and value.func.id == "getattr" and len(value.args) >= 2
                    and isinstance(value.args[1], ast.Constant)
                    and value.args[1].value == "loaded_runtime_record"):
                for target in targets:
                    if isinstance(target, ast.Name):
                        bindings[target.id] = value.args[0]
        for call in ast.walk(methods[name]):
            if not isinstance(call, ast.Call):
                continue
            if isinstance(call.func, ast.Attribute) and call.func.attr == "loaded_runtime_record":
                observers.append(call.func.value)
            # A hasattr guard is allowed; only actual invocation is evidence.
            if isinstance(call.func, ast.Name) and call.func.id in bindings:
                observers.append(bindings[call.func.id])
            if (isinstance(call.func, ast.Call) and isinstance(call.func.func, ast.Name)
                    and call.func.func.id == "getattr" and len(call.func.args) >= 2
                    and isinstance(call.func.args[1], ast.Constant)
                    and call.func.args[1].value == "loaded_runtime_record"):
                observers.append(call.func.args[0])
    assert observers, "CAUSAL_RED: heartbeat publishes readiness without retained runtime observation"
    assert any(isinstance(value, ast.Attribute) and value.attr == "_detector"
               for value in observers), "worker observation must originate at self._detector"
    assert all("get_shared_face_pipeline_runtime" not in called_names(methods[name]) for name in reached)


def retained_worker(monkeypatch, tmp_path, generation, state):
    monkeypatch.syspath_prepend(str(ROOT))
    worker_module = importlib.import_module("recognition.worker.scan_worker")
    observations = []

    class RetainedDetector:
        # ABI-07 is keyword-only: a no-argument call must fail this double.
        def loaded_runtime_record(self, *, expected_config, active_generation_id, captured_at):
            assert expected_config is not None, "ABI-07 expected_config is required"
            assert active_generation_id in (None, generation), "health singleton is not role-local policy"
            assert isinstance(captured_at, datetime)
            assert captured_at.utcoffset() == UTC.utcoffset(captured_at)
            observations.append((generation, expected_config, active_generation_id, captured_at))
            return SimpleNamespace(runtime_generation_id=generation, state=state,
                                   reason_code="artifact_changed" if state == "drifted" else None)

    def forbidden(*args, **kwargs):
        raise AssertionError("singleton/factory/DB/client must not replace retained evidence")

    monkeypatch.setattr(worker_module, "get_recognition_settings", lambda: face_settings(tmp_path))
    monkeypatch.setattr(worker_module, "build_embedding_runtime", forbidden)
    monkeypatch.setattr(worker_module, "get_shared_face_pipeline_runtime", forbidden, raising=False)
    worker = object.__new__(worker_module.ScanWorker)
    worker._runtime_mode = "production"
    worker._detector = RetainedDetector()
    worker._embedding_runtime_ready = True
    worker._embedding_retry_after = None
    worker._http_client = None
    worker._face_pipeline_metrics = None
    worker._session_factory = forbidden
    return worker, observations


@pytest.mark.parametrize("generation", ["worker-old", "worker-restarted"])
def test_sticky_ready_still_observes_worker_generation_before_return(monkeypatch, tmp_path, generation):
    worker, observations = retained_worker(monkeypatch, tmp_path, generation, "loaded_unexercised")
    asyncio.run(worker._ensure_embedding_runtime())
    assert [row[0] for row in observations] == [generation], "CAUSAL_RED: sticky ready bypasses retained-generation evidence"
    assert worker._embedding_runtime_ready is True


def test_sticky_ready_drift_refuses_claims_without_rebuilding(monkeypatch, tmp_path):
    worker, observations = retained_worker(monkeypatch, tmp_path, "worker-old", "drifted")
    asyncio.run(worker._ensure_embedding_runtime())
    assert [row[0] for row in observations] == ["worker-old"], "CAUSAL_RED: retained drift not observed"
    assert worker._embedding_runtime_ready is False, "CAUSAL_RED: drift must demote sticky readiness"
    assert worker._can_claim_scan_items() is False


def test_existing_readiness_fixture_is_real_worker_method():
    method = function(tree(WORKER), "_ensure_embedding_runtime")
    assert isinstance(method, ast.AsyncFunctionDef)
    assert "build_embedding_runtime" in called_names(method)
