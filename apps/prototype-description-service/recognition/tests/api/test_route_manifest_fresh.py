"""Freshness and side-effect guards for the exported API route manifest."""

from __future__ import annotations

import json
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest


_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
_FIXTURE_PATH = _REPOSITORY_ROOT / "apps/prototype-wp-alt-context/tests/fixtures/api-route-manifest.json"

_RETENTION_ROUTES = {
    ("GET", "/recognition/retention/policy"),
    ("PATCH", "/recognition/retention/policy"),
    ("POST", "/recognition/retention/policy/preset"),
    ("POST", "/recognition/retention/export"),
    ("GET", "/recognition/retention/export/{param_0}/status"),
    ("GET", "/recognition/retention/export/{param_0}/data"),
    ("POST", "/recognition/retention/purge"),
    ("GET", "/recognition/retention/audit"),
    ("POST", "/recognition/retention/import"),
}


def _fail_socket_connect(_socket: socket.socket, address: object) -> None:
    raise AssertionError(f"route manifest export attempted a socket connection to {address!r}")


@asynccontextmanager
async def _unexpected_lifespan(_app: Any):
    raise AssertionError("route manifest export entered the FastAPI lifespan")
    yield


def _export_with_side_effect_guards(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(socket.socket, "connect", _fail_socket_connect)

    import api.main as api_main

    monkeypatch.setattr(api_main, "_lifespan", _unexpected_lifespan)

    from scripts.export_route_manifest import export_route_manifest

    return export_route_manifest()


def _route_pairs(manifest_text: str) -> set[tuple[str, str]]:
    payload = json.loads(manifest_text)
    return {(entry["method"], entry["path"]) for entry in payload["routes"]}


def test_route_manifest_matches_committed_fixture_byte_for_byte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exported = _export_with_side_effect_guards(monkeypatch)
    assert exported.encode("utf-8") == _FIXTURE_PATH.read_bytes()


def test_route_manifest_export_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _export_with_side_effect_guards(monkeypatch)
    second = _export_with_side_effect_guards(monkeypatch)
    assert first == second


def test_route_manifest_contains_all_retention_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    exported = _export_with_side_effect_guards(monkeypatch)
    assert _RETENTION_ROUTES <= _route_pairs(exported)


def test_route_manifest_records_all_optional_routers_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    exported = _export_with_side_effect_guards(monkeypatch)
    posture = json.loads(exported)["settings_posture"]
    assert posture == {
        "admin": "enabled",
        "billing_webhooks": "enabled",
        "portal": "enabled",
        "runtime_mode": "test",
    }
