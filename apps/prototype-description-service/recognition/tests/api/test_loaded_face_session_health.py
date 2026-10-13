"""Offline C76 health/worker wiring contracts; no application import or DB.

Execute only the existing worker readiness method with inert dependencies.
Health ABI is additive diagnostics; AST checks do not claim endpoint/E2E PASS.
"""
from __future__ import annotations

import ast
import asyncio
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


def test_health_labels_probe_only_generation_in_executable_code():
    constants = {n.value for n in ast.walk(tree(HEALTH)) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "health_probe_only" in constants, "CAUSAL_RED: singleton origin lacks health_probe_only label"


def test_health_observes_api_registry_without_relabeling_singleton():
    calls = called_names(tree(HEALTH))
    assert "observe_api_face_adapters" in calls, "CAUSAL_RED: missing actual API adapter registry observation (ABI-07/09)"


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
    observers = [n for name in reached for n in ast.walk(methods[name])
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "loaded_runtime_record"]
    assert observers, "CAUSAL_RED: heartbeat publishes readiness without retained runtime observation"
    assert any(isinstance(call.func.value, ast.Attribute) and call.func.value.attr == "_detector"
               for call in observers), "worker observation must originate at self._detector"
    assert all("get_shared_face_pipeline_runtime" not in called_names(methods[name]) for name in reached)


@pytest.mark.parametrize("generation", ["worker-old", "worker-restarted"])
def test_sticky_ready_still_observes_worker_generation_before_return(generation):
    method = function(tree(WORKER), "_ensure_embedding_runtime")
    observations = []

    class RetainedDetector:
        def loaded_runtime_record(self, **kwargs):
            observations.append(generation)
            return SimpleNamespace(runtime_generation_id=generation, state="drifted")

    def forbidden(*args, **kwargs):
        raise AssertionError("health singleton/factory/settings must not replace retained evidence")

    namespace = {"UnavailableFaceDetector": type("UnavailableFaceDetector", (), {}),
                 "build_embedding_runtime": forbidden, "get_recognition_settings": forbidden,
                 "get_shared_face_pipeline_runtime": forbidden}
    isolated = ast.Module(body=[method], type_ignores=[])
    exec(compile(isolated, str(WORKER), "exec"), namespace)
    worker = SimpleNamespace(_runtime_mode="production", _detector=RetainedDetector(),
                             _embedding_runtime_ready=True)
    # Helper implementations are checked separately by the heartbeat call graph.
    # A helper needed here must be a real worker method, never a test-built producer.
    class_node = next(n for n in tree(WORKER).body if isinstance(n, ast.ClassDef) and n.name == "ScanWorker")
    for helper in class_node.body:
        if isinstance(helper, (ast.FunctionDef, ast.AsyncFunctionDef)) and helper.name in called_names(method):
            helper_module = ast.Module(body=[helper], type_ignores=[])
            exec(compile(helper_module, str(WORKER), "exec"), namespace)
            setattr(worker, helper.name, namespace[helper.name].__get__(worker))
    asyncio.run(namespace["_ensure_embedding_runtime"](worker))
    assert observations == [generation], "CAUSAL_RED: sticky ready bypasses retained-generation evidence"


def test_existing_readiness_fixture_is_real_worker_method():
    method = function(tree(WORKER), "_ensure_embedding_runtime")
    assert isinstance(method, ast.AsyncFunctionDef)
    assert "build_embedding_runtime" in called_names(method)
