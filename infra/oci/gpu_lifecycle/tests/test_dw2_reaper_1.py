"""Regression tests for operator-stop handling of transitioning GPU instances."""

from __future__ import annotations

import json
from pathlib import Path

from infra.oci.gpu_lifecycle.controller import GpuInstance, GpuLifecycleController, LifecycleAction
from infra.oci.gpu_lifecycle.intent import IntentStatus
from infra.oci.gpu_lifecycle.reaper import StaticJobLoadSource, run_start_cycle
from infra.oci.gpu_lifecycle.state_snapshot import LastTransitionReason


class RecordingStartActuator:
    def __init__(self) -> None:
        self.started: list[str] = []

    def start_instance(self, instance_id: str) -> None:
        self.started.append(instance_id)


def test_stop_intent_with_work_and_stopping_gpu_emits_operator_stop_fallback(
    tmp_path: Path,
) -> None:
    gpu_state_path = tmp_path / "gpu-state.json"
    actuator = RecordingStartActuator()
    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[GpuInstance(instance_id="ocid1.gpu", state="STOPPING", idle_for_seconds=0)],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=actuator,
        gpu_state_path=gpu_state_path,
        intent="stop",
    )

    assert result.decided == []
    assert result.actuated == []
    assert actuator.started == []
    assert len(result.fallbacks) == 1
    fallback = result.fallbacks[0]
    assert fallback.action is LifecycleAction.FALLBACK
    assert fallback.instance_id == "ocid1.gpu"
    assert fallback.reason == "operator_stop_with_work"
    assert result.errors == []
    assert result.intent_status is IntentStatus.STOPPED_WITH_WORK
    assert result.last_transition_reason is LastTransitionReason.OPERATOR
    snapshot = json.loads(gpu_state_path.read_text())
    assert snapshot["state"] == "degraded"
    assert snapshot["reason"] == "operator_stop_with_work"
    assert snapshot["intent_status"] == "stopped_with_work"
    assert snapshot["last_transition_reason"] == "operator"
