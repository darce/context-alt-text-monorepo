"""Runnable idle-reaper: decision → fence → OCI STOP actuation.

Production entrypoint (load from the describe job store dump):

  python -m infra.oci.gpu_lifecycle \\
    --instance-id ocid1.instance... \\
    --idle-seconds 300 \\
    --load-json /run/acx/describe-load.json

The describe service writes ``/run/acx/describe-load.json`` (or
``ACX_DESCRIBE_LOAD_PATH``) on enqueue / terminal poll. A stale dump is treated
as busy so a dead writer cannot cause a STOP of a working GPU (VLMFIX-S2-02).

Static ``--queue-depth`` / ``--in-flight`` flags are for unit tests only; the
fence delay re-samples the load source, so a constant static source is a no-op
fence and must not be the operator default.

Auth assumption (VLMFIX-S2-03): ``OciCliStopActuator`` uses the OCI CLI with the
host's default API-key profile (``~/.oci/config``) unless ``--oci-auth`` /
``OCI_CLI_AUTH`` selects another mode (e.g. ``instance_principal`` on
acx-backend). No dynamic-group policy is provisioned here — operators must
grant ``INSTANCE_POWER_ACTIONS`` for the GPU compartment.

The fencing guard re-samples load after ``--fence-delay-seconds`` so a request
that arrived in the decision→actuation gap cannot be reaped mid-flight.
Default fence delay is 2.0s so two samples are meaningfully separated in time.
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
    LifecycleAction,
)

logger = logging.getLogger(__name__)

# Fail-safe busy snapshot: never STOP when load data is untrustworthy.
_BUSY_LOAD = JobLoadSnapshot(queue_depth=1, in_flight=1)
_DEFAULT_LOAD_MAX_AGE_SECONDS = 120.0
_DEFAULT_OCI_TIMEOUT_SECONDS = 120
_DEFAULT_FENCE_DELAY_SECONDS = 2.0


class JobLoadSource(Protocol):
    def snapshot(self) -> JobLoadSnapshot: ...


class InstanceStopActuator(Protocol):
    def stop_instance(self, instance_id: str) -> None: ...


class InstanceStartActuator(Protocol):
    def start_instance(self, instance_id: str) -> None: ...


def build_instance_action_cmd(
    *,
    oci_bin: str,
    instance_id: str,
    action: str,
    wait_state: str,
    auth: str | None = None,
    max_wait_seconds: int = 600,
) -> list[str]:
    """OCI CLI power-action argv. START/STOP twins share this builder."""
    cmd = [
        oci_bin,
        "compute",
        "instance",
        "action",
        "--instance-id",
        instance_id,
        "--action",
        action,
        "--wait-for-state",
        wait_state,
        "--max-wait-seconds",
        str(max_wait_seconds),
    ]
    if auth:
        cmd.extend(["--auth", auth])
    return cmd


@dataclass(frozen=True)
class StaticJobLoadSource:
    """CLI / test load source with fixed queue_depth and in_flight.

    Not suitable as a production fence — both samples return the same constants.
    """

    queue_depth: int
    in_flight: int

    def snapshot(self) -> JobLoadSnapshot:
        return JobLoadSnapshot(queue_depth=self.queue_depth, in_flight=self.in_flight)


@dataclass(frozen=True)
class JsonFileJobLoadSource:
    """Load snapshot from a JSON file written by the describe service.

    Expected shape (mirrors InMemoryDescribeJobStore.load_snapshot):
      {"queue_depth": <int>, "in_flight": <int>, "written_at": <unix float optional>}

    Stale files (mtime or written_at older than max_age_seconds) are treated as
    busy so the reaper never STOPs on silent writer failure (VLMFIX-S2-02).
    """

    path: Path
    max_age_seconds: float = _DEFAULT_LOAD_MAX_AGE_SECONDS

    def snapshot(self) -> JobLoadSnapshot:
        if not self.path.is_file():
            logger.warning("load json missing; treating as busy: %s", self.path)
            return _BUSY_LOAD
        try:
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            logger.warning("load json unstatable; treating as busy: %s", self.path)
            return _BUSY_LOAD
        if age > self.max_age_seconds:
            logger.warning(
                "load json stale (mtime age=%.1fs > %.1fs); treating as busy: %s",
                age,
                self.max_age_seconds,
                self.path,
            )
            return _BUSY_LOAD
        try:
            payload = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "load json unreadable; treating as busy: %s (%s)", self.path, exc
            )
            return _BUSY_LOAD
        if not isinstance(payload, dict):
            logger.warning("load json not an object; treating as busy: %s", self.path)
            return _BUSY_LOAD
        written_at = payload.get("written_at")
        if isinstance(written_at, (int, float)):
            written_age = time.time() - float(written_at)
            if written_age > self.max_age_seconds:
                logger.warning(
                    "load json written_at stale (age=%.1fs); treating as busy: %s",
                    written_age,
                    self.path,
                )
                return _BUSY_LOAD
        try:
            queue_depth = int(payload["queue_depth"])
            in_flight = int(payload["in_flight"])
        except (KeyError, TypeError, ValueError):
            logger.warning(
                "load json missing queue_depth/in_flight; treating as busy: %s",
                self.path,
            )
            return _BUSY_LOAD
        return JobLoadSnapshot(queue_depth=queue_depth, in_flight=in_flight)


class OciCliStopActuator:
    """STOP via OCI CLI (`oci compute instance action --action STOP`).

    Auth: default API key from ``~/.oci/config``. Pass ``auth`` (or set
    ``OCI_CLI_AUTH``) for ``instance_principal`` / ``resource_principal`` when
    the reaper runs on a principal-enabled host. ``subprocess`` timeout bounds
    CLI hangs independent of ``--max-wait-seconds`` (VLMFIX-S2-03).
    """

    def __init__(
        self,
        *,
        oci_bin: str | None = None,
        dry_run: bool = False,
        auth: str | None = None,
        timeout_seconds: int = _DEFAULT_OCI_TIMEOUT_SECONDS,
    ) -> None:
        self._oci_bin = oci_bin or shutil.which("oci") or "oci"
        self._dry_run = dry_run
        self._auth = auth
        self._timeout_seconds = timeout_seconds

    def build_cmd(self, instance_id: str) -> list[str]:
        return build_instance_action_cmd(
            oci_bin=self._oci_bin,
            instance_id=instance_id,
            action=LifecycleAction.STOP,
            wait_state="STOPPED",
            auth=self._auth,
        )

    def stop_instance(self, instance_id: str) -> None:
        cmd = self.build_cmd(instance_id)
        if self._dry_run:
            logger.info("dry-run STOP %s: %s", instance_id, " ".join(cmd))
            return
        logger.info("actuating STOP for %s", instance_id)
        subprocess.run(cmd, check=True, timeout=self._timeout_seconds)


class OciCliStartActuator:
    """START via OCI CLI (`oci compute instance action --action START`).

    Symmetric twin of ``OciCliStopActuator``: same auth, timeout, dry-run, and
    wait-for-state flags; only ``--action`` / ``--wait-for-state`` differ.
    """

    def __init__(
        self,
        *,
        oci_bin: str | None = None,
        dry_run: bool = False,
        auth: str | None = None,
        timeout_seconds: int = _DEFAULT_OCI_TIMEOUT_SECONDS,
    ) -> None:
        self._oci_bin = oci_bin or shutil.which("oci") or "oci"
        self._dry_run = dry_run
        self._auth = auth
        self._timeout_seconds = timeout_seconds

    def build_cmd(self, instance_id: str) -> list[str]:
        return build_instance_action_cmd(
            oci_bin=self._oci_bin,
            instance_id=instance_id,
            action=LifecycleAction.START,
            wait_state="RUNNING",
            auth=self._auth,
        )

    def start_instance(self, instance_id: str) -> None:
        cmd = self.build_cmd(instance_id)
        if self._dry_run:
            logger.info("dry-run START %s: %s", instance_id, " ".join(cmd))
            return
        logger.info("actuating START for %s", instance_id)
        subprocess.run(cmd, check=True, timeout=self._timeout_seconds)


def fetch_instance_idle_seconds(
    *,
    instance_id: str,
    oci_bin: str | None = None,
    auth: str | None = None,
    timeout_seconds: int = _DEFAULT_OCI_TIMEOUT_SECONDS,
) -> tuple[str, int] | None:
    """Best-effort lifecycle + time-since-last-state-change from OCI CLI.

    Returns ``(lifecycle_state, idle_for_seconds)`` or None on failure.
    """
    bin_path = oci_bin or shutil.which("oci") or "oci"
    cmd = [
        bin_path,
        "compute",
        "instance",
        "get",
        "--instance-id",
        instance_id,
        "--output",
        "json",
    ]
    if auth:
        cmd.extend(["--auth", auth])
    try:
        proc = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        payload = json.loads(proc.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as exc:
        logger.warning("oci instance get failed for %s: %s", instance_id, exc)
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None
    state = str(data.get("lifecycle-state") or data.get("lifecycle_state") or "UNKNOWN")
    # Prefer time-updated / freeform last-start; fall back to time-created.
    stamp = (
        data.get("time-updated")
        or data.get("time_updated")
        or data.get("time-created")
        or data.get("time_created")
    )
    idle_for = 0
    if isinstance(stamp, str) and stamp:
        try:
            from datetime import datetime, timezone

            # OCI returns RFC3339 with Z.
            cleaned = stamp.replace("Z", "+00:00")
            started = datetime.fromisoformat(cleaned)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            idle_for = max(
                0, int((datetime.now(timezone.utc) - started).total_seconds())
            )
        except ValueError:
            idle_for = 0
    return state, idle_for


@dataclass(frozen=True)
class ReapCycleResult:
    decided: list[tuple[str, str]]
    actuated: list[tuple[str, str]]
    fenced_off: bool
    errors: list[str]


@dataclass(frozen=True)
class StartCycleResult:
    decided: list[tuple[str, str]]
    actuated: list[tuple[str, str]]
    errors: list[str]


def run_reap_cycle(
    *,
    controller: GpuLifecycleController,
    instances: list[GpuInstance],
    load_source: JobLoadSource,
    actuator: InstanceStopActuator,
    fence_delay_seconds: float = _DEFAULT_FENCE_DELAY_SECONDS,
) -> ReapCycleResult:
    """Decision → fence delay → re-sample → STOP only if still idle.

    Per-instance STOP failures are collected; the loop continues (rg-007).
    """
    load = load_source.snapshot()
    decided = controller.reap_idle_instances(
        instances,
        queue_depth=load.queue_depth,
        in_flight=load.in_flight,
    )
    if not decided:
        return ReapCycleResult(decided=[], actuated=[], fenced_off=False, errors=[])

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
        return ReapCycleResult(decided=decided, actuated=[], fenced_off=True, errors=[])

    actuated: list[tuple[str, str]] = []
    errors: list[str] = []
    for action, instance_id in fenced:
        if action != "STOP":
            continue
        try:
            actuator.stop_instance(instance_id)
            actuated.append((action, instance_id))
        except Exception as exc:  # noqa: BLE001 - isolate per-instance (VLMFIX-S2-03)
            msg = f"{instance_id}: {type(exc).__name__}: {exc}"
            logger.error("STOP failed: %s", msg)
            errors.append(msg)
    return ReapCycleResult(
        decided=decided, actuated=actuated, fenced_off=False, errors=errors
    )


def run_start_cycle(
    *,
    controller: GpuLifecycleController,
    instances: list[GpuInstance],
    load_source: JobLoadSource,
    actuator: InstanceStartActuator,
) -> StartCycleResult:
    """Emit START for STOPPED instances when the job store has work.

    Per-instance START failures are collected; the loop continues (rg-007).
    """
    load = load_source.snapshot()
    decided = controller.start_needed_instances(
        instances,
        queue_depth=load.queue_depth,
        in_flight=load.in_flight,
    )
    if not decided:
        return StartCycleResult(decided=[], actuated=[], errors=[])

    actuated: list[tuple[str, str]] = []
    errors: list[str] = []
    for action, instance_id in decided:
        if action != LifecycleAction.START:
            continue
        try:
            actuator.start_instance(instance_id)
            actuated.append((action, instance_id))
        except Exception as exc:  # noqa: BLE001 - isolate per-instance (rg-007)
            msg = f"{instance_id}: {type(exc).__name__}: {exc}"
            logger.error("START failed: %s", msg)
            errors.append(msg)
    return StartCycleResult(decided=decided, actuated=actuated, errors=errors)


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
        "--mode",
        choices=("reap", "start"),
        default="reap",
        help="reap=STOP idle GPUs (default); start=START stopped GPUs when work waits",
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
        help="Override idle seconds for all instances (default: probe OCI or = --idle-seconds)",
    )
    parser.add_argument(
        "--instance-state",
        default=None,
        help="Override lifecycle state for all instances (default: probe OCI or RUNNING)",
    )
    parser.add_argument(
        "--probe-oci",
        action="store_true",
        help="Fetch lifecycle state / age via `oci compute instance get` (recommended)",
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
        help="Static queue depth (tests only; prefer --load-json in production)",
    )
    parser.add_argument(
        "--in-flight",
        type=int,
        default=None,
        help="Static in-flight count (tests only; prefer --load-json in production)",
    )
    parser.add_argument(
        "--load-max-age-seconds",
        type=float,
        default=_DEFAULT_LOAD_MAX_AGE_SECONDS,
        help="Max age of --load-json before treating as busy (default 120)",
    )
    parser.add_argument(
        "--fence-delay-seconds",
        type=float,
        default=_DEFAULT_FENCE_DELAY_SECONDS,
        help="Grace window between decision and STOP re-sample (default 2.0)",
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
    parser.add_argument(
        "--oci-auth",
        default=None,
        help="OCI CLI --auth mode (e.g. api_key, instance_principal)",
    )
    parser.add_argument(
        "--oci-timeout-seconds",
        type=int,
        default=_DEFAULT_OCI_TIMEOUT_SECONDS,
        help="Subprocess timeout for OCI CLI calls (default 120)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)

    if args.load_json is not None:
        load_source: JobLoadSource = JsonFileJobLoadSource(
            path=args.load_json,
            max_age_seconds=args.load_max_age_seconds,
        )
    else:
        if args.queue_depth is None or args.in_flight is None:
            print(
                "error: provide --load-json (production) or both --queue-depth and "
                "--in-flight (tests only)",
                file=sys.stderr,
            )
            return 2
        if args.fence_delay_seconds <= 0:
            print(
                "warning: static load + zero fence delay makes fencing a no-op",
                file=sys.stderr,
            )
        load_source = StaticJobLoadSource(
            queue_depth=args.queue_depth,
            in_flight=args.in_flight,
        )

    instances: list[GpuInstance] = []
    for instance_id in args.instance_ids:
        state = args.instance_state
        idle_for = args.instance_idle_for
        if args.probe_oci or state is None or idle_for is None:
            probed = fetch_instance_idle_seconds(
                instance_id=instance_id,
                oci_bin=args.oci_bin,
                auth=args.oci_auth,
                timeout_seconds=args.oci_timeout_seconds,
            )
            if probed is not None:
                probed_state, probed_idle = probed
                if state is None:
                    state = probed_state
                if idle_for is None:
                    idle_for = probed_idle
            elif state is None or idle_for is None:
                # Without a probe, refuse to treat as auto-idle forever: require
                # explicit overrides so a bare invocation cannot STOP by construction.
                print(
                    f"error: could not probe {instance_id}; pass --instance-state and "
                    f"--instance-idle-for, or --probe-oci with working OCI CLI",
                    file=sys.stderr,
                )
                return 2
        assert state is not None and idle_for is not None
        instances.append(
            GpuInstance(
                instance_id=instance_id,
                state=state,
                idle_for_seconds=idle_for,
            )
        )

    controller = GpuLifecycleController(idle_seconds=args.idle_seconds)
    if args.mode == "start":
        start_actuator = OciCliStartActuator(
            oci_bin=args.oci_bin,
            dry_run=args.dry_run,
            auth=args.oci_auth,
            timeout_seconds=args.oci_timeout_seconds,
        )
        start_result = run_start_cycle(
            controller=controller,
            instances=instances,
            load_source=load_source,
            actuator=start_actuator,
        )
        logger.info(
            "start cycle decided=%s actuated=%s errors=%s",
            start_result.decided,
            start_result.actuated,
            start_result.errors,
        )
        return 1 if start_result.errors else 0

    actuator = OciCliStopActuator(
        oci_bin=args.oci_bin,
        dry_run=args.dry_run,
        auth=args.oci_auth,
        timeout_seconds=args.oci_timeout_seconds,
    )
    result = run_reap_cycle(
        controller=controller,
        instances=instances,
        load_source=load_source,
        actuator=actuator,
        fence_delay_seconds=args.fence_delay_seconds,
    )
    logger.info(
        "reap cycle decided=%s actuated=%s fenced_off=%s errors=%s",
        result.decided,
        result.actuated,
        result.fenced_off,
        result.errors,
    )
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
