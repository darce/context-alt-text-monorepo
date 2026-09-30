"""Freshness and side-effect guards for the exported API route manifest."""

from __future__ import annotations

import inspect
import json
import os
import socket
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, NamedTuple

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

_OPTIONAL_ROUTER_ROUTES = {
    ("GET", "/admin/tenants"),
    ("GET", "/portal/me"),
    ("POST", "/billing/webhooks/polar"),
}


def _fail_network(*args: object, **kwargs: object) -> None:
    raise AssertionError("route manifest export attempted a network connection")


@asynccontextmanager
async def _unexpected_lifespan(_app: Any):
    raise AssertionError("route manifest export entered the FastAPI lifespan")
    yield


def _export_with_side_effect_guards(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(socket.socket, "connect", _fail_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _fail_network)
    monkeypatch.setattr(socket, "create_connection", _fail_network)
    monkeypatch.setattr(socket, "getaddrinfo", _fail_network)

    import api.main as api_main

    monkeypatch.setattr(api_main, "_lifespan", _unexpected_lifespan)

    from scripts.export_route_manifest import _export_route_manifest_in_process

    # The socket and _lifespan monkeypatches only bind in this process, so this helper
    # deliberately exercises the private in-process path.
    return _export_route_manifest_in_process()


def _route_pairs(manifest_text: str) -> set[tuple[str, str]]:
    payload = json.loads(manifest_text)
    return {(entry["method"], entry["path"]) for entry in payload["routes"]}


class _PublicRouteManifestExports(NamedTuple):
    default: str
    ambient: str
    subprocess_calls: tuple[tuple[object, ...], ...]
    environment_before_default: dict[str, str]
    environment_after_default: dict[str, str]
    secret_provider_before_default: Any
    secret_provider_after_default: Any
    ambient_environment: dict[str, str]


@pytest.fixture(scope="module")
def guarded_route_manifest_exports() -> tuple[str, str]:
    with pytest.MonkeyPatch.context() as monkeypatch:
        first = _export_with_side_effect_guards(monkeypatch)
        second = _export_with_side_effect_guards(monkeypatch)
    return first, second


@pytest.fixture(scope="module")
def public_route_manifest_exports() -> _PublicRouteManifestExports:
    import shared.secrets as secrets
    from scripts.export_route_manifest import export_route_manifest

    real_run = subprocess.run
    subprocess_calls: list[tuple[object, ...]] = []

    def recording_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        subprocess_calls.append(args)
        return real_run(*args, **kwargs)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.delenv("ACX_DESCRIPTION_ADAPTER", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("PGVECTOR_DIM", raising=False)
        monkeypatch.setattr(subprocess, "run", recording_run)

        environment_before_default = dict(os.environ)
        secret_provider_before_default = secrets._secret_provider
        default = export_route_manifest()
        environment_after_default = dict(os.environ)
        secret_provider_after_default = secrets._secret_provider

        monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "ambient-poison")
        monkeypatch.setenv("DATABASE_URL", "postgresql://nonsense")
        monkeypatch.setenv("PGVECTOR_DIM", "not-an-integer")
        ambient_environment = {
            name: os.environ[name]
            for name in ("ACX_DESCRIPTION_ADAPTER", "DATABASE_URL", "PGVECTOR_DIM")
        }
        ambient = export_route_manifest()

    return _PublicRouteManifestExports(
        default=default,
        ambient=ambient,
        subprocess_calls=tuple(subprocess_calls),
        environment_before_default=environment_before_default,
        environment_after_default=environment_after_default,
        secret_provider_before_default=secret_provider_before_default,
        secret_provider_after_default=secret_provider_after_default,
        ambient_environment=ambient_environment,
    )


def test_route_manifest_matches_committed_fixture_byte_for_byte(
    guarded_route_manifest_exports: tuple[str, str],
) -> None:
    exported, _ = guarded_route_manifest_exports
    assert exported.encode("utf-8") == _FIXTURE_PATH.read_bytes()


def test_route_manifest_export_is_deterministic(guarded_route_manifest_exports: tuple[str, str]) -> None:
    first, second = guarded_route_manifest_exports
    assert first == second


def test_route_manifest_contains_all_retention_routes(guarded_route_manifest_exports: tuple[str, str]) -> None:
    exported, _ = guarded_route_manifest_exports
    assert _RETENTION_ROUTES <= _route_pairs(exported)


def test_route_manifest_records_all_optional_routers_enabled(
    guarded_route_manifest_exports: tuple[str, str],
) -> None:
    exported, _ = guarded_route_manifest_exports
    posture = json.loads(exported)["settings_posture"]
    assert _OPTIONAL_ROUTER_ROUTES <= _route_pairs(exported)
    assert posture == {
        "admin": "enabled",
        "billing_webhooks": "enabled",
        "portal": "enabled",
        "runtime_mode": "test",
    }


def test_default_route_manifest_export_does_not_mutate_parent_process(
    public_route_manifest_exports: _PublicRouteManifestExports,
) -> None:
    assert public_route_manifest_exports.default
    assert any(
        args
        and isinstance(args[0], list)
        and args[0]
        and args[0][-1] == "--stdout"
        for args in public_route_manifest_exports.subprocess_calls
    )
    assert len(public_route_manifest_exports.subprocess_calls) == 2
    assert (
        public_route_manifest_exports.environment_after_default
        == public_route_manifest_exports.environment_before_default
    )
    assert (
        public_route_manifest_exports.secret_provider_after_default
        is public_route_manifest_exports.secret_provider_before_default
    )


def test_default_route_manifest_export_ignores_ambient_description_adapter(
    public_route_manifest_exports: _PublicRouteManifestExports,
) -> None:
    assert public_route_manifest_exports.ambient_environment["ACX_DESCRIPTION_ADAPTER"] == "ambient-poison"
    assert public_route_manifest_exports.ambient == public_route_manifest_exports.default


def test_route_manifest_export_does_not_expose_in_process_mode() -> None:
    from scripts.export_route_manifest import export_route_manifest

    assert "in_process" not in inspect.signature(export_route_manifest).parameters


def test_route_manifest_export_ignores_malformed_ambient_database_settings(
    public_route_manifest_exports: _PublicRouteManifestExports,
) -> None:
    assert public_route_manifest_exports.ambient_environment["DATABASE_URL"] == "postgresql://nonsense"
    assert public_route_manifest_exports.ambient_environment["PGVECTOR_DIM"] == "not-an-integer"
    assert public_route_manifest_exports.ambient.encode("utf-8") == _FIXTURE_PATH.read_bytes()


def test_route_manifest_excludes_mount_and_websocket_routes() -> None:
    from fastapi import FastAPI, WebSocket
    from scripts.export_route_manifest import _route_pairs
    from starlette.applications import Starlette

    app = FastAPI()

    @app.get("/normal")
    async def normal_route() -> dict[str, str]:
        return {"status": "ok"}

    app.mount("/static", Starlette())

    @app.websocket("/ws")
    async def websocket_route(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.close()

    route_paths = {entry["path"] for entry in _route_pairs(app)}

    assert "/normal" in route_paths
    assert "/static" not in route_paths
    assert "/ws" not in route_paths


def test_route_manifest_excludes_non_api_and_documentation_routes(
    guarded_route_manifest_exports: tuple[str, str],
) -> None:
    exported, _ = guarded_route_manifest_exports
    route_pairs = _route_pairs(exported)

    assert all(method not in {"HEAD", "OPTIONS"} for method, _path in route_pairs)
    assert all(path not in {"/openapi.json", "/docs", "/redoc"} for _method, path in route_pairs)
    assert all(path.startswith("/") for _method, path in route_pairs)
