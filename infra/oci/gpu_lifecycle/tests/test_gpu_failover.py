"""GPUFAIL-1: ordered multi-instance START failover on OCI capacity failure."""

from __future__ import annotations

import json
from pathlib import Path

from infra.oci.gpu_lifecycle.controller import GpuInstance, GpuLifecycleController
from infra.oci.gpu_lifecycle.reaper import (
    StaticJobLoadSource,
    _build_parser,
    run_reap_cycle,
    run_start_cycle,
)

A = "ocid1.instance.oc1.phx.a"
B = "ocid1.instance.oc1.phx.b"
C = "ocid1.instance.oc1.phx.c"


class OrderedActuator:
    def __init__(self, capacity_fail: set[str] | None = None, fail_all: bool = False) -> None:
        self.attempts: list[str] = []
        self.capacity_fail = capacity_fail or set()
        self.fail_all = fail_all

    def start_instance(self, instance_id: str) -> None:
        self.attempts.append(instance_id)
        if self.fail_all or instance_id in self.capacity_fail:
            raise RuntimeError("Out of host capacity.")


def _instances(*ids: str) -> list[GpuInstance]:
    return [GpuInstance(instance_id=i, state="STOPPED", idle_for_seconds=0) for i in ids]


def test_capacity_failover_tries_next_and_names_winner(tmp_path: Path) -> None:
    actuator = OrderedActuator(capacity_fail={A})
    gpu_state = tmp_path / "gpu-state.json"
    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=_instances(A, B, C),
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=actuator,
        gpu_state_path=gpu_state,
    )
    assert actuator.attempts == [A, B]
    assert result.actuated == [("START", B)]
    assert result.fallbacks == ()
    snapshot = json.loads(gpu_state.read_text())
    assert snapshot["instance_id"] == B
    assert snapshot["state"] == "starting"


def test_all_capacity_fail_emits_fallback() -> None:
    actuator = OrderedActuator(fail_all=True)
    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=_instances(A, B),
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=actuator,
    )
    assert actuator.attempts == [A, B]
    assert result.actuated == []
    assert result.fallbacks
    assert all(f.reason == "start_failed" for f in result.fallbacks)


def test_first_success_short_circuits() -> None:
    actuator = OrderedActuator()
    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=_instances(A, B, C),
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=actuator,
    )
    assert actuator.attempts == [A]
    assert result.actuated == [("START", A)]
    assert result.fallbacks == ()


def test_parser_accepts_multiple_instance_ids() -> None:
    args = _build_parser().parse_args(
        ["--instance-id", A, "--instance-id", B, "--queue-depth", "1", "--in-flight", "0"]
    )
    assert args.instance_ids == [A, B]


def test_reap_all_running_idle_instances() -> None:
    class Stopper:
        def __init__(self) -> None:
            self.stopped: list[str] = []

        def stop_instance(self, instance_id: str) -> None:
            self.stopped.append(instance_id)
            return None

    stopper = Stopper()
    instances = [
        GpuInstance(instance_id=A, state="RUNNING", idle_for_seconds=999),
        GpuInstance(instance_id=B, state="RUNNING", idle_for_seconds=999),
    ]
    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=instances,
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=stopper,  # type: ignore[arg-type]
        fence_delay_seconds=0.0,
    )
    assert sorted(stopper.stopped) == sorted([A, B])
    assert sorted(i for _, i in result.actuated) == sorted([A, B])


def test_installer_supports_plural_instance_ids_backward_compatible() -> None:
    repo = Path(__file__).resolve().parents[4]
    script = (repo / "scripts/deploy/gpu-lifecycle-install.sh").read_text()
    assert "GPU_INSTANCE_IDS" in script
    assert "--instance-ids" in script
    assert "GPU_INSTANCE_ID" in script  # legacy singular env/flag retained
