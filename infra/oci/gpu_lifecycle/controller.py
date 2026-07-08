"""Small, testable OCI GPU lifecycle controller core."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GpuInstance:
    instance_id: str
    state: str
    idle_for_seconds: int


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
            if instance.state == "RUNNING" and instance.idle_for_seconds >= self.idle_seconds
        ]
