"""Small, testable OCI GPU lifecycle controller core."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class GpuInstanceState(StrEnum):
    """Provider lifecycle states used by the decision layer."""

    RUNNING = "RUNNING"
    STARTING = "STARTING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    UNKNOWN = "UNKNOWN"


class GpuLifecycleAction(StrEnum):
    """Actions the lifecycle actuator can perform."""

    START = "START"
    STOP = "STOP"


class GpuServingStatus(StrEnum):
    """Stable, user-facing status contract for GPU-backed serving."""

    GPU_OFFLINE = "gpu_offline"
    GPU_WARMING = "gpu_warming"
    GPU_READY = "gpu_ready"


GpuLifecycleDecision = tuple[GpuLifecycleAction, str]


@dataclass(frozen=True)
class GpuInstance:
    instance_id: str
    state: GpuInstanceState
    idle_for_seconds: int

    def __post_init__(self) -> None:
        if isinstance(self.state, GpuInstanceState):
            return
        try:
            normalized = GpuInstanceState(str(self.state).upper())
        except ValueError:
            normalized = GpuInstanceState.UNKNOWN
        object.__setattr__(self, "state", normalized)


@dataclass(frozen=True)
class JobLoadSnapshot:
    """Describe-job and recent viewer activity used by the controller.

    ``active_sessions`` is supplied by session heartbeats. A positive count
    blocks reaping even when no describe job is queued or in flight, so a
    viewer reading existing results is not mistaken for abandonment.
    """

    queue_depth: int
    in_flight: int
    active_sessions: int = 0

    @property
    def has_work(self) -> bool:
        return self.queue_depth > 0 or self.in_flight > 0

    @property
    def blocks_reaping(self) -> bool:
        return self.has_work or self.active_sessions > 0


class GpuLifecycleController:
    """Pure decision core for warming and reaping burst GPU instances."""

    def __init__(self, *, idle_seconds: int) -> None:
        self.idle_seconds = idle_seconds

    def decide_actions(
        self,
        instances: list[GpuInstance],
        *,
        load: JobLoadSnapshot,
    ) -> list[GpuLifecycleDecision]:
        """Return START, STOP, or no action for the current snapshot.

        A queued job warms one stopped instance unless an instance is already
        running or warming. STOP requires an idle running instance, no work,
        and no recent session heartbeat.
        """
        if load.queue_depth > 0:
            active_states = {
                GpuInstanceState.RUNNING,
                GpuInstanceState.STARTING,
            }
            if any(instance.state in active_states for instance in instances):
                return []
            stopped = next(
                (instance for instance in instances if instance.state is GpuInstanceState.STOPPED),
                None,
            )
            if stopped is not None:
                return [(GpuLifecycleAction.START, stopped.instance_id)]
            return []

        if load.blocks_reaping:
            return []
        return [
            (GpuLifecycleAction.STOP, instance.instance_id)
            for instance in instances
            if instance.state is GpuInstanceState.RUNNING and instance.idle_for_seconds >= self.idle_seconds
        ]

    def serving_status(self, instances: list[GpuInstance]) -> GpuServingStatus:
        """Report whether GPU serving is ready, warming, or offline."""
        if any(instance.state is GpuInstanceState.RUNNING for instance in instances):
            return GpuServingStatus.GPU_READY
        if any(instance.state is GpuInstanceState.STARTING for instance in instances):
            return GpuServingStatus.GPU_WARMING
        return GpuServingStatus.GPU_OFFLINE

    def reap_idle_instances(
        self,
        instances: list[GpuInstance],
        *,
        queue_depth: int,
        in_flight: int,
    ) -> list[GpuLifecycleDecision]:
        """Compatibility entrypoint for callers that only consume STOPs."""
        return [
            decision
            for decision in self.decide_actions(
                instances,
                load=JobLoadSnapshot(
                    queue_depth=queue_depth,
                    in_flight=in_flight,
                ),
            )
            if decision[0] is GpuLifecycleAction.STOP
        ]

    def fence_stop_actions(
        self,
        actions: list[GpuLifecycleDecision],
        *,
        pre_stop_load: JobLoadSnapshot,
    ) -> list[GpuLifecycleDecision]:
        """Drop STOP decisions if work arrived between decision and actuation.

        Callers must re-sample the job store immediately before actuating and
        pass that sample here. Any non-empty queue or in-flight set cancels
        all STOPs in the batch (fail-closed on mid-request reaping).
        """
        if pre_stop_load.blocks_reaping:
            return []
        return [action for action in actions if action[0] is GpuLifecycleAction.STOP]
