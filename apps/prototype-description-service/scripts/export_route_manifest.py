"""Export the FastAPI route inventory used by the WordPress parity checks.

The exporter constructs the application factory and inspects its route table. It
does not enter the ASGI lifespan, issue requests, open a socket, or call a
database. Path parameters are renamed to ``{param_N}`` in encounter order so a
consumer never depends on a backend parameter's source-level name.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PATH_PARAMETER = re.compile(r"\{[^{}]+\}")
_EXCLUDED_METHODS = frozenset({"HEAD", "OPTIONS"})
_EXPORT_LOCK = threading.Lock()

# The manifest deliberately uses a fixed, non-production posture. Enabling all
# optional routers gives the parity fixture the superset of routes while the
# test runtime prevents required-secret validation from touching production
# configuration. Values are local placeholders; no request is made with them.
_EXPORT_ENVIRONMENT = {
    "RECOGNITION_RUNTIME_MODE": "test",
    "RECOGNITION_SECRET_BACKEND": "env",
    "RECOGNITION_AUTH_ENABLED": "0",
    "RECOGNITION_PORTAL_ENABLED": "1",
    "RECOGNITION_ADMIN_ENABLED": "1",
    "RECOGNITION_ADMIN_TOKEN": "route-manifest-admin-token-for-tests",
    "ACX_CLERK_ISSUER": "https://route-manifest.invalid/issuer",
    "ACX_CLERK_JWKS_URL": "https://route-manifest.invalid/.well-known/jwks.json",
    "ACX_CLERK_AUTHORIZED_PARTIES": "route-manifest",
    "POLAR_WEBHOOK_SECRET": "route-manifest-webhook-secret",
    "POLAR_PRODUCT_IDS": "starter=route-manifest-product",
}


def normalize_route_path(path: str) -> str:
    """Replace each FastAPI path parameter with its positional placeholder."""

    parameter_index = 0

    def replace_parameter(_match: re.Match[str]) -> str:
        nonlocal parameter_index
        placeholder = f"{{param_{parameter_index}}}"
        parameter_index += 1
        return placeholder

    return _PATH_PARAMETER.sub(replace_parameter, path)


def _ensure_project_import_path() -> None:
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))


@contextmanager
def _forced_export_environment() -> Iterator[None]:
    previous = {name: os.environ.get(name) for name in _EXPORT_ENVIRONMENT}
    _ensure_project_import_path()
    from shared import secrets

    previous_secret_provider = getattr(secrets, "_secret_provider", None)
    secrets.set_secret_provider(secrets.EnvSecretProvider())
    os.environ.update(_EXPORT_ENVIRONMENT)
    try:
        yield
    finally:
        if previous_secret_provider is None:
            secrets.reset_secret_provider()
        else:
            secrets.set_secret_provider(previous_secret_provider)
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _import_create_app() -> Any:
    _ensure_project_import_path()
    from api.main import create_app

    return create_app


def _documentation_paths(app: Any) -> frozenset[str]:
    return frozenset(
        path
        for path in (getattr(app, "openapi_url", None), getattr(app, "docs_url", None), getattr(app, "redoc_url", None))
        if isinstance(path, str)
    )


def _route_pairs(app: Any) -> list[dict[str, str]]:
    documentation_paths = _documentation_paths(app)
    pairs: set[tuple[str, str]] = set()

    for route in app.routes:
        # APIRoute is intentional: it excludes Starlette Mount and
        # WebSocketRoute entries, including static and websocket surfaces.
        if not isinstance(route, APIRoute):
            continue
        path = getattr(route, "path", None)
        if not isinstance(path, str) or path in documentation_paths:
            continue
        for raw_method in route.methods or ():
            method = str(raw_method).upper()
            if method in _EXCLUDED_METHODS:
                continue
            pairs.add((method, normalize_route_path(path)))

    return [
        {"method": method, "path": path}
        for method, path in sorted(pairs, key=lambda pair: (pair[0], pair[1]))
    ]


def _manifest_payload(app: Any) -> dict[str, object]:
    return {
        "routes": _route_pairs(app),
        "settings_posture": {
            "admin": "enabled",
            "billing_webhooks": "enabled",
            "portal": "enabled",
            "runtime_mode": "test",
        },
    }


def export_route_manifest() -> str:
    """Return the deterministic route manifest JSON, including its final newline."""

    with _EXPORT_LOCK:
        with _forced_export_environment():
            app = _import_create_app()()
            payload = _manifest_payload(app)
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write the generated manifest to this path")
    parser.add_argument("--check", type=Path, help="fail if this path is not byte-for-byte current")
    arguments = parser.parse_args(argv)
    if arguments.output is None and arguments.check is None:
        parser.error("one of --output or --check is required")
    return arguments


def main(argv: list[str] | None = None) -> int:
    arguments = _parse_args(argv)
    content = export_route_manifest()

    if arguments.output is not None:
        _atomic_write(arguments.output, content)

    if arguments.check is not None:
        try:
            current = arguments.check.read_bytes()
        except FileNotFoundError:
            current = None
        if current != content.encode("utf-8"):
            print(
                f"route manifest is stale: {arguments.check}; regenerate with --output {arguments.check}",
                file=sys.stderr,
            )
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
