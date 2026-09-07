"""Compose contracts for the Postgres filesystem headroom mount."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml


ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "apps/prototype-description-service/docker-compose.env.yml"
DEPLOY_ROOT = ROOT / "scripts/deploy"
SYSTEMD_ROOT = ROOT / "apps/prototype-description-service/systemd"
EXPECTED_PROBE_PATH = "/run/acx-pg-headroom"
_PROBE_ENVIRONMENT_KEY = "ACX_PG_HEADROOM_PROBE_PATH"


@dataclass(frozen=True)
class _Mount:
    source: str
    destination: str
    read_only: bool
    is_bind: bool


def _service_environment(service: dict[str, object]) -> dict[str, str]:
    raw_environment = service.get("environment", [])
    if isinstance(raw_environment, dict):
        return {str(key): str(value) for key, value in raw_environment.items()}

    values: dict[str, str] = {}
    for entry in raw_environment:
        if not isinstance(entry, str) or "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        values[key] = value
    return values


def _service_mounts(service: dict[str, object]) -> list[_Mount]:
    raw_volumes = service.get("volumes", [])
    mounts: list[_Mount] = []
    for entry in raw_volumes:
        if isinstance(entry, dict):
            source = str(entry.get("source", ""))
            destination = str(entry.get("target", ""))
            read_only = bool(entry.get("read_only", False))
            mount_type = str(entry.get("type", ""))
            is_bind = mount_type == "bind" or source.startswith(("/", ".", "$", "~"))
            if destination:
                mounts.append(_Mount(source, destination, read_only, is_bind))
            continue

        if not isinstance(entry, str):
            continue
        fields = entry.rsplit(":", 2)
        if len(fields) == 3:
            source, destination, mode = fields
            read_only = "ro" in mode.split(",")
        elif len(fields) == 2:
            source, destination = fields
            read_only = False
        else:
            continue
        is_bind = source.startswith(("/", ".", "$", "~"))
        mounts.append(_Mount(source, destination, read_only, is_bind))
    return mounts


def _is_nested(path: str, parent: str) -> bool:
    """Return whether path is a strict descendant of parent."""
    try:
        PurePosixPath(path).relative_to(PurePosixPath(parent))
    except ValueError:
        return False
    return path != parent


def _host_creation_sources(destination: str) -> list[Path]:
    """Find deploy/systemd commands that explicitly create a host directory."""
    destination_pattern = re.compile(
        rf"(?<![A-Za-z0-9_.-]){re.escape(destination)}(?![A-Za-z0-9_.-])"
    )
    sources: list[Path] = []
    candidates = [
        path
        for path in DEPLOY_ROOT.rglob("*")
        if path.is_file() and "tests" not in path.parts
    ] + [path for path in SYSTEMD_ROOT.rglob("*") if path.is_file()]
    for path in candidates:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not destination_pattern.search(line):
                continue
            stripped = line.lstrip()
            if re.match(r"^(?:sudo\s+)?(?:mkdir|install)(?:\s|$)", stripped):
                sources.append(path)
                break
            if re.match(r"^d\s+", stripped):
                sources.append(path)
                break
    return sources


def _compose() -> dict[str, object]:
    parsed = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def test_api_and_worker_probe_path_is_a_read_only_bind_destination() -> None:
    services = _compose()["services"]

    for service_name in ("api", "worker"):
        service = services[service_name]
        environment = _service_environment(service)
        mounts = _service_mounts(service)

        probe_path = environment[_PROBE_ENVIRONMENT_KEY]
        assert probe_path == EXPECTED_PROBE_PATH
        assert any(
            mount.is_bind and mount.read_only and mount.destination == probe_path
            for mount in mounts
        ), f"{service_name} probe path must be the destination of a read-only bind mount"
        assert any(
            mount.source == "${ACX_PGDATA_PATH}"
            and mount.is_bind
            and mount.read_only
            and mount.destination == probe_path
            for mount in mounts
        ), f"{service_name} probe must observe the Postgres data filesystem"


def test_read_only_mounts_do_not_hide_uncreated_nested_mountpoints() -> None:
    services = _compose()["services"]

    for service_name, service in services.items():
        mounts = [mount for mount in _service_mounts(service) if mount.is_bind]
        read_only_destinations = [mount.destination for mount in mounts if mount.read_only]
        for mount in mounts:
            parents = [
                parent
                for parent in read_only_destinations
                if _is_nested(mount.destination, parent)
            ]
            if not parents:
                continue
            creators = _host_creation_sources(mount.destination)
            assert creators, (
                f"{service_name} destination {mount.destination!r} is nested under a read-only "
                f"mount ({parents!r}) but no deploy/systemd path creates it on the host"
            )
