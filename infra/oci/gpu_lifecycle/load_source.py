"""Describe-load sources that combine isolated environment publications."""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path

from infra.oci.gpu_lifecycle.controller import JobLoadSnapshot

logger = logging.getLogger(__name__)

_FAIL_CLOSED_BUSY = JobLoadSnapshot(
    queue_depth=1,
    in_flight=1,
    batch_in_progress=True,
    untrustworthy=True,
)


@dataclass(frozen=True)
class AggregateJobLoadSource:
    """Aggregate ``<environment>/describe-load.json`` snapshots.

    Fresh valid files are summed. A stale file contributes a fail-closed busy
    sentinel through the bounded grace deadline, after which it is ignored if
    at least one other environment is fresh. Missing/unreadable input, or a
    scan with no fresh files, preserves the lifecycle's existing fail-closed
    busy outcome.
    """

    directory: Path
    stale_seconds: float
    stale_grace_seconds: float = 600.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "directory", Path(self.directory))
        if not math.isfinite(self.stale_seconds) or self.stale_seconds <= 0:
            raise ValueError("stale_seconds must be a positive finite number")
        if not math.isfinite(self.stale_grace_seconds) or self.stale_grace_seconds <= 0:
            raise ValueError("stale_grace_seconds must be a positive finite number")
        if self.stale_grace_seconds < self.stale_seconds:
            raise ValueError("stale_grace_seconds must be at least stale_seconds")

    def snapshot(self) -> JobLoadSnapshot:
        if not self.directory.is_dir():
            logger.warning(
                "aggregate load directory missing; treating as busy: %s",
                self.directory,
            )
            return _FAIL_CLOSED_BUSY

        try:
            paths = sorted(self.directory.glob("*/describe-load.json"))
        except OSError as exc:
            logger.warning(
                "aggregate load directory unreadable; treating as busy: %s (%s)",
                self.directory,
                exc,
            )
            return _FAIL_CLOSED_BUSY
        if not paths:
            logger.warning(
                "aggregate load directory has no environment snapshots; treating as busy: %s",
                self.directory,
            )
            return _FAIL_CLOSED_BUSY

        now = time.time()
        snapshots: list[JobLoadSnapshot] = []
        fresh_count = 0
        for path in paths:
            environment = path.parent.name
            parsed = self._read_snapshot(path, environment=environment)
            if parsed is None:
                snapshots.append(_FAIL_CLOSED_BUSY)
                continue
            snapshot, written_at = parsed
            age = now - written_at
            if age <= self.stale_seconds:
                fresh_count += 1
                snapshots.append(snapshot)
            elif age <= self.stale_grace_seconds:
                logger.warning(
                    "describe load for environment %s is stale (age=%.1fs > %.1fs); "
                    "treating as busy until %.1fs grace deadline",
                    environment,
                    age,
                    self.stale_seconds,
                    self.stale_grace_seconds,
                )
                snapshots.append(_FAIL_CLOSED_BUSY)
            else:
                logger.warning(
                    "describe load for environment %s ignored after stale grace (age=%.1fs > %.1fs): %s",
                    environment,
                    age,
                    self.stale_grace_seconds,
                    path,
                )

        if fresh_count == 0:
            logger.warning(
                "aggregate load has no fresh environment snapshots; treating as busy: %s",
                self.directory,
            )
            return _FAIL_CLOSED_BUSY

        return JobLoadSnapshot(
            queue_depth=sum(snapshot.queue_depth for snapshot in snapshots),
            in_flight=sum(snapshot.in_flight for snapshot in snapshots),
            batch_in_progress=any(snapshot.batch_in_progress for snapshot in snapshots),
            untrustworthy=any(snapshot.untrustworthy for snapshot in snapshots),
        )

    @staticmethod
    def _read_snapshot(
        path: Path,
        *,
        environment: str,
    ) -> tuple[JobLoadSnapshot, float] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            logger.warning(
                "describe load for environment %s is unreadable; treating as busy: %s (%s)",
                environment,
                path,
                exc,
            )
            return None
        if not isinstance(payload, dict):
            logger.warning(
                "describe load for environment %s is not an object; treating as busy: %s",
                environment,
                path,
            )
            return None

        written_at = payload.get("written_at")
        try:
            written_timestamp = float(written_at)
        except (TypeError, ValueError, OverflowError):
            written_timestamp = math.nan
        if isinstance(written_at, bool) or not math.isfinite(written_timestamp):
            logger.warning(
                "describe load for environment %s has invalid written_at; treating as busy: %s",
                environment,
                path,
            )
            return None
        try:
            queue_depth = int(payload["queue_depth"])
            in_flight = int(payload["in_flight"])
        except (KeyError, TypeError, ValueError, OverflowError):
            logger.warning(
                "describe load for environment %s is missing queue_depth/in_flight; treating as busy: %s",
                environment,
                path,
            )
            return None
        if queue_depth < 0 or in_flight < 0:
            logger.warning(
                "describe load for environment %s has negative work counts; treating as busy: %s",
                environment,
                path,
            )
            return None
        batch_in_progress = payload.get("batch_in_progress", False)
        if not isinstance(batch_in_progress, bool):
            logger.warning(
                "describe load for environment %s has non-bool batch_in_progress; treating as busy: %s",
                environment,
                path,
            )
            return None
        return (
            JobLoadSnapshot(
                queue_depth=queue_depth,
                in_flight=in_flight,
                batch_in_progress=batch_in_progress,
            ),
            written_timestamp,
        )
