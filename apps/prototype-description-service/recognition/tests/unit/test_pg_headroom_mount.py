"""Regression tests for the Postgres filesystem headroom probe mount."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from shared.disk_headroom import probe_disk_headroom
from shared.health import HealthStatus


_FOREIGN_PRIVATE_DIRECTORIES = (Path("/root"), Path("/private/var/root"))
_PRIVATE_DIRECTORY_MODES = frozenset({0o700, 0o750})


def _foreign_private_directory() -> Path | None:
    """Return a private directory owned by another uid, when this host has one."""
    if os.name != "posix" or os.geteuid() == 0:
        return None

    effective_uid = os.geteuid()
    for candidate in _FOREIGN_PRIVATE_DIRECTORIES:
        try:
            candidate_stat = candidate.stat()
        except OSError:
            continue
        if not stat.S_ISDIR(candidate_stat.st_mode):
            continue
        if candidate_stat.st_uid == effective_uid:
            continue
        if stat.S_IMODE(candidate_stat.st_mode) not in _PRIVATE_DIRECTORY_MODES:
            continue
        return candidate
    return None


def test_statvfs_succeeds_for_non_owner_of_private_directory() -> None:
    """statvfs needs prefix search, not read/search permission on the final directory."""
    candidate = _foreign_private_directory()
    if candidate is None:
        pytest.skip("requires a non-root POSIX process and a foreign-owned 0700/0750 directory")

    result = probe_disk_headroom(candidate)

    assert result.status in {HealthStatus.OK, HealthStatus.DEGRADED}
    assert result.total_bytes > 0
    assert not result.reason.startswith("unable to probe")


def test_nonexistent_probe_path_is_unhealthy(tmp_path: Path) -> None:
    result = probe_disk_headroom(tmp_path / "missing-pg-headroom")

    assert result.status is HealthStatus.UNHEALTHY
    assert result.reason.startswith("unable to probe")
