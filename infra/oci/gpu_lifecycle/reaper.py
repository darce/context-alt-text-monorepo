"""Runnable idle-reaper: decision → fence → OCI STOP actuation.

Entrypoint:
  python -m infra.oci.gpu_lifecycle.reaper \\
    --instance-id ocid1.instance... \\
    --idle-seconds 300 \\
    --queue-depth 0 --in-flight 0

Or source load from a describe-job-store HTTP snapshot JSON file:
  python -m infra.oci.gpu_lifecycle.reaper --load-json /run/acx/describe-load.json ...

The fencing guard re-samples load immediately before STOP so a request that
arrived in the decision→actuation gap cannot be reaped mid-flight.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from infra.oci.gpu_lifecycle.controller import (
    GpuInstance,
    GpuLifecycleController,
    JobLoadSnapshot,
)

logger = logging.getLogger(__name__)


class JobLoadSource(Protocol):
    def snapshot(self) -> JobLoadSnapshot: ...


class InstanceStopActuator(Protocol):
    def stop_instance(self, instance_id: str) -> None: ...


@dataclass(frozen=True)
class StaticJobLoadSource:
    """CLI / test load source with fixed queue_depth and in_flight."""

    queue_depth: int
    in_flight: int

    def snapshot(self) -> JobLoadSnapshot:
        return JobLoadSnapshot(queue_depth=self.queue_depth, in_flight=self.in_flight)


@dataclass(frozen=True)
class JsonFileJobLoadSource:
    """Load snapshot from a JSON file written by the describe service.

    Expected shape (mirrors InMemoryDescribeJobStore.queue_depth / in_flight):
      {"queue_depth": <int>, "in_flight": <int>}
    """

    path: Path

    def snapshot(self) -> JobLoadSnapshot:
        payload = json.loads(self.path.read_text())
        if not isinstance(payload, dict):
            raise ValueError(f"load json must be an object: {self.path}")
        try:
            queue_depth = int(payload["queue_depth"])
            in_flight = int(payload["in_flight"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"load json requires integer queue_depth and in_flight: {self.path}"
            ) from exc
        return JobLoadSnapshot(queue_depth=queue_depth, in_flight=in_flight)


class OciCliStopActuator:
    """STOP via OCI CLI (`oci compute instance action --action STOP`)."""

    def __init__(self, *, oci_bin: str | None = None, dry_run: bool = False) -> None:
        self._oci_bin = oci_bin or shutil.which("oci") or "oci"
        self._dry_run = dry_run

    def stop_instance(self, instance_id: str) -> None:
        cmd = [
            self._oci_bin,
            "compute",
            "instance",
            "action",
            "--instance-id",
            instance_id,
            "--action",
            "STOP",
            "--wait-for-state",
            "STOPPED",
            "--max-wait-seconds",
            "600",
        ]
        if self._dry_run:
            logger.info("dry-run STOP %s: %s", instance_id, " ".join(cmd))
            return
        logger.info("actuating STOP for %s", instance_id)
        subprocess.run(cmd, check=True)


@dataclass(frozen=True)
class ReapCycleResult:
    decided: list[tuple[str, str]]
    actuated: list[tuple[str, str]]
    fenced_off: bool


def run_reap_cycle(
    *,
    controller: GpuLifecycleController,
    instances: list[GpuInstance],
    load_source: JobLoadSource,
    actuator: InstanceStopActuator,
    fence_delay_seconds: float = 0.0,
) -> ReapCycleResult:
    """Decision → optional fence delay → re-sample → STOP only if still idle."""
    load = load_source.snapshot()
    decided = controller.reap_idle_instances(
        instances,
        queue_depth=load.queue_depth,
        in_flight=load.in_flight,
    )
    if not decided:
        return ReapCycleResult(decided=[], actuated=[], fenced_off=False)

    if fence_delay_seconds > 0:
        time.sleep(fence_delay_seconds)

    pre_stop = load_source.snapshot()
    fenced = controller.fence_stop_actions(decided, pre_stop_load=pre_stop)
    if not fenced:
        logger.info(
            "fence cancelled STOP (queue_depth=%s in_flight=%s)",
            pre_stop.queue_depth,
            pre_stop.in_flight,
        )
        return ReapCycleResult(decided=decided, actuated=[], fenced_off=True)

    actuated: list[tuple[str, str]] = []
    for action, instance_id in fenced:
        if action != "STOP":
            continue
        actuator.stop_instance(instance_id)
        actuated.append((action, instance_id))
    return ReapCycleResult(decided=decided, actuated=actuated, fenced_off=False)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ACX GPU idle reaper (STOP actuator)")
    parser.add_argument(
        "--instance-id",
        action="append",
        dest="instance_ids",
        required=True,
        help="OCI instance OCID to consider (repeatable)",
    )
    parser.add_argument(
        "--idle-seconds",
        type=int,
        default=300,
        help="Idle threshold before STOP is considered (default 300)",
    )
    parser.add_argument(
        "--instance-idle-for",
        type=int,
        default=None,
        help="Reported idle seconds for all instances (default = --idle-seconds)",
    )
    parser.add_argument(
        "--instance-state",
        default="RUNNING",
        help="Reported lifecycle state for all instances (default RUNNING)",
    )
    load = parser.add_mutually_exclusive_group()
    load.add_argument(
        "--load-json",
        type=Path,
        help="Path to {queue_depth,in_flight} JSON from the describe job store",
    )
    load.add_argument(
        "--queue-depth",
        type=int,
        default=None,
        help="Static queue depth when not using --load-json",
    )
    parser.add_argument(
        "--in-flight",
        type=int,
        default=None,
        help="Static in-flight count when not using --load-json",
    )
    parser.add_argument(
        "--fence-delay-seconds",
        type=float,
        default=1.0,
        help="Grace window between decision and STOP re-sample (default 1.0)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log STOP commands without calling the OCI CLI",
    )
    parser.add_argument(
        "--oci-bin",
        default=None,
        help="Path to oci CLI binary (default: PATH lookup)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)

    if args.load_json is not None:
        load_source: JobLoadSource = JsonFileJobLoadSource(path=args.load_json)
    else:
        if args.queue_depth is None or args.in_flight is None:
            print(
                "error: provide --load-json or both --queue-depth and --in-flight",
                file=sys.stderr,
            )
            return 2
        load_source = StaticJobLoadSource(
            queue_depth=args.queue_depth,
            in_flight=args.in_flight,
        )

    idle_for = (
        args.instance_idle_for
        if args.instance_idle_for is not None
        else args.idle_seconds
    )
    instances = [
        GpuInstance(
            instance_id=instance_id,
            state=args.instance_state,
            idle_for_seconds=idle_for,
        )
        for instance_id in args.instance_ids
    ]
    controller = GpuLifecycleController(idle_seconds=args.idle_seconds)
    actuator = OciCliStopActuator(oci_bin=args.oci_bin, dry_run=args.dry_run)
    result = run_reap_cycle(
        controller=controller,
        instances=instances,
        load_source=load_source,
        actuator=actuator,
        fence_delay_seconds=args.fence_delay_seconds,
    )
    logger.info(
        "reap cycle decided=%s actuated=%s fenced_off=%s",
        result.decided,
        result.actuated,
        result.fenced_off,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
