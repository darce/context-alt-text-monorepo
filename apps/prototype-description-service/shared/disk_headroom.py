"""Disk-space probes used to protect heavyweight Postgres operations."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from os import PathLike

from shared.health import HealthStatus

DEFAULT_MIN_HEADROOM_BYTES = 2 * 1024**3
_PROBE_PATH_ENV = "ACX_PG_HEADROOM_PROBE_PATH"
_MIN_BYTES_ENV = "ACX_PG_HEADROOM_MIN_BYTES"


@dataclass(frozen=True, slots=True)
class DiskHeadroomSettings:
    """Configuration for the Postgres filesystem headroom probe."""

    probe_path: str | None = None
    min_bytes: int = DEFAULT_MIN_HEADROOM_BYTES

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> DiskHeadroomSettings:
        values = os.environ if environ is None else environ
        raw_probe_path = values.get(_PROBE_PATH_ENV)
        probe_path = raw_probe_path.strip() if raw_probe_path is not None else None
        if not probe_path:
            probe_path = None

        raw_min_bytes = values.get(_MIN_BYTES_ENV)
        if raw_min_bytes is None:
            min_bytes = DEFAULT_MIN_HEADROOM_BYTES
        else:
            try:
                min_bytes = int(raw_min_bytes, 10)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid {_MIN_BYTES_ENV}={raw_min_bytes!r}; must be a non-negative integer"
                ) from exc
            if min_bytes < 0:
                raise ValueError(
                    f"Invalid {_MIN_BYTES_ENV}={raw_min_bytes!r}; must be a non-negative integer"
                )

        return cls(probe_path=probe_path, min_bytes=min_bytes)


@lru_cache(maxsize=1)
def get_disk_headroom_settings() -> DiskHeadroomSettings:
    """Read disk-headroom settings once for the process."""

    return DiskHeadroomSettings.from_env()


@dataclass(frozen=True, slots=True)
class DiskHeadroom:
    """Result of probing free space on the Postgres data filesystem."""

    probe_path: str
    free_bytes: int
    total_bytes: int
    status: HealthStatus
    reason: str


def probe_disk_headroom(path: str | PathLike[str]) -> DiskHeadroom:
    """Probe filesystem space without allowing probe errors to escape."""

    settings = get_disk_headroom_settings()
    try:
        probe_path = os.fspath(path)
        stat = os.statvfs(probe_path)
        block_size = int(getattr(stat, "f_frsize", 0) or getattr(stat, "f_bsize", 0))
        available_blocks = getattr(stat, "f_bavail", None)
        if available_blocks is None:
            available_blocks = getattr(stat, "f_bfree")
        free_bytes = int(available_blocks) * block_size
        total_bytes = int(getattr(stat, "f_blocks")) * block_size
        if free_bytes >= settings.min_bytes:
            status = HealthStatus.OK
            reason = f"free bytes meet minimum headroom ({settings.min_bytes})"
        else:
            status = HealthStatus.UNHEALTHY
            reason = f"free bytes below minimum headroom ({settings.min_bytes})"
        return DiskHeadroom(
            probe_path=probe_path,
            free_bytes=max(free_bytes, 0),
            total_bytes=max(total_bytes, 0),
            status=status,
            reason=reason,
        )
    except Exception as exc:
        try:
            probe_path = os.fspath(path)
        except Exception:
            probe_path = repr(path)
        return DiskHeadroom(
            probe_path=probe_path,
            free_bytes=0,
            total_bytes=0,
            status=HealthStatus.UNHEALTHY,
            reason=f"unable to probe disk headroom: {exc}",
        )


def has_headroom(probe: DiskHeadroom, required_bytes: int) -> bool:
    """Return whether a successful probe has at least the required space."""

    return required_bytes >= 0 and probe.status == HealthStatus.OK and probe.free_bytes >= required_bytes


__all__ = [
    "DEFAULT_MIN_HEADROOM_BYTES",
    "DiskHeadroom",
    "DiskHeadroomSettings",
    "get_disk_headroom_settings",
    "has_headroom",
    "probe_disk_headroom",
]
