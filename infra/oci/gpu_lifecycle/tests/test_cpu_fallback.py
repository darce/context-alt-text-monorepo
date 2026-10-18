"""GPU-01d: emit florence_small fallback when the burst GPU will not come up."""

from __future__ import annotations

from infra.oci.gpu_lifecycle.controller import (
    CPU_FALLBACK_PROFILE,
    FallbackDecision,
    GpuInstance,
    GpuLifecycleController,
    LifecycleAction,
)
from infra.oci.gpu_lifecycle.probe import (
    ProbeSample,
    ProbeStatus,
    WarmReadinessWait,
)
from infra.oci.gpu_lifecycle.reaper import StaticJobLoadSource, run_start_cycle


class NeverReady:
    def probe(self, instance_id: str) -> ProbeSample:
        return ProbeSample(instance_id=instance_id, status=ProbeStatus.NOT_READY, detail="cold")


class AlwaysReady:
    def probe(self, instance_id: str) -> ProbeSample:
        return ProbeSample(instance_id=instance_id, status=ProbeStatus.READY)


class RecordingStartActuator:
    def start_instance(self, instance_id: str) -> None:
        return None


def test_fallback_decision_on_boot_failure() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    decisions = controller.fallback_on_boot_failure(["ocid1.gpu"], reason="readiness_timeout")
    assert decisions == [
        FallbackDecision(
            instance_id="ocid1.gpu",
            reason="readiness_timeout",
            action=LifecycleAction.FALLBACK,
            profile="florence_small",
        )
    ]
    assert CPU_FALLBACK_PROFILE == "florence_small"


def test_run_start_cycle_emits_fallback_on_probe_timeout() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(instance_id="ocid1.gpu", state="STOPPED", idle_for_seconds=0)
    result = run_start_cycle(
        controller=controller,
        instances=[instance],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=RecordingStartActuator(),
        probe=NeverReady(),
        readiness_wait=WarmReadinessWait(max_cycles=2, stall_cycles=10, sleep_seconds=0.0),
    )
    assert result.wait_result is not None
    assert result.wait_result.exit_code == 1
    assert len(result.fallbacks) == 1
    assert result.fallbacks[0].profile == "florence_small"
    assert result.fallbacks[0].action == LifecycleAction.FALLBACK
    assert result.fallbacks[0].instance_id == "ocid1.gpu"
    assert result.fallbacks[0].reason == "readiness_timeout"


class AlwaysError:
    def probe(self, instance_id: str) -> ProbeSample:
        return ProbeSample(instance_id=instance_id, status=ProbeStatus.ERROR, detail="hung")


def test_run_start_cycle_stall_emits_readiness_stall_fallback() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(instance_id="ocid1.gpu", state="STOPPED", idle_for_seconds=0)
    result = run_start_cycle(
        controller=controller,
        instances=[instance],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=RecordingStartActuator(),
        probe=AlwaysError(),
        readiness_wait=WarmReadinessWait(max_cycles=5, stall_cycles=2, sleep_seconds=0.0),
    )
    assert result.fallbacks
    assert result.fallbacks[0].reason == "readiness_stall"
    assert result.fallbacks[0].profile == "florence_small"


def test_no_fallback_when_instance_becomes_ready() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(instance_id="ocid1.gpu", state="STOPPED", idle_for_seconds=0)
    result = run_start_cycle(
        controller=controller,
        instances=[instance],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=RecordingStartActuator(),
        probe=AlwaysReady(),
        readiness_wait=WarmReadinessWait(max_cycles=2, stall_cycles=2, sleep_seconds=0.0),
    )
    assert result.fallbacks == ()
    assert result.wait_result is not None
    assert result.wait_result.exit_code == 0
