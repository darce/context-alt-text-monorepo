"""W3-D-05: STARTING waits; STOPPING/UNKNOWN fail closed while work waits."""

from __future__ import annotations

from infra.oci.gpu_lifecycle.controller import (
    GpuInstance,
    GpuLifecycleController,
)
from infra.oci.gpu_lifecycle.probe import (
    ProbeSample,
    ProbeStatus,
    WarmReadinessWait,
)
from infra.oci.gpu_lifecycle.reaper import StaticJobLoadSource, run_start_cycle


class RecordingStartActuator:
    def __init__(self) -> None:
        self.started: list[str] = []

    def start_instance(self, instance_id: str) -> None:
        self.started.append(instance_id)


class NeverReady:
    def probe(self, instance_id: str) -> ProbeSample:
        return ProbeSample(instance_id=instance_id, status=ProbeStatus.NOT_READY, detail="cold")


def test_starting_never_restarts_but_waits_and_fallbacks() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(instance_id="ocid1.gpu", state="STARTING", idle_for_seconds=0)
    actuator = RecordingStartActuator()
    result = run_start_cycle(
        controller=controller,
        instances=[instance],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=actuator,
        probe=NeverReady(),
        readiness_wait=WarmReadinessWait(max_cycles=2, stall_cycles=10, sleep_seconds=0.0),
    )
    assert result.decided == []
    assert result.actuated == []
    assert actuator.started == []
    assert result.wait_result is not None
    assert result.wait_result.timed_out == ("ocid1.gpu",)
    assert len(result.fallbacks) == 1
    assert result.fallbacks[0].reason == "readiness_timeout"
    assert result.fallbacks[0].profile == "florence_small"


def test_stopping_fail_closed_when_work_waits() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(instance_id="ocid1.gpu", state="STOPPING", idle_for_seconds=0)
    actuator = RecordingStartActuator()
    result = run_start_cycle(
        controller=controller,
        instances=[instance],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=actuator,
    )
    assert result.decided == []
    assert result.actuated == []
    assert actuator.started == []
    assert result.errors
    assert "STOPPING" in result.errors[0]


def test_unknown_fail_closed_when_work_waits() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(instance_id="ocid1.gpu", state="UNKNOWN", idle_for_seconds=0)
    actuator = RecordingStartActuator()
    result = run_start_cycle(
        controller=controller,
        instances=[instance],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=actuator,
    )
    assert result.decided == []
    assert result.actuated == []
    assert actuator.started == []
    assert result.errors
    assert "UNKNOWN" in result.errors[0]
