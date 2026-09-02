"""GPUW-1: the max-lease cost backstop.

Everything else in this module fails closed *toward busy*: a missing, stale or
unparseable load dump cancels the STOP. That protects jobs and leaves cost
unbounded -- a dead load writer means nothing in the system will ever stop a
running A10 (~$2/hr). These pin the one path that stops on wall clock alone.
"""

from __future__ import annotations

from infra.oci.gpu_lifecycle.controller import (
    GpuInstance,
    GpuLifecycleController,
)
from infra.oci.gpu_lifecycle.reaper import (
    StaticJobLoadSource,
    _build_parser,
    run_reap_cycle,
)


class RecordingActuator:
    def __init__(self) -> None:
        self.stopped: list[str] = []

    def stop_instance(self, instance_id: str) -> None:
        self.stopped.append(instance_id)


class ExplodingActuator:
    def stop_instance(self, instance_id: str) -> None:
        raise RuntimeError("oci unavailable")


class BusyLoadSource:
    """The failure this backstop exists for: load always claims work."""

    def snapshot(self):
        from infra.oci.gpu_lifecycle.controller import JobLoadSnapshot

        return JobLoadSnapshot(queue_depth=5, in_flight=2, batch_in_progress=True)


def _running(age: int, instance_id: str = "ocid1.instance.oc1..gpu") -> GpuInstance:
    return GpuInstance(instance_id=instance_id, state="RUNNING", idle_for_seconds=age)


# --- controller-level -------------------------------------------------------


def test_lease_expired_selects_running_instance_past_the_cap() -> None:
    controller = GpuLifecycleController(idle_seconds=300)
    actions = controller.lease_expired_instances(
        [_running(3601)], max_lease_seconds=3600
    )
    assert actions == [("STOP", "ocid1.instance.oc1..gpu")]


def test_lease_not_expired_below_the_cap() -> None:
    """TEST-15: the cap must be able to *not* fire, or it kills every batch."""
    controller = GpuLifecycleController(idle_seconds=300)
    assert controller.lease_expired_instances([_running(60)], max_lease_seconds=3600) == []


def test_lease_cap_ignores_instances_that_are_not_running() -> None:
    controller = GpuLifecycleController(idle_seconds=300)
    stopped = GpuInstance(
        instance_id="ocid1.instance.oc1..gpu", state="STOPPED", idle_for_seconds=99_999
    )
    starting = GpuInstance(
        instance_id="ocid1.instance.oc1..gpu2", state="STARTING", idle_for_seconds=99_999
    )
    assert controller.lease_expired_instances(
        [stopped, starting], max_lease_seconds=60
    ) == []


def test_lease_cap_disabled_by_zero() -> None:
    controller = GpuLifecycleController(idle_seconds=300)
    assert controller.lease_expired_instances([_running(99_999)], max_lease_seconds=0) == []


# --- cycle-level: the cap must beat the fence -------------------------------


def test_lease_expiry_stops_even_when_load_claims_a_batch_is_running() -> None:
    """The whole point: a busy-forever load signal cannot veto the backstop."""
    controller = GpuLifecycleController(idle_seconds=300)
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=controller,
        instances=[_running(7200)],
        load_source=BusyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
    )

    assert actuator.stopped == ["ocid1.instance.oc1..gpu"]
    assert result.lease_expired == [("STOP", "ocid1.instance.oc1..gpu")]
    # Reported separately from a normal drain so an operator can tell the
    # backstop firing from the queue emptying.
    assert result.actuated == []


def test_within_lease_the_busy_fence_still_protects_the_batch() -> None:
    """The backstop must not become a blanket 'always stop'."""
    controller = GpuLifecycleController(idle_seconds=300)
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=controller,
        instances=[_running(120)],
        load_source=BusyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
    )

    assert actuator.stopped == []
    assert result.lease_expired == []


def test_lease_expired_instance_is_not_stopped_twice_in_one_cycle() -> None:
    controller = GpuLifecycleController(idle_seconds=300)
    actuator = RecordingActuator()

    run_reap_cycle(
        controller=controller,
        instances=[_running(7200)],
        # Idle load would also select this instance via the normal path.
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
    )

    assert actuator.stopped == ["ocid1.instance.oc1..gpu"]


def test_lease_stop_failure_is_reported_not_swallowed() -> None:
    controller = GpuLifecycleController(idle_seconds=300)

    result = run_reap_cycle(
        controller=controller,
        instances=[_running(7200)],
        load_source=BusyLoadSource(),
        actuator=ExplodingActuator(),
        fence_delay_seconds=0,
        max_lease_seconds=3600,
    )

    assert result.lease_expired == []
    assert len(result.errors) == 1
    assert "oci unavailable" in result.errors[0]


def test_one_instances_lease_failure_does_not_block_another(  # rg-007
) -> None:
    controller = GpuLifecycleController(idle_seconds=300)

    class HalfBrokenActuator:
        def __init__(self) -> None:
            self.stopped: list[str] = []

        def stop_instance(self, instance_id: str) -> None:
            if instance_id.endswith("bad"):
                raise RuntimeError("boom")
            self.stopped.append(instance_id)

    actuator = HalfBrokenActuator()
    result = run_reap_cycle(
        controller=controller,
        instances=[_running(7200, "ocid1.bad"), _running(7200, "ocid1.good")],
        load_source=BusyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
    )

    assert actuator.stopped == ["ocid1.good"]
    assert result.lease_expired == [("STOP", "ocid1.good")]
    assert len(result.errors) == 1


# --- CLI --------------------------------------------------------------------


def test_cli_defaults_the_cap_on_rather_than_off() -> None:
    """A backstop that ships disabled is not a backstop [RES-07]."""
    args = _build_parser().parse_args(["--instance-id", "ocid1.x", "--load-json", "/tmp/x"])
    assert args.max_lease_seconds == 3600


def test_cli_accepts_an_explicit_cap() -> None:
    args = _build_parser().parse_args(
        ["--instance-id", "ocid1.x", "--load-json", "/tmp/x", "--max-lease-seconds", "900"]
    )
    assert args.max_lease_seconds == 900
