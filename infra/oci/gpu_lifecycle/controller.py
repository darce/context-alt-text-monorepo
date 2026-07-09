"""Small, testable OCI GPU lifecycle controller core."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GpuInstance:
    instance_id: str
    state: str
    idle_for_seconds: int


@dataclass(frozen=True)
class JobLoadSnapshot:
    """Mirrors describe-job-store load used by the idle reaper."""

    queue_depth: int
    in_flight: int

    @property
    def has_work(self) -> bool:
        return self.queue_depth > 0 or self.in_flight > 0


class GpuLifecycleController:
    """Decides when the out-of-band OCI controller should stop burst GPUs."""

    def __init__(self, *, idle_seconds: int) -> None:
        self.idle_seconds = idle_seconds

    def reap_idle_instances(
        self,
        instances: list[GpuInstance],
        *,
        queue_depth: int,
        in_flight: int,
    ) -> list[tuple[str, str]]:
        if queue_depth > 0 or in_flight > 0:
            return []
        return [
            ("STOP", instance.instance_id)
            for instance in instances
            if instance.state == "RUNNING"
            and instance.idle_for_seconds >= self.idle_seconds
        ]

    def fence_stop_actions(
        self,
        actions: list[tuple[str, str]],
        *,
        pre_stop_load: JobLoadSnapshot,
    ) -> list[tuple[str, str]]:
        """Drop STOP decisions if work arrived between decision and actuation.

        Callers must re-sample the job store immediately before actuating and
        pass that sample here. Any non-empty queue or in-flight set cancels
        all STOPs in the batch (fail-closed on mid-request reaping).
        """
        if pre_stop_load.has_work:
            return []
        return [action for action in actions if action[0] == "STOP"]
