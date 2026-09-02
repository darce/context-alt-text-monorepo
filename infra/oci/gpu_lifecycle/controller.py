"""Small, testable OCI GPU lifecycle controller core."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LifecycleAction(StrEnum):
    START = "START"
    STOP = "STOP"
    FALLBACK = "FALLBACK"


class GpuInstanceState(StrEnum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    STOPPING = "STOPPING"
    UNKNOWN = "UNKNOWN"


CPU_FALLBACK_PROFILE = "florence_small"


@dataclass(frozen=True)
class FallbackDecision:
    """CPU-tier fallback. Emitted only; the consumer is not wired here."""

    instance_id: str
    reason: str
    action: str = LifecycleAction.FALLBACK
    profile: str = CPU_FALLBACK_PROFILE


@dataclass(frozen=True)
class GpuInstance:
    instance_id: str
    state: str
    idle_for_seconds: int


@dataclass(frozen=True)
class JobLoadSnapshot:
    """Mirrors describe-job-store load used by the idle reaper.

    ``untrustworthy=True`` means the snapshot is a sentinel, not observed
    load. STOP treats it as busy (fail closed). START treats it as no-work
    and must refuse actuation (W3-D-04).
    """

    queue_depth: int
    in_flight: int
    batch_in_progress: bool = False
    untrustworthy: bool = False

    @property
    def has_work(self) -> bool:
        return (
            self.queue_depth > 0 or self.in_flight > 0 or self.batch_in_progress
        )


class GpuLifecycleController:
    """Decides when the out-of-band OCI controller should start or stop burst GPUs."""

    def __init__(self, *, idle_seconds: int) -> None:
        self.idle_seconds = idle_seconds

    def start_needed_instances(
        self,
        instances: list[GpuInstance],
        *,
        queue_depth: int,
        in_flight: int,
        batch_in_progress: bool = False,
    ) -> list[tuple[str, str]]:
        """Emit START for STOPPED burst instances when work is waiting.

        STARTING is an in-flight boot: never re-START (caller must probe/wait).
        STOPPING and UNKNOWN are fail-closed: never START.
        """
        if queue_depth <= 0 and in_flight <= 0 and not batch_in_progress:
            return []
        return [
            (LifecycleAction.START, instance.instance_id)
            for instance in instances
            if instance.state == GpuInstanceState.STOPPED
        ]

    def instances_waiting_on_boot(self, instances: list[GpuInstance]) -> list[str]:
        """STARTING instances already booting; wait/probe, never re-START."""
        return [
            instance.instance_id
            for instance in instances
            if instance.state == GpuInstanceState.STARTING
        ]

    def instances_blocking_start(
        self, instances: list[GpuInstance]
    ) -> list[GpuInstance]:
        """STOPPING/UNKNOWN while work waits: fail closed, do not START."""
        return [
            instance
            for instance in instances
            if instance.state
            in (GpuInstanceState.STOPPING, GpuInstanceState.UNKNOWN)
        ]

    def reap_idle_instances(
        self,
        instances: list[GpuInstance],
        *,
        queue_depth: int,
        in_flight: int,
        batch_in_progress: bool = False,
    ) -> list[tuple[str, str]]:
        if queue_depth > 0 or in_flight > 0 or batch_in_progress:
            return []
        return [
            (LifecycleAction.STOP, instance.instance_id)
            for instance in instances
            if instance.state == GpuInstanceState.RUNNING
            and instance.idle_for_seconds >= self.idle_seconds
        ]

    def lease_expired_instances(
        self,
        instances: list[GpuInstance],
        *,
        max_lease_seconds: int,
    ) -> list[tuple[str, str]]:
        """STOP RUNNING instances older than the max lease, whatever the load says.

        Cost backstop (GPUW-1). Every other path in this module fails closed
        *toward busy*: a missing, stale or unparseable load dump is treated as
        work in progress and cancels the STOP. That is right for jobs and wrong
        for money -- a writer that dies leaves an A10 running at roughly $2/hr
        with nothing left in the system that will ever stop it. [RES-07]

        These STOPs deliberately bypass ``fence_stop_actions``: a fence that
        consults the same load source that may be broken cannot bound the
        exposure. A batch longer than the lease is killed, which is the intended
        trade -- raise the lease rather than disable it.

        ``max_lease_seconds <= 0`` disables the cap.

        Note the field name: ``idle_for_seconds`` is populated from the time of
        the instance's last lifecycle transition, so for a RUNNING instance it
        is the age of the current run, not a measure of inactivity.
        """
        if max_lease_seconds <= 0:
            return []
        return [
            (LifecycleAction.STOP, instance.instance_id)
            for instance in instances
            if instance.state == GpuInstanceState.RUNNING
            and instance.idle_for_seconds >= max_lease_seconds
        ]

    def fence_stop_actions(
        self,
        actions: list[tuple[str, str]],
        *,
        pre_stop_load: JobLoadSnapshot | None = None,
        fence_expired: bool = False,
    ) -> list[tuple[str, str]]:
        """Drop STOP decisions if proven work is running or the fence is unusable.

        Callers must re-sample the job store immediately before actuating and
        pass that sample here. Queue, in-flight, or an explicit True
        batch_in_progress cancels all STOPs. An absent batch_in_progress key
        is not protection. Fence expiry (no trustworthy re-sample) falls back
        closed.
        """
        if fence_expired or pre_stop_load is None or pre_stop_load.has_work:
            return []
        return [action for action in actions if action[0] == LifecycleAction.STOP]

    def fallback_on_boot_failure(
        self,
        failed_instance_ids: list[str],
        *,
        reason: str,
    ) -> list[FallbackDecision]:
        """Emit florence_small fallback when the burst instance will not come up."""
        return [
            FallbackDecision(instance_id=instance_id, reason=reason)
            for instance_id in failed_instance_ids
        ]
