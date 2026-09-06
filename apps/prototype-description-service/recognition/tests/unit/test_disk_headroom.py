from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from shared.disk_headroom import (
    DEFAULT_MIN_HEADROOM_BYTES,
    DiskHeadroomSettings,
    get_disk_headroom_settings,
    has_headroom,
    probe_disk_headroom,
)
from shared.health import HealthStatus


@pytest.fixture(autouse=True)
def clear_disk_headroom_settings_cache(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ACX_PG_HEADROOM_PROBE_PATH", raising=False)
    monkeypatch.delenv("ACX_PG_HEADROOM_MIN_BYTES", raising=False)
    get_disk_headroom_settings.cache_clear()
    yield
    get_disk_headroom_settings.cache_clear()


def _statvfs(*, free_blocks: int, total_blocks: int, block_size: int = 4096) -> SimpleNamespace:
    return SimpleNamespace(
        f_frsize=block_size,
        f_bsize=block_size,
        f_bavail=free_blocks,
        f_blocks=total_blocks,
    )


def test_probe_reports_ok_and_has_headroom_above_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACX_PG_HEADROOM_MIN_BYTES", "4096")
    get_disk_headroom_settings.cache_clear()
    monkeypatch.setattr(os, "statvfs", lambda _path: _statvfs(free_blocks=4, total_blocks=8))

    probe = probe_disk_headroom("/postgres-data")

    assert probe.probe_path == "/postgres-data"
    assert probe.free_bytes == 16_384
    assert probe.total_bytes == 32_768
    assert probe.status is HealthStatus.OK
    assert has_headroom(probe, 16_384)


def test_probe_reports_unhealthy_and_fails_closed_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACX_PG_HEADROOM_MIN_BYTES", "16_384")
    get_disk_headroom_settings.cache_clear()
    monkeypatch.setattr(os, "statvfs", lambda _path: _statvfs(free_blocks=3, total_blocks=8))

    probe = probe_disk_headroom("/postgres-data")

    assert probe.free_bytes == 12_288
    assert probe.status is HealthStatus.UNHEALTHY
    assert "below" in probe.reason
    assert not has_headroom(probe, 1)


def test_missing_probe_path_is_unhealthy_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_path: str):
        raise FileNotFoundError("missing probe path")

    monkeypatch.setattr(os, "statvfs", missing)

    probe = probe_disk_headroom("/missing-postgres-data")

    assert probe.free_bytes == 0
    assert probe.total_bytes == 0
    assert probe.status is HealthStatus.UNHEALTHY
    assert "missing probe path" in probe.reason
    assert not has_headroom(probe, 0)


def test_settings_use_defaults_and_are_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACX_PG_HEADROOM_PROBE_PATH", " /postgres-data ")

    first = get_disk_headroom_settings()
    monkeypatch.setenv("ACX_PG_HEADROOM_MIN_BYTES", "123")
    second = get_disk_headroom_settings()

    assert first is second
    assert first.probe_path == "/postgres-data"
    assert first.min_bytes == DEFAULT_MIN_HEADROOM_BYTES


@pytest.mark.parametrize("raw_value", ["", "not-an-integer", "1.5", "-1"])
def test_settings_reject_malformed_min_bytes(raw_value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACX_PG_HEADROOM_MIN_BYTES", raw_value)

    with pytest.raises(ValueError, match="ACX_PG_HEADROOM_MIN_BYTES"):
        DiskHeadroomSettings.from_env()
